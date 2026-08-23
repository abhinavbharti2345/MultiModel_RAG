# Multimodal RAG — Evidence Pipeline for RAG-Ready Systems

Hackathon build: **Multimodal Data Management Pipeline for RAG-Ready Systems**.

🚀 **[Live Website / Demo](YOUR_NGROK_OR_VERCEL_LINK_HERE)**  
🎥 **[2-Minute Pitch Video](YOUR_YOUTUBE_OR_DRIVE_LINK_HERE)**

The system ingests **video, audio, images and PDFs**, decomposes each into structured,
provenance-tracked evidence objects (transcript segments, visual frame descriptions,
OCR text, document chunks), links evidence **across modalities and time** in a graph,
indexes everything in a vector DB, and answers natural-language questions with
grounded, cited answers whose proof spans multiple modalities.

> Example question this system is built to answer:
> *"What architecture was discussed for reducing database load, who explained it, and
> where was the corresponding diagram shown?"*
> Answering requires connecting speech (who said it), video frames/OCR (where the diagram
> appeared), and PDF pages (the formal spec) — not just text similarity.

---

## 1. Architecture

```
                        ┌──────────────────────────────────────────────────────┐
                        │                  INGESTION (per file)                │
 Video ──► FFmpeg ──┬──► Audio ──► Groq Whisper STT ──► TranscriptSegments ──┐   │
                    └──► Frames ─► OpenCV sampling + scene-change scoring    │   │
 Image ────────────────────────────► Vision-Language Model ──► description    │   │
 PDF ──────────► pypdf ──► page text ──► chunker (700c/180o)                  ▼   ▼
 Audio ──► Groq Whisper STT ──► TranscriptSegments            ┌──────────────────────┐
                                                              │   EVIDENCE BUILDER   │
                              content · modality · timestamps │ entities (regex NER) │
                              speaker · page · confidence     │ provenance           │
                              source_id                       └──────────┬───────────┘
                                                                         │
              ┌──────────────────────────────────────────────────────────┼──────────┐
              ▼                                                          ▼          │
   ┌───────────────────┐   temporal_coincidence,               ┌──────────────────┐  │
   │ Qdrant (vectors)  │◄── explains, shares_entities ◄────────│ PostgreSQL /     │  │
   │ payload: source,  │        (relationship graph)           │ SQLite (metadata,│  │
   │ ts, page, speaker │                                       │ entities, rels)  │  │
   └─────────┬─────────┘                                       └──────────────────┘  │
             │                          RETRIEVAL                                    │
             ▼                                                                        │
   question ──► embed ──► vector top-k (all modalities) ──► graph expansion (≤1 hop)  │
             ──► ranked multi-modal evidence package ──► Groq LLM ──► answer with
                                                        provenance citations
```

### Repository layout

| Path | Purpose |
|---|---|
| `backend/app/services/` | Ingestion orchestrator, STT, VLM analyzer, video processor, document ingestor, evidence builder, embedding, Qdrant, retrieval, LLM |
| `backend/app/models/db_models.py` | Structured schema: `Source`, `Frame`, `Evidence`, `Entity`, `Relationship` |
| `backend/app/routers/` | FastAPI: `/api/upload`, `/api/sources`, `/api/query`, `/api/assets` |
| `frontend/` | React + Vite + Tailwind UI: upload, live processing status, evidence explorer, query panel |
| `backend/scripts/generate_demo_dataset.py` | Generates the real 4-modality demo corpus |
| `backend/scripts/smoke_test.py` | End-to-end pipeline test |
| `backend/scripts/evaluate.py` | Multimodal vs text-only RAG evaluation |

---

## 2. Key design decisions

1. **Evidence, not chunks.** Every extracted unit becomes an `Evidence` row carrying
   *content, modality, timestamp(s)/page, speaker, confidence, provenance* — the fields
   required by the problem statement's structured-representation checklist. A transcript
   sentence, a frame description and an OCR snippet stay distinct but referenceable.

2. **Relationships are first-class data.** Cross-modal context is stored as typed edges in
   a `relationships` table (`explains`, `is_explained_by`, `temporally_coincident_with`,
   `shares_entities_with`) with per-edge confidence. Speech temporally overlapping an
   important frame is linked to that frame's visual evidence, so "what was on screen while
   X was said" is a single graph hop, not a guess.

3. **Entities bridge sources.** Lightweight regex NER extracts technology/people/QoS
   entities (Redis, PostgreSQL, TTL, Sarah Chen…). Shared-entity edges connect related
   observations *across different files*, enabling the stretch goal of cross-file entity
   relationships without a heavy KG stack.

4. **Retrieval = vectors + graph expansion.** Vector search returns candidate evidence of
   any modality; the retriever then walks relationship edges (confidence ≥ 0.6) to pull in
   connected evidence — e.g. a transcript hit automatically drags in the diagram frame it
   explains. Provenance (source name, timestamp, page, speaker, evidence ID) survives into
   the LLM context and the UI.

5. **Grounded generation.** The LLM prompt hard-forbids invented citations and instructs
   weighting visual/written evidence over speech for questions about diagrams or written
   text. Without API keys the whole stack degrades gracefully to deterministic mock
   services so the pipeline is always demonstrable offline.

6. **Graceful degradation everywhere.** No Groq key → mock transcription/LLM. No VLM →
   heuristic frame analysis. No Qdrant server → in-memory client. No Postgres → SQLite.
   This keeps the 13-hour hackathon demo bulletproof.

## 3. Quickstart

### Docker (recommended)

```bash
cp .env.example .env         # add GROQ_API_KEY / VLM_API_KEY for full quality (optional)
docker compose up --build
# backend  http://localhost:8000/docs
# frontend http://localhost:5173
```

### Local

```bash
cd backend
pip install -r requirements.txt      # needs FFmpeg on PATH for video ingestion
uvicorn app.main:app --reload --port 8000
```

### Run the demo (≥3 modalities)

```bash
cd backend
python scripts/generate_demo_dataset.py   # builds design_doc.pdf, caching_diagram.png,
                                          # meeting_narration.wav (real TTS), meeting_recording.mp4*
python scripts/evaluate.py                # auto-ingests the corpus + prints baseline comparison
```

\* mp4 requires FFmpeg (present in the Docker image); WAV/PDF/PNG are generated natively.

Then open the UI, watch each file process through status stages
(`extracting_audio → transcribing → analyzing_visuals → building_evidence → embedding`),
and ask:
*"What architecture was proposed for reducing database load, who explained it, and
where is the corresponding diagram shown?"*

### Evaluation vs text-centric RAG

```bash
python scripts/evaluate.py --k 10
```

Both systems share the same corpus and embedding model. Baseline = plain vector search over
text chunks only (the "chunk → embed → retrieve" pipeline from the problem statement).
Ours adds cross-modality retrieval + relationship-graph expansion. Gold answers require
facts living in different modalities.

Measured on the demo corpus (offline mode, hashing embeddings):

| Metric (avg) | Text-only RAG | Multimodal | Δ |
|---|---|---|---|
| Fact hit rate | 0.278 | 0.611 | **+0.333** |
| Modality coverage | 0.389 | 0.722 | **+0.333** |
| MRR | 0.833 | 1.000 | +0.167 |

Full JSON report: `backend/storage/evidence/eval_report.json`. With neural embeddings
(`sentence-transformers`) and real API keys, absolute numbers rise further.

## 4. API

| Method & path | Description |
|---|---|
| `POST /api/upload` | Upload video/image/pdf/audio → async processing job |
| `GET /api/sources/{id}/status` | Live progress % + stage |
| `GET /api/sources/{id}/evidence-summary` | Evidence counts grouped by modality |
| `POST /api/query` | NL question → grounded answer + provenance summary + evidence |
| `POST /api/query/evidence-only` | Retrieval only (no LLM) |
| `GET /api/query/evidence/{id}/related` | Graph neighbours of one evidence object |
| `GET /api/assets/frames/{id}` | Frame image (for UI thumbnails) |

## 5. Scope choices

Implemented from mandatory scope: all four input modalities, full structured
representation (content/modality/timestamp/source/entities/relationships/confidence/
provenance), cross-modal + temporal linking, multi-modal retrieval with traceability.
Out of scope per problem statement: custom model training, auth, exotic formats.

## 6. Future improvements

- **Semantic event segmentation** instead of fixed sampling/chunking (shot detection +
  topic-shift boundaries) so evidence aligns to discussion moments.
- **Temporal knowledge graph**: promote the relationships table to a real graph store and
  answer change-over-time questions ("what did we decide about TTL last quarter?").
- **Exact image-region provenance** by having the VLM return bounding boxes for OCR hits.
- **Neural reranking** (cross-encoder) after graph expansion, and hybrid BM25+vector search.
- **Confidence-weighted retrieval**: currently stored per evidence/edge; next step is using
  them as retrieval-time features and calibration against human labels.
- **A/B measurement harness expansion**: more gold questions, judged LLM-answer scoring,
  and latency benchmarking against the text-only baseline.
