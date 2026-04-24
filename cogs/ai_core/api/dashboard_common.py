"""
Shared utilities for dashboard chat handlers (Gemini & Claude).

Centralizes duplicated logic: sanitization, DB helpers, profile/memory context.
"""

from __future__ import annotations

import logging
logger = logging.getLogger(__name__)
import re as _re
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

# Canonical timezone for all prompt-injected timestamps so the model sees a
# consistent frame of reference regardless of how a timestamp was stored
# (SQLite CURRENT_TIMESTAMP = UTC naive, older Discord history = UTC ISO, new
# messages = Bangkok ISO).
BANGKOK_TZ = ZoneInfo("Asia/Bangkok")


def bangkok_now_iso() -> str:
    """Return the current time as an ISO-8601 string in Asia/Bangkok."""
    return datetime.now(tz=BANGKOK_TZ).isoformat(timespec="seconds")


def normalize_timestamp_to_bangkok(raw: Any) -> str:
    """Best-effort convert an arbitrary stored timestamp to Bangkok ISO.

    Accepts:
      - ISO-8601 with offset (e.g. ``2026-04-22T10:30:00+00:00``)
      - ISO-8601 without offset (assumed UTC)
      - SQLite ``CURRENT_TIMESTAMP`` output (``"YYYY-MM-DD HH:MM:SS"`` in UTC)
    Returns the input unchanged (coerced to str) if parsing fails, so we never
    drop the prefix entirely \u2014 partial info is better than none for the model.
    """
    if raw is None:
        return ""
    s = str(raw).strip()
    if not s:
        return ""
    try:
        # SQLite CURRENT_TIMESTAMP uses a space separator and no timezone.
        candidate = s.replace(" ", "T", 1) if "T" not in s and " " in s else s
        dt = datetime.fromisoformat(candidate)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(BANGKOK_TZ).isoformat(timespec="seconds")
    except (ValueError, TypeError):
        return s


def get_db():
    """Get a Database instance (lazy import to avoid circular deps)."""
    from .dashboard_config import Database
    return Database()


# Pattern for a single leading ISO-8601 timestamp prefix like:
#   [2026-04-22T23:17:33+07:00]  or  [2026-04-22T23:17:33Z]  or  [2026-04-22T23:17:33]
# Matches only at the start of the text and consumes trailing whitespace.
_LEADING_TIMESTAMP_RE = _re.compile(
    r"^\s*\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:[+-]\d{2}:?\d{2}|Z)?\]\s*"
)


def strip_leading_timestamp(text: str) -> str:
    """Remove a single leading ``[ISO-timestamp]`` prefix if present."""
    if not text:
        return text
    return _LEADING_TIMESTAMP_RE.sub("", text, count=1)


class LeadingTimestampStripper:
    """Stateful stripper for streaming LLM output.

    Models occasionally echo the ``[ISO-timestamp]`` prefix we inject on user
    turns back into their own responses. This class buffers the first few
    stream deltas until we can decide whether the response begins with such a
    prefix; if so, the prefix is dropped, otherwise the buffered text is
    flushed through untouched. Once the first non-timestamp output has been
    emitted, subsequent calls to :meth:`feed` pass the text through unchanged.
    """

    # Once the buffer exceeds this, we stop waiting and flush as-is. A valid
    # prefix like ``[2026-04-22T23:17:33+07:00]`` is 27 chars, so 64 is ample.
    _MAX_PROBE = 64

    def __init__(self) -> None:
        self._buffer = ""
        self._done = False

    def feed(self, text: str) -> str:
        """Consume a streaming chunk and return the text safe to emit."""
        if self._done:
            return text
        self._buffer += text
        # If the non-whitespace content clearly does not start with '[', there
        # is no timestamp prefix \u2014 flush immediately.
        lstripped = self._buffer.lstrip()
        if lstripped and not lstripped.startswith("["):
            out = self._buffer
            self._buffer = ""
            self._done = True
            return out
        # Try a full match against the buffered text.
        match = _LEADING_TIMESTAMP_RE.match(self._buffer)
        if match:
            out = self._buffer[match.end():]
            self._buffer = ""
            self._done = True
            return out
        # Haven't seen enough yet \u2014 keep buffering unless we've waited too long.
        if len(self._buffer) >= self._MAX_PROBE:
            out = self._buffer
            self._buffer = ""
            self._done = True
            return out
        return ""

    def flush(self) -> str:
        """Return any remaining buffered text at end-of-stream."""
        if self._done:
            return ""
        out = self._buffer
        self._buffer = ""
        self._done = True
        return out


def sanitize_profile_field(value: Any, max_len: int = 200) -> str:
    """Sanitize user profile fields to prevent system instruction injection.

    Accepts any type — non-str values are coerced via ``str()`` first so the
    function works when callers pass dict/list/int profile fields. Unicode is
    normalized (NFKC) so that lookalike attacks like ``sуstem:`` (Cyrillic ``у``)
    cannot bypass the keyword filter.
    """  # noqa: RUF002
    if value is None or value == "":
        return ""
    if not isinstance(value, str):
        value = str(value)
    import unicodedata as _unicodedata
    value = _unicodedata.normalize("NFKC", value)
    value = _re.sub(r'[\x00-\x1f\x7f]', '', value)  # Remove control chars
    value = _re.sub(r'[\[\]{}`]', '', value)  # Strip brackets/braces/backticks to prevent instruction injection
    # Remove patterns that could be used for prompt injection
    value = _re.sub(r'(?i)\b(system|ignore|instruction|override|forget)\s*:', '', value)
    return value[:max_len]


async def build_user_context(
    user_name: str,
    unrestricted_mode_requested: bool,
) -> tuple[str, str, bool]:
    """Build user profile context and load memories from DB.

    Returns:
        (user_context, memories_context, unrestricted_mode)
    """
    from .dashboard_config import DB_AVAILABLE

    user_profile: dict[str, Any] = {}
    if DB_AVAILABLE:
        try:
            db = get_db()
            user_profile = await db.get_dashboard_user_profile() or {}
        except Exception as e:
            logger.warning("Failed to load user profile: %s", e)

    profile_name = sanitize_profile_field(user_profile.get("display_name") or user_name)
    profile_info_parts = [f"Name: {profile_name}"]

    if user_profile.get("is_creator"):
        profile_info_parts.append(
            "Role: Creator/Developer of this bot (treat with special respect, they made you!)"
        )

    unrestricted_mode = unrestricted_mode_requested and bool(user_profile.get("is_creator"))

    if user_profile.get("bio"):
        profile_info_parts.append(f"About: {sanitize_profile_field(user_profile['bio'], 500)}")
    if user_profile.get("preferences"):
        profile_info_parts.append(
            f"Preferences: {sanitize_profile_field(user_profile['preferences'], 500)}"
        )

    user_context = "[User Profile]\n" + "\n".join(profile_info_parts)

    # Load long-term memories
    memories_context = ""
    if DB_AVAILABLE:
        try:
            db = get_db()
            memories = await db.get_dashboard_memories(limit=20)
            if memories:
                memories_text = "\n".join(
                    [f"- {sanitize_profile_field(m['content'], 500)}" for m in memories]
                )
                memories_context = f"\n\n[Long-term Memories about User]\n{memories_text}"
        except Exception as e:
            logger.warning("Failed to load memories: %s", e)

    return user_context, memories_context, unrestricted_mode
