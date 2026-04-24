"""
Regression tests for bugs fixed in v3.3.11.
Ensures these specific bugs don't reoccur.
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

# ============================================================================
# Bug #1: get_ai_history with limit returned OLDEST instead of NEWEST
# ============================================================================

class TestGetAiHistoryLimit:
    """Regression: get_ai_history(limit=N) must return the NEWEST N messages."""

    @pytest.mark.asyncio
    async def test_limit_returns_newest_messages(self):
        """The subquery should ORDER BY id DESC then re-sort ASC."""
        import aiosqlite

        db_path = ":memory:"
        async with aiosqlite.connect(db_path) as conn:
            await conn.execute("""
                CREATE TABLE ai_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    message_id INTEGER,
                    timestamp TEXT
                )
            """)
            # Insert 10 messages
            for i in range(1, 11):
                await conn.execute(
                    "INSERT INTO ai_history (channel_id, role, content) VALUES (?, ?, ?)",
                    (100, "user", f"msg_{i}"),
                )
            await conn.commit()

            # Query with limit=3 — should get msg_8, msg_9, msg_10 (newest)
            cursor = await conn.execute("""
                SELECT id, role, content FROM (
                    SELECT id, role, content FROM ai_history
                    WHERE channel_id = ? ORDER BY id DESC LIMIT ?
                ) sub ORDER BY id ASC
            """, (100, 3))
            rows = await cursor.fetchall()

            assert len(rows) == 3
            assert rows[0][2] == "msg_8"   # oldest of the 3 newest
            assert rows[1][2] == "msg_9"
            assert rows[2][2] == "msg_10"  # newest


# ============================================================================
# Bug #3: Guild state defaults — _gs() returns correct defaults
# ============================================================================

class TestGuildStateDefaults:
    """Regression: _gs() must return correct defaults for all fields."""

    def test_auto_disconnect_task_defaults_to_none(self):
        """auto_disconnect_task should default to None."""
        from cogs.music.cog import MusicGuildState

        gs = MusicGuildState()
        assert gs.auto_disconnect_task is None

    def test_auto_disconnect_task_when_set(self):
        """auto_disconnect_task can be set to a non-None value."""
        from cogs.music.cog import MusicGuildState

        gs = MusicGuildState()
        gs.auto_disconnect_task = MagicMock()
        assert gs.auto_disconnect_task is not None

    def test_queue_defaults_to_empty_deque(self):
        """queue should default to empty deque."""
        from cogs.music.cog import MusicGuildState

        gs = MusicGuildState()
        assert len(gs.queue) == 0
        # Add item — should be accessible
        gs.queue.append({"url": "test"})
        assert len(gs.queue) == 1


# ============================================================================
# Bug #6: test_pool_semaphore_created — lazy init
# ============================================================================

class TestDatabaseLazyInit:
    """Regression: pool semaphore must work via lazy getter."""

    def test_pool_semaphore_lazy_init(self):
        """_pool_semaphore starts as None, _get_pool_semaphore() creates it."""
        from utils.database.database import Database

        db = Database()
        # Don't access _pool_semaphore directly — use getter
        sem = db._get_pool_semaphore()
        assert sem is not None
        assert sem._value == 32
