import test, { describe, it } from "node:test";
import assert from "node:assert/strict";

import { getRepositoryImpact, ApiClientError } from "../lib/api.ts";
import type { RepositoryImpactResponse } from "../lib/types.ts";

describe("Impact API Client - getRepositoryImpact (P0-23)", () => {
  const originalFetch = globalThis.fetch;

  function restoreFetch() {
    globalThis.fetch = originalFetch;
  }

  const sampleImpactResponse: RepositoryImpactResponse = {
    entity: {
      id: "repo::atlas_fixture::function::utils.format_identifier",
      name: "format_identifier",
      label: "Function",
      type: "Function",
      file_path: "utils.py",
      properties: {},
    },
    direct_dependents: [
      {
        id: "repo::atlas_fixture::class::services.ItemService",
        name: "ItemService",
        depth: 1,
        label: "Class",
        type: "Class",
        file_path: "services.py",
      },
    ],
    transitive_dependents: [
      {
        id: "repo::atlas_fixture::function::app.main",
        name: "main",
        depth: 3,
        label: "Function",
        type: "Function",
        file_path: "app.py",
      },
    ],
    affected_files: ["app.py", "services.py"],
    max_depth: 10,
    repository_id: "atlas_fixture",
  };

  it("rejects empty or whitespace repository ID before calling fetch", async () => {
    await assert.rejects(
      async () => {
        await getRepositoryImpact("", "entity:123");
      },
      (err: unknown) => {
        assert.ok(err instanceof ApiClientError);
        assert.equal(err.code, "INVALID_ID");
        assert.equal(err.status, 400);
        assert.ok(err.message.includes("Repository identifier is required"));
        return true;
      }
    );

    await assert.rejects(
      async () => {
        await getRepositoryImpact("   ", "entity:123");
      },
      (err: unknown) => {
        assert.ok(err instanceof ApiClientError);
        assert.equal(err.code, "INVALID_ID");
        return true;
      }
    );
  });

  it("rejects empty or whitespace entity ID before calling fetch", async () => {
    await assert.rejects(
      async () => {
        await getRepositoryImpact("repo_01", "");
      },
      (err: unknown) => {
        assert.ok(err instanceof ApiClientError);
        assert.equal(err.code, "INVALID_ID");
        assert.equal(err.status, 400);
        assert.ok(err.message.includes("Entity identifier is required"));
        return true;
      }
    );

    await assert.rejects(
      async () => {
        await getRepositoryImpact("repo_01", "   \t\n  ");
      },
      (err: unknown) => {
        assert.ok(err instanceof ApiClientError);
        assert.equal(err.code, "INVALID_ID");
        return true;
      }
    );
  });

  it("calls correct GET /api/v1/repositories/{repo_id}/impact/{entity_id} with URL encoding", async () => {
    let capturedUrl = "";
    let capturedMethod = "";
    let capturedAccept = "";

    globalThis.fetch = (async (url: string | URL | Request, init?: RequestInit) => {
      capturedUrl = url.toString();
      capturedMethod = init?.method || "";
      const headers = init?.headers as Record<string, string>;
      capturedAccept = headers?.Accept || "";

      return new Response(JSON.stringify(sampleImpactResponse), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }) as typeof fetch;

    try {
      const response = await getRepositoryImpact(
        "atlas_fixture",
        "repo::atlas_fixture::function::utils.format_identifier"
      );

      assert.ok(
        capturedUrl.includes(
          "/api/v1/repositories/atlas_fixture/impact/repo%3A%3Aatlas_fixture%3A%3Afunction%3A%3Autils.format_identifier"
        )
      );
      assert.equal(capturedMethod, "GET");
      assert.equal(capturedAccept, "application/json");

      assert.equal(response.entity.id, "repo::atlas_fixture::function::utils.format_identifier");
      assert.equal(response.entity.name, "format_identifier");
      assert.equal(response.direct_dependents.length, 1);
      assert.equal(response.direct_dependents[0].name, "ItemService");
      assert.equal(response.direct_dependents[0].depth, 1);
      assert.equal(response.transitive_dependents.length, 1);
      assert.equal(response.transitive_dependents[0].name, "main");
      assert.equal(response.transitive_dependents[0].depth, 3);
      assert.deepEqual(response.affected_files, ["app.py", "services.py"]);
      assert.equal(response.max_depth, 10);
    } finally {
      restoreFetch();
    }
  });

  it("appends max_depth query parameter when specified", async () => {
    let capturedUrl = "";

    globalThis.fetch = (async (url: string | URL | Request) => {
      capturedUrl = url.toString();
      return new Response(JSON.stringify(sampleImpactResponse), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }) as typeof fetch;

    try {
      await getRepositoryImpact("atlas_fixture", "entity_1", { maxDepth: 5 });
      assert.ok(capturedUrl.includes("?max_depth=5"));
    } finally {
      restoreFetch();
    }
  });

  it("handles 404 Not Found when entity or repository does not exist", async () => {
    globalThis.fetch = (async () => {
      return new Response(
        JSON.stringify({ detail: "Entity 'missing_fn' not found in repository 'repo_1'" }),
        { status: 404, headers: { "Content-Type": "application/json" } }
      );
    }) as typeof fetch;

    try {
      await assert.rejects(
        async () => {
          await getRepositoryImpact("repo_1", "missing_fn");
        },
        (err: unknown) => {
          assert.ok(err instanceof ApiClientError);
          assert.equal(err.status, 404);
          assert.ok(err.message.includes("not found"));
          return true;
        }
      );
    } finally {
      restoreFetch();
    }
  });

  it("handles 503 Service Unavailable when Neo4j is offline", async () => {
    globalThis.fetch = (async () => {
      return new Response(
        JSON.stringify({ detail: "Graph database service unavailable" }),
        { status: 503, headers: { "Content-Type": "application/json" } }
      );
    }) as typeof fetch;

    try {
      await assert.rejects(
        async () => {
          await getRepositoryImpact("repo_1", "fn_1");
        },
        (err: unknown) => {
          assert.ok(err instanceof ApiClientError);
          assert.equal(err.status, 503);
          assert.ok(err.message.includes("unavailable"));
          return true;
        }
      );
    } finally {
      restoreFetch();
    }
  });

  it("handles network failure gracefully", async () => {
    globalThis.fetch = (async () => {
      throw new TypeError("fetch failed");
    }) as typeof fetch;

    try {
      await assert.rejects(
        async () => {
          await getRepositoryImpact("repo_1", "fn_1");
        },
        (err: unknown) => {
          assert.ok(err instanceof ApiClientError);
          assert.equal(err.code, "NETWORK_ERROR");
          assert.equal(err.status, 0);
          assert.ok(err.message.includes("Unable to reach backend service"));
          return true;
        }
      );
    } finally {
      restoreFetch();
    }
  });

  it("supports request cancellation via AbortSignal", async () => {
    const controller = new AbortController();

    globalThis.fetch = (async (_url: string | URL | Request, init?: RequestInit) => {
      const signal = init?.signal;
      if (signal?.aborted) {
        const error = new DOMException("The user aborted a request.", "AbortError");
        throw error;
      }
      return new Promise((_resolve, reject) => {
        signal?.addEventListener("abort", () => {
          reject(new DOMException("The user aborted a request.", "AbortError"));
        });
      });
    }) as typeof fetch;

    try {
      const promise = getRepositoryImpact("repo_1", "fn_1", { signal: controller.signal });
      controller.abort();

      await assert.rejects(
        promise,
        (err: unknown) => {
          assert.ok(err instanceof ApiClientError);
          assert.equal(err.code, "ABORTED");
          return true;
        }
      );
    } finally {
      restoreFetch();
    }
  });

  it("rejects incomplete impact response missing required fields", async () => {
    globalThis.fetch = (async () => {
      return new Response(JSON.stringify({ entity: { id: "1", name: "test" } }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }) as typeof fetch;

    try {
      await assert.rejects(
        async () => {
          await getRepositoryImpact("repo_1", "fn_1");
        },
        (err: unknown) => {
          assert.ok(err instanceof ApiClientError);
          assert.equal(err.code, "INVALID_RESPONSE");
          assert.ok(err.message.includes("Missing required fields"));
          return true;
        }
      );
    } finally {
      restoreFetch();
    }
  });
});
