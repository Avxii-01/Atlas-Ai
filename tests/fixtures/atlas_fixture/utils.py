"""Utility helper functions for the Atlas fixture repository."""


def format_identifier(prefix: str, raw_id: str) -> str:
    """Format and normalize a prefixed identifier string."""
    return f"{prefix}::{raw_id}"
