"""Automated tests for Python syntax extraction and UCM entity conversion."""

from pathlib import Path
import pytest

from app.extractor import (
    ExtractionResult,
    PythonExtractor,
    derive_module_info,
    extract_python_file,
    extract_python_repository,
    extract_python_source,
)
from app.parser.models import SyntaxErrorInfo
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


def test_derive_module_info():
    """Verify derivation of module names and qualified names from file paths."""
    assert derive_module_info("app.py") == ("app", "app")
    assert derive_module_info("services.py") == ("services", "services")
    assert derive_module_info("pkg/sub/module.py") == ("module", "pkg.sub.module")
    assert derive_module_info("pkg/__init__.py") == ("pkg", "pkg")
    assert derive_module_info("pkg/sub/__init__.py") == ("sub", "pkg.sub")
    assert derive_module_info("__init__.py") == ("root", "root")


def test_extract_basic_constructs():
    """Verify extraction of standard class, method, function, imports, and docstrings."""
    source = '''"""Module level docstring."""
import os
from typing import Optional as Opt

class WorkerService:
    """Worker service class docstring."""

    def __init__(self, name: str) -> None:
        """Initialize worker."""
        self.name = name

    def process(self) -> str:
        return self.name

def run_worker() -> None:
    """Module-level worker runner."""
    pass
'''
    res = extract_python_source(source, "worker.py", repo_id="repo::test_repo")

    assert isinstance(res, ExtractionResult)
    assert res.is_valid is True
    assert res.has_syntax_errors is False
    assert res.errors == []

    # File and Module
    assert res.file is not None
    assert res.file.id == "repo::test_repo::file::worker.py"
    assert res.file.path == "worker.py"
    assert res.file.language == "python"

    assert res.module is not None
    assert res.module.id == "repo::test_repo::module::worker"
    assert res.module.name == "worker"
    assert res.module.qualified_name == "worker"

    # Classes
    assert len(res.classes) == 1
    worker_cls = res.classes[0]
    assert worker_cls.name == "WorkerService"
    assert worker_cls.qualified_name == "worker.WorkerService"
    assert worker_cls.id == "repo::test_repo::class::worker.WorkerService"
    assert worker_cls.docstring == "Worker service class docstring."

    # Methods
    assert len(res.methods) == 2
    method_names = [m.name for m in res.methods]
    assert method_names == ["__init__", "process"]
    init_m = res.methods[0]
    assert init_m.qualified_name == "worker.WorkerService.__init__"
    assert init_m.id == "repo::test_repo::method::worker.WorkerService.__init__"
    assert init_m.docstring == "Initialize worker."

    # Functions
    assert len(res.functions) == 1
    run_fn = res.functions[0]
    assert run_fn.name == "run_worker"
    assert run_fn.qualified_name == "worker.run_worker"
    assert run_fn.id == "repo::test_repo::function::worker.run_worker"
    assert run_fn.docstring == "Module-level worker runner."

    # Imports
    assert len(res.imports) == 2
    imp_os = res.imports[0]
    assert imp_os.module_name == "os"
    assert imp_os.imported_name == "os"
    assert imp_os.alias is None

    imp_opt = res.imports[1]
    assert imp_opt.module_name == "typing"
    assert imp_opt.imported_name == "Optional"
    assert imp_opt.alias == "Opt"

    # Containment relationships
    rel_map = {(r.source_id, r.target_id) for r in res.relationships}
    assert (res.repository.id, res.file.id) in rel_map
    assert (res.file.id, worker_cls.id) in rel_map
    assert (worker_cls.id, init_m.id) in rel_map
    assert (worker_cls.id, res.methods[1].id) in rel_map
    assert (res.file.id, run_fn.id) in rel_map


def test_extract_nested_definitions_classification_and_containment():
    """Verify correct classification of nested classes, functions, and methods without misclassification."""
    source = '''
class OuterClass:
    class InnerClass:
        def inner_method(self):
            pass

def outer_function():
    def inner_function():
        pass

    class LocalClassInFunc:
        def local_method(self):
            def deep_nested_function():
                pass
'''
    res = extract_python_source(source, "nested.py", repo_id="repo::nested_repo")

    # Classes: OuterClass, OuterClass.InnerClass, outer_function.LocalClassInFunc
    class_qnames = [c.qualified_name for c in res.classes]
    assert class_qnames == [
        "nested.OuterClass",
        "nested.OuterClass.InnerClass",
        "nested.outer_function.LocalClassInFunc",
    ]

    # Methods: inner_method, local_method
    method_qnames = [m.qualified_name for m in res.methods]
    assert method_qnames == [
        "nested.OuterClass.InnerClass.inner_method",
        "nested.outer_function.LocalClassInFunc.local_method",
    ]

    # Functions: outer_function, inner_function, deep_nested_function
    func_qnames = [f.qualified_name for f in res.functions]
    assert func_qnames == [
        "nested.outer_function",
        "nested.outer_function.inner_function",
        "nested.outer_function.LocalClassInFunc.local_method.deep_nested_function",
    ]

    # Check structural containment relationships
    rel_pairs = [(r.source_id, r.target_id) for r in res.relationships]

    # File -> OuterClass -> InnerClass -> inner_method
    file_id = res.file.id
    outer_cls_id = build_class_id("repo::nested_repo", "nested.OuterClass")
    inner_cls_id = build_class_id("repo::nested_repo", "nested.OuterClass.InnerClass")
    inner_meth_id = build_method_id("repo::nested_repo", "nested.OuterClass.InnerClass.inner_meth" if False else "nested.OuterClass.InnerClass.inner_method")

    assert (file_id, outer_cls_id) in rel_pairs
    assert (outer_cls_id, inner_cls_id) in rel_pairs
    assert (inner_cls_id, inner_meth_id) in rel_pairs

    # File -> outer_function -> inner_function
    outer_fn_id = build_function_id("repo::nested_repo", "nested.outer_function")
    inner_fn_id = build_function_id("repo::nested_repo", "nested.outer_function.inner_function")
    assert (file_id, outer_fn_id) in rel_pairs
    assert (outer_fn_id, inner_fn_id) in rel_pairs

    # outer_function -> LocalClassInFunc -> local_method -> deep_nested_function
    local_cls_id = build_class_id("repo::nested_repo", "nested.outer_function.LocalClassInFunc")
    local_meth_id = build_method_id("repo::nested_repo", "nested.outer_function.LocalClassInFunc.local_method")
    deep_fn_id = build_function_id("repo::nested_repo", "nested.outer_function.LocalClassInFunc.local_method.deep_nested_function")

    assert (outer_fn_id, local_cls_id) in rel_pairs
    assert (local_cls_id, local_meth_id) in rel_pairs
    assert (local_meth_id, deep_fn_id) in rel_pairs


def test_source_locations_and_normalized_paths():
    """Verify source ranges and path normalization across Windows/POSIX styles."""
    source = """class Item:
    def get_id(self):
        return 42
"""
    # Windows-style path with redundant relative prefix
    res = extract_python_source(source, r".\services\item.py", repo_id="repo::norm_test")

    assert res.file.path == "services/item.py"
    assert res.file.id == "repo::norm_test::file::services/item.py"
    assert res.module.qualified_name == "services.item"

    # Line and byte range checks (1-indexed lines, 0-indexed bytes)
    assert res.file.start_byte == 0
    assert res.file.end_byte == len(source.encode("utf-8"))

    cls_ent = res.classes[0]
    assert cls_ent.start_line == 1
    assert cls_ent.end_line == 3
    assert cls_ent.start_byte == 0
    assert cls_ent.end_byte == len(source.rstrip().encode("utf-8"))

    meth_ent = res.methods[0]
    assert meth_ent.start_line == 2
    assert meth_ent.end_line == 3


def test_stable_identifiers_repeatability():
    """Verify that repeated extraction of identical source produces identical IDs and UCM."""
    source = """def calculate(a: int, b: int) -> int:
    return a + b
"""
    res1 = extract_python_source(source, "math_ops.py", repo_id="repo::calc")
    res2 = extract_python_source(source, "math_ops.py", repo_id="repo::calc")

    assert res1.file.id == res2.file.id
    assert res1.functions[0].id == res2.functions[0].id
    assert res1.to_ucm().to_json() == res2.to_ucm().to_json()


def test_import_forms_extraction():
    """Verify extraction of diverse import forms: dotted, aliased, multiline, wildcard."""
    source = """
import os, sys as s
from math import sin, cos as c
from .local_mod import Helper
from wildcard_mod import *
from pkg.sub import (
    First,
    Second as S,
)
"""
    res = extract_python_source(source, "imports.py", repo_id="repo::imports_test")
    assert res.is_valid is True

    import_summary = [(i.module_name, i.imported_name, i.alias) for i in res.imports]
    assert ("os", "os", None) in import_summary
    assert ("sys", "sys", "s") in import_summary
    assert ("math", "sin", None) in import_summary
    assert ("math", "cos", "c") in import_summary
    assert (".local_mod", "Helper", None) in import_summary
    assert ("wildcard_mod", "*", None) in import_summary
    assert ("pkg.sub", "First", None) in import_summary
    assert ("pkg.sub", "Second", "S") in import_summary


def test_syntax_errors_and_error_recovery():
    """Verify that syntax errors are surfaced while valid definitions are recovered."""
    mixed_source = """def valid_first() -> int:
    return 1

def broken_syntax(:
    return 2

def valid_second() -> int:
    return 3
"""
    res = extract_python_source(mixed_source, "broken.py", repo_id="repo::error_test")

    assert res.has_syntax_errors is True
    assert res.is_valid is False
    assert len(res.errors) > 0
    assert isinstance(res.errors[0], SyntaxErrorInfo)

    # Valid functions are recovered
    func_names = [f.name for f in res.functions]
    assert "valid_first" in func_names
    assert "valid_second" in func_names


def test_empty_and_comment_only_source():
    """Verify extraction on empty files and comment-only files."""
    res_empty = extract_python_source("", "empty.py", repo_id="repo::empty")
    assert res_empty.file is not None
    assert res_empty.file.start_line == 1
    assert res_empty.file.end_line == 1
    assert res_empty.classes == []
    assert res_empty.functions == []
    assert res_empty.methods == []
    assert res_empty.imports == []

    res_comment = extract_python_source("# Just a comment\n", "comment.py", repo_id="repo::comment")
    assert res_comment.file is not None
    assert res_comment.classes == []
    assert res_comment.functions == []


def test_extract_atlas_fixture_oracle_exact_alignment():
    """Verify full extraction of the P0 correctness oracle (tests/fixtures/atlas_fixture).

    Checks exact alignment with docs/GRAPH_SCHEMA.md and tests/fixtures/atlas_fixture/README.md:
    - 7 files
    - 7 modules
    - 7 classes
    - 12 methods
    - 11 functions (10 module-level + 1 inner_local_function)
    - 8 imports
    - 37 containment relationships
    """
    backend_dir = Path(__file__).resolve().parent.parent
    repo_root = backend_dir.parent
    fixture_dir = repo_root / "tests" / "fixtures" / "atlas_fixture"

    assert fixture_dir.exists(), f"Fixture directory not found at {fixture_dir}"

    ucm = extract_python_repository(fixture_dir, repo_name="atlas_fixture")

    # 1. Files & Modules (7 expected)
    expected_filenames = [
        "ambiguous.py",
        "app.py",
        "base.py",
        "models.py",
        "services.py",
        "unrelated.py",
        "utils.py",
    ]
    extracted_filenames = sorted(f.path for f in ucm.files)
    assert extracted_filenames == expected_filenames
    assert len(ucm.modules) == 7

    # 2. Classes (7 expected)
    expected_classes = [
        "ambiguous.AlphaWorker",
        "ambiguous.BetaWorker",
        "app.Application",
        "base.BaseEntity",
        "models.ItemModel",
        "services.ItemService",
        "unrelated.StandaloneCalculator",
    ]
    extracted_classes = sorted(c.qualified_name for c in ucm.classes)
    assert extracted_classes == expected_classes

    # 3. Methods (12 expected)
    expected_methods = [
        "ambiguous.AlphaWorker.execute_task",
        "ambiguous.BetaWorker.execute_task",
        "app.Application.__init__",
        "app.Application.run",
        "base.BaseEntity.__init__",
        "base.BaseEntity.get_id",
        "models.ItemModel.__init__",
        "models.ItemModel.get_display_name",
        "services.ItemService.create_tagged_item",
        "services.ItemService.get_item_summary",
        "unrelated.StandaloneCalculator.add",
        "unrelated.StandaloneCalculator.compute_total",
    ]
    extracted_methods = sorted(m.qualified_name for m in ucm.methods)
    assert extracted_methods == expected_methods

    # 4. Functions (11 expected: 10 module-level + 1 inner_local_function)
    expected_functions = [
        "ambiguous.call_ambiguous_worker",
        "ambiguous.call_undefined_symbol",
        "ambiguous.dynamic_reflection_dispatch",
        "ambiguous.execute_task",
        "ambiguous.outer_scope_function",
        "ambiguous.outer_scope_function.inner_local_function",
        "app.main",
        "models.create_default_item",
        "services.process_item_workflow",
        "unrelated.sum_values",
        "utils.format_identifier",
    ]
    extracted_functions = sorted(f.qualified_name for f in ucm.functions)
    assert extracted_functions == expected_functions

    # 5. Imports (8 expected)
    expected_import_names = [
        ("ambiguous.py", "missing_symbol"),
        ("ambiguous.py", "MissingModel"),
        ("app.py", "ItemService"),
        ("app.py", "process_item_workflow"),
        ("models.py", "BaseEntity"),
        ("services.py", "ItemModel"),
        ("services.py", "create_default_item"),
        ("services.py", "format_identifier"),
    ]
    extracted_imports = sorted((i.file_path, i.imported_name) for i in ucm.imports)
    assert extracted_imports == sorted(expected_import_names)

    # 6. Relationships (37 CONTAINS expected: 7 repo->file + 7 file->class + 10 file->fn + 12 class->meth + 1 fn->fn)
    assert len(ucm.relationships) == 37
    assert all(r.rel_type == RelationshipType.CONTAINS for r in ucm.relationships)

    # 7. Lossless JSON round-trip
    json_data = ucm.to_json(indent=2)
    restored_ucm = UnifiedCodeModel.from_json(json_data)
    assert restored_ucm == ucm
