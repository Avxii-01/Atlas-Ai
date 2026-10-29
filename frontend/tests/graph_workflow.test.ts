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

  // Race condition & cancellation guards
  private currentAbortController: AbortController | null = null;
  private activeRepoId: string | null = null;
  private currentRequestId: number = 0;

  constructor(initialRepositoryId: string = "") {
    this.repositoryIdInput = initialRepositoryId;
    this.activeRepositoryId = initialRepositoryId;
  }

  setInput(newInput: string) {
    this.repositoryIdInput = newInput;
  }

  async loadGraph(
    fetchFn: (repoId: string, options?: { signal?: AbortSignal }) => Promise<RepositoryGraphResponse>,
    explicitRepoId?: string
  ): Promise<void> {
    const targetId = explicitRepoId !== undefined ? explicitRepoId : this.repositoryIdInput;
    const cleanId = targetId.trim();
    if (!cleanId) {
      this.errorMessage = "Please enter a valid repository identifier.";
      this.status = "error";
      return;
    }

    // In UI, submit button is disabled when status is loading AND input has not changed
    if (this.status === "loading" && this.activeRepoId === cleanId && explicitRepoId === undefined) {
      return;
    }

    // Abort prior in-flight request if present
    if (this.currentAbortController) {
      this.currentAbortController.abort();
    }

    const controller = new AbortController();
    this.currentAbortController = controller;
    this.activeRepoId = cleanId;
    const reqId = ++this.currentRequestId;

    this.status = "loading";
    this.errorMessage = null;

    try {
      this.callCount++;
      const response = await fetchFn(cleanId, { signal: controller.signal });

      // Stale response guard: ensure response matches active request and was not aborted
      if (
        this.currentRequestId !== reqId ||
        this.activeRepoId !== cleanId ||
        controller.signal.aborted
      ) {
        return;
      }

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
      if (
        controller.signal.aborted ||
        (err instanceof ApiClientError && err.code === "ABORTED") ||
        (err instanceof Error && err.name === "AbortError")
      ) {
        return;
      }

      if (this.currentRequestId === reqId && this.activeRepoId === cleanId) {
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
  }

  unmount() {
    if (this.currentAbortController) {
      this.currentAbortController.abort();
    }
  }

  reset() {
    if (this.currentAbortController) {
      this.currentAbortController.abort();
    }
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

  it("prevents race condition: slow response for Repo A cannot overwrite newer response for Repo B", async () => {
    const workflow = new GraphWorkflowState("repo_A");

    let resolveRepoA: (val: RepositoryGraphResponse) => void = () => {};
    let rejectRepoA: (reason?: unknown) => void = () => {};
    const repoAPromise = new Promise<RepositoryGraphResponse>((resolve, reject) => {
      resolveRepoA = resolve;
      rejectRepoA = reject;
    });

    // 1. User loads repo_A (slow network)
    const loadAPromise = workflow.loadGraph(async (_id, options) => {
      options?.signal?.addEventListener("abort", () => {
        rejectRepoA(new ApiClientError("Request aborted", 0, undefined, "ABORTED"));
      });
      return repoAPromise;
    });

    assert.equal(workflow.status, "loading");
    assert.equal(workflow.callCount, 1);

    // 2. User quickly switches input to repo_B and triggers load
    const repoBResponse: RepositoryGraphResponse = {
      repository_id: "repo_B",
      nodes: [
        { id: "repo:repo_B", label: "Repository", name: "repo_B", type: "Repository" },
      ],
      relationships: [],
    };

    workflow.setInput("repo_B");
    const loadBPromise = workflow.loadGraph(async () => repoBResponse);
    await loadBPromise;

    // Repo B must now be the active state
    assert.equal(workflow.status, "success");
    assert.equal(workflow.activeRepositoryId, "repo_B");
    assert.equal(workflow.nodes.length, 1);
    assert.equal(workflow.nodes[0].id, "repo:repo_B");

    // 3. Stale repo_A completes afterward
    resolveRepoA(sampleSuccessGraph);
    await loadAPromise;

    // Invariant: Repo A response MUST NOT overwrite active Repo B state
    assert.equal(workflow.status, "success");
    assert.equal(workflow.activeRepositoryId, "repo_B");
    assert.equal(workflow.nodes.length, 1);
    assert.equal(workflow.nodes[0].id, "repo:repo_B");
  });

  it("rapid repository changes supersede earlier in-flight requests and retain only the newest graph", async () => {
    const workflow = new GraphWorkflowState("repo_1");

    let abortedCount = 0;
    const makeFailingOrAbortedFetch = (id: string) => async (_repoId: string, options?: { signal?: AbortSignal }) => {
      return new Promise<RepositoryGraphResponse>((resolve, reject) => {
        options?.signal?.addEventListener("abort", () => {
          abortedCount++;
          reject(new ApiClientError("Request aborted", 0, undefined, "ABORTED"));
        });
        setTimeout(() => {
          resolve({
            repository_id: id,
            nodes: [{ id: `node:${id}`, label: "Repository", name: id, type: "Repository" }],
            relationships: [],
          });
        }, 50);
      });
    };

    // Trigger repo 1, then immediately repo 2, then repo 3
    const p1 = workflow.loadGraph(makeFailingOrAbortedFetch("repo_1"));
    workflow.setInput("repo_2");
    const p2 = workflow.loadGraph(makeFailingOrAbortedFetch("repo_2"));
    workflow.setInput("repo_3");
    const p3 = workflow.loadGraph(async () => ({
      repository_id: "repo_3",
      nodes: [{ id: "node:repo_3", label: "Repository", name: "repo_3", type: "Repository" }],
      relationships: [],
    }));

    await Promise.all([p1, p2, p3]);

    assert.equal(workflow.status, "success");
    assert.equal(workflow.activeRepositoryId, "repo_3");
    assert.equal(workflow.nodes[0].id, "node:repo_3");
    assert.equal(abortedCount, 2, "Both superseded requests must have had abort triggered");
  });

  it("stale request A failing with error does not overwrite active request B's success or loading state", async () => {
    const workflow = new GraphWorkflowState("failing_repo_A");

    let rejectRepoA: (reason?: unknown) => void = () => {};
    const repoAPromise = new Promise<RepositoryGraphResponse>((_resolve, reject) => {
      rejectRepoA = reject;
    });

    const loadAPromise = workflow.loadGraph(async () => repoAPromise);
    assert.equal(workflow.status, "loading");

    // Supersede with successful Repo B
    workflow.setInput("working_repo_B");
    const loadBPromise = workflow.loadGraph(async () => ({
      repository_id: "working_repo_B",
      nodes: [{ id: "node:B", label: "Repository", name: "B", type: "Repository" }],
      relationships: [],
    }));

    await loadBPromise;
    assert.equal(workflow.status, "success");
    assert.equal(workflow.errorMessage, null);

    // Stale Repo A rejects with 500 error
    rejectRepoA(new ApiClientError("Database failure for Repo A", 500));
    await loadAPromise;

    // Invariant: Status must remain success for Repo B, NOT overwritten by Repo A's error
    assert.equal(workflow.status, "success");
    assert.equal(workflow.activeRepositoryId, "working_repo_B");
    assert.equal(workflow.errorMessage, null);
  });

  it("cancelled request via AbortSignal does not transition UI into error state", async () => {
    const workflow = new GraphWorkflowState("repo_cancelled");

    const p = workflow.loadGraph(async (_id, options) => {
      return new Promise<RepositoryGraphResponse>((_resolve, reject) => {
        options?.signal?.addEventListener("abort", () => {
          reject(new ApiClientError("Request cancelled", 0, undefined, "ABORTED"));
        });
      });
    });

    assert.equal(workflow.status, "loading");
    workflow.unmount(); // Simulates unmount or user cancellation
    await p;

    // Invariant: Status must NOT be error
    assert.notEqual(workflow.status, "error");
    assert.equal(workflow.errorMessage, null);
  });

  it("unmount cleanup aborts active request and prevents state updates after unmount", async () => {
    const workflow = new GraphWorkflowState("repo_unmount");

    let signalAborted = false;
    let resolvePending: (val: RepositoryGraphResponse) => void = () => {};
    const pendingPromise = new Promise<RepositoryGraphResponse>((resolve) => {
      resolvePending = resolve;
    });

    const p = workflow.loadGraph(async (_id, options) => {
      options?.signal?.addEventListener("abort", () => {
        signalAborted = true;
      });
      return pendingPromise;
    });

    assert.equal(workflow.status, "loading");
    workflow.unmount();
    assert.equal(signalAborted, true, "Signal must be aborted on unmount");

    // Resolve after unmount
    resolvePending(sampleSuccessGraph);
    await p;

    // State must not have committed the nodes
    assert.equal(workflow.nodes.length, 0);
  });
});
