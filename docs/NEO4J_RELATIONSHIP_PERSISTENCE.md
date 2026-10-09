# Atlas AI — Neo4j Relationship Persistence (P0-14)

## 1. Overview and Architectural Boundaries

This document defines the Neo4j relationship persistence component (`app.db.relationship_persister`) for Atlas AI P0.

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
Neo4j Entity Persister (P0-13)◄─── (persists UCM entities as Neo4j nodes)
        │
        ▼
Neo4j Relationship Persister (P0-14) ◄─── [Persists semantic directed edges]
        │
        ▼
Graph Retrieval / Impact API (P0-15+)
```

### Boundary Constraints
- **Scope**: Persists resolved relationships (`CONTAINS`, `IMPORTS`, `CALLS`, `INHERITS`) into Neo4j as typed directed edges.
- **Preconditions**: Assumes entity nodes have been persisted via P0-13 or exist in Neo4j.
- **Safety Invariant**: Never manufactures missing endpoint nodes. If an endpoint does not exist, the relationship is skipped.

---

## 2. Supported Relationship Types & Edge Patterns

Conforms strictly to `docs/GRAPH_SCHEMA.md` and `docs/NEO4J_SCHEMA.md`:

| Relationship Type | Source Node Label | Target Node Label | Semantics & Direction |
| :--- | :--- | :--- | :--- |
| **`CONTAINS`** | `Repository` | `File` | File membership in repository |
| **`CONTAINS`** | `File` | `Class`, `Function` | Top-level declarations in file |
| **`CONTAINS`** | `Class` | `Method`, `Class` | Class members & nested classes |
| **`CONTAINS`** | `Function` | `Function` | Nested local functions |
| **`IMPORTS`** | `File` | `Module` | Source file imports repository module |
| **`CALLS`** | `Function`, `Method` | `Function`, `Method` | Verified call invocation |
| **`INHERITS`** | `Class` | `Class` | Class inheritance hierarchy |

---

## 3. Idempotent Write Strategy and Endpoint Validation

Relationships are persisted using parameterized Cypher `UNWIND` batches with `MATCH` on endpoints and `MERGE` on edges:

```cypher
UNWIND $batch AS rel
MATCH (src:<src_label> {id: rel.source_id})
WHERE src.repo_id = $repo_id
MATCH (tgt:<tgt_label> {id: rel.target_id})
WHERE tgt.repo_id = $repo_id
MERGE (src)-[r:<RELATIONSHIP_TYPE>]->(tgt)
SET r += rel.properties
RETURN count(r) AS persisted_count
```

*(For `Repository` nodes, `WHERE src.id = $repo_id` is used instead of `src.repo_id = $repo_id`)*

### Core Guarantees:
1. **No Missing Node Fabrication**: Because `MATCH` is used on `src` and `tgt`, if either node does not exist in the database, the query matches 0 rows and creates **no** edge and **no** fake nodes.
2. **Duplicate Prevention**: `MERGE (src)-[r:TYPE]->(tgt)` matches existing edges when the pipeline is run repeatedly, preventing duplicate relationships.
3. **Evidence Preservation**: `SET r += rel.properties` preserves source range evidence (`start_line`, `start_column`, `end_line`, `end_column`, `start_byte`, `end_byte`) and metadata (e.g. `alias`).
4. **Strict Repository Isolation**:
   - Python-level check: Asserts `repo_id_from_entity_id(src_id) == repo_id` and `repo_id_from_entity_id(tgt_id) == repo_id`.
   - Cypher-level check: Asserts `src.repo_id = $repo_id` and `tgt.repo_id = $repo_id` directly in the graph query.
   - Cross-repository edges are strictly impossible.

---

## 4. Transaction and Session Lifecycle

- **Atomic Transactions**: All relationship batches for a repository snapshot execute inside a single transaction (`with session.begin_transaction() as tx: ... tx.commit()`).
- **Session Lifecycle**: Caller-provided sessions are never closed; driver-managed sessions are closed safely via context managers.
- **Observable Results**: Returns `RelationshipPersistenceResult` tracking counts of persisted and skipped edges by relationship type.

---

## 5. Answers to AI Coding Rules (Rule 2)

1. **What?**
   - Idempotent, evidence-preserving persistence of resolved code relationships into Neo4j.
2. **Why?**
   - Complete the static analysis graph model required for dependency traversal and impact blast radius calculation.
3. **How?**
   - Parameterized batch `MATCH ... MERGE` queries grouped by `(rel_type, src_label, tgt_label)`.
4. **Inputs?**
   - `UnifiedCodeModel` or list of `Relationship` records with `repo_id`.
5. **Outputs?**
   - `RelationshipPersistenceResult` with counts of persisted and skipped relationships.
6. **Dependencies?**
   - `neo4j` Python driver, standard library `dataclasses`. Zero new dependencies.
7. **Trade-offs?**
   - Grouped queries by endpoint label pair to leverage Neo4j's per-label uniqueness constraint indexes for O(1) matching.
8. **Known Limitations?**
   - Does not perform graph traversal or impact analysis (covered in subsequent milestones).
