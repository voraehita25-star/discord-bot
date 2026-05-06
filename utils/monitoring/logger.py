"""
Logger Utility Module
Sets up smart color-coded logging and handles log file rotation.
"""

from __future__ import annotations

import logging
import re
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, ClassVar

logger = logging.getLogger(__name__)

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
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

        # Enable ANSI escape sequences in Windows Console.
        # Validate the handle before calling GetConsoleMode — when stdout is
        # piped/redirected (CI, Docker, systemd) the handle is NULL or
        # INVALID_HANDLE_VALUE and the API call would either no-op or, on
        # some Windows builds, raise OSError.
        handle = kernel32.GetStdHandle(-11)
        if handle and handle != -1:
            console_mode = ctypes.c_ulong()
            if kernel32.GetConsoleMode(handle, ctypes.byref(console_mode)):
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

    FORMATS: ClassVar[dict[int, str]] = {
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


# Patterns that look like secrets (Discord tokens, API keys, bearer tokens).
#
# We use TWO compiled regexes and chain them in `_redact_sensitive` so the
# AWS/GitHub patterns can stay case-sensitive (the prefixes AKIA / ghp_ /
# gho_ / ghs_ are FIXED CASE in the real format — making them
# case-insensitive caused false-positive redactions on innocuous text like
# "akia" appearing inside English words / hex digests).
_SECRET_PATTERNS_CI = re.compile(
    r"(?:"
    # Discord bot token: base64.base64.base64 (3 dot-separated segments, 59+ chars)
    r"[A-Za-z0-9_-]{24,}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,}"
    r"|"
    # Generic long base64-like API key (32+ alphanumeric chars)
    r"(?:key|token|secret|password|apikey|api_key|authorization)[\s=:]+['\"]?[A-Za-z0-9_\-]{32,}['\"]?"
    r"|"
    # Anthropic API keys (sk-ant-api03-..., sk-ant-...) — kept BEFORE the
    # generic sk- pattern so the longer match wins.
    r"sk-ant-[A-Za-z0-9_\-]{40,}"
    r"|"
    # OpenAI / generic sk- API keys
    r"sk-[A-Za-z0-9]{20,}"
    r"|"
    # Google API keys (AIza...) — fixed 39 chars total
    r"AIza[A-Za-z0-9_\-]{35}"
    r")",
    re.IGNORECASE,
)

# Case-SENSITIVE patterns. Real AWS/GitHub keys have fixed-case prefixes;
# matching case-insensitively snared things like "akia"/"ghp_" appearing
# in lowercase identifiers/words and produced noisy `[REDACTED]` output.
_SECRET_PATTERNS_CS = re.compile(
    r"(?:"
    # GitHub Personal Access Tokens (ghp_..., gho_..., ghs_...) — fixed lowercase prefix
    r"gh[pos]_[A-Za-z0-9_]{36,}"
    r"|"
    # AWS Access Key IDs — fixed uppercase prefix
    r"AKIA[0-9A-Z]{16}"
    r")",
)

# Backward-compat alias used by callers that import the symbol directly.
_SECRET_PATTERNS = _SECRET_PATTERNS_CI


def _redact_sensitive(value: str) -> str:
    """Redact patterns in `value` that look like secrets.

    Public helper so other subsystems (e.g. the Sentry breadcrumb scrubber)
    can apply the same redaction policy without re-implementing the regex.

    Applies both the case-insensitive pattern set (covers Discord tokens
    and prefixed keys like ``sk-``/``AIza``) AND the case-sensitive set
    (AWS ``AKIA``/GitHub ``gh[pos]_`` — these have fixed-case prefixes,
    so a case-insensitive match falsely flagged english text containing
    "akia" or lowercase identifiers).
    """
    if not isinstance(value, str):
        return value
    redacted = _SECRET_PATTERNS_CI.sub("[REDACTED]", value)
    redacted = _SECRET_PATTERNS_CS.sub("[REDACTED]", redacted)
    return redacted


class SensitiveDataFilter(logging.Filter):
    """Filter that redacts potential secrets from log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.args:
            # Redact args if they are strings containing secrets
            if isinstance(record.args, dict):
                record.args = {
                    k: _redact_sensitive(str(v)) if isinstance(v, str) else v
                    for k, v in record.args.items()
                }
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    _redact_sensitive(str(a)) if isinstance(a, str) else a for a in record.args
                )
        if isinstance(record.msg, str):
            record.msg = _redact_sensitive(record.msg)
        return True


def setup_smart_logging(json_logs: bool = False) -> None:
    """Initialize logging with file and console handlers.

    Args:
        json_logs: If True, also create a JSON-formatted log file for analysis.
    """
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    # Close existing handlers before clearing — otherwise file descriptors
    # for old RotatingFileHandlers leak across hot reloads until GC runs.
    for h in list(logger.handlers):
        try:
            h.close()
        except Exception:
            pass
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

    # Optional: JSON structured logs for analysis. Add BEFORE the secret
    # filter loop so structured logs also get redaction (previously the
    # JSON handler was added after the filter loop and bypassed it).
    if json_logs:
        json_handler = RotatingFileHandler(
            "logs/bot_structured.jsonl", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        json_handler.setFormatter(JSONLogFormatter())
        logger.addHandler(json_handler)

    # Add sensitive data redaction filter to ALL handlers (including JSON).
    secret_filter = SensitiveDataFilter()
    for handler in logger.handlers:
        handler.addFilter(secret_filter)

    if json_logs:
        logger.info("📊 JSON structured logging enabled")

    logger.info("🧠 Smart Logging System Initialized.")


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
                    logger.warning("Failed to delete temp file %s: %s", file.name, e)
        if count > 0:
            logger.info("🧹 Cleaned up %s orphaned audio files from temp/.", count)
    except OSError:
        logger.exception("Cleanup failed")
