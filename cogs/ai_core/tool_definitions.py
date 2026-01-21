"""
Backward compatibility re-export for tool_definitions module.
This file re-exports from tools/ subdirectory.
"""

from .tools.tool_definitions import FunctionDeclarationType, get_tool_definitions

__all__ = ["FunctionDeclarationType", "get_tool_definitions"]
