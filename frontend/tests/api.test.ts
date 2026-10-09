import test, { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  analyzeRepository,
  validateRepositoryRequest,
  ApiClientError,
  getApiBaseUrl,
} from "../lib/api.ts";
import type {
  RepositoryAnalysisRequest,
  RepositoryAnalysisResponse,
} from "../lib/types.ts";

describe("API Client - validateRepositoryRequest", () => {
  it("accepts a valid repository path and returns trimmed request", () => {
    const raw: RepositoryAnalysisRequest = {
      path: "  tests/fixtures/atlas_fixture  ",
    };
    const validated = validateRepositoryRequest(raw);
    assert.equal(validated.path, "tests/fixtures/atlas_fixture");
    assert.equal(validated.name, undefined);
  });

  it("preserves optional repository name when provided", () => {
    const raw: RepositoryAnalysisRequest = {
      path: "tests/fixtures/atlas_fixture",
      name: "atlas_fixture",
    };
    const validated = validateRepositoryRequest(raw);
    assert.equal(validated.path, "tests/fixtures/atlas_fixture");
    assert.equal(validated.name, "atlas_fixture");
  });

  it("throws ApiClientError with code INVALID_PATH when path is empty", () => {
    assert.throws(
      () => validateRepositoryRequest({ path: "" }),
      (err: unknown) => {
        assert.ok(err instanceof ApiClientError);
        assert.equal(err.code, "INVALID_PATH");
        assert.equal(err.status, 400);
        assert.ok(err.message.includes("Repository path is required"));
        return true;
      }
    );
  });

  it("throws ApiClientError with code INVALID_PATH when path is only whitespace", () => {
    assert.throws(
      () => validateRepositoryRequest({ path: "   \t  \n  " }),
      (err: unknown) => {
        assert.ok(err instanceof ApiClientError);
        assert.equal(err.code, "INVALID_PATH");
        assert.equal(err.status, 400);
        return true;
      }
    );
  });
});

describe("API Client - analyzeRepository", () => {
  const originalFetch = globalThis.fetch;

  function restoreFetch() {
    globalThis.fetch = originalFetch;
  }

  const mockSuccessfulResponse: RepositoryAnalysisResponse = {
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

  it("successfully posts analysis request and returns backend response", async () => {
    let capturedUrl = "";
    let capturedMethod = "";
    let capturedBody = "";
    let capturedHeaders: Record<string, string> = {};

    globalThis.fetch = (async (url: string | URL | Request, init?: RequestInit) => {
      capturedUrl = url.toString();
      capturedMethod = init?.method || "";
      capturedBody = init?.body as string;
      capturedHeaders = (init?.headers as Record<string, string>) || {};

      return new Response(JSON.stringify(mockSuccessfulResponse), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }) as typeof fetch;

    try {
      const response = await analyzeRepository({
        path: "tests/fixtures/atlas_fixture",
        name: "atlas_fixture",
      });

      assert.ok(capturedUrl.includes("/api/v1/repositories/analyze"));
      assert.equal(capturedMethod, "POST");
      assert.equal(capturedHeaders["Content-Type"], "application/json");

      const parsedBody = JSON.parse(capturedBody);
      assert.equal(parsedBody.path, "tests/fixtures/atlas_fixture");
      assert.equal(parsedBody.name, "atlas_fixture");

      assert.equal(response.repository_id, "atlas_fixture");
      assert.equal(response.status, "completed");
      assert.equal(response.summary.files, 5);
      assert.equal(response.summary.classes, 3);
      assert.equal(response.summary.functions, 10);
      assert.equal(response.summary.relationships, 12);
      assert.equal(response.summary.modules, 2);
    } finally {
      restoreFetch();
    }
  });

  it("handles valid response with zero counts", async () => {
    const zeroCountsResponse: RepositoryAnalysisResponse = {
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

    globalThis.fetch = (async () => {
      return new Response(JSON.stringify(zeroCountsResponse), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }) as typeof fetch;

    try {
      const response = await analyzeRepository({ path: "/empty/repo" });
      assert.equal(response.repository_id, "empty_repo");
      assert.equal(response.summary.files, 0);
      assert.equal(response.summary.classes, 0);
      assert.equal(response.summary.functions, 0);
      assert.equal(response.summary.relationships, 0);
    } finally {
      restoreFetch();
    }
  });

  it("handles 400 Bad Request with safe backend detail message", async () => {
    globalThis.fetch = (async () => {
      return new Response(
        JSON.stringify({ detail: "Repository path does not exist or is not a directory: /invalid/path" }),
        {
          status: 400,
          headers: { "Content-Type": "application/json" },
        }
      );
    }) as typeof fetch;

    try {
      await assert.rejects(
        async () => {
          await analyzeRepository({ path: "/invalid/path" });
        },
        (err: unknown) => {
          assert.ok(err instanceof ApiClientError);
          assert.equal(err.status, 400);
          assert.ok(err.message.includes("Repository path does not exist"));
          return true;
        }
      );
    } finally {
      restoreFetch();
    }
  });

  it("handles 422 Unprocessable Entity with validation details", async () => {
    globalThis.fetch = (async () => {
      return new Response(
        JSON.stringify({
          detail: [
            { loc: ["body", "path"], msg: "Field required", type: "missing" },
          ],
        }),
        {
          status: 422,
          headers: { "Content-Type": "application/json" },
        }
      );
    }) as typeof fetch;

    try {
      await assert.rejects(
        async () => {
          await analyzeRepository({ path: "some-path" });
        },
        (err: unknown) => {
          assert.ok(err instanceof ApiClientError);
          assert.equal(err.status, 422);
          assert.ok(err.message.includes("Field required"));
          return true;
        }
      );
    } finally {
      restoreFetch();
    }
  });

  it("handles 500 Internal Server Error with user-friendly safe message", async () => {
    globalThis.fetch = (async () => {
      return new Response(
        JSON.stringify({ detail: "Internal error processing graph" }),
        {
          status: 500,
          headers: { "Content-Type": "application/json" },
        }
      );
    }) as typeof fetch;

    try {
      await assert.rejects(
        async () => {
          await analyzeRepository({ path: "/valid/path" });
        },
        (err: unknown) => {
          assert.ok(err instanceof ApiClientError);
          assert.equal(err.status, 500);
          assert.ok(err.message.includes("Internal error processing graph"));
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
          await analyzeRepository({ path: "/valid/path" });
        },
        (err: unknown) => {
          assert.ok(err instanceof ApiClientError);
          assert.equal(err.status, 0);
          assert.equal(err.code, "NETWORK_ERROR");
          assert.ok(err.message.includes("Unable to reach backend service"));
          return true;
        }
      );
    } finally {
      restoreFetch();
    }
  });

  it("handles unexpected malformed JSON response gracefully", async () => {
    globalThis.fetch = (async () => {
      return new Response("Not JSON at all", {
        status: 200,
        headers: { "Content-Type": "text/html" },
      });
    }) as typeof fetch;

    try {
      await assert.rejects(
        async () => {
          await analyzeRepository({ path: "/valid/path" });
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

  it("handles response missing required fields gracefully", async () => {
    globalThis.fetch = (async () => {
      return new Response(JSON.stringify({ status: "incomplete" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }) as typeof fetch;

    try {
      await assert.rejects(
        async () => {
          await analyzeRepository({ path: "/valid/path" });
        },
        (err: unknown) => {
          assert.ok(err instanceof ApiClientError);
          assert.equal(err.code, "INVALID_RESPONSE");
          assert.ok(err.message.includes("Missing required field"));
          return true;
        }
      );
    } finally {
      restoreFetch();
    }
  });
});
