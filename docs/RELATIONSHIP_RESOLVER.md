# Atlas AI — Symbol Index and Relationship Resolver (P0-10)

## 1. Overview and Purpose

### What
The Relationship Resolver module (`app.resolver`) performs deterministic, evidence-based relationship resolution across code entities represented in the Unified Code Model (UCM). It indexes declarations across a repository and resolves cross-file `CONTAINS`, `IMPORTS`, `INHERITS`, and `CALLS` relationships.

### Why
Static AST parsing and syntax extraction (P0-09) extract entities within individual files and structural containment. However, dependency analysis, change-impact analysis, and knowledge graph construction require verified cross-file relationships (which module imports which, which class inherits from which base, and which function or method calls which target).

---

## 2. Architectural Pipeline and Boundaries

```text
Tree-sitter Parser (P0-07)
         │
         ▼
Python Syntax Extractor (P0-09)
         │ (AST parsing & UCM entity extraction: File, Module, Class, Function, Method, Import, CONTAINS)
         ▼
Unified Code Model (P0-08)
         │
         ▼
Relationship Resolver (P0-10)
         │ (Repository SymbolIndex & deterministic resolution: IMPORTS, INHERITS, CALLS)
         ▼
Resolved Unified Code Model
         │
         ▼
Neo4j Graph Persister (P0-10+)
```

### Boundary Constraints
- **Evidence Before Inference**: Never guesses ambiguous call receivers or creates speculative edges. If multiple candidates exist or the receiver is dynamically typed, the call is left unresolved.
- **Repository Isolation**: Resolution is strictly scoped to the analyzed repository. No cross-repository links or phantom external entity nodes are created.
- **Valid UCM Endpoints**: Emits relationships only when both `source_id` and `target_id` exist in the repository's UCM.
- **Deduplication**: Equivalent edges are deduplicated, and all output relationships are sorted deterministically.

---

## 3. Supported Relationships and Resolution Rules

### 3.1 `CONTAINS`
- Re-uses and validates all structural containment edges emitted by P0-09 (`Repository -> File`, `File -> Class`, `File -> Function`, `Class -> Method`, etc.).
- Verifies endpoints exist in the UCM and eliminates duplicates.

### 3.2 `IMPORTS`
- Pattern: `(:File)-[:IMPORTS]->(:Module)`
- Matches explicit `Import` entities against indexed `Module` entities in the repository.
- Supports direct imports (`import services`), dotted imports (`from app.services import ...`), relative imports (`from .models import ...`), and aliases (`import services as srv`).
- Ignores external libraries (`import os`) and missing modules (`from nonexistent import ...`).

### 3.3 `INHERITS`
- Pattern: `(:Class)-[:INHERITS]->(:Class)`
- Inspects `superclasses` of each class definition AST node.
- Resolves the base identifier via the `SymbolIndex` using lexical file scope and imported symbols.
- Ignores built-in classes (`Exception`, `object`) and external classes not declared in the repository.

### 3.4 `CALLS`
- Patterns:
  - `(:Function)-[:CALLS]->(:Function)`
  - `(:Method)-[:CALLS]->(:Function)`
  - `(:Method)-[:CALLS]->(:Method)`
- Resolves call sites:
  1. **Direct Identifier Calls**: Calls to local lexical inner functions, current-file functions, current-file class constructors, imported functions, and imported class constructors.
  2. **`self.<method>()`**: Member method calls on the current class or its base classes.
  3. **`super().__init__()` / `super().<method>()`**: Method invocations on resolved base classes.
  4. **Typed Receiver Calls**:
     - `self.<attr>.<method>()` where `self.<attr>` was instantiated to a known class in `__init__`.
     - `local_var.<method>()` where `local_var` was instantiated to a known class within the caller's body.
     - `module.<func>()` where `module` is an imported module.
  5. **Ambiguous and Dynamic Calls (Left Unresolved)**:
     - Untyped parameter receivers (e.g. `worker.execute_task()`).
     - Reflection dispatch (e.g. `getattr(target, method)()`).
     - Undefined functions (e.g. `undefined_function()`).

---

## 4. Public API

### `SymbolIndex`
Repository-scoped index of all UCM entities:
- `resolve_module(module_name, relative_to_path=None) -> Module | None`
- `resolve_symbol_in_file(file_path, symbol_name) -> Class | Function | Module | None`
- `get_method_on_class(class_qname, method_name) -> Method | None`

### `RelationshipResolver`
- `resolve(ucm, repo_path=..., sources=..., parse_results=...) -> UnifiedCodeModel`:
  Resolves all relationships and returns an augmented `UnifiedCodeModel`.
- `resolve_imports(ucm, index) -> list[Relationship]`
- `resolve_inherits(ucm, index, parse_results) -> list[Relationship]`
- `resolve_calls(ucm, index, parse_results) -> list[Relationship]`

### Module Functions
- `resolve_relationships(ucm, ...) -> UnifiedCodeModel`
- `resolve_repository(repo_path, repo_name=..., repo_source=...) -> UnifiedCodeModel`

---

## 5. Verification Against Fixture Oracle

Verified against `tests/fixtures/atlas_fixture`:
- **37 `CONTAINS` Relationships**: All structural containment edges preserved.
- **5 `IMPORTS` Relationships**: Exactly matching fixture ground truth (`app.py -> services`, `services.py -> models`, `services.py -> utils`, `models.py -> base`, `ambiguous.py -> models`).
- **1 `INHERITS` Relationship**: `models.ItemModel -> base.BaseEntity`.
- **15 `CALLS` Relationships**: All deterministically resolvable calls to declared entities in the UCM.
- **Total Relationships**: 58.
