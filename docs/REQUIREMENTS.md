# Atlas AI --- Requirements

## 1. Functional Requirements

### FR-01 Repository ingestion

The system shall accept a Python repository suitable for analysis.

### FR-02 Source discovery

The system shall identify supported Python source files within the
repository.

### FR-03 Python parsing

The system shall parse supported Python files using Tree-sitter.

### FR-04 Entity extraction

The system shall extract, at minimum: - files/modules; - classes; -
functions; - methods; - imports.

### FR-05 Relationship extraction

The system shall create reliable relationships for supported constructs,
including: - containment; - imports; - calls where resolvable; -
inheritance where resolvable.

### FR-06 Evidence

Extracted entities should retain source evidence including
repository-relative file path and source location where available.

### FR-07 Graph persistence

The system shall persist the normalized model in Neo4j.

### FR-08 Graph retrieval

The system shall retrieve graph nodes and relationships for
visualization.

### FR-09 Dependency analysis

The system shall identify direct and transitive dependencies.

### FR-10 Dependent analysis

The system shall identify direct and transitive dependents.

### FR-11 Impact analysis

For a selected entity, the system shall return the deterministic
dependency blast radius based on graph relationships.

### FR-12 API

The backend shall expose repository analysis, graph retrieval, and
impact analysis operations through FastAPI.

### FR-13 Visualization

The frontend shall visualize repository relationships using React Flow
or an equivalent graph visualization component.

### FR-14 Entity selection

The user shall be able to select an entity in the graph and request
impact analysis.

## 2. Non-Functional Requirements

### NFR-01 Reliability

The system shall avoid creating relationships when the resolver cannot
establish them with sufficient confidence.

### NFR-02 Maintainability

Core parsing, graph construction, API, and impact logic shall remain
modular and testable.

### NFR-03 Explainability

Impact results shall be traceable to graph relationships and source
entities.

### NFR-04 Performance

P0 should be designed for small-to-medium demonstration repositories.
Premature optimization for very large repositories is not required.

### NFR-05 Reproducibility

The development environment shall be reproducible through Docker Compose
where practical.

### NFR-06 Testability

Core extraction, relationship resolution, graph construction, and impact
traversal shall have automated tests.

### NFR-07 Security

P0 shall avoid unnecessary credential/authentication infrastructure and
shall not execute arbitrary repository code as part of static analysis.

## 3. P0 Constraints

-   Python only.
-   No LLM dependency.
-   No embeddings/vector search.
-   No production authentication.
-   No distributed architecture.

## 4. Acceptance Test

A valid P0 implementation can analyze a known Python fixture and produce
the expected graph relationships and expected impact set for predefined
test cases.
