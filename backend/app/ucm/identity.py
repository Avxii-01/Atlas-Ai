"""Deterministic identity generation and path normalization for the Unified Code Model."""

from pathlib import Path, PurePosixPath
import re


def normalize_path(path: str | Path) -> str:
    """Normalize file paths to standard repository-relative POSIX format.

    Replaces Windows-style backslashes with forward slashes, strips redundant
    current-directory prefixes ('./'), and removes leading/trailing slashes.

    Args:
        path: Path string or Path object to normalize.

    Returns:
        Normalized relative path string using forward slashes (e.g. 'models.py', 'pkg/sub.py').
    """
    raw_str = str(path).strip().replace("\\", "/")
    # Remove leading './' or '/'
    raw_str = re.sub(r"^\.?/+", "", raw_str)
    # Collapse duplicate slashes and resolve '.' segments
    parts = [segment for segment in raw_str.split("/") if segment and segment != "."]
    normalized = "/".join(parts)
    return normalized


def build_repo_id(repo_name: str) -> str:
    """Generate a deterministic identifier for a Repository entity."""
    clean_name = repo_name.strip()
    if not clean_name:
        raise ValueError("Repository name cannot be empty")
    return f"repo::{clean_name}"


def build_file_id(repo_id: str, relative_path: str | Path) -> str:
    """Generate a deterministic identifier for a File entity."""
    if not repo_id or not repo_id.strip():
        raise ValueError("Repository ID cannot be empty")
    norm_path = normalize_path(relative_path)
    if not norm_path:
        raise ValueError("File path cannot be empty")
    return f"{repo_id}::file::{norm_path}"


def build_module_id(repo_id: str, qualified_name: str) -> str:
    """Generate a deterministic identifier for a Module entity."""
    if not repo_id or not repo_id.strip():
        raise ValueError("Repository ID cannot be empty")
    clean_qname = qualified_name.strip()
    if not clean_qname:
        raise ValueError("Module qualified name cannot be empty")
    return f"{repo_id}::module::{clean_qname}"


def build_class_id(repo_id: str, qualified_name: str) -> str:
    """Generate a deterministic identifier for a Class entity."""
    if not repo_id or not repo_id.strip():
        raise ValueError("Repository ID cannot be empty")
    clean_qname = qualified_name.strip()
    if not clean_qname:
        raise ValueError("Class qualified name cannot be empty")
    return f"{repo_id}::class::{clean_qname}"


def build_function_id(repo_id: str, qualified_name: str) -> str:
    """Generate a deterministic identifier for a Function entity."""
    if not repo_id or not repo_id.strip():
        raise ValueError("Repository ID cannot be empty")
    clean_qname = qualified_name.strip()
    if not clean_qname:
        raise ValueError("Function qualified name cannot be empty")
    return f"{repo_id}::function::{clean_qname}"


def build_method_id(repo_id: str, qualified_name: str) -> str:
    """Generate a deterministic identifier for a Method entity."""
    if not repo_id or not repo_id.strip():
        raise ValueError("Repository ID cannot be empty")
    clean_qname = qualified_name.strip()
    if not clean_qname:
        raise ValueError("Method qualified name cannot be empty")
    return f"{repo_id}::method::{clean_qname}"


def build_import_id(repo_id: str, relative_path: str | Path, line: int, imported_name: str) -> str:
    """Generate a deterministic identifier for an Import entity."""
    if not repo_id or not repo_id.strip():
        raise ValueError("Repository ID cannot be empty")
    norm_path = normalize_path(relative_path)
    if not norm_path:
        raise ValueError("Import file path cannot be empty")
    if line < 1:
        raise ValueError("Import line must be >= 1")
    clean_name = imported_name.strip()
    if not clean_name:
        raise ValueError("Imported symbol name cannot be empty")
    return f"{repo_id}::import::{norm_path}::L{line}::{clean_name}"
