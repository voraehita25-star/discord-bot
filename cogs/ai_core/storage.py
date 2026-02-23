"""
Storage module for the AI Core.
Handles saving and loading chat history using SQLite database.
Optimized with in-memory caching for better performance.
"""

from __future__ import annotations

import copy  # For deep copy of cached data

# ==================== Performance: Faster JSON ====================
# orjson is ~10x faster than standard json for parsing and dumping
try:
    import orjson

    def json_loads(data):
        return orjson.loads(data)

    def json_dumps(obj, **kwargs):
        # orjson returns bytes, decode to str for compatibility
        # Note: orjson does not support ensure_ascii/indent kwargs;
        # use standard json if those are needed
        if kwargs.get("indent") or kwargs.get("ensure_ascii") is False:
            import json

            return json.dumps(obj, **kwargs)
        return orjson.dumps(obj).decode("utf-8")

    _ORJSON_ENABLED = True
except ImportError:
    import json

    json_loads = json.loads
    json_dumps = json.dumps
    _ORJSON_ENABLED = False

import asyncio
import logging
import re
import time
from pathlib import Path
from typing import Any

from discord.ext.commands import Bot

from .data.constants import (
    GUILD_ID_MAIN,
    GUILD_ID_RP,
    HISTORY_LIMIT_DEFAULT,
    HISTORY_LIMIT_MAIN,
    HISTORY_LIMIT_RP,
)

# Import database module
try:
    from utils.database import db

    DATABASE_AVAILABLE = True
except ImportError:
    DATABASE_AVAILABLE = False
    db = None
    logging.warning("Database module not available, falling back to JSON storage")

# Legacy paths for fallback
DATA_DIR = Path("data")
CONFIG_DIR = Path("data/ai_config")

# Ensure data directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_DIR.mkdir(parents=True, exist_ok=True)


# ==================== In-Memory Cache ====================
# TTL cache for history to reduce database reads
# Optimized for single-user high-RAM setup (32GB+)
import threading

_history_cache: dict[int, tuple[float, list[dict[str, Any]]]] = {}
_metadata_cache: dict[int, tuple[float, dict[str, Any]]] = {}
_cache_lock = (
    threading.RLock()
)  # Reentrant lock for thread-safe cache operations (supports nested locking)
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
            # Sort by timestamp (oldest first) and remove excess
            sorted_items = sorted(_history_cache.items(), key=lambda x: x[1][0])
            excess = len(_history_cache) - MAX_CACHE_SIZE
            for k, _ in sorted_items[:excess]:
                _history_cache.pop(k, None)
                removed += 1

        # Check metadata cache
        if len(_metadata_cache) > MAX_CACHE_SIZE:
            sorted_items = sorted(_metadata_cache.items(), key=lambda x: x[1][0])
            excess = len(_metadata_cache) - MAX_CACHE_SIZE
            for k, _ in sorted_items[:excess]:
                _metadata_cache.pop(k, None)
                removed += 1

    if removed > 0:
        logging.debug("🧹 Cache size limit enforced: removed %d entries", removed)

    return removed


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
) -> None:
    """Save chat history to database."""
    if not chat_data:
        return

    try:
        # Determine limit based on Guild (optimized for memory)
        limit = HISTORY_LIMIT_DEFAULT

        channel = bot.get_channel(channel_id)
        if channel and hasattr(channel, "guild") and channel.guild:
            if channel.guild.id == GUILD_ID_MAIN:
                limit = HISTORY_LIMIT_MAIN
            elif channel.guild.id == GUILD_ID_RP:
                limit = HISTORY_LIMIT_RP

        if DATABASE_AVAILABLE:
            # Use database storage
            try:
                await _save_history_db(channel_id, chat_data, limit, new_entries)
            except Exception as e:
                logging.error("Database save failed for channel %s: %s", channel_id, e)
        else:
            # Fallback to JSON
            await _save_history_json(bot, channel_id, chat_data, limit)

    except Exception as e:
        logging.error("Failed to save history: %s", e)


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
    dedup_limit = max(50, len(history)) if history else 50
    db_history = await db.get_ai_history(channel_id, limit=dedup_limit)

    # Use explicitly provided new entries if available
    new_messages = []
    if new_entries:
        new_messages = new_entries
    else:
        # Fallback: smarter diffing logic
        history = chat_data.get("history", [])

        if not db_history:
            new_messages = history
        elif not history:
            new_messages = []
        else:
            # Find where the DB history ends in the current history
            last_db_msg = db_history[-1]
            last_db_ts = last_db_msg.get("timestamp")

            # Look for this message in history (iterate backwards)
            found_idx = -1
            for i in range(len(history) - 1, -1, -1):
                item = history[i]
                # Compare timestamps (primary) and role/content (secondary)
                if item.get("timestamp") == last_db_ts:
                    if item.get("role") == last_db_msg.get("role"):
                        found_idx = i
                        break

            if found_idx != -1:
                # We found the overlap, everything after is new
                if found_idx < len(history) - 1:
                    new_messages = history[found_idx + 1 :]
            # No overlap found? This implies disjoint history or different timestamps.
            # Fallback to appending everything that has a timestamp > last_db_ts
            elif last_db_ts:
                # NOTE: This string comparison relies on ISO 8601 format (e.g. "2024-01-15T12:00:00Z")
                # which sorts lexicographically. Non-ISO timestamps will produce incorrect results.
                new_messages = [
                    m
                    for m in history
                    if isinstance(m.get("timestamp", ""), str)
                    and isinstance(last_db_ts, str)
                    and m.get("timestamp", "") > last_db_ts
                ]
            # Dangerous fallback: length-based heuristic when timestamps can't sync.
            # Log explicitly so we can detect and investigate these cases.
            elif len(history) > len(db_history):
                # Verify first message content matches as a sanity check
                if (
                    db_history
                    and history
                    and history[0].get("parts") == db_history[0].get("parts", [db_history[0].get("content", "")])
                ):
                    new_messages = history[len(db_history):]
                    logging.warning(
                        "⚠️ History sync used length-based fallback for channel (db=%d, mem=%d, new=%d). "
                        "This may indicate timestamp issues.",
                        len(db_history),
                        len(history),
                        len(new_messages),
                    )
                else:
                    logging.warning(
                        "⚠️ History sync: length heuristic rejected — first messages don't match "
                        "(db=%d, mem=%d). Skipping to prevent data corruption.",
                        len(db_history),
                        len(history),
                    )

    # Process new messages
    if new_messages:
        # Prepare batch data
        batch_data = []
        seen_content_hashes: set[str] = set()  # Track content to prevent duplicates

        # Get last message from DB to check for duplicates
        # Use 500 chars for better duplicate detection (was 200)
        HASH_LENGTH = 500
        last_db_content = None
        if db_history:
            last_db_content = db_history[-1].get("content", "")[:HASH_LENGTH]

        for item in new_messages:
            if not isinstance(item, dict):
                continue

            role = item.get("role", "user")
            parts = item.get("parts", [])
            message_id = item.get("message_id")
            timestamp = item.get("timestamp")

            # Convert parts to string
            if isinstance(parts, list):
                content = "\n".join(str(p) for p in parts if p)
            else:
                content = str(parts)

            if not content:
                continue

            # Create content hash for duplicate detection (use first 500 chars + role)
            content_hash = f"{role}:{timestamp}:{content[:HASH_LENGTH]}"

            # Skip if this exact content was just in DB (immediate duplicate)
            if (
                last_db_content
                and content[:HASH_LENGTH] == last_db_content
                and role == db_history[-1].get("role")
            ):
                logging.warning(
                    "⚠️ Skipping duplicate message (matches last DB entry): %s...", content[:50]
                )
                continue

            # Skip if we've already seen this content in current batch
            if content_hash in seen_content_hashes:
                logging.warning(
                    "⚠️ Skipping duplicate message (already in batch): %s...", content[:50]
                )
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
            await db.save_ai_messages_batch(batch_data)
            logging.debug("💾 Batch saved %d messages for channel %s", len(batch_data), channel_id)

    # Prune if over limit
    total_count = await db.get_ai_history_count(channel_id)
    if total_count > limit:
        await db.prune_ai_history(channel_id, limit)
        logging.info("🧹 Pruned history for channel %s to %d messages", channel_id, limit)

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

            if keep_end > len(history) - keep_start:
                keep_end = len(history) - keep_start
                keep_end = max(keep_end, 0)

            actual_keep_end = min(keep_end, len(history) - keep_start)
            if actual_keep_end > 0:
                history = history[:keep_start] + history[-actual_keep_end:]
                chat_data["history"] = history
            else:
                # Fallback: simple tail truncation when smart pruning can't work
                history = history[-limit:]
                chat_data["history"] = history

    # Write to file
    def _write():
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
        filepath = CONFIG_DIR / f"ai_metadata_{channel_id}.json"
        filepath.write_text(json_dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    await loop.run_in_executor(None, _write_meta)


async def load_history(bot: Bot, channel_id: int) -> list[dict[str, Any]]:
    """Load chat history from database or JSON file with caching."""
    now = time.time()

    # Check cache first (thread-safe)
    with _cache_lock:
        if channel_id in _history_cache:
            cached_time, cached_data = _history_cache[channel_id]
            if now - cached_time < CACHE_TTL:
                logging.debug(
                    "📖 Cache hit for channel %s (%d messages)", channel_id, len(cached_data)
                )
                # Use deep copy to prevent mutation of cached nested objects
                return copy.deepcopy(cached_data)

    if DATABASE_AVAILABLE:
        # Try database
        db_history = await db.get_ai_history(channel_id)
        if db_history:
            # Convert DB format {role, content} to API format {role, parts: [...]}
            history = []
            for item in db_history:
                converted = {"role": item.get("role", "user"), "parts": [item.get("content", "")]}
                history.append(converted)

            # Update cache with converted format (thread-safe)
            with _cache_lock:
                _history_cache[channel_id] = (now, copy.deepcopy(history))
            logging.info(
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
        except (OSError, ValueError) as e:
            logging.error("File read error for %s: %s", filepath, e)
            return None

    data = await asyncio.get_running_loop().run_in_executor(None, _read)

    if data:
        logging.info("📖 Loaded %d messages from JSON for channel %s", len(data), channel_id)

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
    """Load session metadata from database or JSON file with caching."""
    now = time.time()

    # Check cache first (thread-safe)
    with _cache_lock:
        if channel_id in _metadata_cache:
            cached_time, cached_data = _metadata_cache[channel_id]
            if now - cached_time < CACHE_TTL:
                logging.debug("📋 Cache hit for metadata channel %s", channel_id)
                return copy.deepcopy(cached_data)

    if DATABASE_AVAILABLE:
        metadata = await db.get_ai_metadata(channel_id)
        if metadata:
            with _cache_lock:
                _metadata_cache[channel_id] = (now, metadata)
            logging.info("📋 Loaded metadata from database for channel %s", channel_id)
            return metadata

    # Fallback to JSON file
    metadata = await _load_metadata_json(bot, channel_id)
    if metadata:
        with _cache_lock:
            _metadata_cache[channel_id] = (now, metadata)
    return metadata


async def _load_metadata_json(bot: Bot, channel_id: int) -> dict[str, Any]:
    """Fallback: Load metadata from JSON file."""
    filepath = CONFIG_DIR / f"ai_metadata_{channel_id}.json"

    if not filepath.exists():
        return {}

    def _read():
        try:
            return json_loads(filepath.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            logging.error("Metadata read error for %s: %s", channel_id, e)
            return {}

    metadata = await asyncio.get_running_loop().run_in_executor(None, _read)

    if metadata:
        logging.info("📋 Loaded metadata from JSON for channel %s", channel_id)

    return metadata if metadata else {}


async def delete_history(channel_id: int) -> bool:
    """Delete history for a channel."""
    success = False

    if DATABASE_AVAILABLE:
        success = await db.delete_ai_history(channel_id)

    # Also try to delete JSON files (for cleanup)
    try:
        filepath = DATA_DIR / f"ai_history_{channel_id}.json"
        if filepath.exists():
            filepath.unlink()
            success = True
    except OSError as e:
        logging.error("Failed to delete JSON history file: %s", e)

    # Invalidate cache
    invalidate_cache(channel_id)

    return success


async def update_message_id(channel_id: int, message_id: int) -> None:
    """Update message ID for the last model response."""
    if DATABASE_AVAILABLE:
        await db.update_message_id(channel_id, message_id)


async def copy_history(source_channel_id: int, target_channel_id: int) -> int:
    """Copy chat history from source channel to target channel.

    Returns the number of messages copied.
    """
    if not DATABASE_AVAILABLE:
        logging.error("Database not available for copy_history")
        return 0

    try:
        # Get source history
        source_history = await db.get_ai_history(source_channel_id)

        if not source_history:
            logging.warning("No history found in source channel %s", source_channel_id)
            return 0

        # Copy messages in batch for performance instead of one-by-one
        batch_messages = []
        for item in source_history:
            if not isinstance(item, dict):
                continue

            role = item.get("role", "user")
            # DB returns 'content' directly, not 'parts'
            content = item.get("content", "")
            message_id = item.get("message_id")
            timestamp = item.get("timestamp")

            if content:
                batch_messages.append(
                    {
                        "channel_id": target_channel_id,
                        "role": role,
                        "content": content,
                        "message_id": message_id,
                        "timestamp": timestamp,
                        "user_id": None,
                    }
                )

        copied = 0
        if batch_messages:
            copied = await db.save_ai_messages_batch(batch_messages)

        logging.info(
            "📋 Copied %d messages from channel %s to %s",
            copied,
            source_channel_id,
            target_channel_id,
        )

        # Invalidate cache for target channel to ensure fresh data on next read
        invalidate_cache(target_channel_id)

        return copied

    except OSError as e:
        logging.error("Failed to copy history: %s", e)
        return 0


async def get_all_channel_ids() -> list[int]:
    """Get all channel IDs that have chat history."""
    if not DATABASE_AVAILABLE:
        return []

    try:
        return await db.get_all_ai_channel_ids()
    except OSError as e:
        logging.error("Failed to get channel IDs: %s", e)
        return []


async def move_history(source_channel_id: int, target_channel_id: int) -> int:
    """Move chat history from source channel to target channel.

    This will DELETE the source history after copying.
    Returns the number of messages moved.
    """
    if not DATABASE_AVAILABLE:
        logging.error("Database not available for move_history")
        return 0

    try:
        # First copy the history
        copied = await copy_history(source_channel_id, target_channel_id)

        if copied > 0:
            # Delete source history
            await db.delete_ai_history(source_channel_id)

            # Invalidate cache for both channels
            invalidate_cache(source_channel_id)
            invalidate_cache(target_channel_id)

            logging.info(
                "🚚 Moved %d messages from channel %s to %s (source deleted)",
                copied,
                source_channel_id,
                target_channel_id,
            )

        return copied

    except OSError as e:
        logging.error("Failed to move history: %s", e)
        return 0


async def get_all_channels_summary() -> list[dict]:
    """Get summary of all channels with chat history.

    Returns list of dicts with channel_id and message_count.
    """
    if not DATABASE_AVAILABLE:
        return []

    try:
        channel_ids = await db.get_all_ai_channel_ids()
        summaries = []

        for cid in channel_ids:
            count = await db.get_ai_history_count(cid)
            summaries.append({"channel_id": cid, "message_count": count})

        return summaries
    except OSError as e:
        logging.error("Failed to get channels summary: %s", e)
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
    except OSError as e:
        logging.error("Failed to get history preview for %s: %s", channel_id, e)
        return []


async def get_message_by_local_id(channel_id: int, local_id: int) -> dict[str, Any] | None:
    """Get a specific message from database by its local_id.

    Returns the message dict with 'role', 'parts', etc. or None if not found.
    """
    if not DATABASE_AVAILABLE:
        logging.error("Database not available for get_message_by_local_id")
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
    except Exception as e:
        logging.error("Failed to get message by local_id %s: %s", local_id, e)
        return None


async def get_last_model_message(channel_id: int) -> dict[str, Any] | None:
    """Get the last model message from database.

    Returns the message dict or None if not found.
    """
    if not DATABASE_AVAILABLE:
        logging.error("Database not available for get_last_model_message")
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
    except Exception as e:
        logging.error("Failed to get last model message: %s", e)
        return None
