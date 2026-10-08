"""Application entry point and top-level orchestrator for the Atlas fixture repository."""

from services import ItemService, process_item_workflow


class Application:
    """Main application orchestrator coordinating service operations."""

    def __init__(self) -> None:
        self.service = ItemService()

    def run(self, item_id: str, item_name: str) -> str:
        """Execute application workflow using ItemService."""
        return self.service.get_item_summary(item_id, item_name)


def main() -> str:
    """Application-level entry point function."""
    app = Application()
    workflow_result = process_item_workflow("default-1", "Atlas Default")
    app_result = app.run("item-1", "Atlas Item")
    return f"{workflow_result} | {app_result}"


if __name__ == "__main__":
    print(main())
