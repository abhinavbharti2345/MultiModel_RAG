from __future__ import annotations
import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.db_models import SourceType
from app.schemas.evidence_schemas import (
    ProcessingJobResponse,
    SourceResponse,
    SourceUpdateStatus,
)
from app.services.storage_service import StorageService

router = APIRouter(prefix="/api/sources", tags=["sources"])

logger = logging.getLogger(__name__)


@router.delete("/clear-all")
def clear_all_sources(db: Session = Depends(get_db)):
    storage = StorageService(db)
    storage.clear_all()
    # Note: Does not delete actual files in this basic implementation
    return {"message": "All sources cleared"}

@router.get("", response_model=list[SourceResponse])
def list_sources(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    source_type: Optional[SourceType] = Query(None),
    db: Session = Depends(get_db),
):
    storage = StorageService(db)
    sources = storage.list_sources(skip=skip, limit=limit, source_type=source_type)
    return [SourceResponse.model_validate(s) for s in sources]


@router.get("/{source_id}", response_model=SourceResponse)
def get_source(source_id: UUID, db: Session = Depends(get_db)):
    storage = StorageService(db)
    source = storage.get_source(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return SourceResponse.model_validate(source)

@router.delete("/{source_id}")
def delete_source(source_id: UUID, db: Session = Depends(get_db)):
    storage = StorageService(db)
    success = storage.delete_source(source_id)
    if not success:
        raise HTTPException(status_code=404, detail="Source not found")
    return {"message": "Source deleted"}


@router.get("/{source_id}/status", response_model=ProcessingJobResponse)
def get_source_status(source_id: UUID, db: Session = Depends(get_db)):
    storage = StorageService(db)
    source = storage.get_source(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return ProcessingJobResponse(
        source_id=source.id,
        status=source.status,
        status_message=source.status_message,
        progress_percent=source.progress_percent,
    )


@router.patch("/{source_id}/status", response_model=SourceResponse)
def update_source_status(
    source_id: UUID,
    update: SourceUpdateStatus,
    db: Session = Depends(get_db),
):
    storage = StorageService(db)
    source = storage.update_source_status(
        source_id,
        status=update.status,
        status_message=update.status_message,
        progress_percent=update.progress_percent,
    )
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return SourceResponse.model_validate(source)


@router.get("/{source_id}/evidence-summary")
def get_evidence_summary(source_id: UUID, db: Session = Depends(get_db)):
    storage = StorageService(db)
    source = storage.get_source(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    evidences = storage.get_evidence_for_source(source_id)
    by_modality: dict[str, int] = {}
    for ev in evidences:
        key = ev.modality.value if hasattr(ev.modality, "value") else str(ev.modality)
        by_modality[key] = by_modality.get(key, 0) + 1
    frames = storage.get_frames(source_id)
    return {
        "source_id": str(source_id),
        "name": source.name,
        "status": source.status,
        "total_evidence": len(evidences),
        "evidence_by_modality": by_modality,
        "frames_total": len(frames),
        "frames_important": sum(1 for f in frames if f.is_important),
    }
