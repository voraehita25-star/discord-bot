"""
Logger Utility Module
Sets up smart color-coded logging and handles log file rotation.
"""

from __future__ import annotations

import logging
import re
import sys
from datetime import datetime, timezone
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
    # Bare codepoints without the U+FE0F variation selector — some sources
    # emit U+26A0 / U+2139 WITHOUT trailing VS-16, which the literal
    # str.replace above (keyed on the VS-16 form) would otherwise miss.
    "⚠": "[!]",
    "ℹ": "[i]",
}


def safe_ascii(text: Any) -> str:
    """Convert emojis to ASCII-safe text"""
    result = str(text)
    for emoji, ascii_text in EMOJI_MAP.items():
        result = result.replace(emoji, ascii_text)
    # Replace any remaining non-ASCII with ?
    return result.encode("ascii", "replace").decode("ascii")


def safe_unicode(text: Any) -> str:
    """Like ``safe_ascii`` but preserves Thai/CJK/other Unicode.

    Only the known emoji set is rewritten to ``[BRACKETED]`` tokens so
    non-Unicode consoles still get readable output. Everything else —
    Thai script, Japanese, accented Latin — passes through unchanged.
    Used by the JSON formatter where the output is UTF-8 and the
    ASCII-mangling of ``safe_ascii`` would destroy meaningful content.
    """
    result = str(text)
    for emoji, ascii_text in EMOJI_MAP.items():
        result = result.replace(emoji, ascii_text)
    return result


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
        #
        # INVALID_HANDLE_VALUE on Win32 is ``(HANDLE)-1`` which is
        # ``0xFFFFFFFF`` on Win32 / ``0xFFFFFFFFFFFFFFFF`` on Win64. A
        # raw ``handle != -1`` compares against the signed Python int
        # ``-1``, which differs from the unsigned HANDLE value returned
        # by ctypes — we'd miss the sentinel on Win64. ``c_void_p(-1).value``
        # gives the platform-correct unsigned bit pattern.
        _INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
        # Set restype so the HANDLE comes back as an unsigned pointer-width int.
        # Without this ctypes defaults to c_int (signed 32-bit), truncating a
        # Win64 INVALID_HANDLE_VALUE (0xFFFF...FFFF) to Python -1, which never
        # equals the unsigned _INVALID_HANDLE_VALUE sentinel — so the guard
        # below silently failed to detect an invalid handle.
        kernel32.GetStdHandle.restype = ctypes.c_void_p
        handle = kernel32.GetStdHandle(-11)
        if handle and handle != _INVALID_HANDLE_VALUE:
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

        log_entry = {
            # Naive ``datetime.now()`` is interpreted as wall-clock by most
            # log aggregators (Loki, ES) but loses timezone info. UTC ISO
            # is unambiguous and survives shipping across regions.
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            # ``safe_unicode`` keeps Thai/CJK intact while still rewriting
            # known emojis to ``[BRACKETED]`` tokens. JSON output is UTF-8
            # so there's no reason to mangle non-ASCII via safe_ascii.
            "message": safe_unicode(record.getMessage()),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add exception info if present
        if record.exc_info:
            log_entry["exception"] = _redact_sensitive(self.formatException(record.exc_info))

        # ensure_ascii=False so multibyte characters land verbatim instead
        # of being \u-escaped — matches the policy in health_api.py.
        return json.dumps(log_entry, ensure_ascii=False)


# Patterns that look like secrets (Discord tokens, API keys, bearer tokens).
#
# We use TWO compiled regexes and chain them in `_redact_sensitive` so the
# AWS/GitHub patterns can stay case-sensitive (the prefixes AKIA / ghp_ /
# gho_ / ghs_ are FIXED CASE in the real format — making them
# case-insensitive caused false-positive redactions on innocuous text like
# "akia" appearing inside English words / hex digests).
_SECRET_PATTERNS_CI = re.compile(
    r"(?:"
    # Discord bot token: base64.base64.base64 (3 dot-separated segments).
    # Upper bounds keep the regex linear-time against pathological input —
    # an unbounded ``{24,}`` lets a long base64-looking input feed the
    # backtracker for ages on the dot-separator branches.
    r"[A-Za-z0-9_-]{24,90}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,90}"
    r"|"
    # Generic long base64-like API key (32+ alphanumeric chars).
    # Keyword + delimiter sit in zero-width lookbehinds so the replacement
    # only redacts the SECRET, leaving the keyword visible (so you can see
    # *which* class of secret was scrubbed). Note the match still consumes
    # the surrounding quotes and the ``:``/``=`` delimiter, so a secret in
    # raw JSON (``"key":"abc..."``) becomes ``"key[REDACTED]`` — the value is
    # fully redacted (no leak), but the text is NOT kept structurally valid
    # JSON. The JSON *log file* path (JSONLogFormatter) is unaffected: this
    # text is re-escaped inside a JSON string field there.
    #
    # NOTE on the lookbehinds: each keyword needs a word boundary BEFORE
    # it so a keyword embedded in a larger word (e.g. ``monkey: <hex>``
    # matching on the ``key`` suffix) does not trigger redaction. The
    # previous form placed a bare ``(?<![A-Za-z0-9_])`` next to
    # ``(?<=key)``; both lookbehinds evaluate at the SAME position (right
    # after the keyword), so it asserted the last keyword char was BOTH
    # ``y`` AND not-alphanumeric — a contradiction that made every branch
    # match nothing, leaking opaque ``password=…`` / ``token=…`` /
    # ``authorization:…`` secrets unredacted. Fold the keyword into one
    # fixed-width negative lookbehind instead: ``(?<![A-Za-z0-9]key)``
    # rejects ``<alnum>key`` (so ``monkey`` is skipped) while ``(?<=key)``
    # confirms the keyword is present. Crucially the negative class is
    # ``[A-Za-z0-9]`` WITHOUT ``_``: a leading ``_``/``-`` separator must be
    # allowed so compound OAuth parameter names (``client_secret``,
    # ``access_token``, ``refresh_token``, ``x_api_key``) still redact —
    # their value-shape (e.g. 32-hex Spotify client secret) is too generic
    # for the prefix patterns above, so this keyword fallback is their only
    # cover. The value class includes base64 chars (``+/=``) so opaque
    # base64 credentials are not cut short. The leading ``['\"]?`` then
    # consumes an optional close-quote so JSON ``"key":"…"`` and bare
    # ``key=…`` forms both redact the value while keeping the keyword visible.
    r"(?:"
    r"(?<![A-Za-z0-9]key)(?<=key)|"
    r"(?<![A-Za-z0-9]token)(?<=token)|"
    r"(?<![A-Za-z0-9]secret)(?<=secret)|"
    r"(?<![A-Za-z0-9]password)(?<=password)|"
    r"(?<![A-Za-z0-9]apikey)(?<=apikey)|"
    r"(?<![A-Za-z0-9]api_key)(?<=api_key)|"
    r"(?<![A-Za-z0-9]authorization)(?<=authorization)|"
    r"(?<![A-Za-z0-9]bearer)(?<=bearer)"
    r")['\"]?[\s=:]+['\"]?[A-Za-z0-9+/=_\-]{32,128}(?:\.[A-Za-z0-9_\-]{4,4096}){0,2}['\"]?"
    r"|"
    # Anthropic API keys (sk-ant-api03-..., sk-ant-...) — kept BEFORE the
    # generic sk- pattern so the longer match wins.
    r"sk-ant-[A-Za-z0-9_\-]{40,}"
    r"|"
    # OpenAI / generic sk- API keys. Allow `_` and `-` so newer prefixed
    # keys (sk-proj-…, sk-svcacct-…) are redacted in full instead of being
    # cut at the first `-`, which would leak the suffix. The longer anthropic
    # pattern above runs first, so sk-ant-… still wins its more specific match.
    r"sk-[A-Za-z0-9_-]{20,}"
    r"|"
    # Google API keys (AIza...) — fixed 39 chars total
    r"AIza[A-Za-z0-9_\-]{35}"
    r"|"
    # JWTs (eyJ<base64url>.<base64url>.<base64url>), e.g. ``Bearer eyJ...``.
    # The keyword pattern above now also consumes up to two trailing JWT
    # dot-segments, so a keyword-prefixed token (``Authorization: Bearer <jwt>``,
    # ``token=<jwt>``) redacts in FULL — header, payload AND signature — instead
    # of leaking the payload/signature after the first '.'. This branch still
    # catches a BARE JWT with no keyword prefix. Bounds keep matching linear-time.
    r"eyJ[A-Za-z0-9_\-]{10,2048}\.[A-Za-z0-9_\-]{4,4096}\.[A-Za-z0-9_\-]{4,2048}"
    r"|"
    # HTTP auth-scheme credentials (``Authorization: Basic <base64>`` /
    # ``Bearer <token>``). The keyword fallback above CANNOT reach these: the
    # scheme word (``Basic``/``Bearer``) sits between the ``authorization``
    # keyword and the credential, so its contiguous value run breaks at the
    # space after the scheme; and base64 ``user:pass`` credentials contain
    # ``+``/``/``/``=`` which fall outside the keyword value class. Match the
    # scheme word + credential directly (base64 charset incl. ``+/=``) so the
    # whole header redacts regardless of the scheme word. Upper bound keeps it
    # linear-time on pathological no-whitespace input.
    r"\b(?:Basic|Bearer)\s+[A-Za-z0-9+/=_\-\.]{16,1024}"
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

# Webhook URLs (Discord/Slack) — the path token grants full send access to the
# channel, so it is a real secret. These have no key=/sk- style prefix, so the
# patterns above miss them. Capture everything up to and including the final '/'
# before the token and redact ONLY the token, keeping the URL shape visible so a
# log reader can still tell which webhook class leaked.
_WEBHOOK_TOKEN_PATTERN = re.compile(
    # Optional scheme (http:// AND https:// both grant send access) and an
    # optional leading subdomain (canary./ptb./ptb. discord, etc.) so those
    # variants don't leak the token. The captured group keeps the URL shape.
    # The subdomain run is bounded to a 63-char DNS label ({1,63}) — an
    # unbounded ``+`` here caused catastrophic backtracking (quadratic time) on
    # long no-whitespace tokens, a ReDoS on the hot per-log-line redaction path.
    r"((?:https?://)?(?:[a-z0-9-]{1,63}\.)?(?:discord(?:app)?|slack)\.com/api/webhooks/[^/\s?#]+/)"
    r"[^/\s?#]+",
    re.IGNORECASE,
)

# URL userinfo credentials (``scheme://user:password@host``) — DB / proxy /
# connection strings logged at WARNING/ERROR otherwise leak the password.
# Preserve the ``://user:`` prefix and the ``@`` so the host stays readable;
# redact only the password component between them.
# Username is zero-or-more so password-only userinfo (``redis://:pass@host``)
# still has its password redacted.
_URL_USERINFO_PATTERN = re.compile(r"(://[^/\s:@]*:)[^/\s@]+(@)")


def _redact_sensitive(value: str) -> str:
    """Redact patterns in `value` that look like secrets.

    Public helper so other subsystems (e.g. the Sentry breadcrumb scrubber)
    can apply the same redaction policy without re-implementing the regex.

    Applies both the case-insensitive pattern set (covers Discord tokens
    and prefixed keys like ``sk-``/``AIza``) AND the case-sensitive set
    (AWS ``AKIA``/GitHub ``gh[pos]_`` — these have fixed-case prefixes,
    so a case-insensitive match falsely flagged english text containing
    "akia" or lowercase identifiers).

    Also redacts webhook URL path tokens and URL-embedded passwords
    (``user:pass@host``) — neither carries a keyword/prefix the pattern sets
    above key on, so they would otherwise leak verbatim.
    """
    if not isinstance(value, str):
        return value
    redacted = _SECRET_PATTERNS_CI.sub("[REDACTED]", value)
    redacted = _SECRET_PATTERNS_CS.sub("[REDACTED]", redacted)
    redacted = _WEBHOOK_TOKEN_PATTERN.sub(r"\1[REDACTED]", redacted)
    redacted = _URL_USERINFO_PATTERN.sub(r"\1[REDACTED]\2", redacted)
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
        # The per-field passes above redact the template (record.msg) and each
        # arg INDEPENDENTLY, before the logging machinery interpolates msg % args.
        # The keyword branch of the regex only fires when a keyword sits
        # immediately before the value in the SAME string, so the dominant idiom
        # ``logger.info("api_key=%s", secret)`` slips through: the template has no
        # value and the bare arg has no keyword prefix. Redact the FULLY-RENDERED
        # message as well so a secret that only becomes keyword-adjacent after
        # interpolation is still scrubbed; collapse to a plain string and drop
        # args so downstream formatters emit the redacted text. The per-field
        # passes stay as defense-in-depth (e.g. if getMessage() ever raises).
        try:
            rendered = record.getMessage()
        except Exception:
            rendered = None
        if isinstance(rendered, str):
            redacted_rendered = _redact_sensitive(rendered)
            # Only collapse msg+args when the rendered-message pass actually
            # redacted something the per-field passes missed. When nothing
            # changed, leave record.args intact so downstream/third-party
            # handlers that introspect record.args still see the (already
            # per-field-redacted) values rather than None.
            if redacted_rendered != rendered:
                record.msg = redacted_rendered
                record.args = None
        # Scrub exception tracebacks too — secrets in exception messages would
        # otherwise leak through every handler's formatException(). Render the
        # traceback once into record.exc_text (which standard formatters reuse
        # verbatim instead of re-rendering when it's already set) so the cleaned
        # text is shared by console/file/JSONL handlers.
        if record.exc_info:
            if not record.exc_text:
                record.exc_text = logging.Formatter().formatException(record.exc_info)
            record.exc_text = _redact_sensitive(record.exc_text)
        elif record.exc_text:
            record.exc_text = _redact_sensitive(record.exc_text)
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
