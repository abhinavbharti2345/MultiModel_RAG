import { useState, useEffect } from "react";
import { api } from "../api";
import type { HealthResponse, SourceResponse } from "../types";
import { Database, ShieldCheck, Activity, Cpu, Server, Box, Layers, RefreshCw } from "lucide-react";

interface Props {
  health: HealthResponse | null;
  sources: SourceResponse[];
}

export function QdrantExplorer({ health, sources }: Props) {
  const [config, setConfig] = useState<Record<string, unknown> | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    fetch("/api/config")
      .then(res => res.json())
      .then(setConfig)
      .catch(() => undefined);
  }, []);

  async function handleRefresh() {
    setRefreshing(true);
    try {
      const res = await fetch("/api/config");
      const data = await res.json();
      setConfig(data);
    } catch {
      // ignore
    } finally {
      setTimeout(() => setRefreshing(false), 500);
    }
  }

  return (
    <div className="flex-1 flex flex-col h-full gap-3 overflow-hidden">
      {/* Header */}
      <div className="card-surface p-3 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-2">
          <Database className="w-4 h-4 text-emerald-400" />
          <span className="text-xs font-semibold text-zinc-100">Qdrant Vector Database & Storage Engine</span>
        </div>
        <button
          onClick={handleRefresh}
          className="px-2.5 py-1 rounded bg-[#27272a] hover:bg-[#3f3f46] text-zinc-300 text-xs font-medium flex items-center gap-1.5 transition"
        >
          <RefreshCw className={`w-3 h-3 ${refreshing ? "animate-spin" : ""}`} />
          Refresh Metrics
        </button>
      </div>

      {/* Metrics Row */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-3 shrink-0">
        <div className="card-surface p-3.5 flex items-center justify-between">
          <div>
            <div className="text-[10px] text-zinc-500 uppercase font-semibold">Qdrant Collection</div>
            <div className="text-sm font-semibold text-zinc-200 mt-0.5 mono">
              {health?.qdrant_collection || "evidence_items"}
            </div>
          </div>
          <div className="w-8 h-8 rounded bg-emerald-950/40 border border-emerald-800/40 flex items-center justify-center text-emerald-400">
            <Database className="w-4 h-4" />
          </div>
        </div>

        <div className="card-surface p-3.5 flex items-center justify-between">
          <div>
            <div className="text-[10px] text-zinc-500 uppercase font-semibold">Vector Dimension</div>
            <div className="text-sm font-semibold text-zinc-200 mt-0.5 mono">
              {String(config?.embedding_dimension || 384)} Dim (Dense)
            </div>
          </div>
          <div className="w-8 h-8 rounded bg-indigo-950/40 border border-indigo-800/40 flex items-center justify-center text-indigo-400">
            <Layers className="w-4 h-4" />
          </div>
        </div>

        <div className="card-surface p-3.5 flex items-center justify-between">
          <div>
            <div className="text-[10px] text-zinc-500 uppercase font-semibold">Distance Metric</div>
            <div className="text-sm font-semibold text-zinc-200 mt-0.5 mono">Cosine Similarity</div>
          </div>
          <div className="w-8 h-8 rounded bg-amber-950/40 border border-amber-800/40 flex items-center justify-center text-amber-400">
            <Activity className="w-4 h-4" />
          </div>
        </div>

        <div className="card-surface p-3.5 flex items-center justify-between">
          <div>
            <div className="text-[10px] text-zinc-500 uppercase font-semibold">Embedding Engine</div>
            <div className="text-sm font-semibold text-zinc-200 mt-0.5 truncate max-w-[150px]">
              {health?.embedding_model || "FastEmbed BGE"}
            </div>
          </div>
          <div className="w-8 h-8 rounded bg-purple-950/40 border border-purple-800/40 flex items-center justify-center text-purple-400">
            <Cpu className="w-4 h-4" />
          </div>
        </div>
      </div>

      {/* Details Grid */}
      <div className="flex-1 grid grid-cols-12 gap-3 min-h-0 overflow-hidden">
        {/* Left: Engine Config */}
        <div className="col-span-12 lg:col-span-6 card-surface p-3.5 flex flex-col min-h-0">
          <div className="text-xs font-semibold text-zinc-300 mb-3 flex items-center gap-1.5 shrink-0">
            <Server className="w-3.5 h-3.5 text-zinc-400" />
            Active Vector Architecture & Pipeline Configurations
          </div>

          <div className="space-y-2.5 text-xs overflow-y-auto scrollbar-thin flex-1 pr-1">
            <div className="p-2.5 rounded bg-[#09090b] border border-[#27272a] flex justify-between items-center">
              <span className="text-zinc-400">Primary Inference LLM</span>
              <span className="font-mono text-zinc-200 text-[11px] bg-zinc-800/80 px-2 py-0.5 rounded border border-zinc-700">
                {health?.groq_model || "llama-3.3-70b-versatile"}
              </span>
            </div>

            <div className="p-2.5 rounded bg-[#09090b] border border-[#27272a] flex justify-between items-center">
              <span className="text-zinc-400">Speech-to-Text Whisper Model</span>
              <span className="font-mono text-zinc-200 text-[11px] bg-zinc-800/80 px-2 py-0.5 rounded border border-zinc-700">
                {health?.whisper_model || "whisper-large-v3"}
              </span>
            </div>

            <div className="p-2.5 rounded bg-[#09090b] border border-[#27272a] flex justify-between items-center">
              <span className="text-zinc-400">Frame Sample Interval</span>
              <span className="font-mono text-zinc-200 text-[11px]">
                {String(config?.frame_sample_interval || 2.0)}s
              </span>
            </div>

            <div className="p-2.5 rounded bg-[#09090b] border border-[#27272a] flex justify-between items-center">
              <span className="text-zinc-400">Scene Change Sensitivity</span>
              <span className="font-mono text-zinc-200 text-[11px]">
                {String(config?.scene_change_threshold || 0.35)}
              </span>
            </div>

            <div className="p-2.5 rounded bg-[#09090b] border border-[#27272a] flex justify-between items-center">
              <span className="text-zinc-400">Max Important Frames / Source</span>
              <span className="font-mono text-zinc-200 text-[11px]">
                {String(config?.max_important_frames || 20)}
              </span>
            </div>

            <div className="p-2.5 rounded bg-[#09090b] border border-[#27272a] flex flex-col gap-1">
              <span className="text-zinc-400">Storage Root Path</span>
              <span className="font-mono text-zinc-400 text-[10px] break-all bg-[#121215] p-1.5 rounded border border-zinc-800">
                {health?.storage_path || "c:\\CS\\CS Projects\\Web-Projects\\Hackathon\\backend\\storage"}
              </span>
            </div>
          </div>
        </div>

        {/* Right: Payload Schema Viewer */}
        <div className="col-span-12 lg:col-span-6 card-surface p-3.5 flex flex-col min-h-0">
          <div className="text-xs font-semibold text-zinc-300 mb-3 flex items-center justify-between shrink-0">
            <span className="flex items-center gap-1.5">
              <Box className="w-3.5 h-3.5 text-zinc-400" />
              Qdrant Payload Schema Specification
            </span>
            <span className="text-[10px] text-emerald-400 font-mono flex items-center gap-1">
              <ShieldCheck className="w-3 h-3" /> Zero-Loss Provenance
            </span>
          </div>

          <div className="bg-[#09090b] border border-[#27272a] rounded p-3 text-[11px] font-mono text-zinc-300 overflow-y-auto scrollbar-thin flex-1 leading-relaxed">
            <pre className="text-emerald-400/90 mb-2">{"// Point Struct stored in Qdrant with 384-dim dense vector"}</pre>
            <pre className="text-zinc-300">{`{
  "id": "uuid4 (Evidence ID)",
  "vector": [0.034, -0.012, 0.089, ... 384 dimensions],
  "payload": {
    "source_id": "UUID -> Parent Source",
    "modality": "audio | visual | text | ocr | multimodal",
    "content": "Raw transcript or extracted chunk text",
    "confidence": 0.95,
    "timestamp_start": 20.0,
    "timestamp_end": 40.0,
    "page_number": 4,
    "speaker": "Sarah Chen",
    "entities": ["Redis", "PostgreSQL", "Latency"],
    "relationship_ids": ["uuid-link-1", "uuid-link-2"]
  }
}`}</pre>
          </div>
        </div>
      </div>
    </div>
  );
}
