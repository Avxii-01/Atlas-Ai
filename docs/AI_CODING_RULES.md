# Atlas AI --- AI-Assisted Development Rules

## 1. Principle

AI coding tools such as Antigravity are development assistants. They do
not own the architecture, requirements, or engineering decisions of
Atlas AI.

Humans remain responsible for: - requirements; - architecture; -
security; - correctness; - review; - integration; - final decisions.

## 2. Standard Workflow

``` text
Human requirement
      ↓
Task design
      ↓
Antigravity implementation
      ↓
Human code review
      ↓
Automated tests
      ↓
Integration test
      ↓
Documentation update
      ↓
Commit
```

## 3. Prompt Scope

Do not ask an AI coding tool to build the entire project in one prompt.

Prefer small tasks such as: - create Neo4j connection module; -
implement Python file scanner; - extract function declarations; - add
one relationship resolver; - add one API endpoint; - write tests for one
component.

## 4. Architecture Control

AI-generated code must follow the existing project architecture.

AI tools must not introduce: - a new database; - a new message queue; -
a new framework; - a new service boundary; - a new dependency;

without an explicit human decision.

## 5. Code Quality

Generated code must: - be readable; - use clear names; - have
appropriate type hints; - handle expected errors; - avoid unnecessary
abstraction; - avoid duplicated logic; - include tests for important
behavior.

## 6. Explainability

For non-trivial generated code, the developer must be able to explain: -
what it does; - why it exists; - its inputs and outputs; - important
assumptions; - failure cases; - performance implications.

If the team cannot explain the code, it should not be merged unchanged.

## 7. Testing

No significant feature is considered complete without appropriate tests.

Parser and resolver changes must include cases covering: - valid
syntax; - expected extraction; - ambiguous/unresolvable cases; -
relationship correctness.

## 8. Documentation

When behavior or architecture changes, update the relevant
documentation.

At minimum: - architecture changes → `ARCHITECTURE.md` / decisions; -
graph changes → `GRAPH_SCHEMA.md`; - API changes → `API.md`; -
requirements/scope changes → `REQUIREMENTS.md` / `P0_SPEC.md`.

## 9. Git Discipline

Prefer small commits with meaningful messages.

Examples:

``` text
feat(parser): extract python functions
feat(graph): persist class containment
feat(impact): add dependent traversal
test(parser): cover nested functions
docs(graph): document call relationship
```

Avoid giant commits containing unrelated changes.

## 10. AI Output Review Checklist

Before merging AI-generated code:

-   [ ] Does it match the requirement?
-   [ ] Does it respect the current architecture?
-   [ ] Are dependencies justified?
-   [ ] Is error handling appropriate?
-   [ ] Are tests present?
-   [ ] Is the implementation understandable?
-   [ ] Are performance implications understood?
-   [ ] Is documentation updated?
-   [ ] Does the feature remain inside P0 scope?

## 11. Scope Protection

AI tools must not silently expand P0.

If implementation suggests: - embeddings; - LLM calls; - vector
databases; - authentication; - distributed workers; - additional
languages;

stop and raise the decision with the technical lead.
