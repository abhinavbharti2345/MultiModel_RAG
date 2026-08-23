import { useState, useEffect } from "react";
import type { EvidenceWithScore, EvidenceResponse } from "../types";
import { ModalityBadge, formatSeconds } from "./Badges";

interface Props {
  hit: EvidenceWithScore;
  rank: number;
}

function EvidenceMeta({ ev }: { ev: EvidenceResponse }) {
  const items: string[] = [];
  if (ev.timestamp_start !== undefined) {
    const end = ev.timestamp_end !== undefined && ev.timestamp_end !== ev.timestamp_start;
    items.push(`⏱ ${formatSeconds(ev.timestamp_start)}${end ? "–" + formatSeconds(ev.timestamp_end) : ""}`);
  }
  if (ev.page_number !== undefined && ev.page_number !== null) {
    items.push(`📄 p. ${ev.page_number}`);
  }
  if (ev.speaker) {
    items.push(`🎙 ${ev.speaker}`);
  }
  items.push(`score ${ev.confidence.toFixed(2)}`);
  return (
    <div className="text-xs text-slate-500 flex flex-wrap items-center gap-x-3 gap-y-0.5">
      {items.map((it) => (
        <span key={it}>{it}</span>
      ))}
    </div>
  );
}

export function EvidenceCard({ hit, rank }: Props) {
  const { evidence, similarity_score, related_evidence, related_frames } = hit;
  const [lightboxImage, setLightboxImage] = useState<string | null>(null);

  // Give the card an ID for smooth scrolling from citations
  return (
    <div id={`evidence-${evidence.id}`} className="rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden animate-fade-in scroll-mt-24">
      <div className="px-4 py-3 border-b border-slate-100 flex items-center justify-between gap-3 bg-slate-50/50">
        <div className="flex items-center gap-2 min-w-0">
          <span className="inline-flex w-6 h-6 rounded-full bg-white text-white items-center justify-center text-[11px] font-semibold">
            {rank + 1}
          </span>
          <ModalityBadge modality={evidence.modality} />
          <span className="text-xs text-slate-500 font-medium truncate">
            evidence {evidence.id.slice(0, 8)}…
          </span>
        </div>
        <div className="text-xs text-slate-500 whitespace-nowrap">
          similarity <span className="font-semibold text-slate-700">{(similarity_score * 100).toFixed(0)}%</span>
        </div>
      </div>

      <div className="p-4 space-y-3">
        <EvidenceMeta ev={evidence} />

        {related_frames.length > 0 && (
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
            {related_frames.slice(0, 3).map((fr) => (
              <div
                key={fr.frame_id}
                className="rounded-lg overflow-hidden border border-slate-200 bg-slate-50 aspect-video relative group cursor-pointer"
                onClick={() => setLightboxImage(`/api/assets/frames/${fr.frame_id}`)}
              >
                <img
                  src={`/api/assets/frames/${fr.frame_id}`}
                  alt="Evidence frame"
                  className="w-full h-full object-cover transition-transform duration-300 group-hover:scale-105"
                  loading="lazy"
                  onError={(e) => {
                    (e.currentTarget as HTMLImageElement).style.display = "none";
                  }}
                />
                <div className="absolute inset-0 bg-black/0 group-hover:bg-black/10 transition-colors flex items-center justify-center">
                  <svg className="w-6 h-6 text-white opacity-0 group-hover:opacity-100 transition-opacity" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0zM10 7v3m0 0v3m0-3h3m-3 0H7" />
                  </svg>
                </div>
                <div className="absolute bottom-0 inset-x-0 bg-gradient-to-t from-black/60 to-transparent px-1.5 py-1 text-[10px] text-white flex justify-between pointer-events-none">
                  <span>{formatSeconds(fr.timestamp_seconds)}</span>
                  {fr.is_important && <span className="font-semibold">★ key</span>}
                </div>
              </div>
            ))}
          </div>
        )}

        <div className="text-sm text-slate-800 whitespace-pre-wrap leading-relaxed">
          {evidence.content}
        </div>

        {evidence.entities && evidence.entities.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {evidence.entities.slice(0, 12).map((e) => (
              <span
                key={e}
                className="text-[11px] px-1.5 py-0.5 rounded bg-brand-50 text-brand-700 ring-1 ring-inset ring-brand-200"
              >
                #{e}
              </span>
            ))}
          </div>
        )}

        {related_evidence && related_evidence.length > 0 && (
          <div className="pt-2 border-t border-slate-100">
            <div className="text-[11px] font-semibold text-slate-500 uppercase tracking-wide mb-2">
              Cross-modal links ({related_evidence.length})
            </div>
            <div className="space-y-2">
              {related_evidence.slice(0, 4).map((rel) => (
                <div
                  key={rel.id}
                  className="rounded-lg bg-slate-50 border border-slate-200 p-2.5"
                >
                  <div className="flex items-center justify-between gap-2 mb-1">
                    <ModalityBadge modality={rel.modality} />
                    <EvidenceMeta ev={rel} />
                  </div>
                  <div className="text-xs text-slate-700 line-clamp-3">
                    {rel.content.length > 240 ? rel.content.slice(0, 240) + "…" : rel.content}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {lightboxImage && (
        <div 
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/80 backdrop-blur-sm animate-fade-in"
          onClick={() => setLightboxImage(null)}
        >
          <div className="relative max-w-7xl max-h-screen w-full h-full flex items-center justify-center">
            <button 
              onClick={() => setLightboxImage(null)}
              className="absolute top-4 right-4 text-white bg-black/50 hover:bg-black/70 rounded-full p-2"
            >
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M18 6L6 18M6 6l12 12" />
              </svg>
            </button>
            <img 
              src={lightboxImage} 
              alt="Expanded evidence" 
              className="max-w-full max-h-full object-contain rounded-lg shadow-2xl"
              onClick={(e) => e.stopPropagation()}
            />
          </div>
        </div>
      )}
    </div>
  );
}
