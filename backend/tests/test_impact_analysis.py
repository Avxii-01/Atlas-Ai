"""Automated test suite for Atlas AI Impact Analysis Engine (P0-17).

Verifies direct and transitive impact blast radius, shortest-path depths, affected file
resolution, depth bounds, cycles, repository isolation, and ground-truth validation
against the controlled Atlas fixture.
"""

from pathlib import Path
from unittest.mock import MagicMock
import pytest
from neo4j import Session

from app.db.neo4j import Neo4jConnectionError, set_driver
from app.graph.impact import (
    AffectedFile,
    ImpactAnalysisError,
    ImpactAnalysisResult,
    ImpactAnalyzer,
    analyze_impact,
    resolve_affected_files,
)
from app.graph.traversal import (
    GraphTraversal,
    GraphTraversalError,
    TraversalNode,
)
from app.resolver.relationship_resolver import resolve_repository
from app.ucm.relationships import RelationshipType
from tests.test_graph_traversal import GraphSimulatorSession

FIXTURE_DIR = Path(__file__).resolve().parent.parent.parent / "tests" / "fixtures" / "atlas_fixture"


@pytest.fixture(autouse=True)
def reset_driver_state():
    """Ensure driver state is reset before and after every test."""
    set_driver(None)
    yield
    set_driver(None)


# ==============================================================================
# 1. Parameter Validation & Error Handling Tests
# ==============================================================================


def test_invalid_parameters_raise_value_error():
    """Verify empty or invalid target_entity_id, repo_id, and max_depth raise ValueError."""
    analyzer = ImpactAnalyzer()
    sim = GraphSimulatorSession()

    with pytest.raises(ValueError, match="target_entity_id must be a non-empty string"):
        analyzer.analyze_impact("", repo_id="repo::1", session=sim)

    with pytest.raises(ValueError, match="target_entity_id must be a non-empty string"):
        analyzer.analyze_impact(None, repo_id="repo::1", session=sim)  # type: ignore

    with pytest.raises(ValueError, match="repo_id must be a non-empty string"):
        analyzer.analyze_impact("repo::1::func::foo", repo_id="", session=sim)

    with pytest.raises(ValueError, match="repo_id must be provided or inferrable"):
        analyzer.analyze_impact("unprefixed_target", repo_id=None, session=sim)

    for invalid_depth in [0, -1, True, False, 1.5, "2", None]:
        with pytest.raises(ValueError, match="Traversal depth must be an integer >= 1"):
            analyzer.analyze_impact("repo::1::func::foo", repo_id="repo::1", max_depth=invalid_depth, session=sim)  # type: ignore


def test_database_error_raises_impact_error_and_masks_credentials():
    """Verify database exceptions are not disguised as empty results and mask connection secrets."""
    mock_session = MagicMock(spec=Session)
    mock_session.run.side_effect = Exception(
        "Connection refused to bolt://neo4j:classified_pass@neo4j:7687"
    )

    analyzer = ImpactAnalyzer()
    with pytest.raises(GraphTraversalError) as exc_info:
        analyzer.analyze_impact("repo::err::func::x", repo_id="repo::err", session=mock_session)

    assert "classified_pass" not in str(exc_info.value)
    assert isinstance(exc_info.value, Neo4jConnectionError)


# ==============================================================================
# 2. Direct vs Transitive Impact Semantics (Chain A -> B -> C)
# ==============================================================================


def test_direct_and_transitive_impact_chain():
    """Verify reverse traversal semantics on dependency chain:

    CallerA -> CallerB -> TargetC (A calls B, B calls C)
    - Directly impacted by TargetC (depth 1): CallerB
    - Transitive impact of TargetC at depth 2: CallerB and CallerA
    - TargetC is excluded from its own impact set.
    """
    sim = GraphSimulatorSession()
    repo = "repo::chain"
    sim.add_node("func::CallerA", repo, ["Function"], {"file_path": "a.py"})
    sim.add_node("func::CallerB", repo, ["Function"], {"file_path": "b.py"})
    sim.add_node("func::TargetC", repo, ["Function"], {"file_path": "c.py"})

    sim.add_edge("func::CallerA", "func::CallerB", "CALLS")
    sim.add_edge("func::CallerB", "func::TargetC", "CALLS")

    analyzer = ImpactAnalyzer()

    # 1. Depth 1: Direct impact only
    res_d1 = analyzer.analyze_impact("func::TargetC", repo_id=repo, max_depth=1, session=sim)
    assert res_d1.target_entity_found is True
    assert res_d1.blast_radius == 1
    assert res_d1.directly_impacted_entity_ids == ["func::CallerB"]
    assert res_d1.impacted_entity_ids == ["func::CallerB"]
    assert res_d1.affected_file_paths == ["b.py"]
    assert "func::TargetC" not in res_d1.impacted_entity_ids

    # 2. Depth 2: Direct and transitive impact
    res_d2 = analyzer.analyze_impact("func::TargetC", repo_id=repo, max_depth=2, session=sim)
    assert res_d2.target_entity_found is True
    assert res_d2.blast_radius == 2
    assert res_d2.directly_impacted_entity_ids == ["func::CallerB"]
    assert res_d2.impacted_entity_ids == ["func::CallerB", "func::CallerA"]

    # Shortest path depths
    assert res_d2.get_entity("func::CallerB").depth == 1
    assert res_d2.get_entity("func::CallerA").depth == 2

    # Grouping by depth
    assert [n.entity_id for n in res_d2.by_depth[1]] == ["func::CallerB"]
    assert [n.entity_id for n in res_d2.by_depth[2]] == ["func::CallerA"]

    # Affected files
    assert res_d2.affected_file_count == 2
    assert res_d2.affected_file_paths == ["a.py", "b.py"]
    assert "c.py" not in res_d2.affected_file_paths


# ==============================================================================
# 3. Depth Limits & Multi-Hop Bounds
# ==============================================================================


def test_depth_limits_strict_enforcement():
    """Verify impact analysis strictly respects max_depth on a deep 5-hop caller chain."""
    sim = GraphSimulatorSession()
    repo = "repo::deep"
    # Call chain: 5 -> 4 -> 3 -> 2 -> 1 (where 1 is modified target)
    for i in range(1, 6):
        sim.add_node(f"node::{i}", repo, ["Function"], {"file_path": f"f{i}.py"})

    for i in range(5, 1, -1):
        sim.add_edge(f"node::{i}", f"node::{i-1}", "CALLS")

    analyzer = ImpactAnalyzer()

    # Target is node::1
    # Depth 1: node::2
    res_1 = analyzer.analyze_impact("node::1", repo_id=repo, max_depth=1, session=sim)
    assert res_1.impacted_entity_ids == ["node::2"]
    assert res_1.affected_file_paths == ["f2.py"]

    # Depth 2: node::2, node::3
    res_2 = analyzer.analyze_impact("node::1", repo_id=repo, max_depth=2, session=sim)
    assert res_2.impacted_entity_ids == ["node::2", "node::3"]
    assert res_2.affected_file_paths == ["f2.py", "f3.py"]

    # Depth 3: node::2, node::3, node::4
    res_3 = analyzer.analyze_impact("node::1", repo_id=repo, max_depth=3, session=sim)
    assert res_3.impacted_entity_ids == ["node::2", "node::3", "node::4"]
    assert res_3.affected_file_paths == ["f2.py", "f3.py", "f4.py"]

    # Depth 4: node::2, node::3, node::4, node::5
    res_4 = analyzer.analyze_impact("node::1", repo_id=repo, max_depth=4, session=sim)
    assert res_4.impacted_entity_ids == ["node::2", "node::3", "node::4", "node::5"]
    assert res_4.affected_file_paths == ["f2.py", "f3.py", "f4.py", "f5.py"]


# ==============================================================================
# 4. Cycles, Self-Loops, and Diamond Deduplication
# ==============================================================================


def test_cycles_and_self_loops_do_not_include_target():
    """Verify cyclic call graphs terminate safely and never return the target entity."""
    sim = GraphSimulatorSession()
    repo = "repo::cyc"
    sim.add_node("node::Target", repo, ["Function"], {"file_path": "t.py"})
    sim.add_node("node::Caller1", repo, ["Function"], {"file_path": "c1.py"})
    sim.add_node("node::Caller2", repo, ["Function"], {"file_path": "c2.py"})

    # Cycle: Target <- Caller1 <- Caller2 <- Target (Target calls Caller2, Caller2 calls Caller1, Caller1 calls Target)
    sim.add_edge("node::Caller1", "node::Target", "CALLS")
    sim.add_edge("node::Caller2", "node::Caller1", "CALLS")
    sim.add_edge("node::Target", "node::Caller2", "CALLS")

    # Self-loop: Target calls Target
    sim.add_edge("node::Target", "node::Target", "CALLS")

    analyzer = ImpactAnalyzer()
    res = analyzer.analyze_impact("node::Target", repo_id=repo, max_depth=5, session=sim)

    assert "node::Target" not in res.impacted_entity_ids
    assert res.impacted_entity_ids == ["node::Caller1", "node::Caller2"]
    assert res.directly_impacted_entity_ids == ["node::Caller1"]
    assert res.get_entity("node::Caller1").depth == 1
    assert res.get_entity("node::Caller2").depth == 2
    assert res.affected_file_paths == ["c1.py", "c2.py"]


def test_diamond_multiple_paths_deduplication():
    """Verify diamond paths preserve shortest-path depth and avoid duplicate entity/file entries."""
    sim = GraphSimulatorSession()
    repo = "repo::dia"
    sim.add_node("Target", repo, ["Function"], {"file_path": "t.py"})
    sim.add_node("CallerB", repo, ["Function"], {"file_path": "shared.py"})
    sim.add_node("CallerC", repo, ["Function"], {"file_path": "shared.py"})
    sim.add_node("RootCaller", repo, ["Function"], {"file_path": "root.py"})

    # Both CallerB and CallerC call Target (depth 1)
    # RootCaller calls both CallerB and CallerC (depth 2)
    sim.add_edge("CallerB", "Target", "CALLS")
    sim.add_edge("CallerC", "Target", "CALLS")
    sim.add_edge("RootCaller", "CallerB", "CALLS")
    sim.add_edge("RootCaller", "CallerC", "CALLS")

    analyzer = ImpactAnalyzer()
    res = analyzer.analyze_impact("Target", repo_id=repo, max_depth=3, session=sim)

    # Reached: CallerB (1), CallerC (1), RootCaller (2)
    assert len(res.impacted_entities) == 3
    assert res.get_entity("RootCaller").depth == 2
    assert len([n for n in res.impacted_entities if n.entity_id == "RootCaller"]) == 1

    # Multiple entities in shared.py must produce exactly ONE entry in affected_files
    assert res.affected_file_paths == ["root.py", "shared.py"]
    assert res.affected_file_count == 2


# ==============================================================================
# 5. Affected Files Resolution & Missing Ownership Handling
# ==============================================================================


def test_resolve_affected_files_deduplication_and_missing_ownership():
    """Verify resolve_affected_files deduplicates by file_id and safely handles missing ownership."""
    nodes = [
        # Entity 1: has file_path
        TraversalNode(
            entity_id="func::1",
            depth=1,
            labels=("Function",),
            properties={"file_path": "services/user.py"},
        ),
        # Entity 2: in same file
        TraversalNode(
            entity_id="func::2",
            depth=2,
            labels=("Function",),
            properties={"file_path": "services/user.py"},
        ),
        # Entity 3: File entity with path property
        TraversalNode(
            entity_id="file::util",
            depth=1,
            labels=("File",),
            properties={"path": "utils/helpers.py"},
        ),
        # Entity 4: Missing file ownership property
        TraversalNode(
            entity_id="repo::root",
            depth=1,
            labels=("Repository",),
            properties={},
        ),
    ]

    affected = resolve_affected_files(nodes, repo_id="repo::demo")

    assert len(affected) == 2
    paths = [f.path for f in affected]
    file_ids = [f.file_id for f in affected]

    assert paths == ["services/user.py", "utils/helpers.py"]
    assert file_ids == [
        "repo::demo::file::services/user.py",
        "repo::demo::file::utils/helpers.py",
    ]


def test_affected_file_equality_and_helpers():
    """Verify AffectedFile supports rich comparison against strings and AffectedFile objects."""
    af = AffectedFile(file_id="repo::r::file::app.py", path="app.py")

    assert str(af) == "app.py"
    assert af == "app.py"
    assert af == "repo::r::file::app.py"
    assert af != "other.py"
    assert af == AffectedFile(file_id="repo::r::file::app.py", path="app.py")


# ==============================================================================
# 6. Repository Isolation and Missing/Empty Data
# ==============================================================================


def test_repository_isolation_excludes_other_repositories():
    """Verify entities in another repository are never included in impact results."""
    sim = GraphSimulatorSession()
    # Repo 1
    sim.add_node("target_1", "repo::1", ["Function"], {"file_path": "t1.py"})
    # Repo 2 callers
    sim.add_node("caller_2", "repo::2", ["Function"], {"file_path": "c2.py"})
    sim.add_edge("caller_2", "target_1", "CALLS")

    analyzer = ImpactAnalyzer()
    res = analyzer.analyze_impact("target_1", repo_id="repo::1", max_depth=5, session=sim)

    # Cross-repo caller must be excluded by Cypher path isolation
    assert res.blast_radius == 0
    assert res.impacted_entity_ids == []
    assert res.affected_files == ()


def test_missing_target_entity_and_empty_dependents():
    """Verify nonexistent target and leaf targets return predictable empty results."""
    sim = GraphSimulatorSession()
    sim.add_node("leaf_target", "repo::test", ["Function"], {"file_path": "leaf.py"})

    analyzer = ImpactAnalyzer()

    # 1. Nonexistent target
    res_missing = analyzer.analyze_impact("nonexistent", repo_id="repo::test", session=sim)
    assert res_missing.target_entity_found is False
    assert res_missing.blast_radius == 0
    assert res_missing.directly_impacted_entities == ()
    assert res_missing.affected_files == ()

    # 2. Target with no dependents (leaf entry point)
    res_leaf = analyzer.analyze_impact("leaf_target", repo_id="repo::test", session=sim)
    assert res_leaf.target_entity_found is True
    assert res_leaf.blast_radius == 0
    assert res_leaf.directly_impacted_entities == ()
    assert res_leaf.affected_files == ()


def test_deterministic_output_across_repeated_runs():
    """Verify repeated executions produce identically ordered and equivalent results."""
    sim = GraphSimulatorSession()
    repo = "repo::repeat"
    sim.add_node("Target", repo, ["Function"], {"file_path": "t.py"})
    sim.add_node("Z_Caller", repo, ["Function"], {"file_path": "z.py"})
    sim.add_node("A_Caller", repo, ["Function"], {"file_path": "a.py"})

    sim.add_edge("Z_Caller", "Target", "CALLS")
    sim.add_edge("A_Caller", "Target", "CALLS")

    analyzer = ImpactAnalyzer()
    res1 = analyzer.analyze_impact("Target", repo_id=repo, session=sim)
    res2 = analyzer.analyze_impact("Target", repo_id=repo, session=sim)

    assert res1.impacted_entity_ids == res2.impacted_entity_ids
    assert res1.affected_file_paths == res2.affected_file_paths == ["a.py", "z.py"]


# ==============================================================================
# 7. Atlas Fixture Ground Truth Integration Tests
# ==============================================================================


def test_atlas_fixture_ground_truth_impact_analysis():
    """Verify impact analysis conforms to the documented Atlas fixture ground truth oracle.

    Tests:
    - utils.format_identifier:
      - Direct impact: services.ItemService.create_tagged_item (depth 1)
      - Transitive impact: services.process_item_workflow (depth 2), app.main (depth 3)
      - Affected files: services.py, app.py
      - Negative isolation: models.py, base.py, unrelated.py, ambiguous.py are unaffected.
    - base.BaseEntity:
      - Direct impact: models.ItemModel (via INHERITS)
      - Affected file: models.py
    - base.BaseEntity.__init__:
      - Multi-hop impact: ItemModel.__init__ -> create_default_item / ItemService -> workflow / run -> main
      - Affected files: models.py, services.py, app.py
    - unrelated.StandaloneCalculator:
      - Isolated component: 0 blast radius on other files.
    """
    resolved_fixture = resolve_repository(repo_path=FIXTURE_DIR, repo_name="atlas_fixture")
    repo_id = resolved_fixture.repository.id

    sim = GraphSimulatorSession()
    sim.add_node(repo_id, repo_id, ["Repository"], resolved_fixture.repository.to_dict())

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

    for r in resolved_fixture.relationships:
        sim.add_edge(r.source_id, r.target_id, r.rel_type.value)

    analyzer = ImpactAnalyzer()

    # --------------------------------------------------------------------------
    # Case 1: Modifying utils.format_identifier
    # Ground truth (README.md section 11.2):
    # - Direct: services.ItemService.create_tagged_item (depth 1)
    # - Transitive: services.process_item_workflow (depth 2), app.main (depth 3)
    # - Affected files: services.py, app.py
    # --------------------------------------------------------------------------
    format_id = "repo::atlas_fixture::function::utils.format_identifier"
    res_fmt = analyzer.analyze_impact(format_id, session=sim)

    tagged_id = "repo::atlas_fixture::method::services.ItemService.create_tagged_item"
    workflow_id = "repo::atlas_fixture::function::services.process_item_workflow"
    main_id = "repo::atlas_fixture::function::app.main"

    assert res_fmt.blast_radius == 3
    assert res_fmt.directly_impacted_entity_ids == [tagged_id]
    assert set(res_fmt.impacted_entity_ids) == {tagged_id, workflow_id, main_id}

    # Verify depths
    assert res_fmt.get_entity(tagged_id).depth == 1
    assert res_fmt.get_entity(workflow_id).depth == 2
    assert res_fmt.get_entity(main_id).depth == 3

    # Verify affected files
    assert res_fmt.affected_file_paths == ["app.py", "services.py"]
    assert "services.py" in res_fmt.affected_files
    assert "app.py" in res_fmt.affected_files

    # Negative isolation
    for unaffected in ["utils.py", "models.py", "base.py", "unrelated.py", "ambiguous.py"]:
        assert unaffected not in res_fmt.affected_file_paths

    # --------------------------------------------------------------------------
    # Case 2: Modifying base.BaseEntity (Class)
    # Ground truth (README.md section 11.1):
    # - Direct dependent: models.ItemModel (via INHERITS)
    # - Affected file: models.py
    # --------------------------------------------------------------------------
    base_class_id = "repo::atlas_fixture::class::base.BaseEntity"
    res_base = analyzer.analyze_impact(base_class_id, session=sim)

    item_model_id = "repo::atlas_fixture::class::models.ItemModel"
    assert res_base.blast_radius == 1
    assert res_base.directly_impacted_entity_ids == [item_model_id]
    assert res_base.affected_file_paths == ["models.py"]

    # --------------------------------------------------------------------------
    # Case 3: Modifying base.BaseEntity.__init__ (Method)
    # Ground truth (README.md section 11.1):
    # - Multi-hop chain across models.py, services.py, and app.py
    # --------------------------------------------------------------------------
    base_init_id = "repo::atlas_fixture::method::base.BaseEntity.__init__"
    res_init = analyzer.analyze_impact(base_init_id, session=sim)

    assert "repo::atlas_fixture::method::models.ItemModel.__init__" in res_init.directly_impacted_entity_ids
    assert res_init.affected_file_paths == ["app.py", "models.py", "services.py"]
    assert "unrelated.py" not in res_init.affected_file_paths
    assert "utils.py" not in res_init.affected_file_paths

    # --------------------------------------------------------------------------
    # Case 4: Negative isolation: unrelated.StandaloneCalculator
    # Ground truth: Completely isolated component
    # --------------------------------------------------------------------------
    calc_id = "repo::atlas_fixture::class::unrelated.StandaloneCalculator"
    res_calc = analyzer.analyze_impact(calc_id, session=sim)
    assert res_calc.blast_radius == 0
    assert res_calc.affected_files == ()

    # --------------------------------------------------------------------------
    # Case 5: Entry point with no callers: app.main
    # --------------------------------------------------------------------------
    res_main = analyzer.analyze_impact(main_id, session=sim)
    assert res_main.blast_radius == 0
    assert res_main.affected_files == ()


# ==============================================================================
# 8. Functional Convenience Helper & Result Protocol Tests
# ==============================================================================


def test_analyze_impact_convenience_helper():
    """Verify top-level analyze_impact function delegates correctly to ImpactAnalyzer."""
    sim = GraphSimulatorSession()
    repo = "repo::convenience"
    sim.add_node("target", repo, ["Function"], {"file_path": "tgt.py"})
    sim.add_node("caller", repo, ["Function"], {"file_path": "call.py"})
    sim.add_edge("caller", "target", "CALLS")

    res = analyze_impact("target", repo_id=repo, session=sim)
    assert isinstance(res, ImpactAnalysisResult)
    assert res.blast_radius == 1
    assert res.directly_impacted_entity_ids == ["caller"]
    assert res.affected_file_paths == ["call.py"]

    # Protocol methods: len, iter, indexing
    assert len(res) == 1
    assert list(res)[0].entity_id == "caller"
    assert res[0].entity_id == "caller"
