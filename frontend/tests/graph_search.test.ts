import test, { describe, it } from "node:test";
import assert from "node:assert/strict";

import {
  searchGraphNodes,
  extractNodeSearchFields,
  calculateMatchScore,
  type SearchableEntityNode,
  type GraphSearchResult,
} from "../lib/graphSearch.ts";
import type { Node } from "@xyflow/react";
import type { EntityNodeData } from "../lib/graphMapper.ts";

// Sample fixture nodes simulating a loaded repository graph
const mockLoadedNodes: Node<EntityNodeData>[] = [
  {
    id: "atlas_fixture/app.py",
    type: "entityNode",
    position: { x: 340, y: 60 },
    data: {
      id: "atlas_fixture/app.py",
      label: "file",
      name: "app.py",
      type: "file",
      displayName: "app.py",
      properties: {
        file_path: "atlas_fixture/app.py",
        path: "atlas_fixture/app.py",
      },
    },
  },
  {
    id: "atlas_fixture/app.py:RepositoryAnalyzer",
    type: "entityNode",
    position: { x: 620, y: 60 },
    data: {
      id: "atlas_fixture/app.py:RepositoryAnalyzer",
      label: "class",
      name: "RepositoryAnalyzer",
      type: "class",
      displayName: "RepositoryAnalyzer",
      properties: {
        file_path: "atlas_fixture/app.py",
      },
    },
  },
  {
    id: "atlas_fixture/app.py:analyze_code",
    type: "entityNode",
    position: { x: 900, y: 60 },
    data: {
      id: "atlas_fixture/app.py:analyze_code",
      label: "function",
      name: "analyze_code",
      type: "function",
      displayName: "analyze_code",
      properties: {
        file_path: "atlas_fixture/app.py",
      },
    },
  },
  {
    id: "atlas_fixture/utils/parser.py:parse_ast",
    type: "entityNode",
    position: { x: 900, y: 145 },
    data: {
      id: "atlas_fixture/utils/parser.py:parse_ast",
      label: "function",
      name: "parse_ast",
      type: "function",
      displayName: "parse_ast (AST Parser)",
      properties: {
        file_path: "atlas_fixture/utils/parser.py",
      },
    },
  },
  {
    id: "atlas_fixture/models/node.py:GraphNode",
    type: "entityNode",
    position: { x: 620, y: 145 },
    data: {
      id: "atlas_fixture/models/node.py:GraphNode",
      label: "class",
      name: "GraphNode",
      type: "class",
      displayName: "GraphNode Data Model",
      properties: {
        file_path: "atlas_fixture/models/node.py",
      },
    },
  },
];

describe("Local In-Memory Graph Search (Checkpoint 3)", () => {
  it("extracts search fields correctly from React Flow nodes and raw objects", () => {
    const fields = extractNodeSearchFields(mockLoadedNodes[1]);
    assert.equal(fields.id, "atlas_fixture/app.py:RepositoryAnalyzer");
    assert.equal(fields.name, "RepositoryAnalyzer");
    assert.equal(fields.displayName, "RepositoryAnalyzer");
    assert.equal(fields.type, "class");
    assert.equal(fields.filePath, "atlas_fixture/app.py");

    // Raw object with display_name
    const rawFields = extractNodeSearchFields({
      id: "raw:123",
      name: "raw_func",
      display_name: "Special Func",
      type: "function",
      properties: { path: "src/raw.ts" },
    });
    assert.equal(rawFields.id, "raw:123");
    assert.equal(rawFields.name, "raw_func");
    assert.equal(rawFields.displayName, "Special Func");
    assert.equal(rawFields.filePath, "src/raw.ts");
  });

  it("returns empty array for empty or whitespace-only queries", () => {
    assert.deepEqual(searchGraphNodes(mockLoadedNodes, ""), []);
    assert.deepEqual(searchGraphNodes(mockLoadedNodes, "   "), []);
    assert.deepEqual(searchGraphNodes(mockLoadedNodes, "\t\n  "), []);
    assert.deepEqual(searchGraphNodes([], "app"), []);
  });

  it("matches case-insensitively across lowercase, uppercase, and mixed-case queries", () => {
    const lowerResults = searchGraphNodes(mockLoadedNodes, "analyzer");
    const upperResults = searchGraphNodes(mockLoadedNodes, "ANALYZER");
    const mixedResults = searchGraphNodes(mockLoadedNodes, "AnAlYzEr");

    assert.ok(lowerResults.length > 0, "Lower query should find matches");
    assert.equal(lowerResults.length, upperResults.length);
    assert.equal(lowerResults.length, mixedResults.length);
    assert.equal(lowerResults[0].id, "atlas_fixture/app.py:RepositoryAnalyzer");
  });

  it("matches nodes by display name or name", () => {
    const results = searchGraphNodes(mockLoadedNodes, "AST Parser");
    assert.ok(results.length > 0);
    assert.equal(results[0].id, "atlas_fixture/utils/parser.py:parse_ast");
    assert.equal(results[0].matchField, "displayName");

    const funcResults = searchGraphNodes(mockLoadedNodes, "analyze_code");
    assert.ok(funcResults.length > 0);
    assert.equal(funcResults[0].id, "atlas_fixture/app.py:analyze_code");
  });

  it("matches nodes by ID when ID contains the query", () => {
    const idResults = searchGraphNodes(mockLoadedNodes, "models/node.py");
    assert.ok(idResults.length > 0);
    assert.equal(idResults[0].id, "atlas_fixture/models/node.py:GraphNode");
  });

  it("matches nodes by file_path or path property", () => {
    const pathResults = searchGraphNodes(mockLoadedNodes, "utils/parser");
    assert.ok(pathResults.length > 0);
    assert.equal(pathResults[0].id, "atlas_fixture/utils/parser.py:parse_ast");
  });

  it("returns empty results array when no loaded nodes match the query (no-results state)", () => {
    const results = searchGraphNodes(mockLoadedNodes, "non_existent_symbol_xyz");
    assert.equal(results.length, 0);
  });

  it("ranks exact matches and prefix matches higher than loose substring matches", () => {
    const results = searchGraphNodes(mockLoadedNodes, "app.py");
    // "app.py" file node is exact match for displayName and name
    assert.ok(results.length >= 2);
    assert.equal(results[0].id, "atlas_fixture/app.py");
    assert.equal(results[0].score > results[1].score, true);
  });

  it("respects the limit option", () => {
    // "a" matches all 5 fixture nodes
    const limited = searchGraphNodes(mockLoadedNodes, "a", { limit: 2 });
    assert.equal(limited.length, 2);

    const full = searchGraphNodes(mockLoadedNodes, "a", { limit: 10 });
    assert.ok(full.length > 2);
  });
});

describe("Graph Search Selection and Viewport Focus State Machine (Checkpoint 3)", () => {
  /**
   * Simulates the exact state behavior of RepositoryGraphView when selecting an entity via search.
   */
  class MockGraphSelectionCoordinator {
    nodes: Node<EntityNodeData>[];
    selectedEntity: EntityNodeData | null = null;
    centerCalls: Array<{ x: number; y: number; options: { duration: number; zoom: number } }> = [];
    zoomLevel: number = 1.0;

    constructor(initialNodes: Node<EntityNodeData>[]) {
      this.nodes = initialNodes.map((n) => ({ ...n, selected: false }));
    }

    getSelectedEntity(): EntityNodeData | null {
      return this.selectedEntity;
    }

    // Mirror of handleSelectEntityById in RepositoryGraphView.tsx
    selectEntityById(entityId: string) {
      const targetNode = this.nodes.find((n) => n.id === entityId);
      if (targetNode) {
        this.selectedEntity = targetNode.data;
        this.nodes = this.nodes.map((n) => ({
          ...n,
          selected: n.id === entityId,
        }));
        this.mockSetCenter(
          targetNode.position.x + 100,
          targetNode.position.y + 40,
          { duration: 400, zoom: Math.max(this.zoomLevel, 0.8) }
        );
      }
    }

    mockSetCenter(x: number, y: number, options: { duration: number; zoom: number }) {
      this.centerCalls.push({ x, y, options });
    }
  }

  it("selecting a search result updates node selection, sets active entity, and focuses viewport", () => {
    const coordinator = new MockGraphSelectionCoordinator(mockLoadedNodes);

    assert.equal(coordinator.selectedEntity, null);
    assert.equal(coordinator.nodes.every((n) => !n.selected), true);
    assert.equal(coordinator.centerCalls.length, 0);

    // Search and select
    const results = searchGraphNodes(coordinator.nodes, "RepositoryAnalyzer");
    assert.ok(results.length > 0);
    const chosenResult = results[0];

    coordinator.selectEntityById(chosenResult.id);

    // 1. Target node is selected
    const selectedNodes = coordinator.nodes.filter((n) => n.selected);
    assert.equal(selectedNodes.length, 1);
    assert.equal(selectedNodes[0].id, chosenResult.id);

    // 2. Active entity data is set
    const selected = coordinator.getSelectedEntity();
    assert.ok(selected !== null);
    assert.equal(selected.name, "RepositoryAnalyzer");
    assert.equal(selected.type, "class");

    // 3. Viewport center was called with node position + offset
    assert.equal(coordinator.centerCalls.length, 1);
    const call = coordinator.centerCalls[0];
    const target = mockLoadedNodes.find((n) => n.id === chosenResult.id)!;
    assert.equal(call.x, target.position.x + 100);
    assert.equal(call.y, target.position.y + 40);
    assert.equal(call.options.duration, 400);
    assert.ok(call.options.zoom >= 0.8);
  });

  it("selecting another search result switches the active selection cleanly", () => {
    const coordinator = new MockGraphSelectionCoordinator(mockLoadedNodes);

    // Select first node
    coordinator.selectEntityById("atlas_fixture/app.py");
    assert.equal(coordinator.getSelectedEntity()?.id, "atlas_fixture/app.py");

    // Select second node
    coordinator.selectEntityById("atlas_fixture/utils/parser.py:parse_ast");
    assert.equal(coordinator.getSelectedEntity()?.id, "atlas_fixture/utils/parser.py:parse_ast");

    // Only second node is marked selected
    const selectedNodes = coordinator.nodes.filter((n) => n.selected);
    assert.equal(selectedNodes.length, 1);
    assert.equal(selectedNodes[0].id, "atlas_fixture/utils/parser.py:parse_ast");
    assert.equal(coordinator.centerCalls.length, 2);
  });
});

describe("GraphSearch Keyboard Navigation and Accessible State Model (Checkpoint 3)", () => {
  class SearchInputModel {
    query: string = "";
    isOpen: boolean = false;
    highlightedIndex: number = -1;
    nodes: Node<EntityNodeData>[];

    constructor(nodes: Node<EntityNodeData>[]) {
      this.nodes = nodes;
    }

    get results(): GraphSearchResult[] {
      if (!this.query.trim()) return [];
      return searchGraphNodes(this.nodes, this.query.trim());
    }

    setQuery(newQuery: string) {
      this.query = newQuery;
      this.isOpen = newQuery.trim().length > 0;
      this.highlightedIndex = this.results.length > 0 ? 0 : -1;
    }

    onArrowDown() {
      if (!this.isOpen && this.query.trim()) {
        this.isOpen = true;
        return;
      }
      if (this.results.length > 0) {
        this.highlightedIndex = (this.highlightedIndex + 1) % this.results.length;
      }
    }

    onArrowUp() {
      if (!this.isOpen && this.query.trim()) {
        this.isOpen = true;
        return;
      }
      if (this.results.length > 0) {
        this.highlightedIndex =
          (this.highlightedIndex - 1 + this.results.length) % this.results.length;
      }
    }

    onEscape() {
      if (this.isOpen) {
        this.isOpen = false;
      } else {
        this.query = "";
      }
    }

    clear() {
      this.query = "";
      this.isOpen = false;
      this.highlightedIndex = -1;
    }

    getAriaExpanded(): boolean {
      return this.isOpen && this.query.trim().length > 0;
    }

    getActiveDescendantId(): string | undefined {
      if (this.isOpen && this.highlightedIndex >= 0) {
        return `graph-search-item-${this.highlightedIndex}`;
      }
      return undefined;
    }
  }

  it("maintains correct initial collapsed state", () => {
    const model = new SearchInputModel(mockLoadedNodes);
    assert.equal(model.query, "");
    assert.equal(model.isOpen, false);
    assert.equal(model.highlightedIndex, -1);
    assert.equal(model.getAriaExpanded(), false);
    assert.equal(model.getActiveDescendantId(), undefined);
  });

  it("opens dropdown and highlights first match when typing a matching query", () => {
    const model = new SearchInputModel(mockLoadedNodes);
    model.setQuery("app");

    assert.equal(model.isOpen, true);
    assert.equal(model.getAriaExpanded(), true);
    assert.equal(model.highlightedIndex, 0);
    assert.equal(model.getActiveDescendantId(), "graph-search-item-0");
    assert.ok(model.results.length > 0);
  });

  it("navigates results with ArrowDown and wraps around", () => {
    const model = new SearchInputModel(mockLoadedNodes);
    model.setQuery("analyze");
    const count = model.results.length;
    assert.ok(count >= 2);

    assert.equal(model.highlightedIndex, 0);

    // Arrow down
    model.onArrowDown();
    assert.equal(model.highlightedIndex, 1);

    // Arrow down past end wraps around to 0
    for (let i = 2; i < count; i++) {
      model.onArrowDown();
    }
    model.onArrowDown(); // Wrap around
    assert.equal(model.highlightedIndex, 0);
  });

  it("navigates results with ArrowUp and wraps backwards", () => {
    const model = new SearchInputModel(mockLoadedNodes);
    model.setQuery("analyze");
    const count = model.results.length;
    assert.equal(model.highlightedIndex, 0);

    // Arrow up from 0 wraps to count - 1
    model.onArrowUp();
    assert.equal(model.highlightedIndex, count - 1);
  });

  it("handles Escape by closing dropdown first, then clearing on second Escape", () => {
    const model = new SearchInputModel(mockLoadedNodes);
    model.setQuery("analyze");
    assert.equal(model.isOpen, true);

    // 1st Escape closes dropdown
    model.onEscape();
    assert.equal(model.isOpen, false);
    assert.equal(model.query, "analyze");

    // 2nd Escape clears query
    model.onEscape();
    assert.equal(model.query, "");
  });

  it("clear() resets query, closed dropdown, and reset highlight index", () => {
    const model = new SearchInputModel(mockLoadedNodes);
    model.setQuery("parse");
    assert.equal(model.isOpen, true);

    model.clear();
    assert.equal(model.query, "");
    assert.equal(model.isOpen, false);
    assert.equal(model.highlightedIndex, -1);
    assert.equal(model.getAriaExpanded(), false);
  });
});
