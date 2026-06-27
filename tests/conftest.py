"""
Pytest Configuration and Fixtures.
Shared fixtures for all test modules.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))


# ==================== Async Support ====================
# Use pytest-asyncio's recommended configuration for session-scoped event loops

pytest_plugins = ("pytest_asyncio",)


@pytest.fixture(scope="session")
def event_loop_policy():
    """Return the event loop policy for the test session.

    Python 3.14 deprecated asyncio.*EventLoopPolicy (removal in 3.16).
    The warning is suppressed via pyproject.toml filterwarnings.
    We keep using DefaultEventLoopPolicy (ProactorEventLoop on Windows)
    because SelectorEventLoop blocks aiosqlite I/O.

    NOTE: pytest-asyncio also deprecated *overriding* this fixture (it wants the
    ``pytest_asyncio_loop_factories`` hook). We keep the override deliberately —
    the ProactorEventLoop requirement above is load-bearing on Windows — and
    suppress that specific PytestDeprecationWarning via pyproject filterwarnings.
    """
    return asyncio.DefaultEventLoopPolicy()


def closing_create_task_mock():
    """A drop-in replacement for ``asyncio.create_task`` for unit tests.

    Tests that exercise code which starts background loops (cog load/unload,
    periodic savers, cleanup loops) but mock out the task machinery would
    otherwise leak ``RuntimeWarning: coroutine '...' was never awaited`` because
    the real coroutine is created and then discarded. This replacement *closes*
    the coroutine it receives (silencing the warning without running it) and
    returns a ``MagicMock`` standing in for the Task, so ``.cancel()`` etc.
    still work and call assertions remain possible.

    Usage::

        with patch("asyncio.create_task", new=closing_create_task_mock()):
            await cog.cog_load()
    """
    from unittest.mock import MagicMock

    def _factory(coro: Any = None, *args: Any, **kwargs: Any) -> Any:
        if asyncio.iscoroutine(coro):
            coro.close()
        return MagicMock()

    return MagicMock(side_effect=_factory)


# ==================== Database Cleanup ====================


@pytest.fixture(autouse=True, scope="session")
def _cleanup_db_pool_on_exit():
    """Close the Database connection pool at session end.

    Without this, pooled aiosqlite connections keep the event loop alive
    after all tests finish, causing pytest to hang indefinitely on Windows.
    """
    yield
    try:
        from utils.database.database import Database

        Database().close_pool_sync()
    except Exception:
        pass


# ==================== Database Fixtures ====================

# Test-specific IDs that should NEVER appear in production database
# Using obviously fake IDs makes it easy to identify test data leaks
TEST_CHANNEL_ID = 987654321
TEST_USER_ID = 123456789
TEST_GUILD_ID = 111222333


@pytest.fixture
def temp_db() -> Generator[str]:
    """Create a temporary database file."""
    fd, path_str = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    path = Path(path_str)
    yield path_str
    if path.exists():
        path.unlink()


@pytest.fixture
def temp_dir() -> Generator[str]:
    """Create a temporary directory."""
    path_str = tempfile.mkdtemp()
    path = Path(path_str)
    yield path_str
    # Cleanup
    import shutil

    if path.exists():
        shutil.rmtree(path)


@pytest.fixture
def mock_database(temp_db: str) -> Generator[Any]:
    """Mock the database module to use a temporary database.

    This fixture patches the database singleton to prevent tests from
    writing mock data (like TEST_CHANNEL_ID) to the production database.

    Usage:
        def test_something(mock_database):
            # Database operations now use temp DB
            ...
    """
    from unittest.mock import MagicMock, patch

    # Create a mock database that doesn't write to production
    mock_db = MagicMock()
    mock_db.get_ai_history.return_value = []
    mock_db.get_ai_metadata.return_value = {"thinking_enabled": True}
    mock_db.save_ai_message.return_value = 1
    mock_db.save_ai_messages_batch.return_value = 0
    mock_db.get_ai_history_count.return_value = 0
    mock_db.save_ai_metadata.return_value = None
    mock_db.delete_ai_history.return_value = 0

    with patch("utils.database.db", mock_db), patch("cogs.ai_core.storage.db", mock_db):
        with patch("cogs.ai_core.storage.DATABASE_AVAILABLE", True):
            yield mock_db


# ==================== Mock Fixtures ====================


@pytest.fixture
def mock_bot() -> Any:
    """Create a mock Discord bot."""
    from unittest.mock import AsyncMock, MagicMock

    bot = MagicMock()
    bot.is_ready.return_value = True
    bot.is_closed.return_value = False
    bot.loop = MagicMock()  # Mock the loop instead of creating a real one
    bot.loop.is_running.return_value = True
    bot.loop.is_closed.return_value = False
    bot.voice_clients = []
    bot.guilds = []
    bot.get_channel = MagicMock(return_value=None)
    bot.get_guild = MagicMock(return_value=None)
    bot.change_presence = AsyncMock()

    return bot


@pytest.fixture
def mock_message() -> Any:
    """Create a mock Discord message."""
    from unittest.mock import AsyncMock, MagicMock

    message = MagicMock()
    message.content = "Test message"
    message.author.id = 123456789
    message.author.display_name = "TestUser"
    message.author.bot = False
    message.channel.id = 987654321
    message.guild.id = 111222333
    message.channel.send = AsyncMock()

    return message


@pytest.fixture
def mock_context() -> Any:
    """Create a mock Discord command context."""
    from unittest.mock import AsyncMock, MagicMock

    ctx = MagicMock()
    ctx.author.id = 123456789
    ctx.author.display_name = "TestUser"
    ctx.channel.id = 987654321
    ctx.guild.id = 111222333
    ctx.voice_client = None
    ctx.send = AsyncMock()
    ctx.typing = MagicMock()

    return ctx


# ==================== Environment Fixtures ====================


@pytest.fixture
def mock_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set up mock environment variables."""
    monkeypatch.setenv("DISCORD_TOKEN", "test_token")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test_anthropic_key")
    monkeypatch.setenv("GEMINI_API_KEY", "test_gemini_key")
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "test_spotify_id")
    monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", "test_spotify_secret")
    monkeypatch.setenv("CREATOR_ID", "781560793719636019")
    monkeypatch.setenv("GUILD_ID_MAIN", "123456789")


# ==================== Pytest Configuration ====================


def pytest_configure(config: pytest.Config) -> None:
    """Configure pytest with custom markers."""
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line("markers", "integration: marks tests as integration tests")
    config.addinivalue_line("markers", "requires_api: marks tests that require API keys")
