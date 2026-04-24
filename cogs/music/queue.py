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
logger = logging.getLogger(__name__)
from pathlib import Path
from typing import Any

# Import database at module level for efficiency
try:
    from utils.database import db

    DB_AVAILABLE = True
except ImportError:
    DB_AVAILABLE = False
    db = None  # type: ignore[assignment]


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
        async with self._get_lock(guild_id):
            queue: collections.deque[dict[str, Any]] | list[Any] = self.queues.get(guild_id, [])

            if not DB_AVAILABLE or db is None:
                await asyncio.to_thread(self._save_queue_json, guild_id)
                return

            if not queue:
                await db.clear_music_queue(guild_id)
                return

            await db.save_music_queue(guild_id, list(queue))
            logger.info("💾 Saved queue for guild %s (%d tracks)", guild_id, len(queue))

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
        if DB_AVAILABLE and db is not None:
            queue = await db.load_music_queue(guild_id)
            if queue:
                self.queues[guild_id] = collections.deque(queue)
                logger.info("📂 Loaded queue (%d tracks) from database", len(queue))
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
                # Validate each queue item is a dict with required fields
                valid_items = [item for item in queue[:500] if isinstance(item, dict) and "url" in item]
                self.queues[guild_id] = collections.deque(valid_items)  # Enforce max size
                self.volumes[guild_id] = float(data.get("volume", 0.5))
                self.loops[guild_id] = bool(data.get("loop", False))
                self.mode_247[guild_id] = bool(data.get("mode_247", False))
                logger.info("📂 Loaded queue (%d tracks) from JSON", len(queue))
                await asyncio.to_thread(filepath.unlink)  # Migrate to DB
                return True
        except (OSError, json.JSONDecodeError, ValueError, TypeError):
            logger.exception("Failed to load queue")

        return False


# Global queue manager instance
queue_manager = QueueManager()
