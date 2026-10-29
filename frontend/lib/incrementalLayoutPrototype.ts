/**
 * Isolated Incremental Layout Prototype for Atlas AI (Checkpoint 5).
 *
 * Implements a lightweight, deterministic incremental layout strategy for newly
 * explored graph nodes relative to an expansion parent.
 *
 * Architectural Guarantees:
 * 1. Zero layout drift on existing nodes (coordinates are strictly preserved).
 * 2. Guaranteed bounded execution: candidate generation is strictly bounded and monotonic.
 * 3. 2D bounding-box collision avoidance against both existing nodes and newly placed siblings.
 * 4. Graceful handling of measured dimensions with robust fallback for unmeasured nodes.
 * 5. Bounded failure: returns explicit unplaced status instead of overlapping or hanging.
 * 6. Isolated prototype: does NOT modify or replace the production layout engine.
 */

export interface NodeDimension {
  width: number;
  height: number;
}

export type DimensionResolver = (
  nodeId: string,
  node?: Record<string, unknown>
) => Partial<NodeDimension> | undefined;

export interface PositionedNodeInput {
  id: string;
  position: { x: number; y: number };
  measured?: { width?: number; height?: number };
  width?: number;
  height?: number;
  data?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface DiscoveredNodeInput {
  id: string;
  label?: string;
  name?: string;
  type?: string;
  measured?: { width?: number; height?: number };
  width?: number;
  height?: number;
  properties?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface IncrementalLayoutOptions {
  /** Horizontal column offset from parent to start placing children (default: 280) */
  columnStep?: number;
  /** Horizontal gap between sub-columns or sibling nodes (default: 40) */
  horizontalGap?: number;
  /** Vertical gap between nodes in the same column (default: 20) */
  verticalGap?: number;
  /** Default width for nodes without measured dimensions (default: 220) */
  defaultNodeWidth?: number;
  /** Default height for nodes without measured dimensions (default: 68) */
  defaultNodeHeight?: number;
  /** Maximum number of sub-columns to explore to the right of parent (default: 3) */
  maxSubColumns?: number;
  /** Maximum vertical rows per sub-column before wrapping to next sub-column (default: 10) */
  maxRowsPerColumn?: number;
  /** Maximum vertical distance from parent Y to search (default: 3000) */
  maxVerticalDistance?: number;
  /** Maximum search iterations per node before returning unplaced (default: 60) */
  maxCandidatesPerNode?: number;
  /** Custom dimension resolver function */
  resolveDimension?: DimensionResolver;
}

export interface PlacedNodeResult {
  id: string;
  position: { x: number; y: number };
  dimensions: NodeDimension;
  subColumnIndex: number;
  rowIndex: number;
}

export type UnplacedReason =
  | "parent_not_found"
  | "invalid_node_id"
  | "duplicate_with_existing_node"
  | "duplicate_in_input"
  | "no_collision_free_position_within_bounds"
  | "invalid_parent_position";

export interface UnplacedNodeResult {
  id: string;
  reason: UnplacedReason;
  details?: string;
}

export interface IncrementalLayoutResult {
  placedNodes: Map<string, PlacedNodeResult>;
  unplacedNodes: UnplacedNodeResult[];
  summary: {
    totalRequested: number;
    placedCount: number;
    unplacedCount: number;
  };
}

export interface BoundingBox {
  left: number;
  top: number;
  right: number;
  bottom: number;
  width: number;
  height: number;
  id: string;
}

/**
 * Validates whether a value is a strictly positive finite number.
 */
export function isValidPositiveNumber(val: unknown): val is number {
  return typeof val === "number" && !isNaN(val) && isFinite(val) && val > 0;
}

/**
 * Resolves node dimensions in order of precedence:
 * 1. User-supplied DimensionResolver callback
 * 2. Node's measured dimensions (from React Flow ResizeObserver)
 * 3. Node's explicit width/height properties
 * 4. Configured default fallback dimensions
 */
export function resolveNodeDimensions(
  nodeId: string,
  rawNode: Record<string, unknown> | undefined,
  options: IncrementalLayoutOptions = {}
): NodeDimension {
  const defaultW = options.defaultNodeWidth ?? 220;
  const defaultH = options.defaultNodeHeight ?? 68;

  // 1. Check custom dimension resolver
  if (options.resolveDimension) {
    try {
      const custom = options.resolveDimension(nodeId, rawNode);
      if (custom) {
        const w = isValidPositiveNumber(custom.width) ? custom.width : defaultW;
        const h = isValidPositiveNumber(custom.height) ? custom.height : defaultH;
        return { width: w, height: h };
      }
    } catch {
      // Ignore resolver errors and fall back safely
    }
  }

  // 2. Check React Flow measured dimensions
  if (rawNode && typeof rawNode === "object") {
    const measured = (rawNode as { measured?: { width?: number; height?: number } }).measured;
    if (measured && isValidPositiveNumber(measured.width) && isValidPositiveNumber(measured.height)) {
      return { width: measured.width, height: measured.height };
    }

    // 3. Check explicit width/height
    const w = (rawNode as { width?: number }).width;
    const h = (rawNode as { height?: number }).height;
    if (isValidPositiveNumber(w) && isValidPositiveNumber(h)) {
      return { width: w, height: h };
    }
  }

  // 4. Default fallback
  return { width: defaultW, height: defaultH };
}

/**
 * Tests whether two 2D axis-aligned bounding boxes overlap, accounting for horizontal and vertical gaps.
 */
export function checkBoundingBoxCollision(
  boxA: BoundingBox,
  boxB: BoundingBox,
  horizontalGap: number = 0,
  verticalGap: number = 0
): boolean {
  return (
    boxA.left < boxB.right + horizontalGap &&
    boxA.right + horizontalGap > boxB.left &&
    boxA.top < boxB.bottom + verticalGap &&
    boxA.bottom + verticalGap > boxB.top
  );
}

/**
 * Computes non-overlapping coordinates for newly discovered nodes relative to an expansion parent.
 *
 * Algorithm Overview:
 * - Deterministic Grid Search with Collision-Adaptive Placement:
 *   New children are distributed across bounded sub-columns to the right of the parent.
 * - When a candidate coordinate collides with an existing or previously placed node's bounding box,
 *   the candidate Y advances monotonically to the bottom of the colliding obstacle plus vertical gap.
 * - If vertical search in the current sub-column exceeds maxVerticalDistance or maxCandidatesPerNode,
 *   search wraps to the next sub-column.
 * - If all sub-columns and candidates are exhausted without a collision-free placement, the node is
 *   explicitly reported as unplaced with reason 'no_collision_free_position_within_bounds'.
 */
export function computeIncrementalLayoutPrototype(
  existingNodes: PositionedNodeInput[],
  newNodes: DiscoveredNodeInput[],
  parentId: string,
  options: IncrementalLayoutOptions = {}
): IncrementalLayoutResult {
  const result: IncrementalLayoutResult = {
    placedNodes: new Map<string, PlacedNodeResult>(),
    unplacedNodes: [],
    summary: {
      totalRequested: newNodes?.length || 0,
      placedCount: 0,
      unplacedCount: 0,
    },
  };

  if (!newNodes || newNodes.length === 0) {
    return result;
  }

  // 1. Locate parent node in existing nodes
  const parentNode = existingNodes.find((n) => n && n.id === parentId);
  if (!parentNode) {
    for (const child of newNodes) {
      if (child && child.id) {
        result.unplacedNodes.push({
          id: child.id,
          reason: "parent_not_found",
          details: `Parent node '${parentId}' was not found in existing nodes list.`,
        });
      }
    }
    result.summary.unplacedCount = result.unplacedNodes.length;
    return result;
  }

  // Validate parent position
  if (
    !parentNode.position ||
    typeof parentNode.position.x !== "number" ||
    typeof parentNode.position.y !== "number" ||
    isNaN(parentNode.position.x) ||
    isNaN(parentNode.position.y)
  ) {
    for (const child of newNodes) {
      if (child && child.id) {
        result.unplacedNodes.push({
          id: child.id,
          reason: "invalid_parent_position",
          details: `Parent node '${parentId}' has invalid coordinates.`,
        });
      }
    }
    result.summary.unplacedCount = result.unplacedNodes.length;
    return result;
  }

  // 2. Configuration & defaults
  const columnStep = options.columnStep ?? 280;
  const horizontalGap = options.horizontalGap ?? 40;
  const verticalGap = options.verticalGap ?? 20;
  const maxSubColumns = Math.max(1, options.maxSubColumns ?? 3);
  const maxRowsPerColumn = Math.max(1, options.maxRowsPerColumn ?? 10);
  const maxVerticalDistance = options.maxVerticalDistance ?? 3000;
  const maxCandidatesPerNode = Math.max(10, options.maxCandidatesPerNode ?? 60);

  const parentX = parentNode.position.x;
  const parentY = parentNode.position.y;
  const baseTargetX = parentX + columnStep;

  // 3. Build lookup of existing node IDs and obstacle bounding boxes
  const existingIdSet = new Set<string>();
  const obstacles: BoundingBox[] = [];

  for (const n of existingNodes) {
    if (!n || !n.id) continue;
    existingIdSet.add(n.id);

    if (n.position && typeof n.position.x === "number" && typeof n.position.y === "number") {
      const dim = resolveNodeDimensions(n.id, n, options);
      obstacles.push({
        id: n.id,
        left: n.position.x,
        top: n.position.y,
        right: n.position.x + dim.width,
        bottom: n.position.y + dim.height,
        width: dim.width,
        height: dim.height,
      });
    }
  }

  // 4. Process incoming new nodes with deduplication
  const seenIncomingIds = new Set<string>();

  for (let nodeIdx = 0; nodeIdx < newNodes.length; nodeIdx++) {
    const rawChild = newNodes[nodeIdx];

    // Validate node ID
    if (!rawChild || typeof rawChild.id !== "string" || !rawChild.id.trim()) {
      result.unplacedNodes.push({
        id: rawChild?.id || `unknown_index_${nodeIdx}`,
        reason: "invalid_node_id",
        details: "Node ID is missing or empty.",
      });
      continue;
    }

    const childId = rawChild.id.trim();

    // Check duplicate against existing nodes
    if (existingIdSet.has(childId)) {
      result.unplacedNodes.push({
        id: childId,
        reason: "duplicate_with_existing_node",
        details: `Node '${childId}' already exists in active graph.`,
      });
      continue;
    }

    // Check duplicate within incoming batch
    if (seenIncomingIds.has(childId)) {
      result.unplacedNodes.push({
        id: childId,
        reason: "duplicate_in_input",
        details: `Node '${childId}' is duplicated in incoming discovered nodes.`,
      });
      continue;
    }

    seenIncomingIds.add(childId);

    const childDim = resolveNodeDimensions(childId, rawChild, options);

    // Initial sub-column assignment based on index to distribute wide child sets (e.g. 20+ children)
    const initialSubCol = Math.floor(result.placedNodes.size / maxRowsPerColumn) % maxSubColumns;
    let placed = false;

    // Try starting from initialSubCol, wrapping around through all available sub-columns
    for (let colAttempt = 0; colAttempt < maxSubColumns; colAttempt++) {
      const currentSubCol = (initialSubCol + colAttempt) % maxSubColumns;
      const targetColX = baseTargetX + currentSubCol * columnStep;

      // Start candidate Y at parentY or top boundary
      let candidateY = Math.max(parentY, 60);
      let iterationsLeft = maxCandidatesPerNode;

      while (iterationsLeft-- > 0) {
        // Enforce maximum vertical search boundary
        if (candidateY - parentY > maxVerticalDistance) {
          break;
        }

        const candidateBox: BoundingBox = {
          id: childId,
          left: targetColX,
          top: candidateY,
          right: targetColX + childDim.width,
          bottom: candidateY + childDim.height,
          width: childDim.width,
          height: childDim.height,
        };

        // Check for collisions against all known obstacles (existing + newly placed)
        let collidingObstacle: BoundingBox | null = null;

        for (const obs of obstacles) {
          if (checkBoundingBoxCollision(candidateBox, obs, horizontalGap, verticalGap)) {
            collidingObstacle = obs;
            break;
          }
        }

        if (!collidingObstacle) {
          // Found a collision-free position!
          const placedResult: PlacedNodeResult = {
            id: childId,
            position: { x: targetColX, y: candidateY },
            dimensions: childDim,
            subColumnIndex: currentSubCol,
            rowIndex: Math.floor((candidateY - parentY) / (childDim.height + verticalGap)),
          };

          result.placedNodes.set(childId, placedResult);

          // Register placed node as a new obstacle for subsequent siblings
          obstacles.push({
            id: childId,
            left: targetColX,
            top: candidateY,
            right: targetColX + childDim.width,
            bottom: candidateY + childDim.height,
            width: childDim.width,
            height: childDim.height,
          });

          placed = true;
          break;
        }

        // Monotonic progression: place below the colliding obstacle
        candidateY = collidingObstacle.bottom + verticalGap;
      }

      if (placed) {
        break;
      }
    }

    if (!placed) {
      result.unplacedNodes.push({
        id: childId,
        reason: "no_collision_free_position_within_bounds",
        details: `Exhausted search space across ${maxSubColumns} sub-columns (max distance: ${maxVerticalDistance}px).`,
      });
    }
  }

  result.summary.placedCount = result.placedNodes.size;
  result.summary.unplacedCount = result.unplacedNodes.length;

  return result;
}

