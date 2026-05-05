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
    # orjson returns bytes, decode to str for compatibility
    # Note: orjson does not support ensure_ascii/indent kwargs;
    # use standard json if those are needed
    if kwargs.get("indent") or kwargs.get("ensure_ascii") is False:
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
HistoryCacheEntry = tuple[float, list[dict[str, Any]]]
MetadataCacheEntry = tuple[float, dict[str, Any]]
# Note: threading.RLock used here because cache is accessed from both async coroutines
# and synchronous thread-pool callbacks (e.g., JSON save in executor).
# CPython's GIL ensures dict operations are atomic, but the lock provides extra safety
# for multi-statement read-modify-write patterns across thread boundaries.
_cache_lock = threading.RLock()
CACHE_TTL = 900  # 15 minutes (was 5 min) - keep data in RAM longer
MAX_CACHE_SIZE = 2000  # Maximum channels to cache (was 1000)


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


def invalidate_cache(channel_id: int) -> None:
    """Invalidate cache for a specific channel."""
    with _cache_lock:
        _history_cache.pop(channel_id, None)
        _metadata_cache.pop(channel_id, None)


def invalidate_all_cache() -> None:
    """Invalidate all caches."""
    with _cache_lock:
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
            if force:
                await _replace_history_db(channel_id, chat_data, limit)
            else:
                await _save_history_db(channel_id, chat_data, limit, new_entries)
            return True
        except aiosqlite.Error as e:
            logger.error(
                "Database save failed for channel %s: %s",
                channel_id, e,
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
) -> None:
    """Replace the persisted DB history for a channel with the in-memory view.

    Used by save_history(force=True) after auto-trim mutates history.
    Runs as a single transaction: delete-all then bulk-insert.
    """
    history = chat_data.get("history", [])

    # Apply the same cap auto-trim already enforces.
    if len(history) > MAX_HISTORY_ITEMS:
        history = history[-MAX_HISTORY_ITEMS:]

    rows: list[tuple[Any, ...]] = []
    for item in history:
        if not isinstance(item, dict):
            continue
        role = item.get("role", "user")
        parts = item.get("parts", [])
        if isinstance(parts, list):
            content = "\n".join(str(p) for p in parts if p)
        else:
            content = str(parts)
        if not content:
            continue
        rows.append((
            channel_id,
            item.get("user_id"),
            role,
            content,
            item.get("message_id"),
            _normalize_history_timestamp(item.get("timestamp")),
        ))

    async with db.get_write_connection() as conn:
        await conn.execute("DELETE FROM ai_history WHERE channel_id = ?", (channel_id,))
        if rows:
            insert_rows = []
            for i, (ch, uid, role, content, mid, ts) in enumerate(rows, start=1):
                insert_rows.append((ch, uid, role, content, mid, ts, i))
            await conn.executemany(
                """INSERT INTO ai_history
                   (channel_id, user_id, role, content, message_id, timestamp, local_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                insert_rows,
            )
        await conn.commit()

    # Save metadata
    thinking_enabled = chat_data.get("thinking_enabled", True)
    await db.save_ai_metadata(channel_id=channel_id, thinking_enabled=thinking_enabled)
    invalidate_cache(channel_id)
    logger.info(
        "💾 Force-replaced %d messages for channel %s (limit=%d)",
        len(rows), channel_id, limit,
    )


async def _save_history_db(
    channel_id: int,
    chat_data: dict[str, Any],
    limit: int,
    new_entries: list[dict[str, Any]] | None = None,
) -> None:
    """Save history using SQLite database with batch operations."""

    # Fetch enough messages from DB for reliable duplicate checking
    # Using a small limit caused missed duplicates when history was long
    history = chat_data.get("history", [])
    dedup_limit = max(50, MAX_HISTORY_ITEMS or 5000) if history else 50
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
                    channel_id, len(history),
                )
                return
            new_messages = history
        elif not history:
            new_messages = []
        else:
            # Find where the DB history ends in the current history
            last_db_msg = db_history[-1]
            last_db_ts = _normalize_history_timestamp(last_db_msg.get("timestamp"))
            last_db_dt = _parse_history_timestamp(last_db_msg.get("timestamp"))

            # Look for this message in history (iterate backwards). Match
            # on timestamp + role + content-prefix so two assistant messages
            # sent in the same second (same timestamp, same role) don't get
            # collapsed into one. Without the content check, the second
            # message would be silently dropped on the next save.
            def _content_key(item: dict) -> str:
                parts = item.get("parts") or []
                if not parts:
                    return ""
                first = parts[0]
                if isinstance(first, str):
                    return first[:200]
                if isinstance(first, dict):
                    return str(first.get("text", ""))[:200]
                return str(first)[:200]

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
            # Fallback to appending everything that has a timestamp >= last_db_ts,
            # using a content-key set to dedupe within the same-second boundary.
            elif last_db_dt is not None:
                if last_db_ts is None:
                    logger.warning(
                        "Unparseable timestamp in DB for channel %s: %s — skipping diff",
                        channel_id,
                        last_db_msg.get("timestamp"),
                    )
                    new_messages = []
                else:
                    # Build dedupe set from DB entries that share the boundary timestamp
                    # so we don't re-insert messages already persisted in the same second.
                    db_boundary_keys: set[tuple[str, str]] = set()
                    for db_item in db_history:
                        db_dt = _parse_history_timestamp(db_item.get("timestamp"))
                        if db_dt is not None and db_dt >= last_db_dt:
                            db_role = db_item.get("role") or "user"
                            db_content = db_item.get("content") or ""
                            db_boundary_keys.add((db_role, db_content[:200]))

                    candidates = [
                        m for m in history
                        if (_parse_history_timestamp(m.get("timestamp")) or datetime.min.replace(tzinfo=timezone.utc)) >= last_db_dt
                    ]
                    new_messages = []
                    for m in candidates:
                        m_role = m.get("role") or "user"
                        m_key = _content_key(m)
                        if (m_role, m_key) in db_boundary_keys:
                            continue
                        db_boundary_keys.add((m_role, m_key))
                        new_messages.append(m)
            else:
                # Position-based diff is unsafe — it slices the wrong region
                # whenever history and db_history don't have aligned positions
                # (e.g. after a prune). Refuse to write rather than risk
                # corrupting persisted history with duplicates.
                logger.error(
                    "❌ history dedup failed, position-based fallback disabled to prevent corruption "
                    "(channel %s, history=%d, db=%d)",
                    channel_id, len(history), len(db_history),
                )
                return

    # Process new messages
    if new_messages:
        # Prepare batch data
        batch_data = []
        seen_content_hashes: set[str] = set()  # Track content to prevent duplicates

        # Get last message from DB to check for duplicates
        # Hash the full content (not just a prefix) so two messages that share
        # a long prefix but diverge later don't get falsely flagged as
        # duplicates and silently dropped. SHA-256 is fast enough that 500-char
        # vs full-content makes no measurable difference for chat-sized payloads.
        last_db_content_hash = None
        last_db_role = None
        if db_history:
            last_db_content_hash = hashlib.sha256(
                db_history[-1].get("content", "").encode()
            ).hexdigest()
            last_db_role = db_history[-1].get("role")

        for item in new_messages:
            if not isinstance(item, dict):
                continue

            role = item.get("role", "user")
            parts = item.get("parts", [])
            message_id = item.get("message_id")
            timestamp = _normalize_history_timestamp(item.get("timestamp"))

            # Convert parts to string
            if isinstance(parts, list):
                content = "\n".join(str(p) for p in parts if p)
            else:
                content = str(parts)

            if not content:
                continue

            # Hash the content once; reuse for both the per-batch dedupe key
            # and the just-in-DB comparison. Recomputing twice was wasteful on
            # long messages and trivially fixable.
            raw_hash = hashlib.sha256(content.encode()).hexdigest()
            content_hash = f"{role}:{raw_hash}"

            # Skip if this exact content was just in DB (immediate duplicate)
            if last_db_content_hash and raw_hash == last_db_content_hash and role == last_db_role:
                logger.warning("⚠️ Skipping duplicate message (matches last DB entry): %s...", content[:50])
                continue

            # Skip if we've already seen this content in current batch
            if content_hash in seen_content_hashes:
                logger.warning("⚠️ Skipping duplicate message (already in batch): %s...", content[:50])
                continue

            seen_content_hashes.add(content_hash)
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
                logger.debug("💾 Batch saved %d messages for channel %s", len(batch_data), channel_id)
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
    total_count = await db.get_ai_history_count(channel_id)
    if total_count > limit + 50:
        await db.prune_ai_history(channel_id, limit)
        logger.info("🧹 Pruned history for channel %s to %d messages", channel_id, limit)

    # Save metadata
    thinking_enabled = chat_data.get("thinking_enabled", True)
    await db.save_ai_metadata(channel_id=channel_id, thinking_enabled=thinking_enabled)

    # Invalidate cache after save to ensure fresh data on next read
    invalidate_cache(channel_id)


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
                    chat_data["history"] = history
                else:
                    history = history[-limit:]

    # Write to file
    def _write():
        _ensure_data_dirs()
        filepath = DATA_DIR / f"ai_history_{channel_id}.json"
        temp_filepath = filepath.with_suffix(".json.tmp")

        temp_filepath.write_text(
            json_dumps(history, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        temp_filepath.replace(filepath)  # Atomic replace, works whether target exists or not

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _write)

    # Save metadata
    metadata = {"thinking_enabled": chat_data.get("thinking_enabled", True)}

    def _write_meta():
        _ensure_data_dirs()
        filepath = CONFIG_DIR / f"ai_metadata_{channel_id}.json"
        # Atomic write: temp file + rename, mirroring the history JSON path
        # above. A direct write_text() truncates the target before writing,
        # so a process kill mid-write leaves a zero-byte metadata file with
        # no recovery path.
        temp_filepath = filepath.with_suffix(".tmp")
        temp_filepath.write_text(
            json_dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temp_filepath.replace(filepath)

    await loop.run_in_executor(None, _write_meta)


async def load_history(bot: Bot, channel_id: int) -> list[dict[str, Any]]:
    """Load chat history from database or JSON file with caching."""
    now = time.time()

    # Check cache first (thread-safe)
    with _cache_lock:
        if channel_id in _history_cache:
            cached_time, cached_data = _history_cache[channel_id]
            if now - cached_time < CACHE_TTL:
                logger.debug("📖 Cache hit for channel %s (%d messages)", channel_id, len(cached_data))
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

            # Update cache with converted format (thread-safe)
            with _cache_lock:
                _history_cache[channel_id] = (now, copy.deepcopy(history))
            logger.info(
                "📖 Loaded %d messages from database for channel %s", len(history), channel_id
            )
            return history

    # Fallback to JSON file
    history = await _load_history_json(bot, channel_id)
    if history:
        with _cache_lock:
            _history_cache[channel_id] = (now, copy.deepcopy(history))
    return history


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

            role = item.get("role", "user")
            if role not in ("user", "model"):
                continue

            history_item = {"role": role, "parts": parts}

            if "timestamp" in item:
                history_item["timestamp"] = item["timestamp"]
            if "message_id" in item:
                history_item["message_id"] = item["message_id"]

            history.append(history_item)

        return history

    return []


async def load_metadata(bot: Bot, channel_id: int) -> dict[str, Any]:
    """Load session metadata from database or JSON file with caching.

    Always returns a deep copy: callers mutating the returned dict (e.g.
    setting last_user_id) used to corrupt the cached entry on hits and not
    on misses, depending on path.
    """
    now = time.time()

    # Check cache first (thread-safe)
    with _cache_lock:
        if channel_id in _metadata_cache:
            cached_time, cached_data = _metadata_cache[channel_id]
            if now - cached_time < CACHE_TTL:
                logger.debug("📋 Cache hit for metadata channel %s", channel_id)
                return copy.deepcopy(cached_data)

    if DATABASE_AVAILABLE:
        metadata = await db.get_ai_metadata(channel_id)
        if metadata:
            with _cache_lock:
                _metadata_cache[channel_id] = (now, metadata)
            logger.info("📋 Loaded metadata from database for channel %s", channel_id)
            return copy.deepcopy(metadata)

    # Fallback to JSON file
    metadata = await _load_metadata_json(bot, channel_id)
    if metadata:
        with _cache_lock:
            _metadata_cache[channel_id] = (now, metadata)
    return copy.deepcopy(metadata) if metadata else metadata


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

    if DATABASE_AVAILABLE:
        try:
            success = await db.delete_ai_history(channel_id)  # type: ignore[assignment]
        except aiosqlite.Error:
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
            timestamp = item.get("timestamp")

            if content:
                rows_to_insert.append((role, content, message_id, timestamp))

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
                for role, content, message_id, timestamp in rows_to_insert:
                    insert_rows.append((
                        target_channel_id,
                        None,  # user_id
                        role,
                        content,
                        message_id,
                        timestamp,
                        next_local_id,
                    ))
                    next_local_id += 1

                await conn.executemany(
                    """INSERT INTO ai_history
                       (channel_id, user_id, role, content, message_id, timestamp, local_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
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
    except OSError:
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
                target_channel_id, existing,
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
                logger.exception(
                    "Source delete failed during move; rolling back target copy"
                )
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
    except OSError:
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

            # Clean up system info prefixes for compact view
            content = re.sub(r"\[System Info\].*?\n", "", content)
            content = re.sub(r"\[Voice Status\][\s\S]*?Members:.*?\n", "", content)
            content = re.sub(r"\[Chat History Access\][\s\S]*?💡.*?\n", "", content)
            content = re.sub(r"\[Requested Chat History\][\s\S]*?---\n", "", content)
            content = re.sub(r"User Message:\s*", "", content)
            content = re.sub(r"\n+", " ", content)  # Replace newlines with space
            content = content.strip()

            # Very short truncation (100 chars max)
            if len(content) > 100:
                content = content[:100] + "..."

            # Skip empty content after cleanup
            if not content:
                continue

            preview.append({"role": role, "content": content})

        return preview
    except OSError:
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
