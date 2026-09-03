import { useState } from "react";
import type { EvidenceWithScore, EvidenceResponse } from "../types";
import { formatSeconds } from "./Badges";
import { Mic, Image as ImageIcon, FileText, LayoutGrid } from "lucide-react";

interface Props {
  hit: EvidenceWithScore;
  rank: number;
}

function getModalityInfo(modality: string) {
  switch (modality) {
    case 'audio': return { icon: <Mic className="w-3 h-3" />, label: 'Audio Speech', color: 'text-amber-400' };
    case 'visual': return { icon: <ImageIcon className="w-3 h-3" />, label: 'Visual Frame', color: 'text-purple-400' };
    case 'text': return { icon: <FileText className="w-3 h-3" />, label: 'Document Chunk', color: 'text-emerald-400' };
    case 'ocr': return { icon: <LayoutGrid className="w-3 h-3" />, label: 'OCR Text', color: 'text-indigo-400' };
    default: return { icon: <FileText className="w-3 h-3" />, label: 'Evidence', color: 'text-zinc-400' };
  }
}

export function EvidenceCard({ hit, rank }: Props) {
  const { evidence, similarity_score, related_evidence, related_frames } = hit;
  const [lightboxImage, setLightboxImage] = useState<string | null>(null);

  const modInfo = getModalityInfo(evidence.modality);
  
  let timeStr = "";
  if (evidence.timestamp_start !== undefined) {
    timeStr = formatSeconds(evidence.timestamp_start);
    if (evidence.timestamp_end !== undefined && evidence.timestamp_end !== evidence.timestamp_start) {
      timeStr += ` - ${formatSeconds(evidence.timestamp_end)}`;
    }
  } else if (evidence.page_number !== undefined && evidence.page_number !== null) {
    timeStr = `Page ${evidence.page_number}`;
  } else {
    timeStr = `Chunk #${evidence.id.substring(0, 5)}`;
  }

  return (
    <div id={`evidence-${evidence.id}`} className="p-2.5 rounded bg-[#09090b] border border-[#27272a] hover:border-[#3f3f46] transition-colors flex flex-col justify-between scroll-mt-24">
      <div>
        <div className="flex items-center justify-between text-[10px] mb-1">
          <span className={`font-semibold flex items-center gap-1 ${modInfo.color}`}>
            {modInfo.icon} {modInfo.label}
          </span>
          <span className="text-zinc-400 mono">{timeStr}</span>
        </div>
        
        <div className="text-[10px] text-zinc-300 italic mb-2 line-clamp-4">
          "{evidence.content}"
        </div>

        {related_frames.length > 0 && (
          <div className="flex gap-1.5 mb-2 overflow-x-auto scrollbar-thin">
            {related_frames.slice(0, 3).map((fr) => (
              <div
                key={fr.frame_id}
                className="relative cursor-pointer group rounded border border-zinc-700 w-16 h-10 flex-shrink-0 bg-zinc-900"
                onClick={() => setLightboxImage(`/api/assets/frames/${fr.frame_id}`)}
              >
                <img
                  src={`/api/assets/frames/${fr.frame_id}`}
                  alt="Frame"
                  className="w-full h-full object-cover opacity-80 group-hover:opacity-100"
                  loading="lazy"
                />
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="text-[9px] text-zinc-400 pt-1 border-t border-zinc-800 flex justify-between items-center mt-1">
        <span>{evidence.speaker ? evidence.speaker : (evidence.modality === 'visual' ? 'Graph Link' : 'Top-K Match')}</span>
        <span className="mono text-zinc-300">Conf: {similarity_score.toFixed(2)}</span>
      </div>

      {lightboxImage && (
        <div 
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-[#09090b]/90 backdrop-blur animate-fade-in"
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
              className="max-w-full max-h-full object-contain rounded-lg shadow-2xl border border-zinc-800"
              onClick={(e) => e.stopPropagation()}
            />
          </div>
        </div>
      )}
    </div>
  );
}
