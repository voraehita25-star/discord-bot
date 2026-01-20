"""
Storage module for the AI Core.
Handles saving and loading chat history using SQLite database.
Optimized with in-memory caching for better performance.
"""

from __future__ import annotations

# ==================== Performance: Faster JSON ====================
# orjson is ~10x faster than standard json for parsing and dumping
try:
    import orjson

    def json_loads(data):
        return orjson.loads(data)

    def json_dumps(obj, **kwargs):
        # orjson returns bytes, decode to str for compatibility
        return orjson.dumps(obj).decode("utf-8")

    _ORJSON_ENABLED = True
except ImportError:
    import json

    json_loads = json.loads
    json_dumps = json.dumps
    _ORJSON_ENABLED = False

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
_history_cache: dict[int, tuple[float, list[dict[str, Any]]]] = {}
_metadata_cache: dict[int, tuple[float, dict[str, Any]]] = {}
CACHE_TTL = 300  # 5 minutes


def invalidate_cache(channel_id: int) -> None:
    """Invalidate cache for a specific channel."""
    _history_cache.pop(channel_id, None)
    _metadata_cache.pop(channel_id, None)


def invalidate_all_cache() -> None:
    """Invalidate all caches."""
    _history_cache.clear()
    _metadata_cache.clear()


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
            await _save_history_db(channel_id, chat_data, limit, new_entries)
        else:
            # Fallback to JSON
            await _save_history_json(bot, channel_id, chat_data, limit)

    except OSError as e:
        logging.error("Failed to save history: %s", e)


async def _save_history_db(
    channel_id: int,
    chat_data: dict[str, Any],
    limit: int,
    new_entries: list[dict[str, Any]] | None = None,
) -> None:
    """Save history using SQLite database with batch operations."""

    # Use explicitly provided new entries if available
    new_messages = []
    if new_entries:
        new_messages = new_entries
    else:
        # Fallback: smarter diffing logic
        history = chat_data.get("history", [])
        # Get only the last 10 messages from DB for overlap check to avoid loading full history
        db_history = await db.get_ai_history(channel_id, limit=10)

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
                new_messages = [m for m in history if m.get("timestamp", "") > last_db_ts]
            # Dangerous fallback, but better than nothing
            # If DB exists but we can't sync, we might duplicate or lose data.
            # Assuming history > db_history in size is a proxy (old buggy behavior but safer
            # than duplicating all)
            elif len(history) > len(db_history):
                new_messages = history[len(db_history) :]

    # Process new messages
    if new_messages:
        # Prepare batch data
        batch_data = []
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

            if content:
                batch_data.append(
                    {
                        "channel_id": channel_id,
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
        keep_start = 6
        keep_end = limit - keep_start

        if keep_end > 0:
            if keep_end % 2 != 0:
                keep_end -= 1

            if keep_end > len(history):
                keep_end = len(history) - keep_start
                keep_end = max(keep_end, 0)

            actual_keep_end = min(keep_end, len(history) - keep_start)
            if actual_keep_end > 0:
                history = history[:keep_start] + history[-actual_keep_end:]
                chat_data["history"] = history

    # Write to file
    def _write():
        filepath = DATA_DIR / f"ai_history_{channel_id}.json"
        temp_filepath = filepath.with_suffix(".json.tmp")

        temp_filepath.write_text(
            json_dumps(history, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        if filepath.exists():
            temp_filepath.replace(filepath)
        else:
            temp_filepath.rename(filepath)

    await bot.loop.run_in_executor(None, _write)

    # Save metadata
    metadata = {"thinking_enabled": chat_data.get("thinking_enabled", True)}

    def _write_meta():
        filepath = CONFIG_DIR / f"ai_metadata_{channel_id}.json"
        filepath.write_text(json_dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    await bot.loop.run_in_executor(None, _write_meta)


async def load_history(bot: Bot, channel_id: int) -> list[dict[str, Any]]:
    """Load chat history from database or JSON file with caching."""
    now = time.time()

    # Check cache first
    if channel_id in _history_cache:
        cached_time, cached_data = _history_cache[channel_id]
        if now - cached_time < CACHE_TTL:
            logging.debug("📖 Cache hit for channel %s (%d messages)", channel_id, len(cached_data))
            return [item.copy() for item in cached_data]  # Return copy to prevent mutation

    if DATABASE_AVAILABLE:
        # Try database
        db_history = await db.get_ai_history(channel_id)
        if db_history:
            # Convert DB format {role, content} to API format {role, parts: [...]}
            history = []
            for item in db_history:
                converted = {"role": item.get("role", "user"), "parts": [item.get("content", "")]}
                history.append(converted)

            # Update cache with converted format
            _history_cache[channel_id] = (now, history)
            logging.info(
                "📖 Loaded %d messages from database for channel %s", len(history), channel_id
            )
            return history

    # Fallback to JSON file
    history = await _load_history_json(bot, channel_id)
    if history:
        _history_cache[channel_id] = (now, history)
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

    data = await bot.loop.run_in_executor(None, _read)

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

    # Check cache first
    if channel_id in _metadata_cache:
        cached_time, cached_data = _metadata_cache[channel_id]
        if now - cached_time < CACHE_TTL:
            logging.debug("📋 Cache hit for metadata channel %s", channel_id)
            return cached_data.copy()

    if DATABASE_AVAILABLE:
        metadata = await db.get_ai_metadata(channel_id)
        if metadata:
            _metadata_cache[channel_id] = (now, metadata)
            logging.info("📋 Loaded metadata from database for channel %s", channel_id)
            return metadata

    # Fallback to JSON file
    metadata = await _load_metadata_json(bot, channel_id)
    if metadata:
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

    metadata = await bot.loop.run_in_executor(None, _read)

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

        # Copy each message to target channel
        copied = 0
        for item in source_history:
            if not isinstance(item, dict):
                continue

            role = item.get("role", "user")
            # DB returns 'content' directly, not 'parts'
            content = item.get("content", "")
            message_id = item.get("message_id")
            timestamp = item.get("timestamp")

            if content:
                await db.save_ai_message(
                    channel_id=target_channel_id,
                    role=role,
                    content=content,
                    message_id=message_id,
                    timestamp=timestamp,
                )
                copied += 1

        logging.info(
            "📋 Copied %d messages from channel %s to %s",
            copied,
            source_channel_id,
            target_channel_id,
        )
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
