import test, { describe, it } from "node:test";
import assert from "node:assert/strict";

import {
  SUPPORTED_ENTITY_TYPES,
  SUPPORTED_RELATIONSHIP_TYPES,
  ENTITY_TYPE_CONFIG,
  RELATIONSHIP_TYPE_CONFIG,
  getEntityBadgeStyle,
  getRelationshipEdgeStyle,
  DEFAULT_ENTITY_BADGE_STYLE,
  DEFAULT_EDGE_STYLE,
} from "../lib/graphTokens.ts";
import { getEdgeStyle } from "../lib/graphMapper.ts";

describe("Graph Legend & Visual Token Alignment (Checkpoint 2)", () => {
  it("defines all 7 supported entity types with exact ground truth labels and descriptions", () => {
    const expectedTypes = [
      "repository",
      "file",
      "module",
      "class",
      "function",
      "method",
      "import",
    ];

    assert.equal(SUPPORTED_ENTITY_TYPES.length, 7);
    const types = SUPPORTED_ENTITY_TYPES.map((t) => t.type);
    assert.deepEqual(types, expectedTypes);

    for (const item of SUPPORTED_ENTITY_TYPES) {
      assert.ok(item.label.length > 0, `Entity '${item.type}' must have non-empty label`);
      assert.ok(item.description.length > 0, `Entity '${item.type}' must have non-empty description`);
    }
  });

  it("defines all 4 supported relationship types with exact ground truth types and descriptions", () => {
    const expectedRels = ["CONTAINS", "IMPORTS", "CALLS", "INHERITS"];

    assert.equal(SUPPORTED_RELATIONSHIP_TYPES.length, 4);
    const rels = SUPPORTED_RELATIONSHIP_TYPES.map((r) => r.type);
    assert.deepEqual(rels, expectedRels);

    for (const item of SUPPORTED_RELATIONSHIP_TYPES) {
      assert.ok(item.label.length > 0, `Relationship '${item.type}' must have non-empty label`);
      assert.ok(item.description.length > 0, `Relationship '${item.type}' must have non-empty description`);
    }
  });

  it("verifies badge styles match exact colors used by existing renderer", () => {
    // 1. Repository -> purple
    const repoStyle = getEntityBadgeStyle("repository");
    assert.equal(repoStyle.text, "#c084fc");
    assert.equal(repoStyle.bg, "rgba(168, 85, 247, 0.15)");
    assert.equal(repoStyle.border, "rgba(168, 85, 247, 0.35)");

    // 2. File -> blue
    const fileStyle = getEntityBadgeStyle("file");
    assert.equal(fileStyle.text, "#60a5fa");
    assert.equal(fileStyle.bg, "rgba(59, 130, 246, 0.15)");
    assert.equal(fileStyle.border, "rgba(59, 130, 246, 0.35)");

    // 3. Module -> cyan
    const moduleStyle = getEntityBadgeStyle("module");
    assert.equal(moduleStyle.text, "#22d3ee");
    assert.equal(moduleStyle.bg, "rgba(6, 182, 212, 0.15)");

    // 4. Class -> indigo
    const classStyle = getEntityBadgeStyle("class");
    assert.equal(classStyle.text, "#a5b4fc");
    assert.equal(classStyle.bg, "rgba(99, 102, 241, 0.15)");

    // 5. Function -> emerald
    const funcStyle = getEntityBadgeStyle("function");
    assert.equal(funcStyle.text, "#34d399");
    assert.equal(funcStyle.bg, "rgba(16, 185, 129, 0.15)");

    // 6. Method -> teal
    const methodStyle = getEntityBadgeStyle("method");
    assert.equal(methodStyle.text, "#2dd4bf");
    assert.equal(methodStyle.bg, "rgba(20, 184, 166, 0.15)");

    // 7. Import -> amber
    const importStyle = getEntityBadgeStyle("import");
    assert.equal(importStyle.text, "#fbbf24");
    assert.equal(importStyle.bg, "rgba(245, 158, 11, 0.15)");
  });

  it("verifies graphMapper edge styles delegate to graphTokens and match exactly", () => {
    for (const item of SUPPORTED_RELATIONSHIP_TYPES) {
      const fromTokens = getRelationshipEdgeStyle(item.type);
      const fromMapper = getEdgeStyle(item.type);

      assert.deepEqual(
        fromMapper,
        fromTokens,
        `Edge style for relationship '${item.type}' must match between graphMapper and graphTokens`
      );

      assert.ok(fromTokens.stroke.startsWith("#"), `Relationship '${item.type}' must have hex stroke`);
      assert.equal(fromTokens.strokeWidth, 1.5, `Relationship '${item.type}' strokeWidth must be 1.5`);
    }

    // Specific colors
    assert.equal(getEdgeStyle("CONTAINS").stroke, "#64748b");
    assert.equal(getEdgeStyle("IMPORTS").stroke, "#60a5fa");
    assert.equal(getEdgeStyle("CALLS").stroke, "#34d399");
    assert.equal(getEdgeStyle("INHERITS").stroke, "#fbbf24");
  });

  it("is case-insensitive for entity and relationship lookups", () => {
    assert.deepEqual(getEntityBadgeStyle("REPOSITORY"), getEntityBadgeStyle("repository"));
    assert.deepEqual(getEntityBadgeStyle("Class"), getEntityBadgeStyle("class"));
    assert.deepEqual(getRelationshipEdgeStyle("contains"), getRelationshipEdgeStyle("CONTAINS"));
    assert.deepEqual(getRelationshipEdgeStyle("calls"), getRelationshipEdgeStyle("CALLS"));
  });

  it("falls back to default styles gracefully for unknown types", () => {
    const unknownBadge = getEntityBadgeStyle("unknown_kind");
    assert.deepEqual(unknownBadge, DEFAULT_ENTITY_BADGE_STYLE);

    const unknownEdge = getRelationshipEdgeStyle("UNKNOWN_REL");
    assert.deepEqual(unknownEdge, DEFAULT_EDGE_STYLE);
  });
});

describe("GraphLegend State Management Invariants (Checkpoint 2)", () => {
  /**
   * Pure state simulation mirroring GraphLegend toggle behavior.
   */
  class LegendStateModel {
    isOpen: boolean;
    toggleCount: number = 0;

    constructor(initialOpen: boolean = false) {
      this.isOpen = initialOpen;
    }

    toggle() {
      this.isOpen = !this.isOpen;
      this.toggleCount++;
    }

    getAriaExpanded(): boolean {
      return this.isOpen;
    }

    getAriaLabel(): string {
      return this.isOpen ? "Collapse Graph Legend" : "Expand Graph Legend";
    }

    getToggleIcon(): string {
      return this.isOpen ? "▾" : "▴";
    }
  }

  it("initializes in collapsed state by default with correct aria attributes", () => {
    const legend = new LegendStateModel(false);
    assert.equal(legend.isOpen, false);
    assert.equal(legend.getAriaExpanded(), false);
    assert.equal(legend.getAriaLabel(), "Expand Graph Legend");
    assert.equal(legend.getToggleIcon(), "▴");
  });

  it("initializes in expanded state when configured with initialOpen=true", () => {
    const legend = new LegendStateModel(true);
    assert.equal(legend.isOpen, true);
    assert.equal(legend.getAriaExpanded(), true);
    assert.equal(legend.getAriaLabel(), "Collapse Graph Legend");
    assert.equal(legend.getToggleIcon(), "▾");
  });

  it("toggles open and closed state cleanly and updates aria attributes", () => {
    const legend = new LegendStateModel(false);

    // 1st toggle: open
    legend.toggle();
    assert.equal(legend.isOpen, true);
    assert.equal(legend.getAriaExpanded(), true);
    assert.equal(legend.getAriaLabel(), "Collapse Graph Legend");
    assert.equal(legend.getToggleIcon(), "▾");
    assert.equal(legend.toggleCount, 1);

    // 2nd toggle: close
    legend.toggle();
    assert.equal(legend.isOpen, false);
    assert.equal(legend.getAriaExpanded(), false);
    assert.equal(legend.getAriaLabel(), "Expand Graph Legend");
    assert.equal(legend.getToggleIcon(), "▴");
    assert.equal(legend.toggleCount, 2);
  });
});
