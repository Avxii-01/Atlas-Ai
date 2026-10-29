# Atlas AI — P0 API

## 1. API Goal

The P0 API provides the minimum backend contract required to analyze a
repository, retrieve its graph (full or bounded progressive exploration),
and perform deterministic impact analysis.

Base path:

``` text
/api/v1
```

## 2. Analyze Repository

### Request

``` http
POST /api/v1/repositories/analyze
```

Purpose:
- accept repository input filesystem path;
- scan and parse supported source files;
- build/update the Neo4j knowledge graph.

Illustrative response:

``` json
{
  "repository_id": "repo_001",
  "status": "completed",
  "summary": {
    "files": 24,
    "classes": 18,
    "functions": 73,
    "relationships": 126,
    "modules": 5,
    "methods": 32,
    "imports": 40
  }
}
```

## 3. Retrieve Graph

### 3.1 Legacy Full Graph Retrieval

``` http
GET /api/v1/repositories/{repository_id}/graph
```

Query parameters:
- `limit` (integer, optional): Maximum number of nodes to return. When omitted, returns the full repository graph.

Illustrative response:

``` json
{
  "repository_id": "repo_001",
  "nodes": [
    {
      "id": "repo_001",
      "label": "Repository",
      "name": "repo_001",
      "type": "Repository",
      "display_name": "repo_001",
      "properties": {}
    }
  ],
  "relationships": [],
  "metadata": null
}
```

### 3.2 Bounded Repository Overview

``` http
GET /api/v1/repositories/{repository_id}/graph?view=overview&limit={limit}&offset={offset}
```

Purpose:
- returns top-level repository structure (Repository node and File nodes connected by CONTAINS);
- supports bounded pagination without loading internal AST entities;
- includes pagination metadata to indicate whether additional files remain.

Query parameters:
- `view` (string, required for overview): Must be `overview`.
- `limit` (integer, optional, default 50, max 200): Maximum number of File nodes to return.
- `offset` (integer, optional, default 0, min 0): Pagination offset for File nodes.

Illustrative response:

``` json
{
  "repository_id": "repo_001",
  "nodes": [
    {
      "id": "repo_001",
      "label": "Repository",
      "name": "repo_001",
      "type": "Repository",
      "display_name": "repo_001",
      "properties": {}
    },
    {
      "id": "repo_001::file::main.py",
      "label": "File",
      "name": "main.py",
      "type": "File",
      "display_name": "main.py",
      "properties": {
        "repo_id": "repo_001",
        "path": "main.py",
        "language": "python"
      }
    }
  ],
  "relationships": [
    {
      "id": "rel:contains:repo_001->repo_001::file::main.py",
      "source": "repo_001",
      "target": "repo_001::file::main.py",
      "type": "CONTAINS"
    }
  ],
  "metadata": {
    "view": "overview",
    "total_files": 24,
    "returned_files": 1,
    "has_more": true,
    "truncated": true,
    "offset": 0,
    "limit": 1
  }
}
```

## 4. Entity Children (Progressive Exploration)

``` http
GET /api/v1/repositories/{repository_id}/entities/{entity_id}/children?limit={limit}&offset={offset}
```

Purpose:
- retrieves direct structural child entities connected via outgoing `CONTAINS` relationships;
- enables progressive node expansion in the UI without loading the full repository;
- deterministic ordering and pagination.

Path parameters:
- `repository_id` (string, required): Repository identifier.
- `entity_id` (string, required, path parameter): Parent entity ID. Supports hierarchical and file path separators (e.g. `repo::demo::file::services/auth.py`).

Query parameters:
- `limit` (integer, optional, default 50, min 1, max 200): Maximum children to return.
- `offset` (integer, optional, default 0, min 0): Children pagination offset.

Illustrative response:

``` json
{
  "repository_id": "repo_001",
  "parent_id": "repo_001::file::main.py",
  "parent": {
    "id": "repo_001::file::main.py",
    "label": "File",
    "name": "main.py",
    "type": "File",
    "display_name": "main.py",
    "properties": { "path": "main.py" }
  },
  "children": [
    {
      "id": "repo_001::class::App",
      "label": "Class",
      "name": "App",
      "type": "Class",
      "display_name": "App",
      "properties": {
        "file_path": "main.py",
        "qualified_name": "main.App"
      }
    }
  ],
  "relationships": [
    {
      "id": "rel:contains:main->App",
      "source": "repo_001::file::main.py",
      "target": "repo_001::class::App",
      "type": "CONTAINS"
    }
  ],
  "total_children": 1,
  "returned_children": 1,
  "has_more": false,
  "truncated": false,
  "offset": 0,
  "limit": 50
}
```

## 5. Entity Neighbors

``` http
GET /api/v1/repositories/{repository_id}/entities/{entity_id}/neighbors?direction={direction}&types={types}&limit={limit}&offset={offset}
```

Purpose:
- retrieves direct graph neighbors and incident relationship edges for a target entity;
- supports directional filtering (`incoming`, `outgoing`, `both`);
- supports optional filtering by relationship types (`CONTAINS`, `IMPORTS`, `CALLS`, `INHERITS`).

Path parameters:
- `repository_id` (string, required): Repository identifier.
- `entity_id` (string, required, path parameter): Center entity ID.

Query parameters:
- `direction` (string, optional, default `both`): Relationship direction (`incoming`, `outgoing`, or `both`).
- `types` (string, optional): Comma-separated list of relationship types to include (e.g. `CALLS,IMPORTS`).
- `limit` (integer, optional, default 50, min 1, max 200): Maximum relationships to return.
- `offset` (integer, optional, default 0, min 0): Relationships pagination offset.

Illustrative response:

``` json
{
  "repository_id": "repo_001",
  "entity_id": "repo_001::function::run",
  "center": {
    "id": "repo_001::function::run",
    "label": "Function",
    "name": "run",
    "type": "Function",
    "display_name": "run",
    "properties": {}
  },
  "neighbors": [
    {
      "id": "repo_001::function::helper",
      "label": "Function",
      "name": "helper",
      "type": "Function",
      "display_name": "helper",
      "properties": {}
    }
  ],
  "relationships": [
    {
      "id": "rel:calls:run->helper",
      "source": "repo_001::function::run",
      "target": "repo_001::function::helper",
      "type": "CALLS"
    }
  ],
  "total_relationships": 1,
  "returned_relationships": 1,
  "total_neighbors": 1,
  "returned_neighbors": 1,
  "direction": "outgoing",
  "has_more": false,
  "truncated": false,
  "offset": 0,
  "limit": 50
}
```

## 6. Entity Search

``` http
GET /api/v1/repositories/{repository_id}/entities/search?q={query}&type={type}&limit={limit}&offset={offset}
```

Purpose:
- search code entities across a single repository by case-insensitive text match;
- match against verified persisted properties (`name`, `qualified_name`, `path`, `file_path`, `imported_name`, `id`);
- deterministic relevance ranking (exact match, prefix match, substring match, ID tie-breaker);
- bounded pagination without reconstructing the full graph;
- emits both `entities` (canonical) and `results` (backward-compatibility alias).

Query parameters:
- `q` (string, required, length 1–100): Search query string.
- `type` (string, optional): Entity label filter (`Repository`, `File`, `Module`, `Class`, `Function`, `Method`, `Import`).
- `limit` (integer, optional, default 50, min 1, max 200): Maximum entities to return.
- `offset` (integer, optional, default 0, min 0): Pagination offset.

Illustrative response:

``` json
{
  "repository_id": "repo_001",
  "query": "process_payment",
  "entities": [
    {
      "id": "repo_001:func::payments.py:process_payment",
      "label": "Function",
      "name": "process_payment",
      "type": "Function",
      "display_name": "process_payment",
      "properties": {
        "repo_id": "repo_001",
        "name": "process_payment",
        "qualified_name": "payments.process_payment",
        "file_path": "payments.py",
        "language": "python",
        "start_line": 10,
        "end_line": 30
      }
    }
  ],
  "results": [
    {
      "id": "repo_001:func::payments.py:process_payment",
      "label": "Function",
      "name": "process_payment",
      "type": "Function",
      "display_name": "process_payment",
      "properties": {
        "repo_id": "repo_001",
        "name": "process_payment",
        "qualified_name": "payments.process_payment",
        "file_path": "payments.py",
        "language": "python",
        "start_line": 10,
        "end_line": 30
      }
    }
  ],
  "total_matches": 1,
  "returned_matches": 1,
  "has_more": false,
  "truncated": false,
  "offset": 0,
  "limit": 50,
  "type_filter": null
}
```

## 7. Impact Analysis

``` http
GET /api/v1/repositories/{repository_id}/impact/{entity_id}?max_depth={max_depth}
```

Purpose:
- identify direct and transitive dependents/affected entities in the reverse call/import/inherit graph.

Query parameters:
- `max_depth` (integer, optional, default 3, min 1): Maximum traversal depth.

Illustrative response:

``` json
{
  "entity": {
    "id": "fn_123",
    "name": "process_payment",
    "label": "Function",
    "type": "Function",
    "file_path": "payments.py",
    "properties": {}
  },
  "direct_dependents": [],
  "transitive_dependents": [],
  "affected_files": [],
  "max_depth": 3,
  "repository_id": "repo_001"
}
```

## 8. Dependency Direction

The API strictly distinguishes:

### Dependencies

"What does this entity depend on?"

``` text
A → B
A depends on B (outgoing edge from A to B)
```

### Dependents

"What depends on this entity?"

``` text
A → B
B is depended on by A (incoming edge into B from A)
```

Impact analysis primarily uses the dependent direction when answering:

> If this entity changes or is removed, what may be affected?

## 9. API Design Rules

-   Use explicit request/response schemas validated via Pydantic / TypeScript types.
-   Validate repository and entity identifiers; reject empty or whitespace IDs with HTTP 400.
-   Return deterministic HTTP status codes (200 OK, 400 Bad Request, 404 Not Found, 422 Unprocessable Entity, 503 Service Unavailable).
-   Deterministic ordering across all paginated endpoints via secondary and tertiary tie-breakers (`id ASC`).
-   Do not expose raw database implementation details unnecessarily.
-   Keep API models separate from Neo4j persistence models where practical.
-   Version all endpoints under `/api/v1`.
-   Document non-obvious fields.

## 10. Future API Extensions

Not part of P0:
- semantic search;
- embeddings;
- `/ask`;
- GraphRAG;
- risk scoring;
- authentication;
- repository history analysis.
