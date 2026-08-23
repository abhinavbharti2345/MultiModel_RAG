import { useEffect, useState } from "react";
import { api } from "./api";
import type { HealthResponse, ProcessingJobResponse } from "./types";
import { UploadPanel } from "./components/UploadPanel";
import { SourcesList } from "./components/SourcesList";
import { QueryPanel } from "./components/QueryPanel";

export default function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [refreshNonce, setRefreshNonce] = useState(0);
  const [selectedSourceId, setSelectedSourceId] = useState<string | null>(null);

  useEffect(() => {
    api.health().then(setHealth).catch(() => undefined);
  }, []);

  function handleUploaded(_job: ProcessingJobResponse) {
    setRefreshNonce((n) => n + 1);
  }

  return (
    <div className="min-h-screen flex flex-col">
      <header className="sticky top-0 z-20 backdrop-blur bg-white/85 border-b border-slate-200">
        <div className="max-w-[1600px] mx-auto px-6 py-3.5 flex items-center gap-4">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-brand-500 via-indigo-500 to-purple-500 text-white flex items-center justify-center shadow-sm">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <rect x="2" y="3" width="20" height="14" rx="2" />
                <path d="M8 21h8M12 17v4" />
                <path d="m8 10 3 3L16 7" />
              </svg>
            </div>
            <div>
              <div className="font-semibold leading-tight text-white">Multimodal RAG</div>
              <div className="text-[11px] text-slate-500 leading-tight">
                Evidence Explorer · Video · Audio · PDF · Image
              </div>
            </div>
          </div>

          <div className="ml-auto flex items-center gap-2 text-xs">
            {health && (
              <div className="flex items-center gap-3 text-slate-500">
                <span className="inline-flex items-center gap-1.5">
                  <span
                    className={`w-1.5 h-1.5 rounded-full ${
                      health.status === "ok" ? "bg-emerald-500" : "bg-amber-500"
                    }`}
                  />
                  API {health.status}
                </span>
                <span className="text-slate-500">·</span>
                <span title="Groq LLM / Whisper configured">
                  🔊 {health.whisper_model}
                </span>
                <span className="text-slate-500">·</span>
                <span title="LLM">{health.groq_model}</span>
                <span className="text-slate-500">·</span>
                <span title="Embeddings">{health.embedding_model}</span>
                {!health.groq_configured && (
                  <span className="ml-1 px-1.5 py-0.5 rounded bg-amber-50 text-amber-700 ring-1 ring-amber-200">
                    Mock mode — add GROQ_API_KEY
                  </span>
                )}
              </div>
            )}
          </div>
        </div>
      </header>

      <main className="max-w-[1600px] mx-auto w-full flex-1 px-6 py-6">
        <div className="grid grid-cols-12 gap-6 items-start">
          <section className="col-span-12 lg:col-span-5 space-y-6 min-h-0">
            <UploadPanel onUploaded={handleUploaded} />
            <div className="lg:sticky lg:top-24">
              <SourcesList
                refreshNonce={refreshNonce}
                selectedSourceId={selectedSourceId}
                onSelect={setSelectedSourceId}
              />
            </div>
          </section>

          <section className="col-span-12 lg:col-span-7">
            <QueryPanel />
          </section>
        </div>
      </main>

      <footer className="border-t border-slate-200 bg-white/60">
        <div className="max-w-[1600px] mx-auto px-6 py-3 text-[11px] text-slate-500 flex items-center justify-between gap-3 flex-wrap">
          <div>
            Multimodal evidence ingestion + retrieval pipeline · Qdrant vector search · PostgreSQL metadata · Groq LLM with provenance grounding
          </div>
          <div>
            {health && (
              <>Qdrant collection: <span className="font-mono text-slate-700">{health.qdrant_collection}</span> · Storage: <span className="font-mono text-slate-700">{health.storage_path}</span></>
            )}
          </div>
        </div>
      </footer>
    </div>
  );
}
