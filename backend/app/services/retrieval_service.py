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
            top_k=max(top_k * 2, 20),
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

    def build_context_prompt(
        self,
        results: list[EvidenceWithScore],
        max_chars: int = 12000,
    ) -> str:
        blocks = []
        total = 0
        for hit in results:
            block = self.evidence_to_text_block(hit.evidence)
            if total + len(block) > max_chars:
                break
            blocks.append(block)
            total += len(block)
            for rel in hit.related_evidence:
                rblock = "[Related] " + self.evidence_to_text_block(rel)
                if total + len(rblock) > max_chars:
                    continue
                blocks.append(rblock)
                total += len(rblock)
        return "\n\n".join(blocks)

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
