"""Python syntax extraction module for Atlas AI.

Converts Tree-sitter parse trees into Unified Code Model (UCM) entities and
syntactic CONTAINS relationships.
"""

from app.extractor.python_extractor import (
    ExtractionResult,
    PythonExtractor,
    derive_module_info,
    extract_python_file,
    extract_python_repository,
    extract_python_source,
    get_default_extractor,
)

__all__ = [
    "ExtractionResult",
    "PythonExtractor",
    "derive_module_info",
    "extract_python_file",
    "extract_python_repository",
    "extract_python_source",
    "get_default_extractor",
]
