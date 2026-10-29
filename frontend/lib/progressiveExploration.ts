/**
 * Progressive Graph Exploration Module for Atlas AI (Checkpoint 4).
 *
 * Implements client-side interaction foundations for expanding, collapsing,
 * and tracking graph nodes incrementally without loading full repository graphs.
 * Operates strictly with fixtures/mock adapters until Developer A's revised
 * backend API contract is finalized and approved.
 */

import { MarkerType, type Node, type Edge } from "@xyflow/react";
import type { GraphNodeModel, GraphRelationshipModel, EntityChildrenResponse } from "./types.ts";
import { getEntityChildren } from "./api.ts";
import { getNodeDisplayLabel, type EntityNodeData } from "./graphMapper.ts";
import { getRelationshipEdgeStyle } from "./graphTokens.ts";

export interface NodeChildrenResponse {
  parent_id: string;
  nodes: GraphNodeModel[];
  relationships: GraphRelationshipModel[];
}

export type FetchNodeChildrenFn = (
  repositoryId: string,
  parentNodeId: string,
  options?: { signal?: AbortSignal }
) => Promise<NodeChildrenResponse | EntityChildrenResponse>;

/**
 * Checks whether an entity type is known to be a leaf entity in standard software ASTs.
 */
export function isKnownLeafType(labelOrType: string): boolean {
  const kind = (labelOrType || "").toLowerCase().trim();
  return kind === "method" || kind === "import";
}

/**
 * Extracts a human-friendly short name from hierarchical IDs using either '::' or '/' separators.
 */
export function extractEntityShortName(id: string): string {
  const clean = (id || "").trim();
  if (clean.includes("::")) {
    const parts = clean.split("::");
    return parts[parts.length - 1];
  }
  if (clean.includes("/")) {
    const parts = clean.split("/");
    return parts[parts.length - 1];
  }
  return clean;
}

/**
 * Calculates incremental non-overlapping (x, y) coordinates for newly revealed child nodes.
 * Guarantees:
 * 1. Zero drift on existing nodes (existing coordinates are strictly preserved).
 * 2. Guaranteed bounded execution: intervals are merged and candidateY advances monotonically.
 * 3. Never produces an infinite loop or blocks the main thread.
 */
export function computeIncrementalChildPositions(
  parentNode: Node<EntityNodeData>,
  childNodes: GraphNodeModel[],
  existingNodes: Node<EntityNodeData>[]
): Map<string, { x: number; y: number }> {
  const positions = new Map<string, { x: number; y: number }>();
  if (!childNodes || childNodes.length === 0) {
    return positions;
  }

  const parentX = parentNode.position.x;
  const parentY = parentNode.position.y;
  const targetX = parentX + 280; // Standard column step to the right of parent

  const ROW_HEIGHT = 85;
  const HALF_HEIGHT = 42;
  const VERTICAL_GAP = 20;

  // 1. Collect occupied intervals in target column band (x within +/- 140px)
  const rawIntervals: Array<{ top: number; bottom: number }> = [];
  for (const n of existingNodes) {
    if (Math.abs(n.position.x - targetX) < 140) {
      rawIntervals.push({
        top: n.position.y - HALF_HEIGHT,
        bottom: n.position.y + HALF_HEIGHT,
      });
    }
  }

  // 2. Sort and merge overlapping or adjacent intervals
  rawIntervals.sort((a, b) => a.top - b.top);
  const mergedIntervals: Array<{ top: number; bottom: number }> = [];

  for (const iv of rawIntervals) {
    if (mergedIntervals.length === 0) {
      mergedIntervals.push({ top: iv.top, bottom: iv.bottom });
    } else {
      const last = mergedIntervals[mergedIntervals.length - 1];
      if (iv.top <= last.bottom + VERTICAL_GAP) {
        last.bottom = Math.max(last.bottom, iv.bottom);
      } else {
        mergedIntervals.push({ top: iv.top, bottom: iv.bottom });
      }
    }
  }

  let currentY = Math.max(parentY, 60);

  for (const child of childNodes) {
    let candidateY = currentY;

    // Check candidate against merged intervals with a strict loop boundary
    let maxIters = mergedIntervals.length + 5;
    while (maxIters-- > 0) {
      let collided = false;
      const candTop = candidateY - HALF_HEIGHT;
      const candBottom = candidateY + HALF_HEIGHT;

      for (const iv of mergedIntervals) {
        if (candTop < iv.bottom + VERTICAL_GAP && candBottom > iv.top - VERTICAL_GAP) {
          // Place completely below this interval so candTop > iv.bottom + VERTICAL_GAP
          candidateY = iv.bottom + VERTICAL_GAP + HALF_HEIGHT;
          collided = true;
          break;
        }
      }

      if (!collided) {
        break;
      }
    }

    positions.set(child.id, { x: targetX, y: candidateY });

    // Insert new interval and maintain merged state for subsequent siblings
    mergedIntervals.push({
      top: candidateY - HALF_HEIGHT,
      bottom: candidateY + HALF_HEIGHT,
    });
    mergedIntervals.sort((a, b) => a.top - b.top);

    currentY = candidateY + ROW_HEIGHT;
  }

  return positions;
}

export interface MergeGraphOptions {
  onToggleExpand?: (nodeId: string) => void;
  expandedNodeIds?: Set<string>;
  loadingNodeIds?: Set<string>;
}

/**
 * Merges newly fetched child nodes and relationships into existing React Flow state.
 *
 * Rules:
 * - Detects and skips duplicate node IDs.
 * - Detects and skips duplicate edges (by ID or source-target-label triple).
 * - Avoids dangling edges connecting non-existent nodes.
 * - Preserves existing node positions with zero layout drift.
 */
export function mergeGraphData(
  existingNodes: Node<EntityNodeData>[],
  existingEdges: Edge[],
  parentNode: Node<EntityNodeData>,
  newChildren: GraphNodeModel[],
  newRelationships: GraphRelationshipModel[],
  options: MergeGraphOptions = {}
): {
  mergedNodes: Node<EntityNodeData>[];
  mergedEdges: Edge[];
  addedNodeIds: string[];
} {
  const existingNodeMap = new Map<string, Node<EntityNodeData>>();
  for (const n of existingNodes) {
    existingNodeMap.set(n.id, n);
  }

  // De-duplicate incoming children against existing nodes and within incoming payload
  const uniqueNewChildren: GraphNodeModel[] = [];
  const incomingSeen = new Set<string>();

  for (const child of newChildren) {
    if (!child || !child.id) continue;
    if (existingNodeMap.has(child.id) || incomingSeen.has(child.id)) {
      continue;
    }
    incomingSeen.add(child.id);
    uniqueNewChildren.push(child);
  }

  // Calculate coordinates for newly added nodes only
  const newPositions = computeIncrementalChildPositions(
    parentNode,
    uniqueNewChildren,
    existingNodes
  );

  const addedNodeIds: string[] = [];
  const createdNodes: Node<EntityNodeData>[] = uniqueNewChildren.map((rawChild) => {
    addedNodeIds.push(rawChild.id);
    const pos = newPositions.get(rawChild.id) || {
      x: parentNode.position.x + 280,
      y: parentNode.position.y,
    };
    const displayName = getNodeDisplayLabel(rawChild);
    const rawType = rawChild.type || rawChild.label || "Entity";

    return {
      id: rawChild.id,
      type: "entityNode",
      position: pos,
      data: {
        id: rawChild.id,
        label: rawChild.label || rawChild.type || "Entity",
        name: rawChild.name || rawChild.id,
        type: rawType,
        displayName,
        properties: rawChild.properties || {},
        isExpandable: !isKnownLeafType(rawType),
        isExpanded: options.expandedNodeIds?.has(rawChild.id) || false,
        isLoadingChildren: options.loadingNodeIds?.has(rawChild.id) || false,
        onToggleExpand: options.onToggleExpand,
      },
    };
  });

  // Update existing nodes to ensure parent is marked expanded and handlers are bound
  const updatedExistingNodes = existingNodes.map((n) => {
    const isTargetParent = n.id === parentNode.id;
    return {
      ...n,
      data: {
        ...n.data,
        isExpanded: isTargetParent ? true : options.expandedNodeIds?.has(n.id) || false,
        isLoadingChildren: options.loadingNodeIds?.has(n.id) || false,
        onToggleExpand: options.onToggleExpand || n.data.onToggleExpand,
      },
    };
  });

  const mergedNodes = [...updatedExistingNodes, ...createdNodes];
  const allNodeIds = new Set(mergedNodes.map((n) => n.id));

  // Build edge lookup to prevent duplicates
  const existingEdgeKeys = new Set<string>();
  const existingEdgeIds = new Set<string>();

  for (const edge of existingEdges) {
    existingEdgeIds.add(edge.id);
    existingEdgeKeys.add(`${edge.source}->${edge.target}:${edge.label || ""}`);
  }

  const mergedEdges = [...existingEdges];

  for (const rel of newRelationships) {
    if (!rel || !rel.source || !rel.target) continue;

    // Reject dangling edges
    if (!allNodeIds.has(rel.source) || !allNodeIds.has(rel.target)) {
      continue;
    }

    const key = `${rel.source}->${rel.target}:${rel.type || ""}`;
    if (existingEdgeIds.has(rel.id) || existingEdgeKeys.has(key)) {
      continue;
    }

    existingEdgeIds.add(rel.id);
    existingEdgeKeys.add(key);

    const edgeStyle = getRelationshipEdgeStyle(rel.type);

    mergedEdges.push({
      id: rel.id,
      source: rel.source,
      target: rel.target,
      label: rel.type || "CONTAINS",
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

  return { mergedNodes, mergedEdges, addedNodeIds };
}

/**
 * Recursively collects all descendant node IDs introduced by expanding a given parent.
 */
export function collectDescendantIds(
  rootId: string,
  parentToChildrenMap: Map<string, Set<string>>
): Set<string> {
  const result = new Set<string>();
  const queue = [rootId];

  while (queue.length > 0) {
    const current = queue.shift()!;
    const children = parentToChildrenMap.get(current);
    if (children) {
      for (const childId of children) {
        if (!result.has(childId)) {
          result.add(childId);
          queue.push(childId);
        }
      }
    }
  }

  return result;
}

/**
 * Collapses a parent node and removes its revealed descendants from the active graph.
 */
export function collapseNodeDescendants(
  parentId: string,
  parentToChildrenMap: Map<string, Set<string>>,
  existingNodes: Node<EntityNodeData>[],
  existingEdges: Edge[]
): {
  updatedNodes: Node<EntityNodeData>[];
  updatedEdges: Edge[];
  removedNodeIds: Set<string>;
} {
  const removedNodeIds = collectDescendantIds(parentId, parentToChildrenMap);

  const updatedNodes = existingNodes
    .filter((n) => !removedNodeIds.has(n.id))
    .map((n) => {
      if (n.id === parentId) {
        return {
          ...n,
          data: {
            ...n.data,
            isExpanded: false,
          },
        };
      }
      return n;
    });

  const updatedEdges = existingEdges.filter(
    (e) => !removedNodeIds.has(e.source) && !removedNodeIds.has(e.target)
  );

  return { updatedNodes, updatedEdges, removedNodeIds };
}

/**
 * Default mock / prototype progressive exploration adapter.
 * Provides realistic software repository hierarchy data for prototype exploration
 * until Developer A's revised backend contract is finalized.
 */
export type MockFetchNodeChildrenFn = (
  repositoryId: string,
  parentNodeId: string,
  options?: { signal?: AbortSignal }
) => Promise<NodeChildrenResponse>;

export const mockFetchNodeChildren: MockFetchNodeChildrenFn = async (
  _repositoryId: string,
  parentNodeId: string,
  options?: { signal?: AbortSignal }
): Promise<NodeChildrenResponse> => {
  // Respect abort signal if provided
  if (options?.signal?.aborted) {
    const err = new Error("Expansion request aborted");
    err.name = "AbortError";
    throw err;
  }

  // Artificial slight latency simulation (50ms) to model asynchronous behavior
  await new Promise((resolve) => setTimeout(resolve, 50));

  const cleanId = (parentNodeId || "").trim();
  const shortName = extractEntityShortName(cleanId);

  // If node is a file (e.g. ends in .py or contains file tag)
  if (shortName.endsWith(".py") || cleanId.includes("::file::") || cleanId.includes("/file/")) {
    const baseName = shortName.replace(".py", "").replace("file::", "");
    const className = `${baseName.charAt(0).toUpperCase() + baseName.slice(1)}Handler`;
    const sep = cleanId.includes("::") ? "::" : ":";

    return {
      parent_id: cleanId,
      nodes: [
        {
          id: `${cleanId}${sep}${className}`,
          label: "class",
          name: className,
          type: "class",
          display_name: className,
          properties: { file_path: cleanId },
        },
        {
          id: `${cleanId}${sep}run_${baseName}`,
          label: "function",
          name: `run_${baseName}`,
          type: "function",
          display_name: `run_${baseName}()`,
          properties: { file_path: cleanId },
        },
        {
          id: `${cleanId}${sep}import:typing`,
          label: "import",
          name: "typing",
          type: "import",
          display_name: "import typing",
          properties: { file_path: cleanId },
        },
      ],
      relationships: [
        {
          id: `rel:${cleanId}->${cleanId}${sep}${className}`,
          source: cleanId,
          target: `${cleanId}${sep}${className}`,
          type: "CONTAINS",
        },
        {
          id: `rel:${cleanId}->${cleanId}${sep}run_${baseName}`,
          source: cleanId,
          target: `${cleanId}${sep}run_${baseName}`,
          type: "CONTAINS",
        },
        {
          id: `rel:${cleanId}->${cleanId}${sep}import:typing`,
          source: cleanId,
          target: `${cleanId}${sep}import:typing`,
          type: "CONTAINS",
        },
      ],
    };
  }

  // If node is a repository root
  if (
    cleanId.startsWith("repo::") &&
    !cleanId.includes("::file::") &&
    !cleanId.includes("::class::") &&
    !cleanId.includes("::function::") &&
    !cleanId.includes("::method::") &&
    !cleanId.includes("::import::") &&
    !cleanId.includes("::module::")
  ) {
    return {
      parent_id: cleanId,
      nodes: [
        {
          id: `${cleanId}::file::main.py`,
          label: "file",
          name: "main.py",
          type: "file",
          display_name: "main.py",
          properties: { repo: cleanId },
        },
        {
          id: `${cleanId}::file::config.py`,
          label: "file",
          name: "config.py",
          type: "file",
          display_name: "config.py",
          properties: { repo: cleanId },
        },
      ],
      relationships: [
        {
          id: `rel:${cleanId}->${cleanId}::file::main.py`,
          source: cleanId,
          target: `${cleanId}::file::main.py`,
          type: "CONTAINS",
        },
        {
          id: `rel:${cleanId}->${cleanId}::file::config.py`,
          source: cleanId,
          target: `${cleanId}::file::config.py`,
          type: "CONTAINS",
        },
      ],
    };
  }

  // If node is a module
  if (cleanId.includes("::module::")) {
    const modName = extractEntityShortName(cleanId);
    return {
      parent_id: cleanId,
      nodes: [
        {
          id: `${cleanId}::file::${modName}.py`,
          label: "file",
          name: `${modName}.py`,
          type: "file",
          display_name: `${modName}.py`,
          properties: { module: cleanId },
        },
      ],
      relationships: [
        {
          id: `rel:${cleanId}->${cleanId}::file::${modName}.py`,
          source: cleanId,
          target: `${cleanId}::file::${modName}.py`,
          type: "CONTAINS",
        },
      ],
    };
  }

  // If node is a class
  if (
    (cleanId.includes("::class::") ||
      shortName.endsWith("Handler") ||
      (!cleanId.includes("::") && cleanId.includes(":"))) &&
    !cleanId.includes("::function::") &&
    !cleanId.includes("::method::") &&
    !cleanId.includes("::import::") &&
    !cleanId.includes("(") &&
    !cleanId.includes("import:")
  ) {
    // If it's already a method, return 0 children (leaf)
    if (shortName.startsWith("__") || shortName.startsWith("run_") || shortName.startsWith("test_")) {
      return { parent_id: cleanId, nodes: [], relationships: [] };
    }

    const sep = cleanId.includes("::") ? "::" : ":";
    return {
      parent_id: cleanId,
      nodes: [
        {
          id: `${cleanId}${sep}__init__`,
          label: "method",
          name: "__init__",
          type: "method",
          display_name: `${shortName}.__init__()`,
          properties: { class_id: cleanId },
        },
        {
          id: `${cleanId}${sep}execute`,
          label: "method",
          name: "execute",
          type: "method",
          display_name: `${shortName}.execute()`,
          properties: { class_id: cleanId },
        },
      ],
      relationships: [
        {
          id: `rel:${cleanId}->${cleanId}${sep}__init__`,
          source: cleanId,
          target: `${cleanId}${sep}__init__`,
          type: "CONTAINS",
        },
        {
          id: `rel:${cleanId}->${cleanId}${sep}execute`,
          source: cleanId,
          target: `${cleanId}${sep}execute`,
          type: "CONTAINS",
        },
      ],
    };
  }

  // Fallback for leaf or unknown nodes: empty child set
  return {
    parent_id: cleanId,
    nodes: [],
    relationships: [],
  };
};

/**
 * Merges newly fetched neighbor nodes and incident relationships into existing React Flow state.
 */
export function mergeNeighborData(
  existingNodes: Node<EntityNodeData>[],
  existingEdges: Edge[],
  centerNode: Node<EntityNodeData>,
  neighborNodes: GraphNodeModel[],
  relationships: GraphRelationshipModel[],
  options: MergeGraphOptions = {}
): {
  mergedNodes: Node<EntityNodeData>[];
  mergedEdges: Edge[];
  addedNodeIds: string[];
} {
  return mergeGraphData(
    existingNodes,
    existingEdges,
    centerNode,
    neighborNodes,
    relationships,
    options
  );
}

/**
 * Adapter allowing getEntityChildren from lib/api.ts to be passed as a FetchNodeChildrenFn.
 */
export async function fetchEntityChildrenAdapter(
  repositoryId: string,
  parentNodeId: string,
  options?: { signal?: AbortSignal }
): Promise<EntityChildrenResponse> {
  return getEntityChildren(repositoryId, parentNodeId, options);
}
