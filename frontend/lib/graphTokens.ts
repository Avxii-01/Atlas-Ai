/**
 * Shared visual styling tokens and display metadata for Atlas AI graph entities and relationships.
 * Acts as the single source of truth for EntityNode, graphMapper, and GraphLegend.
 */

export interface EntityBadgeStyle {
  bg: string;
  text: string;
  border: string;
}

export interface EdgeStyle {
  stroke: string;
  strokeWidth: number;
}

export interface EntityTypeDescriptor {
  type: string;
  label: string;
  description: string;
}

export interface RelationshipTypeDescriptor {
  type: string;
  label: string;
  description: string;
}

/**
 * Exact badge colors from the existing EntityNode renderer.
 */
export const ENTITY_TYPE_CONFIG: Record<string, EntityBadgeStyle> = {
  repository: { bg: "rgba(168, 85, 247, 0.15)", text: "#c084fc", border: "rgba(168, 85, 247, 0.35)" },
  file: { bg: "rgba(59, 130, 246, 0.15)", text: "#60a5fa", border: "rgba(59, 130, 246, 0.35)" },
  module: { bg: "rgba(6, 182, 212, 0.15)", text: "#22d3ee", border: "rgba(6, 182, 212, 0.35)" },
  class: { bg: "rgba(99, 102, 241, 0.15)", text: "#a5b4fc", border: "rgba(99, 102, 241, 0.35)" },
  function: { bg: "rgba(16, 185, 129, 0.15)", text: "#34d399", border: "rgba(16, 185, 129, 0.35)" },
  method: { bg: "rgba(20, 184, 166, 0.15)", text: "#2dd4bf", border: "rgba(20, 184, 166, 0.35)" },
  import: { bg: "rgba(245, 158, 11, 0.15)", text: "#fbbf24", border: "rgba(245, 158, 11, 0.35)" },
};

export const DEFAULT_ENTITY_BADGE_STYLE: EntityBadgeStyle = {
  bg: "rgba(148, 163, 184, 0.15)",
  text: "#cbd5e1",
  border: "rgba(148, 163, 184, 0.3)",
};

/**
 * Returns the badge style corresponding to an entity label or type.
 */
export function getEntityBadgeStyle(labelOrType: string): EntityBadgeStyle {
  const kind = (labelOrType || "").toLowerCase();
  return ENTITY_TYPE_CONFIG[kind] || DEFAULT_ENTITY_BADGE_STYLE;
}

/**
 * Exact edge strokes from the existing graphMapper renderer.
 */
export const RELATIONSHIP_TYPE_CONFIG: Record<string, EdgeStyle> = {
  CONTAINS: { stroke: "#64748b", strokeWidth: 1.5 },
  IMPORTS: { stroke: "#60a5fa", strokeWidth: 1.5 },
  CALLS: { stroke: "#34d399", strokeWidth: 1.5 },
  INHERITS: { stroke: "#fbbf24", strokeWidth: 1.5 },
};

export const DEFAULT_EDGE_STYLE: EdgeStyle = {
  stroke: "#94a3b8",
  strokeWidth: 1.5,
};

/**
 * Returns the edge stroke style corresponding to a relationship type.
 */
export function getRelationshipEdgeStyle(relType: string): EdgeStyle {
  const upper = (relType || "").toUpperCase();
  return RELATIONSHIP_TYPE_CONFIG[upper] || DEFAULT_EDGE_STYLE;
}

/**
 * Every entity type supported by the current renderer, in architectural order.
 */
export const SUPPORTED_ENTITY_TYPES: readonly EntityTypeDescriptor[] = [
  { type: "repository", label: "Repository", description: "Root repository container" },
  { type: "file", label: "File", description: "Source code file" },
  { type: "module", label: "Module", description: "Logical module" },
  { type: "class", label: "Class", description: "Class declaration" },
  { type: "function", label: "Function", description: "Module-level function" },
  { type: "method", label: "Method", description: "Class method" },
  { type: "import", label: "Import", description: "Import statement" },
];

/**
 * Every relationship type supported by the current renderer.
 */
export const SUPPORTED_RELATIONSHIP_TYPES: readonly RelationshipTypeDescriptor[] = [
  { type: "CONTAINS", label: "CONTAINS", description: "Hierarchy (Repo -> File -> Class/Function)" },
  { type: "IMPORTS", label: "IMPORTS", description: "Import dependency" },
  { type: "CALLS", label: "CALLS", description: "Function/method invocation" },
  { type: "INHERITS", label: "INHERITS", description: "Class inheritance" },
];

