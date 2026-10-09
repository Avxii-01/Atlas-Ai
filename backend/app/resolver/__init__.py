"""Symbol Index and Relationship Resolver module for Atlas AI.

Resolves CONTAINS, IMPORTS, INHERITS, and CALLS relationships across Unified Code Model entities.
"""

from app.resolver.relationship_resolver import (
    RelationshipResolver,
    resolve_relationships,
    resolve_repository,
)
from app.resolver.symbol_index import SymbolIndex

__all__ = [
    "RelationshipResolver",
    "SymbolIndex",
    "resolve_relationships",
    "resolve_repository",
]
