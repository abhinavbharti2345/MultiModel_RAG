import { useState, useEffect } from "react";
import { api } from "../api";
import type { SourceResponse, EvidenceResponse } from "../types";
import { GitFork, Search, Sparkles, Layers, ArrowRight, Video, Mic, FileText, Image as ImageIcon } from "lucide-react";

interface Props {
  sources: SourceResponse[];
}

export function GraphExplorer({ sources }: Props) {
  const [selectedSourceId, setSelectedSourceId] = useState<string>(sources[0]?.id || "");
  const [searchQuery, setSearchQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [graphEvidence, setGraphEvidence] = useState<EvidenceResponse[]>([]);
  const [selectedEvidence, setSelectedEvidence] = useState<EvidenceResponse | null>(null);
  const [relatedLinks, setRelatedLinks] = useState<EvidenceResponse[]>([]);

  useEffect(() => {
    if (!selectedSourceId && sources.length > 0) {
      setSelectedSourceId(sources[0].id);
    }
  }, [sources, selectedSourceId]);

  async function handleFindConnections() {
    if (!searchQuery.trim()) return;
    setLoading(true);
    try {
      const hits = await api.queryEvidenceOnly(searchQuery, { topK: 12, expandRelationships: true });
      const evs = hits.map(h => h.evidence);
      setGraphEvidence(evs);
      if (evs.length > 0) {
        setSelectedEvidence(evs[0]);
        if (hits[0].related_evidence) {
          setRelatedLinks(hits[0].related_evidence);
        }
      }
    } catch {
      // fallback
    } finally {
      setLoading(false);
    }
  }

  async function selectNode(ev: EvidenceResponse) {
    setSelectedEvidence(ev);
    try {
      const related = await api.getRelatedEvidence(ev.id);
      setRelatedLinks(related);
    } catch {
      setRelatedLinks([]);
    }
  }

  function getModalityIcon(modality: string) {
    switch (modality) {
      case "video":
      case "visual":
        return <ImageIcon className="w-3.5 h-3.5 text-purple-400" />;
      case "audio":
        return <Mic className="w-3.5 h-3.5 text-amber-400" />;
      case "pdf":
      case "text":
        return <FileText className="w-3.5 h-3.5 text-emerald-400" />;
      default:
        return <Layers className="w-3.5 h-3.5 text-indigo-400" />;
    }
  }

  return (
    <div className="flex-1 flex flex-col h-full gap-3 overflow-hidden">
      {/* Search Header */}
      <div className="card-surface p-3 flex items-center justify-between gap-3 shrink-0">
        <div className="flex items-center gap-2">
          <GitFork className="w-4 h-4 text-indigo-400" />
          <span className="text-xs font-semibold text-zinc-100">Cross-Modal Relationship Graph (≤1 Hop Expansion)</span>
        </div>
        <div className="flex items-center gap-2 max-w-md w-full">
          <div className="flex-1 flex items-center gap-2 bg-[#09090b] px-3 py-1.5 rounded border border-[#27272a]">
            <Search className="w-3.5 h-3.5 text-zinc-400" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleFindConnections()}
              placeholder="Filter graph by entity (e.g. Redis, latency, diagram)..."
              className="bg-transparent text-xs text-zinc-100 placeholder-zinc-500 focus:outline-none w-full"
            />
          </div>
          <button
            onClick={handleFindConnections}
            disabled={loading || !searchQuery.trim()}
            className="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-xs font-semibold text-white rounded transition flex items-center gap-1.5 shrink-0"
          >
            <Sparkles className="w-3 h-3" />
            Traverse
          </button>
        </div>
      </div>

      {/* Main Graph Grid */}
      <div className="flex-1 grid grid-cols-12 gap-3 min-h-0 overflow-hidden">
        {/* Left: Nodes List */}
        <div className="col-span-12 lg:col-span-4 card-surface p-3 flex flex-col min-h-0">
          <div className="text-xs font-semibold text-zinc-300 mb-2 flex items-center justify-between shrink-0">
            <span>Discovered Evidence Nodes ({graphEvidence.length})</span>
            <span className="text-[10px] text-zinc-500 font-mono">AST + Cross-Modal</span>
          </div>

          <div className="space-y-2 overflow-y-auto scrollbar-thin flex-1 pr-1">
            {graphEvidence.length === 0 && (
              <div className="text-center text-xs text-zinc-500 py-12">
                Type an entity or topic above and click <strong>Traverse</strong> to explore interconnected video, audio, and PDF nodes.
              </div>
            )}
            {graphEvidence.map((ev) => {
              const isSelected = selectedEvidence?.id === ev.id;
              return (
                <div
                  key={ev.id}
                  onClick={() => selectNode(ev)}
                  className={`p-2.5 rounded border cursor-pointer transition ${
                    isSelected
                      ? "bg-indigo-950/40 border-indigo-500/60 text-zinc-100"
                      : "bg-[#09090b] border-[#27272a] hover:border-zinc-700 text-zinc-300"
                  }`}
                >
                  <div className="flex items-center justify-between text-[11px] mb-1">
                    <span className="flex items-center gap-1.5 font-medium capitalize">
                      {getModalityIcon(ev.modality)}
                      {ev.modality} Node
                    </span>
                    <span className="text-[10px] mono text-zinc-400">id: {ev.id.slice(0, 8)}</span>
                  </div>
                  <div className="text-[11px] text-zinc-400 line-clamp-2">
                    {ev.content}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Center: Selected Node Focus */}
        <div className="col-span-12 lg:col-span-4 card-surface p-3 flex flex-col min-h-0">
          <div className="text-xs font-semibold text-zinc-300 mb-2 shrink-0">Node Inspector</div>
          {selectedEvidence ? (
            <div className="flex-1 flex flex-col justify-between overflow-y-auto scrollbar-thin bg-[#09090b] p-3 rounded border border-[#27272a]">
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-indigo-900/40 border border-indigo-700/50 text-indigo-300 capitalize flex items-center gap-1.5">
                    {getModalityIcon(selectedEvidence.modality)}
                    {selectedEvidence.modality}
                  </span>
                  <span className="text-[10px] text-zinc-500 mono">Confidence: {selectedEvidence.confidence.toFixed(2)}</span>
                </div>

                <div>
                  <div className="text-[10px] uppercase font-semibold text-zinc-400 mb-1">Content Payload</div>
                  <div className="text-xs text-zinc-200 bg-[#121215] p-2.5 rounded border border-zinc-800 leading-relaxed">
                    {selectedEvidence.content}
                  </div>
                </div>

                {selectedEvidence.entities && selectedEvidence.entities.length > 0 && (
                  <div>
                    <div className="text-[10px] uppercase font-semibold text-zinc-400 mb-1">Extracted Entities</div>
                    <div className="flex flex-wrap gap-1">
                      {selectedEvidence.entities.map((e, idx) => (
                        <span key={idx} className="px-1.5 py-0.5 rounded bg-zinc-800 border border-zinc-700 text-[10px] text-zinc-300">
                          #{e}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              <div className="pt-2 mt-2 border-t border-zinc-800 text-[10px] text-zinc-500 flex justify-between">
                <span>Source ID: {selectedEvidence.source_id.slice(0, 8)}…</span>
                <span>{selectedEvidence.page_number ? `Page ${selectedEvidence.page_number}` : selectedEvidence.timestamp_start ? `${selectedEvidence.timestamp_start}s` : 'Raw Text'}</span>
              </div>
            </div>
          ) : (
            <div className="flex-1 flex items-center justify-center text-xs text-zinc-500 border border-dashed border-zinc-800 rounded">
              Select a node to inspect payload and relationships.
            </div>
          )}
        </div>

        {/* Right: Connected Graph Neighbors (1-Hop) */}
        <div className="col-span-12 lg:col-span-4 card-surface p-3 flex flex-col min-h-0">
          <div className="text-xs font-semibold text-zinc-300 mb-2 flex items-center justify-between shrink-0">
            <span>Linked Edges (≤1 Hop)</span>
            <span className="text-[10px] text-indigo-400 mono">{relatedLinks.length} Connections</span>
          </div>

          <div className="space-y-2 overflow-y-auto scrollbar-thin flex-1 pr-1">
            {relatedLinks.length === 0 && (
              <div className="text-center text-xs text-zinc-500 py-12">
                No immediate 1-hop cross-modal edges found for this node.
              </div>
            )}
            {relatedLinks.map((rel) => (
              <div
                key={rel.id}
                onClick={() => selectNode(rel)}
                className="p-2.5 rounded bg-[#09090b] border border-[#27272a] hover:border-indigo-500/50 cursor-pointer transition"
              >
                <div className="flex items-center justify-between text-[10px] mb-1">
                  <span className="text-indigo-400 font-semibold flex items-center gap-1">
                    <ArrowRight className="w-3 h-3 text-zinc-500" />
                    Cross-modal link
                  </span>
                  <span className="capitalize text-zinc-400">{rel.modality}</span>
                </div>
                <div className="text-[11px] text-zinc-300 line-clamp-2">
                  {rel.content}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
