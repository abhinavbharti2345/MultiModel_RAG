import { useRef, useState } from "react";
import { api } from "../api";
import type { ProcessingJobResponse } from "../types";
import { ProgressBar, StatusBadge } from "./Badges";

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
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm">
      <div className="px-5 py-4 border-b border-slate-100 flex items-center justify-between">
        <div>
          <h2 className="font-semibold text-slate-900">Upload media</h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Videos, PDFs, images — each ingested into structured, retrieval-ready evidence.
          </p>
        </div>
        {(job || error) && (
          <button
            onClick={reset}
            className="text-xs text-slate-500 hover:text-slate-700 px-2 py-1 rounded hover:bg-slate-50"
          >
            Upload another
          </button>
        )}
      </div>

      <div className="p-5">
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
            className={`block cursor-pointer border-2 border-dashed rounded-lg p-8 text-center transition
              ${dragActive ? "border-brand-400 bg-brand-50" : "border-slate-200 hover:border-brand-300 hover:bg-slate-50"}`}
          >
            <input
              ref={inputRef}
              type="file"
              accept={ACCEPTED}
              className="hidden"
              onChange={(e) => onFiles(e.target.files)}
              disabled={uploading}
            />
            <div className="mx-auto w-12 h-12 rounded-full bg-brand-100 text-brand-600 flex items-center justify-center">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="17 8 12 3 7 8" />
                <line x1="12" y1="3" x2="12" y2="15" />
              </svg>
            </div>
            <p className="mt-3 font-medium text-slate-800">
              {uploading ? "Uploading…" : "Drop file here or click to browse"}
            </p>
            <p className="mt-1 text-xs text-slate-500">
              MP4 / MOV / MKV · PDF · JPG / PNG · MP3 / WAV
            </p>
            {uploading && (
              <div className="mt-4 max-w-sm mx-auto">
                <ProgressBar value={uploadPct} status="processing" />
                <p className="mt-1.5 text-xs text-slate-500">{Math.round(uploadPct)}% uploaded</p>
              </div>
            )}
          </label>
        )}

        {error && (
          <div className="rounded-lg bg-rose-50 border border-rose-200 p-4 text-sm text-rose-800">
            <div className="font-semibold">Upload failed</div>
            <div className="mt-1">{error}</div>
          </div>
        )}

        {job && !error && (
          <div className="rounded-lg border border-slate-200 p-4 space-y-3 animate-fade-in">
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <div className="font-medium text-slate-900 truncate">
                  {file?.name ?? "File"}
                </div>
                <div className="text-xs text-slate-500 mt-0.5">
                  Queued for processing · source_id {job.source_id.slice(0, 8)}…
                </div>
              </div>
              <StatusBadge status={job.status} />
            </div>
            <ProgressBar value={job.progress_percent} status={job.status} />
            <div className="text-xs text-slate-500 min-h-[1.25rem]">
              {job.status_message ?? "Preparing ingestion pipeline…"}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
