"""Tests for debug_commands cog."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from discord.ext import commands


class TestAIDebugCog:
    """Tests for AIDebug cog initialization."""

    def test_cog_creation(self):
        """Test AIDebug cog can be created."""
        from cogs.ai_core.commands.debug_commands import AIDebug

        mock_bot = MagicMock(spec=commands.Bot)
        cog = AIDebug(mock_bot)

        assert cog.bot == mock_bot
        assert cog.logger is not None

    def test_cog_has_ai_debug_command(self):
        """Test cog has ai_debug command."""
        from cogs.ai_core.commands.debug_commands import AIDebug

        mock_bot = MagicMock(spec=commands.Bot)
        cog = AIDebug(mock_bot)

        assert hasattr(cog, "ai_debug")

    def test_cog_has_ai_perf_command(self):
        """Test cog has ai_perf command."""
        from cogs.ai_core.commands.debug_commands import AIDebug

        mock_bot = MagicMock(spec=commands.Bot)
        cog = AIDebug(mock_bot)

        assert hasattr(cog, "ai_perf")

    def test_cog_has_ai_cache_clear_command(self):
        """Test cog has ai_cache_clear command."""
        from cogs.ai_core.commands.debug_commands import AIDebug

        mock_bot = MagicMock(spec=commands.Bot)
        cog = AIDebug(mock_bot)

        assert hasattr(cog, "ai_cache_clear")


class TestGetChatManager:
    """Tests for _get_chat_manager method."""

    def test_get_chat_manager_no_cog(self):
        """Test _get_chat_manager when no AI cog."""
        from cogs.ai_core.commands.debug_commands import AIDebug

        mock_bot = MagicMock(spec=commands.Bot)
        mock_bot.get_cog.return_value = None

        cog = AIDebug(mock_bot)
        result = cog._get_chat_manager()

        assert result is None

    def test_get_chat_manager_with_cog(self):
        """Test _get_chat_manager when AI cog exists."""
        from cogs.ai_core.commands.debug_commands import AIDebug

        mock_bot = MagicMock(spec=commands.Bot)
        mock_ai_cog = MagicMock()
        mock_ai_cog.chat_manager = MagicMock()
        mock_bot.get_cog.return_value = mock_ai_cog

        cog = AIDebug(mock_bot)
        result = cog._get_chat_manager()

        assert result == mock_ai_cog.chat_manager


class TestAIDebugCommand:
    """Tests for ai_debug command."""

    @pytest.mark.asyncio
    async def test_ai_debug_no_session(self):
        """Test ai_debug with no session."""
        from cogs.ai_core.commands.debug_commands import AIDebug

        mock_bot = MagicMock(spec=commands.Bot)
        mock_bot.get_cog.return_value = None

        cog = AIDebug(mock_bot)

        mock_ctx = MagicMock()
        mock_ctx.send = AsyncMock()
        mock_ctx.channel = MagicMock()
        mock_ctx.channel.id = 123
        mock_ctx.message = MagicMock()
        mock_ctx.message.reference = None

        await cog.ai_debug.callback(cog, mock_ctx)

        mock_ctx.send.assert_called_once()
        # Should have sent an embed
        call_args = mock_ctx.send.call_args
        assert "embed" in call_args.kwargs or len(call_args.args) > 0

    @pytest.mark.asyncio
    async def test_ai_debug_with_chat_manager(self):
        """Test ai_debug with chat manager."""
        from cogs.ai_core.commands.debug_commands import AIDebug

        mock_bot = MagicMock(spec=commands.Bot)
        mock_chat_manager = MagicMock()
        mock_chat_manager.chats = {}
        mock_chat_manager.get_performance_stats.return_value = {}

        mock_ai_cog = MagicMock()
        mock_ai_cog.chat_manager = mock_chat_manager
        mock_bot.get_cog.return_value = mock_ai_cog

        cog = AIDebug(mock_bot)

        mock_ctx = MagicMock()
        mock_ctx.send = AsyncMock()
        mock_ctx.channel = MagicMock()
        mock_ctx.channel.id = 123
        mock_ctx.message = MagicMock()
        mock_ctx.message.reference = None

        await cog.ai_debug.callback(cog, mock_ctx)

        mock_ctx.send.assert_called_once()


class TestAIPerfCommand:
    """Tests for ai_perf command."""

    @pytest.mark.asyncio
    async def test_ai_perf_no_chat_manager(self):
        """Test ai_perf when no chat manager."""
        from cogs.ai_core.commands.debug_commands import AIDebug

        mock_bot = MagicMock(spec=commands.Bot)
        mock_bot.get_cog.return_value = None

        cog = AIDebug(mock_bot)

        mock_ctx = MagicMock()
        mock_ctx.send = AsyncMock()

        await cog.ai_perf.callback(cog, mock_ctx)

        mock_ctx.send.assert_called_once()
        assert "❌" in mock_ctx.send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_ai_perf_with_stats(self):
        """Test ai_perf with performance stats."""
        from cogs.ai_core.commands.debug_commands import AIDebug

        mock_bot = MagicMock(spec=commands.Bot)
        mock_chat_manager = MagicMock()
        mock_chat_manager.get_performance_stats.return_value = {
            "test": {
                "avg_ms": 100.0,
                "min_ms": 50.0,
                "max_ms": 150.0,
                "count": 10,
            }
        }

        mock_ai_cog = MagicMock()
        mock_ai_cog.chat_manager = mock_chat_manager
        mock_bot.get_cog.return_value = mock_ai_cog

        cog = AIDebug(mock_bot)

        mock_ctx = MagicMock()
        mock_ctx.send = AsyncMock()

        await cog.ai_perf.callback(cog, mock_ctx)

        mock_ctx.send.assert_called_once()
        assert "⚡" in mock_ctx.send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_ai_perf_empty_stats(self):
        """Test ai_perf with empty stats."""
        from cogs.ai_core.commands.debug_commands import AIDebug

        mock_bot = MagicMock(spec=commands.Bot)
        mock_chat_manager = MagicMock()
        mock_chat_manager.get_performance_stats.return_value = {}

        mock_ai_cog = MagicMock()
        mock_ai_cog.chat_manager = mock_chat_manager
        mock_bot.get_cog.return_value = mock_ai_cog

        cog = AIDebug(mock_bot)

        mock_ctx = MagicMock()
        mock_ctx.send = AsyncMock()

        await cog.ai_perf.callback(cog, mock_ctx)

        mock_ctx.send.assert_called_once()


class TestAICacheClearCommand:
    """Tests for ai_cache_clear command."""

    @pytest.mark.asyncio
    async def test_ai_cache_clear_success(self):
        """Test ai_cache_clear success."""
        from cogs.ai_core.commands.debug_commands import AIDebug

        mock_bot = MagicMock(spec=commands.Bot)
        cog = AIDebug(mock_bot)

        mock_ctx = MagicMock()
        mock_ctx.send = AsyncMock()

        mock_cache = MagicMock()
        mock_cache.invalidate.return_value = 5

        with patch.dict(
            "sys.modules", {"cogs.ai_core.cache.ai_cache": MagicMock(ai_cache=mock_cache)}
        ):
            with patch("cogs.ai_core.cache.ai_cache.ai_cache", mock_cache, create=True):
                await cog.ai_cache_clear.callback(cog, mock_ctx)

        mock_ctx.send.assert_called()


class TestCommandAttributes:
    """Tests for command attributes."""

    def test_ai_debug_command_name(self):
        """Test ai_debug command has correct name."""
        from cogs.ai_core.commands.debug_commands import AIDebug

        mock_bot = MagicMock(spec=commands.Bot)
        cog = AIDebug(mock_bot)

        assert cog.ai_debug.name == "ai_debug"

    def test_ai_perf_command_name(self):
        """Test ai_perf command has correct name."""
        from cogs.ai_core.commands.debug_commands import AIDebug

        mock_bot = MagicMock(spec=commands.Bot)
        cog = AIDebug(mock_bot)

        assert cog.ai_perf.name == "ai_perf"

    def test_ai_cache_clear_command_name(self):
        """Test ai_cache_clear command has correct name."""
        from cogs.ai_core.commands.debug_commands import AIDebug

        mock_bot = MagicMock(spec=commands.Bot)
        cog = AIDebug(mock_bot)

        assert cog.ai_cache_clear.name == "ai_cache_clear"


class TestSetupFunction:
    """Tests for setup function."""

    @pytest.mark.asyncio
    async def test_setup_adds_cog(self):
        """Test setup adds cog to bot."""
        from cogs.ai_core.commands.debug_commands import setup

        mock_bot = MagicMock(spec=commands.Bot)
        mock_bot.add_cog = AsyncMock()

        await setup(mock_bot)

        mock_bot.add_cog.assert_called_once()


class TestModuleImports:
    """Tests for module imports."""

    def test_import_ai_debug_cog(self):
        """Test importing AIDebug cog."""
        from cogs.ai_core.commands.debug_commands import AIDebug

        assert AIDebug is not None

    def test_import_setup(self):
        """Test importing setup function."""
        from cogs.ai_core.commands.debug_commands import setup

        assert callable(setup)


# ======================================================================
# Merged from test_debug_commands_extended.py
# ======================================================================


class TestAIDebugCog:
    """Tests for AIDebug cog initialization."""

    def test_ai_debug_cog_init(self):
        """Test AIDebug cog initializes correctly."""
        try:
            from cogs.ai_core.commands.debug_commands import AIDebug
        except ImportError:
            pytest.skip("debug_commands not available")
            return

        mock_bot = MagicMock(spec=commands.Bot)
        cog = AIDebug(mock_bot)

        assert cog.bot == mock_bot
        assert hasattr(cog, "logger")

    def test_ai_debug_has_commands(self):
        """Test AIDebug cog has expected commands."""
        try:
            from cogs.ai_core.commands.debug_commands import AIDebug
        except ImportError:
            pytest.skip("debug_commands not available")
            return

        mock_bot = MagicMock(spec=commands.Bot)
        cog = AIDebug(mock_bot)

        # Check for expected command methods
        assert hasattr(cog, "ai_debug")
        assert hasattr(cog, "ai_perf")
        assert hasattr(cog, "ai_cache_clear")
        assert hasattr(cog, "ai_trace")
        assert hasattr(cog, "ai_stats_cmd")
        assert hasattr(cog, "ai_tokens_cmd")


class TestGetChatManager:
    """Tests for _get_chat_manager helper method."""

    def test_get_chat_manager_returns_chat_manager(self):
        """Test _get_chat_manager returns chat_manager when available."""
        try:
            from cogs.ai_core.commands.debug_commands import AIDebug
        except ImportError:
            pytest.skip("debug_commands not available")
            return

        mock_bot = MagicMock(spec=commands.Bot)
        mock_ai_cog = MagicMock()
        mock_chat_manager = MagicMock()
        mock_ai_cog.chat_manager = mock_chat_manager
        mock_bot.get_cog.return_value = mock_ai_cog

        cog = AIDebug(mock_bot)
        result = cog._get_chat_manager()

        assert result == mock_chat_manager
        mock_bot.get_cog.assert_called_with("AI")

    def test_get_chat_manager_returns_none_when_no_ai_cog(self):
        """Test _get_chat_manager returns None when AI cog not found."""
        try:
            from cogs.ai_core.commands.debug_commands import AIDebug
        except ImportError:
            pytest.skip("debug_commands not available")
            return

        mock_bot = MagicMock(spec=commands.Bot)
        mock_bot.get_cog.return_value = None

        cog = AIDebug(mock_bot)
        result = cog._get_chat_manager()

        assert result is None

    def test_get_chat_manager_returns_none_when_no_chat_manager(self):
        """Test _get_chat_manager returns None when chat_manager not present."""
        try:
            from cogs.ai_core.commands.debug_commands import AIDebug
        except ImportError:
            pytest.skip("debug_commands not available")
            return

        mock_bot = MagicMock(spec=commands.Bot)
        mock_ai_cog = MagicMock(spec=[])  # No chat_manager attribute
        mock_bot.get_cog.return_value = mock_ai_cog

        cog = AIDebug(mock_bot)
        result = cog._get_chat_manager()

        assert result is None


class TestAIDebugCommand:
    """Tests for ai_debug command."""

    @pytest.fixture
    def setup_debug_cog(self):
        """Setup debug cog with mocks."""
        try:
            from cogs.ai_core.commands.debug_commands import AIDebug
        except ImportError:
            pytest.skip("debug_commands not available")
            return None

        mock_bot = MagicMock(spec=commands.Bot)
        cog = AIDebug(mock_bot)

        mock_ctx = MagicMock()
        mock_ctx.channel.id = 123456
        mock_ctx.send = AsyncMock()
        # Add message reference mock to avoid TypeError in detect_intent
        mock_ctx.message.reference = None

        return cog, mock_ctx

    async def test_ai_debug_no_chat_manager(self, setup_debug_cog):
        """Test ai_debug command when chat_manager unavailable."""
        if setup_debug_cog is None:
            pytest.skip("debug_commands not available")
            return

        cog, mock_ctx = setup_debug_cog
        cog._get_chat_manager = MagicMock(return_value=None)

        await cog.ai_debug.callback(cog, mock_ctx)

        # Should still send debug embed even without chat manager
        mock_ctx.send.assert_called_once()

    async def test_ai_debug_with_active_session(self, setup_debug_cog):
        """Test ai_debug command with active session."""
        if setup_debug_cog is None:
            pytest.skip("debug_commands not available")
            return

        cog, mock_ctx = setup_debug_cog

        mock_chat_manager = MagicMock()
        mock_chat_manager.chats = {
            123456: {"history": [{"role": "user", "content": "test"}], "thinking_enabled": True}
        }
        mock_chat_manager.get_performance_stats.return_value = {}
        cog._get_chat_manager = MagicMock(return_value=mock_chat_manager)

        with patch("cogs.ai_core.commands.debug_commands.discord.Embed"):
            await cog.ai_debug.callback(cog, mock_ctx)

        mock_ctx.send.assert_called_once()


class TestAIPerfCommand:
    """Tests for ai_perf command."""

    async def test_ai_perf_no_chat_manager(self):
        """Test ai_perf command when chat_manager unavailable."""
        try:
            from cogs.ai_core.commands.debug_commands import AIDebug
        except ImportError:
            pytest.skip("debug_commands not available")
            return

        mock_bot = MagicMock(spec=commands.Bot)
        cog = AIDebug(mock_bot)

        mock_ctx = MagicMock()
        mock_ctx.send = AsyncMock()

        cog._get_chat_manager = MagicMock(return_value=None)

        await cog.ai_perf.callback(cog, mock_ctx)

        mock_ctx.send.assert_called_with("❌ AI system not available")

    async def test_ai_perf_with_stats(self):
        """Test ai_perf command with performance stats."""
        try:
            from cogs.ai_core.commands.debug_commands import AIDebug
        except ImportError:
            pytest.skip("debug_commands not available")
            return

        mock_bot = MagicMock(spec=commands.Bot)
        cog = AIDebug(mock_bot)

        mock_ctx = MagicMock()
        mock_ctx.send = AsyncMock()

        mock_chat_manager = MagicMock()
        mock_chat_manager.get_performance_stats.return_value = {
            "api_call": {"avg_ms": 150.5, "min_ms": 100.0, "max_ms": 200.0, "count": 10},
            "rag_query": {"avg_ms": 25.0, "min_ms": 10.0, "max_ms": 50.0, "count": 5},
        }
        cog._get_chat_manager = MagicMock(return_value=mock_chat_manager)

        await cog.ai_perf.callback(cog, mock_ctx)

        call_args = mock_ctx.send.call_args[0][0]
        assert "api_call" in call_args
        assert "150.5ms" in call_args


class TestAICacheClearCommand:
    """Tests for ai_cache_clear command."""

    async def test_ai_cache_clear_success(self):
        """Test ai_cache_clear command success."""
        try:
            from cogs.ai_core.commands.debug_commands import AIDebug
        except ImportError:
            pytest.skip("debug_commands not available")
            return

        mock_bot = MagicMock(spec=commands.Bot)
        cog = AIDebug(mock_bot)

        mock_ctx = MagicMock()
        mock_ctx.send = AsyncMock()

        mock_cache = MagicMock()
        mock_cache.invalidate.return_value = 5

        with patch.dict(
            "sys.modules", {"cogs.ai_core.cache.ai_cache": MagicMock(ai_cache=mock_cache)}
        ):
            with patch("cogs.ai_core.commands.debug_commands.ai_cache", mock_cache, create=True):
                # Import and re-mock within context
                pass

        # Test import error path
        with patch.object(cog, "ai_cache_clear") as mock_cmd:
            mock_cmd.callback = AsyncMock()

    async def test_ai_cache_clear_import_error(self):
        """Test ai_cache_clear handles ImportError."""
        try:
            from cogs.ai_core.commands.debug_commands import AIDebug
        except ImportError:
            pytest.skip("debug_commands not available")
            return

        mock_bot = MagicMock(spec=commands.Bot)
        AIDebug(mock_bot)

        mock_ctx = MagicMock()
        mock_ctx.send = AsyncMock()

        # Simulate ImportError by having get_cog work but cache import fail

        # Call with mocked import to raise ImportError
        with patch("builtins.__import__", side_effect=ImportError):
            # The command itself handles the import internally
            pass


class TestAITraceCommand:
    """Tests for ai_trace command."""

    async def test_ai_trace_no_chat_manager(self):
        """Test ai_trace command when chat_manager unavailable."""
        try:
            from cogs.ai_core.commands.debug_commands import AIDebug
        except ImportError:
            pytest.skip("debug_commands not available")
            return

        mock_bot = MagicMock(spec=commands.Bot)
        cog = AIDebug(mock_bot)

        mock_ctx = MagicMock()
        mock_ctx.send = AsyncMock()

        cog._get_chat_manager = MagicMock(return_value=None)

        await cog.ai_trace.callback(cog, mock_ctx)

        mock_ctx.send.assert_called_with("❌ AI system not available")

    async def test_ai_trace_no_active_session(self):
        """Test ai_trace command when no active session."""
        try:
            from cogs.ai_core.commands.debug_commands import AIDebug
        except ImportError:
            pytest.skip("debug_commands not available")
            return

        mock_bot = MagicMock(spec=commands.Bot)
        cog = AIDebug(mock_bot)

        mock_ctx = MagicMock()
        mock_ctx.channel.id = 123456
        mock_ctx.send = AsyncMock()

        mock_chat_manager = MagicMock()
        mock_chat_manager.chats = {}  # No active session
        cog._get_chat_manager = MagicMock(return_value=mock_chat_manager)

        await cog.ai_trace.callback(cog, mock_ctx)

        mock_ctx.send.assert_called_with("❌ No active session in this channel")

    async def test_ai_trace_with_trace_data(self):
        """Test ai_trace command with trace data."""
        try:
            from cogs.ai_core.commands.debug_commands import AIDebug
        except ImportError:
            pytest.skip("debug_commands not available")
            return

        mock_bot = MagicMock(spec=commands.Bot)
        cog = AIDebug(mock_bot)

        mock_ctx = MagicMock()
        mock_ctx.channel.id = 123456
        mock_ctx.send = AsyncMock()

        mock_chat_manager = MagicMock()
        mock_chat_manager.chats = {
            123456: {
                "history": [],
                "thinking_enabled": True,
                "streaming_enabled": True,
                "last_trace": {
                    "total_ms": 500,
                    "api_ms": 450,
                    "rag_ms": 30,
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "cache_hit": False,
                    "rag_results": 3,
                    "intent": "question",
                },
            }
        }
        cog._get_chat_manager = MagicMock(return_value=mock_chat_manager)

        await cog.ai_trace.callback(cog, mock_ctx)

        mock_ctx.send.assert_called_once()


class TestAIStatsCommand:
    """Tests for ai_stats_cmd command."""

    async def test_ai_stats_import_error(self):
        """Test ai_stats_cmd handles ImportError."""
        try:
            from cogs.ai_core.commands.debug_commands import AIDebug
        except ImportError:
            pytest.skip("debug_commands not available")
            return

        mock_bot = MagicMock(spec=commands.Bot)
        AIDebug(mock_bot)

        mock_ctx = MagicMock()
        mock_ctx.send = AsyncMock()

        # Test will call the command and it handles import error internally


class TestAITokensCommand:
    """Tests for ai_tokens_cmd command."""

    async def test_ai_tokens_import_error(self):
        """Test ai_tokens_cmd handles ImportError."""
        try:
            from cogs.ai_core.commands.debug_commands import AIDebug
        except ImportError:
            pytest.skip("debug_commands not available")
            return

        mock_bot = MagicMock(spec=commands.Bot)
        AIDebug(mock_bot)

        mock_ctx = MagicMock()
        mock_ctx.send = AsyncMock()


class TestSetupFunction:
    """Tests for setup function."""

    async def test_setup_function_exists(self):
        """Test setup function is defined."""
        try:
            from cogs.ai_core.commands.debug_commands import setup
        except ImportError:
            pytest.skip("debug_commands not available")
            return

        assert callable(setup)

    async def test_setup_adds_cog(self):
        """Test setup adds AIDebug cog to bot."""
        try:
            from cogs.ai_core.commands.debug_commands import AIDebug, setup
        except ImportError:
            pytest.skip("debug_commands not available")
            return

        mock_bot = MagicMock(spec=commands.Bot)
        mock_bot.add_cog = AsyncMock()

        await setup(mock_bot)

        mock_bot.add_cog.assert_called_once()
        call_args = mock_bot.add_cog.call_args[0]
        assert isinstance(call_args[0], AIDebug)


class TestCommandDecorators:
    """Tests for command decorators."""

    def test_commands_have_owner_check(self):
        """Test debug commands have is_owner check."""
        try:
            from cogs.ai_core.commands.debug_commands import AIDebug
        except ImportError:
            pytest.skip("debug_commands not available")
            return

        mock_bot = MagicMock(spec=commands.Bot)
        cog = AIDebug(mock_bot)

        # Check that commands have checks
        # The commands should have the is_owner check
        assert hasattr(cog.ai_debug, "checks") or hasattr(cog.ai_debug, "__commands_checks__")

    def test_command_names(self):
        """Test commands have correct names."""
        try:
            from cogs.ai_core.commands.debug_commands import AIDebug
        except ImportError:
            pytest.skip("debug_commands not available")
            return

        mock_bot = MagicMock(spec=commands.Bot)
        cog = AIDebug(mock_bot)

        # Check command names
        assert cog.ai_debug.name == "ai_debug"
        assert cog.ai_perf.name == "ai_perf"
        assert cog.ai_cache_clear.name == "ai_cache_clear"
        assert cog.ai_trace.name == "ai_trace"


class TestEdgeCases:
    """Tests for edge cases."""

    def test_logger_initialization(self):
        """Test logger is initialized with correct name."""
        try:
            from cogs.ai_core.commands.debug_commands import AIDebug
        except ImportError:
            pytest.skip("debug_commands not available")
            return

        mock_bot = MagicMock(spec=commands.Bot)
        cog = AIDebug(mock_bot)

        assert cog.logger.name == "AIDebug"

    async def test_ai_perf_no_data(self):
        """Test ai_perf with empty stats."""
        try:
            from cogs.ai_core.commands.debug_commands import AIDebug
        except ImportError:
            pytest.skip("debug_commands not available")
            return

        mock_bot = MagicMock(spec=commands.Bot)
        cog = AIDebug(mock_bot)

        mock_ctx = MagicMock()
        mock_ctx.send = AsyncMock()

        mock_chat_manager = MagicMock()
        mock_chat_manager.get_performance_stats.return_value = {}
        cog._get_chat_manager = MagicMock(return_value=mock_chat_manager)

        await cog.ai_perf.callback(cog, mock_ctx)

        mock_ctx.send.assert_called_with("No performance data yet")

    async def test_ai_trace_no_trace_data(self):
        """Test ai_trace with session but no trace data."""
        try:
            from cogs.ai_core.commands.debug_commands import AIDebug
        except ImportError:
            pytest.skip("debug_commands not available")
            return

        mock_bot = MagicMock(spec=commands.Bot)
        cog = AIDebug(mock_bot)

        mock_ctx = MagicMock()
        mock_ctx.channel.id = 123456
        mock_ctx.send = AsyncMock()

        mock_chat_manager = MagicMock()
        mock_chat_manager.chats = {
            123456: {
                "history": [],
                "thinking_enabled": False,
                "streaming_enabled": False,
                # No last_trace
            }
        }
        cog._get_chat_manager = MagicMock(return_value=mock_chat_manager)

        await cog.ai_trace.callback(cog, mock_ctx)

        mock_ctx.send.assert_called_once()


# ======================================================================
# Coverage-completion tests (append-only): drives the import-error and
# error branches, the active-session debug panels, and the ai_stats /
# ai_tokens command bodies that the earlier tests don't reach.
# ======================================================================


import sys

import discord


def _make_cog():
    from cogs.ai_core.commands.debug_commands import AIDebug

    mock_bot = MagicMock(spec=commands.Bot)
    return AIDebug(mock_bot)


def _make_ctx(channel_id=123456, reference=None):
    """Build a ctx whose message.reference is controllable.

    Default reference=None mirrors the "no reply" case so detect_intent
    falls back to the default Thai test string.
    """
    ctx = MagicMock()
    ctx.channel.id = channel_id
    ctx.send = AsyncMock()
    ctx.message = MagicMock()
    ctx.message.reference = reference
    return ctx


class TestAIDebugBranches:
    """Exercise the per-panel import-error / error branches of ai_debug."""

    async def test_history_manager_import_error_falls_back(self):
        """66-67: history_manager import fails -> rough token estimate."""
        cog = _make_cog()
        ctx = _make_ctx()

        cm = MagicMock()
        cm.chats = {123456: {"history": [{"role": "user", "content": "hi"}] * 3}}
        cm.get_performance_stats.return_value = {}
        cog._get_chat_manager = MagicMock(return_value=cm)

        # Force the local ``from ...history_manager import history_manager`` to fail
        with patch.dict(sys.modules, {"cogs.ai_core.memory.history_manager": None}):
            await cog.ai_debug.callback(cog, ctx)

        ctx.send.assert_called_once()
        # Rough estimate path uses len(history)*50 = 150 -> rendered as ~150
        sent_embed = ctx.send.call_args.kwargs["embed"]
        session_field = next(f for f in sent_embed.fields if f.name == "📝 Session")
        assert "150" in session_field.value

    async def test_cache_stats_import_error(self):
        """90-91: ai_cache import fails -> 'Cache not available'."""
        cog = _make_cog()
        ctx = _make_ctx()
        cog._get_chat_manager = MagicMock(return_value=None)

        with patch.dict(sys.modules, {"cogs.ai_core.cache.ai_cache": None}):
            await cog.ai_debug.callback(cog, ctx)

        sent_embed = ctx.send.call_args.kwargs["embed"]
        cache_field = next(f for f in sent_embed.fields if f.name == "💾 Cache")
        assert "Cache not available" in cache_field.value

    async def test_cache_stats_attribute_error_degrades(self):
        """92-96: CacheStats schema drift -> 'Cache stats unavailable'."""
        cog = _make_cog()
        ctx = _make_ctx()
        cog._get_chat_manager = MagicMock(return_value=None)

        # get_stats returns an object missing fields -> AttributeError when
        # the f-string reads stats.total_entries.
        bad_stats = object()
        fake_cache_mod = MagicMock()
        fake_cache_mod.ai_cache.get_stats.return_value = bad_stats

        with patch.dict(sys.modules, {"cogs.ai_core.cache.ai_cache": fake_cache_mod}):
            await cog.ai_debug.callback(cog, ctx)

        sent_embed = ctx.send.call_args.kwargs["embed"]
        cache_field = next(f for f in sent_embed.fields if f.name == "💾 Cache")
        assert "Cache stats unavailable" in cache_field.value

    async def test_rag_import_error(self):
        """115-116: rag_system import fails -> 'RAG not available'."""
        cog = _make_cog()
        ctx = _make_ctx()
        cog._get_chat_manager = MagicMock(return_value=None)

        with patch.dict(sys.modules, {"cogs.ai_core.memory.rag": None}):
            await cog.ai_debug.callback(cog, ctx)

        sent_embed = ctx.send.call_args.kwargs["embed"]
        rag_field = next(f for f in sent_embed.fields if f.name == "🧠 RAG Memory")
        assert "RAG not available" in rag_field.value

    async def test_performance_panel_rendered(self):
        """124-129: perf stats with count>0 -> Performance field added."""
        cog = _make_cog()
        ctx = _make_ctx()

        cm = MagicMock()
        cm.chats = {123456: {"history": [], "thinking_enabled": True}}
        cm.get_performance_stats.return_value = {
            "api": {"count": 4, "avg_ms": 123.4},
            "idle": {"count": 0, "avg_ms": 0.0},  # filtered out
        }
        cog._get_chat_manager = MagicMock(return_value=cm)

        await cog.ai_debug.callback(cog, ctx)

        sent_embed = ctx.send.call_args.kwargs["embed"]
        perf_field = next(f for f in sent_embed.fields if f.name == "⚡ Performance")
        assert "api: 123ms avg" in perf_field.value
        assert "idle" not in perf_field.value

    async def test_intent_uses_replied_message_content(self):
        """146: a real replied discord.Message supplies the intent test text."""
        cog = _make_cog()

        replied = MagicMock(spec=discord.Message)
        replied.content = "what time is it"
        ref = MagicMock()
        ref.resolved = replied
        ctx = _make_ctx(reference=ref)
        cog._get_chat_manager = MagicMock(return_value=None)

        captured = {}

        def fake_detect(msg):
            captured["msg"] = msg
            result = MagicMock()
            result.intent.value = "question"
            result.confidence = 0.9
            result.sub_category = None
            return result

        fake_mod = MagicMock()
        fake_mod.detect_intent = fake_detect
        with patch.dict(sys.modules, {"cogs.ai_core.processing.intent_detector": fake_mod}):
            await cog.ai_debug.callback(cog, ctx)

        assert captured["msg"] == "what time is it"

    async def test_intent_import_error_logged(self):
        """157-158: intent_detector import fails -> branch logged, no crash."""
        cog = _make_cog()
        ctx = _make_ctx()
        cog._get_chat_manager = MagicMock(return_value=None)

        with patch.dict(sys.modules, {"cogs.ai_core.processing.intent_detector": None}):
            await cog.ai_debug.callback(cog, ctx)

        # Command still completes and sends the embed.
        ctx.send.assert_called_once()
        sent_embed = ctx.send.call_args.kwargs["embed"]
        # No Intent Detection field when import fails.
        assert all(f.name != "🎯 Intent Detection" for f in sent_embed.fields)

    async def test_entity_memory_import_error_logged(self):
        """178-179: entity_memory import fails -> branch logged, no crash."""
        cog = _make_cog()
        ctx = _make_ctx()
        cog._get_chat_manager = MagicMock(return_value=None)

        with patch.dict(sys.modules, {"cogs.ai_core.memory.entity_memory": None}):
            await cog.ai_debug.callback(cog, ctx)

        ctx.send.assert_called_once()
        sent_embed = ctx.send.call_args.kwargs["embed"]
        assert all(f.name != "👤 Entity Memory" for f in sent_embed.fields)


class TestAICacheClearBranches:
    """ai_cache_clear success + ImportError branches (212-218)."""

    async def test_cache_clear_success(self):
        """215-216: invalidate count reported."""
        cog = _make_cog()
        ctx = _make_ctx()

        fake_mod = MagicMock()
        fake_mod.ai_cache.invalidate.return_value = 7
        with patch.dict(sys.modules, {"cogs.ai_core.cache.ai_cache": fake_mod}):
            await cog.ai_cache_clear.callback(cog, ctx)

        ctx.send.assert_called_once_with("✅ Cleared 7 cache entries")

    async def test_cache_clear_import_error(self):
        """217-218: import fails -> 'Cache not available'."""
        cog = _make_cog()
        ctx = _make_ctx()

        with patch.dict(sys.modules, {"cogs.ai_core.cache.ai_cache": None}):
            await cog.ai_cache_clear.callback(cog, ctx)

        ctx.send.assert_called_once_with("❌ Cache not available")


class TestAIStatsCommandFull:
    """ai_stats_cmd body (308-371)."""

    async def test_stats_import_error(self):
        """312-314: analytics import fails -> message + early return."""
        cog = _make_cog()
        ctx = _make_ctx()

        with patch.dict(sys.modules, {"cogs.ai_core.cache.analytics": None}):
            await cog.ai_stats_cmd.callback(cog, ctx)

        ctx.send.assert_called_once_with("❌ Analytics not available")

    async def test_stats_full_payload(self):
        """308-371: all optional panels (latency, quality, intent) rendered."""
        cog = _make_cog()
        ctx = _make_ctx()

        stats = {
            "summary": {
                "total_interactions": 1234,
                "avg_response_time_ms": 250.0,
                "cache_hit_rate": 0.42,
                "error_rate": 0.01,
                "interactions_per_hour": 12.5,
            },
            "latency_percentiles": {
                "count": 100,
                "p50": 200.0,
                "p95": 400.0,
                "p99": 600.0,
                "min": 50.0,
                "max": 800.0,
            },
            "tokens": {"input": 1000, "output": 500, "total": 1500},
            "quality": {
                "total_ratings": 10,
                "average_score": 4.5,
                "positive_reactions": 8,
                "negative_reactions": 2,
            },
            "intent_accuracy": {"total_feedback": 5, "accuracy": 0.8},
        }
        fake_mod = MagicMock()
        fake_mod.get_detailed_ai_stats.return_value = stats
        with patch.dict(sys.modules, {"cogs.ai_core.cache.analytics": fake_mod}):
            await cog.ai_stats_cmd.callback(cog, ctx)

        ctx.send.assert_called_once()
        sent_embed = ctx.send.call_args.kwargs["embed"]
        names = {f.name for f in sent_embed.fields}
        assert "📈 Summary" in names
        assert "⏱️ Latency Percentiles" in names
        assert "🔢 Token Usage (Est.)" in names
        assert "⭐ Quality" in names
        assert "🎯 Intent Accuracy" in names

    async def test_stats_optional_panels_skipped(self):
        """Counts of 0 skip latency/quality/intent panels (327/350 still hit)."""
        cog = _make_cog()
        ctx = _make_ctx()

        stats = {
            "summary": {},
            "latency_percentiles": {"count": 0},
            "tokens": {},
            "quality": {"total_ratings": 0},
            "intent_accuracy": {"total_feedback": 0},
        }
        fake_mod = MagicMock()
        fake_mod.get_detailed_ai_stats.return_value = stats
        with patch.dict(sys.modules, {"cogs.ai_core.cache.analytics": fake_mod}):
            await cog.ai_stats_cmd.callback(cog, ctx)

        ctx.send.assert_called_once()
        sent_embed = ctx.send.call_args.kwargs["embed"]
        names = {f.name for f in sent_embed.fields}
        # Required panels present, optional zero-count panels absent.
        assert "📈 Summary" in names
        assert "🔢 Token Usage (Est.)" in names
        assert "⏱️ Latency Percentiles" not in names
        assert "⭐ Quality" not in names
        assert "🎯 Intent Accuracy" not in names


class TestAITokensCommandFull:
    """ai_tokens_cmd body (377-402)."""

    async def test_tokens_success(self):
        """380-400: global stats fetched + embed sent."""
        cog = _make_cog()
        ctx = _make_ctx()

        fake_tracker = MagicMock()
        fake_tracker.get_global_stats = AsyncMock(
            return_value={
                "total_records": 100,
                "total_tokens": 50000,
                "unique_users": 5,
                "unique_channels": 3,
            }
        )
        fake_mod = MagicMock()
        fake_mod.token_tracker = fake_tracker
        with patch.dict(sys.modules, {"cogs.ai_core.cache.token_tracker": fake_mod}):
            await cog.ai_tokens_cmd.callback(cog, ctx)

        ctx.send.assert_called_once()
        sent_embed = ctx.send.call_args.kwargs["embed"]
        field = next(f for f in sent_embed.fields if f.name == "📊 Global Stats")
        assert "100" in field.value
        assert "50,000" in field.value

    async def test_tokens_fetch_raises(self):
        """382-385: get_global_stats raises -> graceful error + return."""
        cog = _make_cog()
        ctx = _make_ctx()

        fake_tracker = MagicMock()
        fake_tracker.get_global_stats = AsyncMock(side_effect=RuntimeError("db down"))
        fake_mod = MagicMock()
        fake_mod.token_tracker = fake_tracker
        with patch.dict(sys.modules, {"cogs.ai_core.cache.token_tracker": fake_mod}):
            await cog.ai_tokens_cmd.callback(cog, ctx)

        ctx.send.assert_called_once()
        msg = ctx.send.call_args[0][0]
        assert "RuntimeError" in msg
        assert "token" in msg

    async def test_tokens_import_error(self):
        """401-402: token_tracker import fails -> 'Token tracker not available'."""
        cog = _make_cog()
        ctx = _make_ctx()

        with patch.dict(sys.modules, {"cogs.ai_core.cache.token_tracker": None}):
            await cog.ai_tokens_cmd.callback(cog, ctx)

        ctx.send.assert_called_once_with("❌ Token tracker not available")
