"""Relationship resolver for Atlas AI Unified Code Model.

Resolves CONTAINS, IMPORTS, INHERITS, and CALLS relationships across entities
using the SymbolIndex and AST parse trees.
"""

from pathlib import Path
from typing import Any

from app.parser.models import ParseResult, SourcePosition, SourceRange
from app.parser.python_parser import PythonParser, get_default_parser
from app.resolver.symbol_index import SymbolIndex
from app.ucm import (
    Class,
    File,
    Function,
    Method,
    Module,
    Relationship,
    RelationshipType,
    UnifiedCodeModel,
    create_calls_rel,
    create_imports_rel,
    create_inherits_rel,
)


class RelationshipResolver:
    """Resolves semantic relationships across code entities in a UnifiedCodeModel."""

    def __init__(self, parser: PythonParser | None = None) -> None:
        """Initialize the relationship resolver with an optional parser."""
        self.parser = parser or get_default_parser()

    def resolve(
        self,
        ucm: UnifiedCodeModel,
        repo_path: str | Path | None = None,
        sources: dict[str, str | bytes] | None = None,
        parse_results: dict[str, ParseResult] | None = None,
    ) -> UnifiedCodeModel:
        """Resolve all relationships for a UnifiedCodeModel and return an updated model.

        Args:
            ucm: The UnifiedCodeModel containing extracted entities.
            repo_path: Optional filesystem path of the repository for reading source files.
            sources: Optional mapping of file_path -> source string or bytes.
            parse_results: Optional mapping of file_path -> precomputed ParseResult.

        Returns:
            A new UnifiedCodeModel with all entities preserved and resolved relationships added.
        """
        # Build symbol index for repository
        index = SymbolIndex(ucm)

        # Collect parse results for all files in the UCM
        pr_map = self._collect_parse_results(ucm, repo_path, sources, parse_results)

        # 1. CONTAINS: Preserve existing valid containment relationships from UCM
        existing_entity_ids = self._collect_all_entity_ids(ucm)
        all_relationships: list[Relationship] = []
        seen_edges: set[tuple[str, str, str]] = set()

        for rel in ucm.relationships:
            if rel.rel_type == RelationshipType.CONTAINS:
                if rel.source_id in existing_entity_ids and rel.target_id in existing_entity_ids:
                    key = (rel.rel_type.value, rel.source_id, rel.target_id)
                    if key not in seen_edges:
                        seen_edges.add(key)
                        all_relationships.append(rel)

        # 2. IMPORTS: Resolve file to module import relationships
        import_rels = self.resolve_imports(ucm, index)
        for rel in import_rels:
            if rel.source_id in existing_entity_ids and rel.target_id in existing_entity_ids:
                key = (rel.rel_type.value, rel.source_id, rel.target_id)
                if key not in seen_edges:
                    seen_edges.add(key)
                    all_relationships.append(rel)

        # 3. INHERITS: Resolve class inheritance hierarchies
        inherits_rels = self.resolve_inherits(ucm, index, pr_map)
        for rel in inherits_rels:
            if rel.source_id in existing_entity_ids and rel.target_id in existing_entity_ids:
                key = (rel.rel_type.value, rel.source_id, rel.target_id)
                if key not in seen_edges:
                    seen_edges.add(key)
                    all_relationships.append(rel)

        # 4. CALLS: Resolve function and method calls
        calls_rels = self.resolve_calls(ucm, index, pr_map)
        for rel in calls_rels:
            if rel.source_id in existing_entity_ids and rel.target_id in existing_entity_ids:
                key = (rel.rel_type.value, rel.source_id, rel.target_id)
                if key not in seen_edges:
                    seen_edges.add(key)
                    all_relationships.append(rel)

        # Sort relationships deterministically: by rel_type, source_id, target_id
        all_relationships.sort(key=lambda r: (r.rel_type.value, r.source_id, r.target_id))

        # Build resolved UnifiedCodeModel document
        resolved_ucm = UnifiedCodeModel(
            repository=ucm.repository,
            files=list(ucm.files),
            modules=list(ucm.modules),
            classes=list(ucm.classes),
            functions=list(ucm.functions),
            methods=list(ucm.methods),
            imports=list(ucm.imports),
            relationships=all_relationships,
        )
        return resolved_ucm

    def resolve_imports(
        self,
        ucm: UnifiedCodeModel,
        index: SymbolIndex,
    ) -> list[Relationship]:
        """Resolve File -> Module IMPORTS relationships from explicit Import declarations.

        Args:
            ucm: UnifiedCodeModel instance.
            index: Initialized SymbolIndex for the repository.

        Returns:
            List of typed IMPORTS relationships.
        """
        import_rels: list[Relationship] = []
        for file_ent in ucm.files:
            seen_targets: set[str] = set()
            for imp in index.imports_by_file.get(file_ent.path, []):
                target_mod = index.resolve_module(imp.module_name, relative_to_path=file_ent.path)
                if target_mod is not None and target_mod.id not in seen_targets:
                    seen_targets.add(target_mod.id)
                    import_rels.append(create_imports_rel(file_ent.id, target_mod.id))
        return import_rels

    def resolve_inherits(
        self,
        ucm: UnifiedCodeModel,
        index: SymbolIndex,
        parse_results: dict[str, ParseResult],
    ) -> list[Relationship]:
        """Resolve Class -> Class INHERITS relationships from class base declarations.

        Args:
            ucm: UnifiedCodeModel instance.
            index: Initialized SymbolIndex for the repository.
            parse_results: Mapping of file_path -> ParseResult.

        Returns:
            List of typed INHERITS relationships.
        """
        inherits_rels: list[Relationship] = []

        for file_ent in ucm.files:
            pr = parse_results.get(file_ent.path)
            if pr is None or pr.root_node is None:
                continue

            mod_ent = index.modules_by_path.get(file_ent.path)
            if not mod_ent:
                continue

            def find_classes(node: Any, current_scope: str) -> None:
                if node.type == "class_definition":
                    name_node = node.child_by_field_name("name")
                    if not name_node:
                        return
                    class_name = name_node.text.decode("utf-8")
                    class_qname = f"{current_scope}.{class_name}"
                    child_cls = index.classes_by_qname.get(class_qname)

                    if child_cls is not None:
                        sc_node = node.child_by_field_name("superclasses")
                        if sc_node is not None:
                            for sub in sc_node.children:
                                if sub.type in ("identifier", "attribute"):
                                    base_name = sub.text.decode("utf-8")
                                    base_cls = index.resolve_symbol_in_file(file_ent.path, base_name)
                                    if isinstance(base_cls, Class):
                                        index.class_bases.setdefault(class_qname, []).append(base_cls)
                                        loc = SourceRange.from_node(sub)
                                        inherits_rels.append(
                                            create_inherits_rel(child_cls.id, base_cls.id, location=loc)
                                        )

                    body = node.child_by_field_name("body")
                    if body:
                        for child in body.children:
                            find_classes(child, class_qname)
                    return

                for child in node.children:
                    find_classes(child, current_scope)

            for root_child in pr.root_node.children:
                find_classes(root_child, mod_ent.qualified_name)

        return inherits_rels

    def resolve_calls(
        self,
        ucm: UnifiedCodeModel,
        index: SymbolIndex,
        parse_results: dict[str, ParseResult],
    ) -> list[Relationship]:
        """Resolve Function/Method -> Function/Method CALLS relationships.

        Args:
            ucm: UnifiedCodeModel instance.
            index: Initialized SymbolIndex for the repository.
            parse_results: Mapping of file_path -> ParseResult.

        Returns:
            List of typed CALLS relationships.
        """
        # Pre-pass: Discover class instance attributes (e.g. self.service = ItemService())
        self._discover_class_instance_attributes(ucm, index, parse_results)

        calls_rels: list[Relationship] = []

        for file_ent in ucm.files:
            pr = parse_results.get(file_ent.path)
            if pr is None or pr.root_node is None:
                continue

            mod_ent = index.modules_by_path.get(file_ent.path)
            if not mod_ent:
                continue

            def walk_ast(
                node: Any,
                current_class: Class | None,
                current_caller: Function | Method | None,
                local_vars: dict[str, Class],
            ) -> None:
                # Track entering class
                if node.type == "class_definition":
                    c_name_node = node.child_by_field_name("name")
                    if not c_name_node:
                        return
                    c_name = c_name_node.text.decode("utf-8")
                    if current_class:
                        c_qname = f"{current_class.qualified_name}.{c_name}"
                    else:
                        c_qname = f"{mod_ent.qualified_name}.{c_name}"
                    new_class = index.classes_by_qname.get(c_qname)
                    body = node.child_by_field_name("body")
                    if body:
                        for child in body.children:
                            walk_ast(child, new_class, current_caller, dict(local_vars))
                    return

                # Track entering function or method
                if node.type == "function_definition":
                    f_name_node = node.child_by_field_name("name")
                    if not f_name_node:
                        return
                    f_name = f_name_node.text.decode("utf-8")
                    if current_class:
                        m_qname = f"{current_class.qualified_name}.{f_name}"
                        new_caller = index.methods_by_qname.get(m_qname)
                    else:
                        if current_caller:
                            f_qname = f"{current_caller.qualified_name}.{f_name}"
                        else:
                            f_qname = f"{mod_ent.qualified_name}.{f_name}"
                        new_caller = index.functions_by_qname.get(f_qname)

                    new_locals = dict(local_vars)
                    body = node.child_by_field_name("body")
                    if body:
                        for child in body.children:
                            walk_ast(child, current_class, new_caller, new_locals)
                    return

                # Track local variable assignment (e.g. app = Application(), item = ItemModel(...))
                if node.type == "assignment":
                    left = node.child_by_field_name("left")
                    right = node.child_by_field_name("right")
                    if left and right and left.type == "identifier" and right.type == "call":
                        r_fn = right.child_by_field_name("function")
                        if r_fn and r_fn.type == "identifier":
                            r_sym = index.resolve_symbol_in_file(file_ent.path, r_fn.text.decode("utf-8"))
                            if isinstance(r_sym, Class):
                                local_vars[left.text.decode("utf-8")] = r_sym

                # Inspect and resolve CALL nodes
                if node.type == "call" and current_caller is not None:
                    func_node = node.child_by_field_name("function")
                    loc = SourceRange.from_node(node)

                    # 1. Direct identifier call: e.g. process_item_workflow(...), ItemModel(...)
                    if func_node and func_node.type == "identifier":
                        callee_name = func_node.text.decode("utf-8")
                        inner_qname = f"{current_caller.qualified_name}.{callee_name}"
                        if inner_qname in index.functions_by_qname:
                            target_fn = index.functions_by_qname[inner_qname]
                            calls_rels.append(create_calls_rel(current_caller.id, target_fn.id, location=loc))
                        else:
                            sym = index.resolve_symbol_in_file(file_ent.path, callee_name)
                            if isinstance(sym, Function):
                                calls_rels.append(create_calls_rel(current_caller.id, sym.id, location=loc))
                            elif isinstance(sym, Class):
                                init_m = index.get_method_on_class(sym.qualified_name, "__init__")
                                if init_m is not None:
                                    calls_rels.append(create_calls_rel(current_caller.id, init_m.id, location=loc))

                    # 2. Attribute call: e.g. self.get_id(), super().__init__(), self.service.get_item_summary()
                    elif func_node and func_node.type == "attribute":
                        attr_name_node = func_node.child_by_field_name("attribute")
                        obj_node = func_node.child_by_field_name("object")
                        if attr_name_node and obj_node:
                            attr_name = attr_name_node.text.decode("utf-8")

                            # 2A. super().__init__()
                            if obj_node.type == "call":
                                s_fn = obj_node.child_by_field_name("function")
                                if s_fn and s_fn.text == b"super" and current_class is not None:
                                    for base in index.class_bases.get(current_class.qualified_name, []):
                                        base_m = index.get_method_on_class(base.qualified_name, attr_name)
                                        if base_m is not None:
                                            calls_rels.append(
                                                create_calls_rel(current_caller.id, base_m.id, location=loc)
                                            )
                                            break

                            # 2B. self.<method>()
                            elif obj_node.type == "identifier" and obj_node.text == b"self" and current_class is not None:
                                target_m = index.get_method_on_class(current_class.qualified_name, attr_name)
                                if target_m is not None:
                                    calls_rels.append(create_calls_rel(current_caller.id, target_m.id, location=loc))

                            # 2C. self.<attr>.<method>()
                            elif obj_node.type == "attribute":
                                sub_obj = obj_node.child_by_field_name("object")
                                sub_attr = obj_node.child_by_field_name("attribute")
                                if sub_obj and sub_attr and sub_obj.text == b"self" and current_class is not None:
                                    sub_attr_name = sub_attr.text.decode("utf-8")
                                    target_class = index.class_attr_types.get(
                                        current_class.qualified_name, {}
                                    ).get(sub_attr_name)
                                    if target_class is not None:
                                        target_m = index.get_method_on_class(target_class.qualified_name, attr_name)
                                        if target_m is not None:
                                            calls_rels.append(
                                                create_calls_rel(current_caller.id, target_m.id, location=loc)
                                            )

                            # 2D. local_var.<method>()
                            elif obj_node.type == "identifier":
                                var_name = obj_node.text.decode("utf-8")
                                target_class = local_vars.get(var_name)
                                if target_class is not None:
                                    target_m = index.get_method_on_class(target_class.qualified_name, attr_name)
                                    if target_m is not None:
                                        calls_rels.append(
                                            create_calls_rel(current_caller.id, target_m.id, location=loc)
                                        )
                                else:
                                    # Check if var_name is an imported module (e.g. utils.format_identifier)
                                    target_mod = index.resolve_module(var_name, relative_to_path=file_ent.path)
                                    if target_mod is not None:
                                        target_func_qname = f"{target_mod.qualified_name}.{attr_name}"
                                        target_fn = index.functions_by_qname.get(target_func_qname)
                                        if target_fn is not None:
                                            calls_rels.append(
                                                create_calls_rel(current_caller.id, target_fn.id, location=loc)
                                            )

                for child in node.children:
                    walk_ast(child, current_class, current_caller, local_vars)

            walk_ast(pr.root_node, None, None, {})

        return calls_rels

    def _discover_class_instance_attributes(
        self,
        ucm: UnifiedCodeModel,
        index: SymbolIndex,
        parse_results: dict[str, ParseResult],
    ) -> None:
        """Scan methods for self.<attr> = ClassConstructor() assignments."""
        for file_ent in ucm.files:
            pr = parse_results.get(file_ent.path)
            if pr is None or pr.root_node is None:
                continue

            mod_ent = index.modules_by_path.get(file_ent.path)
            if not mod_ent:
                continue

            for node in pr.root_node.children:
                if node.type == "class_definition":
                    c_name_node = node.child_by_field_name("name")
                    if not c_name_node:
                        continue
                    cls_qname = f"{mod_ent.qualified_name}.{c_name_node.text.decode('utf-8')}"
                    body = node.child_by_field_name("body")
                    if not body:
                        continue
                    for item in body.children:
                        if item.type == "function_definition":
                            m_body = item.child_by_field_name("body")
                            if not m_body:
                                continue
                            for stmt in m_body.children:
                                if stmt.type == "expression_statement":
                                    assign = stmt.children[0] if stmt.children else None
                                    if assign and assign.type == "assignment":
                                        left = assign.child_by_field_name("left")
                                        right = assign.child_by_field_name("right")
                                        if left and right and left.type == "attribute":
                                            obj = left.child_by_field_name("object")
                                            attr = left.child_by_field_name("attribute")
                                            if obj and attr and obj.text == b"self" and right.type == "call":
                                                r_fn = right.child_by_field_name("function")
                                                if r_fn and r_fn.type == "identifier":
                                                    r_sym = index.resolve_symbol_in_file(
                                                        file_ent.path, r_fn.text.decode("utf-8")
                                                    )
                                                    if isinstance(r_sym, Class):
                                                        attr_name = attr.text.decode("utf-8")
                                                        index.class_attr_types.setdefault(
                                                            cls_qname, {}
                                                        )[attr_name] = r_sym

    def _collect_parse_results(
        self,
        ucm: UnifiedCodeModel,
        repo_path: str | Path | None,
        sources: dict[str, str | bytes] | None,
        parse_results: dict[str, ParseResult] | None,
    ) -> dict[str, ParseResult]:
        pr_map: dict[str, ParseResult] = dict(parse_results or {})
        for file_ent in ucm.files:
            if file_ent.path in pr_map:
                continue
            if sources and file_ent.path in sources:
                pr_map[file_ent.path] = self.parser.parse(sources[file_ent.path], file_path=file_ent.path)
            elif repo_path:
                disk_path = Path(repo_path) / file_ent.path
                if disk_path.exists():
                    pr_map[file_ent.path] = self.parser.parse_file(disk_path)
            elif ucm.repository.source:
                disk_path = Path(ucm.repository.source) / file_ent.path
                if disk_path.exists():
                    pr_map[file_ent.path] = self.parser.parse_file(disk_path)
        return pr_map

    @staticmethod
    def _collect_all_entity_ids(ucm: UnifiedCodeModel) -> set[str]:
        entity_ids = {ucm.repository.id}
        for f in ucm.files:
            entity_ids.add(f.id)
        for m in ucm.modules:
            entity_ids.add(m.id)
        for c in ucm.classes:
            entity_ids.add(c.id)
        for fn in ucm.functions:
            entity_ids.add(fn.id)
        for meth in ucm.methods:
            entity_ids.add(meth.id)
        for imp in ucm.imports:
            entity_ids.add(imp.id)
        return entity_ids


def resolve_relationships(
    ucm: UnifiedCodeModel,
    repo_path: str | Path | None = None,
    sources: dict[str, str | bytes] | None = None,
    parse_results: dict[str, ParseResult] | None = None,
) -> UnifiedCodeModel:
    """Convenience function to resolve relationships on a UnifiedCodeModel."""
    resolver = RelationshipResolver()
    return resolver.resolve(
        ucm=ucm,
        repo_path=repo_path,
        sources=sources,
        parse_results=parse_results,
    )


def resolve_repository(
    repo_path: str | Path,
    repo_name: str | None = None,
    repo_source: str | None = None,
    file_paths: list[str | Path] | None = None,
) -> UnifiedCodeModel:
    """Convenience function to extract and resolve relationships for an entire repository."""
    from app.extractor import extract_python_repository

    ucm = extract_python_repository(
        repo_path,
        repo_name=repo_name,
        repo_source=repo_source,
        file_paths=file_paths,
    )
    return resolve_relationships(ucm, repo_path=repo_path)
