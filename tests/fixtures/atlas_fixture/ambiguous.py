"""Deterministic examples of references that must remain unresolved or ambiguous.

This module provides oracle negative test cases for the Atlas AI static analyzer:
1. Missing import module: Target module does not exist in the repository.
2. Missing imported symbol: Target module exists in the repository, but the imported symbol does not.
3. Ambiguous method dispatch: Dynamic receiver with identically named methods on multiple classes.
4. Name collision: Module-level function sharing the exact same name as class methods.
5. Unresolved function call: Call to a function symbol that is neither defined nor imported.
6. Scoped nested definition: Lexically scoped inner function within an enclosing function.
7. Dynamic reflection dispatch: Attribute access and invocation via getattr.
"""

# Case 1: Unresolved module import (target module does not exist in repository)
from nonexistent_module import missing_symbol  # type: ignore # noqa: F401

# Case 2: Unresolved symbol import (module 'models' exists, but symbol 'MissingModel' does not)
from models import MissingModel  # type: ignore # noqa: F401


# Case 3: Ambiguous call targets (two unrelated classes share identical method name)
class AlphaWorker:
    """First worker class defining an execute_task method."""

    def execute_task(self, task_name: str) -> str:
        """Execute task within Alpha worker."""
        return f"alpha:{task_name}"


class BetaWorker:
    """Second worker class defining an identical execute_task method name."""

    def execute_task(self, task_name: str) -> str:
        """Execute task within Beta worker."""
        return f"beta:{task_name}"


def call_ambiguous_worker(worker, task_name: str) -> str:
    """Ambiguous call site: receiver 'worker' is dynamically typed.

    Static resolution cannot determine whether worker.execute_task resolves to
    AlphaWorker.execute_task or BetaWorker.execute_task.
    The resolver must NOT create speculative CALLS edges to either target.
    """
    return worker.execute_task(task_name)


# Case 4: Name collision across different entity types (function vs method)
def execute_task(task_name: str) -> str:
    """Standalone function sharing identical name with AlphaWorker and BetaWorker methods.

    The resolver must not confound this standalone function with the class methods.
    """
    return f"standalone:{task_name}"


# Case 5: Unresolved function call (symbol is neither defined nor imported)
def call_undefined_symbol() -> None:
    """Unresolved call site: target function is undefined in the module and repository.

    The resolver must record this as unresolved and not invent a target node or edge.
    """
    undefined_function()  # type: ignore # noqa: F821


# Case 6: Nested function definition / local lexical scope
def outer_scope_function(value: int) -> int:
    """Nested definition test case.

    inner_local_function is locally scoped to outer_scope_function, not a module-level entity.
    """
    def inner_local_function(x: int) -> int:
        return x * 2

    return inner_local_function(value)


# Case 7: Dynamic attribute access / reflection
def dynamic_reflection_dispatch(target: object, method_name: str):
    """Dynamic call site using getattr.

    Dynamic reflection cannot be resolved statically; no speculative CALLS edge should be created.
    """
    method = getattr(target, method_name)
    return method()
