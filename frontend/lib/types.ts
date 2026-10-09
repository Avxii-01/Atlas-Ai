/**
 * Type definitions for Atlas AI repository analysis workflow (P0-18, P0-21).
 */

export interface AnalysisSummary {
  files: number;
  classes: number;
  functions: number;
  relationships: number;
  modules?: number | null;
  methods?: number | null;
  imports?: number | null;
}

export interface RepositoryAnalysisRequest {
  path: string;
  name?: string;
}

export interface RepositoryAnalysisResponse {
  repository_id: string;
  status: string;
  summary: AnalysisSummary;
}

export type AnalysisStatus = "idle" | "loading" | "success" | "error";

export interface AnalysisError {
  message: string;
  status?: number;
  detail?: string;
}
