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

/**
 * Graph node representation aligned with GET /api/v1/repositories/{id}/graph (P0-19).
 */
export interface GraphNodeModel {
  id: string;
  label: string; // Repository, File, Module, Class, Function, Method, Import
  name: string;
  type: string;
  display_name?: string | null;
  properties?: Record<string, unknown>;
}

/**
 * Graph relationship edge representation aligned with GET /api/v1/repositories/{id}/graph (P0-19).
 */
export interface GraphRelationshipModel {
  id: string;
  source: string;
  target: string;
  type: string; // CONTAINS, IMPORTS, CALLS, INHERITS
  source_id?: string | null;
  target_id?: string | null;
  rel_type?: string | null;
  properties?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
}

/**
 * API response contract for GET /api/v1/repositories/{repository_id}/graph.
 */
export interface RepositoryGraphResponse {
  repository_id: string;
  nodes: GraphNodeModel[];
  relationships: GraphRelationshipModel[];
}

export type GraphFetchStatus = "idle" | "loading" | "success" | "empty" | "error";

/**
 * Target entity model whose impact was analyzed (P0-20, P0-23).
 */
export interface TargetEntityModel {
  id: string;
  name: string;
  label?: string | null;
  type?: string | null;
  file_path?: string | null;
  properties?: Record<string, unknown>;
}

/**
 * Impacted entity model affected directly or transitively (P0-20, P0-23).
 */
export interface ImpactedEntityModel {
  id: string;
  name: string;
  depth: number;
  label?: string | null;
  type?: string | null;
  file_path?: string | null;
  entity_id?: string | null;
  properties?: Record<string, unknown>;
}

/**
 * Response payload for GET /api/v1/repositories/{repository_id}/impact/{entity_id}.
 */
export interface RepositoryImpactResponse {
  entity: TargetEntityModel;
  direct_dependents: ImpactedEntityModel[];
  transitive_dependents: ImpactedEntityModel[];
  affected_files: string[];
  max_depth: number;
  repository_id?: string | null;
}

export type ImpactFetchStatus = "idle" | "loading" | "success" | "empty" | "error";
