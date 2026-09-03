"""
Tests for multimodal context ordering in retrieval_service.py.

Verifies that audio + OCR + visual evidence is interleaved by timestamp,
PDFs are kept separate, duplicates are suppressed, and format is correct.

Run from backend/ directory:
    python scripts/test_context_ordering.py
"""
from __future__ import annotations
import sys
import uuid
from pathlib import Path
from typing import Optional

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.services.retrieval_service import RetrievalService, _is_near_duplicate
from app.schemas.evidence_schemas import (
    EvidenceResponse, EvidenceWithScore, Provenance,
)
from app.models.db_models import ModalityType

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"


# ── helpers ───────────────────────────────────────────────────────────────────

def check(label: str, condition: bool, detail: str = "") -> bool:
    status = PASS if condition else FAIL
    print(f"  {status}  {label}" + (f"  [{detail}]" if detail else ""))
    return condition


def make_ev(
    modality: str,
    content: str,
    timestamp_start: Optional[float] = None,
    timestamp_end: Optional[float] = None,
    page_number: Optional[int] = None,
    speaker: Optional[str] = None,
) -> EvidenceResponse:
    source_id = uuid.uuid4()
    return EvidenceResponse(
        id=uuid.uuid4(),
        source_id=source_id,
        modality=modality,
        content=content,
        timestamp_start=timestamp_start,
        timestamp_end=timestamp_end,
        page_number=page_number,
        speaker=speaker,
        confidence=1.0,
        entities=[],
        relationships=[],
        provenance=Provenance(source=str(source_id)),
        created_at="2024-01-01T00:00:00",
    )


def make_hit(ev: EvidenceResponse, score: float = 0.9) -> EvidenceWithScore:
    return EvidenceWithScore(
        evidence=ev,
        similarity_score=score,
        related_evidence=[],
        related_frames=[],
    )


# RetrievalService requires a DB session, but build_context_prompt is pure logic.
# Instantiate with None — only storage-touching methods need a real session.
class _NullDB:
    pass


def get_service() -> RetrievalService:
    svc = object.__new__(RetrievalService)
    svc.db = _NullDB()
    svc.storage = None
    return svc


# ── tests ─────────────────────────────────────────────────────────────────────

def test_chronological_interleaving():
    """Audio, visual, OCR at different timestamps must appear in time order."""
    print("\n[1] Chronological interleaving of audio + visual + OCR")

    ev_audio_5 = make_ev("audio", "Presenter introduces the API", timestamp_start=5.0, timestamp_end=6.9, speaker="Alice")
    ev_visual_6 = make_ev("visual", "Architecture diagram appears on screen", timestamp_start=6.0)  # no end
    ev_ocr_7 = make_ev("ocr", "API Gateway", timestamp_start=7.0)
    ev_audio_8 = make_ev("audio", "Presenter explains the gateway component", timestamp_start=8.0, speaker="Alice")
    ev_visual_10 = make_ev("visual", "Database diagram appears", timestamp_start=10.0)

    hits = [make_hit(ev_audio_8), make_hit(ev_visual_6), make_hit(ev_ocr_7),
            make_hit(ev_audio_5), make_hit(ev_visual_10)]

    svc = get_service()
    ctx = svc.build_context_prompt(hits)

    # Find positions of *content strings* which are unique per evidence block.
    # This avoids false matches from timestamps embedded in ranges (e.g. [00:05–00:06 AUDIO]).
    pos_5 = ctx.find("Presenter introduces the API")
    pos_6 = ctx.find("Architecture diagram appears on screen")
    pos_7 = ctx.find("API Gateway")
    pos_8 = ctx.find("Presenter explains the gateway component")
    pos_10 = ctx.find("Database diagram appears")

    passed = True
    passed &= check("00:05 AUDIO content found", pos_5 != -1)
    passed &= check("00:06 VISUAL content found", pos_6 != -1)
    passed &= check("00:07 OCR content found", pos_7 != -1)
    passed &= check("00:08 AUDIO content found", pos_8 != -1)
    passed &= check("00:10 VISUAL content found", pos_10 != -1)
    passed &= check("All content in chronological order",
                    pos_5 < pos_6 < pos_7 < pos_8 < pos_10,
                    f"positions: {pos_5},{pos_6},{pos_7},{pos_8},{pos_10}")

    return passed


def test_modality_labels_visible():
    """Each timeline block must include its modality label."""
    print("\n[2] Modality labels present in each timeline block")

    ev_a = make_ev("audio", "Audio content here", timestamp_start=2.0)
    ev_v = make_ev("visual", "Visual content here", timestamp_start=4.0)
    ev_o = make_ev("ocr", "OCR text here", timestamp_start=6.0)

    svc = get_service()
    ctx = svc.build_context_prompt([make_hit(ev_a), make_hit(ev_v), make_hit(ev_o)])

    passed = True
    passed &= check("AUDIO label present", "AUDIO" in ctx)
    passed &= check("VISUAL label present", "VISUAL" in ctx)
    passed &= check("OCR label present", "OCR" in ctx)
    return passed


def test_pdf_pages_not_in_timeline():
    """PDF page-based evidence must appear in the document section, not timeline."""
    print("\n[3] PDF page evidence kept separate from timeline")

    ev_audio = make_ev("audio", "Spoken content", timestamp_start=5.0)
    ev_pdf_p1 = make_ev("text", "PDF page one content", page_number=1)
    ev_pdf_p2 = make_ev("text", "PDF page two content", page_number=2)

    svc = get_service()
    ctx = svc.build_context_prompt([make_hit(ev_audio), make_hit(ev_pdf_p1), make_hit(ev_pdf_p2)])

    # Timeline section should not have "Page 1" or "Page 2"
    timeline_end = ctx.find("Document Evidence")
    timeline_section = ctx[:timeline_end] if timeline_end != -1 else ctx

    passed = True
    passed &= check("Document Evidence section present", "Document Evidence" in ctx)
    passed &= check("Video/Audio Timeline section present", "Video / Audio Timeline" in ctx)
    passed &= check("Page 1 not in timeline section",
                    "Page 1" not in timeline_section)
    passed &= check("Page 2 not in timeline section",
                    "Page 2" not in timeline_section)
    # But pages should be in the doc section
    doc_section = ctx[timeline_end:] if timeline_end != -1 else ""
    passed &= check("Page 1 appears in doc section", "Page 1" in doc_section)
    passed &= check("Page 2 appears in doc section", "Page 2" in doc_section)
    return passed


def test_deduplication():
    """Near-identical content at different IDs must be suppressed."""
    print("\n[4] Near-duplicate evidence deduplication")

    content = "The system uses Redis caching layer in front of PostgreSQL database"
    ev1 = make_ev("audio", content, timestamp_start=10.0)
    ev2 = make_ev("ocr", content, timestamp_start=11.0)  # identical text — should be dropped
    ev3 = make_ev("visual", "Database topology diagram shown", timestamp_start=12.0)

    svc = get_service()
    ctx = svc.build_context_prompt([make_hit(ev1), make_hit(ev2), make_hit(ev3)])

    # Evidence ID for ev1 should appear, evidence ID for ev2 should NOT (deduped)
    ev1_present = str(ev1.id) in ctx
    ev2_present = str(ev2.id) in ctx
    ev3_present = str(ev3.id) in ctx

    passed = True
    passed &= check("First occurrence retained", ev1_present)
    passed &= check("Near-duplicate suppressed", not ev2_present,
                    "ev2 ID found in context (should be deduped)")
    passed &= check("Non-duplicate visual retained", ev3_present)
    return passed


def test_audio_before_visual_same_timestamp():
    """Audio should appear before visual at identical timestamps."""
    print("\n[5] Audio before visual at same timestamp")

    ev_visual = make_ev("visual", "Diagram shown", timestamp_start=15.0)
    ev_audio = make_ev("audio", "Explaining the diagram", timestamp_start=15.0)

    svc = get_service()
    ctx = svc.build_context_prompt([make_hit(ev_visual), make_hit(ev_audio)])

    pos_audio = ctx.find("Explaining the diagram")
    pos_visual = ctx.find("Diagram shown")

    passed = check("Audio content before visual at same timestamp",
                   pos_audio < pos_visual,
                   f"audio_pos={pos_audio}, visual_pos={pos_visual}")
    return passed


def test_evidence_ids_preserved():
    """Every evidence ID must appear in the output context."""
    print("\n[6] Evidence IDs preserved in context")

    ev1 = make_ev("audio", "First statement", timestamp_start=1.0)
    ev2 = make_ev("ocr", "OCR text block", timestamp_start=3.0)
    ev3 = make_ev("visual", "Visual frame", timestamp_start=5.0)
    ev4 = make_ev("text", "Document content", page_number=3)

    svc = get_service()
    ctx = svc.build_context_prompt([make_hit(ev1), make_hit(ev2), make_hit(ev3), make_hit(ev4)])

    passed = True
    for ev in [ev1, ev2, ev3, ev4]:
        passed &= check(f"ID {str(ev.id)[:8]}... in context", str(ev.id) in ctx)
    return passed


def test_speaker_label_present():
    """Speaker metadata must appear in timeline blocks."""
    print("\n[7] Speaker label in timeline block")

    ev = make_ev("audio", "Some speech content", timestamp_start=20.0, speaker="Dr. Smith")
    svc = get_service()
    ctx = svc.build_context_prompt([make_hit(ev)])

    passed = check("Speaker: Dr. Smith in output", "Dr. Smith" in ctx)
    return passed


def test_max_chars_respected():
    """Output must not exceed max_chars budget."""
    print("\n[8] max_chars budget respected")

    evs = [make_ev("audio", "A" * 500, timestamp_start=float(i)) for i in range(30)]
    hits = [make_hit(e) for e in evs]
    svc = get_service()
    ctx = svc.build_context_prompt(hits, max_chars=3000)

    passed = check("Output within 3000 chars", len(ctx) <= 3000, f"{len(ctx)} chars")
    return passed


def test_near_duplicate_helper():
    """_is_near_duplicate utility correctness."""
    print("\n[9] _is_near_duplicate helper")
    passed = True
    passed &= check("Identical strings are duplicates",
                    _is_near_duplicate("hello world", "hello world"))
    passed &= check("Substring is duplicate",
                    _is_near_duplicate("Redis", "Redis caching layer"))
    passed &= check("Completely different strings are not duplicates",
                    not _is_near_duplicate("Redis caching layer", "PostgreSQL database schema"))
    return passed


def test_no_modality_grouping_headers():
    """Old-style modality headers (=== Audio / Transcript Evidence ===) must be gone."""
    print("\n[10] Old modality-group headers absent")

    ev1 = make_ev("audio", "Speech", timestamp_start=1.0)
    ev2 = make_ev("visual", "Frame", timestamp_start=2.0)
    svc = get_service()
    ctx = svc.build_context_prompt([make_hit(ev1), make_hit(ev2)])

    passed = True
    passed &= check("No '=== Audio / Transcript Evidence ===' header",
                    "Audio / Transcript Evidence" not in ctx)
    passed &= check("No '=== OCR / Text Evidence ===' header",
                    "OCR / Text Evidence" not in ctx)
    passed &= check("No '=== Visual Evidence ===' header",
                    "Visual Evidence" not in ctx)
    return passed


# ── runner ────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("Context Ordering Tests")
    print("=" * 60)

    tests = [
        test_chronological_interleaving,
        test_modality_labels_visible,
        test_pdf_pages_not_in_timeline,
        test_deduplication,
        test_audio_before_visual_same_timestamp,
        test_evidence_ids_preserved,
        test_speaker_label_present,
        test_max_chars_respected,
        test_near_duplicate_helper,
        test_no_modality_grouping_headers,
    ]

    results = []
    for t in tests:
        try:
            results.append(t())
        except Exception as e:
            import traceback
            print(f"  {FAIL}  Test raised exception: {e}")
            traceback.print_exc()
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
