# How to Run the Multimodal RAG Application for Development

This guide provides step-by-step instructions for starting the backend and frontend environments for local development and testing.

## Prerequisites

Before starting, ensure you have the following installed:
1. **Python 3.10+** (for the backend)
2. **Node.js (v18+) & npm** (for the frontend)
3. **Docker Desktop** (for running the Qdrant vector database)
4. **FFmpeg** (must be installed and added to your system PATH or configured in your `.env`)

---

## 1. Start Qdrant (Vector Database)

The application uses Qdrant for storing embeddings and cross-modal retrieval. Start the Docker container first.

Open a terminal (Powershell or Command Prompt) and run:

```powershell
docker run -d -p 6333:6333 -p 6334:6334 --name qdrant qdrant/qdrant
```

*To verify Qdrant is running, visit http://localhost:6333 in your browser. You should see a JSON response with Qdrant version info.*

---

## 2. Environment Configuration

Ensure your `.env` files are configured. You need API keys for the LLM, VLM, and Whisper models.

Check the following files:
*   `backend/.env`
*   `.env` (root folder)

Example essential variables:
```env
GROQ_API_KEY=your_primary_api_key_here
VLM_API_KEY=your_vision_api_key_here
QDRANT_HOST=localhost
QDRANT_PORT=6333
VLM_MODEL=qwen/qwen3.8-27b
```

---

## 3. Start the Backend (FastAPI / Uvicorn)

The backend handles video processing, chunking, embeddings, API endpoints, and talks to Qdrant.

Open a new terminal and navigate to the project root:

```powershell
# 1. Activate the Python virtual environment
.venv\Scripts\activate

# 2. Navigate to the backend directory
cd backend

# 3. Ensure PYTHONPATH includes the current directory, then start Uvicorn
$env:PYTHONPATH="."
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

*The backend API will be available at http://localhost:8000.*
*You can view the interactive API documentation at http://localhost:8000/docs.*

---

## 4. Start the Frontend (React / Vite)

The frontend is a React application built with Vite.

Open a *new* separate terminal and navigate to the `frontend` folder:

```powershell
# 1. Navigate to the frontend directory
cd frontend

# 2. Install dependencies (if you haven't already)
npm install

# 3. Start the Vite development server
npm run dev
```

*The frontend UI will be available at http://localhost:5173 (or another port if 5173 is busy, check the terminal output).*

---

## 5. View the Application

1. Open your browser and navigate to the local frontend URL (usually `http://localhost:5173`).
2. The UI should load successfully.
3. Check the **AI Services** panel on the left side of the screen. If configured correctly, it should show:
   * 🟢 LLM: Ready
   * 🟢 VLM: Ready
   * 🟢 Whisper: Ready
   * 🟢 Embeddings: Ready
   * 🟢 Qdrant: Connected

You are now ready to upload documents and videos, and start querying your Multimodal RAG system!
