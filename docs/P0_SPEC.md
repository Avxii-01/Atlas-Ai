# Atlas AI --- P0 Specification

## 1. Purpose

P0 is the first working vertical slice of Atlas AI. Its purpose is to
prove that a software repository can be parsed into a structured
knowledge model, stored in Neo4j, queried for dependencies, and used for
deterministic change-impact analysis.

P0 prioritizes a working end-to-end prototype over breadth, advanced AI,
or production infrastructure.

## 2. P0 Success Criterion

Given a Python repository, Atlas must be able to:

1.  ingest the repository;
2.  parse relevant Python constructs;
3.  normalize extracted entities into a unified model;
4.  resolve reliable relationships;
5.  store the resulting graph in Neo4j;
6.  query dependencies and dependents;
7.  calculate a deterministic dependency blast radius for a selected
    entity;
8.  expose the results through FastAPI;
9.  display the repository structure and impact relationships in a
    minimal web UI.

## 3. In Scope

### Repository ingestion

-   Local/repository input suitable for the prototype
-   Repository scanning
-   Python source-file discovery

### Static extraction

-   Files/modules
-   Classes
-   Functions
-   Methods
-   Imports
-   Relevant inheritance and call relationships where reliably
    resolvable

### Relationship resolution

-   Lightweight symbol-resolution/indexing layer after Tree-sitter
    parsing
-   Evidence-first relationship creation
-   No invented relationships when resolution is ambiguous

### Knowledge graph

-   Neo4j
-   Unified node and relationship model
-   Repository-scoped graph data

### Impact analysis

-   Direct dependencies
-   Direct dependents
-   Transitive dependencies/dependents
-   Affected entities/files
-   BFS/Cypher-based traversal

### Backend

-   Python
-   FastAPI
-   Minimal REST API for analysis, graph retrieval, and impact analysis

### Frontend

-   Next.js/React
-   React Flow for graph visualization
-   Minimal repository → graph → entity → impact workflow

### Validation

-   Controlled Python fixture repository with known ground truth
-   One real Python repository for showcase/validation
-   Basic automated tests

## 4. Explicitly Out of Scope

-   Embeddings
-   Vector search
-   GraphRAG
-   LLM-based explanations
-   Sophisticated risk scoring
-   Multi-language parsing
-   Authentication/OAuth
-   Redis
-   Qdrant
-   Kubernetes
-   Production cloud deployment
-   Advanced observability
-   Large-scale distributed processing
-   Advanced dashboard/analytics

These may be considered after P0.

## 5. P0 Design Principles

1.  Deterministic before generative.
2.  Evidence before inference.
3.  Small vertical slices before broad feature development.
4.  Human-controlled AI-assisted development.
5.  Keep the implementation understandable to the team.
6.  Do not add infrastructure without a demonstrated need.
7.  Preserve source evidence such as file paths and line ranges wherever
    practical.

## 6. P0 Exit Criteria

P0 is complete when the team can perform a repeatable demo:

Python repository → parse → build graph → visualize structure → select
an entity → inspect dependencies/dependents → show deterministic
impact/blast radius.

The prototype must also pass the controlled fixture tests and
successfully process the selected real-world Python showcase repository.
