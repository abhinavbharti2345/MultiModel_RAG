from __future__ import annotations
import logging
from pathlib import Path
from typing import Any

from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings
from app.schemas.evidence_schemas import TranscriptSegment

logger = logging.getLogger(__name__)


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

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def transcribe_file(self, audio_path: Path) -> list[TranscriptSegment]:
        if not self.api_key:
            logger.warning("GROQ_API_KEY not set. Using mock transcription for demo.")
            return self._mock_transcription(audio_path)

        logger.info(f"Transcribing {audio_path.name} with Groq Whisper {self.model}...")

        import httpx
        audio_bytes = audio_path.read_bytes()
        filename = audio_path.name

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

        if resp.status_code != 200:
            logger.error(f"Groq STT error {resp.status_code}: {resp.text}")
            raise RuntimeError(f"STT failed: {resp.status_code} {resp.text[:200]}")

        result = resp.json()
        segments_raw = result.get("segments") or []

        segments: list[TranscriptSegment] = []
        for seg in segments_raw:
            text = (seg.get("text") or "").strip()
            if not text:
                continue
            segments.append(TranscriptSegment(
                start=float(seg.get("start", 0)),
                end=float(seg.get("end", 0)),
                text=text,
                speaker=seg.get("speaker"),
            ))

        logger.info(f"Transcription complete: {len(segments)} segments, "
                    f"{sum(s.end - s.start for s in segments):.1f}s of speech")
        return segments

    def _mock_transcription(self, audio_path: Path) -> list[TranscriptSegment]:
        logger.info(f"Generating mock transcription for {audio_path}")
        try:
            import subprocess
            result = subprocess.run(
                [settings.FFMPEG_PATH, "-i", str(audio_path), "-v", "error",
                 "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1"],
                capture_output=True, text=True, timeout=30,
            )
            duration = float(result.stdout.strip() or 600)
        except Exception:
            duration = 600.0

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
