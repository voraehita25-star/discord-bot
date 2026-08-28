# pyright: reportAttributeAccessIssue=false
# pyright: reportAssignmentType=false
"""
AI Logic Module
Handles the core chat logic, Gemini API integration, and context management.
Optimized with precompiled regex patterns and lazy image loading.

Note: Type checker warnings for optional imports and Discord.py types are suppressed
because the conditional imports with fallback stubs work correctly at runtime.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import datetime
import logging
import os
import re
import time
from collections.abc import AsyncIterator
from datetime import timedelta, timezone
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Pre-allocate timezone to avoid re-creating on every message. On Windows
# without the ``tzdata`` package, ``ZoneInfo("Asia/Bangkok")`` raises and
# the whole AI cog would fail to load. Fall back to a fixed UTC+7 offset
# so the bot stays operational and only the IANA-aware features (DST,
# historical-transition data — which Bangkok doesn't observe anyway)
# silently degrade.
try:
    BANGKOK_TZ: Any = ZoneInfo("Asia/Bangkok")
except ZoneInfoNotFoundError:
    import logging as _logging_zi

    _logging_zi.getLogger(__name__).warning(
        "ZoneInfo('Asia/Bangkok') unavailable (tzdata not installed). "
        "Falling back to fixed UTC+7. `pip install tzdata` to restore IANA accuracy."
    )
    BANGKOK_TZ = timezone(timedelta(hours=7), name="Asia/Bangkok")

import aiohttp
import anthropic
import discord
from PIL import Image


class _NewMessageInterrupt(BaseException):
    """Raised when a new message arrives to cancel current processing.

    Inherits from BaseException (not Exception) so blanket ``except Exception``
    handlers upstream cannot accidentally swallow the interrupt, which would
    leave the abort-old-response flow broken.
    """


def _utc_now_iso() -> str:
    """Return a normalized UTC ISO 8601 timestamp for persisted chat history.

    Returns a timezone-aware UTC value so the function name matches its
    behaviour. Downstream consumers that need to display in Asia/Bangkok
    apply ``normalize_timestamp_to_bangkok`` at format time, so storing UTC
    is the safer canonical form.
    """
    return datetime.datetime.now(timezone.utc).isoformat(timespec="seconds")


from .api.api_handler import (
    build_api_config,
    call_claude_api,
    call_claude_api_streaming,
)
from .character_tags import replace_character_names
from .claude_payloads import ClaudeContentBlockParam
from .core.message_queue import MessageQueue

# Import new modular components (v3.3.6 - direct subfolder imports)
from .core.performance import PerformanceTracker, RequestDeduplicator

# Import extracted modules
from .data.constants import (
    ANTHROPIC_API_KEY,
    CLAUDE_MODEL,
    CREATOR_ID,
    ENTITY_TOP_K,
    GUILD_ID_RP,
    LOCK_TIMEOUT,
    MAX_HISTORY_ITEMS,
    RAG_TOP_K,
)
from .emoji import convert_discord_emojis, extract_discord_emojis, fetch_emoji_images

# Centralized optional dependencies. FALLBACK_AVAILABLE /
# TOKEN_TRACKER_AVAILABLE aren't referenced locally but are part of this
# module's public surface (tests import them via
# ``from cogs.ai_core.logic import X``).
from .imports import (  # noqa: F401 - public re-exports
    CIRCUIT_BREAKER_AVAILABLE,
    FALLBACK_AVAILABLE,
    FEEDBACK_AVAILABLE,
    GUARDRAILS_AVAILABLE,
    HISTORY_MANAGER_AVAILABLE,
    TOKEN_TRACKER_AVAILABLE,
    URL_FETCHER_AVAILABLE,
    add_feedback_reactions,
    extract_urls,
    feedback_collector,
    fetch_all_urls,
    format_url_content_for_context,
    gemini_circuit,
    history_manager,
    validate_response_for_channel,
)

# Import media processing module
from .media_processor import (
    InlineDataPart,
    ProcessedVideoPart,
    convert_gif_to_video,
    is_animated_gif,
    load_character_image,
    pil_to_inline_data,
    prepare_user_avatar,
    process_attachments,
)
from .memory.consolidator import memory_consolidator
from .memory.entity_memory import entity_memory
from .memory.rag import rag_system
from .memory.state_tracker import state_tracker
from .memory.summarizer import summarizer
from .response.response_mixin import ResponseMixin

# The single mention-defang implementation, shared with ``send_as_webhook`` so
# the plain-send and per-character paths of one reply cannot escape by
# different rules (see the note above PATTERN_CHARACTER_TAG).
from .sanitization import escape_mentions
from .session_mixin import SessionMixin
from .storage import (
    _normalize_history_timestamp,
    _parts_to_text,
    delete_message_by_id,
    edit_message_by_id,
    resolve_history_limit,
    save_history,
    update_message_id,
)
from .tools import send_as_webhook

# NOTE: tool-use execution is intentionally NOT wired into this turn loop.
# The Anthropic streaming pipeline in ``api_handler.py`` currently surfaces
# tool_use blocks through the third return slot (``_function_calls`` below)
# as an always-empty list — the legacy Gemini code path that consumed
# function calls was removed during the Claude migration, and no Claude
# tool_result roundtrip has been wired in its place. ``execute_tool_call``
# stays exported from ``cogs.ai_core.tools`` for direct CLI use, tests,
# and dev probes (``scripts/dev/probe_ai_flow.py`` etc.); putting it back
# into the AI's turn loop requires a proper assistant→tool_use→tool_result
# alternation per the Anthropic API contract, not the previous text-blob
# concat-into-reply approach.
from .voice import (
    join_voice_channel as voice_join,
    leave_voice_channel as voice_leave,
    parse_voice_command as voice_parse_command,
)

logger = logging.getLogger(__name__)

# NOTE: IMAGEIO_AVAILABLE is imported from .media_processor (line 61)
# No need to re-import imageio here

if TYPE_CHECKING:
    import discord
    from discord.ext.commands import Bot


# ==================== Precompiled Regex Patterns ====================
# Compile patterns once at module load for better performance

# Post-processing patterns
PATTERN_QUOTE = re.compile(r'^>\s*(["\'])', re.MULTILINE)
PATTERN_SPACED = re.compile(r'^\s*>\s*(["\'])', re.MULTILINE)
# Strips a leading ``[ID: nnn]`` from STORED text before it is re-fed to the
# model. Kept deliberately: message ids reach the prompt from the authoritative
# ``message_id``/``sent_message_ids`` bookkeeping (see
# ``_format_message_id_prefix``), so an id the model once echoed into its own
# reply must not be laundered back in as if it were one of ours.
PATTERN_ID = re.compile(r"^\[ID:\s*\d+\]\s*")

# How many per-message ids to name in one annotation. A turn is capped at ~30
# {{Name}} blocks upstream; listing every one of a pathological turn would cost
# more prompt than it is worth, and read_channel can always resolve the rest.
_MAX_ANNOTATED_MESSAGE_IDS = 12


def _format_message_id_prefix(item: dict[str, Any]) -> str:
    """Render the ``(msg …)`` annotation for one stored model turn.

    The AI cannot correct an earlier message without that message's Discord id,
    and a turn is not always a single message: a long reply is split across
    chunks, and a multi-character RP turn sends one webhook message per
    ``{{Name}}`` block — while all of it is stored as ONE history row with room
    for one ``message_id``. So prefer the recorded per-message ids and fall back
    to the row's single id.

    Returns "" when nothing was recorded — rows written before the ids were
    tracked, or a turn whose send failed. ``read_channel`` reports ids straight
    from Discord and covers those.
    """
    sent = item.get("sent_message_ids")
    if isinstance(sent, list) and sent:
        labelled: list[str] = []
        for entry in sent[:_MAX_ANNOTATED_MESSAGE_IDS]:
            if not isinstance(entry, dict) or entry.get("id") is None:
                continue
            name = str(entry.get("name") or "").strip()
            labelled.append(f"{name}={entry['id']}" if name else str(entry["id"]))
        if labelled:
            suffix = ", …" if len(sent) > _MAX_ANNOTATED_MESSAGE_IDS else ""
            return f"(msgs {', '.join(labelled)}{suffix}) "
    message_id = item.get("message_id")
    if message_id is not None:
        return f"(msg {message_id}) "
    return ""


# Character tag pattern {{Name}}
PATTERN_CHARACTER_TAG = re.compile(r"\{\{(.+?)\}\}")

# How many ``{{Name}}`` blocks one turn may send as separate webhook messages.
# Each block is one Discord send plus a 0.5s spacing sleep, so an adversarial
# or malformed reply full of tags would otherwise turn a single turn into
# hundreds of sends. Expressed as a BLOCK count (not an element count) because
# ``PATTERN_CHARACTER_TAG.split`` returns ``1 + 2 * blocks`` elements — see the
# cap in ``process_chat`` for why an even element cap silently loses one block.
MAX_CHARACTER_BLOCKS = 30

# A {{Name}} marker left dangling at the end of a prefix — i.e. immediately
# before the text being removed. Used to take the speaker label out with the
# line it labelled.
PATTERN_TRAILING_CHARACTER_TAG = re.compile(r"\{\{[^{}]+\}\}\s*$")


def _sent_message_entries(item: Any) -> list[dict[str, Any]]:
    """The recorded ``[{"name", "id"}]`` entries of a history row, or []."""
    sent = item.get("sent_message_ids") if isinstance(item, dict) else None
    if not isinstance(sent, list):
        return []
    return [e for e in sent if isinstance(e, dict) and e.get("id") is not None]


def _row_covers_message(item: Any, message_id: int) -> bool:
    """Whether a history row accounts for a given Discord message.

    A row covers its ``message_id``, and — for a turn that went out as several
    messages — every id in ``sent_message_ids``. Checking only the former is
    what left intermediate RP character messages invisible to the Discord
    delete/edit mirroring.
    """
    if not isinstance(item, dict):
        return False
    if item.get("message_id") == message_id:
        return True
    return any(entry.get("id") == message_id for entry in _sent_message_entries(item))


def _remove_message_fragment(text: str, fragment: str) -> str:
    """Cut one sent message's text out of the turn that stored it.

    A multi-character RP turn is a single history row holding every
    ``{{Name}}`` block, so deleting ONE of its Discord messages must remove
    just that block — dropping the row would forget lines still on screen. The
    speaker marker goes with the line it labelled, otherwise the turn keeps a
    dangling ``{{Name}}`` introducing nothing.
    """
    idx = text.find(fragment)
    if idx == -1:
        return text
    start = idx
    prefix = text[:idx]
    marker = PATTERN_TRAILING_CHARACTER_TAG.search(prefix)
    if marker:
        start = marker.start()
    # Blocks are joined by a newline, so cutting one out of the middle would
    # leave the separator from BOTH sides. Take the leading one with it.
    if start > 0 and text[start - 1] == "\n":
        start -= 1
    remainder = text[:start] + text[idx + len(fragment) :]
    # Safety net for text that was separated by blank lines to begin with.
    return re.sub(r"\n{3,}", "\n\n", remainder).strip()


# Pattern to detect AI comments about character tags that should be actual tags
# Matches: (ตรงนี้ควรใช้เป็น {{Name}}...) or similar patterns
PATTERN_AI_TAG_COMMENT = re.compile(
    r"\(ตรงนี้ควร(?:ใช้|เป็น|เปลี่ยน).*?\{\{(.+?)\}\}.*?\)|"
    r"\((?:should use|switch to|this should be)\s*\{\{(.+?)\}\}.*?\)",
    re.IGNORECASE,
)

# Channel ID extraction pattern
PATTERN_CHANNEL_ID = re.compile(r"\b(\d{17,20})\b")

# Discord custom emoji pattern - <:name:id> or <a:name:id> (animated)
PATTERN_DISCORD_EMOJI = re.compile(r"<(a?):(\w+):(\d+)>")

# NOTE: this module deliberately keeps NO mention-escape patterns of its own.
# It used to carry a private copy (PATTERN_AT_EVERYONE / _AT_HERE / _USER_TAG /
# _ROLE_TAG) whose comment claimed to "mirror the canonical pattern in
# sanitization.py". It did not, and the drift reintroduced three of the exact
# bugs ``sanitization.escape_mentions`` documents as fixed:
#   * ``@EVERYONE`` came back LOWERCASED — a fixed replacement string under
#     IGNORECASE, where the canonical version re-emits the keyword through a
#     backreference so the model's casing survives.
#   * ``<@!123>`` lost its legacy-nickname bang — ``!?`` consumed it and the
#     replacement never put it back, so the rendered text named a different
#     id form than the model actually wrote.
#   * ``＠everyone`` (full-width @) went out UNESCAPED — the canonical version
#     NFKC-folds first, so width variants reach the regex as a plain ``@``.
# And because ``send_as_webhook`` already calls ``escape_mentions``, a
# multi-character RP turn escaped its ``{{Name}}`` blocks by one set of rules
# and its narrator/plain text by another — inside a single reply.
# ``process_chat`` now calls the canonical escaper for both paths. Do not
# reintroduce a local copy: the rules belong in ONE function.

# Thai combining marks (tone marks, vowel marks) cannot appear at the start of
# a chunk — splitting just before one renders as a stray ◌-form glyph.
_THAI_COMBINING = set(range(0x0E30, 0x0E3B)) | set(range(0x0E47, 0x0E4F))

# How far a hard cut may rewind looking for the start of a Thai cluster. A real
# cluster is a base plus at most a handful of marks, so 16 is already generous
# (it matches the rewind cap in ``sanitization.sanitize_message_content``).
#
# The cap is load-bearing, not cosmetic. The rewind walks back over EVERY
# consecutive mark, so text that is nothing but marks — a "zalgo"/tone-mark
# flood a user can trivially ask the model to produce — rewound all the way to
# index 1 and the splitter emitted ONE CHARACTER per chunk: a 5,000-mark reply
# became 3,001 chunks, i.e. 3,001 separate Discord sends from the loop in
# ``process_chat`` (measured). Bounding the rewind keeps progress at ~``limit``
# per chunk; the trade-off is that such degenerate input may orphan a mark at a
# chunk start, which is unavoidable for a string that contains no base char.
_MAX_COMBINING_REWIND = 16


def _split_for_discord(text: str, limit: int = 2000) -> list[str]:
    """Split ``text`` into ``<=limit``-char chunks at natural boundaries.

    Prefers a newline boundary, then a space, then a hard cut at ``limit``.
    A hard cut is rewound past any Thai combining marks AND their base char so
    a mark never lands orphaned at the start of the next chunk. Shared by the
    narrator-intro path and the normal-send path so both are Thai-safe — the
    narrator path previously used a raw fixed-width slice and could orphan a
    combining mark on a long (>2000-char) intro.
    """
    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break
        # Find best split point near `limit` chars.
        split_at = remaining.rfind("\n", 0, limit)
        # Track whether the chosen boundary is the delimiter newline: only then
        # may we consume it. A hard mid-content cut must NOT strip leading
        # newlines, or intentional blank lines straddling the boundary
        # (ASCII art / code) are dropped.
        split_on_newline = split_at != -1 and split_at >= limit // 2
        if not split_on_newline:
            split_at = remaining.rfind(" ", 0, limit)
        if split_at == -1 or split_at < limit // 2:
            split_at = limit
        # Newline/space split points can never land on a combining mark, so
        # only the hard-split case needs the rewind.
        if split_at >= limit:
            rewind = split_at
            # Never rewind further than one cluster's worth — see
            # _MAX_COMBINING_REWIND for why an unbounded walk collapses a
            # mark-only reply into one-character chunks.
            rewind_floor = max(1, split_at - _MAX_COMBINING_REWIND)
            # Case 1: the cut lands ON a mark (base|first-mark boundary, or
            # inside a multi-mark cluster) — the char AT the cut is combining.
            # Step back to the cluster's base so the whole cluster moves to
            # the next chunk. This case was previously missed: only
            # remaining[rewind-1] was inspected, so a cut exactly between a
            # base and its FIRST mark orphaned the mark at the next chunk's
            # start (stray dotted-circle glyph).
            while rewind > rewind_floor and ord(remaining[rewind]) in _THAI_COMBINING:
                rewind -= 1
            # Case 2 (only when case 1 didn't fire): the cut lands right
            # AFTER trailing marks — walk back past the marks AND their base
            # char (stopping at the base would orphan its marks).
            if rewind == split_at:
                while rewind > rewind_floor and ord(remaining[rewind - 1]) in _THAI_COMBINING:
                    rewind -= 1
                if rewind > rewind_floor and rewind < split_at:
                    rewind -= 1
            elif ord(remaining[rewind]) in _THAI_COMBINING:
                # Hit the rewind cap without reaching a cluster base: the whole
                # window is marks. Keep the full-width cut — a stray glyph beats
                # fanning one reply out into thousands of Discord messages.
                rewind = split_at
            split_at = rewind
        chunks.append(remaining[:split_at])
        if split_on_newline:
            # Consume exactly the single delimiter newline (preserve any
            # further intentional blank lines).
            remaining = remaining[split_at + 1 :]
        else:
            # Space split keeps its leading space; hard cut keeps content as-is.
            remaining = remaining[split_at:]
    return chunks


# NOTE: convert_discord_emojis, extract_discord_emojis, fetch_emoji_images
# are imported from .emoji module (line 45) - DO NOT redefine here

# NOTE: _load_cached_image_bytes is imported from .media_processor (line 61)
# DO NOT redefine here - removed duplicate @lru_cache function


@contextlib.asynccontextmanager
async def _typing_or_noop(channel: Any) -> AsyncIterator[None]:
    """เปิด typing indicator แบบ fail-safe — เปิดไม่ได้ก็ทำงานต่อโดยไม่มี typing.

    ``channel.typing().__aenter__()`` ยิง HTTP ``send_typing`` จริง ถ้า Discord
    ตอบ Forbidden/5xx/rate-limit ตรงนั้น exception จะข้ามทุก handler ด้านในแล้ว
    หลุดออกจาก process_chat ทำให้ข้อความผู้ใช้ถูกทิ้งเงียบ ๆ. typing เป็นแค่
    สัญญาณ cosmetic จึงต้อง degrade เป็น "ไม่มี typing" แทนการล้มทั้ง turn.

    ใช้ ``__aenter__``/``__aexit__`` แบบ manual (ไม่ใช่ ``async with ...: yield``)
    เพื่อกลืนเฉพาะความล้มเหลวตอน enter แล้วยัง ``yield`` ต่อได้ โดยไม่เกิด
    double-yield RuntimeError เวลา body ภายในโยน exception.
    """
    typing_cm = channel.typing()
    try:
        await typing_cm.__aenter__()
    except discord.HTTPException as e:
        logger.debug("Typing indicator unavailable, continuing without it: %s", e)
        yield
        return
    try:
        yield
    finally:
        # suppress(Exception) ไม่ใช่ BaseException — ให้ CancelledError จาก body
        # ยัง propagate ออกไปเพื่อ cancel task ได้ถูกต้อง (ตรงกับ re-raise ด้านล่าง).
        with contextlib.suppress(Exception):
            await typing_cm.__aexit__(None, None, None)


def _find_history_item_index(
    chat_history: list[dict[str, Any]], row: dict[str, Any], occurrence: int = 0
) -> int | None:
    """Locate the in-memory history item that a DB ``ai_history`` row refers to.

    Shared matcher for the dashboard's external edit/delete mirroring
    (``ChatManager.patch_history_content`` / ``remove_history_content``), so
    both operations identify the same item for the same row. Matching mirrors
    how the save paths identify rows: by ``message_id`` when the row has one,
    else by role + normalized timestamp + content equality (the same triple
    the diff-save overlap hash uses).

    ``occurrence`` disambiguates message_id-less "twins" (multiple items
    identical on all three fallback keys): it is the row's ordinal among its
    twins in DB id order, which equals memory order on load. If fewer matches
    exist than the ordinal, the LAST match wins — twin sets are
    content-identical, so a best-effort hit at the wrong slot only affects
    ordering, while no-match would leave the stale item to clobber the DB
    state on the next save.

    Returns the matched index, or None when nothing matches.
    """
    message_id = row.get("message_id")
    if message_id is not None:
        for i, item in enumerate(chat_history):
            if item.get("message_id") == message_id:
                return i
        return None

    role = row.get("role")
    row_ts = _normalize_history_timestamp(row.get("timestamp"))
    row_content = str(row.get("content") or "")
    last_match: int | None = None
    matches_seen = 0
    for i, item in enumerate(chat_history):
        if item.get("message_id") is not None:
            # Carries a Discord id -> corresponds to a non-NULL-message_id DB
            # row, which the row-id path above would have matched. Skipping
            # keeps the twin ordinal congruent with the IS NULL filter in
            # count_identical_history_rows_before.
            continue
        if item.get("role") != role:
            continue
        if _normalize_history_timestamp(item.get("timestamp")) != row_ts:
            continue
        if _parts_to_text(item.get("parts") or []) != row_content:
            continue
        if matches_seen == occurrence:
            return i
        last_match = i
        matches_seen += 1
    # Fewer matches than the requested ordinal: clamp to the LAST match.
    return last_match


def _count_history_item_matches(chat_history: list[dict[str, Any]], row: dict[str, Any]) -> int:
    """Count message_id-less in-memory twins of a DB ``ai_history`` row.

    Same match keys as ``_find_history_item_index``'s fallback loop (skip
    items carrying a ``message_id``, match role + normalized timestamp +
    content), so the count is congruent with the twin-ordinal machinery.
    ``insert_history_content`` compares this against the DB's twin count to
    decide whether a restored mid-less row is genuinely already in memory or
    only a surviving identical twin is.
    """
    role = row.get("role")
    row_ts = _normalize_history_timestamp(row.get("timestamp"))
    row_content = str(row.get("content") or "")
    count = 0
    for item in chat_history:
        if item.get("message_id") is not None:
            continue
        if item.get("role") != role:
            continue
        if _normalize_history_timestamp(item.get("timestamp")) != row_ts:
            continue
        if _parts_to_text(item.get("parts") or []) != row_content:
            continue
        count += 1
    return count


class ChatManager(SessionMixin, ResponseMixin):
    """
    Manages AI chat sessions, history, and interactions with the Gemini API.

    Inherits from:
    - SessionMixin: Session lifecycle, history, cleanup
    - ResponseMixin: Response processing, voice status, history retrieval
    """

    # Maximum number of channels to track to prevent unbounded memory growth
    MAX_CHANNELS = 5000

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot
        self.chats: dict[int, Any] = {}  # Channel ID -> Chat object
        self.last_accessed: dict[int, float] = {}  # Channel ID -> Timestamp
        self.seen_users: dict[int, set[str]] = {}  # Channel ID -> Set of user_keys
        self.client: anthropic.AsyncAnthropic | None = None
        self.target_model: str | None = None
        # ``cli_mode`` mirrors the env-var read in ``setup_ai`` but is
        # cheaper to consult on the hot path (``process_chat`` checks it
        # on every message). True when ``CLAUDE_BACKEND=cli`` and the
        # Discord-side path should route to ``discord_chat_claude_cli``
        # instead of the SDK client.
        self.cli_mode: bool = False
        # NOTE: processing_locks is aliased to the MessageQueue's dict below
        # (after _message_queue is constructed) so the two share one map.

        # Streaming mode settings
        self.streaming_enabled: dict[int, bool] = {}  # Channel ID -> Streaming enabled

        # Use new modular components (v3.3.6)
        self._message_queue = MessageQueue()
        self._performance = PerformanceTracker()
        self._deduplicator = RequestDeduplicator()

        # Strong references to fire-and-forget background tasks (consolidation, LRU save)
        # to prevent them being GC'd mid-execution (event loop only holds weak refs).
        self._background_tasks: set[asyncio.Task] = set()

        # Channels whose pending queue is currently being drained by
        # _process_pending_messages. process_chat's finally consults this so
        # nested turns don't re-enter the drain loop recursively.
        self._draining: set[int] = set()

        # Legacy aliases for backward compatibility
        self.pending_messages = self._message_queue.pending_messages
        self.cancel_flags = self._message_queue.cancel_flags
        self._lock_times = self._message_queue._lock_times
        # Share ONE processing_locks dict with the queue. process_chat populates
        # it when acquiring a channel's lock; MessageQueue.queue_message's
        # MAX_CHANNELS eviction guard reads the same dict to skip channels that
        # are actively being processed. They were previously two separate dicts,
        # so the guard always saw an empty map and could evict an in-flight
        # channel's pending queue.
        self.processing_locks: dict[int, asyncio.Lock] = self._message_queue.processing_locks
        self._performance_metrics = self._performance._metrics

        self.setup_ai()

    def _enforce_channel_limit(self) -> int:
        """Enforce max channel limit by removing oldest accessed channels (LRU eviction).

        Returns:
            Number of channels evicted.
        """
        if len(self.chats) <= self.MAX_CHANNELS:
            return 0

        # Sort by last_accessed timestamp (oldest first)
        sorted_channels = sorted(self.last_accessed.items(), key=lambda x: x[1])

        # Calculate how many to evict (evict 10% to avoid frequent evictions)
        evict_count = max(1, len(self.chats) - self.MAX_CHANNELS + (self.MAX_CHANNELS // 10))
        evicted = 0

        # Collect channels to evict (saving history requires async, schedule it)
        channels_to_evict = []
        for channel_id, _ in sorted_channels[:evict_count]:
            # Skip channels that are currently being processed (have a locked lock)
            lock = self.processing_locks.get(channel_id)
            if lock is not None and lock.locked():
                continue
            channels_to_evict.append(channel_id)

        for channel_id in channels_to_evict:
            # Save history before evicting to prevent data loss.
            # The callback deletes from memory only on save success.
            if channel_id in self.chats:
                chat_copy = self.chats[channel_id]
                # Snapshot the access time at SCHEDULE time. save_history is
                # awaited on a background task, so the channel can be re-accessed
                # before the callback fires; the timestamp lets the callback tell
                # a stale snapshot from a live one.
                ts_at_schedule = self.last_accessed.get(channel_id)
                try:
                    loop = asyncio.get_running_loop()
                    from .storage import save_history

                    task = loop.create_task(save_history(self.bot, channel_id, chat_copy))

                    # Keep strong reference so task isn't GC'd before completion.
                    self._background_tasks.add(task)
                    task.add_done_callback(self._background_tasks.discard)

                    # Capture channel_id and self per-iteration for the callback.
                    # Clean up channel data only after save succeeds to prevent data loss.
                    def _handle_lru_save_result(
                        t: asyncio.Task,
                        _cid: int = channel_id,
                        _mgr=self,
                        _ts: float | None = ts_at_schedule,
                    ) -> None:
                        if t.cancelled():
                            return
                        # save_history never raises — it catches internally and
                        # returns False — so checking t.exception() alone made
                        # this guard dead code and evicted channels whose save
                        # had actually failed. Check the bool result too.
                        exc = t.exception()
                        if exc or t.result() is not True:
                            logger.error(
                                "LRU save failed for channel %s, keeping in memory: %s",
                                _cid,
                                exc if exc else "save_history returned False",
                            )
                            return  # Don't delete if save failed — prevents data loss
                        # The channel may have been re-accessed between scheduling
                        # and now (get_chat_session updates last_accessed and may
                        # hold its processing_lock). Don't evict a freshly-reloaded
                        # session, and NEVER pop a HELD lock — orphaning it breaks
                        # per-channel mutual exclusion and lets two process_chat
                        # turns run concurrently. Mirrors cleanup_inactive_sessions.
                        if _mgr.last_accessed.get(_cid) != _ts:
                            return
                        lock = _mgr.processing_locks.get(_cid)
                        if lock is not None and lock.locked():
                            return
                        # Save succeeded and the channel is still idle — clean up.
                        _mgr.chats.pop(_cid, None)
                        _mgr.last_accessed.pop(_cid, None)
                        _mgr.seen_users.pop(_cid, None)
                        _mgr.processing_locks.pop(_cid, None)
                        _mgr.streaming_enabled.pop(_cid, None)
                        _mgr._message_queue.pending_messages.pop(_cid, None)
                        _mgr._message_queue.cancel_flags.pop(_cid, None)

                    task.add_done_callback(_handle_lru_save_result)
                    evicted += 1
                except RuntimeError:
                    logger.warning("No event loop for LRU eviction save of channel %s", channel_id)
                except Exception as e:
                    logger.warning(
                        "Failed to save history before LRU eviction for %s: %s", channel_id, e
                    )
            else:
                # No chat data, safe to clean up immediately
                self.last_accessed.pop(channel_id, None)
                self.seen_users.pop(channel_id, None)
                self.processing_locks.pop(channel_id, None)
                self.streaming_enabled.pop(channel_id, None)
                self._message_queue.pending_messages.pop(channel_id, None)
                self._message_queue.cancel_flags.pop(channel_id, None)
                evicted += 1

        if evicted > 0:
            logger.info("🧹 ChatManager LRU eviction: removed %d channels (history saved)", evicted)

        return evicted

    def setup_ai(self) -> None:
        """Initialize the Claude AI client."""
        # CLAUDE_BACKEND=cli: skip SDK init and route Discord-side AI to
        # the ``claude -p`` subprocess via ``discord_chat_claude_cli``.
        # The SDK client stays None; downstream code branches on
        # ``self.cli_mode`` to pick the right caller. Previously this
        # branch left Discord-side AI replies dead — only the dashboard
        # worked. Now the bot answers in Discord too, using the same
        # subscription quota as the dashboard CLI chat.
        if os.getenv("CLAUDE_BACKEND", "cli").strip().lower() == "cli":
            from .api.discord_chat_claude_cli import is_cli_backend_ready

            self.client = None
            self.target_model = CLAUDE_MODEL
            self.cli_mode = True
            ok, reason = is_cli_backend_ready()
            if ok:
                logger.info(
                    "🤖 Discord-side Claude CLI mode active (model: %s)",
                    self.target_model,
                )
            else:
                # Don't return early — the bot still starts; the user-
                # facing error fires only when a real message arrives,
                # so an admin can install ``claude`` without restarting.
                logger.warning(
                    "⚠️ Discord-side CLI mode requested but Claude CLI not ready: %s. "
                    "Messages will surface this error until ``claude`` is on PATH.",
                    reason,
                )
            return

        # Try failover manager first (supports proxy/direct switching)
        try:
            from .api.api_failover import api_failover

            if not api_failover._initialized:
                api_failover.initialize()
            if api_failover.active_config:
                self.client = api_failover.get_client()
                self.target_model = CLAUDE_MODEL
                logger.info(
                    "Claude AI Initialized via failover (Model: %s, Endpoint: %s)",
                    self.target_model,
                    api_failover.active_endpoint.value,
                )
                memory_consolidator.initialize(api_failover.active_config.api_key)
                return
        except Exception as e:
            logger.debug("Failover manager not available, using legacy init: %s", e)

        if not ANTHROPIC_API_KEY:
            logger.error(
                "ANTHROPIC_API_KEY not found in environment variables. AI features disabled."
            )
            return

        # Honor ANTHROPIC_BASE_URL on the legacy fallback path. Without
        # this, users with proxy-only keys would silently bypass their
        # proxy and hit the real Anthropic endpoint with the proxy key,
        # producing 401s or unintended billing.
        legacy_base_url = os.getenv("ANTHROPIC_BASE_URL", "").strip() or None

        try:
            client_kwargs: dict[str, Any] = {"api_key": ANTHROPIC_API_KEY}
            if legacy_base_url:
                client_kwargs["base_url"] = legacy_base_url
            self.client = anthropic.AsyncAnthropic(**client_kwargs)
            self.target_model = CLAUDE_MODEL
            logger.info(
                "Claude AI Initialized (Model: %s%s)",
                self.target_model,
                f", base_url={legacy_base_url}" if legacy_base_url else "",
            )

            # Initialize memory consolidator with same API key
            memory_consolidator.initialize(ANTHROPIC_API_KEY)
        except Exception:
            # Broad like the failover branch above and the consolidator's own
            # init: any SDK constructor error (e.g. an unexpected-kwarg TypeError)
            # must degrade to client=None, not propagate through setup_ai ->
            # __init__ and crash ChatManager construction.
            logger.exception("Claude Init Failed")
            self.client = None

    def get_performance_stats(self) -> dict[str, Any]:
        """Get performance statistics for AI processing steps.
        Delegates to PerformanceTracker module.
        """
        return self._performance.get_stats()

    def record_timing(self, step: str, duration: float) -> None:
        """Record timing for a processing step.
        Delegates to PerformanceTracker module.
        """
        self._performance.record_timing(step, duration)

    def cleanup_pending_requests(self, max_age: float = 60.0) -> int:
        """Clean up old pending requests to prevent memory leaks.
        Delegates to RequestDeduplicator module.

        Args:
            max_age: Maximum age in seconds before a request is considered stale

        Returns:
            Number of requests cleaned up
        """
        return self._deduplicator.cleanup(max_age)

    # ==================== Voice Channel Management ====================

    async def join_voice_channel(self, channel_id: int) -> tuple[bool, str]:
        """Join a voice channel by ID. Delegates to voice module."""
        return await voice_join(self.bot, channel_id)

    async def leave_voice_channel(self, guild_id: int) -> tuple[bool, str]:
        """Leave voice channel in a guild. Delegates to voice module."""
        return await voice_leave(self.bot, guild_id)

    def parse_voice_command(self, message: str) -> tuple[str | None, int | None]:
        """Parse voice channel commands from message. Delegates to voice module."""
        return voice_parse_command(message)

    # Session methods (get_chat_session, save_all_sessions, cleanup_inactive_sessions,
    # toggle_thinking, toggle_streaming, is_streaming_enabled) are inherited from SessionMixin

    @staticmethod
    def _pil_to_inline_data(img: Image.Image) -> InlineDataPart:
        """Convert PIL Image to base64 inline_data dict. Delegates to media_processor."""
        return pil_to_inline_data(img)

    async def _prepare_user_avatar(
        self,
        user: discord.User | discord.Member,
        message: str,
        chat_data: dict[str, Any],
        context_channel_id: int,
    ) -> Image.Image | None:
        """Prepare user avatar image if needed. Delegates to media_processor."""
        return await prepare_user_avatar(
            user, message, chat_data, context_channel_id, self.seen_users
        )

    async def _process_attachments(
        self, attachments: list[discord.Attachment] | None, user_name: str
    ) -> tuple[list[Image.Image], list[ProcessedVideoPart], list[str]]:
        """Process image and text attachments. Delegates to media_processor.

        Image work is skipped on a backend that can't carry inline images —
        see :meth:`accepts_inline_images`.
        """
        return await process_attachments(
            attachments, user_name, include_images=self.accepts_inline_images()
        )

    def accepts_inline_images(self) -> bool:
        """Whether the active backend can actually deliver an image to the model.

        False under ``CLAUDE_BACKEND=cli`` (the DEFAULT). That path flattens the
        turn into a single text prompt, and
        ``discord_chat_claude_cli._flatten_contents_to_prompt`` replaces every
        ``inline_data`` part with "[attachment omitted: …]" — so an image reaches
        the model as nothing at all.

        Everything upstream of that replacement was still being paid for on every
        turn: the user's avatar downloaded and PIL-decoded, custom emoji images
        fetched, a character reference image decoded (up to the 30MP cap), each
        attachment downloaded and decoded, an animated GIF ffmpeg-encoded to MP4,
        then all of it PNG-encoded and base64'd by ``pil_to_inline_data`` — for a
        prompt that keeps none of it.

        The waste was the smaller half of the problem. The TEXT labels that
        introduce those images ("[System Notice: The following image is …'s
        Discord profile picture]", "[Character Reference Image: …]",
        "[Custom Emoji: …]") are plain strings, so they survived the flattening
        and announced images that never arrived — the model was told to look at a
        profile picture that wasn't there. Callers gate both on this.
        """
        return not self.cli_mode

    def _is_animated_gif(self, image_data: bytes) -> bool:
        """Check if GIF data contains animation. Delegates to media_processor."""
        return is_animated_gif(image_data)

    def _convert_gif_to_video(self, gif_data: bytes) -> bytes | None:
        """Convert animated GIF to MP4 video. Delegates to media_processor."""
        return convert_gif_to_video(gif_data)

    def _load_character_image(
        self, message: str, guild_id: int | None
    ) -> tuple[str, Image.Image] | None:
        """Load character reference image. Delegates to media_processor."""
        return load_character_image(message, guild_id)

    # Response methods (_get_voice_status, _get_chat_history_index, _extract_channel_id_request,
    # _is_asking_about_channels, _get_requested_history) are inherited from ResponseMixin

    def _build_api_config(
        self,
        chat_data: dict[str, Any],
        guild_id: int | None = None,
    ) -> dict[str, Any]:
        """Build API configuration. Delegates to api_handler."""
        return build_api_config(chat_data, guild_id)

    async def _call_gemini_api_streaming(
        self,
        contents: list[dict[str, Any]],
        config_params: dict[str, Any],
        send_channel: Any,
        channel_id: int | None = None,
        user_id: int | None = None,
        guild_id: int | None = None,
    ) -> tuple[str, str, list[Any]]:
        """Call Claude API with streaming.

        Routes to the CLI subprocess when ``CLAUDE_BACKEND=cli`` (no SDK
        client available), or the SDK ``call_claude_api_streaming`` path
        otherwise. Both paths return the same ``(text, indicator, tool_calls)``
        triple so callers don't branch.
        """
        if self.cli_mode:
            from .api.discord_chat_claude_cli import call_claude_cli_streaming

            return await call_claude_cli_streaming(
                contents=contents,
                config_params=config_params,
                send_channel=send_channel,
                channel_id=channel_id,
                cancel_flags=self.cancel_flags,
                user_id=user_id,
                guild_id=guild_id,
            )
        if self.client is None or self.target_model is None:
            raise ValueError("Claude client not initialized")
        return await call_claude_api_streaming(
            client=self.client,
            target_model=self.target_model,
            contents=contents,
            config_params=config_params,
            send_channel=send_channel,
            channel_id=channel_id,
            cancel_flags=self.cancel_flags,
            fallback_func=self._call_gemini_api,
            user_id=user_id,
            guild_id=guild_id,
        )

    async def _call_gemini_api(
        self,
        contents: list[dict[str, Any]],
        config_params: dict[str, Any],
        channel_id: int | None = None,
        user_id: int | None = None,
        guild_id: int | None = None,
    ) -> tuple[str, str, list[Any]]:
        """Call Claude API with retry logic.

        Routes to the CLI subprocess in CLI mode (same contract as the
        streaming variant), or the SDK ``call_claude_api`` path
        otherwise.
        """
        if self.cli_mode:
            from .api.discord_chat_claude_cli import call_claude_cli

            return await call_claude_cli(
                contents=contents,
                config_params=config_params,
                channel_id=channel_id,
                cancel_flags=self.cancel_flags,
                user_id=user_id,
                guild_id=guild_id,
            )
        if self.client is None or self.target_model is None:
            raise ValueError("Claude client not initialized")
        return await call_claude_api(
            client=self.client,
            target_model=self.target_model,
            contents=contents,
            config_params=config_params,
            channel_id=channel_id,
            cancel_flags=self.cancel_flags,
            user_id=user_id,
            guild_id=guild_id,
        )

    def _process_response_text(
        self, response_text: str, guild_id: int | None, search_indicator: str
    ) -> str:
        """Process and clean up response text using precompiled patterns."""
        # Post-processing: Fix > before dialogue (using precompiled patterns)
        response_text = PATTERN_QUOTE.sub(r"\1", response_text)
        response_text = PATTERN_SPACED.sub(r"\1", response_text)

        # Fix AI comments about character tags - convert to actual tags
        response_text = self._fix_ai_character_tag_comments(response_text)

        # Convert standalone character names to {{Name}} tags
        response_text = replace_character_names(response_text, guild_id)

        # Prepend search indicator
        if search_indicator:
            response_text = search_indicator + response_text

        return response_text

    def _fix_ai_character_tag_comments(self, text: str) -> str:
        """Fix AI-generated comments about character tags by converting them to actual tags.

        Sometimes AI writes comments like "(ตรงนี้ควรใช้เป็น {{Han Seo-ah}}...)"
        instead of actually using the tag. This function detects these patterns
        and converts them into proper {{Name}} tags.

        Args:
            text: The response text to process

        Returns:
            Text with comment patterns converted to actual character tags
        """
        if not text:
            return text

        def replace_comment_with_tag(match: re.Match) -> str:
            """Replace the comment with an actual character tag."""
            # Try both capture groups (Thai and English patterns)
            char_name = match.group(1) or match.group(2)
            if char_name:
                logger.info("🔧 Converting AI comment to tag: %s", char_name)
                return f"\n\n{{{{{char_name}}}}}\n"
            return match.group(0)  # type: ignore[no-any-return]

        return PATTERN_AI_TAG_COMMENT.sub(replace_comment_with_tag, text)

    def _drop_cli_session_after_history_mutation(self, channel_id: int) -> None:
        """Invalidate the channel's Claude-CLI ``--resume`` session after an edit.

        The CLI backend is the DEFAULT, and a resumed turn sends only the new
        message — ``discord_chat_claude_cli`` passes
        ``include_history=session_id is None``, so on a live session the locally
        corrected history is never transmitted at all. Correcting our own copy
        therefore changes nothing the model sees: the server-side session still
        holds the pre-edit text and keeps answering from it for the rest of the
        conversation. Dropping the session forces the next turn to start fresh
        and resend the full, corrected history.

        Every other durable history mutation already does this — ``reset_ai``,
        channel delete, memory link/move, and the dashboard's own history editor
        (``dashboard_handlers._live_session_sync``, which spells out the same
        hazard). Discord-side delete/edit mirroring was the one path that did not.

        Best-effort by design: the DB mutation has already committed, so a
        failure here must never propagate to the caller. Gated on an actual hit
        by both callers so an unrelated message delete cannot drop a live session.
        """
        try:
            from .api.discord_chat_claude_cli import reset_channel_session

            reset_channel_session(channel_id)
        except Exception:
            logger.exception("Failed to reset Discord CLI session for channel %s", channel_id)

    async def remove_message_from_history(
        self, channel_id: int, message_id: int, deleted_content: str | None = None
    ) -> bool:
        """Drop a message from the channel's memory by its Discord ``message_id``.

        Called when a message is deleted in Discord so the bot's memory mirrors
        what's actually visible — a deleted message stops feeding future prompts
        ("like reading live"). Matches the user turn that stored this id, the
        bot's own reply if its id was recorded via ``update_message_id``, and
        every message of a turn that went out as several (``sent_message_ids``).

        A row is only DROPPED when the deleted message was the last one it still
        accounts for. When the row covers messages that are still on screen — a
        multi-character RP turn, a chunked long reply — it is kept and patched
        instead: the dead id leaves ``sent_message_ids`` (so the prompt stops
        offering an id that now 404s) and, when Discord gave us the deleted text
        via the raw event's cached message, that fragment is cut out too. With
        no cached text the line's wording stays in memory; MESSAGE_DELETE
        carries no content, and guessing which fragment to cut would risk
        destroying a line that is still visible.

        Both the in-memory session and the persisted rows are updated. The
        in-memory rebuild takes no ``await`` in the middle, so it is atomic
        against ``process_chat`` on the single event loop and never corrupts a
        history being rendered.

        On a hit the channel's Claude-CLI ``--resume`` session is dropped too —
        see :meth:`_drop_cli_session_after_history_mutation`, without which the
        "stops feeding future prompts" guarantee above is false on the default
        backend.

        Returns True if anything was removed or patched in memory or storage.
        """
        removed_in_memory = False
        patched_in_memory = False
        session = self.chats.get(channel_id)
        if session is not None:
            history = session.get("history") or []
            kept: list[Any] = []
            for item in history:
                if not _row_covers_message(item, message_id):
                    kept.append(item)
                    continue
                survivors = [e for e in _sent_message_entries(item) if e.get("id") != message_id]
                if not survivors:
                    # Nothing of this row is left in Discord — forget it whole.
                    removed_in_memory = True
                    continue
                item["sent_message_ids"] = survivors
                if item.get("message_id") == message_id:
                    # The row's headline id was the deleted one; re-point it at
                    # the last surviving message so edit/delete mirroring and
                    # the DB's single-id column keep working for this turn.
                    item["message_id"] = survivors[-1].get("id")
                if deleted_content:
                    item["parts"] = [
                        _remove_message_fragment(part, deleted_content)
                        if isinstance(part, str)
                        else (
                            {
                                **part,
                                "text": _remove_message_fragment(part["text"], deleted_content),
                            }
                            if isinstance(part, dict) and isinstance(part.get("text"), str)
                            else part
                        )
                        for part in item.get("parts", [])
                    ]
                patched_in_memory = True
                kept.append(item)
            if removed_in_memory or patched_in_memory:
                session["history"] = kept
                # Drop the length-keyed auto-compress cache (process_chat): a
                # delete followed by a later insert that nets to the same length
                # would otherwise leave the cache serving a stale compression that
                # still contains this deleted message — defeating the
                # delete-mirroring guarantee above. Mirrors edit_message_in_history
                # / remove_history_content. A patch keeps the length identical,
                # so it needs this just as much as a removal.
                session.pop("_compress_cache", None)

        deleted_rows = await delete_message_by_id(channel_id, message_id)
        if patched_in_memory and session is not None:
            # A patched row can't be addressed by the deleted id (that is the
            # whole point — the id is gone), so commit the in-memory view.
            await save_history(self.bot, channel_id, session, force=True)
        hit = removed_in_memory or patched_in_memory or deleted_rows > 0
        if hit:
            self._drop_cli_session_after_history_mutation(channel_id)
        return hit

    async def edit_message_in_history(
        self, channel_id: int, message_id: int, new_content: str
    ) -> bool:
        """Update a stored message's text by its Discord ``message_id``.

        Called when a message is edited in Discord so later turns see the new
        text rather than the original. Updates both the in-memory session and the
        persisted DB row.

        Returns True if anything was updated in memory or storage.
        """
        updated_in_memory = False
        session = self.chats.get(channel_id)
        if session is not None:
            for item in session.get("history") or []:
                if item.get("message_id") == message_id:
                    item["parts"] = [new_content]
                    updated_in_memory = True
            if updated_in_memory:
                # In-place edit keeps history length unchanged, so the
                # length-keyed auto-compress cache (process_chat) would still
                # serve the stale pre-edit compression. Drop it so the next
                # turn recomputes.
                session.pop("_compress_cache", None)

        updated_rows = await edit_message_by_id(channel_id, message_id, new_content)
        hit = updated_in_memory or updated_rows > 0
        if hit:
            self._drop_cli_session_after_history_mutation(channel_id)
        return hit

    async def replace_message_text_in_history(
        self, channel_id: int, message_id: int, old_content: str, new_content: str
    ) -> bool:
        """Mirror an edit the BOT performed on its own message into memory.

        ``on_raw_message_edit`` deliberately ignores edits authored by the bot
        (streaming works by re-editing the bot's own message), so an edit made
        through the ``edit_message`` tool would otherwise leave the ORIGINAL
        text in history — and the model would keep replaying the very wording
        it was just asked to remove.

        :meth:`edit_message_in_history` can't be reused here because it swaps a
        row's text WHOLESALE. That is right for one-message-per-row replies but
        destructive for a multi-character RP turn, which stores every
        ``{{Name}}`` block of the reply in ONE row while each block went out as
        its own webhook message. So this replaces the edited message's text as a
        FRAGMENT of whatever row contains it, keyed on the pre-edit content.

        Row preference: one carrying this ``message_id`` (the normal path
        stamps it), else the most recent model row containing the old text —
        intermediate webhook messages never had their id recorded, so the text
        is the only link back.

        Returns True if a row was patched.
        """
        if not old_content or old_content == new_content:
            return False
        session = self.chats.get(channel_id)
        if session is None:
            return False
        history = session.get("history") or []

        def _contains(item: Any) -> bool:
            return isinstance(item, dict) and old_content in _parts_to_text(item.get("parts", []))

        target = next(
            (item for item in history if _contains(item) and item.get("message_id") == message_id),
            None,
        )
        if target is None:
            # Reverse scan: the most recent occurrence is the edited one when
            # there is no id to key on (an identical line said twice in the
            # same channel would otherwise patch the older turn).
            target = next(
                (
                    item
                    for item in reversed(history)
                    if _contains(item) and item.get("role") == "model"
                ),
                None,
            )
        if target is None:
            return False

        patched_parts: list[Any] = []
        for part in target.get("parts", []):
            if isinstance(part, str) and old_content in part:
                patched_parts.append(part.replace(old_content, new_content))
            elif (
                isinstance(part, dict)
                and isinstance(part.get("text"), str)
                and old_content in part["text"]
            ):
                patched = dict(part)
                patched["text"] = part["text"].replace(old_content, new_content)
                patched_parts.append(patched)
            else:
                patched_parts.append(part)
        target["parts"] = patched_parts
        # Same reason as edit_message_in_history: an in-place edit leaves the
        # history LENGTH unchanged, so the length-keyed compress cache would
        # keep serving the pre-edit compression.
        session.pop("_compress_cache", None)

        row_id = target.get("message_id")
        if row_id is not None:
            # Targeted UPDATE — keeps ai_history row ids stable, so dashboard
            # undo entries captured earlier stay valid.
            await edit_message_by_id(channel_id, int(row_id), _parts_to_text(patched_parts))
        else:
            # No id on the row (an intermediate webhook message): nothing to key
            # a targeted UPDATE on, so commit the in-memory view wholesale.
            await save_history(self.bot, channel_id, session, force=True)
        self._drop_cli_session_after_history_mutation(channel_id)
        return True

    def patch_history_content(
        self, channel_id: int, *, row: dict[str, Any], new_content: str, occurrence: int = 0
    ) -> bool:
        """Patch one in-memory history item after an *external* DB edit.

        The dashboard's AI-history editor updates a row directly in SQLite
        (keyed by the ``ai_history`` primary key). If this channel's session is
        loaded, the stale in-memory copy would later clobber that edit: a
        force=True save delete-and-reinserts the in-memory list, and diff-mode
        saves match overlap by timestamp+role+SHA256(content) — the external
        edit breaks the hash and the stale tail gets re-appended over it. So
        the editor calls this to mirror the edit into memory.

        ``row`` is the DB row as it was *before* the edit (id, role, content,
        message_id, timestamp, ...). Matching strategy mirrors how the save
        paths identify rows: by ``message_id`` when the row has one, else by
        role + normalized timestamp + old-content equality (the same triple the
        diff-save overlap hash uses, so whatever this patches is exactly what
        the save would have hashed).

        ``occurrence`` disambiguates message_id-less "twins" (multiple items
        identical on all three fallback keys): it is the edited row's ordinal
        among its twins in DB id order, which equals memory order on load. The
        occurrence-th match gets patched; if fewer matches exist, the LAST one
        is patched — twin sets are content-identical, so a best-effort patch at
        the wrong slot only affects ordering, while no-patch would let the
        stale item clobber the DB edit on the next save.

        Purely in-memory and synchronous — atomic against ``process_chat`` on
        the single event loop. Returns True when an item was patched.
        """
        session = self.chats.get(channel_id)
        if session is None:
            return False
        history = session.get("history") or []
        index = _find_history_item_index(history, row, occurrence)
        if index is None:
            return False
        history[index]["parts"] = [new_content]
        # In-place edit keeps history length unchanged, so the length-keyed
        # auto-compress cache (process_chat) would still serve the stale
        # pre-edit compression. Drop it so the next turn recomputes.
        session.pop("_compress_cache", None)
        return True

    def remove_history_content(
        self, channel_id: int, *, row: dict[str, Any], occurrence: int = 0
    ) -> bool:
        """Remove one in-memory history item after an *external* DB delete.

        The dashboard's AI-history editor deletes a row directly in SQLite
        (keyed by the ``ai_history`` primary key). If this channel's session
        is loaded, the stale in-memory copy would later resurrect that row: a
        force=True save delete-and-reinserts the in-memory list, and
        diff-mode saves re-append the unmatched stale tail via the no-overlap
        fallback. So the editor calls this to mirror the delete into memory.

        ``row`` is the DB row as it was *before* the delete. Matching is the
        SAME logic ``patch_history_content`` uses (shared
        ``_find_history_item_index``): by ``message_id`` when the row has
        one, else role + normalized timestamp + content with the
        ``occurrence`` twin ordinal (clamped to the last match).

        Purely in-memory and synchronous — atomic against ``process_chat`` on
        the single event loop. Returns True when an item was removed.
        """
        session = self.chats.get(channel_id)
        if session is None:
            return False
        history = session.get("history") or []
        index = _find_history_item_index(history, row, occurrence)
        if index is None:
            return False
        del history[index]
        # A delete + later insert that nets to the same length would leave the
        # length-keyed auto-compress cache (process_chat) serving a stale
        # pre-edit compression. Drop it so the next turn recomputes — mirrors
        # the edit/patch paths.
        session.pop("_compress_cache", None)
        return True

    def insert_history_content(
        self,
        channel_id: int,
        *,
        row: dict[str, Any],
        prev_row: dict[str, Any] | None,
        next_row: dict[str, Any] | None,
        prev_occurrence: int = 0,
        next_occurrence: int = 0,
        expected_twins: int = 1,
    ) -> bool:
        """Re-insert one in-memory history item after an *external* DB restore.

        The dashboard's undo re-inserts a deleted ``ai_history`` row directly
        in SQLite (with its original primary-key id). If this channel's
        session is loaded, the in-memory copy must mirror the restore or the
        next save destroys it: a force=True save delete-and-reinserts the
        in-memory list (without the restored row), and diff-mode saves treat
        the DB-only row as not-in-memory.

        ``row`` is the restored row; ``prev_row`` / ``next_row`` are its DB
        neighbors by id (either may be None at the history's edge).
        ``prev_occurrence`` / ``next_occurrence`` are each anchor's twin
        ordinal among message_id-less rows identical on (role, timestamp,
        content) — the same ordinal machinery the edit/delete paths use — so
        the insert anchors on the actual DB neighbor instead of its earliest
        twin. ``expected_twins`` is the DB's post-restore count of the
        restored row's own mid-less twins. The item is built EXACTLY like
        ``storage.load_history``'s row→item conversion: role +
        parts=[content], with timestamp/message_id/user_id carried only when
        non-NULL.

        Insertion anchors via the shared ``_find_history_item_index``:
        - the row already in memory → True without inserting (idempotent
          retry, or the delete's memory removal had missed and the item never
          left — inserting again would duplicate it). For message_id rows
          this is plain existence; for mid-less rows mere existence cannot
          distinguish "the restored row is back" from "a surviving identical
          twin is here", so the skip compares the in-memory twin count
          against ``expected_twins`` and only skips when memory already holds
          as many twins as the DB does;
        - both neighbors None AND memory empty → seed at index 0 (the
          restored row is the channel's only DB row, so no wrong order is
          possible — and it re-seeds the anchor chain for multi-row undo
          sequences);
        - ``next_row`` matches an item (at ``next_occurrence``) → insert
          BEFORE it;
        - else ``prev_row`` matches (at ``prev_occurrence``) → insert AFTER
          it;
        - else False. Never append blindly: a force-save would persist a
          wrong order — the DB is already correct, so the caller reports
          ``no_match`` instead.

        Purely in-memory and synchronous — atomic against ``process_chat`` on
        the single event loop. Returns True when memory reflects the restore.
        """
        session = self.chats.get(channel_id)
        if session is None:
            return False
        history = session.get("history") or []

        if row.get("message_id") is not None:
            if _find_history_item_index(history, row) is not None:
                return True
        elif _count_history_item_matches(history, row) >= max(expected_twins, 1):
            # Memory already holds as many mid-less twins as the DB does
            # post-restore — the restored row's own item never left (or an
            # idempotent retry already inserted it). Fewer twins than the DB
            # means only siblings survive and the insert below is needed.
            return True

        item: dict[str, Any] = {
            "role": row.get("role", "user"),
            "parts": [row.get("content", "")],
        }
        # Carry forward bookkeeping fields if present so the round trip is
        # lossless (same key-omission rule as load_history's conversion).
        for k in ("timestamp", "message_id", "user_id"):
            if row.get(k) is not None:
                item[k] = row[k]

        if prev_row is None and next_row is None and not history:
            # The restored row is the channel's only DB row and the loaded
            # session is empty: index 0 cannot produce a wrong order, and it
            # re-seeds the anchor chain so multi-row undo sequences patch
            # memory instead of cascading no_match warnings. Assign back —
            # ``history`` may be the ``or []`` fallback list, so inserting
            # into it would be lost.
            session["history"] = [item]
            # A net-zero length change (this insert paired with a delete) would
            # leave the length-keyed auto-compress cache (process_chat) serving
            # a stale pre-edit compression. Drop it on every successful insert
            # so the next turn recomputes — mirrors the edit/patch paths.
            session.pop("_compress_cache", None)
            return True

        if next_row is not None:
            index = _find_history_item_index(history, next_row, next_occurrence)
            if index is not None:
                history.insert(index, item)
                session.pop("_compress_cache", None)
                return True
        if prev_row is not None:
            index = _find_history_item_index(history, prev_row, prev_occurrence)
            if index is not None:
                history.insert(index + 1, item)
                session.pop("_compress_cache", None)
                return True
        return False

    async def _process_pending_messages(self, channel_id: int) -> None:
        """Process any pending messages for a channel.
        Uses MessageQueue module for message merging.

        Convert the previous recursion (``process_chat`` → finally →
        ``_process_pending_messages`` → ``process_chat`` → ...) into a
        bounded while-loop. The recursion depth was bounded in practice
        by the user's send rate, but a perfectly-timed message burst
        could push it deep enough to hit Python's default recursion
        limit on the AI turn's already-deep call stack. The loop runs
        until the pending queue is empty for this channel.
        """
        if channel_id in self._draining:
            # Re-entered from a nested process_chat's finally: the outer drain
            # loop below is already consuming this channel's queue. Returning
            # here is what actually breaks the old recursion chain
            # (process_chat → finally → _ppm → process_chat → finally → ...);
            # without this guard the while-loop conversion was ineffective and
            # stack depth still grew with every mid-turn message burst.
            return
        self._draining.add(channel_id)
        try:
            await self._drain_pending_loop(channel_id)
        finally:
            self._draining.discard(channel_id)

    async def _drain_pending_loop(self, channel_id: int) -> None:
        """Iteratively consume the channel's pending queue (see caller)."""
        # Hard cap on iterations as a defence against a hypothetical bug
        # where ``merge_pending_messages`` returns the same message
        # forever — without it, an infinite loop would hold the bot
        # locked on this channel.
        max_iterations = 16
        iteration = 0
        while iteration < max_iterations:
            iteration += 1
            if not self._message_queue.has_pending(channel_id):
                return

            # Merge pending messages using MessageQueue
            latest_msg, combined_message = self._message_queue.merge_pending_messages(channel_id)

            if not latest_msg:
                return

            # Process the combined message. ``process_chat``'s ``finally``
            # block USED to recurse here; it now no-ops because
            # ``_process_pending_messages`` itself loops, so we keep
            # going only when new messages arrive between the
            # process_chat awaits.
            await self.process_chat(
                channel=latest_msg.channel,
                user=latest_msg.user,
                message=combined_message,
                attachments=latest_msg.attachments,
                output_channel=latest_msg.output_channel,
                generate_response=latest_msg.generate_response,
                user_message_id=latest_msg.user_message_id,
            )
        # Guarded against a runaway merge bug — only reached when the
        # loop counter runs out without ``has_pending`` ever returning
        # False, i.e. ``merge_pending_messages`` consumed but
        # repopulated the queue 16× in a row.
        logger.warning(
            "_process_pending_messages exceeded %d iterations for channel %s; "
            "bailing to avoid lock starvation",
            max_iterations,
            channel_id,
        )

    async def _maybe_track_feedback(
        self, sent_message: discord.Message | None, channel_id: int, response_text: str
    ) -> None:
        """Register an AI reply for feedback + add the reaction palette.

        Gated behind the opt-in FEEDBACK_COLLECTION_ENABLED env flag (default
        off → today's behavior is byte-for-byte unchanged). The flag is read at
        call time so it stays runtime-/test-togglable. add_feedback_reactions
        already self-suppresses discord.HTTPException, so no extra guard is
        needed here — let any other exception surface to process_chat's handlers.
        """
        if sent_message is None or not FEEDBACK_AVAILABLE or feedback_collector is None:
            return
        if os.getenv("FEEDBACK_COLLECTION_ENABLED", "").strip().lower() not in (
            "1",
            "true",
            "yes",
            "on",
        ):
            return
        feedback_collector.track_message(sent_message.id, channel_id, response_text)
        await add_feedback_reactions(sent_message)

    async def process_chat(
        self,
        channel: discord.TextChannel | discord.Thread | discord.DMChannel,
        user: discord.User | discord.Member,
        message: str,
        attachments: list[discord.Attachment] | None = None,
        output_channel: discord.TextChannel | discord.Thread | discord.DMChannel | None = None,
        generate_response: bool = True,
        user_message_id: int | None = None,
    ) -> None:
        """Process chat message and generate AI response."""
        # In CLI mode the SDK client stays None but the CLI subprocess
        # path can still answer. Allow either route through this gate;
        # the actual choice happens in ``_call_gemini_api_streaming`` /
        # ``_call_gemini_api`` below.
        if not self.client and not self.cli_mode:
            return  # AI not initialized

        # Input length validation - prevent extremely large messages
        MAX_MESSAGE_LENGTH = 100_000  # 100KB max
        if message and len(message) > MAX_MESSAGE_LENGTH:
            original_length = len(message)
            message = message[:MAX_MESSAGE_LENGTH] + "\n[... ข้อความถูกตัดเนื่องจากยาวเกินไป ...]"
            logger.warning(
                "Truncated oversized message from user %s (%d chars)", user.id, original_length
            )

        # Determine Context and Send channels
        context_channel = output_channel if output_channel else channel
        send_channel = output_channel if output_channel else channel
        channel_id = context_channel.id

        # (Input guardrails removed: the guardrails module was deleted, so the
        # old INPUT_GUARDRAILS/INPUT_GUARDRAILS_ENFORCE opt-in here only called a
        # no-op shim — it sanitized nothing and never enforced. The dead control
        # was removed so it can't imply a protection that no longer exists.)

        # Request deduplication - prevent double processing of same message.
        # Include attachment identity in the key material: attachment-only
        # messages otherwise all collapse to the same ":empty" key, so a
        # SECOND image-only message sent while the first is still processing
        # was classified as a duplicate and silently dropped instead of being
        # queued/merged by MessageQueue.
        dedup_material = message or ""
        if attachments:
            dedup_material += "|att:" + ",".join(str(a.id) for a in attachments)
        request_key = self._deduplicator.generate_key(channel_id, user.id, dedup_material)
        if self._deduplicator.check_and_add(request_key):
            logger.debug("🔄 Duplicate request blocked: %s", request_key[:30])
            return

        # Graceful degradation - check circuit breaker before processing
        if CIRCUIT_BREAKER_AVAILABLE and gemini_circuit and not gemini_circuit.can_execute():
            # Remove the dedup key FIRST and suppress send failures: this early-out
            # is OUTSIDE the function's try/finally, so a raising send() would leave
            # request_key stranded (blocking the user from re-sending for ~60s).
            self._deduplicator.remove_request(request_key)
            with contextlib.suppress(discord.HTTPException):
                await send_channel.send(
                    "⏳ ระบบ AI กำลังพักผ่อนสักครู่ กรุณาลองใหม่อีกครั้งในอีก 1 นาที", delete_after=30
                )
            return

        # Create lock for this channel if not exists. We deliberately do NOT
        # use ``setdefault(channel_id, asyncio.Lock())`` here because
        # ``setdefault``'s second argument is always evaluated — every call
        # allocates a fresh ``asyncio.Lock`` even when the existing one is
        # returned, which produces meaningful garbage churn on busy
        # channels. The check-then-set pattern is safe in single-threaded
        # asyncio (no ``await`` between the read and the write).
        lock = self.processing_locks.get(channel_id)
        if lock is None:
            lock = asyncio.Lock()
            self.processing_locks[channel_id] = lock

        # If already processing, queue this message and signal cancellation
        if lock.locked():
            # Add to pending queue using MessageQueue
            self._message_queue.queue_message(
                channel_id=channel_id,
                channel=channel,
                user=user,
                message=message,
                attachments=attachments,
                output_channel=output_channel,
                generate_response=generate_response,
                user_message_id=user_message_id,
            )
            # Signal to cancel current processing
            self._message_queue.signal_cancel(channel_id)
            logger.info("📝 Queued new message, signaling cancel for channel %s", channel_id)
            self._deduplicator.remove_request(request_key)
            return

        # Acquire lock with timeout using a safe pattern that avoids the known
        # asyncio.wait_for(lock.acquire()) deadlock (CPython issue #42130).
        # We shield the acquire task so wait_for's cancellation doesn't corrupt
        # the lock state, then attach a done_callback to release the lock if
        # the shielded task completes after we've already timed out.
        lock_acquired = False
        try:
            # Safe lock acquisition with timeout.
            # Uses asyncio.wait_for directly — the CPython #42130 fix landed
            # in Python 3.12+ (we require 3.14+), so the shield workaround
            # is no longer needed and avoids the double-release race.
            await asyncio.wait_for(lock.acquire(), timeout=LOCK_TIMEOUT)
            lock_acquired = True
        except asyncio.CancelledError:
            # Cancelled while waiting for the lock (shutdown / cog reload):
            # drop the dedup key so the identical message isn't silently
            # suppressed for the next 60s if it's retried after restart.
            self._deduplicator.remove_request(request_key)
            raise
        except TimeoutError:
            logger.error(
                "⚠️ Lock acquisition timeout for channel %s (>%ss)", channel_id, LOCK_TIMEOUT
            )
            self._deduplicator.remove_request(request_key)
            # Suppress send failures — a raising send here would escape
            # process_chat entirely (same rationale as the circuit-breaker
            # early-out above).
            with contextlib.suppress(discord.HTTPException):
                await send_channel.send(
                    "⏳ ระบบกำลังประมวลผลอยู่ กรุณารอสักครู่แล้วลองใหม่", delete_after=15
                )
            return

        try:  # Manual lock management with timeout protection
            # Track lock acquisition time for timeout detection
            self._message_queue._lock_times[channel_id] = time.time()
            self._message_queue.reset_cancel(channel_id)
            typing_context = (
                _typing_or_noop(send_channel) if generate_response else contextlib.nullcontext()
            )

            # Initialize variables BEFORE async with to prevent NameError in finally block
            content_parts: list[Any] = []
            image_parts: list[Image.Image] = []

            async with typing_context:
                try:
                    # Get guild_id if available
                    guild_id = None
                    if hasattr(context_channel, "guild") and context_channel.guild:
                        guild_id = context_channel.guild.id

                    chat_data = await self.get_chat_session(context_channel.id, guild_id)
                    if not chat_data:
                        logger.error("Could not create chat session.")
                        self._deduplicator.remove_request(request_key)
                        return

                    # Strip newlines so a crafted display name can't forge a
                    # line-based prompt-structure boundary (e.g. an injected
                    # "---END SYSTEM CONTEXT---" line) in the flattened prompt.
                    user_name = user.display_name.replace("\n", " ").replace("\r", " ")
                    # Get real-time in Bangkok timezone (ICT)
                    now_bangkok = datetime.datetime.now(BANGKOK_TZ)
                    now = now_bangkok.strftime("%A, %d %B %Y %H:%M:%S (ICT)")

                    # Trace anchors for the owner's !ai_trace panel — written
                    # into chat_data["last_trace"] right after the API call.
                    _trace_turn_start = time.time()
                    _trace_rag_ms = 0.0
                    _trace_rag_results = 0
                    # The panel renders a "🎯 Intent" field but nothing ever
                    # produced this key, so it read "N/A" on every request.
                    # Classified below from the RAW user text (once real text
                    # exists) — never from ``prompt_with_context``, which is the
                    # system-header + memory wrapper and would classify the
                    # scaffolding instead of what the user actually said.
                    _trace_intent = "n/a"

                    # Resolved once: every image branch below is gated on it, so
                    # a backend that drops inline images neither pays for the
                    # pixels nor emits a text label announcing them. See
                    # ``accepts_inline_images``.
                    accepts_images = self.accepts_inline_images()

                    # 1. Prepare user avatar using helper method
                    avatar_image = (
                        await self._prepare_user_avatar(
                            user, message, chat_data, context_channel.id
                        )
                        if accepts_images
                        else None
                    )
                    if avatar_image:
                        content_parts.append(
                            f"[System Notice: The following image is {user_name}'s "
                            f"Discord profile picture. This was automatically fetched "
                            f"by the system for user identification purposes. "
                            f"The user did NOT send this image - do NOT comment on or "
                            f"ask about it unless they mention their appearance.]"
                        )
                        content_parts.append(avatar_image)

                    # 2. Add text prompt with context
                    is_creator = user.id == CREATOR_ID
                    creator_tag = " | Creator: Yes" if is_creator else ""

                    # Handle empty messages
                    has_attachments = attachments and len(attachments) > 0
                    if not message or not message.strip():
                        if has_attachments:
                            # User sent only image(s)
                            display_message = "[User sent image(s) without text]"
                        else:
                            # User sent empty message - wants AI to continue
                            display_message = "[User wants to continue the conversation]"
                    else:
                        display_message = message

                    # Extract and fetch Discord custom emoji images. The textual
                    # ``<:name:id>`` → ``[:name:]`` rewrite below runs on every
                    # backend; only the IMAGE fetch is gated, since the picture
                    # would be dropped by the flattener anyway.
                    emoji_list = extract_discord_emojis(message or "") if accepts_images else []
                    if emoji_list:
                        try:
                            emoji_images = await fetch_emoji_images(emoji_list)
                            for emoji_name, emoji_img in emoji_images:
                                content_parts.append(f"[Custom Emoji: {emoji_name}]")
                                content_parts.append(emoji_img)
                        except (TimeoutError, aiohttp.ClientError, OSError) as e:
                            logger.debug("Failed to fetch emoji images: %s", e)

                    # Convert Discord custom emojis to readable format in text
                    # <:smile:123456789> -> [:smile:]
                    display_message = convert_discord_emojis(display_message)

                    # --- URL Content Fetching ---
                    url_context = ""
                    if URL_FETCHER_AVAILABLE:
                        try:
                            urls = extract_urls(message or "")
                            if urls:
                                logger.info(
                                    "🔗 Found %d URL(s) in message, fetching content...", len(urls)
                                )
                                # No max_urls here: url_fetcher owns the
                                # policy (MAX_URLS_PER_MESSAGE, env-tunable via
                                # URL_FETCH_MAX_URLS). The old hard-coded 2 sat
                                # below even that module's own default.
                                fetched = await fetch_all_urls(urls)
                                url_context = format_url_content_for_context(fetched)
                                if url_context:
                                    logger.info("🔗 Fetched content from %d URL(s)", len(fetched))
                        except (TimeoutError, aiohttp.ClientError, ValueError, OSError) as e:
                            logger.debug("URL fetching failed: %s", e)

                    # When the user sent no real text (attachment-only or
                    # continue-the-conversation), display_message is a synthetic
                    # placeholder like "[User sent image(s) without text]". Running
                    # semantic/prefix memory search on that placeholder retrieves
                    # noise matching the placeholder words and wastes an embedding
                    # round-trip, so skip RAG + entity search unless real text exists.
                    has_user_text = bool(message and message.strip())

                    # Classify intent for the !ai_trace panel. Pure compiled-regex
                    # work on the user's own text — no I/O, no model call — and
                    # skipped entirely for attachment-only / continue turns, whose
                    # synthetic placeholder carries no intent to read. Wrapped so a
                    # diagnostic field can never abort a real turn; a missing
                    # optional module leaves the "n/a" default in place.
                    if has_user_text:
                        try:
                            from .processing.intent_detector import detect_intent

                            _trace_intent = detect_intent(message).intent.value
                        except Exception:
                            logger.debug("Intent classification skipped", exc_info=True)

                    # --- RAG: Retrieve Relevant Memories ---
                    rag_context = ""

                    if has_user_text:
                        try:
                            # Scope retrieval to THIS channel. ``remember`` writes
                            # are already channel-tagged (tool_executor passes
                            # ``channel_id=origin_channel.id`` to add_memory), but
                            # this read omitted the filter, and ``channel_id=None``
                            # means "search every channel" all the way down to
                            # ``get_all_rag_memories`` — so a fact stored in one
                            # guild's channel surfaced in another guild's prompt.
                            # Passing it makes read scope match write scope; the
                            # rows are untouched, only retrieval narrows.
                            _rag_start = time.time()
                            memories = await rag_system.search_memory(
                                display_message, limit=RAG_TOP_K, channel_id=channel_id
                            )
                            self.record_timing("rag_search", time.time() - _rag_start)
                            _trace_rag_ms = (time.time() - _rag_start) * 1000
                            _trace_rag_results = len(memories) if memories else 0
                            if memories:
                                rag_context = "\n\n[Long-term Memory]\n" + "\n".join(
                                    f"- {m}" for m in memories
                                )
                        except Exception:
                            # RAG is a non-critical enhancement: a backend
                            # failure (FAISS RuntimeError, numpy ValueError, DB
                            # OSError, …) must degrade to "no memory", never
                            # abort the whole turn via the outer broad handler.
                            logger.exception("RAG search failed")

                    # --- Entity Memory: Retrieve verified character/location facts ---
                    entity_context = ""
                    if has_user_text:
                        try:
                            # Extract entity names from message (look for {{Name}} patterns)
                            entity_names = re.findall(r"\{\{([^}]+)\}\}", display_message)
                            # Also search for known character names in the message.
                            if not entity_names:
                                # Find stored entities whose NAME appears in the
                                # message. search_entities does the opposite —
                                # it matches rows whose name/facts CONTAIN the
                                # query as a substring, so passing the whole
                                # message inverted the direction and never
                                # matched a normal multi-word message. Instead
                                # pull the channel's known entities (most-used
                                # first) and keep those actually mentioned.
                                lowered_message = display_message.lower()
                                known_entities = await entity_memory.get_all_entities(
                                    channel_id=channel_id,
                                    guild_id=guild_id,
                                )
                                entity_names = [
                                    e.name
                                    for e in known_entities
                                    if e.name and e.name.lower() in lowered_message
                                ][:ENTITY_TOP_K]

                            if entity_names:
                                entity_context = await entity_memory.get_entities_for_prompt(
                                    entity_names, channel_id=channel_id, guild_id=guild_id
                                )
                        except (KeyError, ValueError, TypeError, AttributeError) as e:
                            logger.debug("Entity memory lookup failed: %s", e)

                    # --- State Tracker: Get current character states (RP only) ---
                    state_context = ""
                    if guild_id == GUILD_ID_RP:
                        try:
                            state_context = state_tracker.get_states_for_prompt(channel_id)
                        except (KeyError, ValueError, TypeError) as e:
                            logger.debug("State tracker failed: %s", e)

                    # Combine all memory contexts
                    memory_context = ""
                    if entity_context:
                        memory_context += f"\n{entity_context}"
                    if state_context:
                        memory_context += f"\n{state_context}"
                    if url_context:
                        memory_context += f"\n{url_context}"
                    if rag_context:
                        memory_context += rag_context

                    # Build prompt with context
                    # For DM (guild_id is None), add voice status and chat history
                    # access — but ONLY for the creator. This enrichment exposes
                    # cross-guild metadata (every guild/channel name + id + message
                    # counts via the history index, and live voice occupancy across
                    # all guilds via voice status). A non-owner can reach process_chat
                    # in a DM through the ungated !chat / !ask command path, so gate
                    # the whole block on is_creator; everyone else gets a plain reply
                    # with no cross-guild disclosure.
                    if guild_id is None and is_creator:
                        voice_status = self._get_voice_status()

                        # Check if user is requesting specific channel history
                        requested_channel = self._extract_channel_id_request(display_message)
                        if requested_channel:
                            history_data = await self._get_requested_history(
                                requested_channel, requester_id=user.id
                            )
                            prompt_with_context = (
                                f"[System Info] Current Time: {now} | "
                                f"User: {user_name}{creator_tag}\n"
                                f"[Voice Status] {voice_status}\n"
                                f"[Requested Chat History]\n{history_data}\n"
                                f"{memory_context}\n"
                                f"---END SYSTEM CONTEXT---\n"
                                f"User Message: {display_message}"
                            )
                        elif self._is_asking_about_channels(display_message):
                            # Only show channel list if user is asking about it
                            history_index = await self._get_chat_history_index()
                            prompt_with_context = (
                                f"[System Info] Current Time: {now} | "
                                f"User: {user_name}{creator_tag}\n"
                                f"[Voice Status] {voice_status}\n"
                                f"[Chat History Access]\n{history_index}\n"
                                f"{memory_context}\n"
                                f"---END SYSTEM CONTEXT---\n"
                                f"User Message: {display_message}"
                            )
                        else:
                            # Normal DM chat - just voice status
                            prompt_with_context = (
                                f"[System Info] Current Time: {now} | "
                                f"User: {user_name}{creator_tag}\n"
                                f"[Voice Status] {voice_status}\n"
                                f"{memory_context}\n"
                                f"---END SYSTEM CONTEXT---\n"
                                f"User Message: {display_message}"
                            )
                    else:
                        prompt_with_context = (
                            f"[System Info] Current Time: {now} | "
                            f"User: {user_name}{creator_tag}\n"
                            f"{memory_context}\n"
                            f"---END SYSTEM CONTEXT---\n"
                            f"User Message: {display_message}"
                        )
                    content_parts.append(prompt_with_context)

                    # 3. Load character reference image if mentioned.
                    # Offload to a worker thread: load_character_image runs
                    # Image.open + .copy(), and .copy() forces a FULL pixel
                    # decode (only the raw file bytes are cached, so the
                    # decode repeats on every matching turn — up to the 30MP
                    # cap that's tens-to-hundreds of ms). Running it inline
                    # stalled the event loop for ALL guilds; process_attachments
                    # already offloads the identical operation for the same
                    # reason.
                    # Gated on the backend carrying images: the decode is the
                    # single most expensive image op here, and its
                    # "[Character Reference Image: …]" label would otherwise
                    # introduce a picture the prompt never delivers.
                    char_result = (
                        await asyncio.to_thread(self._load_character_image, message, guild_id)
                        if accepts_images
                        else None
                    )
                    if char_result:
                        char_name, char_image = char_result
                        content_parts.append(f"[Character Reference Image: {char_name}]")
                        content_parts.append(char_image)

                    # 4. Process attachments using helper method (images, videos, text files)
                    image_parts, video_parts, text_parts = await self._process_attachments(
                        attachments, user_name
                    )

                    # 5. Build current user message parts
                    current_parts: list[
                        dict[str, Any] | ClaudeContentBlockParam | InlineDataPart
                    ] = []
                    for part in content_parts:
                        if isinstance(part, str):
                            current_parts.append({"text": part})
                        elif isinstance(part, Image.Image):
                            try:
                                current_parts.append(self._pil_to_inline_data(part))
                            except Exception as conv_exc:
                                # One unconvertible image shouldn't nuke the whole
                                # turn (and silently drop the other parts) — log
                                # and skip it, keeping the rest of the message.
                                logger.warning(
                                    "Skipping unconvertible character-reference image: %s",
                                    conv_exc,
                                )
                            finally:
                                part.close()

                    for img in image_parts:
                        try:
                            current_parts.append(self._pil_to_inline_data(img))
                        except Exception as conv_exc:
                            # Skip a single bad attachment image instead of
                            # failing the whole turn and dropping the others.
                            logger.warning("Skipping unconvertible attachment image: %s", conv_exc)
                        finally:
                            img.close()

                    # Add text file contents
                    for text_content in text_parts:
                        current_parts.append({"text": text_content})

                    # Add video parts from animated GIFs
                    for video in video_parts:
                        current_parts.append(
                            {
                                "inline_data": {
                                    "mime_type": video["mime_type"],
                                    "data": base64.b64encode(video["data"]).decode("utf-8"),
                                }
                            }
                        )

                    # 6. Build contents with history (limit to recent messages for better context)
                    history = chat_data.get("history", [])

                    # Limit history — Claude Opus 5 has a 1M token context window.
                    # Using maximum context for all contexts (RP, DM, normal servers)
                    # to preserve AI personality and conversation continuity.
                    # Note: MAX_HISTORY_ITEMS constant defined in data/constants.py.

                    # Auto-compress very long histories using summarizer
                    # COMPRESS_THRESHOLD should be slightly higher than MAX_HISTORY_ITEMS
                    compress_threshold = MAX_HISTORY_ITEMS + 500  # Compress when exceeded
                    # Gate on the summarizer being operational (mirrors the
                    # ``memory_consolidator.enabled`` gate below). Under
                    # CLAUDE_BACKEND=cli (the default) the summarizer's SDK
                    # client is None, so compress_history() returns the history
                    # unchanged after an awaited round trip — recomputed on every
                    # message once the threshold is crossed. Skipping it when the
                    # client is absent avoids that per-turn wasted work; the
                    # MAX_HISTORY_ITEMS trim below still bounds the prompt size.
                    # Avoid recomputing the (prompt-only) compression on every
                    # message once the threshold is crossed: the source history
                    # is unchanged unless its length moved, so the summarizer
                    # would return the same result. Cache the last compressed
                    # length keyed on the source length; recompute only when the
                    # source length differs. Prompt-only semantics are preserved
                    # (compressed is never written back to chat_data["history"]).
                    if summarizer.client is not None and len(history) > compress_threshold:
                        _cur_len = len(history)
                        _cache = chat_data.get("_compress_cache")
                        if not (isinstance(_cache, dict) and _cache.get("src_len") == _cur_len):
                            try:
                                compressed = await asyncio.wait_for(
                                    summarizer.compress_history(
                                        history,
                                        keep_recent=200,  # Keep 200 most recent messages intact (less lossy)
                                    ),
                                    timeout=60,  # 60s timeout to prevent indefinite blocking
                                )
                                if len(compressed) < len(history):
                                    history = compressed
                                    logger.info(
                                        "📦 Auto-compressed history: %d → %d messages",
                                        len(chat_data.get("history", [])),
                                        len(compressed),
                                    )
                                chat_data["_compress_cache"] = {
                                    "src_len": _cur_len,
                                    "history": history,
                                }
                            except (TimeoutError, ValueError, TypeError, KeyError) as e:
                                logger.warning("Auto-summarize failed: %s", e)
                        else:
                            # Reuse the previously computed compression for this
                            # unchanged source length (prompt-only, not persisted).
                            history = _cache["history"]

                    # Use only recent history if too long (constant in data/constants.py)
                    if len(history) > MAX_HISTORY_ITEMS:
                        pre_trim_len = len(history)
                        history = history[-MAX_HISTORY_ITEMS:]
                        logger.info(
                            "📚 Trimmed history from %d to %d messages for API call",
                            pre_trim_len,
                            MAX_HISTORY_ITEMS,
                        )

                    contents = []

                    # Helper: normalize any stored timestamp to Bangkok ISO at
                    # render time. Timestamps are STORED as UTC (_utc_now_iso);
                    # Bangkok is applied only when formatting, matching the
                    # Bangkok "Current Time" header embedded in the live prompt.
                    from .api.dashboard_common import normalize_timestamp_to_bangkok as _norm_ts

                    for item in history:
                        role = item.get("role", "user")
                        parts_data = item.get("parts", [])
                        converted_parts = []
                        # Prefix-once: attach the stored send timestamp to the
                        # first text part so the model can see when each
                        # historical message was sent, plus — for the bot's own
                        # turns — the Discord message id(s) that turn was sent
                        # as, which is what makes ``edit_message`` usable on an
                        # earlier reply without a read_channel lookup first.
                        meta_prefix = ""
                        ts_raw = item.get("timestamp")
                        if ts_raw:
                            meta_prefix = f"[{_norm_ts(ts_raw)}] "
                        if role == "model":
                            meta_prefix += _format_message_id_prefix(item)
                        prefix_applied = False
                        had_image_only = False
                        for p in parts_data:
                            if isinstance(p, str):
                                clean_text = PATTERN_ID.sub("", p)
                                if meta_prefix and not prefix_applied:
                                    clean_text = meta_prefix + clean_text
                                    prefix_applied = True
                                if clean_text.strip():
                                    converted_parts.append({"text": clean_text})
                            elif isinstance(p, dict) and "text" in p:
                                clean_text = PATTERN_ID.sub("", p["text"])
                                if meta_prefix and not prefix_applied:
                                    clean_text = meta_prefix + clean_text
                                    prefix_applied = True
                                if clean_text.strip():
                                    converted_parts.append({"text": clean_text})
                            elif isinstance(p, dict) and (
                                "image_url" in p or "inline_data" in p or "source" in p
                            ):
                                # Image-only parts: track that this message had
                                # image content so we can emit a placeholder
                                # text and preserve role alternation. Dropping
                                # these silently could collapse two consecutive
                                # same-role turns into one.
                                had_image_only = True
                        if not converted_parts and had_image_only:
                            placeholder = "[image]"
                            if meta_prefix:
                                placeholder = meta_prefix + placeholder
                            converted_parts.append({"text": placeholder})
                        if converted_parts:
                            contents.append({"role": role, "parts": converted_parts})

                    contents.append({"role": "user", "parts": current_parts})

                    # 7. Handle memory-only mode (no response generation)
                    if not generate_response:
                        user_msg_text = prompt_with_context
                        if image_parts:
                            user_msg_text += " [Image/Attachment]"
                        # Include text file contents in saved history
                        if text_parts:
                            user_msg_text += "\n\n" + "\n".join(text_parts)
                        current_time = _utc_now_iso()

                        new_item = {
                            "role": "user",
                            "parts": [user_msg_text],
                            "timestamp": current_time,
                            # message_id keeps Discord delete/edit sync working
                            # for rows saved on this path (same as the normal
                            # save path below).
                            "message_id": user_message_id,
                            "user_id": user.id,
                        }
                        chat_data["history"].append(new_item)
                        await save_history(
                            self.bot, context_channel.id, chat_data, new_entries=[new_item]
                        )
                        logger.info("Saved user message (No Response) for %s", context_channel.id)
                        return

                    # NOTE: Cancel check before API call was removed - it caused infinite loops
                    # when users sent rapid messages. Instead, pending messages are now
                    # processed AFTER this message completes (via finally block calling
                    # _process_pending_messages). The messages will be merged there.
                    # If cancel was requested, reset flag and continue with this message,
                    # then process pending messages after completion.
                    if self._message_queue.is_cancelled(channel_id):
                        logger.info(
                            "📝 Cancel requested for channel %s - pending after",
                            channel_id,
                        )
                        self._message_queue.reset_cancel(channel_id)

                    # 8. Build API config and call the model
                    config_params = self._build_api_config(chat_data, guild_id)

                    # Check if streaming is enabled for this channel
                    use_streaming = self.is_streaming_enabled(channel_id)

                    _trace_api_start = time.time()
                    if use_streaming:
                        # Use streaming API for real-time updates. Third slot
                        # is the legacy tool-call list from the Gemini era —
                        # the Claude pipeline always returns ``[]`` here and
                        # no consumer reads it; underscore-prefix to flag the
                        # deliberate-drop to readers.
                        (
                            model_text,
                            search_indicator,
                            _function_calls,
                        ) = await self._call_gemini_api_streaming(
                            contents,
                            config_params,
                            send_channel,
                            channel_id,
                            user_id=user.id,
                            guild_id=guild_id,
                        )
                    else:
                        # Use normal API call
                        model_text, search_indicator, _function_calls = await self._call_gemini_api(
                            contents,
                            config_params,
                            channel_id,
                            user_id=user.id,
                            guild_id=guild_id,
                        )

                    # Per-channel trace for the owner's !ai_trace debug panel
                    # (debug_commands.ai_trace_cmd reads chat_data["last_trace"]).
                    # This key previously had NO producer anywhere, so the
                    # panel always claimed "No trace data available" even right
                    # after a request. Tokens are intentionally omitted (they
                    # are recorded in api_handler/token_tracker; the panel
                    # renders N/A) and total_ms spans context-build → API done.
                    _trace_now = time.time()
                    chat_data["last_trace"] = {
                        "total_ms": (_trace_now - _trace_turn_start) * 1000,
                        "api_ms": (_trace_now - _trace_api_start) * 1000,
                        "rag_ms": _trace_rag_ms,
                        "rag_results": _trace_rag_results,
                        "cache_hit": False,
                        "intent": _trace_intent,
                    }

                    # Check for cancellation after API call
                    was_cancelled = self._message_queue.is_cancelled(channel_id)
                    if was_cancelled:
                        logger.info("⏹️ Cancelled after API call for channel %s", channel_id)
                        # Save user message to history
                        user_msg_text = prompt_with_context
                        if image_parts:
                            user_msg_text += " [Image/Attachment]"
                        # Include text file contents in saved history
                        if text_parts:
                            user_msg_text += "\n\n" + "\n".join(text_parts)
                        current_time = _utc_now_iso()

                        new_entries: list[dict[str, Any]] = []
                        user_item = {
                            "role": "user",
                            "parts": [user_msg_text],
                            "timestamp": current_time,
                            # message_id keeps Discord delete/edit sync working
                            # for rows saved by the cancelled-turn path — this
                            # branch fires precisely during rapid sends, so
                            # without it those rows could never be unlinked.
                            "message_id": user_message_id,
                            "user_id": user.id,
                        }
                        chat_data["history"].append(user_item)
                        new_entries.append(user_item)

                        # Save the model turn only when it's a COMPLETE reply.
                        # A cancelled stream returns the partial text accumulated
                        # before the interrupt; persisting that records a reply the
                        # model never finished and poisons later turns. The
                        # non-streaming call returns atomically, so a non-empty
                        # result there is the full reply, worth keeping to avoid
                        # re-billing. (The partial was already shown in Discord.)
                        if model_text and model_text.strip() and not use_streaming:
                            model_item = {
                                "role": "model",
                                "parts": [model_text],
                                # NOTE: seconds-resolution — usually IDENTICAL
                                # to the user item's timestamp (ordering is by
                                # DB insertion id, not this field).
                                "timestamp": _utc_now_iso(),
                            }
                            chat_data["history"].append(model_item)
                            new_entries.append(model_item)

                        await save_history(
                            self.bot, context_channel.id, chat_data, new_entries=new_entries
                        )
                        # Don't return - fall through to process pending messages
                        raise _NewMessageInterrupt("New message received")

                    # 9. Update history
                    user_msg_text = prompt_with_context
                    if image_parts:
                        user_msg_text += " [Image/Attachment]"
                    # Include text file contents in saved history
                    if text_parts:
                        user_msg_text += "\n\n" + "\n".join(text_parts)
                    current_time = _utc_now_iso()

                    new_entries = []

                    user_item = {
                        "role": "user",
                        "parts": [user_msg_text],
                        "timestamp": current_time,
                        "message_id": user_message_id,
                        "user_id": user.id,
                    }
                    chat_data["history"].append(user_item)
                    new_entries.append(user_item)

                    if model_text and model_text.strip():
                        model_item = {
                            "role": "model",
                            "parts": [model_text],
                            # NOTE: seconds-resolution — usually IDENTICAL to
                            # the user item's timestamp above (history order
                            # comes from the DB insertion id, not this field).
                            "timestamp": _utc_now_iso(),
                        }
                        chat_data["history"].append(model_item)
                        new_entries.append(model_item)

                    # NOTE: legacy "9.5 Handle Function Calls" block removed.
                    # The Claude streaming path never surfaces tool_use blocks
                    # to this layer (``_function_calls`` is the always-empty
                    # third slot returned by ``api_handler``). If/when proper
                    # Claude tool_use roundtrips get wired in, this is where
                    # the assistant→tool_use→tool_result alternation should
                    # be threaded back into ``chat_data["history"]``.
                    if not (model_text and model_text.strip()):
                        logger.warning("⚠️ Skipped saving empty model response")

                    await save_history(
                        self.bot, context_channel.id, chat_data, new_entries=new_entries
                    )

                    # Bound the in-memory history to the SAME per-guild retention
                    # cap the DB prune enforces (HISTORY_LIMIT_*), and do it
                    # WITHOUT writing anything back.
                    #
                    # What was here before: a hardcoded "over 2000 -> importance-
                    # trim to 1500", committed with ``save_history(force=True)``.
                    # That force-replace is a DELETE-all + re-insert, so every
                    # crossing PERMANENTLY destroyed the messages it dropped —
                    # measured at ~500 rows per crossing, repeating forever, which
                    # pinned every active channel at ~1499 stored messages and put
                    # the configured caps (HISTORY_LIMIT_RP = 30000,
                    # MAX_HISTORY_ITEMS = 8000) permanently out of reach. The
                    # summary that was supposed to stand in for the dropped turns
                    # only exists when the summarizer has an SDK client, which it
                    # never does under CLAUDE_BACKEND=cli (the default), so in
                    # practice the turns were dropped with nothing replacing them.
                    #
                    # A memory-only bound is sufficient: the PROMPT is already
                    # clamped by MAX_HISTORY_ITEMS above, and storage's prune keeps
                    # the DB at this same cap — so memory and DB stay congruent
                    # with no destructive write from the reply path. Deliberate
                    # tail slice rather than importance scoring: this list mirrors
                    # a retention window, and reordering/among-equals selection is
                    # what made the old trim drop mid-recent context.
                    retention_limit = resolve_history_limit(self.bot, context_channel.id)
                    if retention_limit > 0 and len(chat_data.get("history", [])) > retention_limit:
                        original_len = len(chat_data["history"])
                        chat_data["history"] = chat_data["history"][-retention_limit:]
                        # The length-keyed compress cache would otherwise serve a
                        # stale compression once history regrows to the pre-trim
                        # length. Drop it so the next turn recomputes — mirrors
                        # the edit/patch/delete/insert paths.
                        chat_data.pop("_compress_cache", None)
                        logger.info(
                            "📦 Bounded in-memory history for channel %s: %d -> %d "
                            "(retention cap; stored rows are pruned to the same cap)",
                            channel_id,
                            original_len,
                            len(chat_data["history"]),
                        )

                    # --- Memory Enhancement: Update state tracker and consolidator ---
                    if guild_id == GUILD_ID_RP and model_text:
                        try:
                            # Update character states from response
                            updated_chars = state_tracker.update_from_response(
                                str(model_text), context_channel.id
                            )
                            if updated_chars:
                                logger.debug("🎭 Updated states for: %s", ", ".join(updated_chars))
                        except (KeyError, ValueError, TypeError, re.error) as e:
                            logger.debug("State tracker update failed: %s", e)

                    # Record message for memory consolidation — but only when
                    # the consolidator is actually active. Under CLAUDE_BACKEND=cli
                    # (the default) the SDK client is never initialised, so
                    # consolidate() no-ops without resetting the counter; gating
                    # on ``enabled`` avoids spawning a throwaway task on every
                    # message once the threshold is first crossed.
                    if memory_consolidator.enabled:
                        memory_consolidator.record_message(context_channel.id)

                        # Check if consolidation should run (auto-extract facts every N messages)
                        if memory_consolidator.should_consolidate(context_channel.id):
                            try:
                                # Create task with proper error handling to avoid orphaned tasks
                                task = asyncio.create_task(
                                    memory_consolidator.consolidate(
                                        context_channel.id, chat_data.get("history", []), guild_id
                                    ),
                                    name=f"consolidate_{context_channel.id}",
                                )

                                # Keep strong reference to avoid GC of fire-and-forget task
                                self._background_tasks.add(task)
                                task.add_done_callback(self._background_tasks.discard)

                                # Add callback to log any unhandled exceptions
                                def _handle_consolidation_error(t: asyncio.Task) -> None:
                                    if t.cancelled():
                                        return
                                    exc = t.exception()
                                    if exc:
                                        logger.warning("Memory consolidation task failed: %s", exc)

                                task.add_done_callback(_handle_consolidation_error)
                            except (RuntimeError, asyncio.InvalidStateError) as e:
                                logger.debug("Memory consolidation trigger failed: %s", e)

                    # 10. Process response text
                    response_text = str(model_text).strip() if model_text else ""

                    # (tool_outputs concat dropped along with the dead tool
                    # execution block above)
                    response_text = self._process_response_text(
                        response_text, guild_id, search_indicator
                    )

                    # (Output guardrails removed along with the input ones —
                    # GUARDRAILS_AVAILABLE is hardcoded False in imports.py and
                    # the shim is a pass-through, so the old "10.5 sanitize"
                    # block here could never run and only implied a protection
                    # that no longer exists.)

                    # Defang Discord mentions in ALL AI output (defense-in-depth), through
                    # the ONE canonical escaper. Must run BEFORE the {{Name}} split so the
                    # narrator/plain text is escaped by the same rules ``send_as_webhook``
                    # applies to the character blocks — the private copy that used to live
                    # here diverged from it (see the note above PATTERN_CHARACTER_TAG).
                    # ``escape_mentions`` is idempotent, so a retry path can re-run it
                    # without accumulating zero-width spaces.
                    response_text = escape_mentions(response_text)

                    # Check for {{Name}} syntax (Multi-Character Support)
                    # Split by {{Name}} blocks using precompiled pattern
                    parts = PATTERN_CHARACTER_TAG.split(response_text)

                    # Cap the number of {{Name}} blocks to prevent runaway
                    # webhook spam from a malformed/adversarial response.
                    #
                    # ``re.split`` with ONE capture group always returns an ODD
                    # number of elements — the narrator text, then a (name,
                    # message) pair per block — so the cap must be odd too. The
                    # previous even cap (60) ended the list on a NAME whose
                    # message had just been sliced off, and the send loop's
                    # ``i + 1 < len(parts)`` guard then skipped it: 29 blocks
                    # went out where the comment promised 30.
                    dropped_blocks = 0
                    _max_parts = 1 + 2 * MAX_CHARACTER_BLOCKS
                    if len(parts) > _max_parts:
                        # Round up: a trailing dangling name (no message) still
                        # counts as a block the reader was meant to see.
                        dropped_blocks = (len(parts) - _max_parts + 1) // 2
                        logger.warning(
                            "⚠️ Truncating {{Name}} blocks for channel %s: %d parts -> %d "
                            "(%d block(s) dropped)",
                            channel_id,
                            len(parts),
                            _max_parts,
                            dropped_blocks,
                        )
                        parts = parts[:_max_parts]

                    # If parts has more than 1 element, it means we found {{...}}
                    if len(parts) > 1:
                        # Every Discord message this turn produces, paired with the
                        # speaker it was sent as. ONE history row holds the whole
                        # multi-character reply, but it goes out as many separate
                        # messages — so a single ``message_id`` cannot address the
                        # individual character lines the AI may later be asked to
                        # correct. Collect them all; the prompt builder renders the
                        # pairs so ``edit_message`` can target an exact line.
                        sent_ids: list[dict[str, Any]] = []
                        # parts[0] is the text before the first {{...}} (Narrator/Intro).
                        # Must be chunked to Discord's 2000-char limit — a long
                        # narrator intro previously went out as ONE send, whose
                        # 400 error aborted the entire multi-character response.
                        if parts[0] and parts[0].strip():
                            narrator_text = parts[0].strip()
                            # Thai-combining-aware split (shared with the
                            # normal-send path) — a raw 2000-char slice could
                            # orphan a combining mark on a long intro.
                            for _chunk in _split_for_discord(narrator_text):
                                _narrator_msg = await send_channel.send(
                                    _chunk,
                                    allowed_mentions=discord.AllowedMentions.none(),
                                )
                                if _narrator_msg is not None:
                                    sent_ids.append({"name": "narration", "id": _narrator_msg.id})

                        # Iterate through the rest: odd indices are Names, even are Messages.
                        # ``range(1, len(parts), 2)`` already bounds ``i`` to
                        # valid indices — the prior ``if i >= len(parts): break``
                        # was dead defensive code.
                        last_msg_id = None
                        for i in range(1, len(parts), 2):
                            char_name = parts[i].strip() if parts[i] else ""
                            if not char_name:
                                continue
                            if i + 1 < len(parts):
                                char_msg = parts[i + 1].strip() if parts[i + 1] else ""
                                if char_msg:
                                    sent_msg = await send_as_webhook(
                                        self.bot, send_channel, char_name, char_msg
                                    )
                                    # Capture the last sent message ID
                                    if sent_msg:
                                        last_msg_id = sent_msg.id
                                        sent_ids.append({"name": char_name, "id": sent_msg.id})

                                    # Small delay to ensure order and prevent rate limits
                                    await asyncio.sleep(0.5)

                        # Say what the cap swallowed. The FULL reply — every
                        # dropped block included — is what gets written to
                        # history above, so a silent truncation leaves Discord
                        # and the stored turn disagreeing about what was said,
                        # and the AI will happily reference lines nobody saw.
                        # Same rule ``_safe_split_message`` already follows for
                        # its own chunk ceiling: drop if you must, but say so.
                        if dropped_blocks:
                            with contextlib.suppress(discord.HTTPException):
                                await send_channel.send(
                                    f"*[ตัวละครในข้อความนี้เกิน {MAX_CHARACTER_BLOCKS} ตัว "
                                    f"จึงไม่ได้ส่งอีก {dropped_blocks} ช่วง]*",
                                    allowed_mentions=discord.AllowedMentions.none(),
                                )

                        # Stamp the tail model item. ``message_id`` keeps its old
                        # meaning — the FINAL webhook message — because the Discord
                        # delete/edit mirroring is built on it. ``sent_message_ids``
                        # carries the rest so the individual character messages are
                        # addressable too, and rides along on the same back-fill
                        # UPDATE (both ids only exist once the reply has been sent,
                        # which is after the row was inserted).
                        if sent_ids and chat_data.get("history"):
                            history_list = chat_data["history"]
                            if history_list and len(history_list) > 0:
                                last_item = history_list[-1]
                                # role guard mirrors the normal-send path below:
                                # a dashboard delete during the per-character
                                # webhook loop can remove the in-flight model
                                # item, leaving the user item (or the previous
                                # turn) at the tail — stamping that would also
                                # make update_message_id retarget the previous
                                # turn's model row in the DB.
                                if isinstance(last_item, dict) and last_item.get("role") == "model":
                                    last_item["sent_message_ids"] = sent_ids
                                    # ``last_msg_id`` only tracks WEBHOOK sends, so
                                    # a turn whose {{Name}} blocks all came out
                                    # empty (a dangling tag) — or whose webhook
                                    # sends all failed — left it None. The row then
                                    # kept its ids in memory and persisted NONE of
                                    # them, so after a restart the narration
                                    # messages that DID go out were invisible to the
                                    # Discord delete/edit mirroring. ``sent_ids`` is
                                    # append-ordered, so its tail is the last
                                    # message this turn actually sent — the same
                                    # value ``last_msg_id`` holds whenever a webhook
                                    # succeeded, and the narration fallback when
                                    # none did.
                                    headline_id = last_msg_id or sent_ids[-1].get("id")
                                    if headline_id:
                                        last_item["message_id"] = headline_id
                                        await update_message_id(
                                            context_channel.id, headline_id, sent_ids
                                        )

                        return  # Skip normal sending

                    # Normal Sending (Discord has a 2000 char limit). Split at
                    # natural boundaries, keeping Thai combining marks attached
                    # to their base char (see _split_for_discord). sent_message
                    # ends as the LAST chunk's send, which is what the history
                    # message-id stamping below expects.
                    sent_message = None
                    # Every chunk's id, for the same reason as the webhook path:
                    # a reply over 2000 chars becomes several Discord messages
                    # while staying ONE history row, and only the last one's id
                    # fits the row's ``message_id``.
                    plain_sent_ids: list[dict[str, Any]] = []
                    if response_text:  # Only send if there is text left
                        for _chunk in _split_for_discord(response_text):
                            sent_message = await send_channel.send(
                                _chunk, allowed_mentions=discord.AllowedMentions.none()
                            )
                            if sent_message is not None:
                                plain_sent_ids.append({"name": "reply", "id": sent_message.id})

                    # Update history with Message ID if available
                    if sent_message and chat_data.get("history"):
                        history_list = chat_data["history"]
                        if history_list and len(history_list) > 0:
                            last_item = history_list[-1]
                            if isinstance(last_item, dict) and last_item.get("role") == "model":
                                last_item["message_id"] = sent_message.id
                                # Single-chunk replies are fully described by
                                # ``message_id`` — only record the list when it
                                # actually adds something.
                                extra_ids = plain_sent_ids if len(plain_sent_ids) > 1 else None
                                if extra_ids:
                                    last_item["sent_message_ids"] = extra_ids
                                # Save again to persist ID
                                await update_message_id(
                                    context_channel.id, sent_message.id, extra_ids
                                )

                    # Feedback collection (opt-in via FEEDBACK_COLLECTION_ENABLED;
                    # a no-op otherwise). Only the normal send path is wired here —
                    # the per-character webhook/RP path above is out of scope.
                    await self._maybe_track_feedback(sent_message, channel_id, response_text)

                except _NewMessageInterrupt:
                    # Expected when a new message arrives — allow pending message processing
                    logger.info("🔄 Processing interrupted by new message, will handle pending")
                except asyncio.CancelledError:
                    # Must re-raise to allow proper task cancellation
                    logger.info("🔄 Processing cancelled")
                    raise
                except (discord.HTTPException, ValueError, TypeError) as e:
                    # Truncate so a giant payload in the exception can't flood the log
                    error_msg = str(e)
                    if len(error_msg) > 500:
                        error_msg = error_msg[:500] + "..."
                    logger.error("AI provider error: %s", error_msg)
                    # Send generic error to user (don't leak internal details).
                    # Suppressed: this handler already catches HTTPException —
                    # the same failure class would make this send raise too and
                    # escape process_chat (the catch-all below suppresses it).
                    with contextlib.suppress(discord.HTTPException):
                        await send_channel.send("❌ เกิดข้อผิดพลาดจาก AI กรุณาลองใหม่อีกครั้ง")
                except Exception as e:
                    # Catch-all so unexpected errors don't escape `process_chat`
                    # and orphan queued messages (the `_process_pending_messages`
                    # check at the end of the function would never run).
                    logger.exception("Unhandled error in process_chat: %s", e)
                    with contextlib.suppress(discord.HTTPException):
                        await send_channel.send("❌ เกิดข้อผิดพลาดจาก AI กรุณาลองใหม่อีกครั้ง")
                finally:
                    # Cleanup: Close any remaining PIL images to prevent memory leaks
                    # Most images are closed during processing, this is a safety net
                    # Variables initialized before async with block, so no NameError
                    for part in content_parts:
                        if isinstance(part, Image.Image):
                            try:
                                part.close()
                            except OSError:
                                pass
                    for img in image_parts:
                        if isinstance(img, Image.Image):
                            try:
                                img.close()
                            except OSError:
                                pass

                    # Cleanup request deduplication key
                    self._deduplicator.remove_request(request_key)
        finally:
            # Always release the lock properly — only if we actually acquired it
            try:
                if lock_acquired and lock.locked():
                    lock.release()
            except RuntimeError:
                pass  # Lock was not acquired or already released
            # Clear lock time tracking
            self._message_queue._lock_times.pop(channel_id, None)
            # Idempotent dedup-key cleanup — now a defensive safety net. The
            # inner finally clears this key once we're INSIDE the `async with`
            # body; previously a typing() __aenter__ raise (Forbidden/HTTPException
            # on send_typing) escaped before that and stranded the key. `_typing_or_noop`
            # now degrades such a failure to no-typing instead of escaping, so the
            # key can no longer be stranded here — this release just belt-and-suspenders
            # covers any other early return that skips the inner finally.
            self._deduplicator.remove_request(request_key)
            # Drain pending messages even on error paths so a single failure
            # doesn't leave queued user messages stranded until the next turn.
            # Log the failure instead of swallowing silently — if this raises
            # repeatedly it means the queue is growing unboundedly and we
            # want that to surface, not hide behind suppress().
            if self._message_queue.has_pending(channel_id):
                try:
                    await self._process_pending_messages(channel_id)
                except Exception:
                    logger.warning(
                        "Draining pending messages failed for channel %s",
                        channel_id,
                        exc_info=True,
                    )
