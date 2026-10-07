# Atlas AI --- Architecture Decisions

This document records important decisions for the P0 implementation.
Significant changes should include a reason rather than being made
silently.

## ADR-001 --- Use Neo4j as the P0 Graph Store

**Decision:** Use Neo4j for the initial knowledge graph.

**Reason:** Atlas AI's core P0 problem is graph representation and
traversal. Neo4j provides a direct graph data model and Cypher for
relationship queries.

**Consequence:** The team must learn and maintain Cypher and Neo4j data
modeling.

## ADR-002 --- Use Tree-sitter for Source Parsing

**Decision:** Use Tree-sitter for initial Python syntax parsing.

**Reason:** It provides structured syntax trees suitable for source-code
analysis and leaves room for additional languages later.

**Consequence:** Tree-sitter alone does not provide complete semantic
symbol resolution, so P0 requires a resolver/indexing layer.

## ADR-003 --- Python Only for P0

**Decision:** P0 supports Python only.

**Reason:** Breadth would slow down the first end-to-end prototype.
Python is sufficient to prove the architecture.

**Consequence:** JavaScript/TypeScript support is deferred.

## ADR-004 --- Modular Monolith

**Decision:** Implement P0 as a modular monolith.

**Reason:** The team needs fast iteration and understandable code
without distributed-system overhead.

**Consequence:** Clear module boundaries are important so later
extraction into services remains possible if required.

## ADR-005 --- Deterministic Impact Analysis First

**Decision:** P0 impact analysis is graph-based and deterministic.

**Reason:** It provides an explainable baseline and proves the knowledge
graph has practical value before adding AI.

**Consequence:** LLM explanations and risk scoring are deferred.

## ADR-006 --- Evidence-First Relationship Resolution

**Decision:** Do not create semantic relationships solely from textual
name similarity.

**Reason:** Incorrect graph edges can produce incorrect impact analysis.

**Consequence:** Some relationships may remain unresolved in P0.
Precision is preferred over speculative recall.

## ADR-007 --- Human-Controlled AI Development

**Decision:** Antigravity may generate implementation code, but humans
control requirements, architecture, review, testing, and merge
decisions.

**Reason:** The project is both an engineering system and an academic
project where the team must understand and defend the implementation.

## ADR-008: Python Dependency Management with uv

### Status

Accepted

### Context

Atlas AI is a multi-developer Python project with a growing backend dependency
set including FastAPI, the Neo4j Python driver, Tree-sitter, testing tools,
and future analysis components.

The project needs a dependency-management approach that provides:

- reproducible development environments
- consistent dependency resolution across developers
- compatibility with Docker
- compatibility with CI/CD
- explicit project dependencies
- deterministic dependency versions
- minimal manual environment setup
- a workflow that remains maintainable as the backend grows

The project also follows the principle that dependencies should not be added
without justification.

### Decision

Atlas AI will use:

- `pyproject.toml` as the Python project configuration and dependency declaration
- `uv` as the Python dependency and environment manager
- `uv.lock` as the committed dependency lockfile

These files will live inside the backend project:

```text
backend/
├── pyproject.toml
├── uv.lock
└── ...