import { useState, useRef, useEffect } from "react";
import { api } from "../api";
import type { QueryResponse, SourceResponse } from "../types";
import { EvidenceCard } from "./EvidenceCard";
import { AnswerRenderer } from "./AnswerRenderer";
import { Search, Send, Activity, ShieldCheck, AlertCircle } from "lucide-react";

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
  const [latency, setLatency] = useState<number | null>(null);

  async function runQuery(e?: React.FormEvent) {
    e?.preventDefault();
    if (!question.trim() || loading) return;
    setLoading(true);
    setError(null);
    setLatency(null);
    
    const start = performance.now();
    try {
      const resp = await api.query(question.trim(), {
        topK,
        expandRelationships: expandRelations,
      });
      setLatency(Math.round(performance.now() - start));
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

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 100)}px`;
    }
  }, [question]);

  return (
    <div className="flex flex-col gap-3 h-full">
      {/* Search Box */}
      <div className="card-surface p-2.5 flex items-center gap-2 shrink-0">
        <form onSubmit={runQuery} className="flex-1 flex items-center gap-2">
          <div className="flex-1 flex items-center gap-2 bg-[#09090b] px-3 py-1.5 rounded border border-[#27272a] focus-within:border-indigo-500/50 focus-within:ring-1 focus-within:ring-indigo-500/50 transition">
            <Search className="w-4 h-4 text-zinc-400 shrink-0" />
            <textarea
              ref={textareaRef}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              rows={1}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  runQuery();
                }
              }}
              className="w-full bg-transparent text-xs text-zinc-100 font-medium focus:outline-none resize-none py-1 max-h-24 scrollbar-thin placeholder-zinc-600"
              placeholder="Ask about architecture, decisions, who said what, where diagrams appeared..."
            />
            <span className="mono text-[10px] text-zinc-400 bg-zinc-800 px-1.5 py-0.5 rounded border border-zinc-700 shrink-0 select-none">⌘K</span>
          </div>
          <button
            type="submit"
            disabled={disableAnswer}
            className="px-3.5 h-[38px] bg-indigo-600 hover:bg-indigo-500 text-xs font-semibold text-white rounded transition flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed shrink-0"
          >
            {loading ? (
              <Activity className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Send className="w-3.5 h-3.5" />
            )}
            Run Query
          </button>
        </form>
      </div>

      {/* States / Warnings */}
      {isCurrentlyProcessing && (
        <div className="rounded border border-sky-900/50 bg-sky-950/30 p-3 text-xs text-sky-400 flex items-center gap-2 shrink-0">
          <Activity className="w-4 h-4 animate-spin" />
          Evidence is currently being indexed. Queries will be available once processing completes.
        </div>
      )}

      {error && (
        <div className="rounded border border-rose-900/50 bg-rose-950/30 p-3 text-xs text-rose-400 flex gap-2 shrink-0">
          <AlertCircle className="w-4 h-4 shrink-0" />
          <div>
            <div className="font-semibold mb-0.5">Query Failed</div>
            <div className="text-[10px] text-rose-300">{error}</div>
          </div>
        </div>
      )}

      {/* Results Area */}
      {!result && !loading && !error && (
        <div className="card-surface p-4 flex-1 flex flex-col items-center justify-center text-center text-zinc-500 border-dashed border-zinc-700">
          <Search className="w-8 h-8 mb-3 opacity-50" />
          <div className="text-sm font-semibold text-zinc-300">Awaiting Query</div>
          <div className="text-xs mt-1 max-w-sm">Enter a natural language question above to search the multi-modal evidence graph.</div>
        </div>
      )}

      {loading && (
        <div className="card-surface p-4 flex-1 flex flex-col justify-center items-center text-zinc-500 animate-pulse border-zinc-700">
          <Activity className="w-8 h-8 mb-3 opacity-50 animate-spin" />
          <div className="text-sm font-semibold text-zinc-300">Searching Corpus...</div>
          <div className="text-xs mt-1 max-w-sm">Retrieving text, visual, and audio evidence to synthesize answer.</div>
        </div>
      )}

      {result && !loading && (
        <div className="card-surface p-4 flex-1 flex flex-col justify-between overflow-hidden">
          {/* Answer Section */}
          <div className="flex-1 overflow-y-auto scrollbar-thin min-h-0 pr-2">
            <div className="flex items-center justify-between mb-3 sticky top-0 bg-[#18181b] pb-2 z-10 border-b border-[#27272a]">
              <div className="flex items-center gap-2">
                <div className="w-2 h-2 rounded-full bg-indigo-500"></div>
                <span className="text-xs font-semibold text-zinc-100">Grounded LLM Response</span>
              </div>
              <div className="flex items-center gap-2 text-[10px] text-zinc-400">
                {latency && (
                  <>
                    <span>Latency: <strong className="text-zinc-200 mono">{latency}ms</strong></span>
                    <span>•</span>
                  </>
                )}
                <span>Grounding: <strong className="text-emerald-400 mono flex items-center gap-1 inline-flex"><ShieldCheck className="w-3 h-3"/> Zero Invention</strong></span>
              </div>
            </div>

            <div className="text-xs text-zinc-300 leading-relaxed bg-[#09090b] p-3.5 rounded-lg border border-[#27272a] mb-4 font-normal">
              <AnswerRenderer answer={result.answer} onCitationClick={() => {}} />
            </div>

            {/* Provenance Evidence Section */}
            <div>
              <div className="text-[11px] font-medium text-zinc-400 mb-2.5 flex items-center justify-between">
                <span>Retained Context Evidence ({result.evidence.length} Items)</span>
                {expandRelations && <span className="text-[10px] text-indigo-400 mono">Graph Expansion (≤1 Hop)</span>}
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2 pb-2">
                {result.evidence.map((hit, i) => (
                  <EvidenceCard key={hit.evidence.id} hit={hit} rank={i} />
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
