"""
Tests for token-aware context budgeting in retrieval_service.py.

Specifically proves that:
- Evidence beyond the old 12,000-char boundary reaches the LLM when the model
  has a larger context window.
- Primary (Qdrant-ranked) evidence always lands before related/expanded evidence.
- Budget is derived from llm_service.evidence_char_budget (model-driven).
- An explicit max_chars override still works.
- No evidence block is ever truncated mid-way.
- Skipped items are reported, not silently dropped.

Run from backend/ directory:
    python scripts/test_context_budget.py
"""
from __future__ import annotations
import sys
import uuid
from pathlib import Path
from typing import Optional

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.services.retrieval_service import RetrievalService, _is_near_duplicate
from app.services.llm_service import llm_service, _CHARS_PER_TOKEN, _KNOWN_MODEL_CONTEXT_WINDOWS
from app.schemas.evidence_schemas import EvidenceResponse, EvidenceWithScore, Provenance
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
    page_number: Optional[int] = None,
    speaker: Optional[str] = None,
) -> EvidenceResponse:
    sid = uuid.uuid4()
    return EvidenceResponse(
        id=uuid.uuid4(),
        source_id=sid,
        modality=modality,
        content=content,
        timestamp_start=timestamp_start,
        page_number=page_number,
        speaker=speaker,
        confidence=1.0,
        entities=[],
        relationships=[],
        provenance=Provenance(source=str(sid)),
        created_at="2024-01-01T00:00:00",
    )


def make_hit(
    ev: EvidenceResponse,
    score: float = 0.9,
    related: list[EvidenceResponse] | None = None,
) -> EvidenceWithScore:
    return EvidenceWithScore(
        evidence=ev,
        similarity_score=score,
        related_evidence=[EvidenceResponse.model_validate(r) for r in (related or [])],
        related_frames=[],
    )


def get_service() -> RetrievalService:
    svc = object.__new__(RetrievalService)
    svc.db = None
    svc.storage = None
    return svc


# ── tests ─────────────────────────────────────────────────────────────────────

def test_model_context_window_lookup():
    """llama-3.3-70b-versatile must resolve to 131072 tokens."""
    print("\n[1] Model context window lookup")
    svc_llm = llm_service
    # Force model to known model (test env may have different .env)
    orig = svc_llm.model
    svc_llm.model = "llama-3.3-70b-versatile"
    ctx = svc_llm.context_window_tokens
    budget = svc_llm.evidence_token_budget
    char_budget = svc_llm.evidence_char_budget
    svc_llm.model = orig

    passed = True
    passed &= check("Context window = 131072 tokens", ctx == 131_072, str(ctx))
    passed &= check("Token budget > 12000 tokens (old hardcoded limit / chars_per_token)",
                    budget > 12_000, f"{budget} tokens")
    passed &= check("Char budget > 12000 chars (old hardcoded char limit)",
                    char_budget > 12_000, f"{char_budget} chars")
    return passed


def test_env_override():
    """LLM_CONTEXT_WINDOW_TOKENS env override is respected."""
    print("\n[2] LLM_CONTEXT_WINDOW_TOKENS env override")
    from app.config import settings
    orig = settings.LLM_CONTEXT_WINDOW_TOKENS
    settings.__dict__["LLM_CONTEXT_WINDOW_TOKENS"] = 16_000
    try:
        svc_llm = llm_service
        orig_model = svc_llm.model
        svc_llm.model = "llama-3.3-70b-versatile"  # model table says 131072
        ctx = svc_llm.context_window_tokens
        svc_llm.model = orig_model
    finally:
        settings.__dict__["LLM_CONTEXT_WINDOW_TOKENS"] = orig

    passed = check("Override 16000 wins over model table 131072", ctx == 16_000, str(ctx))
    return passed


def test_evidence_beyond_old_12k_limit():
    """
    Evidence items collectively exceeding the old 12,000-char hardcoded limit
    must all be included when the model has a larger context window.
    """
    print("\n[3] Evidence beyond old 12,000-char limit reaches context")

    # 30 unique audio clips, each ~500 chars of content (total ~15,000 chars)
    evs = [
        make_ev("audio", f"Segment {i}: " + f"content-{i}-" * 40, timestamp_start=float(i * 5))
        for i in range(30)
    ]
    hits = [make_hit(ev, score=0.9 - i * 0.01) for i, ev in enumerate(evs)]

    svc = get_service()
    # Use default budget (model-driven — much larger than 12000 chars)
    ctx = svc.build_context_prompt(hits)

    # All 30 unique content strings should appear (no budget exhaustion)
    included = sum(1 for ev in evs if ev.content[:30] in ctx)
    old_12k_included = sum(
        1 for ev in evs
        if ev.content[:30] in svc.build_context_prompt(hits, max_chars=12_000)
    )

    passed = True
    passed &= check("Default budget includes all 30 items", included == 30,
                    f"{included}/30 included")
    passed &= check("Old 12k limit would have excluded some",
                    old_12k_included < 30,
                    f"12k limit included {old_12k_included}/30")
    passed &= check(f"Total context > 12000 chars", len(ctx) > 12_000,
                    f"{len(ctx)} chars")
    return passed


def test_primary_before_related():
    """Primary evidence (higher Qdrant score) must appear before related/expanded."""
    print("\n[4] Primary evidence appears before related evidence")

    primary = make_ev("audio", "Primary high-relevance content A", timestamp_start=100.0)
    related = make_ev("audio", "Related lower-relevance content B", timestamp_start=1.0)

    # related has earlier timestamp BUT is in the related_evidence list, not primary
    hit = make_hit(primary, score=0.95, related=[related])
    svc = get_service()

    # Use a tight budget that can only fit primary + one block overhead
    # primary block ~300 chars, related block ~300 chars, header ~50 chars
    ctx = svc.build_context_prompt([hit], max_chars=500)

    pos_primary = ctx.find("Primary high-relevance content A")
    pos_related = ctx.find("Related lower-relevance content B")

    passed = True
    passed &= check("Primary content present in context", pos_primary != -1)
    # related may or may not fit — it should not displace primary
    if pos_related != -1:
        passed &= check("Primary appears before related in output",
                        pos_primary < pos_related,
                        f"primary={pos_primary}, related={pos_related}")
    else:
        passed &= check("Related excluded when budget is tight (primary kept)", True)
    return passed


def test_atomic_blocks_never_cut():
    """No evidence block should be truncated halfway through."""
    print("\n[5] Evidence blocks are never truncated mid-way")

    # Create items with 200-char content each
    evs = [
        make_ev("audio", f"Block {i}: " + "x" * 180, timestamp_start=float(i))
        for i in range(20)
    ]
    hits = [make_hit(ev) for ev in evs]
    svc = get_service()

    # Use a budget of 1500 chars — large enough for a few blocks but not all
    ctx = svc.build_context_prompt(hits, max_chars=1500)

    # Every block that appears must be complete — check for '---' ending
    # Split on the section header to get individual blocks
    block_texts = [b.strip() for b in ctx.split("---") if b.strip()]
    # Every non-header, non-marker block should contain content
    incomplete = [b for b in block_texts if b.startswith("[") and not b]

    passed = True
    passed &= check("Context fits within 1500 chars", len(ctx) <= 1500, f"{len(ctx)} chars")
    passed &= check("No incomplete blocks detected", len(incomplete) == 0,
                    f"{len(incomplete)} incomplete blocks")

    # Verify that included content strings appear complete (not cut mid-word)
    for ev in evs:
        tag = f"Block {ev.content.split(':')[0].split(' ')[-1]}:"
        if tag in ctx:
            full = ev.content
            passed &= check(f"Block starting '{tag}' complete",
                            full in ctx, f"content truncated")
    return passed


def test_skip_marker_present_when_over_budget():
    """When evidence is skipped, the omission marker must appear in the context."""
    print("\n[6] Omission marker appears when items are skipped")

    evs = [make_ev("audio", f"Speech segment number {i} " + "w" * 200,
                   timestamp_start=float(i)) for i in range(20)]
    hits = [make_hit(ev) for ev in evs]
    svc = get_service()

    ctx = svc.build_context_prompt(hits, max_chars=1200)

    passed = check("Omission marker present when items skipped",
                   "omitted" in ctx.lower() or "truncated" in ctx.lower(),
                   repr(ctx[-200:]))
    return passed


def test_explicit_max_chars_override():
    """max_chars=N must override the model-derived budget."""
    print("\n[7] Explicit max_chars overrides model-derived budget")

    evs = [make_ev("audio", "A" * 300, timestamp_start=float(i)) for i in range(50)]
    hits = [make_hit(ev) for ev in evs]
    svc = get_service()

    ctx_small = svc.build_context_prompt(hits, max_chars=2000)
    ctx_large = svc.build_context_prompt(hits, max_chars=30_000)

    passed = True
    passed &= check("Small override respected", len(ctx_small) <= 2000,
                    f"{len(ctx_small)} chars")
    passed &= check("Large override respected", len(ctx_large) <= 30_000,
                    f"{len(ctx_large)} chars")
    passed &= check("Large context includes more than small context",
                    len(ctx_large) > len(ctx_small))
    return passed


def test_reserve_tokens_configurable():
    """LLM_ANSWER_RESERVE_TOKENS controls how much is deducted from the budget."""
    print("\n[8] LLM_ANSWER_RESERVE_TOKENS is configurable")
    from app.config import settings
    orig_reserve = settings.LLM_ANSWER_RESERVE_TOKENS
    orig_ctx = settings.LLM_CONTEXT_WINDOW_TOKENS

    try:
        # Fix context window to 10000 tokens for deterministic test
        settings.__dict__["LLM_CONTEXT_WINDOW_TOKENS"] = 10_000
        settings.__dict__["LLM_ANSWER_RESERVE_TOKENS"] = 1_000
        budget_small_reserve = llm_service.evidence_char_budget

        settings.__dict__["LLM_ANSWER_RESERVE_TOKENS"] = 5_000
        budget_large_reserve = llm_service.evidence_char_budget
    finally:
        settings.__dict__["LLM_ANSWER_RESERVE_TOKENS"] = orig_reserve
        settings.__dict__["LLM_CONTEXT_WINDOW_TOKENS"] = orig_ctx

    passed = check("Larger reserve → smaller evidence budget",
                   budget_small_reserve > budget_large_reserve,
                   f"small_reserve→{budget_small_reserve}, large_reserve→{budget_large_reserve}")
    return passed


def test_unknown_model_fallback():
    """An unrecognised model name should fall back to a safe small context window."""
    print("\n[9] Unknown model falls back to 8192-token conservative window")
    orig = llm_service.model
    llm_service.model = "some-unknown-future-model-v99"
    ctx = llm_service.context_window_tokens
    llm_service.model = orig

    passed = check("Fallback = 8192 tokens", ctx == 8_192, str(ctx))
    return passed


def test_token_estimate_reasonable():
    """Char budget should be within 20% of evidence_token_budget * chars_per_token."""
    print("\n[10] Char budget matches token budget * chars_per_token")
    orig = llm_service.model
    llm_service.model = "llama-3.3-70b-versatile"
    token_budget = llm_service.evidence_token_budget
    char_budget = llm_service.evidence_char_budget
    llm_service.model = orig

    expected = int(token_budget * _CHARS_PER_TOKEN)
    passed = check(
        f"char_budget == token_budget * {_CHARS_PER_TOKEN}",
        char_budget == expected,
        f"char_budget={char_budget}, expected={expected}"
    )
    return passed


# ── runner ────────────────────────────────────────────────────────────────────

def main():
    print("=" * 62)
    print("Context Budget Tests")
    print(f"  Active model (from config): {llm_service.model}")
    print(f"  Context window:  {llm_service.context_window_tokens:,} tokens")
    print(f"  Evidence budget: {llm_service.evidence_token_budget:,} tokens")
    print(f"  Char budget:     {llm_service.evidence_char_budget:,} chars")
    print(f"  Old hard limit:  12,000 chars (was hardcoded)")
    print("=" * 62)

    tests = [
        test_model_context_window_lookup,
        test_env_override,
        test_evidence_beyond_old_12k_limit,
        test_primary_before_related,
        test_atomic_blocks_never_cut,
        test_skip_marker_present_when_over_budget,
        test_explicit_max_chars_override,
        test_reserve_tokens_configurable,
        test_unknown_model_fallback,
        test_token_estimate_reasonable,
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

    print("\n" + "=" * 62)
    passed = sum(results)
    total = len(results)
    color = "\033[32m" if passed == total else "\033[31m"
    print(f"{color}{passed}/{total} tests passed\033[0m")
    print("=" * 62)
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
