"""P0-11: Automated test suite for the complete static analysis pipeline.

Verifies end-to-end integration across scanner discovery, Tree-sitter parsing,
Unified Code Model (UCM) extraction, symbol indexing, and relationship resolution.
Uses tests/fixtures/atlas_fixture as the independent correctness oracle.
"""

from pathlib import Path
import pytest

from app.extractor import extract_python_repository, extract_python_source
from app.parser.models import SyntaxErrorInfo
from app.resolver import (
    RelationshipResolver,
    SymbolIndex,
    resolve_relationships,
    resolve_repository,
)
from app.ucm import (
    Class,
    File,
    Function,
    Import,
    Method,
    Module,
    RelationshipType,
    Repository,
    UnifiedCodeModel,
    build_class_id,
    build_file_id,
    build_function_id,
    build_import_id,
    build_method_id,
    build_module_id,
    build_repo_id,
)


@pytest.fixture
def atlas_fixture_dir() -> Path:
    """Return the absolute path to tests/fixtures/atlas_fixture."""
    backend_dir = Path(__file__).resolve().parent.parent
    repo_root = backend_dir.parent
    fixture_dir = repo_root / "tests" / "fixtures" / "atlas_fixture"
    assert fixture_dir.exists(), f"Fixture directory not found at {fixture_dir}"
    return fixture_dir


# ==============================================================================
# 1. Scanner & Source Discovery Tests
# ==============================================================================


def test_pipeline_scanner_discovery_and_exclusion(atlas_fixture_dir: Path, tmp_path: Path):
    """Verify scanner file discovery, non-source exclusion, and sorting."""
    # 1. Oracle discovery check
    ucm = extract_python_repository(atlas_fixture_dir, repo_name="atlas_fixture")
    discovered_files = sorted(f.path for f in ucm.files)
    expected_files = [
        "ambiguous.py",
        "app.py",
        "base.py",
        "models.py",
        "services.py",
        "unrelated.py",
        "utils.py",
    ]
    assert discovered_files == expected_files

    # 2. Verify exclusion of non-python files and ignored directory patterns
    mock_repo = tmp_path / "mock_repo"
    mock_repo.mkdir()
    (mock_repo / "valid_a.py").write_text("def a(): pass\n", encoding="utf-8")
    (mock_repo / "valid_b.py").write_text("def b(): pass\n", encoding="utf-8")
    (mock_repo / "README.md").write_text("# Not a code file\n", encoding="utf-8")
    (mock_repo / "data.json").write_text("{}", encoding="utf-8")

    # Ignored directories
    venv_dir = mock_repo / ".venv" / "sub"
    venv_dir.mkdir(parents=True)
    (venv_dir / "hidden.py").write_text("def hidden(): pass\n", encoding="utf-8")

    pycache_dir = mock_repo / "__pycache__"
    pycache_dir.mkdir()
    (pycache_dir / "cached.py").write_text("def cached(): pass\n", encoding="utf-8")

    mock_ucm = extract_python_repository(mock_repo, repo_name="mock")
    mock_paths = sorted(f.path for f in mock_ucm.files)
    assert mock_paths == ["valid_a.py", "valid_b.py"]

    # 3. Explicit file_paths subset filtering
    subset_ucm = resolve_repository(
        atlas_fixture_dir,
        repo_name="subset_fixture",
        file_paths=["app.py", "services.py"],
    )
    subset_paths = sorted(f.path for f in subset_ucm.files)
    assert subset_paths == ["app.py", "services.py"]
    assert len(subset_ucm.files) == 2


# ==============================================================================
# 2. Oracle Ground Truth Entity Extraction (Positive & Negative)
# ==============================================================================


def test_pipeline_oracle_entities_positive_and_negative(atlas_fixture_dir: Path):
    """Verify all entities extracted from atlas_fixture against README Section 4."""
    ucm = resolve_repository(atlas_fixture_dir, repo_name="atlas_fixture")

    # 1. Files & Modules (7 expected)
    assert len(ucm.files) == 7
    assert len(ucm.modules) == 7

    # Positive modules
    expected_mod_qnames = {
        "app",
        "services",
        "models",
        "base",
        "utils",
        "unrelated",
        "ambiguous",
    }
    extracted_mod_qnames = {m.qualified_name for m in ucm.modules}
    assert extracted_mod_qnames == expected_mod_qnames

    # Negative module: non-existent module must not exist
    assert "nonexistent_module" not in extracted_mod_qnames

    # 2. Classes (7 expected)
    expected_classes = {
        "app.Application",
        "services.ItemService",
        "models.ItemModel",
        "base.BaseEntity",
        "unrelated.StandaloneCalculator",
        "ambiguous.AlphaWorker",
        "ambiguous.BetaWorker",
    }
    extracted_classes = {c.qualified_name for c in ucm.classes}
    assert extracted_classes == expected_classes

    # Negative class: MissingModel from ambiguous.py must NOT be present
    assert "models.MissingModel" not in extracted_classes
    assert "ambiguous.MissingModel" not in extracted_classes

    # 3. Methods (12 expected)
    expected_methods = {
        "app.Application.__init__",
        "app.Application.run",
        "services.ItemService.get_item_summary",
        "services.ItemService.create_tagged_item",
        "models.ItemModel.__init__",
        "models.ItemModel.get_display_name",
        "base.BaseEntity.__init__",
        "base.BaseEntity.get_id",
        "unrelated.StandaloneCalculator.add",
        "unrelated.StandaloneCalculator.compute_total",
        "ambiguous.AlphaWorker.execute_task",
        "ambiguous.BetaWorker.execute_task",
    }
    extracted_methods = {m.qualified_name for m in ucm.methods}
    assert extracted_methods == expected_methods

    # Negative method: ItemService does not define __init__; it must not exist in UCM
    assert "services.ItemService.__init__" not in extracted_methods

    # 4. Functions (11 expected: 10 module-level + 1 inner_local_function)
    expected_functions = {
        "app.main",
        "services.process_item_workflow",
        "models.create_default_item",
        "utils.format_identifier",
        "unrelated.sum_values",
        "ambiguous.call_ambiguous_worker",
        "ambiguous.execute_task",
        "ambiguous.call_undefined_symbol",
        "ambiguous.outer_scope_function",
        "ambiguous.outer_scope_function.inner_local_function",
        "ambiguous.dynamic_reflection_dispatch",
    }
    extracted_functions = {f.qualified_name for f in ucm.functions}
    assert extracted_functions == expected_functions

    # Negative function: undefined_function must not exist
    assert "ambiguous.undefined_function" not in extracted_functions
    # Negative function: inner_local_function must NOT be at top-level module scope
    assert "ambiguous.inner_local_function" not in extracted_functions

    # 5. Imports (8 expected)
    expected_imports = {
        ("ambiguous.py", "nonexistent_module", "missing_symbol"),
        ("ambiguous.py", "models", "MissingModel"),
        ("app.py", "services", "ItemService"),
        ("app.py", "services", "process_item_workflow"),
        ("models.py", "base", "BaseEntity"),
        ("services.py", "models", "ItemModel"),
        ("services.py", "models", "create_default_item"),
        ("services.py", "utils", "format_identifier"),
    }
    extracted_imports = {(i.file_path, i.module_name, i.imported_name) for i in ucm.imports}
    assert extracted_imports == expected_imports


# ==============================================================================
# 3. Oracle Ground Truth Relationship Verification (Positive & Negative)
# ==============================================================================


def test_pipeline_oracle_relationships_positive_and_negative(atlas_fixture_dir: Path):
    """Verify all relationships in atlas_fixture against README Sections 5, 6, 7, 8."""
    ucm = resolve_repository(atlas_fixture_dir, repo_name="atlas_fixture")

    by_type: dict[RelationshipType, list] = {}
    for r in ucm.relationships:
        by_type.setdefault(r.rel_type, []).append(r)

    # --------------------------------------------------------------------------
    # 3.1 CONTAINS (37 expected)
    # --------------------------------------------------------------------------
    contains_rels = by_type.get(RelationshipType.CONTAINS, [])
    assert len(contains_rels) == 37

    # Structure checks
    repo_file_contains = [r for r in contains_rels if "repo::" in r.source_id and "::file::" in r.target_id]
    assert len(repo_file_contains) == 7

    file_class_contains = [r for r in contains_rels if "::file::" in r.source_id and "::class::" in r.target_id]
    assert len(file_class_contains) == 7

    file_func_contains = [r for r in contains_rels if "::file::" in r.source_id and "::function::" in r.target_id]
    assert len(file_func_contains) == 10

    class_meth_contains = [r for r in contains_rels if "::class::" in r.source_id and "::method::" in r.target_id]
    assert len(class_meth_contains) == 12

    func_func_contains = [r for r in contains_rels if "::function::" in r.source_id and "::function::" in r.target_id]
    assert len(func_func_contains) == 1
    assert func_func_contains[0].source_id == "repo::atlas_fixture::function::ambiguous.outer_scope_function"
    assert func_func_contains[0].target_id == "repo::atlas_fixture::function::ambiguous.outer_scope_function.inner_local_function"

    # Negative containment: inner_local_function must NOT be contained by file
    contains_pairs = {(r.source_id, r.target_id) for r in contains_rels}
    assert ("repo::atlas_fixture::file::ambiguous.py", "repo::atlas_fixture::function::ambiguous.outer_scope_function.inner_local_function") not in contains_pairs

    # --------------------------------------------------------------------------
    # 3.2 IMPORTS (5 expected)
    # --------------------------------------------------------------------------
    imports_rels = by_type.get(RelationshipType.IMPORTS, [])
    assert len(imports_rels) == 5

    expected_import_pairs = {
        ("repo::atlas_fixture::file::app.py", "repo::atlas_fixture::module::services"),
        ("repo::atlas_fixture::file::services.py", "repo::atlas_fixture::module::models"),
        ("repo::atlas_fixture::file::services.py", "repo::atlas_fixture::module::utils"),
        ("repo::atlas_fixture::file::models.py", "repo::atlas_fixture::module::base"),
        ("repo::atlas_fixture::file::ambiguous.py", "repo::atlas_fixture::module::models"),
    }
    extracted_import_pairs = {(r.source_id, r.target_id) for r in imports_rels}
    assert extracted_import_pairs == expected_import_pairs

    # Negative imports:
    # 1. from nonexistent_module must NOT produce an IMPORTS edge
    assert not any("nonexistent_module" in r.target_id for r in imports_rels)
    # 2. base.py, utils.py, unrelated.py must have zero outbound imports
    assert not any(r.source_id == "repo::atlas_fixture::file::base.py" for r in imports_rels)
    assert not any(r.source_id == "repo::atlas_fixture::file::utils.py" for r in imports_rels)
    assert not any(r.source_id == "repo::atlas_fixture::file::unrelated.py" for r in imports_rels)
    # 3. unrelated.py must have zero inbound imports
    assert not any(r.target_id == "repo::atlas_fixture::module::unrelated" for r in imports_rels)

    # --------------------------------------------------------------------------
    # 3.3 INHERITS (1 expected)
    # --------------------------------------------------------------------------
    inherits_rels = by_type.get(RelationshipType.INHERITS, [])
    assert len(inherits_rels) == 1
    assert inherits_rels[0].source_id == "repo::atlas_fixture::class::models.ItemModel"
    assert inherits_rels[0].target_id == "repo::atlas_fixture::class::base.BaseEntity"

    # Negative inheritance: Application, ItemService, BaseEntity, StandaloneCalculator, AlphaWorker, BetaWorker
    inheriting_classes = {r.source_id for r in inherits_rels}
    assert "repo::atlas_fixture::class::app.Application" not in inheriting_classes
    assert "repo::atlas_fixture::class::services.ItemService" not in inheriting_classes
    assert "repo::atlas_fixture::class::base.BaseEntity" not in inheriting_classes
    assert "repo::atlas_fixture::class::unrelated.StandaloneCalculator" not in inheriting_classes
    assert "repo::atlas_fixture::class::ambiguous.AlphaWorker" not in inheriting_classes
    assert "repo::atlas_fixture::class::ambiguous.BetaWorker" not in inheriting_classes

    # --------------------------------------------------------------------------
    # 3.4 CALLS (15 expected)
    # --------------------------------------------------------------------------
    calls_rels = by_type.get(RelationshipType.CALLS, [])
    assert len(calls_rels) == 15

    expected_call_pairs = {
        ("repo::atlas_fixture::function::ambiguous.outer_scope_function", "repo::atlas_fixture::function::ambiguous.outer_scope_function.inner_local_function"),
        ("repo::atlas_fixture::function::app.main", "repo::atlas_fixture::method::app.Application.__init__"),
        ("repo::atlas_fixture::function::app.main", "repo::atlas_fixture::function::services.process_item_workflow"),
        ("repo::atlas_fixture::function::app.main", "repo::atlas_fixture::method::app.Application.run"),
        ("repo::atlas_fixture::method::app.Application.run", "repo::atlas_fixture::method::services.ItemService.get_item_summary"),
        ("repo::atlas_fixture::function::services.process_item_workflow", "repo::atlas_fixture::method::services.ItemService.get_item_summary"),
        ("repo::atlas_fixture::function::services.process_item_workflow", "repo::atlas_fixture::method::services.ItemService.create_tagged_item"),
        ("repo::atlas_fixture::method::services.ItemService.get_item_summary", "repo::atlas_fixture::method::models.ItemModel.__init__"),
        ("repo::atlas_fixture::method::services.ItemService.get_item_summary", "repo::atlas_fixture::method::models.ItemModel.get_display_name"),
        ("repo::atlas_fixture::method::services.ItemService.create_tagged_item", "repo::atlas_fixture::function::utils.format_identifier"),
        ("repo::atlas_fixture::method::services.ItemService.create_tagged_item", "repo::atlas_fixture::function::models.create_default_item"),
        ("repo::atlas_fixture::function::models.create_default_item", "repo::atlas_fixture::method::models.ItemModel.__init__"),
        ("repo::atlas_fixture::method::models.ItemModel.__init__", "repo::atlas_fixture::method::base.BaseEntity.__init__"),
        ("repo::atlas_fixture::method::models.ItemModel.get_display_name", "repo::atlas_fixture::method::base.BaseEntity.get_id"),
        ("repo::atlas_fixture::method::unrelated.StandaloneCalculator.compute_total", "repo::atlas_fixture::function::unrelated.sum_values"),
    }
    extracted_call_pairs = {(r.source_id, r.target_id) for r in calls_rels}
    assert extracted_call_pairs == expected_call_pairs

    # Total relationship invariant: 37 CONTAINS + 5 IMPORTS + 1 INHERITS + 15 CALLS = 58
    assert len(ucm.relationships) == 58


# ==============================================================================
# 4. Negative Ambiguity & Unresolved Reference Verification (README Section 13)
# ==============================================================================


def test_pipeline_oracle_negative_ambiguity_cases(atlas_fixture_dir: Path):
    """Verify all 7 documented negative ambiguity cases in ambiguous.py."""
    ucm = resolve_repository(atlas_fixture_dir, repo_name="atlas_fixture")
    calls = [r for r in ucm.relationships if r.rel_type == RelationshipType.CALLS]
    imports = [r for r in ucm.relationships if r.rel_type == RelationshipType.IMPORTS]

    # Case 1: Missing target module
    assert not any("nonexistent_module" in r.target_id for r in imports)

    # Case 2: Missing symbol in existing module
    # 'models' module is imported, but 'MissingModel' must not be connected to any entity
    assert any(r.source_id == "repo::atlas_fixture::file::ambiguous.py" and r.target_id == "repo::atlas_fixture::module::models" for r in imports)
    all_entity_names = {c.name for c in ucm.classes} | {f.name for f in ucm.functions}
    assert "MissingModel" not in all_entity_names

    # Case 3: Ambiguous call receiver (worker.execute_task)
    worker_calls = [r for r in calls if "call_ambiguous_worker" in r.source_id]
    assert worker_calls == [], "Ambiguous call receiver must produce zero speculative edges"

    # Case 4: Name collision between standalone function and class methods
    func_exec_id = "repo::atlas_fixture::function::ambiguous.execute_task"
    alpha_exec_id = "repo::atlas_fixture::method::ambiguous.AlphaWorker.execute_task"
    beta_exec_id = "repo::atlas_fixture::method::ambiguous.BetaWorker.execute_task"
    assert func_exec_id != alpha_exec_id
    assert func_exec_id != beta_exec_id

    # Case 5: Unresolved function call (undefined_function)
    undef_calls = [r for r in calls if "call_undefined_symbol" in r.source_id]
    assert undef_calls == [], "Call to undefined function must not produce speculative edges"

    # Case 6: Nested lexical scope (inner_local_function)
    inner_calls = [r for r in calls if "outer_scope_function" in r.source_id]
    assert len(inner_calls) == 1
    assert inner_calls[0].target_id == "repo::atlas_fixture::function::ambiguous.outer_scope_function.inner_local_function"

    # Case 7: Dynamic reflection dispatch (getattr)
    reflect_calls = [r for r in calls if "dynamic_reflection_dispatch" in r.source_id]
    assert reflect_calls == [], "Dynamic reflection calls must remain unresolved"


# ==============================================================================
# 5. Isolation of Unrelated Component (Negative Invariant)
# ==============================================================================


def test_pipeline_unrelated_component_complete_isolation(atlas_fixture_dir: Path):
    """Verify that unrelated.py has zero dependencies or connections to the main application."""
    ucm = resolve_repository(atlas_fixture_dir, repo_name="atlas_fixture")

    # Inbound / outbound non-containment relationships for unrelated
    semantic_rels = [r for r in ucm.relationships if r.rel_type != RelationshipType.CONTAINS]

    # No outbound dependencies from unrelated to other files
    outbound_from_unrelated = [
        r for r in semantic_rels
        if "unrelated" in r.source_id and "unrelated" not in r.target_id
    ]
    assert outbound_from_unrelated == []

    # No inbound dependencies from other files to unrelated
    inbound_to_unrelated = [
        r for r in semantic_rels
        if "unrelated" in r.target_id and "unrelated" not in r.source_id
    ]
    assert inbound_to_unrelated == []


# ==============================================================================
# 6. Synthetic Cases: Multi-Level Inheritance, Aliases, Collision
# ==============================================================================


def test_pipeline_synthetic_multi_level_inheritance_and_mro():
    """Verify multi-level inheritance resolution and method dispatch up the hierarchy."""
    src_gp = """
class GrandParent:
    def root_method(self) -> str:
        return "root"
"""
    src_p = """
from gp import GrandParent

class Parent(GrandParent):
    def parent_method(self) -> str:
        return "parent"
"""
    src_c = """
from p import Parent

class Child(Parent):
    def test_call(self) -> str:
        r = self.root_method()
        p = self.parent_method()
        return f"{r}-{p}"
"""
    sources = {"gp.py": src_gp, "p.py": src_p, "c.py": src_c}
    ucm = extract_python_source(src_gp, "gp.py", repo_id="repo::synth_mro").to_ucm()
    extract_python_source(src_p, "p.py", repo_id="repo::synth_mro").add_to_ucm(ucm)
    extract_python_source(src_c, "c.py", repo_id="repo::synth_mro").add_to_ucm(ucm)

    resolved = resolve_relationships(ucm, sources=sources)

    # Inheritance chain: Child -> Parent, Parent -> GrandParent
    inherits = {(r.source_id, r.target_id) for r in resolved.relationships if r.rel_type == RelationshipType.INHERITS}
    c_id = build_class_id("repo::synth_mro", "c.Child")
    p_id = build_class_id("repo::synth_mro", "p.Parent")
    gp_id = build_class_id("repo::synth_mro", "gp.GrandParent")

    assert (c_id, p_id) in inherits
    assert (p_id, gp_id) in inherits

    # Method dispatch: Child.test_call calls GrandParent.root_method and Parent.parent_method
    calls = {(r.source_id, r.target_id) for r in resolved.relationships if r.rel_type == RelationshipType.CALLS}
    caller_id = build_method_id("repo::synth_mro", "c.Child.test_call")
    root_m_id = build_method_id("repo::synth_mro", "gp.GrandParent.root_method")
    parent_m_id = build_method_id("repo::synth_mro", "p.Parent.parent_method")

    assert (caller_id, root_m_id) in calls
    assert (caller_id, parent_m_id) in calls


def test_pipeline_synthetic_aliased_cross_file_calls():
    """Verify function and class calls when imported under aliases."""
    src_lib = """
class Calculator:
    def __init__(self):
        self.val = 0

    def compute(self, n: int) -> int:
        return n * 2

def helper_func(x: int) -> int:
    return x + 1
"""
    src_client = """
from lib import Calculator as Calc, helper_func as hf

def execute():
    c = Calc()
    res = c.compute(10)
    return hf(res)
"""
    sources = {"lib.py": src_lib, "client.py": src_client}
    ucm = extract_python_source(src_lib, "lib.py", repo_id="repo::alias_call").to_ucm()
    extract_python_source(src_client, "client.py", repo_id="repo::alias_call").add_to_ucm(ucm)

    resolved = resolve_relationships(ucm, sources=sources)
    calls = {(r.source_id, r.target_id) for r in resolved.relationships if r.rel_type == RelationshipType.CALLS}

    caller = build_function_id("repo::alias_call", "client.execute")
    calc_init = build_method_id("repo::alias_call", "lib.Calculator.__init__")
    calc_compute = build_method_id("repo::alias_call", "lib.Calculator.compute")
    hf_target = build_function_id("repo::alias_call", "lib.helper_func")

    assert (caller, calc_init) in calls
    assert (caller, calc_compute) in calls
    assert (caller, hf_target) in calls


# ==============================================================================
# 7. Repository Isolation
# ==============================================================================


def test_pipeline_strict_repository_isolation():
    """Verify that multiple repositories remain completely isolated without cross-repo leakage."""
    src = "def process(): return 1\ndef run(): return process()"

    ucm_a = extract_python_source(src, "mod.py", repo_id="repo::alpha").to_ucm()
    ucm_b = extract_python_source(src, "mod.py", repo_id="repo::beta").to_ucm()

    res_a = resolve_relationships(ucm_a, sources={"mod.py": src})
    res_b = resolve_relationships(ucm_b, sources={"mod.py": src})

    for rel in res_a.relationships:
        assert rel.source_id.startswith("repo::alpha")
        assert rel.target_id.startswith("repo::alpha")

    for rel in res_b.relationships:
        assert rel.source_id.startswith("repo::beta")
        assert rel.target_id.startswith("repo::beta")


# ==============================================================================
# 8. Determinism and Idempotency
# ==============================================================================


def test_pipeline_determinism_and_stability(atlas_fixture_dir: Path):
    """Verify that repeated pipeline runs produce byte-for-byte identical output."""
    run1 = resolve_repository(atlas_fixture_dir, repo_name="atlas_fixture")
    run2 = resolve_repository(atlas_fixture_dir, repo_name="atlas_fixture")

    json1 = run1.to_json(indent=2)
    json2 = run2.to_json(indent=2)
    assert json1 == json2

    # Verify JSON deserialization preserves all fields and relationships
    restored1 = UnifiedCodeModel.from_json(json1)
    assert restored1 == run1
    assert len(restored1.relationships) == 58


# ==============================================================================
# 9. Syntax Error Resilience in Pipeline
# ==============================================================================


def test_pipeline_syntax_error_resilience(tmp_path: Path):
    """Verify that the pipeline handles syntax errors gracefully without crashing."""
    repo_dir = tmp_path / "broken_repo"
    repo_dir.mkdir()

    (repo_dir / "valid.py").write_text("def work(): return 1\n", encoding="utf-8")
    (repo_dir / "broken.py").write_text(
        "def broken_syntax(:\n    pass\n\ndef recovered(): return 2\n",
        encoding="utf-8",
    )

    ucm = resolve_repository(repo_dir, repo_name="broken_repo")

    # Pipeline successfully ran and extracted both files
    assert len(ucm.files) == 2
    func_names = {f.name for f in ucm.functions}
    assert "work" in func_names
    assert "recovered" in func_names
