import type { ProcessingStatus, ModalityType, SourceType } from "../types";

export function formatSeconds(s?: number): string {
  if (s === undefined || s === null || Number.isNaN(s)) return "—";
  const total = Math.max(0, Math.floor(Number(s)));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const sec = total % 60;
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
  return `${m}:${String(sec).padStart(2, "0")}`;
}

export function formatBytes(bytes?: number): string {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  let v = bytes;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(v < 10 && i > 0 ? 2 : 0)} ${units[i]}`;
}

const statusColors: Record<ProcessingStatus, string> = {
  pending: "bg-slate-50 text-slate-700 ring-slate-200",
  uploaded: "bg-sky-50 text-sky-700 ring-sky-200",
  processing: "bg-blue-50 text-blue-700 ring-blue-200",
  extracting_audio: "bg-indigo-50 text-indigo-700 ring-indigo-200",
  extracting_frames: "bg-violet-50 text-violet-700 ring-violet-200",
  transcribing: "bg-fuchsia-50 text-fuchsia-700 ring-fuchsia-200",
  analyzing_visuals: "bg-purple-50 text-purple-700 ring-purple-200",
  extracting_ocr: "bg-pink-50 text-pink-700 ring-pink-200",
  building_evidence: "bg-amber-50 text-amber-800 ring-amber-200",
  embedding: "bg-yellow-50 text-yellow-800 ring-yellow-200",
  completed: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  failed: "bg-rose-50 text-rose-700 ring-rose-200",
};

const statusLabels: Record<ProcessingStatus, string> = {
  pending: "Pending",
  uploaded: "Uploaded",
  processing: "Processing",
  extracting_audio: "Extracting audio",
  extracting_frames: "Sampling frames",
  transcribing: "Transcribing speech",
  analyzing_visuals: "Analyzing visuals",
  extracting_ocr: "Extracting OCR",
  building_evidence: "Building evidence",
  embedding: "Indexing vectors",
  completed: "Completed",
  failed: "Failed",
};

export function StatusBadge({ status }: { status: ProcessingStatus }) {
  const cls = statusColors[status] ?? statusColors.pending;
  const label = statusLabels[status] ?? status;
  const showPulse = ![
    "completed",
    "failed",
    "pending",
    "uploaded",
  ].includes(status);
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium ring-1 ring-inset ${cls}`}
    >
      {showPulse && (
        <span className="inline-block w-1.5 h-1.5 rounded-full bg-current opacity-70 animate-pulse-bar" />
      )}
      {label}
    </span>
  );
}

const modalityColors: Record<ModalityType, string> = {
  audio: "bg-sky-50 text-sky-700 ring-sky-200",
  visual: "bg-purple-50 text-purple-700 ring-purple-200",
  text: "bg-slate-50 text-slate-700 ring-slate-200",
  ocr: "bg-amber-50 text-amber-800 ring-amber-200",
  multimodal: "bg-emerald-50 text-emerald-700 ring-emerald-200",
};

const modalityLabels: Record<ModalityType, string> = {
  audio: "Audio / Transcript",
  visual: "Visual / Frame",
  text: "Text / Document",
  ocr: "OCR",
  multimodal: "Multimodal",
};

export function ModalityBadge({ modality }: { modality: ModalityType }) {
  const cls = modalityColors[modality] ?? modalityColors.text;
  const label = modalityLabels[modality] ?? String(modality);
  return (
    <span className={`inline-flex px-1.5 py-0.5 rounded text-[11px] font-medium ring-1 ring-inset ${cls}`}>
      {label}
    </span>
  );
}

const sourceTypeColors: Record<SourceType, string> = {
  video: "bg-rose-50 text-rose-700 ring-rose-200",
  pdf: "bg-orange-50 text-orange-700 ring-orange-200",
  image: "bg-teal-50 text-teal-700 ring-teal-200",
  audio: "bg-indigo-50 text-indigo-700 ring-indigo-200",
};

const sourceTypeLabels: Record<SourceType, string> = {
  video: "Video",
  pdf: "PDF",
  image: "Image",
  audio: "Audio",
};

export function SourceTypeBadge({ type }: { type: SourceType }) {
  const cls = sourceTypeColors[type] ?? sourceTypeColors.image;
  const label = sourceTypeLabels[type] ?? String(type);
  return (
    <span className={`inline-flex px-1.5 py-0.5 rounded text-[11px] font-medium ring-1 ring-inset ${cls}`}>
      {label}
    </span>
  );
}

export function ProgressBar({ value, status }: { value: number; status: ProcessingStatus }) {
  const pct = Math.max(0, Math.min(100, Number(value) || 0));
  let barColor = "bg-brand-500";
  if (status === "completed") barColor = "bg-emerald-500";
  else if (status === "failed") barColor = "bg-rose-500";
  return (
    <div className="w-full h-1.5 bg-slate-50 rounded-full overflow-hidden">
      <div
        className={`h-full ${barColor} transition-all duration-300 ease-out`}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}
