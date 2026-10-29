/**
 * Pure search filtering and ranking logic for Atlas AI in-memory graph nodes (Checkpoint 3).
 * Operates strictly on already-loaded nodes in the frontend without initiating backend requests.
 */

import type { Node } from "@xyflow/react";
import type { GraphNodeModel } from "./types.ts";
import type { EntityNodeData } from "./graphMapper.ts";

export interface SearchableEntityNode {
  id: string;
  name?: string;
  displayName?: string;
  display_name?: string | null;
  label?: string;
  type?: string;
  properties?: Record<string, unknown>;
  data?: {
    id?: string;
    name?: string;
    displayName?: string;
    display_name?: string | null;
    label?: string;
    type?: string;
    properties?: Record<string, unknown>;
  };
}

export type MatchFieldType = "displayName" | "name" | "id" | "path";

export interface GraphSearchResult {
  id: string;
  name: string;
  displayName: string;
  type: string;
  filePath?: string;
  matchField: MatchFieldType;
  score: number;
}

export interface SearchGraphOptions {
  limit?: number;
}

/**
 * Extracts normalized search fields from a React Flow node or backend GraphNodeModel.
 */
export function extractNodeSearchFields(node: SearchableEntityNode | Node<EntityNodeData> | GraphNodeModel) {
  const data = (node as { data?: Record<string, unknown> }).data;

  const id = String(data?.id || (node as { id?: unknown }).id || "").trim();
  const name = String(data?.name || (node as { name?: unknown }).name || id).trim();

  const rawDisplayName =
    data?.displayName ||
    data?.display_name ||
    (node as { displayName?: unknown }).displayName ||
    (node as { display_name?: unknown }).display_name;

  const displayName = String(rawDisplayName || name || id).trim();

  const type = String(
    data?.type ||
    data?.label ||
    (node as { type?: unknown }).type ||
    (node as { label?: unknown }).label ||
    "Entity"
  ).trim();

  const props = (data?.properties || (node as { properties?: unknown }).properties || {}) as Record<string, unknown>;

  const rawPath =
    typeof props.file_path === "string"
      ? props.file_path
      : typeof props.path === "string"
      ? props.path
      : typeof props.filepath === "string"
      ? props.filepath
      : undefined;

  const filePath = rawPath ? rawPath.trim() : undefined;

  return { id, name, displayName, type, filePath, props };
}

/**
 * Calculates a match score for a candidate string against a normalized query.
 * Higher score indicates higher match relevance:
 * - Exact match: 100
 * - Prefix match: 80
 * - Substring match: 50
 * - Word boundary match (e.g. after '_', '.', '/', or ':'): 65
 */
export function calculateMatchScore(candidate: string, queryLower: string): number {
  const lower = candidate.toLowerCase();
  if (lower === queryLower) {
    return 100;
  }
  if (lower.startsWith(queryLower)) {
    return 80;
  }

  // Word boundary match check
  const boundaryRegex = new RegExp(`[._/:\\s]${queryLower.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`);
  if (boundaryRegex.test(lower)) {
    return 65;
  }

  if (lower.includes(queryLower)) {
    return 50;
  }

  return 0;
}

/**
 * Searches loaded graph nodes in-memory against a user query string.
 *
 * Rules:
 * - Empty or whitespace-only queries return an empty list immediately.
 * - Searches strictly loaded nodes; never initiates network calls.
 * - Case-insensitive matching across:
 *   1. displayName (highest priority)
 *   2. name
 *   3. id
 *   4. path / file_path
 * - Sorts results descending by relevance score, then shorter string length, then alphabetical.
 */
export function searchGraphNodes(
  nodes: Array<SearchableEntityNode | Node<EntityNodeData> | GraphNodeModel>,
  query: string,
  options: SearchGraphOptions = {}
): GraphSearchResult[] {
  if (!query || !query.trim() || !Array.isArray(nodes) || nodes.length === 0) {
    return [];
  }

  const queryLower = query.trim().toLowerCase();
  const limit = options.limit !== undefined && options.limit > 0 ? options.limit : 20;

  const results: GraphSearchResult[] = [];

  for (const rawNode of nodes) {
    if (!rawNode) continue;

    const { id, name, displayName, type, filePath } = extractNodeSearchFields(rawNode);
    if (!id) continue;

    // Check matches in field priority order
    const displayScore = calculateMatchScore(displayName, queryLower);
    const nameScore = calculateMatchScore(name, queryLower);
    const idScore = calculateMatchScore(id, queryLower);
    const pathScore = filePath ? calculateMatchScore(filePath, queryLower) : 0;

    let bestScore = 0;
    let matchField: MatchFieldType = "displayName";

    if (displayScore > 0) {
      bestScore = displayScore + 10; // Bias toward display name
      matchField = "displayName";
    } else if (nameScore > 0) {
      bestScore = nameScore + 5; // Bias toward name
      matchField = "name";
    } else if (idScore > 0) {
      bestScore = idScore;
      matchField = "id";
    } else if (pathScore > 0) {
      bestScore = pathScore - 5;
      matchField = "path";
    }

    if (bestScore > 0) {
      results.push({
        id,
        name,
        displayName,
        type,
        filePath,
        matchField,
        score: bestScore,
      });
    }
  }

  // Sort descending by score, then ascending by length of matched field, then alphabetical
  results.sort((a, b) => {
    if (b.score !== a.score) {
      return b.score - a.score;
    }
    const lenA = a.displayName.length;
    const lenB = b.displayName.length;
    if (lenA !== lenB) {
      return lenA - lenB;
    }
    return a.displayName.localeCompare(b.displayName);
  });

  return results.slice(0, limit);
}

