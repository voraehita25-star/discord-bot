"""
Backward compatibility re-export for debug_commands module.
This file re-exports from commands/ subdirectory.
"""

from .commands.debug_commands import AIDebug as DebugCommands

__all__ = ["DebugCommands"]
