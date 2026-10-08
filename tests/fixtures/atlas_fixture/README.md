# Atlas AI — P0 Correctness Oracle Fixture Repository

## 1. Purpose

This directory (`tests/fixtures/atlas_fixture/`) is the **P0 correctness oracle** for Atlas AI's static analysis pipeline.

The fixture provides a minimal, strictly deterministic, and fully verifiable Python codebase with known ground-truth structure. It establishes the benchmark against which Atlas AI static code extraction, symbol resolution, Neo4j graph construction, and impact analysis algorithms are verified.

## 2. Critical Correctness Rule

> **"The fixture repository and its documented expected entities and relationships constitute the P0 correctness oracle."**

- **Production implementation must conform to the documented expected results.** The parser, resolver, graph schema, and impact engine must satisfy the ground truth defined here.
- **Expected results must not be changed merely to accommodate an incorrect implementation.** If an algorithm or query produces results that contradict this oracle, the implementation is defective, not the oracle.
- **Intentional fixture changes require an explicit explanation of why the correctness oracle changed.** Any evolution of this fixture must be justified through an architecture decision and documented rationale.

---

## 3. Fixture Architecture and File Purposes

The fixture models a clean multi-layer Python application with explicit dependency chains, an isolated component, and deliberate ambiguity cases:

```text
[app.py]
   │
   ▼
[services.py] ──────► [utils.py]
   │
   ▼
[models.py]
   │
   ▼
[base.py]

[unrelated.py] (isolated / disconnected)

[ambiguous.py] (unresolved / ambiguous references)
```

### File Purposes

1. **`app.py`**:
   - Application-level entry point orchestrating top-level execution.
   - Defines the `Application` class and `main()` function.
   - Imports from and calls into `services.py`.
2. **`services.py`**:
   - Business service layer coordinating model operations and utility formatting.
   - Defines `ItemService` and standalone function `process_item_workflow`.
   - Imports from and calls into `models.py` and `utils.py`.
3. **`models.py`**:
   - Domain data models and object factories.
   - Defines `ItemModel` (inherits from `BaseEntity`) and factory function `create_default_item`.
   - Imports from and calls into `base.py`.
4. **`base.py`**:
   - Foundation class providing root entity identity attributes and accessor methods.
   - Defines `BaseEntity`. Has zero inbound/outbound fixture dependencies except being inherited by `ItemModel`.
5. **`utils.py`**:
   - General utility helper functions.
   - Defines `format_identifier` used by `services.py` to validate secondary cross-file dependency branches.
6. **`unrelated.py`**:
   - Valid, executable Python module intentionally disconnected from all other files.
   - Defines `StandaloneCalculator` and `sum_values`.
   - Serves as a negative isolation boundary for dependency traversal and blast-radius testing.
7. **`ambiguous.py`**:
   - Deterministic test cases representing unresolved imports, missing symbols, duck-typed dynamic dispatches, and local scopes.
   - Validates that the static resolver strictly adheres to "evidence before inference" and does not invent speculative graph edges.

---

## 4. Expected Entities (Nodes)

The following entities must be identified by static extraction according to `docs/GRAPH_SCHEMA.md`:

### 4.1 Files and Modules

| File Path (`File.path`) | Module Qualified Name (`Module.qualified_name`) | Language |
| :--- | :--- | :--- |
| `app.py` | `app` | `python` |
| `services.py` | `services` | `python` |
| `models.py` | `models` | `python` |
| `base.py` | `base` | `python` |
| `utils.py` | `utils` | `python` |
| `unrelated.py` | `unrelated` | `python` |
| `ambiguous.py` | `ambiguous` | `python` |

### 4.2 Classes

| File | Class Name | Qualified Name | Base Classes |
| :--- | :--- | :--- | :--- |
| `app.py` | `Application` | `app.Application` | None |
| `services.py` | `ItemService` | `services.ItemService` | None |
| `models.py` | `ItemModel` | `models.ItemModel` | `BaseEntity` (`base.BaseEntity`) |
| `base.py` | `BaseEntity` | `base.BaseEntity` | None |
| `unrelated.py` | `StandaloneCalculator` | `unrelated.StandaloneCalculator` | None |
| `ambiguous.py` | `AlphaWorker` | `ambiguous.AlphaWorker` | None |
| `ambiguous.py` | `BetaWorker` | `ambiguous.BetaWorker` | None |

### 4.3 Functions (Module-Level)

| File | Function Name | Qualified Name |
| :--- | :--- | :--- |
| `app.py` | `main` | `app.main` |
| `services.py` | `process_item_workflow` | `services.process_item_workflow` |
| `models.py` | `create_default_item` | `models.create_default_item` |
| `utils.py` | `format_identifier` | `utils.format_identifier` |
| `unrelated.py` | `sum_values` | `unrelated.sum_values` |
| `ambiguous.py` | `call_ambiguous_worker` | `ambiguous.call_ambiguous_worker` |
| `ambiguous.py` | `execute_task` | `ambiguous.execute_task` |
| `ambiguous.py` | `call_undefined_symbol` | `ambiguous.call_undefined_symbol` |
| `ambiguous.py` | `outer_scope_function` | `ambiguous.outer_scope_function` |
| `ambiguous.py` | `dynamic_reflection_dispatch` | `ambiguous.dynamic_reflection_dispatch` |

*(Note: `inner_local_function` in `ambiguous.py` is scoped inside `outer_scope_function`, not a top-level module function.)*

### 4.4 Methods

| Class Qualified Name | Method Name | Method Qualified Name |
| :--- | :--- | :--- |
| `app.Application` | `__init__` | `app.Application.__init__` |
| `app.Application` | `run` | `app.Application.run` |
| `services.ItemService` | `get_item_summary` | `services.ItemService.get_item_summary` |
| `services.ItemService` | `create_tagged_item` | `services.ItemService.create_tagged_item` |
| `models.ItemModel` | `__init__` | `models.ItemModel.__init__` |
| `models.ItemModel` | `get_display_name` | `models.ItemModel.get_display_name` |
| `base.BaseEntity` | `__init__` | `base.BaseEntity.__init__` |
| `base.BaseEntity` | `get_id` | `base.BaseEntity.get_id` |
| `unrelated.StandaloneCalculator` | `add` | `unrelated.StandaloneCalculator.add` |
| `unrelated.StandaloneCalculator` | `compute_total` | `unrelated.StandaloneCalculator.compute_total` |
| `ambiguous.AlphaWorker` | `execute_task` | `ambiguous.AlphaWorker.execute_task` |
| `ambiguous.BetaWorker` | `execute_task` | `ambiguous.BetaWorker.execute_task` |

---

## 5. Expected Containment (`CONTAINS`)

Containment models syntactic ownership:

- **Repository → File**:
  - `(:Repository)-[:CONTAINS]->(:File {path: "app.py"})`
  - `(:Repository)-[:CONTAINS]->(:File {path: "services.py"})`
  - `(:Repository)-[:CONTAINS]->(:File {path: "models.py"})`
  - `(:Repository)-[:CONTAINS]->(:File {path: "base.py"})`
  - `(:Repository)-[:CONTAINS]->(:File {path: "utils.py"})`
  - `(:Repository)-[:CONTAINS]->(:File {path: "unrelated.py"})`
  - `(:Repository)-[:CONTAINS]->(:File {path: "ambiguous.py"})`
- **File → Class**:
  - `app.py` CONTAINS `Application`
  - `services.py` CONTAINS `ItemService`
  - `models.py` CONTAINS `ItemModel`
  - `base.py` CONTAINS `BaseEntity`
  - `unrelated.py` CONTAINS `StandaloneCalculator`
  - `ambiguous.py` CONTAINS `AlphaWorker`, `BetaWorker`
- **File → Function**:
  - `app.py` CONTAINS `main`
  - `services.py` CONTAINS `process_item_workflow`
  - `models.py` CONTAINS `create_default_item`
  - `utils.py` CONTAINS `format_identifier`
  - `unrelated.py` CONTAINS `sum_values`
  - `ambiguous.py` CONTAINS `call_ambiguous_worker`, `execute_task`, `call_undefined_symbol`, `outer_scope_function`, `dynamic_reflection_dispatch`
- **Class → Method**:
  - `Application` CONTAINS `__init__`, `run`
  - `ItemService` CONTAINS `get_item_summary`, `create_tagged_item`
  - `ItemModel` CONTAINS `__init__`, `get_display_name`
  - `BaseEntity` CONTAINS `__init__`, `get_id`
  - `StandaloneCalculator` CONTAINS `add`, `compute_total`
  - `AlphaWorker` CONTAINS `execute_task`
  - `BetaWorker` CONTAINS `execute_task`

---

## 6. Expected Imports (`IMPORTS`)

In accordance with `docs/GRAPH_SCHEMA.md`, import analysis evaluates two distinct resolution tiers:
1. **Module-level resolution**: Linking the source file to the target module node via `(:File)-[:IMPORTS]->(:Module)`.
2. **Symbol-level resolution**: Binding individual imported identifiers to specific declaration entities (`Class`, `Function`, etc.) within the target module.

### 6.1 Resolved Imports (Both Module and Symbols Resolved)

| Source File | Imported Module Target | Module-Level Relationship | Imported Symbols | Symbol Resolution Status |
| :--- | :--- | :--- | :--- | :--- |
| `app.py` | `services` (`services.py`) | `(:File {path: "app.py"})-[:IMPORTS]->(:Module {name: "services"})` | `ItemService`, `process_item_workflow` | RESOLVED (`services.ItemService`, `services.process_item_workflow`) |
| `services.py` | `models` (`models.py`) | `(:File {path: "services.py"})-[:IMPORTS]->(:Module {name: "models"})` | `ItemModel`, `create_default_item` | RESOLVED (`models.ItemModel`, `models.create_default_item`) |
| `services.py` | `utils` (`utils.py`) | `(:File {path: "services.py"})-[:IMPORTS]->(:Module {name: "utils"})` | `format_identifier` | RESOLVED (`utils.format_identifier`) |
| `models.py` | `base` (`base.py`) | `(:File {path: "models.py"})-[:IMPORTS]->(:Module {name: "base"})` | `BaseEntity` | RESOLVED (`base.BaseEntity`) |

### 6.2 Negative / Ambiguity Import Outcomes (in `ambiguous.py`)

| Source File | Import Statement | Module-Level Outcome | Symbol-Level Outcome | Explanation |
| :--- | :--- | :--- | :--- | :--- |
| `ambiguous.py` | `from models import MissingModel` | **RESOLVED**:<br>`(:File {path: "ambiguous.py"})-[:IMPORTS]->(:Module {name: "models"})` | **UNRESOLVED**:<br>No entity edge created | The target module `models` exists in the repository (`models.py`), so the module-level `IMPORTS` edge is established. However, the symbol `MissingModel` does not exist in `models.py`; symbol-level resolution fails and must not bind to any entity. |
| `ambiguous.py` | `from nonexistent_module import missing_symbol` | **UNRESOLVED**:<br>No `IMPORTS` edge created | **UNRESOLVED**:<br>No entity edge created | The target module `nonexistent_module` does not exist anywhere in the repository. Both module-level and symbol-level resolution fail. |

### 6.3 Isolated Modules (No Imports)

- `base.py`: No imports.
- `utils.py`: No imports.
- `unrelated.py`: No imports.

---

## 7. Expected Inheritance (`INHERITS`)

### 7.1 Resolved Inheritance

| Child Class | Parent Class | Source Evidence |
| :--- | :--- | :--- |
| `models.ItemModel` | `base.BaseEntity` | `class ItemModel(BaseEntity):` |

Relationship:
```text
(:Class {name: "ItemModel"})-[:INHERITS]->(:Class {name: "BaseEntity"})
```

### 7.2 Non-Inherited Classes

- `app.Application`: Does not inherit from any custom class.
- `services.ItemService`: Does not inherit from any custom class.
- `base.BaseEntity`: Root class; does not inherit from any custom class.
- `unrelated.StandaloneCalculator`: Does not inherit from any custom class.
- `ambiguous.AlphaWorker`: Does not inherit from any custom class.
- `ambiguous.BetaWorker`: Does not inherit from any custom class.

---

## 8. Expected Calls (`CALLS`)

### 8.1 Resolved Function / Method Calls

| Caller Entity | Callee Entity | Call Scope | Evidence / Location |
| :--- | :--- | :--- | :--- |
| `app.main` | `app.Application.__init__` | Intra-file | `Application()` instantiation in `main` |
| `app.main` | `app.Application.run` | Intra-file | `app.run("item-1", "Atlas Item")` in `main` |
| `app.main` | `services.process_item_workflow` | Cross-file | `process_item_workflow(...)` in `main` |
| `app.Application.__init__` | `services.ItemService.__init__` | Cross-file | `self.service = ItemService()` in `Application.__init__` |
| `app.Application.run` | `services.ItemService.get_item_summary` | Cross-file | `self.service.get_item_summary(...)` in `Application.run` |
| `services.process_item_workflow` | `services.ItemService.__init__` | Intra-file | `service = ItemService()` in `process_item_workflow` |
| `services.process_item_workflow` | `services.ItemService.get_item_summary` | Intra-file | `service.get_item_summary(...)` in `process_item_workflow` |
| `services.process_item_workflow` | `services.ItemService.create_tagged_item` | Intra-file | `service.create_tagged_item(...)` in `process_item_workflow` |
| `services.ItemService.get_item_summary` | `models.ItemModel.__init__` | Cross-file | `ItemModel(...)` instantiation |
| `services.ItemService.get_item_summary` | `models.ItemModel.get_display_name` | Cross-file | `item.get_display_name()` |
| `services.ItemService.create_tagged_item` | `utils.format_identifier` | Cross-file | `format_identifier("srv", raw_id)` |
| `services.ItemService.create_tagged_item` | `models.create_default_item` | Cross-file | `create_default_item(entity_id=normalized_id)` |
| `models.ItemModel.__init__` | `base.BaseEntity.__init__` | Cross-file | `super().__init__(entity_id=entity_id)` |
| `models.ItemModel.get_display_name` | `base.BaseEntity.get_id` | Cross-file | `self.get_id()` inherited method invocation |
| `models.create_default_item` | `models.ItemModel.__init__` | Intra-file | `ItemModel(entity_id=entity_id, name="default_item")` |
| `unrelated.StandaloneCalculator.compute_total` | `unrelated.sum_values` | Intra-file | `sum_values(values)` |
| `ambiguous.outer_scope_function` | `ambiguous.inner_local_function` | Lexical / Intra-func | `inner_local_function(value)` |

### 8.2 Disallowed / Speculative Calls (Must Remain Unresolved)

The static resolver **must NOT** create speculative `CALLS` edges for:
1. `ambiguous.call_ambiguous_worker`: Receiver `worker` is untyped at static extraction time; it must not be linked to `AlphaWorker.execute_task` or `BetaWorker.execute_task`.
2. `ambiguous.call_undefined_symbol`: Callee `undefined_function` is neither defined nor imported.
3. `ambiguous.dynamic_reflection_dispatch`: Call is executed via `getattr()`.
4. Any caller in `app.py`, `services.py`, `models.py`, `base.py`, or `utils.py` pointing to `unrelated.py`.

---

## 9. Direct Dependencies

Direct dependencies represent 1-hop dependencies between source files/modules:

| Source Entity | Direct Dependencies (Outbound) | Description |
| :--- | :--- | :--- |
| `app.py` | `services.py` | Relies on `ItemService` and `process_item_workflow` |
| `services.py` | `models.py`, `utils.py` | Relies on `ItemModel`, `create_default_item`, and `format_identifier` |
| `models.py` | `base.py` | Relies on `BaseEntity` |
| `base.py` | *None* | Independent root entity |
| `utils.py` | *None* | Independent leaf utility |
| `unrelated.py` | *None* | Completely self-contained |
| `ambiguous.py` | `models.py` | Establishes module-level import to `models.py` (though symbol `MissingModel` is unresolved) |

---

## 10. Transitive Dependencies

Transitive dependencies represent multi-hop reachability in the dependency graph:

### Primary Transitive Dependency Chain

```text
app.py
  └──► services.py
         ├──► models.py
         │      └──► base.py
         └──► utils.py
```

### File-Level Transitive Reachability

- **`app.py` Transitive Dependency Set**:
  `{ services.py, models.py, base.py, utils.py }`
- **`services.py` Transitive Dependency Set**:
  `{ models.py, base.py, utils.py }`
- **`models.py` Transitive Dependency Set**:
  `{ base.py }`
- **`ambiguous.py` Transitive Dependency Set**:
  `{ models.py, base.py }` (via module import of `models.py`)
- **`base.py` Transitive Dependency Set**:
  `∅` (empty)
- **`utils.py` Transitive Dependency Set**:
  `∅` (empty)
- **`unrelated.py` Transitive Dependency Set**:
  `∅` (empty)

---

## 11. Impact and Dependent Expectations (Blast Radius)

Impact analysis traverses inverse dependency relationships (who depends on the modified entity). Atlas AI distinguishes between two complementary impact models:
- **File-Level Impact**: Identifies affected source files via reverse transitive module imports.
- **Entity-Level Impact**: Identifies affected graph entities (`Class`, `Method`, `Function`) through explicit semantic relationships (`INHERITS`, `CALLS`).

### 11.1 Impact on Changes to `base.py` / `BaseEntity`

When `base.py` (or `BaseEntity`) is modified:

#### A. File-Level Impact (Affected Files)
- **Direct Dependent Files**: `models.py` (imports `base.py`)
- **Transitive Dependent Files**:
  - `services.py` (imports `models.py`)
  - `app.py` (imports `services.py`)
  - `ambiguous.py` (imports `models.py`)
- **File Impact Set**: `{ models.py, services.py, app.py, ambiguous.py }`
- **Unaffected Files (Negative Isolation)**:
  - `utils.py`: **Not impacted** (no dependency path to `base.py`).
  - `unrelated.py`: **Not impacted** (completely isolated).

#### B. Entity-Level Impact (Affected Entities)
- **Modified Entity**: `base.BaseEntity` (and methods `__init__`, `get_id`)
- **Direct Dependent Entities**:
  - `models.ItemModel` (via `INHERITS` `BaseEntity`)
  - `models.ItemModel.__init__` (via `CALLS` `BaseEntity.__init__`)
  - `models.ItemModel.get_display_name` (via `CALLS` `BaseEntity.get_id`)
- **Transitive Dependent Entities**:
  - `models.create_default_item` (calls `ItemModel.__init__`)
  - `services.ItemService.get_item_summary` (calls `ItemModel.__init__` and `ItemModel.get_display_name`)
  - `services.ItemService.create_tagged_item` (calls `models.create_default_item`)
  - `services.process_item_workflow` (calls `ItemService.get_item_summary` and `ItemService.create_tagged_item`)
  - `app.Application.run` (calls `ItemService.get_item_summary`)
  - `app.main` (calls `process_item_workflow` and `Application.run`)
- **Entity Impact Set**:
  `{ models.ItemModel, models.ItemModel.__init__, models.ItemModel.get_display_name, models.create_default_item, services.ItemService.get_item_summary, services.ItemService.create_tagged_item, services.process_item_workflow, app.Application.run, app.main }`
- **Entity-Level Negative Isolation (Unaffected Entities)**:
  - `utils.format_identifier`: **Not impacted** (no call or inheritance path).
  - `app.Application.__init__`: **Not impacted** (only calls `ItemService.__init__`).
  - `unrelated.StandaloneCalculator`, `unrelated.sum_values`: **Not impacted** (isolated).
  - All entities in `ambiguous.py` (`AlphaWorker`, `BetaWorker`, `call_ambiguous_worker`, `execute_task`, `call_undefined_symbol`, `outer_scope_function`, `dynamic_reflection_dispatch`): **Not impacted**. Although `ambiguous.py` has a file-level import of `models.py`, none of its entities reference, call, or inherit from `BaseEntity` or its descendants.

---

### 11.2 Impact on Changes to `utils.py` / `format_identifier`

When `utils.py` (or `format_identifier`) is modified:

#### A. File-Level Impact (Affected Files)
- **Direct Dependent Files**: `services.py` (imports `utils.py`)
- **Transitive Dependent Files**: `app.py` (imports `services.py`)
- **File Impact Set**: `{ services.py, app.py }`
- **Unaffected Files**: `models.py`, `base.py`, `unrelated.py`, `ambiguous.py`

#### B. Entity-Level Impact (Affected Entities)
- **Modified Entity**: `utils.format_identifier`
- **Direct Dependent Entities**:
  - `services.ItemService.create_tagged_item` (via `CALLS` `format_identifier`)
- **Transitive Dependent Entities**:
  - `services.process_item_workflow` (via `CALLS` `ItemService.create_tagged_item`)
  - `app.main` (via `CALLS` `process_item_workflow`)
- **Entity Impact Set**:
  `{ services.ItemService.create_tagged_item, services.process_item_workflow, app.main }`
- **Entity-Level Negative Isolation (Unaffected Entities)**:
  - `services.ItemService.get_item_summary`: **Not impacted** (does not call `format_identifier` or `create_tagged_item`).
  - `app.Application.__init__`, `app.Application.run`: **Not impacted** (neither method invokes `create_tagged_item` or `process_item_workflow`).
  - All entities in `models.py`, `base.py`, `unrelated.py`, `ambiguous.py`: **Not impacted**.

---

### 11.3 Impact on Changes to `models.py` / `ItemModel`

When `models.py` (or `ItemModel`) is modified:

#### A. File-Level Impact (Affected Files)
- **Direct Dependent Files**: `services.py` (imports `models.py`), `ambiguous.py` (imports `models.py`)
- **Transitive Dependent Files**: `app.py` (imports `services.py`)
- **File Impact Set**: `{ services.py, ambiguous.py, app.py }`
- **Unaffected Files**: `base.py`, `utils.py`, `unrelated.py`

#### B. Entity-Level Impact (Affected Entities)
- **Modified Entity**: `models.ItemModel`
- **Direct Dependent Entities**:
  - `models.create_default_item` (calls `ItemModel.__init__`)
  - `services.ItemService.get_item_summary` (calls `ItemModel.__init__` and `ItemModel.get_display_name`)
- **Transitive Dependent Entities**:
  - `services.ItemService.create_tagged_item` (calls `create_default_item`)
  - `services.process_item_workflow` (calls `ItemService.get_item_summary` and `create_tagged_item`)
  - `app.Application.run` (calls `ItemService.get_item_summary`)
  - `app.main` (calls `process_item_workflow` and `Application.run`)
- **Entity Impact Set**:
  `{ models.create_default_item, services.ItemService.get_item_summary, services.ItemService.create_tagged_item, services.process_item_workflow, app.Application.run, app.main }`
- **Entity-Level Negative Isolation (Unaffected Entities)**:
  - `base.BaseEntity`: **Not impacted** (dependencies point *to* `BaseEntity`, not from it).
  - `utils.format_identifier`: **Not impacted**.
  - All entities in `ambiguous.py`: **Not impacted** (none reference or call `ItemModel`).
  - `unrelated.StandaloneCalculator`, `unrelated.sum_values`: **Not impacted**.

---

### 11.4 Impact on Changes to `unrelated.py` / `StandaloneCalculator`

When `unrelated.py` (or `StandaloneCalculator`) is modified:

#### A. File-Level Impact (Affected Files)
- **Direct / Transitive Dependent Files**: `unrelated.py` only.
- **Cross-File Impact Set**: `∅` (empty).
- **Unaffected Files**: `app.py`, `services.py`, `models.py`, `base.py`, `utils.py`, `ambiguous.py`.

#### B. Entity-Level Impact (Affected Entities)
- **Modified Entity**: `unrelated.sum_values`
- **Direct Dependent Entities**: `unrelated.StandaloneCalculator.compute_total` (calls `sum_values`).
- **Cross-File Impact Set**: `∅` (empty).
- **Unaffected Entities**: All entities in all other fixture files.

---

## 12. Unrelated Code Isolation

`unrelated.py` is intentionally disconnected from the main application graph:

- It contains valid Python code: a class `StandaloneCalculator`, methods `add` and `compute_total`, and a helper function `sum_values`.
- It imports no modules from this fixture repository.
- No fixture file imports `unrelated.py`.
- No function or method outside `unrelated.py` calls anything in `unrelated.py`.
- No class in `unrelated.py` participates in inheritance with any other class.

**Invariant**: Any graph traversal (e.g., BFS or Cypher pattern match `()-[:DEPENDS_ON|CALLS|IMPORTS*]->()`) originating from the main dependency tree (`app.py`, `services.py`, `models.py`, `base.py`, `utils.py`) must **never** reach any entity in `unrelated.py`, and vice-versa.

---

## 13. Ambiguous and Unresolved Reference Cases

`ambiguous.py` documents 7 deterministic negative cases based on `docs/TESTING.md` and `docs/GRAPH_SCHEMA.md`:

| Case # | Description | Code in `ambiguous.py` | Expected Ground Truth |
| :--- | :--- | :--- | :--- |
| **1** | Missing target module | `from nonexistent_module import missing_symbol` | Target module does not exist in the repository. Both module resolution and symbol resolution fail. No `IMPORTS` edge to any repository `Module` or `File`. |
| **2** | Missing imported symbol in existing module | `from models import MissingModel` | Target module `models` exists (`models.py`), so the module-level import resolves: `(:File {path: "ambiguous.py"})-[:IMPORTS]->(:Module {name: "models"})`. However, symbol `MissingModel` does not exist in `models.py`; symbol-level resolution fails and must not bind to any entity. |
| **3** | Ambiguous call receiver | `worker.execute_task(task_name)` where both `AlphaWorker` and `BetaWorker` define `execute_task` | The receiver `worker` is untyped. Without runtime type inference, the target is ambiguous. Resolver must NOT guess or invent a `CALLS` edge to either class method. |
| **4** | Name collision (Function vs Method) | Standalone function `execute_task(task_name)` vs methods on `AlphaWorker` and `BetaWorker` | Demonstrates identical name across different entity types and containers. The resolver must not confound the standalone function with either class method. |
| **5** | Unresolved function call | `undefined_function()` in `call_undefined_symbol()` | Target function is neither imported nor defined. Resolver must mark call as unresolved without creating dummy or speculative nodes. |
| **6** | Nested lexical scope | `inner_local_function` defined inside `outer_scope_function` | Inner function is local to enclosing function scope, not an accessible top-level module function. Call resolution is strictly lexical. |
| **7** | Dynamic reflection | `method = getattr(target, method_name); method()` | Dynamic reflection cannot be resolved statically. Resolver must not create speculative `CALLS` edges. |

---

## 14. Verification Summary

To verify the fixture repository against Python syntax and self-containment:

```bash
# 1. Parse validation (AST)
python -c "import ast, glob; [ast.parse(open(f, encoding='utf-8').read(), filename=f) for f in glob.glob('tests/fixtures/atlas_fixture/*.py')]; print('Syntax valid!')"

# 2. Execution validation of deterministic entry point
python tests/fixtures/atlas_fixture/app.py
# Output: Workflow: Item[default-1]: Atlas Default (tag=srv::default-1) | Item[item-1]: Atlas Item
```
