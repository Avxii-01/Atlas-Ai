import test, { describe, it } from "node:test";
import assert from "node:assert/strict";

import { getRepositoryGraph, ApiClientError } from "../lib/api.ts";
import type { RepositoryGraphResponse } from "../lib/types.ts";

describe("Graph API Client - getRepositoryGraph (P0-22)", () => {
  const originalFetch = globalThis.fetch;

  function restoreFetch() {
    globalThis.fetch = originalFetch;
  }

  const sampleGraphResponse: RepositoryGraphResponse = {
    repository_id: "test_repo",
    nodes: [
      {
        id: "repo:test_repo",
        label: "Repository",
        name: "test_repo",
        type: "Repository",
        display_name: "Test Repository",
        properties: {},
      },
      {
        id: "file:main.py",
        label: "File",
        name: "main.py",
        type: "File",
        display_name: "main.py",
        properties: { path: "main.py" },
      },
    ],
    relationships: [
      {
        id: "rel:contains:1",
        source: "repo:test_repo",
        target: "file:main.py",
        type: "CONTAINS",
      },
    ],
  };

  it("rejects empty or whitespace repository ID before calling fetch", async () => {
    await assert.rejects(
      async () => {
        await getRepositoryGraph("");
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
        await getRepositoryGraph("   \t  ");
      },
      (err: unknown) => {
        assert.ok(err instanceof ApiClientError);
        assert.equal(err.code, "INVALID_ID");
        return true;
      }
    );
  });

  it("calls correct GET /api/v1/repositories/{id}/graph endpoint with URL encoding", async () => {
    let capturedUrl = "";
    let capturedMethod = "";
    let capturedAccept = "";

    globalThis.fetch = (async (url: string | URL | Request, init?: RequestInit) => {
      capturedUrl = url.toString();
      capturedMethod = init?.method || "";
      const headers = init?.headers as Record<string, string>;
      capturedAccept = headers?.Accept || "";

      return new Response(JSON.stringify(sampleGraphResponse), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }) as typeof fetch;

    try {
      const response = await getRepositoryGraph("atlas_fixture");

      assert.ok(capturedUrl.includes("/api/v1/repositories/atlas_fixture/graph"));
      assert.equal(capturedMethod, "GET");
      assert.equal(capturedAccept, "application/json");

      assert.equal(response.repository_id, "test_repo");
      assert.equal(response.nodes.length, 2);
      assert.equal(response.relationships.length, 1);
      assert.equal(response.nodes[0].display_name, "Test Repository");
      assert.equal(response.relationships[0].type, "CONTAINS");
    } finally {
      restoreFetch();
    }
  });

  it("appends limit query parameter when provided", async () => {
    let capturedUrl = "";

    globalThis.fetch = (async (url: string | URL | Request) => {
      capturedUrl = url.toString();
      return new Response(JSON.stringify(sampleGraphResponse), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }) as typeof fetch;

    try {
      await getRepositoryGraph("test_repo", 50);
      assert.ok(capturedUrl.includes("/graph?limit=50"));
    } finally {
      restoreFetch();
    }
  });

  it("handles 404 Not Found when repository does not exist", async () => {
    globalThis.fetch = (async () => {
      return new Response(
        JSON.stringify({ detail: "Repository 'unknown_repo' not found" }),
        { status: 404, headers: { "Content-Type": "application/json" } }
      );
    }) as typeof fetch;

    try {
      await assert.rejects(
        async () => {
          await getRepositoryGraph("unknown_repo");
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
        JSON.stringify({ detail: "Neo4j connection unavailable" }),
        { status: 503, headers: { "Content-Type": "application/json" } }
      );
    }) as typeof fetch;

    try {
      await assert.rejects(
        async () => {
          await getRepositoryGraph("test_repo");
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

  it("handles 500 Internal Server Error safely", async () => {
    globalThis.fetch = (async () => {
      return new Response(
        JSON.stringify({ detail: "Internal error executing Cypher query" }),
        { status: 500, headers: { "Content-Type": "application/json" } }
      );
    }) as typeof fetch;

    try {
      await assert.rejects(
        async () => {
          await getRepositoryGraph("test_repo");
        },
        (err: unknown) => {
          assert.ok(err instanceof ApiClientError);
          assert.equal(err.status, 500);
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
          await getRepositoryGraph("test_repo");
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

  it("rejects malformed non-JSON response data", async () => {
    globalThis.fetch = (async () => {
      return new Response("<html>Bad Gateway</html>", {
        status: 200,
        headers: { "Content-Type": "text/html" },
      });
    }) as typeof fetch;

    try {
      await assert.rejects(
        async () => {
          await getRepositoryGraph("test_repo");
        },
        (err: unknown) => {
          assert.ok(err instanceof ApiClientError);
          assert.equal(err.code, "INVALID_RESPONSE");
          return true;
        }
      );
    } finally {
      restoreFetch();
    }
  });

  it("rejects incomplete graph data missing required arrays", async () => {
    globalThis.fetch = (async () => {
      return new Response(JSON.stringify({ repository_id: "test_repo" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }) as typeof fetch;

    try {
      await assert.rejects(
        async () => {
          await getRepositoryGraph("test_repo");
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
