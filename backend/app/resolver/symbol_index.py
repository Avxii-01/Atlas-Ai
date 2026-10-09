"""Symbol Index for repository-scoped symbol lookup and resolution."""

from pathlib import Path, PurePosixPath
from typing import Any

from app.ucm import (
    Class,
    File,
    Function,
    Import,
    Method,
    Module,
    UnifiedCodeModel,
)


class SymbolIndex:
    """Repository-scoped symbol index for deterministic entity and reference resolution.

    Indexes all UCM entities within a single repository and provides lookup
    methods for modules, classes, functions, methods, and import bindings.
    """

    def __init__(self, ucm: UnifiedCodeModel) -> None:
        """Initialize and populate the symbol index from a UnifiedCodeModel."""
        self.repo_id = ucm.repository.id
        self.files_by_path: dict[str, File] = {f.path: f for f in ucm.files}

        # Modules
        self.modules_by_name: dict[str, list[Module]] = {}
        self.modules_by_qname: dict[str, Module] = {}
        self.modules_by_path: dict[str, Module] = {}
        for m in ucm.modules:
            if m.repo_id != self.repo_id:
                continue
            self.modules_by_name.setdefault(m.name, []).append(m)
            self.modules_by_qname[m.qualified_name] = m
            self.modules_by_path[m.file_path] = m

        # Classes
        self.classes_by_qname: dict[str, Class] = {}
        self.classes_by_file_and_name: dict[tuple[str, str], list[Class]] = {}
        for c in ucm.classes:
            if c.repo_id != self.repo_id:
                continue
            self.classes_by_qname[c.qualified_name] = c
            self.classes_by_file_and_name.setdefault((c.file_path, c.name), []).append(c)

        # Methods
        self.methods_by_qname: dict[str, Method] = {}
        self.methods_by_class: dict[tuple[str, str], Method] = {}
        for m in ucm.methods:
            if m.repo_id != self.repo_id:
                continue
            self.methods_by_qname[m.qualified_name] = m
            parts = m.qualified_name.rsplit(".", 1)
            if len(parts) == 2:
                class_qname, meth_name = parts
                self.methods_by_class[(class_qname, meth_name)] = m

        # Functions
        self.functions_by_qname: dict[str, Function] = {}
        self.functions_by_file_and_name: dict[tuple[str, str], list[Function]] = {}
        for f in ucm.functions:
            if f.repo_id != self.repo_id:
                continue
            self.functions_by_qname[f.qualified_name] = f
            self.functions_by_file_and_name.setdefault((f.file_path, f.name), []).append(f)

        # Imports by file path
        self.imports_by_file: dict[str, list[Import]] = {}
        for imp in ucm.imports:
            if imp.repo_id != self.repo_id:
                continue
            self.imports_by_file.setdefault(imp.file_path, []).append(imp)

        # Inheritance map: class_qname -> list of resolved base Class entities
        self.class_bases: dict[str, list[Class]] = {}

        # Class attribute types: class_qname -> {attr_name: Class}
        self.class_attr_types: dict[str, dict[str, Class]] = {}

    def resolve_module(self, module_name: str, relative_to_path: str | None = None) -> Module | None:
        """Resolve a module specifier to an indexed Module entity in this repository.

        Args:
            module_name: Module identifier or import path (e.g. 'models', 'pkg.models', '.models').
            relative_to_path: Containing file path for relative import resolution.

        Returns:
            Resolved Module entity, or None if external, unresolved, or ambiguous.
        """
        clean_mod = module_name.strip()
        if not clean_mod:
            return None

        # 1. Direct match by qualified name
        if clean_mod in self.modules_by_qname:
            return self.modules_by_qname[clean_mod]

        # 2. Match by short name (if unique in repository)
        if clean_mod in self.modules_by_name:
            candidates = self.modules_by_name[clean_mod]
            if len(candidates) == 1:
                return candidates[0]
            # If multiple modules share the short name, try matching relative path context
            if relative_to_path:
                rel_dir = PurePosixPath(relative_to_path).parent.as_posix()
                for cand in candidates:
                    if PurePosixPath(cand.file_path).parent.as_posix() == rel_dir:
                        return cand
            # Ambiguous module name without discriminating context
            return None

        # 3. Relative import resolution (e.g. '.models', '..base', '.')
        if clean_mod.startswith(".") and relative_to_path:
            cur_dir = PurePosixPath(relative_to_path).parent
            dots = 0
            for char in clean_mod:
                if char == ".":
                    dots += 1
                else:
                    break
            remainder = clean_mod[dots:]
            target_dir = cur_dir
            for _ in range(dots - 1):
                target_dir = target_dir.parent

            if remainder:
                rel_candidate = (target_dir / remainder).as_posix().lstrip("/")
            else:
                rel_candidate = target_dir.as_posix().lstrip("/")

            if rel_candidate in self.modules_by_qname:
                return self.modules_by_qname[rel_candidate]
            if rel_candidate in self.modules_by_name:
                candidates = self.modules_by_name[rel_candidate]
                if len(candidates) == 1:
                    return candidates[0]

        return None

    def resolve_symbol_in_file(self, file_path: str, symbol_name: str) -> Any | None:
        """Resolve an identifier used within a file to its target repository entity.

        Follows standard Python scope order: local file declarations first, then imported symbols.
        Respects import aliases. Prevents ambiguous or speculative resolution.

        Args:
            file_path: Normalized path of the file where the symbol is referenced.
            symbol_name: Identifier name (or alias) referenced in code.

        Returns:
            Class, Function, or Module entity if resolvable, or None.
        """
        clean_name = symbol_name.strip()
        if not clean_name:
            return None

        # 1. Definitions declared in this file
        class_candidates = self.classes_by_file_and_name.get((file_path, clean_name), [])
        if len(class_candidates) == 1:
            return class_candidates[0]

        func_candidates = self.functions_by_file_and_name.get((file_path, clean_name), [])
        if len(func_candidates) == 1:
            return func_candidates[0]

        # 2. Imports declared in this file
        for imp in self.imports_by_file.get(file_path, []):
            bound_name = imp.alias if imp.alias else imp.imported_name
            if bound_name == clean_name:
                # Find target module
                target_mod = self.resolve_module(imp.module_name, relative_to_path=file_path)
                if target_mod is not None:
                    # Look up imported_name in target_mod
                    target_qname = f"{target_mod.qualified_name}.{imp.imported_name}"
                    if target_qname in self.classes_by_qname:
                        return self.classes_by_qname[target_qname]
                    if target_qname in self.functions_by_qname:
                        return self.functions_by_qname[target_qname]
                    # If imported_name is the module itself (e.g. import utils)
                    if imp.imported_name == target_mod.name or imp.imported_name == target_mod.qualified_name:
                        return target_mod

        return None

    def get_method_on_class(self, class_qname: str, method_name: str) -> Method | None:
        """Find a method on a class, checking the class definition and its base classes.

        Args:
            class_qname: Fully qualified name of the class.
            method_name: Name of the method to find.

        Returns:
            Resolved Method entity, or None if not found.
        """
        # 1. Direct member method on the class
        if (class_qname, method_name) in self.methods_by_class:
            return self.methods_by_class[(class_qname, method_name)]

        # 2. Check base classes (in breadth-first / linear order)
        visited = {class_qname}
        queue = list(self.class_bases.get(class_qname, []))
        while queue:
            base_cls = queue.pop(0)
            if base_cls.qualified_name in visited:
                continue
            visited.add(base_cls.qualified_name)

            if (base_cls.qualified_name, method_name) in self.methods_by_class:
                return self.methods_by_class[(base_cls.qualified_name, method_name)]

            for next_base in self.class_bases.get(base_cls.qualified_name, []):
                if next_base.qualified_name not in visited:
                    queue.append(next_base)

        return None
