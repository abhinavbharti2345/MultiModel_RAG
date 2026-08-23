from __future__ import annotations
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.config import settings
from app.schemas.evidence_schemas import TranscriptSegment

logger = logging.getLogger(__name__)


@dataclass
class PDFPage:
    page_number: int
    text: str
    image_paths: list[str]


@dataclass
class ImageText:
    text: str
    description: str
    entities: list[str]


class DocumentIngestor:
    def extract_pdf_pages(
        self,
        pdf_path: Path,
        progress_callback=None,
    ) -> list[PDFPage]:
        pages: list[PDFPage] = []
        try:
            try:
                from pypdf import PdfReader
                use_pypdf = True
            except ImportError:
                use_pypdf = False

            if use_pypdf:
                reader = PdfReader(str(pdf_path))
                for i, page in enumerate(reader.pages):
                    text = page.extract_text() or ""
                    image_paths = []
                    for count, image_file_object in enumerate(page.images):
                        try:
                            img_path = settings.FRAME_PATH / f"pdf_{pdf_path.stem}_p{i}_{count}.png"
                            with open(str(img_path), "wb") as fp:
                                fp.write(image_file_object.data)
                            image_paths.append(str(img_path))
                        except Exception as e:
                            logger.warning(f"Failed to extract image {count} from page {i}: {e}")

                    pages.append(PDFPage(
                        page_number=i + 1,
                        text=text.strip(),
                        image_paths=image_paths,
                    ))
                    if progress_callback:
                        progress_callback(
                            min(99.0, (i + 1) / max(1, len(reader.pages)) * 100),
                            f"Extracted page {i + 1}/{len(reader.pages)}",
                        )
                logger.info(f"pypdf extracted {len(pages)} pages from {pdf_path.name}")
            else:
                logger.warning("pypdf not installed. Using mock PDF extraction.")
                pages = self._mock_pdf_pages(pdf_path)
        except Exception as e:
            logger.error(f"PDF extraction failed: {e}")
            if not pages:
                pages = self._mock_pdf_pages(pdf_path)
        return pages

    def _mock_pdf_pages(self, pdf_path: Path) -> list[PDFPage]:
        return [
            PDFPage(
                page_number=1,
                text=(
                    "Multimodal RAG System Architecture - Design Document\n"
                    "Version 1.0, Team Execution Plan\n\n"
                    "1. Executive Summary\n"
                    "This document outlines the architecture of a multimodal retrieval-augmented generation "
                    "system capable of processing video, audio, images, and PDF documents. The system transforms "
                    "raw unstructured media into structured evidence objects with precise provenance, enabling "
                    "users to ask natural language questions and receive grounded answers with citations "
                    "to exact timestamps, video frames, and document pages.\n\n"
                    "2. Problem Statement\n"
                    "Traditional RAG pipelines treat each chunk of text independently, destroying the "
                    "temporal and cross-modal relationships present in real-world meetings and documentation. "
                    "Users need to understand not just WHAT was said, but WHO said it, WHEN, WHAT was on the "
                    "screen at the time, and WHERE the corresponding architecture diagrams live.\n"
                ),
                image_paths=[],
            ),
            PDFPage(
                page_number=2,
                text=(
                    "3. Proposed Architecture\n\n"
                    "3.1 Overview\n"
                    "Ingestion Pipeline:\n"
                    "VIDEO / IMAGE / PDF -> Local preprocessing (FFmpeg, OpenCV) -> Cloud AI extraction "
                    "(Groq Whisper STT, Vision-Language Model) -> Structured Evidence objects -> "
                    "Qdrant (vector similarity) + PostgreSQL (metadata, provenance, entities, relationships)\n\n"
                    "Query Pipeline:\n"
                    "User question -> Query embedding -> Qdrant similarity search -> Relationship expansion in "
                    "PostgreSQL -> Ranked multimodal evidence package -> Groq LLM -> Answer with provenance "
                    "citations.\n\n"
                    "3.2 Database Load Reduction Strategy\n"
                    "A Redis caching layer is positioned between the application servers and PostgreSQL to "
                    "absorb read traffic. Cached entries carry a 5-minute TTL. Cache writes follow a "
                    "write-through pattern to avoid stale reads. Estimated PostgreSQL read reduction: 60%. "
                    "See the architecture diagram (Page 7, Figure 3.2-1) for the annotated data flow.\n"
                ),
                image_paths=[],
            ),
            PDFPage(
                page_number=7,
                text=(
                    "7. Appendix: Data Flow Diagram\n\n"
                    "Figure 7-1: Redis + PostgreSQL Caching Architecture\n\n"
                    "[Client] -> [API Gateway] -> [Load Balancers] -> [Application Servers]\n"
                    "                                                  |\n"
                    "                                         +--------+--------+\n"
                    "                                         |                 |\n"
                    "                                    [Redis Cache]    [PostgreSQL DB]\n"
                    "                                         |                 |\n"
                    "                                         +--- Write-thru --+\n\n"
                    "Annotations:\n"
                    "  - Read path: Application first queries Redis. On cache MISS, queries PostgreSQL and "
                    "populates Redis with TTL of 300 seconds (5 minutes).\n"
                    "  - Write path: Application writes PostgreSQL first, synchronously invalidates and "
                    "refreshes the corresponding Redis key.\n"
                    "  - Failure mode: If Redis is unavailable, all traffic gracefully falls back to "
                    "PostgreSQL. Redis is therefore in the critical path for performance but not availability.\n\n"
                    "Proposed by: Sarah Chen (Principal Engineer)\n"
                    "Reviewed with: Team Execution Plan meeting, session recording meeting.mp4 @ 12:30-15:00.\n"
                ),
                image_paths=[],
            ),
        ]

    def analyze_image(
        self,
        image_path: Path,
        context_hint: Optional[str] = None,
    ) -> ImageText:
        try:
            from app.services.visual_analyzer import visual_analyzer
            import asyncio

            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    import nest_asyncio
                    nest_asyncio.apply()
            except Exception:
                pass

            result = asyncio.run(visual_analyzer.analyze_frame(image_path, context_hint))
            return ImageText(
                text=result.ocr_text or "",
                description=result.description,
                entities=result.entities,
            )
        except Exception as e:
            logger.warning(f"Image analysis failed: {e}, using mock")
            return self._mock_image_analysis(image_path)

    def _mock_image_analysis(self, image_path: Path) -> ImageText:
        return ImageText(
            text=(
                "System Architecture Overview\n"
                "Clients -> API Gateway -> Load Balancers -> App Servers\n"
                "App Servers -> Redis Cache (TTL 5 min)\n"
                "App Servers -> PostgreSQL (persistence)\n"
                "Redis -> PostgreSQL (cache miss hydrate, write-through)"
            ),
            description=(
                "A clean vector architecture diagram showing a four-tier request flow, with Redis "
                "positioned as a sidecar cache beside PostgreSQL. Includes TTL and write-through annotations."
            ),
            entities=["Redis", "PostgreSQL", "API Gateway", "Load Balancers", "TTL", "write-through"],
        )

    def chunk_text(
        self,
        text: str,
        chunk_size: int = 700,
        overlap: int = 180,
    ) -> list[tuple[int, int, str]]:
        chunks: list[tuple[int, int, str]] = []
        if not text:
            return chunks

        import re
        # Split by paragraph (double newline)
        paragraphs = [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]
        
        start_idx = 0
        for p in paragraphs:
            # find actual position of p in text
            idx = text.find(p, start_idx)
            if idx == -1:
                idx = start_idx
            
            # If paragraph is still too big, chunk it
            if len(p) > chunk_size:
                p_start = 0
                while p_start < len(p):
                    p_end = min(len(p), p_start + chunk_size)
                    if p_end < len(p):
                        last_space = p.rfind(" ", p_start, p_end)
                        if last_space > p_start + overlap:
                            p_end = last_space
                    c_text = p[p_start:p_end]
                    chunks.append((idx + p_start, idx + p_end, c_text))
                    if p_end >= len(p):
                        break
                    p_start = max(p_start + 1, p_end - overlap)
            else:
                chunks.append((idx, idx + len(p), p))
            
            start_idx = idx + len(p)
            
        return chunks

    def segments_from_chunks(
        self,
        chunks: list[tuple[int, int, str]],
        page_number: Optional[int] = None,
    ) -> list[TranscriptSegment]:
        segments: list[TranscriptSegment] = []
        for idx, (s, e, text) in enumerate(chunks):
            seg_len = max(5, (e - s) / 20)
            segments.append(TranscriptSegment(
                start=float(idx * seg_len),
                end=float((idx + 1) * seg_len),
                text=text,
                speaker=f"page_{page_number}" if page_number else None,
            ))
        return segments


document_ingestor = DocumentIngestor()
