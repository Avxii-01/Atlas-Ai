# Atlas AI --- P0 Development Plan

## Phase 0 --- Foundation

-   Repository structure
-   Docker Compose
-   Neo4j
-   FastAPI skeleton
-   Frontend skeleton
-   Environment configuration
-   Basic health checks

## Phase 1 --- Repository Parsing

-   Repository scanner
-   Python file discovery
-   Tree-sitter integration
-   File/module extraction
-   Class extraction
-   Function/method extraction
-   Import extraction
-   Source-location metadata

## Phase 2 --- Relationship Resolution

-   Symbol index
-   Import resolution
-   Containment relationships
-   Reliable call resolution
-   Inheritance resolution
-   Conservative unresolved-symbol handling

## Phase 3 --- Neo4j Graph

-   Graph schema implementation
-   Node upsert
-   Relationship upsert
-   Repository isolation
-   Graph retrieval query

## Phase 4 --- Impact Engine

-   Dependency traversal
-   Dependent traversal
-   BFS/multi-hop traversal
-   Affected-file aggregation
-   Impact response model
-   Fixture-based correctness tests

## Phase 5 --- API

-   Repository analysis endpoint
-   Graph endpoint
-   Impact endpoint
-   Validation/error handling
-   API integration tests

## Phase 6 --- Minimal UI

-   Repository input
-   Analysis status
-   Graph view
-   Entity selection
-   Impact view
-   Basic navigation/error states

## Phase 7 --- Validation

-   Controlled fixture repository
-   Expected graph assertions
-   Expected impact assertions
-   Real Python showcase repository
-   Demo rehearsal
-   Failure/fallback plan

## P0 Rule

A phase is not a reason to add unrelated features. Every implementation
task must trace back to the P0 success criterion.

## After P0

Potential next stages: 1. embeddings/vector retrieval; 2. hybrid graph +
vector retrieval; 3. evidence-grounded LLM/GraphRAG; 4. richer
impact/risk analysis; 5. additional language support; 6. evaluation and
performance benchmarking.

These are not P0 commitments.
