from datetime import datetime
from enum import Enum as PyEnum
from uuid import UUID as UUID_TYPE, uuid4
from sqlalchemy import (
    Column,
    String,
    Integer,
    Float,
    DateTime,
    ForeignKey,
    Text,
    Enum,
    JSON,
    Boolean,
    TypeDecorator,
    CHAR,
)
from sqlalchemy.orm import relationship

from app.database import Base, db_url


class GUID(TypeDecorator):
    impl = CHAR(32)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        if isinstance(value, UUID_TYPE):
            return value.hex
        if isinstance(value, str):
            return value.replace("-", "")
        return str(value).replace("-", "")

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        if len(value) == 32:
            return UUID_TYPE(hex=value)
        return UUID_TYPE(value)


USE_PG_UUID = db_url.startswith("postgresql")

if USE_PG_UUID:
    from sqlalchemy.dialects.postgresql import UUID as PG_UUID
    _UUID_TYPE = PG_UUID(as_uuid=True)
else:
    _UUID_TYPE = GUID


def _uuid_pk():
    return Column(_UUID_TYPE, primary_key=True, default=uuid4)


def _uuid_fk(col, nullable=True, **kw):
    return Column(_UUID_TYPE, ForeignKey(col, ondelete="CASCADE"), nullable=nullable, **kw)


class SourceType(str, PyEnum):
    VIDEO = "video"
    IMAGE = "image"
    PDF = "pdf"
    AUDIO = "audio"


class ModalityType(str, PyEnum):
    AUDIO = "audio"
    VISUAL = "visual"
    TEXT = "text"
    OCR = "ocr"
    MULTIMODAL = "multimodal"


class ProcessingStatus(str, PyEnum):
    PENDING = "pending"
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    EXTRACTING_AUDIO = "extracting_audio"
    EXTRACTING_FRAMES = "extracting_frames"
    TRANSCRIBING = "transcribing"
    ANALYZING_VISUALS = "analyzing_visuals"
    EXTRACTING_OCR = "extracting_ocr"
    BUILDING_EVIDENCE = "building_evidence"
    EMBEDDING = "embedding"
    COMPLETED = "completed"
    FAILED = "failed"


class Source(Base):
    __tablename__ = "sources"

    id = _uuid_pk()
    name = Column(String(512), nullable=False)
    source_type = Column(Enum(SourceType), nullable=False)
    file_path = Column(Text, nullable=False)
    file_size = Column(Integer)
    mime_type = Column(String(256))
    duration_seconds = Column(Float)
    page_count = Column(Integer)
    status = Column(Enum(ProcessingStatus), default=ProcessingStatus.PENDING, nullable=False)
    status_message = Column(Text)
    progress_percent = Column(Float, default=0.0)
    extra_metadata = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    evidence_records = relationship("Evidence", back_populates="source", cascade="all, delete-orphan")
    frames = relationship("Frame", back_populates="source", cascade="all, delete-orphan")


class Frame(Base):
    __tablename__ = "frames"

    id = _uuid_pk()
    source_id = _uuid_fk("sources.id", nullable=False)
    timestamp_seconds = Column(Float, nullable=False)
    frame_path = Column(Text, nullable=False)
    frame_number = Column(Integer)
    width = Column(Integer)
    height = Column(Integer)
    is_important = Column(Boolean, default=False)
    scene_score = Column(Float)
    ocr_text = Column(Text)
    visual_description = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    source = relationship("Source", back_populates="frames")
    evidence_records = relationship("Evidence", secondary="evidence_frames", back_populates="frames")


class Evidence(Base):
    __tablename__ = "evidence"

    id = _uuid_pk()
    source_id = _uuid_fk("sources.id", nullable=False)
    content = Column(Text, nullable=False)
    modality = Column(Enum(ModalityType), nullable=False)
    timestamp_start = Column(Float)
    timestamp_end = Column(Float)
    page_number = Column(Integer)
    speaker = Column(String(256))
    confidence = Column(Float, default=1.0)
    qdrant_point_id = Column(_UUID_TYPE)
    provenance = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    source = relationship("Source", back_populates="evidence_records")
    frames = relationship("Frame", secondary="evidence_frames", back_populates="evidence_records")
    entities = relationship("Entity", secondary="evidence_entities", back_populates="evidence_records")
    outgoing_relationships = relationship(
        "Relationship",
        foreign_keys="Relationship.from_evidence_id",
        back_populates="from_evidence",
        cascade="all, delete-orphan",
    )
    incoming_relationships = relationship(
        "Relationship",
        foreign_keys="Relationship.to_evidence_id",
        back_populates="to_evidence",
        cascade="all, delete-orphan",
    )


class Entity(Base):
    __tablename__ = "entities"

    id = _uuid_pk()
    name = Column(String(512), nullable=False)
    entity_type = Column(String(256))
    description = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    evidence_records = relationship("Evidence", secondary="evidence_entities", back_populates="entities")


class EvidenceEntity(Base):
    __tablename__ = "evidence_entities"

    evidence_id = Column(_UUID_TYPE, ForeignKey("evidence.id", ondelete="CASCADE"), primary_key=True)
    entity_id = Column(_UUID_TYPE, ForeignKey("entities.id", ondelete="CASCADE"), primary_key=True)


class EvidenceFrame(Base):
    __tablename__ = "evidence_frames"

    evidence_id = Column(_UUID_TYPE, ForeignKey("evidence.id", ondelete="CASCADE"), primary_key=True)
    frame_id = Column(_UUID_TYPE, ForeignKey("frames.id", ondelete="CASCADE"), primary_key=True)


class Relationship(Base):
    __tablename__ = "relationships"

    id = _uuid_pk()
    from_evidence_id = Column(_UUID_TYPE, ForeignKey("evidence.id", ondelete="CASCADE"), nullable=False)
    to_evidence_id = Column(_UUID_TYPE, ForeignKey("evidence.id", ondelete="CASCADE"), nullable=False)
    relationship_type = Column(String(128), nullable=False)
    confidence = Column(Float, default=1.0)
    rel_metadata = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    from_evidence = relationship("Evidence", foreign_keys=[from_evidence_id], back_populates="outgoing_relationships")
    to_evidence = relationship("Evidence", foreign_keys=[to_evidence_id], back_populates="incoming_relationships")
