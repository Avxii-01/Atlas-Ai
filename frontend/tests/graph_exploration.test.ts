import test, { describe, it } from "node:test";
import assert from "node:assert/strict";

import type { Node, Edge } from "@xyflow/react";
import type { GraphNodeModel, GraphRelationshipModel } from "../lib/types.ts";
import type { EntityNodeData } from "../lib/graphMapper.ts";
import {
  computeIncrementalChildPositions,
  mergeGraphData,
  collapseNodeDescendants,
  collectDescendantIds,
  mockFetchNodeChildren,
  isKnownLeafType,
  extractEntityShortName,
  type NodeChildrenResponse,
} from "../lib/progressiveExploration.ts";
import { searchGraphNodes } from "../lib/graphSearch.ts";
import { getEntityBadgeStyle, getRelationshipEdgeStyle } from "../lib/graphTokens.ts";

// Base fixture nodes simulating an initial repository graph slice
const baseFixtureNodes: Node<EntityNodeData>[] = [
  {
    id: "atlas_fixture/app.py",
    type: "entityNode",
    position: { x: 340, y: 100 },
    data: {
      id: "atlas_fixture/app.py",
      label: "file",
      name: "app.py",
      type: "file",
      displayName: "app.py",
      properties: { file_path: "atlas_fixture/app.py" },
      isExpandable: true,
      isExpanded: false,
    },
  },
  {
    id: "atlas_fixture/core.py",
    type: "entityNode",
    position: { x: 340, y: 220 },
    data: {
      id: "atlas_fixture/core.py",
      label: "file",
      name: "core.py",
      type: "file",
      displayName: "core.py",
      properties: { file_path: "atlas_fixture/core.py" },
      isExpandable: true,
      isExpanded: false,
    },
  },
];

const baseFixtureEdges: Edge[] = [
  {
    id: "rel:repo->app",
    source: "atlas_fixture",
    target: "atlas_fixture/app.py",
    label: "CONTAINS",
    type: "smoothstep",
  },
  {
    id: "rel:repo->core",
    source: "atlas_fixture",
    target: "atlas_fixture/core.py",
    label: "CONTAINS",
    type: "smoothstep",
  },
];

describe("Progressive Graph Exploration - Incremental Layout & Merging (Checkpoint 4)", () => {
  it("computes non-overlapping incremental child positions preserving existing node coordinates", () => {
    const parentNode = baseFixtureNodes[0]; // (340, 100)
    const children: GraphNodeModel[] = [
      { id: "child:1", label: "class", name: "ClassA", type: "class" },
      { id: "child:2", label: "function", name: "funcB", type: "function" },
    ];

    const positions = computeIncrementalChildPositions(parentNode, children, baseFixtureNodes);

    assert.equal(positions.size, 2);
    const pos1 = positions.get("child:1")!;
    const pos2 = positions.get("child:2")!;

    // Positioned in target column to the right of parent (340 + 280 = 620)
    assert.equal(pos1.x, 620);
    assert.equal(pos2.x, 620);

    // Vertical spacing
    assert.ok(pos2.y > pos1.y);
    assert.ok(pos2.y - pos1.y >= 85);

    // Existing nodes retain exact positions
    assert.equal(baseFixtureNodes[0].position.x, 340);
    assert.equal(baseFixtureNodes[0].position.y, 100);
    assert.equal(baseFixtureNodes[1].position.x, 340);
    assert.equal(baseFixtureNodes[1].position.y, 220);
  });

  it("regression test: does NOT freeze or enter infinite loop when target column already contains occupied nodes", () => {
    const parentNode = baseFixtureNodes[0]; // (340, 100), targetX = 620

    // Column 620 already has multiple existing nodes (as in 50+ node graphs)
    const existingWithCollisions: Node<EntityNodeData>[] = [
      ...baseFixtureNodes,
      {
        id: "existing_col2_node1",
        type: "entityNode",
        position: { x: 620, y: 60 },
        data: { id: "c1", label: "class", name: "C1", type: "class", displayName: "C1", properties: {} },
      },
      {
        id: "existing_col2_node2",
        type: "entityNode",
        position: { x: 620, y: 145 },
        data: { id: "c2", label: "class", name: "C2", type: "class", displayName: "C2", properties: {} },
      },
      {
        id: "existing_col2_node3",
        type: "entityNode",
        position: { x: 620, y: 230 },
        data: { id: "c3", label: "class", name: "C3", type: "class", displayName: "C3", properties: {} },
      },
    ];

    const childrenToPlace: GraphNodeModel[] = [
      { id: "new_child_1", label: "class", name: "NewClass1", type: "class" },
      { id: "new_child_2", label: "function", name: "NewFunc2", type: "function" },
    ];

    const startTime = Date.now();
    const positions = computeIncrementalChildPositions(parentNode, childrenToPlace, existingWithCollisions);
    const duration = Date.now() - startTime;

    // Must finish immediately (< 50ms) without infinite loop
    assert.ok(duration < 50, `Expected instant execution, took ${duration}ms`);
    assert.equal(positions.size, 2);

    const pos1 = positions.get("new_child_1")!;
    const pos2 = positions.get("new_child_2")!;

    assert.equal(pos1.x, 620);
    assert.equal(pos2.x, 620);

    // Must be placed below the existing collision intervals
    assert.ok(pos1.y > 230, `pos1.y (${pos1.y}) should be placed below existing nodes (y > 230)`);
    assert.ok(pos2.y > pos1.y, `pos2.y (${pos2.y}) should be placed below pos1.y (${pos1.y})`);
  });

  it("regression test: handles a realistic 53-node multi-column repository graph without freezing", () => {
    // Generate realistic 53 nodes across tiers 0..4 mirroring repo::atlas_fixture
    const realistic53Nodes: Node<EntityNodeData>[] = [];
    const columns = [60, 340, 620, 900, 1180];

    let idCounter = 0;
    for (const colX of columns) {
      for (let row = 0; row < 11; row++) {
        if (idCounter >= 53) break;
        const nodeId = `node_${idCounter++}`;
        realistic53Nodes.push({
          id: nodeId,
          type: "entityNode",
          position: { x: colX, y: 60 + row * 85 },
          data: {
            id: nodeId,
            label: "class",
            name: `Entity_${nodeId}`,
            type: "class",
            displayName: `Entity_${nodeId}`,
            properties: {},
          },
        });
      }
    }

    assert.equal(realistic53Nodes.length, 53);

    // Pick a node in column 340 to expand
    const fileNode = realistic53Nodes.find((n) => n.position.x === 340)!;

    const children: GraphNodeModel[] = [
      { id: "child_exp_1", label: "class", name: "Exp1", type: "class" },
      { id: "child_exp_2", label: "function", name: "Exp2", type: "function" },
      { id: "child_exp_3", label: "import", name: "Exp3", type: "import" },
    ];

    const startTime = Date.now();
    const result = computeIncrementalChildPositions(fileNode, children, realistic53Nodes);
    const duration = Date.now() - startTime;

    assert.ok(duration < 50, `Execution on 53 nodes must take < 50ms, took ${duration}ms`);
    assert.equal(result.size, 3);

    for (const [cId, pos] of result) {
      assert.equal(pos.x, 340 + 280);
      assert.ok(pos.y > 0);
    }
  });

  it("expands a node with children and merges them cleanly", () => {
    const parentNode = baseFixtureNodes[0];
    const incomingChildren: GraphNodeModel[] = [
      {
        id: "atlas_fixture/app.py:RepositoryAnalyzer",
        label: "class",
        name: "RepositoryAnalyzer",
        type: "class",
        display_name: "RepositoryAnalyzer",
      },
      {
        id: "atlas_fixture/app.py:analyze_code",
        label: "function",
        name: "analyze_code",
        type: "function",
        display_name: "analyze_code()",
      },
    ];

    const incomingRels: GraphRelationshipModel[] = [
      {
        id: "rel:app->analyzer",
        source: "atlas_fixture/app.py",
        target: "atlas_fixture/app.py:RepositoryAnalyzer",
        type: "CONTAINS",
      },
      {
        id: "rel:app->analyze_code",
        source: "atlas_fixture/app.py",
        target: "atlas_fixture/app.py:analyze_code",
        type: "CONTAINS",
      },
    ];

    const { mergedNodes, mergedEdges, addedNodeIds } = mergeGraphData(
      baseFixtureNodes,
      baseFixtureEdges,
      parentNode,
      incomingChildren,
      incomingRels
    );

    // 2 original + 2 new = 4 total nodes
    assert.equal(mergedNodes.length, 4);
    assert.equal(addedNodeIds.length, 2);
    assert.deepEqual(addedNodeIds, [
      "atlas_fixture/app.py:RepositoryAnalyzer",
      "atlas_fixture/app.py:analyze_code",
    ]);

    // Parent is marked expanded
    const updatedParent = mergedNodes.find((n) => n.id === parentNode.id);
    assert.equal(updatedParent?.data.isExpanded, true);

    // 2 original + 2 new = 4 total edges
    assert.equal(mergedEdges.length, 4);

    // Verify existing node positions are strictly preserved
    const orig0 = mergedNodes.find((n) => n.id === baseFixtureNodes[0].id)!;
    const orig1 = mergedNodes.find((n) => n.id === baseFixtureNodes[1].id)!;
    assert.deepEqual(orig0.position, baseFixtureNodes[0].position);
    assert.deepEqual(orig1.position, baseFixtureNodes[1].position);
  });

  it("handles duplicate nodes and duplicate edges in returned payload gracefully", () => {
    const parentNode = baseFixtureNodes[0];

    // Payload includes a node that is ALREADY on canvas ("atlas_fixture/core.py")
    // and duplicate copies of a new node
    const incomingChildren: GraphNodeModel[] = [
      {
        id: "atlas_fixture/core.py", // Already exists!
        label: "file",
        name: "core.py",
        type: "file",
      },
      {
        id: "atlas_fixture/app.py:NewClass",
        label: "class",
        name: "NewClass",
        type: "class",
      },
      {
        id: "atlas_fixture/app.py:NewClass", // Duplicate in same payload!
        label: "class",
        name: "NewClass",
        type: "class",
      },
    ];

    const incomingRels: GraphRelationshipModel[] = [
      {
        id: "rel:app->newclass",
        source: "atlas_fixture/app.py",
        target: "atlas_fixture/app.py:NewClass",
        type: "CONTAINS",
      },
      {
        id: "rel:app->newclass", // Duplicate rel
        source: "atlas_fixture/app.py",
        target: "atlas_fixture/app.py:NewClass",
        type: "CONTAINS",
      },
    ];

    const { mergedNodes, mergedEdges, addedNodeIds } = mergeGraphData(
      baseFixtureNodes,
      baseFixtureEdges,
      parentNode,
      incomingChildren,
      incomingRels
    );

    // Only 1 new node was added
    assert.equal(addedNodeIds.length, 1);
    assert.equal(addedNodeIds[0], "atlas_fixture/app.py:NewClass");
    assert.equal(mergedNodes.length, 3); // 2 base + 1 new

    // Only 1 new edge was added
    assert.equal(mergedEdges.length, 3); // 2 base + 1 new
  });

  it("rejects dangling edges connecting non-existent nodes", () => {
    const parentNode = baseFixtureNodes[0];
    const incomingChildren: GraphNodeModel[] = [
      { id: "valid_child", label: "class", name: "ValidClass", type: "class" },
    ];

    const incomingRels: GraphRelationshipModel[] = [
      {
        id: "rel:valid",
        source: "atlas_fixture/app.py",
        target: "valid_child",
        type: "CONTAINS",
      },
      {
        id: "rel:dangling",
        source: "atlas_fixture/app.py",
        target: "ghost_nonexistent_node",
        type: "CONTAINS",
      },
    ];

    const { mergedEdges } = mergeGraphData(
      baseFixtureNodes,
      baseFixtureEdges,
      parentNode,
      incomingChildren,
      incomingRels
    );

    assert.equal(mergedEdges.length, 3); // 2 base + 1 valid edge (dangling edge skipped)
    assert.equal(mergedEdges.some((e) => e.target === "ghost_nonexistent_node"), false);
  });
});

describe("Progressive Exploration - Collapse and Re-expansion (Checkpoint 4)", () => {
  it("recursively collapses descendants and removes associated edges", () => {
    const parentId = "atlas_fixture/app.py";
    const child1Id = "atlas_fixture/app.py:ClassA";
    const grandChildId = "atlas_fixture/app.py:ClassA:methodB";

    const parentToChildren = new Map<string, Set<string>>([
      [parentId, new Set([child1Id])],
      [child1Id, new Set([grandChildId])],
    ]);

    const activeNodes: Node<EntityNodeData>[] = [
      ...baseFixtureNodes,
      {
        id: child1Id,
        type: "entityNode",
        position: { x: 620, y: 100 },
        data: {
          id: child1Id,
          label: "class",
          name: "ClassA",
          type: "class",
          displayName: "ClassA",
          properties: {},
          isExpanded: true,
        },
      },
      {
        id: grandChildId,
        type: "entityNode",
        position: { x: 900, y: 100 },
        data: {
          id: grandChildId,
          label: "method",
          name: "methodB",
          type: "method",
          displayName: "methodB",
          properties: {},
          isExpanded: false,
        },
      },
    ];

    const activeEdges: Edge[] = [
      ...baseFixtureEdges,
      { id: "e1", source: parentId, target: child1Id, label: "CONTAINS" },
      { id: "e2", source: child1Id, target: grandChildId, label: "CONTAINS" },
    ];

    const { updatedNodes, updatedEdges, removedNodeIds } = collapseNodeDescendants(
      parentId,
      parentToChildren,
      activeNodes,
      activeEdges
    );

    // Both child and grandchild are removed
    assert.equal(removedNodeIds.size, 2);
    assert.ok(removedNodeIds.has(child1Id));
    assert.ok(removedNodeIds.has(grandChildId));

    // Remaining nodes are only the original base nodes
    assert.equal(updatedNodes.length, 2);
    assert.deepEqual(
      updatedNodes.map((n) => n.id),
      ["atlas_fixture/app.py", "atlas_fixture/core.py"]
    );

    // Parent is marked collapsed
    const collapsedParent = updatedNodes.find((n) => n.id === parentId);
    assert.equal(collapsedParent?.data.isExpanded, false);

    // Edges connected to descendants are removed
    assert.equal(updatedEdges.length, 2);
    assert.deepEqual(
      updatedEdges.map((e) => e.id),
      ["rel:repo->app", "rel:repo->core"]
    );
  });
});

describe("Progressive Exploration State Machine Simulation (Checkpoint 4)", () => {
  class MockExplorationCoordinator {
    nodes: Node<EntityNodeData>[];
    edges: Edge[];
    expandedNodeIds: Set<string> = new Set();
    loadingNodeIds: Set<string> = new Set();
    parentToChildrenMap: Map<string, Set<string>> = new Map();
    fetchCallCount: number = 0;
    lastError: string | null = null;

    constructor(initialNodes: Node<EntityNodeData>[], initialEdges: Edge[]) {
      this.nodes = [...initialNodes];
      this.edges = [...initialEdges];
    }

    async toggleExpand(
      nodeId: string,
      fetchFn: (repoId: string, parentId: string) => Promise<NodeChildrenResponse>
    ) {
      if (this.loadingNodeIds.has(nodeId)) {
        return; // Idempotent guard
      }

      // If already expanded, collapse
      if (this.expandedNodeIds.has(nodeId)) {
        const { updatedNodes, updatedEdges, removedNodeIds } = collapseNodeDescendants(
          nodeId,
          this.parentToChildrenMap,
          this.nodes,
          this.edges
        );
        this.parentToChildrenMap.delete(nodeId);
        this.expandedNodeIds.delete(nodeId);
        for (const r of removedNodeIds) {
          this.expandedNodeIds.delete(r);
        }
        this.nodes = updatedNodes;
        this.edges = updatedEdges;
        return;
      }

      // Expand
      const parent = this.nodes.find((n) => n.id === nodeId);
      if (!parent) return;

      this.loadingNodeIds.add(nodeId);
      this.fetchCallCount++;
      this.lastError = null;

      try {
        const response = await fetchFn("atlas_fixture", nodeId);

        if (!response.nodes || response.nodes.length === 0) {
          // Empty children
          this.nodes = this.nodes.map((n) =>
            n.id === nodeId ? { ...n, data: { ...n.data, hasNoChildren: true } } : n
          );
          this.loadingNodeIds.delete(nodeId);
          return;
        }

        const { mergedNodes, mergedEdges, addedNodeIds } = mergeGraphData(
          this.nodes,
          this.edges,
          parent,
          response.nodes,
          response.relationships,
          { expandedNodeIds: this.expandedNodeIds }
        );

        this.parentToChildrenMap.set(nodeId, new Set(addedNodeIds));
        this.expandedNodeIds.add(nodeId);
        this.loadingNodeIds.delete(nodeId);
        this.nodes = mergedNodes;
        this.edges = mergedEdges;
      } catch (err: unknown) {
        this.loadingNodeIds.delete(nodeId);
        this.lastError = err instanceof Error ? err.message : "Failed to expand node";
      }
    }
  }

  it("handles expanding a node with children through the state machine", async () => {
    const coordinator = new MockExplorationCoordinator(baseFixtureNodes, baseFixtureEdges);

    await coordinator.toggleExpand("atlas_fixture/app.py", mockFetchNodeChildren);

    assert.equal(coordinator.expandedNodeIds.has("atlas_fixture/app.py"), true);
    assert.equal(coordinator.nodes.length > baseFixtureNodes.length, true);
    assert.equal(coordinator.edges.length > baseFixtureEdges.length, true);
    assert.equal(coordinator.fetchCallCount, 1);
  });

  it("handles expanding a node with no children gracefully", async () => {
    const coordinator = new MockExplorationCoordinator(baseFixtureNodes, baseFixtureEdges);

    // Mock returning 0 children
    await coordinator.toggleExpand("atlas_fixture/app.py", async () => ({
      parent_id: "atlas_fixture/app.py",
      nodes: [],
      relationships: [],
    }));

    // Not marked as expanded
    assert.equal(coordinator.expandedNodeIds.has("atlas_fixture/app.py"), false);
    // Node is marked as hasNoChildren: true
    const node = coordinator.nodes.find((n) => n.id === "atlas_fixture/app.py")!;
    assert.equal(node.data.hasNoChildren, true);
    // Node count remains unchanged
    assert.equal(coordinator.nodes.length, baseFixtureNodes.length);
  });

  it("prevents duplicate concurrent expansion requests for the same node", async () => {
    const coordinator = new MockExplorationCoordinator(baseFixtureNodes, baseFixtureEdges);

    let resolvePromise: (val: NodeChildrenResponse) => void = () => {};
    const pendingPromise = new Promise<NodeChildrenResponse>((resolve) => {
      resolvePromise = resolve;
    });

    // 1st click initiates fetch
    const p1 = coordinator.toggleExpand("atlas_fixture/app.py", async () => pendingPromise);
    assert.equal(coordinator.loadingNodeIds.has("atlas_fixture/app.py"), true);
    assert.equal(coordinator.fetchCallCount, 1);

    // 2nd rapid click while loading is ignored
    const p2 = coordinator.toggleExpand("atlas_fixture/app.py", async () => pendingPromise);
    assert.equal(coordinator.fetchCallCount, 1); // No new call made!

    resolvePromise({
      parent_id: "atlas_fixture/app.py",
      nodes: [{ id: "new_c", label: "class", name: "C", type: "class" }],
      relationships: [],
    });

    await Promise.all([p1, p2]);
    assert.equal(coordinator.loadingNodeIds.has("atlas_fixture/app.py"), false);
    assert.equal(coordinator.expandedNodeIds.has("atlas_fixture/app.py"), true);
  });

  it("handles error state without corrupting existing graph state and allows retry", async () => {
    const coordinator = new MockExplorationCoordinator(baseFixtureNodes, baseFixtureEdges);

    // 1. First expansion attempt fails
    await coordinator.toggleExpand("atlas_fixture/app.py", async () => {
      throw new Error("Network disruption fetching children");
    });

    assert.equal(coordinator.lastError, "Network disruption fetching children");
    assert.equal(coordinator.loadingNodeIds.size, 0);
    assert.equal(coordinator.expandedNodeIds.size, 0);
    assert.equal(coordinator.nodes.length, baseFixtureNodes.length); // Uncorrupted

    // 2. Retry succeeds
    await coordinator.toggleExpand("atlas_fixture/app.py", mockFetchNodeChildren);
    assert.equal(coordinator.lastError, null);
    assert.equal(coordinator.expandedNodeIds.has("atlas_fixture/app.py"), true);
    assert.ok(coordinator.nodes.length > baseFixtureNodes.length);
  });

  it("supports collapsing and re-expanding", async () => {
    const coordinator = new MockExplorationCoordinator(baseFixtureNodes, baseFixtureEdges);

    // 1. Expand
    await coordinator.toggleExpand("atlas_fixture/app.py", mockFetchNodeChildren);
    assert.equal(coordinator.expandedNodeIds.has("atlas_fixture/app.py"), true);
    const countAfterExpand = coordinator.nodes.length;
    assert.ok(countAfterExpand > baseFixtureNodes.length);

    // 2. Collapse
    await coordinator.toggleExpand("atlas_fixture/app.py", mockFetchNodeChildren);
    assert.equal(coordinator.expandedNodeIds.has("atlas_fixture/app.py"), false);
    assert.equal(coordinator.nodes.length, baseFixtureNodes.length);

    // 3. Re-expand
    await coordinator.toggleExpand("atlas_fixture/app.py", mockFetchNodeChildren);
    assert.equal(coordinator.expandedNodeIds.has("atlas_fixture/app.py"), true);
    assert.equal(coordinator.nodes.length, countAfterExpand);
  });
});

describe("Integration: Search, Legend & Selection over Progressively Loaded Nodes (Checkpoint 4)", () => {
  it("searches newly revealed child nodes that were not present in initial graph", async () => {
    // 1. Expand app.py using mock adapter
    const parentNode = baseFixtureNodes[0];
    const response = await mockFetchNodeChildren("atlas_fixture", parentNode.id);
    const { mergedNodes } = mergeGraphData(
      baseFixtureNodes,
      baseFixtureEdges,
      parentNode,
      response.nodes,
      response.relationships
    );

    // Initially "AppHandler" was not in baseFixtureNodes
    assert.equal(searchGraphNodes(baseFixtureNodes, "AppHandler").length, 0);

    // After progressive expansion, local search finds the newly loaded node!
    const searchResults = searchGraphNodes(mergedNodes, "AppHandler");
    assert.ok(searchResults.length > 0);
    assert.equal(searchResults[0].displayName, "AppHandler");
    assert.equal(searchResults[0].type, "class");
  });

  it("verifies legend visual tokens match all progressively loaded entity and relationship types", async () => {
    const response = await mockFetchNodeChildren("atlas_fixture", "atlas_fixture/app.py");

    for (const node of response.nodes) {
      const style = getEntityBadgeStyle(node.type || node.label);
      assert.ok(style.bg.length > 0);
      assert.ok(style.text.length > 0);
      assert.ok(style.border.length > 0);
    }

    for (const rel of response.relationships) {
      const edgeStyle = getRelationshipEdgeStyle(rel.type);
      assert.ok(edgeStyle.stroke.startsWith("#"));
      assert.equal(edgeStyle.strokeWidth, 1.5);
    }
  });

  it("identifies leaf types correctly", () => {
    assert.equal(isKnownLeafType("method"), true);
    assert.equal(isKnownLeafType("import"), true);
    assert.equal(isKnownLeafType("class"), false);
    assert.equal(isKnownLeafType("file"), false);
    assert.equal(isKnownLeafType("repository"), false);
  });

  it("extracts short human-readable entity names across both '::' and '/' separators", () => {
    assert.equal(extractEntityShortName("repo::atlas_fixture::file::ambiguous.py"), "ambiguous.py");
    assert.equal(extractEntityShortName("atlas_fixture/app.py"), "app.py");
    assert.equal(extractEntityShortName("repo::atlas_fixture::class::RepositoryAnalyzer"), "RepositoryAnalyzer");
    assert.equal(extractEntityShortName("repo/src/utils/parser.py"), "parser.py");
    assert.equal(extractEntityShortName("standalone_symbol"), "standalone_symbol");
  });
});

describe("Progressive Exploration - Real Backend 'repo::atlas_fixture' Hierarchy & State Updates (Checkpoint 4)", () => {
  it("expands real backend file node format ('repo::atlas_fixture::file::...') returning valid children with '::' separator", async () => {
    const parentId = "repo::atlas_fixture::file::ambiguous.py";
    const res = await mockFetchNodeChildren("repo::atlas_fixture", parentId);

    assert.equal(res.parent_id, parentId);
    assert.equal(res.nodes.length, 3);
    assert.equal(res.relationships.length, 3);

    const classChild = res.nodes.find((n) => n.type === "class")!;
    const funcChild = res.nodes.find((n) => n.type === "function")!;
    const importChild = res.nodes.find((n) => n.type === "import")!;

    assert.ok(classChild);
    assert.ok(funcChild);
    assert.ok(importChild);

    assert.equal(classChild.id, `${parentId}::AmbiguousHandler`);
    assert.equal(funcChild.id, `${parentId}::run_ambiguous`);
    assert.equal(importChild.id, `${parentId}::import:typing`);

    // Verify relationships connect parent directly to children
    for (const rel of res.relationships) {
      assert.equal(rel.source, parentId);
      assert.ok(rel.target.startsWith(parentId));
      assert.equal(rel.type, "CONTAINS");
    }
  });

  it("expands repository root node ('repo::atlas_fixture') returning file children", async () => {
    const res = await mockFetchNodeChildren("repo::atlas_fixture", "repo::atlas_fixture");
    assert.equal(res.parent_id, "repo::atlas_fixture");
    assert.ok(res.nodes.length > 0);
    assert.ok(res.nodes.every((n) => n.type === "file"));
  });

  it("expands module node ('repo::atlas_fixture::module::...') returning file children", async () => {
    const res = await mockFetchNodeChildren("repo::atlas_fixture", "repo::atlas_fixture::module::ambiguous");
    assert.equal(res.parent_id, "repo::atlas_fixture::module::ambiguous");
    assert.equal(res.nodes.length, 1);
    assert.equal(res.nodes[0].type, "file");
    assert.equal(res.nodes[0].name, "ambiguous.py");
  });

  it("expands real backend class node ('repo::atlas_fixture::class::...') returning method children", async () => {
    const classId = "repo::atlas_fixture::class::ambiguous.AlphaWorker";
    const res = await mockFetchNodeChildren("repo::atlas_fixture", classId);
    assert.equal(res.parent_id, classId);
    assert.equal(res.nodes.length, 2);
    assert.ok(res.nodes.every((n) => n.type === "method"));
    assert.ok(res.nodes.some((n) => n.name === "__init__"));
    assert.ok(res.nodes.some((n) => n.name === "execute"));
  });

  it("returns empty children for leaf methods", async () => {
    const methodId = "repo::atlas_fixture::class::ambiguous.AlphaWorker::__init__";
    const res = await mockFetchNodeChildren("repo::atlas_fixture", methodId);
    assert.equal(res.nodes.length, 0);
    assert.equal(res.relationships.length, 0);
  });

  it("regression test: full 53-node realistic graph expansion increases BOTH nodes and edges state", async () => {
    // Mirror realistic repo::atlas_fixture nodes (53 total)
    const initial53Nodes: Node<EntityNodeData>[] = [
      {
        id: "repo::atlas_fixture",
        type: "entityNode",
        position: { x: 60, y: 60 },
        data: {
          id: "repo::atlas_fixture",
          label: "repository",
          name: "atlas_fixture",
          type: "repository",
          displayName: "atlas_fixture",
          properties: {},
        },
      },
      {
        id: "repo::atlas_fixture::file::ambiguous.py",
        type: "entityNode",
        position: { x: 420, y: 60 },
        data: {
          id: "repo::atlas_fixture::file::ambiguous.py",
          label: "file",
          name: "ambiguous.py",
          type: "file",
          displayName: "ambiguous.py",
          properties: {},
        },
      },
      {
        id: "repo::atlas_fixture::file::app.py",
        type: "entityNode",
        position: { x: 420, y: 145 },
        data: {
          id: "repo::atlas_fixture::file::app.py",
          label: "file",
          name: "app.py",
          type: "file",
          displayName: "app.py",
          properties: {},
        },
      },
    ];

    // Pad remaining 50 nodes to accurately simulate 53-node graph
    for (let i = 3; i < 53; i++) {
      const nid = `repo::atlas_fixture::dummy::node_${i}`;
      initial53Nodes.push({
        id: nid,
        type: "entityNode",
        position: { x: 780, y: 60 + (i - 3) * 85 },
        data: {
          id: nid,
          label: "class",
          name: `Dummy_${i}`,
          type: "class",
          displayName: `Dummy_${i}`,
          properties: {},
        },
      });
    }

    const initial58Edges: Edge[] = [];
    for (let i = 0; i < 58; i++) {
      initial58Edges.push({
        id: `rel:init_${i}`,
        source: initial53Nodes[0].id,
        target: initial53Nodes[(i % 52) + 1].id,
        label: "CONTAINS",
      });
    }

    assert.equal(initial53Nodes.length, 53);
    assert.equal(initial58Edges.length, 58);

    // State machine coordinator simulating React Flow state
    let currentNodes: Node<EntityNodeData>[] = [...initial53Nodes];
    let currentEdges: Edge[] = [...initial58Edges];
    const expandedIds = new Set<string>();
    const parentToChildren = new Map<string, Set<string>>();

    const expandNode = async (targetId: string) => {
      const parent = currentNodes.find((n) => n.id === targetId)!;
      const resp = await mockFetchNodeChildren("repo::atlas_fixture", targetId);
      expandedIds.add(targetId);

      const { mergedNodes, mergedEdges, addedNodeIds } = mergeGraphData(
        currentNodes,
        currentEdges,
        parent,
        resp.nodes,
        resp.relationships,
        { expandedNodeIds: expandedIds }
      );

      parentToChildren.set(targetId, new Set(addedNodeIds));
      currentNodes = mergedNodes;
      currentEdges = mergedEdges;
      return addedNodeIds;
    };

    const collapseNode = (targetId: string) => {
      const { updatedNodes, updatedEdges, removedNodeIds } = collapseNodeDescendants(
        targetId,
        parentToChildren,
        currentNodes,
        currentEdges
      );
      parentToChildren.delete(targetId);
      expandedIds.delete(targetId);
      for (const r of removedNodeIds) {
        expandedIds.delete(r);
        parentToChildren.delete(r);
      }
      currentNodes = updatedNodes;
      currentEdges = updatedEdges;
    };

    // 1. Expand first file: ambiguous.py
    const added1 = await expandNode("repo::atlas_fixture::file::ambiguous.py");
    assert.equal(added1.length, 3);
    assert.equal(currentNodes.length, 56, "Nodes MUST increase from 53 to 56 on first expand");
    assert.equal(currentEdges.length, 61, "Edges MUST increase from 58 to 61 on first expand");
    assert.equal(expandedIds.size, 1);

    // Verify all 3 child nodes are present in state with valid non-overlapping coordinates
    for (const childId of added1) {
      const found = currentNodes.find((n) => n.id === childId);
      assert.ok(found, `Node ${childId} must be present in nodes state`);
      assert.equal(found.position.x, 420 + 280); // Target column = 700
      assert.ok(found.position.y > 0);
    }

    // 2. Expand second file: app.py
    const added2 = await expandNode("repo::atlas_fixture::file::app.py");
    assert.equal(added2.length, 3);
    assert.equal(currentNodes.length, 59, "Nodes MUST increase from 56 to 59 on second expand");
    assert.equal(currentEdges.length, 64, "Edges MUST increase from 61 to 64 on second expand");
    assert.equal(expandedIds.size, 2);

    // 3. Collapse first file: ambiguous.py
    collapseNode("repo::atlas_fixture::file::ambiguous.py");
    assert.equal(currentNodes.length, 56, "Nodes MUST decrease from 59 to 56 after collapsing first file");
    assert.equal(currentEdges.length, 61, "Edges MUST decrease from 64 to 61 after collapsing first file");
    assert.equal(expandedIds.size, 1);

    // 4. Collapse second file: app.py
    collapseNode("repo::atlas_fixture::file::app.py");
    assert.equal(currentNodes.length, 53, "Nodes MUST return to 53 after collapsing all");
    assert.equal(currentEdges.length, 58, "Edges MUST return to 58 after collapsing all");
    assert.equal(expandedIds.size, 0);
  });
});

