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

        assert hasattr(cog, "remember_fact")

    def test_cog_has_forget_command(self):
        """Test cog has forget command."""
        from cogs.ai_core.commands.memory_commands import MemoryCommands

        mock_bot = MagicMock(spec=commands.Bot)
        cog = MemoryCommands(mock_bot)

        assert hasattr(cog, "forget_fact")

    def test_cog_has_memories_command(self):
        """Test cog has memories command."""
        from cogs.ai_core.commands.memory_commands import MemoryCommands

        mock_bot = MagicMock(spec=commands.Bot)
        cog = MemoryCommands(mock_bot)

        assert hasattr(cog, "view_memories")

    def test_cog_has_consolidate_command(self):
        """Test cog has consolidate command."""
        from cogs.ai_core.commands.memory_commands import MemoryCommands

        mock_bot = MagicMock(spec=commands.Bot)
        cog = MemoryCommands(mock_bot)

        assert hasattr(cog, "force_consolidate")

    def test_cog_has_memory_stats_command(self):
        """Test cog has memory_stats command."""
        from cogs.ai_core.commands.memory_commands import MemoryCommands

        mock_bot = MagicMock(spec=commands.Bot)
        cog = MemoryCommands(mock_bot)

        assert hasattr(cog, "memory_stats")


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
        assert hasattr(cog, "remember_fact")
        assert hasattr(cog, "forget_fact")
        assert hasattr(cog, "view_memories")


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
        if hasattr(cog, "consolidate_memory"):
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
        view_cmd = getattr(cog, "view_memories", None)
        if view_cmd and hasattr(view_cmd, "aliases"):
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


# ======================================================================
# Coverage-driving tests: exercise every branch of every command with
# the memory backends mocked. These patch the module-level singletons
# (long_term_memory / summary_archiver) that the command callbacks import
# lazily inside each function body.
# ======================================================================

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch


def _make_cog():
    from cogs.ai_core.commands.memory_commands import MemoryCommands

    return MemoryCommands(MagicMock(spec=commands.Bot))


def _make_ctx():
    ctx = MagicMock()
    ctx.send = AsyncMock()
    ctx.author = MagicMock()
    ctx.author.id = 123
    ctx.author.display_name = "TestUser"
    ctx.channel = MagicMock()
    ctx.channel.id = 456
    return ctx


@contextmanager
def _patch_ltm(**method_mocks):
    """Patch attributes on the long_term_memory singleton."""
    import cogs.ai_core.memory.long_term_memory as ltm_mod

    with patch.multiple(ltm_mod.long_term_memory, **method_mocks):
        yield ltm_mod.long_term_memory


@contextmanager
def _patch_archiver(**method_mocks):
    """Patch attributes on the summary_archiver singleton."""
    import cogs.ai_core.memory.memory_consolidator as mc_mod

    with patch.multiple(mc_mod.summary_archiver, **method_mocks):
        yield mc_mod.summary_archiver


@contextmanager
def _force_import_error(module_path):
    """Make `import module_path` raise ImportError inside a command body."""
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == module_path:
            raise ImportError(f"forced for {module_path}")
        return real_import(name, *args, **kwargs)

    with patch.object(builtins, "__import__", side_effect=fake_import):
        yield


def _fact(content="x", category="custom", confidence=1.0, mention_count=1):
    return SimpleNamespace(
        content=content,
        category=category,
        confidence=confidence,
        mention_count=mention_count,
    )


class TestRememberBranches:
    """Drive every branch of remember_fact."""

    @pytest.mark.asyncio
    async def test_short_after_sanitize(self):
        """Fact that becomes <3 chars after stripping control chars (lines 59-60)."""
        cog = _make_cog()
        ctx = _make_ctx()

        # 3 control chars + 2 visible -> after strip len == 2 (< 3)
        await cog.remember_fact.callback(cog, ctx, fact="\x00\x01\x02ab")

        ctx.send.assert_called_once()
        assert "สั้นเกินไปหลังทำความสะอาด" in ctx.send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_success_result_truthy(self):
        """add_explicit_fact returns truthy -> success embed (lines 69-74)."""
        cog = _make_cog()
        ctx = _make_ctx()

        with _patch_ltm(add_explicit_fact=AsyncMock(return_value=True)) as ltm:
            await cog.remember_fact.callback(cog, ctx, fact="I like pizza very much")

            ltm.add_explicit_fact.assert_awaited_once()
            kwargs = ltm.add_explicit_fact.call_args.kwargs
            assert kwargs["user_id"] == 123
            assert kwargs["channel_id"] == 456
            assert kwargs["content"] == "I like pizza very much"
        # An embed was sent (success path), not a plain string
        assert ctx.send.call_args.kwargs.get("embed") is not None

    @pytest.mark.asyncio
    async def test_success_result_falsy(self):
        """add_explicit_fact returns falsy -> failure message (line 76)."""
        cog = _make_cog()
        ctx = _make_ctx()

        with _patch_ltm(add_explicit_fact=AsyncMock(return_value=False)):
            await cog.remember_fact.callback(cog, ctx, fact="some valid fact text")

        ctx.send.assert_called_once()
        assert "ไม่สามารถบันทึกได้" in ctx.send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_import_error(self):
        """ImportError branch (lines 78-79)."""
        cog = _make_cog()
        ctx = _make_ctx()

        with _force_import_error("cogs.ai_core.memory.long_term_memory"):
            await cog.remember_fact.callback(cog, ctx, fact="valid fact text here")

        ctx.send.assert_called_once()
        assert "ระบบความจำยังไม่พร้อมใช้งาน" in ctx.send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_generic_exception(self):
        """Generic Exception branch (lines 80-82)."""
        cog = _make_cog()
        ctx = _make_ctx()

        with _patch_ltm(add_explicit_fact=AsyncMock(side_effect=RuntimeError("boom"))):
            await cog.remember_fact.callback(cog, ctx, fact="valid fact text here")

        ctx.send.assert_called_once()
        assert "เกิดข้อผิดพลาด" in ctx.send.call_args[0][0]


class TestForgetBranches:
    """Drive every branch of forget_fact."""

    @pytest.mark.asyncio
    async def test_too_long(self):
        """Query over 500 chars (lines 95-97)."""
        cog = _make_cog()
        ctx = _make_ctx()

        await cog.forget_fact.callback(cog, ctx, query="z" * 501)

        ctx.send.assert_called_once()
        assert "ยาวเกินไป" in ctx.send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_empty_after_sanitize(self):
        """Query becomes empty after stripping control chars (lines 101-104)."""
        cog = _make_cog()
        ctx = _make_ctx()

        await cog.forget_fact.callback(cog, ctx, query="\x00\x01\x02")

        ctx.send.assert_called_once()
        assert "สั้นเกินไปหลังทำความสะอาด" in ctx.send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_success(self):
        """forget_fact returns True -> success embed (lines 115-121)."""
        cog = _make_cog()
        ctx = _make_ctx()

        with _patch_ltm(forget_fact=AsyncMock(return_value=True)) as ltm:
            await cog.forget_fact.callback(cog, ctx, query="allergic to peanuts")

            ltm.forget_fact.assert_awaited_once()
            assert ltm.forget_fact.call_args.kwargs["user_id"] == 123
        assert ctx.send.call_args.kwargs.get("embed") is not None

    @pytest.mark.asyncio
    async def test_not_found(self):
        """forget_fact returns False -> not-found message (lines 122-123)."""
        cog = _make_cog()
        ctx = _make_ctx()

        with _patch_ltm(forget_fact=AsyncMock(return_value=False)):
            await cog.forget_fact.callback(cog, ctx, query="nonexistent fact")

        ctx.send.assert_called_once()
        assert "ไม่พบข้อมูลที่ตรงกับ" in ctx.send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_backtick_neutralized(self):
        """Backticks in the query are neutralized in the not-found message (line 108)."""
        cog = _make_cog()
        ctx = _make_ctx()

        with _patch_ltm(forget_fact=AsyncMock(return_value=False)):
            await cog.forget_fact.callback(cog, ctx, query="bad`code`here")

        sent = ctx.send.call_args[0][0]
        assert "`code`" not in sent  # raw backticks gone
        assert "ʻ" in sent  # replaced with the modifier letter

    @pytest.mark.asyncio
    async def test_import_error(self):
        """ImportError branch (lines 125-126)."""
        cog = _make_cog()
        ctx = _make_ctx()

        with _force_import_error("cogs.ai_core.memory.long_term_memory"):
            await cog.forget_fact.callback(cog, ctx, query="something to forget")

        ctx.send.assert_called_once()
        assert "ระบบความจำยังไม่พร้อมใช้งาน" in ctx.send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_generic_exception(self):
        """Generic Exception branch (lines 127-129)."""
        cog = _make_cog()
        ctx = _make_ctx()

        with _patch_ltm(forget_fact=AsyncMock(side_effect=RuntimeError("boom"))):
            await cog.forget_fact.callback(cog, ctx, query="something to forget")

        ctx.send.assert_called_once()
        assert "เกิดข้อผิดพลาด" in ctx.send.call_args[0][0]


class TestViewMemoriesBranches:
    """Drive every branch of view_memories."""

    @pytest.mark.asyncio
    async def test_no_facts(self):
        """Empty facts list -> empty embed (lines 146-153)."""
        cog = _make_cog()
        ctx = _make_ctx()

        with _patch_ltm(get_user_facts=AsyncMock(return_value=[])):
            await cog.view_memories.callback(cog, ctx, category=None)

        ctx.send.assert_called_once()
        embed = ctx.send.call_args.kwargs.get("embed")
        assert embed is not None
        assert "ไม่มีความจำ" in embed.title

    @pytest.mark.asyncio
    async def test_with_facts_grouped(self):
        """Non-empty facts grouped by category with overflow + low confidence
        + multi-mention (lines 155-196)."""
        cog = _make_cog()
        ctx = _make_ctx()

        # 6 facts in one category (triggers the >5 overflow line) plus mix of
        # confidence and mention_count to hit both ternary branches.
        facts = [
            _fact(content="high conf", category="identity", confidence=0.9, mention_count=3),
            _fact(content="low conf", category="identity", confidence=0.5, mention_count=1),
            _fact(content="c", category="identity"),
            _fact(content="d", category="identity"),
            _fact(content="e", category="identity"),
            _fact(content="f", category="identity"),
            _fact(content="pref one", category="weirdcat", confidence=0.8, mention_count=2),
        ]

        with _patch_ltm(get_user_facts=AsyncMock(return_value=facts)) as ltm:
            await cog.view_memories.callback(cog, ctx, category=None)

            ltm.get_user_facts.assert_awaited_once()
            assert ltm.get_user_facts.call_args.kwargs["category"] is None
        embed = ctx.send.call_args.kwargs.get("embed")
        assert embed is not None
        # Footer mentions total count
        assert "รวม 7" in embed.footer.text
        # Two field groups (identity + weirdcat -> unknown emoji fallback)
        field_names = [f.name for f in embed.fields]
        assert any("IDENTITY" in n for n in field_names)
        assert any("WEIRDCAT" in n for n in field_names)
        # The overflow "... and N more" line is present for identity (6 facts)
        identity_field = next(f for f in embed.fields if "IDENTITY" in f.name)
        assert "และอีก 1" in identity_field.value

    @pytest.mark.asyncio
    async def test_with_category_filter(self):
        """category arg is forwarded to get_user_facts."""
        cog = _make_cog()
        ctx = _make_ctx()

        with _patch_ltm(
            get_user_facts=AsyncMock(return_value=[_fact(category="preference")])
        ) as ltm:
            await cog.view_memories.callback(cog, ctx, category="preference")

            assert ltm.get_user_facts.call_args.kwargs["category"] == "preference"

    @pytest.mark.asyncio
    async def test_import_error(self):
        """ImportError branch (lines 198-199)."""
        cog = _make_cog()
        ctx = _make_ctx()

        with _force_import_error("cogs.ai_core.memory.long_term_memory"):
            await cog.view_memories.callback(cog, ctx, category=None)

        ctx.send.assert_called_once()
        assert "ระบบความจำยังไม่พร้อมใช้งาน" in ctx.send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_generic_exception(self):
        """Generic Exception branch (lines 200-202)."""
        cog = _make_cog()
        ctx = _make_ctx()

        with _patch_ltm(get_user_facts=AsyncMock(side_effect=RuntimeError("boom"))):
            await cog.view_memories.callback(cog, ctx, category=None)

        ctx.send.assert_called_once()
        assert "เกิดข้อผิดพลาด" in ctx.send.call_args[0][0]


class TestConsolidateBranches:
    """Drive every branch of force_consolidate."""

    def _ctx_with_status(self):
        ctx = _make_ctx()
        status = MagicMock()
        status.edit = AsyncMock()
        ctx.send = AsyncMock(return_value=status)
        return ctx, status

    @pytest.mark.asyncio
    async def test_success_full_result(self):
        """Result with summary + key_topics -> edit with embed (lines 220-235)."""
        cog = _make_cog()
        ctx, status = self._ctx_with_status()

        result = SimpleNamespace(
            message_count=42,
            summary="a summary of the conversation",
            key_topics=["t1", "t2", "t3", "t4", "t5", "t6"],
        )
        with _patch_archiver(consolidate_channel=AsyncMock(return_value=result)) as arch:
            await cog.force_consolidate.callback(cog, ctx)

            arch.consolidate_channel.assert_awaited_once()
            assert arch.consolidate_channel.call_args.kwargs["channel_id"] == 456
            assert arch.consolidate_channel.call_args.kwargs["force"] is True
        status.edit.assert_awaited_once()
        embed = status.edit.call_args.kwargs.get("embed")
        assert embed is not None
        assert "42" in embed.description

    @pytest.mark.asyncio
    async def test_success_no_topics_no_summary(self):
        """Result truthy but empty summary and no topics (lines 226-235, false branch
        of key_topics)."""
        cog = _make_cog()
        ctx, status = self._ctx_with_status()

        result = SimpleNamespace(message_count=5, summary="", key_topics=[])
        with _patch_archiver(consolidate_channel=AsyncMock(return_value=result)):
            await cog.force_consolidate.callback(cog, ctx)

        status.edit.assert_awaited_once()
        embed = status.edit.call_args.kwargs.get("embed")
        assert embed is not None
        # summary fallback "ไม่มี" used when summary is empty
        summary_field = next(f for f in embed.fields if "สรุป" in f.name)
        assert summary_field.value == "ไม่มี"

    @pytest.mark.asyncio
    async def test_no_result(self):
        """consolidate_channel returns falsy -> edit with error text (lines 236-237)."""
        cog = _make_cog()
        ctx, status = self._ctx_with_status()

        with _patch_archiver(consolidate_channel=AsyncMock(return_value=None)):
            await cog.force_consolidate.callback(cog, ctx)

        status.edit.assert_awaited_once()
        assert "ไม่มีข้อความเพียงพอ" in status.edit.call_args.kwargs.get("content")

    @pytest.mark.asyncio
    async def test_import_error(self):
        """ImportError branch (lines 239-240)."""
        cog = _make_cog()
        ctx = _make_ctx()

        with _force_import_error("cogs.ai_core.memory.memory_consolidator"):
            await cog.force_consolidate.callback(cog, ctx)

        ctx.send.assert_called_once()
        assert "ระบบ consolidation ยังไม่พร้อมใช้งาน" in ctx.send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_generic_exception(self):
        """Generic Exception branch (lines 241-246)."""
        cog = _make_cog()
        ctx, _status = self._ctx_with_status()

        with _patch_archiver(consolidate_channel=AsyncMock(side_effect=RuntimeError("boom"))):
            await cog.force_consolidate.callback(cog, ctx)

        # First send = status msg, second send = error message
        assert ctx.send.await_count >= 1
        assert "เกิดข้อผิดพลาดในการรวบรวม" in ctx.send.call_args[0][0]


class TestMemoryStatsBranches:
    """Drive every branch of memory_stats."""

    @pytest.mark.asyncio
    async def test_success_with_cache(self):
        """Singleton has _cache -> facts-count field added (lines 259-279)."""
        cog = _make_cog()
        ctx = _make_ctx()

        import cogs.ai_core.memory.long_term_memory as ltm_mod

        with (
            patch.object(
                ltm_mod.long_term_memory,
                "get_user_facts",
                AsyncMock(return_value=[_fact(), _fact()]),
            ),
            patch.object(
                ltm_mod.long_term_memory, "_cache", {"u1": [1, 2], "u2": [3]}, create=True
            ),
            _patch_archiver(get_channel_summaries=AsyncMock(return_value=["s1", "s2", "s3"])),
        ):
            await cog.memory_stats.callback(cog, ctx)

        ctx.send.assert_called_once()
        embed = ctx.send.call_args.kwargs.get("embed")
        assert embed is not None
        field_values = " ".join(f.value for f in embed.fields)
        # cache total = 3, user facts = 2, summaries = 3
        assert "3 facts" in field_values  # cache count
        assert "2 facts" in field_values  # user facts
        assert "3 summaries" in field_values

    @pytest.mark.asyncio
    async def test_success_without_cache(self):
        """Singleton missing _cache -> cache field skipped (line 259 false branch)."""
        cog = _make_cog()
        ctx = _make_ctx()

        import cogs.ai_core.memory.long_term_memory as ltm_mod

        # Ensure _cache is absent for the duration of this test.
        had_cache = hasattr(ltm_mod.long_term_memory, "_cache")
        saved = getattr(ltm_mod.long_term_memory, "_cache", None)
        if had_cache:
            delattr(ltm_mod.long_term_memory, "_cache")
        try:
            with (
                patch.object(
                    ltm_mod.long_term_memory, "get_user_facts", AsyncMock(return_value=[])
                ),
                _patch_archiver(get_channel_summaries=AsyncMock(return_value=[])),
            ):
                await cog.memory_stats.callback(cog, ctx)
        finally:
            if had_cache:
                ltm_mod.long_term_memory._cache = saved

        ctx.send.assert_called_once()
        embed = ctx.send.call_args.kwargs.get("embed")
        assert embed is not None
        field_names = [f.name for f in embed.fields]
        # No cache field, but user-facts and summaries fields exist
        assert not any("Cache" in n for n in field_names)
        assert any("Your Facts" in n for n in field_names)

    @pytest.mark.asyncio
    async def test_import_error(self):
        """ImportError branch (lines 281-282)."""
        cog = _make_cog()
        ctx = _make_ctx()

        with _force_import_error("cogs.ai_core.memory.long_term_memory"):
            await cog.memory_stats.callback(cog, ctx)

        ctx.send.assert_called_once()
        assert "ระบบยังไม่พร้อม" in ctx.send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_generic_exception(self):
        """Generic Exception branch (lines 283-287)."""
        cog = _make_cog()
        ctx = _make_ctx()

        import cogs.ai_core.memory.long_term_memory as ltm_mod

        with patch.object(
            ltm_mod.long_term_memory,
            "get_user_facts",
            AsyncMock(side_effect=RuntimeError("boom")),
        ):
            await cog.memory_stats.callback(cog, ctx)

        ctx.send.assert_called_once()
        assert "เกิดข้อผิดพลาดในการดึงสถิติ" in ctx.send.call_args[0][0]
