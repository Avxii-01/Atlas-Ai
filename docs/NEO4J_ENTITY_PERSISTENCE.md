# Atlas AI — Neo4j Entity Persistence (P0-13)

## 1. Overview and Architectural Boundaries

This document defines the Neo4j entity persistence component (`app.db.entity_persister`) for Atlas AI P0.

### Architectural Pipeline & Component Boundaries

```text
Tree-sitter Parser (P0-07)
        │ (concrete syntax tree & token ranges)
        ▼
Unified Code Model (P0-08) ◄─── (normalized entities & explicit relationships)
        │
        ▼
Relationship Resolver (P0-10) ◄─── (resolves cross-file calls, imports, inheritance)
        │
        ▼
Neo4j Graph Schema (P0-12)    ◄─── (uniqueness constraints & repository indexes)
        │
        ▼
Neo4j Entity Persister (P0-13)◄─── [Persists UCM entities as Neo4j nodes]
        │
        ▼
Neo4j Relationship Persister (P0-14+) ◄─── (persists semantic relationship edges)
```

### Boundary Constraints
- **Scope**: Persists UCM entities (`Repository`, `File`, `Module`, `Class`, `Function`, `Method`, `Import`) as Neo4j nodes.
- **Isolation**: Does **not** persist relationship edges (`CONTAINS`, `IMPORTS`, `CALLS`, `INHERITS` - deferred to P0-14).
- **Integrity**: Enforces idempotent `MERGE` writes using stable UCM identifiers (`id`), ensuring safe re-ingestion, no duplicate nodes, and repository isolation.

---

## 2. Supported Entity Types and Property Mapping

Conforms to `docs/GRAPH_SCHEMA.md`, `docs/UNIFIED_CODE_MODEL.md`, and `docs/NEO4J_SCHEMA.md`:

| Entity Type | Target Node Label | Persisted Properties | Handling of Optional Values |
| :--- | :--- | :--- | :--- |
| **`Repository`** | `Repository` | `id`, `name`, `source`, `created_at` | `created_at` omitted if `None` |
| **`File`** | `File` | `id`, `repo_id`, `path`, `language`, `start_line`, `end_line`, `start_byte`, `end_byte` | Non-nullable primitives |
| **`Module`** | `Module` | `id`, `repo_id`, `name`, `qualified_name`, `file_path` | Non-nullable primitives; references file via `file_path` |
| **`Class`** | `Class` | `id`, `repo_id`, `name`, `qualified_name`, `file_path`, `language`, `start_line`, `end_line`, `start_byte`, `end_byte`, `docstring` | `docstring` omitted if `None` |
| **`Function`** | `Function` | `id`, `repo_id`, `name`, `qualified_name`, `file_path`, `language`, `start_line`, `end_line`, `start_byte`, `end_byte`, `docstring` | `docstring` omitted if `None` |
| **`Method`** | `Method` | `id`, `repo_id`, `name`, `qualified_name`, `file_path`, `language`, `start_line`, `end_line`, `start_byte`, `end_byte`, `docstring` | `docstring` omitted if `None` |
| **`Import`** | `Import` | `id`, `repo_id`, `file_path`, `module_name`, `imported_name`, `alias`, `start_line`, `end_line`, `start_byte`, `end_byte` | `alias` omitted if `None` |

---

## 3. Idempotent Write Strategy and Re-Ingestion

To guarantee safe re-ingestion without duplicate nodes, entity writes use parameterized Cypher `UNWIND` and `MERGE`:

```cypher
UNWIND $batch AS props
MERGE (n:<Label> {id: props.id})
SET n += props
```

### Invariants:
1. **Uniqueness Constraint Guarantee**: `id` is guaranteed unique per node label by the P0-12 schema constraints (`CREATE CONSTRAINT ... FOR (n:<Label>) REQUIRE n.id IS UNIQUE`).
2. **Safe Property Merging**: `SET n += props` merges the latest properties. Optional properties with `None` values are filtered out prior to query execution, preventing existing database fields from being overwritten with null.
3. **Repository Isolation**: All non-repository entity identifiers embed the `repo_id` (e.g. `repo::repo_a::class::models.User` vs `repo::repo_b::class::models.User`), preventing cross-repository entity collisions.

---

## 4. Transaction and Session Lifecycle Management

- **Transaction Boundaries**: Bulk entity persistence runs inside a single database transaction (`with session.begin_transaction() as tx: ... tx.commit()`), ensuring all entities of a repository snapshot are committed atomically.
- **Session Lifecycle**:
  - If a `Session` is passed by the caller, the persister uses it and **does not close it**.
  - If no `Session` is passed, the persister acquires a session from the driver context manager and ensures it is safely closed upon exit.
  - The application-level driver is never closed by the persister.
- **Error Handling**: Database and transaction failures are caught, logged without credential leakage, and raised as `Neo4jPersistenceError` (a subclass of `Neo4jConnectionError`).

---

## 5. Answers to AI Coding Rules (Rule 2)

1. **What?**
   - High-performance, idempotent persistence of UCM code entities into Neo4j nodes.
2. **Why?**
   - Translate static analysis results into a queryable graph database representation required for dependency and impact analysis.
3. **How?**
   - Parameterized batch `MERGE` queries grouped by entity label, executed within explicit transaction boundaries.
4. **Inputs?**
   - `UnifiedCodeModel` instance, optional `Driver` or `Session`.
5. **Outputs?**
   - `EntityPersistenceResult` containing repository ID and entity counts per label.
6. **Dependencies?**
   - Neo4j Python driver (`neo4j`), standard library `dataclasses`. Zero additional dependencies.
7. **Trade-offs?**
   - Omitted `None` properties from update dictionaries to prevent overwriting existing data with missing fields.
8. **Known Limitations?**
   - Does not persist relationship edges; relationship persistence is handled in P0-14.
