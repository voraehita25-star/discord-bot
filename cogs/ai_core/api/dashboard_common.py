"""
Shared utilities for dashboard chat handlers (Gemini & Claude).

Centralizes duplicated logic: sanitization, DB helpers, profile/memory context.
"""

from __future__ import annotations

import asyncio
import logging
import time

logger = logging.getLogger(__name__)
import re as _re
from datetime import datetime, timezone
from typing import Any, TypedDict
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
    """  # noqa: RUF002 - intentional Cyrillic example in docstring
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
    return str(value[:max_len])


class _UserContextCacheEntry(TypedDict):
    """Cached user_context payload — see ``build_user_context``."""

    expires_at: float
    user_context: str
    memories_context: str
    profile_is_creator: bool


# Per-conversation cache for build_user_context. Each AI turn used to re-query
# profile + 20 documents from SQLite and rebuild a ~400 KB string; with the
# cache we skip both work items unless the conversation's documents changed.
# Invalidation is explicit (see ``invalidate_user_context_cache``) — TTL is a
# safety net so callers that forget to invalidate still see fresh data within
# 60 s. user_name is NOT part of the key because it's only the fallback when
# the DB profile lacks a display_name; same conversation has the same fallback.
_USER_CONTEXT_CACHE: dict[str | None, _UserContextCacheEntry] = {}
_USER_CONTEXT_CACHE_TTL = 60.0  # seconds
_USER_CONTEXT_CACHE_MAX_ENTRIES = 64
_user_context_lock: asyncio.Lock | None = None


def _get_user_context_lock() -> asyncio.Lock:
    """Lazily create the cache lock to avoid event-loop binding at import time."""
    global _user_context_lock
    if _user_context_lock is None:
        _user_context_lock = asyncio.Lock()
    return _user_context_lock


def invalidate_user_context_cache(conversation_id: str | None = None) -> None:
    """Drop the cached ``user_context`` so the next AI turn rebuilds it.

    Pass a conversation id to clear only that conversation's entry. Pass
    ``None`` to clear *all* entries (use after profile updates, since the
    profile is shared across every conversation). This is fire-and-forget —
    a missing key is silently ignored so callers don't have to care whether
    the cache had been populated yet.
    """
    if conversation_id is None:
        _USER_CONTEXT_CACHE.clear()
    else:
        _USER_CONTEXT_CACHE.pop(conversation_id, None)


async def build_user_context(
    user_name: str,
    unrestricted_mode_requested: bool,
    conversation_id: str | None = None,
) -> tuple[str, str, bool]:
    """Build user profile context and load memories from DB.

    ``conversation_id`` scopes the document-memory lookup: each conversation
    has its own library of uploaded PDFs/text files, so documents attached
    in conversation A don't leak into conversation B. ``None`` falls back to
    the unscoped behaviour (all documents visible) — kept for callers that
    don't have a conversation context, e.g. persona refresh paths.

    Results are cached per-conversation for ``_USER_CONTEXT_CACHE_TTL`` seconds
    or until ``invalidate_user_context_cache`` is called. The cache stores
    ``profile_is_creator`` separately so toggling ``unrestricted_mode_requested``
    between turns doesn't require a rebuild — we re-AND it on every lookup.

    Returns:
        (user_context, memories_context, unrestricted_mode)
    """
    from .dashboard_config import DB_AVAILABLE

    cache_key = conversation_id
    now = time.monotonic()
    cached = _USER_CONTEXT_CACHE.get(cache_key)
    if cached is not None and cached["expires_at"] > now:
        unrestricted = unrestricted_mode_requested and cached["profile_is_creator"]
        return cached["user_context"], cached["memories_context"], unrestricted

    user_profile: dict[str, Any] = {}
    if DB_AVAILABLE:
        try:
            db = get_db()
            user_profile = await db.get_dashboard_user_profile() or {}
        except Exception as e:
            logger.warning("Failed to load user profile: %s", e)

    profile_name = sanitize_profile_field(user_profile.get("display_name") or user_name)
    profile_info_parts = [f"Name: {profile_name}"]

    profile_is_creator = bool(user_profile.get("is_creator"))
    if profile_is_creator:
        profile_info_parts.append(
            "Role: Creator/Developer of this bot (treat with special respect, they made you!)"
        )

    unrestricted_mode = unrestricted_mode_requested and profile_is_creator

    if user_profile.get("bio"):
        profile_info_parts.append(f"About: {sanitize_profile_field(user_profile['bio'], 500)}")
    if user_profile.get("preferences"):
        profile_info_parts.append(
            f"Preferences: {sanitize_profile_field(user_profile['preferences'], 500)}"
        )

    user_context = "[User Profile]\n" + "\n".join(profile_info_parts)

    # Persistent document memories — text extracted from PDF / DOCX / text
    # files the user has uploaded in THIS conversation. Scoped per-conversation
    # so each RP thread keeps its own library; attachments from one conversation
    # don't bleed into another. Auto-injected on every turn so users don't
    # re-upload the same character sheet. Newest first, trimmed for prompt.
    if DB_AVAILABLE:
        try:
            db = get_db()
            docs = await db.get_document_memories(limit=20, conversation_id=conversation_id)
            if docs:
                doc_sections: list[str] = []
                running_total = 0
                # Hard cap the injection so one big PDF can't eat the whole
                # prompt budget. Sized for Opus/Sonnet 1M-context: 400K chars
                # ≈ ~120-150K tokens, enough to fit a single near-max-extract
                # PDF (MAX_EXTRACTED_CHARS = 500K) almost in full while leaving
                # ample room for chat history, system prompt, and response.
                # If users hit this, older docs get dropped from this turn
                # but stay in DB for later.
                MAX_INJECT_CHARS = 400_000
                for doc in docs:
                    text = doc.get("extracted_text") or ""
                    filename = doc.get("filename") or "document"
                    if not text:
                        continue
                    remaining = MAX_INJECT_CHARS - running_total
                    if remaining <= 0:
                        break
                    snippet = text if len(text) <= remaining else text[:remaining] + "\n[... truncated in prompt]"
                    doc_sections.append(f"## {filename}\n{snippet}")
                    running_total += len(snippet)
                if doc_sections:
                    user_context += (
                        "\n\n[Attached Documents (persistent)]\n"
                        "The following documents were uploaded in past turns. "
                        "Treat them as reference material the user has shared with you:\n\n"
                        + "\n\n".join(doc_sections)
                    )
        except Exception as e:
            logger.warning("Failed to load document memories: %s", e)

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

    # Populate the cache before returning. We don't need the lock for the dict
    # write itself (CPython dict assignment is atomic), but we DO need it for
    # the over-capacity trim so two concurrent rebuilds can't both decide to
    # evict the same entry and leave the cache empty.
    async with _get_user_context_lock():
        if (
            cache_key not in _USER_CONTEXT_CACHE
            and len(_USER_CONTEXT_CACHE) >= _USER_CONTEXT_CACHE_MAX_ENTRIES
        ):
            # Evict the entry with the soonest expiry (effectively LRU since
            # every lookup that misses refreshes expires_at).
            oldest = min(
                _USER_CONTEXT_CACHE,
                key=lambda k: _USER_CONTEXT_CACHE[k]["expires_at"],
            )
            _USER_CONTEXT_CACHE.pop(oldest, None)
        _USER_CONTEXT_CACHE[cache_key] = {
            "expires_at": now + _USER_CONTEXT_CACHE_TTL,
            "user_context": user_context,
            "memories_context": memories_context,
            "profile_is_creator": profile_is_creator,
        }

    return user_context, memories_context, unrestricted_mode
