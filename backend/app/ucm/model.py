"""Unified Code Model top-level container and JSON serialization."""

from dataclasses import dataclass, field
import json
from typing import Any

from app.ucm.entities import (
    Class,
    File,
    Function,
    Import,
    Method,
    Module,
    Repository,
)
from app.ucm.relationships import Relationship


@dataclass
class UnifiedCodeModel:
    """Unified Code Model document containing normalized entities and relationships for a repository.

    Attributes:
        repository: Owning Repository metadata.
        files: List of File entities.
        modules: List of Module entities.
        classes: List of Class entities.
        functions: List of Function entities.
        methods: List of Method entities.
        imports: List of Import entities.
        relationships: List of Relationship records.
    """

    repository: Repository
    files: list[File] = field(default_factory=list)
    modules: list[Module] = field(default_factory=list)
    classes: list[Class] = field(default_factory=list)
    functions: list[Function] = field(default_factory=list)
    methods: list[Method] = field(default_factory=list)
    imports: list[Import] = field(default_factory=list)
    relationships: list[Relationship] = field(default_factory=list)

    def add_file(self, file_entity: File) -> None:
        """Add a File entity to the model."""
        self.files.append(file_entity)

    def add_module(self, module_entity: Module) -> None:
        """Add a Module entity to the model."""
        self.modules.append(module_entity)

    def add_class(self, class_entity: Class) -> None:
        """Add a Class entity to the model."""
        self.classes.append(class_entity)

    def add_function(self, function_entity: Function) -> None:
        """Add a Function entity to the model."""
        self.functions.append(function_entity)

    def add_method(self, method_entity: Method) -> None:
        """Add a Method entity to the model."""
        self.methods.append(method_entity)

    def add_import(self, import_entity: Import) -> None:
        """Add an Import entity to the model."""
        self.imports.append(import_entity)

    def add_relationship(self, relationship: Relationship) -> None:
        """Add a Relationship record to the model."""
        self.relationships.append(relationship)

    def get_entity_by_id(self, entity_id: str) -> Any | None:
        """Find any entity in the model by its deterministic ID."""
        if self.repository.id == entity_id:
            return self.repository
        for collection in (self.files, self.modules, self.classes, self.functions, self.methods, self.imports):
            for entity in collection:
                if entity.id == entity_id:
                    return entity
        return None

    def to_dict(self) -> dict[str, Any]:
        """Serialize the complete model to a plain dictionary."""
        return {
            "repository": self.repository.to_dict(),
            "files": [f.to_dict() for f in self.files],
            "modules": [m.to_dict() for m in self.modules],
            "classes": [c.to_dict() for c in self.classes],
            "functions": [fn.to_dict() for fn in self.functions],
            "methods": [mt.to_dict() for mt in self.methods],
            "imports": [im.to_dict() for im in self.imports],
            "relationships": [rel.to_dict() for rel in self.relationships],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UnifiedCodeModel":
        """Deserialize a complete model from a plain dictionary."""
        return cls(
            repository=Repository.from_dict(data["repository"]),
            files=[File.from_dict(f) for f in data.get("files", [])],
            modules=[Module.from_dict(m) for m in data.get("modules", [])],
            classes=[Class.from_dict(c) for c in data.get("classes", [])],
            functions=[Function.from_dict(fn) for fn in data.get("functions", [])],
            methods=[Method.from_dict(mt) for mt in data.get("methods", [])],
            imports=[Import.from_dict(im) for im in data.get("imports", [])],
            relationships=[Relationship.from_dict(rel) for rel in data.get("relationships", [])],
        )

    def to_json(self, indent: int | None = None) -> str:
        """Serialize the complete model to a JSON string with sorted keys."""
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @classmethod
    def from_json(cls, json_str: str) -> "UnifiedCodeModel":
        """Deserialize a complete model from a JSON string."""
        return cls.from_dict(json.loads(json_str))
