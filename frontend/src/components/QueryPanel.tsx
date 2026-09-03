import { useState, useRef, useEffect } from "react";
import { api } from "../api";
import type { QueryResponse, SourceResponse } from "../types";
import { EvidenceCard } from "./EvidenceCard";
import { AnswerRenderer } from "./AnswerRenderer";

interface Props {
  sources?: SourceResponse[];
  summaries?: Record<string, Record<string, unknown>>;
}

export function QueryPanel({ sources = [], summaries = {} }: Props) {
  const [question, setQuestion] = useState("");
  const [topK, setTopK] = useState(10);
  const [expandRelations, setExpandRelations] = useState(true);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<QueryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"answer" | "evidence">("answer");

  async function runQuery(e?: React.FormEvent) {
    e?.preventDefault();
    if (!question.trim() || loading) return;
    setLoading(true);
    setError(null);
    setActiveTab("answer");
    try {
      const resp = await api.query(question.trim(), {
        topK,
        expandRelationships: expandRelations,
      });
      setResult(resp);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Query failed");
      setResult(null);
    } finally {
      setLoading(false);
    }
  }

  const isCurrentlyProcessing = sources.length > 0 && sources.every(s => !["completed", "failed"].includes(s.status));
  const disableAnswer = loading || !question.trim() || isCurrentlyProcessing;



  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-resize textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 200)}px`;
    }
  }, [question]);

  return (
    <div className="flex flex-col gap-4">
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm mb-4">
        <div className="px-5 py-4 border-b border-slate-100">
          <h2 className="font-semibold text-slate-900">Ask the evidence</h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Questions are answered only from indexed evidence, with grounded provenance.
          </p>
        </div>
        <form onSubmit={runQuery} className="p-5 space-y-3">
          <textarea
            ref={textareaRef}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            rows={2}
            className="w-full resize-none rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400 focus:border-brand-400 overflow-y-auto transition-all"
            placeholder="Ask about architecture, decisions, who said what, where diagrams appeared…"
          />

          <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
            <div className="flex items-center gap-2 text-sm">
              <label className="text-slate-500">Top-K</label>
              <input
                type="number"
                min={1}
                max={30}
                value={topK}
                onChange={(e) => setTopK(Math.max(1, Math.min(30, Number(e.target.value) || 10)))}
                className="w-16 rounded border border-slate-300 px-2 py-1 text-sm"
              />
            </div>
            <label className="flex items-center gap-2 text-sm text-slate-700 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={expandRelations}
                onChange={(e) => setExpandRelations(e.target.checked)}
                className="rounded border-slate-300 text-brand-600 focus:ring-brand-500"
              />
              Expand cross-modal relationships
            </label>

            <div className="ml-auto flex items-center gap-2">
              <button
                type="button"
                onClick={() => setResult(null)}
                className="px-3 py-1.5 text-sm rounded-lg border border-slate-300 text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                disabled={loading}
              >
                Clear
              </button>
              <button
                type="submit"
                className="px-4 py-1.5 text-sm font-medium rounded-lg bg-brand-600 text-white hover:bg-brand-700 shadow-sm disabled:opacity-60 disabled:cursor-not-allowed flex items-center gap-2"
                disabled={disableAnswer}
              >
                {loading ? (
                  <>
                    <span className="inline-block w-3.5 h-3.5 border-2 border-white/60 border-t-white rounded-full animate-spin" />
                    Retrieving…
                  </>
                ) : (
                  <>
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <circle cx="11" cy="11" r="8" />
                      <path d="m21 21-4.3-4.3" />
                    </svg>
                    Answer
                  </>
                )}
              </button>
            </div>
          </div>

        </form>
      </div>

      {isCurrentlyProcessing && (
        <div className="mb-4 rounded-lg bg-sky-50 border border-sky-200 p-4 text-sm text-sky-800 flex items-center gap-3">
          <span className="inline-block w-4 h-4 border-2 border-sky-300 border-t-sky-700 rounded-full animate-spin" />
          <span>Evidence is currently being indexed. Queries will be available once processing completes.</span>
        </div>
      )}

      {error && (
        <div className={`mb-4 rounded-lg border p-4 text-sm ${error.includes('429') ? 'bg-amber-50 border-amber-200 text-amber-800' : 'bg-rose-50 border-rose-200 text-rose-800'}`}>
          {error.includes('429') ? (
            <div>
              <div className="font-semibold text-amber-900 mb-1 flex items-center gap-2">
                <span>⚠️</span> AI Service temporarily unavailable
              </div>
              <p className="mb-2">The AI service is currently rate-limited.</p>
              <p className="mb-3 text-amber-700">Your uploaded documents, videos, and indexed data are completely safe.</p>
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={runQuery}
                  className="px-4 py-1.5 bg-amber-100 hover:bg-amber-200 text-amber-900 rounded font-medium transition"
                >
                  Retry Now
                </button>
                <span className="text-amber-700 text-xs italic">{error}</span>
              </div>
            </div>
          ) : (
            error
          )}
        </div>
      )}

      {result && !loading && (
        <div className="space-y-6">
          <div className="flex border-b border-slate-200">
            <button
              onClick={() => setActiveTab("answer")}
              className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
                activeTab === "answer"
                  ? "border-brand-500 text-brand-600"
                  : "border-transparent text-slate-500 hover:text-slate-700 hover:border-slate-300"
              }`}
            >
              Answer
            </button>
            <button
              onClick={() => setActiveTab("evidence")}
              className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
                activeTab === "evidence"
                  ? "border-brand-500 text-brand-600"
                  : "border-transparent text-slate-500 hover:text-slate-700 hover:border-slate-300"
              }`}
            >
              Evidence Used ({result.evidence.length})
            </button>
          </div>

          {activeTab === "answer" && (
            <div className="rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden">
              <div className="p-5 animate-fade-in bg-white">
                <AnswerRenderer 
                  answer={result.answer} 
                  onCitationClick={() => setActiveTab("evidence")}
                />
              </div>
              {result.provenance_summary && result.provenance_summary.length > 0 && (
                <div className="px-5 pb-5 pt-0 border-t border-slate-100 mt-4">
                  <div className="text-[11px] font-semibold text-slate-500 uppercase tracking-wide mb-3 mt-4">
                    Provenance at a glance
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {result.provenance_summary.map((s, i) => {
                      const isAudio = s.includes("modality=audio");
                      const isVisual = s.includes("modality=visual");
                      const isText = s.includes("modality=text");
                      
                      let colorClass = "bg-slate-50 text-slate-700 border-slate-200";
                      if (isAudio) colorClass = "bg-sky-50 text-sky-700 border-sky-200";
                      if (isVisual) colorClass = "bg-fuchsia-50 text-fuchsia-700 border-fuchsia-200";
                      if (isText) colorClass = "bg-indigo-50 text-indigo-700 border-indigo-200";

                      return (
                        <div key={i} className={`text-xs px-2.5 py-1.5 rounded-md border shadow-sm ${colorClass} max-w-full truncate`} title={s}>
                          {s}
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          )}

          {activeTab === "evidence" && (
            <div className="animate-fade-in">
              <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
                {result.evidence.map((hit, i) => (
                  <EvidenceCard key={hit.evidence.id} hit={hit} rank={i} />
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {loading && (
        <div className="space-y-6 animate-pulse">
          <div className="rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden">
            <div className="px-5 py-3 border-b border-slate-100 bg-slate-50 flex items-center gap-3">
              <div className="w-5 h-5 bg-slate-200 rounded-full"></div>
              <div className="h-4 bg-slate-200 rounded w-1/4"></div>
            </div>
            <div className="p-5 space-y-3">
              <div className="h-3 bg-slate-200 rounded w-3/4"></div>
              <div className="h-3 bg-slate-200 rounded w-full"></div>
              <div className="h-3 bg-slate-200 rounded w-5/6"></div>
              <div className="h-3 bg-slate-200 rounded w-2/3"></div>
            </div>
          </div>
          
          <div>
            <div className="flex items-center justify-between mb-3 px-1">
              <div className="h-4 bg-slate-200 rounded w-1/4"></div>
            </div>
            <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
              {[1, 2, 3, 4].map((i) => (
                <div key={i} className="rounded-xl border border-slate-200 bg-white h-48"></div>
              ))}
            </div>
          </div>
        </div>
      )}

      {!result && !loading && !error && (
        <div className="flex-1 flex items-center justify-center rounded-xl border border-dashed border-slate-200 bg-white/50 text-sm text-slate-500 px-6 py-12 text-center">
          <div>
            <div className="mx-auto w-10 h-10 rounded-full bg-slate-50 text-slate-500 flex items-center justify-center mb-3">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="11" cy="11" r="8" />
                <path d="m21 21-4.3-4.3" />
              </svg>
            </div>
            <p className="font-medium text-slate-700">No query yet</p>
            <p className="mt-1 text-xs max-w-sm mx-auto">
              Upload a video or PDF above, then ask a question. You'll get a grounded answer plus
              a ranked list of transcript, visual, OCR, and document evidence cards.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
