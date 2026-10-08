# Atlas AI — Unified Code Model (UCM) Specification

## 1. Overview and Architectural Boundaries

The **Unified Code Model (UCM)** is the typed, language-independent intermediary between static syntax parsing, semantic resolution, and graph persistence in Atlas AI.

### Architectural Pipeline & Component Boundaries

```text
Tree-sitter Parser
        │ (concrete syntax tree & ranges)
        ▼
Unified Code Model (UCM) ◄─── (normalized entities & explicit relationships)
        │
        ▼
Relationship Resolver    ◄─── (resolves cross-file calls, imports, inheritance)
        │
        ▼
Neo4j Graph Persister    ◄─── (persists nodes & relationships to graph store)
```

1. **Syntax Parser (P0-07)**:
   - Parses concrete syntax and detects syntax errors using Tree-sitter.
   - Operates strictly on raw file bytes; has no knowledge of repository structure, symbols, or graphs.
2. **Unified Code Model (P0-08)**:
   - Encapsulates normalized entity models (`Repository`, `File`, `Module`, `Class`, `Function`, `Method`, `Import`).
   - Encapsulates typed relationship records (`CONTAINS`, `IMPORTS`, `CALLS`, `INHERITS`).
   - Guarantees deterministic identifiers and source location tracking.
   - **Boundary constraint**: Does **not** infer or resolve relationships, query syntax trees, or access Neo4j.
3. **Relationship Resolver (P0-09+)**:
   - Indexes symbols across files and determines verified semantic edges using evidence.
   - Supplies verified `Relationship` records to the UCM.
4. **Graph Persistence (P0-10+)**:
   - Translates UCM entities and relationships directly into Neo4j nodes and Cypher statements.

---

## 2. Supported Entity Types and Properties

Conforms to the node specifications defined in `docs/GRAPH_SCHEMA.md`:

### 2.1 Repository
Represents the root repository being analyzed.

- `id` (str, required): Deterministic ID (`repo::<name>`).
- `name` (str, required): Repository name.
- `source` (str, required): Ingestion origin (e.g. file path URI or git URL).
- `created_at` (str | None): Optional ISO 8601 creation timestamp.

### 2.2 File
Represents a source file within the repository.

- `id` (str, required): Deterministic ID (`<repo_id>::file::<normalized_path>`).
- `repo_id` (str, required): Owning repository ID.
- `path` (str, required): Repository-relative normalized POSIX path.
- `language` (str, default: `"python"`): Source programming language.
- `start_line` (int, default: 1): Starting line number (1-indexed).
- `end_line` (int, required): Ending line number (1-indexed, >= start_line).
- `start_byte` (int, default: 0): 0-indexed byte offset of file start.
- `end_byte` (int, default: 0): 0-indexed byte offset of file end (>= start_byte).

### 2.3 Module
Represents a Python module.

- `id` (str, required): Deterministic ID (`<repo_id>::module::<qualified_name>`).
- `repo_id` (str, required): Owning repository ID.
- `name` (str, required): Module short name (e.g. `"services"`).
- `qualified_name` (str, required): Dot-separated module path (e.g. `"services"` or `"app.services"`).
- `file_path` (str, required): Normalized repository-relative path to the implementing file.

### 2.4 Class
Represents a class declaration.

- `id` (str, required): Deterministic ID (`<repo_id>::class::<qualified_name>`).
- `repo_id` (str, required): Owning repository ID.
- `name` (str, required): Class identifier (e.g. `"ItemModel"`).
- `qualified_name` (str, required): Fully qualified name (e.g. `"models.ItemModel"`).
- `file_path` (str, required): Normalized path to containing file.
- `language` (str, default: `"python"`): Programming language.
- `start_line` (int, required): Starting line (1-indexed).
- `end_line` (int, required): Ending line (1-indexed, >= start_line).
- `start_byte` (int, required): 0-indexed byte offset.
- `end_byte` (int, required): 0-indexed byte offset (>= start_byte).
- `docstring` (str | None): Optional docstring text.

### 2.5 Function
Represents a module-level standalone function declaration.

- `id` (str, required): Deterministic ID (`<repo_id>::function::<qualified_name>`).
- `repo_id` (str, required): Owning repository ID.
- `name` (str, required): Function identifier (e.g. `"process_item_workflow"`).
- `qualified_name` (str, required): Fully qualified name (e.g. `"services.process_item_workflow"`).
- `file_path` (str, required): Normalized path to containing file.
- `language` (str, default: `"python"`): Programming language.
- `start_line` (int, required): Starting line (1-indexed).
- `end_line` (int, required): Ending line (1-indexed, >= start_line).
- `start_byte` (int, required): 0-indexed byte offset.
- `end_byte` (int, required): 0-indexed byte offset (>= start_byte).
- `docstring` (str | None): Optional docstring text.

### 2.6 Method
Represents a member method declaration on a class.

- `id` (str, required): Deterministic ID (`<repo_id>::method::<qualified_name>`).
- `repo_id` (str, required): Owning repository ID.
- `name` (str, required): Method identifier (e.g. `"get_item_summary"`).
- `qualified_name` (str, required): Fully qualified name (e.g. `"services.ItemService.get_item_summary"`).
- `file_path` (str, required): Normalized path to containing file.
- `language` (str, default: `"python"`): Programming language.
- `start_line` (int, required): Starting line (1-indexed).
- `end_line` (int, required): Ending line (1-indexed, >= start_line).
- `start_byte` (int, required): 0-indexed byte offset.
- `end_byte` (int, required): 0-indexed byte offset (>= start_byte).
- `docstring` (str | None): Optional docstring text.

### 2.7 Import
Represents an explicit import statement declaration.

- `id` (str, required): Deterministic ID (`<repo_id>::import::<path>::L<line>::<imported_name>`).
- `repo_id` (str, required): Owning repository ID.
- `file_path` (str, required): Normalized path to containing file.
- `module_name` (str, required): Target module name (e.g. `"models"`).
- `imported_name` (str, required): Imported symbol or module name (e.g. `"ItemModel"`).
- `alias` (str | None): Optional import alias.
- `start_line` (int, required): Line number of import statement (1-indexed).
- `end_line` (int, required): Line number of import statement end (1-indexed).
- `start_byte` (int, default: 0): Byte offset.
- `end_byte` (int, default: 0): Byte offset.

---

## 3. Stable Identifier Contract

In accordance with `docs/GRAPH_SCHEMA.md` Section 4, entity identifiers are **deterministic pure functions** of their identity inputs:

| Entity Type | Identity Formula | Example |
| :--- | :--- | :--- |
| **Repository** | `repo::{clean_name}` | `repo::atlas_fixture` |
| **File** | `{repo_id}::file::{normalized_path}` | `repo::atlas_fixture::file::models.py` |
| **Module** | `{repo_id}::module::{qualified_name}` | `repo::atlas_fixture::module::models` |
| **Class** | `{repo_id}::class::{qualified_name}` | `repo::atlas_fixture::class::models.ItemModel` |
| **Function** | `{repo_id}::function::{qualified_name}` | `repo::atlas_fixture::function::services.process_item_workflow` |
| **Method** | `{repo_id}::method::{qualified_name}` | `repo::atlas_fixture::method::models.ItemModel.get_display_name` |
| **Import** | `{repo_id}::import::{path}::L{line}::{name}` | `repo::atlas_fixture::import::services.py::L3::ItemModel` |

### Determinism Guarantees

1. **Repeatability**: Repeated analysis of identical code produces identical IDs.
2. **No Volatile State**: IDs never use memory pointers, UUIDs, filesystem iteration order, or execution timestamps.
3. **Collision Resistance**: Different entity types with identical qualified names (e.g. a module-level function `run` vs a class `run`) have distinct prefixes (`::function::` vs `::class::`).
4. **Namespace Scoping**: All non-repository entities are strictly scoped by `repo_id`.

---

## 4. Path Normalization

Paths are normalized using `normalize_path()`:
- Windows backslashes (`\`) are normalized to forward slashes (`/`).
- Redundant relative prefixes (`./` or `.\`) and leading slashes are stripped.
- Duplicate slashes (`//`) and redundant current-directory markers (`/.`) are resolved.
- Case is preserved to ensure parity across case-sensitive environments.

Example: `.\services\..\services\models.py` becomes `services/models.py`.

---

## 5. Source-Location Conventions

Conforming to P0-07 and `docs/GRAPH_SCHEMA.md`:
- **Line Numbers**: Always **1-indexed** (`start_line >= 1`).
- **Column Numbers**: Always **0-indexed** character/byte offset from the beginning of the line.
- **Byte Offsets**: Always **0-indexed** from the beginning of the source file (`start_byte >= 0`, `end_byte >= start_byte`).
- Represented consistently by `SourcePosition` and `SourceRange`.

---

## 6. Relationships

UCM models typed relationships explicitly:

### 6.1 Supported Relationship Types
- **`CONTAINS`**: Hierarchical containment (`Repository -> File`, `File -> Class`, `File -> Function`, `Class -> Method`).
- **`IMPORTS`**: File/Module import dependency (`File -> Module`).
- **`CALLS`**: Invocations (`Function -> Function`, `Method -> Method`, `Method -> Function`, `Function -> Method`).
- **`INHERITS`**: Class inheritance hierarchy (`Class -> Class`).

### 6.2 Relationship Record Structure
- `rel_type` (`RelationshipType`): Enum representing the relationship type.
- `source_id` (str): Deterministic ID of the source entity.
- `target_id` (str): Deterministic ID of the target entity.
- `location` (`SourceRange | None`): Optional source location evidence of the relationship.
- `metadata` (dict): Optional key-value evidence attributes (e.g. call argument count, alias).

---

## 7. Serialization Format

The top-level `UnifiedCodeModel` container supports lossless JSON serialization:

- `to_dict()` / `from_dict()`: Converts the entire code model into/from plain Python dictionaries.
- `to_json()` / `from_json()`: Serializes to/from deterministic JSON with sorted keys.
- **Round-Trip Fidelity**: Serializing and deserializing preserves all entities, identifiers, line ranges, byte offsets, and relationship records without loss.
- **Zero Third-Party Serialization Overhead**: Implemented strictly using Python's standard library `json` and `dataclasses`.
