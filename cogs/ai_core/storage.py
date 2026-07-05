"""
Storage module for the AI Core.
Handles saving and loading chat history using SQLite database.
Optimized with in-memory caching for better performance.
"""

from __future__ import annotations

import contextlib
import copy  # For deep copy of cached data

# ==================== Performance: Faster JSON ====================
# orjson is ~10x faster than standard json for parsing and dumping
# Listed as required dependency in requirements.txt
import json

import orjson


def json_loads(data):
    return orjson.loads(data)


def json_dumps(obj, **kwargs):
    # orjson returns bytes, decode to str for compatibility.
    # orjson.dumps() here honors NONE of stdlib json's kwargs (indent,
    # ensure_ascii, sort_keys, default, separators, ...), so any kwargs at
    # all must route to stdlib json — otherwise they'd be silently dropped
    # and the output would diverge from json.dumps semantics. ``indent`` /
    # ``ensure_ascii=False`` are the cases current callers hit; the broader
    # ``if kwargs`` guard keeps a future caller passing sort_keys/default/etc.
    # from being silently ignored.
    if kwargs:
        return json.dumps(obj, **kwargs)
    return orjson.dumps(obj).decode("utf-8")


import asyncio
import hashlib
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from discord.ext.commands import Bot

from .data.constants import (
    GUILD_ID_MAIN,
    GUILD_ID_RP,
    HISTORY_LIMIT_DEFAULT,
    HISTORY_LIMIT_MAIN,
    HISTORY_LIMIT_RP,
    MAX_HISTORY_ITEMS,
)

logger = logging.getLogger(__name__)

# Precompiled regexes for ``get_channel_history_preview`` — applied to
# every history item in a tight loop, so compiling at module scope
# avoids re-parsing the same six patterns on every preview request.
_PREVIEW_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\[System Info\].*?\n"), ""),
    (re.compile(r"\[Voice Status\][\s\S]*?Members:.*?\n"), ""),
    (re.compile(r"\[Chat History Access\][\s\S]*?💡.*?\n"), ""),
    (re.compile(r"\[Requested Chat History\][\s\S]*?---\n"), ""),
    (re.compile(r"User Message:\s*"), ""),
    (re.compile(r"\n+"), " "),
)

# Import database module
try:
    import aiosqlite

    from utils.database import db

    DATABASE_AVAILABLE = True
except ImportError:
    DATABASE_AVAILABLE = False
    aiosqlite = None  # type: ignore[assignment]
    db = None  # type: ignore[assignment]
    logger.warning("Database module not available, falling back to JSON storage")

# Legacy paths for fallback
DATA_DIR = Path("data")
CONFIG_DIR = Path("data/ai_config")


def _ensure_data_dirs() -> None:
    """Create data directories. Called lazily to avoid import-time side effects."""
    for path in (DATA_DIR, CONFIG_DIR):
        try:
            path.mkdir(parents=True, exist_ok=True)
        except (PermissionError, OSError) as exc:
            logger.warning("Could not create directory %s: %s", path, exc)


# Create directories only when running as the bot, not during test/introspection imports.
if os.environ.get("BOT_RUNNING"):
    _ensure_data_dirs()


# ==================== In-Memory Cache ====================
# TTL cache for history to reduce database reads
# Optimized for single-user high-RAM setup (32GB+)

_history_cache: dict[int, tuple[float, list[dict[str, Any]]]] = {}
_metadata_cache: dict[int, tuple[float, dict[str, Any]]] = {}
# Per-channel invalidation generation counter. Bumped (under _cache_lock) by
# every invalidate_cache() call so an in-flight load_history() can detect that
# its DB snapshot went stale mid-await (e.g. a dashboard edit landed while the
# SELECT was running) and re-read instead of re-poisoning the cache with
# pre-edit rows for up to CACHE_TTL.
_cache_generations: dict[int, int] = {}
HistoryCacheEntry = tuple[float, list[dict[str, Any]]]
MetadataCacheEntry = tuple[float, dict[str, Any]]
# Note: threading.RLock used here because cache is accessed from both async coroutines
# and synchronous thread-pool callbacks (e.g., JSON save in executor).
# CPython's GIL ensures dict operations are atomic, but the lock provides extra safety
# for multi-statement read-modify-write patterns across thread boundaries.
_cache_lock = threading.RLock()
CACHE_TTL = 900  # 15 minutes (was 5 min) - keep data in RAM longer
MAX_CACHE_SIZE = 2000  # Maximum channels to cache (was 1000)


def _lock_evictable(lock: asyncio.Lock) -> bool:
    """True when a per-channel history lock is safe to drop from the dict.

    ``locked()`` alone is NOT sufficient: on CPython, ``Lock.release()`` sets
    the woken waiter's future and only schedules its resumption via
    ``call_soon`` — until that waiter's ``acquire()`` actually resumes,
    ``locked()`` reads False while a coroutine is committed to acquiring THAT
    lock object. Evicting in that window orphans the waiter; a later
    ``get_history_lock`` then mints a SECOND lock for the same channel and two
    save/edit critical sections run concurrently — exactly the duplicate-row /
    stale-snapshot corruption the lock exists to prevent. Reads the private
    ``_waiters`` attr (None or deque on CPython 3.14); if a future CPython
    removes it, fail safe: treat the lock as NOT evictable.
    """
    if lock.locked():
        return False
    if not hasattr(lock, "_waiters"):
        return False
    return not getattr(lock, "_waiters", None)


def _cleanup_expired_cache() -> int:
    """Remove expired cache entries proactively.

    Returns:
        Number of entries removed.
    """
    now = time.time()
    with _cache_lock:
        expired_history = [k for k, (t, _) in _history_cache.items() if now - t >= CACHE_TTL]
        expired_metadata = [k for k, (t, _) in _metadata_cache.items() if now - t >= CACHE_TTL]

        for k in expired_history:
            _history_cache.pop(k, None)
        for k in expired_metadata:
            _metadata_cache.pop(k, None)

        # Reclaim the companion per-channel maps for channels no longer live in
        # either cache. invalidate_cache() pops a channel out of _history_cache
        # on every save while bumping its generation, so a save-heavy workload
        # can keep the live cache under MAX_CACHE_SIZE indefinitely and never
        # trigger _enforce_cache_size_limit's eviction loop (the only other place
        # these maps shrink). Drop the orphans here too: a held/awaited
        # _history_lock is in active use by a save/edit and must survive;
        # _post_replace_min_id / _db_loaded_channels are rebuilt on the next
        # force-replace / DB load.
        #
        # _cache_generations is deliberately NOT pruned: generations are
        # staleness counters whose only contract is "never repeats within a
        # snapshot→re-check window". Popping an entry resets the channel to
        # the implicit 0 — a load that snapshotted 0, raced a dashboard edit
        # (gen→1), then saw this tick pop the entry back to 0 would pass its
        # re-check and register PRE-edit history as fresh (a later force-save
        # then durably destroys the edit). An int→int entry per channel ever
        # invalidated is a trivial, naturally-bounded cost.
        live = _history_cache.keys() | _metadata_cache.keys()
        for k in [c for c in _post_replace_min_id if c not in live]:
            _post_replace_min_id.pop(k, None)
        for k in [c for c in _db_loaded_channels if c not in live]:
            _db_loaded_channels.discard(k)
        for k in [c for c in _history_locks if c not in live]:
            _lk = _history_locks.get(k)
            if _lk is not None and _lock_evictable(_lk):
                _history_locks.pop(k, None)

    return len(expired_history) + len(expired_metadata)


def _enforce_cache_size_limit() -> int:
    """Enforce max cache size by removing oldest entries.

    Returns:
        Number of entries removed.
    """
    removed = 0

    with _cache_lock:
        # Check history cache
        if len(_history_cache) > MAX_CACHE_SIZE:
            # Use heapq.nsmallest for O(n) instead of full sort O(n log n)
            import heapq

            excess = len(_history_cache) - MAX_CACHE_SIZE
            oldest_history: list[tuple[int, HistoryCacheEntry]] = heapq.nsmallest(
                excess,
                _history_cache.items(),
                key=lambda item: item[1][0],
            )
            for k, _ in oldest_history:
                _history_cache.pop(k, None)
                # Drop the companion per-channel maps for the evicted channel so
                # they don't grow unbounded relative to the cache they shadow.
                # _cache_generations is NOT popped — see _cleanup_expired_cache:
                #   resetting a generation to the implicit 0 defeats the
                #   stale-load guard for gen-0 snapshots.
                # _post_replace_min_id / _db_loaded_channels: rebuilt on the next
                #   force-replace / DB load respectively.
                _post_replace_min_id.pop(k, None)
                _db_loaded_channels.discard(k)
                # Only drop the lock when it is neither held nor awaited — a
                # held lock is in active use by a save/edit and a lock with a
                # pending waiter is mid-handoff (see _lock_evictable).
                _lk = _history_locks.get(k)
                if _lk is not None and _lock_evictable(_lk):
                    _history_locks.pop(k, None)
                removed += 1

        # Check metadata cache
        if len(_metadata_cache) > MAX_CACHE_SIZE:
            import heapq

            excess = len(_metadata_cache) - MAX_CACHE_SIZE
            oldest_metadata: list[tuple[int, MetadataCacheEntry]] = heapq.nsmallest(
                excess,
                _metadata_cache.items(),
                key=lambda item: item[1][0],
            )
            for k, _ in oldest_metadata:
                _metadata_cache.pop(k, None)
                removed += 1

    if removed > 0:
        logger.debug("🧹 Cache size limit enforced: removed %d entries", removed)

    return removed


def _parse_history_timestamp(value: Any) -> datetime | None:
    """Parse legacy and ISO timestamps from stored AI history values."""
    if not isinstance(value, str):
        return None

    text = value.strip()
    if not text:
        return None

    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"

    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _normalize_history_timestamp(value: Any) -> str | None:
    """Normalize timestamps to UTC ISO 8601 for consistent comparisons."""
    parsed = _parse_history_timestamp(value)
    if parsed is None:
        return None
    return parsed.isoformat(timespec="seconds")


def _parts_to_text(parts: Any) -> str:
    """Serialize a history item's ``parts`` into the canonical content string.

    Single source of truth for BOTH the DB INSERT paths and the dedup hashes:
    previously the INSERTs used ``str(p)`` (which is the Python *repr* for
    dict parts like ``{"text": ...}`` from legacy JSON histories) while the
    overlap hash extracted ``p.get("text")`` — so legacy dict-part rows were
    persisted as repr strings and never matched their own dedup keys.
    """
    if not isinstance(parts, list):
        return str(parts)
    pieces: list[str] = []
    for p in parts:
        if not p:
            continue
        if isinstance(p, dict):
            text = str(p.get("text", ""))
            if text:
                pieces.append(text)
        else:
            pieces.append(str(p))
    return "\n".join(pieces)


def invalidate_cache(channel_id: int) -> None:
    """Invalidate cache for a specific channel.

    Also bumps the channel's generation counter so a load_history() whose DB
    read was already in flight when this ran knows its snapshot is stale.
    """
    with _cache_lock:
        _history_cache.pop(channel_id, None)
        _metadata_cache.pop(channel_id, None)
        _cache_generations[channel_id] = _cache_generations.get(channel_id, 0) + 1


def get_cache_generation(channel_id: int) -> int:
    """Current cache-invalidation generation for a channel.

    Callers (e.g. ``SessionMixin.get_chat_session``) snapshot this before an
    awaited load and re-check it before registering the result: a bump in
    between means an external edit invalidated the channel mid-load and the
    loaded history must be re-read.
    """
    with _cache_lock:
        return _cache_generations.get(channel_id, 0)


# Per-channel asyncio locks serializing history SAVES (diff-mode fetch+write
# and force-replace delete+reinsert) against dashboard row EDITS. Without
# this, an edit completing inside a save's get_ai_history await makes the
# save's stale snapshot fail the content-hash overlap and re-append (duplicate)
# the edited row via the no-overlap fallback. Single event loop — a plain dict
# setdefault is race-free here.
_history_locks: dict[int, asyncio.Lock] = {}


def get_history_lock(channel_id: int) -> asyncio.Lock:
    """Per-channel lock serializing history saves against dashboard edits.

    Held by ``_save_history_db`` / ``_replace_history_db`` and by the
    dashboard's ``handle_edit_ai_history_message`` (read-row + UPDATE +
    memory patch) / ``handle_delete_ai_history_message`` (read-row + DELETE +
    memory removal). Nothing inside those regions may await something that
    takes the same lock — in particular ``load_history`` is NOT under it.
    """
    return _history_locks.setdefault(channel_id, asyncio.Lock())


# Per-channel watermark: the smallest ai_history row id minted by the last
# force-replace save (``_replace_history_db``'s DELETE-all + re-INSERT mints
# fresh AUTOINCREMENT ids above the old maximum). An undo entry captured
# BEFORE that rewrite holds an id lower than every surviving row, so a
# restore would silently land the row at position 0 (ordering is by id) with
# a success ack — ``restore_message_by_row`` rejects such ids as ``'stale'``
# instead. In-process only (resets on bot restart); updated under
# ``get_history_lock``, read on the restore path which holds the same lock.
_post_replace_min_id: dict[int, int] = {}


def invalidate_all_cache() -> None:
    """Invalidate all caches."""
    with _cache_lock:
        # Bump generations for every channel so in-flight loads see the wipe
        # (same staleness rule as the per-channel invalidation). Cover the
        # UNION of _history_cache, _metadata_cache and _cache_generations
        # keys — not just _history_cache: a channel that is currently
        # uncached (never cached, or evicted by _enforce_cache_size_limit
        # which also pops its generation) can still have a load_history() in
        # flight that snapshotted its generation. Without bumping it here,
        # that pre-wipe snapshot would be cached for up to CACHE_TTL.
        for cid in set(_history_cache) | set(_metadata_cache) | set(_cache_generations):
            _cache_generations[cid] = _cache_generations.get(cid, 0) + 1
        _history_cache.clear()
        _metadata_cache.clear()


def cleanup_cache() -> int:
    """Perform full cache maintenance: expire old entries and enforce size limit.

    Call this periodically (e.g., every 5 minutes) to prevent memory growth.

    Returns:
        Total number of entries removed.
    """
    removed = _cleanup_expired_cache()
    removed += _enforce_cache_size_limit()
    return removed


# ==================== Database Storage (Primary) ====================


async def save_history(
    bot: Bot,
    channel_id: int,
    chat_data: dict[str, Any],
    new_entries: list[dict[str, Any]] | None = None,
    force: bool = False,
) -> bool:
    """Save chat history to database.

    Returns True if persistence succeeded, False otherwise. Callers that
    rely on save success to evict in-memory state (e.g. cleanup_inactive_sessions)
    must check this return value — otherwise a silent DB failure would cause
    the in-memory data to be discarded while never having been persisted.

    When ``force`` is True, the in-memory ``chat_data["history"]`` is treated
    as the canonical view and the persisted DB rows are replaced wholesale
    (used by auto-trim, which mutates history in place and needs to commit
    that view immediately).
    """
    if not chat_data:
        return True

    # Determine limit based on Guild (optimized for memory). Bot.get_channel /
    # channel.guild access is best-effort — failures here don't make the save
    # fail, we just fall back to the default limit.
    limit = HISTORY_LIMIT_DEFAULT
    try:
        channel = bot.get_channel(channel_id)
        if channel and hasattr(channel, "guild") and channel.guild:
            if channel.guild.id == GUILD_ID_MAIN:
                limit = HISTORY_LIMIT_MAIN
            elif channel.guild.id == GUILD_ID_RP:
                limit = HISTORY_LIMIT_RP
    except Exception:
        logger.debug("Failed to resolve guild for channel %s", channel_id)

    if DATABASE_AVAILABLE:
        try:
            # Both helpers return False when they REFUSE to persist (empty-
            # history guard, dedup-failure guard). Propagating that is what
            # keeps eviction paths (cleanup_inactive_sessions, LRU) from
            # discarding in-memory history that was never written.
            if force:
                persisted = await _replace_history_db(channel_id, chat_data, limit)
            else:
                persisted = await _save_history_db(channel_id, chat_data, limit, new_entries)
            return bool(persisted)
        except aiosqlite.Error as e:
            logger.error(
                "Database save failed for channel %s: %s",
                channel_id,
                e,
                extra={"event": "db_save_failed", "channel_id": channel_id},
            )
            return False
        except Exception:
            logger.exception("Unexpected save_history failure for channel %s", channel_id)
            return False

    try:
        await _save_history_json(bot, channel_id, chat_data, limit)
        return True
    except Exception:
        logger.exception("JSON history save failed for channel %s", channel_id)
        return False


async def _replace_history_db(
    channel_id: int,
    chat_data: dict[str, Any],
    limit: int,
) -> bool:
    """Replace the persisted DB history for a channel with the in-memory view.

    Used by save_history(force=True) after auto-trim mutates history.
    Runs as a single transaction: delete-all then bulk-insert.
    """
    history = chat_data.get("history", [])

    # Defense-in-depth: refuse to wipe a DB-backed channel down to zero rows.
    # The diff path already guards against this (line 383-390); mirror that
    # guard here so a force=True call from a buggy caller (or a chat_data
    # whose history was accidentally cleared in-memory) doesn't silently
    # destroy the persisted history. Callers that legitimately want to
    # erase a channel should use ``delete_ai_history`` directly.
    if not history and chat_data.get("_db_loaded"):
        logger.error(
            "❌ Refusing force-replace with empty history for channel %s "
            "(chat_data was DB-loaded). Use delete_ai_history if a wipe "
            "is actually intended.",
            channel_id,
        )
        return False

    # Honor the per-guild retention limit save_history computed (RP=30000
    # etc.). The old global MAX_HISTORY_ITEMS cap silently truncated RP
    # channels to 2000 on force-replace while logging the unused limit.
    cap = limit if limit and limit > 0 else MAX_HISTORY_ITEMS
    if len(history) > cap:
        history = history[-cap:]

    rows: list[tuple[Any, ...]] = []
    for item in history:
        if not isinstance(item, dict):
            continue
        role = item.get("role", "user")
        content = _parts_to_text(item.get("parts", []))
        if not content:
            continue
        rows.append(
            (
                channel_id,
                item.get("user_id"),
                role,
                content,
                item.get("message_id"),
                # A missing timestamp must not insert NULL — NULL bypasses the
                # column's CURRENT_TIMESTAMP default and sorts inconsistently
                # under ORDER BY timestamp (same rule as save_ai_messages_batch
                # in utils/database/database.py). smart_trim summary entries
                # historically lacked timestamps and landed here via force=True.
                _normalize_history_timestamp(item.get("timestamp"))
                or datetime.now(timezone.utc).isoformat(timespec="seconds"),
            )
        )

    # Per-channel lock: the delete+reinsert must not interleave with a
    # dashboard edit (DB UPDATE + memory patch) — see get_history_lock.
    async with get_history_lock(channel_id):
        async with db.get_write_connection() as conn:
            await conn.execute("DELETE FROM ai_history WHERE channel_id = ?", (channel_id,))
            if rows:
                insert_rows = []
                for i, (ch, uid, role, content, mid, ts) in enumerate(rows, start=1):
                    insert_rows.append((ch, uid, role, content, mid, ts, i))
                # Upsert on (channel_id, message_id) to match the other ai_history
                # write paths. The DELETE above clears the channel, so a collision
                # can only come from two in-memory rows sharing the same non-NULL
                # message_id; without ON CONFLICT that would raise IntegrityError and
                # roll back the whole replace (losing the save). Last write wins.
                await conn.executemany(
                    """INSERT INTO ai_history
                       (channel_id, user_id, role, content, message_id, timestamp, local_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(channel_id, message_id) WHERE message_id IS NOT NULL
                       DO UPDATE SET content = excluded.content""",
                    insert_rows,
                )
            await conn.commit()
            # Record the smallest id this rewrite minted (still under the
            # lock): undo entries captured before the rewrite carry ids below
            # it and must be rejected as stale — see _post_replace_min_id.
            cursor = await conn.execute(
                "SELECT MIN(id) FROM ai_history WHERE channel_id = ?", (channel_id,)
            )
            min_row = await cursor.fetchone()
            min_id = min_row[0] if min_row else None
            if min_id is not None:
                _post_replace_min_id[channel_id] = int(min_id)

    thinking_enabled = chat_data.get("thinking_enabled", True)
    # Pass the in-memory system_instruction through so the UPSERT (which
    # unconditionally sets system_instruction = excluded.system_instruction)
    # doesn't clobber a persisted per-channel instruction back to NULL.
    await db.save_ai_metadata(
        channel_id=channel_id,
        thinking_enabled=thinking_enabled,
        system_instruction=chat_data.get("system_instruction"),
    )
    invalidate_cache(channel_id)
    logger.info(
        "💾 Force-replaced %d messages for channel %s (limit=%d)",
        len(rows),
        channel_id,
        limit,
    )
    return True


async def _save_history_db(
    channel_id: int,
    chat_data: dict[str, Any],
    limit: int,
    new_entries: list[dict[str, Any]] | None = None,
) -> bool:
    """Save history using SQLite database with batch operations.

    Returns True when the save completed (or there was legitimately nothing
    to write); False when a safety guard REFUSED to persist — callers must
    not treat a refusal as success (eviction would discard unsaved history).
    """

    # Fetch enough messages from DB for reliable duplicate checking
    # Using a small limit caused missed duplicates when history was long
    history = chat_data.get("history", [])
    dedup_limit = max(50, MAX_HISTORY_ITEMS or 5000) if history else 50
    # Per-channel lock — held from the db_history fetch through the batch
    # write. A dashboard edit completing inside the fetch await would leave
    # this snapshot stale: the edited row then fails the content-hash overlap
    # match and gets re-appended (duplicated) by the no-overlap fallback. With
    # the lock, a save sees pre-edit or post-edit state consistently on both
    # sides. Nothing in here awaits anything that takes this lock (in
    # particular, load_history is NOT called under it).
    async with get_history_lock(channel_id):
        db_history = await db.get_ai_history(channel_id, limit=dedup_limit)

        # Use explicitly provided new entries if available
        new_messages = []
        if new_entries:
            new_messages = new_entries
        else:
            # Fallback: smarter diffing logic
            history = chat_data.get("history", [])

            if not db_history:
                # Refuse to dump entire history if chat_data was previously loaded
                # from DB. Without this, an empty fetch (transient DB read failure
                # or post-prune race) would re-insert the whole in-memory history,
                # creating massive duplicate runs.
                if history and chat_data.get("_db_loaded"):
                    logger.error(
                        "❌ Refusing to dump full history for channel %s: db_history is empty "
                        "but chat_data was DB-loaded (history=%d items). Possible read failure.",
                        channel_id,
                        len(history),
                    )
                    return False
                new_messages = history
            elif not history:
                new_messages = []
            else:
                # Find where the DB history ends in the current history
                last_db_msg = db_history[-1]
                last_db_ts = _normalize_history_timestamp(last_db_msg.get("timestamp"))
                last_db_dt = _parse_history_timestamp(last_db_msg.get("timestamp"))

                # Look for this message in history (iterate backwards). Match
                # on timestamp + role + content-hash so two assistant messages
                # sent in the same second (same timestamp, same role) don't get
                # collapsed into one. SHA-256 of the FULL joined content matches
                # the dedup approach at the bottom of this function — using a
                # 200-char prefix here silently dropped messages whose first
                # 200 chars matched but tails diverged.
                def _content_key(item: dict) -> str:
                    # ``item`` can come from either side:
                    #   - history (in-memory): has ``parts`` list (str/dict)
                    #   - db_history (persisted): has flat ``content`` string
                    # Both sides MUST hash the same text the INSERT paths persist,
                    # hence the shared ``_parts_to_text`` serializer.
                    content_value = item.get("content")
                    if content_value is not None:
                        content = str(content_value)
                    else:
                        content = _parts_to_text(item.get("parts") or [])
                    return hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()

                last_db_content_key = _content_key(last_db_msg)
                found_idx = -1
                for i in range(len(history) - 1, -1, -1):
                    item = history[i]
                    if (
                        _normalize_history_timestamp(item.get("timestamp")) == last_db_ts
                        and item.get("role") == last_db_msg.get("role")
                        and _content_key(item) == last_db_content_key
                    ):
                        found_idx = i
                        break

                if found_idx != -1:
                    # We found the overlap, everything after is new
                    if found_idx < len(history) - 1:
                        new_messages = history[found_idx + 1 :]
                # No overlap found? This implies disjoint history or different timestamps.
                # Fallback to appending everything that has a timestamp >= last_db_dt,
                # using a (role, timestamp, content-hash) set to dedupe against rows
                # already persisted at/after the boundary. (``last_db_ts`` cannot be
                # None here: it derives from the same parse that made
                # ``last_db_dt`` non-None.) Including the timestamp in the key keeps
                # genuinely distinct repeats (same text sent at different times)
                # instead of silently dropping the later one.
                elif last_db_dt is not None:
                    db_boundary_keys: set[tuple[str, str | None, str]] = set()
                    for db_item in db_history:
                        db_dt = _parse_history_timestamp(db_item.get("timestamp"))
                        if db_dt is not None and db_dt >= last_db_dt:
                            db_role = db_item.get("role") or "user"
                            db_boundary_keys.add(
                                (
                                    db_role,
                                    _normalize_history_timestamp(db_item.get("timestamp")),
                                    _content_key(db_item),
                                )
                            )

                    candidates = []
                    skipped_untimestamped = 0
                    for m in history:
                        m_dt = _parse_history_timestamp(m.get("timestamp"))
                        if m_dt is None:
                            # Can't position an untimestamped item against the
                            # boundary — excluded (conservative), but say so
                            # instead of silently never persisting it.
                            skipped_untimestamped += 1
                            continue
                        if m_dt >= last_db_dt:
                            candidates.append(m)
                    if skipped_untimestamped:
                        logger.warning(
                            "⚠️ No-overlap fallback for channel %s excluded %d in-memory "
                            "item(s) without parseable timestamps from persistence",
                            channel_id,
                            skipped_untimestamped,
                        )

                    new_messages = []
                    for m in candidates:
                        m_role = m.get("role") or "user"
                        m_key = (
                            m_role,
                            _normalize_history_timestamp(m.get("timestamp")),
                            _content_key(m),
                        )
                        if m_key in db_boundary_keys:
                            continue
                        db_boundary_keys.add(m_key)
                        new_messages.append(m)
                else:
                    # Position-based diff is unsafe — it slices the wrong region
                    # whenever history and db_history don't have aligned positions
                    # (e.g. after a prune). Refuse to write rather than risk
                    # corrupting persisted history with duplicates.
                    logger.error(
                        "❌ history dedup failed, position-based fallback disabled to prevent corruption "
                        "(channel %s, history=%d, db=%d)",
                        channel_id,
                        len(history),
                        len(db_history),
                    )
                    return False

        # Process new messages
        if new_messages:
            # Prepare batch data
            batch_data = []
            prev_batch_hash: str | None = None  # adjacent-duplicate tracking
            prev_batch_timestamp: str | None = None
            prev_batch_message_id: Any = None

            # Get last message from DB to check for duplicates
            # Hash the full content (not just a prefix) so two messages that share
            # a long prefix but diverge later don't get falsely flagged as
            # duplicates and silently dropped. SHA-256 is fast enough that 500-char
            # vs full-content makes no measurable difference for chat-sized payloads.
            last_db_content_hash = None
            last_db_role = None
            last_db_message_id = None
            last_db_timestamp = None
            if db_history:
                last_db_message_id = db_history[-1].get("message_id")
                last_db_timestamp = _normalize_history_timestamp(db_history[-1].get("timestamp"))
                # ``errors="replace"`` keeps the hash deterministic even when an
                # older row contains a malformed surrogate from a previous bug —
                # the default ``strict`` would raise here and abort the whole
                # save_history path on a single corrupt historic record.
                last_db_content_hash = hashlib.sha256(
                    db_history[-1].get("content", "").encode("utf-8", errors="replace")
                ).hexdigest()
                last_db_role = db_history[-1].get("role")

            for item in new_messages:
                if not isinstance(item, dict):
                    continue

                role = item.get("role", "user")
                message_id = item.get("message_id")
                timestamp = _normalize_history_timestamp(item.get("timestamp"))

                # Convert parts to string (shared serializer — keeps the persisted
                # content identical to what the dedup hashes were computed from).
                content = _parts_to_text(item.get("parts", []))

                if not content:
                    continue

                # Hash the content once; reuse for both the per-batch dedupe key
                # and the just-in-DB comparison. Recomputing twice was wasteful on
                # long messages and trivially fixable.
                # Match the ``errors="replace"`` strategy used for the DB-side
                # hash above so live and historic strings hash identically and
                # dedupe still works across malformed historic rows.
                raw_hash = hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()
                content_hash = f"{role}:{raw_hash}"

                # Skip if this exact content was just in DB (immediate duplicate).
                # Tiebreakers: message_id for user rows, timestamp for model rows.
                # Model items have NO message_id at save time (it's back-filled
                # later by update_message_id), so the message_id wildcard alone
                # silently dropped a NEW model reply whose text equals the
                # previous turn's persisted reply — and update_message_id then
                # back-filled the new Discord id onto the OLD row. A genuinely
                # re-presented item carries the same timestamp; a new turn gets a
                # fresh one, so timestamp equality keeps the dedup for true
                # duplicates while letting legitimate repeats through.
                if (
                    last_db_content_hash
                    and raw_hash == last_db_content_hash
                    and role == last_db_role
                    and timestamp == last_db_timestamp
                    and (message_id is None or message_id == last_db_message_id)
                ):
                    logger.warning(
                        "⚠️ Skipping duplicate message (matches last DB entry): %s...", content[:50]
                    )
                    continue

                # Skip ADJACENT repeats within the current batch only. The old
                # batch-wide set dropped non-adjacent legitimate repeats
                # ([user:"ok", model:..., user:"ok"]) from a pending-queue flush.
                # Timestamp equality is required for the same reason as the
                # just-in-DB check above: identical text at a DIFFERENT time is a
                # legitimate new entry, not a double-append.
                if (
                    content_hash == prev_batch_hash
                    and timestamp == prev_batch_timestamp
                    and (message_id is None or message_id == prev_batch_message_id)
                ):
                    logger.warning(
                        "⚠️ Skipping duplicate message (adjacent in batch): %s...", content[:50]
                    )
                    continue

                prev_batch_hash = content_hash
                prev_batch_timestamp = timestamp
                prev_batch_message_id = message_id
                batch_data.append(
                    {
                        "channel_id": channel_id,
                        "user_id": item.get("user_id"),
                        "role": role,
                        "content": content,
                        "message_id": message_id,
                        "timestamp": timestamp,
                    }
                )

            if batch_data:
                try:
                    await db.save_ai_messages_batch(batch_data)
                    logger.debug(
                        "💾 Batch saved %d messages for channel %s", len(batch_data), channel_id
                    )
                except aiosqlite.Error:
                    # Surface the failure so save_history can flip its return to False
                    # rather than reporting success while silently dropping messages.
                    logger.exception(
                        "❌ Failed to batch save %d messages for channel %s",
                        len(batch_data),
                        channel_id,
                    )
                    raise

        # Prune if over limit. Add a 50-message buffer to avoid count/prune
        # thrashing under concurrent writes — without this, two near-simultaneous
        # saves can each see "count > limit" and both call prune, doubling the
        # write cost and racing on the same rows.
        # Held under get_history_lock so the count-then-prune is atomic against
        # the restore path (restore_message_by_row, also under this lock): an
        # unlocked prune could DELETE an old-id row a restore had just
        # re-inserted, or pull the id floor out from under an in-flight restore.
        total_count = await db.get_ai_history_count(channel_id)
        if total_count > limit + 50:
            await db.prune_ai_history(channel_id, limit)
            logger.info("🧹 Pruned history for channel %s to %d messages", channel_id, limit)
            # prune raises the smallest surviving id (it deletes the oldest
            # rows), so refresh the stale-restore watermark just like
            # _replace_history_db does. Without this, an undo entry captured
            # before the prune carries an id below every surviving row, passes
            # the restore stale guard, and lands at position 0. Still under
            # get_history_lock, so this is serialized against the restore path.
            async with db.get_connection() as conn:
                cursor = await conn.execute(
                    "SELECT MIN(id) FROM ai_history WHERE channel_id = ?", (channel_id,)
                )
                min_row = await cursor.fetchone()
            min_id = min_row[0] if min_row else None
            if min_id is not None:
                _post_replace_min_id[channel_id] = int(min_id)

    thinking_enabled = chat_data.get("thinking_enabled", True)
    # Pass the in-memory system_instruction through so the UPSERT (which
    # unconditionally sets system_instruction = excluded.system_instruction)
    # doesn't clobber a persisted per-channel instruction back to NULL.
    await db.save_ai_metadata(
        channel_id=channel_id,
        thinking_enabled=thinking_enabled,
        system_instruction=chat_data.get("system_instruction"),
    )
    invalidate_cache(channel_id)
    return True


async def _save_history_json(
    bot: Bot, channel_id: int, chat_data: dict[str, Any], limit: int
) -> None:
    """Fallback: Save history using JSON files."""
    history = chat_data.get("history", [])

    # Smart pruning
    if len(history) > limit:
        # For small limits, just keep the most recent messages
        if limit <= 6:
            history = history[-limit:]
        else:
            keep_start = 6
            keep_end = limit - keep_start

            if keep_end % 2 != 0:
                keep_end -= 1

            # Guard against keep_end <= 0 (e.g. limit=7 -> keep_end=0 after odd fix)
            if keep_end <= 0:
                history = history[-limit:]
            else:
                if keep_end > len(history) - keep_start:
                    keep_end = len(history) - keep_start
                    keep_end = max(keep_end, 0)

                actual_keep_end = min(keep_end, len(history) - keep_start)
                if actual_keep_end > 0:
                    history = history[:keep_start] + history[-actual_keep_end:]
                else:
                    history = history[-limit:]

    # Keep the caller's in-memory view in sync with what we persist in EVERY
    # pruning branch. Previously only the actual_keep_end>0 branch reassigned
    # chat_data["history"], so the other branches left the live session list
    # diverging from what was written to disk.
    chat_data["history"] = history

    def _write():
        _ensure_data_dirs()
        filepath = DATA_DIR / f"ai_history_{channel_id}.json"
        temp_filepath = filepath.with_suffix(".json.tmp")

        # fsync BEFORE the atomic rename: without it a power loss can persist
        # the rename while the data blocks were never flushed, leaving an
        # empty/truncated file — and this JSON path is the only persistence
        # when the DB is unavailable.
        with temp_filepath.open("w", encoding="utf-8") as fh:
            fh.write(json_dumps(history, ensure_ascii=False, indent=2))
            fh.flush()
            os.fsync(fh.fileno())

        temp_filepath.replace(filepath)  # Atomic replace, works whether target exists or not

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _write)

    metadata = {"thinking_enabled": chat_data.get("thinking_enabled", True)}

    def _write_meta():
        _ensure_data_dirs()
        filepath = CONFIG_DIR / f"ai_metadata_{channel_id}.json"
        # Atomic write: temp file + rename, mirroring the history JSON path
        # above. A direct write_text() truncates the target before writing,
        # so a process kill mid-write leaves a zero-byte metadata file with
        # no recovery path. Use ``.json.tmp`` to match the history path's
        # naming convention so cleanup tools that glob ``*.json.tmp`` catch
        # orphans uniformly.
        temp_filepath = filepath.with_suffix(".json.tmp")
        with temp_filepath.open("w", encoding="utf-8") as fh:
            fh.write(json_dumps(metadata, ensure_ascii=False, indent=2))
            fh.flush()
            os.fsync(fh.fileno())
        temp_filepath.replace(filepath)

    await loop.run_in_executor(None, _write_meta)

    # Mirror the DB save paths (_save_history_db:627 / _replace_history_db:374):
    # drop the in-memory cache so the next load_history re-reads the file just
    # written instead of serving stale cached history for up to CACHE_TTL (this
    # JSON fallback path previously skipped invalidation entirely).
    invalidate_cache(channel_id)


# Channels whose most recent non-cached load_history() came from the DATABASE
# (as opposed to the legacy JSON fallback). session_mixin consults this to set
# ``_db_loaded`` truthfully — flagging JSON-loaded history as DB-loaded made
# _save_history_db's empty-fetch guard permanently refuse every save for
# legacy JSON channels (nothing was ever migrated OR persisted).
_db_loaded_channels: set[int] = set()


def last_load_was_db(channel_id: int) -> bool:
    """True when the channel's history was last loaded from the database."""
    return channel_id in _db_loaded_channels


# Bounded re-read attempts for load_history/load_metadata when an invalidation
# lands mid-load (see below).
_LOAD_HISTORY_MAX_ATTEMPTS = 3


async def load_history(bot: Bot, channel_id: int) -> list[dict[str, Any]]:
    """Load chat history from database or JSON file with caching.

    Guarded against the in-flight-edit race: a dashboard edit can UPDATE the
    row and invalidate the cache WHILE the DB read below is awaiting. Storing
    that pre-edit snapshot would re-poison the cache for up to CACHE_TTL after
    the invalidation, so the generation counter is snapshotted before the read
    and re-checked before the cache store — on a bump, re-read (bounded); if
    the bumps keep coming, return the last snapshot WITHOUT caching it.
    """
    for attempt in range(_LOAD_HISTORY_MAX_ATTEMPTS):
        last_attempt = attempt == _LOAD_HISTORY_MAX_ATTEMPTS - 1
        now = time.time()

        # Check cache first (thread-safe), snapshotting the generation the
        # load starts from in the same locked section.
        with _cache_lock:
            generation = _cache_generations.get(channel_id, 0)
            if channel_id in _history_cache:
                cached_time, cached_data = _history_cache[channel_id]
                if now - cached_time < CACHE_TTL:
                    logger.debug(
                        "📖 Cache hit for channel %s (%d messages)", channel_id, len(cached_data)
                    )
                    # Use deep copy to prevent mutation of cached nested objects
                    return copy.deepcopy(cached_data)

        if DATABASE_AVAILABLE:
            # Try database
            db_history = await db.get_ai_history(channel_id)
            if db_history:
                # Convert DB format {role, content, timestamp, message_id, ...}
                # to API format. Preserve timestamp/message_id/user_id so the
                # next save's overlap detection (timestamp+role+content match)
                # has the data it needs — without these, save_history's
                # _normalize_history_timestamp returns None on every row and
                # forces the "dangerous fallback" position-based slice path.
                history = []
                for item in db_history:
                    converted: dict[str, Any] = {
                        "role": item.get("role", "user"),
                        "parts": [item.get("content", "")],
                    }
                    # Carry forward bookkeeping fields if present so the round
                    # trip is lossless.
                    for k in ("timestamp", "message_id", "user_id"):
                        if item.get(k) is not None:
                            converted[k] = item[k]
                    history.append(converted)

                # Update cache with converted format (thread-safe) — unless an
                # invalidation landed during the await above (the snapshot is
                # then pre-edit and must not be cached).
                with _cache_lock:
                    fresh = _cache_generations.get(channel_id, 0) == generation
                    if fresh:
                        _history_cache[channel_id] = (now, copy.deepcopy(history))
                if not fresh and not last_attempt:
                    continue  # re-read: the post-edit rows are one SELECT away
                if not fresh:
                    logger.warning(
                        "⚠️ load_history for channel %s kept racing invalidations "
                        "(%d attempts) — returning uncached snapshot",
                        channel_id,
                        _LOAD_HISTORY_MAX_ATTEMPTS,
                    )
                _db_loaded_channels.add(channel_id)
                logger.info(
                    "📖 Loaded %d messages from database for channel %s", len(history), channel_id
                )
                return history

        # Fallback to JSON file
        history = await _load_history_json(bot, channel_id)
        _db_loaded_channels.discard(channel_id)
        if history:
            with _cache_lock:
                fresh = _cache_generations.get(channel_id, 0) == generation
                if fresh:
                    _history_cache[channel_id] = (now, copy.deepcopy(history))
            if not fresh and not last_attempt:
                continue
            if not fresh:
                logger.warning(
                    "⚠️ load_history (JSON) for channel %s kept racing invalidations "
                    "(%d attempts) — returning uncached snapshot",
                    channel_id,
                    _LOAD_HISTORY_MAX_ATTEMPTS,
                )
        return history

    return []  # unreachable: the last attempt always returns above


async def _load_history_json(bot: Bot, channel_id: int) -> list[dict[str, Any]]:
    """Fallback: Load history from JSON file."""
    filepath = DATA_DIR / f"ai_history_{channel_id}.json"

    if not filepath.exists():
        return []

    def _read():
        try:
            return json_loads(filepath.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.exception("File read error for %s", filepath)
            return None

    data = await asyncio.get_running_loop().run_in_executor(None, _read)

    if data:
        logger.info("📖 Loaded %d messages from JSON for channel %s", len(data), channel_id)

        history = []
        for item in data:
            if not isinstance(item, dict):
                continue

            parts = item.get("parts", [])
            if isinstance(parts, str):
                parts = [parts]
            elif not isinstance(parts, list):
                parts = []

            # Keep whatever role string is stored, matching the DB loader path
            # in load_history (which applies no role filter). Filtering to
            # only user/model here made the JSON fallback silently shrink
            # history relative to the DB backend for rows carrying a
            # 'system'/'assistant'/legacy role.
            role = item.get("role", "user")

            history_item = {"role": role, "parts": parts}

            # Carry user_id too — _save_history_json dumps in-memory items
            # verbatim (which include it), and dropping it here meant the
            # JSON→DB migration save wrote every row with user_id=NULL,
            # permanently stripping per-user attribution even though the JSON
            # file still held the real ids (the DB loader deliberately keeps
            # it "so the round trip is lossless" — keep this path in lockstep).
            for k in ("timestamp", "message_id", "user_id"):
                if k in item:
                    history_item[k] = item[k]

            history.append(history_item)

        return history

    return []


# get_ai_metadata (utils/database/database.py) returns this EXACT dict when a
# channel has no ai_metadata row — an always-truthy synthetic default. A real row
# additionally carries "last_accessed", so it can never equal this sentinel.
# Detecting it lets load_metadata fall back to legacy per-channel JSON like
# load_history, instead of masking JSON metadata (e.g. thinking_enabled=False)
# whenever the DB is available.
_AI_METADATA_DB_DEFAULT: dict[str, Any] = {"thinking_enabled": True, "system_instruction": None}


async def load_metadata(bot: Bot, channel_id: int) -> dict[str, Any]:
    """Load session metadata from database or JSON file with caching.

    Always returns a deep copy: callers mutating the returned dict (e.g.
    setting last_user_id) used to corrupt the cached entry on hits and not
    on misses, depending on path.

    Guarded against the in-flight-edit race exactly like load_history: an
    invalidation (e.g. a dashboard thinking_enabled toggle) landing WHILE the
    DB/JSON read below is awaiting would otherwise re-poison the cache with the
    pre-edit snapshot for up to CACHE_TTL. The generation counter is
    snapshotted before the read and re-checked before the cache store — on a
    bump, re-read (bounded); if the bumps keep coming, return the last snapshot
    WITHOUT caching it.
    """
    for attempt in range(_LOAD_HISTORY_MAX_ATTEMPTS):
        last_attempt = attempt == _LOAD_HISTORY_MAX_ATTEMPTS - 1
        now = time.time()

        # Check cache first (thread-safe), snapshotting the generation the
        # load starts from in the same locked section.
        with _cache_lock:
            generation = _cache_generations.get(channel_id, 0)
            if channel_id in _metadata_cache:
                cached_time, cached_data = _metadata_cache[channel_id]
                if now - cached_time < CACHE_TTL:
                    logger.debug("📋 Cache hit for metadata channel %s", channel_id)
                    return copy.deepcopy(cached_data)

        db_metadata: dict[str, Any] | None = None
        if DATABASE_AVAILABLE:
            db_metadata = await db.get_ai_metadata(channel_id)
            # Only treat this as a real DB hit when it is NOT the "no row"
            # synthetic default (see _AI_METADATA_DB_DEFAULT); otherwise fall
            # through to the per-channel JSON file exactly like load_history so a
            # legacy JSON metadata file is honored instead of silently ignored.
            if db_metadata and db_metadata != _AI_METADATA_DB_DEFAULT:
                # Cache a DEEP COPY rather than the live dict. Previously the
                # cache held a reference to the same object returned to the
                # caller; if any caller mutated the dict (e.g. updating
                # ``thinking_enabled`` in place), the next cache hit would
                # serve the mutated value to other callers and the DB would
                # silently diverge. Skip the store when an invalidation landed
                # during the await above (the snapshot is then pre-edit).
                with _cache_lock:
                    fresh = _cache_generations.get(channel_id, 0) == generation
                    if fresh:
                        _metadata_cache[channel_id] = (now, copy.deepcopy(db_metadata))
                if not fresh and not last_attempt:
                    continue  # re-read: the post-edit row is one SELECT away
                if not fresh:
                    logger.warning(
                        "⚠️ load_metadata for channel %s kept racing invalidations "
                        "(%d attempts) — returning uncached snapshot",
                        channel_id,
                        _LOAD_HISTORY_MAX_ATTEMPTS,
                    )
                logger.info("📋 Loaded metadata from database for channel %s", channel_id)
                return copy.deepcopy(db_metadata)

        # Fallback to JSON file. Also runs when the DB had no row (db_metadata is
        # the synthetic default), so legacy per-channel JSON metadata still loads.
        metadata = await _load_metadata_json(bot, channel_id)
        if metadata:
            with _cache_lock:
                fresh = _cache_generations.get(channel_id, 0) == generation
                if fresh:
                    _metadata_cache[channel_id] = (now, copy.deepcopy(metadata))
            if not fresh and not last_attempt:
                continue
            if not fresh:
                logger.warning(
                    "⚠️ load_metadata (JSON) for channel %s kept racing invalidations "
                    "(%d attempts) — returning uncached snapshot",
                    channel_id,
                    _LOAD_HISTORY_MAX_ATTEMPTS,
                )
            return copy.deepcopy(metadata)

        # No JSON file either: fall back to the DB's synthetic default (thinking
        # on) when the DB was available, preserving the prior contract that a
        # channel with no stored metadata still yields the default; else {}.
        return copy.deepcopy(db_metadata) if db_metadata else {}

    return {}  # unreachable: the last attempt always returns above


async def _load_metadata_json(bot: Bot, channel_id: int) -> dict[str, Any]:
    """Fallback: Load metadata from JSON file."""
    filepath = CONFIG_DIR / f"ai_metadata_{channel_id}.json"

    if not filepath.exists():
        return {}

    def _read():
        try:
            return json_loads(filepath.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.exception("Metadata read error for %s", channel_id)
            return {}

    metadata = await asyncio.get_running_loop().run_in_executor(None, _read)

    if metadata:
        logger.info("📋 Loaded metadata from JSON for channel %s", channel_id)

    return metadata if metadata else {}


async def delete_history(channel_id: int) -> bool:
    """Delete history for a channel."""
    success: bool = False
    db_failed = False

    if DATABASE_AVAILABLE:
        try:
            # delete_ai_history returns a rowcount; "success" here means the
            # delete completed without error (deleting zero rows is still a
            # successful delete), so don't key the bool on rowcount.
            await db.delete_ai_history(channel_id)
            success = True
        except aiosqlite.Error:
            db_failed = True
            logger.exception("Database delete failed for channel %s", channel_id)

    # Also try to delete JSON files (for cleanup)
    try:
        filepath = DATA_DIR / f"ai_history_{channel_id}.json"
        if filepath.exists():
            filepath.unlink()
            success = True
    except OSError:
        logger.exception("Failed to delete JSON history file")

    # Invalidate cache regardless of DB outcome — stale entries shouldn't
    # outlive a delete attempt; the next read will re-populate from DB.
    invalidate_cache(channel_id)

    # A failed DB delete means the rows survive and will resurrect on the
    # next load — never report success just because a legacy JSON file was
    # also cleaned up.
    if db_failed:
        return False
    return success


async def update_message_id(channel_id: int, message_id: int) -> None:
    """Update message ID for the last model response.

    Invalidates _history_cache so the next load picks up the new message_id;
    without this, readers within the 15-min TTL window would see message_id=None
    even after this update returned, breaking edit/resend round-trips.
    """
    if DATABASE_AVAILABLE:
        await db.update_message_id(channel_id, message_id)
        invalidate_cache(channel_id)


async def delete_message_by_id(channel_id: int, message_id: int) -> int:
    """Delete the persisted history row(s) for a Discord message_id.

    Mirrors a Discord deletion into the DB so the message stops feeding future
    prompts. Invalidates the cache so a reader inside the TTL window doesn't keep
    serving the just-deleted row. Returns rows deleted (0 if DB unavailable).
    """
    if not DATABASE_AVAILABLE:
        return 0
    deleted = await db.delete_ai_message_by_message_id(message_id, channel_id)
    invalidate_cache(channel_id)
    return deleted


async def edit_message_by_id(channel_id: int, message_id: int, content: str) -> int:
    """Update the persisted history content for a Discord message_id.

    Mirrors a Discord edit into the DB. Invalidates the cache so the new text is
    what the next load serves. Returns rows updated (0 if DB unavailable).
    """
    if not DATABASE_AVAILABLE:
        return 0
    updated = await db.update_ai_message_by_message_id(message_id, content, channel_id)
    invalidate_cache(channel_id)
    return updated


async def edit_message_by_row_id(channel_id: int, row_id: int, new_content: str) -> bool:
    """Update the persisted history content for an ``ai_history`` primary-key id.

    Dashboard edits target rows that may carry no ``message_id`` (e.g. model
    responses whose sent id was never back-filled), so this keys on the row id
    instead of the Discord message_id. Invalidates the cache so the new text is
    what the next load serves. Returns True when a row was updated (False if DB
    unavailable or no row matched the channel+id pair).
    """
    if not DATABASE_AVAILABLE:
        return False
    updated = await db.update_ai_history_content(channel_id, row_id, new_content)
    invalidate_cache(channel_id)
    return bool(updated)


async def delete_message_by_row_id(channel_id: int, row_id: int) -> bool:
    """Delete the persisted history row for an ``ai_history`` primary-key id.

    Dashboard deletes target rows that may carry no ``message_id`` (e.g. model
    responses whose sent id was never back-filled), so this keys on the row id
    instead of the Discord message_id. Invalidates the cache so the next load
    stops serving the deleted row. Returns True when a row was deleted (False
    if DB unavailable or no row matched the channel+id pair).
    """
    if not DATABASE_AVAILABLE:
        return False
    deleted = await db.delete_ai_history_row(channel_id, row_id)
    invalidate_cache(channel_id)
    return bool(deleted)


async def restore_message_by_row(channel_id: int, row: dict[str, Any]) -> str:
    """Re-insert a deleted ``ai_history`` row (undo of a dashboard delete).

    ``row`` carries the original column values (id, local_id, role, content,
    message_id, timestamp, user_id); the insert keeps the original primary-key
    id so the row returns to its original position. Returns the DB outcome:
    ``'restored'`` | ``'exists_same'`` (idempotent retry — same role AND
    content already under that id) | ``'conflict'`` (id taken by a different
    row, or the (channel_id, message_id) unique index rejected the insert) |
    ``'stale'`` (the row id predates the last force-replace rewrite of this
    channel — see ``_post_replace_min_id``: every surviving row was re-minted
    with a higher id, so "original id = original position" no longer holds
    and the restore would silently land at position 0). Rows deleted AFTER
    the rewrite carry ids >= the watermark, so legitimate undos still work.

    Invalidates the cache on ``'restored'`` AND on ``'exists_same'`` — the
    retry path is cheap to invalidate and must serve fresh rows too (the
    first attempt's invalidation could have been followed by a re-cache of a
    snapshot read mid-restore). Returns ``'conflict'`` when the database
    module is unavailable, but callers gate on DB availability first.
    """
    if not DATABASE_AVAILABLE:
        return "conflict"
    watermark = _post_replace_min_id.get(channel_id)
    row_id = row.get("id")
    if watermark is not None and isinstance(row_id, int) and row_id < watermark:
        return "stale"
    result: str = await db.restore_ai_history_row(channel_id, row)
    if result in ("restored", "exists_same"):
        invalidate_cache(channel_id)
    return result


async def copy_history(source_channel_id: int, target_channel_id: int) -> int:
    """Copy chat history from source channel to target channel.

    The full copy is performed inside a single write transaction so that a
    mid-copy failure leaves the target channel completely empty rather than
    partially populated. Without this, an interrupted copy left the target
    in an inconsistent state that the caller (move_history's rollback) would
    then mishandle.

    Returns the number of messages copied.
    """
    if not DATABASE_AVAILABLE:
        logger.error("Database not available for copy_history")
        return 0

    try:
        # Get source history
        source_history = await db.get_ai_history(source_channel_id)

        if not source_history:
            logger.warning("No history found in source channel %s", source_channel_id)
            return 0

        # Build all rows up-front so the write transaction below is brief.
        rows_to_insert = []
        for item in source_history:
            if not isinstance(item, dict):
                continue

            role = item.get("role", "user")
            # DB returns 'content' directly, not 'parts'
            content = item.get("content", "")
            message_id = item.get("message_id")
            # get_ai_history returns user_id in every row (database.py) — carry it
            # through so the copy preserves per-user attribution. Dropping it here
            # re-inserted user_id=NULL, permanently wiping attribution on a move.
            user_id = item.get("user_id")
            # A missing/malformed timestamp must not insert NULL — NULL bypasses
            # the column's CURRENT_TIMESTAMP default (database.py:409) and sorts
            # inconsistently under ORDER BY timestamp. Same rule as
            # _replace_history_db / save_ai_messages_batch.
            timestamp = _normalize_history_timestamp(item.get("timestamp")) or datetime.now(
                timezone.utc
            ).isoformat(timespec="seconds")

            if content:
                rows_to_insert.append((role, content, message_id, timestamp, user_id))

        copied = 0
        if rows_to_insert:
            # Single transaction for the entire copy: grab MAX(local_id) once,
            # assign sequential ids, executemany, commit. If any step raises,
            # the connection's implicit rollback leaves the target untouched.
            async with db.get_write_connection() as conn:
                cursor = await conn.execute(
                    "SELECT COALESCE(MAX(local_id), 0) FROM ai_history WHERE channel_id = ?",
                    (target_channel_id,),
                )
                row = await cursor.fetchone()
                next_local_id = (row[0] if row else 0) + 1

                insert_rows = []
                for role, content, message_id, timestamp, user_id in rows_to_insert:
                    insert_rows.append(
                        (
                            target_channel_id,
                            user_id,
                            role,
                            content,
                            message_id,
                            timestamp,
                            next_local_id,
                        )
                    )
                    next_local_id += 1

                # Upsert on (channel_id, message_id) to match save_ai_message /
                # save_ai_messages_batch. The partial unique index
                # idx_ai_history_msgid_unique would otherwise make a plain INSERT
                # raise IntegrityError (and roll back the whole copy) when the
                # target already holds a row with one of the source's message_ids
                # — e.g. re-running the same copy. Re-copying now updates content
                # instead of crashing. NULL message_ids are excluded by the
                # partial index, so they always insert.
                await conn.executemany(
                    """INSERT INTO ai_history
                       (channel_id, user_id, role, content, message_id, timestamp, local_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(channel_id, message_id) WHERE message_id IS NOT NULL
                       DO UPDATE SET content = excluded.content""",
                    insert_rows,
                )
                await conn.commit()
                copied = len(insert_rows)

        logger.info(
            "📋 Copied %d messages from channel %s to %s",
            copied,
            source_channel_id,
            target_channel_id,
        )

        # Invalidate cache for target channel to ensure fresh data on next read
        invalidate_cache(target_channel_id)

        return copied

    except (OSError, aiosqlite.Error):
        logger.exception("Failed to copy history")
        return 0


async def get_all_channel_ids() -> list[int]:
    """Get all channel IDs that have chat history."""
    if not DATABASE_AVAILABLE:
        return []

    try:
        return await db.get_all_ai_channel_ids()
    except (OSError, aiosqlite.Error):
        # aiosqlite.Error (== sqlite3.Error) is NOT an OSError subclass, so a
        # transient DB error ("database is locked") would otherwise escape this
        # helper instead of degrading to [] — match the sibling DB helpers.
        logger.exception("Failed to get channel IDs")
        return []


async def move_history(source_channel_id: int, target_channel_id: int) -> int:
    """Move chat history from source channel to target channel.

    This will DELETE the source history after copying.
    Returns the number of messages moved (0 if any step failed).

    Refuses the move if the target channel already has history — the previous
    behaviour copied into a non-empty target and, if the source delete then
    failed, called ``delete_ai_history(target_channel_id)`` as a "rollback"
    which would destroy the pre-existing target rows along with the copies.
    Requiring an empty target makes the operation safe regardless of failure
    point.
    """
    if not DATABASE_AVAILABLE:
        logger.error("Database not available for move_history")
        return 0

    copied = 0
    try:
        # Refuse to move into a channel that already has history. Without this
        # check, a rollback after a failed source-delete would wipe the
        # pre-existing target rows (the rollback used delete_ai_history which
        # is unconditional). Callers should clear the target explicitly first.
        try:
            existing = await db.get_ai_history_count(target_channel_id)
        except (OSError, aiosqlite.Error):
            logger.exception("Failed to read target history count for move")
            return 0
        if existing > 0:
            logger.warning(
                "Refusing move_history: target channel %s already has %d messages",
                target_channel_id,
                existing,
            )
            return 0

        # First copy the history
        copied = await copy_history(source_channel_id, target_channel_id)

        if copied > 0:
            try:
                # Delete source history
                await db.delete_ai_history(source_channel_id)
            except (OSError, aiosqlite.Error):
                # Compensating action: roll back the copy we just made. Safe
                # because we verified the target was empty above, so this
                # only deletes the rows we just inserted.
                logger.exception("Source delete failed during move; rolling back target copy")
                with contextlib.suppress(OSError, aiosqlite.Error):
                    await db.delete_ai_history(target_channel_id)
                invalidate_cache(source_channel_id)
                invalidate_cache(target_channel_id)
                return 0

            # Invalidate cache for both channels
            invalidate_cache(source_channel_id)
            invalidate_cache(target_channel_id)

            logger.info(
                "🚚 Moved %d messages from channel %s to %s (source deleted)",
                copied,
                source_channel_id,
                target_channel_id,
            )

        return copied

    except (OSError, aiosqlite.Error):
        logger.exception("Failed to move history")
        return 0


async def get_all_channels_summary() -> list[dict]:
    """Get summary of all channels with chat history.

    Returns list of dicts with channel_id and message_count.
    """
    if not DATABASE_AVAILABLE:
        return []

    try:
        return await db.get_all_ai_channels_summary()
    except (OSError, aiosqlite.Error):
        # aiosqlite.Error isn't an OSError subclass — catch both so a DB error
        # honors the documented "returns [] on failure" contract.
        logger.exception("Failed to get channels summary")
        return []


async def get_channel_history_preview(channel_id: int, limit: int = 10) -> list[dict]:
    """Get recent history preview from a specific channel.

    Returns the last N messages from the channel (very compact format).
    """
    if not DATABASE_AVAILABLE:
        return []

    try:
        history = await db.get_ai_history(channel_id)
        if not history:
            return []

        # Get last N messages
        recent = history[-limit:] if len(history) > limit else history

        preview = []
        for item in recent:
            if not isinstance(item, dict):
                continue

            role = item.get("role", "user")
            # DB returns 'content' directly, not 'parts'
            content = item.get("content", "")

            # Clean up system info prefixes for compact view using
            # module-level precompiled patterns. Skip the regex loop for
            # empty content — none of the patterns produce output, so the
            # iterations are wasted work.
            if content:
                for _pat, _repl in _PREVIEW_PATTERNS:
                    content = _pat.sub(_repl, content)
                content = content.strip()

            # Very short truncation (100 chars max)
            if len(content) > 100:
                content = content[:100] + "..."

            # Skip empty content after cleanup
            if not content:
                continue

            preview.append({"role": role, "content": content})

        return preview
    except (OSError, aiosqlite.Error):
        # aiosqlite.Error isn't an OSError subclass — catch both so a SQLite
        # error degrades to [] per the docstring instead of escaping.
        logger.exception("Failed to get history preview for %s", channel_id)
        return []


async def get_message_by_local_id(channel_id: int, local_id: int) -> dict[str, Any] | None:
    """Get a specific message from database by its local_id.

    Returns the message dict with 'role', 'parts', etc. or None if not found.
    """
    if not DATABASE_AVAILABLE:
        logger.error("Database not available for get_message_by_local_id")
        return None

    try:
        async with db.get_connection() as conn:
            cursor = await conn.execute(
                """
                SELECT role, content, message_id, timestamp, local_id
                FROM ai_history
                WHERE channel_id = ? AND local_id = ?
                """,
                (channel_id, local_id),
            )
            row = await cursor.fetchone()

            if row:
                return {
                    "role": row[0],
                    "parts": [row[1]] if row[1] else [],
                    "message_id": row[2],
                    "timestamp": row[3],
                    "local_id": row[4],
                }
            return None
    except aiosqlite.Error:
        logger.exception("Failed to get message by local_id %s", local_id)
        return None


async def get_last_model_message(channel_id: int) -> dict[str, Any] | None:
    """Get the last model message from database.

    Returns the message dict or None if not found.
    """
    if not DATABASE_AVAILABLE:
        logger.error("Database not available for get_last_model_message")
        return None

    try:
        async with db.get_connection() as conn:
            cursor = await conn.execute(
                """
                SELECT role, content, message_id, timestamp, local_id
                FROM ai_history
                WHERE channel_id = ? AND role = 'model'
                ORDER BY local_id DESC
                LIMIT 1
                """,
                (channel_id,),
            )
            row = await cursor.fetchone()

            if row:
                return {
                    "role": row[0],
                    "parts": [row[1]] if row[1] else [],
                    "message_id": row[2],
                    "timestamp": row[3],
                    "local_id": row[4],
                }
            return None
    except aiosqlite.Error:
        logger.exception("Failed to get last model message")
        return None
