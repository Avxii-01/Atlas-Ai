"""Base domain entity definitions for the Atlas fixture repository."""


class BaseEntity:
    """Base class providing entity identity and identifier access."""

    def __init__(self, entity_id: str) -> None:
        self.entity_id = entity_id

    def get_id(self) -> str:
        """Return the entity identifier."""
        return self.entity_id
