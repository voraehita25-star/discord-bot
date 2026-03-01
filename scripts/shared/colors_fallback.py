"""
Shared Colors Fallback Module.
Provides Colors class when utils.media.colors is not available.
Used by scripts that may run outside the main bot environment.
"""

from __future__ import annotations

# Try to import from main utils first
try:
    from utils.media.colors import Colors, enable_windows_ansi

    enable_windows_ansi()
    COLORS_FROM_UTILS = True
except ImportError:
    COLORS_FROM_UTILS = False

    class Colors:
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


__all__ = ["COLORS_FROM_UTILS", "Colors"]
