import asyncio
import logging
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

logging.basicConfig(level=logging.INFO, format="%(levelname).1s %(name)s: %(message)s")
logger = logging.getLogger("smoke-test")

from app.config import settings

print(f"[*] Database URL: {settings.DATABASE_URL}")
print(f"[*] Storage: {settings.STORAGE_PATH.resolve()}")
print(f"[*] Groq configured: {bool(settings.GROQ_API_KEY)}")
print(f"[*] VLM configured: {bool(settings.VLM_API_URL and settings.VLM_API_KEY)}")
print()

from app.database import init_db, SessionLocal

print("[*] Initializing database tables…")
init_db()

from app.models.db_models import Source, SourceType, ProcessingStatus, ModalityType
from app.services.storage_service import StorageService
from app.services.evidence_builder import EvidenceBuilder
from app.services.embedding_service import embedding_service
from app.services.qdrant_service import qdrant_service
from app.services.retrieval_service import RetrievalService
from app.services.llm_service import llm_service
from app.schemas.evidence_schemas import (
    SourceCreate,
    TranscriptSegment,
    VisualAnalysisResult,
)

db = SessionLocal()
storage = StorageService(db)
builder = EvidenceBuilder(db)

print("[*] Creating test source: architecture_design.pdf…")
pdf_source = storage.create_source(SourceCreate(
    name="architecture_design_document.pdf",
    source_type=SourceType.PDF,
    file_path="./storage/uploads/mock_architecture.pdf",
    page_count=7,
    metadata={"mock": True, "app": "hackathon-spec"},
))
storage.update_source_status(pdf_source.id, ProcessingStatus.PROCESSING, "Mock PDF ingestion", 50)

print("[*] Creating test source: meeting_recording.mp4…")
video_source = storage.create_source(SourceCreate(
    name="team_architecture_meeting.mp4",
    source_type=SourceType.VIDEO,
    file_path="./storage/uploads/mock_meeting.mp4",
    duration_seconds=60 * 12 + 30,
    mime_type="video/mp4",
    metadata={"mock": True, "speakers": ["Sarah Chen", "Alex P"]},
))
storage.update_source_status(video_source.id, ProcessingStatus.EXTRACTING_FRAMES, "Extracted 152 frames, 28 important", 30)

print("[*] Creating transcript evidence from the meeting (Speaker 1 = Sarah Chen, Principal Engineer)…")
transcript_events = [
    (60, 100, "Welcome everyone. Today's architecture review will focus on database load during peak hours.", "Sarah Chen"),
    (100, 140, "I propose we introduce a Redis caching layer positioned in front of PostgreSQL.", "Sarah Chen"),
    (140, 180, "The idea is to cache frequent queries and reduce read pressure on the database. Sarah will walk us through the diagram next.", "Alex P"),
    (180, 220, "As you can see here on the slide, requests first hit the API gateway, then load balancers, then application servers which check the Redis cache.", "Sarah Chen"),
    (220, 260, "Cache misses fall through to PostgreSQL, and we write the results back to Redis with a TTL.", "Sarah Chen"),
    (260, 310, "For write operations we use a write-through pattern to keep cache consistent. TTL for most entries is five minutes.", "Sarah Chen"),
    (310, 360, "Expected database read reduction is about sixty percent with these parameters.", "Sarah Chen"),
    (560, 600, "Thanks everyone. Action items will be in the shared document by end of day. Sarah is publishing appendix page 7 with the diagram.", "Alex P"),
]
video_frame = Source.__table__  # placeholder
for start, end, text, speaker in transcript_events:
    seg = TranscriptSegment(start=float(start), end=float(end), text=text, speaker=speaker)
    builder.create_evidence_from_transcript(video_source.id, seg, frame_ids=[], base_confidence=0.96)
db.commit()

print("[*] Creating PDF text evidence — including appendix Page 7 with the Redis + PostgreSQL diagram…")
pdf_pages = {
    1: "Executive Summary: This document describes our multimodal RAG design and the Redis caching strategy for database load reduction.",
    2: "Architecture: Ingestion pipeline VIDEO / IMAGE / PDF -> Local preprocessing -> Cloud AI extraction -> Structured Evidence -> Qdrant + PostgreSQL. Section 3.2: A Redis caching layer sits between application servers and PostgreSQL to absorb read traffic. Write-through, TTL 5 min. Estimated 60% read reduction. See Figure 7-1 on page 7.",
    7: (
        "Appendix: Data Flow Diagram - Figure 7-1: Redis + PostgreSQL Caching Architecture.\n"
        "[Client] -> [API Gateway] -> [Load Balancers] -> [Application Servers]\n"
        "  Application Servers -> [Redis Cache] TTL 5 min (read path: on miss, hydrate from PostgreSQL)\n"
        "  Application Servers -> [PostgreSQL] -> on write: synchronously invalidate + refresh Redis key (write-through)\n"
        "Annotations: QPS target 10k, SLA 99.9%, P95 < 200ms.\n"
        "Proposed by: Sarah Chen (Principal Engineer)\n"
        "Discussed in: team_architecture_meeting.mp4 timestamp 02:00 through 05:10."
    ),
}
for page_num, text in pdf_pages.items():
    for s, e, chunk in [(0, len(text), text)]:
        builder.create_evidence_from_text(
            pdf_source.id, chunk, page_number=page_num,
            start_offset=s, end_offset=e, base_confidence=0.99
        )
db.commit()

print("[*] Creating visual evidence (frame showing the architecture diagram projected on screen @ 03:30)…")
from app.models.db_models import Frame
frame_obj = Frame(
    source_id=video_source.id,
    timestamp_seconds=210.0,
    frame_path=str(settings.FRAME_PATH / "demo_diagram_placeholder.jpg"),
    frame_number=12600,
    width=1280, height=720,
    is_important=True, scene_score=48.1,
)
db.add(frame_obj)
db.flush()

va = VisualAnalysisResult(
    description="A presentation slide projected during the meeting showing the 2-tier Redis + PostgreSQL caching data flow. Boxes: API Gateway, Load Balancers, Application Servers, Redis Cache (labeled TTL 5min), PostgreSQL. Arrows indicate read path: App->Redis->Postgres (on miss), and write path: App->Postgres->Redis invalidate+refresh.",
    ocr_text="Data Layer Caching Strategy\nRedis TTL: 300 seconds (5 min)\nRead reduction target: 60%\nSarah Chen · Architecture Review",
    entities=["Redis", "PostgreSQL", "API Gateway", "Load Balancers", "TTL"],
    objects_detected=["presentation slide", "architecture diagram", "boxes", "arrows"],
)
builder.create_evidence_from_visual(video_source.id, frame_obj.id, va, timestamp_seconds=210.0)
builder.create_evidence_from_ocr(video_source.id, frame_obj.id, va.ocr_text, timestamp_seconds=210.0)
db.commit()

print("[*] Creating cross-modal relationships: transcript -> explains visual, shared entity links…")
from app.models.db_models import Evidence
all_video_ev = storage.get_evidence_for_source(video_source.id)
all_pdf_ev = storage.get_evidence_for_source(pdf_source.id)
builder.link_same_source(all_video_ev, same_frame_max_gap=8.0)
for a in all_video_ev:
    for b in all_pdf_ev:
        builder.link_shared_entity(a, b, min_shared=1)
db.commit()

print("[*] Generating embeddings & indexing into Qdrant (in-memory, since no Qdrant server)…")
all_evidence = all_video_ev + all_pdf_ev
contents = []
for ev in all_evidence:
    prefix_parts = []
    if ev.timestamp_start is not None:
        ts = ev.timestamp_start
        total = int(ts)
        h, m, s = total // 3600, (total % 3600) // 60, total % 60
        prefix_parts.append(f"timestamp={h:02d}:{m:02d}:{s:02d}")
    if ev.page_number is not None:
        prefix_parts.append(f"page={ev.page_number}")
    prefix = " ".join(prefix_parts)
    contents.append(f"[{ev.modality}] {prefix}\n{ev.content}")
vectors = embedding_service.embed_texts(contents)
print(f"    Embedding dim: {len(vectors[0])}, records: {len(vectors)}")

qdrant_items = []
source_names = {video_source.id: video_source.name, pdf_source.id: pdf_source.name}
for ev, vec in zip(all_evidence, vectors):
    payload = {
        "source_id": str(ev.source_id),
        "source_name": source_names.get(ev.source_id, "unknown"),
        "modality": ev.modality.value if hasattr(ev.modality, "value") else str(ev.modality),
        "timestamp": ev.timestamp_start or 0.0,
        "page": ev.page_number or 0,
        "speaker": ev.speaker or "",
        "confidence": ev.confidence or 1.0,
    }
    qdrant_items.append((ev.id, ev.content, vec, payload))
point_ids = qdrant_service.upsert_many(qdrant_items)
print(f"    Qdrant upserted {len(point_ids)} points (in-memory collection '{settings.QDRANT_COLLECTION}')")

for ev, pid in zip(all_evidence, point_ids):
    storage.update_evidence_qdrant_id(ev.id, pid)

storage.update_source_status(video_source.id, ProcessingStatus.COMPLETED, f"Done: {len(all_video_ev)} evidence records", 100)
storage.update_source_status(pdf_source.id, ProcessingStatus.COMPLETED, f"Done: {len(all_pdf_ev)} evidence records", 100)
print()

questions = [
    "What architecture was discussed for reducing database load, who explained it, and where was the corresponding diagram shown?",
    "What is the TTL on the Redis cache and by what percentage is database traffic estimated to drop?",
    "Summarize the write-through cache pattern described in both the meeting and the PDF appendix.",
]

print("=== RUNNING RETRIEVAL + ANSWER GENERATION (mock Groq LLM mode) ===")
retrieval = RetrievalService(db)
for i, q in enumerate(questions):
    print(f"\n[Q{i+1}] {q}\n")
    hits = asyncio.run(retrieval.query(q, top_k=8, expand_relationships=True, include_multimodal=True))
    print(f"    Qdrant hits returned: {len(hits)}")
    for rank, hit in enumerate(hits[:4]):
        ev = hit.evidence
        meta = []
        meta.append(f"sim {(hit.similarity_score*100):.0f}%")
        if ev.timestamp_start is not None:
            ts = int(ev.timestamp_start)
            meta.append(f"@{ts//60:02d}:{ts%60:02d} in {source_names.get(ev.source_id, 'src')}")
        if ev.page_number:
            meta.append(f"pdf p.{ev.page_number}")
        if ev.speaker:
            meta.append(f"speaker={ev.speaker}")
        meta.append(f"mod={ev.modality.value if hasattr(ev.modality, 'value') else ev.modality}")
        snippet = ev.content[:120].replace("\n", " ")
        print(f"    [{rank+1}] ({', '.join(meta)}) {snippet}...")
        for rel in hit.related_evidence[:2]:
            rmeta = []
            if rel.timestamp_start is not None:
                ts = int(rel.timestamp_start); rmeta.append(f"@{ts//60:02d}:{ts%60:02d}")
            if rel.page_number: rmeta.append(f"p.{rel.page_number}")
            rmeta.append(f"mod={rel.modality.value if hasattr(rel.modality, 'value') else rel.modality}")
            rsnippet = rel.content[:70].replace("\n", " ")
            print(f"          -> linked ({', '.join(rmeta)}) {rsnippet}...")
    ctx = retrieval.build_context_prompt(hits)
    ans = asyncio.run(llm_service.generate_answer(q, ctx))
    print(f"\n    --- ANSWER ---\n    " + "\n    ".join(ans.splitlines()[:18]))
    if len(ans.splitlines()) > 18:
        print(f"    ... [truncated, total {len(ans.splitlines())} lines]")
    print()

db.close()
print("[OK] End-to-end smoke test PASSED. Evidence + Qdrant retrieval + relationships + (mock) LLM answer all functional.")
