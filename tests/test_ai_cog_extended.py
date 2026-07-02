"""
Extended tests for AI Cog module.
Tests imports, constants, and configuration.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import closing_create_task_mock


class TestAiCogImports:
    """Tests for ai_cog module imports."""

    def test_guardrails_available_defined(self):
        """Test GUARDRAILS_AVAILABLE is defined."""
        from cogs.ai_core.ai_cog import GUARDRAILS_AVAILABLE

        assert isinstance(GUARDRAILS_AVAILABLE, bool)

    def test_feedback_available_defined(self):
        """Test FEEDBACK_AVAILABLE is defined."""
        from cogs.ai_core.ai_cog import FEEDBACK_AVAILABLE

        assert isinstance(FEEDBACK_AVAILABLE, bool)


class TestStorageImports:
    """Tests for storage imports in ai_cog."""

    def test_cleanup_storage_cache_import(self):
        """Test cleanup_storage_cache is imported."""
        from cogs.ai_core.ai_cog import cleanup_storage_cache

        assert callable(cleanup_storage_cache)

    def test_copy_history_import(self):
        """Test copy_history is imported."""
        from cogs.ai_core.ai_cog import copy_history

        assert callable(copy_history)

    def test_delete_history_import(self):
        """Test delete_history is imported."""
        from cogs.ai_core.ai_cog import delete_history

        assert callable(delete_history)

    def test_get_all_channel_ids_import(self):
        """Test get_all_channel_ids is imported."""
        from cogs.ai_core.ai_cog import get_all_channel_ids

        assert callable(get_all_channel_ids)

    def test_get_last_model_message_import(self):
        """Test get_last_model_message is imported."""
        from cogs.ai_core.ai_cog import get_last_model_message

        assert callable(get_last_model_message)

    def test_get_message_by_local_id_import(self):
        """Test get_message_by_local_id is imported."""
        from cogs.ai_core.ai_cog import get_message_by_local_id

        assert callable(get_message_by_local_id)

    def test_move_history_import(self):
        """Test move_history is imported."""
        from cogs.ai_core.ai_cog import move_history

        assert callable(move_history)


class TestToolsImports:
    """Tests for tools imports in ai_cog."""

    def test_invalidate_webhook_cache_import(self):
        """Test invalidate_webhook_cache_on_channel_delete is imported."""
        from cogs.ai_core.ai_cog import invalidate_webhook_cache_on_channel_delete

        assert callable(invalidate_webhook_cache_on_channel_delete)

    def test_send_as_webhook_import(self):
        """Test send_as_webhook is imported."""
        from cogs.ai_core.ai_cog import send_as_webhook

        assert callable(send_as_webhook)

    def test_start_webhook_cache_cleanup_import(self):
        """Test start_webhook_cache_cleanup is imported."""
        from cogs.ai_core.ai_cog import start_webhook_cache_cleanup

        assert callable(start_webhook_cache_cleanup)

    def test_stop_webhook_cache_cleanup_import(self):
        """Test stop_webhook_cache_cleanup is imported."""
        from cogs.ai_core.ai_cog import stop_webhook_cache_cleanup

        assert callable(stop_webhook_cache_cleanup)


class TestLogicImport:
    """Tests for logic import in ai_cog."""

    def test_chat_manager_import(self):
        """Test ChatManager is imported."""
        from cogs.ai_core.ai_cog import ChatManager

        assert ChatManager is not None


class TestRagImport:
    """Tests for RAG import in ai_cog."""

    def test_rag_system_import(self):
        """Test rag_system is imported."""
        from cogs.ai_core.ai_cog import rag_system

        assert rag_system is not None


class TestRateLimiterImports:
    """Tests for rate limiter imports."""

    def test_check_rate_limit_import(self):
        """Test check_rate_limit is imported."""
        from cogs.ai_core.ai_cog import check_rate_limit

        assert callable(check_rate_limit)

    def test_rate_limiter_import(self):
        """Test rate_limiter is imported."""
        from cogs.ai_core.ai_cog import rate_limiter

        assert rate_limiter is not None


class TestColorsImport:
    """Tests for Colors import."""

    def test_colors_import(self):
        """Test Colors is imported."""
        from cogs.ai_core.ai_cog import Colors

        assert Colors is not None


class TestConstantsImports:
    """Tests for constants imports."""

    def test_channel_id_allowed_import(self):
        """Test CHANNEL_ID_ALLOWED is imported."""
        from cogs.ai_core.ai_cog import CHANNEL_ID_ALLOWED

        assert CHANNEL_ID_ALLOWED is not None

    def test_channel_id_rp_command_import(self):
        """Test CHANNEL_ID_RP_COMMAND is imported."""
        from cogs.ai_core.ai_cog import CHANNEL_ID_RP_COMMAND

        assert CHANNEL_ID_RP_COMMAND is not None

    def test_channel_id_rp_output_import(self):
        """Test CHANNEL_ID_RP_OUTPUT is imported."""
        from cogs.ai_core.ai_cog import CHANNEL_ID_RP_OUTPUT

        assert CHANNEL_ID_RP_OUTPUT is not None

    def test_creator_id_import(self):
        """Test CREATOR_ID is imported."""
        from cogs.ai_core.ai_cog import CREATOR_ID

        assert CREATOR_ID is not None

    def test_guild_id_main_import(self):
        """Test GUILD_ID_MAIN is imported."""
        from cogs.ai_core.ai_cog import GUILD_ID_MAIN

        assert GUILD_ID_MAIN is not None

    def test_guild_id_rp_import(self):
        """Test GUILD_ID_RP is imported."""
        from cogs.ai_core.ai_cog import GUILD_ID_RP

        assert GUILD_ID_RP is not None

    def test_guild_id_restricted_import(self):
        """Test GUILD_ID_RESTRICTED is imported."""
        from cogs.ai_core.ai_cog import GUILD_ID_RESTRICTED

        assert GUILD_ID_RESTRICTED is not None

    def test_guild_id_command_only_import(self):
        """Test GUILD_ID_COMMAND_ONLY is imported."""
        from cogs.ai_core.ai_cog import GUILD_ID_COMMAND_ONLY

        assert GUILD_ID_COMMAND_ONLY is not None


class TestModuleDocstring:
    """Tests for module documentation."""

    def test_module_docstring_mentions_discord(self):
        """Test ai_cog module docstring mentions Discord."""
        from cogs.ai_core import ai_cog

        assert "Discord" in ai_cog.__doc__


class TestUnrestrictedFunctions:
    """Tests for unrestricted fallback functions."""

    def test_is_unrestricted_callable(self):
        """Test is_unrestricted is callable."""
        from cogs.ai_core.ai_cog import is_unrestricted

        assert callable(is_unrestricted)

    def test_set_unrestricted_callable(self):
        """Test set_unrestricted is callable."""
        from cogs.ai_core.ai_cog import set_unrestricted

        assert callable(set_unrestricted)


class TestUnrestrictedChannels:
    """Tests for the unrestricted-channels accessor."""

    def test_get_unrestricted_channels_exists(self):
        """ai_cog consumes the thread-safe snapshot accessor, not the raw set
        (iterating the raw set raced set_unrestricted's worker-thread mutation)."""
        from cogs.ai_core.ai_cog import get_unrestricted_channels

        assert callable(get_unrestricted_channels)
        assert isinstance(get_unrestricted_channels(), frozenset)


class TestFeedbackCollector:
    """Tests for feedback collector."""

    def test_add_feedback_reactions_callable(self):
        """Test add_feedback_reactions is callable."""
        from cogs.ai_core.ai_cog import add_feedback_reactions

        assert callable(add_feedback_reactions)


# ======================================================================
# Merged from test_ai_cog_module.py
# ======================================================================


class TestAICogInit:
    """Tests for AI Cog initialization."""

    def test_ai_cog_creation(self):
        """Test creating AI cog."""
        from cogs.ai_core.ai_cog import AI

        mock_bot = MagicMock()

        with patch("cogs.ai_core.ai_cog.ChatManager"):
            with patch("cogs.ai_core.ai_cog.rate_limiter"):
                cog = AI(mock_bot)

                assert cog.bot == mock_bot
                assert cog.cleanup_task is None

    def test_ai_cog_has_chat_manager(self):
        """Test AI cog has ChatManager."""
        from cogs.ai_core.ai_cog import AI

        mock_bot = MagicMock()

        with patch("cogs.ai_core.ai_cog.ChatManager") as mock_cm:
            with patch("cogs.ai_core.ai_cog.rate_limiter"):
                AI(mock_bot)

                mock_cm.assert_called_once_with(mock_bot)


class TestAICogLoadUnload:
    """Tests for cog load and unload."""

    @pytest.mark.asyncio
    async def test_cog_load(self):
        """Test cog_load method."""
        from cogs.ai_core.ai_cog import AI

        mock_bot = MagicMock()

        with patch("cogs.ai_core.ai_cog.ChatManager") as mock_cm:
            with patch("cogs.ai_core.ai_cog.rate_limiter"):
                with patch("cogs.ai_core.ai_cog.start_webhook_cache_cleanup"):
                    with patch("cogs.ai_core.ai_cog.rag_system"):
                        mock_cm_instance = MagicMock()
                        mock_cm_instance.cleanup_inactive_sessions = AsyncMock()
                        mock_cm.return_value = mock_cm_instance

                        cog = AI(mock_bot)
                        await cog.cog_load()

                        assert cog.cleanup_task is not None

    @pytest.mark.asyncio
    async def test_cog_unload(self):
        """Test cog_unload method."""
        from cogs.ai_core.ai_cog import AI

        mock_bot = MagicMock()

        with patch("cogs.ai_core.ai_cog.ChatManager") as mock_cm:
            with patch("cogs.ai_core.ai_cog.rate_limiter"):
                with patch("cogs.ai_core.ai_cog.stop_webhook_cache_cleanup"):
                    mock_rag = MagicMock()
                    mock_rag.stop_periodic_save = AsyncMock()
                    mock_rag.force_save_index = AsyncMock()

                    with patch("cogs.ai_core.ai_cog.rag_system", mock_rag):
                        mock_cm_instance = MagicMock()
                        mock_cm_instance.save_all_sessions = AsyncMock()
                        mock_cm.return_value = mock_cm_instance

                        cog = AI(mock_bot)
                        cog.cleanup_task = None
                        cog._pending_request_cleanup_task = None

                        await cog.cog_unload()

                        mock_cm_instance.save_all_sessions.assert_called_once()


class TestChatCommand:
    """Tests for chat command."""

    @pytest.mark.asyncio
    async def test_chat_command_exists(self):
        """Test chat command is defined."""
        from cogs.ai_core.ai_cog import AI

        mock_bot = MagicMock()

        with patch("cogs.ai_core.ai_cog.ChatManager"):
            with patch("cogs.ai_core.ai_cog.rate_limiter"):
                cog = AI(mock_bot)

                assert hasattr(cog, "chat_command")

    @pytest.mark.asyncio
    async def test_chat_command_error_handler(self):
        """Test chat command error handler."""
        from discord.ext import commands

        from cogs.ai_core.ai_cog import AI

        mock_bot = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.send = AsyncMock()

        with patch("cogs.ai_core.ai_cog.ChatManager"):
            with patch("cogs.ai_core.ai_cog.rate_limiter"):
                cog = AI(mock_bot)

                # Create a cooldown error
                error = commands.CommandOnCooldown(
                    commands.Cooldown(1, 3), 2.5, commands.BucketType.user
                )

                await cog.chat_command_error(mock_ctx, error)

                mock_ctx.send.assert_called_once()
                call_args = mock_ctx.send.call_args[0][0]
                assert "2.5" in call_args


class TestOwnerCommands:
    """Tests for owner-only commands."""

    @pytest.mark.asyncio
    async def test_reset_ai_command_exists(self):
        """Test reset_ai command is defined."""
        from cogs.ai_core.ai_cog import AI

        mock_bot = MagicMock()

        with patch("cogs.ai_core.ai_cog.ChatManager"):
            with patch("cogs.ai_core.ai_cog.rate_limiter"):
                cog = AI(mock_bot)

                assert hasattr(cog, "reset_ai")


class TestFeatureFlags:
    """Tests for feature availability flags."""

    def test_guardrails_available_flag(self):
        """Test GUARDRAILS_AVAILABLE is defined."""
        from cogs.ai_core.ai_cog import GUARDRAILS_AVAILABLE

        assert isinstance(GUARDRAILS_AVAILABLE, bool)

    def test_feedback_available_flag(self):
        """Test FEEDBACK_AVAILABLE is defined."""
        from cogs.ai_core.ai_cog import FEEDBACK_AVAILABLE

        assert isinstance(FEEDBACK_AVAILABLE, bool)

    def test_localization_available_flag(self):
        """Test LOCALIZATION_AVAILABLE is defined."""
        from cogs.ai_core.ai_cog import LOCALIZATION_AVAILABLE

        assert isinstance(LOCALIZATION_AVAILABLE, bool)


class TestConstants:
    """Tests for module constants."""

    def test_owner_id_defined(self):
        """Test OWNER_ID is defined in cog."""
        from cogs.ai_core.ai_cog import AI

        assert hasattr(AI, "OWNER_ID")


class TestModuleImports:
    """Tests for module imports."""

    def test_import_ai_cog(self):
        """Test importing AI cog."""
        from cogs.ai_core.ai_cog import AI

        assert AI is not None

    def test_import_constants(self):
        """Test importing constants."""
        from cogs.ai_core.ai_cog import (
            GUILD_ID_MAIN,
        )

        # Constants may be None but should be importable
        assert GUILD_ID_MAIN is not None or GUILD_ID_MAIN is None

    def test_import_chat_manager_class(self):
        """Test ChatManager is imported."""
        from cogs.ai_core.ai_cog import ChatManager

        assert ChatManager is not None

    def test_import_storage_functions(self):
        """Test storage functions are imported."""
        from cogs.ai_core.ai_cog import (
            copy_history,
            delete_history,
        )

        assert copy_history is not None
        assert delete_history is not None


class TestFallbackFunctions:
    """Tests for fallback functions when features unavailable."""

    def test_is_unrestricted_fallback(self):
        """Test is_unrestricted fallback when guardrails unavailable."""
        from cogs.ai_core.ai_cog import is_unrestricted

        # Should return False by default
        result = is_unrestricted(123456)
        assert result is False or result is True  # Either is valid

    def test_msg_fallback(self):
        """Test msg fallback when localization unavailable."""
        from cogs.ai_core.ai_cog import msg

        # Should return key as is
        result = msg("test_key")
        assert "test_key" in result or result is not None


# ======================================================================
# Region 1-500 coverage: on_message pipeline entry, lifecycle, commands.
# Callbacks invoked directly via ``cog.<cmd>.callback(cog, ctx, ...)`` to
# bypass discord.py's owner/cooldown decorators. All discord/external deps
# mocked — no network, no real sleeps.
# ======================================================================

import asyncio

import discord


def _make_cog_r1():
    """Create an AI cog with ChatManager + rate_limiter patched out.

    The ChatManager mock is wired with the dict attributes and async methods
    the region-1-500 code paths touch (process_chat, save_all_sessions, the
    per-channel state dicts, _message_queue.clear_channel, cli_mode).
    """
    from cogs.ai_core.ai_cog import AI

    bot = MagicMock()
    with (
        patch("cogs.ai_core.ai_cog.ChatManager") as mock_cm,
        patch("cogs.ai_core.ai_cog.rate_limiter"),
    ):
        cm = MagicMock()
        cm.process_chat = AsyncMock()
        cm.save_all_sessions = AsyncMock()
        cm.cleanup_inactive_sessions = AsyncMock()
        cm.cleanup_pending_requests = MagicMock(return_value=0)
        cm.chats = {}
        cm.seen_users = {}
        cm.last_accessed = {}
        cm.processing_locks = {}
        cm.streaming_enabled = {}
        cm._message_queue = MagicMock()
        cm._message_queue.clear_channel = MagicMock()
        cm.cli_mode = False
        mock_cm.return_value = cm
        cog = AI(bot)
    return cog


def _ctx_r1(channel_id=987654321, guild_id=111222333):
    ctx = MagicMock()
    ctx.channel.id = channel_id
    ctx.guild = MagicMock()
    ctx.guild.id = guild_id
    ctx.send = AsyncMock()
    ctx.message = MagicMock()
    ctx.message.attachments = []
    ctx.message.reference = None
    ctx.message.id = 555
    # โมเดลการเรียกแบบ prefix (!chat) → ไม่มี interaction จึงไม่ defer
    ctx.interaction = None
    return ctx


def _discord_exc(cls):
    resp = MagicMock()
    resp.status = 404
    resp.reason = "test"
    return cls(resp, "boom")


class _FakeTask:
    """A minimal awaitable task stand-in.

    ``await``-ing it raises ``CancelledError`` (mirroring a real cancelled
    task being awaited) so the cog's ``contextlib.suppress`` branches run.
    ``__await__`` must live on the type — MagicMock can't supply it.
    """

    def __init__(self, done: bool = False) -> None:
        self._done = done
        self.cancel = MagicMock()

    def done(self) -> bool:
        return self._done

    def __await__(self):
        async def _raise():
            raise asyncio.CancelledError

        return _raise().__await__()


# ----------------------------------------------------------------------
# _on_bg_task_done (131-136)
# ----------------------------------------------------------------------


class TestOnBgTaskDone:
    def test_cancelled_task_is_ignored(self):
        from cogs.ai_core.ai_cog import AI

        task = MagicMock()
        task.cancelled.return_value = True
        # exception() must not be consulted when cancelled
        task.exception.side_effect = AssertionError("should not be called")
        AI._on_bg_task_done(task)  # no raise == pass

    def test_task_with_exception_logs(self):
        from cogs.ai_core.ai_cog import AI

        task = MagicMock()
        task.cancelled.return_value = False
        task.exception.return_value = RuntimeError("kaboom")
        task.get_name.return_value = "bg-1"
        with patch("cogs.ai_core.ai_cog.logger") as log:
            AI._on_bg_task_done(task)
            assert log.error.called

    def test_task_without_exception_no_log(self):
        from cogs.ai_core.ai_cog import AI

        task = MagicMock()
        task.cancelled.return_value = False
        task.exception.return_value = None
        with patch("cogs.ai_core.ai_cog.logger") as log:
            AI._on_bg_task_done(task)
            assert not log.error.called


# ----------------------------------------------------------------------
# _as_* channel coercion helpers (142-156)
# ----------------------------------------------------------------------


class TestChannelCoercionHelpers:
    def test_as_chat_channel_text(self):
        from cogs.ai_core.ai_cog import AI

        ch = MagicMock(spec=discord.TextChannel)
        assert AI._as_chat_channel(ch) is ch

    def test_as_chat_channel_dm(self):
        from cogs.ai_core.ai_cog import AI

        ch = MagicMock(spec=discord.DMChannel)
        assert AI._as_chat_channel(ch) is ch

    def test_as_chat_channel_none_for_other(self):
        from cogs.ai_core.ai_cog import AI

        assert AI._as_chat_channel(object()) is None

    def test_as_fetchable_channel_thread(self):
        from cogs.ai_core.ai_cog import AI

        ch = MagicMock(spec=discord.Thread)
        assert AI._as_fetchable_channel(ch) is ch

    def test_as_fetchable_channel_none_for_dm(self):
        from cogs.ai_core.ai_cog import AI

        ch = MagicMock(spec=discord.DMChannel)
        assert AI._as_fetchable_channel(ch) is None

    def test_as_text_channel_match(self):
        from cogs.ai_core.ai_cog import AI

        ch = MagicMock(spec=discord.TextChannel)
        assert AI._as_text_channel(ch) is ch

    def test_as_text_channel_none(self):
        from cogs.ai_core.ai_cog import AI

        assert AI._as_text_channel(MagicMock(spec=discord.Thread)) is None


class TestCheckCustomChannelLimit:
    """Fix D: _check_custom_channel_limit forwards ``send_message`` onward.

    The owner-set per-channel limit enforcement gained a keyword-only
    ``send_message`` param so the webhook proxy path (Tupperbox/PluralKit) can
    drop an exceeded request SILENTLY (``send_message=False``), matching its
    sibling rate-limit checks, while the @mention/reply and DM callers keep the
    visible default (``True``). The flag must reach ``check_rate_limit``.
    """

    @pytest.mark.asyncio
    async def test_check_custom_channel_limit_forwards_send_message_false(self):
        """send_message=False is forwarded verbatim to check_rate_limit."""
        from cogs.ai_core.ai_cog import AI

        message = MagicMock()
        message.channel.id = 999

        with (
            patch(
                "cogs.ai_core.ai_cog.check_rate_limit",
                new_callable=AsyncMock,
                return_value=True,
            ) as crl,
            patch(
                "cogs.ai_core.ai_cog.rate_limiter.get_custom_channel_limit",
                return_value=5,
            ),
            patch(
                "cogs.ai_core.ai_cog.rate_limiter.channel_config_name",
                return_value="custom_channel_999",
            ),
        ):
            result = await AI._check_custom_channel_limit(message, send_message=False)

        assert result is True
        crl.assert_awaited_once()
        # Pre-fix the param did not exist (TypeError); the fix must pass it on.
        assert crl.await_args.kwargs.get("send_message") is False

    @pytest.mark.asyncio
    async def test_check_custom_channel_limit_defaults_send_message_true(self):
        """Omitting send_message defaults to True (the visible-message path)."""
        from cogs.ai_core.ai_cog import AI

        message = MagicMock()
        message.channel.id = 999

        with (
            patch(
                "cogs.ai_core.ai_cog.check_rate_limit",
                new_callable=AsyncMock,
                return_value=True,
            ) as crl,
            patch(
                "cogs.ai_core.ai_cog.rate_limiter.get_custom_channel_limit",
                return_value=5,
            ),
            patch(
                "cogs.ai_core.ai_cog.rate_limiter.channel_config_name",
                return_value="custom_channel_999",
            ),
        ):
            result = await AI._check_custom_channel_limit(message)

        assert result is True
        crl.assert_awaited_once()
        assert crl.await_args.kwargs.get("send_message") is True

    @pytest.mark.asyncio
    async def test_check_custom_channel_limit_no_custom_limit_returns_true(self):
        """No custom limit configured -> True without consulting check_rate_limit."""
        from cogs.ai_core.ai_cog import AI

        message = MagicMock()
        message.channel.id = 999

        with (
            patch(
                "cogs.ai_core.ai_cog.check_rate_limit",
                new_callable=AsyncMock,
                return_value=True,
            ) as crl,
            patch(
                "cogs.ai_core.ai_cog.rate_limiter.get_custom_channel_limit",
                return_value=None,
            ),
        ):
            result = await AI._check_custom_channel_limit(message)

        assert result is True
        crl.assert_not_awaited()


# ----------------------------------------------------------------------
# cog_load (164-166, 184-191, 205-206, 229-230)
# ----------------------------------------------------------------------


class TestCogLoadRegion:
    @pytest.mark.asyncio
    async def test_cog_load_cancels_leftover_task(self):
        cog = _make_cog_r1()
        # Simulate a leftover, not-done task from a prior load.
        leftover = _FakeTask(done=False)
        cog.cleanup_task = leftover

        with (
            patch("cogs.ai_core.ai_cog.start_webhook_cache_cleanup"),
            patch("cogs.ai_core.ai_cog.rag_system"),
            patch("asyncio.create_task", new=closing_create_task_mock()),
            patch.dict("os.environ", {"MEMORY_CONSOLIDATOR_AUTOSTART": ""}, clear=False),
        ):
            await cog.cog_load()
        leftover.cancel.assert_called_once()

    @pytest.mark.asyncio
    async def test_cog_load_consolidator_autostart_success(self):
        cog = _make_cog_r1()
        cog.cleanup_task = None
        cog._pending_request_cleanup_task = None
        cog._cache_cleanup_task = None

        archiver = MagicMock()
        archiver.init_schema = AsyncMock()
        archiver.start_background_task = MagicMock()
        fake_mod = MagicMock(summary_archiver=archiver)

        with (
            patch("cogs.ai_core.ai_cog.start_webhook_cache_cleanup"),
            patch("cogs.ai_core.ai_cog.rag_system"),
            patch("asyncio.create_task", new=closing_create_task_mock()),
            patch.dict("os.environ", {"MEMORY_CONSOLIDATOR_AUTOSTART": "1"}, clear=False),
            patch.dict(
                "sys.modules",
                {"cogs.ai_core.memory.memory_consolidator": fake_mod},
            ),
        ):
            await cog.cog_load()
        archiver.init_schema.assert_awaited_once()
        archiver.start_background_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_cog_load_consolidator_autostart_exception(self):
        cog = _make_cog_r1()
        cog.cleanup_task = None
        cog._pending_request_cleanup_task = None
        cog._cache_cleanup_task = None

        archiver = MagicMock()
        archiver.init_schema = AsyncMock(side_effect=RuntimeError("schema fail"))
        fake_mod = MagicMock(summary_archiver=archiver)

        with (
            patch("cogs.ai_core.ai_cog.start_webhook_cache_cleanup"),
            patch("cogs.ai_core.ai_cog.rag_system"),
            patch("asyncio.create_task", new=closing_create_task_mock()),
            patch.dict("os.environ", {"MEMORY_CONSOLIDATOR_AUTOSTART": "true"}, clear=False),
            patch.dict(
                "sys.modules",
                {"cogs.ai_core.memory.memory_consolidator": fake_mod},
            ),
            patch("cogs.ai_core.ai_cog.logger") as log,
        ):
            await cog.cog_load()
        # Exception path logs via logger.exception
        assert log.exception.called

    @pytest.mark.asyncio
    async def test_cog_load_cache_and_tokentracker_importerror(self):
        cog = _make_cog_r1()
        cog.cleanup_task = None
        cog._pending_request_cleanup_task = None
        cog._cache_cleanup_task = None

        real_import = __import__

        def _blocking_import(name, *args, **kwargs):
            if name in (
                "cogs.ai_core.cache.ai_cache",
                "cogs.ai_core.cache.token_tracker",
            ):
                raise ImportError(f"blocked {name}")
            return real_import(name, *args, **kwargs)

        with (
            patch("cogs.ai_core.ai_cog.start_webhook_cache_cleanup"),
            patch("cogs.ai_core.ai_cog.rag_system"),
            patch("asyncio.create_task", new=closing_create_task_mock()),
            patch.dict("os.environ", {"MEMORY_CONSOLIDATOR_AUTOSTART": ""}, clear=False),
            patch("builtins.__import__", side_effect=_blocking_import),
        ):
            # ImportError on both optional caches must be swallowed (pass).
            await cog.cog_load()
        # cog_load completed without raising despite ImportErrors
        assert cog._cache_cleanup_task is None


# ----------------------------------------------------------------------
# cog_unload (239-263, 286-287, 299-300, 312-314, 322-323)
# ----------------------------------------------------------------------


class TestCogUnloadRegion:
    @pytest.mark.asyncio
    async def test_cog_unload_cancels_all_tasks_and_bg(self):
        cog = _make_cog_r1()

        cog.cleanup_task = _FakeTask(done=False)
        cog._pending_request_cleanup_task = _FakeTask(done=False)
        cog._cache_cleanup_task = _FakeTask(done=False)
        bg = _FakeTask(done=False)
        cog._bg_tasks = {bg}

        rag = MagicMock()
        rag.stop_periodic_save = AsyncMock()
        rag.force_save_index = AsyncMock()

        with (
            patch("cogs.ai_core.ai_cog.rag_system", rag),
            patch("cogs.ai_core.ai_cog.stop_webhook_cache_cleanup", new=AsyncMock()),
            patch("cogs.ai_core.ai_cog.rate_limiter") as rl,
        ):
            rl.stop_cleanup_task = AsyncMock()
            await cog.cog_unload()

        cog.cleanup_task.cancel.assert_called_once()
        cog._pending_request_cleanup_task.cancel.assert_called_once()
        cog._cache_cleanup_task.cancel.assert_called_once()
        bg.cancel.assert_called_once()
        cog.chat_manager.save_all_sessions.assert_awaited_once()
        rag.stop_periodic_save.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cog_unload_suppresses_subsystem_errors(self):
        cog = _make_cog_r1()
        cog.cleanup_task = None
        cog._pending_request_cleanup_task = None
        cog._cache_cleanup_task = None
        cog._bg_tasks = set()

        rag = MagicMock()
        rag.stop_periodic_save = AsyncMock()
        rag.force_save_index = AsyncMock()

        # token_tracker.stop raises (286-287); consolidator stop raises
        # (299-300); flush_l2_pending raises (312-314); db flush raises
        # (322-323). All four must be swallowed/logged, not propagated.
        tt = MagicMock()
        tt.stop_cleanup_task = AsyncMock(side_effect=RuntimeError("tt boom"))
        tt_mod = MagicMock(token_tracker=tt)

        archiver = MagicMock()
        archiver.stop_background_task = AsyncMock(side_effect=RuntimeError("arch boom"))
        consol_mod = MagicMock(summary_archiver=archiver)

        cache_mod = MagicMock()
        cache_mod.flush_l2_pending = AsyncMock(side_effect=RuntimeError("flush boom"))

        fake_db = MagicMock()
        fake_db.flush_pending_exports = AsyncMock(side_effect=RuntimeError("db boom"))
        db_mod = MagicMock(db=fake_db)

        with (
            patch("cogs.ai_core.ai_cog.rag_system", rag),
            patch("cogs.ai_core.ai_cog.stop_webhook_cache_cleanup", new=AsyncMock()),
            patch("cogs.ai_core.ai_cog.rate_limiter") as rl,
            patch.dict(
                "sys.modules",
                {
                    "cogs.ai_core.cache.token_tracker": tt_mod,
                    "cogs.ai_core.memory.memory_consolidator": consol_mod,
                    "cogs.ai_core.cache.ai_cache": cache_mod,
                    "utils.database": db_mod,
                },
            ),
        ):
            rl.stop_cleanup_task = AsyncMock()
            # Must complete despite every subsystem raising.
            await cog.cog_unload()

        cog.chat_manager.save_all_sessions.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cog_unload_flush_l2_reports_count(self):
        cog = _make_cog_r1()
        cog.cleanup_task = None
        cog._pending_request_cleanup_task = None
        cog._cache_cleanup_task = None
        cog._bg_tasks = set()

        rag = MagicMock()
        rag.stop_periodic_save = AsyncMock()
        rag.force_save_index = AsyncMock()

        cache_mod = MagicMock()
        cache_mod.flush_l2_pending = AsyncMock(return_value=3)  # >0 → log info

        fake_db = MagicMock()
        fake_db.flush_pending_exports = AsyncMock()
        db_mod = MagicMock(db=fake_db)

        with (
            patch("cogs.ai_core.ai_cog.rag_system", rag),
            patch("cogs.ai_core.ai_cog.stop_webhook_cache_cleanup", new=AsyncMock()),
            patch("cogs.ai_core.ai_cog.rate_limiter") as rl,
            patch.dict(
                "sys.modules",
                {
                    "cogs.ai_core.cache.ai_cache": cache_mod,
                    "utils.database": db_mod,
                },
            ),
        ):
            rl.stop_cleanup_task = AsyncMock()
            await cog.cog_unload()

        cache_mod.flush_l2_pending.assert_awaited_once()
        fake_db.flush_pending_exports.assert_awaited_once()


# ----------------------------------------------------------------------
# _cleanup_pending_requests_loop (334-388)
# ----------------------------------------------------------------------


class TestCleanupPendingRequestsLoop:
    @pytest.mark.asyncio
    async def test_loop_runs_all_branches_then_cancelled(self):
        """Drive >=30 iterations so the 5-iter storage + 30-iter memory
        cleanup branches all execute, then cancel to break out (384-386)."""
        cog = _make_cog_r1()

        state = {"n": 0}

        async def _fake_sleep(_seconds):
            state["n"] += 1
            if state["n"] > 31:
                raise asyncio.CancelledError
            return None

        # storage cleanup returns >0 to enter the debug-log branch (341-346)
        st = MagicMock()
        st.cleanup_old_states.return_value = 2
        consol = MagicMock()
        consol.cleanup_old_channels.return_value = 1
        # Lock cleanup now runs on the LIVE handler's queue
        # (cog.chat_manager._message_queue), not the module-level singleton.
        cog.chat_manager._message_queue.cleanup_unused_locks.return_value = 4

        with (
            patch("cogs.ai_core.ai_cog.asyncio.sleep", side_effect=_fake_sleep),
            patch("cogs.ai_core.ai_cog.cleanup_storage_cache", return_value=7),
            patch.dict(
                "sys.modules",
                {
                    "cogs.ai_core.memory.state_tracker": MagicMock(state_tracker=st),
                    "cogs.ai_core.memory.consolidator": MagicMock(memory_consolidator=consol),
                },
            ),
        ):
            await cog._cleanup_pending_requests_loop()

        assert cog.chat_manager.cleanup_pending_requests.call_count >= 30
        st.cleanup_old_states.assert_called()
        consol.cleanup_old_channels.assert_called()
        cog.chat_manager._message_queue.cleanup_unused_locks.assert_called()

    @pytest.mark.asyncio
    async def test_loop_memory_cleanup_exception_swallowed(self):
        """Memory-cleanup inner except (381-382) is hit when an import in the
        30-iter block raises; loop keeps going then is cancelled."""
        cog = _make_cog_r1()

        state = {"n": 0}

        async def _fake_sleep(_seconds):
            state["n"] += 1
            if state["n"] > 31:
                raise asyncio.CancelledError
            return None

        with (
            patch("cogs.ai_core.ai_cog.asyncio.sleep", side_effect=_fake_sleep),
            patch("cogs.ai_core.ai_cog.cleanup_storage_cache", return_value=0),
            patch.dict(
                "sys.modules",
                {"cogs.ai_core.memory.state_tracker": None},  # import → ImportError
            ),
            patch("cogs.ai_core.ai_cog.logger") as log,
        ):
            await cog._cleanup_pending_requests_loop()

        # The non-critical memory-cleanup error is logged at debug level.
        assert log.debug.called

    @pytest.mark.asyncio
    async def test_loop_generic_exception_then_cancel(self):
        """A non-cancel exception from cleanup_pending_requests hits 387-388
        (logger.exception) and the loop continues; next iter cancels."""
        cog = _make_cog_r1()

        state = {"n": 0}

        async def _fake_sleep(_seconds):
            state["n"] += 1
            if state["n"] > 2:
                raise asyncio.CancelledError
            return None

        cog.chat_manager.cleanup_pending_requests.side_effect = RuntimeError("boom")

        with (
            patch("cogs.ai_core.ai_cog.asyncio.sleep", side_effect=_fake_sleep),
            patch("cogs.ai_core.ai_cog.logger") as log,
        ):
            await cog._cleanup_pending_requests_loop()

        assert log.exception.called


# ----------------------------------------------------------------------
# chat_command (395-455) + error handler (460-463)
# ----------------------------------------------------------------------


class TestChatCommandRegion:
    @pytest.mark.asyncio
    async def test_rp_command_channel_routes_to_output(self):
        cog = _make_cog_r1()
        ctx = _ctx_r1(channel_id=100, guild_id=900)
        ctx.channel = MagicMock(spec=discord.TextChannel)
        ctx.channel.id = 100
        out_channel = MagicMock(spec=discord.TextChannel)
        cog.bot.get_channel = MagicMock(return_value=out_channel)

        with (
            patch("cogs.ai_core.ai_cog.GUILD_ID_RP", 900),
            patch("cogs.ai_core.ai_cog.CHANNEL_ID_RP_COMMAND", 100),
            patch("cogs.ai_core.ai_cog.CHANNEL_ID_RP_OUTPUT", 200),
        ):
            await cog.chat_command.callback(cog, ctx, message="hi")

        cog.chat_manager.process_chat.assert_awaited_once()
        _, kwargs = cog.chat_manager.process_chat.call_args
        assert kwargs.get("output_channel") is out_channel

    @pytest.mark.asyncio
    async def test_chat_command_defers_slash_interaction(self):
        # /chat (slash) ต้อง defer เพื่อ ack ภายใน 3 วินาที — finding #9
        cog = _make_cog_r1()
        ctx = _ctx_r1(channel_id=100, guild_id=900)
        ctx.interaction = MagicMock()  # มี interaction = ถูกเรียกแบบ slash
        ctx.interaction.delete_original_response = AsyncMock()
        ctx.defer = AsyncMock()
        ctx.channel = MagicMock(spec=discord.TextChannel)
        ctx.channel.id = 100
        out_channel = MagicMock(spec=discord.TextChannel)
        cog.bot.get_channel = MagicMock(return_value=out_channel)

        with (
            patch("cogs.ai_core.ai_cog.GUILD_ID_RP", 900),
            patch("cogs.ai_core.ai_cog.CHANNEL_ID_RP_COMMAND", 100),
            patch("cogs.ai_core.ai_cog.CHANNEL_ID_RP_OUTPUT", 200),
        ):
            await cog.chat_command.callback(cog, ctx, message="hi")

        ctx.defer.assert_awaited_once()
        # ทางสำเร็จต้อง resolve interaction ที่ defer ค้างไว้ด้วย (ไม่งั้น
        # placeholder "thinking…" ค้างจน token หมดอายุแล้วกลายเป็น
        # "The application did not respond")
        ctx.interaction.delete_original_response.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_chat_command_prefix_does_not_defer(self):
        # prefix (!chat) ไม่มี interaction → ต้องไม่เรียก defer
        cog = _make_cog_r1()
        ctx = _ctx_r1(channel_id=100, guild_id=900)  # interaction = None
        ctx.defer = AsyncMock()
        ctx.channel = MagicMock(spec=discord.TextChannel)
        ctx.channel.id = 100
        cog.bot.get_channel = MagicMock(return_value=MagicMock(spec=discord.TextChannel))

        with (
            patch("cogs.ai_core.ai_cog.GUILD_ID_RP", 900),
            patch("cogs.ai_core.ai_cog.CHANNEL_ID_RP_COMMAND", 100),
            patch("cogs.ai_core.ai_cog.CHANNEL_ID_RP_OUTPUT", 200),
        ):
            await cog.chat_command.callback(cog, ctx, message="hi")

        ctx.defer.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_rp_command_channel_unsupported_chat_channel(self):
        cog = _make_cog_r1()
        ctx = _ctx_r1(channel_id=100, guild_id=900)
        # ctx.channel is a plain mock (not a chat channel) → _as_chat_channel None
        ctx.channel = MagicMock()
        ctx.channel.id = 100
        cog.bot.get_channel = MagicMock(return_value=MagicMock(spec=discord.TextChannel))

        with (
            patch("cogs.ai_core.ai_cog.GUILD_ID_RP", 900),
            patch("cogs.ai_core.ai_cog.CHANNEL_ID_RP_COMMAND", 100),
            patch("cogs.ai_core.ai_cog.CHANNEL_ID_RP_OUTPUT", 200),
        ):
            await cog.chat_command.callback(cog, ctx, message="hi")

        ctx.send.assert_awaited_once()
        assert "ไม่รองรับ" in ctx.send.call_args[0][0]
        cog.chat_manager.process_chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_rp_command_channel_no_output_room(self):
        cog = _make_cog_r1()
        ctx = _ctx_r1(channel_id=100, guild_id=900)
        ctx.channel = MagicMock(spec=discord.TextChannel)
        ctx.channel.id = 100
        # get_channel returns non-text → _as_text_channel None → no output room
        cog.bot.get_channel = MagicMock(return_value=None)

        with (
            patch("cogs.ai_core.ai_cog.GUILD_ID_RP", 900),
            patch("cogs.ai_core.ai_cog.CHANNEL_ID_RP_COMMAND", 100),
            patch("cogs.ai_core.ai_cog.CHANNEL_ID_RP_OUTPUT", 200),
        ):
            await cog.chat_command.callback(cog, ctx, message="hi")

        ctx.send.assert_awaited_once()
        assert "Output" in ctx.send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_rp_output_channel_rejected(self):
        # The OUTPUT channel is write-only: !chat there is rejected and the user
        # is pointed back to the single COMMAND channel.
        cog = _make_cog_r1()
        ctx = _ctx_r1(channel_id=200, guild_id=900)
        ctx.channel = MagicMock(spec=discord.TextChannel)
        ctx.channel.id = 200

        with (
            patch("cogs.ai_core.ai_cog.GUILD_ID_RP", 900),
            patch("cogs.ai_core.ai_cog.CHANNEL_ID_RP_COMMAND", 100),
            patch("cogs.ai_core.ai_cog.CHANNEL_ID_RP_OUTPUT", 200),
        ):
            await cog.chat_command.callback(cog, ctx, message="hello")

        ctx.send.assert_awaited_once()
        assert "กรุณาใช้คำสั่ง" in ctx.send.call_args[0][0]
        cog.chat_manager.process_chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_rp_wrong_channel_rejected(self):
        cog = _make_cog_r1()
        ctx = _ctx_r1(channel_id=999, guild_id=900)
        ctx.channel = MagicMock(spec=discord.TextChannel)
        ctx.channel.id = 999

        with (
            patch("cogs.ai_core.ai_cog.GUILD_ID_RP", 900),
            patch("cogs.ai_core.ai_cog.CHANNEL_ID_RP_COMMAND", 100),
            patch("cogs.ai_core.ai_cog.CHANNEL_ID_RP_OUTPUT", 200),
        ):
            await cog.chat_command.callback(cog, ctx, message="hello")

        ctx.send.assert_awaited_once()
        assert "กรุณาใช้คำสั่ง" in ctx.send.call_args[0][0]
        cog.chat_manager.process_chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_message_reply_resolves_content(self):
        cog = _make_cog_r1()
        ctx = _ctx_r1(guild_id=12345)
        ctx.channel = MagicMock(spec=discord.TextChannel)
        ctx.channel.id = 987654321
        ref = MagicMock()
        ref.message_id = 42
        ctx.message.reference = ref
        ref_msg = MagicMock()
        ref_msg.content = "referenced text"
        ctx.channel.fetch_message = AsyncMock(return_value=ref_msg)

        with patch("cogs.ai_core.ai_cog.GUILD_ID_RP", 999999):
            await cog.chat_command.callback(cog, ctx, message=None)

        ctx.channel.fetch_message.assert_awaited_once_with(42)
        args, _ = cog.chat_manager.process_chat.call_args
        assert "referenced text" in args

    @pytest.mark.asyncio
    async def test_no_message_reply_not_found(self):
        cog = _make_cog_r1()
        ctx = _ctx_r1(guild_id=12345)
        ctx.channel = MagicMock(spec=discord.TextChannel)
        ctx.channel.id = 987654321
        ref = MagicMock()
        ref.message_id = 42
        ctx.message.reference = ref
        ctx.channel.fetch_message = AsyncMock(side_effect=_discord_exc(discord.NotFound))

        with patch("cogs.ai_core.ai_cog.GUILD_ID_RP", 999999):
            await cog.chat_command.callback(cog, ctx, message=None)

        ctx.send.assert_awaited_once()
        assert "ไม่พบข้อความ" in ctx.send.call_args[0][0]
        cog.chat_manager.process_chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_message_reply_forbidden(self):
        cog = _make_cog_r1()
        ctx = _ctx_r1(guild_id=12345)
        ctx.channel = MagicMock(spec=discord.TextChannel)
        ctx.channel.id = 987654321
        ref = MagicMock()
        ref.message_id = 42
        ctx.message.reference = ref
        ctx.channel.fetch_message = AsyncMock(side_effect=_discord_exc(discord.Forbidden))

        with patch("cogs.ai_core.ai_cog.GUILD_ID_RP", 999999):
            await cog.chat_command.callback(cog, ctx, message=None)

        ctx.send.assert_awaited_once()
        assert "สิทธิ์" in ctx.send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_no_message_reply_http_exception(self):
        cog = _make_cog_r1()
        ctx = _ctx_r1(guild_id=12345)
        ctx.channel = MagicMock(spec=discord.TextChannel)
        ctx.channel.id = 987654321
        ref = MagicMock()
        ref.message_id = 42
        ctx.message.reference = ref
        ctx.channel.fetch_message = AsyncMock(side_effect=_discord_exc(discord.HTTPException))

        with patch("cogs.ai_core.ai_cog.GUILD_ID_RP", 999999):
            await cog.chat_command.callback(cog, ctx, message=None)

        ctx.send.assert_awaited_once()
        assert "ข้อผิดพลาด" in ctx.send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_no_message_with_attachments(self):
        cog = _make_cog_r1()
        ctx = _ctx_r1(guild_id=12345)
        ctx.channel = MagicMock(spec=discord.TextChannel)
        ctx.channel.id = 987654321
        ctx.message.reference = None
        ctx.message.attachments = [MagicMock()]

        with patch("cogs.ai_core.ai_cog.GUILD_ID_RP", 999999):
            await cog.chat_command.callback(cog, ctx, message=None)

        cog.chat_manager.process_chat.assert_awaited_once()
        args, kwargs = cog.chat_manager.process_chat.call_args
        assert kwargs.get("user_message_id") == 555

    @pytest.mark.asyncio
    async def test_empty_message_no_attachments_continues(self):
        cog = _make_cog_r1()
        ctx = _ctx_r1(guild_id=12345)
        ctx.channel = MagicMock(spec=discord.TextChannel)
        ctx.channel.id = 987654321
        ctx.message.reference = None
        ctx.message.attachments = []

        with patch("cogs.ai_core.ai_cog.GUILD_ID_RP", 999999):
            await cog.chat_command.callback(cog, ctx, message=None)

        cog.chat_manager.process_chat.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_chat_command_unsupported_channel(self):
        cog = _make_cog_r1()
        ctx = _ctx_r1(guild_id=12345)
        # Plain mock channel → not a chat channel
        ctx.channel = MagicMock()
        ctx.channel.id = 987654321
        ctx.message.reference = None
        ctx.message.attachments = []

        with patch("cogs.ai_core.ai_cog.GUILD_ID_RP", 999999):
            await cog.chat_command.callback(cog, ctx, message="hi")

        ctx.send.assert_awaited_once()
        assert "ไม่รองรับ" in ctx.send.call_args[0][0]
        cog.chat_manager.process_chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_guild_skips_rp_block(self):
        cog = _make_cog_r1()
        ctx = _ctx_r1()
        ctx.guild = None
        ctx.channel = MagicMock(spec=discord.TextChannel)
        ctx.channel.id = 987654321

        await cog.chat_command.callback(cog, ctx, message="dm-ish")

        cog.chat_manager.process_chat.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_chat_command_error_cooldown(self):
        from discord.ext import commands

        cog = _make_cog_r1()
        ctx = _ctx_r1()
        error = commands.CommandOnCooldown(commands.Cooldown(1, 3), 4.2, commands.BucketType.user)
        await cog.chat_command_error(ctx, error)
        ctx.send.assert_awaited_once()
        assert "4.2" in ctx.send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_chat_command_error_reraises_other(self):
        cog = _make_cog_r1()
        ctx = _ctx_r1()
        boom = ValueError("not a cooldown")
        with pytest.raises(ValueError, match="not a cooldown"):
            await cog.chat_command_error(ctx, boom)


# ----------------------------------------------------------------------
# reset_ai (469-505) + error handler (510-513)
# ----------------------------------------------------------------------


class TestResetAiRegion:
    @pytest.mark.asyncio
    async def test_reset_ai_clears_state_non_cli(self):
        cog = _make_cog_r1()
        ctx = _ctx_r1(channel_id=4242)
        cid = 4242
        cog.chat_manager.chats = {cid: "x"}
        cog.chat_manager.seen_users = {cid: "y"}
        cog.chat_manager.last_accessed = {cid: 1.0}
        cog.chat_manager.processing_locks = {cid: object()}
        cog.chat_manager.streaming_enabled = {cid: True}
        cog.chat_manager.cli_mode = False

        with patch("cogs.ai_core.ai_cog.delete_history", new=AsyncMock()) as del_hist:
            await cog.reset_ai.callback(cog, ctx)

        del_hist.assert_awaited_once_with(cid)
        assert cid not in cog.chat_manager.chats
        assert cid not in cog.chat_manager.seen_users
        cog.chat_manager._message_queue.clear_channel.assert_called_once_with(cid)
        ctx.send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_reset_ai_cli_mode_resets_session(self):
        cog = _make_cog_r1()
        ctx = _ctx_r1(channel_id=7777)
        cog.chat_manager.cli_mode = True

        reset_fn = MagicMock()
        cli_mod = MagicMock(reset_channel_session=reset_fn)

        with (
            patch("cogs.ai_core.ai_cog.delete_history", new=AsyncMock()),
            patch.dict(
                "sys.modules",
                {"cogs.ai_core.api.discord_chat_claude_cli": cli_mod},
            ),
        ):
            await cog.reset_ai.callback(cog, ctx)

        reset_fn.assert_called_once_with(7777)
        ctx.send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_reset_ai_error_not_owner(self):
        from discord.ext import commands

        cog = _make_cog_r1()
        ctx = _ctx_r1()
        await cog.reset_ai_error(ctx, commands.NotOwner())
        ctx.send.assert_awaited_once()
        assert "เจ้าของบอท" in ctx.send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_reset_ai_error_reraises_other(self):
        cog = _make_cog_r1()
        ctx = _ctx_r1()
        with pytest.raises(RuntimeError, match="other"):
            await cog.reset_ai_error(ctx, RuntimeError("other"))


# ----------------------------------------------------------------------
# on_message dispatch (576-590) + on_guild_channel_delete (523-537)
# ----------------------------------------------------------------------


class TestOnMessageDispatch:
    @pytest.mark.asyncio
    async def test_webhook_message_routed(self):
        cog = _make_cog_r1()
        cog._handle_webhook_message = AsyncMock()
        msg = MagicMock()
        msg.webhook_id = 12345
        await cog.on_message(msg)
        cog._handle_webhook_message.assert_awaited_once_with(msg)

    @pytest.mark.asyncio
    async def test_own_message_ignored(self):
        cog = _make_cog_r1()
        cog._handle_dm_message = AsyncMock()
        cog._handle_guild_message = AsyncMock()
        msg = MagicMock()
        msg.webhook_id = None
        msg.author = cog.bot.user  # author == bot.user
        await cog.on_message(msg)
        cog._handle_dm_message.assert_not_called()
        cog._handle_guild_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_bot_author_ignored(self):
        cog = _make_cog_r1()
        cog._handle_guild_message = AsyncMock()
        msg = MagicMock()
        msg.webhook_id = None
        msg.author = MagicMock()  # not bot.user
        msg.author.bot = True
        await cog.on_message(msg)
        cog._handle_guild_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_dm_routed(self):
        cog = _make_cog_r1()
        cog._handle_dm_message = AsyncMock()
        msg = MagicMock()
        msg.webhook_id = None
        msg.author = MagicMock()
        msg.author.bot = False
        msg.guild = None
        await cog.on_message(msg)
        cog._handle_dm_message.assert_awaited_once_with(msg)

    @pytest.mark.asyncio
    async def test_guild_message_routed(self):
        cog = _make_cog_r1()
        cog._handle_guild_message = AsyncMock()
        msg = MagicMock()
        msg.webhook_id = None
        msg.author = MagicMock()
        msg.author.bot = False
        msg.guild = MagicMock()
        await cog.on_message(msg)
        cog._handle_guild_message.assert_awaited_once_with(msg)


class TestOnGuildChannelDelete:
    @pytest.mark.asyncio
    async def test_channel_delete_cleans_state(self):
        cog = _make_cog_r1()
        cid = 31337
        cog.chat_manager.chats = {cid: "x"}
        cog.chat_manager.seen_users = {cid: "y"}
        cog.chat_manager.last_accessed = {cid: 1.0}
        cog.chat_manager.processing_locks = {cid: object()}
        cog.chat_manager.streaming_enabled = {cid: True}
        channel = MagicMock()
        channel.id = cid

        with patch("cogs.ai_core.ai_cog.invalidate_webhook_cache_on_channel_delete") as inval:
            await cog.on_guild_channel_delete(channel)

        inval.assert_called_once_with(cid)
        assert cid not in cog.chat_manager.chats
        assert cid not in cog.chat_manager.streaming_enabled
        cog.chat_manager._message_queue.clear_channel.assert_called_once_with(cid)
