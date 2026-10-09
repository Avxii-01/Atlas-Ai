import test, { describe, it } from "node:test";
import assert from "node:assert/strict";

import { ApiClientError } from "../lib/api.ts";
import type {
  RepositoryImpactResponse,
  ImpactFetchStatus,
} from "../lib/types.ts";
import type { EntityNodeData } from "../lib/graphMapper.ts";
import type { Node } from "@xyflow/react";

/**
 * State machine simulating the exact selection, synchronization,
 * cancellation, and impact-loading behaviors of RepositoryGraphView
 * and ImpactDetailsPanel.
 */
class ImpactWorkflowState {
  repositoryId: string;
  nodes: Node<EntityNodeData>[];
  selectedEntity: EntityNodeData | null = null;
  status: ImpactFetchStatus = "idle";
  impactData: RepositoryImpactResponse | null = null;
  errorMessage: string | null = null;

  // Race condition & cancellation guards
  private activeEntityId: string | null = null;
  private currentAbortController: AbortController | null = null;
  public requestCount: number = 0;

  constructor(repositoryId: string, initialNodes: Node<EntityNodeData>[] = []) {
    this.repositoryId = repositoryId;
    this.nodes = initialNodes;
  }

  /**
   * Simulates clicking a node on the graph canvas.
   */
  async selectNode(
    nodeId: string,
    fetchFn: (
      repoId: string,
      entityId: string,
      options?: { signal?: AbortSignal }
    ) => Promise<RepositoryImpactResponse>
  ): Promise<void> {
    const targetNode = this.nodes.find((n) => n.id === nodeId);
    if (!targetNode) {
      return;
    }

    // 1. Synchronize visual selection on graph nodes
    this.nodes = this.nodes.map((n) => ({
      ...n,
      selected: n.id === nodeId,
    }));

    // 2. Set selected entity
    this.selectedEntity = targetNode.data;

    // 3. Trigger impact load
    await this.loadImpact(targetNode.data.id, fetchFn);
  }

  /**
   * Simulates clicking an impacted dependent in the panel to navigate to it.
   */
  async selectEntityById(
    entityId: string,
    fetchFn: (
      repoId: string,
      entityId: string,
      options?: { signal?: AbortSignal }
    ) => Promise<RepositoryImpactResponse>
  ): Promise<boolean> {
    const targetNode = this.nodes.find((n) => n.id === entityId);
    if (!targetNode) {
      return false;
    }

    await this.selectNode(entityId, fetchFn);
    return true;
  }

  /**
   * Simulates clearing the selection (clicking canvas pane or close button).
   */
  clearSelection(): void {
    if (this.currentAbortController) {
      this.currentAbortController.abort();
      this.currentAbortController = null;
    }
    this.activeEntityId = null;
    this.selectedEntity = null;
    this.status = "idle";
    this.impactData = null;
    this.errorMessage = null;

    // Clear node selection flags
    this.nodes = this.nodes.map((n) => ({
      ...n,
      selected: false,
    }));
  }

  /**
   * Loads impact analysis for the target entity with cancellation & race guards.
   */
  async loadImpact(
    entityId: string,
    fetchFn: (
      repoId: string,
      entityId: string,
      options?: { signal?: AbortSignal }
    ) => Promise<RepositoryImpactResponse>
  ): Promise<void> {
    // Abort previous in-flight request
    if (this.currentAbortController) {
      this.currentAbortController.abort();
    }

    const controller = new AbortController();
    this.currentAbortController = controller;
    this.activeEntityId = entityId;

    this.status = "loading";
    this.errorMessage = null;
    this.impactData = null; // Clear stale results immediately

    this.requestCount++;

    try {
      const response = await fetchFn(this.repositoryId, entityId, {
        signal: controller.signal,
      });

      // Guard: only commit if response matches active entity and was not aborted
      if (this.activeEntityId === entityId && !controller.signal.aborted) {
        this.impactData = response;
        const hasDependents =
          (response.direct_dependents && response.direct_dependents.length > 0) ||
          (response.transitive_dependents && response.transitive_dependents.length > 0);

        this.status = hasDependents ? "success" : "empty";
      }
    } catch (err: unknown) {
      // Ignore cancellations
      if (controller.signal.aborted) {
        return;
      }

      if (this.activeEntityId === entityId) {
        this.status = "error";
        if (err instanceof ApiClientError) {
          this.errorMessage = err.message;
        } else if (err instanceof Error) {
          this.errorMessage = err.message;
        } else {
          this.errorMessage = "Failed to calculate impact analysis.";
        }
      }
    }
  }

  /**
   * Retries impact loading for the currently selected entity.
   */
  async retry(
    fetchFn: (
      repoId: string,
      entityId: string,
      options?: { signal?: AbortSignal }
    ) => Promise<RepositoryImpactResponse>
  ): Promise<void> {
    if (this.selectedEntity) {
      await this.loadImpact(this.selectedEntity.id, fetchFn);
    }
  }
}

describe("Impact Workflow and Selection State Machine (P0-23)", () => {
  const sampleNodes: Node<EntityNodeData>[] = [
    {
      id: "entity:func:format_identifier",
      type: "entityNode",
      position: { x: 100, y: 100 },
      data: {
        id: "entity:func:format_identifier",
        label: "Function",
        name: "format_identifier",
        type: "Function",
        displayName: "format_identifier(val)",
        properties: {},
      },
      selected: false,
    },
    {
      id: "entity:class:ItemService",
      type: "entityNode",
      position: { x: 300, y: 200 },
      data: {
        id: "entity:class:ItemService",
        label: "Class",
        name: "ItemService",
        type: "Class",
        displayName: "ItemService",
        properties: {},
      },
      selected: false,
    },
    {
      id: "entity:file:app.py",
      type: "entityNode",
      position: { x: 500, y: 300 },
      data: {
        id: "entity:file:app.py",
        label: "File",
        name: "app.py",
        type: "File",
        displayName: "app.py",
        properties: {},
      },
      selected: false,
    },
  ];

  const sampleSuccessImpact: RepositoryImpactResponse = {
    entity: {
      id: "entity:func:format_identifier",
      name: "format_identifier",
      label: "Function",
      type: "Function",
      file_path: "utils.py",
      properties: {},
    },
    direct_dependents: [
      {
        id: "entity:class:ItemService",
        name: "ItemService",
        depth: 1,
        label: "Class",
        type: "Class",
        file_path: "services.py",
      },
    ],
    transitive_dependents: [
      {
        id: "entity:func:main",
        name: "main",
        depth: 2,
        label: "Function",
        type: "Function",
        file_path: "app.py",
      },
    ],
    affected_files: ["services.py", "app.py"],
    max_depth: 10,
    repository_id: "atlas_fixture",
  };

  const sampleEmptyImpact: RepositoryImpactResponse = {
    entity: {
      id: "entity:file:app.py",
      name: "app.py",
      label: "File",
      type: "File",
      file_path: "app.py",
      properties: {},
    },
    direct_dependents: [],
    transitive_dependents: [],
    affected_files: [],
    max_depth: 10,
    repository_id: "atlas_fixture",
  };

  it("initializes with idle status and no entity selected", () => {
    const workflow = new ImpactWorkflowState("atlas_fixture", [...sampleNodes]);
    assert.equal(workflow.status, "idle");
    assert.equal(workflow.selectedEntity, null);
    assert.equal(workflow.impactData, null);
    assert.equal(workflow.errorMessage, null);
    assert.ok(workflow.nodes.every((n) => n.selected === false));
  });

  it("selects a graph node, records stable entity identity, and highlights it visually", async () => {
    const workflow = new ImpactWorkflowState("atlas_fixture", [...sampleNodes]);

    await workflow.selectNode("entity:func:format_identifier", async () => sampleSuccessImpact);

    // Selected entity matches target node
    const selected = workflow.selectedEntity;
    if (!selected) {
      assert.fail("selectedEntity must not be null");
    }
    assert.equal(selected.id, "entity:func:format_identifier");
    assert.equal(selected.name, "format_identifier");
    assert.equal(selected.type, "Function");

    // Only the target node is marked selected in the nodes array
    assert.equal(workflow.nodes[0].selected, true);
    assert.equal(workflow.nodes[1].selected, false);
    assert.equal(workflow.nodes[2].selected, false);

    // Impact details are populated
    assert.equal(workflow.status, "success");
    const impact = workflow.impactData;
    assert.ok(impact !== null);
    assert.equal(impact.direct_dependents.length, 1);
    assert.equal(impact.transitive_dependents.length, 1);
    assert.equal(impact.affected_files.length, 2);
  });

  it("updating selection switches active node, clears previous impact, and requests new data", async () => {
    const workflow = new ImpactWorkflowState("atlas_fixture", [...sampleNodes]);

    // Select first node
    await workflow.selectNode("entity:func:format_identifier", async () => sampleSuccessImpact);
    assert.equal(workflow.selectedEntity?.id, "entity:func:format_identifier");
    assert.equal(workflow.nodes[0].selected, true);

    // Select second node
    await workflow.selectNode("entity:file:app.py", async () => sampleEmptyImpact);

    assert.equal(workflow.selectedEntity?.id, "entity:file:app.py");
    assert.equal(workflow.nodes[0].selected, false, "Previous node must be unselected");
    assert.equal(workflow.nodes[2].selected, true, "New node must be selected");

    // Impact data must be updated to new selection
    assert.equal(workflow.status, "empty");
    assert.equal(workflow.impactData?.entity.id, "entity:file:app.py");
    assert.equal(workflow.impactData?.direct_dependents.length, 0);
  });

  it("clearing selection resets impact panel state, unselects all nodes, and clears stale data", async () => {
    const workflow = new ImpactWorkflowState("atlas_fixture", [...sampleNodes]);

    await workflow.selectNode("entity:func:format_identifier", async () => sampleSuccessImpact);
    assert.ok(workflow.selectedEntity !== null);
    assert.equal(workflow.status, "success");

    // Clear selection
    workflow.clearSelection();

    assert.equal(workflow.selectedEntity, null);
    assert.equal(workflow.status, "idle");
    assert.equal(workflow.impactData, null);
    assert.equal(workflow.errorMessage, null);
    assert.ok(workflow.nodes.every((n) => n.selected === false));
  });

  it("distinguishes direct dependents from transitive dependents and preserves traversal depth", async () => {
    const workflow = new ImpactWorkflowState("atlas_fixture", [...sampleNodes]);

    await workflow.selectNode("entity:func:format_identifier", async () => sampleSuccessImpact);

    assert.equal(workflow.status, "success");
    const impact = workflow.impactData;
    assert.ok(impact);

    // Direct dependents
    assert.equal(impact.direct_dependents.length, 1);
    assert.equal(impact.direct_dependents[0].name, "ItemService");
    assert.equal(impact.direct_dependents[0].type, "Class");
    assert.equal(impact.direct_dependents[0].depth, 1);

    // Transitive dependents
    assert.equal(impact.transitive_dependents.length, 1);
    assert.equal(impact.transitive_dependents[0].name, "main");
    assert.equal(impact.transitive_dependents[0].type, "Function");
    assert.equal(impact.transitive_dependents[0].depth, 2);

    // Affected files
    assert.deepEqual(impact.affected_files, ["services.py", "app.py"]);
    assert.equal(impact.max_depth, 10);
  });

  it("treats zero direct and zero transitive dependents as valid empty state rather than error", async () => {
    const workflow = new ImpactWorkflowState("atlas_fixture", [...sampleNodes]);

    await workflow.selectNode("entity:file:app.py", async () => sampleEmptyImpact);

    assert.equal(workflow.status, "empty");
    assert.equal(workflow.errorMessage, null);
    assert.ok(workflow.impactData !== null);
    assert.equal(workflow.impactData.direct_dependents.length, 0);
    assert.equal(workflow.impactData.transitive_dependents.length, 0);
    assert.equal(workflow.impactData.affected_files.length, 0);
  });

  it("navigates to impacted entity when clicking an impacted dependent present in the graph", async () => {
    const workflow = new ImpactWorkflowState("atlas_fixture", [...sampleNodes]);

    // Select format_identifier
    await workflow.selectNode("entity:func:format_identifier", async () => sampleSuccessImpact);
    assert.equal(workflow.selectedEntity?.id, "entity:func:format_identifier");

    // Click on ItemService in the impact list (present in sampleNodes)
    const navigated = await workflow.selectEntityById(
      "entity:class:ItemService",
      async () => ({
        ...sampleSuccessImpact,
        entity: {
          id: "entity:class:ItemService",
          name: "ItemService",
          label: "Class",
          type: "Class",
          file_path: "services.py",
        },
      })
    );

    assert.equal(navigated, true);
    assert.equal(workflow.selectedEntity?.id, "entity:class:ItemService");
    assert.equal(workflow.nodes[1].selected, true);
    assert.equal(workflow.nodes[0].selected, false);
  });

  it("handles navigation attempt to an impacted entity not present in current graph nodes", async () => {
    const workflow = new ImpactWorkflowState("atlas_fixture", [...sampleNodes]);

    await workflow.selectNode("entity:func:format_identifier", async () => sampleSuccessImpact);

    // Try navigating to main (which is not in sampleNodes)
    const navigated = await workflow.selectEntityById(
      "entity:func:main",
      async () => sampleSuccessImpact
    );

    assert.equal(navigated, false);
    // Selection remains unchanged
    assert.equal(workflow.selectedEntity?.id, "entity:func:format_identifier");
  });

  it("handles API error, presents readable message, and allows user to retry", async () => {
    const workflow = new ImpactWorkflowState("atlas_fixture", [...sampleNodes]);

    let attempt = 0;
    const failingApi = async (_repo: string, _entity: string) => {
      attempt++;
      if (attempt === 1) {
        throw new ApiClientError("Entity not found in repository graph.", 404);
      }
      return sampleSuccessImpact;
    };

    // First attempt fails
    await workflow.selectNode("entity:func:format_identifier", failingApi);

    assert.equal(workflow.status, "error");
    assert.equal(workflow.errorMessage, "Entity not found in repository graph.");
    assert.equal(workflow.impactData as unknown, null);

    // Retry succeeded
    await workflow.retry(failingApi);

    assert.equal(workflow.status, "success");
    assert.equal(workflow.errorMessage, null);
    const retriedImpact = workflow.impactData;
    if (!retriedImpact) {
      assert.fail("retriedImpact must not be null");
    }
    assert.equal(retriedImpact.entity.id, "entity:func:format_identifier");
  });

  it("handles network failure without getting stuck in loading state", async () => {
    const workflow = new ImpactWorkflowState("atlas_fixture", [...sampleNodes]);

    await workflow.selectNode("entity:func:format_identifier", async () => {
      throw new ApiClientError(
        "Unable to reach backend service to calculate impact.",
        0,
        "Network connection failed",
        "NETWORK_ERROR"
      );
    });

    assert.equal(workflow.status, "error");
    assert.ok(workflow.errorMessage?.includes("Unable to reach backend service"));
    assert.equal(workflow.impactData, null);
  });

  it("prevents race condition: slow response for Entity A cannot overwrite newer selection Entity B", async () => {
    const workflow = new ImpactWorkflowState("atlas_fixture", [...sampleNodes]);

    let resolveEntityA: (val: RepositoryImpactResponse) => void = () => {};
    let rejectEntityA: (reason?: unknown) => void = () => {};
    const entityAPromise = new Promise<RepositoryImpactResponse>((resolve, reject) => {
      resolveEntityA = resolve;
      rejectEntityA = reject;
    });

    // 1. User selects Entity A (slow)
    const selectAPromise = workflow.selectNode(
      "entity:func:format_identifier",
      async (_repo, _entity, options) => {
        options?.signal?.addEventListener("abort", () => {
          rejectEntityA(new ApiClientError("Request aborted", 0, undefined, "ABORTED"));
        });
        return entityAPromise;
      }
    );

    assert.equal(workflow.status, "loading");
    assert.equal(workflow.selectedEntity?.id, "entity:func:format_identifier");

    // 2. User quickly selects Entity B (fast) before Entity A responds
    const entityBResponse: RepositoryImpactResponse = {
      entity: {
        id: "entity:class:ItemService",
        name: "ItemService",
        label: "Class",
        type: "Class",
        file_path: "services.py",
      },
      direct_dependents: [],
      transitive_dependents: [],
      affected_files: ["services.py"],
      max_depth: 5,
      repository_id: "atlas_fixture",
    };

    const selectBPromise = workflow.selectNode(
      "entity:class:ItemService",
      async () => entityBResponse
    );

    await selectBPromise;

    // Entity B is now the active selection
    assert.equal(workflow.selectedEntity?.id, "entity:class:ItemService");
    assert.equal(workflow.impactData?.entity.id, "entity:class:ItemService");
    assert.equal(workflow.nodes[1].selected, true);
    assert.equal(workflow.nodes[0].selected, false);

    // 3. Now slow Entity A finishes or rejects due to abort
    resolveEntityA(sampleSuccessImpact);
    await selectAPromise;

    // INVARIANT: State must remain Entity B's state, NOT overwritten by Entity A
    assert.equal(workflow.selectedEntity?.id, "entity:class:ItemService");
    assert.equal(workflow.impactData?.entity.id, "entity:class:ItemService");
    assert.equal(workflow.nodes[1].selected, true);
    assert.equal(workflow.nodes[0].selected, false);
  });
});
