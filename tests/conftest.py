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
    """Return the event loop policy for the test session."""
    return asyncio.DefaultEventLoopPolicy()


# ==================== Database Fixtures ====================

# Test-specific IDs that should NEVER appear in production database
# Using obviously fake IDs makes it easy to identify test data leaks
TEST_CHANNEL_ID = 987654321
TEST_USER_ID = 123456789
TEST_GUILD_ID = 111222333


# Cache guardrails module reference once to avoid repeated import overhead
# (guardrails import chain takes ~900ms on first import)
_guardrails_module = None
try:
    from cogs.ai_core.processing import guardrails as _guardrails_module
except ImportError:
    pass


@pytest.fixture(autouse=True)
def _reset_guardrails_state():
    """Reset module-level mutable state in guardrails to prevent test pollution.
    
    The guardrails module has a module-level `unrestricted_channels` set that
    persists across tests. Tests that call set_unrestricted() can leak state
    into subsequent tests, causing spurious failures.
    """
    yield
    if _guardrails_module is not None and hasattr(_guardrails_module, "unrestricted_channels"):
        _guardrails_module.unrestricted_channels.clear()


@pytest.fixture
def temp_db() -> Generator[str, None, None]:
    """Create a temporary database file."""
    fd, path_str = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    path = Path(path_str)
    yield path_str
    if path.exists():
        path.unlink()


@pytest.fixture
def temp_dir() -> Generator[str, None, None]:
    """Create a temporary directory."""
    path_str = tempfile.mkdtemp()
    path = Path(path_str)
    yield path_str
    # Cleanup
    import shutil

    if path.exists():
        shutil.rmtree(path)


@pytest.fixture
def mock_database(temp_db: str) -> Generator[Any, None, None]:
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

    loop = asyncio.new_event_loop()
    bot = MagicMock()
    bot.is_ready.return_value = True
    bot.is_closed.return_value = False
    bot.loop = loop
    bot.voice_clients = []
    bot.guilds = []
    bot.get_channel = MagicMock(return_value=None)
    bot.get_guild = MagicMock(return_value=None)
    bot.change_presence = AsyncMock()

    yield bot

    # Cleanup: Close the event loop
    loop.close()


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
