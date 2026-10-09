"""Automated tests for Symbol Index and Relationship Resolver (P0-10)."""

from pathlib import Path
import pytest

from app.extractor import extract_python_repository, extract_python_source
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
    build_method_id,
    build_module_id,
    build_repo_id,
    create_contains_rel,
)


def test_cross_file_imports_and_aliases():
    """Verify resolution of cross-file imports and alias handling."""
    ucm = UnifiedCodeModel(repository=Repository.create(name="import_test", source="test"))

    f_consumer = File.create(ucm.repository.id, "consumer.py", 10)
    f_provider = File.create(ucm.repository.id, "provider.py", 10)
    m_consumer = Module.create(ucm.repository.id, "consumer", "consumer", "consumer.py")
    m_provider = Module.create(ucm.repository.id, "provider", "provider", "provider.py")

    imp_alias = Import.create(
        repo_id=ucm.repository.id,
        file_path="consumer.py",
        module_name="provider",
        imported_name="Service",
        alias="Srv",
        start_line=1,
        end_line=1,
    )
    imp_external = Import.create(
        repo_id=ucm.repository.id,
        file_path="consumer.py",
        module_name="os",
        imported_name="path",
        start_line=2,
        end_line=2,
    )

    ucm.add_file(f_consumer)
    ucm.add_file(f_provider)
    ucm.add_module(m_consumer)
    ucm.add_module(m_provider)
    ucm.add_import(imp_alias)
    ucm.add_import(imp_external)

    index = SymbolIndex(ucm)
    resolved = RelationshipResolver().resolve_imports(ucm, index)

    # Only provider.py is an internal module in this repo; os must be ignored
    assert len(resolved) == 1
    assert resolved[0].rel_type == RelationshipType.IMPORTS
    assert resolved[0].source_id == f_consumer.id
    assert resolved[0].target_id == m_provider.id


def test_resolvable_function_calls_intra_and_cross_file():
    """Verify resolution of direct function calls intra-file and cross-file."""
    source_utils = """
def format_text(s: str) -> str:
    return s.strip()
"""
    source_main = """
from utils import format_text

def helper(x: str) -> str:
    return x.lower()

def run_app():
    val = format_text(" hello ")
    return helper(val)
"""
    r_utils = extract_python_source(source_utils, "utils.py", repo_id="repo::calls_test")
    r_main = extract_python_source(source_main, "main.py", repo_id="repo::calls_test")

    ucm = r_utils.to_ucm()
    r_main.add_to_ucm(ucm)

    sources = {"utils.py": source_utils, "main.py": source_main}
    resolved_ucm = resolve_relationships(ucm, sources=sources)

    calls = [r for r in resolved_ucm.relationships if r.rel_type == RelationshipType.CALLS]
    caller_targets = {(r.source_id, r.target_id) for r in calls}

    run_app_id = build_function_id("repo::calls_test", "main.run_app")
    format_text_id = build_function_id("repo::calls_test", "utils.format_text")
    helper_id = build_function_id("repo::calls_test", "main.helper")

    # run_app -> format_text (cross-file)
    assert (run_app_id, format_text_id) in caller_targets
    # run_app -> helper (intra-file)
    assert (run_app_id, helper_id) in caller_targets


def test_method_calls_and_receiver_tracking():
    """Verify resolution of method calls with local variables, self, and attributes."""
    source_srv = """
class Worker:
    def execute(self) -> str:
        return "done"
"""
    source_client = """
from srv import Worker

class Client:
    def __init__(self):
        self.worker = Worker()

    def do_work(self) -> str:
        return self.worker.execute()

def main_func():
    w = Worker()
    return w.execute()
"""
    r_srv = extract_python_source(source_srv, "srv.py", repo_id="repo::meth_test")
    r_client = extract_python_source(source_client, "client.py", repo_id="repo::meth_test")

    ucm = r_srv.to_ucm()
    r_client.add_to_ucm(ucm)

    sources = {"srv.py": source_srv, "client.py": source_client}
    resolved_ucm = resolve_relationships(ucm, sources=sources)

    calls = [r for r in resolved_ucm.relationships if r.rel_type == RelationshipType.CALLS]
    call_pairs = {(r.source_id, r.target_id) for r in calls}

    do_work_id = build_method_id("repo::meth_test", "client.Client.do_work")
    execute_id = build_method_id("repo::meth_test", "srv.Worker.execute")
    main_func_id = build_function_id("repo::meth_test", "client.main_func")

    # self.worker.execute() in Client.do_work
    assert (do_work_id, execute_id) in call_pairs
    # w.execute() in main_func
    assert (main_func_id, execute_id) in call_pairs


def test_inheritance_resolution_cross_file_and_super_calls():
    """Verify resolution of INHERITS edges and super() / self calls across inheritance hierarchy."""
    source_base = """
class Base:
    def __init__(self, id_val: str):
        self.id_val = id_val

    def get_id(self) -> str:
        return self.id_val
"""
    source_child = """
from base import Base as CustomBase

class Child(CustomBase):
    def __init__(self, id_val: str):
        super().__init__(id_val)

    def display(self) -> str:
        return self.get_id()
"""
    r_base = extract_python_source(source_base, "base.py", repo_id="repo::inherit_test")
    r_child = extract_python_source(source_child, "child.py", repo_id="repo::inherit_test")

    ucm = r_base.to_ucm()
    r_child.add_to_ucm(ucm)

    sources = {"base.py": source_base, "child.py": source_child}
    resolved_ucm = resolve_relationships(ucm, sources=sources)

    # 1. INHERITS
    inherits = [r for r in resolved_ucm.relationships if r.rel_type == RelationshipType.INHERITS]
    assert len(inherits) == 1
    child_cls_id = build_class_id("repo::inherit_test", "child.Child")
    base_cls_id = build_class_id("repo::inherit_test", "base.Base")
    assert inherits[0].source_id == child_cls_id
    assert inherits[0].target_id == base_cls_id

    # 2. CALLS
    calls = {(r.source_id, r.target_id) for r in resolved_ucm.relationships if r.rel_type == RelationshipType.CALLS}
    child_init_id = build_method_id("repo::inherit_test", "child.Child.__init__")
    base_init_id = build_method_id("repo::inherit_test", "base.Base.__init__")
    child_display_id = build_method_id("repo::inherit_test", "child.Child.display")
    base_get_id = build_method_id("repo::inherit_test", "base.Base.get_id")

    # super().__init__ -> Base.__init__
    assert (child_init_id, base_init_id) in calls
    # self.get_id() -> Base.get_id
    assert (child_display_id, base_get_id) in calls


def test_ambiguous_and_unresolved_references_leave_no_edges():
    """Verify that untyped dynamic receivers and undefined symbols produce no speculative edges."""
    source_ambiguous = """
class Alpha:
    def run(self): pass

class Beta:
    def run(self): pass

def call_worker(worker):
    return worker.run()

def call_unknown():
    return undefined_func()
"""
    r_amb = extract_python_source(source_ambiguous, "amb.py", repo_id="repo::amb_test")
    resolved_ucm = resolve_relationships(r_amb.to_ucm(), sources={"amb.py": source_ambiguous})

    calls = [r for r in resolved_ucm.relationships if r.rel_type == RelationshipType.CALLS]
    # Neither call_worker nor call_unknown should have CALLS edges
    call_workers = [r for r in calls if "call_worker" in r.source_id or "call_unknown" in r.source_id]
    assert call_workers == []


def test_same_name_unrelated_functions_not_conflated():
    """Verify that functions with identical names in different modules are not conflated."""
    src_a = "def process(): return 'a'"
    src_b = "def process(): return 'b'"
    src_runner = """
from mod_a import process as proc_a

def run_both():
    return proc_a()
"""
    r_a = extract_python_source(src_a, "mod_a.py", repo_id="repo::collision")
    r_b = extract_python_source(src_b, "mod_b.py", repo_id="repo::collision")
    r_run = extract_python_source(src_runner, "runner.py", repo_id="repo::collision")

    ucm = r_a.to_ucm()
    r_b.add_to_ucm(ucm)
    r_run.add_to_ucm(ucm)

    sources = {"mod_a.py": src_a, "mod_b.py": src_b, "runner.py": src_runner}
    resolved_ucm = resolve_relationships(ucm, sources=sources)

    calls = [r for r in resolved_ucm.relationships if r.rel_type == RelationshipType.CALLS]
    target_ids = [r.target_id for r in calls]

    # Only mod_a.process is called, NOT mod_b.process
    assert build_function_id("repo::collision", "mod_a.process") in target_ids
    assert build_function_id("repo::collision", "mod_b.process") not in target_ids


def test_repository_isolation():
    """Verify that symbol index and resolution never resolves across repository boundaries."""
    ucm1 = extract_python_source("def shared(): pass", "a.py", repo_id="repo::repo1").to_ucm()
    ucm2 = extract_python_source("def shared(): pass", "a.py", repo_id="repo::repo2").to_ucm()

    index1 = SymbolIndex(ucm1)
    index2 = SymbolIndex(ucm2)

    assert index1.repo_id == "repo::repo1"
    assert index2.repo_id == "repo::repo2"
    # No crossover of entities
    for m in index1.functions_by_qname.values():
        assert m.repo_id == "repo::repo1"
    for m in index2.functions_by_qname.values():
        assert m.repo_id == "repo::repo2"


def test_duplicate_relationship_prevention_and_determinism():
    """Verify deduplication of relationships and identical output across repeated runs."""
    src = """
def helper(): pass

def main():
    helper()
    helper()
"""
    r = extract_python_source(src, "dedup.py", repo_id="repo::dedup")
    sources = {"dedup.py": src}

    run1 = resolve_relationships(r.to_ucm(), sources=sources)
    run2 = resolve_relationships(r.to_ucm(), sources=sources)

    # CALLS relationship between main and helper should be deduplicated
    main_helper_calls = [
        rel for rel in run1.relationships
        if rel.rel_type == RelationshipType.CALLS
    ]
    assert len(main_helper_calls) == 1

    # Exact deterministic identity across repeated runs
    assert run1.to_json() == run2.to_json()


def test_valid_ucm_relationship_endpoints_and_containment_preserved():
    """Verify that all relationship endpoints exist in UCM and CONTAINS edges are preserved."""
    src = """class A:
    def m(self): pass
"""
    r = extract_python_source(src, "tree.py", repo_id="repo::valid")
    resolved = resolve_relationships(r.to_ucm(), sources={"tree.py": src})

    # Every endpoint must exist in the model
    all_entity_ids = {resolved.repository.id}
    for col in (resolved.files, resolved.modules, resolved.classes, resolved.functions, resolved.methods, resolved.imports):
        for item in col:
            all_entity_ids.add(item.id)

    for rel in resolved.relationships:
        assert rel.source_id in all_entity_ids
        assert rel.target_id in all_entity_ids

    # CONTAINS edges from extraction must be intact
    contains = [rel for rel in resolved.relationships if rel.rel_type == RelationshipType.CONTAINS]
    assert len(contains) == 3  # repo->file, file->class, class->method


def test_atlas_fixture_oracle_exact_resolution():
    """Verify relationship resolution against the P0 correctness oracle (tests/fixtures/atlas_fixture).

    Checks exact alignment with tests/fixtures/atlas_fixture/README.md:
    - 37 CONTAINS relationships
    - 5 IMPORTS relationships
    - 1 INHERITS relationship
    - 15 CALLS relationships (all resolvable calls to declared entities in UCM)
    """
    backend_dir = Path(__file__).resolve().parent.parent
    repo_root = backend_dir.parent
    fixture_dir = repo_root / "tests" / "fixtures" / "atlas_fixture"

    assert fixture_dir.exists(), f"Fixture directory not found at {fixture_dir}"

    resolved_ucm = resolve_repository(fixture_dir, repo_name="atlas_fixture")

    # Group relationships by type
    by_type: dict[RelationshipType, list] = {}
    for r in resolved_ucm.relationships:
        by_type.setdefault(r.rel_type, []).append(r)

    # 1. CONTAINS: 37
    contains_rels = by_type.get(RelationshipType.CONTAINS, [])
    assert len(contains_rels) == 37

    # 2. IMPORTS: 5
    imports_rels = by_type.get(RelationshipType.IMPORTS, [])
    assert len(imports_rels) == 5
    import_pairs = sorted((r.source_id, r.target_id) for r in imports_rels)
    expected_imports = sorted([
        ("repo::atlas_fixture::file::ambiguous.py", "repo::atlas_fixture::module::models"),
        ("repo::atlas_fixture::file::app.py", "repo::atlas_fixture::module::services"),
        ("repo::atlas_fixture::file::models.py", "repo::atlas_fixture::module::base"),
        ("repo::atlas_fixture::file::services.py", "repo::atlas_fixture::module::models"),
        ("repo::atlas_fixture::file::services.py", "repo::atlas_fixture::module::utils"),
    ])
    assert import_pairs == expected_imports

    # 3. INHERITS: 1
    inherits_rels = by_type.get(RelationshipType.INHERITS, [])
    assert len(inherits_rels) == 1
    assert inherits_rels[0].source_id == "repo::atlas_fixture::class::models.ItemModel"
    assert inherits_rels[0].target_id == "repo::atlas_fixture::class::base.BaseEntity"

    # 4. CALLS: 15
    calls_rels = by_type.get(RelationshipType.CALLS, [])
    assert len(calls_rels) == 15
    call_pairs = sorted((r.source_id, r.target_id) for r in calls_rels)
    expected_calls = sorted([
        # Intra-func / lexical
        ("repo::atlas_fixture::function::ambiguous.outer_scope_function", "repo::atlas_fixture::function::ambiguous.outer_scope_function.inner_local_function"),
        # app.py
        ("repo::atlas_fixture::function::app.main", "repo::atlas_fixture::method::app.Application.__init__"),
        ("repo::atlas_fixture::function::app.main", "repo::atlas_fixture::function::services.process_item_workflow"),
        ("repo::atlas_fixture::function::app.main", "repo::atlas_fixture::method::app.Application.run"),
        ("repo::atlas_fixture::method::app.Application.run", "repo::atlas_fixture::method::services.ItemService.get_item_summary"),
        # services.py
        ("repo::atlas_fixture::function::services.process_item_workflow", "repo::atlas_fixture::method::services.ItemService.get_item_summary"),
        ("repo::atlas_fixture::function::services.process_item_workflow", "repo::atlas_fixture::method::services.ItemService.create_tagged_item"),
        ("repo::atlas_fixture::method::services.ItemService.get_item_summary", "repo::atlas_fixture::method::models.ItemModel.__init__"),
        ("repo::atlas_fixture::method::services.ItemService.get_item_summary", "repo::atlas_fixture::method::models.ItemModel.get_display_name"),
        ("repo::atlas_fixture::method::services.ItemService.create_tagged_item", "repo::atlas_fixture::function::utils.format_identifier"),
        ("repo::atlas_fixture::method::services.ItemService.create_tagged_item", "repo::atlas_fixture::function::models.create_default_item"),
        # models.py
        ("repo::atlas_fixture::function::models.create_default_item", "repo::atlas_fixture::method::models.ItemModel.__init__"),
        ("repo::atlas_fixture::method::models.ItemModel.__init__", "repo::atlas_fixture::method::base.BaseEntity.__init__"),
        ("repo::atlas_fixture::method::models.ItemModel.get_display_name", "repo::atlas_fixture::method::base.BaseEntity.get_id"),
        # unrelated.py
        ("repo::atlas_fixture::method::unrelated.StandaloneCalculator.compute_total", "repo::atlas_fixture::function::unrelated.sum_values"),
    ])
    assert call_pairs == expected_calls

    # Total relationships in fixture: 37 CONTAINS + 5 IMPORTS + 1 INHERITS + 15 CALLS = 58
    assert len(resolved_ucm.relationships) == 58
