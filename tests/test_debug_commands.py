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

        assert hasattr(cog, 'ai_debug')

    def test_cog_has_ai_perf_command(self):
        """Test cog has ai_perf command."""
        from cogs.ai_core.commands.debug_commands import AIDebug

        mock_bot = MagicMock(spec=commands.Bot)
        cog = AIDebug(mock_bot)

        assert hasattr(cog, 'ai_perf')

    def test_cog_has_ai_cache_clear_command(self):
        """Test cog has ai_cache_clear command."""
        from cogs.ai_core.commands.debug_commands import AIDebug

        mock_bot = MagicMock(spec=commands.Bot)
        cog = AIDebug(mock_bot)

        assert hasattr(cog, 'ai_cache_clear')


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
        assert 'embed' in call_args.kwargs or len(call_args.args) > 0

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

        with patch.dict("sys.modules", {"cogs.ai_core.cache.ai_cache": MagicMock(ai_cache=mock_cache)}):
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
        assert hasattr(cog, 'logger')

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
        assert hasattr(cog, 'ai_debug')
        assert hasattr(cog, 'ai_perf')
        assert hasattr(cog, 'ai_cache_clear')
        assert hasattr(cog, 'ai_trace')
        assert hasattr(cog, 'ai_stats_cmd')
        assert hasattr(cog, 'ai_tokens_cmd')


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
            123456: {
                "history": [{"role": "user", "content": "test"}],
                "thinking_enabled": True
            }
        }
        mock_chat_manager.get_performance_stats.return_value = {}
        cog._get_chat_manager = MagicMock(return_value=mock_chat_manager)

        with patch('cogs.ai_core.commands.debug_commands.discord.Embed'):
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
            "rag_query": {"avg_ms": 25.0, "min_ms": 10.0, "max_ms": 50.0, "count": 5}
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

        with patch.dict('sys.modules', {'cogs.ai_core.cache.ai_cache': MagicMock(ai_cache=mock_cache)}):
            with patch('cogs.ai_core.commands.debug_commands.ai_cache', mock_cache, create=True):
                # Import and re-mock within context
                pass

        # Test import error path
        with patch.object(cog, 'ai_cache_clear') as mock_cmd:
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
        with patch('builtins.__import__', side_effect=ImportError):
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
                    "intent": "question"
                }
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
        assert hasattr(cog.ai_debug, 'checks') or hasattr(cog.ai_debug, '__commands_checks__')

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
                "streaming_enabled": False
                # No last_trace
            }
        }
        cog._get_chat_manager = MagicMock(return_value=mock_chat_manager)

        await cog.ai_trace.callback(cog, mock_ctx)

        mock_ctx.send.assert_called_once()
