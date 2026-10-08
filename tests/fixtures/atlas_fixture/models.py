"""Domain models and entity factory functions for the Atlas fixture repository."""

from base import BaseEntity


class ItemModel(BaseEntity):
    """Domain model representing an item entity, inheriting from BaseEntity."""

    def __init__(self, entity_id: str, name: str) -> None:
        super().__init__(entity_id=entity_id)
        self.name = name

    def get_display_name(self) -> str:
        """Return formatted display name combining base identifier and item name."""
        base_id = self.get_id()
        return f"Item[{base_id}]: {self.name}"


def create_default_item(entity_id: str) -> ItemModel:
    """Factory function creating a default ItemModel instance."""
    return ItemModel(entity_id=entity_id, name="default_item")
