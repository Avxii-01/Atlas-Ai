"""Service layer providing domain operations and workflows for the Atlas fixture repository."""

from models import ItemModel, create_default_item
from utils import format_identifier


class ItemService:
    """Service class coordinating item model operations and formatting."""

    def get_item_summary(self, item_id: str, name: str) -> str:
        """Retrieve formatted summary for an item by creating a model instance."""
        item = ItemModel(entity_id=item_id, name=name)
        return item.get_display_name()

    def create_tagged_item(self, raw_id: str) -> ItemModel:
        """Create a default item with a normalized prefix from utils."""
        normalized_id = format_identifier("srv", raw_id)
        return create_default_item(entity_id=normalized_id)


def process_item_workflow(item_id: str, name: str) -> str:
    """Execute item workflow; useful for cross-file call analysis."""
    service = ItemService()
    summary = service.get_item_summary(item_id, name)
    tagged = service.create_tagged_item(item_id)
    return f"Workflow: {summary} (tag={tagged.entity_id})"
