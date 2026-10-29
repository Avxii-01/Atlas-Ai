# Atlas AI --- P0 API

## 1. API Goal

The P0 API provides the minimum backend contract required to analyze a
repository, retrieve its graph, and perform deterministic impact
analysis.

Base path:

``` text
/api/v1
```

## 2. Analyze Repository

### Request

``` http
POST /api/v1/repositories/analyze
```

Purpose: - accept repository input; - scan and parse supported files; -
build/update the Neo4j graph.

Illustrative response:

``` json
{
  "repository_id": "repo_001",
  "status": "completed",
  "summary": {
    "files": 24,
    "classes": 18,
    "functions": 73,
    "relationships": 126
  }
}
```

The exact upload/input mechanism may be refined during implementation.

## 3. Retrieve Graph

``` http
GET /api/v1/repositories/{repository_id}/graph
```

Purpose: - return graph nodes and relationships needed by the frontend.

Illustrative response:

``` json
{
  "repository_id": "repo_001",
  "nodes": [],
  "relationships": []
}
```

The implementation should support filtering or limiting the graph if the
full graph is too large for a useful UI response.

## 4. Impact Analysis

``` http
GET /api/v1/repositories/{repository_id}/impact/{entity_id}
```

Purpose: - identify direct and transitive dependents/affected entities.

Illustrative response:

``` json
{
  "entity": {
    "id": "fn_123",
    "name": "process_payment"
  },
  "direct_dependents": [],
  "transitive_dependents": [],
  "affected_files": [],
  "max_depth": 3
}
```

## 5. Entity Search

``` http
GET /api/v1/repositories/{repository_id}/entities/search?q={query}&type={type}&limit={limit}&offset={offset}
```

Purpose:
- search code entities across a repository by case-insensitive text match;
- match against verified persisted properties (`name`, `qualified_name`, `path`, `file_path`, `imported_name`, `id`);
- deterministic relevance ranking (exact match, prefix match, substring match, ID tie-breaker);
- bounded pagination without reconstructing the full graph.

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

## 6. Dependency Direction

The API must distinguish:

### Dependencies

"What does this entity depend on?"

``` text
A → B
A depends on B
```

### Dependents

"What depends on this entity?"

``` text
A → B
B is depended on by A
```

Impact analysis primarily uses the dependent direction when answering:

> If this entity changes or is removed, what may be affected?

## 7. API Design Rules

-   Use explicit request/response schemas.
-   Validate repository and entity identifiers.
-   Return deterministic errors.
-   Do not expose raw database implementation details unnecessarily.
-   Keep API models separate from Neo4j persistence models where
    practical.
-   Version the API under `/api/v1`.
-   Document non-obvious fields.

## 8. Future API Extensions

Not part of P0: - semantic search; - embeddings; - `/ask`; - GraphRAG; -
risk scoring; - authentication; - repository history analysis.
