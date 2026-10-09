import test, { describe, it } from "node:test";
import assert from "node:assert/strict";

import { ApiClientError } from "../lib/api.ts";
import {
  mapGraphResponseToReactFlow,
  type EntityNodeData,
} from "../lib/graphMapper.ts";
import type {
  RepositoryGraphResponse,
  GraphFetchStatus,
} from "../lib/types.ts";
import type { Node, Edge } from "@xyflow/react";

/**
 * State machine simulation mirroring RepositoryGraphView.
 */
class GraphWorkflowState {
  repositoryIdInput: string = "";
  activeRepositoryId: string = "";
  status: GraphFetchStatus = "idle";
  errorMessage: string | null = null;
  nodes: Node<EntityNodeData>[] = [];
  edges: Edge[] = [];
  callCount: number = 0;

  constructor(initialRepositoryId: string = "") {
    this.repositoryIdInput = initialRepositoryId;
    this.activeRepositoryId = initialRepositoryId;
  }

  setInput(newInput: string) {
    this.repositoryIdInput = newInput;
  }

  async loadGraph(
    fetchFn: (repoId: string) => Promise<RepositoryGraphResponse>
  ): Promise<void> {
    const cleanId = this.repositoryIdInput.trim();
    if (!cleanId) {
      this.errorMessage = "Please enter a valid repository identifier.";
      this.status = "error";
      return;
    }

    // Guard duplicate submissions while loading
    if (this.status === "loading") {
      return;
    }

    this.status = "loading";
    this.errorMessage = null;

    try {
      this.callCount++;
      const response = await fetchFn(cleanId);
      this.activeRepositoryId = response.repository_id || cleanId;

      if (!response.nodes || response.nodes.length === 0) {
        this.nodes = [];
        this.edges = [];
        this.status = "empty";
        return;
      }

      const mapped = mapGraphResponseToReactFlow(response);
      this.nodes = mapped.nodes;
      this.edges = mapped.edges;
      this.status = "success";
    } catch (err: unknown) {
      this.status = "error";
      if (err instanceof ApiClientError) {
        this.errorMessage = err.message;
      } else if (err instanceof Error) {
        this.errorMessage = err.message;
      } else {
        this.errorMessage = "Failed to retrieve repository graph.";
      }
    }
  }

  reset() {
    this.status = "idle";
    this.errorMessage = null;
    this.nodes = [];
    this.edges = [];
  }
}

describe("Graph Visualization Workflow State Machine (P0-22)", () => {
  const sampleSuccessGraph: RepositoryGraphResponse = {
    repository_id: "atlas_fixture",
    nodes: [
      {
        id: "repo:atlas_fixture",
        label: "Repository",
        name: "atlas_fixture",
        type: "Repository",
        display_name: "Atlas Fixture",
      },
      {
        id: "file:main.py",
        label: "File",
        name: "main.py",
        type: "File",
      },
    ],
    relationships: [
      {
        id: "rel:contains:1",
        source: "repo:atlas_fixture",
        target: "file:main.py",
        type: "CONTAINS",
      },
    ],
  };

  it("initializes in idle state when no repository identifier is provided", () => {
    const workflow = new GraphWorkflowState("");
    assert.equal(workflow.status, "idle");
    assert.equal(workflow.nodes.length, 0);
    assert.equal(workflow.edges.length, 0);
    assert.equal(workflow.errorMessage, null);
  });

  it("rejects loading when repository input is empty or whitespace", async () => {
    const workflow = new GraphWorkflowState("   ");
    let apiCalled = false;

    await workflow.loadGraph(async () => {
      apiCalled = true;
      return sampleSuccessGraph;
    });

    assert.equal(apiCalled, false, "API must not be called on whitespace ID");
    assert.equal(workflow.status, "error");
    assert.ok(workflow.errorMessage?.includes("Please enter a valid repository identifier"));
  });

  it("handles successful graph loading and populates nodes and edges", async () => {
    const workflow = new GraphWorkflowState("atlas_fixture");

    await workflow.loadGraph(async (repoId) => {
      assert.equal(repoId, "atlas_fixture");
      return sampleSuccessGraph;
    });

    assert.equal(workflow.status, "success");
    assert.equal(workflow.activeRepositoryId, "atlas_fixture");
    assert.equal(workflow.nodes.length, 2);
    assert.equal(workflow.edges.length, 1);
    assert.equal(workflow.errorMessage, null);
    assert.equal(workflow.nodes[0].id, "repo:atlas_fixture");
    assert.equal(workflow.edges[0].id, "rel:contains:1");
  });

  it("handles empty repository response gracefully without crashing", async () => {
    const workflow = new GraphWorkflowState("empty_repo");
    const emptyResponse: RepositoryGraphResponse = {
      repository_id: "empty_repo",
      nodes: [],
      relationships: [],
    };

    await workflow.loadGraph(async () => emptyResponse);

    assert.equal(workflow.status, "empty");
    assert.equal(workflow.nodes.length, 0);
    assert.equal(workflow.edges.length, 0);
    assert.equal(workflow.errorMessage, null);
  });

  it("prevents duplicate requests while a graph request is already loading", async () => {
    const workflow = new GraphWorkflowState("atlas_fixture");
    let resolvePending: (val: RepositoryGraphResponse) => void = () => {};
    const pendingPromise = new Promise<RepositoryGraphResponse>((resolve) => {
      resolvePending = resolve;
    });

    // Start first request
    const firstCall = workflow.loadGraph(async () => pendingPromise);
    assert.equal(workflow.status, "loading");
    assert.equal(workflow.callCount, 1);

    // Attempt second load while first is pending
    await workflow.loadGraph(async () => pendingPromise);
    assert.equal(workflow.callCount, 1, "Duplicate loadGraph call must be prevented");

    // Resolve first request
    resolvePending(sampleSuccessGraph);
    await firstCall;

    assert.equal(workflow.status, "success");
    assert.equal(workflow.callCount, 1);
  });

  it("handles API failure (404 / 503) and allows user retry", async () => {
    const workflow = new GraphWorkflowState("nonexistent_repo");

    let attempt = 0;
    const failingApi = async (id: string) => {
      attempt++;
      if (attempt === 1) {
        throw new ApiClientError(
          `Repository '${id}' was not found in the graph database.`,
          404
        );
      }
      return sampleSuccessGraph;
    };

    // First attempt fails
    await workflow.loadGraph(failingApi);
    assert.equal(workflow.status, "error");
    assert.ok(workflow.errorMessage?.includes("not found"));

    // User updates ID and retries
    workflow.setInput("atlas_fixture");
    await workflow.loadGraph(failingApi);

    assert.equal(workflow.status, "success");
    assert.equal(workflow.activeRepositoryId, "atlas_fixture");
    assert.equal(workflow.errorMessage, null);
    assert.equal(workflow.nodes.length, 2);
  });

  it("handles network failure without leaving application stuck in loading", async () => {
    const workflow = new GraphWorkflowState("atlas_fixture");

    await workflow.loadGraph(async () => {
      throw new ApiClientError(
        "Unable to reach backend service to retrieve repository graph.",
        0,
        "Connection refused",
        "NETWORK_ERROR"
      );
    });

    assert.equal(workflow.status, "error");
    assert.ok(workflow.errorMessage?.includes("Unable to reach backend service"));
    assert.equal(workflow.nodes.length, 0);
  });

  it("clears previous graph data and errors when switching repositories", async () => {
    const workflow = new GraphWorkflowState("repo_A");

    // Load repo_A
    await workflow.loadGraph(async () => sampleSuccessGraph);
    assert.equal(workflow.status, "success");
    assert.equal(workflow.nodes.length, 2);

    // Switch to repo_B which is empty
    workflow.setInput("repo_B");
    await workflow.loadGraph(async () => ({
      repository_id: "repo_B",
      nodes: [],
      relationships: [],
    }));

    assert.equal(workflow.status, "empty");
    assert.equal(workflow.activeRepositoryId, "repo_B");
    assert.equal(workflow.nodes.length, 0, "Stale nodes from repo_A must be cleared");
    assert.equal(workflow.edges.length, 0, "Stale edges from repo_A must be cleared");
  });
});
