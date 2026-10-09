"""Automated tests for Neo4j code graph traversal (P0-16).

Verifies direct and transitive dependency and dependent traversal, depth bounds,
cycle and duplicate handling, repository isolation, session lifecycles, and
ground-truth fixture conformance.
"""

from collections import deque
from pathlib import Path
import re
from unittest.mock import MagicMock
import pytest
from neo4j import Driver, Session

from app.db.neo4j import Neo4jConnectionError, set_driver
from app.graph.traversal import (
    ALL_ALLOWED_RELATIONSHIPS,
    DEFAULT_DEPENDENCY_RELATIONSHIPS,
    DEFAULT_TRANSITIVE_MAX_DEPTH,
    GraphTraversal,
    GraphTraversalError,
    TraversalDirection,
    TraversalNode,
    TraversalResult,
    build_traversal_cypher,
    get_dependencies,
    get_dependents,
    get_direct_dependencies,
    get_direct_dependents,
    get_transitive_dependencies,
    get_transitive_dependents,
    validate_depth,
    validate_relationship_types,
)
from app.resolver.relationship_resolver import resolve_repository
from app.ucm.entities import Function
from app.ucm.relationships import RelationshipType

FIXTURE_DIR = Path(__file__).resolve().parent.parent.parent / "tests" / "fixtures" / "atlas_fixture"


@pytest.fixture(autouse=True)
def reset_driver_state():
    """Ensure driver state is reset before and after every test."""
    set_driver(None)
    yield
    set_driver(None)


class GraphSimulatorSession:
    """Mock Neo4j session simulating Cypher execution over an in-memory graph.

    Accurately models Cypher's MATCH ... OPTIONAL MATCH ... WITH shortest path logic,
    repository scoping, cycle safety, self-loop elimination, and deterministic sorting.
    """

    def __init__(self):
        self.nodes: dict[str, dict] = {}
        self.edges: list[dict] = []
        self.executed_queries: list[tuple[str, dict]] = []
        self.close_called: bool = False

    def add_node(
        self,
        node_id: str,
        repo_id: str,
        labels: list[str],
        props: dict | None = None,
    ) -> None:
        clean_props = dict(props or {})
        clean_props.setdefault("id", node_id)
        clean_props.setdefault("repo_id", repo_id)
        self.nodes[node_id] = {
            "id": node_id,
            "repo_id": repo_id,
            "labels": list(labels),
            "props": clean_props,
        }

    def add_edge(
        self,
        source_id: str,
        target_id: str,
        rel_type: str,
        props: dict | None = None,
    ) -> None:
        self.edges.append({
            "source_id": source_id,
            "target_id": target_id,
            "rel_type": rel_type,
            "props": dict(props or {}),
        })

    def close(self) -> None:
        self.close_called = True

    def run(self, query: str, **params):
        self.executed_queries.append((query, params))
        entity_id = params.get("entity_id")
        repo_id = params.get("repo_id")

        start_node = self.nodes.get(entity_id)
        if not start_node:
            mock_res = MagicMock()
            mock_res.__iter__.return_value = []
            return mock_res

        # Repository scoping check on start entity
        is_repo_node = "Repository" in start_node["labels"]
        start_in_repo = (
            start_node["id"] == repo_id if is_repo_node else start_node["repo_id"] == repo_id
        )
        if not start_in_repo:
            mock_res = MagicMock()
            mock_res.__iter__.return_value = []
            return mock_res

        is_reverse = "<-[" in query
        m = re.search(r":([A-Z|]+)\*1\.\.(\d+)", query)
        if not m:
            raise ValueError(f"Unable to parse relationship pattern from query: {query}")
        allowed_rels = set(m.group(1).split("|"))
        max_depth = int(m.group(2))

        # BFS shortest-path exploration
        visited_depth: dict[str, int] = {}
        shortest_path_rels: dict[str, list[str]] = {}
        queue: deque[tuple[str, int, list[str]]] = deque([(entity_id, 0, [])])

        while queue:
            curr_id, depth, path_rels = queue.popleft()
            if depth >= max_depth:
                continue

            for edge in self.edges:
                if edge["rel_type"] not in allowed_rels:
                    continue

                if not is_reverse:
                    if edge["source_id"] == curr_id:
                        nxt_id = edge["target_id"]
                        nxt_rel = edge["rel_type"]
                    else:
                        continue
                else:
                    if edge["target_id"] == curr_id:
                        nxt_id = edge["source_id"]
                        nxt_rel = edge["rel_type"]
                    else:
                        continue

                # Repository isolation: intermediate and target nodes must belong to requested repo
                nxt_node = self.nodes.get(nxt_id)
                if not nxt_node:
                    continue
                nxt_is_repo = "Repository" in nxt_node["labels"]
                nxt_in_repo = (
                    nxt_node["id"] == repo_id if nxt_is_repo else nxt_node["repo_id"] == repo_id
                )
                if not nxt_in_repo:
                    continue

                new_depth = depth + 1
                if nxt_id not in visited_depth or new_depth < visited_depth[nxt_id]:
                    visited_depth[nxt_id] = new_depth
                    shortest_path_rels[nxt_id] = path_rels + [nxt_rel]
                    queue.append((nxt_id, new_depth, path_rels + [nxt_rel]))

        # The starting entity must never be returned in its own results
        visited_depth.pop(entity_id, None)

        if not visited_depth:
            # OPTIONAL MATCH yielded no target: 1 record with null target and start_id present
            record = {
                "entity_id": None,
                "labels": None,
                "properties": None,
                "depth": None,
                "rel_types": [],
                "start_id": entity_id,
            }
            mock_res = MagicMock()
            mock_res.__iter__.return_value = [record]
            return mock_res

        records = []
        for target_id, depth in visited_depth.items():
            t_node = self.nodes[target_id]
            records.append({
                "entity_id": target_id,
                "labels": t_node["labels"],
                "properties": t_node["props"],
                "depth": depth,
                "rel_types": shortest_path_rels[target_id],
                "start_id": entity_id,
            })

        # ORDER BY depth ASC, entity_id ASC
        records.sort(key=lambda r: (r["depth"], r["entity_id"]))
        mock_res = MagicMock()
        mock_res.__iter__.return_value = records
        return mock_res


# ==============================================================================
# 1. Parameter Validation Tests
# ==============================================================================


def test_validate_depth_success_and_failures():
    """Verify validate_depth accepts positive integers and rejects non-integers and <= 0."""
    assert validate_depth(1) == 1
    assert validate_depth(2) == 2
    assert validate_depth(10) == 10

    for invalid in [0, -1, -10, True, False, 1.5, "1", None, []]:
        with pytest.raises(ValueError, match="Traversal depth must be an integer >= 1"):
            validate_depth(invalid)  # type: ignore


def test_validate_relationship_types():
    """Verify validate_relationship_types enforces internal allowlist and defaults."""
    # Default returns CALLS, IMPORTS, INHERITS (CONTAINS excluded)
    assert validate_relationship_types(None) == DEFAULT_DEPENDENCY_RELATIONSHIPS

    # Explicit subset
    assert validate_relationship_types([RelationshipType.CALLS]) == ("CALLS",)
    assert validate_relationship_types(["calls", "IMPORTS"]) == ("CALLS", "IMPORTS")
    assert validate_relationship_types([RelationshipType.CONTAINS]) == ("CONTAINS",)

    # Empty collection rejected
    with pytest.raises(ValueError, match="relationship_types must not be empty"):
        validate_relationship_types([])

    # Unsupported types rejected
    with pytest.raises(ValueError, match="Unsupported relationship type"):
        validate_relationship_types(["CUSTOM_EDGE"])


def test_invalid_entity_id_and_repo_id_rejected():
    """Verify empty or non-string entity_id and repo_id raise ValueError."""
    traversal = GraphTraversal()
    sim = GraphSimulatorSession()

    with pytest.raises(ValueError, match="entity_id must be a non-empty string"):
        traversal.get_dependencies("", repo_id="repo::1", session=sim)

    with pytest.raises(ValueError, match="entity_id must be a non-empty string"):
        traversal.get_dependencies(None, repo_id="repo::1", session=sim)  # type: ignore

    with pytest.raises(ValueError, match="repo_id must be a non-empty string"):
        traversal.get_dependencies("repo::1::func::foo", repo_id="", session=sim)

    with pytest.raises(ValueError, match="repo_id must be provided or inferrable"):
        traversal.get_dependencies("unprefixed_entity", repo_id=None, session=sim)


# ==============================================================================
# 2. Direction and Reachability Tests (A -> B -> C)
# ==============================================================================


def test_direction_and_reachability_chain_abc():
    """Explicitly verify A -> B -> C traversal semantics:

    - Dependencies of A at depth 1 contain B but not C.
    - Dependencies of A at depth 2 contain B and C.
    - Dependents of C at depth 1 contain B but not A.
    - Dependents of C at depth 2 contain B and A.
    """
    sim = GraphSimulatorSession()
    sim.add_node("node::A", "repo::test", ["Function"], {"name": "A"})
    sim.add_node("node::B", "repo::test", ["Function"], {"name": "B"})
    sim.add_node("node::C", "repo::test", ["Function"], {"name": "C"})

    sim.add_edge("node::A", "node::B", "CALLS")
    sim.add_edge("node::B", "node::C", "CALLS")

    traversal = GraphTraversal()

    # 1. Outgoing dependencies of A at depth 1: B only
    res_a1 = traversal.get_dependencies("node::A", repo_id="repo::test", max_depth=1, session=sim)
    assert res_a1.entity_ids == ["node::B"]
    assert len(res_a1) == 1
    assert res_a1[0].entity_id == "node::B"
    assert res_a1[0].depth == 1
    assert res_a1[0].path_relationship_types == ("CALLS",)

    # 2. Outgoing dependencies of A at depth 2: B and C
    res_a2 = traversal.get_dependencies("node::A", repo_id="repo::test", max_depth=2, session=sim)
    assert res_a2.entity_ids == ["node::B", "node::C"]
    assert len(res_a2) == 2
    assert res_a2.get_node("node::B").depth == 1
    assert res_a2.get_node("node::C").depth == 2
    assert res_a2.get_node("node::C").path_relationship_types == ("CALLS", "CALLS")

    # Verify grouping by depth
    by_depth_a = res_a2.by_depth
    assert [n.entity_id for n in by_depth_a[1]] == ["node::B"]
    assert [n.entity_id for n in by_depth_a[2]] == ["node::C"]

    # 3. Incoming dependents of C at depth 1: B only
    res_c1 = traversal.get_dependents("node::C", repo_id="repo::test", max_depth=1, session=sim)
    assert res_c1.entity_ids == ["node::B"]
    assert len(res_c1) == 1
    assert res_c1[0].depth == 1

    # 4. Incoming dependents of C at depth 2: B and A
    res_c2 = traversal.get_dependents("node::C", repo_id="repo::test", max_depth=2, session=sim)
    assert res_c2.entity_ids == ["node::B", "node::A"]
    assert res_c2.get_node("node::B").depth == 1
    assert res_c2.get_node("node::A").depth == 2


# ==============================================================================
# 3. Depth Limits Tests
# ==============================================================================


def test_traversal_depth_chain_five_hops():
    """Verify deep linear chain respects max_depth bounds strictly."""
    sim = GraphSimulatorSession()
    repo = "repo::chain"
    for i in range(1, 6):
        sim.add_node(f"node::{i}", repo, ["Function"])

    # 1 -> 2 -> 3 -> 4 -> 5
    for i in range(1, 5):
        sim.add_edge(f"node::{i}", f"node::{i+1}", "CALLS")

    traversal = GraphTraversal()

    res_1 = traversal.get_dependencies("node::1", repo_id=repo, max_depth=1, session=sim)
    assert res_1.entity_ids == ["node::2"]

    res_2 = traversal.get_dependencies("node::1", repo_id=repo, max_depth=2, session=sim)
    assert res_2.entity_ids == ["node::2", "node::3"]

    res_3 = traversal.get_dependencies("node::1", repo_id=repo, max_depth=3, session=sim)
    assert res_3.entity_ids == ["node::2", "node::3", "node::4"]

    res_4 = traversal.get_dependencies("node::1", repo_id=repo, max_depth=4, session=sim)
    assert res_4.entity_ids == ["node::2", "node::3", "node::4", "node::5"]

    # max_depth 10 on a 4-hop chain stops naturally at node::5 without error
    res_10 = traversal.get_dependencies("node::1", repo_id=repo, max_depth=10, session=sim)
    assert res_10.entity_ids == ["node::2", "node::3", "node::4", "node::5"]


# ==============================================================================
# 4. Cycles and Deduplication Tests
# ==============================================================================


def test_cycle_termination_and_start_entity_exclusion():
    """Verify cyclic paths terminate safely and never return the starting entity."""
    sim = GraphSimulatorSession()
    repo = "repo::cycles"
    sim.add_node("node::X", repo, ["Function"])
    sim.add_node("node::Y", repo, ["Function"])
    sim.add_node("node::Z", repo, ["Function"])

    # Cycle: X -> Y -> Z -> X
    sim.add_edge("node::X", "node::Y", "CALLS")
    sim.add_edge("node::Y", "node::Z", "CALLS")
    sim.add_edge("node::Z", "node::X", "CALLS")

    traversal = GraphTraversal()

    # Traversal from X at depth 5
    res = traversal.get_dependencies("node::X", repo_id=repo, max_depth=5, session=sim)
    assert res.entity_ids == ["node::Y", "node::Z"]
    assert "node::X" not in res.entity_ids
    assert res.get_node("node::Y").depth == 1
    assert res.get_node("node::Z").depth == 2


def test_self_loop_exclusion():
    """Verify self-referential relationships (A -> A) do not return the starting entity."""
    sim = GraphSimulatorSession()
    repo = "repo::self"
    sim.add_node("node::Self", repo, ["Function"])
    sim.add_edge("node::Self", "node::Self", "CALLS")

    traversal = GraphTraversal()
    res = traversal.get_dependencies("node::Self", repo_id=repo, max_depth=3, session=sim)
    assert res.entity_ids == []
    assert len(res) == 0
    assert res.start_entity_found is True


def test_diamond_multiple_paths_deduplication_and_shortest_path():
    """Verify multiple paths to the same target entity preserve shortest depth without duplication."""
    sim = GraphSimulatorSession()
    repo = "repo::diamond"
    sim.add_node("A", repo, ["Function"])
    sim.add_node("B", repo, ["Function"])
    sim.add_node("C", repo, ["Function"])
    sim.add_node("D", repo, ["Function"])

    # Paths:
    # A -> B -> D (length 2)
    # A -> C -> D (length 2)
    # A -> D (length 1 direct)
    sim.add_edge("A", "B", "CALLS")
    sim.add_edge("B", "D", "CALLS")
    sim.add_edge("A", "C", "CALLS")
    sim.add_edge("C", "D", "CALLS")
    sim.add_edge("A", "D", "CALLS")

    traversal = GraphTraversal()
    res = traversal.get_dependencies("A", repo_id=repo, max_depth=3, session=sim)

    # Reached nodes must be [B, C, D] all at depth 1
    assert res.entity_ids == ["B", "C", "D"]
    assert res.get_node("D").depth == 1
    assert len([n for n in res.nodes if n.entity_id == "D"]) == 1


# ==============================================================================
# 5. Repository Isolation and Missing Data Tests
# ==============================================================================


def test_repository_isolation_cross_repository_edges_prevented():
    """Verify traversal strictly never crosses repository boundaries."""
    sim = GraphSimulatorSession()
    # Repo 1 nodes
    sim.add_node("repo::1::func::a", "repo::1", ["Function"])
    sim.add_node("repo::1::func::c", "repo::1", ["Function"])

    # Repo 2 node
    sim.add_node("repo::2::func::b", "repo::2", ["Function"])

    # Edge from repo::1 to repo::2, and repo::2 to repo::1
    sim.add_edge("repo::1::func::a", "repo::2::func::b", "CALLS")
    sim.add_edge("repo::2::func::b", "repo::1::func::c", "CALLS")

    traversal = GraphTraversal()

    # Traversal from repo::1 must NOT follow cross-repo edge to repo::2
    res = traversal.get_dependencies(
        "repo::1::func::a",
        repo_id="repo::1",
        max_depth=5,
        session=sim,
    )
    assert res.entity_ids == []
    assert len(res) == 0


def test_nonexistent_entity_and_repository_mismatch():
    """Verify nonexistent starting entity and repo mismatch return empty result safely."""
    sim = GraphSimulatorSession()
    sim.add_node("repo::alpha::func::x", "repo::alpha", ["Function"])

    traversal = GraphTraversal()

    # 1. Nonexistent entity
    res_missing = traversal.get_dependencies(
        "repo::alpha::func::missing",
        repo_id="repo::alpha",
        session=sim,
    )
    assert res_missing.entity_ids == []
    assert len(res_missing) == 0
    assert res_missing.start_entity_found is False

    # 2. Repository mismatch (entity exists in repo::alpha, but queried for repo::beta)
    res_mismatch = traversal.get_dependencies(
        "repo::alpha::func::x",
        repo_id="repo::beta",
        session=sim,
    )
    assert res_mismatch.entity_ids == []
    assert len(res_mismatch) == 0
    assert res_mismatch.start_entity_found is False


def test_empty_neighborhood_returns_empty_result():
    """Verify starting entity with zero dependencies returns empty result with start_entity_found=True."""
    sim = GraphSimulatorSession()
    sim.add_node("repo::r::func::leaf", "repo::r", ["Function"])

    traversal = GraphTraversal()
    res = traversal.get_dependencies("repo::r::func::leaf", repo_id="repo::r", session=sim)
    assert res.entity_ids == []
    assert len(res) == 0
    assert res.start_entity_found is True


# ==============================================================================
# 6. Relationship-Type Filtering Tests
# ==============================================================================


def test_relationship_filtering_calls_imports_inherits():
    """Verify filtering by relationship types includes only requested edge types."""
    sim = GraphSimulatorSession()
    repo = "repo::filtering"
    sim.add_node("src", repo, ["Function"])
    sim.add_node("target_call", repo, ["Function"])
    sim.add_node("target_import", repo, ["Module"])
    sim.add_node("target_inherits", repo, ["Class"])
    sim.add_node("target_contains", repo, ["Method"])

    sim.add_edge("src", "target_call", "CALLS")
    sim.add_edge("src", "target_import", "IMPORTS")
    sim.add_edge("src", "target_inherits", "INHERITS")
    sim.add_edge("src", "target_contains", "CONTAINS")

    traversal = GraphTraversal()

    # Default excludes CONTAINS
    res_default = traversal.get_dependencies("src", repo_id=repo, session=sim)
    assert set(res_default.entity_ids) == {"target_call", "target_import", "target_inherits"}

    # Only CALLS
    res_calls = traversal.get_dependencies(
        "src",
        repo_id=repo,
        relationship_types=[RelationshipType.CALLS],
        session=sim,
    )
    assert res_calls.entity_ids == ["target_call"]

    # Only CONTAINS (structural, when explicitly requested)
    res_contains = traversal.get_dependencies(
        "src",
        repo_id=repo,
        relationship_types=[RelationshipType.CONTAINS],
        session=sim,
    )
    assert res_contains.entity_ids == ["target_contains"]


# ==============================================================================
# 7. Read-Only Query Invariants and Determinism Tests
# ==============================================================================


def test_cypher_queries_are_strictly_read_only_and_parameterized():
    """Verify generated Cypher queries contain zero mutation statements and enforce repo isolation."""
    for direction in (TraversalDirection.DEPENDENCIES, TraversalDirection.DEPENDENTS):
        cypher = build_traversal_cypher(
            direction=direction,
            max_depth=2,
            relationship_types=("CALLS", "IMPORTS"),
            start_label="Function",
        )
        assert cypher.strip().startswith("MATCH")

        forbidden_keywords = {"CREATE", "MERGE", "SET", "DELETE", "REMOVE", "DROP"}
        for word in cypher.upper().split():
            assert word not in forbidden_keywords, f"Forbidden keyword {word} in Cypher: {cypher}"

        # Parameterization and isolation assertions
        assert "$entity_id" in cypher
        assert "$repo_id" in cypher
        assert "ALL(node IN nodes(path)" in cypher
        assert "target.id <> $entity_id" in cypher
        assert "ORDER BY depth ASC, entity_id ASC" in cypher


def test_deterministic_result_ordering():
    """Verify multiple executions return identically ordered results independent of storage order."""
    sim = GraphSimulatorSession()
    repo = "repo::det"
    sim.add_node("start", repo, ["Function"])
    sim.add_node("z_depth1", repo, ["Function"])
    sim.add_node("a_depth1", repo, ["Function"])
    sim.add_node("m_depth2", repo, ["Function"])
    sim.add_node("b_depth2", repo, ["Function"])

    sim.add_edge("start", "z_depth1", "CALLS")
    sim.add_edge("start", "a_depth1", "CALLS")
    sim.add_edge("z_depth1", "m_depth2", "CALLS")
    sim.add_edge("a_depth1", "b_depth2", "CALLS")

    traversal = GraphTraversal()

    res1 = traversal.get_dependencies("start", repo_id=repo, max_depth=2, session=sim)
    res2 = traversal.get_dependencies("start", repo_id=repo, max_depth=2, session=sim)

    # Order must be depth 1 sorted alphabetically (a_depth1, z_depth1) then depth 2 (b_depth2, m_depth2)
    expected_order = ["a_depth1", "z_depth1", "b_depth2", "m_depth2"]
    assert res1.entity_ids == expected_order
    assert res2.entity_ids == expected_order


# ==============================================================================
# 8. Session Ownership and Error Handling Tests
# ==============================================================================


def test_session_lifecycle_caller_owned_session_not_closed():
    """Verify caller-owned session is not closed by traversal component."""
    sim = GraphSimulatorSession()
    sim.add_node("node::A", "repo::1", ["Function"])

    traversal = GraphTraversal()
    traversal.get_dependencies("node::A", repo_id="repo::1", session=sim)
    assert not sim.close_called


def test_session_lifecycle_managed_driver_session_closed():
    """Verify driver session acquired internally is closed in finally."""
    sim = GraphSimulatorSession()
    sim.add_node("node::A", "repo::1", ["Function"])

    mock_driver = MagicMock(spec=Driver)
    mock_driver.session.return_value = sim

    traversal = GraphTraversal(driver=mock_driver)
    traversal.get_dependencies("node::A", repo_id="repo::1")

    mock_driver.session.assert_called_once()
    assert sim.close_called


def test_error_handling_masks_credentials_and_raises_traversal_error():
    """Verify database errors raise GraphTraversalError and mask sensitive connection details."""
    mock_session = MagicMock(spec=Session)
    mock_session.run.side_effect = Exception(
        "Connection failed to bolt://neo4j:super_secret_pw@neo4j:7687"
    )

    traversal = GraphTraversal()
    with pytest.raises(GraphTraversalError) as exc_info:
        traversal.get_dependencies("node::A", repo_id="repo::1", session=mock_session)

    assert "super_secret_pw" not in str(exc_info.value)
    assert isinstance(exc_info.value, Neo4jConnectionError)


# ==============================================================================
# 9. Atlas Fixture Ground Truth Integration Tests
# ==============================================================================


def test_atlas_fixture_ground_truth_traversal():
    """Verify traversal conforms to the documented Atlas fixture ground truth oracle.

    Tests:
    - ItemService.create_tagged_item dependencies (format_identifier, create_default_item).
    - format_identifier dependents chain (ItemService.create_tagged_item -> process_item_workflow -> app.main).
    - BaseEntity incoming inheritance (ItemModel).
    - Unrelated isolation (StandaloneCalculator has 0 cross-file connections).
    """
    resolved_fixture = resolve_repository(repo_path=FIXTURE_DIR, repo_name="atlas_fixture")
    repo_id = resolved_fixture.repository.id

    sim = GraphSimulatorSession()
    sim.add_node(repo_id, repo_id, ["Repository"], resolved_fixture.repository.to_dict())

    # Add all fixture entities
    for f in resolved_fixture.files:
        sim.add_node(f.id, repo_id, ["File"], f.to_dict())
    for m in resolved_fixture.modules:
        sim.add_node(m.id, repo_id, ["Module"], m.to_dict())
    for c in resolved_fixture.classes:
        sim.add_node(c.id, repo_id, ["Class"], c.to_dict())
    for fn in resolved_fixture.functions:
        sim.add_node(fn.id, repo_id, ["Function"], fn.to_dict())
    for mt in resolved_fixture.methods:
        sim.add_node(mt.id, repo_id, ["Method"], mt.to_dict())
    for im in resolved_fixture.imports:
        sim.add_node(im.id, repo_id, ["Import"], im.to_dict())

    # Add all fixture relationships
    for r in resolved_fixture.relationships:
        sim.add_edge(r.source_id, r.target_id, r.rel_type.value)

    traversal = GraphTraversal()

    # 1. Outgoing dependencies of ItemService.create_tagged_item
    tagged_item_id = "repo::atlas_fixture::method::services.ItemService.create_tagged_item"
    res_tagged = traversal.get_direct_dependencies(tagged_item_id, session=sim)

    expected_tagged_deps = {
        "repo::atlas_fixture::function::models.create_default_item",
        "repo::atlas_fixture::function::utils.format_identifier",
    }
    assert set(res_tagged.entity_ids) == expected_tagged_deps
    # CONTAINS parent services.ItemService must not be in dependencies
    assert "repo::atlas_fixture::class::services.ItemService" not in res_tagged.entity_ids

    # 2. Reverse traversal: Dependents of utils.format_identifier
    format_id = "repo::atlas_fixture::function::utils.format_identifier"

    # Depth 1 dependent: ItemService.create_tagged_item
    res_fmt_d1 = traversal.get_direct_dependents(format_id, session=sim)
    assert res_fmt_d1.entity_ids == [tagged_item_id]

    # Depth 2 dependents: ItemService.create_tagged_item + services.process_item_workflow
    res_fmt_d2 = traversal.get_dependents(format_id, max_depth=2, session=sim)
    workflow_id = "repo::atlas_fixture::function::services.process_item_workflow"
    assert set(res_fmt_d2.entity_ids) == {tagged_item_id, workflow_id}

    # Depth 3 dependents: includes app.main
    res_fmt_d3 = traversal.get_dependents(format_id, max_depth=3, session=sim)
    main_id = "repo::atlas_fixture::function::app.main"
    assert set(res_fmt_d3.entity_ids) == {tagged_item_id, workflow_id, main_id}

    # 3. Dependents of BaseEntity: ItemModel via INHERITS
    base_class_id = "repo::atlas_fixture::class::base.BaseEntity"
    res_base = traversal.get_dependents(base_class_id, session=sim)
    item_model_id = "repo::atlas_fixture::class::models.ItemModel"
    assert item_model_id in res_base.entity_ids

    # 4. Negative isolation: unrelated.StandaloneCalculator
    calc_id = "repo::atlas_fixture::class::unrelated.StandaloneCalculator"
    res_calc_deps = traversal.get_transitive_dependencies(calc_id, session=sim)
    # Calculator has zero cross-file dependencies
    for dep_id in res_calc_deps.entity_ids:
        assert "unrelated" in dep_id, f"Unrelated entity leaked dependency: {dep_id}"


def test_functional_convenience_entry_points():
    """Verify all top-level module convenience functions delegate correctly."""
    sim = GraphSimulatorSession()
    repo = "repo::func"
    sim.add_node("A", repo, ["Function"])
    sim.add_node("B", repo, ["Function"])
    sim.add_node("C", repo, ["Function"])
    sim.add_edge("A", "B", "CALLS")
    sim.add_edge("B", "C", "CALLS")

    # Direct dependencies
    d_dir = get_direct_dependencies("A", repo_id=repo, session=sim)
    assert d_dir.entity_ids == ["B"]

    # Transitive dependencies
    d_trans = get_transitive_dependencies("A", repo_id=repo, max_depth=2, session=sim)
    assert d_trans.entity_ids == ["B", "C"]

    # General dependencies
    d_gen = get_dependencies("A", repo_id=repo, max_depth=1, session=sim)
    assert d_gen.entity_ids == ["B"]

    # Direct dependents
    r_dir = get_direct_dependents("C", repo_id=repo, session=sim)
    assert r_dir.entity_ids == ["B"]

    # Transitive dependents
    r_trans = get_transitive_dependents("C", repo_id=repo, max_depth=2, session=sim)
    assert r_trans.entity_ids == ["B", "A"]

    # General dependents
    r_gen = get_dependents("C", repo_id=repo, max_depth=1, session=sim)
    assert r_gen.entity_ids == ["B"]
