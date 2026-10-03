# Atlas AI --- Testing Strategy

## 1. Testing Goal

P0 testing must establish that Atlas extracts the expected repository
structure and produces correct deterministic graph-based impact results.

## 2. Test Layers

### Unit tests

Test individual components: - repository scanner; - Tree-sitter
extraction; - symbol/index construction; - relationship resolver; -
graph query builders; - impact traversal logic.

### Integration tests

Verify: - parser output can be persisted to Neo4j; - graph queries
return expected relationships; - impact analysis works against a real
Neo4j instance; - FastAPI endpoints return expected results.

### End-to-end test

Verify the complete flow:

``` text
Fixture repository
→ scan
→ parse
→ resolve
→ Neo4j
→ API
→ impact result
```

## 3. Controlled Fixture Repository

The fixture repository is the primary correctness oracle for P0.

It should contain intentionally known relationships such as:

``` text
main
 ↓
user_service
 ↓
user_repository
 ↓
database
```

and independent components to test that unrelated entities are not
included in the impact set.

## 4. Ground Truth

For each fixture scenario, define expected: - nodes; - relationships; -
direct dependents; - transitive dependents; - affected files.

The test should compare actual output against this ground truth.

## 5. Negative Cases

Tests must include cases where: - a symbol cannot be resolved; - an
import target does not exist; - a call is ambiguous; - nested
definitions exist; - unrelated functions share the same name.

The expected behavior in ambiguous cases is conservative handling rather
than speculative relationship creation.

## 6. Demo Repository Validation

After the fixture passes, validate against one real Python repository.

The real repository is used to demonstrate usefulness and robustness,
while the fixture remains the primary correctness benchmark for
deterministic behavior.

## 7. P0 Definition of Done

A P0 feature is complete only when: - implementation exists; - relevant
tests pass; - API behavior is documented if applicable; - graph behavior
is documented if applicable; - the feature has been manually verified in
the integrated prototype.
