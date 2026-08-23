from __future__ import annotations
import mimetypes
from pathlib import Path
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.storage_service import StorageService

router = APIRouter(prefix="/api/assets", tags=["assets"])


@router.get("/frames/{frame_id}")
def get_frame_image(frame_id: UUID, db: Session = Depends(get_db)):
    from app.models.db_models import Frame
    frame = db.query(Frame).filter(Frame.id == frame_id).first()
    if frame is None:
        raise HTTPException(status_code=404, detail="Frame not found")
    path = Path(frame.frame_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Frame file missing")
    media_type = mimetypes.guess_type(str(path))[0] or "image/jpeg"
    return FileResponse(path, media_type=media_type, filename=path.name)


@router.get("/sources/{source_id}/original")
def get_source_original(source_id: UUID, db: Session = Depends(get_db)):
    storage = StorageService(db)
    source = storage.get_source(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    path = Path(source.file_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="File missing")
    media_type = source.mime_type or mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type, filename=source.name)


@router.get("/sources/{source_id}/frames")
def list_source_frames(
    source_id: UUID,
    only_important: bool = True,
    db: Session = Depends(get_db),
):
    storage = StorageService(db)
    source = storage.get_source(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    frames = storage.get_frames(source_id, only_important=only_important)
    out = []
    for f in frames:
        out.append({
            "frame_id": str(f.id),
            "timestamp_seconds": f.timestamp_seconds,
            "timestamp_formatted": _fmt_ts(f.timestamp_seconds),
            "frame_path": f.frame_path,
            "width": f.width,
            "height": f.height,
            "is_important": f.is_important,
            "scene_score": f.scene_score,
            "ocr_text": f.ocr_text,
            "visual_description": f.visual_description,
            "image_url": f"/api/assets/frames/{f.id}",
        })
    return JSONResponse(out)


def _fmt_ts(seconds: Optional[float]) -> str:
    if seconds is None:
        return "00:00:00"
    total = int(seconds)
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:02d}:{m:02d}:{s:02d}"
