import type {
  HealthResponse,
  ProcessingJobResponse,
  QueryResponse,
  SourceResponse,
  EvidenceWithScore,
  EvidenceResponse,
} from "./types";

const API_BASE = "";

async function handle<T>(resp: Response): Promise<T> {
  if (!resp.ok) {
    let msg = `HTTP ${resp.status}`;
    try {
      const data = await resp.json();
      if (data?.detail) msg = String(data.detail);
    } catch {
      // ignore
    }
    throw new Error(msg);
  }
  return (await resp.json()) as T;
}

export const api = {
  health: async (): Promise<HealthResponse> => {
    const r = await fetch(`${API_BASE}/api/health`);
    return handle<HealthResponse>(r);
  },

  uploadFile: async (
    file: File,
    description?: string,
    { onProgress }: { onProgress?: (pct: number, loaded: number, total: number) => void } = {},
  ): Promise<ProcessingJobResponse> => {
    const fd = new FormData();
    fd.append("file", file);
    if (description) fd.append("description", description);

    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", `${API_BASE}/api/upload`);
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable && onProgress) {
          onProgress((e.loaded / e.total) * 100, e.loaded, e.total);
        }
      };
      xhr.onload = () => {
        try {
          const data = JSON.parse(xhr.responseText);
          if (xhr.status >= 200 && xhr.status < 300) resolve(data);
          else reject(new Error(data?.detail || `HTTP ${xhr.status}`));
        } catch (e) {
          reject(e);
        }
      };
      xhr.onerror = () => reject(new Error("Network error during upload"));
      xhr.send(fd);
    });
  },

  listSources: async (): Promise<SourceResponse[]> => {
    const r = await fetch(`${API_BASE}/api/sources?limit=200`);
    return handle<SourceResponse[]>(r);
  },

  clearAllSources: async (): Promise<void> => {
    const r = await fetch(`${API_BASE}/api/sources/clear-all`, { method: "DELETE" });
    return handle<void>(r);
  },

  deleteSource: async (sourceId: string): Promise<void> => {
    const r = await fetch(`${API_BASE}/api/sources/${sourceId}`, { method: "DELETE" });
    return handle<void>(r);
  },

  getSourceStatus: async (sourceId: string) => {
    const r = await fetch(`${API_BASE}/api/sources/${sourceId}/status`);
    return handle<ProcessingJobResponse>(r);
  },

  getSource: async (sourceId: string): Promise<SourceResponse> => {
    const r = await fetch(`${API_BASE}/api/sources/${sourceId}`);
    return handle<SourceResponse>(r);
  },

  getEvidenceSummary: async (sourceId: string) => {
    const r = await fetch(`${API_BASE}/api/sources/${sourceId}/evidence-summary`);
    return handle<Record<string, unknown>>(r);
  },

  query: async (
    question: string,
    opts: { topK?: number; expandRelationships?: boolean } = {},
  ): Promise<QueryResponse> => {
    const r = await fetch(`${API_BASE}/api/query`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query: question,
        top_k: opts.topK ?? 10,
        expand_relationships: opts.expandRelationships ?? true,
        include_multimodal: true,
      }),
    });
    return handle<QueryResponse>(r);
  },

  queryEvidenceOnly: async (
    question: string,
    opts: { topK?: number; expandRelationships?: boolean } = {},
  ): Promise<EvidenceWithScore[]> => {
    const r = await fetch(`${API_BASE}/api/query/evidence-only`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query: question,
        top_k: opts.topK ?? 10,
        expand_relationships: opts.expandRelationships ?? true,
        include_multimodal: true,
      }),
    });
    return handle<EvidenceWithScore[]>(r);
  },

  getRelatedEvidence: async (evidenceId: string): Promise<EvidenceResponse[]> => {
    const r = await fetch(`${API_BASE}/api/query/evidence/${evidenceId}/related?max_hops=1&min_confidence=0.5`);
    return handle<EvidenceResponse[]>(r);
  },

  listFrames: async (sourceId: string, onlyImportant = true) => {
    const r = await fetch(`${API_BASE}/api/assets/sources/${sourceId}/frames?only_important=${onlyImportant}`);
    return handle<FrameInfo[]>(r);
  },
};

interface FrameInfo {
  frame_id: string;
  timestamp_seconds?: number;
  frame_path: string;
  width?: number;
  height?: number;
  is_important?: boolean;
  ocr_text?: string;
  visual_description?: string;
  image_url?: string;
}
