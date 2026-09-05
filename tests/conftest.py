"""
Pytest Configuration and Fixtures.
Shared fixtures for all test modules.
"""

from __future__ import annotations

import asyncio
import gc
import os
import shutil
import sys
import tempfile
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))


# ==================== Live-database isolation ====================
# ``utils.database.database`` computes DB_FILE at import time and ``Database()``
# is a singleton that pins that path, so the redirect has to be in place BEFORE
# any project module is imported — here, at conftest import, not in a fixture.
# Without it every test that exercises the real singleton (schema init,
# ai_metadata, copy_history, save_history …) writes into the operator's live
# ``data/bot_database.db``: that is where the "I like pizza very much" fact and
# the 12345 / 920030 / 444444444 / 987654321 channels came from. ``setdefault``
# keeps a deliberate operator override in force. Not covered: the music queue
# sidecars (CWD-relative ``data/queue_*.json``) and the ``claude_cli_*.json``
# files (repo-anchored) — those tests isolate themselves with tmp_path.
try:
    _TEST_DB_DIR = Path(tempfile.mkdtemp(prefix="botdb-test-"))
except OSError:
    # TEMP with unusable ACLs (seen under the pre-commit hook) — fall back to a
    # gitignored spot inside the repo rather than to the live data/ directory.
    _TEST_DB_DIR = PROJECT_ROOT / ".pytest_cache" / f"db-{os.getpid()}"
    _TEST_DB_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("BOT_DATABASE_DIR", str(_TEST_DB_DIR))
if os.environ["BOT_DATABASE_DIR"] != str(_TEST_DB_DIR):
    # An operator override won; the directory just created would never be used.
    shutil.rmtree(_TEST_DB_DIR, ignore_errors=True)


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


# ==================== No live model calls from the test suite ====================


@pytest.fixture(autouse=True)
def _disable_memory_extraction_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the memory subsystems from spawning a real ``claude -p``.

    ``summarizer`` and ``consolidator`` fall back to a CLI subprocess when there
    is no Anthropic SDK client — which is the DEFAULT configuration, and the
    whole point of ``memory/extraction_backend``. Under test that means any code
    path reaching ``summarize()`` or ``consolidate()`` would spawn a real
    process, hit the network, spend subscription quota and return
    non-deterministic text. It is not hypothetical: wiring the backend up made
    ``test_compress_history_needs_compression`` start producing a genuine
    Thai-language summary of its own placeholder fixture, and added ~25s to the
    suite.

    ``sdk`` rather than ``off``: it uses whatever SDK client a test has already
    mocked onto the subsystem — so every existing test that stubs
    ``client.messages.create`` keeps working unchanged — while making the CLI
    fallback unreachable, so nothing can spawn. Tests that want the CLI branch
    set the env themselves and mock ``_run_claude_subprocess`` (see
    ``test_memory_extraction_backend.py``); tests that want NO backend at all
    set ``off``.
    """
    monkeypatch.setenv("MEMORY_EXTRACTION_BACKEND", "sdk")


# ==================== Database Cleanup ====================


@pytest.fixture(autouse=True, scope="session")
def _cleanup_db_pool_on_exit():
    """Create the isolated DB directory up front, close the pool at session end,
    then remove the directory.

    The create step makes ``DB_DIR`` / ``EXPORT_DIR`` exist before the constants
    tests look for them (the bot itself creates them lazily on the first
    ``init_schema``). Without the close, pooled aiosqlite connections keep the
    event loop alive after all tests finish, causing pytest to hang indefinitely
    on Windows — and hold the files open, which is why the removal comes last.
    """
    from utils.database.database import _ensure_db_dirs

    _ensure_db_dirs()
    yield
    try:
        from utils.database.database import Database

        Database().close_pool_sync()
    except Exception:
        pass
    if os.environ.get("BOT_DATABASE_DIR") == str(_TEST_DB_DIR):
        # Windows refuses to delete a file something still has open; collect
        # any unreferenced aiosqlite handles first. Best-effort — a leftover
        # directory in TEMP is a few hundred KB, not a correctness problem.
        gc.collect()
        shutil.rmtree(_TEST_DB_DIR, ignore_errors=True)


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
