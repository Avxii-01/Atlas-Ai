"""Data models and value objects representing parser results and source locations."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tree_sitter import Node, Tree


@dataclass(frozen=True)
class SourcePosition:
    """Represents a discrete position within source code.

    Attributes:
        line: 1-indexed line number.
        column: 0-indexed column character/byte offset within the line.
    """

    line: int
    column: int


@dataclass(frozen=True)
class SourceRange:
    """Represents a bounded span in source code.

    Attributes:
        start_point: Starting SourcePosition (line 1-indexed, column 0-indexed).
        end_point: Ending SourcePosition (line 1-indexed, column 0-indexed).
        start_byte: 0-indexed byte offset of the beginning of the span.
        end_byte: 0-indexed byte offset of the end of the span.
    """

    start_point: SourcePosition
    end_point: SourcePosition
    start_byte: int
    end_byte: int

    @classmethod
    def from_node(cls, node: Any) -> "SourceRange":
        """Construct a SourceRange from a Tree-sitter Node."""
        start_p = node.start_point
        end_p = node.end_point
        return cls(
            start_point=SourcePosition(line=start_p[0] + 1, column=start_p[1]),
            end_point=SourcePosition(line=end_p[0] + 1, column=end_p[1]),
            start_byte=node.start_byte,
            end_byte=node.end_byte,
        )


@dataclass(frozen=True)
class SyntaxErrorInfo:
    """Structured information about a detected syntax error or missing token.

    Attributes:
        message: Human-readable error description with location context.
        range: SourceRange of the error or missing token.
        is_missing: True if Tree-sitter detected an omitted token required by grammar.
        node_type: Node type identifier (e.g. 'ERROR', ')', or ':').
    """

    message: str
    range: SourceRange
    is_missing: bool
    node_type: str


@dataclass
class ParseResult:
    """Result of parsing Python source code with Tree-sitter.

    Attributes:
        tree: The parsed Tree-sitter syntax Tree, or None if catastrophic failure occurred.
        source_bytes: The raw bytes parsed by Tree-sitter.
        file_path: Optional repository-relative or absolute file path for provenance.
        has_syntax_errors: True if syntax errors or missing tokens were detected.
        errors: Detailed list of syntax error occurrences.
    """

    tree: Any | None
    source_bytes: bytes
    file_path: str | None = None
    has_syntax_errors: bool = False
    errors: list[SyntaxErrorInfo] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        """True only when parsing produced a syntax tree without any syntax errors."""
        return self.tree is not None and not self.has_syntax_errors

    @property
    def is_recoverable(self) -> bool:
        """True when syntax errors exist, but Tree-sitter successfully produced a partial tree."""
        return self.tree is not None and self.has_syntax_errors

    @property
    def root_node(self) -> Any | None:
        """Convenience property returning the root Node of the syntax tree, if available."""
        if self.tree is not None:
            return self.tree.root_node
        return None
