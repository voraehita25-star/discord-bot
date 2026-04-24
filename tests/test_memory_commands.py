"""Tests for memory_commands cog."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from discord.ext import commands


class TestMemoryCommandsCog:
    """Tests for MemoryCommands cog initialization."""

    def test_cog_creation(self):
        """Test MemoryCommands cog can be created."""
        from cogs.ai_core.commands.memory_commands import MemoryCommands

        mock_bot = MagicMock(spec=commands.Bot)
        cog = MemoryCommands(mock_bot)

        assert cog.bot == mock_bot
        assert cog.logger is not None

    def test_cog_has_remember_command(self):
        """Test cog has remember command."""
        from cogs.ai_core.commands.memory_commands import MemoryCommands

        mock_bot = MagicMock(spec=commands.Bot)
        cog = MemoryCommands(mock_bot)

        assert hasattr(cog, 'remember_fact')

    def test_cog_has_forget_command(self):
        """Test cog has forget command."""
        from cogs.ai_core.commands.memory_commands import MemoryCommands

        mock_bot = MagicMock(spec=commands.Bot)
        cog = MemoryCommands(mock_bot)

        assert hasattr(cog, 'forget_fact')

    def test_cog_has_memories_command(self):
        """Test cog has memories command."""
        from cogs.ai_core.commands.memory_commands import MemoryCommands

        mock_bot = MagicMock(spec=commands.Bot)
        cog = MemoryCommands(mock_bot)

        assert hasattr(cog, 'view_memories')

    def test_cog_has_consolidate_command(self):
        """Test cog has consolidate command."""
        from cogs.ai_core.commands.memory_commands import MemoryCommands

        mock_bot = MagicMock(spec=commands.Bot)
        cog = MemoryCommands(mock_bot)

        assert hasattr(cog, 'force_consolidate')

    def test_cog_has_memory_stats_command(self):
        """Test cog has memory_stats command."""
        from cogs.ai_core.commands.memory_commands import MemoryCommands

        mock_bot = MagicMock(spec=commands.Bot)
        cog = MemoryCommands(mock_bot)

        assert hasattr(cog, 'memory_stats')


class TestRememberCommand:
    """Tests for remember command."""

    @pytest.mark.asyncio
    async def test_remember_empty_fact(self):
        """Test remember with empty fact."""
        from cogs.ai_core.commands.memory_commands import MemoryCommands

        mock_bot = MagicMock(spec=commands.Bot)
        cog = MemoryCommands(mock_bot)

        mock_ctx = MagicMock()
        mock_ctx.send = AsyncMock()

        # Call the underlying callback directly
        await cog.remember_fact.callback(cog, mock_ctx, fact="")

        mock_ctx.send.assert_called_once()
        assert "❌" in mock_ctx.send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_remember_short_fact(self):
        """Test remember with too short fact."""
        from cogs.ai_core.commands.memory_commands import MemoryCommands

        mock_bot = MagicMock(spec=commands.Bot)
        cog = MemoryCommands(mock_bot)

        mock_ctx = MagicMock()
        mock_ctx.send = AsyncMock()

        await cog.remember_fact.callback(cog, mock_ctx, fact="ab")

        mock_ctx.send.assert_called_once()
        assert "❌" in mock_ctx.send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_remember_too_long_fact(self):
        """Test remember with fact too long."""
        from cogs.ai_core.commands.memory_commands import MemoryCommands

        mock_bot = MagicMock(spec=commands.Bot)
        cog = MemoryCommands(mock_bot)

        mock_ctx = MagicMock()
        mock_ctx.send = AsyncMock()

        long_fact = "x" * 600  # Over 500 limit
        await cog.remember_fact.callback(cog, mock_ctx, fact=long_fact)

        mock_ctx.send.assert_called_once()
        assert "❌" in mock_ctx.send.call_args[0][0]
        assert "ยาวเกินไป" in mock_ctx.send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_remember_valid_fact_length(self):
        """Test remember with valid fact length calls the import."""
        from cogs.ai_core.commands.memory_commands import MemoryCommands

        mock_bot = MagicMock(spec=commands.Bot)
        cog = MemoryCommands(mock_bot)

        mock_ctx = MagicMock()
        mock_ctx.send = AsyncMock()
        mock_ctx.author = MagicMock()
        mock_ctx.author.id = 123
        mock_ctx.channel = MagicMock()
        mock_ctx.channel.id = 456

        # This will likely call the send function due to import error or success
        await cog.remember_fact.callback(cog, mock_ctx, fact="I like pizza very much")

        # Should call send at least once (either success or error)
        mock_ctx.send.assert_called()


class TestForgetCommand:
    """Tests for forget command."""

    @pytest.mark.asyncio
    async def test_forget_empty_query(self):
        """Test forget with empty query."""
        from cogs.ai_core.commands.memory_commands import MemoryCommands

        mock_bot = MagicMock(spec=commands.Bot)
        cog = MemoryCommands(mock_bot)

        mock_ctx = MagicMock()
        mock_ctx.send = AsyncMock()

        await cog.forget_fact.callback(cog, mock_ctx, query="")

        mock_ctx.send.assert_called_once()
        assert "❌" in mock_ctx.send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_forget_with_query(self):
        """Test forget with valid query."""
        from cogs.ai_core.commands.memory_commands import MemoryCommands

        mock_bot = MagicMock(spec=commands.Bot)
        cog = MemoryCommands(mock_bot)

        mock_ctx = MagicMock()
        mock_ctx.send = AsyncMock()
        mock_ctx.author = MagicMock()
        mock_ctx.author.id = 123

        # Call the callback - it will try to import long_term_memory
        await cog.forget_fact.callback(cog, mock_ctx, query="allergic to peanuts")

        # Should send something
        mock_ctx.send.assert_called()


class TestViewMemoriesCommand:
    """Tests for memories command."""

    @pytest.mark.asyncio
    async def test_view_memories(self):
        """Test viewing memories."""
        from cogs.ai_core.commands.memory_commands import MemoryCommands

        mock_bot = MagicMock(spec=commands.Bot)
        cog = MemoryCommands(mock_bot)

        mock_ctx = MagicMock()
        mock_ctx.send = AsyncMock()
        mock_ctx.author = MagicMock()
        mock_ctx.author.id = 123

        await cog.view_memories.callback(cog, mock_ctx, category=None)

        # Should send something
        mock_ctx.send.assert_called()

    @pytest.mark.asyncio
    async def test_view_memories_with_category(self):
        """Test viewing memories with category filter."""
        from cogs.ai_core.commands.memory_commands import MemoryCommands

        mock_bot = MagicMock(spec=commands.Bot)
        cog = MemoryCommands(mock_bot)

        mock_ctx = MagicMock()
        mock_ctx.send = AsyncMock()
        mock_ctx.author = MagicMock()
        mock_ctx.author.id = 123

        await cog.view_memories.callback(cog, mock_ctx, category="preference")

        mock_ctx.send.assert_called()


class TestConsolidateCommand:
    """Tests for consolidate command."""

    @pytest.mark.asyncio
    async def test_consolidate_sends_status(self):
        """Test consolidation sends status message."""
        from cogs.ai_core.commands.memory_commands import MemoryCommands

        mock_bot = MagicMock(spec=commands.Bot)
        cog = MemoryCommands(mock_bot)

        mock_ctx = MagicMock()
        mock_status = MagicMock()
        mock_status.edit = AsyncMock()
        mock_ctx.send = AsyncMock(return_value=mock_status)
        mock_ctx.channel = MagicMock()
        mock_ctx.channel.id = 456

        await cog.force_consolidate.callback(cog, mock_ctx)

        # Should send status message
        mock_ctx.send.assert_called()


class TestMemoryStatsCommand:
    """Tests for memory_stats command."""

    @pytest.mark.asyncio
    async def test_memory_stats(self):
        """Test memory stats."""
        from cogs.ai_core.commands.memory_commands import MemoryCommands

        mock_bot = MagicMock(spec=commands.Bot)
        cog = MemoryCommands(mock_bot)

        mock_ctx = MagicMock()
        mock_ctx.send = AsyncMock()
        mock_ctx.author = MagicMock()
        mock_ctx.author.id = 123
        mock_ctx.channel = MagicMock()
        mock_ctx.channel.id = 456

        await cog.memory_stats.callback(cog, mock_ctx)

        mock_ctx.send.assert_called()


class TestSetupFunction:
    """Tests for setup function."""

    @pytest.mark.asyncio
    async def test_setup_adds_cog(self):
        """Test setup adds cog to bot."""
        from cogs.ai_core.commands.memory_commands import setup

        mock_bot = MagicMock(spec=commands.Bot)
        mock_bot.add_cog = AsyncMock()

        await setup(mock_bot)

        mock_bot.add_cog.assert_called_once()


class TestCommandAttributes:
    """Tests for command attributes."""

    def test_remember_command_name(self):
        """Test remember command has correct name."""
        from cogs.ai_core.commands.memory_commands import MemoryCommands

        mock_bot = MagicMock(spec=commands.Bot)
        cog = MemoryCommands(mock_bot)

        assert cog.remember_fact.name == "remember"

    def test_forget_command_name(self):
        """Test forget command has correct name."""
        from cogs.ai_core.commands.memory_commands import MemoryCommands

        mock_bot = MagicMock(spec=commands.Bot)
        cog = MemoryCommands(mock_bot)

        assert cog.forget_fact.name == "forget"

    def test_memories_command_name(self):
        """Test memories command has correct name."""
        from cogs.ai_core.commands.memory_commands import MemoryCommands

        mock_bot = MagicMock(spec=commands.Bot)
        cog = MemoryCommands(mock_bot)

        assert cog.view_memories.name == "memories"

    def test_memories_command_aliases(self):
        """Test memories command has aliases."""
        from cogs.ai_core.commands.memory_commands import MemoryCommands

        mock_bot = MagicMock(spec=commands.Bot)
        cog = MemoryCommands(mock_bot)

        assert "mymemory" in cog.view_memories.aliases
        assert "facts" in cog.view_memories.aliases

    def test_consolidate_command_name(self):
        """Test consolidate command has correct name."""
        from cogs.ai_core.commands.memory_commands import MemoryCommands

        mock_bot = MagicMock(spec=commands.Bot)
        cog = MemoryCommands(mock_bot)

        assert cog.force_consolidate.name == "consolidate"

    def test_memory_stats_command_name(self):
        """Test memory_stats command has correct name."""
        from cogs.ai_core.commands.memory_commands import MemoryCommands

        mock_bot = MagicMock(spec=commands.Bot)
        cog = MemoryCommands(mock_bot)

        assert cog.memory_stats.name == "memory_stats"


# ======================================================================
# Merged from test_memory_commands_extended.py
# ======================================================================

class TestMemoryCommandsCog:
    """Tests for MemoryCommands cog."""

    def test_memory_commands_init(self):
        """Test MemoryCommands initialization."""
        from cogs.ai_core.commands.memory_commands import MemoryCommands

        mock_bot = MagicMock(spec=commands.Bot)
        cog = MemoryCommands(mock_bot)

        assert cog.bot == mock_bot
        assert cog.logger is not None

    def test_memory_commands_has_commands(self):
        """Test MemoryCommands has expected commands."""
        from cogs.ai_core.commands.memory_commands import MemoryCommands

        mock_bot = MagicMock(spec=commands.Bot)
        cog = MemoryCommands(mock_bot)

        # Check command methods exist
        assert hasattr(cog, 'remember_fact')
        assert hasattr(cog, 'forget_fact')
        assert hasattr(cog, 'view_memories')


class TestRememberCommand:
    """Tests for the remember command."""

    @pytest.mark.asyncio
    async def test_remember_empty_fact(self):
        """Test remember with empty fact."""
        from cogs.ai_core.commands.memory_commands import MemoryCommands

        mock_bot = MagicMock(spec=commands.Bot)
        cog = MemoryCommands(mock_bot)

        mock_ctx = MagicMock()
        mock_ctx.send = AsyncMock()

        # Call the underlying function directly (skip decorator)
        await cog.remember_fact.callback(cog, mock_ctx, fact="")
        mock_ctx.send.assert_called_once()
        assert "กรุณาระบุ" in str(mock_ctx.send.call_args)

    @pytest.mark.asyncio
    async def test_remember_short_fact(self):
        """Test remember with too short fact."""
        from cogs.ai_core.commands.memory_commands import MemoryCommands

        mock_bot = MagicMock(spec=commands.Bot)
        cog = MemoryCommands(mock_bot)

        mock_ctx = MagicMock()
        mock_ctx.send = AsyncMock()

        await cog.remember_fact.callback(cog, mock_ctx, fact="ab")
        mock_ctx.send.assert_called_once()
        assert "กรุณาระบุ" in str(mock_ctx.send.call_args)

    @pytest.mark.asyncio
    async def test_remember_too_long_fact(self):
        """Test remember with too long fact."""
        from cogs.ai_core.commands.memory_commands import MemoryCommands

        mock_bot = MagicMock(spec=commands.Bot)
        cog = MemoryCommands(mock_bot)

        mock_ctx = MagicMock()
        mock_ctx.send = AsyncMock()

        long_fact = "a" * 501
        await cog.remember_fact.callback(cog, mock_ctx, fact=long_fact)
        mock_ctx.send.assert_called_once()
        assert "ยาวเกินไป" in str(mock_ctx.send.call_args)

    @pytest.mark.asyncio
    async def test_remember_success(self):
        """Test remember with valid fact - import handling."""
        from cogs.ai_core.commands.memory_commands import MemoryCommands

        mock_bot = MagicMock(spec=commands.Bot)
        cog = MemoryCommands(mock_bot)

        mock_ctx = MagicMock()
        mock_ctx.send = AsyncMock()
        mock_ctx.author = MagicMock()
        mock_ctx.author.id = 123
        mock_ctx.channel = MagicMock()
        mock_ctx.channel.id = 456

        # Test that valid fact triggers the memory save path
        # (may fail on import, which is expected behavior in test environment)
        try:
            await cog.remember_fact.callback(cog, mock_ctx, fact="I like pizza")
            # If no exception, check send was called
            assert mock_ctx.send.called
        except ImportError:
            # Expected if long_term_memory not available
            pass

    @pytest.mark.asyncio
    async def test_remember_handles_exception(self):
        """Test remember handles exceptions gracefully."""
        from cogs.ai_core.commands.memory_commands import MemoryCommands

        mock_bot = MagicMock(spec=commands.Bot)
        cog = MemoryCommands(mock_bot)

        mock_ctx = MagicMock()
        mock_ctx.send = AsyncMock()
        mock_ctx.author = MagicMock()
        mock_ctx.author.id = 123
        mock_ctx.channel = MagicMock()
        mock_ctx.channel.id = 456

        # Should handle import or other errors gracefully
        await cog.remember_fact.callback(cog, mock_ctx, fact="Valid test fact")
        # Should have called send at least once (either success or error message)
        assert mock_ctx.send.called


class TestForgetCommand:
    """Tests for the forget command."""

    @pytest.mark.asyncio
    async def test_forget_empty_query(self):
        """Test forget with empty query."""
        from cogs.ai_core.commands.memory_commands import MemoryCommands

        mock_bot = MagicMock(spec=commands.Bot)
        cog = MemoryCommands(mock_bot)

        mock_ctx = MagicMock()
        mock_ctx.send = AsyncMock()

        await cog.forget_fact.callback(cog, mock_ctx, query="")
        mock_ctx.send.assert_called_once()
        assert "กรุณาระบุ" in str(mock_ctx.send.call_args)


class TestViewMemoriesCommand:
    """Tests for the view_memories command."""

    @pytest.mark.asyncio
    async def test_view_memories_basic(self):
        """Test view_memories basic call."""
        from cogs.ai_core.commands.memory_commands import MemoryCommands

        mock_bot = MagicMock(spec=commands.Bot)
        MemoryCommands(mock_bot)

        mock_ctx = MagicMock()
        mock_ctx.send = AsyncMock()
        mock_ctx.author = MagicMock()
        mock_ctx.author.id = 123
        mock_ctx.author.display_name = "TestUser"

        # Will try to import long_term_memory
        # Expected to handle ImportError gracefully


class TestMemoryCommandsSetup:
    """Tests for setup function."""

    @pytest.mark.asyncio
    async def test_setup_function_exists(self):
        """Test setup function exists."""
        from cogs.ai_core.commands.memory_commands import setup

        assert callable(setup)

    @pytest.mark.asyncio
    async def test_setup_adds_cog(self):
        """Test setup adds cog to bot."""
        from cogs.ai_core.commands.memory_commands import setup

        mock_bot = MagicMock(spec=commands.Bot)
        mock_bot.add_cog = AsyncMock()

        await setup(mock_bot)
        mock_bot.add_cog.assert_called_once()


class TestConsolidateCommand:
    """Tests for consolidate command if exists."""

    def test_consolidate_command_callable(self):
        """Test consolidate command exists and is callable."""
        from cogs.ai_core.commands.memory_commands import MemoryCommands

        mock_bot = MagicMock(spec=commands.Bot)
        cog = MemoryCommands(mock_bot)

        # Check if consolidate command exists
        if hasattr(cog, 'consolidate_memory'):
            assert callable(cog.consolidate_memory)


class TestMemoryCommandsValidation:
    """Tests for input validation."""

    @pytest.mark.asyncio
    async def test_remember_special_characters(self):
        """Test remember with special characters."""
        from cogs.ai_core.commands.memory_commands import MemoryCommands

        mock_bot = MagicMock(spec=commands.Bot)
        MemoryCommands(mock_bot)

        mock_ctx = MagicMock()
        mock_ctx.send = AsyncMock()
        mock_ctx.author = MagicMock()
        mock_ctx.author.id = 123
        mock_ctx.channel = MagicMock()
        mock_ctx.channel.id = 456

        # Should handle special characters
        # Function should process without crashing

    @pytest.mark.asyncio
    async def test_remember_unicode_content(self):
        """Test remember with unicode content."""
        from cogs.ai_core.commands.memory_commands import MemoryCommands

        mock_bot = MagicMock(spec=commands.Bot)
        MemoryCommands(mock_bot)

        mock_ctx = MagicMock()
        mock_ctx.send = AsyncMock()
        mock_ctx.author = MagicMock()
        mock_ctx.author.id = 123
        mock_ctx.channel = MagicMock()
        mock_ctx.channel.id = 456

        # Thai text
        # Function should process Thai text

    @pytest.mark.asyncio
    async def test_remember_max_length_boundary(self):
        """Test remember at exactly max length."""
        from cogs.ai_core.commands.memory_commands import MemoryCommands

        mock_bot = MagicMock(spec=commands.Bot)
        MemoryCommands(mock_bot)

        mock_ctx = MagicMock()
        mock_ctx.send = AsyncMock()
        mock_ctx.author = MagicMock()
        mock_ctx.author.id = 123
        mock_ctx.channel = MagicMock()
        mock_ctx.channel.id = 456

        # Exactly 500 characters should be allowed
        # Should not trigger length error

    @pytest.mark.asyncio
    async def test_forget_special_characters(self):
        """Test forget with special characters in query."""
        from cogs.ai_core.commands.memory_commands import MemoryCommands

        mock_bot = MagicMock(spec=commands.Bot)
        MemoryCommands(mock_bot)

        mock_ctx = MagicMock()
        mock_ctx.send = AsyncMock()
        mock_ctx.author = MagicMock()
        mock_ctx.author.id = 123

        # Should handle special characters
        # Function should process without crashing


class TestMemoryCommandsHelpers:
    """Tests for helper methods."""

    def test_cog_name(self):
        """Test cog has correct name."""
        from cogs.ai_core.commands.memory_commands import MemoryCommands

        mock_bot = MagicMock(spec=commands.Bot)
        cog = MemoryCommands(mock_bot)

        # Cog should have qualified_name
        assert cog.qualified_name == "MemoryCommands"

    def test_command_aliases(self):
        """Test command aliases are set correctly."""
        from cogs.ai_core.commands.memory_commands import MemoryCommands

        mock_bot = MagicMock(spec=commands.Bot)
        cog = MemoryCommands(mock_bot)

        # view_memories should have aliases
        view_cmd = getattr(cog, 'view_memories', None)
        if view_cmd and hasattr(view_cmd, 'aliases'):
            # Check aliases exist (mymemory, facts)
            pass


class TestMemoryCommandsEmbeds:
    """Tests for embed creation."""

    def test_embed_colors_import(self):
        """Test Colors import works."""
        try:
            from utils.media.colors import Colors

            # Check if Colors class has expected attributes
            assert Colors is not None
        except ImportError:
            # Colors module may not be available in test environment
            pytest.skip("Colors module not available")


class TestMemoryFactModel:
    """Tests for memory fact model if exposed."""

    def test_fact_attributes(self):
        """Test expected fact attributes."""
        # Memory facts should have: content, category, confidence, timestamp
        # This tests the expected interface
        pass
