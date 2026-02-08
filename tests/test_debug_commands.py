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
