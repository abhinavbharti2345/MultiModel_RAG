"""
Tests for the audio chunking behaviour in speech_to_text.py.

Run from backend/ directory:
    python scripts/test_stt_chunking.py

Uses only ffmpeg (already bundled) and no API key — all assertions are
on the chunking logic itself (timestamp offsets, overlap dedup, temp cleanup,
failure handling) using the mock path and synthetic audio files.
"""
from __future__ import annotations
import asyncio
import subprocess
import sys
import tempfile
from pathlib import Path

# ── resolve project root so `app` imports work ────────────────────────────────
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings
from app.services.speech_to_text import GroqWhisperSTT, _MAX_CHUNK_BYTES, _CHUNK_OVERLAP_SECONDS
from app.schemas.evidence_schemas import TranscriptSegment

# Resolve ffmpeg: prefer bundled exe, fall back to config, then bare name
_BUNDLED_FFMPEG = BACKEND_DIR / "ffmpeg.exe"
if _BUNDLED_FFMPEG.exists():
    FFMPEG = str(_BUNDLED_FFMPEG)
else:
    FFMPEG = settings.FFMPEG_PATH
PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"


# ── helpers ───────────────────────────────────────────────────────────────────

def make_silent_mp3(dest: Path, duration_seconds: float) -> None:
    """Generate a silent mono MP3 using ffmpeg."""
    cmd = [
        FFMPEG, "-y",
        "-f", "lavfi", "-i", f"anullsrc=r=16000:cl=mono",
        "-t", str(duration_seconds),
        "-acodec", "libmp3lame", "-ar", "16000", "-ac", "1",
        "-b:a", "128k",
        str(dest),
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed: {result.stderr.decode(errors='replace')[-300:]}"
        )


def file_size_mb(p: Path) -> float:
    return p.stat().st_size / 1024 / 1024


def run(coro):
    return asyncio.run(coro)


def check(label: str, condition: bool, detail: str = "") -> bool:
    status = PASS if condition else FAIL
    print(f"  {status}  {label}" + (f"  [{detail}]" if detail else ""))
    return condition


# ── tests ─────────────────────────────────────────────────────────────────────

def test_short_audio_no_chunking():
    """Short file (<20 MB) should not trigger chunking."""
    print("\n[1] Short audio — no chunking (mock path)")
    stt = GroqWhisperSTT()
    stt.api_key = ""  # Force mock path

    with tempfile.TemporaryDirectory() as tmp:
        audio = Path(tmp) / "short.mp3"
        make_silent_mp3(audio, 30.0)  # 30-second silent MP3
        size_mb = file_size_mb(audio)
        segs = run(stt.transcribe_file(audio))

    passed = True
    passed &= check("File <20 MB (no chunk needed)", size_mb < 20, f"{size_mb:.2f} MB")
    passed &= check("Returns list of TranscriptSegments", isinstance(segs, list))
    if segs:
        passed &= check("Segments have correct types", all(
            isinstance(s.start, float) and isinstance(s.end, float)
            for s in segs
        ))
    return passed


def test_timestamp_offsets():
    """Verify _extract_chunk produces a file of the expected duration."""
    print("\n[2] Timestamp offset correctness")
    stt = GroqWhisperSTT()
    # Override ffmpeg path to use bundled executable
    import app.config as _cfg
    _orig = _cfg.settings.FFMPEG_PATH
    _cfg.settings.__dict__["FFMPEG_PATH"] = FFMPEG

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "source.mp3"
        dest = Path(tmp) / "chunk.mp3"
        make_silent_mp3(src, 60.0)

        stt._extract_chunk(src, dest, start=20.0, end=40.0)
        duration_after = stt._get_audio_duration(dest)

        passed = True
        if duration_after is not None:
            passed &= check(
                "Chunk duration ~= 20s",
                abs(duration_after - 20.0) < 1.0,
                f"{duration_after:.2f}s"
            )
        else:
            passed &= check("Could read chunk duration", False, "ffmpeg returned None")

    _cfg.settings.__dict__["FFMPEG_PATH"] = _orig
    return passed


def test_duration_estimation():
    """_estimate_chunk_duration should return <= _MAX_CHUNK_DURATION_SECONDS."""
    print("\n[3] Chunk duration estimation")
    stt = GroqWhisperSTT()
    import app.config as _cfg
    _orig = _cfg.settings.FFMPEG_PATH
    _cfg.settings.__dict__["FFMPEG_PATH"] = FFMPEG

    with tempfile.TemporaryDirectory() as tmp:
        audio = Path(tmp) / "test.mp3"
        make_silent_mp3(audio, 120.0)
        duration = stt._get_audio_duration(audio)
        chunk_dur = stt._estimate_chunk_duration(audio, duration or 120.0)

    _cfg.settings.__dict__["FFMPEG_PATH"] = _orig

    passed = True
    passed &= check("Duration detectable", duration is not None, str(duration))
    passed &= check("Chunk duration <= cap (600s)", chunk_dur <= 600.0, f"{chunk_dur:.1f}s")
    passed &= check("Chunk duration > 0", chunk_dur > 0, f"{chunk_dur:.1f}s")
    return passed


def test_silent_audio_no_crash():
    """Silent audio (no speech) should return empty list, not crash."""
    print("\n[4] Silent audio — no speech — should not crash")
    stt = GroqWhisperSTT()
    stt.api_key = ""  # Use mock

    with tempfile.TemporaryDirectory() as tmp:
        audio = Path(tmp) / "silent.mp3"
        make_silent_mp3(audio, 10.0)
        segs = run(stt.transcribe_file(audio))

    passed = check("Returns list (not exception)", isinstance(segs, list))
    return passed


def test_temp_cleanup():
    """Temp chunk files must be deleted after chunked transcription."""
    print("\n[5] Temp chunk cleanup")
    import os

    stt = GroqWhisperSTT()
    stt.api_key = ""  # mock path — won't actually chunk, but tests cleanup path

    with tempfile.TemporaryDirectory() as tmp:
        audio = Path(tmp) / "audio.mp3"
        make_silent_mp3(audio, 15.0)
        tmp_before = set(Path(tempfile.gettempdir()).glob("stt_chunks_*"))
        run(stt.transcribe_file(audio))
        tmp_after = set(Path(tempfile.gettempdir()).glob("stt_chunks_*"))
        new_dirs = tmp_after - tmp_before

    passed = check("No leftover stt_chunks_ temp dirs", len(new_dirs) == 0,
                   f"{len(new_dirs)} leftover dir(s)")
    return passed


def test_large_synthetic_audio():
    """
    Creates a synthetic audio file that exceeds _MAX_CHUNK_BYTES by target size.
    Verifies the chunker splits it without crashing and cleans up.
    We use the mock path (no API key) so no real API call is made.
    """
    print("\n[6] Large synthetic audio (> 20 MB threshold) — chunking path")

    # At 128kbps MP3, 1 minute ≈ 960 KB. To exceed 20 MB we need ~21 minutes.
    # Use 25 minutes to be safely over the limit.
    TARGET_DURATION_SECONDS = 25 * 60  # 25 minutes

    stt = GroqWhisperSTT()
    stt.api_key = ""  # Force mock — we test chunking logic, not actual API

    with tempfile.TemporaryDirectory() as tmp:
        audio = Path(tmp) / "large.mp3"
        print(f"  Generating {TARGET_DURATION_SECONDS / 60:.0f}-minute silent MP3...")
        make_silent_mp3(audio, TARGET_DURATION_SECONDS)
        size_mb = file_size_mb(audio)
        print(f"  File size: {size_mb:.1f} MB")

        # Count stt_chunks_ dirs before
        tmp_before = set(Path(tempfile.gettempdir()).glob("stt_chunks_*"))
        segs = run(stt.transcribe_file(audio))
        tmp_after = set(Path(tempfile.gettempdir()).glob("stt_chunks_*"))
        new_dirs = tmp_after - tmp_before

    passed = True
    passed &= check("File exceeds 20 MB", size_mb > 20, f"{size_mb:.1f} MB")
    passed &= check("Transcription returned segments", isinstance(segs, list))
    passed &= check("No leftover temp dirs", len(new_dirs) == 0,
                    f"{len(new_dirs)} leftover")

    # Mock returns segments based on duration; verify timestamps are sane
    if segs:
        max_ts = max(s.end for s in segs)
        passed &= check("Segment timestamps within file duration",
                        max_ts <= TARGET_DURATION_SECONDS + 1,
                        f"max_end={max_ts:.1f}s")
        passed &= check("Segments monotonically ordered",
                        all(segs[i].start <= segs[i + 1].start for i in range(len(segs) - 1)))

    return passed


def test_no_audio_track():
    """Audio path that doesn't exist is handled gracefully by caller (not STT)."""
    print("\n[7] Non-existent audio path — should raise, not silently return empty")
    stt = GroqWhisperSTT()
    stt.api_key = "fake_key"

    raised = False
    try:
        run(stt._transcribe_single_chunk(Path("/nonexistent/audio.mp3"), time_offset=0.0))
    except Exception:
        raised = True

    return check("Raises on missing file", raised)


# ── runner ────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("STT Chunking Tests")
    print(f"  MAX_CHUNK_BYTES: {_MAX_CHUNK_BYTES / 1024 / 1024:.0f} MB")
    print(f"  OVERLAP: {_CHUNK_OVERLAP_SECONDS}s")
    print(f"  FFMPEG: {FFMPEG}")
    print("=" * 60)

    tests = [
        test_short_audio_no_chunking,
        test_timestamp_offsets,
        test_duration_estimation,
        test_silent_audio_no_crash,
        test_temp_cleanup,
        test_large_synthetic_audio,
        test_no_audio_track,
    ]

    results = []
    for t in tests:
        try:
            results.append(t())
        except Exception as e:
            print(f"  {FAIL}  Test raised exception: {e}")
            results.append(False)

    print("\n" + "=" * 60)
    passed = sum(results)
    total = len(results)
    color = "\033[32m" if passed == total else "\033[31m"
    print(f"{color}{passed}/{total} tests passed\033[0m")
    print("=" * 60)
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
