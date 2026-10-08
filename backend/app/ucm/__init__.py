"""Unified Code Model (UCM) package.

Provides the typed, language-independent representation of repository code structure
and relationships between static analysis and graph persistence.
"""

from app.ucm.entities import (
    Class,
    File,
    Function,
    Import,
    Method,
    Module,
    Repository,
)
from app.ucm.identity import (
    build_class_id,
    build_file_id,
    build_function_id,
    build_import_id,
    build_method_id,
    build_module_id,
    build_repo_id,
    normalize_path,
)
from app.ucm.model import UnifiedCodeModel
from app.ucm.relationships import (
    Relationship,
    RelationshipType,
    create_calls_rel,
    create_contains_rel,
    create_imports_rel,
    create_inherits_rel,
    create_relationship,
)

__all__ = [
    "Class",
    "File",
    "Function",
    "Import",
    "Method",
    "Module",
    "Relationship",
    "RelationshipType",
    "Repository",
    "UnifiedCodeModel",
    "build_class_id",
    "build_file_id",
    "build_function_id",
    "build_import_id",
    "build_method_id",
    "build_module_id",
    "build_repo_id",
    "create_calls_rel",
    "create_contains_rel",
    "create_imports_rel",
    "create_inherits_rel",
    "create_relationship",
    "normalize_path",
]
