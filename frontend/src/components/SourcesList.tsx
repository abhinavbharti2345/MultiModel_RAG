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

  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm h-full flex flex-col">
      <div className="px-5 py-4 border-b border-slate-100 flex items-center justify-between">
        <div>
          <h2 className="font-semibold text-slate-900">Media library</h2>
          <p className="text-xs text-slate-500 mt-0.5">
            {sorted.length} source{sorted.length === 1 ? "" : "s"} · processing status auto-refreshes
          </p>
        </div>
        <button
          onClick={async () => {
            if (confirm("Clear all sources and evidence?")) {
              await api.clearAllSources();
              window.location.reload();
            }
          }}
          className="text-xs px-3 py-1.5 rounded-lg border border-rose-200 text-rose-600 hover:bg-rose-50"
        >
          Clear
        </button>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto scrollbar-thin divide-y divide-slate-100">
        {loading && sorted.length === 0 && (
          <div className="p-8 text-center text-sm text-slate-500">Loading…</div>
        )}
        {!loading && sorted.length === 0 && (
          <div className="p-8 text-center text-sm text-slate-500">
            Nothing uploaded yet. Start by dropping a video or PDF above.
          </div>
        )}

        {sorted.map((s) => {
          const sum = summary[s.id];
          const selected = s.id === selectedSourceId;
          return (
            <button
              key={s.id}
              onClick={() => onSelect(selected ? null : s.id)}
              className={`w-full text-left px-5 py-4 transition hover:bg-slate-50
                ${selected ? "bg-brand-50/50 hover:bg-brand-50" : ""}`}
            >
              <div className="flex items-start gap-3">
                <div className="mt-0.5">
                  <SourceTypeBadge type={s.source_type} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between gap-2">
                    <div className="truncate font-medium text-slate-900">{s.name}</div>
                    <div className="flex items-center gap-2">
                      <StatusBadge status={s.status} />
                      <button
                        onClick={async (e) => {
                          e.stopPropagation();
                          if (confirm(`Delete source "${s.name}"?`)) {
                            await api.deleteSource(s.id);
                            window.location.reload();
                          }
                        }}
                        className="text-slate-400 hover:text-rose-600 transition-colors p-1 rounded-md hover:bg-rose-50"
                        title="Delete source"
                      >
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                        </svg>
                      </button>
                    </div>
                  </div>
                  <div className="mt-1 text-xs text-slate-500 flex flex-wrap items-center gap-x-3 gap-y-0.5">
                    {s.duration_seconds !== undefined && s.duration_seconds > 0 && (
                      <span>⏱ {formatSeconds(s.duration_seconds)}</span>
                    )}
                    {s.page_count !== undefined && s.page_count > 0 && (
                      <span>📄 {s.page_count} page{s.page_count === 1 ? "" : "s"}</span>
                    )}
                    {s.file_size !== undefined && <span>{formatBytes(s.file_size)}</span>}
                    <span className="opacity-70">
                      {new Date(s.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                    </span>
                  </div>

                  <div className="mt-2 space-y-1.5">
                    <ProgressBar value={s.progress_percent} status={s.status} />
                    {sum && (
                      <div className="text-xs text-slate-500 flex flex-wrap gap-x-3">
                        <span>{String(sum.total_evidence ?? 0)} evidence records</span>
                        {sum.evidence_by_modality ? (
                          Object.entries(sum.evidence_by_modality as Record<string, number>).map(
                            ([k, v]) => (
                              <span key={k}>
                                {k}: {v}
                              </span>
                            ),
                          )
                        ) : null}
                        <span>
                          {String(sum.frames_important ?? 0)}/{String(sum.frames_total ?? 0)} key frames
                        </span>
                      </div>
                    )}
                    {!sum && s.status_message && s.status !== "completed" && (
                      <div className="text-xs text-slate-500 truncate">{s.status_message}</div>
                    )}
                  </div>
                </div>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
