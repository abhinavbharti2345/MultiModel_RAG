"""Evaluation harness: Multimodal RAG vs conventional TEXT-ONLY RAG baseline.

Implements deliverable #6 of the hackathon problem statement:
    "Evaluation against a basic text-centric RAG approach"

Methodology
-----------
Both systems share the SAME corpus (the ingested demo dataset) and the SAME
embedding model. The only difference is the retrieval strategy:

  BASELINE (text-centric RAG):
      Plain vector similarity search restricted to modality="text" chunks,
      no timestamps, no relationship expansion - i.e. the ordinary
      "chunk -> embed -> store -> retrieve" pipeline described in the
      problem statement.

  OURS (multimodal RAG):
      Vector search over ALL modalities + graph expansion over stored
      cross-modal relationships (explains / temporally_coincident_with /
      shares_entities_with).

Metrics per question (gold answers require facts from MULTIPLE modalities):
  fact_hit_rate       fraction of gold facts found among top-k retrieved
  hit@k               1.0 if ALL required facts are found within top-k
  mrr                 reciprocal rank of the first gold-fact-bearing result
  modality_coverage   fraction of REQUIRED modalities present in top-k

Usage:
    python scripts/evaluate.py [--k 10]

Writes storage/evidence/eval_report.json and prints a comparison table.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

logging.basicConfig(level=logging.WARNING, format="%(levelname).1s %(name)s: %(message)s")

from app.config import settings  # noqa: E402
from app.database import SessionLocal, init_db  # noqa: E402
from app.models.db_models import SourceType  # noqa: E402
from app.services.storage_service import StorageService  # noqa: E402
from app.services.retrieval_service import RetrievalService  # noqa: E402
from app.services.embedding_service import embedding_service  # noqa: E402
from app.services.qdrant_service import qdrant_service  # noqa: E402

REPORT_PATH = settings.STORAGE_PATH / "evidence" / "eval_report.json"

# ---------------------------------------------------------------------------
# Gold set: every question NEEDS facts that live in different modalities.
# A fact counts as retrieved when ANY keyword appears in a top-k item whose
# modality matches the fact's modality.
# ---------------------------------------------------------------------------
GOLD_SET = [
    {
        "id": "Q1",
        "question": ("What architecture was proposed for reducing database load, "
                     "who explained it, and where is the corresponding diagram shown?"),
        "required_modalities": ["audio", "visual", "text"],
        "facts": [
            {"modality": "audio", "keywords": ["redis caching layer",
                                               "cache frequent queries",
                                               "reads check redis"]},
            {"modality": "audio", "keywords": ["sarah chen", "principal engineer"]},
            {"modality": "visual", "keywords": ["data flow", "caching strategy",
                                                "api gateway", "load balancer",
                                                "app servers"]},
            {"modality": "text", "keywords": ["section 3.2", "appendix",
                                              "figure 7-1", "write-through"]},
        ],
    },
    {
        "id": "Q2",
        "question": ("What TTL is used for cached entries and how much read "
                     "traffic should Redis absorb?"),
        "required_modalities": ["audio", "visual", "text"],
        "facts": [
            {"modality": "audio", "keywords": ["five minute", "5 minutes", "ttl"]},
            {"modality": "audio", "keywords": ["sixty percent", "60 percent", "60%"]},
            {"modality": "visual", "keywords": ["ttl 300s", "ttl 300",
                                                "read reduction", "60%"]},
            {"modality": "text", "keywords": ["ttl of 300 seconds", "60%",
                                              "five minutes"]},
        ],
    },
    {
        "id": "Q3",
        "question": ("Describe the write path of the caching pattern and what "
                     "happens when Redis fails."),
        "required_modalities": ["visual", "text"],
        "facts": [
            {"modality": "audio", "keywords": ["write-through", "invalidate"]},
            {"modality": "visual", "keywords": ["write-through", "invalidate"]},
            {"modality": "text", "keywords": ["falls back to postgresql",
                                              "availability", "write-through"]},
        ],
    },
]


def norm_mod(m) -> str:
    return m.value if hasattr(m, "value") else str(m)


def ingest_demo_files_if_needed(db) -> None:
    """Ingest storage/demo_dataset/* synchronously unless already indexed."""
    storage = StorageService(db)
    demo_dir = settings.STORAGE_PATH / "demo_dataset"
    if not demo_dir.exists():
        print(f"[!] {demo_dir} not found - run scripts/generate_demo_dataset.py first.")
        return
    existing_names = {s.name for s in storage.list_sources(limit=500)}

    type_by_ext = {
        ".pdf": SourceType.PDF, ".png": SourceType.IMAGE, ".jpg": SourceType.IMAGE,
        ".jpeg": SourceType.IMAGE, ".wav": SourceType.AUDIO, ".mp3": SourceType.AUDIO,
        ".mp4": SourceType.VIDEO, ".mov": SourceType.VIDEO, ".mkv": SourceType.VIDEO,
    }
    mime_by_type = {
        SourceType.PDF: "application/pdf", SourceType.IMAGE: "image/png",
        SourceType.AUDIO: "audio/wav", SourceType.VIDEO: "video/mp4",
    }

    from app.schemas.evidence_schemas import SourceCreate
    from app.services.ingestion_orchestrator import IngestionOrchestrator

    orch = IngestionOrchestrator(db)
    for f in sorted(demo_dir.iterdir()):
        st = type_by_ext.get(f.suffix.lower())
        if st is None or f.name.startswith("_") or f.name in existing_names:
            continue
        src = storage.create_source(SourceCreate(
            name=f.name, source_type=st, file_path=str(f),
            file_size=f.stat().st_size, mime_type=mime_by_type[st],
        ))
        print(f"[*] Ingesting {f.name} ({st.value})...")
        t0 = time.time()
        if st == SourceType.PDF:
            orch.ingest_pdf(src.id, f)
        elif st == SourceType.IMAGE:
            orch.ingest_image(src.id, f)
        elif st == SourceType.AUDIO:
            orch.ingest_audio(src.id, f)
        else:
            orch.ingest_video(src.id, f)
        print(f"    done in {time.time() - t0:.1f}s")


# --- BASELINE: text-only vector RAG ----------------------------------------
def baseline_text_only_query(query_text: str, top_k: int) -> list[dict]:
    vectors = asyncio.run(embedding_service.embed_texts_async([query_text]))
    hits = qdrant_service.search(vectors[0], top_k=top_k,
                                 score_threshold=0.0, modalities=["text"])
    out = []
    for _eid, score, payload in hits:
        out.append({"content": "", "modality": "text",
                    "score": score, "payload": payload})
    return out


def enrich_baseline_with_content(db, hits: list[dict]) -> None:
    from uuid import UUID
    from app.models.db_models import Evidence
    for h in hits:
        try:
            eid = UUID(str(h["payload"].get("evidence_id")))
        except Exception:
            continue
        ev = db.query(Evidence).filter(Evidence.id == eid).first()
        h["content"] = ev.content if ev else ""


# --- scoring ----------------------------------------------------------------
def score_results(results: list[dict], spec: dict, k: int) -> dict:
    top = results[:k]
    facts = spec["facts"]
    found_ranks = []
    modality_seen = set()

    for f in facts:
        rank = None
        for idx, r in enumerate(top):
            mod = norm_mod(r.get("modality"))
            modality_seen.add(mod)
            if mod == f["modality"]:
                content = (r.get("content") or "").lower()
                if any(kw.lower() in content for kw in f["keywords"]):
                    rank = idx + 1
                    break
        found_ranks.append(rank)

    n_found = sum(1 for r in found_ranks if r is not None)
    first_rank = next((r for r in found_ranks if r is not None), None)
    req_mods = set(spec["required_modalities"])

    return {
        "facts_found": n_found,
        "facts_total": len(facts),
        "fact_hit_rate": round(n_found / len(facts), 3),
        "hit_at_k": 1.0 if n_found == len(facts) else 0.0,
        "mrr": round(1.0 / first_rank, 3) if first_rank else 0.0,
        "modality_coverage": round(len(req_mods & modality_seen) / len(req_mods), 3),
        "fact_ranks": found_ranks,
    }

# --- main -------------------------------------------------------------------
def mm_results_to_dicts(hits) -> list[dict]:
    out = []
    for h in hits:
        out.append({"content": h.evidence.content,
                    "modality": norm_mod(h.evidence.modality),
                    "score": h.similarity_score})
        for rel in h.related_evidence:
            out.append({"content": rel.content,
                        "modality": norm_mod(rel.modality),
                        "score": 0.0})
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Multimodal vs text-only RAG evaluation")
    parser.add_argument("--k", type=int, default=10, help="top-k cutoff")
    args = parser.parse_args()

    init_db()
    db = SessionLocal()

    print("=" * 78)
    print("MULTIMODAL RAG EVALUATION - multimodal system vs text-centric baseline")
    print(f"Embedding: {settings.EMBEDDING_MODEL}   k={args.k}")
    print("=" * 78)

    ingest_demo_files_if_needed(db)

    retrieval = RetrievalService(db)
    report = {"k": args.k, "embedding_model": settings.EMBEDDING_MODEL, "questions": []}
    agg = {"baseline": {"fact_hit_rate": 0, "hit_at_k": 0, "mrr": 0, "modality_coverage": 0},
           "multimodal": {"fact_hit_rate": 0, "hit_at_k": 0, "mrr": 0, "modality_coverage": 0}}
    n = 0

    for spec in GOLD_SET:
        print(f"\n[{spec['id']}] {spec['question']}")

        t0 = time.time()
        base_hits = baseline_text_only_query(spec["question"], top_k=args.k * 2)
        enrich_baseline_with_content(db, base_hits)
        base_time = time.time() - t0
        base_scores = score_results(base_hits, spec, k=args.k)

        t0 = time.time()
        mm_hits = asyncio.run(retrieval.query(
            spec["question"], top_k=args.k,
            expand_relationships=True, include_multimodal=True))
        mm_time = time.time() - t0
        mm_dicts = mm_results_to_dicts(mm_hits)
        mm_scores = score_results(mm_dicts, spec, k=args.k)

        mods_base = {norm_mod(r["modality"]) for r in base_hits[:args.k]}
        mods_mm = {d["modality"] for d in mm_dicts[:args.k]}
        print(f"    baseline : facts {base_scores['facts_found']}/{base_scores['facts_total']}"
              f"  hit@k={base_scores['hit_at_k']:.1f}  mrr={base_scores['mrr']:.3f}"
              f"  modalities={sorted(mods_base)}  ({base_time:.2f}s)")
        print(f"    multimodal: facts {mm_scores['facts_found']}/{mm_scores['facts_total']}"
              f"  hit@k={mm_scores['hit_at_k']:.1f}  mrr={mm_scores['mrr']:.3f}"
              f"  modalities={sorted(mods_mm)}  ({mm_time:.2f}s)")

        report["questions"].append({
            "id": spec["id"], "question": spec["question"],
            "baseline": {**base_scores, "modalities_seen": sorted(mods_base),
                         "latency_seconds": round(base_time, 3)},
            "multimodal": {**mm_scores, "modalities_seen": sorted(mods_mm),
                           "latency_seconds": round(mm_time, 3)},
        })
        for key in agg["baseline"]:
            agg["baseline"][key] += base_scores[key]
            agg["multimodal"][key] += mm_scores[key]
        n += 1

    if n:
        report["aggregate"] = {
            side: {k: round(v / n, 3) for k, v in vals.items()}
            for side, vals in agg.items()
        }
        b, m = report["aggregate"]["baseline"], report["aggregate"]["multimodal"]
        print("\n" + "=" * 78)
        print(f"{'METRIC (avg over questions)':38s} {'TEXT-ONLY RAG':>14s} {'MULTIMODAL':>12s}  delta")
        print("-" * 78)
        label = {"fact_hit_rate": "Fact hit rate", "hit_at_k": "Full-answer hit@k",
                 "mrr": "MRR", "modality_coverage": "Modality coverage"}
        for key in ("fact_hit_rate", "hit_at_k", "mrr", "modality_coverage"):
            delta = m[key] - b[key]
            sign = "+" if delta >= 0 else ""
            print(f"{label[key]:38s} {b[key]:14.3f} {m[key]:12.3f}  {sign}{delta:.3f}")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nReport written to {REPORT_PATH}")
    db.close()


if __name__ == "__main__":
    main()
