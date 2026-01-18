"""
Shared ANSI Color Codes for terminal output.
Used across dev_watcher.py, bot_manager.py, and other tools.
"""

import ctypes
import sys

try:
    import colorama
except ImportError:
    colorama = None


class Colors:
    """ANSI Color Codes for terminal output.

    Usage:
        print(f"{Colors.GREEN}Success!{Colors.RESET}")
        print(f"{Colors.BOLD}{Colors.RED}Error!{Colors.RESET}")

    Attributes:
        RESET: Reset all formatting
        BOLD: Bold text
        DIM: Dimmed text
        RED-WHITE: Standard colors
        BRIGHT_*: Bright/intense color variants
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


def enable_windows_ansi() -> bool:
    """Enable ANSI escape sequences and UTF-8 on Windows Console."""
    if sys.platform != "win32":
        return True

    try:
        kernel32 = ctypes.windll.kernel32

        # Set console output code page to UTF-8 (65001)
        kernel32.SetConsoleOutputCP(65001)
        kernel32.SetConsoleCP(65001)

        # Also set stdout/stderr to UTF-8
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

        # Enable ANSI escape sequences in Windows Console
        # STD_OUTPUT_HANDLE = -11
        # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        handle = kernel32.GetStdHandle(-11)
        console_mode = ctypes.c_ulong()
        kernel32.GetConsoleMode(handle, ctypes.byref(console_mode))
        kernel32.SetConsoleMode(handle, console_mode.value | 0x0004)
        return True
    except (AttributeError, OSError, ValueError):
        # Fallback: try colorama init if available
        if colorama:
            colorama.init()
            return True

    return False
