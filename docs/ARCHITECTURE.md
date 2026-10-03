# Atlas AI --- Architecture

## 1. System Goal

Atlas AI is an engineering knowledge platform that transforms software
repositories into a structured knowledge graph for repository
understanding and change-impact analysis.

The P0 architecture intentionally excludes AI retrieval and embeddings.
It establishes the deterministic foundation required by later features.

## 2. P0 Architecture

``` text
Python Repository
       |
       v
Repository Scanner
       |
       v
Tree-sitter Parser
       |
       v
Unified Code Model
       |
       v
Relationship Resolver
       |
       v
Neo4j Knowledge Graph
       |
       +----------------------+
       |                      |
       v                      v
Graph Query API         Impact Engine
       |                      |
       +----------+-----------+
                  |
                  v
              FastAPI
                  |
                  v
          Next.js / React UI
                  |
                  v
             React Flow
```

## 3. Component Responsibilities

### Repository Scanner

Discovers source files and provides stable repository-relative paths.

### Tree-sitter Parser

Builds syntax-level representations of Python source files and extracts
relevant declarations and syntax relationships.

Tree-sitter is responsible for parsing syntax. It is not treated as a
complete semantic resolver.

### Unified Code Model

Normalizes extracted constructs into a language-independent internal
representation so later language support can reuse the same graph model.

P0 implements only Python extraction.

### Relationship Resolver

Resolves relationships that require symbol/context information beyond
raw syntax. It must prefer conservative, evidence-backed relationships
over speculative ones.

### Neo4j

Stores the repository knowledge graph and supports graph
traversal/querying.

### Impact Engine

Uses deterministic graph traversal to identify direct and transitive
entities that may be affected by a change.

### FastAPI

Exposes analysis, graph, and impact functionality to the frontend.

### Frontend

Provides the minimum workflow required to demonstrate repository
analysis and graph-based impact analysis.

## 4. Architectural Style

P0 uses a modular monolith.

The codebase is separated into logical modules, but deployed as a small
number of services rather than prematurely introducing distributed
workers.

## 5. Initial Technology Decisions

  Area               Decision
  ------------------ ------------------
  Backend            Python + FastAPI
  Parsing            Tree-sitter
  Graph              Neo4j
  Frontend           Next.js + React
  Graph UI           React Flow
  Containers         Docker Compose
  Initial language   Python
  Architecture       Modular monolith

## 6. Data Flow

1.  User provides a repository.
2.  Scanner discovers Python files.
3.  Parser extracts code entities and source evidence.
4.  Resolver determines reliable relationships.
5.  Graph builder persists entities and relationships in Neo4j.
6.  API exposes graph data and analysis operations.
7.  UI visualizes the graph.
8.  User selects an entity.
9.  Impact engine traverses the graph.
10. UI displays affected entities/files.

## 7. Future Extension Point

After P0, the architecture can extend:

``` text
Neo4j Graph + Vector Index
          |
          v
    Hybrid Retrieval
          |
          v
       GraphRAG
          |
          v
Evidence-grounded LLM response
```

This is not part of P0.
