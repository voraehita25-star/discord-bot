"""
Logger Utility Module
Sets up smart color-coded logging and handles log file rotation.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

# Emoji to ASCII mapping for console compatibility
EMOJI_MAP = {
    "🧠": "[BRAIN]",
    "✅": "[OK]",
    "❌": "[X]",
    "⚠️": "[!]",
    "🔄": "[SYNC]",
    "📝": "[NOTE]",
    "🎵": "[MUSIC]",
    "🎶": "[MUSIC]",
    "💾": "[SAVE]",
    "📖": "[LOAD]",
    "📋": "[LIST]",
    "📜": "[SCROLL]",
    "🧹": "[CLEAN]",
    "🚀": "[START]",
    "🛑": "[STOP]",
    "🔍": "[SEARCH]",
    "💬": "[CHAT]",
    "🤖": "[BOT]",
    "ℹ️": "[i]",
    "🌐": "[WEB]",
}


def safe_ascii(text: Any) -> str:
    """Convert emojis to ASCII-safe text"""
    result = str(text)
    for emoji, ascii_text in EMOJI_MAP.items():
        result = result.replace(emoji, ascii_text)
    # Replace any remaining non-ASCII with ?
    return result.encode("ascii", "replace").decode("ascii")


# Check if console supports Unicode
CONSOLE_UNICODE_SAFE = False
if sys.platform == "win32":
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32

        # Set console output code page to UTF-8 (65001)
        kernel32.SetConsoleOutputCP(65001)
        kernel32.SetConsoleCP(65001)

        # Also set stdout/stderr to UTF-8
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

        # Enable ANSI escape sequences in Windows Console
        handle = kernel32.GetStdHandle(-11)
        console_mode = ctypes.c_ulong()
        kernel32.GetConsoleMode(handle, ctypes.byref(console_mode))
        kernel32.SetConsoleMode(handle, console_mode.value | 0x0004)

        # Test if Unicode actually works
        try:
            sys.stdout.write("")  # Try writing empty (safe check)
            CONSOLE_UNICODE_SAFE = True
        except (UnicodeEncodeError, OSError):
            CONSOLE_UNICODE_SAFE = False

    except (AttributeError, OSError, ValueError):
        try:
            import colorama

            colorama.init()
        except ImportError:
            pass
else:
    CONSOLE_UNICODE_SAFE = True  # Linux/Mac usually support Unicode


class SmartLogFormatter(logging.Formatter):
    """Custom formatter with colors for console output"""

    grey = "\x1b[38;20m"
    green = "\x1b[32;20m"
    yellow = "\x1b[33;20m"
    red = "\x1b[31;20m"
    bold_red = "\x1b[31;1m"
    reset = "\x1b[0m"
    # Shorter format for console to prevent horizontal scrollbar
    format_str = "%(asctime)s [%(levelname)s] %(message)s"

    FORMATS = {
        logging.DEBUG: grey + format_str + reset,
        logging.INFO: green + format_str + reset,
        logging.WARNING: yellow + format_str + reset,
        logging.ERROR: red + format_str + reset,
        logging.CRITICAL: bold_red + format_str + reset,
    }

    def format(self, record: logging.LogRecord) -> str:
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt, datefmt="%Y-%m-%d %H:%M:%S")
        formatted = formatter.format(record)
        # Convert to ASCII-safe if console doesn't support Unicode
        if not CONSOLE_UNICODE_SAFE:
            return safe_ascii(formatted)
        return formatted


class JSONLogFormatter(logging.Formatter):
    """Structured JSON formatter for log analysis."""

    def format(self, record: logging.LogRecord) -> str:
        import json
        from datetime import datetime

        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "level": record.levelname,
            "message": safe_ascii(record.getMessage()),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add exception info if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, ensure_ascii=True)


def setup_smart_logging(json_logs: bool = False) -> None:
    """Initialize logging with file and console handlers.

    Args:
        json_logs: If True, also create a JSON-formatted log file for analysis.
    """
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    if logger.hasHandlers():
        logger.handlers.clear()

    # Formatter for files
    file_fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s (%(filename)s:%(lineno)d)",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Ensure logs directory exists
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)

    file_handler = RotatingFileHandler(
        "logs/bot.log", maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(file_fmt)

    error_handler = RotatingFileHandler(
        "logs/bot_errors.log", maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(file_fmt)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(SmartLogFormatter())

    logger.addHandler(file_handler)
    logger.addHandler(error_handler)
    logger.addHandler(console_handler)

    # Optional: JSON structured logs for analysis
    if json_logs:
        json_handler = RotatingFileHandler(
            "logs/bot_structured.jsonl", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        json_handler.setFormatter(JSONLogFormatter())
        logger.addHandler(json_handler)
        logging.info("📊 JSON structured logging enabled")

    logging.info("🧠 Smart Logging System Initialized.")


def cleanup_cache() -> None:
    """Clean up old audio files that may be left in temp folder"""
    try:
        temp_dir = Path("temp")
        if not temp_dir.exists():
            return

        count = 0
        for file in temp_dir.iterdir():
            if file.suffix in (".webm", ".m4a", ".mp3", ".opus"):
                try:
                    file.unlink()
                    count += 1
                except OSError as e:
                    logging.warning("Failed to delete temp file %s: %s", file.name, e)
        if count > 0:
            logging.info("🧹 Cleaned up %s orphaned audio files from temp/.", count)
    except OSError as e:
        logging.error("Cleanup failed: %s", e)
