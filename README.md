# Atlas AI

> An engineering knowledge platform that transforms software
> repositories into a structured knowledge graph for code understanding,
> dependency analysis, and change-impact assessment.

Atlas AI analyzes software repositories, extracts their structural
relationships, and represents them as a knowledge graph. This graph
enables developers to understand how components of a codebase are
connected and determine which components may be affected when a
function, class, or other code entity changes.

The project is being developed as an academic major project with a focus
on building the system incrementally, validating each layer, and
establishing a deterministic foundation before introducing AI-powered
capabilities.

------------------------------------------------------------------------

## Project Status

**Current Phase:** P0 --- Repository → Knowledge Graph → Impact Analysis

P0 is the first working vertical slice of Atlas AI.

The current goal is to demonstrate the complete deterministic pipeline:

``` text
Python Repository
       ↓
Repository Scanner
       ↓
Tree-sitter Parser
       ↓
Unified Code Model
       ↓
Relationship Resolver
       ↓
Neo4j Knowledge Graph
       ↓
 ┌───────────────┐
 ↓               ↓
Graph Queries   Impact Engine
 ↓               ↓
 └───────┬───────┘
         ↓
      FastAPI
         ↓
   React / React Flow
```

### P0 Success Criterion

Given a Python repository, Atlas AI should be able to:

1.  Parse the repository.
2.  Extract relevant code entities and relationships.
3.  Build a structured knowledge graph in Neo4j.
4.  Query dependencies and dependents.
5.  Select a code entity and determine its dependency blast radius.
6.  Visualize repository structure and impact relationships through a
    minimal web interface.

------------------------------------------------------------------------

## Problem

Modern software repositories contain a large amount of architectural and
dependency information, but that information is distributed across
source files and is difficult to understand as a whole.

Traditional development tools provide capabilities such as:

-   code and text search;
-   file navigation;
-   version control;
-   static analysis.

However, questions such as:

> What depends on this function?

or:

> If I modify this class, what parts of the repository could be
> affected?

often require developers to manually trace relationships across multiple
files.

Atlas AI aims to make these relationships explicit by transforming
repository structure into a queryable knowledge graph.

------------------------------------------------------------------------

## Vision

The long-term vision of Atlas AI is to evolve from a deterministic
repository graph into an engineering intelligence layer.

``` text
Software Repository
        ↓
Code Analysis
        ↓
Knowledge Graph
        +
Semantic Representation
        ↓
Hybrid Retrieval
        ↓
GraphRAG
        ↓
Evidence-Grounded AI
```

Future capabilities may include:

-   semantic code search;
-   graph + vector retrieval;
-   evidence-grounded repository Q&A;
-   architecture understanding;
-   richer change-impact analysis;
-   risk assessment;
-   support for additional programming languages.

These capabilities are **not part of the current P0 scope**.

------------------------------------------------------------------------

## P0 Architecture

The initial architecture is intentionally simple and deterministic:

``` text
                    ┌─────────────────────┐
                    │  Python Repository  │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │ Repository Scanner  │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │   Tree-sitter AST   │
                    │       Parsing       │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │ Unified Code Model  │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │    Relationship     │
                    │      Resolver       │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │  Neo4j Knowledge    │
                    │       Graph         │
                    └───────┬─────┬───────┘
                            │     │
                    ┌───────┘     └────────┐
                    ▼                       ▼
             ┌─────────────┐       ┌───────────────┐
             │ Graph Query │       │ Impact Engine │
             └──────┬──────┘       └───────┬───────┘
                    │                       │
                    └───────────┬───────────┘
                                ▼
                         ┌────────────┐
                         │  FastAPI   │
                         └─────┬──────┘
                               │
                               ▼
                     ┌──────────────────┐
                     │ React / React    │
                     │      Flow        │
                     └──────────────────┘
```

P0 uses a **modular monolith** architecture to keep the system
understandable and easy to develop.

------------------------------------------------------------------------

## Core Technology Stack

  Layer                     Technology
  ------------------------- ------------------
  Backend                   Python
  API                       FastAPI
  Code Parsing              Tree-sitter
  Graph Database            Neo4j
  Frontend                  Next.js / React
  Graph Visualization       React Flow
  Development Environment   Docker Compose
  Initial Language          Python
  Architecture              Modular Monolith

------------------------------------------------------------------------

## P0 Code Model

The initial graph represents the important structural elements of a
Python repository.

### Entities

``` text
Repository
File
Module
Class
Function
Method
```

### Relationships

``` text
Repository ──CONTAINS──> File

File ──CONTAINS──> Class
File ──CONTAINS──> Function

Class ──CONTAINS──> Method

File ──IMPORTS──> Module

Function ──CALLS──> Function
Method ──CALLS──> Function
Method ──CALLS──> Method

Class ──INHERITS──> Class
```

The complete graph model is documented in:

[`docs/GRAPH_SCHEMA.md`](docs/GRAPH_SCHEMA.md)

------------------------------------------------------------------------

## Change-Impact Analysis

P0 implements a deterministic graph-based impact analysis engine.

For example:

``` text
Controller
    │
    ▼
Service
    │
    ▼
Repository
    │
    ▼
Database
```

If the `Repository` component is modified, Atlas AI can traverse the
graph in the dependent direction and identify components that may be
affected.

P0 focuses on:

-   direct dependencies;
-   direct dependents;
-   transitive dependencies;
-   transitive dependents;
-   affected entities;
-   affected files.

The goal is to establish an explainable graph-based baseline before
introducing AI-based reasoning.

------------------------------------------------------------------------

## P0 Scope

### Included

-   Python repository ingestion
-   Repository scanning
-   Tree-sitter parsing
-   Code entity extraction
-   Relationship resolution
-   Neo4j graph construction
-   Dependency queries
-   Dependent queries
-   Deterministic impact analysis
-   FastAPI backend
-   Minimal React/React Flow interface
-   Controlled test repository
-   Real Python repository validation
-   Automated testing
-   Engineering documentation

### Not Included

The following are intentionally outside the P0 scope:

-   Embeddings
-   Vector search
-   GraphRAG
-   LLM-based explanations
-   Sophisticated risk scoring
-   Multi-language parsing
-   OAuth/authentication
-   Redis
-   Qdrant
-   Kubernetes
-   Production cloud infrastructure
-   Distributed processing
-   Advanced analytics/dashboard features

These may be considered in later development phases.

------------------------------------------------------------------------

## Development Principles

### 1. Deterministic Before Generative

The repository graph and impact engine must work without an LLM.

This gives Atlas AI a reliable foundation for future AI capabilities.

### 2. Evidence Before Inference

Relationships should be created from repository evidence.

The system should avoid inventing relationships when they cannot be
reliably resolved.

### 3. Small Vertical Slices

Features should be implemented, tested, documented, and integrated
incrementally.

### 4. Human-Controlled AI Development

AI coding tools such as Antigravity may assist with implementation, but
humans remain responsible for:

-   requirements;
-   architecture;
-   code review;
-   testing;
-   security;
-   integration;
-   final decisions.

See [`docs/AI_CODING_RULES.md`](docs/AI_CODING_RULES.md).

### 5. Avoid Premature Infrastructure

P0 intentionally avoids introducing infrastructure that is not required
to demonstrate the core system.

------------------------------------------------------------------------

## Development Workflow

Atlas AI follows the following engineering workflow:

``` text
Requirement
    ↓
GitHub Issue
    ↓
Task Design
    ↓
Implementation
    ↓
Code Review
    ↓
Automated Tests
    ↓
Integration Test
    ↓
Documentation
    ↓
Commit / Pull Request
```

AI-generated code is reviewed and validated by the development team
before integration.

------------------------------------------------------------------------

## Repository Structure

``` text
Atlas-Ai/
│
├── backend/
│   └── ...
│
├── frontend/
│   └── ...
│
├── docs/
│   ├── P0_SPEC.md
│   ├── ARCHITECTURE.md
│   ├── REQUIREMENTS.md
│   ├── GRAPH_SCHEMA.md
│   ├── API.md
│   ├── AI_CODING_RULES.md
│   ├── TESTING.md
│   ├── DECISIONS.md
│   └── DEVELOPMENT_PLAN.md
│
├── documentation/
│   └── ...
│
└── README.md
```

------------------------------------------------------------------------

## Documentation

The `docs/` directory contains the project's technical source of truth.

  ---------------------------------------------------------------------------------------
  Document                                            Purpose
  --------------------------------------------------- -----------------------------------
  [`P0_SPEC.md`](docs/P0_SPEC.md)                     Frozen P0 scope and success
                                                      criteria

  [`ARCHITECTURE.md`](docs/ARCHITECTURE.md)           System architecture and component
                                                      responsibilities

  [`REQUIREMENTS.md`](docs/REQUIREMENTS.md)           Functional and non-functional
                                                      requirements

  [`GRAPH_SCHEMA.md`](docs/GRAPH_SCHEMA.md)           Neo4j nodes, relationships, and
                                                      identity model

  [`API.md`](docs/API.md)                             P0 backend API contract

  [`AI_CODING_RULES.md`](docs/AI_CODING_RULES.md)     Rules for AI-assisted development

  [`TESTING.md`](docs/TESTING.md)                     Testing strategy and validation
                                                      approach

  [`DECISIONS.md`](docs/DECISIONS.md)                 Important architecture decisions

  [`DEVELOPMENT_PLAN.md`](docs/DEVELOPMENT_PLAN.md)   P0 implementation phases

  [`DEVELOPMENT_SETUP.md`](docs/DEVELOPMENT_SETUP.md) Local Docker Compose development setup
  ---------------------------------------------------------------------------------------

------------------------------------------------------------------------

## Testing Strategy

P0 uses a controlled test repository as the primary correctness
benchmark.

The test repository contains intentionally known relationships so that
the expected graph and impact results can be compared against the actual
output.

Testing is performed at multiple levels:

``` text
Unit Tests
    ↓
Integration Tests
    ↓
End-to-End Tests
    ↓
Real Repository Validation
```

The controlled fixture establishes correctness, while a real Python
repository is used to validate the prototype against a more realistic
codebase.

See [`docs/TESTING.md`](docs/TESTING.md).

------------------------------------------------------------------------

## P0 Definition of Done

P0 is complete when the following workflow works end-to-end:

``` text
Python Repository
        ↓
      Parse
        ↓
 Build Knowledge Graph
        ↓
 Visualize Structure
        ↓
  Select Entity
        ↓
Query Dependencies
        ↓
 Calculate Impact
        ↓
Display Affected Components
```

The implementation must also:

-   pass the controlled fixture tests;
-   successfully build the expected graph;
-   correctly calculate predefined impact cases;
-   expose the functionality through the backend API;
-   demonstrate the workflow through the frontend;
-   successfully analyze the selected real-world Python showcase
    repository.

------------------------------------------------------------------------

## Future Development

Once P0 is stable, development can progress toward:

### Phase 1 --- Semantic Retrieval

Introduce code embeddings and semantic search.

### Phase 2 --- Hybrid Retrieval

Combine graph relationships with vector similarity.

``` text
Knowledge Graph
       +
Vector Search
       ↓
Hybrid Retrieval
```

### Phase 3 --- GraphRAG

Use the structured graph and retrieved repository evidence to provide
contextual AI responses.

### Phase 4 --- Evidence-Grounded AI

Enable natural-language repository questions while grounding responses
in actual repository entities, relationships, and source evidence.

### Phase 5 --- Advanced Impact Intelligence

Potentially introduce:

-   richer impact analysis;
-   risk scoring;
-   historical change information;
-   additional evidence signals;
-   support for additional programming languages.

These phases will be evaluated after the P0 foundation is stable.

------------------------------------------------------------------------

## Project Status

**Atlas AI is currently under active development.**

**Current milestone:**

> **P0 --- Repository → Knowledge Graph → Impact Analysis**

The immediate priority is to build and validate the deterministic core
before expanding into semantic retrieval and AI-powered capabilities.

------------------------------------------------------------------------

## License

License information will be added when the project license is finalized.
