# Atlas AI — Neo4j P0 Graph Schema (P0-12)

## 1. Overview and Architectural Boundaries

This document defines the Neo4j graph schema, uniqueness constraints, repository-scoped property indexes, and schema initialization logic for Atlas AI P0.

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
Neo4j Graph Schema (P0-12)    ◄─── [Enforces constraints, indexes, and graph typing]
        │
        ▼
Neo4j Graph Persister (P0-13+)◄─── (persists nodes & relationships to graph store)
```

### Boundary Constraints
- **Scope**: Defines node labels, property schemas, relationship patterns, uniqueness constraints, property indexes, and idempotent initialization.
- **Isolation**: Does **not** perform entity or relationship persistence (P0-13), graph traversal, impact analysis, or REST API endpoints.
- **Integrity**: Schema initialization is strictly **non-destructive** (contains no `DELETE`, `DROP`, or `REMOVE` operations).

---

## 2. Supported Node Labels & Property Contracts

Conforms directly to `docs/GRAPH_SCHEMA.md` and `docs/UNIFIED_CODE_MODEL.md`:

| Node Label | Required Properties | Optional Properties | Deterministic ID Format |
| :--- | :--- | :--- | :--- |
| **`Repository`** | `id`, `name`, `source` | `created_at` | `repo::{clean_name}` |
| **`File`** | `id`, `repo_id`, `path`, `language`, `start_line`, `end_line` | `start_byte`, `end_byte` | `{repo_id}::file::{normalized_path}` |
| **`Module`** | `id`, `repo_id`, `name`, `qualified_name`, `file_path` | — | `{repo_id}::module::{qualified_name}` |
| **`Class`** | `id`, `repo_id`, `name`, `qualified_name`, `file_path`, `language`, `start_line`, `end_line` | `start_byte`, `end_byte`, `docstring` | `{repo_id}::class::{qualified_name}` |
| **`Function`** | `id`, `repo_id`, `name`, `qualified_name`, `file_path`, `language`, `start_line`, `end_line` | `start_byte`, `end_byte`, `docstring` | `{repo_id}::function::{qualified_name}` |
| **`Method`** | `id`, `repo_id`, `name`, `qualified_name`, `file_path`, `language`, `start_line`, `end_line` | `start_byte`, `end_byte`, `docstring` | `{repo_id}::method::{qualified_name}` |
| **`Import`** | `id`, `repo_id`, `file_path`, `module_name`, `imported_name`, `start_line`, `end_line` | `alias`, `start_byte`, `end_byte` | `{repo_id}::import::{path}::L{line}::{name}` |

### Structural Rules on File Association
- `Module` and `Import` nodes link to their containing file via the **`file_path`** property.
- To prevent circular and ambiguous traversal paths, `Module` and `Import` are **not** connected by `CONTAINS` edges.

---

## 3. Supported Relationship Types & Edge Patterns

The schema defines 4 typed relationship edges:

| Relationship Type | Source Node Label(s) | Target Node Label(s) | Semantic Meaning |
| :--- | :--- | :--- | :--- |
| **`CONTAINS`** | `Repository` | `File` | File containment in repository |
| **`CONTAINS`** | `File` | `Class`, `Function` | Module-level declarations in file |
| **`CONTAINS`** | `Class` | `Method`, `Class` | Class member and nested class declarations |
| **`CONTAINS`** | `Function` | `Function` | Nested local function definitions |
| **`IMPORTS`** | `File` | `Module` | Source file imports a repository module |
| **`CALLS`** | `Function`, `Method` | `Function`, `Method` | Direct verified call invocation |
| **`INHERITS`** | `Class` | `Class` | Class inheritance hierarchy |

---

## 4. Uniqueness Constraints

Entity identifiers (`id`) are deterministic, pure functions of repository scope, type, and qualified names. Uniqueness is enforced at the database level for all 7 node labels using standard Neo4j 5+ idempotent Cypher:

```cypher
CREATE CONSTRAINT constraint_repository_id IF NOT EXISTS FOR (n:Repository) REQUIRE n.id IS UNIQUE
CREATE CONSTRAINT constraint_file_id IF NOT EXISTS FOR (n:File) REQUIRE n.id IS UNIQUE
CREATE CONSTRAINT constraint_module_id IF NOT EXISTS FOR (n:Module) REQUIRE n.id IS UNIQUE
CREATE CONSTRAINT constraint_class_id IF NOT EXISTS FOR (n:Class) REQUIRE n.id IS UNIQUE
CREATE CONSTRAINT constraint_function_id IF NOT EXISTS FOR (n:Function) REQUIRE n.id IS UNIQUE
CREATE CONSTRAINT constraint_method_id IF NOT EXISTS FOR (n:Method) REQUIRE n.id IS UNIQUE
CREATE CONSTRAINT constraint_import_id IF NOT EXISTS FOR (n:Import) REQUIRE n.id IS UNIQUE
```

*Note: In Neo4j 5+, a uniqueness constraint on `n.id` automatically backs property lookups on `id` with an internal unique B-Tree/Range index. No redundant indexes on `id` are created.*

---

## 5. Repository-Scoped Property Indexes

To ensure fast repository isolation, traversal, reindexing, and deletion (`WHERE n.repo_id = $repo_id`), dedicated property indexes are established:

```cypher
CREATE INDEX index_repository_name IF NOT EXISTS FOR (n:Repository) ON (n.name)
CREATE INDEX index_file_repo_id IF NOT EXISTS FOR (n:File) ON (n.repo_id)
CREATE INDEX index_module_repo_id IF NOT EXISTS FOR (n:Module) ON (n.repo_id)
CREATE INDEX index_class_repo_id IF NOT EXISTS FOR (n:Class) ON (n.repo_id)
CREATE INDEX index_function_repo_id IF NOT EXISTS FOR (n:Function) ON (n.repo_id)
CREATE INDEX index_method_repo_id IF NOT EXISTS FOR (n:Method) ON (n.repo_id)
CREATE INDEX index_import_repo_id IF NOT EXISTS FOR (n:Import) ON (n.repo_id)
```

---

## 6. Programmatic API and Schema Initialization

The schema module lives under `app.db.schema`:

```python
from app.db import init_schema

# Initialize using the application-level driver singleton
statements = init_schema()

# Or initialize using a custom driver or active session
statements = init_schema(driver=custom_driver)
statements = init_schema(session=active_session)
```

### Safety and Idempotency Guarantees
1. **Idempotent**: All DDL statements use `IF NOT EXISTS`. Safe to execute at startup or during repeated pipeline executions.
2. **Non-Destructive**: Contains no `DELETE`, `DROP`, `DETACH`, or `MATCH` queries. Existing graph nodes and edges are completely preserved.
3. **No Credential Leakage**: Exceptions during driver acquisition or Cypher execution are wrapped in `Neo4jSchemaError` (subclass of `Neo4jConnectionError`), masking sensitive connection URIs and authentication tokens.

---

## 7. Design Decisions & Trade-Offs

### Answers to AI Coding Rules (Rule 2)
1. **What?**
   - Formal schema contracts, uniqueness constraints, and repository-scoped property indexes for Neo4j.
2. **Why?**
   - Prevent entity ID collisions in Neo4j, ensure fast repository-filtered queries (`repo_id`), and establish schema invariants before entity persistence.
3. **How?**
   - Pure Cypher DDL executed via Neo4j Python driver `session.run()` with `IF NOT EXISTS`.
4. **Inputs?**
   - Optional `Driver` or `Session` instance. If omitted, uses the application driver singleton (`app.db.get_driver()`).
5. **Outputs?**
   - List of executed idempotent Cypher statements (`list[str]`).
6. **Dependencies?**
   - Uses existing `neo4j` Python driver and standard library `dataclasses` / `enum`. Zero additional third-party dependencies.
7. **Trade-offs?**
   - Opted for single-property `repo_id` indexes rather than composite `(repo_id, qualified_name)` indexes because `id` already embeds `repo_id` and qualified name, avoiding index overhead.
8. **Known Limitations?**
   - Does not persist entities or relationships; persistence is encapsulated in P0-13.
