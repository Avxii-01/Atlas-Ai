import test, { describe, it } from "node:test";
import assert from "node:assert/strict";

import {
  computeIncrementalLayoutPrototype,
  resolveNodeDimensions,
  checkBoundingBoxCollision,
  type PositionedNodeInput,
  type DiscoveredNodeInput,
  type BoundingBox,
} from "../lib/incrementalLayoutPrototype.ts";

import { computeNodePositions } from "../lib/graphMapper.ts";
import { computeIncrementalChildPositions } from "../lib/progressiveExploration.ts";
import type { GraphNodeModel } from "../lib/types.ts";
import type { Node } from "@xyflow/react";
import type { EntityNodeData } from "../lib/graphMapper.ts";

describe("Isolated Incremental Layout Prototype (Checkpoint 5)", () => {
  const baseExistingNodes: PositionedNodeInput[] = [
    {
      id: "repo::root",
      position: { x: 60, y: 60 },
      width: 200,
      height: 60,
    },
    {
      id: "file::alpha.py",
      position: { x: 340, y: 60 },
      width: 220,
      height: 70,
    },
    {
      id: "file::beta.py",
      position: { x: 340, y: 160 },
      measured: { width: 240, height: 80 },
    },
    {
      id: "class::Worker",
      position: { x: 620, y: 60 },
      width: 200,
      height: 65,
    },
    {
      id: "class::Handler",
      position: { x: 620, y: 155 },
      measured: { width: 250, height: 90 },
    },
  ];

  it("1. existing coordinates remain exactly unchanged", () => {
    // Deep clone existing nodes to ensure no mutation
    const existingSnapshot = JSON.parse(JSON.stringify(baseExistingNodes));
    const parentId = "file::alpha.py";
    const newNodes: DiscoveredNodeInput[] = [
      { id: "child::1", width: 210, height: 60 },
      { id: "child::2", width: 230, height: 75 },
    ];

    const result = computeIncrementalLayoutPrototype(baseExistingNodes, newNodes, parentId);

    assert.equal(result.summary.placedCount, 2);
    assert.equal(result.summary.unplacedCount, 0);

    // Verify existing coordinates are strictly identical to the snapshot
    for (let i = 0; i < baseExistingNodes.length; i++) {
      assert.deepEqual(baseExistingNodes[i].position, existingSnapshot[i].position);
      assert.equal(baseExistingNodes[i].id, existingSnapshot[i].id);
    }
  });

  it("2. identical inputs produce identical output (determinism)", () => {
    const parentId = "file::alpha.py";
    const newNodes: DiscoveredNodeInput[] = [
      { id: "child::a", width: 220, height: 70 },
      { id: "child::b", width: 260, height: 85 },
      { id: "child::c", width: 190, height: 55 },
    ];

    const run1 = computeIncrementalLayoutPrototype(baseExistingNodes, newNodes, parentId);
    const run2 = computeIncrementalLayoutPrototype(baseExistingNodes, newNodes, parentId);

    assert.equal(run1.placedNodes.size, run2.placedNodes.size);
    assert.deepEqual(Array.from(run1.placedNodes.entries()), Array.from(run2.placedNodes.entries()));
    assert.deepEqual(run1.summary, run2.summary);
  });

  it("3. new node bounding boxes do not overlap existing nodes (varied node sizes)", () => {
    const parentId = "file::alpha.py"; // at (340, 60), target col starts at 340 + 280 = 620
    // Notice existing nodes already occupy (620, 60..125) and (620, 155..245)
    const newNodes: DiscoveredNodeInput[] = [
      { id: "new::large", width: 280, height: 110 },
      { id: "new::small", width: 160, height: 50 },
      { id: "new::tall", width: 200, height: 130 },
    ];

    const result = computeIncrementalLayoutPrototype(baseExistingNodes, newNodes, parentId, {
      horizontalGap: 30,
      verticalGap: 20,
    });

    assert.equal(result.summary.placedCount, 3);

    // Check every placed node against every existing node
    for (const [newId, placed] of result.placedNodes) {
      const placedBox: BoundingBox = {
        id: newId,
        left: placed.position.x,
        top: placed.position.y,
        right: placed.position.x + placed.dimensions.width,
        bottom: placed.position.y + placed.dimensions.height,
        width: placed.dimensions.width,
        height: placed.dimensions.height,
      };

      for (const exist of baseExistingNodes) {
        const existDim = resolveNodeDimensions(exist.id, exist);
        const existBox: BoundingBox = {
          id: exist.id,
          left: exist.position.x,
          top: exist.position.y,
          right: exist.position.x + existDim.width,
          bottom: exist.position.y + existDim.height,
          width: existDim.width,
          height: existDim.height,
        };

        const collides = checkBoundingBoxCollision(placedBox, existBox, 30, 20);
        assert.equal(
          collides,
          false,
          `Placed node '${newId}' collides with existing node '${exist.id}'`
        );
      }
    }
  });

  it("4. newly placed nodes do not overlap one another", () => {
    const parentId = "file::alpha.py";
    const newNodes: DiscoveredNodeInput[] = [
      { id: "sib::1", width: 210, height: 65 },
      { id: "sib::2", width: 250, height: 80 },
      { id: "sib::3", width: 195, height: 55 },
      { id: "sib::4", width: 270, height: 95 },
      { id: "sib::5", width: 230, height: 70 },
    ];

    const result = computeIncrementalLayoutPrototype(baseExistingNodes, newNodes, parentId, {
      horizontalGap: 30,
      verticalGap: 20,
    });

    assert.equal(result.summary.placedCount, 5);

    const placedList = Array.from(result.placedNodes.values());
    for (let i = 0; i < placedList.length; i++) {
      for (let j = i + 1; j < placedList.length; j++) {
        const a = placedList[i];
        const b = placedList[j];

        const boxA: BoundingBox = {
          id: a.id,
          left: a.position.x,
          top: a.position.y,
          right: a.position.x + a.dimensions.width,
          bottom: a.position.y + a.dimensions.height,
          width: a.dimensions.width,
          height: a.dimensions.height,
        };

        const boxB: BoundingBox = {
          id: b.id,
          left: b.position.x,
          top: b.position.y,
          right: b.position.x + b.dimensions.width,
          bottom: b.position.y + b.dimensions.height,
          width: b.dimensions.width,
          height: b.dimensions.height,
        };

        const collides = checkBoundingBoxCollision(boxA, boxB, 30, 20);
        assert.equal(
          collides,
          false,
          `Sibling '${a.id}' collides with sibling '${b.id}'`
        );
      }
    }
  });

  it("5. a parent with at least 20 children is handled without hanging (< 50ms)", () => {
    const parentId = "file::alpha.py";
    const children25: DiscoveredNodeInput[] = [];

    for (let i = 0; i < 25; i++) {
      children25.push({
        id: `bulk::child_${i}`,
        // Varied non-uniform dimensions
        width: 180 + (i % 5) * 20, // 180, 200, 220, 240, 260
        height: 55 + (i % 4) * 15, // 55, 70, 85, 100
      });
    }

    const startTime = Date.now();
    const result = computeIncrementalLayoutPrototype(baseExistingNodes, children25, parentId, {
      maxSubColumns: 3,
      maxRowsPerColumn: 10,
    });
    const duration = Date.now() - startTime;

    assert.ok(duration < 50, `Execution for 25 children took ${duration}ms (must be < 50ms)`);
    assert.equal(result.summary.placedCount, 25);
    assert.equal(result.summary.unplacedCount, 0);

    // Verify sub-column distribution (nodes are distributed across sub-columns)
    const subColCounts = new Map<number, number>();
    for (const [, placed] of result.placedNodes) {
      const col = placed.subColumnIndex;
      subColCounts.set(col, (subColCounts.get(col) || 0) + 1);
    }

    assert.ok(subColCounts.size > 1, "25 children should be distributed across multiple sub-columns");
  });

  it("6. multiple expansions behave predictably", () => {
    // 1st expansion: Parent 1 (file::alpha.py at 340, 60)
    const newChildren1: DiscoveredNodeInput[] = [
      { id: "p1_c1", width: 220, height: 60 },
      { id: "p1_c2", width: 220, height: 60 },
    ];

    const exp1 = computeIncrementalLayoutPrototype(baseExistingNodes, newChildren1, "file::alpha.py");
    assert.equal(exp1.summary.placedCount, 2);

    // Form updated graph including expansion 1 nodes
    const graphAfterExp1: PositionedNodeInput[] = [...baseExistingNodes];
    for (const [cId, p] of exp1.placedNodes) {
      graphAfterExp1.push({
        id: cId,
        position: p.position,
        width: p.dimensions.width,
        height: p.dimensions.height,
      });
    }

    // 2nd expansion: Parent 2 (file::beta.py at 340, 160)
    const newChildren2: DiscoveredNodeInput[] = [
      { id: "p2_c1", width: 220, height: 60 },
      { id: "p2_c2", width: 220, height: 60 },
    ];

    const exp2 = computeIncrementalLayoutPrototype(graphAfterExp1, newChildren2, "file::beta.py");
    assert.equal(exp2.summary.placedCount, 2);

    // Verify none of exp2's children collide with exp1's children or base nodes
    for (const [id2, p2] of exp2.placedNodes) {
      const box2: BoundingBox = {
        id: id2,
        left: p2.position.x,
        top: p2.position.y,
        right: p2.position.x + p2.dimensions.width,
        bottom: p2.position.y + p2.dimensions.height,
        width: p2.dimensions.width,
        height: p2.dimensions.height,
      };

      for (const node of graphAfterExp1) {
        const dim = resolveNodeDimensions(node.id, node);
        const boxOld: BoundingBox = {
          id: node.id,
          left: node.position.x,
          top: node.position.y,
          right: node.position.x + dim.width,
          bottom: node.position.y + dim.height,
          width: dim.width,
          height: dim.height,
        };

        const collides = checkBoundingBoxCollision(box2, boxOld, 40, 20);
        assert.equal(collides, false, `Child '${id2}' collides with previously existing/placed node '${node.id}'`);
      }
    }
  });

  it("7. duplicate node IDs and duplicate inputs are handled safely", () => {
    const parentId = "file::alpha.py";
    const duplicateInputs: DiscoveredNodeInput[] = [
      { id: "class::Worker" }, // Already exists in baseExistingNodes!
      { id: "unique::node1", width: 200, height: 60 },
      { id: "unique::node1", width: 200, height: 60 }, // Duplicated in incoming batch!
      { id: "" }, // Empty node ID
      { id: "   " }, // Whitespace node ID
    ];

    const result = computeIncrementalLayoutPrototype(baseExistingNodes, duplicateInputs, parentId);

    assert.equal(result.summary.placedCount, 1);
    assert.ok(result.placedNodes.has("unique::node1"));

    // Check unplaced error reasons
    const unplacedReasons = new Map(result.unplacedNodes.map((u) => [u.id, u.reason]));
    assert.equal(unplacedReasons.get("class::Worker"), "duplicate_with_existing_node");
    assert.equal(unplacedReasons.get("unique::node1"), "duplicate_in_input");
    assert.ok(result.unplacedNodes.some((u) => u.reason === "invalid_node_id"));
  });

  it("8. invalid dimensions and missing parents are handled safely", () => {
    // A) Missing parent
    const resultMissingParent = computeIncrementalLayoutPrototype(
      baseExistingNodes,
      [{ id: "lost::child" }],
      "nonexistent::parent"
    );
    assert.equal(resultMissingParent.summary.placedCount, 0);
    assert.equal(resultMissingParent.summary.unplacedCount, 1);
    assert.equal(resultMissingParent.unplacedNodes[0].reason, "parent_not_found");

    // B) Invalid dimensions (negative, zero, NaN, strings)
    const resultInvalidDims = computeIncrementalLayoutPrototype(
      baseExistingNodes,
      [
        { id: "node::negative_dim", width: -100, height: 0 },
        { id: "node::nan_dim", width: NaN, height: Infinity },
        { id: "node::undefined_dim" },
      ],
      "file::alpha.py"
    );

    // All should be placed using safe default dimensions (220 x 68)
    assert.equal(resultInvalidDims.summary.placedCount, 3);
    for (const [, placed] of resultInvalidDims.placedNodes) {
      assert.equal(placed.dimensions.width, 220);
      assert.equal(placed.dimensions.height, 68);
    }
  });

  it("9. bounded placement failure is reported explicitly", () => {
    // Construct a tight trap where search is artificially restricted
    const parent = { id: "p", position: { x: 100, y: 100 } };
    // Create an obstacle that completely blocks the only available sub-column
    const blockingObstacle = {
      id: "wall",
      position: { x: 100 + 280, y: 100 },
      width: 500,
      height: 500,
    };

    const result = computeIncrementalLayoutPrototype(
      [parent, blockingObstacle],
      [{ id: "trapped_node", width: 200, height: 100 }],
      "p",
      {
        maxSubColumns: 1, // Only 1 column allowed
        maxVerticalDistance: 200, // Very small search window
        maxCandidatesPerNode: 5, // Strict bounded iteration cap
      }
    );

    assert.equal(result.summary.placedCount, 0);
    assert.equal(result.summary.unplacedCount, 1);
    assert.equal(result.unplacedNodes[0].id, "trapped_node");
    assert.equal(result.unplacedNodes[0].reason, "no_collision_free_position_within_bounds");
  });

  it("10. production layout behavior remains unchanged", () => {
    // Verify production computeNodePositions continues to work as expected
    const sampleModels: GraphNodeModel[] = [
      { id: "r1", label: "repository", type: "repository", name: "r1" },
      { id: "f1", label: "file", type: "file", name: "f1" },
      { id: "c1", label: "class", type: "class", name: "c1" },
    ];
    const prodPositions = computeNodePositions(sampleModels);
    assert.equal(prodPositions.size, 3);
    assert.equal(prodPositions.get("r1")!.x, 60);
    assert.equal(prodPositions.get("f1")!.x, 60 + 280 + 80);

    // Verify production computeIncrementalChildPositions continues to work as expected
    const fakeParent: Node<EntityNodeData> = {
      id: "f1",
      position: { x: 420, y: 60 },
      data: {
        id: "f1",
        label: "file",
        name: "f1",
        type: "file",
        displayName: "f1",
        properties: {},
      },
    };
    const prodChildPositions = computeIncrementalChildPositions(fakeParent, sampleModels.slice(2), [fakeParent]);
    assert.equal(prodChildPositions.size, 1);
    assert.equal(prodChildPositions.get("c1")!.x, 420 + 280);
  });
});

