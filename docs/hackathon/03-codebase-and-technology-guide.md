# Codebase & Technology Deep Dive

## 1. Project Structure

```text
├── backend/
│   ├── app/
│   │   ├── config.py             # Parses .env using Pydantic Settings
│   │   ├── database.py           # SQLite connection setup
│   │   ├── main.py               # FastAPI application entry point
│   │   ├── models/               # SQLAlchemy DB models (Source, Evidence, Relationship)
│   │   ├── routers/              # FastAPI endpoints (upload, query, sources)
│   │   ├── schemas/              # Pydantic validation schemas
│   │   └── services/             # Core business logic (ingestion, retrieval, LLM, VLM)
│   ├── scripts/                  # CLI testing scripts (smoke_test.py, test_upload.py)
│   ├── storage/                  # SQLite DB, uploads, extracted frames, audio files
│   └── .env                      # API keys and model configurations
├── frontend/
│   ├── src/
│   │   ├── api.ts                # Axios wrappers for backend calls
│   │   ├── components/           # React UI components (QueryPanel, SourcesList)
│   │   ├── App.tsx               # Main application layout and state logic
│   │   └── index.css             # Vanilla CSS styling
│   └── package.json
└── docs/hackathon/               # Hackathon presentation materials
```

## 2. Backend

* **FastAPI:** Provides the async web server. `app/main.py` wires up CORS and mounts the routers.
* **Routers:** `upload_router.py` handles multipart form data and triggers background ingestion. `query_router.py` handles user questions and streams LLM answers.
* **Services:** The brains of the operation. `ingestion_orchestrator.py` manages the pipeline. `evidence_builder.py` normalizes raw data into standard evidence objects.
* **Database Layer:** `database.py` and `db_models.py` define the SQLite schema. We use SQLAlchemy ORM to track `Source` status and `Relationship` links between evidence items.
* **Ingestion:** Files are saved, media is split by FFmpeg, text/audio/vision data is extracted via APIs, embedded, and stored in Qdrant.
* **Retrieval:** `retrieval_service.py` performs vector searches via `qdrant_service.py` and expands context using SQLite relationships.
* **Error Handling:** Errors in background threads update the SQLite `Source` status to 'failed' with a `status_message` so the frontend can display the failure.

## 3. Frontend

* **Framework:** React + Vite + TypeScript.
* **Components & Why They Exist:**
  * **`SourcesList` (Sidebar):** Displays all uploaded files and their current processing status. 
    * *Why it's there:* Multimodal ingestion (especially video processing and VLM analysis) takes time. Users need visual feedback (progress percentages, processing stages) so they don't think the application has frozen. It builds trust by showing exactly what the backend is doing (e.g., "Extracting audio", "Generating embeddings").
  * **`QueryPanel` (Chat Interface):** The main interaction area for the RAG pipeline.
    * *Why it's there:* It provides a familiar, conversational interface to query complex, cross-modal data. It renders the LLM's Markdown responses, including citations.
  * **Dynamic "Try These" Suggestions:** Context-aware prompts that appear based on what has been uploaded.
    * *Why it's there:* To solve the "blank canvas problem". When a user uploads a video, they might not know what the system is capable of analyzing. By dynamically suggesting questions (e.g., "Summarize the architectural diagram in the video"), we guide the user to test the multimodal features.
* **State Management:** Lifted state in `App.tsx` synchronizes the `SourcesList` and `QueryPanel`. 
  * *Why it's there:* When an upload finishes processing in the sidebar, the chat panel instantly updates its "Try These" suggestions to reflect the newly available context without requiring a page reload.
* **API Calls & Upload Flow:** `api.ts` handles drag-and-drop file POSTs. It uses short-polling (`setInterval`) to check `/api/sources/{id}/status`.
  * *Why polling instead of WebSockets:* Polling is stateless, vastly simplifying the backend architecture for a hackathon. It avoids the overhead of managing persistent WebSocket connections while still providing near real-time progress updates to the user.

## 4. Database

### SQLite
* **What is stored:** File metadata (filename, upload time), job status (Processing, Failed, Completed), and temporal/cross-modal relationships (e.g., Evidence A is related to Evidence B).
* **Why:** To maintain relational integrity and track state that vector databases are not designed to handle.

### Qdrant
* **What is stored:** The actual 384-dimensional mathematical vectors of the text, along with JSON payloads containing the raw text, timestamps, and modality types.
* **Why:** Qdrant is optimized for blazing-fast similarity search (Cosine Distance) across high-dimensional space.

## 5. Embeddings

* **Model:** `all-MiniLM-L6-v2`
* **What are embeddings:** They convert semantic meaning into a mathematical vector (an array of numbers).
* **Why this model:** It is exceptionally fast, lightweight, and runs entirely locally via the `sentence-transformers` python library, avoiding third-party API costs for basic text chunking.
* **What gets embedded:** PDF text chunks, transcribed audio sentences, and VLM-generated visual descriptions.

## 6. LLM

* **Provider:** Groq
* **Model:** `llama-3.3-70b-versatile`
* **API Flow:** The `query_router` passes the user question and the Qdrant-retrieved context to `llm_service.py`, which formats a strict prompt commanding the LLM to synthesize an answer and cite the provided Evidence IDs.

## 7. VLM (Vision-Language Model)

* **Provider:** Groq
* **Model:** `llama-3.2-11b-vision-preview` (Note: frequently updated/decommissioned by Groq. System falls back to mock analysis if the API fails or is unconfigured).
* **How it works:** FFmpeg extracts keyframes. They are base64 encoded and sent to the VLM.
* **Structured Output:** The prompt forces the VLM to return strict JSON matching a Pydantic schema, containing `description`, `ocr_text`, `entities`, `relationships`, and `diagram_info`.
* **Failure handling:** If the VLM hallucinates invalid JSON, the service gracefully falls back to dumping the raw output into the basic description field.

## 8. STT (Speech-to-Text)

* **Integration:** Groq's `whisper-large-v3` API.
* **Flow:** FFmpeg strips the audio track to a small `.mp3`. Whisper transcribes it, providing raw text and crucial temporal metadata (timestamps) so spoken words can be synced with visual frames.

## 9. FFmpeg

* **Where it is used:** Exclusively in `video_processor.py` via `subprocess.run()`. It is used to query video metadata, extract the `.mp3` audio track, and sample frames based on a scene-change detection algorithm.

## 10. PDF Processing

* **Parsing:** Uses standard Python PDF libraries to extract text page by page.
* **Chunking:** Splits massive text blocks into overlapping chunks (e.g., 1000 characters) to ensure embeddings capture specific semantic meaning rather than diluting it across a whole chapter.

## 11. Video Processing

* **Frame Extraction:** FFmpeg samples frames on a set interval and detects major visual shifts to avoid processing 30 identical frames of a static slide.
* **Visual Analysis:** Keyframes go to the VLM.
* **Indexing:** Temporal data (timestamps) are strictly attached to both the audio chunks and the visual frames before embedding.

## 12. Retrieval

* **Algorithm:** 
  1. Embed user query.
  2. Search Qdrant for top-k nearest vectors.
  3. Fetch associated `evidence_id`s.
  4. Query SQLite to find any `Relationships` linked to those IDs (e.g., if a spoken phrase is retrieved, pull the visual frame from that exact second).
  5. Format the expanded evidence into a massive Markdown string for the LLM.

## 13. Prompt Engineering

* **VLM Prompt:** Highly structured. Instructs the model: "Do NOT hallucinate diagram relationships." Forces JSON output.
* **LLM Prompt:** Enforces strict provenance. "Use ONLY the provided context. Cite your sources using the exact Evidence IDs provided."

## 14. Configuration (.env)

* `GROQ_API_KEY`: The master key for LLM, VLM, and STT.
* `QDRANT_HOST`: Points to localhost.
* `VLM_MODEL`: Easily swappable when Groq changes experimental endpoints.
* *(Never print API keys to logs or UI)*

## 15. Docker

* **Usage:** We use Docker exclusively to host the Qdrant Vector Database.
* **Why:** Qdrant is built in Rust and runs best as a containerized service. Running it in Docker isolates the vector storage engine from our Python environment and ensures consistent behavior across OS platforms.

## 16. Dependencies

| Technology | Purpose | Where Used |
| ---------- | ------- | ---------- |
| FastAPI | Web framework | `app/main.py`, `routers/` |
| Uvicorn | ASGI Server | Starting the backend |
| SQLAlchemy | SQLite ORM | `models/`, `database.py` |
| Qdrant-Client | Vector DB Driver | `qdrant_service.py` |
| Sentence-Transformers | Local Embeddings | `embedding_service.py` |
| Httpx | Async HTTP client | Calling Groq APIs |
| React/Vite | Frontend Framework | `frontend/src/` |

## 17. "If a Judge Asks..."

* **Why Qdrant instead of PostgreSQL for vectors?** Qdrant is purpose-built for vector similarity search and payload filtering at scale, whereas pgvector is an extension bolted onto a relational DB. Qdrant is faster for our specific workload.
* **Why SQLite?** For a hackathon, SQLite provides zero-configuration relational storage for tracking job statuses and temporal links without requiring a separate database server.
* **Why SentenceTransformers locally?** To save API costs and reduce latency. Text chunking generates thousands of strings; embedding them locally is fast and free.
* **Why Groq?** Groq provides ultra-low latency inference using LPUs, allowing us to process heavy VLM and LLM tasks in seconds rather than minutes.
* **How is multimodal retrieval performed?** We don't rely on the LLM to figure out time. We use temporal metadata. If audio from 01:23 is highly relevant to the query, our retrieval pipeline automatically grabs the visual frame from 01:23 and feeds both to the LLM.
* **How do you handle hallucinations?** By enforcing strict JSON schemas on the VLM and using rigid system prompts on the LLM that instruct it to reject answering if the context doesn't contain the data.
* **What happens if an API fails?** The `IngestionOrchestrator` catches the exception, marks the specific source as `Failed` in SQLite, and propagates a clean error message to the user UI, preventing the whole app from crashing.
