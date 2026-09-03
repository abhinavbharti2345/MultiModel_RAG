from __future__ import annotations
import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.evidence_schemas import (
    EvidenceResponse,
    EvidenceWithScore,
    QueryRequest,
    QueryResponse,
)
from app.services.retrieval_service import RetrievalService
from app.services.llm_service import llm_service
from app.services.storage_service import StorageService

router = APIRouter(prefix="/api/query", tags=["query"])

logger = logging.getLogger(__name__)


@router.post("", response_model=QueryResponse)
async def query(
    req: QueryRequest,
    db: Session = Depends(get_db),
):
    logger.info(f"[QUERY] Received query: {req.query}")
    
    try:
        logger.info("[EMBEDDING] AND [QDRANT RETRIEVAL] AND [CROSS-MODAL EXPANSION] starting...")
        retrieval = RetrievalService(db)
        evidence_hits = await retrieval.query(
            query_text=req.query,
            top_k=req.top_k,
            expand_relationships=req.expand_relationships,
            include_multimodal=req.include_multimodal,
        )
        if not evidence_hits:
            logger.info("[QDRANT RETRIEVAL] No matching evidence found.")
            return QueryResponse(
                answer="No matching evidence was found in the index. Try rephrasing your question or uploading more documents/videos.",
                provenance_summary=[],
                evidence=[],
            )

        logger.info("[CONTEXT BUILD] Building context prompt...")
        context = retrieval.build_context_prompt(evidence_hits)
        
        logger.info("[LLM REQUEST] Requesting answer from Groq...")
        answer_text = await llm_service.generate_answer(req.query, context)
        logger.info("[LLM RESPONSE] Successfully parsed generated answer.")

        provenance_summary = []
        for hit in evidence_hits[:8]:
            ev = hit.evidence
            parts = []
            parts.append(f"modality={ev.modality}")
            if ev.timestamp_start is not None:
                parts.append(f"ts={_fmt_ts(ev.timestamp_start)}")
            if ev.page_number is not None:
                parts.append(f"page={ev.page_number}")
            if ev.speaker:
                parts.append(f"speaker={ev.speaker}")
            meta = ", ".join(parts)
            snippet = ev.content[:80].replace("\n", " ")
            provenance_summary.append(f"- [{meta}] {snippet}…")

        return QueryResponse(
            answer=answer_text,
            provenance_summary=provenance_summary,
            evidence=evidence_hits,
        )
    except Exception as e:
        logger.exception("[QUERY PIPELINE FAILED] Unhandled error during query processing")
        # Provide a safe human-readable error while backend logs traceback
        error_msg = str(e)
        if "404" in error_msg and "LLM generation failed" in error_msg:
            safe_detail = "The configured AI model is no longer available on the provider (Model Decommissioned). Please update the LLM model configuration."
        else:
            safe_detail = f"An error occurred while generating the answer: {error_msg}"
        raise HTTPException(status_code=500, detail=safe_detail)


@router.post("/evidence-only", response_model=list[EvidenceWithScore])
async def query_evidence_only(
    req: QueryRequest,
    db: Session = Depends(get_db),
):
    retrieval = RetrievalService(db)
    return await retrieval.query(
        query_text=req.query,
        top_k=req.top_k,
        expand_relationships=req.expand_relationships,
        include_multimodal=req.include_multimodal,
    )


@router.get("/evidence/{evidence_id}", response_model=EvidenceResponse)
def get_evidence(evidence_id: UUID, db: Session = Depends(get_db)):
    storage = StorageService(db)
    ev = storage.get_evidence(evidence_id)
    if ev is None:
        raise HTTPException(status_code=404, detail="Evidence not found")
    return EvidenceResponse.model_validate(ev)


@router.get("/evidence/{evidence_id}/related", response_model=list[EvidenceResponse])
def get_related_evidence(
    evidence_id: UUID,
    max_hops: int = Query(1, ge=1, le=3),
    min_confidence: float = Query(0.5, ge=0.0, le=1.0),
    db: Session = Depends(get_db),
):
    storage = StorageService(db)
    ev = storage.get_evidence(evidence_id)
    if ev is None:
        raise HTTPException(status_code=404, detail="Evidence not found")
    related = storage.get_related_evidence(evidence_id, max_hops=max_hops, min_confidence=min_confidence)
    return [EvidenceResponse.model_validate(r) for r in related]


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
