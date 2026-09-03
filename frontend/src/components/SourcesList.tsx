import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type { SourceResponse } from "../types";
import {
  ProgressBar,
  SourceTypeBadge,
  StatusBadge,
  formatBytes,
  formatSeconds,
} from "./Badges";
import { Video, Mic, Image as ImageIcon, FileText, Trash2 } from "lucide-react";

interface Props {
  refreshNonce: number;
  selectedSourceId: string | null;
  onSelect: (id: string | null) => void;
  onSourcesUpdate?: (sources: SourceResponse[], summary: Record<string, Record<string, unknown>>) => void;
}

export function SourcesList({ refreshNonce, selectedSourceId, onSelect, onSourcesUpdate }: Props) {
  const [sources, setSources] = useState<SourceResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [summary, setSummary] = useState<Record<string, Record<string, unknown>>>({});

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api
      .listSources()
      .then((data) => {
        if (cancelled) return;
        setSources(data);
        setLoading(false);
      })
      .catch(() => !cancelled && setLoading(false));

    return () => {
      cancelled = true;
    };
  }, [refreshNonce]);

  useEffect(() => {
    const inProgress = sources.filter((s) => !["completed", "failed", "pending"].includes(s.status));
    if (inProgress.length === 0) return;
    let cancelled = false;

    const interval = setInterval(() => {
      inProgress.forEach((s) => {
        api
          .getSourceStatus(s.id)
          .then((st) => {
            if (cancelled) return;
            setSources((prev) =>
              prev.map((p) =>
                p.id === s.id
                  ? {
                      ...p,
                      status: st.status,
                      status_message: st.status_message ?? p.status_message,
                      progress_percent: st.progress_percent,
                    }
                  : p,
              ),
            );
          })
          .catch(() => undefined);
      });
    }, 1500);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [sources]);

  useEffect(() => {
    const completed = sources.filter((s) => s.status === "completed" && !summary[s.id]);
    if (completed.length === 0) return;
    let cancelled = false;
    completed.forEach((s) => {
      api
        .getEvidenceSummary(s.id)
        .then((data) => !cancelled && setSummary((prev) => ({ ...prev, [s.id]: data as Record<string, unknown> })))
        .catch(() => undefined);
    });
    return () => {
      cancelled = true;
    };
  }, [sources, summary]);

  useEffect(() => {
    if (onSourcesUpdate) {
      onSourcesUpdate(sources, summary);
    }
  }, [sources, summary, onSourcesUpdate]);

  const sorted = useMemo(
    () => [...sources].sort((a, b) => (a.created_at < b.created_at ? 1 : -1)),
    [sources],
  );

  const totalEvidenceRows = Object.values(summary).reduce((acc, curr) => acc + (Number(curr.total_evidence) || 0), 0);

  function getIcon(type: string) {
    switch (type) {
      case "video": return <Video className="w-3.5 h-3.5 text-pink-400" />;
      case "audio": return <Mic className="w-3.5 h-3.5 text-amber-400" />;
      case "image": return <ImageIcon className="w-3.5 h-3.5 text-purple-400" />;
      case "pdf": return <FileText className="w-3.5 h-3.5 text-emerald-400" />;
      default: return <FileText className="w-3.5 h-3.5 text-zinc-400" />;
    }
  }

  return (
    <div className="card-surface p-3 flex-1 flex flex-col justify-between overflow-hidden">
      <div className="flex-1 flex flex-col min-h-0">
        <div className="flex items-center justify-between mb-2.5 shrink-0">
          <span className="text-xs font-semibold text-zinc-300">Active Corpus ({sorted.length} files)</span>
          {sorted.length > 0 && (
            <button
              onClick={async () => {
                if (confirm("Clear all sources and evidence?")) {
                  await api.clearAllSources();
                  window.location.reload();
                }
              }}
              className="text-[10px] text-rose-400 hover:text-rose-300 transition"
            >
              Clear All
            </button>
          )}
        </div>

        <div className="space-y-2 overflow-y-auto scrollbar-thin pr-1 flex-1">
          {loading && sorted.length === 0 && (
            <div className="text-center text-xs text-zinc-500 py-4">Loading corpus...</div>
          )}
          {!loading && sorted.length === 0 && (
            <div className="text-center text-xs text-zinc-500 py-4">
              Nothing uploaded yet.
            </div>
          )}

          {sorted.map((s) => {
            const sum = summary[s.id];
            const selected = s.id === selectedSourceId;
            
            return (
              <div
                key={s.id}
                onClick={() => onSelect(selected ? null : s.id)}
                className={`p-2 rounded cursor-pointer transition border 
                  ${selected ? "bg-[#27272a] border-[#3f3f46]" : "bg-[#27272a]/40 border-[#3f3f46]/40 hover:bg-[#27272a]/70"}`}
              >
                <div className="flex items-center justify-between text-xs">
                  <div className="flex items-center gap-2 overflow-hidden">
                    {getIcon(s.source_type)}
                    <div className="min-w-0">
                      <div className="font-medium text-zinc-200 text-[11px] truncate">{s.name}</div>
                      <div className="text-[9.5px] text-zinc-400 truncate">
                        {s.status === 'completed' && sum ? (
                          <>
                            {s.source_type === 'video' ? `FFmpeg + OpenCV Keyframes (${sum.frames_important ?? 0} frames)` : ''}
                            {s.source_type === 'audio' ? 'Whisper STT' : ''}
                            {s.source_type === 'image' ? 'VLM Diagram OCR' : ''}
                            {s.source_type === 'pdf' ? `pypdf (${sum.total_evidence ?? 0} chunks)` : ''}
                          </>
                        ) : (
                          <span className="capitalize">{s.status.replace('_', ' ')}</span>
                        )}
                      </div>
                    </div>
                  </div>
                  
                  <div className="flex flex-col items-end gap-1 shrink-0">
                    <span className="text-[10px] text-zinc-400 mono flex items-center gap-1.5">
                      {s.status === 'completed' ? (
                        sum ? `${sum.total_evidence ?? 0} evidence` : 'Done'
                      ) : (
                        `${Math.round(s.progress_percent)}%`
                      )}
                      <button
                        onClick={async (e) => {
                          e.stopPropagation();
                          if (confirm(`Delete source "${s.name}"?`)) {
                            await api.deleteSource(s.id);
                            window.location.reload();
                          }
                        }}
                        className="text-zinc-500 hover:text-rose-400"
                        title="Delete source"
                      >
                        <Trash2 className="w-3 h-3" />
                      </button>
                    </span>
                  </div>
                </div>

                {s.status !== "completed" && s.status !== "failed" && (
                  <div className="mt-2">
                    <ProgressBar value={s.progress_percent} status={s.status} />
                    <div className="mt-1 text-[9px] text-zinc-500 truncate">{s.status_message}</div>
                  </div>
                )}
                {s.status === "failed" && (
                  <div className="mt-2 text-[9px] text-rose-400 truncate">{s.status_message}</div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      <div className="pt-2 mt-2 border-t border-[#27272a] text-[10px] text-zinc-400 flex justify-between shrink-0">
        <span>Multi-Modal Indexing</span>
        <span className="text-zinc-300 font-mono">{totalEvidenceRows} Evidence Rows</span>
      </div>
    </div>
  );
}
