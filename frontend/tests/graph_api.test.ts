import test, { describe, it } from "node:test";
import assert from "node:assert/strict";

import {
  getRepositoryGraph,
  getRepositoryOverview,
  getEntityChildren,
  getEntityNeighbors,
  searchRepositoryEntities,
  ApiClientError,
} from "../lib/api.ts";
import type {
  RepositoryGraphResponse,
  EntityChildrenResponse,
  EntityNeighborsResponse,
  EntitySearchResponse,
} from "../lib/types.ts";

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

  it("supports request cancellation via AbortSignal in options object", async () => {
    const controller = new AbortController();

    globalThis.fetch = (async (_url: string | URL | Request, init?: RequestInit) => {
      const signal = init?.signal;
      if (signal?.aborted) {
        throw new DOMException("The user aborted a request.", "AbortError");
      }
      return new Promise((_resolve, reject) => {
        signal?.addEventListener("abort", () => {
          reject(new DOMException("The user aborted a request.", "AbortError"));
        });
      });
    }) as typeof fetch;

    try {
      const promise = getRepositoryGraph("test_repo", { signal: controller.signal });
      controller.abort();

      await assert.rejects(
        promise,
        (err: unknown) => {
          assert.ok(err instanceof ApiClientError);
          assert.equal(err.code, "ABORTED");
          assert.equal(err.status, 0);
          assert.ok(err.message.includes("cancelled"));
          return true;
        }
      );
    } finally {
      restoreFetch();
    }
  });

  it("supports request cancellation via AbortSignal when numeric limit is also provided", async () => {
    const controller = new AbortController();

    globalThis.fetch = (async (_url: string | URL | Request, init?: RequestInit) => {
      const signal = init?.signal;
      if (signal?.aborted) {
        throw new DOMException("The user aborted a request.", "AbortError");
      }
      return new Promise((_resolve, reject) => {
        signal?.addEventListener("abort", () => {
          reject(new DOMException("The user aborted a request.", "AbortError"));
        });
      });
    }) as typeof fetch;

    try {
      const promise = getRepositoryGraph("test_repo", 50, { signal: controller.signal });
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

  it("preserves limit when passed in options object", async () => {
    let capturedUrl = "";

    globalThis.fetch = (async (url: string | URL | Request) => {
      capturedUrl = url.toString();
      return new Response(JSON.stringify(sampleGraphResponse), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }) as typeof fetch;

    try {
      await getRepositoryGraph("test_repo", { limit: 25 });
      assert.ok(capturedUrl.includes("/graph?limit=25"));
    } finally {
      restoreFetch();
    }
  });

  it("handles empty search matches and dual alias when entities only is returned", async () => {
    // Empty search matches
    globalThis.fetch = (async () => {
      return new Response(
        JSON.stringify({
          repository_id: "test_repo",
          query: "unknown_fn",
          entities: [],
          results: [],
          total_matches: 0,
          returned_matches: 0,
          has_more: false,
          truncated: false,
          offset: 0,
          limit: 50,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }) as typeof fetch;

    try {
      const res = await searchRepositoryEntities("test_repo", "unknown_fn");
      assert.equal(res.total_matches, 0);
      assert.equal(res.entities.length, 0);
      assert.equal(res.results.length, 0);
      assert.equal(res.has_more, false);
    } finally {
      restoreFetch();
    }

    // Backend emits entities only (without results key)
    globalThis.fetch = (async () => {
      return new Response(
        JSON.stringify({
          repository_id: "test_repo",
          query: "mod",
          entities: [{ id: "m:1", label: "Module", name: "mod1", type: "Module" }],
          total_matches: 1,
          returned_matches: 1,
          has_more: false,
          truncated: false,
          offset: 0,
          limit: 50,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }) as typeof fetch;

    try {
      const res = await searchRepositoryEntities("test_repo", "mod");
      assert.equal(res.entities.length, 1);
      assert.equal(res.results.length, 1);
      assert.equal(res.results[0].name, "mod1");
    } finally {
      restoreFetch();
    }
  });

  it("handles 404, 503, and AbortSignal cancellation in searchRepositoryEntities", async () => {
    // 404 Not Found
    globalThis.fetch = (async () => {
      return new Response(JSON.stringify({ detail: "Repository not found" }), {
        status: 404,
        headers: { "Content-Type": "application/json" },
      });
    }) as typeof fetch;

    try {
      await assert.rejects(
        async () => {
          await searchRepositoryEntities("missing_repo", "query");
        },
        (err: unknown) => {
          assert.ok(err instanceof ApiClientError);
          assert.equal(err.status, 404);
          return true;
        }
      );
    } finally {
      restoreFetch();
    }

    // AbortSignal
    const controller = new AbortController();
    globalThis.fetch = (async (_url: string | URL | Request, init?: RequestInit) => {
      const signal = init?.signal;
      if (signal?.aborted) {
        throw new DOMException("Aborted", "AbortError");
      }
      return new Promise((_resolve, reject) => {
        signal?.addEventListener("abort", () => {
          reject(new DOMException("Aborted", "AbortError"));
        });
      });
    }) as typeof fetch;

    try {
      const promise = searchRepositoryEntities("test_repo", "query", { signal: controller.signal });
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
});

describe("Bounded Overview API Client - getRepositoryOverview (Step 6)", () => {
  const originalFetch = globalThis.fetch;

  function restoreFetch() {
    globalThis.fetch = originalFetch;
  }

  const sampleOverviewResponse: RepositoryGraphResponse = {
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
    metadata: {
      view: "overview",
      total_files: 10,
      returned_files: 1,
      has_more: true,
      truncated: true,
      offset: 0,
      limit: 1,
    },
  };

  it("calls GET /graph?view=overview with limit and offset query parameters", async () => {
    let capturedUrl = "";

    globalThis.fetch = (async (url: string | URL | Request) => {
      capturedUrl = url.toString();
      return new Response(JSON.stringify(sampleOverviewResponse), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }) as typeof fetch;

    try {
      const res = await getRepositoryOverview("atlas_fixture", { limit: 10, offset: 20 });
      assert.ok(capturedUrl.includes("/api/v1/repositories/atlas_fixture/graph?"));
      assert.ok(capturedUrl.includes("view=overview"));
      assert.ok(capturedUrl.includes("limit=10"));
      assert.ok(capturedUrl.includes("offset=20"));
      assert.equal(res.metadata?.view, "overview");
      assert.equal(res.metadata?.total_files, 10);
      assert.equal(res.metadata?.has_more, true);
    } finally {
      restoreFetch();
    }
  });

  it("rejects empty repository ID", async () => {
    await assert.rejects(
      async () => {
        await getRepositoryOverview("");
      },
      (err: unknown) => {
        assert.ok(err instanceof ApiClientError);
        assert.equal(err.code, "INVALID_ID");
        return true;
      }
    );
  });
});

describe("Entity Children API Client - getEntityChildren (Step 6)", () => {
  const originalFetch = globalThis.fetch;

  function restoreFetch() {
    globalThis.fetch = originalFetch;
  }

  const sampleChildrenResponse: EntityChildrenResponse = {
    repository_id: "test_repo",
    parent_id: "repo:test_repo::file::main.py",
    parent: {
      id: "repo:test_repo::file::main.py",
      label: "File",
      name: "main.py",
      type: "File",
    },
    children: [
      {
        id: "repo:test_repo::class::App",
        label: "Class",
        name: "App",
        type: "Class",
      },
    ],
    relationships: [
      {
        id: "rel:contains:main->App",
        source: "repo:test_repo::file::main.py",
        target: "repo:test_repo::class::App",
        type: "CONTAINS",
      },
    ],
    total_children: 1,
    returned_children: 1,
    has_more: false,
    truncated: false,
    offset: 0,
    limit: 50,
  };

  it("calls correct GET /entities/{entity_id}/children endpoint with pagination", async () => {
    let capturedUrl = "";

    globalThis.fetch = (async (url: string | URL | Request) => {
      capturedUrl = url.toString();
      return new Response(JSON.stringify(sampleChildrenResponse), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }) as typeof fetch;

    try {
      const res = await getEntityChildren("test_repo", "repo:test_repo::file::main.py", {
        limit: 25,
        offset: 5,
      });

      assert.ok(capturedUrl.includes("/api/v1/repositories/test_repo/entities/"));
      assert.ok(capturedUrl.includes("/children?"));
      assert.ok(capturedUrl.includes("limit=25"));
      assert.ok(capturedUrl.includes("offset=5"));
      assert.equal(res.parent_id, "repo:test_repo::file::main.py");
      assert.equal(res.children.length, 1);
      assert.equal(res.children[0].name, "App");
    } finally {
      restoreFetch();
    }
  });

  it("safely encodes entity IDs containing colons and preserves slashes", async () => {
    let capturedUrl = "";

    globalThis.fetch = (async (url: string | URL | Request) => {
      capturedUrl = url.toString();
      return new Response(JSON.stringify(sampleChildrenResponse), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }) as typeof fetch;

    try {
      await getEntityChildren("test_repo", "file::services/auth.py");
      assert.ok(capturedUrl.includes("/entities/file%3A%3Aservices/auth.py/children"));
    } finally {
      restoreFetch();
    }
  });

  it("rejects empty repository ID or entity ID", async () => {
    await assert.rejects(
      async () => {
        await getEntityChildren("", "entity1");
      },
      (err: unknown) => {
        assert.ok(err instanceof ApiClientError);
        assert.equal(err.code, "INVALID_ID");
        return true;
      }
    );

    await assert.rejects(
      async () => {
        await getEntityChildren("repo1", "   ");
      },
      (err: unknown) => {
        assert.ok(err instanceof ApiClientError);
        assert.equal(err.code, "INVALID_ID");
        return true;
      }
    );
  });

  it("handles 404 Not Found error gracefully", async () => {
    globalThis.fetch = (async () => {
      return new Response(JSON.stringify({ detail: "Entity not found" }), {
        status: 404,
        headers: { "Content-Type": "application/json" },
      });
    }) as typeof fetch;

    try {
      await assert.rejects(
        async () => {
          await getEntityChildren("repo1", "missing_entity");
        },
        (err: unknown) => {
          assert.ok(err instanceof ApiClientError);
          assert.equal(err.status, 404);
          assert.equal(err.message, "Entity not found");
          return true;
        }
      );
    } finally {
      restoreFetch();
    }
  });

  it("handles empty children results correctly", async () => {
    globalThis.fetch = (async () => {
      return new Response(
        JSON.stringify({
          repository_id: "test_repo",
          parent_id: "p_leaf",
          parent: { id: "p_leaf", label: "Function", name: "leaf_fn", type: "Function" },
          children: [],
          relationships: [],
          total_children: 0,
          returned_children: 0,
          has_more: false,
          truncated: false,
          offset: 0,
          limit: 50,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }) as typeof fetch;

    try {
      const res = await getEntityChildren("test_repo", "p_leaf");
      assert.equal(res.total_children, 0);
      assert.equal(res.children.length, 0);
      assert.equal(res.relationships.length, 0);
      assert.equal(res.has_more, false);
    } finally {
      restoreFetch();
    }
  });

  it("handles 503 database unavailable and network disruption in getEntityChildren", async () => {
    globalThis.fetch = (async () => {
      return new Response(JSON.stringify({ detail: "Database unavailable" }), {
        status: 503,
        headers: { "Content-Type": "application/json" },
      });
    }) as typeof fetch;

    try {
      await assert.rejects(
        async () => {
          await getEntityChildren("test_repo", "p_node");
        },
        (err: unknown) => {
          assert.ok(err instanceof ApiClientError);
          assert.equal(err.status, 503);
          return true;
        }
      );
    } finally {
      restoreFetch();
    }

    globalThis.fetch = (async () => {
      throw new Error("Connection refused");
    }) as typeof fetch;

    try {
      await assert.rejects(
        async () => {
          await getEntityChildren("test_repo", "p_node");
        },
        (err: unknown) => {
          assert.ok(err instanceof ApiClientError);
          assert.equal(err.code, "NETWORK_ERROR");
          return true;
        }
      );
    } finally {
      restoreFetch();
    }
  });

  it("supports request cancellation via AbortSignal in getEntityChildren", async () => {
    const controller = new AbortController();
    globalThis.fetch = (async (_url: string | URL | Request, init?: RequestInit) => {
      const signal = init?.signal;
      if (signal?.aborted) {
        throw new DOMException("Aborted", "AbortError");
      }
      return new Promise((_resolve, reject) => {
        signal?.addEventListener("abort", () => {
          reject(new DOMException("Aborted", "AbortError"));
        });
      });
    }) as typeof fetch;

    try {
      const promise = getEntityChildren("test_repo", "p_node", { signal: controller.signal });
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
});

describe("Entity Neighbors API Client - getEntityNeighbors (Step 6)", () => {
  const originalFetch = globalThis.fetch;

  function restoreFetch() {
    globalThis.fetch = originalFetch;
  }

  const sampleNeighborsResponse: EntityNeighborsResponse = {
    repository_id: "test_repo",
    entity_id: "fn_1",
    center: {
      id: "fn_1",
      label: "Function",
      name: "run",
      type: "Function",
    },
    neighbors: [
      {
        id: "fn_2",
        label: "Function",
        name: "calc",
        type: "Function",
      },
    ],
    relationships: [
      {
        id: "rel:calls:1",
        source: "fn_1",
        target: "fn_2",
        type: "CALLS",
      },
    ],
    total_relationships: 1,
    returned_relationships: 1,
    total_neighbors: 1,
    returned_neighbors: 1,
    direction: "outgoing",
    has_more: false,
    truncated: false,
    offset: 0,
    limit: 50,
  };

  it("calls correct GET /entities/{entity_id}/neighbors with direction and types filter", async () => {
    let capturedUrl = "";

    globalThis.fetch = (async (url: string | URL | Request) => {
      capturedUrl = url.toString();
      return new Response(JSON.stringify(sampleNeighborsResponse), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }) as typeof fetch;

    try {
      const res = await getEntityNeighbors("test_repo", "fn_1", {
        direction: "outgoing",
        types: "CALLS,IMPORTS",
        limit: 10,
        offset: 0,
      });

      assert.ok(capturedUrl.includes("/entities/fn_1/neighbors?"));
      assert.ok(capturedUrl.includes("direction=outgoing"));
      assert.ok(capturedUrl.includes("types=CALLS%2CIMPORTS"));
      assert.ok(capturedUrl.includes("limit=10"));
      assert.equal(res.direction, "outgoing");
      assert.equal(res.neighbors.length, 1);
      assert.equal(res.relationships[0].type, "CALLS");
    } finally {
      restoreFetch();
    }
  });

  it("rejects invalid direction value before network call", async () => {
    await assert.rejects(
      async () => {
        // @ts-expect-error invalid direction testing
        await getEntityNeighbors("test_repo", "fn_1", { direction: "sideways" });
      },
      (err: unknown) => {
        assert.ok(err instanceof ApiClientError);
        assert.equal(err.code, "INVALID_DIRECTION");
        return true;
      }
    );
  });

  it("supports incoming, bidirectional, and omitted direction semantics", async () => {
    const urls: string[] = [];

    globalThis.fetch = (async (url: string | URL | Request) => {
      urls.push(url.toString());
      return new Response(JSON.stringify(sampleNeighborsResponse), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }) as typeof fetch;

    try {
      // 1. Incoming direction
      await getEntityNeighbors("test_repo", "fn_1", { direction: "incoming" });
      assert.ok(urls[0].includes("direction=incoming"));

      // 2. Both / bidirectional
      await getEntityNeighbors("test_repo", "fn_1", { direction: "both" });
      assert.ok(urls[1].includes("direction=both"));

      // 3. Omitted direction (no direction query param in url)
      await getEntityNeighbors("test_repo", "fn_1");
      assert.ok(!urls[2].includes("direction="));
    } finally {
      restoreFetch();
    }
  });

  it("safely encodes entity IDs containing colons and preserves slashes in neighbors endpoint", async () => {
    let capturedUrl = "";

    globalThis.fetch = (async (url: string | URL | Request) => {
      capturedUrl = url.toString();
      return new Response(JSON.stringify(sampleNeighborsResponse), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }) as typeof fetch;

    try {
      await getEntityNeighbors("test_repo", "repo::demo::file::services/auth.py");
      assert.ok(capturedUrl.includes("/entities/repo%3A%3Ademo%3A%3Afile%3A%3Aservices/auth.py/neighbors"));
    } finally {
      restoreFetch();
    }
  });

  it("handles empty neighbor results, 404 missing entity, and 503 service unavailable", async () => {
    // Empty neighbors
    globalThis.fetch = (async () => {
      return new Response(
        JSON.stringify({
          repository_id: "test_repo",
          entity_id: "isolated_fn",
          center: { id: "isolated_fn", label: "Function", name: "iso", type: "Function" },
          neighbors: [],
          relationships: [],
          total_relationships: 0,
          returned_relationships: 0,
          total_neighbors: 0,
          returned_neighbors: 0,
          direction: "both",
          has_more: false,
          truncated: false,
          offset: 0,
          limit: 50,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }) as typeof fetch;

    try {
      const res = await getEntityNeighbors("test_repo", "isolated_fn");
      assert.equal(res.total_neighbors, 0);
      assert.equal(res.neighbors.length, 0);
      assert.equal(res.relationships.length, 0);
    } finally {
      restoreFetch();
    }

    // 404 Not Found
    globalThis.fetch = (async () => {
      return new Response(JSON.stringify({ detail: "Entity not found" }), {
        status: 404,
        headers: { "Content-Type": "application/json" },
      });
    }) as typeof fetch;

    try {
      await assert.rejects(
        async () => {
          await getEntityNeighbors("test_repo", "missing_fn");
        },
        (err: unknown) => {
          assert.ok(err instanceof ApiClientError);
          assert.equal(err.status, 404);
          return true;
        }
      );
    } finally {
      restoreFetch();
    }
  });

  it("supports cancellation via AbortSignal in getEntityNeighbors", async () => {
    const controller = new AbortController();
    globalThis.fetch = (async (_url: string | URL | Request, init?: RequestInit) => {
      const signal = init?.signal;
      if (signal?.aborted) {
        throw new DOMException("Aborted", "AbortError");
      }
      return new Promise((_resolve, reject) => {
        signal?.addEventListener("abort", () => {
          reject(new DOMException("Aborted", "AbortError"));
        });
      });
    }) as typeof fetch;

    try {
      const promise = getEntityNeighbors("test_repo", "fn_1", { signal: controller.signal });
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
});

describe("Entity Search API Client - searchRepositoryEntities (Step 6)", () => {
  const originalFetch = globalThis.fetch;

  function restoreFetch() {
    globalThis.fetch = originalFetch;
  }

  const sampleSearchResponse: EntitySearchResponse = {
    repository_id: "test_repo",
    query: "process",
    entities: [
      {
        id: "fn:process_data",
        label: "Function",
        name: "process_data",
        type: "Function",
      },
    ],
    results: [
      {
        id: "fn:process_data",
        label: "Function",
        name: "process_data",
        type: "Function",
      },
    ],
    total_matches: 1,
    returned_matches: 1,
    has_more: false,
    truncated: false,
    offset: 0,
    limit: 50,
    type_filter: "Function",
  };

  it("calls correct GET /entities/search endpoint with query and type filter", async () => {
    let capturedUrl = "";

    globalThis.fetch = (async (url: string | URL | Request) => {
      capturedUrl = url.toString();
      return new Response(JSON.stringify(sampleSearchResponse), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }) as typeof fetch;

    try {
      const res = await searchRepositoryEntities("test_repo", "process", {
        type: "Function",
        limit: 20,
        offset: 0,
      });

      assert.ok(capturedUrl.includes("/api/v1/repositories/test_repo/entities/search?"));
      assert.ok(capturedUrl.includes("q=process"));
      assert.ok(capturedUrl.includes("type=Function"));
      assert.ok(capturedUrl.includes("limit=20"));
      assert.equal(res.total_matches, 1);
      assert.equal(res.entities[0].name, "process_data");
      assert.equal(res.results[0].name, "process_data");
    } finally {
      restoreFetch();
    }
  });

  it("handles dual alias: populates entities when backend returns results only", async () => {
    globalThis.fetch = (async () => {
      return new Response(
        JSON.stringify({
          repository_id: "test_repo",
          query: "calc",
          results: [{ id: "fn:calc", label: "Function", name: "calc", type: "Function" }],
          total_matches: 1,
          returned_matches: 1,
          has_more: false,
          truncated: false,
          offset: 0,
          limit: 50,
        }),
        {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }
      );
    }) as typeof fetch;

    try {
      const res = await searchRepositoryEntities("test_repo", "calc");
      assert.equal(res.entities.length, 1);
      assert.equal(res.entities[0].name, "calc");
      assert.equal(res.results.length, 1);
      assert.equal(res.results[0].name, "calc");
    } finally {
      restoreFetch();
    }
  });

  it("rejects empty query before network call", async () => {
    await assert.rejects(
      async () => {
        await searchRepositoryEntities("test_repo", "   ");
      },
      (err: unknown) => {
        assert.ok(err instanceof ApiClientError);
        assert.equal(err.code, "INVALID_QUERY");
        return true;
      }
    );
  });
});
