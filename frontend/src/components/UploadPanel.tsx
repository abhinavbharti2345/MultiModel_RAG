import { useRef, useState } from "react";
import { api } from "../api";
import type { ProcessingJobResponse } from "../types";
import { ProgressBar, StatusBadge } from "./Badges";
import { UploadCloud } from "lucide-react";

interface Props {
  onUploaded: (job: ProcessingJobResponse) => void;
}

const ACCEPTED = "video/*,application/pdf,image/*,.mp3,.wav,.flac,.m4a";

export function UploadPanel({ onUploaded }: Props) {
  const [dragActive, setDragActive] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadPct, setUploadPct] = useState(0);
  const [job, setJob] = useState<ProcessingJobResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  function reset() {
    setError(null);
    setJob(null);
    setUploadPct(0);
    setFile(null);
    if (inputRef.current) inputRef.current.value = "";
  }

  async function doUpload(f: File) {
    setError(null);
    setFile(f);
    setUploading(true);
    setUploadPct(0);
    try {
      const result = await api.uploadFile(f, undefined, {
        onProgress: (pct) => setUploadPct(pct),
      });
      setJob(result);
      onUploaded(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setUploading(false);
      // Auto-reset upload panel after 2 seconds so user doesn't see "Queued" forever
      setTimeout(() => reset(), 2000);
    }
  }

  function onFiles(files: FileList | null) {
    if (!files || files.length === 0) return;
    doUpload(files[0]);
  }

  return (
    <div>
      {!job && !error && (
        <label
          onDragEnter={(e) => {
            e.preventDefault();
            setDragActive(true);
          }}
          onDragOver={(e) => {
            e.preventDefault();
            setDragActive(true);
          }}
          onDragLeave={() => setDragActive(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragActive(false);
            onFiles(e.dataTransfer.files);
          }}
          className={`card-surface p-3 border-dashed flex flex-col items-center justify-center text-center cursor-pointer transition
            ${dragActive ? "border-indigo-500 bg-indigo-950/20" : "border-zinc-700 hover:border-zinc-500"}
          `}
        >
          <input
            ref={inputRef}
            type="file"
            accept={ACCEPTED}
            className="hidden"
            onChange={(e) => onFiles(e.target.files)}
            disabled={uploading}
          />
          <UploadCloud className="w-4 h-4 text-zinc-400 mb-1" />
          <div className="text-xs font-semibold text-zinc-200">
            {uploading ? "Uploading..." : "Upload Source (Video, Audio, Image, PDF)"}
          </div>
          <div className="text-[10px] text-zinc-400">
            {uploading ? `${Math.round(uploadPct)}% uploaded` : "Triggers async ingestion pipeline & graph builder"}
          </div>
          
          {uploading && (
            <div className="w-full max-w-[200px] mt-2">
              <ProgressBar value={uploadPct} status="processing" />
            </div>
          )}
        </label>
      )}

      {error && (
        <div className="rounded border border-rose-900/50 bg-rose-950/30 p-3 text-sm text-rose-400 flex justify-between items-center">
          <div>
            <div className="font-semibold text-xs">Upload failed</div>
            <div className="text-[10px]">{error}</div>
          </div>
          <button onClick={reset} className="text-[10px] px-2 py-1 bg-rose-900/50 rounded hover:bg-rose-800/50 text-rose-200">Retry</button>
        </div>
      )}

      {job && !error && (
        <div className="card-surface p-3 space-y-2 animate-fade-in border-zinc-700">
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0">
              <div className="font-medium text-xs text-zinc-200 truncate">
                {file?.name ?? "File"}
              </div>
              <div className="text-[10px] text-zinc-400 mt-0.5">
                Queued for processing · source_id {job.source_id.slice(0, 8)}…
              </div>
            </div>
            <StatusBadge status={job.status} />
          </div>
          <ProgressBar value={job.progress_percent} status={job.status} />
          <div className="text-[10px] text-zinc-400 min-h-[1.25rem]">
            {job.status_message ?? "Preparing ingestion pipeline…"}
          </div>
        </div>
      )}
    </div>
  );
}
