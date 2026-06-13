"""
Shared Colors Fallback Module.
Provides Colors class when utils.media.colors is not available.
Used by scripts that may run outside the main bot environment.
"""

from __future__ import annotations

import os
from typing import Any


class _FallbackColors:
    """Fallback ANSI Color Codes for terminal output.

    This class is used when the main utils.media.colors module
    is not available (e.g., running scripts standalone).
    """

    # Formatting
    RESET: str = "\033[0m"
    BOLD: str = "\033[1m"
    DIM: str = "\033[2m"

    # Standard Colors
    RED: str = "\033[31m"
    GREEN: str = "\033[32m"
    YELLOW: str = "\033[33m"
    BLUE: str = "\033[34m"
    MAGENTA: str = "\033[35m"
    CYAN: str = "\033[36m"
    WHITE: str = "\033[37m"

    # Bright Colors
    BRIGHT_RED: str = "\033[91m"
    BRIGHT_GREEN: str = "\033[92m"
    BRIGHT_YELLOW: str = "\033[93m"
    BRIGHT_BLUE: str = "\033[94m"
    BRIGHT_MAGENTA: str = "\033[95m"
    BRIGHT_CYAN: str = "\033[96m"


# Try to import from main utils first
Colors: type[Any]
try:
    from utils.media.colors import Colors as _ImportedColors, enable_windows_ansi

    enable_windows_ansi()
    Colors = _ImportedColors
    COLORS_FROM_UTILS = True
except ImportError:
    Colors = _FallbackColors
    COLORS_FROM_UTILS = False
    # utils.media.colors (which calls enable_windows_ansi) is unavailable on
    # this branch, so best-effort enable Windows VT processing ourselves —
    # otherwise on a legacy Windows console without VT support the ANSI escape
    # codes above print as literal text instead of color.
    if os.name == "nt":
        try:
            import ctypes

            _k = ctypes.windll.kernel32  # type: ignore[attr-defined]
            _h = _k.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
            _mode = ctypes.c_uint()
            if _k.GetConsoleMode(_h, ctypes.byref(_mode)):
                # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
                _k.SetConsoleMode(_h, _mode.value | 0x0004)
        except Exception:
            pass


__all__ = ["COLORS_FROM_UTILS", "Colors"]
