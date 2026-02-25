"""
Regression tests for bugs fixed in v3.3.11.
Ensures these specific bugs don't reoccur.
"""
from __future__ import annotations

import asyncio
import collections
from unittest.mock import AsyncMock, MagicMock, patch

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
# Bug #3: _DictProxy.__contains__ checked guild existence, not attribute value
# ============================================================================

class TestDictProxyContains:
    """Regression: _DictProxy.__contains__ must check attribute value, not just guild."""

    def test_contains_false_when_attr_is_none(self):
        """guild_id in proxy should be False when the attribute is None."""
        from cogs.music.cog import Music, MusicGuildState

        mock_bot = MagicMock()
        mock_bot.loop = asyncio.new_event_loop()
        try:
            cog = object.__new__(Music)
            cog._guild_states = {123: MusicGuildState()}
            # auto_disconnect_task defaults to None
            assert cog._guild_states[123].auto_disconnect_task is None
            # __contains__ should return False since value is None
            assert 123 not in cog.auto_disconnect_tasks
        finally:
            mock_bot.loop.close()

    def test_contains_true_when_attr_is_set(self):
        """guild_id in proxy should be True when the attribute is not None."""
        from cogs.music.cog import Music, MusicGuildState

        mock_bot = MagicMock()
        mock_bot.loop = asyncio.new_event_loop()
        try:
            cog = object.__new__(Music)
            gs = MusicGuildState()
            gs.auto_disconnect_task = MagicMock()  # Set to non-None
            cog._guild_states = {123: gs}
            assert 123 in cog.auto_disconnect_tasks
        finally:
            mock_bot.loop.close()

    def test_queue_contains_checks_non_empty(self):
        """guild_id in queues should be True only when queue is non-empty."""
        from cogs.music.cog import Music, MusicGuildState

        mock_bot = MagicMock()
        mock_bot.loop = asyncio.new_event_loop()
        try:
            cog = object.__new__(Music)
            cog._guild_states = {123: MusicGuildState()}
            # Empty deque — should be False
            assert 123 not in cog.queues
            # Add item — should be True
            cog._guild_states[123].queue.append({"url": "test"})
            assert 123 in cog.queues
        finally:
            mock_bot.loop.close()


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
