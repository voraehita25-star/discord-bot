"""
Queue Manager Module.
Handles music queue persistence and management.
"""

from __future__ import annotations

import asyncio
import collections
import contextlib
import json
import logging
from pathlib import Path
from typing import Any

# Import database at module level for efficiency
try:
    from utils.database import db

    DB_AVAILABLE = True
except ImportError:
    DB_AVAILABLE = False
    db = None  # type: ignore[assignment]


logger = logging.getLogger(__name__)

# Maximum queue size to prevent memory issues
MAX_QUEUE_SIZE = 500


class QueueManager:
    """Manages music queue persistence and operations."""

    def __init__(self):
        self.queues: dict[int, collections.deque[dict[str, Any]]] = {}
        self.loops: dict[int, bool] = {}
        self.volumes: dict[int, float] = {}
        self.mode_247: dict[int, bool] = {}
        self.current_track: dict[int, dict[str, Any]] = {}
        self._locks: dict[int, asyncio.Lock] = {}

    def _get_lock(self, guild_id: int) -> asyncio.Lock:
        """Get or create an asyncio.Lock for a guild to serialize queue writes."""
        return self._locks.setdefault(guild_id, asyncio.Lock())

    def get_queue(self, guild_id: int) -> collections.deque[dict[str, Any]]:
        """Get or create queue for a guild."""
        if guild_id not in self.queues:
            self.queues[guild_id] = collections.deque()
        return self.queues[guild_id]

    def add_to_queue(self, guild_id: int, track: dict[str, Any]) -> int:
        """Add a track to the queue. Returns queue position, or -1 if queue is full."""
        queue = self.get_queue(guild_id)
        if len(queue) >= MAX_QUEUE_SIZE:
            logger.warning("Queue full for guild %s (max %d tracks)", guild_id, MAX_QUEUE_SIZE)
            return -1  # Queue is full
        queue.append(track)
        return len(queue)

    def is_queue_full(self, guild_id: int) -> bool:
        """Check if queue is at maximum capacity."""
        return len(self.get_queue(guild_id)) >= MAX_QUEUE_SIZE

    def get_next(self, guild_id: int) -> dict[str, Any] | None:
        """Get and remove the next track from queue."""
        queue = self.get_queue(guild_id)
        if not queue:
            return None
        return queue.popleft()

    def peek_next(self, guild_id: int) -> dict[str, Any] | None:
        """Peek at the next track without removing it."""
        queue = self.get_queue(guild_id)
        return queue[0] if queue else None

    def clear_queue(self, guild_id: int) -> int:
        """Clear the queue. Returns number of tracks removed."""
        queue = self.get_queue(guild_id)
        count = len(queue)
        queue.clear()
        return count

    def shuffle_queue(self, guild_id: int) -> bool:
        """Shuffle the queue. Returns True if shuffled."""
        import random

        queue = self.get_queue(guild_id)
        if len(queue) < 2:
            return False
        # Convert to list for O(n) shuffle — random.shuffle on deque is O(n²)
        items = list(queue)
        random.shuffle(items)
        queue.clear()
        queue.extend(items)
        return True

    def remove_track(self, guild_id: int, position: int) -> dict[str, Any] | None:
        """Remove a track by position (1-indexed). Returns removed track."""
        queue = self.get_queue(guild_id)
        if 1 <= position <= len(queue):
            idx = position - 1
            track = queue[idx]
            del queue[idx]
            return track
        return None

    def is_looping(self, guild_id: int) -> bool:
        """Check if looping is enabled."""
        return self.loops.get(guild_id, False)

    def toggle_loop(self, guild_id: int) -> bool:
        """Toggle loop mode. Returns new state."""
        self.loops[guild_id] = not self.loops.get(guild_id, False)
        return self.loops[guild_id]

    def get_volume(self, guild_id: int) -> float:
        """Get volume for guild."""
        return self.volumes.get(guild_id, 0.5)

    def set_volume(self, guild_id: int, volume: float) -> None:
        """Set volume for guild (0.0 - 2.0)."""
        self.volumes[guild_id] = max(0.0, min(2.0, volume))

    def is_247_mode(self, guild_id: int) -> bool:
        """Check if 24/7 mode is enabled."""
        return self.mode_247.get(guild_id, False)

    def toggle_247_mode(self, guild_id: int) -> bool:
        """Toggle 24/7 mode. Returns new state."""
        self.mode_247[guild_id] = not self.mode_247.get(guild_id, False)
        return self.mode_247[guild_id]

    def cleanup_guild(self, guild_id: int) -> None:
        """Clean up all data for a guild (except 24/7 mode)."""
        self.queues.pop(guild_id, None)
        self.loops.pop(guild_id, None)
        self.current_track.pop(guild_id, None)
        # Don't remove mode_247 so setting persists

    async def save_queue(self, guild_id: int) -> None:
        """Save queue to database for persistence."""
        # Snapshot under the lock so a concurrent `add_to_queue` can't
        # mutate the deque mid-iteration, then release the lock BEFORE
        # the slow I/O call. Holding the lock across `db.save_music_queue`
        # serialises queue mutations behind disk/network I/O and stalls
        # playback callbacks.
        async with self._get_lock(guild_id):
            queue_snapshot = list(self.queues.get(guild_id, []))

        if not DB_AVAILABLE or db is None:
            await asyncio.to_thread(self._save_queue_json, guild_id)
            return

        if not queue_snapshot:
            await db.clear_music_queue(guild_id)
            return

        await db.save_music_queue(guild_id, queue_snapshot)
        logger.info("💾 Saved queue for guild %s (%d tracks)", guild_id, len(queue_snapshot))

    def _save_queue_json(self, guild_id: int) -> None:
        """Legacy JSON save as fallback with atomic write pattern."""
        queue: collections.deque[dict[str, Any]] | list[Any] = self.queues.get(guild_id, [])
        filepath = Path(f"data/queue_{guild_id}.json")

        if not queue:
            if filepath.exists():
                with contextlib.suppress(OSError):
                    filepath.unlink()  # sync method, blocking OK for legacy fallback
            return

        data = {
            "queue": list(queue),
            "volume": self.volumes.get(guild_id, 0.5),
            "loop": self.loops.get(guild_id, False),
            "mode_247": self.mode_247.get(guild_id, False),
        }

        # Ensure data/ exists. On a fresh install the directory may not
        # have been created yet, and write_text would raise FileNotFoundError.
        with contextlib.suppress(OSError):
            filepath.parent.mkdir(parents=True, exist_ok=True)

        # Define temp_path before try block to ensure it's always bound
        temp_path = filepath.with_suffix(".tmp")
        try:
            # Atomic write pattern: write to temp file, then rename
            temp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            temp_path.replace(filepath)  # Atomic on most filesystems
        except OSError:
            logger.exception("Failed to save queue for guild %s", guild_id)
            # Clean up temp file on failure
            with contextlib.suppress(OSError):
                temp_path.unlink()  # sync method, blocking OK for legacy fallback

    async def load_queue(self, guild_id: int) -> bool:
        """Load queue from database. Returns True if loaded."""
        # Hold the per-guild lock for the entire load so a concurrent
        # save_queue can't race with us and partially overwrite. Without
        # this, a save scheduled mid-load could land between the DB fetch
        # and the deque assignment and torpedo state.
        async with self._get_lock(guild_id):
            if DB_AVAILABLE and db is not None:
                queue = await db.load_music_queue(guild_id)
                if queue:
                    # Reject malformed entries — a row with no url / falsy url
                    # would be stored unchanged and then crash play_next().
                    valid = [item for item in queue if isinstance(item, dict) and item.get("url")]
                    self.queues[guild_id] = collections.deque(valid)
                    # The DB schema only stores the queue itself, not
                    # per-guild volume/loop/24-7 settings. If a leftover
                    # JSON sidecar exists (from before migration or set by
                    # the JSON-only fallback path), pick those settings up
                    # so they aren't silently reset to defaults each restart.
                    settings_path = Path(f"data/queue_{guild_id}.json")
                    if await asyncio.to_thread(settings_path.exists):
                        try:
                            content = await asyncio.to_thread(
                                settings_path.read_text, encoding="utf-8"
                            )
                            settings_data = json.loads(content)
                            if isinstance(settings_data, dict):
                                self.volumes[guild_id] = float(settings_data.get("volume", 0.5))
                                self.loops[guild_id] = bool(settings_data.get("loop", False))
                                self.mode_247[guild_id] = bool(settings_data.get("mode_247", False))
                        except (OSError, json.JSONDecodeError, ValueError, TypeError):
                            logger.debug(
                                "Settings sidecar unreadable for guild %s — using defaults",
                                guild_id,
                            )
                    logger.info(
                        "📂 Loaded queue (%d tracks, %d valid) from database",
                        len(queue),
                        len(valid),
                    )
                    return True

            # Fallback to JSON
            filepath = Path(f"data/queue_{guild_id}.json")
            if not await asyncio.to_thread(filepath.exists):
                return False

            try:
                # Use asyncio.to_thread to avoid blocking the event loop
                content = await asyncio.to_thread(filepath.read_text, encoding="utf-8")
                data = json.loads(content)
                # Validate expected JSON structure
                if not isinstance(data, dict) or not isinstance(data.get("queue"), list):
                    logger.warning("Invalid queue file format for guild %s — skipping", guild_id)
                    return False
                queue = data["queue"]
                if queue:
                    # Validate each queue item is a dict with non-empty URL.
                    # Previously empty/None URLs were accepted because the
                    # check only required the key to exist.
                    valid_items = [
                        item for item in queue[:500] if isinstance(item, dict) and item.get("url")
                    ]
                    if not valid_items:
                        # Nothing to migrate — leave the JSON file alone so a
                        # future bug fix can recover whatever was in there.
                        return False
                    self.queues[guild_id] = collections.deque(valid_items)  # Enforce max size
                    self.volumes[guild_id] = float(data.get("volume", 0.5))
                    self.loops[guild_id] = bool(data.get("loop", False))
                    self.mode_247[guild_id] = bool(data.get("mode_247", False))
                    logger.info("📂 Loaded queue (%d tracks) from JSON", len(valid_items))
                    # Only delete the JSON migration file AFTER confirming
                    # the new state was persisted to DB — a crash between
                    # populating self.queues and deleting the file would
                    # otherwise lose the queue silently.
                    if DB_AVAILABLE and db is not None:
                        try:
                            await db.save_music_queue(guild_id, valid_items)
                        except Exception:
                            logger.exception(
                                "Failed to migrate JSON queue to DB for guild %s; "
                                "keeping JSON file as fallback",
                                guild_id,
                            )
                            return True
                        # DB save succeeded — safe to remove JSON.
                        await asyncio.to_thread(filepath.unlink)
                        return True
                    # No DB available — keep the JSON file as the only
                    # persistence layer rather than deleting it. Otherwise
                    # the queue is held only in memory and is lost on the
                    # next restart.
                    logger.info(
                        "📂 Keeping JSON queue file for guild %s (no DB available)",
                        guild_id,
                    )
                    return True
            except (OSError, json.JSONDecodeError, ValueError, TypeError):
                logger.exception("Failed to load queue")

            return False


# Global queue manager instance
queue_manager = QueueManager()
