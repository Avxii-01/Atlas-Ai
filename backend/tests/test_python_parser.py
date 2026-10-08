"""Automated tests for the Tree-sitter Python parser foundation."""

from pathlib import Path

import pytest

from app.parser import (
    ParseResult,
    PythonParser,
    SourcePosition,
    SourceRange,
    SyntaxErrorInfo,
    find_nodes_by_type,
    parse_python,
    walk_tree,
)


def test_parse_simple_valid_source():
    """Verify parsing of a simple valid Python source string."""
    source = "x = 42\ny = x + 1\nprint(y)\n"
    parser = PythonParser()
    result = parser.parse(source)

    assert isinstance(result, ParseResult)
    assert result.is_valid is True
    assert result.has_syntax_errors is False
    assert result.is_recoverable is False
    assert result.errors == []
    assert result.tree is not None
    assert result.root_node is not None
    assert result.root_node.type == "module"
    assert result.source_bytes == source.encode("utf-8")

    # Verify source position mapping on root node
    root_range = SourceRange.from_node(result.root_node)
    assert root_range.start_point == SourcePosition(line=1, column=0)
    assert root_range.start_byte == 0
    assert root_range.end_byte == len(source.encode("utf-8"))


def test_parse_constructs_functions_classes_methods_imports_inheritance():
    """Verify extraction of core Python syntax constructs: functions, classes, methods, imports, inheritance."""
    source = """import os
from typing import Optional

class BaseEntity:
    def __init__(self, id_val: str) -> None:
        self.id_val = id_val

class ItemModel(BaseEntity):
    def get_name(self) -> str:
        return "Item"

def compute_total(a: int, b: int) -> int:
    return a + b
"""
    result = parse_python(source)

    assert result.is_valid is True
    assert result.has_syntax_errors is False
    assert result.root_node is not None

    # Verify import statements
    import_stmts = find_nodes_by_type(result.root_node, "import_statement")
    assert len(import_stmts) == 1
    assert b"import os" in import_stmts[0].text

    import_from_stmts = find_nodes_by_type(result.root_node, "import_from_statement")
    assert len(import_from_stmts) == 1
    assert b"from typing import Optional" in import_from_stmts[0].text

    # Verify class definitions
    class_defs = find_nodes_by_type(result.root_node, "class_definition")
    assert len(class_defs) == 2

    # Verify BaseEntity class
    base_class = class_defs[0]
    base_name_node = base_class.child_by_field_name("name")
    assert base_name_node is not None
    assert base_name_node.text == b"BaseEntity"

    # Verify ItemModel class and inheritance from BaseEntity
    item_class = class_defs[1]
    item_name_node = item_class.child_by_field_name("name")
    assert item_name_node is not None
    assert item_name_node.text == b"ItemModel"

    superclasses = item_class.child_by_field_name("superclasses")
    assert superclasses is not None
    assert b"BaseEntity" in superclasses.text

    # Verify function/method definitions
    func_defs = find_nodes_by_type(result.root_node, "function_definition")
    # BaseEntity.__init__, ItemModel.get_name, and module-level compute_total
    assert len(func_defs) == 3

    func_names = [f.child_by_field_name("name").text for f in func_defs if f.child_by_field_name("name")]
    assert b"__init__" in func_names
    assert b"get_name" in func_names
    assert b"compute_total" in func_names


def test_syntax_tree_traversal_and_deterministic_order():
    """Verify deterministic pre-order traversal and node filtering."""
    source = """def outer():
    x = 1
    def inner():
        return x
    return inner()
"""
    result = parse_python(source)
    assert result.is_valid is True

    visited_types = [node.type for node in walk_tree(result.root_node)]

    # Pre-order check: module appears first, followed by outer function_definition before its body
    assert visited_types[0] == "module"
    assert visited_types[1] == "function_definition"

    # Verify find_nodes_by_type with multiple target types
    targets = find_nodes_by_type(result.root_node, {"function_definition", "return_statement"})
    types_found = [t.type for t in targets]
    assert "function_definition" in types_found
    assert "return_statement" in types_found
    assert types_found.count("function_definition") == 2
    assert types_found.count("return_statement") == 2


def test_malformed_syntax_error_detection():
    """Verify that malformed Python syntax is detected and structured error details are returned."""
    # Omitted closing parenthesis in parameters
    malformed_source = "def broken(:\n    pass\n"
    result = parse_python(malformed_source)

    assert result.is_valid is False
    assert result.has_syntax_errors is True
    assert len(result.errors) > 0

    error_info = result.errors[0]
    assert isinstance(error_info, SyntaxErrorInfo)
    assert error_info.range.start_point.line == 1
    assert "line 1" in error_info.message

    # Completely invalid statement
    malformed_stmt = "class 1234:\n    pass\n"
    res_stmt = parse_python(malformed_stmt)
    assert res_stmt.is_valid is False
    assert res_stmt.has_syntax_errors is True
    assert len(res_stmt.errors) > 0


def test_malformed_source_recovery_without_uncaught_exception():
    """Verify that a malformed source file produces a recoverable partial tree without crashing."""
    mixed_source = """def valid_first() -> int:
    return 1

def broken_syntax(:
    return 2

def valid_second() -> int:
    return 3
"""
    parser = PythonParser()
    result = parser.parse(mixed_source)

    # Parsing must not crash and must flag syntax errors
    assert result.has_syntax_errors is True
    assert result.is_valid is False
    assert result.is_recoverable is True
    assert result.tree is not None
    assert len(result.errors) > 0

    # Tree-sitter must recover and retain the valid function definitions
    func_nodes = find_nodes_by_type(result.root_node, "function_definition")
    func_names = [f.child_by_field_name("name").text for f in func_nodes if f.child_by_field_name("name")]

    assert b"valid_first" in func_names
    assert b"valid_second" in func_names


def test_parse_representative_atlas_fixture_files():
    """Verify that representative source files from tests/fixtures/atlas_fixture parse successfully."""
    backend_dir = Path(__file__).resolve().parent.parent
    repo_root = backend_dir.parent
    fixture_dir = repo_root / "tests" / "fixtures" / "atlas_fixture"

    assert fixture_dir.exists(), f"Fixture directory not found at {fixture_dir}"

    expected_files = [
        "app.py",
        "services.py",
        "models.py",
        "base.py",
        "utils.py",
        "unrelated.py",
        "ambiguous.py",
    ]

    parser = PythonParser()

    for filename in expected_files:
        file_path = fixture_dir / filename
        assert file_path.exists(), f"Expected fixture file {filename} missing"

        result = parser.parse_file(file_path)

        assert result.is_valid is True, f"{filename} failed syntax validation: {result.errors}"
        assert result.has_syntax_errors is False
        assert result.tree is not None
        assert result.file_path == str(file_path)
        assert result.root_node.type == "module"

    # Semantic structural checks on parsed fixture trees
    # 1. models.py: ItemModel inherits BaseEntity
    models_res = parser.parse_file(fixture_dir / "models.py")
    classes = find_nodes_by_type(models_res.root_node, "class_definition")
    assert len(classes) == 1
    assert classes[0].child_by_field_name("name").text == b"ItemModel"
    assert b"BaseEntity" in classes[0].child_by_field_name("superclasses").text

    # 2. app.py: Application class and main function
    app_res = parser.parse_file(fixture_dir / "app.py")
    app_classes = find_nodes_by_type(app_res.root_node, "class_definition")
    assert len(app_classes) == 1
    assert app_classes[0].child_by_field_name("name").text == b"Application"
    app_funcs = find_nodes_by_type(app_res.root_node, "function_definition")
    app_func_names = [f.child_by_field_name("name").text for f in app_funcs]
    assert b"main" in app_func_names

    # 3. unrelated.py: StandaloneCalculator class and sum_values function
    unrelated_res = parser.parse_file(fixture_dir / "unrelated.py")
    unrelated_classes = find_nodes_by_type(unrelated_res.root_node, "class_definition")
    assert len(unrelated_classes) == 1
    assert unrelated_classes[0].child_by_field_name("name").text == b"StandaloneCalculator"
    unrelated_funcs = find_nodes_by_type(unrelated_res.root_node, "function_definition")
    unrelated_func_names = [f.child_by_field_name("name").text for f in unrelated_funcs]
    assert b"sum_values" in unrelated_func_names


def test_parse_file_nonexistent_returns_io_error():
    """Verify that attempting to parse a nonexistent file returns a structured error without throwing."""
    parser = PythonParser()
    result = parser.parse_file("nonexistent_phantom_path.py")

    assert result.is_valid is False
    assert result.has_syntax_errors is True
    assert result.tree is None
    assert len(result.errors) == 1
    assert result.errors[0].node_type == "IO_ERROR"
    assert "Failed to read file" in result.errors[0].message
