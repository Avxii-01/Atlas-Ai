"""Python syntax extraction converting Tree-sitter parse trees into Unified Code Model entities."""

from dataclasses import dataclass, field
import inspect
from pathlib import Path, PurePosixPath
from typing import Any

from app.parser.models import ParseResult, SourceRange, SyntaxErrorInfo
from app.parser.python_parser import PythonParser, get_default_parser, parse_python
from app.ucm import (
    Class,
    File,
    Function,
    Import,
    Method,
    Module,
    Relationship,
    Repository,
    UnifiedCodeModel,
    build_class_id,
    build_file_id,
    build_function_id,
    build_import_id,
    build_method_id,
    build_module_id,
    build_repo_id,
    create_contains_rel,
    normalize_path,
)


def derive_module_info(normalized_path: str) -> tuple[str, str]:
    """Derive module short name and qualified name from a normalized repository-relative path.

    Args:
        normalized_path: Normalized POSIX path (e.g. 'models.py', 'pkg/services.py', 'pkg/__init__.py').

    Returns:
        tuple[str, str]: (module_short_name, module_qualified_name).
    """
    path_obj = PurePosixPath(normalized_path)
    segments = list(path_obj.parts)

    if not segments:
        return "root", "root"

    last_segment = segments[-1]
    if last_segment.endswith(".py"):
        last_name = last_segment[:-3]
    else:
        last_name = last_segment

    if last_name == "__init__":
        if len(segments) > 1:
            pkg_segments = list(segments[:-1])
            module_name = pkg_segments[-1]
            module_qname = ".".join(pkg_segments)
            return module_name, module_qname
        return "root", "root"

    mod_segments = list(segments[:-1]) + [last_name]
    module_name = last_name
    module_qname = ".".join(mod_segments)
    return module_name, module_qname


def _extract_docstring(body_node: Any) -> str | None:
    """Extract and normalize docstring from a class or function body block node.

    Args:
        body_node: The Tree-sitter 'block' child node.

    Returns:
        Cleaned docstring string, or None if no docstring is present.
    """
    if body_node is None:
        return None

    for child in body_node.children:
        if child.type == "comment":
            continue
        if child.type == "expression_statement":
            for sub in child.children:
                if sub.type == "string":
                    raw_text = sub.text.decode("utf-8")
                    if raw_text.startswith('"""') and raw_text.endswith('"""') and len(raw_text) >= 6:
                        inner = raw_text[3:-3]
                    elif raw_text.startswith("'''") and raw_text.endswith("'''") and len(raw_text) >= 6:
                        inner = raw_text[3:-3]
                    elif raw_text.startswith('"') and raw_text.endswith('"') and len(raw_text) >= 2:
                        inner = raw_text[1:-1]
                    elif raw_text.startswith("'") and raw_text.endswith("'") and len(raw_text) >= 2:
                        inner = raw_text[1:-1]
                    else:
                        inner = raw_text
                    cleaned = inspect.cleandoc(inner).strip()
                    return cleaned if cleaned else None
        break
    return None


def _extract_import_targets(node: Any) -> list[tuple[str, str | None, int, int]]:
    """Extract imported symbols from an import_from_statement node.

    Returns:
        List of tuples: (imported_name, alias, start_byte, end_byte).
    """
    targets: list[tuple[str, str | None, int, int]] = []
    import_idx = -1
    for i, child in enumerate(node.children):
        if child.type == "import" or child.text == b"import":
            import_idx = i
            break
    if import_idx == -1:
        return targets

    for child in node.children[import_idx + 1:]:
        if child.type in (",", "(", ")"):
            continue
        if child.type == "dotted_name":
            name = child.text.decode("utf-8")
            targets.append((name, None, child.start_byte, child.end_byte))
        elif child.type == "aliased_import":
            name_sub = child.child_by_field_name("name")
            alias_sub = child.child_by_field_name("alias")
            name = name_sub.text.decode("utf-8") if name_sub is not None else child.text.decode("utf-8")
            alias = alias_sub.text.decode("utf-8") if alias_sub is not None else None
            targets.append((name, alias, child.start_byte, child.end_byte))
        elif child.type == "wildcard_import":
            targets.append(("*", None, child.start_byte, child.end_byte))

    return targets


@dataclass(frozen=True)
class _DefinitionScope:
    scope_type: str  # "file", "class", "function", "method"
    entity_id: str
    qualified_name: str


@dataclass
class ExtractionResult:
    """Result of Python syntax extraction for a single source file.

    Attributes:
        repository: Owning Repository entity.
        file: Extracted File entity (or None if unparseable/read failure).
        module: Extracted Module entity (or None if unparseable/read failure).
        classes: List of extracted Class entities.
        functions: List of extracted Function entities.
        methods: List of extracted Method entities.
        imports: List of extracted Import entities.
        relationships: List of extracted CONTAINS Relationship entities.
        parse_result: The underlying ParseResult from Tree-sitter parsing.
    """

    repository: Repository
    file: File | None
    module: Module | None
    classes: list[Class] = field(default_factory=list)
    functions: list[Function] = field(default_factory=list)
    methods: list[Method] = field(default_factory=list)
    imports: list[Import] = field(default_factory=list)
    relationships: list[Relationship] = field(default_factory=list)
    parse_result: ParseResult | None = None

    @property
    def has_syntax_errors(self) -> bool:
        """True if the underlying parse result detected syntax errors."""
        return self.parse_result.has_syntax_errors if self.parse_result else False

    @property
    def is_valid(self) -> bool:
        """True if the syntax tree is completely valid without syntax errors."""
        return self.parse_result.is_valid if self.parse_result else False

    @property
    def errors(self) -> list[SyntaxErrorInfo]:
        """List of syntax errors detected during parsing."""
        return self.parse_result.errors if self.parse_result else []

    def to_ucm(self) -> UnifiedCodeModel:
        """Convert this extraction result into a UnifiedCodeModel document."""
        ucm = UnifiedCodeModel(repository=self.repository)
        self.add_to_ucm(ucm)
        return ucm

    def add_to_ucm(self, ucm: UnifiedCodeModel) -> None:
        """Add all entities and relationships from this extraction into an existing UnifiedCodeModel."""
        if self.file is not None:
            ucm.add_file(self.file)
        if self.module is not None:
            ucm.add_module(self.module)
        for c in self.classes:
            ucm.add_class(c)
        for f in self.functions:
            ucm.add_function(f)
        for m in self.methods:
            ucm.add_method(m)
        for imp in self.imports:
            ucm.add_import(imp)
        for rel in self.relationships:
            ucm.add_relationship(rel)


def _resolve_repository(
    repo_id: str | None,
    repository: Repository | None,
    default_name: str = "default",
    default_source: str = "local",
) -> tuple[Repository, str]:
    """Helper to resolve Repository entity and repo_id consistently."""
    if repository is not None:
        return repository, repository.id
    if repo_id is not None and repo_id.strip():
        clean_id = repo_id.strip()
        if clean_id.startswith("repo::"):
            name = clean_id[6:]
        else:
            name = clean_id
            clean_id = build_repo_id(name)
        repo_ent = Repository(id=clean_id, name=name, source=default_source)
        return repo_ent, clean_id
    default_id = build_repo_id(default_name)
    repo_ent = Repository(id=default_id, name=default_name, source=default_source)
    return repo_ent, default_id


class PythonExtractor:
    """Extracts Unified Code Model entities and containment relationships from Python ASTs."""

    def __init__(self, parser: PythonParser | None = None) -> None:
        """Initialize the extractor with an optional Tree-sitter parser instance."""
        self.parser = parser or get_default_parser()

    def extract_source(
        self,
        source: str | bytes,
        file_path: str | Path,
        repo_id: str | None = None,
        repository: Repository | None = None,
        module_qualified_name: str | None = None,
    ) -> ExtractionResult:
        """Extract code entities from Python source code string or bytes.

        Args:
            source: Python source code as str or bytes.
            file_path: Repository-relative or normalized file path.
            repo_id: Optional repository identifier string.
            repository: Optional Repository instance providing context.
            module_qualified_name: Optional explicit module qualified name override.

        Returns:
            ExtractionResult containing all extracted entities and CONTAINS relationships.
        """
        norm_path = normalize_path(file_path)
        parse_result = self.parser.parse(source, file_path=norm_path)
        return self.extract_parse_result(
            parse_result=parse_result,
            file_path=norm_path,
            repo_id=repo_id,
            repository=repository,
            module_qualified_name=module_qualified_name,
        )

    def extract_file(
        self,
        file_path: str | Path,
        base_dir: str | Path | None = None,
        repo_id: str | None = None,
        repository: Repository | None = None,
        module_qualified_name: str | None = None,
    ) -> ExtractionResult:
        """Read a Python source file from disk and extract its code entities.

        Args:
            file_path: Path to the Python file.
            base_dir: Optional repository base directory for computing relative paths.
            repo_id: Optional repository identifier string.
            repository: Optional Repository instance providing context.
            module_qualified_name: Optional explicit module qualified name override.

        Returns:
            ExtractionResult containing all extracted entities and CONTAINS relationships.
        """
        path_obj = Path(file_path)
        if base_dir is not None:
            try:
                rel_path = path_obj.relative_to(base_dir)
            except ValueError:
                rel_path = path_obj
        else:
            rel_path = path_obj

        norm_path = normalize_path(rel_path)
        parse_result = self.parser.parse_file(file_path)
        return self.extract_parse_result(
            parse_result=parse_result,
            file_path=norm_path,
            repo_id=repo_id,
            repository=repository,
            module_qualified_name=module_qualified_name,
        )

    def extract_parse_result(
        self,
        parse_result: ParseResult,
        file_path: str | Path,
        repo_id: str | None = None,
        repository: Repository | None = None,
        module_qualified_name: str | None = None,
    ) -> ExtractionResult:
        """Extract code entities from an existing Tree-sitter ParseResult.

        Args:
            parse_result: Pre-computed ParseResult from PythonParser.
            file_path: Normalized or repository-relative file path.
            repo_id: Optional repository identifier string.
            repository: Optional Repository instance providing context.
            module_qualified_name: Optional explicit module qualified name override.

        Returns:
            ExtractionResult containing all extracted entities and CONTAINS relationships.
        """
        norm_path = normalize_path(file_path)
        repo_ent, clean_repo_id = _resolve_repository(repo_id, repository)

        if parse_result.tree is None or parse_result.root_node is None:
            # Catastrophic parse failure or unreadable file
            return ExtractionResult(
                repository=repo_ent,
                file=None,
                module=None,
                parse_result=parse_result,
            )

        root_node = parse_result.root_node
        source_bytes = parse_result.source_bytes

        # Compute file line and byte ranges
        end_line = max(1, root_node.end_point[0] + 1)
        start_byte = 0
        end_byte = len(source_bytes)

        file_ent = File.create(
            repo_id=clean_repo_id,
            path=norm_path,
            start_line=1,
            end_line=end_line,
            start_byte=start_byte,
            end_byte=end_byte,
            language="python",
        )

        # Derive module identifiers
        if module_qualified_name is not None and module_qualified_name.strip():
            mod_qname = module_qualified_name.strip()
            mod_short_name = mod_qname.split(".")[-1]
        else:
            mod_short_name, mod_qname = derive_module_info(norm_path)

        module_ent = Module.create(
            repo_id=clean_repo_id,
            name=mod_short_name,
            qualified_name=mod_qname,
            file_path=norm_path,
        )

        classes: list[Class] = []
        functions: list[Function] = []
        methods: list[Method] = []
        imports: list[Import] = []
        relationships: list[Relationship] = [
            create_contains_rel(clean_repo_id, file_ent.id)
        ]

        def visit(node: Any, scope: _DefinitionScope, decorated_node: Any = None) -> None:
            if node.type == "decorated_definition":
                def_child = None
                for child in node.children:
                    if child.type in ("function_definition", "class_definition"):
                        def_child = child
                        break
                if def_child is not None:
                    visit(def_child, scope, decorated_node=node)
                return

            if node.type == "class_definition":
                name_node = node.child_by_field_name("name")
                if name_node is None:
                    return
                class_name = name_node.text.decode("utf-8")
                class_qname = f"{scope.qualified_name}.{class_name}"

                span_node = decorated_node if decorated_node is not None else node
                body_node = node.child_by_field_name("body")
                docstring = _extract_docstring(body_node)

                class_ent = Class.create(
                    repo_id=clean_repo_id,
                    name=class_name,
                    qualified_name=class_qname,
                    file_path=norm_path,
                    start_line=span_node.start_point[0] + 1,
                    end_line=span_node.end_point[0] + 1,
                    start_byte=span_node.start_byte,
                    end_byte=span_node.end_byte,
                    language="python",
                    docstring=docstring,
                )
                classes.append(class_ent)
                relationships.append(create_contains_rel(scope.entity_id, class_ent.id))

                child_scope = _DefinitionScope(
                    scope_type="class",
                    entity_id=class_ent.id,
                    qualified_name=class_qname,
                )
                if body_node is not None:
                    for sub in body_node.children:
                        visit(sub, child_scope)
                return

            if node.type == "function_definition":
                name_node = node.child_by_field_name("name")
                if name_node is None:
                    return
                func_name = name_node.text.decode("utf-8")
                func_qname = f"{scope.qualified_name}.{func_name}"

                span_node = decorated_node if decorated_node is not None else node
                body_node = node.child_by_field_name("body")
                docstring = _extract_docstring(body_node)

                if scope.scope_type == "class":
                    method_ent = Method.create(
                        repo_id=clean_repo_id,
                        name=func_name,
                        qualified_name=func_qname,
                        file_path=norm_path,
                        start_line=span_node.start_point[0] + 1,
                        end_line=span_node.end_point[0] + 1,
                        start_byte=span_node.start_byte,
                        end_byte=span_node.end_byte,
                        language="python",
                        docstring=docstring,
                    )
                    methods.append(method_ent)
                    relationships.append(create_contains_rel(scope.entity_id, method_ent.id))
                    child_scope = _DefinitionScope(
                        scope_type="method",
                        entity_id=method_ent.id,
                        qualified_name=func_qname,
                    )
                else:
                    func_ent = Function.create(
                        repo_id=clean_repo_id,
                        name=func_name,
                        qualified_name=func_qname,
                        file_path=norm_path,
                        start_line=span_node.start_point[0] + 1,
                        end_line=span_node.end_point[0] + 1,
                        start_byte=span_node.start_byte,
                        end_byte=span_node.end_byte,
                        language="python",
                        docstring=docstring,
                    )
                    functions.append(func_ent)
                    relationships.append(create_contains_rel(scope.entity_id, func_ent.id))
                    child_scope = _DefinitionScope(
                        scope_type="function",
                        entity_id=func_ent.id,
                        qualified_name=func_qname,
                    )

                if body_node is not None:
                    for sub in body_node.children:
                        visit(sub, child_scope)
                return

            if node.type == "import_statement":
                stmt_start_line = node.start_point[0] + 1
                stmt_end_line = node.end_point[0] + 1
                for child in node.children:
                    if child.type == "dotted_name":
                        name = child.text.decode("utf-8")
                        imp = Import.create(
                            repo_id=clean_repo_id,
                            file_path=norm_path,
                            module_name=name,
                            imported_name=name,
                            start_line=stmt_start_line,
                            end_line=stmt_end_line,
                            alias=None,
                            start_byte=child.start_byte,
                            end_byte=child.end_byte,
                        )
                        imports.append(imp)
                    elif child.type == "aliased_import":
                        name_sub = child.child_by_field_name("name")
                        alias_sub = child.child_by_field_name("alias")
                        name = (
                            name_sub.text.decode("utf-8")
                            if name_sub is not None
                            else child.text.decode("utf-8")
                        )
                        alias = alias_sub.text.decode("utf-8") if alias_sub is not None else None
                        imp = Import.create(
                            repo_id=clean_repo_id,
                            file_path=norm_path,
                            module_name=name,
                            imported_name=name,
                            start_line=stmt_start_line,
                            end_line=stmt_end_line,
                            alias=alias,
                            start_byte=child.start_byte,
                            end_byte=child.end_byte,
                        )
                        imports.append(imp)
                return

            if node.type == "import_from_statement":
                stmt_start_line = node.start_point[0] + 1
                stmt_end_line = node.end_point[0] + 1
                mod_node = node.child_by_field_name("module_name")
                mod_name = mod_node.text.decode("utf-8") if mod_node is not None else ""

                targets = _extract_import_targets(node)
                for imp_name, alias, s_byte, e_byte in targets:
                    imp = Import.create(
                        repo_id=clean_repo_id,
                        file_path=norm_path,
                        module_name=mod_name,
                        imported_name=imp_name,
                        start_line=stmt_start_line,
                        end_line=stmt_end_line,
                        alias=alias,
                        start_byte=s_byte,
                        end_byte=e_byte,
                    )
                    imports.append(imp)
                return

            # Traverse child statements (for compound constructs like if, try, with)
            for child in node.children:
                visit(child, scope)

        initial_scope = _DefinitionScope(
            scope_type="file",
            entity_id=file_ent.id,
            qualified_name=mod_qname,
        )
        for child in root_node.children:
            visit(child, initial_scope)

        return ExtractionResult(
            repository=repo_ent,
            file=file_ent,
            module=module_ent,
            classes=classes,
            functions=functions,
            methods=methods,
            imports=imports,
            relationships=relationships,
            parse_result=parse_result,
        )

    def extract_repository(
        self,
        repo_path: str | Path,
        repo_name: str | None = None,
        repo_source: str | None = None,
        file_paths: list[str | Path] | None = None,
    ) -> UnifiedCodeModel:
        """Scan and extract an entire Python repository into a UnifiedCodeModel document.

        Args:
            repo_path: Root filesystem path of the repository.
            repo_name: Optional human-readable repository name (defaults to folder name).
            repo_source: Optional repository source origin (defaults to repo_path URI).
            file_paths: Optional list of explicit file paths to extract within repo_path.

        Returns:
            UnifiedCodeModel containing all extracted entities and CONTAINS relationships.
        """
        root_path = Path(repo_path).resolve()
        name = repo_name or root_path.name
        source = repo_source or str(root_path)

        repo_ent = Repository.create(name=name, source=source)
        ucm = UnifiedCodeModel(repository=repo_ent)

        if file_paths is not None:
            target_files = [Path(fp) for fp in file_paths]
        else:
            # Deterministic discovery of Python files excluding common non-source directories
            ignored_dirs = {".git", ".venv", "venv", "__pycache__", "node_modules", ".pytest_cache", ".ruff_cache"}
            target_files = []
            for item in sorted(root_path.rglob("*.py")):
                if any(ignored in item.parts for ignored in ignored_dirs):
                    continue
                target_files.append(item)

        for py_file in sorted(target_files):
            result = self.extract_file(
                file_path=py_file,
                base_dir=root_path,
                repository=repo_ent,
            )
            result.add_to_ucm(ucm)

        return ucm


_default_extractor: PythonExtractor | None = None


def get_default_extractor() -> PythonExtractor:
    """Return a shared singleton instance of PythonExtractor."""
    global _default_extractor
    if _default_extractor is None:
        _default_extractor = PythonExtractor()
    return _default_extractor


def extract_python_source(
    source: str | bytes,
    file_path: str | Path,
    repo_id: str | None = None,
    repository: Repository | None = None,
    module_qualified_name: str | None = None,
) -> ExtractionResult:
    """Convenience function to extract code entities from Python source."""
    return get_default_extractor().extract_source(
        source=source,
        file_path=file_path,
        repo_id=repo_id,
        repository=repository,
        module_qualified_name=module_qualified_name,
    )


def extract_python_file(
    file_path: str | Path,
    base_dir: str | Path | None = None,
    repo_id: str | None = None,
    repository: Repository | None = None,
    module_qualified_name: str | None = None,
) -> ExtractionResult:
    """Convenience function to extract code entities from a Python file on disk."""
    return get_default_extractor().extract_file(
        file_path=file_path,
        base_dir=base_dir,
        repo_id=repo_id,
        repository=repository,
        module_qualified_name=module_qualified_name,
    )


def extract_python_repository(
    repo_path: str | Path,
    repo_name: str | None = None,
    repo_source: str | None = None,
    file_paths: list[str | Path] | None = None,
) -> UnifiedCodeModel:
    """Convenience function to extract an entire Python repository into a UnifiedCodeModel."""
    return get_default_extractor().extract_repository(
        repo_path=repo_path,
        repo_name=repo_name,
        repo_source=repo_source,
        file_paths=file_paths,
    )
