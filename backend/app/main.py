from __future__ import annotations
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.database import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("multimodal-rag")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Multimodal RAG backend")
    try:
        init_db()
        logger.info("Database tables initialized")
    except Exception as e:
        logger.warning(f"DB init on startup failed (DB may not be ready yet): {e}")
    from app.services.qdrant_service import qdrant_service, QdrantConnectionError
    from app.services.embedding_service import embedding_service
    try:
        qdrant_service.health_check()
        _ = embedding_service.vector_size
        logger.info("Qdrant and embedding services initialized")
    except QdrantConnectionError as e:
        logger.error(f"QDRANT UNAVAILABLE: {e}")
        logger.error("The application will start but ingestion and queries will fail until Qdrant is available.")
    except Exception as e:
        logger.warning(f"Embedder init warning: {e}")

    # Clean up stuck tasks
    try:
        from app.database import SessionLocal
        from app.models.db_models import Source, ProcessingStatus
        db = SessionLocal()
        stuck_statuses = [
            ProcessingStatus.PROCESSING,
            ProcessingStatus.EXTRACTING_AUDIO,
            ProcessingStatus.EXTRACTING_FRAMES,
            ProcessingStatus.TRANSCRIBING,
            ProcessingStatus.ANALYZING_VISUALS,
            ProcessingStatus.EXTRACTING_OCR,
            ProcessingStatus.BUILDING_EVIDENCE,
            ProcessingStatus.EMBEDDING,
        ]
        stuck_sources = db.query(Source).filter(Source.status.in_(stuck_statuses)).all()
        for source in stuck_sources:
            source.status = ProcessingStatus.FAILED
            source.status_message = "Interrupted by server restart"
        db.commit()
        db.close()
        if stuck_sources:
            logger.info(f"Cleaned up {len(stuck_sources)} stuck tasks")
    except Exception as e:
        logger.warning(f"Failed to clean up stuck tasks: {e}")

    yield
    logger.info("Shutting down backend")


app = FastAPI(
    title="Multimodal RAG Hackathon API",
    description=(
        "End-to-end multimodal evidence ingestion and retrieval pipeline. "
        "Handles video, audio, images, PDFs; constructs structured evidence "
        "with cross-modal relationships; answers natural language questions "
        "with grounded provenance citations."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health", tags=["system"])
async def health_check():
    return {
        "status": "ok",
        "qdrant_collection": settings.QDRANT_COLLECTION,
        "embedding_model": settings.EMBEDDING_MODEL,
        "groq_model": settings.GROQ_LLM_MODEL,
        "whisper_model": settings.GROQ_WHISPER_MODEL,
        "storage_path": str(settings.STORAGE_PATH.resolve()),
        "groq_configured": bool(settings.GROQ_API_KEY),
        "vlm_configured": bool(settings.VLM_API_URL and settings.VLM_API_KEY),
    }


@app.get("/api/config", tags=["system"])
async def public_config():
    return {
        "frame_sample_interval": settings.FRAME_SAMPLE_INTERVAL,
        "scene_change_threshold": settings.SCENE_CHANGE_THRESHOLD,
        "max_important_frames": settings.MAX_IMPORTANT_FRAMES,
        "embedding_dimension": settings.EMBEDDING_DIMENSION,
    }


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.exception(f"Unhandled exception on {request.method} {request.url.path}: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": f"Internal server error: {exc.__class__.__name__}: {exc}"},
    )


from app.routers.upload_router import router as upload_router
from app.routers.sources_router import router as sources_router
from app.routers.query_router import router as query_router
from app.routers.assets_router import router as assets_router
from app.routers.health_router import router as health_router

app.include_router(upload_router)
app.include_router(sources_router)
app.include_router(query_router)
app.include_router(assets_router)
app.include_router(health_router)
