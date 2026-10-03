# Atlas AI --- P0 Graph Schema

## 1. Purpose

This document defines the initial Neo4j model for P0.

The schema is intentionally small. It should represent the constructs
required for repository structure, dependency traversal, and basic
impact analysis without attempting to model every semantic aspect of a
programming language.

## 2. Node Types

### Repository

Represents an analyzed repository.

Suggested properties: - `id` - `name` - `source` - `created_at`

### File

Represents a source file.

Suggested properties: - `id` - `path` - `language` - `start_line` -
`end_line`

### Module

Represents a Python module where useful for import/module semantics.

Suggested properties: - `id` - `name` - `qualified_name` - `file_path`

### Class

Suggested properties: - `id` - `name` - `qualified_name` - `file_path` -
`start_line` - `end_line` - `language`

### Function

Suggested properties: - `id` - `name` - `qualified_name` - `file_path` -
`start_line` - `end_line` - `language`

### Method

Suggested properties: - `id` - `name` - `qualified_name` - `file_path` -
`start_line` - `end_line` - `language`

### Import

An optional explicit import node may be used if the implementation
benefits from preserving import declarations as first-class entities.
The implementation may instead normalize imports directly into
relationships where appropriate.

## 3. Relationships

### Repository → File

``` text
(:Repository)-[:CONTAINS]->(:File)
```

### File → Class

``` text
(:File)-[:CONTAINS]->(:Class)
```

### File → Function

``` text
(:File)-[:CONTAINS]->(:Function)
```

### Class → Method

``` text
(:Class)-[:CONTAINS]->(:Method)
```

### File/Module → Imported Module

``` text
(:File)-[:IMPORTS]->(:Module)
```

### Function/Method → Function/Method

``` text
(:Function)-[:CALLS]->(:Function)
(:Method)-[:CALLS]->(:Function)
(:Method)-[:CALLS]->(:Method)
```

### Class → Class

``` text
(:Class)-[:INHERITS]->(:Class)
```

## 4. Identity

Every entity should have a stable identifier within an analyzed
repository.

A recommended identity approach is based on: - repository identity; -
entity type; - qualified name; - source path/location where necessary.

Example:

``` text
repository_id + "::" + qualified_name + "::" + entity_type
```

The exact implementation may evolve, but identifiers must be
deterministic for repeated analysis of the same repository state.

## 5. Source Evidence

Where available, entities and relationships should preserve: -
repository-relative path; - start line; - end line; - qualified name; -
relationship evidence/source location.

This supports later evidence-grounded explanations.

## 6. Relationship Resolution Rule

Tree-sitter syntax alone is insufficient to guarantee semantic
cross-file relationships.

Therefore:

``` text
Tree-sitter
    ↓
Syntax extraction
    ↓
Symbol/index information
    ↓
Relationship resolution
    ↓
Neo4j
```

The resolver must not invent a `CALLS`, `IMPORTS`, or `INHERITS`
relationship merely because a name looks similar.

## 7. Future Relationships

Possible later relationships include: - `REFERENCES` - `INSTANTIATES` -
`TESTS` - `MODIFIES` - `OVERRIDES`

These are deliberately excluded from the initial required P0 schema
unless implementation needs justify them.
