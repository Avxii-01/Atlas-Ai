import { MarkerType, type Node, type Edge } from "@xyflow/react";
import type {
  RepositoryGraphResponse,
  GraphNodeModel,
  GraphRelationshipModel,
} from "./types.ts";

export interface EntityNodeData extends Record<string, unknown> {
  id: string;
  label: string;
  name: string;
  type: string;
  displayName: string;
  properties: Record<string, unknown>;
}

/**
 * Assigns architectural hierarchy tiers to entity types for clear column-based layout.
 */
const ENTITY_TIER_ORDER: Record<string, number> = {
  repository: 0,
  file: 1,
  module: 1,
  class: 2,
  function: 3,
  method: 3,
  import: 4,
};

/**
 * Returns a display-friendly label for a node, preferring display_name, then name, then id.
 */
export function getNodeDisplayLabel(node: GraphNodeModel): string {
  if (node.display_name && node.display_name.trim()) {
    return node.display_name.trim();
  }
  if (node.name && node.name.trim()) {
    return node.name.trim();
  }
  return node.id;
}

/**
 * Calculates deterministic (x, y) coordinates for nodes based on their entity types and counts.
 * Uses a tiered column layout with max rows per sub-column to prevent overlapping and excessive height.
 */
export function computeNodePositions(
  nodes: GraphNodeModel[]
): Map<string, { x: number; y: number }> {
  const positions = new Map<string, { x: number; y: number }>();

  // Group nodes by tier
  const tierBuckets = new Map<number, GraphNodeModel[]>();
  for (let i = 0; i <= 5; i++) {
    tierBuckets.set(i, []);
  }

  for (const node of nodes) {
    const typeKey = (node.label || node.type || "").toLowerCase();
    const tier = ENTITY_TIER_ORDER[typeKey] ?? 5; // 5 for unknown/other types
    tierBuckets.get(tier)!.push(node);
  }

  const ROW_HEIGHT = 85;
  const COLUMN_WIDTH = 280;
  const MAX_ROWS_PER_SUBCOLUMN = 12;
  const X_OFFSET = 60;
  const Y_OFFSET = 60;

  let currentBaseX = X_OFFSET;

  for (let tier = 0; tier <= 5; tier++) {
    const tierNodes = tierBuckets.get(tier) || [];
    if (tierNodes.length === 0) {
      continue;
    }

    // Sort deterministically by label then name then id
    tierNodes.sort((a, b) => {
      const labelCmp = (a.label || "").localeCompare(b.label || "");
      if (labelCmp !== 0) return labelCmp;
      const nameCmp = (a.name || "").localeCompare(b.name || "");
      if (nameCmp !== 0) return nameCmp;
      return a.id.localeCompare(b.id);
    });

    const subColumnsCount = Math.max(
      1,
      Math.ceil(tierNodes.length / MAX_ROWS_PER_SUBCOLUMN)
    );

    tierNodes.forEach((node, idx) => {
      const subCol = Math.floor(idx / MAX_ROWS_PER_SUBCOLUMN);
      const row = idx % MAX_ROWS_PER_SUBCOLUMN;

      const x = currentBaseX + subCol * COLUMN_WIDTH;
      const y = Y_OFFSET + row * ROW_HEIGHT;
      positions.set(node.id, { x, y });
    });

    currentBaseX += subColumnsCount * COLUMN_WIDTH + 80;
  }

  return positions;
}

/**
 * Maps edge relationship types to subtle, distinguished visual edge styles.
 */
function getEdgeStyle(type: string): { stroke: string; strokeWidth: number } {
  const upper = (type || "").toUpperCase();
  switch (upper) {
    case "CONTAINS":
      return { stroke: "#64748b", strokeWidth: 1.5 }; // Slate
    case "IMPORTS":
      return { stroke: "#60a5fa", strokeWidth: 1.5 }; // Blue
    case "CALLS":
      return { stroke: "#34d399", strokeWidth: 1.5 }; // Emerald
    case "INHERITS":
      return { stroke: "#fbbf24", strokeWidth: 1.5 }; // Amber
    default:
      return { stroke: "#94a3b8", strokeWidth: 1.5 };
  }
}

/**
 * Converts backend graph response into React Flow nodes and edges.
 *
 * Invariants:
 * - Stable backend entity IDs preserved as React Flow node IDs.
 * - Display label derived preferring display_name, falling back to name/id.
 * - Edges preserve source-to-target direction and stable edge IDs.
 * - Only edges connecting existing nodes are created (dangling edges skipped).
 * - Distinct edges between the same nodes are preserved.
 */
export function mapGraphResponseToReactFlow(
  response: RepositoryGraphResponse
): {
  nodes: Node<EntityNodeData>[];
  edges: Edge[];
} {
  const rawNodes = response?.nodes || [];
  const rawEdges = response?.relationships || [];

  const positions = computeNodePositions(rawNodes);
  const nodeMap = new Map<string, GraphNodeModel>();

  const nodes: Node<EntityNodeData>[] = rawNodes.map((rawNode) => {
    nodeMap.set(rawNode.id, rawNode);
    const pos = positions.get(rawNode.id) || { x: 0, y: 0 };
    const displayName = getNodeDisplayLabel(rawNode);

    return {
      id: rawNode.id,
      type: "entityNode",
      position: pos,
      data: {
        id: rawNode.id,
        label: rawNode.label || rawNode.type || "Entity",
        name: rawNode.name || rawNode.id,
        type: rawNode.type || rawNode.label || "Entity",
        displayName,
        properties: rawNode.properties || {},
      },
    };
  });

  const validNodeIds = new Set(nodes.map((n) => n.id));
  const edges: Edge[] = [];

  for (const rel of rawEdges) {
    // Invariant: Do not create edges whose source or target nodes are absent
    if (!validNodeIds.has(rel.source) || !validNodeIds.has(rel.target)) {
      continue;
    }

    const edgeStyle = getEdgeStyle(rel.type);

    edges.push({
      id: rel.id,
      source: rel.source,
      target: rel.target,
      label: rel.type || "RELATED_TO",
      type: "smoothstep",
      animated: false,
      style: edgeStyle,
      labelStyle: {
        fill: "#94a3b8",
        fontSize: 10,
        fontWeight: 600,
        fontFamily: "monospace",
      },
      labelBgStyle: {
        fill: "rgba(15, 23, 42, 0.85)",
        rx: 4,
        ry: 4,
      },
      labelBgPadding: [4, 2],
      markerEnd: {
        type: MarkerType.ArrowClosed,
        width: 14,
        height: 14,
        color: edgeStyle.stroke,
      },
    });
  }

  return { nodes, edges };
}
