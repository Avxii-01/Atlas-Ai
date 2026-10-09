# Atlas AI — Impact Analysis Engine (P0-17)

## 1. Overview and Architectural Boundaries

This document defines the impact analysis engine (`app.graph.impact`) for Atlas AI P0.

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
Graph Traversal Layer (P0-16) ◄─── (bounded dependent graph traversal)
        │
        ▼
Impact Analysis Engine (P0-17) ◄─── [Direct/transitive blast radius & affected files]
        │
        ▼
Impact Analysis REST API (P0-20)
        │
        ▼
Impact Visualization / UI (P0-23)
```

### Boundary Constraints
- **Scope**: Reuses the P0-16 `GraphTraversal` layer to evaluate the blast radius of code modifications. Identifies directly impacted entities, transitively impacted entities, and affected source files.
- **Traversal Reuse**: Does **not** implement secondary Cypher traversal queries or reload graphs into Python. Reuses `GraphTraversal.get_dependents` in reverse dependency direction.
- **Read-Only Invariant**: Non-mutating analysis. Never issues `CREATE`, `MERGE`, `SET`, `DELETE`, `REMOVE`, or `DROP` statements.
- **Explicit Exclusions**: Does **not** compute numerical risk scores, severity heuristics, blast-radius weights, or LLM-generated explanations. These are reserved for later milestones.

---

## 2. Public API and Usage Examples

The impact engine is located at `backend/app/graph/impact.py` and exported through `backend/app/graph/__init__.py`.

### 2.1 Public Classes and Data Structures

#### `AffectedFile`
Represents a source file containing one or more impacted entities:
- `file_id: str`: Deterministic identifier (`{repo_id}::file::{path}`).
- `path: str`: Normalized repository-relative POSIX file path.
- Supports rich string comparisons: `file == "services.py"`, `file == "repo::r::file::services.py"`, and `str(file) -> path`.

#### `ImpactAnalysisResult`
Encapsulates the complete impact analysis result:
- `repository_id: str`: Analyzed repository scope.
- `target_entity_id: str`: Identifier of the modified target entity.
- `max_depth: int`: Maximum traversal depth limit applied.
- `directly_impacted_entities: tuple[TraversalNode, ...]`: Reached dependents at hop depth `1`.
- `impacted_entities: tuple[TraversalNode, ...]`: All reached dependents (depths `1` through `max_depth`).
- `affected_files: tuple[AffectedFile, ...]`: Deduplicated source files, sorted deterministically by path.
- `target_entity_found: bool`: Whether the target entity existed in the repository graph.
- `blast_radius: int`: Total count of impacted entities (`len(res)`).
- `directly_impacted_count: int`: Count of directly impacted entities.
- `directly_impacted_entity_ids: list[str]`: IDs of entities at depth `1`.
- `impacted_entity_ids: list[str]`: IDs of all impacted entities in deterministic traversal order.
- `affected_file_count: int`: Count of affected files.
- `affected_file_ids: list[str]`: List of deterministic file IDs.
- `affected_file_paths: list[str]`: List of affected file relative paths.
- `by_depth: dict[int, list[TraversalNode]]`: Grouping of impacted entities by hop distance.
- `get_entity(entity_id: str) -> TraversalNode | None`: Lookup helper by entity ID.
- Protocol support: `len(res)`, `iter(res)`, `res[index]`.

#### `ImpactAnalyzer`
The impact analysis coordinator:
```python
from app.graph.impact import ImpactAnalyzer

analyzer = ImpactAnalyzer()

result = analyzer.analyze_impact(
    target_entity_id="repo::atlas_fixture::function::utils.format_identifier",
    max_depth=5,
)
```

#### Functional Convenience Helper
```python
from app.graph import analyze_impact

result = analyze_impact("repo::atlas_fixture::function::utils.format_identifier")
```

---

## 3. Direct versus Transitive Impact Semantics

Impact analysis follows the **reverse dependency direction** (dependents):

$$\text{Caller} \xrightarrow{\text{CALLS}} \text{Target}$$

If $\text{Target}$ is modified, $\text{Caller}$ is impacted.

1. **Direct Impact**:
   - Entities that directly call, import, or inherit from the target entity.
   - Hop distance is strictly `depth == 1`.
2. **Transitive Impact**:
   - All entities reachable through chains of dependency relationships up to `max_depth`.
   - Includes entities at depths $1, 2, \dots, \text{max\_depth}$.
3. **Target Exclusion**:
   - The target entity itself is never returned as an impacted entity (`target.id <> $entity_id`).

---

## 4. Affected-File Resolution Rules

Affected files are derived from the impacted entities:

1. **Entity Metadata Extraction**:
   - For `File` entities: extracts the `path` property.
   - For `Module`, `Class`, `Function`, `Method`, and `Import` entities: extracts the `file_path` property or `node.entity.file_path`.
2. **Normalization & ID Generation**:
   - Relative paths are normalized using POSIX forward slashes via `normalize_path`.
   - Stable file IDs are computed as `build_file_id(repo_id, norm_path)`.
3. **Deduplication**:
   - Multiple impacted entities residing in the same file (e.g. methods and functions in `services.py`) produce exactly **one** entry in `affected_files`.
4. **Deterministic Ordering**:
   - Affected files are sorted deterministically by `path ASC`.
5. **Missing File Ownership Policy**:
   - If an entity lacks file ownership information (e.g. a `Repository` node or an unassociated entity), it is safely skipped without fabricating speculative associations.
   - An imported file is **not** marked affected unless a code entity inside it is an impacted dependent.

---

## 5. Depth Bounds, Repository Isolation, and Cycle Safety

1. **Depth Limits**:
   - Depth `1` yields direct dependents only.
   - Depth `2` includes secondary callers/inheritors up to 2 hops away.
   - Depths $\le 0$, non-integers, floats, and booleans are strictly rejected with a `ValueError`.
   - Default transitive depth is `10`.
2. **Repository Isolation**:
   - All Cypher queries require `$repo_id` and enforce repository ownership on all nodes along the path (`ALL(node IN nodes(path) WHERE node.repo_id = $repo_id)`).
   - Cross-repository callers cannot enter the impact set.
3. **Cycle and Duplicate Handling**:
   - Cyclic caller graphs (`A -> B -> A`) terminate naturally without infinite traversal.
   - Self-loops (`A -> A`) are eliminated.
   - Diamond shapes (multiple paths reaching the same caller) preserve the shortest hop distance and prevent duplicate entity entries.
4. **Missing Targets and Error Handling**:
   - Nonexistent target entities return `target_entity_found=False`, an empty impact set (`blast_radius == 0`), and empty `affected_files`.
   - Targets with no dependents (e.g. entry-point functions) return `target_entity_found=True`, `blast_radius == 0`, and empty `affected_files`.
   - Database connection failures raise `ImpactAnalysisError` (subclass of `GraphTraversalError` and `Neo4jConnectionError`) with masked credentials.

---

## 6. Exposure Through P0-20 Impact REST API

P0-20 can expose the engine directly via FastAPI:

```python
from fastapi import APIRouter, Depends, HTTPException, Query
from app.graph.impact import ImpactAnalysisResult, ImpactAnalyzer, analyze_impact

router = APIRouter(prefix="/api/v1/impact", tags=["impact"])

@router.get("/{entity_id:path}")
def get_entity_impact(
    entity_id: str,
    repo_id: str | None = Query(default=None),
    max_depth: int = Query(default=10, ge=1, le=50),
) -> dict:
    try:
        result = analyze_impact(
            target_entity_id=entity_id,
            repo_id=repo_id,
            max_depth=max_depth,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not result.target_entity_found:
        raise HTTPException(status_code=404, detail=f"Entity not found: {entity_id}")

    return {
        "repository_id": result.repository_id,
        "target_entity_id": result.target_entity_id,
        "blast_radius": result.blast_radius,
        "directly_impacted_count": result.directly_impacted_count,
        "affected_file_count": result.affected_file_count,
        "directly_impacted_entities": result.directly_impacted_entity_ids,
        "impacted_entities": [
            {
                "entity_id": n.entity_id,
                "depth": n.depth,
                "label": n.primary_label,
                "path_relationships": list(n.path_relationship_types),
            }
            for n in result.impacted_entities
        ],
        "affected_files": [
            {"file_id": f.file_id, "path": f.path}
            for f in result.affected_files
        ],
    }
```

---

## 7. Answers to AI Coding Rules (Rule 2)

1. **What?**
   - Impact analysis engine computing direct and transitive blast radius of code changes and affected files in Neo4j.
2. **Why?**
   - To identify upstream dependents and files that must be re-tested or reviewed when modifying a function, class, or method.
3. **How?**
   - Delegates to P0-16 `GraphTraversal.get_dependents` in reverse dependency direction, segregates depth-1 direct impacts, and aggregates affected source files by file ID.
4. **Inputs?**
   - `target_entity_id`, optional `repo_id`, `max_depth`, optional `relationship_types`, optional `Session`/`Driver`.
5. **Outputs?**
   - Typed `ImpactAnalysisResult` containing directly impacted entities, transitive impacted entities, and affected `AffectedFile` entries.
6. **Dependencies?**
   - Existing `app.graph.traversal` and `app.ucm.identity`. Zero new external dependencies.
7. **Trade-offs?**
   - Reused a single `GraphTraversal.get_dependents` query to derive both direct (depth 1) and transitive (depths 1..max_depth) impact, eliminating redundant round-trips to Neo4j.
   - Structured `AffectedFile` supports both object attributes (`.file_id`, `.path`) and string comparison (`"app.py" in result.affected_files`).
8. **Known Limitations?**
   - Does not perform impact risk scoring or blast-radius weighting; these belong to future issues.
