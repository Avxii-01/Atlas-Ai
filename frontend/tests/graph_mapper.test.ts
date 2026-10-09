import test, { describe, it } from "node:test";
import assert from "node:assert/strict";

import {
  mapGraphResponseToReactFlow,
  getNodeDisplayLabel,
  computeNodePositions,
} from "../lib/graphMapper.ts";
import type {
  RepositoryGraphResponse,
  GraphNodeModel,
  GraphRelationshipModel,
} from "../lib/types.ts";

describe("Graph Mapper - getNodeDisplayLabel (P0-22)", () => {
  it("prefers display_name when available", () => {
    const node: GraphNodeModel = {
      id: "fn:order_process",
      label: "Function",
      name: "process",
      type: "Function",
      display_name: "order.process",
    };
    assert.equal(getNodeDisplayLabel(node), "order.process");
  });

  it("falls back to name when display_name is null or empty", () => {
    const node: GraphNodeModel = {
      id: "file:main.py",
      label: "File",
      name: "main.py",
      type: "File",
      display_name: null,
    };
    assert.equal(getNodeDisplayLabel(node), "main.py");
  });

  it("falls back to id when name is absent", () => {
    const node: GraphNodeModel = {
      id: "anon:node_123",
      label: "Import",
      name: "",
      type: "Import",
    };
    assert.equal(getNodeDisplayLabel(node), "anon:node_123");
  });
});

describe("Graph Mapper - computeNodePositions", () => {
  it("generates deterministic non-overlapping coordinates for nodes", () => {
    const nodes: GraphNodeModel[] = [
      { id: "repo:1", label: "Repository", name: "repo", type: "Repository" },
      { id: "file:1", label: "File", name: "a.py", type: "File" },
      { id: "file:2", label: "File", name: "b.py", type: "File" },
      { id: "cls:1", label: "Class", name: "User", type: "Class" },
      { id: "fn:1", label: "Function", name: "run", type: "Function" },
    ];

    const positions = computeNodePositions(nodes);
    assert.equal(positions.size, 5);

    const coordSet = new Set<string>();
    for (const [id, pos] of positions.entries()) {
      const coordKey = `${pos.x},${pos.y}`;
      assert.ok(!coordSet.has(coordKey), `Node '${id}' has overlapping coordinate ${coordKey}`);
      coordSet.add(coordKey);
    }
  });
});

describe("Graph Mapper - mapGraphResponseToReactFlow", () => {
  it("maps nodes preserving stable IDs, types, and labels", () => {
    const response: RepositoryGraphResponse = {
      repository_id: "demo",
      nodes: [
        {
          id: "repo:demo",
          label: "Repository",
          name: "demo",
          type: "Repository",
          display_name: "Demo Repository",
        },
        {
          id: "file:app.py",
          label: "File",
          name: "app.py",
          type: "File",
          properties: { size: 1024 },
        },
      ],
      relationships: [
        {
          id: "rel:1",
          source: "repo:demo",
          target: "file:app.py",
          type: "CONTAINS",
        },
      ],
    };

    const { nodes, edges } = mapGraphResponseToReactFlow(response);

    assert.equal(nodes.length, 2);
    assert.equal(nodes[0].id, "repo:demo");
    assert.equal(nodes[0].type, "entityNode");
    assert.equal(nodes[0].data.displayName, "Demo Repository");
    assert.equal(nodes[0].data.label, "Repository");

    assert.equal(nodes[1].id, "file:app.py");
    assert.equal(nodes[1].data.displayName, "app.py");
    assert.equal(nodes[1].data.properties.size, 1024);

    assert.equal(edges.length, 1);
    assert.equal(edges[0].id, "rel:1");
    assert.equal(edges[0].source, "repo:demo");
    assert.equal(edges[0].target, "file:app.py");
    assert.equal(edges[0].label, "CONTAINS");
  });

  it("skips dangling edges whose source or target node is missing", () => {
    const response: RepositoryGraphResponse = {
      repository_id: "demo",
      nodes: [
        { id: "node:1", label: "File", name: "1", type: "File" },
        { id: "node:2", label: "File", name: "2", type: "File" },
      ],
      relationships: [
        { id: "valid_rel", source: "node:1", target: "node:2", type: "CALLS" },
        { id: "dangling_source", source: "missing_source", target: "node:2", type: "CALLS" },
        { id: "dangling_target", source: "node:1", target: "missing_target", type: "CALLS" },
      ],
    };

    const { edges } = mapGraphResponseToReactFlow(response);

    assert.equal(edges.length, 1);
    assert.equal(edges[0].id, "valid_rel");
  });

  it("preserves distinct edges connecting the same source and target nodes", () => {
    const response: RepositoryGraphResponse = {
      repository_id: "demo",
      nodes: [
        { id: "node:A", label: "Class", name: "A", type: "Class" },
        { id: "node:B", label: "Class", name: "B", type: "Class" },
      ],
      relationships: [
        { id: "edge:1", source: "node:A", target: "node:B", type: "CALLS" },
        { id: "edge:2", source: "node:A", target: "node:B", type: "INHERITS" },
      ],
    };

    const { edges } = mapGraphResponseToReactFlow(response);

    assert.equal(edges.length, 2);
    assert.equal(edges[0].id, "edge:1");
    assert.equal(edges[0].label, "CALLS");
    assert.equal(edges[1].id, "edge:2");
    assert.equal(edges[1].label, "INHERITS");
  });
});

describe("Graph Mapper - Controlled atlas_fixture Graph Invariants", () => {
  // Construct mock fixture matching tests/fixtures/atlas_fixture ground truth:
  // 53 nodes: 1 Repo, 7 Files, 7 Modules, 7 Classes, 11 Functions, 12 Methods, 8 Imports
  // 58 relationships: 37 CONTAINS, 5 IMPORTS, 15 CALLS, 1 INHERITS
  function createControlledAtlasFixtureGraph(): RepositoryGraphResponse {
    const nodes: GraphNodeModel[] = [];
    const relationships: GraphRelationshipModel[] = [];

    // 1 Repository node
    nodes.push({
      id: "repo:atlas_fixture",
      label: "Repository",
      name: "atlas_fixture",
      type: "Repository",
      display_name: "Atlas Fixture",
    });

    // 7 Files & 7 Modules
    for (let i = 1; i <= 7; i++) {
      const fileId = `file:module_${i}.py`;
      const modId = `mod:module_${i}`;
      nodes.push({ id: fileId, label: "File", name: `module_${i}.py`, type: "File" });
      nodes.push({ id: modId, label: "Module", name: `module_${i}`, type: "Module" });

      relationships.push({
        id: `rel:contains:repo:file:${i}`,
        source: "repo:atlas_fixture",
        target: fileId,
        type: "CONTAINS",
      });
      relationships.push({
        id: `rel:contains:file:mod:${i}`,
        source: fileId,
        target: modId,
        type: "CONTAINS",
      });
    }

    // 7 Classes
    for (let i = 1; i <= 7; i++) {
      const clsId = `cls:Class_${i}`;
      nodes.push({ id: clsId, label: "Class", name: `Class_${i}`, type: "Class" });
      relationships.push({
        id: `rel:contains:mod:cls:${i}`,
        source: `mod:module_${i}`,
        target: clsId,
        type: "CONTAINS",
      });
    }

    // 11 Functions
    for (let i = 1; i <= 11; i++) {
      const fnId = `fn:function_${i}`;
      nodes.push({ id: fnId, label: "Function", name: `function_${i}`, type: "Function" });
    }
    // 4 CONTAINS from module to functions (making total CONTAINS exactly 37)
    for (let i = 1; i <= 4; i++) {
      relationships.push({
        id: `rel:contains:mod:fn:${i}`,
        source: `mod:module_${i}`,
        target: `fn:function_${i}`,
        type: "CONTAINS",
      });
    }

    // 12 Methods
    for (let i = 1; i <= 12; i++) {
      const methId = `meth:method_${i}`;
      nodes.push({ id: methId, label: "Method", name: `method_${i}`, type: "Method" });
      relationships.push({
        id: `rel:contains:cls:meth:${i}`,
        source: `cls:Class_${((i - 1) % 7) + 1}`,
        target: methId,
        type: "CONTAINS",
      });
    }


    // 8 Imports
    for (let i = 1; i <= 8; i++) {
      const impId = `imp:import_${i}`;
      nodes.push({ id: impId, label: "Import", name: `import_${i}`, type: "Import" });
    }

    // 5 IMPORTS relationships
    for (let i = 1; i <= 5; i++) {
      relationships.push({
        id: `rel:imports:${i}`,
        source: `mod:module_${i}`,
        target: `imp:import_${i}`,
        type: "IMPORTS",
      });
    }

    // 15 CALLS relationships
    for (let i = 1; i <= 15; i++) {
      const srcFn = `fn:function_${((i - 1) % 11) + 1}`;
      const tgtFn = `fn:function_${(i % 11) + 1}`;
      relationships.push({
        id: `rel:calls:${i}`,
        source: srcFn,
        target: tgtFn,
        type: "CALLS",
      });
    }

    // 1 INHERITS relationship
    relationships.push({
      id: "rel:inherits:1",
      source: "cls:Class_2",
      target: "cls:Class_1",
      type: "INHERITS",
    });

    return {
      repository_id: "atlas_fixture",
      nodes,
      relationships,
    };
  }

  it("correctly maps full 53-node and 58-relationship fixture graph", () => {
    const fixtureGraph = createControlledAtlasFixtureGraph();

    assert.equal(fixtureGraph.nodes.length, 53, "Ground truth: 53 nodes");
    assert.equal(fixtureGraph.relationships.length, 58, "Ground truth: 58 relationships");

    const { nodes: rfNodes, edges: rfEdges } = mapGraphResponseToReactFlow(fixtureGraph);

    assert.equal(rfNodes.length, 53, "React Flow must receive all 53 nodes");
    assert.equal(rfEdges.length, 58, "React Flow must receive all 58 edges");

    // Verify all entity types are represented
    const nodeTypes = new Set(rfNodes.map((n) => n.data.label));
    assert.ok(nodeTypes.has("Repository"));
    assert.ok(nodeTypes.has("File"));
    assert.ok(nodeTypes.has("Module"));
    assert.ok(nodeTypes.has("Class"));
    assert.ok(nodeTypes.has("Function"));
    assert.ok(nodeTypes.has("Method"));
    assert.ok(nodeTypes.has("Import"));

    // Verify all relationship types are represented
    const edgeTypes = new Set(rfEdges.map((e) => e.label));
    assert.ok(edgeTypes.has("CONTAINS"));
    assert.ok(edgeTypes.has("IMPORTS"));
    assert.ok(edgeTypes.has("CALLS"));
    assert.ok(edgeTypes.has("INHERITS"));

    // Verify all edge endpoints exist in the node set
    const rfNodeIds = new Set(rfNodes.map((n) => n.id));
    for (const edge of rfEdges) {
      assert.ok(rfNodeIds.has(edge.source), `Edge source '${edge.source}' must exist in nodes`);
      assert.ok(rfNodeIds.has(edge.target), `Edge target '${edge.target}' must exist in nodes`);
    }
  });
});
