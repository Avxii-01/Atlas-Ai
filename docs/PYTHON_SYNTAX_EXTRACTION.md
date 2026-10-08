# Atlas AI — Python Syntax Extraction (P0-09)

## 1. Overview and Purpose

### What
The Python Syntax Extraction module (`app.extractor`) bridges the Tree-sitter concrete syntax parser (P0-07) and the Unified Code Model (P0-08). It translates concrete Python AST nodes into typed, normalized UCM entities (`File`, `Module`, `Class`, `Function`, `Method`, `Import`) and syntactic `CONTAINS` relationships.

### Why
Tree-sitter provides raw concrete syntax trees and token byte offsets. Neo4j and downstream graph query engines require typed, repository-scoped entities with stable identities and structural hierarchy. The extractor performs this transformation deterministically without introducing semantic speculation.

---

## 2. Architectural Pipeline and Boundaries

```text
Tree-sitter Parser (P0-07)
         │ (concrete syntax tree & error recovery)
         ▼
Python Syntax Extractor (P0-09)
         │ (AST traversal, scope tracking, UCM entity creation, CONTAINS edges)
         ▼
Unified Code Model (P0-08)
         │ (normalized entity bundle & lossless JSON serialization)
         ▼
Relationship Resolver (P0-09+)
         │ (semantic resolution: IMPORTS, CALLS, INHERITS)
         ▼
Neo4j Persistence (P0-10)
```

### Boundary Constraints
- **Syntactic Only**: Extracts declarations and structural containment (`CONTAINS`).
- **No Semantic Resolution**: Does **not** infer `CALLS`, `INHERITS`, or semantic `IMPORTS` relationships from syntax. Those belong strictly to the Relationship Resolver.
- **Parser Decoupling**: Uses `app.parser.python_parser` and `ParseResult` interfaces; does not re-initialize grammars or duplicate Tree-sitter logic.
- **UCM Identity Conformance**: Uses exclusively P0-08 identity builders (`build_class_id`, `build_function_id`, etc.). Does not invent secondary identifiers.

---

## 3. Scope Tracking and Nesting Rules

To prevent misclassifying functions, methods, and nested definitions, extraction uses a strict lexical `_DefinitionScope`:

| Context | Definition Node | Classification | Qualified Name Pattern | Containment Relationship |
| :--- | :--- | :--- | :--- | :--- |
| File / Module | `class_definition` | `Class` | `{module}.{Class}` | `File -> Class` |
| File / Module | `function_definition` | `Function` | `{module}.{func}` | `File -> Function` |
| Inside `Class` | `function_definition` | `Method` | `{module}.{Class}.{method}` | `Class -> Method` |
| Inside `Class` | `class_definition` | `Class` | `{module}.{Class}.{InnerClass}` | `Class -> Class` |
| Inside `Function` | `function_definition` | `Function` | `{parent_qname}.{inner_func}` | `Function -> Function` |
| Inside `Function` | `class_definition` | `Class` | `{parent_qname}.{LocalClass}` | `Function -> Class` |
| Inside `Method` | `function_definition` | `Function` | `{parent_qname}.{local_func}` | `Method -> Function` |
| Inside `Method` | `class_definition` | `Class` | `{parent_qname}.{LocalClass}` | `Method -> Class` |

### Method vs. Function Invariant
A `function_definition` node is classified as a `Method` if and only if its **immediate enclosing definition scope is a `Class`**. Functions defined within functions or methods (local lexical helper functions) are classified as `Function` entities, properly scoped to their enclosing parent.

---

## 4. Extraction API

### `PythonExtractor`
Main extractor class backed by an optional or singleton `PythonParser`.

- `extract_source(source, file_path, repo_id=..., repository=..., module_qualified_name=...) -> ExtractionResult`:
  Parses and extracts entities from Python source string or bytes.
- `extract_file(file_path, base_dir=..., repo_id=..., repository=..., module_qualified_name=...) -> ExtractionResult`:
  Reads and extracts from a file path on disk.
- `extract_parse_result(parse_result, file_path, repo_id=..., repository=..., module_qualified_name=...) -> ExtractionResult`:
  Extracts entities from a pre-existing `ParseResult`.
- `extract_repository(repo_path, repo_name=..., repo_source=..., file_paths=...) -> UnifiedCodeModel`:
  Scans all `.py` files in a repository directory, extracts them deterministically, and aggregates them into a complete `UnifiedCodeModel`.

### Module Convenience Functions
- `extract_python_source(...)`
- `extract_python_file(...)`
- `extract_python_repository(...)`
- `derive_module_info(normalized_path) -> (name, qualified_name)`

### `ExtractionResult`
Container for per-file extraction results:
- `repository: Repository`
- `file: File | None`
- `module: Module | None`
- `classes: list[Class]`
- `functions: list[Function]`
- `methods: list[Method]`
- `imports: list[Import]`
- `relationships: list[Relationship]`
- `parse_result: ParseResult | None`
- `has_syntax_errors: bool`
- `is_valid: bool`
- `errors: list[SyntaxErrorInfo]`
- `to_ucm() -> UnifiedCodeModel`
- `add_to_ucm(ucm: UnifiedCodeModel) -> None`

---

## 5. Import Statement Handling

Both standard and `from ... import` statements are parsed into individual `Import` entities for each imported symbol:

| Syntax Example | Extracted `Import` Fields |
| :--- | :--- |
| `import os` | `module_name="os"`, `imported_name="os"`, `alias=None` |
| `import sys as s, json` | 1: `module_name="sys"`, `imported_name="sys"`, `alias="s"`<br>2: `module_name="json"`, `imported_name="json"`, `alias=None` |
| `from models import ItemModel, create_item as ci` | 1: `module_name="models"`, `imported_name="ItemModel"`, `alias=None`<br>2: `module_name="models"`, `imported_name="create_item"`, `alias="ci"` |
| `from . import utils` | `module_name="."`, `imported_name="utils"`, `alias=None` |
| `from wildcard_mod import *` | `module_name="wildcard_mod"`, `imported_name="*"`, `alias=None` |

Each import record preserves the 1-indexed statement line, token byte offsets, and deterministic ID (`{repo_id}::import::{norm_path}::L{line}::{imported_name}`).

---

## 6. Error Handling and Syntax Recovery

The extractor preserves Tree-sitter's partial tree recovery:
- **Valid Source**: `is_valid=True`, `has_syntax_errors=False`, all declarations extracted.
- **Recoverable Syntax Errors**: `is_valid=False`, `has_syntax_errors=True`. Structured `SyntaxErrorInfo` items are exposed on `result.errors`. Valid definitions preceding or following the syntax error in the source file are recovered and extracted.
- **Catastrophic Failure / IO Error**: `file=None`, `module=None`, empty entity lists, error records surfaced cleanly without uncaught exceptions.

---

## 7. Verification Against Fixture Oracle

Tested against `tests/fixtures/atlas_fixture`:
- **7 Files & 7 Modules**: `app.py`, `services.py`, `models.py`, `base.py`, `utils.py`, `unrelated.py`, `ambiguous.py`.
- **7 Classes**: `app.Application`, `services.ItemService`, `models.ItemModel`, `base.BaseEntity`, `unrelated.StandaloneCalculator`, `ambiguous.AlphaWorker`, `ambiguous.BetaWorker`.
- **12 Methods**: All member methods matching oracle ground truth.
- **11 Functions**: 10 top-level functions + 1 nested function (`ambiguous.outer_scope_function.inner_local_function`).
- **8 Imports**: All imported symbols matching oracle ground truth.
- **37 Containment Relationships**: Clean hierarchical tree spanning repository, files, classes, methods, and functions.
