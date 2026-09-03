import { useEffect, useState } from "react";
import { api } from "./api";
import type { HealthResponse, ProcessingJobResponse, SourceResponse } from "./types";
import { UploadPanel } from "./components/UploadPanel";
import { SourcesList } from "./components/SourcesList";
import { QueryPanel } from "./components/QueryPanel";
import { GraphExplorer } from "./components/GraphExplorer";
import { QdrantExplorer } from "./components/QdrantExplorer";
import { SourcesExplorer } from "./components/SourcesExplorer";
import { Sparkles, Folder, GitFork, Database, ChevronRight, RefreshCw, Cpu, Layers } from "lucide-react";

type NavigationTab = "query" | "sources" | "graph" | "qdrant";

export default function App() {
  const [activeTab, setActiveTab] = useState<NavigationTab>("query");
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [refreshNonce, setRefreshNonce] = useState(0);
  const [selectedSourceId, setSelectedSourceId] = useState<string | null>(null);
  const [sourcesData, setSourcesData] = useState<{
    sources: SourceResponse[];
    summary: Record<string, Record<string, unknown>>;
  }>({ sources: [], summary: {} });

  useEffect(() => {
    api.health().then(setHealth).catch(() => undefined);
  }, []);

  function handleUploaded(_job?: ProcessingJobResponse) {
    setRefreshNonce((n) => n + 1);
  }

  function getBreadcrumb() {
    switch (activeTab) {
      case "query":
        return "Query & Grounding Engine";
      case "sources":
        return "Ingested Multi-Modal Corpus";
      case "graph":
        return "Cross-Modal Relationship Graph";
      case "qdrant":
        return "Qdrant Vector Database Explorer";
    }
  }

  return (
    <div className="flex h-screen w-screen bg-[#09090b] overflow-hidden text-[#f4f4f5]">
      {/* MAIN LAYOUT (Sidebar + Workspace) */}
      <div className="flex-1 flex overflow-hidden">
        {/* SIDEBAR NAVIGATION */}
        <div className="w-[230px] bg-[#121215] border-r border-[#27272a] p-3 flex flex-col justify-between shrink-0">
          <div>
            {/* Workspace Header */}
            <div className="p-2.5 rounded-lg bg-[#18181b] border border-[#27272a] mb-4 flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <div className="w-6 h-6 rounded bg-indigo-600 flex items-center justify-center text-xs font-bold text-white shadow-sm">
                  R
                </div>
                <div>
                  <div className="text-xs font-semibold text-zinc-100 leading-none">Multimodal RAG</div>
                  <div className="text-[10px] text-zinc-400 leading-none mt-1">Production Pipeline</div>
                </div>
              </div>
            </div>

            {/* Navigation Items */}
            <div className="space-y-1">
              <button
                type="button"
                onClick={() => setActiveTab("query")}
                className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-md font-medium text-xs transition-all ${
                  activeTab === "query"
                    ? "bg-[#27272a] text-white font-semibold shadow-sm"
                    : "text-zinc-400 hover:bg-[#27272a]/60 hover:text-zinc-200"
                }`}
              >
                <Sparkles className={`w-4 h-4 ${activeTab === "query" ? "text-indigo-400" : "text-zinc-400"}`} />
                <span>Query & Grounding</span>
              </button>

              <button
                type="button"
                onClick={() => setActiveTab("sources")}
                className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-md font-medium text-xs transition-all ${
                  activeTab === "sources"
                    ? "bg-[#27272a] text-white font-semibold shadow-sm"
                    : "text-zinc-400 hover:bg-[#27272a]/60 hover:text-zinc-200"
                }`}
              >
                <Folder className={`w-4 h-4 ${activeTab === "sources" ? "text-indigo-400" : "text-zinc-400"}`} />
                <span>Ingested Sources</span>
                {sourcesData.sources.length > 0 && (
                  <span className="ml-auto px-1.5 py-0.2 bg-zinc-800 text-[10px] text-zinc-300 rounded font-mono">
                    {sourcesData.sources.length}
                  </span>
                )}
              </button>

              <button
                type="button"
                onClick={() => setActiveTab("graph")}
                className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-md font-medium text-xs transition-all ${
                  activeTab === "graph"
                    ? "bg-[#27272a] text-white font-semibold shadow-sm"
                    : "text-zinc-400 hover:bg-[#27272a]/60 hover:text-zinc-200"
                }`}
              >
                <GitFork className={`w-4 h-4 ${activeTab === "graph" ? "text-indigo-400" : "text-zinc-400"}`} />
                <span>Relationship Graph</span>
              </button>

              <button
                type="button"
                onClick={() => setActiveTab("qdrant")}
                className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-md font-medium text-xs transition-all ${
                  activeTab === "qdrant"
                    ? "bg-[#27272a] text-white font-semibold shadow-sm"
                    : "text-zinc-400 hover:bg-[#27272a]/60 hover:text-zinc-200"
                }`}
              >
                <Database className={`w-4 h-4 ${activeTab === "qdrant" ? "text-indigo-400" : "text-zinc-400"}`} />
                <span>Qdrant Payload DB</span>
              </button>
            </div>
          </div>

          {/* System Status Footer */}
          <div className="p-2.5 rounded-lg bg-[#18181b] border border-[#27272a] text-xs">
            <div className="text-[11px] font-medium text-zinc-400 mb-1 flex items-center justify-between">
              <span>Database Status</span>
              <span
                className={`font-mono text-[10px] font-semibold ${
                  health?.status === "ok" ? "text-emerald-400" : "text-amber-400"
                }`}
              >
                {health?.status === "ok" ? "Active" : "Degraded"}
              </span>
            </div>
            <div className="text-[10px] text-zinc-400 space-y-0.5 mono">
              <div>Qdrant: {health?.qdrant_collection || "evidence_items"}</div>
              <div>Model: {health?.groq_model ? "Groq Llama-3.3" : "Local / Offline"}</div>
            </div>
          </div>
        </div>

        {/* MAIN WORKSPACE */}
        <div className="flex-1 flex flex-col bg-[#09090b] overflow-hidden">
          {/* TOP TOOLBAR */}
          <div className="h-11 border-b border-[#27272a] px-5 flex items-center justify-between bg-[#121215] shrink-0">
            <div className="flex items-center gap-2 text-xs text-zinc-400">
              <span>Multimodal RAG</span>
              <ChevronRight className="w-3.5 h-3.5 text-zinc-600" />
              <span className="text-zinc-200 font-medium">{getBreadcrumb()}</span>
            </div>

            <div className="flex items-center gap-2">
              <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-[#27272a] text-zinc-300 border border-[#3f3f46]">
                4 Modalities (Video, Audio, PDF, Image)
              </span>
              <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-[#27272a] text-zinc-300 border border-[#3f3f46]">
                Zero-Invention Grounding
              </span>
            </div>
          </div>

          {/* DYNAMIC TAB WORKSPACE */}
          <div className="flex-1 p-4 overflow-hidden min-h-0">
            {activeTab === "query" && (
              <div className="h-full grid grid-cols-12 gap-4 overflow-hidden min-h-0">
                {/* LEFT COLUMN: Sources (5 Cols) */}
                <div className="col-span-12 lg:col-span-5 flex flex-col gap-3 min-h-0 h-full">
                  <UploadPanel onUploaded={handleUploaded} />
                  <SourcesList
                    refreshNonce={refreshNonce}
                    selectedSourceId={selectedSourceId}
                    onSelect={setSelectedSourceId}
                    onSourcesUpdate={(sources, summary) => setSourcesData({ sources, summary })}
                  />
                </div>

                {/* RIGHT COLUMN: Query Box & Answer (7 Cols) */}
                <div className="col-span-12 lg:col-span-7 flex flex-col gap-3 min-h-0 h-full">
                  <QueryPanel sources={sourcesData.sources} summaries={sourcesData.summary} />
                </div>
              </div>
            )}

            {activeTab === "sources" && (
              <SourcesExplorer
                sources={sourcesData.sources}
                summary={sourcesData.summary}
                refreshNonce={refreshNonce}
                onUploaded={handleUploaded}
              />
            )}

            {activeTab === "graph" && <GraphExplorer sources={sourcesData.sources} />}

            {activeTab === "qdrant" && (
              <QdrantExplorer health={health} sources={sourcesData.sources} />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
