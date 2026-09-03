from __future__ import annotations
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings
from app.schemas.evidence_schemas import TranscriptSegment
from app.services.health_tracker import health_tracker

logger = logging.getLogger(__name__)

# Groq Whisper (and OpenAI Whisper) enforce a 25 MB upload limit per request.
# We target 20 MB to leave headroom for multipart framing and metadata.
_MAX_CHUNK_BYTES: int = 20 * 1024 * 1024  # 20 MB

# Overlap between consecutive chunks (seconds) to avoid losing words at boundaries.
# Segments that fall inside the overlap region of the *previous* chunk are deduplicated
# by preferring the earlier chunk's copy (it has a more accurate start time).
_CHUNK_OVERLAP_SECONDS: float = 5.0

# Chunk duration cap in seconds. Even if the file is small enough by byte size,
# we never send more than this many seconds at once (avoids timeout on slow API).
_MAX_CHUNK_DURATION_SECONDS: float = 600.0  # 10 minutes


class GroqWhisperSTT:
    def __init__(self):
        self.api_key = settings.GROQ_API_KEY
        self.base_url = settings.GROQ_API_BASE_URL
        self.model = settings.GROQ_WHISPER_MODEL

    def _get_client(self):
        import httpx
        if not self.api_key:
            raise RuntimeError("GROQ_API_KEY is not set. Cannot use Groq Whisper API.")
        return httpx.AsyncClient(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=300.0,
        )

    # ------------------------------------------------------------------ #
    # Public entry point — called by both ingest_video and ingest_audio.  #
    # Transparently chunks large files; short files go through directly.  #
    # ------------------------------------------------------------------ #

    async def transcribe_file(self, audio_path: Path) -> list[TranscriptSegment]:
        if not self.api_key:
            logger.warning("GROQ_API_KEY not set. Using mock transcription for demo.")
            return self._mock_transcription(audio_path)

        file_size = audio_path.stat().st_size
        duration = self._get_audio_duration(audio_path)

        logger.info(
            f"Transcribing {audio_path.name}: "
            f"{file_size / 1024 / 1024:.1f} MB, "
            f"{duration:.1f}s duration"
        )

        needs_chunking = (
            file_size > _MAX_CHUNK_BYTES
            or (duration is not None and duration > _MAX_CHUNK_DURATION_SECONDS)
        )

        if not needs_chunking:
            return await self._transcribe_single_chunk(audio_path, time_offset=0.0)

        return await self._transcribe_chunked(audio_path, duration)

    # ------------------------------------------------------------------ #
    # Chunked transcription                                               #
    # ------------------------------------------------------------------ #

    async def _transcribe_chunked(
        self, audio_path: Path, total_duration: Optional[float]
    ) -> list[TranscriptSegment]:
        """Split audio into safe-sized chunks, transcribe each, merge results."""

        if total_duration is None or total_duration <= 0:
            # Cannot determine duration — fall back to single-chunk attempt
            logger.warning(
                "Cannot determine audio duration; attempting single-chunk transcription. "
                "This may fail if the file exceeds the 25 MB API limit."
            )
            return await self._transcribe_single_chunk(audio_path, time_offset=0.0)

        # Calculate chunk boundaries (seconds), with overlap between chunks
        chunk_starts: list[float] = []
        cursor = 0.0
        while cursor < total_duration:
            chunk_starts.append(cursor)
            # Advance by chunk duration (minus overlap so next chunk covers the gap)
            # We derive chunk_duration from the byte size limit
            cursor += self._estimate_chunk_duration(audio_path, total_duration)

        total_chunks = len(chunk_starts)
        logger.info(f"Splitting into {total_chunks} chunk(s) with {_CHUNK_OVERLAP_SECONDS}s overlap")

        chunk_duration = self._estimate_chunk_duration(audio_path, total_duration)

        all_segments: list[TranscriptSegment] = []
        failed_chunks: list[int] = []
        tmp_dir = Path(tempfile.mkdtemp(prefix="stt_chunks_"))

        try:
            for idx, chunk_start in enumerate(chunk_starts):
                chunk_end = min(chunk_start + chunk_duration + _CHUNK_OVERLAP_SECONDS, total_duration)
                chunk_path = tmp_dir / f"chunk_{idx:04d}.mp3"

                logger.info(
                    f"Processing chunk {idx + 1}/{total_chunks}: "
                    f"{chunk_start:.1f}s – {chunk_end:.1f}s"
                )

                # Extract chunk with ffmpeg
                try:
                    self._extract_chunk(audio_path, chunk_path, chunk_start, chunk_end)
                except Exception as e:
                    logger.error(f"Failed to extract chunk {idx + 1}/{total_chunks}: {e}")
                    failed_chunks.append(idx)
                    continue

                if not chunk_path.exists() or chunk_path.stat().st_size == 0:
                    logger.warning(
                        f"Chunk {idx + 1}/{total_chunks} produced an empty file "
                        f"(silent audio or no audio track in this segment). Skipping."
                    )
                    continue

                # Transcribe this chunk (with its own retry logic)
                try:
                    chunk_segments = await self._transcribe_single_chunk(
                        chunk_path, time_offset=chunk_start
                    )
                except Exception as e:
                    logger.error(
                        f"Transcription failed for chunk {idx + 1}/{total_chunks} "
                        f"({chunk_start:.1f}s–{chunk_end:.1f}s): {e}"
                    )
                    failed_chunks.append(idx)
                    continue

                # Deduplicate overlap: discard segments from this chunk whose start
                # time falls within the overlap region already covered by the previous chunk.
                overlap_cutoff = chunk_start + _CHUNK_OVERLAP_SECONDS if idx > 0 else chunk_start
                deduped = [s for s in chunk_segments if s.start >= overlap_cutoff]
                all_segments.extend(deduped)

                logger.info(
                    f"Chunk {idx + 1}/{total_chunks}: "
                    f"{len(chunk_segments)} segments "
                    f"({len(deduped)} after overlap dedup)"
                )

        finally:
            # Always clean up temp files, even if some chunks failed
            for f in tmp_dir.iterdir():
                try:
                    f.unlink()
                except Exception:
                    pass
            try:
                tmp_dir.rmdir()
            except Exception:
                pass

        if failed_chunks:
            raise RuntimeError(
                f"STT failed for {len(failed_chunks)}/{total_chunks} chunk(s): "
                f"chunk indices {failed_chunks}. "
                f"Successfully transcribed {len(all_segments)} segments from the remaining chunks."
            )

        # Sort by start time (chunks should already be ordered, but be safe)
        all_segments.sort(key=lambda s: s.start)

        logger.info(
            f"Chunked transcription complete: {len(all_segments)} total segments, "
            f"{sum(s.end - s.start for s in all_segments):.1f}s of speech"
        )
        return all_segments

    # ------------------------------------------------------------------ #
    # Single-chunk transcription (with per-chunk retry)                  #
    # ------------------------------------------------------------------ #

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def _transcribe_single_chunk(
        self, audio_path: Path, time_offset: float = 0.0
    ) -> list[TranscriptSegment]:
        """Send one audio file to Groq Whisper. Offsets all timestamps by time_offset."""
        import httpx

        audio_bytes = audio_path.read_bytes()
        filename = audio_path.name

        try:
            async with self._get_client() as client:
                data = {
                    "model": self.model,
                    "response_format": "verbose_json",
                    "temperature": "0",
                    "language": "en",
                }
                files = {
                    "file": (filename, audio_bytes, "audio/mpeg"),
                }
                resp = await client.post("/audio/transcriptions", data=data, files=files)
        except Exception as e:
            health_tracker.update_status("stt", 503)
            raise RuntimeError(f"STT network error: {e}")

        retry_after = None
        if resp.status_code == 429:
            retry_header = resp.headers.get("retry-after")
            reset_header = resp.headers.get("x-ratelimit-reset-requests")
            if retry_header and retry_header.isdigit():
                retry_after = int(retry_header)
            elif reset_header:
                import re
                match = re.search(r"(\d+(\.\d+)?)s", reset_header)
                if match:
                    retry_after = int(float(match.group(1))) + 1
            if not retry_after:
                retry_after = 60

            health_tracker.update_status("stt", 429, retry_after)
            logger.warning(f"STT Rate Limited. Retry after {retry_after}s")
            raise RuntimeError(f"STT Rate Limited (HTTP 429). Reset in {retry_after}s.")

        health_tracker.update_status("stt", resp.status_code)

        if resp.status_code != 200:
            logger.error(f"Groq STT error {resp.status_code}: {resp.text}")
            raise RuntimeError(f"STT failed: {resp.status_code} {resp.text[:200]}")

        result = resp.json()
        segments_raw = result.get("segments") or []

        if not segments_raw:
            # API returned 200 but no segments — silent audio or no speech detected
            logger.info(
                f"No speech segments returned for {audio_path.name} "
                f"(silent audio or no speech detected)"
            )
            return []

        segments: list[TranscriptSegment] = []
        for seg in segments_raw:
            text = (seg.get("text") or "").strip()
            if not text:
                continue
            segments.append(TranscriptSegment(
                start=float(seg.get("start", 0)) + time_offset,
                end=float(seg.get("end", 0)) + time_offset,
                text=text,
                speaker=seg.get("speaker"),  # preserved if diarization is available
            ))

        return segments

    # ------------------------------------------------------------------ #
    # Helpers                                                             #
    # ------------------------------------------------------------------ #

    def _get_audio_duration(self, audio_path: Path) -> Optional[float]:
        """Return duration in seconds. Tries ffprobe first, then ffmpeg stderr parse."""
        # Strategy 1: ffprobe (standard companion to ffmpeg)
        ffmpeg_path = Path(settings.FFMPEG_PATH)
        # If ffmpeg_path is a full path, look for sibling ffprobe
        if ffmpeg_path.is_absolute() or ffmpeg_path.parent != Path("."):
            ffprobe_candidates = [
                ffmpeg_path.parent / "ffprobe.exe",
                ffmpeg_path.parent / "ffprobe",
                ffmpeg_path.with_name("ffprobe.exe"),
                ffmpeg_path.with_name("ffprobe"),
            ]
        else:
            ffprobe_candidates = []
        # Also try bare "ffprobe" on PATH
        ffprobe_candidates.append(Path("ffprobe"))

        for ffprobe in ffprobe_candidates:
            try:
                result = subprocess.run(
                    [
                        str(ffprobe), "-i", str(audio_path),
                        "-v", "error",
                        "-show_entries", "format=duration",
                        "-of", "default=noprint_wrappers=1:nokey=1",
                    ],
                    capture_output=True, text=True, timeout=30,
                )
                raw = result.stdout.strip()
                if raw:
                    return float(raw)
            except (FileNotFoundError, ValueError):
                continue
            except Exception as e:
                logger.debug(f"ffprobe attempt failed ({ffprobe}): {e}")
                continue

        # Strategy 2: parse ffmpeg stderr (ffmpeg always prints stream info to stderr)
        try:
            result = subprocess.run(
                [settings.FFMPEG_PATH, "-i", str(audio_path)],
                capture_output=True, text=True, timeout=30,
            )
            # ffmpeg outputs: "Duration: HH:MM:SS.ss" in stderr
            import re
            match = re.search(
                r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", result.stderr
            )
            if match:
                h, m, s = int(match.group(1)), int(match.group(2)), float(match.group(3))
                return h * 3600 + m * 60 + s
        except Exception as e:
            logger.warning(f"Could not determine audio duration via ffmpeg stderr: {e}")

        logger.warning(f"Could not determine duration for {audio_path.name}")
        return None


    def _estimate_chunk_duration(self, audio_path: Path, total_duration: float) -> float:
        """
        Estimate how many seconds fit within _MAX_CHUNK_BYTES.
        Uses the file's actual average bitrate for accuracy.
        Caps at _MAX_CHUNK_DURATION_SECONDS.
        """
        file_size = audio_path.stat().st_size
        if total_duration <= 0:
            return _MAX_CHUNK_DURATION_SECONDS
        bytes_per_second = file_size / total_duration
        if bytes_per_second <= 0:
            return _MAX_CHUNK_DURATION_SECONDS
        duration_for_max_bytes = _MAX_CHUNK_BYTES / bytes_per_second
        return min(duration_for_max_bytes, _MAX_CHUNK_DURATION_SECONDS)

    def _extract_chunk(
        self, source: Path, dest: Path, start: float, end: float
    ) -> None:
        """Extract [start, end) seconds from source into dest as MP3 via ffmpeg."""
        duration = end - start
        cmd = [
            settings.FFMPEG_PATH,
            "-y",
            "-ss", str(start),
            "-i", str(source),
            "-t", str(duration),
            "-vn",
            "-acodec", "libmp3lame",
            "-ar", "16000",
            "-ac", "1",
            str(dest),
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=120)
        if result.returncode != 0:
            raise RuntimeError(
                f"ffmpeg chunk extraction failed (exit {result.returncode}): "
                f"{result.stderr.decode(errors='replace')[-300:]}"
            )

    # ------------------------------------------------------------------ #
    # Mock (demo / no API key)                                            #
    # ------------------------------------------------------------------ #

    def _mock_transcription(self, audio_path: Path) -> list[TranscriptSegment]:
        logger.info(f"Generating mock transcription for {audio_path}")
        duration = self._get_audio_duration(audio_path) or 600.0

        sample_topics = [
            (0, 30, "Welcome everyone to our architecture review meeting today."),
            (30, 60, "We've been experiencing significant database load issues during peak hours."),
            (60, 100, "I propose we introduce Redis caching layer in front of PostgreSQL."),
            (100, 140, "The idea is to cache frequent queries and reduce read pressure on the database."),
            (140, 180, "Sarah will walk us through the architecture diagram on the next slide."),
            (180, 220, "As you can see here, requests first hit the API gateway, then load balancers."),
            (220, 260, "From there, they route to application servers which check the Redis cache."),
            (260, 310, "Cache misses fall through to PostgreSQL, and we write the results back to Redis."),
            (310, 360, "For write operations, we use a write-through pattern to keep cache consistent."),
            (360, 410, "The expected TTL for most cached entries will be around five minutes."),
            (410, 460, "Estimated cost reduction for the database tier is about sixty percent."),
            (460, 510, "Now does anyone have questions about the caching strategy or TTL values?"),
            (510, 560, "Great, let's move on to discuss the PDF document that outlines the full design."),
            (560, 600, "Thanks everyone, action items will be posted in the shared doc by end of day."),
        ]

        segments: list[TranscriptSegment] = []
        for start, end, text in sample_topics:
            if start >= duration:
                break
            seg_end = min(end, duration)
            segments.append(TranscriptSegment(
                start=float(start),
                end=float(seg_end),
                text=text,
                speaker="Speaker 1",
            ))
        return segments


stt_service = GroqWhisperSTT()
