# Atlas AI — Repository Graph API (P0-19)

## 1. Overview and Endpoint Specification

This document describes the design, implementation, and operational contract of the repository graph retrieval endpoint for Atlas AI P0:

```http
GET /api/v1/repositories/{repository_id}/graph
```

The endpoint retrieves persisted code entities and relationships for a repository from Neo4j via the graph retrieval layer (`app.db.graph_retriever`), serializes them into deterministically ordered nodes and edges conforming to `docs/API.md`, and prepares the data for downstream consumption and future React Flow integration.

---

## 2. API Contract

### 2.1 Request

```http
GET /api/v1/repositories/{repository_id}/graph
```

#### Path Parameters

| Parameter | Type | Required | Description |
|---|---|---|---|
| `repository_id` | string | Yes | Stable repository identifier (e.g. `repo::atlas_fixture`). Validated against empty/whitespace strings, traversal sequences, and length limits. |

#### Query Parameters

| Parameter | Type | Required | Description |
|---|---|---|---|
| `limit` | integer | No | Optional maximum number of nodes to return. When specified, only relationships whose endpoints are within the limited node set are returned. |

### 2.2 Response Schema

Upon successful retrieval, returns HTTP `200 OK` with:

```json
{
  "repository_id": "repo::atlas_fixture",
  "nodes": [
    {
      "id": "repo::atlas_fixture",
      "label": "Repository",
      "name": "atlas_fixture",
      "type": "Repository",
      "display_name": "atlas_fixture",
      "properties": {
        "name": "atlas_fixture",
        "source": "tests/fixtures/atlas_fixture",
        "created_at": null
      }
    },
    {
      "id": "repo::atlas_fixture::class::models.ItemModel",
      "label": "Class",
      "name": "ItemModel",
      "type": "Class",
      "display_name": "ItemModel",
      "properties": {
        "repo_id": "repo::atlas_fixture",
        "name": "ItemModel",
        "qualified_name": "models.ItemModel",
        "file_path": "models.py",
        "language": "python",
        "start_line": 6,
        "end_line": 20,
        "start_byte": 120,
        "end_byte": 450,
        "docstring": null
      }
    }
  ],
  "relationships": [
    {
      "id": "repo::atlas_fixture->CONTAINS->repo::atlas_fixture::file::app.py",
      "source": "repo::atlas_fixture",
      "target": "repo::atlas_fixture::file::app.py",
      "type": "CONTAINS",
      "source_id": "repo::atlas_fixture",
      "target_id": "repo::atlas_fixture::file::app.py",
      "rel_type": "CONTAINS",
      "properties": {},
      "metadata": {}
    },
    {
      "id": "repo::atlas_fixture::class::models.ItemModel->INHERITS->repo::atlas_fixture::class::base.BaseEntity",
      "source": "repo::atlas_fixture::class::models.ItemModel",
      "target": "repo::atlas_fixture::class::base.BaseEntity",
      "type": "INHERITS",
      "source_id": "repo::atlas_fixture::class::models.ItemModel",
      "target_id": "repo::atlas_fixture::class::base.BaseEntity",
      "rel_type": "INHERITS",
      "properties": {},
      "metadata": {}
    }
  ]
}
```

---

## 3. Serialization Rules and Invariants

### 3.1 Node Serialization and Limit Semantics
- **Stable IDs**: Preserves canonical UCM deterministic entity IDs (e.g. `{repo_id}::class::{qualified_name}`).
- **Labels & Types**: `label` and `type` contain the entity type name (`Repository`, `File`, `Module`, `Class`, `Function`, `Method`, `Import`).
- **Names**: `name` and `display_name` contain the human-readable entity identifier.
- **Properties**: Contains the raw node attributes stored in Neo4j (`file_path`, line numbers, byte offsets, `qualified_name`, `language`, docstring).
- **Deterministic Ordering & Root Handling**: Nodes are sorted with the `Repository` root node placed strictly first (`nodes[0]`), followed by code entities sorted deterministically by stable `id`.
- **`limit` Semantics**: When `limit=N` is specified ($N \ge 1$), the first $N$ deterministically ordered nodes are retained (guaranteeing the Repository root node is preserved), and only relationships whose endpoints are BOTH within the retained $N$ nodes are returned. Relationships referring to omitted nodes are excluded, ensuring the returned subgraph is strictly self-contained.

### 3.2 Relationship Serialization
- **Stable Edge IDs**: Edge IDs are deterministically generated as:
  `{source_id}->{rel_type}->{target_id}` (appended with `:L{line}` when location evidence exists, with collision counters `#1`, `#2` for exact duplicates).
- **Endpoint Direction**: Preserves original relationship direction (`source` is source entity, `target` is target entity). Never reverses direction.
- **Endpoint Presence Invariant**: Every returned edge strictly connects nodes present in the returned `nodes` list. Any edge referring to a node omitted (e.g. through `limit` filtering or unpersisted external symbols) is excluded.
- **Location & Metadata**: Source evidence (`start_line`, `start_column`, `end_line`, `end_column`, `start_byte`, `end_byte`) and scalar metadata (`call_expr`, `alias`) are preserved in `properties` and `metadata`.
- **Deterministic Ordering**: Relationships are deterministically sorted by `(source, type, target, id)`.

---

## 4. Repository Validation and Error Handling

| Scenario | HTTP Status | Detail / Behavior |
|---|---|---|
| Malformed ID (empty, pure whitespace) | 400 Bad Request | `"Repository ID cannot be empty"` |
| Malformed ID (path traversal, null bytes) | 400 Bad Request | `"Invalid repository ID format"` |
| Overly long repository ID (> 255 chars) | 400 Bad Request | `"Repository ID exceeds maximum permitted length"` |
| Repository not found in Neo4j | 404 Not Found | `"Repository '{repository_id}' not found"` |
| Repository exists but has 0 files/edges | 200 OK | Returns repository node with empty `relationships` list |
| Neo4j database unavailable | 503 Service Unavailable | `"Database service unavailable"` (connection secrets/URIs masked) |
| Internal retrieval / query failure | 500 Internal Server Error | `"Failed to retrieve repository graph"` (internal traces hidden) |

---

## 5. Read-Only Invariant

The endpoint is strictly read-only:
- Queries Neo4j using parameterized `MATCH ... RETURN` statements through `GraphRetriever`.
- Contains zero `CREATE`, `MERGE`, `SET`, `DELETE`, `REMOVE`, or `DROP` statements.
- Does not invoke `persist_entities`, `persist_relationships`, or `init_schema`.

---

## 6. Answers to AI Coding Rules (Rule 2)

1. **What?**
   - Implemented `GET /api/v1/repositories/{repository_id}/graph` endpoint retrieving and serializing persisted repository knowledge graphs from Neo4j into deterministic nodes and edges.
2. **Why?**
   - Provide the API layer required for repository graph visualization (React Flow) and downstream exploration without coupling consumers directly to Cypher queries.
3. **How?**
   - Invokes `GraphRetriever.get_repository_graph(repository_id)` to reconstruct the typed `UnifiedCodeModel`, serializes it into `NodeModel` and `RelationshipModel` collections, validates endpoint presence, and sorts deterministically.
4. **Inputs?**
   - `repository_id` (path string), optional `limit` (integer query param).
5. **Outputs?**
   - `RepositoryGraphResponse` matching `docs/API.md` with `repository_id`, `nodes`, `relationships`.
6. **Dependencies?**
   - `FastAPI`, `Pydantic`, `GraphRetriever`, `UnifiedCodeModel`. Zero new external dependencies.
7. **Trade-offs?**
   - Filtered relationships whose endpoints are not in the node list to enforce graph self-containment for client graph visualizers.
8. **Known Limitations?**
   - Graph retrieval loads the repository graph stored in Neo4j; huge multi-million node repositories will benefit from pagination/subgraph filtering in future extensions.
