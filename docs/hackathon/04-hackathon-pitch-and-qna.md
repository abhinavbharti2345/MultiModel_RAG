# Hackathon Pitch + Judge Q&A

## SECTION A — One-Line Pitch

"We built a Multimodal RAG pipeline that finally lets you chat with your videos, audio recordings, and complex PDF diagrams—all in a single, unified vector space."

## SECTION B — 30-Second Elevator Pitch

"Right now, standard AI chat apps are blind and deaf. If you upload a PDF, they strip out the diagrams. If you upload a video lecture, they can't search it. We built a Multimodal RAG system that uses Vision models, Speech-to-Text, and local embeddings to unify video, audio, and text into one semantic database. You can ask a question, and our system will instantly cross-reference what a presenter was saying out loud with the architecture diagram they were pointing at on screen, and synthesize a perfect answer."

## SECTION C — 60-Second Pitch

**Problem:** Companies and students sit on terabytes of video meetings and diagram-heavy PDFs that are completely unsearchable by standard text-based LLMs.
**Limitation:** Conventional RAG only extracts raw text. It loses the visual context of a slide deck and completely ignores spoken lectures.
**Our Solution:** A temporal, cross-modal retrieval system.
**How it works:** When you upload media, we orchestrate FFmpeg, Whisper STT, and a Vision-Language Model to extract text, speech, and visual layout. We embed it all locally using `sentence-transformers` and store it in Qdrant. 
**Why it is different:** We mathematically link the visual frames to the spoken words via timestamps in SQLite, so retrieval preserves temporal context.
**Impact:** You never have to manually scrub through a 2-hour Zoom recording to find a specific whiteboard drawing ever again.

## SECTION D — 2–3 Minute Full Pitch

### Hook
"Imagine trying to study for a final exam, or review a critical engineering meeting, but all you have is a 2-hour video recording and a 50-page PDF full of complex architecture diagrams. If you use a standard RAG tool, it fails. Why?"

### Problem
"Because conventional RAG is blind and deaf. It strips out the diagrams from the PDF. It ignores the video entirely. It can't tell you what the presenter was drawing on the whiteboard while they were talking about database scaling."

### Solution
"That’s why we built this: A Multimodal Retrieval-Augmented Generation pipeline. We don't just search text; we search time, sound, and sight."

### Demo
"Let me show you. I'm dragging in an architectural PDF and a recorded engineering video. *(Upload files)*. In the background, our system is orchestrating a complex pipeline. It's using FFmpeg to strip the audio and sample keyframes. It's passing the audio to Groq's Whisper model. It's passing the frames to a Vision-Language Model to extract diagrams and OCR text. It embeds everything locally and indexes it in Qdrant."

"Now, I'll ask: *'What was discussed when the architecture slide was on screen?'* Watch. It instantly retrieves the visual description of the slide, cross-references the timestamp with the transcribed audio, and generates a synthesized answer."

### Technical Magic
"The magic here isn't just throwing APIs together. It's temporal mapping. By using SQLite alongside Qdrant, we maintain relational integrity. If a vector search finds a highly relevant spoken sentence, our retrieval engine automatically fetches the visual frame that was on screen at that exact millisecond to provide perfect context to the LLM."

### Differentiator
"Other teams might have built a text chatbot. We built a system that actively watches your videos, reads your diagrams, and connects the dots across completely different media types in real-time."

### Impact
"For students, researchers, and enterprise engineering teams, this turns a massive archive of unsearchable meetings and slide decks into a perfectly organized, instantly queryable knowledge base."

### Closing
"Stop searching through video timestamps manually. Let our Multimodal RAG do the watching for you. Thank you."

## SECTION E — DEMO SCRIPT

1. **Open application:** Show the clean React dashboard.
2. **Upload test PDF:** Upload `multimodal_data_management_hackathon.pdf`.
3. **Show ingestion:** Point out the dynamic loading state polling the backend.
4. **Ask text question:** "What is the Hackathon problem statement?"
5. **Upload short video:** Upload a 30-second test video with clear audio and a slide.
6. **Ask cross-modal question:** "What does the slide show, and what did the speaker say about it?"
7. **Show retrieved sources:** Highlight the citations pointing to specific timestamps.
8. **Explain architecture:** Briefly mention Qdrant and Groq while the LLM streams the answer.

### Demo backup plan
* **If VLM API fails (Decommissioned model):** Ensure the `.env` has `VLM_API_KEY` empty before the presentation. The system will gracefully fall back to the built-in Mock Analyzer, allowing the demo to proceed flawlessly.
* **If Uvicorn crashes during upload:** Ensure the server is started with `--reload-exclude "storage/*"` so SQLite writes don't trigger a server reset mid-demo.
* **If Groq API completely fails:** Have a pre-recorded screen capture of the working flow ready to play.

## SECTION F — Judge Q&A

### AI/ML Questions

**Q: Why is this better than ChatGPT with a PDF?**
A: ChatGPT processes files in a single isolated session. Our system builds a persistent vector database (Qdrant). You can upload 100 PDFs and 50 videos over a month, and instantly search across all of them simultaneously without hitting token limits.

**Q: Why do you need a VLM? Why not simply OCR the images?**
A: OCR only gives you raw text. It doesn't tell you that the text is inside a box pointing to a database cylinder. A Vision-Language Model extracts the *semantic meaning* and *relationships* of a diagram, which is critical for accurate retrieval.

**Q: How do you prevent hallucinations?**
A: Two ways. First, our VLM prompt forces strict JSON output for specific objects, preventing the vision model from inventing stories. Second, our LLM prompt enforces strict provenance, requiring it to cite specific Evidence IDs provided in the context.

### Architecture Questions

**Q: Why use Qdrant?**
A: We needed a dedicated vector database that supports payload filtering. Qdrant allows us to instantly filter vector searches by `source_id` or `modality` (e.g., searching only visual frames), which is critical for our cross-modal architecture.

**Q: Why not use a local LLM?**
A: Time to market and hardware constraints. To get near-instant answers for the demo, we utilized Groq's LPUs for the heavy LLM/STT inference, while keeping our embeddings completely local (`sentence-transformers`) to save costs.

**Q: What happens with bad documents or silent videos?**
A: The pipeline is modular. If FFmpeg finds no audio track, the STT phase is skipped, but visual frames are still indexed. If a PDF has no text, the chunker gracefully completes with 0 chunks.

### Scalability & Cost Questions

**Q: How would you scale to 100,000 documents?**
A: We would replace the current in-memory Python `threading` ingestion with a durable queue like Celery or RQ backed by Redis, and migrate the SQLite metadata database to PostgreSQL to prevent database locks.

**Q: How expensive is each query?**
A: Extremely cheap. Because we generate the embeddings locally using `all-MiniLM-L6-v2`, indexing text costs nothing. We only pay for the final LLM generation tokens and the VLM processing.

## SECTION G — Tough Judge Mode (Questions designed to catch us off guard)

**Q: Aren't you just gluing together Groq APIs and Qdrant? What part did your team actually build?**
A: The complex orchestration and temporal mapping. Extracting a transcript is easy. But mapping a specific spoken sentence at 01:23 to the exact visual frame shown on screen at 01:23, embedding them in a shared vector space, and constructing a cross-modal prompt that allows an LLM to reason across time—that is the architecture we built.

**Q: What happens if two users upload massive videos at the exact same time right now?**
A: To be completely transparent, our current implementation uses raw Python threads for background processing. Under heavy concurrent load, it would likely exhaust CPU resources or lock the SQLite database. For production, we would move the `IngestionOrchestrator` to a Celery worker.

**Q: Your VLM extraction seems slow/expensive for 30fps video. How did you solve that?**
A: We don't analyze every frame. We use FFmpeg to sample frames based on scene-change thresholds. If a slide is on screen for 5 minutes, we only extract and analyze it once, drastically saving API costs and indexing time.

**Q: I noticed a slight delay before the answer started streaming. Why?**
A: The delay is the vector search and context expansion. When we retrieve an audio snippet, we do an N+1 SQLite query to pull the temporally linked visual frame. We plan to optimize this by batching the relationship queries into a single SQL join.

## SECTION H — Team Cheat Sheet

```text
Project name: Multimodal RAG
One-line pitch: Chat with your videos, audio, and PDF diagrams in a unified vector space.
Problem: Standard RAG is blind to diagrams and deaf to video/audio.
Solution: Temporal, cross-modal retrieval using VLMs, STT, and vector search.
Key differentiator: We mathematically link spoken words to visual frames using time.
Frontend: React, Vite, TypeScript
Backend: FastAPI, Python
Database: SQLite (Metadata & Temporal Links)
Vector DB: Qdrant (Docker)
Embedding model: all-MiniLM-L6-v2 (Local, 384 dimensions)
LLM: Groq (llama-3.3-70b-versatile)
VLM: Groq (llama-3.2-11b-vision-preview / Mock fallback)
STT: Groq (whisper-large-v3)
Video processing: FFmpeg scene detection -> VLM + STT
PDF processing: PyPDF text chunking
Biggest strength: The unified multimodal architecture.
Biggest weakness: Raw threading for background jobs limits concurrency.
Future improvement: Migrate to Celery/Redis for durable background queues.
```
