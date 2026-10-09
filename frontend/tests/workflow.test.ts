import test, { describe, it } from "node:test";
import assert from "node:assert/strict";

import {
  validateRepositoryRequest,
  analyzeRepository,
  ApiClientError,
} from "../lib/api.ts";
import type {
  RepositoryAnalysisRequest,
  RepositoryAnalysisResponse,
  AnalysisStatus,
} from "../lib/types.ts";

/**
 * Simulates the state machine executed by RepositoryAnalysisView.
 * Tests full state transition invariants specified by P0-21.
 */
class AnalysisWorkflowState {
  path: string = "";
  name: string = "";
  status: AnalysisStatus = "idle";
  result: RepositoryAnalysisResponse | null = null;
  errorMessage: string | null = null;
  validationError: string | null = null;
  apiCallCount: number = 0;

  constructor(initialPath: string = "") {
    this.path = initialPath;
  }

  setPath(newPath: string) {
    this.path = newPath;
    if (this.validationError) {
      this.validationError = null;
    }
  }

  setName(newName: string) {
    this.name = newName;
  }

  async submit(
    apiFn: (req: RepositoryAnalysisRequest) => Promise<RepositoryAnalysisResponse>
  ): Promise<void> {
    // Prevent duplicate submission while loading
    if (this.status === "loading") {
      return;
    }

    const trimmedPath = this.path.trim();
    if (!trimmedPath) {
      this.validationError =
        "Repository path is required. Please enter a valid filesystem path.";
      return;
    }

    this.validationError = null;
    this.errorMessage = null;
    this.result = null; // Clear stale result
    this.status = "loading";

    try {
      const response = await apiFn({
        path: trimmedPath,
        name: this.name.trim() || undefined,
      });
      this.apiCallCount++;
      this.result = response;
      this.status = "success";
    } catch (err: unknown) {
      this.apiCallCount++;
      this.status = "error";
      if (err instanceof ApiClientError) {
        this.errorMessage = err.message;
      } else if (err instanceof Error) {
        this.errorMessage = err.message;
      } else {
        this.errorMessage =
          "An unexpected error occurred during repository analysis. Please try again.";
      }
    }
  }

  reset() {
    this.status = "idle";
    this.result = null;
    this.errorMessage = null;
    this.validationError = null;
  }
}

describe("Analysis Workflow State Machine (P0-21)", () => {
  const sampleSuccessResponse: RepositoryAnalysisResponse = {
    repository_id: "atlas_fixture",
    status: "completed",
    summary: {
      files: 5,
      classes: 3,
      functions: 10,
      relationships: 12,
      modules: 2,
      methods: 6,
      imports: 4,
    },
  };

  it("validates empty input and rejects submission before calling API", async () => {
    const workflow = new AnalysisWorkflowState("");
    let apiCalled = false;

    await workflow.submit(async () => {
      apiCalled = true;
      return sampleSuccessResponse;
    });

    assert.equal(apiCalled, false, "API must not be called on empty path");
    assert.equal(workflow.status, "idle");
    assert.ok(workflow.validationError);
    assert.ok(workflow.validationError.includes("Repository path is required"));
    assert.equal(workflow.result, null);
  });

  it("validates whitespace-only input and rejects submission", async () => {
    const workflow = new AnalysisWorkflowState("    \t  \n  ");
    let apiCalled = false;

    await workflow.submit(async () => {
      apiCalled = true;
      return sampleSuccessResponse;
    });

    assert.equal(apiCalled, false, "API must not be called on whitespace path");
    assert.equal(workflow.status, "idle");
    assert.ok(workflow.validationError);
  });

  it("clears validation error when user enters new input", async () => {
    const workflow = new AnalysisWorkflowState("");
    await workflow.submit(async () => sampleSuccessResponse);
    assert.ok(workflow.validationError);

    workflow.setPath("tests/fixtures/atlas_fixture");
    assert.equal(workflow.validationError, null, "Validation error must clear on input change");
  });

  it("handles successful analysis workflow and preserves response metrics", async () => {
    const workflow = new AnalysisWorkflowState("tests/fixtures/atlas_fixture");
    let receivedPayload: RepositoryAnalysisRequest | undefined;

    await workflow.submit(async (req) => {
      receivedPayload = req;
      return sampleSuccessResponse;
    });

    assert.equal(workflow.status, "success");
    assert.ok(receivedPayload !== undefined);
    assert.equal(receivedPayload.path, "tests/fixtures/atlas_fixture");

    const result = workflow.result;
    assert.ok(result !== null);
    assert.equal(result.repository_id, "atlas_fixture");
    assert.equal(result.status, "completed");

    // Check all 7 summary metrics from response
    assert.equal(result.summary.files, 5);
    assert.equal(result.summary.classes, 3);
    assert.equal(result.summary.functions, 10);
    assert.equal(result.summary.relationships, 12);
    assert.equal(result.summary.modules, 2);
    assert.equal(result.summary.methods, 6);
    assert.equal(result.summary.imports, 4);
    assert.equal(workflow.errorMessage, null);
  });

  it("handles valid response with zero counts across all metrics", async () => {
    const workflow = new AnalysisWorkflowState("/path/to/empty");
    const zeroResponse: RepositoryAnalysisResponse = {
      repository_id: "empty_repo",
      status: "completed",
      summary: {
        files: 0,
        classes: 0,
        functions: 0,
        relationships: 0,
        modules: 0,
        methods: 0,
        imports: 0,
      },
    };

    await workflow.submit(async () => zeroResponse);

    assert.equal(workflow.status, "success");
    assert.equal(workflow.result?.repository_id, "empty_repo");
    assert.equal(workflow.result?.summary.files, 0);
    assert.equal(workflow.result?.summary.classes, 0);
    assert.equal(workflow.result?.summary.functions, 0);
    assert.equal(workflow.result?.summary.relationships, 0);
  });

  it("prevents duplicate submissions while request is loading", async () => {
    const workflow = new AnalysisWorkflowState("tests/fixtures/atlas_fixture");
    let callCount = 0;

    let resolvePending: (val: RepositoryAnalysisResponse) => void = () => {};
    const pendingPromise = new Promise<RepositoryAnalysisResponse>((resolve) => {
      resolvePending = resolve;
    });

    const pendingApi = async () => {
      callCount++;
      return pendingPromise;
    };

    // First submission (starts loading)
    const firstSubmission = workflow.submit(pendingApi);
    assert.equal(workflow.status, "loading");
    assert.equal(workflow.result === null, true);

    // Attempt second submission while loading
    await workflow.submit(pendingApi);

    // Verify second call was ignored
    assert.equal(callCount, 1, "Duplicate submission must be ignored while loading");

    // Complete the first request
    resolvePending(sampleSuccessResponse);
    await firstSubmission;

    assert.equal(workflow.status, "success");
    const loadedResult = workflow.result as RepositoryAnalysisResponse | null;
    assert.equal(loadedResult !== null, true);
    assert.equal(loadedResult?.repository_id, "atlas_fixture");
    assert.equal(callCount, 1);
  });

  it("handles backend API error response and allows retry", async () => {
    const workflow = new AnalysisWorkflowState("/nonexistent/repo");

    let attempt = 0;
    const failingApi = async () => {
      attempt++;
      if (attempt === 1) {
        throw new ApiClientError(
          "Repository path does not exist or is not a directory: /nonexistent/repo",
          400
        );
      }
      return sampleSuccessResponse;
    };

    // First attempt fails
    await workflow.submit(failingApi);
    assert.equal(workflow.status, "error");
    assert.equal(workflow.result === null, true);
    assert.ok(workflow.errorMessage?.includes("Repository path does not exist"));

    // User corrects input and retries
    workflow.setPath("tests/fixtures/atlas_fixture");
    await workflow.submit(failingApi);

    assert.equal(workflow.status, "success");
    const retriedResult = workflow.result as RepositoryAnalysisResponse | null;
    assert.equal(retriedResult !== null, true);
    assert.equal(retriedResult?.repository_id, "atlas_fixture");
    assert.equal(workflow.errorMessage, null);
  });



  it("handles network disruption error without leaving UI stuck in loading", async () => {
    const workflow = new AnalysisWorkflowState("/valid/repo");

    await workflow.submit(async () => {
      throw new ApiClientError(
        "Unable to reach backend service. Please verify the service is running and accessible.",
        0,
        "Network connection failed",
        "NETWORK_ERROR"
      );
    });

    assert.equal(workflow.status, "error");
    assert.equal(workflow.result, null);
    assert.ok(workflow.errorMessage?.includes("Unable to reach backend service"));
  });

  it("clears stale result on repeated analysis of another repository", async () => {
    const workflow = new AnalysisWorkflowState("tests/fixtures/atlas_fixture");

    // Initial successful analysis
    await workflow.submit(async () => sampleSuccessResponse);
    assert.equal(workflow.status, "success");
    assert.equal(workflow.result?.repository_id, "atlas_fixture");

    // Submit second repository which fails
    workflow.setPath("/failing/repo");
    await workflow.submit(async () => {
      throw new ApiClientError("Directory access denied", 403);
    });

    // Stale result must not be shown
    assert.equal(workflow.status, "error");
    assert.equal(workflow.result, null, "Stale result from previous run must be cleared");
    assert.equal(workflow.errorMessage, "Directory access denied");
  });

  it("resets workflow to initial state when user resets", async () => {
    const workflow = new AnalysisWorkflowState("tests/fixtures/atlas_fixture");
    await workflow.submit(async () => sampleSuccessResponse);
    assert.equal(workflow.status, "success");

    workflow.reset();
    assert.equal(workflow.status, "idle");
    assert.equal(workflow.result, null);
    assert.equal(workflow.errorMessage, null);
    assert.equal(workflow.validationError, null);
  });
});
