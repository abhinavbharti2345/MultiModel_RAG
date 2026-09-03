from __future__ import annotations
import asyncio
import logging
from pathlib import Path
from typing import Callable, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.db_models import (
    Source,
    Frame,
    Evidence,
    ProcessingStatus,
    SourceType,
    ModalityType,
)
from app.config import settings
from app.services.video_processor import video_processor
from app.services.speech_to_text import stt_service
from app.services.visual_analyzer import visual_analyzer
from app.services.document_ingestor import document_ingestor
from app.services.evidence_builder import EvidenceBuilder
from app.services.storage_service import StorageService
from app.services.embedding_service import embedding_service
from app.services.qdrant_service import qdrant_service
from app.schemas.evidence_schemas import (
    SourceCreate,
    VisualAnalysisResult,
)

logger = logging.getLogger(__name__)


class IngestionOrchestrator:
    def __init__(self, db: Session, db_factory: Optional[Callable[[], Session]] = None):
        self.db = db
        self.db_factory = db_factory
        self.storage = StorageService(db)
        self.builder = EvidenceBuilder(db)

    def _yield_db(self):
        if self.db and self.db_factory:
            self.db.commit()
            self.db.close()
            self.db = None
            self.storage = None
            self.builder = None

    def _resume_db(self):
        if self.db is None and self.db_factory:
            self.db = self.db_factory()
            self.storage = StorageService(self.db)
            self.builder = EvidenceBuilder(self.db)

    def _make_progress_cb(self, source_id: UUID, base_pct: float, range_pct: float) -> Callable:
        def cb(pct: float, msg: str):
            scaled = base_pct + (pct / 100.0) * range_pct
            self.storage.update_source_status(
                source_id,
                status=self._source_status(source_id),
                status_message=msg,
                progress_percent=scaled,
            )
        return cb

    def _source_status(self, source_id: UUID) -> ProcessingStatus:
        src = self.storage.get_source(source_id)
        return src.status if src else ProcessingStatus.PROCESSING

    def ingest_video(self, source_id: UUID, video_path: Path) -> None:
        source = self.storage.get_source(source_id)
        if source is None:
            raise ValueError(f"Source {source_id} not found")

        self.storage.update_source_status(
            source_id,
            status=ProcessingStatus.PROCESSING,
            status_message="Starting video ingestion",
            progress_percent=2.0,
        )

        video_info = video_processor.get_video_info(video_path)
        if video_info:
            source.duration_seconds = video_info.get("duration_seconds")
            source.file_size = video_info.get("file_size")
            source.extra_metadata = {**(source.extra_metadata or {}), **video_info}
            self.db.commit()

        audio_path = settings.AUDIO_PATH / f"{source_id}.mp3"
        frame_dir = settings.FRAME_PATH / str(source_id)

        self.storage.update_source_status(
            source_id,
            status=ProcessingStatus.EXTRACTING_AUDIO,
            status_message="Extracting audio with FFmpeg",
            progress_percent=5.0,
        )
        try:
            video_processor.extract_audio(video_path, audio_path)
        except Exception as e:
            logger.error(f"Audio extraction failed: {e}")
            audio_path = None

        self.storage.update_source_status(
            source_id,
            status=ProcessingStatus.EXTRACTING_FRAMES,
            status_message="Sampling frames and detecting scene changes",
            progress_percent=15.0,
        )
        extracted_frames = video_processor.sample_frames(
            video_path,
            frame_dir,
            progress_callback=self._make_progress_cb(source_id, 15.0, 25.0),
        )

        frame_objs: list[Frame] = []
        for ef in extracted_frames:
            frame_objs.append(Frame(
                source_id=source_id,
                timestamp_seconds=ef.timestamp_seconds,
                frame_path=ef.frame_path,
                frame_number=ef.frame_number,
                width=ef.width,
                height=ef.height,
                is_important=ef.is_important,
                scene_score=ef.scene_score,
            ))
        self.storage.add_frames_to_source(source_id, frame_objs)
        frame_objs = self.storage.get_frames(source_id)

        self.storage.update_source_status(
            source_id,
            status=ProcessingStatus.TRANSCRIBING,
            status_message="Running Groq Whisper speech-to-text transcription",
            progress_percent=42.0,
        )
        transcript_segments = []
        if audio_path and audio_path.exists():
            try:
                self._yield_db()
                segments = asyncio.run(stt_service.transcribe_file(audio_path))
                self._resume_db()
                transcript_segments = segments
            except Exception as e:
                self._resume_db()
                logger.error(f"STT failed: {e}")
                self.storage.update_source_status(
                    source_id,
                    status=ProcessingStatus.TRANSCRIBING,
                    status_message=f"STT had issues: {e}, continuing without it",
                    progress_percent=48.0,
                )

        evidence_list: list[Evidence] = []

        self.storage.update_source_status(
            source_id,
            status=ProcessingStatus.BUILDING_EVIDENCE,
            status_message="Constructing transcript evidence",
            progress_percent=50.0,
        )
        for i, seg in enumerate(transcript_segments):
            nearby_frames = self._frames_near_time(
                source_id,
                (seg.start + seg.end) / 2.0,
                tolerance=settings.FRAME_SAMPLE_INTERVAL + 2.0,
            )
            nearby_frame_ids = [f.id for f in nearby_frames if f.is_important] or [f.id for f in nearby_frames[:1]]
            try:
                ev = self.builder.create_evidence_from_transcript(
                    source_id=source_id,
                    segment=seg,
                    frame_ids=nearby_frame_ids[:2],
                )
                evidence_list.append(ev)
            except Exception as e:
                logger.debug(f"Skipping transcript segment {i}: {e}")
        self.db.commit()

        important_frames = [f for f in frame_objs if f.is_important]
        if not important_frames:
            important_frames = frame_objs[: min(10, len(frame_objs))]

        self.storage.update_source_status(
            source_id,
            status=ProcessingStatus.ANALYZING_VISUALS,
            status_message=f"Analyzing {len(important_frames)} important frames with VLM",
            progress_percent=58.0,
        )
        frame_index = {f.id: f for f in frame_objs}
        async def _analyze_all(frames):
            sem = asyncio.Semaphore(5)
            async def _analyze_one(fr):
                ctx = self._transcript_context_at_time(transcript_segments, fr.timestamp_seconds)
                async with sem:
                    try:
                        return await visual_analyzer.analyze_frame(Path(fr.frame_path), ctx)
                    except Exception as e:
                        logger.error(f"VLM failed: {e}")
                        return None
            return await asyncio.gather(*[_analyze_one(f) for f in frames])

        self._yield_db()
        analysis_results = asyncio.run(_analyze_all(important_frames))
        self._resume_db()

        analyzed_count = 0
        for frame, analysis in zip(important_frames, analysis_results):
            if not analysis:
                continue
            try:
                frame = self.db.merge(frame)
                frame.ocr_text = analysis.ocr_text
                frame.visual_description = analysis.description
                self.db.commit()

                try:
                    vis_ev = self.builder.create_evidence_from_visual(
                        source_id=source_id,
                        frame_id=frame.id,
                        analysis=analysis,
                        timestamp_seconds=frame.timestamp_seconds,
                    )
                    evidence_list.append(vis_ev)
                except Exception as e:
                    logger.debug(f"Visual evidence creation failed: {e}")

                if analysis.ocr_text and analysis.ocr_text.strip():
                    try:
                        self.builder.create_evidence_from_ocr(
                            source_id=source_id,
                            frame_id=frame.id,
                            ocr_text=analysis.ocr_text,
                            timestamp_seconds=frame.timestamp_seconds,
                        )
                    except Exception as e:
                        logger.debug(f"OCR evidence creation failed: {e}")
                
                analyzed_count += 1
                pct = 58.0 + (analyzed_count / max(1, len(important_frames))) * 22.0
                self.storage.update_source_status(
                    source_id,
                    status=ProcessingStatus.ANALYZING_VISUALS,
                    status_message=f"VLM progress: {analyzed_count}/{len(important_frames)} frames",
                    progress_percent=min(80.0, pct),
                )
            except Exception as e:
                logger.error(f"Frame DB update failed for {frame.id}: {e}")

        self.db.commit()

        self.storage.update_source_status(
            source_id,
            status=ProcessingStatus.BUILDING_EVIDENCE,
            status_message="Building cross-modal relationships (temporal + shared entities)",
            progress_percent=82.0,
        )
        evidence_list = self.storage.get_evidence_for_source(source_id)
        self.builder.link_same_source(evidence_list, same_frame_max_gap=5.0)

        self.builder.link_shared_entities_bulk(evidence_list, min_shared=1)

        transcript_evs = [e for e in evidence_list if e.modality == ModalityType.AUDIO]
        visual_evs = [e for e in evidence_list if e.modality == ModalityType.VISUAL]
        self.builder.link_explains_bulk(transcript_evs, visual_evs, max_gap=8.0)
        
        self.db.commit()

        self.storage.update_source_status(
            source_id,
            status=ProcessingStatus.EMBEDDING,
            status_message="Generating embeddings and indexing into Qdrant",
            progress_percent=88.0,
        )
        self._embed_and_index_evidence(source_id)

        self.storage.update_source_status(
            source_id,
            status=ProcessingStatus.COMPLETED,
            status_message=f"Done: {len(evidence_list)} evidence records indexed",
            progress_percent=100.0,
        )
        logger.info(f"Video ingestion complete for {source_id}: {len(evidence_list)} evidence records")

    def ingest_audio(self, source_id: UUID, audio_path: Path) -> None:
        source = self.storage.get_source(source_id)
        if source is None:
            raise ValueError(f"Source {source_id} not found")

        self.storage.update_source_status(
            source_id,
            status=ProcessingStatus.PROCESSING,
            status_message="Starting standalone audio ingestion",
            progress_percent=5.0,
        )

        try:
            import subprocess
            result = subprocess.run(
                [settings.FFMPEG_PATH, "-i", str(audio_path), "-v", "error",
                 "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1"],
                capture_output=True, text=True, timeout=60,
            )
            duration = float(result.stdout.strip() or 0) or None
        except Exception:
            duration = None
        if duration:
            source.duration_seconds = duration
            self.db.commit()

        self.storage.update_source_status(
            source_id,
            status=ProcessingStatus.TRANSCRIBING,
            status_message="Transcribing standalone audio with Whisper",
            progress_percent=20.0,
        )
        try:
            self._yield_db()
            segments = asyncio.run(stt_service.transcribe_file(audio_path))
            self._resume_db()
            transcript_segments = segments
        except Exception as e:
            self._resume_db()
            logger.error(f"STT failed for standalone audio: {e}")
            transcript_segments = []

        self.storage.update_source_status(
            source_id,
            status=ProcessingStatus.BUILDING_EVIDENCE,
            status_message=f"Building evidence from {len(transcript_segments)} transcript segments",
            progress_percent=55.0,
        )
        for seg in transcript_segments:
            try:
                self.builder.create_evidence_from_transcript(source_id, seg, frame_ids=[])
            except Exception as e:
                logger.debug(f"Skipping segment: {e}")
        self.db.commit()

        evidence_list = self.storage.get_evidence_for_source(source_id)
        self.storage.update_source_status(
            source_id,
            status=ProcessingStatus.BUILDING_EVIDENCE,
            status_message="Linking temporal relationships within audio",
            progress_percent=70.0,
        )
        self.builder.link_same_source(evidence_list, same_frame_max_gap=5.0)
        self.db.commit()

        self.storage.update_source_status(
            source_id,
            status=ProcessingStatus.EMBEDDING,
            status_message="Generating embeddings and indexing into Qdrant",
            progress_percent=85.0,
        )
        self._embed_and_index_evidence(source_id)

        self.storage.update_source_status(
            source_id,
            status=ProcessingStatus.COMPLETED,
            status_message=f"Audio ingestion complete: {len(evidence_list)} evidence records",
            progress_percent=100.0,
        )

    def ingest_pdf(self, source_id: UUID, pdf_path: Path) -> None:
        self.storage.update_source_status(
            source_id,
            status=ProcessingStatus.PROCESSING,
            status_message="Starting PDF ingestion",
            progress_percent=5.0,
        )
        pages = document_ingestor.extract_pdf_pages(
            pdf_path,
            progress_callback=self._make_progress_cb(source_id, 5.0, 30.0),
        )
        src = self.storage.get_source(source_id)
        if src:
            src.page_count = len(pages)
            self.db.commit()

        self.storage.update_source_status(
            source_id,
            status=ProcessingStatus.BUILDING_EVIDENCE,
            status_message="Constructing evidence from PDF pages/chunks",
            progress_percent=40.0,
        )
        for page in pages:
            chunks = document_ingestor.chunk_text(page.text, chunk_size=700, overlap=180)
            for start, end, chunk_text in chunks:
                try:
                    self.builder.create_evidence_from_text(
                        source_id=source_id,
                        text=chunk_text,
                        page_number=page.page_number,
                        start_offset=start,
                        end_offset=end,
                    )
                except Exception:
                    pass
            
            # Process extracted images
            for img_path_str in page.image_paths:
                try:
                    img_path = Path(img_path_str)
                    from PIL import Image
                    with Image.open(img_path) as im:
                        w, h = im.size
                    frame_obj = Frame(
                        source_id=source_id,
                        timestamp_seconds=None,
                        frame_path=str(img_path),
                        frame_number=page.page_number,
                        width=w,
                        height=h,
                        is_important=True,
                        scene_score=0.0,
                    )
                    self.storage.save_frame(frame_obj)
                    
                    self._yield_db()
                    analysis_raw = document_ingestor.analyze_image(img_path)
                    self._resume_db()
                    
                    frame_obj = self.db.merge(frame_obj)
                    analysis = VisualAnalysisResult(
                        description=analysis_raw.description,
                        ocr_text=analysis_raw.text or None,
                        entities=analysis_raw.entities,
                        objects_detected=[],
                    )
                    frame_obj.ocr_text = analysis.ocr_text
                    frame_obj.visual_description = analysis.description
                    self.db.commit()

                    self.builder.create_evidence_from_visual(
                        source_id=source_id,
                        frame_id=frame_obj.id,
                        analysis=analysis,
                        timestamp_seconds=None,
                        page_number=page.page_number,
                    )
                except Exception as e:
                    logger.warning(f"Failed to process PDF image {img_path_str}: {e}")

        self.db.commit()

        self.storage.update_source_status(
            source_id,
            status=ProcessingStatus.EMBEDDING,
            status_message="Generating embeddings and indexing",
            progress_percent=85.0,
        )
        self._embed_and_index_evidence(source_id)

        self.storage.update_source_status(
            source_id,
            status=ProcessingStatus.COMPLETED,
            status_message="PDF ingestion complete",
            progress_percent=100.0,
        )

    def ingest_image(self, source_id: UUID, image_path: Path) -> None:
        self.storage.update_source_status(
            source_id,
            status=ProcessingStatus.EXTRACTING_FRAMES,
            status_message="Processing image",
            progress_percent=20.0,
        )
        from PIL import Image
        try:
            with Image.open(image_path) as im:
                w, h = im.size
        except Exception:
            w, h = 0, 0
        frame_obj = Frame(
            source_id=source_id,
            timestamp_seconds=None,
            frame_path=str(image_path),
            frame_number=0,
            width=w,
            height=h,
            is_important=True,
            scene_score=0.0,
        )
        self.storage.save_frame(frame_obj)

        self.storage.update_source_status(
            source_id,
            status=ProcessingStatus.ANALYZING_VISUALS,
            status_message="Running VLM analysis on image",
            progress_percent=45.0,
        )
        self._yield_db()
        analysis_raw = document_ingestor.analyze_image(image_path)
        self._resume_db()
        
        frame_obj = self.db.merge(frame_obj)
        analysis = VisualAnalysisResult(
            description=analysis_raw.description,
            ocr_text=analysis_raw.text or None,
            entities=analysis_raw.entities,
            objects_detected=[],
        )
        frame_obj.ocr_text = analysis.ocr_text
        frame_obj.visual_description = analysis.description
        self.db.commit()

        self.storage.update_source_status(
            source_id,
            status=ProcessingStatus.BUILDING_EVIDENCE,
            status_message="Creating visual/OCR evidence",
            progress_percent=70.0,
        )
        self.builder.create_evidence_from_visual(
            source_id=source_id,
            frame_id=frame_obj.id,
            analysis=analysis,
            timestamp_seconds=None,
        )
        if analysis.ocr_text and analysis.ocr_text.strip():
            try:
                self.builder.create_evidence_from_ocr(
                    source_id=source_id,
                    frame_id=frame_obj.id,
                    ocr_text=analysis.ocr_text,
                )
            except Exception:
                pass
        self.db.commit()

        self.storage.update_source_status(
            source_id,
            status=ProcessingStatus.EMBEDDING,
            status_message="Generating embeddings and indexing",
            progress_percent=90.0,
        )
        self._embed_and_index_evidence(source_id)

        self.storage.update_source_status(
            source_id,
            status=ProcessingStatus.COMPLETED,
            status_message="Image ingestion complete",
            progress_percent=100.0,
        )

    def _embed_and_index_evidence(self, source_id: UUID) -> None:
        evidence_list = self.storage.get_evidence_for_source(source_id)
        if not evidence_list:
            return

        source = self.storage.get_source(source_id)
        source_name = source.name if source else "unknown"

        contents = []
        for ev in evidence_list:
            header_parts = []
            if ev.modality:
                header_parts.append(f"[{ev.modality}]")
            if ev.timestamp_start is not None:
                header_parts.append(f"timestamp={self._fmt_ts(ev.timestamp_start)}")
            if ev.page_number:
                header_parts.append(f"page={ev.page_number}")
            header = " ".join(header_parts)
            contents.append(f"{header}\n{ev.content}")

        vectors = embedding_service.embed_texts(contents)

        qdrant_items = []
        for ev, vec in zip(evidence_list, vectors):
            payload = {
                "source_id": str(source_id),
                "source_name": source_name,
                "modality": ev.modality.value if hasattr(ev.modality, "value") else str(ev.modality),
                "timestamp": ev.timestamp_start or 0.0,
                "page": ev.page_number or 0,
                "speaker": ev.speaker or "",
                "confidence": ev.confidence or 1.0,
            }
            qdrant_items.append((ev.id, ev.content, vec, payload))

        point_ids = qdrant_service.upsert_many(qdrant_items)
        for ev, pid in zip(evidence_list, point_ids):
            try:
                self.storage.update_evidence_qdrant_id(ev.id, pid)
            except Exception:
                pass

    def _frames_near_time(self, source_id: UUID, t: float, tolerance: float = 5.0) -> list[Frame]:
        return [f for f in self.storage.get_frames(source_id)
                if abs((f.timestamp_seconds or 0) - t) <= tolerance]

    @staticmethod
    def _transcript_context_at_time(segments, t: float, window: float = 15.0) -> str:
        bits = []
        for s in segments:
            mid = (s.start + s.end) / 2.0
            if abs(mid - t) <= window:
                bits.append(s.text)
        return " ".join(bits)[:400]

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
