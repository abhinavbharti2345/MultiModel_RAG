from __future__ import annotations
import logging
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.models.db_models import (
    Source,
    Frame,
    Evidence,
    Entity,
    Relationship,
    EvidenceEntity,
    EvidenceFrame,
    ProcessingStatus,
    SourceType,
)
from app.schemas.evidence_schemas import (
    SourceCreate,
    SourceResponse,
    SourceUpdateStatus,
    EvidenceResponse,
)

logger = logging.getLogger(__name__)


class StorageService:
    def __init__(self, db: Session):
        self.db = db

    def create_source(self, source_in: SourceCreate) -> Source:
        source = Source(**source_in.model_dump())
        self.db.add(source)
        self.db.commit()
        self.db.refresh(source)
        return source

    def get_source(self, source_id: UUID) -> Optional[Source]:
        return self.db.query(Source).filter(Source.id == source_id).first()

    def list_sources(self, skip: int = 0, limit: int = 100, source_type: Optional[SourceType] = None) -> list[Source]:
        q = self.db.query(Source)
        if source_type:
            q = q.filter(Source.source_type == source_type)
        return q.order_by(Source.created_at.desc()).offset(skip).limit(limit).all()

    def update_source_status(
        self,
        source_id: UUID,
        status: ProcessingStatus,
        status_message: Optional[str] = None,
        progress_percent: Optional[float] = None,
    ) -> Optional[Source]:
        source = self.get_source(source_id)
        if not source:
            return None
        source.status = status
        if status_message is not None:
            source.status_message = status_message
        if progress_percent is not None:
            source.progress_percent = max(0.0, min(100.0, progress_percent))
        self.db.commit()
        self.db.refresh(source)
        return source

    def save_frame(self, frame: Frame) -> Frame:
        self.db.add(frame)
        self.db.commit()
        self.db.refresh(frame)
        return frame

    def save_frames_bulk(self, frames: list[Frame]) -> None:
        self.db.bulk_save_objects(frames)
        self.db.commit()

    def get_frames(self, source_id: UUID, only_important: bool = False) -> list[Frame]:
        q = self.db.query(Frame).filter(Frame.source_id == source_id)
        if only_important:
            q = q.filter(Frame.is_important == True)  # noqa: E712
        return q.order_by(Frame.timestamp_seconds.asc()).all()

    def get_frame_at_time(self, source_id: UUID, timestamp_seconds: float, tolerance: float = 5.0) -> Optional[Frame]:
        frame = (
            self.db.query(Frame)
            .filter(
                Frame.source_id == source_id,
                Frame.timestamp_seconds.between(
                    max(0.0, timestamp_seconds - tolerance),
                    timestamp_seconds + tolerance,
                ),
            )
            .order_by(Frame.timestamp_seconds.asc())
            .first()
        )
        if frame:
            return frame
        return (
            self.db.query(Frame)
            .filter(Frame.source_id == source_id)
            .order_by(Frame.timestamp_seconds.asc())
            .first()
        )

    def add_frames_to_source(self, source_id: UUID, frames: list[Frame]) -> None:
        for f in frames:
            f.source_id = source_id
        self.db.bulk_save_objects(frames)
        self.db.commit()

    def commit(self) -> None:
        self.db.commit()

    def flush(self) -> None:
        self.db.flush()

    def get_evidence(self, evidence_id: UUID) -> Optional[Evidence]:
        return self.db.query(Evidence).filter(Evidence.id == evidence_id).first()

    def get_evidence_for_source(self, source_id: UUID) -> list[Evidence]:
        return (
            self.db.query(Evidence)
            .filter(Evidence.source_id == source_id)
            .order_by(Evidence.timestamp_start.is_(None), Evidence.timestamp_start.asc())
            .all()
        )

    def get_related_evidence(self, evidence_id: UUID, max_hops: int = 1, min_confidence: float = 0.5) -> list[Evidence]:
        visited: set[UUID] = {evidence_id}
        frontier: set[UUID] = {evidence_id}
        for _ in range(max_hops):
            next_frontier: set[UUID] = set()
            for eid in frontier:
                rels = (
                    self.db.query(Relationship)
                    .filter(
                        Relationship.from_evidence_id == eid,
                        Relationship.confidence >= min_confidence,
                    )
                    .all()
                )
                for rel in rels:
                    if rel.to_evidence_id not in visited:
                        next_frontier.add(rel.to_evidence_id)
            visited |= next_frontier
            frontier = next_frontier
            if not frontier:
                break
        visited.discard(evidence_id)
        if not visited:
            return []
        return self.db.query(Evidence).filter(Evidence.id.in_(visited)).all()

    def get_frames_for_evidence(self, evidence_id: UUID) -> list[Frame]:
        return (
            self.db.query(Frame)
            .join(EvidenceFrame, EvidenceFrame.frame_id == Frame.id)
            .filter(EvidenceFrame.evidence_id == evidence_id)
            .all()
        )

    def get_entities_for_evidence(self, evidence_id: UUID) -> list[Entity]:
        return (
            self.db.query(Entity)
            .join(EvidenceEntity, EvidenceEntity.entity_id == Entity.id)
            .filter(EvidenceEntity.evidence_id == evidence_id)
            .all()
        )

    def update_evidence_qdrant_id(self, evidence_id: UUID, qdrant_point_id: UUID) -> None:
        ev = self.get_evidence(evidence_id)
        if ev:
            ev.qdrant_point_id = qdrant_point_id
            self.db.commit()

    def clear_all(self) -> None:
        self.db.query(Relationship).delete()
        self.db.query(EvidenceEntity).delete()
        self.db.query(EvidenceFrame).delete()
        self.db.query(Entity).delete()
        self.db.query(Evidence).delete()
        self.db.query(Frame).delete()
        self.db.query(Source).delete()
        self.db.commit()

    def delete_source(self, source_id: UUID) -> bool:
        source = self.get_source(source_id)
        if not source:
            return False
        # Delete related frames, evidence, etc. Cascade should handle it if set up, but let's do it manually for safety
        self.db.query(EvidenceFrame).filter(
            EvidenceFrame.evidence_id.in_(self.db.query(Evidence.id).filter(Evidence.source_id == source_id))
        ).delete(synchronize_session=False)
        self.db.query(EvidenceEntity).filter(
            EvidenceEntity.evidence_id.in_(self.db.query(Evidence.id).filter(Evidence.source_id == source_id))
        ).delete(synchronize_session=False)
        self.db.query(Relationship).filter(
            Relationship.from_evidence_id.in_(self.db.query(Evidence.id).filter(Evidence.source_id == source_id))
        ).delete(synchronize_session=False)
        self.db.query(Relationship).filter(
            Relationship.to_evidence_id.in_(self.db.query(Evidence.id).filter(Evidence.source_id == source_id))
        ).delete(synchronize_session=False)
        self.db.query(Evidence).filter(Evidence.source_id == source_id).delete(synchronize_session=False)
        self.db.query(Frame).filter(Frame.source_id == source_id).delete(synchronize_session=False)
        self.db.delete(source)
        self.db.commit()
        return True
