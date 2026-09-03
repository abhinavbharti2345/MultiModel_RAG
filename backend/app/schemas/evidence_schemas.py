from __future__ import annotations
from datetime import datetime
from typing import Optional, Any
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.db_models import SourceType, ModalityType, ProcessingStatus


class Provenance(BaseModel):
    model_config = ConfigDict(extra="allow")

    source: Optional[str] = None
    timestamp: Optional[str] = None
    page: Optional[int] = None
    frame_id: Optional[UUID] = None


class EvidenceBase(BaseModel):
    content: str
    modality: ModalityType
    timestamp_start: Optional[float] = None
    timestamp_end: Optional[float] = None
    page_number: Optional[int] = None
    speaker: Optional[str] = None
    confidence: float = 1.0
    entities: list[str] = Field(default_factory=list)
    relationships: list[dict[str, Any]] = Field(default_factory=list)
    provenance: Optional[Provenance] = None

    @field_validator("entities", mode="before")
    @classmethod
    def _entities_to_names(cls, v):
        if isinstance(v, list):
            return [e.name if hasattr(e, "name") else str(e) for e in v]
        return v


class EvidenceCreate(EvidenceBase):
    source_id: UUID
    frame_ids: list[UUID] = Field(default_factory=list)


class EvidenceResponse(EvidenceBase):
    id: UUID
    source_id: UUID
    qdrant_point_id: Optional[UUID] = None
    created_at: datetime

    class Config:
        from_attributes = True


class SourceBase(BaseModel):
    name: str
    source_type: SourceType
    file_path: str
    file_size: Optional[int] = None
    mime_type: Optional[str] = None
    duration_seconds: Optional[float] = None
    page_count: Optional[int] = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="extra_metadata")


class SourceCreate(SourceBase):
    pass


class SourceResponse(SourceBase):
    id: UUID
    status: ProcessingStatus
    status_message: Optional[str] = None
    progress_percent: float = 0.0
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SourceUpdateStatus(BaseModel):
    status: ProcessingStatus
    status_message: Optional[str] = None
    progress_percent: Optional[float] = None


class TranscriptSegment(BaseModel):
    start: float
    end: float
    text: str
    speaker: Optional[str] = None


class VisualAnalysisResult(BaseModel):
    description: str
    ocr_text: Optional[str] = None
    entities: list[str] = Field(default_factory=list)
    objects_detected: list[str] = Field(default_factory=list)
    relationships: list[str] = Field(default_factory=list)
    diagram_info: Optional[str] = None


class QueryRequest(BaseModel):
    query: str
    top_k: int = 10
    expand_relationships: bool = True
    include_multimodal: bool = True


class EvidenceWithScore(BaseModel):
    evidence: EvidenceResponse
    similarity_score: float
    related_evidence: list[EvidenceResponse] = Field(default_factory=list)
    related_frames: list[dict[str, Any]] = Field(default_factory=list)


class QueryResponse(BaseModel):
    answer: str
    provenance_summary: list[str]
    evidence: list[EvidenceWithScore]


class ProcessingJobResponse(BaseModel):
    source_id: UUID
    status: ProcessingStatus
    status_message: Optional[str]
    progress_percent: float
    estimated_remaining_seconds: Optional[float] = None
