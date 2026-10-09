# Atlas AI — Neo4j Graph Retrieval (P0-15)

## 1. Overview and Architectural Boundaries

This document defines the Neo4j graph retrieval layer (`app.db.graph_retriever`) for Atlas AI P0.

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
        ▼
Neo4j Graph Retrieval (P0-15) ◄─── [Reconstructs typed UCM from Neo4j graph store]
        │
        ▼
Dependency Traversal / Impact API (P0-16+)
```

### Boundary Constraints
- **Scope**: Queries persisted nodes and relationships from Neo4j and converts them back into typed Unified Code Model (`UnifiedCodeModel`, `Repository`, `File`, `Module`, `Class`, `Function`, `Method`, `Import`, `Relationship`) structures.
- **Read-Only Invariant**: Performs strictly non-mutating queries (`MATCH ... RETURN`). Contains zero `CREATE`, `MERGE`, `SET`, `DELETE`, `REMOVE`, or `DROP` statements.
- **Isolation Guarantee**: All repository-level queries enforce `WHERE repo_id = $repo_id` (and `r.id = $repo_id` for repositories). Cross-repository data cannot be returned.

---

## 2. Supported Retrieval Capabilities

Conforms directly to `docs/GRAPH_SCHEMA.md` and `docs/UNIFIED_CODE_MODEL.md`:

### 2.1 Repository Entity Retrieval
- `get_repository(repo_id)`: Fetches a `Repository` entity by its deterministic ID (e.g. `repo::atlas_fixture`). Returns `None` if not found.

### 2.2 Entity Retrieval by ID
- `get_entity_by_id(entity_id, repo_id=None)`: Resolves any of the 7 supported entity types by its stable ID, optionally enforcing repository scope.
  - Automatically derives the expected node label from the ID discriminator (`::file::`, `::module::`, `::class::`, `::function::`, `::method::`, `::import::`, or `repo::`).

### 2.3 Entity Collection Retrieval
- `get_files(repo_id)`: Returns all `File` entities for the repository.
- `get_modules(repo_id)`: Returns all `Module` entities for the repository.
- `get_classes(repo_id)`: Returns all `Class` entities for the repository.
- `get_functions(repo_id)`: Returns all `Function` entities for the repository.
- `get_methods(repo_id)`: Returns all `Method` entities for the repository.
- `get_imports(repo_id)`: Returns all `Import` entities for the repository.

### 2.4 Relationship Retrieval
- `get_relationships(repo_id, rel_type=None, source_id=None, target_id=None)`: Retrieves persisted relationship edges, optionally filtered by type (`CONTAINS`, `IMPORTS`, `CALLS`, `INHERITS`) or source/target entity IDs.
- Fully reconstructs `SourceRange` location evidence (`start_line`, `start_column`, `end_line`, `end_column`, `start_byte`, `end_byte`) and metadata (e.g. `alias`, `call_expr`).

### 2.5 Full Repository Graph Reconstruction
- `get_repository_graph(repo_id)`: Reconstructs a complete `UnifiedCodeModel` containing the repository root entity, all 6 entity collections, and all relationship edges. Returns `None` if the repository node does not exist in Neo4j.

---

## 3. Safe Missing-Record & Repository Isolation Semantics

1. **Non-Existent Records**:
   - Querying a non-existent repository returns `None` rather than raising an exception.
   - Querying a non-existent entity returns `None`.
   - Querying relationships or collections for an empty repository returns an empty list `[]`.
2. **Repository Isolation**:
   - Every Cypher query requires a `$repo_id` parameter and filters nodes via `WHERE repo_id = $repo_id`.
   - Relationships assert that both `src` and `tgt` belong to `$repo_id`, ensuring cross-repository edges cannot be returned even if corrupt data existed in the database.
3. **Session Lifecycle**:
   - Caller-owned sessions passed to retrieval functions are never closed.
   - Driver-managed sessions acquired internally are closed safely via context managers.

---

## 4. Answers to AI Coding Rules (Rule 2)

1. **What?**
   - High-fidelity graph retrieval that reads Neo4j nodes and edges and reconstructs them into typed UCM models.
2. **Why?**
   - Downstream components (dependency traversal, impact analysis, REST APIs, and React Flow visualization) require access to the code graph without coupling directly to Cypher queries.
3. **How?**
   - Parameterized `MATCH ... RETURN` Cypher queries with factory deserializers mapping Neo4j records into UCM dataclasses.
4. **Inputs?**
   - `repo_id`, `entity_id`, optional filters, optional `Driver` or `Session`.
5. **Outputs?**
   - `UnifiedCodeModel`, individual UCM entity models, or `list[Relationship]`.
6. **Dependencies?**
   - `neo4j` Python driver, existing `app.ucm` dataclasses. Zero new dependencies.
7. **Trade-offs?**
   - Used label-specific `MATCH` queries when `entity_id` label is known to leverage Neo4j's uniqueness constraint indexes for O(1) lookups.
8. **Known Limitations?**
   - Does not perform recursive dependency graph traversal or blast-radius calculation; those belong to P0-16 and P0-17.
