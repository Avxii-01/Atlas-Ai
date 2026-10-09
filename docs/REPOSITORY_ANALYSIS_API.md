# Atlas AI — Repository Analysis API (P0-18)

## 1. Overview and Endpoint Specification

This document describes the design, implementation, and operational contract of the repository analysis endpoint for Atlas AI P0:

```http
POST /api/v1/repositories/analyze
```

The endpoint triggers and coordinates the full Atlas AI static analysis pipeline, persists the resulting entities and relationships into Neo4j graph storage, and returns an analysis summary adhering strictly to `docs/API.md`.

---

## 2. API Contract

### 2.1 Request Schema

`POST /api/v1/repositories/analyze` accepts JSON with the following schema:

```json
{
  "repository_path": "d:/path/to/repo",
  "name": "optional_name",
  "source": "optional_source"
}
```

#### Fields

| Field | Type | Required | Description |
|---|---|---|---|
| `repository_path` | string | Yes | Absolute or workspace-relative path to a local repository directory. Aliased also as `path` or `repo_path`. |
| `name` | string | No | Optional display name for the repository. Defaults to the directory name of `repository_path`. Aliased also as `repo_name`. |
| `source` | string | No | Optional source tag for the repository (e.g. `local`, `github`). Defaults to `"local"`. Aliased also as `repo_source`. |

### 2.2 Response Schema

Upon successful analysis and persistence, the endpoint returns HTTP `200 OK` with:

```json
{
  "repository_id": "repo::atlas_fixture",
  "status": "completed",
  "summary": {
    "files": 7,
    "classes": 7,
    "functions": 11,
    "relationships": 58,
    "modules": 7
  }
}
```

#### Fields

| Field | Type | Description |
|---|---|---|
| `repository_id` | string | Deterministic repository identifier generated using UCM identity rules (`repo::<sanitized_name>`). |
| `status` | string | Always `"completed"` upon success. |
| `summary` | object | Metrics summary of the analyzed codebase. |
| `summary.files` | integer | Number of Python files scanned and ingested. |
| `summary.classes` | integer | Number of classes extracted. |
| `summary.functions` | integer | Number of functions and methods extracted. |
| `summary.relationships` | integer | Number of resolved edges persisted (`CONTAINS`, `IMPORTS`, `CALLS`, `INHERITS`). |
| `summary.modules` | integer | (Optional) Number of modules extracted. |

---

## 3. Analysis Pipeline Orchestration

The pipeline is coordinated in `backend/app/services/repository_service.py`:

```text
HTTP POST /api/v1/repositories/analyze
         │
         ▼
1. Validate & Normalize Repository Path
   (Check existence, directory status, block root/system paths)
         │
         ▼
2. Initialize Neo4j Schema (cached/idempotent)
   (app.db.schema.init_schema)
         │
         ▼
3. Orchestrate Static Analysis
   (app.resolver.resolve_repository)
   ├── Scanner (app.scanner)
   ├── Tree-sitter Parser (app.parser)
   ├── Python AST Extractor (app.extractor)
   └── Symbol Index & Relationship Resolver (app.resolver)
         │
         ▼
4. Persist Entities FIRST
   (app.db.entity_persister.persist_entities)
   [Repository, File, Module, Class, Function, Method, Import]
         │
         ▼
5. Persist Relationships SECOND
   (app.db.relationship_persister.persist_relationships)
   [CONTAINS, IMPORTS, CALLS, INHERITS]
         │
         ▼
6. Return Summary Response (HTTP 200)
```

---

## 4. Repository Path Validation & Security

The endpoint operates on local repository directories. To prevent unauthorized filesystem exploration or operating system directory scanning:

1. **Existence Check**: Rejects empty strings or non-existent paths with HTTP `400 Bad Request` (`"Repository path does not exist"`).
2. **Directory Check**: Rejects paths pointing to files instead of directories with HTTP `400 Bad Request` (`"Repository path must be a directory"`).
3. **Root Traversal Guard**: Rejects scanning filesystem roots (e.g. `C:\`, `/`) with HTTP `400 Bad Request` (`"Cannot scan filesystem root directory"`).
4. **System Directory Block**: Blocks operating system system directories (such as `Windows`, `System32`, `/etc`, `/usr`, `/proc`, `/sys`) with HTTP `400 Bad Request` (`"Scanning system directory is not permitted"`).
5. **Path Normalization**: Resolves paths to absolute, normalized paths before running scanner routines.
6. **Information Privacy**: Internal error details and filesystem tracebacks are masked from client responses.

---

## 5. Persistence Ordering and Idempotency

- **Ordering Guarantee**: Entities are persisted strictly before relationships. Because Neo4j relationships require existing start and end nodes to match (`MATCH (source {id: ...}), (target {id: ...}) CREATE/MERGE (source)-[r]->(target)`), persisting relationships before entities would result in unlinked or dropped edges.
- **Idempotency**: Using existing `MERGE`-based persisters (`persist_entities` and `persist_relationships`), re-analyzing an existing repository updates node properties and relationships deterministically without creating duplicate nodes or edges.

---

## 6. Error Handling Contract

| Condition | HTTP Status | Response Payload | Description |
|---|---|---|---|
| Missing/Invalid Schema Payload | 422 Unprocessable Entity | Standard FastAPI validation details | Malformed JSON or missing required fields. |
| Non-existent or invalid repo path | 400 Bad Request | `{"detail": "..."}` | Path does not exist, is a file, or is a forbidden root/system directory. |
| Database Unavailable | 503 Service Unavailable | `{"detail": "Database service unavailable"}` | Neo4j connection failure or timeout. |
| Entity Persistence Failure | 500 Internal Server Error | `{"detail": "Failed to persist repository entities"}` | Database failure during entity creation. |
| Relationship Persistence Failure | 500 Internal Server Error | `{"detail": "Failed to persist repository relationships"}` | Database failure during edge creation. |
| Analysis Pipeline Crash | 500 Internal Server Error | `{"detail": "Static analysis pipeline failed"}` | Unhandled crash in parser, extractor, or resolver. |

---

## 7. Known Limitations and Tradeoffs

1. **Transaction Atomicity across Stages**: Neo4j transactions are committed per persistence stage (`persist_entities` followed by `persist_relationships`). If entity persistence succeeds but relationship persistence encounters a fatal database error, entities will remain in the database while an HTTP 500 error is returned to the client. Re-running analysis for the repository is fully idempotent and safely completes the graph.
2. **Recoverable Syntax Errors**: The Tree-sitter parser logs warnings and continues on syntax error nodes. Incomplete or malformed Python files will yield partial ASTs rather than aborting the entire repository analysis.
