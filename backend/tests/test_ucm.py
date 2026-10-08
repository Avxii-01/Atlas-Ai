"""Automated tests for the Unified Code Model (UCM)."""

import json
import pytest

from app.parser.models import SourcePosition, SourceRange
from app.ucm import (
    Class,
    File,
    Function,
    Import,
    Method,
    Module,
    Relationship,
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
    create_calls_rel,
    create_contains_rel,
    create_imports_rel,
    create_inherits_rel,
    create_relationship,
    normalize_path,
)


def test_entity_creation_all_types():
    """Verify construction of all representative UCM entity types."""
    repo = Repository.create(name="atlas-test", source="https://github.com/example/atlas-test")
    assert repo.id == "repo::atlas-test"
    assert repo.name == "atlas-test"
    assert repo.source == "https://github.com/example/atlas-test"

    file_ent = File.create(repo_id=repo.id, path="./app/main.py", start_line=1, end_line=50, start_byte=0, end_byte=1000)
    assert file_ent.id == f"{repo.id}::file::app/main.py"
    assert file_ent.path == "app/main.py"
    assert file_ent.language == "python"
    assert file_ent.start_line == 1
    assert file_ent.end_line == 50

    module_ent = Module.create(repo_id=repo.id, name="main", qualified_name="app.main", file_path="app/main.py")
    assert module_ent.id == f"{repo.id}::module::app.main"
    assert module_ent.name == "main"
    assert module_ent.qualified_name == "app.main"
    assert module_ent.file_path == "app/main.py"

    class_ent = Class.create(
        repo_id=repo.id,
        name="AppService",
        qualified_name="app.main.AppService",
        file_path="app/main.py",
        start_line=10,
        end_line=30,
        start_byte=150,
        end_byte=500,
        docstring="Main service orchestrator.",
    )
    assert class_ent.id == f"{repo.id}::class::app.main.AppService"
    assert class_ent.name == "AppService"
    assert class_ent.docstring == "Main service orchestrator."

    func_ent = Function.create(
        repo_id=repo.id,
        name="run_app",
        qualified_name="app.main.run_app",
        file_path="app/main.py",
        start_line=35,
        end_line=45,
        start_byte=550,
        end_byte=800,
    )
    assert func_ent.id == f"{repo.id}::function::app.main.run_app"
    assert func_ent.name == "run_app"

    method_ent = Method.create(
        repo_id=repo.id,
        name="start",
        qualified_name="app.main.AppService.start",
        file_path="app/main.py",
        start_line=15,
        end_line=25,
        start_byte=200,
        end_byte=400,
    )
    assert method_ent.id == f"{repo.id}::method::app.main.AppService.start"
    assert method_ent.name == "start"

    import_ent = Import.create(
        repo_id=repo.id,
        file_path="app/main.py",
        module_name="os",
        imported_name="path",
        start_line=1,
        end_line=1,
        alias="p",
    )
    assert import_ent.id == f"{repo.id}::import::app/main.py::L1::path"
    assert import_ent.module_name == "os"
    assert import_ent.imported_name == "path"
    assert import_ent.alias == "p"


def test_stable_identifiers_identical_inputs():
    """Verify that identical inputs produce identical, deterministic IDs."""
    id1 = build_class_id("repo::atlas", "models.ItemModel")
    id2 = build_class_id("repo::atlas", "models.ItemModel")
    assert id1 == id2 == "repo::atlas::class::models.ItemModel"

    f_id1 = build_file_id("repo::atlas", ".\\tests/fixtures\\atlas_fixture/app.py")
    f_id2 = build_file_id("repo::atlas", "tests/fixtures/atlas_fixture/app.py")
    assert f_id1 == f_id2 == "repo::atlas::file::tests/fixtures/atlas_fixture/app.py"

    imp_id1 = build_import_id("repo::atlas", "services.py", 5, "ItemModel")
    imp_id2 = build_import_id("repo::atlas", "./services.py", 5, "ItemModel")
    assert imp_id1 == imp_id2 == "repo::atlas::import::services.py::L5::ItemModel"


def test_distinct_identifiers_for_distinct_entities():
    """Verify that distinct entity types and definitions receive distinct IDs."""
    repo = "repo::atlas"
    qname = "domain.Worker"

    class_id = build_class_id(repo, qname)
    func_id = build_function_id(repo, qname)
    method_id = build_method_id(repo, qname)
    module_id = build_module_id(repo, qname)

    all_ids = {class_id, func_id, method_id, module_id}
    assert len(all_ids) == 4
    assert class_id != func_id
    assert func_id != method_id
    assert method_id != module_id


def test_source_locations_and_source_metadata():
    """Verify accurate retention and representation of source ranges."""
    pos_start = SourcePosition(line=12, column=4)
    pos_end = SourcePosition(line=18, column=20)
    rng = SourceRange(start_point=pos_start, end_point=pos_end, start_byte=240, end_byte=390)

    rel = create_calls_rel(
        source_id="repo::a::method::A.run",
        target_id="repo::a::method::B.exec",
        location=rng,
        metadata={"call_type": "method_invocation"},
    )

    assert rel.location is not None
    assert rel.location.start_point.line == 12
    assert rel.location.start_point.column == 4
    assert rel.location.end_point.line == 18
    assert rel.location.end_point.column == 20
    assert rel.location.start_byte == 240
    assert rel.location.end_byte == 390
    assert rel.metadata == {"call_type": "method_invocation"}


def test_relationship_records_all_types():
    """Verify typed relationship models for CONTAINS, IMPORTS, CALLS, and INHERITS."""
    r1 = create_contains_rel("repo::test::file::app.py", "repo::test::class::App")
    assert r1.rel_type == RelationshipType.CONTAINS
    assert r1.source_id == "repo::test::file::app.py"
    assert r1.target_id == "repo::test::class::App"

    r2 = create_imports_rel("repo::test::file::app.py", "repo::test::module::services")
    assert r2.rel_type == RelationshipType.IMPORTS

    r3 = create_calls_rel("repo::test::function::main", "repo::test::function::helper")
    assert r3.rel_type == RelationshipType.CALLS

    r4 = create_inherits_rel("repo::test::class::Child", "repo::test::class::Parent")
    assert r4.rel_type == RelationshipType.INHERITS

    # Verify string conversion to RelationshipType
    r_str = create_relationship("CONTAINS", "s", "t")
    assert r_str.rel_type == RelationshipType.CONTAINS


def test_invalid_model_data_and_relationships_raise_validation_errors():
    """Verify validation guards on model entities and relationships."""
    # Empty repository name
    with pytest.raises(ValueError, match="Repository.name"):
        Repository.create(name="", source="local")

    # Inverted line range
    with pytest.raises(ValueError, match="start_line must be >= 1"):
        File.create(repo_id="r1", path="a.py", start_line=0, end_line=10)

    with pytest.raises(ValueError, match="cannot be less than start_line"):
        File.create(repo_id="r1", path="a.py", start_line=20, end_line=10)

    # Inverted byte range
    with pytest.raises(ValueError, match="cannot be less than start_byte"):
        Class.create(
            repo_id="r1",
            name="C",
            qualified_name="m.C",
            file_path="m.py",
            start_line=1,
            end_line=10,
            start_byte=100,
            end_byte=50,
        )

    # Invalid relationship type
    with pytest.raises(ValueError, match="Invalid relationship type"):
        create_relationship("INVALID_EDGE", "src", "tgt")

    # Empty source_id / target_id
    with pytest.raises(ValueError, match="source_id"):
        create_contains_rel("", "tgt")

    with pytest.raises(ValueError, match="target_id"):
        create_contains_rel("src", "   ")


def test_serialization_and_deserialization_round_trips():
    """Verify full fidelity JSON round-trips for all entities and relationships."""
    repo = Repository.create(name="atlas-fixture", source="file:///fixtures")
    file_ent = File.create(repo_id=repo.id, path="services.py", start_line=1, end_line=30, start_byte=0, end_byte=600)
    mod_ent = Module.create(repo_id=repo.id, name="services", qualified_name="services", file_path="services.py")
    cls_ent = Class.create(
        repo_id=repo.id,
        name="ItemService",
        qualified_name="services.ItemService",
        file_path="services.py",
        start_line=5,
        end_line=20,
        start_byte=80,
        end_byte=400,
        docstring="Service layer.",
    )
    meth_ent = Method.create(
        repo_id=repo.id,
        name="get_summary",
        qualified_name="services.ItemService.get_summary",
        file_path="services.py",
        start_line=8,
        end_line=15,
        start_byte=120,
        end_byte=300,
    )
    func_ent = Function.create(
        repo_id=repo.id,
        name="process_item",
        qualified_name="services.process_item",
        file_path="services.py",
        start_line=22,
        end_line=28,
        start_byte=420,
        end_byte=550,
    )
    imp_ent = Import.create(
        repo_id=repo.id,
        file_path="services.py",
        module_name="models",
        imported_name="ItemModel",
        start_line=1,
        end_line=1,
    )

    rng = SourceRange(
        start_point=SourcePosition(line=10, column=8),
        end_point=SourcePosition(line=10, column=32),
        start_byte=150,
        end_byte=174,
    )
    rel_contains = create_contains_rel(file_ent.id, cls_ent.id)
    rel_calls = create_calls_rel(meth_ent.id, "repo::atlas-fixture::method::models.ItemModel.get_id", location=rng)

    ucm = UnifiedCodeModel(repository=repo)
    ucm.add_file(file_ent)
    ucm.add_module(mod_ent)
    ucm.add_class(cls_ent)
    ucm.add_method(meth_ent)
    ucm.add_function(func_ent)
    ucm.add_import(imp_ent)
    ucm.add_relationship(rel_contains)
    ucm.add_relationship(rel_calls)

    # 1. Dict round-trip
    data_dict = ucm.to_dict()
    restored_from_dict = UnifiedCodeModel.from_dict(data_dict)
    assert restored_from_dict == ucm

    # 2. JSON string round-trip
    json_str = ucm.to_json(indent=2)
    restored_from_json = UnifiedCodeModel.from_json(json_str)
    assert restored_from_json == ucm

    # 3. Entity lookup by ID
    found_cls = ucm.get_entity_by_id(cls_ent.id)
    assert found_cls == cls_ent
    found_repo = ucm.get_entity_by_id(repo.id)
    assert found_repo == repo
    assert ucm.get_entity_by_id("nonexistent_id") is None


def test_representative_atlas_fixture_ucm():
    """Verify modeling of representative entities and relationships from tests/fixtures/atlas_fixture."""
    repo = Repository.create(name="atlas_fixture", source="tests/fixtures/atlas_fixture")
    ucm = UnifiedCodeModel(repository=repo)

    # Files
    f_app = File.create(repo.id, "app.py", 26)
    f_services = File.create(repo.id, "services.py", 26)
    f_models = File.create(repo.id, "models.py", 21)
    f_base = File.create(repo.id, "base.py", 12)
    f_utils = File.create(repo.id, "utils.py", 6)
    f_unrelated = File.create(repo.id, "unrelated.py", 21)

    for f in (f_app, f_services, f_models, f_base, f_utils, f_unrelated):
        ucm.add_file(f)
        ucm.add_relationship(create_contains_rel(repo.id, f.id))

    # Modules
    m_app = Module.create(repo.id, "app", "app", "app.py")
    m_services = Module.create(repo.id, "services", "services", "services.py")
    m_models = Module.create(repo.id, "models", "models", "models.py")
    m_base = Module.create(repo.id, "base", "base", "base.py")
    m_utils = Module.create(repo.id, "utils", "utils", "utils.py")
    m_unrelated = Module.create(repo.id, "unrelated", "unrelated", "unrelated.py")

    for m in (m_app, m_services, m_models, m_base, m_utils, m_unrelated):
        ucm.add_module(m)

    # Classes
    c_base = Class.create(repo.id, "BaseEntity", "base.BaseEntity", "base.py", 4, 12, 60, 220)
    c_model = Class.create(repo.id, "ItemModel", "models.ItemModel", "models.py", 6, 17, 80, 420)
    c_service = Class.create(repo.id, "ItemService", "services.ItemService", "services.py", 7, 19, 100, 520)
    c_app = Class.create(repo.id, "Application", "app.Application", "app.py", 6, 15, 80, 360)
    c_calc = Class.create(repo.id, "StandaloneCalculator", "unrelated.StandaloneCalculator", "unrelated.py", 4, 14, 80, 350)

    for c in (c_base, c_model, c_service, c_app, c_calc):
        ucm.add_class(c)

    # Methods
    m_base_init = Method.create(repo.id, "__init__", "base.BaseEntity.__init__", "base.py", 7, 8, 120, 180)
    m_base_get_id = Method.create(repo.id, "get_id", "base.BaseEntity.get_id", "base.py", 10, 12, 190, 250)
    m_model_init = Method.create(repo.id, "__init__", "models.ItemModel.__init__", "models.py", 9, 11, 180, 280)
    m_model_display = Method.create(repo.id, "get_display_name", "models.ItemModel.get_display_name", "models.py", 13, 16, 290, 430)
    m_service_summary = Method.create(repo.id, "get_item_summary", "services.ItemService.get_item_summary", "services.py", 10, 13, 200, 360)
    m_app_run = Method.create(repo.id, "run", "app.Application.run", "app.py", 12, 14, 210, 350)

    for meth in (m_base_init, m_base_get_id, m_model_init, m_model_display, m_service_summary, m_app_run):
        ucm.add_method(meth)

    # Functions
    fn_main = Function.create(repo.id, "main", "app.main", "app.py", 18, 23, 370, 550)
    fn_workflow = Function.create(repo.id, "process_item_workflow", "services.process_item_workflow", "services.py", 22, 27, 530, 720)
    fn_create_item = Function.create(repo.id, "create_default_item", "models.create_default_item", "models.py", 20, 22, 440, 560)
    fn_format = Function.create(repo.id, "format_identifier", "utils.format_identifier", "utils.py", 4, 6, 70, 160)
    fn_sum = Function.create(repo.id, "sum_values", "unrelated.sum_values", "unrelated.py", 17, 22, 360, 500)

    for fn in (fn_main, fn_workflow, fn_create_item, fn_format, fn_sum):
        ucm.add_function(fn)

    # INHERITS relationship
    rel_inherits = create_inherits_rel(c_model.id, c_base.id)
    ucm.add_relationship(rel_inherits)

    # IMPORTS relationships
    rel_imp_app = create_imports_rel(f_app.id, m_services.id)
    rel_imp_srv_mod = create_imports_rel(f_services.id, m_models.id)
    rel_imp_srv_utl = create_imports_rel(f_services.id, m_utils.id)
    rel_imp_mod_base = create_imports_rel(f_models.id, m_base.id)

    for r in (rel_imp_app, rel_imp_srv_mod, rel_imp_srv_utl, rel_imp_mod_base):
        ucm.add_relationship(r)

    # CALLS relationships
    rel_call_app_srv = create_calls_rel(m_app_run.id, m_service_summary.id)
    rel_call_srv_disp = create_calls_rel(m_service_summary.id, m_model_display.id)
    rel_call_disp_base = create_calls_rel(m_model_display.id, m_base_get_id.id)

    for r in (rel_call_app_srv, rel_call_srv_disp, rel_call_disp_base):
        ucm.add_relationship(r)

    # Assert model metrics
    assert len(ucm.files) == 6
    assert len(ucm.modules) == 6
    assert len(ucm.classes) == 5
    assert len(ucm.methods) == 6
    assert len(ucm.functions) == 5
    assert len(ucm.relationships) == 14  # 6 contains + 1 inherits + 4 imports + 3 calls

    # Verify JSON round-trip of full representative model
    serialized = ucm.to_json(indent=2)
    deserialized = UnifiedCodeModel.from_json(serialized)
    assert deserialized == ucm
    assert deserialized.repository.name == "atlas_fixture"
    assert len(deserialized.relationships) == 14
