/**
 * API client module for Atlas AI repository analysis (P0-18, P0-21).
 */

import type {
  RepositoryAnalysisRequest,
  RepositoryAnalysisResponse,
  RepositoryGraphResponse,
} from "./types.ts";

/**
 * Returns the configured base API URL, or empty string for relative paths.
 */
export function getApiBaseUrl(): string {
  if (typeof process !== "undefined" && process.env?.NEXT_PUBLIC_API_URL) {
    return process.env.NEXT_PUBLIC_API_URL.replace(/\/+$/, "");
  }
  return "";
}

/**
 * Custom error class capturing HTTP status, error code, and backend message details.
 */
export class ApiClientError extends Error {
  status?: number;
  code?: string;
  detail?: string;

  constructor(message: string, status?: number, detail?: string, code?: string) {
    super(message);
    this.name = "ApiClientError";
    this.status = status;
    this.detail = detail;
    this.code = code;
  }
}

/**
 * Validates and normalizes repository analysis request input.
 *
 * @throws ApiClientError with code 'INVALID_PATH' if path is missing or blank.
 */
export function validateRepositoryRequest(
  request: RepositoryAnalysisRequest
): RepositoryAnalysisRequest {
  const cleanPath = request?.path ? request.path.trim() : "";

  if (!cleanPath) {
    throw new ApiClientError(
      "Repository path is required. Please enter a valid filesystem path.",
      400,
      undefined,
      "INVALID_PATH"
    );
  }

  const validated: RepositoryAnalysisRequest = {
    path: cleanPath,
  };

  if (request.name && request.name.trim()) {
    validated.name = request.name.trim();
  }

  return validated;
}

/**
 * Formats FastAPI/Pydantic validation details into a readable single string.
 */
function parseErrorDetail(data: unknown): string | null {
  if (!data || typeof data !== "object") {
    return null;
  }

  const obj = data as Record<string, unknown>;

  if (typeof obj.detail === "string" && obj.detail.trim()) {
    return obj.detail.trim();
  }

  // Handle FastAPI 422 validation error arrays: [{ loc: [...], msg: "..." }]
  if (Array.isArray(obj.detail) && obj.detail.length > 0) {
    const messages = obj.detail
      .map((item) => {
        if (typeof item === "object" && item !== null && "msg" in item) {
          return String((item as { msg: unknown }).msg);
        }
        return typeof item === "string" ? item : null;
      })
      .filter(Boolean);

    if (messages.length > 0) {
      return messages.join("; ");
    }
  }

  if (typeof obj.message === "string" && obj.message.trim()) {
    return obj.message.trim();
  }

  return null;
}

/**
 * Submits a repository path to POST /api/v1/repositories/analyze.
 *
 * @param request Typed repository analysis request parameters.
 * @returns Promise resolving to the validated RepositoryAnalysisResponse.
 * @throws ApiClientError on HTTP errors, validation failure, or network disruption.
 */
export async function analyzeRepository(
  request: RepositoryAnalysisRequest
): Promise<RepositoryAnalysisResponse> {
  const validated = validateRepositoryRequest(request);

  const payload: { path: string; name?: string } = {
    path: validated.path,
  };

  if (validated.name) {
    payload.name = validated.name;
  }

  const baseUrl = getApiBaseUrl();
  const endpoint = `${baseUrl}/api/v1/repositories/analyze`;

  let response: Response;
  try {
    response = await fetch(endpoint, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify(payload),
    });
  } catch (err: unknown) {
    const originalMessage = err instanceof Error ? err.message : String(err);
    throw new ApiClientError(
      "Unable to reach backend service. Please verify the service is running and accessible.",
      0,
      originalMessage,
      "NETWORK_ERROR"
    );
  }

  if (!response.ok) {
    let errorDetail: string | null = null;
    try {
      const errJson = await response.json();
      errorDetail = parseErrorDetail(errJson);
    } catch {
      // Body was not JSON; proceed with status-based default message
    }

    if (errorDetail) {
      throw new ApiClientError(errorDetail, response.status, errorDetail);
    }

    // Default friendly status messages
    switch (response.status) {
      case 400:
        throw new ApiClientError(
          "Invalid repository request. Please verify the repository path.",
          400
        );
      case 404:
        throw new ApiClientError(
          "The specified repository path could not be found.",
          404
        );
      case 422:
        throw new ApiClientError(
          "Validation error: The provided repository path format is invalid.",
          422
        );
      case 503:
        throw new ApiClientError(
          "Database service unavailable. Please check the Neo4j database status.",
          503
        );
      case 500:
      default:
        throw new ApiClientError(
          `Analysis failed with server error (${response.status}). Please try again.`,
          response.status
        );
    }
  }

  let data: unknown;
  try {
    data = await response.json();
  } catch {
    throw new ApiClientError(
      "Received malformed response data from the analysis service.",
      response.status,
      undefined,
      "INVALID_RESPONSE"
    );
  }

  if (
    !data ||
    typeof data !== "object" ||
    !("repository_id" in data) ||
    !("summary" in data)
  ) {
    throw new ApiClientError(
      "Received incomplete response data from the analysis service: Missing required fields.",
      response.status,
      undefined,
      "INVALID_RESPONSE"
    );
  }

  return data as RepositoryAnalysisResponse;
}

/**
 * Retrieves the code knowledge graph for a repository from GET /api/v1/repositories/{id}/graph.
 *
 * @param repositoryId Unique identifier of the repository.
 * @param limit Optional maximum number of nodes to return.
 * @returns Promise resolving to the validated RepositoryGraphResponse.
 * @throws ApiClientError on HTTP errors, missing parameters, or network disruption.
 */
export async function getRepositoryGraph(
  repositoryId: string,
  limit?: number
): Promise<RepositoryGraphResponse> {
  const cleanId = repositoryId ? repositoryId.trim() : "";

  if (!cleanId) {
    throw new ApiClientError(
      "Repository identifier is required to retrieve the graph.",
      400,
      undefined,
      "INVALID_ID"
    );
  }

  const baseUrl = getApiBaseUrl();
  const queryParam = limit && limit > 0 ? `?limit=${encodeURIComponent(limit)}` : "";
  const endpoint = `${baseUrl}/api/v1/repositories/${encodeURIComponent(cleanId)}/graph${queryParam}`;

  let response: Response;
  try {
    response = await fetch(endpoint, {
      method: "GET",
      headers: {
        Accept: "application/json",
      },
    });
  } catch (err: unknown) {
    const originalMessage = err instanceof Error ? err.message : String(err);
    throw new ApiClientError(
      "Unable to reach backend service to retrieve repository graph.",
      0,
      originalMessage,
      "NETWORK_ERROR"
    );
  }

  if (!response.ok) {
    let errorDetail: string | null = null;
    try {
      const errJson = await response.json();
      errorDetail = parseErrorDetail(errJson);
    } catch {
      // Body was not JSON
    }

    if (errorDetail) {
      throw new ApiClientError(errorDetail, response.status, errorDetail);
    }

    switch (response.status) {
      case 400:
        throw new ApiClientError(
          `Invalid repository identifier: '${cleanId}'.`,
          400
        );
      case 404:
        throw new ApiClientError(
          `Repository '${cleanId}' was not found in the graph database.`,
          404
        );
      case 503:
        throw new ApiClientError(
          "Graph database service unavailable. Please check the Neo4j database status.",
          503
        );
      case 500:
      default:
        throw new ApiClientError(
          `Failed to retrieve graph with server error (${response.status}). Please try again.`,
          response.status
        );
    }
  }

  let data: unknown;
  try {
    data = await response.json();
  } catch {
    throw new ApiClientError(
      "Received malformed response data from the graph service.",
      response.status,
      undefined,
      "INVALID_RESPONSE"
    );
  }

  if (
    !data ||
    typeof data !== "object" ||
    !("repository_id" in data) ||
    !("nodes" in data) ||
    !("relationships" in data) ||
    !Array.isArray((data as Record<string, unknown>).nodes) ||
    !Array.isArray((data as Record<string, unknown>).relationships)
  ) {
    throw new ApiClientError(
      "Received incomplete graph data from the service: Missing required fields (repository_id, nodes, relationships).",
      response.status,
      undefined,
      "INVALID_RESPONSE"
    );
  }

  return data as RepositoryGraphResponse;
}

