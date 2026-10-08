"""Typed entity definitions for the Unified Code Model."""

from dataclasses import dataclass, field
from typing import Any

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


def _validate_non_empty(value: str, field_name: str) -> str:
    """Validate that a string field is not empty or pure whitespace."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _validate_line_range(start_line: int, end_line: int) -> None:
    """Validate that line numbers are 1-indexed and start_line <= end_line."""
    if start_line < 1:
        raise ValueError(f"start_line must be >= 1, got {start_line}")
    if end_line < start_line:
        raise ValueError(f"end_line ({end_line}) cannot be less than start_line ({start_line})")


def _validate_byte_range(start_byte: int, end_byte: int) -> None:
    """Validate that byte offsets are non-negative and start_byte <= end_byte."""
    if start_byte < 0:
        raise ValueError(f"start_byte must be >= 0, got {start_byte}")
    if end_byte < start_byte:
        raise ValueError(f"end_byte ({end_byte}) cannot be less than start_byte ({start_byte})")


@dataclass(frozen=True)
class Repository:
    """Represents an analyzed repository in the Unified Code Model.

    Attributes:
        id: Stable unique repository identifier.
        name: Human-readable name of the repository.
        source: Source origin (e.g. file URI or git URL).
        created_at: Optional ISO 8601 timestamp string.
    """

    id: str
    name: str
    source: str
    created_at: str | None = None

    def __post_init__(self) -> None:
        _validate_non_empty(self.id, "Repository.id")
        _validate_non_empty(self.name, "Repository.name")
        _validate_non_empty(self.source, "Repository.source")

    @classmethod
    def create(cls, name: str, source: str, created_at: str | None = None, repo_id: str | None = None) -> "Repository":
        """Factory method computing the deterministic repository ID if omitted."""
        clean_name = _validate_non_empty(name, "Repository.name")
        computed_id = repo_id if repo_id else build_repo_id(clean_name)
        return cls(id=computed_id, name=clean_name, source=source.strip(), created_at=created_at)

    def to_dict(self) -> dict[str, Any]:
        """Serialize entity to a plain dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "source": self.source,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Repository":
        """Deserialize entity from a plain dictionary."""
        return cls(
            id=data["id"],
            name=data["name"],
            source=data["source"],
            created_at=data.get("created_at"),
        )


@dataclass(frozen=True)
class File:
    """Represents a source file in the repository.

    Attributes:
        id: Deterministic identifier: '{repo_id}::file::{normalized_path}'.
        repo_id: Owning repository ID.
        path: Normalized repository-relative file path.
        language: Programming language identifier ('python').
        start_line: Starting line (1-indexed).
        end_line: Ending line (1-indexed).
        start_byte: 0-indexed byte offset of file start.
        end_byte: 0-indexed byte offset of file end.
    """

    id: str
    repo_id: str
    path: str
    language: str
    start_line: int
    end_line: int
    start_byte: int = 0
    end_byte: int = 0

    def __post_init__(self) -> None:
        _validate_non_empty(self.id, "File.id")
        _validate_non_empty(self.repo_id, "File.repo_id")
        _validate_non_empty(self.path, "File.path")
        _validate_non_empty(self.language, "File.language")
        _validate_line_range(self.start_line, self.end_line)
        _validate_byte_range(self.start_byte, self.end_byte)

    @classmethod
    def create(
        cls,
        repo_id: str,
        path: str,
        end_line: int,
        start_line: int = 1,
        language: str = "python",
        start_byte: int = 0,
        end_byte: int = 0,
        file_id: str | None = None,
    ) -> "File":
        """Factory method computing the deterministic file ID and normalizing path."""
        norm_path = normalize_path(path)
        computed_id = file_id if file_id else build_file_id(repo_id, norm_path)
        return cls(
            id=computed_id,
            repo_id=repo_id,
            path=norm_path,
            language=language,
            start_line=start_line,
            end_line=end_line,
            start_byte=start_byte,
            end_byte=end_byte,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize entity to a plain dictionary."""
        return {
            "id": self.id,
            "repo_id": self.repo_id,
            "path": self.path,
            "language": self.language,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "start_byte": self.start_byte,
            "end_byte": self.end_byte,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "File":
        """Deserialize entity from a plain dictionary."""
        return cls(
            id=data["id"],
            repo_id=data["repo_id"],
            path=data["path"],
            language=data["language"],
            start_line=data["start_line"],
            end_line=data["end_line"],
            start_byte=data.get("start_byte", 0),
            end_byte=data.get("end_byte", 0),
        )


@dataclass(frozen=True)
class Module:
    """Represents a logical Python module within the repository.

    Attributes:
        id: Deterministic identifier: '{repo_id}::module::{qualified_name}'.
        repo_id: Owning repository ID.
        name: Short name of the module (e.g. 'models').
        qualified_name: Fully qualified module name (e.g. 'pkg.models').
        file_path: Normalized path to the implementing source file.
    """

    id: str
    repo_id: str
    name: str
    qualified_name: str
    file_path: str

    def __post_init__(self) -> None:
        _validate_non_empty(self.id, "Module.id")
        _validate_non_empty(self.repo_id, "Module.repo_id")
        _validate_non_empty(self.name, "Module.name")
        _validate_non_empty(self.qualified_name, "Module.qualified_name")
        _validate_non_empty(self.file_path, "Module.file_path")

    @classmethod
    def create(
        cls,
        repo_id: str,
        name: str,
        qualified_name: str,
        file_path: str,
        module_id: str | None = None,
    ) -> "Module":
        """Factory method computing the deterministic module ID."""
        computed_id = module_id if module_id else build_module_id(repo_id, qualified_name)
        return cls(
            id=computed_id,
            repo_id=repo_id,
            name=name.strip(),
            qualified_name=qualified_name.strip(),
            file_path=normalize_path(file_path),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize entity to a plain dictionary."""
        return {
            "id": self.id,
            "repo_id": self.repo_id,
            "name": self.name,
            "qualified_name": self.qualified_name,
            "file_path": self.file_path,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Module":
        """Deserialize entity from a plain dictionary."""
        return cls(
            id=data["id"],
            repo_id=data["repo_id"],
            name=data["name"],
            qualified_name=data["qualified_name"],
            file_path=data["file_path"],
        )


@dataclass(frozen=True)
class Class:
    """Represents a class declaration in the Unified Code Model.

    Attributes:
        id: Deterministic identifier: '{repo_id}::class::{qualified_name}'.
        repo_id: Owning repository ID.
        name: Short name of the class.
        qualified_name: Fully qualified name (e.g. 'models.ItemModel').
        file_path: Normalized path to the containing file.
        language: Programming language ('python').
        start_line: Starting line (1-indexed).
        end_line: Ending line (1-indexed).
        start_byte: 0-indexed start byte.
        end_byte: 0-indexed end byte.
        docstring: Optional docstring text.
    """

    id: str
    repo_id: str
    name: str
    qualified_name: str
    file_path: str
    language: str
    start_line: int
    end_line: int
    start_byte: int
    end_byte: int
    docstring: str | None = None

    def __post_init__(self) -> None:
        _validate_non_empty(self.id, "Class.id")
        _validate_non_empty(self.repo_id, "Class.repo_id")
        _validate_non_empty(self.name, "Class.name")
        _validate_non_empty(self.qualified_name, "Class.qualified_name")
        _validate_non_empty(self.file_path, "Class.file_path")
        _validate_non_empty(self.language, "Class.language")
        _validate_line_range(self.start_line, self.end_line)
        _validate_byte_range(self.start_byte, self.end_byte)

    @classmethod
    def create(
        cls,
        repo_id: str,
        name: str,
        qualified_name: str,
        file_path: str,
        start_line: int,
        end_line: int,
        start_byte: int,
        end_byte: int,
        language: str = "python",
        docstring: str | None = None,
        class_id: str | None = None,
    ) -> "Class":
        """Factory method computing the deterministic class ID."""
        computed_id = class_id if class_id else build_class_id(repo_id, qualified_name)
        return cls(
            id=computed_id,
            repo_id=repo_id,
            name=name.strip(),
            qualified_name=qualified_name.strip(),
            file_path=normalize_path(file_path),
            language=language,
            start_line=start_line,
            end_line=end_line,
            start_byte=start_byte,
            end_byte=end_byte,
            docstring=docstring,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize entity to a plain dictionary."""
        return {
            "id": self.id,
            "repo_id": self.repo_id,
            "name": self.name,
            "qualified_name": self.qualified_name,
            "file_path": self.file_path,
            "language": self.language,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "start_byte": self.start_byte,
            "end_byte": self.end_byte,
            "docstring": self.docstring,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Class":
        """Deserialize entity from a plain dictionary."""
        return cls(
            id=data["id"],
            repo_id=data["repo_id"],
            name=data["name"],
            qualified_name=data["qualified_name"],
            file_path=data["file_path"],
            language=data["language"],
            start_line=data["start_line"],
            end_line=data["end_line"],
            start_byte=data["start_byte"],
            end_byte=data["end_byte"],
            docstring=data.get("docstring"),
        )


@dataclass(frozen=True)
class Function:
    """Represents a module-level function declaration in the Unified Code Model.

    Attributes:
        id: Deterministic identifier: '{repo_id}::function::{qualified_name}'.
        repo_id: Owning repository ID.
        name: Short name of the function.
        qualified_name: Fully qualified name (e.g. 'services.process_item_workflow').
        file_path: Normalized path to the containing file.
        language: Programming language ('python').
        start_line: Starting line (1-indexed).
        end_line: Ending line (1-indexed).
        start_byte: 0-indexed start byte.
        end_byte: 0-indexed end byte.
        docstring: Optional docstring text.
    """

    id: str
    repo_id: str
    name: str
    qualified_name: str
    file_path: str
    language: str
    start_line: int
    end_line: int
    start_byte: int
    end_byte: int
    docstring: str | None = None

    def __post_init__(self) -> None:
        _validate_non_empty(self.id, "Function.id")
        _validate_non_empty(self.repo_id, "Function.repo_id")
        _validate_non_empty(self.name, "Function.name")
        _validate_non_empty(self.qualified_name, "Function.qualified_name")
        _validate_non_empty(self.file_path, "Function.file_path")
        _validate_non_empty(self.language, "Function.language")
        _validate_line_range(self.start_line, self.end_line)
        _validate_byte_range(self.start_byte, self.end_byte)

    @classmethod
    def create(
        cls,
        repo_id: str,
        name: str,
        qualified_name: str,
        file_path: str,
        start_line: int,
        end_line: int,
        start_byte: int,
        end_byte: int,
        language: str = "python",
        docstring: str | None = None,
        function_id: str | None = None,
    ) -> "Function":
        """Factory method computing the deterministic function ID."""
        computed_id = function_id if function_id else build_function_id(repo_id, qualified_name)
        return cls(
            id=computed_id,
            repo_id=repo_id,
            name=name.strip(),
            qualified_name=qualified_name.strip(),
            file_path=normalize_path(file_path),
            language=language,
            start_line=start_line,
            end_line=end_line,
            start_byte=start_byte,
            end_byte=end_byte,
            docstring=docstring,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize entity to a plain dictionary."""
        return {
            "id": self.id,
            "repo_id": self.repo_id,
            "name": self.name,
            "qualified_name": self.qualified_name,
            "file_path": self.file_path,
            "language": self.language,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "start_byte": self.start_byte,
            "end_byte": self.end_byte,
            "docstring": self.docstring,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Function":
        """Deserialize entity from a plain dictionary."""
        return cls(
            id=data["id"],
            repo_id=data["repo_id"],
            name=data["name"],
            qualified_name=data["qualified_name"],
            file_path=data["file_path"],
            language=data["language"],
            start_line=data["start_line"],
            end_line=data["end_line"],
            start_byte=data["start_byte"],
            end_byte=data["end_byte"],
            docstring=data.get("docstring"),
        )


@dataclass(frozen=True)
class Method:
    """Represents a method declaration on a class in the Unified Code Model.

    Attributes:
        id: Deterministic identifier: '{repo_id}::method::{qualified_name}'.
        repo_id: Owning repository ID.
        name: Short name of the method.
        qualified_name: Fully qualified name (e.g. 'models.ItemModel.get_display_name').
        file_path: Normalized path to the containing file.
        language: Programming language ('python').
        start_line: Starting line (1-indexed).
        end_line: Ending line (1-indexed).
        start_byte: 0-indexed start byte.
        end_byte: 0-indexed end byte.
        docstring: Optional docstring text.
    """

    id: str
    repo_id: str
    name: str
    qualified_name: str
    file_path: str
    language: str
    start_line: int
    end_line: int
    start_byte: int
    end_byte: int
    docstring: str | None = None

    def __post_init__(self) -> None:
        _validate_non_empty(self.id, "Method.id")
        _validate_non_empty(self.repo_id, "Method.repo_id")
        _validate_non_empty(self.name, "Method.name")
        _validate_non_empty(self.qualified_name, "Method.qualified_name")
        _validate_non_empty(self.file_path, "Method.file_path")
        _validate_non_empty(self.language, "Method.language")
        _validate_line_range(self.start_line, self.end_line)
        _validate_byte_range(self.start_byte, self.end_byte)

    @classmethod
    def create(
        cls,
        repo_id: str,
        name: str,
        qualified_name: str,
        file_path: str,
        start_line: int,
        end_line: int,
        start_byte: int,
        end_byte: int,
        language: str = "python",
        docstring: str | None = None,
        method_id: str | None = None,
    ) -> "Method":
        """Factory method computing the deterministic method ID."""
        computed_id = method_id if method_id else build_method_id(repo_id, qualified_name)
        return cls(
            id=computed_id,
            repo_id=repo_id,
            name=name.strip(),
            qualified_name=qualified_name.strip(),
            file_path=normalize_path(file_path),
            language=language,
            start_line=start_line,
            end_line=end_line,
            start_byte=start_byte,
            end_byte=end_byte,
            docstring=docstring,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize entity to a plain dictionary."""
        return {
            "id": self.id,
            "repo_id": self.repo_id,
            "name": self.name,
            "qualified_name": self.qualified_name,
            "file_path": self.file_path,
            "language": self.language,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "start_byte": self.start_byte,
            "end_byte": self.end_byte,
            "docstring": self.docstring,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Method":
        """Deserialize entity from a plain dictionary."""
        return cls(
            id=data["id"],
            repo_id=data["repo_id"],
            name=data["name"],
            qualified_name=data["qualified_name"],
            file_path=data["file_path"],
            language=data["language"],
            start_line=data["start_line"],
            end_line=data["end_line"],
            start_byte=data["start_byte"],
            end_byte=data["end_byte"],
            docstring=data.get("docstring"),
        )


@dataclass(frozen=True)
class Import:
    """Represents an import declaration within a source file.

    Attributes:
        id: Deterministic identifier: '{repo_id}::import::{path}::L{line}::{name}'.
        repo_id: Owning repository ID.
        file_path: Normalized path to the containing file.
        module_name: Name of the imported target module (e.g. 'services').
        imported_name: Name of the specific imported identifier or module.
        alias: Optional imported local alias (e.g. 'as srv').
        start_line: Starting line (1-indexed).
        end_line: Ending line (1-indexed).
        start_byte: 0-indexed start byte.
        end_byte: 0-indexed end byte.
    """

    id: str
    repo_id: str
    file_path: str
    module_name: str
    imported_name: str
    start_line: int
    end_line: int
    alias: str | None = None
    start_byte: int = 0
    end_byte: int = 0

    def __post_init__(self) -> None:
        _validate_non_empty(self.id, "Import.id")
        _validate_non_empty(self.repo_id, "Import.repo_id")
        _validate_non_empty(self.file_path, "Import.file_path")
        _validate_non_empty(self.module_name, "Import.module_name")
        _validate_non_empty(self.imported_name, "Import.imported_name")
        _validate_line_range(self.start_line, self.end_line)
        _validate_byte_range(self.start_byte, self.end_byte)

    @classmethod
    def create(
        cls,
        repo_id: str,
        file_path: str,
        module_name: str,
        imported_name: str,
        start_line: int,
        end_line: int,
        alias: str | None = None,
        start_byte: int = 0,
        end_byte: int = 0,
        import_id: str | None = None,
    ) -> "Import":
        """Factory method computing the deterministic import ID."""
        norm_path = normalize_path(file_path)
        computed_id = (
            import_id if import_id else build_import_id(repo_id, norm_path, start_line, imported_name)
        )
        return cls(
            id=computed_id,
            repo_id=repo_id,
            file_path=norm_path,
            module_name=module_name.strip(),
            imported_name=imported_name.strip(),
            start_line=start_line,
            end_line=end_line,
            alias=alias.strip() if alias else None,
            start_byte=start_byte,
            end_byte=end_byte,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize entity to a plain dictionary."""
        return {
            "id": self.id,
            "repo_id": self.repo_id,
            "file_path": self.file_path,
            "module_name": self.module_name,
            "imported_name": self.imported_name,
            "alias": self.alias,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "start_byte": self.start_byte,
            "end_byte": self.end_byte,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Import":
        """Deserialize entity from a plain dictionary."""
        return cls(
            id=data["id"],
            repo_id=data["repo_id"],
            file_path=data["file_path"],
            module_name=data["module_name"],
            imported_name=data["imported_name"],
            alias=data.get("alias"),
            start_line=data["start_line"],
            end_line=data["end_line"],
            start_byte=data.get("start_byte", 0),
            end_byte=data.get("end_byte", 0),
        )
