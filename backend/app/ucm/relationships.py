"""Typed relationship models and factories for the Unified Code Model."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.parser.models import SourcePosition, SourceRange


class RelationshipType(str, Enum):
    """Supported graph schema relationship types.

    Conforms to docs/GRAPH_SCHEMA.md.
    """

    CONTAINS = "CONTAINS"
    IMPORTS = "IMPORTS"
    CALLS = "CALLS"
    INHERITS = "INHERITS"


@dataclass(frozen=True)
class Relationship:
    """Represents a directed relationship between two UCM entities.

    Attributes:
        rel_type: Type of the relationship (CONTAINS, IMPORTS, CALLS, INHERITS).
        source_id: Deterministic identifier of the source entity.
        target_id: Deterministic identifier of the target entity.
        location: Optional SourceRange preserving relationship source evidence.
        metadata: Optional dictionary for additional evidence attributes.
    """

    rel_type: RelationshipType
    source_id: str
    target_id: str
    location: SourceRange | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.rel_type, RelationshipType):
            try:
                # Attempt to normalize string to enum
                normalized = RelationshipType(self.rel_type)
                object.__setattr__(self, "rel_type", normalized)
            except ValueError:
                valid_types = [rt.value for rt in RelationshipType]
                raise ValueError(
                    f"Invalid relationship type '{self.rel_type}'. Must be one of: {valid_types}"
                )

        if not isinstance(self.source_id, str) or not self.source_id.strip():
            raise ValueError("source_id must be a non-empty string")
        if not isinstance(self.target_id, str) or not self.target_id.strip():
            raise ValueError("target_id must be a non-empty string")

    def to_dict(self) -> dict[str, Any]:
        """Serialize relationship to a plain dictionary."""
        loc_dict = None
        if self.location is not None:
            loc_dict = {
                "start_line": self.location.start_point.line,
                "start_column": self.location.start_point.column,
                "end_line": self.location.end_point.line,
                "end_column": self.location.end_point.column,
                "start_byte": self.location.start_byte,
                "end_byte": self.location.end_byte,
            }

        return {
            "rel_type": self.rel_type.value,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "location": loc_dict,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Relationship":
        """Deserialize relationship from a plain dictionary."""
        location = None
        loc_data = data.get("location")
        if loc_data is not None:
            location = SourceRange(
                start_point=SourcePosition(
                    line=loc_data["start_line"],
                    column=loc_data["start_column"],
                ),
                end_point=SourcePosition(
                    line=loc_data["end_line"],
                    column=loc_data["end_column"],
                ),
                start_byte=loc_data.get("start_byte", 0),
                end_byte=loc_data.get("end_byte", 0),
            )

        return cls(
            rel_type=RelationshipType(data["rel_type"]),
            source_id=data["source_id"],
            target_id=data["target_id"],
            location=location,
            metadata=dict(data.get("metadata", {})),
        )


def create_relationship(
    rel_type: RelationshipType | str,
    source_id: str,
    target_id: str,
    location: SourceRange | None = None,
    metadata: dict[str, Any] | None = None,
) -> Relationship:
    """Create and validate a typed Relationship."""
    if isinstance(rel_type, str):
        try:
            r_type = RelationshipType(rel_type)
        except ValueError:
            valid_types = [rt.value for rt in RelationshipType]
            raise ValueError(
                f"Invalid relationship type '{rel_type}'. Must be one of: {valid_types}"
            )
    else:
        r_type = rel_type

    return Relationship(
        rel_type=r_type,
        source_id=source_id.strip(),
        target_id=target_id.strip(),
        location=location,
        metadata=dict(metadata or {}),
    )


def create_contains_rel(
    source_id: str,
    target_id: str,
    location: SourceRange | None = None,
    metadata: dict[str, Any] | None = None,
) -> Relationship:
    """Create a CONTAINS relationship."""
    return create_relationship(RelationshipType.CONTAINS, source_id, target_id, location, metadata)


def create_imports_rel(
    source_id: str,
    target_id: str,
    location: SourceRange | None = None,
    metadata: dict[str, Any] | None = None,
) -> Relationship:
    """Create an IMPORTS relationship."""
    return create_relationship(RelationshipType.IMPORTS, source_id, target_id, location, metadata)


def create_calls_rel(
    source_id: str,
    target_id: str,
    location: SourceRange | None = None,
    metadata: dict[str, Any] | None = None,
) -> Relationship:
    """Create a CALLS relationship."""
    return create_relationship(RelationshipType.CALLS, source_id, target_id, location, metadata)


def create_inherits_rel(
    source_id: str,
    target_id: str,
    location: SourceRange | None = None,
    metadata: dict[str, Any] | None = None,
) -> Relationship:
    """Create an INHERITS relationship."""
    return create_relationship(RelationshipType.INHERITS, source_id, target_id, location, metadata)
