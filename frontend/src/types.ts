export type Confidence = "low" | "medium" | "high";

export interface Observations {
  visible_text: string[];
  dial: string;
  case: string;
  bezel: string;
  hands: string;
  complications: string[];
  bracelet_or_strap: string;
  condition: string;
}

export interface Candidate {
  brand: string;
  model: string;
  reference: string;
  confidence: Confidence;
  matching_evidence: string[];
  conflicting_evidence: string[];
}

export interface IdentificationAssessment {
  brand: "identified" | "uncertain";
  family: "identified" | "plausible" | "uncertain";
  reference: "supported" | "unresolved";
}

export interface WatchAnalysis {
  is_watch: boolean;
  observations: Observations;
  candidates: Candidate[];
  identification_assessment: IdentificationAssessment;
  unknowns: string[];
  recommended_next_photo: string;
  caution: string;
}

export interface ModelUnavailable {
  id: string;
  retryAfterSeconds?: number;
}

export interface AnalysisModelMetadata {
  requested: string;
  used: string;
  unavailable: ModelUnavailable[];
}

export interface AnalyzeResponse {
  analysis: WatchAnalysis;
  model: AnalysisModelMetadata;
}

export interface ModelOption {
  id: string;
  label: string;
  priority: number;
  available: boolean;
  retryAfterSeconds?: number;
}

export interface ModelsResponse {
  default: string;
  models: ModelOption[];
}

export interface ApiErrorPayload {
  error: {
    code: string;
    message: string;
    retryAfterSeconds?: number;
    unavailable?: ModelUnavailable[];
  };
}
