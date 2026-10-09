# Atlas AI — Graph Traversal Layer (P0-16)

## 1. Overview and Architectural Boundaries

This document defines the repository-scoped graph traversal layer (`app.graph.traversal`) for Atlas AI P0.

### Architectural Pipeline & Component Boundaries

```text
Tree-sitter Parser (P0-07)
        │
Unified Code Model (P0-08)
        │
Relationship Resolver (P0-10)
        │
Neo4j Graph Persister (P0-13, P0-14)
        │
Neo4j Graph Retrieval (P0-15)
        │
        ▼
Graph Traversal Layer (P0-16) ◄─── [Bounded, cycle-safe dependency & dependent traversal]
        │
        ▼
Impact Analysis / Blast Radius (P0-17)
        │
        ▼
API Endpoints & Frontend (P0-18+)
```

### Boundary Constraints
- **Scope**: Executes bounded, cycle-safe graph traversals in Neo4j to retrieve direct and transitive dependencies and dependents.
- **Read-Only Invariant**: All queries are strictly non-mutating (`MATCH ... RETURN`). Contains zero `CREATE`, `MERGE`, `SET`, `DELETE`, `REMOVE`, or `DROP` statements.
- **Repository Isolation**: Cypher-level enforcement ensures traversals never step across repository boundaries.
- **Out of Scope**: Blast-radius scoring, impact weighting, and change-risk analysis belong strictly to P0-17; FastAPI endpoints belong to P0-18+.

---

## 2. Public Traversal Interface

The traversal layer is located at `backend/app/graph/traversal.py` and exported through `backend/app/graph/__init__.py`.

### 2.1 Core Classes and Models

#### `TraversalNode`
Represents an individual entity reached during graph traversal:
- `entity_id: str`: Unique deterministic entity identifier in Neo4j.
- `depth: int`: Shortest path distance (hop count) from the start entity.
- `labels: tuple[str, ...]`: Node labels from Neo4j (e.g. `('Function',)`).
- `properties: dict[str, Any]`: Raw node properties.
- `path_relationship_types: tuple[str, ...]`: Relationship types traversed on the shortest path.
- `entity: Any | None`: Reconstructed typed UCM entity model (`Function`, `Class`, etc.) if available.
- `primary_label: str | None`: Convenience property returning the primary node label.

#### `TraversalResult`
Encapsulates the complete result of a repository-scoped traversal:
- `start_entity_id: str`: Starting entity identifier.
- `repository_id: str`: Repository ID scope.
- `direction: TraversalDirection`: `DEPENDENCIES` (outgoing) or `DEPENDENTS` (incoming).
- `max_depth: int`: Maximum traversal depth limit applied.
- `relationship_types: tuple[str, ...]`: Relationship types included in traversal.
- `nodes: tuple[TraversalNode, ...]`: Deterministically sorted tuple of reached nodes.
- `start_entity_found: bool`: Whether the start entity existed in the repository graph.
- `entity_ids -> list[str]`: List of reached entity IDs in deterministic traversal order.
- `by_depth -> dict[int, list[TraversalNode]]`: Nodes grouped by hop distance.
- `get_node(entity_id: str) -> TraversalNode | None`: Lookup helper by entity ID.
- Supports `len(result)`, `iter(result)`, and indexing `result[i]`.

#### `GraphTraversal`
The main traversal engine:
```python
class GraphTraversal:
    def __init__(self, driver: Driver | None = None) -> None: ...

    def get_dependencies(
        self,
        entity_id: str,
        repo_id: str | None = None,
        max_depth: int = 1,
        relationship_types: Collection[RelationshipType | str] | None = None,
        session: Session | None = None,
    ) -> TraversalResult: ...

    def get_direct_dependencies(self, ...) -> TraversalResult: ...
    def get_transitive_dependencies(self, ..., max_depth: int = 10) -> TraversalResult: ...

    def get_dependents(
        self,
        entity_id: str,
        repo_id: str | None = None,
        max_depth: int = 1,
        relationship_types: Collection[RelationshipType | str] | None = None,
        session: Session | None = None,
    ) -> TraversalResult: ...

    def get_direct_dependents(self, ...) -> TraversalResult: ...
    def get_transitive_dependents(self, ..., max_depth: int = 10) -> TraversalResult: ...
```

#### Functional Convenience Entry Points
- `get_dependencies(...)`
- `get_direct_dependencies(...)`
- `get_transitive_dependencies(...)`
- `get_dependents(...)`
- `get_direct_dependents(...)`
- `get_transitive_dependents(...)`

---

## 3. Traversal Semantics and Relationship Policy

### 3.1 Dependencies vs Dependents

- **Dependencies (Outgoing)**:
  Traverse outgoing dependency edges (`(start)-[r]->(target)`):
  $$\text{start} \xrightarrow{\text{CALLS}} B \xrightarrow{\text{CALLS}} C$$
  - Direct dependencies of `start` (depth 1): $\{ B \}$
  - Transitive dependencies of `start` (depth 2): $\{ B, C \}$

- **Dependents (Incoming / Reverse)**:
  Traverse incoming dependency edges (`(start)<-[r]-(target)`):
  $$\text{target} \xrightarrow{\text{CALLS}} B \xrightarrow{\text{CALLS}} \text{start}$$
  - Direct dependents of `start` (depth 1): $\{ B \}$
  - Transitive dependents of `start` (depth 2): $\{ B, \text{target} \}$

### 3.2 Default Relationship Types and Filtering

- **Default Dependency Types**: `('CALLS', 'IMPORTS', 'INHERITS')`.
- **Structural `CONTAINS` Policy**: Syntactic containment (`Repository -> File -> Class -> Method`) is structural ownership and is **excluded by default**. It is only traversed if explicitly requested in `relationship_types`.
- **Relationship Type Validation**: Any requested relationship types are validated against the fixed internal allowlist `{'CALLS', 'IMPORTS', 'INHERITS', 'CONTAINS'}`. Unrecognized types raise `ValueError`. Raw user strings are never directly interpolated into Cypher.

---

## 4. Depth Bounds, Cycles, and Deduplication

1. **Depth Limits**:
   - Depth `1`: Returns immediate 1-hop neighbors only.
   - Depth `2`: Includes entities reachable within 1 or 2 hops.
   - Validation: Depths $\le 0$, non-integers, floats, and booleans raise `ValueError`.
   - Default: `max_depth = 1` for direct methods; `max_depth = 10` for transitive methods.
2. **Cycle Safety & Self-Loops**:
   - Cypher variable-length path matching avoids traversing duplicate edges in a path.
   - `AND target.id <> $entity_id` guarantees that the starting entity is never returned as its own dependency or dependent, even in cyclic graphs (`A -> B -> A`) or self-loops (`A -> A`).
3. **Deduplication & Shortest Path Distance**:
   - Multiple paths reaching the same target entity (e.g. diamond shapes) are aggregated using `head(collect(path))` ordered by `length(path) ASC`.
   - Each target entity is returned exactly once with its minimum hop distance (`depth`).
4. **Deterministic Sorting**:
   - Results are deterministically ordered by `depth ASC, entity_id ASC` in Cypher, ensuring repeatable output independent of database iteration order.

---

## 5. Repository Isolation

Repository isolation is enforced at the database level:
1. **Start Entity Scoping**: Verified using `((start:Repository AND start.id = $repo_id) OR start.repo_id = $repo_id)`.
2. **Path Node Isolation**: Cypher evaluates `ALL(node IN nodes(path) WHERE (node:Repository AND node.id = $repo_id) OR node.repo_id = $repo_id)`. Cross-repository edges are pruned during path expansion, not after.
3. **Target Isolation**: `((target:Repository AND target.id = $repo_id) OR target.repo_id = $repo_id)`.
4. **Missing Entities and Mismatches**: Nonexistent entities and repository mismatches safely return an empty `TraversalResult` with `nodes = ()` and `start_entity_found = False`.

---

## 6. Session Lifecycle & Error Handling

- **Session Ownership**:
  - Caller-provided sessions (`session=...`) are left open.
  - Driver-managed sessions acquired by the traversal layer are closed in `finally`.
- **Error Wrapping & Credential Masking**:
  - Database exceptions are wrapped in `GraphTraversalError(Neo4jConnectionError)`.
  - Sensitive connection credentials (e.g. URIs with passwords) are masked in exception messages and log output.
  - Database errors are never swallowed to return false empty results.

---

## 7. Consumption Examples for Downstream P0-17 Impact Analysis

Downstream impact analysis (P0-17) can consume traversal results directly:

### Example: Computing Blast Radius of a Changed Function

```python
from app.graph.traversal import GraphTraversal

traversal = GraphTraversal()

# Find all callers and transitive dependents affected by modifying a function
result = traversal.get_transitive_dependents(
    entity_id="repo::atlas_fixture::function::utils.format_identifier",
    max_depth=5,
)

# Total blast-radius count
blast_radius = len(result)  # e.g. 3 (create_tagged_item, process_item_workflow, main)

# Impact rings grouped by distance
ring_1 = [n.entity_id for n in result.by_depth.get(1, [])]  # Direct impact
ring_2 = [n.entity_id for n in result.by_depth.get(2, [])]  # Secondary impact
ring_3 = [n.entity_id for n in result.by_depth.get(3, [])]  # Tertiary impact

# Access typed UCM entities
for node in result:
    print(f"Affected entity: {node.entity_id} at depth {node.depth}")
    if node.entity:
        print(f"Entity type: {type(node.entity).__name__}, location: {node.entity.file_path}")
```

---

## 8. Answers to AI Coding Rules (Rule 2)

1. **What?**
   - High-performance, repository-scoped graph traversal engine for direct and transitive dependencies (`CALLS`, `IMPORTS`, `INHERITS`) and dependents in Neo4j.
2. **Why?**
   - To support impact analysis (P0-17), blast-radius calculations, and architecture dependency queries without loading the entire graph into application memory.
3. **How?**
   - Parameterized, read-only Cypher path queries with shortest-path deduplication, cycle suppression, and strict repository filtering on all path nodes.
4. **Inputs?**
   - `entity_id`, optional `repo_id`, `max_depth`, optional `relationship_types`, optional `Session`/`Driver`.
5. **Outputs?**
   - Typed `TraversalResult` containing ordered `TraversalNode` instances with depth, relationship path types, properties, and typed UCM entity models.
6. **Dependencies?**
   - `neo4j` Python driver, existing `app.db` and `app.ucm` modules. Zero new third-party dependencies.
7. **Trade-offs?**
   - Cypher shortest-path aggregation `WITH target, head(collect(path))` deduplicates nodes at the query level rather than transferring all redundant path combinations to Python.
   - Separate `app.graph` package preserves modularity and avoids circular imports with `app.db`.
8. **Known Limitations?**
   - Traversal does not compute risk scores or blast-radius weights; these are reserved for P0-17.
