"""Deterministic syntax-tree traversal utilities for Tree-sitter nodes."""

from collections.abc import Iterator
from typing import Any

from app.parser.models import SourceRange, SyntaxErrorInfo


def walk_tree(root_node: Any) -> Iterator[Any]:
    """Yield all nodes in the syntax tree in deterministic depth-first pre-order.

    Children are visited from left to right in source order. An iterative stack
    is used to prevent stack overflows on deeply nested AST structures.

    Args:
        root_node: The starting Tree-sitter Node.

    Yields:
        Tree-sitter Node instances in pre-order traversal sequence.
    """
    stack = [root_node]
    while stack:
        current = stack.pop()
        yield current
        for child in reversed(current.children):
            stack.append(child)


def find_nodes_by_type(root_node: Any, node_types: str | set[str] | list[str] | tuple[str, ...]) -> list[Any]:
    """Find and return all syntax nodes matching the specified node type(s).

    Args:
        root_node: The starting Tree-sitter Node.
        node_types: Single node type string or collection of node type strings
            (e.g., 'function_definition' or {'class_definition', 'function_definition'}).

    Returns:
        List of matching Tree-sitter Node instances in pre-order sequence.
    """
    if isinstance(node_types, str):
        target_types = {node_types}
    else:
        target_types = set(node_types)

    return [node for node in walk_tree(root_node) if node.type in target_types]


def collect_syntax_errors(root_node: Any) -> list[SyntaxErrorInfo]:
    """Traverse the syntax tree and collect structured information about syntax errors.

    Identifies both explicit 'ERROR' nodes (unrecognized tokens/syntax) and missing
    tokens (tokens expected by grammar that were omitted in source).

    Args:
        root_node: The root Tree-sitter Node of the parsed tree.

    Returns:
        List of SyntaxErrorInfo instances describing each detected error.
    """
    errors: list[SyntaxErrorInfo] = []

    if not root_node.has_error:
        return errors

    for node in walk_tree(root_node):
        if getattr(node, "is_error", False) or node.type == "ERROR":
            errors.append(
                SyntaxErrorInfo(
                    message=f"Syntax error at line {node.start_point[0] + 1}, column {node.start_point[1]}",
                    range=SourceRange.from_node(node),
                    is_missing=False,
                    node_type=node.type,
                )
            )
        elif getattr(node, "is_missing", False):
            errors.append(
                SyntaxErrorInfo(
                    message=(
                        f"Missing expected token '{node.type}' at line "
                        f"{node.start_point[0] + 1}, column {node.start_point[1]}"
                    ),
                    range=SourceRange.from_node(node),
                    is_missing=True,
                    node_type=node.type,
                )
            )

    # Fallback guard: if root_node reports has_error but no discrete error/missing node was flagged
    if not errors:
        errors.append(
            SyntaxErrorInfo(
                message=f"Syntax error detected in source module at line {root_node.start_point[0] + 1}",
                range=SourceRange.from_node(root_node),
                is_missing=False,
                node_type=root_node.type,
            )
        )

    return errors
