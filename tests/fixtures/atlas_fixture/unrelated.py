"""Isolated module intentionally disconnected from the main fixture dependency chain."""


class StandaloneCalculator:
    """Independent calculator class operating without any domain model dependencies."""

    def add(self, a: int, b: int) -> int:
        """Add two integers."""
        return a + b

    def compute_total(self, values: list[int]) -> int:
        """Compute total sum using internal helper function."""
        return sum_values(values)


def sum_values(items: list[int]) -> int:
    """Standalone helper function summing a sequence of integers."""
    total = 0
    for item in items:
        total += item
    return total
