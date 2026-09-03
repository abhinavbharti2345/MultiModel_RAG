import { useState } from "react";
import type { SourceResponse } from "../types";
import { UploadPanel } from "./UploadPanel";
import { SourcesList } from "./SourcesList";
import { Folder, HardDrive, FileSpreadsheet, Eye } from "lucide-react";

interface Props {
  sources: SourceResponse[];
  summary: Record<string, Record<string, unknown>>;
  refreshNonce: number;
  onUploaded: () => void;
}

export function SourcesExplorer({ sources, summary, refreshNonce, onUploaded }: Props) {
  const [selectedSourceId, setSelectedSourceId] = useState<string | null>(sources[0]?.id || null);

  const selectedSource = sources.find(s => s.id === selectedSourceId);
  const selectedSummary = selectedSourceId ? summary[selectedSourceId] : null;

  return (
    <div className="flex-1 flex flex-col h-full gap-3 overflow-hidden">
      {/* Header */}
      <div className="card-surface p-3 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-2">
          <Folder className="w-4 h-4 text-indigo-400" />
          <span className="text-xs font-semibold text-zinc-100">Ingested Multi-Modal Corpus & Evidence Index</span>
        </div>
        <div className="flex items-center gap-3 text-xs text-zinc-400">
          <span className="flex items-center gap-1.5">
            <HardDrive className="w-3.5 h-3.5 text-zinc-500" />
            <span>Total Sources: <strong className="text-zinc-200">{sources.length}</strong></span>
          </span>
        </div>
      </div>

      {/* Main Grid */}
      <div className="flex-1 grid grid-cols-12 gap-3 min-h-0 overflow-hidden">
        {/* Left Column: Upload & List */}
        <div className="col-span-12 lg:col-span-5 flex flex-col gap-3 min-h-0 h-full">
          <UploadPanel onUploaded={onUploaded} />
          <SourcesList
            refreshNonce={refreshNonce}
            selectedSourceId={selectedSourceId}
            onSelect={setSelectedSourceId}
          />
        </div>

        {/* Right Column: Source Detail Inspector */}
        <div className="col-span-12 lg:col-span-7 card-surface p-4 flex flex-col min-h-0 h-full">
          <div className="text-xs font-semibold text-zinc-200 mb-3 flex items-center justify-between shrink-0 pb-2 border-b border-[#27272a]">
            <span className="flex items-center gap-1.5">
              <Eye className="w-3.5 h-3.5 text-indigo-400" />
              Source Details & Ingestion Diagnostics
            </span>
            {selectedSource && (
              <span className="mono text-[10px] text-zinc-400">ID: {selectedSource.id}</span>
            )}
          </div>

          {selectedSource ? (
            <div className="flex-1 overflow-y-auto scrollbar-thin space-y-3 pr-1">
              <div className="p-3 bg-[#09090b] rounded border border-[#27272a] space-y-2">
                <div className="flex justify-between items-center">
                  <span className="text-sm font-semibold text-zinc-100">{selectedSource.name}</span>
                  <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-zinc-800 text-zinc-300 border border-zinc-700 capitalize">
                    {selectedSource.source_type}
                  </span>
                </div>
                <div className="text-xs text-zinc-400">
                  {typeof selectedSource.metadata?.description === "string"
                    ? selectedSource.metadata.description
                    : "No description provided."}
                </div>
              </div>

              {selectedSummary && (
                <div className="grid grid-cols-3 gap-2">
                  <div className="p-3 bg-[#09090b] rounded border border-[#27272a] text-center">
                    <div className="text-[10px] text-zinc-500 uppercase font-semibold">Evidence Chunks</div>
                    <div className="text-lg font-bold text-indigo-400 mt-1">
                      {String(selectedSummary.total_evidence ?? 0)}
                    </div>
                  </div>
                  <div className="p-3 bg-[#09090b] rounded border border-[#27272a] text-center">
                    <div className="text-[10px] text-zinc-500 uppercase font-semibold">Keyframes Sampled</div>
                    <div className="text-lg font-bold text-purple-400 mt-1">
                      {String(selectedSummary.frames_important ?? selectedSummary.frames_total ?? 0)}
                    </div>
                  </div>
                  <div className="p-3 bg-[#09090b] rounded border border-[#27272a] text-center">
                    <div className="text-[10px] text-zinc-500 uppercase font-semibold">Ingestion Status</div>
                    <div className="text-sm font-semibold text-emerald-400 mt-1 capitalize">
                      {selectedSource.status.replace("_", " ")}
                    </div>
                  </div>
                </div>
              )}

              <div className="p-3 bg-[#09090b] rounded border border-[#27272a] text-xs space-y-2">
                <div className="font-semibold text-zinc-300">File Ingestion Metadata</div>
                <div className="grid grid-cols-2 gap-2 text-zinc-400 text-[11px] mono">
                  <div>Created: {new Date(selectedSource.created_at).toLocaleString()}</div>
                  <div>Size: {selectedSource.file_size ? `${Math.round(selectedSource.file_size / 1024)} KB` : "N/A"}</div>
                  <div>Content Type: {selectedSource.mime_type || "N/A"}</div>
                  <div>Duration: {selectedSource.duration_seconds ? `${selectedSource.duration_seconds}s` : "N/A"}</div>
                </div>
              </div>
            </div>
          ) : (
            <div className="flex-1 flex flex-col items-center justify-center text-zinc-500 text-xs text-center border border-dashed border-zinc-800 rounded">
              <FileSpreadsheet className="w-8 h-8 mb-2 opacity-40" />
              <div>Select a source file from the active corpus to inspect its ingested chunks, keyframes, and diagnostics.</div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
