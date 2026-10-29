/**
 * API client module for Atlas AI repository analysis and progressive graph exploration (P0-18, P0-21, P0-22, P0-23, Step 6).
 */

import type {
  RepositoryAnalysisRequest,
  RepositoryAnalysisResponse,
  RepositoryGraphResponse,
  RepositoryImpactResponse,
  GetRepositoryGraphOptions,
  GetRepositoryOverviewOptions,
  EntityChildrenResponse,
  GetEntityChildrenOptions,
  EntityNeighborsResponse,
  GetEntityNeighborsOptions,
  EntitySearchResponse,
  SearchRepositoryEntitiesOptions,
  NeighborDirection,
} from "./types.ts";

export type { GetRepositoryGraphOptions };

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
 * Safely percent-encodes each path segment of an entity ID while preserving '/' separators.
 */
export function encodePathSegments(pathStr: string): string {
  return pathStr
    .split("/")
    .map((segment) => encodeURIComponent(segment))
    .join("/");
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
 * Supports backwards-compatible invocation:
 * - getRepositoryGraph(id)
 * - getRepositoryGraph(id, limit)
 * - getRepositoryGraph(id, { limit, offset, view, signal })
 * - getRepositoryGraph(id, limit, { signal })
 *
 * @param repositoryId Unique identifier of the repository.
 * @param optionsOrLimit Optional numeric limit or options object containing limit, offset, view, signal.
 * @param maybeOptions Optional additional options if limit was passed as a number.
 * @returns Promise resolving to the validated RepositoryGraphResponse.
 * @throws ApiClientError on HTTP errors, missing parameters, network disruption, or abort.
 */
export async function getRepositoryGraph(
  repositoryId: string,
  optionsOrLimit?: number | GetRepositoryGraphOptions,
  maybeOptions?: { signal?: AbortSignal }
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

  let limit: number | undefined;
  let offset: number | undefined;
  let view: string | undefined;
  let signal: AbortSignal | undefined;

  if (typeof optionsOrLimit === "number") {
    limit = optionsOrLimit;
    signal = maybeOptions?.signal;
  } else if (typeof optionsOrLimit === "object" && optionsOrLimit !== null) {
    limit = optionsOrLimit.limit;
    offset = optionsOrLimit.offset;
    view = optionsOrLimit.view;
    signal = optionsOrLimit.signal;
  } else {
    signal = maybeOptions?.signal;
  }

  const baseUrl = getApiBaseUrl();
  const params = new URLSearchParams();

  if (view && view.trim()) {
    params.set("view", view.trim());
  }
  if (limit !== undefined && limit > 0) {
    params.set("limit", String(limit));
  }
  if (offset !== undefined && offset >= 0) {
    params.set("offset", String(offset));
  }

  const queryString = params.toString() ? `?${params.toString()}` : "";
  const endpoint = `${baseUrl}/api/v1/repositories/${encodeURIComponent(cleanId)}/graph${queryString}`;

  let response: Response;
  try {
    response = await fetch(endpoint, {
      method: "GET",
      headers: {
        Accept: "application/json",
      },
      signal,
    });
  } catch (err: unknown) {
    if (
      (err instanceof DOMException && err.name === "AbortError") ||
      (err instanceof Error && err.name === "AbortError")
    ) {
      throw new ApiClientError("Repository graph request was cancelled", 0, undefined, "ABORTED");
    }
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

/**
 * Retrieves the bounded repository overview from GET /api/v1/repositories/{id}/graph?view=overview.
 *
 * @param repositoryId Unique identifier of the repository.
 * @param options Optional parameters (limit, offset, signal).
 * @returns Promise resolving to the validated RepositoryGraphResponse with OverviewMetadata.
 */
export async function getRepositoryOverview(
  repositoryId: string,
  options?: GetRepositoryOverviewOptions
): Promise<RepositoryGraphResponse> {
  return getRepositoryGraph(repositoryId, {
    view: "overview",
    limit: options?.limit,
    offset: options?.offset,
    signal: options?.signal,
  });
}

/**
 * Retrieves direct structural children of an entity connected via CONTAINS relationships.
 * Calls GET /api/v1/repositories/{repository_id}/entities/{entity_id}/children.
 *
 * @param repositoryId Unique identifier of the repository.
 * @param entityId Unique identifier of the parent entity.
 * @param options Optional parameters (limit, offset, signal).
 * @returns Promise resolving to the validated EntityChildrenResponse.
 * @throws ApiClientError on HTTP errors, missing parameters, network disruption, or abort.
 */
export async function getEntityChildren(
  repositoryId: string,
  entityId: string,
  options?: GetEntityChildrenOptions
): Promise<EntityChildrenResponse> {
  const cleanRepoId = repositoryId ? repositoryId.trim() : "";
  const cleanEntityId = entityId ? entityId.trim() : "";

  if (!cleanRepoId) {
    throw new ApiClientError(
      "Repository identifier is required to retrieve entity children.",
      400,
      undefined,
      "INVALID_ID"
    );
  }

  if (!cleanEntityId) {
    throw new ApiClientError(
      "Entity identifier is required to retrieve entity children.",
      400,
      undefined,
      "INVALID_ID"
    );
  }

  const baseUrl = getApiBaseUrl();
  const params = new URLSearchParams();

  if (options?.limit !== undefined && options?.limit > 0) {
    params.set("limit", String(options.limit));
  }
  if (options?.offset !== undefined && options?.offset >= 0) {
    params.set("offset", String(options.offset));
  }

  const queryString = params.toString() ? `?${params.toString()}` : "";
  const endpoint = `${baseUrl}/api/v1/repositories/${encodeURIComponent(cleanRepoId)}/entities/${encodePathSegments(cleanEntityId)}/children${queryString}`;

  let response: Response;
  try {
    response = await fetch(endpoint, {
      method: "GET",
      headers: {
        Accept: "application/json",
      },
      signal: options?.signal,
    });
  } catch (err: unknown) {
    if (
      (err instanceof DOMException && err.name === "AbortError") ||
      (err instanceof Error && err.name === "AbortError")
    ) {
      throw new ApiClientError("Entity children request was cancelled", 0, undefined, "ABORTED");
    }
    const originalMessage = err instanceof Error ? err.message : String(err);
    throw new ApiClientError(
      "Unable to reach backend service to retrieve entity children.",
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
          `Invalid request for entity children: '${cleanEntityId}'.`,
          400
        );
      case 404:
        throw new ApiClientError(
          `Entity '${cleanEntityId}' or repository '${cleanRepoId}' was not found.`,
          404
        );
      case 503:
        throw new ApiClientError(
          "Graph database service unavailable during children retrieval.",
          503
        );
      case 500:
      default:
        throw new ApiClientError(
          `Failed to retrieve entity children with server error (${response.status}). Please try again.`,
          response.status
        );
    }
  }

  let data: unknown;
  try {
    data = await response.json();
  } catch {
    throw new ApiClientError(
      "Received malformed response data from the entity children service.",
      response.status,
      undefined,
      "INVALID_RESPONSE"
    );
  }

  if (
    !data ||
    typeof data !== "object" ||
    !("repository_id" in data) ||
    !("parent_id" in data) ||
    !("parent" in data) ||
    !("children" in data) ||
    !("relationships" in data) ||
    !Array.isArray((data as Record<string, unknown>).children) ||
    !Array.isArray((data as Record<string, unknown>).relationships)
  ) {
    throw new ApiClientError(
      "Received incomplete entity children data from the service: Missing required fields.",
      response.status,
      undefined,
      "INVALID_RESPONSE"
    );
  }

  return data as EntityChildrenResponse;
}

/**
 * Retrieves direct graph neighbors of an entity with explicit direction filtering.
 * Calls GET /api/v1/repositories/{repository_id}/entities/{entity_id}/neighbors.
 *
 * @param repositoryId Unique identifier of the repository.
 * @param entityId Unique identifier of the center entity.
 * @param options Optional parameters (direction, types, limit, offset, signal).
 * @returns Promise resolving to the validated EntityNeighborsResponse.
 * @throws ApiClientError on HTTP errors, missing parameters, network disruption, or abort.
 */
export async function getEntityNeighbors(
  repositoryId: string,
  entityId: string,
  options?: GetEntityNeighborsOptions
): Promise<EntityNeighborsResponse> {
  const cleanRepoId = repositoryId ? repositoryId.trim() : "";
  const cleanEntityId = entityId ? entityId.trim() : "";

  if (!cleanRepoId) {
    throw new ApiClientError(
      "Repository identifier is required to retrieve entity neighbors.",
      400,
      undefined,
      "INVALID_ID"
    );
  }

  if (!cleanEntityId) {
    throw new ApiClientError(
      "Entity identifier is required to retrieve entity neighbors.",
      400,
      undefined,
      "INVALID_ID"
    );
  }

  if (options?.direction && !["incoming", "outgoing", "both"].includes(options.direction)) {
    throw new ApiClientError(
      "Direction must be 'incoming', 'outgoing', or 'both'",
      400,
      undefined,
      "INVALID_DIRECTION"
    );
  }

  const baseUrl = getApiBaseUrl();
  const params = new URLSearchParams();

  if (options?.direction) {
    params.set("direction", options.direction);
  }
  if (options?.types && options.types.trim()) {
    params.set("types", options.types.trim());
  }
  if (options?.limit !== undefined && options?.limit > 0) {
    params.set("limit", String(options.limit));
  }
  if (options?.offset !== undefined && options?.offset >= 0) {
    params.set("offset", String(options.offset));
  }

  const queryString = params.toString() ? `?${params.toString()}` : "";
  const endpoint = `${baseUrl}/api/v1/repositories/${encodeURIComponent(cleanRepoId)}/entities/${encodePathSegments(cleanEntityId)}/neighbors${queryString}`;

  let response: Response;
  try {
    response = await fetch(endpoint, {
      method: "GET",
      headers: {
        Accept: "application/json",
      },
      signal: options?.signal,
    });
  } catch (err: unknown) {
    if (
      (err instanceof DOMException && err.name === "AbortError") ||
      (err instanceof Error && err.name === "AbortError")
    ) {
      throw new ApiClientError("Entity neighbors request was cancelled", 0, undefined, "ABORTED");
    }
    const originalMessage = err instanceof Error ? err.message : String(err);
    throw new ApiClientError(
      "Unable to reach backend service to retrieve entity neighbors.",
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
          `Invalid request for entity neighbors: '${cleanEntityId}'.`,
          400
        );
      case 404:
        throw new ApiClientError(
          `Entity '${cleanEntityId}' or repository '${cleanRepoId}' was not found.`,
          404
        );
      case 503:
        throw new ApiClientError(
          "Graph database service unavailable during neighbor retrieval.",
          503
        );
      case 500:
      default:
        throw new ApiClientError(
          `Failed to retrieve entity neighbors with server error (${response.status}). Please try again.`,
          response.status
        );
    }
  }

  let data: unknown;
  try {
    data = await response.json();
  } catch {
    throw new ApiClientError(
      "Received malformed response data from the entity neighbors service.",
      response.status,
      undefined,
      "INVALID_RESPONSE"
    );
  }

  if (
    !data ||
    typeof data !== "object" ||
    !("repository_id" in data) ||
    !("entity_id" in data) ||
    !("center" in data) ||
    !("neighbors" in data) ||
    !("relationships" in data) ||
    !Array.isArray((data as Record<string, unknown>).neighbors) ||
    !Array.isArray((data as Record<string, unknown>).relationships)
  ) {
    throw new ApiClientError(
      "Received incomplete entity neighbors data from the service: Missing required fields.",
      response.status,
      undefined,
      "INVALID_RESPONSE"
    );
  }

  return data as EntityNeighborsResponse;
}

/**
 * Searches code entities within a repository by case-insensitive text query.
 * Calls GET /api/v1/repositories/{repository_id}/entities/search.
 *
 * @param repositoryId Unique identifier of the repository.
 * @param query Search query string.
 * @param options Optional parameters (type, limit, offset, signal).
 * @returns Promise resolving to the validated EntitySearchResponse.
 * @throws ApiClientError on HTTP errors, missing parameters, network disruption, or abort.
 */
export async function searchRepositoryEntities(
  repositoryId: string,
  query: string,
  options?: SearchRepositoryEntitiesOptions
): Promise<EntitySearchResponse> {
  const cleanRepoId = repositoryId ? repositoryId.trim() : "";
  const cleanQuery = query ? query.trim() : "";

  if (!cleanRepoId) {
    throw new ApiClientError(
      "Repository identifier is required to search entities.",
      400,
      undefined,
      "INVALID_ID"
    );
  }

  if (!cleanQuery) {
    throw new ApiClientError(
      "Search query string is required.",
      400,
      undefined,
      "INVALID_QUERY"
    );
  }

  const baseUrl = getApiBaseUrl();
  const params = new URLSearchParams();

  params.set("q", cleanQuery);

  if (options?.type && options.type.trim()) {
    params.set("type", options.type.trim());
  }
  if (options?.limit !== undefined && options?.limit > 0) {
    params.set("limit", String(options.limit));
  }
  if (options?.offset !== undefined && options?.offset >= 0) {
    params.set("offset", String(options.offset));
  }

  const endpoint = `${baseUrl}/api/v1/repositories/${encodeURIComponent(cleanRepoId)}/entities/search?${params.toString()}`;

  let response: Response;
  try {
    response = await fetch(endpoint, {
      method: "GET",
      headers: {
        Accept: "application/json",
      },
      signal: options?.signal,
    });
  } catch (err: unknown) {
    if (
      (err instanceof DOMException && err.name === "AbortError") ||
      (err instanceof Error && err.name === "AbortError")
    ) {
      throw new ApiClientError("Entity search request was cancelled", 0, undefined, "ABORTED");
    }
    const originalMessage = err instanceof Error ? err.message : String(err);
    throw new ApiClientError(
      "Unable to reach backend service to search entities.",
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
          `Invalid search parameters for repository '${cleanRepoId}'.`,
          400
        );
      case 404:
        throw new ApiClientError(
          `Repository '${cleanRepoId}' was not found in the graph database.`,
          404
        );
      case 503:
        throw new ApiClientError(
          "Graph database service unavailable during entity search.",
          503
        );
      case 500:
      default:
        throw new ApiClientError(
          `Failed to search entities with server error (${response.status}). Please try again.`,
          response.status
        );
    }
  }

  let data: unknown;
  try {
    data = await response.json();
  } catch {
    throw new ApiClientError(
      "Received malformed response data from the entity search service.",
      response.status,
      undefined,
      "INVALID_RESPONSE"
    );
  }

  if (
    !data ||
    typeof data !== "object" ||
    !("repository_id" in data) ||
    !("query" in data)
  ) {
    throw new ApiClientError(
      "Received incomplete entity search data from the service: Missing required fields.",
      response.status,
      undefined,
      "INVALID_RESPONSE"
    );
  }

  const rawObj = data as Record<string, unknown>;

  // Normalize entities / results aliases: prefer entities, fall back to results, or vice-versa
  const entitiesList = Array.isArray(rawObj.entities)
    ? rawObj.entities
    : Array.isArray(rawObj.results)
    ? rawObj.results
    : [];

  const resultsList = Array.isArray(rawObj.results)
    ? rawObj.results
    : entitiesList;

  const normalized: EntitySearchResponse = {
    repository_id: String(rawObj.repository_id),
    query: String(rawObj.query),
    entities: entitiesList as EntitySearchResponse["entities"],
    results: resultsList as EntitySearchResponse["results"],
    total_matches: typeof rawObj.total_matches === "number" ? rawObj.total_matches : entitiesList.length,
    returned_matches: typeof rawObj.returned_matches === "number" ? rawObj.returned_matches : entitiesList.length,
    has_more: Boolean(rawObj.has_more),
    truncated: Boolean(rawObj.truncated),
    offset: typeof rawObj.offset === "number" ? rawObj.offset : 0,
    limit: typeof rawObj.limit === "number" ? rawObj.limit : entitiesList.length,
    type_filter: typeof rawObj.type_filter === "string" ? rawObj.type_filter : null,
  };

  return normalized;
}

/**
 * Retrieves the direct and transitive impact analysis for a repository entity.
 * Calls GET /api/v1/repositories/{repository_id}/impact/{entity_id}.
 *
 * @param repositoryId Unique identifier of the repository.
 * @param entityId Unique identifier of the target entity.
 * @param options Optional parameters (maxDepth, signal for cancellation).
 * @returns Promise resolving to the validated RepositoryImpactResponse.
 * @throws ApiClientError on HTTP errors, missing parameters, or network disruption.
 */
export async function getRepositoryImpact(
  repositoryId: string,
  entityId: string,
  options?: { maxDepth?: number; signal?: AbortSignal }
): Promise<RepositoryImpactResponse> {
  const cleanRepoId = repositoryId ? repositoryId.trim() : "";
  const cleanEntityId = entityId ? entityId.trim() : "";

  if (!cleanRepoId) {
    throw new ApiClientError(
      "Repository identifier is required to analyze entity impact.",
      400,
      undefined,
      "INVALID_ID"
    );
  }

  if (!cleanEntityId) {
    throw new ApiClientError(
      "Entity identifier is required to analyze entity impact.",
      400,
      undefined,
      "INVALID_ID"
    );
  }

  const baseUrl = getApiBaseUrl();
  const maxDepth = options?.maxDepth;
  const queryParam = maxDepth && maxDepth >= 1 ? `?max_depth=${encodeURIComponent(maxDepth)}` : "";
  const endpoint = `${baseUrl}/api/v1/repositories/${encodeURIComponent(cleanRepoId)}/impact/${encodePathSegments(cleanEntityId)}${queryParam}`;

  let response: Response;
  try {
    response = await fetch(endpoint, {
      method: "GET",
      headers: {
        Accept: "application/json",
      },
      signal: options?.signal,
    });
  } catch (err: unknown) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new ApiClientError("Impact analysis request was cancelled", 0, undefined, "ABORTED");
    }
    const originalMessage = err instanceof Error ? err.message : String(err);
    throw new ApiClientError(
      "Unable to reach backend service to retrieve impact analysis.",
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
          `Invalid impact request parameters for entity '${cleanEntityId}'.`,
          400
        );
      case 404:
        throw new ApiClientError(
          `Entity '${cleanEntityId}' or repository '${cleanRepoId}' was not found.`,
          404
        );
      case 503:
        throw new ApiClientError(
          "Graph database service unavailable during impact analysis.",
          503
        );
      case 500:
      default:
        throw new ApiClientError(
          `Impact analysis failed with server error (${response.status}). Please try again.`,
          response.status
        );
    }
  }

  let data: unknown;
  try {
    data = await response.json();
  } catch {
    throw new ApiClientError(
      "Received malformed response data from the impact analysis service.",
      response.status,
      undefined,
      "INVALID_RESPONSE"
    );
  }

  if (
    !data ||
    typeof data !== "object" ||
    !("entity" in data) ||
    !("direct_dependents" in data) ||
    !("transitive_dependents" in data) ||
    !("affected_files" in data) ||
    !("max_depth" in data) ||
    !Array.isArray((data as Record<string, unknown>).direct_dependents) ||
    !Array.isArray((data as Record<string, unknown>).transitive_dependents) ||
    !Array.isArray((data as Record<string, unknown>).affected_files)
  ) {
    throw new ApiClientError(
      "Received incomplete impact data from the service: Missing required fields.",
      response.status,
      undefined,
      "INVALID_RESPONSE"
    );
  }

  return data as RepositoryImpactResponse;
}
