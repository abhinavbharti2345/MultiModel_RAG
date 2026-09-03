from __future__ import annotations
import logging
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.services.storage_service import StorageService
from app.services.embedding_service import embedding_service
from app.services.qdrant_service import qdrant_service
from app.services.evidence_builder import EvidenceBuilder
from app.models.db_models import Evidence
from app.schemas.evidence_schemas import EvidenceResponse, EvidenceWithScore

logger = logging.getLogger(__name__)

# Events that occur within this many seconds of each other are considered part of
# the same temporal window and are rendered as one grouped entry in the timeline.
_TEMPORAL_WINDOW_SECONDS: float = 2.0

# Minimum character overlap fraction for two content strings to be considered
# near-duplicates (and thus suppressed).
_DEDUP_OVERLAP_RATIO: float = 0.85


def _is_near_duplicate(a: str, b: str) -> bool:
    """Return True when a and b share a very high character-level overlap."""
    if a == b:
        return True
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if not longer:
        return False
    # Count how many characters of the shorter string appear in the longer one
    # via a simple sliding-window common-substring heuristic.
    shorter_stripped = shorter.strip().lower()
    longer_stripped = longer.strip().lower()
    if shorter_stripped in longer_stripped:
        return True
    # Ratio of shorter length to longer length — catches reformatted duplicates
    if len(shorter_stripped) / max(len(longer_stripped), 1) >= _DEDUP_OVERLAP_RATIO:
        if shorter_stripped[:50] == longer_stripped[:50]:
            return True
    return False


class RetrievalService:
    def __init__(self, db: Session):
        self.db = db
        self.storage = StorageService(db)

    async def query(
        self,
        query_text: str,
        top_k: int = 10,
        expand_relationships: bool = True,
        include_multimodal: bool = True,
        source_ids: Optional[list[UUID]] = None,
    ) -> list[EvidenceWithScore]:
        vectors = await embedding_service.embed_texts_async([query_text])
        if not vectors:
            return []
        qvec = vectors[0]

        qdrant_hits = qdrant_service.search(
            query_vector=qvec,
            top_k=max(top_k * 10, 100),
            score_threshold=embedding_service.retrieval_score_threshold,
            source_ids=source_ids,
        )
        if not qdrant_hits:
            return []

        evidence_by_id: dict[UUID, Evidence] = {}
        scored: list[tuple[Evidence, float]] = []

        for evidence_id, score, payload in qdrant_hits:
            ev = self.storage.get_evidence(evidence_id)
            if ev is None:
                ev = self.db.query(Evidence).filter(Evidence.id == evidence_id).first()
            if ev is None:
                continue
            evidence_by_id[evidence_id] = ev
            # Confidence-weighted retrieval
            final_score = score * (ev.confidence if ev.confidence is not None else 1.0)
            scored.append((ev, final_score))

        scored.sort(key=lambda x: -x[1])
        scored = scored[:top_k]

        results: list[EvidenceWithScore] = []
        visited_related: set[UUID] = set()

        for ev, score in scored:
            related_evidences: list[Evidence] = []
            related_frames = []

            if expand_relationships:
                related = self.storage.get_related_evidence(ev.id, max_hops=1, min_confidence=0.6)
                for rev in related:
                    if rev.id in visited_related or rev.id == ev.id:
                        continue
                    visited_related.add(rev.id)
                    related_evidences.append(rev)

            frames = self.storage.get_frames_for_evidence(ev.id)
            for fr in frames:
                related_frames.append({
                    "frame_id": str(fr.id),
                    "timestamp_seconds": fr.timestamp_seconds,
                    "frame_path": fr.frame_path,
                    "width": fr.width,
                    "height": fr.height,
                    "is_important": fr.is_important,
                    "ocr_text": fr.ocr_text,
                })

            results.append(EvidenceWithScore(
                evidence=EvidenceResponse.model_validate(ev),
                similarity_score=score,
                related_evidence=[EvidenceResponse.model_validate(r) for r in related_evidences],
                related_frames=related_frames,
            ))

        return results

    def evidence_to_text_block(self, ev: EvidenceResponse) -> str:
        """Detailed block format. Used by the LLM for provenance-rich output."""
        lines = [f"[Evidence ID: {ev.id}]"]
        lines.append(f"Modality: {ev.modality}")
        lines.append(f"Source ID: {ev.source_id}")
        if ev.timestamp_start is not None:
            lines.append(f"Timestamp: {self._fmt_ts(ev.timestamp_start)}"
                         + (f" - {self._fmt_ts(ev.timestamp_end)}" if ev.timestamp_end else ""))
        if ev.page_number is not None:
            lines.append(f"Page: {ev.page_number}")
        if ev.speaker:
            lines.append(f"Speaker: {ev.speaker}")
        lines.append(f"Content: {ev.content}")
        if ev.entities:
            lines.append(f"Entities: {', '.join(ev.entities)}")
        prov = ev.provenance.model_dump() if ev.provenance else None
        if prov:
            lines.append(f"Provenance: {prov}")
        lines.append("---")
        return "\n".join(lines)

    def _evidence_to_timeline_block(self, ev: EvidenceResponse) -> str:
        """
        Compact timeline block. Timestamp and modality appear in the header so
        the LLM can read the sequence like a script without losing provenance.
        """
        # ModalityType is a str-subclass enum — .value gives the raw string ("audio", "visual", …)
        mod_val = ev.modality.value if hasattr(ev.modality, "value") else str(ev.modality)
        modality = mod_val.upper()
        ts_label = self._fmt_ts(ev.timestamp_start) if ev.timestamp_start is not None else "??:??"
        ts_end_label = (f"–{self._fmt_ts(ev.timestamp_end)}" if ev.timestamp_end is not None else "")
        speaker_label = f"  Speaker: {ev.speaker}" if ev.speaker else ""

        header = f"[{ts_label}{ts_end_label} {modality}]{speaker_label}  (Evidence ID: {ev.id})"
        prov = ev.provenance.model_dump() if ev.provenance else None
        prov_line = f"  Provenance: {prov}" if prov else ""
        entities_line = f"  Entities: {', '.join(ev.entities)}" if ev.entities else ""

        parts = [header, f"  {ev.content}"]
        if entities_line:
            parts.append(entities_line)
        if prov_line:
            parts.append(prov_line)
        parts.append("---")
        return "\n".join(parts)

    def _evidence_to_page_block(self, ev: EvidenceResponse) -> str:
        """Block for page-based document evidence (PDFs). No video timestamp."""
        page_label = f"Page {ev.page_number}" if ev.page_number is not None else "Unknown page"
        mod_val = ev.modality.value if hasattr(ev.modality, "value") else str(ev.modality)
        modality = mod_val.upper()
        header = f"[{page_label} {modality}]  (Evidence ID: {ev.id}, Source: {ev.source_id})"
        prov = ev.provenance.model_dump() if ev.provenance else None
        prov_line = f"  Provenance: {prov}" if prov else ""
        entities_line = f"  Entities: {', '.join(ev.entities)}" if ev.entities else ""

        parts = [header, f"  {ev.content}"]
        if entities_line:
            parts.append(entities_line)
        if prov_line:
            parts.append(prov_line)
        parts.append("---")
        return "\n".join(parts)

    # ------------------------------------------------------------------ #
    # Context builder                                                      #
    # ------------------------------------------------------------------ #

    def build_context_prompt(
        self,
        results: list[EvidenceWithScore],
        max_chars: Optional[int] = None,
    ) -> str:
        """
        Build an LLM context string with a token-aware evidence budget.

        Pipeline:
          retrieve (top_k*2) → dedup → priority ranking → chronological sort
          → pack into token budget (atomic blocks) → LLM

        Args:
            results:   Output of RetrievalService.query().
            max_chars: Optional explicit character cap. When None (default) the
                       budget is derived from llm_service.evidence_char_budget,
                       which uses LLM_CONTEXT_WINDOW_TOKENS and
                       LLM_ANSWER_RESERVE_TOKENS from config/environment.
        """
        # Import here to avoid circular import at module load time.
        from app.services.llm_service import llm_service, _CHARS_PER_TOKEN

        char_budget: int = max_chars if max_chars is not None else llm_service.evidence_char_budget
        logger.debug(
            f"build_context_prompt: budget={char_budget} chars "
            f"(~{char_budget / _CHARS_PER_TOKEN:.0f} tokens), "
            f"{len(results)} primary hits"
        )

        # ── 1. Flatten all evidence, tracking primary vs related tier ──────
        #
        # Primary evidence (directly returned by Qdrant, already ranked by
        # similarity × confidence) takes priority over related/expanded evidence.
        # Both tiers are deduplicated by evidence ID first.
        #
        primary_ids: set[UUID] = set()
        primary_ev: dict[UUID, tuple[EvidenceResponse, float]] = {}  # id → (ev, score)
        related_ev: dict[UUID, EvidenceResponse] = {}

        for hit in results:
            ev = hit.evidence
            if ev.id not in primary_ev:
                primary_ev[ev.id] = (ev, hit.similarity_score)
                primary_ids.add(ev.id)
            for rel in hit.related_evidence:
                if rel.id not in primary_ev and rel.id not in related_ev:
                    related_ev[rel.id] = rel

        # ── 2. Global near-duplicate suppression ───────────────────────────
        #
        # Walk primary hits (highest score first), then related, and suppress
        # any piece of evidence whose content is near-identical to one already
        # retained. This runs before rendering so we don't waste budget on dupes.
        all_scored: list[tuple[EvidenceResponse, float, bool]] = (
            [(ev, score, True) for ev, score in primary_ev.values()]
            + [(ev, 0.0, False) for ev in related_ev.values()]
        )
        # Sort: primary first (descending score), then related
        all_scored.sort(key=lambda x: (-float(x[2]), -x[1]))

        seen_content: list[str] = []
        deduped: list[tuple[EvidenceResponse, bool]] = []   # (evidence, is_primary)
        for ev, score, is_primary in all_scored:
            if any(_is_near_duplicate(ev.content, seen) for seen in seen_content[-12:]):
                logger.debug(f"Suppressing near-duplicate evidence {ev.id}")
                continue
            deduped.append((ev, is_primary))
            seen_content.append(ev.content)

        # ── 3. Split into timed (video/audio) vs page-based (PDF) tracks ──
        timed: list[tuple[EvidenceResponse, bool]] = []
        page_based: list[tuple[EvidenceResponse, bool]] = []

        for ev, is_primary in deduped:
            if ev.timestamp_start is not None:
                timed.append((ev, is_primary))
            elif ev.page_number is not None:
                page_based.append((ev, is_primary))
            else:
                timed.append((ev, is_primary))   # no anchor → put in timeline at t=0

        # ── 4. Sort timed track chronologically (audio before visual at ties) ─
        _MODALITY_PRIORITY = {"audio": 0, "text": 1, "ocr": 2, "visual": 3, "multimodal": 4}

        def _timed_sort_key(item: tuple[EvidenceResponse, bool]):
            ev, _ = item
            ts = ev.timestamp_start if ev.timestamp_start is not None else 0.0
            mod_val = ev.modality.value if hasattr(ev.modality, "value") else str(ev.modality)
            mod_priority = _MODALITY_PRIORITY.get(mod_val.lower(), 99)
            return (ts, mod_priority)

        timed.sort(key=_timed_sort_key)

        # ── 5. Sort page track by page number, primary before related at same page ─
        page_based.sort(key=lambda item: (item[0].page_number or 0, not item[1]))

        # ── 6. Pack into char budget — never cut mid-block ─────────────────
        #
        # Strategy: primary evidence is guaranteed a slot before related.
        # Within each tier, chronological / page order is preserved.
        # A block that would overflow the budget is skipped (not truncated).
        # The skip is noted with a single-line marker at the end.
        blocks: list[str] = []
        chars_used: int = 0
        timed_skipped: int = 0
        page_skipped: int = 0

        def _try_append(text: str) -> bool:
            nonlocal chars_used
            cost = len(text)
            if chars_used + cost > char_budget:
                return False
            blocks.append(text)
            chars_used += cost
            return True

        # --- Timeline section -----------------------------------------------
        if timed:
            _try_append("=== Video / Audio Timeline (chronological) ===")

            # Pass 1: primary timed evidence
            for ev, is_primary in timed:
                if not is_primary:
                    continue
                block = self._evidence_to_timeline_block(ev)
                if not _try_append(block):
                    timed_skipped += 1

            # Pass 2: related timed evidence (fills remaining budget)
            for ev, is_primary in timed:
                if is_primary:
                    continue
                block = self._evidence_to_timeline_block(ev)
                if not _try_append(block):
                    timed_skipped += 1

            if timed_skipped:
                _try_append(
                    f"... [{timed_skipped} additional timeline evidence item(s) omitted "
                    f"— context budget exhausted; increase LLM_CONTEXT_WINDOW_TOKENS or "
                    f"reduce top_k to include them]"
                )

        # --- Document section -----------------------------------------------
        if page_based:
            _try_append("\n=== Document Evidence (page order) ===")

            for ev, is_primary in page_based:
                if not is_primary:
                    continue
                block = self._evidence_to_page_block(ev)
                if not _try_append(block):
                    page_skipped += 1

            for ev, is_primary in page_based:
                if is_primary:
                    continue
                block = self._evidence_to_page_block(ev)
                if not _try_append(block):
                    page_skipped += 1

            if page_skipped:
                _try_append(
                    f"... [{page_skipped} additional document evidence item(s) omitted "
                    f"— context budget exhausted]"
                )

        context = "\n\n".join(blocks)
        estimated_tokens = len(context) / _CHARS_PER_TOKEN
        logger.info(
            f"Context built: {len(context)} chars "
            f"(~{estimated_tokens:.0f} tokens / "
            f"{char_budget / _CHARS_PER_TOKEN:.0f} token budget), "
            f"{len(deduped)} evidence items included, "
            f"{timed_skipped + page_skipped} skipped"
        )
        return context

    @staticmethod
    def _fmt_ts(seconds: Optional[float]) -> str:
        if seconds is None:
            return "00:00"
        total = int(seconds)
        h = total // 3600
        m = (total % 3600) // 60
        s = total % 60
        if h:
            return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"
