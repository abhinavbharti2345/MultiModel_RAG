export type SourceType = "video" | "image" | "pdf" | "audio";
export type ModalityType = "audio" | "visual" | "text" | "ocr" | "multimodal";
export type ProcessingStatus =
  | "pending"
  | "uploaded"
  | "processing"
  | "extracting_audio"
  | "extracting_frames"
  | "transcribing"
  | "analyzing_visuals"
  | "extracting_ocr"
  | "building_evidence"
  | "embedding"
  | "completed"
  | "failed";

export interface Provenance {
  source: string;
  timestamp?: string;
  page?: number;
  frame_id?: string;
}

export interface SourceResponse {
  id: string;
  name: string;
  source_type: SourceType;
  file_path: string;
  file_size?: number;
  mime_type?: string;
  duration_seconds?: number;
  page_count?: number;
  status: ProcessingStatus;
  status_message?: string;
  progress_percent: number;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface EvidenceResponse {
  id: string;
  source_id: string;
  content: string;
  modality: ModalityType;
  timestamp_start?: number;
  timestamp_end?: number;
  page_number?: number;
  speaker?: string;
  confidence: number;
  entities: string[];
  relationships: Array<Record<string, unknown>>;
  provenance?: Provenance;
  qdrant_point_id?: string;
  created_at: string;
}

export interface FrameInfo {
  frame_id: string;
  timestamp_seconds?: number;
  frame_path: string;
  width?: number;
  height?: number;
  is_important?: boolean;
  ocr_text?: string;
}

export interface EvidenceWithScore {
  evidence: EvidenceResponse;
  similarity_score: number;
  related_evidence: EvidenceResponse[];
  related_frames: FrameInfo[];
}

export interface QueryResponse {
  answer: string;
  provenance_summary: string[];
  evidence: EvidenceWithScore[];
}

export interface ProcessingJobResponse {
  source_id: string;
  status: ProcessingStatus;
  status_message?: string;
  progress_percent: number;
}

export interface HealthResponse {
  status: string;
  qdrant_collection: string;
  embedding_model: string;
  groq_model: string;
  whisper_model: string;
  storage_path: string;
  groq_configured: boolean;
  vlm_configured: boolean;
}
