"""Tree-sitter Python parser implementation."""

from pathlib import Path
from typing import Any

from tree_sitter import Language, Parser
import tree_sitter_python

from app.parser.models import ParseResult, SourcePosition, SourceRange, SyntaxErrorInfo
from app.parser.traversal import collect_syntax_errors


class PythonParser:
    """Parser for Python source code based on Tree-sitter.

    Initializes the Tree-sitter Python grammar and produces structured ParseResult
    objects representing the concrete syntax tree and any syntax errors.
    """

    def __init__(self) -> None:
        """Initialize the Tree-sitter parser with the Python grammar."""
        self._language = Language(tree_sitter_python.language())
        self._parser = Parser(self._language)

    @property
    def language(self) -> Any:
        """Return the Tree-sitter Language instance."""
        return self._language

    def parse(self, source: str | bytes, file_path: str | None = None) -> ParseResult:
        """Parse Python source code into a syntax tree and return structured results.

        Accepts either string or bytes. If string is passed, it is encoded as UTF-8.
        Preserves Tree-sitter's error recovery mechanism when malformed source is
        provided, collecting structured syntax error details.

        Args:
            source: Python source code as str or bytes.
            file_path: Optional file path for provenance and error reporting.

        Returns:
            ParseResult containing the syntax tree, error details, and validation state.
        """
        if isinstance(source, str):
            source_bytes = source.encode("utf-8")
        elif isinstance(source, bytes):
            source_bytes = source
        else:
            source_bytes = bytes(source)

        try:
            tree = self._parser.parse(source_bytes)
        except Exception as exc:
            # Safeguard against unexpected low-level parsing panics
            error_range = SourceRange(
                start_point=SourcePosition(line=1, column=0),
                end_point=SourcePosition(line=1, column=0),
                start_byte=0,
                end_byte=len(source_bytes),
            )
            return ParseResult(
                tree=None,
                source_bytes=source_bytes,
                file_path=file_path,
                has_syntax_errors=True,
                errors=[
                    SyntaxErrorInfo(
                        message=f"Catastrophic parser failure: {exc}",
                        range=error_range,
                        is_missing=False,
                        node_type="FATAL_ERROR",
                    )
                ],
            )

        root = tree.root_node
        has_errors = getattr(root, "has_error", False)
        errors: list[SyntaxErrorInfo] = []

        if has_errors:
            errors = collect_syntax_errors(root)

        return ParseResult(
            tree=tree,
            source_bytes=source_bytes,
            file_path=file_path,
            has_syntax_errors=has_errors,
            errors=errors,
        )

    def parse_file(self, file_path: str | Path) -> ParseResult:
        """Read a Python source file from disk and parse it.

        Args:
            file_path: Path to the Python file.

        Returns:
            ParseResult representing the file contents.
        """
        path_obj = Path(file_path)
        try:
            source_bytes = path_obj.read_bytes()
        except OSError as exc:
            dummy_range = SourceRange(
                start_point=SourcePosition(line=1, column=0),
                end_point=SourcePosition(line=1, column=0),
                start_byte=0,
                end_byte=0,
            )
            return ParseResult(
                tree=None,
                source_bytes=b"",
                file_path=str(file_path),
                has_syntax_errors=True,
                errors=[
                    SyntaxErrorInfo(
                        message=f"Failed to read file '{file_path}': {exc}",
                        range=dummy_range,
                        is_missing=False,
                        node_type="IO_ERROR",
                    )
                ],
            )

        return self.parse(source=source_bytes, file_path=str(file_path))


_default_parser: PythonParser | None = None


def get_default_parser() -> PythonParser:
    """Return a shared singleton instance of PythonParser."""
    global _default_parser
    if _default_parser is None:
        _default_parser = PythonParser()
    return _default_parser


def parse_python(source: str | bytes, file_path: str | None = None) -> ParseResult:
    """Convenience function to parse Python source code using the default parser.

    Args:
        source: Python source code as str or bytes.
        file_path: Optional file path.

    Returns:
        ParseResult containing the syntax tree and error details.
    """
    return get_default_parser().parse(source, file_path=file_path)
