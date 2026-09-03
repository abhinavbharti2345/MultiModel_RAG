from __future__ import annotations
import logging
import re
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.models.db_models import (
    Evidence,
    Entity,
    EvidenceEntity,
    EvidenceFrame,
    Relationship,
    ModalityType,
    Source,
    Frame,
)
from app.schemas.evidence_schemas import (
    EvidenceCreate,
    EvidenceResponse,
    TranscriptSegment,
    VisualAnalysisResult,
)

logger = logging.getLogger(__name__)


class EvidenceBuilder:
    def __init__(self, db: Session):
        self.db = db

    def _get_or_create_entity(self, name: str, entity_type: Optional[str] = None) -> Entity:
        normalized = name.strip()
        if not normalized:
            raise ValueError("Entity name cannot be empty")
        existing = self.db.query(Entity).filter(Entity.name.ilike(normalized)).first()
        if existing:
            return existing
        new_entity = Entity(name=normalized, entity_type=entity_type)
        self.db.add(new_entity)
        self.db.flush()
        return new_entity

    def _extract_entities_from_text(self, text: str) -> list[str]:
        tech_patterns = [
            r"\bRedis\b", r"\bPostgre(?:SQL)?\b", r"\bMySQL\b", r"\bMongoDB\b",
            r"\bKafka\b", r"\bDocker\b", r"\bKubernetes\b", r"\bK8s\b",
            r"\bFastAPI\b", r"\bReact\b", r"\bPython\b", r"\bNode\.?js\b",
            r"\bTypeScript\b", r"\bJavaScript\b", r"\bGroq\b", r"\bQdrant\b",
            r"\bFFmpeg\b", r"\bOpenCV\b", r"\bWhisper\b", r"\bRAG\b",
            r"\bAPI\s+Gateway\b", r"\bLoad\s+Balancer\b", r"\bTTL\b",
            r"\bSLA\b", r"\bQPS\b", r"\bP(?:50|95|99)\b",
            r"\bCPU\b", r"\bRAM\b", r"\bSSD\b", r"\bHDD\b",
            r"\bAWS\b", r"\bGCP\b", r"\bAzure\b", r"\bS3\b",
            r"\bVLM\b", r"\bOCR\b", r"\bSTT\b", r"\bLLM\b",
            r"\bGPT\b", r"\bClaude\b", r"\bLlama\b",
        ]
        found: set[str] = set()
        for pattern in tech_patterns:
            for m in re.finditer(pattern, text, flags=re.IGNORECASE):
                match = m.group(0)
                canonical_match = match.replace(" ", "")
                if "Postgre" in match:
                    canonical_match = "PostgreSQL"
                elif "API" in match and "Gateway" in match:
                    canonical_match = "API Gateway"
                elif "Load" in match and "Balancer" in match:
                    canonical_match = "Load Balancers"
                found.add(canonical_match)
        return sorted(found)

    def create_evidence_from_transcript(
        self,
        source_id: UUID,
        segment: TranscriptSegment,
        frame_ids: Optional[list[UUID]] = None,
        base_confidence: float = 0.95,
    ) -> Evidence:
        content = segment.text.strip()
        if not content:
            raise ValueError("Empty transcript segment")

        entities = self._extract_entities_from_text(content)
        if segment.speaker:
            entities.append(f"Speaker: {segment.speaker}")

        evidence = Evidence(
            source_id=source_id,
            content=content,
            modality=ModalityType.AUDIO,
            timestamp_start=segment.start,
            timestamp_end=segment.end,
            speaker=segment.speaker,
            confidence=base_confidence,
            provenance={
                "type": "transcript",
                "source": "audio_extraction",
                "timestamp": f"{self._fmt_ts(segment.start)} - {self._fmt_ts(segment.end)}",
                "raw": segment.model_dump(),
            },
        )
        self.db.add(evidence)
        self.db.flush()

        for entity_name in entities:
            try:
                entity = self._get_or_create_entity(entity_name, entity_type="TECHNOLOGY" if entity_name.startswith("Speaker:") is False else "PERSON")
                self.db.add(EvidenceEntity(evidence_id=evidence.id, entity_id=entity.id))
            except Exception:
                pass

        for fid in (frame_ids or []):
            self.db.add(EvidenceFrame(evidence_id=evidence.id, frame_id=fid))

        return evidence

    def create_evidence_from_visual(
        self,
        source_id: UUID,
        frame_id: UUID,
        analysis: VisualAnalysisResult,
        timestamp_seconds: Optional[float] = None,
        page_number: Optional[int] = None,
        base_confidence: float = 0.85,
    ) -> Evidence:
        visual_content = analysis.description.strip()
        if not visual_content:
            raise ValueError("Empty visual analysis")

        combined_entities = list(dict.fromkeys(analysis.entities + self._extract_entities_from_text(visual_content)))
        if analysis.ocr_text:
            combined_entities += self._extract_entities_from_text(analysis.ocr_text)
        combined_entities = list(dict.fromkeys(combined_entities))

        full_content = visual_content
        if analysis.diagram_info and analysis.diagram_info.strip():
            full_content += "\n\nDiagram / Flow:\n" + analysis.diagram_info.strip()
        if analysis.relationships:
            full_content += "\n\nRelationships:\n" + "\n".join(f"- {r}" for r in analysis.relationships)
        if analysis.ocr_text and analysis.ocr_text.strip():
            full_content += "\n\nVisible text / OCR:\n" + analysis.ocr_text.strip()

        evidence = Evidence(
            source_id=source_id,
            content=full_content,
            modality=ModalityType.VISUAL,
            timestamp_start=timestamp_seconds,
            timestamp_end=timestamp_seconds,
            page_number=page_number,
            confidence=base_confidence,
            provenance={
                "type": "visual_analysis",
                "frame_id": str(frame_id),
                "page_number": page_number,
                "timestamp": self._fmt_ts(timestamp_seconds) if timestamp_seconds else None,
                "objects_detected": analysis.objects_detected,
            },
        )
        self.db.add(evidence)
        self.db.flush()

        for entity_name in combined_entities:
            try:
                entity = self._get_or_create_entity(entity_name, "TECHNOLOGY")
                self.db.add(EvidenceEntity(evidence_id=evidence.id, entity_id=entity.id))
            except Exception:
                pass

        self.db.add(EvidenceFrame(evidence_id=evidence.id, frame_id=frame_id))
        return evidence

    def create_evidence_from_text(
        self,
        source_id: UUID,
        text: str,
        page_number: Optional[int] = None,
        start_offset: Optional[int] = None,
        end_offset: Optional[int] = None,
        base_confidence: float = 0.98,
    ) -> Evidence:
        content = text.strip()
        if not content:
            raise ValueError("Empty text")

        entities = self._extract_entities_from_text(content)

        evidence = Evidence(
            source_id=source_id,
            content=content,
            modality=ModalityType.TEXT,
            page_number=page_number,
            confidence=base_confidence,
            provenance={
                "type": "document_text",
                "page_number": page_number,
                "char_start": start_offset,
                "char_end": end_offset,
            },
        )
        self.db.add(evidence)
        self.db.flush()

        for entity_name in entities:
            try:
                entity = self._get_or_create_entity(entity_name, "TECHNOLOGY")
                self.db.add(EvidenceEntity(evidence_id=evidence.id, entity_id=entity.id))
            except Exception:
                pass
        return evidence

    def create_evidence_from_ocr(
        self,
        source_id: UUID,
        frame_id: UUID,
        ocr_text: str,
        timestamp_seconds: Optional[float] = None,
        page_number: Optional[int] = None,
        base_confidence: float = 0.75,
    ) -> Evidence:
        content = ocr_text.strip()
        if not content:
            raise ValueError("Empty OCR text")

        entities = self._extract_entities_from_text(content)

        evidence = Evidence(
            source_id=source_id,
            content=content,
            modality=ModalityType.OCR,
            timestamp_start=timestamp_seconds,
            timestamp_end=timestamp_seconds,
            page_number=page_number,
            confidence=base_confidence,
            provenance={
                "type": "ocr",
                "frame_id": str(frame_id),
                "page_number": page_number,
            },
        )
        self.db.add(evidence)
        self.db.flush()

        for entity_name in entities:
            try:
                entity = self._get_or_create_entity(entity_name, "TECHNOLOGY")
                self.db.add(EvidenceEntity(evidence_id=evidence.id, entity_id=entity.id))
            except Exception:
                pass
        self.db.add(EvidenceFrame(evidence_id=evidence.id, frame_id=frame_id))
        return evidence

    def link_temporal(
        self,
        transcript_evidence: Evidence,
        visual_evidence: Evidence,
        max_gap_seconds: float = 10.0,
    ) -> Optional[Relationship]:
        t_start = transcript_evidence.timestamp_start or 0
        v_start = visual_evidence.timestamp_start or 0
        gap = abs(t_start - v_start)
        if gap > max_gap_seconds:
            return None

        confidence = max(0.5, 1.0 - (gap / max_gap_seconds) * 0.5)
        rel = Relationship(
            from_evidence_id=transcript_evidence.id,
            to_evidence_id=visual_evidence.id,
            relationship_type="temporally_coincident_with",
            confidence=confidence,
            rel_metadata={"gap_seconds": gap},
        )
        self.db.add(rel)

        reverse = Relationship(
            from_evidence_id=visual_evidence.id,
            to_evidence_id=transcript_evidence.id,
            relationship_type="temporally_coincident_with",
            confidence=confidence,
            rel_metadata={"gap_seconds": gap},
        )
        self.db.add(reverse)
        self.db.flush()
        return rel

    def link_shared_entities_bulk(self, evidence_list: list[Evidence], min_shared: int = 1) -> None:
        if not evidence_list:
            return
            
        ev_ids = [e.id for e in evidence_list]
        ev_entities = self.db.query(EvidenceEntity).filter(EvidenceEntity.evidence_id.in_(ev_ids)).all()
        
        from collections import defaultdict
        entity_to_evs = defaultdict(list)
        for ee in ev_entities:
            entity_to_evs[ee.entity_id].append(ee.evidence_id)
            
        pair_counts = defaultdict(int)
        for entity_id, evidence_ids in entity_to_evs.items():
            for i in range(len(evidence_ids)):
                for j in range(i + 1, len(evidence_ids)):
                    a, b = evidence_ids[i], evidence_ids[j]
                    if a > b:
                        a, b = b, a
                    pair_counts[(a, b)] += 1
                    
        modality_map = {e.id: e.modality for e in evidence_list}
        
        new_rels = []
        for (a_id, b_id), shared_count in pair_counts.items():
            if shared_count >= min_shared:
                if modality_map.get(a_id) != modality_map.get(b_id):
                    confidence = min(0.95, 0.5 + 0.1 * shared_count)
                    new_rels.append(Relationship(
                        from_evidence_id=a_id,
                        to_evidence_id=b_id,
                        relationship_type="shares_entities_with",
                        confidence=confidence,
                        rel_metadata={"shared_entity_count": shared_count},
                    ))
                    
        if new_rels:
            self.db.bulk_save_objects(new_rels)
            self.db.flush()

    def link_shared_entity(
        self,
        ev_a: Evidence,
        ev_b: Evidence,
        min_shared: int = 1,
    ) -> Optional[Relationship]:
        if ev_a.id == ev_b.id:
            return None
        a_entities = {ee.entity_id for ee in self.db.query(EvidenceEntity).filter(EvidenceEntity.evidence_id == ev_a.id).all()}
        b_entities = {ee.entity_id for ee in self.db.query(EvidenceEntity).filter(EvidenceEntity.evidence_id == ev_b.id).all()}
        shared = a_entities & b_entities
        if len(shared) < min_shared:
            return None

        confidence = min(0.95, 0.5 + 0.1 * len(shared))
        rel = Relationship(
            from_evidence_id=ev_a.id,
            to_evidence_id=ev_b.id,
            relationship_type="shares_entities_with",
            confidence=confidence,
            rel_metadata={"shared_entity_count": len(shared)},
        )
        self.db.add(rel)
        self.db.flush()
        return rel

    def link_explains(
        self,
        transcript_evidence: Evidence,
        visual_evidence: Evidence,
    ) -> Relationship:
        rel = Relationship(
            from_evidence_id=transcript_evidence.id,
            to_evidence_id=visual_evidence.id,
            relationship_type="explains",
            confidence=0.9,
            metadata={},
        )
        self.db.add(rel)
        reverse = Relationship(
            from_evidence_id=visual_evidence.id,
            to_evidence_id=transcript_evidence.id,
            relationship_type="is_explained_by",
            confidence=0.9,
            metadata={},
        )
        self.db.add(reverse)
        self.db.flush()
        return rel

    def link_explains_bulk(
        self,
        transcript_evs: list[Evidence],
        visual_evs: list[Evidence],
        max_gap: float = 8.0,
    ) -> None:
        if not transcript_evs or not visual_evs:
            return
            
        # Sort visuals by timestamp
        visual_evs = sorted([v for v in visual_evs if v.timestamp_start is not None], key=lambda x: x.timestamp_start)
        if not visual_evs:
            return
            
        new_rels = []
        for tev in transcript_evs:
            t_mid = ((tev.timestamp_start or 0) + (tev.timestamp_end or 0)) / 2.0
            
            # Binary search or scan could be used, but since visual_evs is usually < 1000 frames,
            # a simple window scan is fine if we early break
            for vev in visual_evs:
                v_mid = vev.timestamp_start
                if v_mid > t_mid + max_gap:
                    break # passed the window
                if v_mid >= t_mid - max_gap:
                    new_rels.append(Relationship(
                        from_evidence_id=tev.id,
                        to_evidence_id=vev.id,
                        relationship_type="explains",
                        confidence=0.9,
                        rel_metadata={},
                    ))
                    new_rels.append(Relationship(
                        from_evidence_id=vev.id,
                        to_evidence_id=tev.id,
                        relationship_type="is_explained_by",
                        confidence=0.9,
                        rel_metadata={},
                    ))
        if new_rels:
            self.db.bulk_save_objects(new_rels)
            self.db.flush()

    def link_same_source(self, evidence_list: list[Evidence], same_frame_max_gap: float = 2.0) -> None:
        sorted_by_time = sorted(
            [e for e in evidence_list if e.timestamp_start is not None],
            key=lambda e: e.timestamp_start or 0,
        )
        new_rels = []
        for i in range(len(sorted_by_time)):
            for j in range(i + 1, len(sorted_by_time)):
                a, b = sorted_by_time[i], sorted_by_time[j]
                gap = (b.timestamp_start or 0) - (a.timestamp_start or 0)
                if gap > same_frame_max_gap:
                    break
                
                confidence = max(0.5, 1.0 - (gap / same_frame_max_gap) * 0.5)
                new_rels.append(Relationship(
                    from_evidence_id=a.id,
                    to_evidence_id=b.id,
                    relationship_type="temporally_coincident_with",
                    confidence=confidence,
                    rel_metadata={"gap_seconds": gap},
                ))
                new_rels.append(Relationship(
                    from_evidence_id=b.id,
                    to_evidence_id=a.id,
                    relationship_type="temporally_coincident_with",
                    confidence=confidence,
                    rel_metadata={"gap_seconds": gap},
                ))
                
        if new_rels:
            self.db.bulk_save_objects(new_rels)
            self.db.flush()

    @staticmethod
    def _fmt_ts(seconds: Optional[float]) -> str:
        if seconds is None:
            return "00:00:00"
        total = int(seconds)
        h = total // 3600
        m = (total % 3600) // 60
        s = total % 60
        if h:
            return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"
