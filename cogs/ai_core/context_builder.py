"""
Backward compatibility re-export for context_builder module.
This file re-exports from core/ subdirectory.
"""

from .core.context_builder import (
    AIContext,
    ContextBuilder,
    context_builder,
)

__all__ = [
    "AIContext",
    "ContextBuilder",
    "context_builder",
]
