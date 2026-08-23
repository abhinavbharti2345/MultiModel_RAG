from __future__ import annotations
import logging
import mimetypes
import shutil
import threading
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.db_models import ProcessingStatus, SourceType
from app.schemas.evidence_schemas import (
    ProcessingJobResponse,
    SourceCreate,
    SourceResponse,
)
from app.services.ingestion_orchestrator import IngestionOrchestrator
from app.services.storage_service import StorageService

router = APIRouter(prefix="/api/upload", tags=["upload"])

logger = logging.getLogger(__name__)


def _detect_source_type(filename: str, content_type: Optional[str]) -> SourceType:
    name = filename.lower()
    ct = (content_type or "").lower()
    if name.endswith((".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v")) or "video" in ct:
        return SourceType.VIDEO
    if name.endswith((".pdf",)) or "pdf" in ct:
        return SourceType.PDF
    if name.endswith((".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff")) or "image" in ct:
        return SourceType.IMAGE
    if name.endswith((".mp3", ".wav", ".flac", ".aac", ".m4a")) or "audio" in ct:
        return SourceType.AUDIO
    raise HTTPException(status_code=400, detail=f"Unsupported file type: {filename} ({content_type})")


def _run_ingestion(db_factory, source_id: uuid.UUID, source_type: SourceType, file_path: Path) -> None:
    db = db_factory()
    try:
        orch = IngestionOrchestrator(db)
        if source_type == SourceType.VIDEO:
            orch.ingest_video(source_id, file_path)
        elif source_type == SourceType.PDF:
            orch.ingest_pdf(source_id, file_path)
        elif source_type == SourceType.IMAGE:
            orch.ingest_image(source_id, file_path)
        elif source_type == SourceType.AUDIO:
            orch.ingest_audio(source_id, file_path)
    except Exception as e:
        logger.exception(f"Ingestion failed for {source_id}: {e}")
        try:
            storage = StorageService(db)
            storage.update_source_status(
                source_id,
                ProcessingStatus.FAILED,
                status_message=str(e)[:500],
                progress_percent=100.0,
            )
        except Exception:
            pass
    finally:
        db.close()


@router.post("", response_model=ProcessingJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_file(
    file: UploadFile = File(...),
    description: Optional[str] = Form(default=None),
    db: Session = Depends(get_db),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="File has no filename")

    source_type = _detect_source_type(file.filename, file.content_type)

    source_id = uuid.uuid4()
    ext = Path(file.filename).suffix or ""
    stored_filename = f"{source_id}{ext}"
    dest_dir = settings.UPLOAD_PATH
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / stored_filename

    try:
        with open(dest_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {e}")
    finally:
        await file.close()

    file_size = dest_path.stat().st_size
    mime_type = file.content_type or mimetypes.guess_type(str(dest_path))[0]

    storage = StorageService(db)
    metadata = {"description": description} if description else {}
    source_in = SourceCreate(
        name=file.filename,
        source_type=source_type,
        file_path=str(dest_path),
        file_size=file_size,
        mime_type=mime_type,
        metadata=metadata,
    )
    source = storage.create_source(source_in)
    storage.update_source_status(
        source.id,
        status=ProcessingStatus.UPLOADED,
        status_message="File saved. Queued for processing.",
        progress_percent=1.0,
    )

    def db_factory():
        from app.database import SessionLocal
        return SessionLocal()

    thread = threading.Thread(
        target=_run_ingestion,
        args=(db_factory, source.id, source_type, dest_path),
        daemon=True,
    )
    thread.start()

    return ProcessingJobResponse(
        source_id=source.id,
        status=source.status,
        status_message=source.status_message,
        progress_percent=source.progress_percent,
    )


@router.post("/sync", response_model=SourceResponse, status_code=status.HTTP_201_CREATED)
async def upload_file_sync(
    file: UploadFile = File(...),
    description: Optional[str] = Form(default=None),
    db: Session = Depends(get_db),
):
    job = await upload_file(file=file, description=description, db=db)
    import time
    storage = StorageService(db)
    for _ in range(600):
        source = storage.get_source(job.source_id)
        if source and source.status in (ProcessingStatus.COMPLETED, ProcessingStatus.FAILED):
            return SourceResponse.model_validate(source)
        time.sleep(1)
    source = storage.get_source(job.source_id)
    return SourceResponse.model_validate(source)
