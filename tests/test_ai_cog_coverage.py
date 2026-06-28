"""Coverage tests for cogs/ai_core/ai_cog.py — region lines 950-1829.

Targets the AICog command callbacks: thinking/streaming toggles, ratelimit
stats, link/move memory, resend, dashboard, audit export, auto-summarize,
channel ratelimit, unrestricted mode, and the module ``setup`` function.

Callbacks are invoked directly via ``cog.<cmd>.callback(cog, ctx, ...)`` to
bypass the discord.py permission/owner decorators (those are exercised by
discord.py itself, not this module). All discord/external deps are mocked —
no network, no real sleeps, no real voice.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

# ============================================================================
# Helpers / fixtures
# ============================================================================


def _make_cog():
    """Create an AI cog with ChatManager and rate_limiter patched out."""
    from cogs.ai_core.ai_cog import AI

    bot = MagicMock()
    with (
        patch("cogs.ai_core.ai_cog.ChatManager") as mock_cm,
        patch("cogs.ai_core.ai_cog.rate_limiter"),
    ):
        cm = MagicMock()
        # default async-capable methods used across commands
        cm.get_chat_session = AsyncMock(return_value=None)
        cm.toggle_thinking = AsyncMock(return_value=True)
        cm.is_streaming_enabled = MagicMock(return_value=False)
        cm.toggle_streaming = MagicMock()
        cm.get_performance_stats = MagicMock(return_value={})
        cm.chats = {}
        cm.processing_locks = {}
        # Pin to False so the CLI-only teardown branches (which import and call
        # the real reset_channel_session) stay off — a bare MagicMock attribute
        # is truthy and would run the unmocked session reset. Tests that want
        # the cli_mode path set it explicitly.
        cm.cli_mode = False
        mock_cm.return_value = cm
        cog = AI(bot)
    return cog


def _make_ctx(channel_id=987654321, guild_id=111222333):
    """Build a mock command Context whose .send is awaitable."""
    ctx = MagicMock()
    ctx.channel.id = channel_id
    ctx.guild.id = guild_id
    ctx.send = AsyncMock()
    return ctx


# ============================================================================
# toggle_thinking_cmd (lines 952-990)
# ============================================================================


class TestToggleThinkingCmd:
    @pytest.mark.asyncio
    async def test_toggle_no_session_enables_default(self):
        cog = _make_cog()
        ctx = _make_ctx()
        cog.chat_manager.get_chat_session = AsyncMock(return_value=None)
        cog.chat_manager.toggle_thinking = AsyncMock(return_value=True)

        await cog.toggle_thinking_cmd.callback(cog, ctx, None)

        # default-enable path: toggle called with True
        cog.chat_manager.toggle_thinking.assert_awaited_once_with(
            ctx.channel.id, True, ctx.guild.id
        )
        ctx.send.assert_awaited()
        assert "embed" in ctx.send.call_args.kwargs

    @pytest.mark.asyncio
    async def test_toggle_existing_session_flips_state(self):
        cog = _make_cog()
        ctx = _make_ctx()
        cog.chat_manager.get_chat_session = AsyncMock(return_value={"thinking_enabled": True})
        cog.chat_manager.toggle_thinking = AsyncMock(return_value=True)

        await cog.toggle_thinking_cmd.callback(cog, ctx, None)

        # current True -> toggle to False
        cog.chat_manager.toggle_thinking.assert_awaited_once_with(
            ctx.channel.id, False, ctx.guild.id
        )

    @pytest.mark.asyncio
    async def test_invalid_mode_sends_error(self):
        cog = _make_cog()
        ctx = _make_ctx()

        await cog.toggle_thinking_cmd.callback(cog, ctx, "bogus")

        ctx.send.assert_awaited_once()
        assert "❌" in ctx.send.call_args.args[0]
        cog.chat_manager.toggle_thinking.assert_not_called()

    @pytest.mark.asyncio
    async def test_mode_on_enables(self):
        cog = _make_cog()
        ctx = _make_ctx()
        cog.chat_manager.toggle_thinking = AsyncMock(return_value=True)

        await cog.toggle_thinking_cmd.callback(cog, ctx, "on")

        cog.chat_manager.toggle_thinking.assert_awaited_once_with(
            ctx.channel.id, True, ctx.guild.id
        )

    @pytest.mark.asyncio
    async def test_mode_off_disables_and_warning_color(self):
        cog = _make_cog()
        ctx = _make_ctx()
        cog.chat_manager.toggle_thinking = AsyncMock(return_value=True)

        await cog.toggle_thinking_cmd.callback(cog, ctx, "OFF")

        cog.chat_manager.toggle_thinking.assert_awaited_once_with(
            ctx.channel.id, False, ctx.guild.id
        )
        ctx.send.assert_awaited()

    @pytest.mark.asyncio
    async def test_toggle_failure_session_not_found(self):
        cog = _make_cog()
        ctx = _make_ctx()
        cog.chat_manager.toggle_thinking = AsyncMock(return_value=False)

        await cog.toggle_thinking_cmd.callback(cog, ctx, "on")

        ctx.send.assert_awaited_once()
        assert "Session not found" in ctx.send.call_args.args[0]

    @pytest.mark.asyncio
    async def test_rp_redirect_uses_output_channel(self):
        cog = _make_cog()
        cog.chat_manager.toggle_thinking = AsyncMock(return_value=True)
        # Patch module RP constants so the redirect branch fires.
        with (
            patch("cogs.ai_core.ai_cog.GUILD_ID_RP", 5000),
            patch("cogs.ai_core.ai_cog.CHANNEL_ID_RP_COMMAND", 6000),
            patch("cogs.ai_core.ai_cog.CHANNEL_ID_RP_OUTPUT", 7000),
        ):
            ctx = _make_ctx(channel_id=6000, guild_id=5000)
            await cog.toggle_thinking_cmd.callback(cog, ctx, "on")

        # toggle should target the OUTPUT channel, not the command channel,
        # and carry the guild so a created session gets the RP persona
        cog.chat_manager.toggle_thinking.assert_awaited_once_with(7000, True, 5000)


# ============================================================================
# toggle_streaming_cmd (lines 992-1032)
# ============================================================================


class TestToggleStreamingCmd:
    @pytest.mark.asyncio
    async def test_toggle_default_flips(self):
        cog = _make_cog()
        ctx = _make_ctx()
        cog.chat_manager.is_streaming_enabled = MagicMock(return_value=False)

        await cog.toggle_streaming_cmd.callback(cog, ctx, None)

        cog.chat_manager.toggle_streaming.assert_called_once_with(ctx.channel.id, True)
        # Enabled -> adds the note field, sends embed
        ctx.send.assert_awaited()
        assert "embed" in ctx.send.call_args.kwargs

    @pytest.mark.asyncio
    async def test_invalid_mode(self):
        cog = _make_cog()
        ctx = _make_ctx()

        await cog.toggle_streaming_cmd.callback(cog, ctx, "weird")

        ctx.send.assert_awaited_once()
        assert "❌" in ctx.send.call_args.args[0]
        cog.chat_manager.toggle_streaming.assert_not_called()

    @pytest.mark.asyncio
    async def test_mode_off_disables_no_note(self):
        cog = _make_cog()
        ctx = _make_ctx()

        await cog.toggle_streaming_cmd.callback(cog, ctx, "off")

        cog.chat_manager.toggle_streaming.assert_called_once_with(ctx.channel.id, False)
        ctx.send.assert_awaited()

    @pytest.mark.asyncio
    async def test_mode_enable(self):
        cog = _make_cog()
        ctx = _make_ctx()

        await cog.toggle_streaming_cmd.callback(cog, ctx, "enable")

        cog.chat_manager.toggle_streaming.assert_called_once_with(ctx.channel.id, True)

    @pytest.mark.asyncio
    async def test_rp_redirect(self):
        cog = _make_cog()
        with (
            patch("cogs.ai_core.ai_cog.GUILD_ID_RP", 5000),
            patch("cogs.ai_core.ai_cog.CHANNEL_ID_RP_COMMAND", 6000),
            patch("cogs.ai_core.ai_cog.CHANNEL_ID_RP_OUTPUT", 7000),
        ):
            ctx = _make_ctx(channel_id=6000, guild_id=5000)
            await cog.toggle_streaming_cmd.callback(cog, ctx, "on")
        cog.chat_manager.toggle_streaming.assert_called_once_with(7000, True)


# ============================================================================
# ratelimit_stats_cmd (lines 1034-1056)
# ============================================================================


class TestRatelimitStatsCmd:
    @pytest.mark.asyncio
    async def test_no_stats(self):
        cog = _make_cog()
        ctx = _make_ctx()
        with patch("cogs.ai_core.ai_cog.rate_limiter") as rl:
            rl.get_stats.return_value = {}
            await cog.ratelimit_stats_cmd.callback(cog, ctx)

        ctx.send.assert_awaited_once()
        assert "No rate limit data" in ctx.send.call_args.args[0]

    @pytest.mark.asyncio
    async def test_with_stats_builds_embed(self):
        cog = _make_cog()
        ctx = _make_ctx()
        with patch("cogs.ai_core.ai_cog.rate_limiter") as rl:
            rl.get_stats.return_value = {
                "bucketA": {"allowed": 8, "blocked": 2},
                "bucketEmpty": {"allowed": 0, "blocked": 0},
            }
            await cog.ratelimit_stats_cmd.callback(cog, ctx)

        ctx.send.assert_awaited_once()
        embed = ctx.send.call_args.kwargs["embed"]
        # Only the non-zero bucket produces a field
        assert len(embed.fields) == 1
        assert embed.fields[0].name == "bucketA"


# ============================================================================
# link_memory_cmd (lines 1058-1177)
# ============================================================================


class TestLinkMemoryCmd:
    @pytest.mark.asyncio
    async def test_list_empty(self):
        cog = _make_cog()
        ctx = _make_ctx()
        with patch("cogs.ai_core.ai_cog.get_all_channel_ids", AsyncMock(return_value=[])):
            await cog.link_memory_cmd.callback(cog, ctx, "list")
        ctx.send.assert_awaited_once()
        assert "ไม่พบประวัติแชท" in ctx.send.call_args.args[0]

    @pytest.mark.asyncio
    async def test_list_with_known_and_unknown(self):
        cog = _make_cog()
        ctx = _make_ctx()
        cog.bot.get_channel = MagicMock(side_effect=lambda cid: MagicMock() if cid == 111 else None)
        with patch("cogs.ai_core.ai_cog.get_all_channel_ids", AsyncMock(return_value=[111, 222])):
            await cog.link_memory_cmd.callback(cog, ctx, "list")
        ctx.send.assert_awaited_once()
        embed = ctx.send.call_args.kwargs["embed"]
        assert "111" in embed.description
        assert "Unknown Channel" in embed.description

    @pytest.mark.asyncio
    async def test_missing_source(self):
        cog = _make_cog()
        ctx = _make_ctx()
        await cog.link_memory_cmd.callback(cog, ctx, None)
        ctx.send.assert_awaited_once()
        assert "กรุณาระบุ Channel ID" in ctx.send.call_args.args[0]

    @pytest.mark.asyncio
    async def test_user_mention_rejected(self):
        cog = _make_cog()
        ctx = _make_ctx()
        await cog.link_memory_cmd.callback(cog, ctx, "<@12345>")
        ctx.send.assert_awaited_once()
        assert "channel mention" in ctx.send.call_args.args[0]

    @pytest.mark.asyncio
    async def test_non_numeric_source(self):
        cog = _make_cog()
        ctx = _make_ctx()
        await cog.link_memory_cmd.callback(cog, ctx, "abc")
        ctx.send.assert_awaited_once()
        assert "ตัวเลข ID" in ctx.send.call_args.args[0]

    @pytest.mark.asyncio
    async def test_non_positive_snowflake(self):
        cog = _make_cog()
        ctx = _make_ctx()
        await cog.link_memory_cmd.callback(cog, ctx, "0")
        ctx.send.assert_awaited_once()
        assert "ตัวเลข ID" in ctx.send.call_args.args[0]

    @pytest.mark.asyncio
    async def test_same_channel(self):
        cog = _make_cog()
        ctx = _make_ctx(channel_id=555)
        await cog.link_memory_cmd.callback(cog, ctx, "555")
        ctx.send.assert_awaited_once()
        assert "channel เดียวกัน" in ctx.send.call_args.args[0]

    @pytest.mark.asyncio
    async def test_confirm_timeout(self):
        cog = _make_cog()
        ctx = _make_ctx(channel_id=555)
        cog.bot.wait_for = AsyncMock(side_effect=TimeoutError())
        await cog.link_memory_cmd.callback(cog, ctx, "999")
        # confirmation embed + timeout message
        assert ctx.send.await_count == 2
        assert "หมดเวลา" in ctx.send.call_args.args[0]

    @pytest.mark.asyncio
    async def test_confirm_no(self):
        cog = _make_cog()
        ctx = _make_ctx(channel_id=555)
        confirm = MagicMock()
        confirm.content = "no"
        cog.bot.wait_for = AsyncMock(return_value=confirm)
        await cog.link_memory_cmd.callback(cog, ctx, "999")
        assert "ยกเลิก" in ctx.send.call_args.args[0]

    @pytest.mark.asyncio
    async def test_confirm_yes_copies_success(self):
        cog = _make_cog()
        ctx = _make_ctx(channel_id=555)
        confirm = MagicMock()
        confirm.content = "yes"
        cog.bot.wait_for = AsyncMock(return_value=confirm)
        status_msg = MagicMock()
        status_msg.edit = AsyncMock()
        ctx.send = AsyncMock(return_value=status_msg)
        cog.chat_manager.chats = {555: {"x": 1}}
        with patch("cogs.ai_core.ai_cog.copy_history", AsyncMock(return_value=4)):
            await cog.link_memory_cmd.callback(cog, ctx, "999")
        status_msg.edit.assert_awaited()
        embed = status_msg.edit.call_args.kwargs["embed"]
        assert "4" in embed.description
        assert 555 not in cog.chat_manager.chats  # session reloaded (popped)

    @pytest.mark.asyncio
    async def test_confirm_yes_no_history(self):
        cog = _make_cog()
        ctx = _make_ctx(channel_id=555)
        confirm = MagicMock()
        confirm.content = "y"
        cog.bot.wait_for = AsyncMock(return_value=confirm)
        status_msg = MagicMock()
        status_msg.edit = AsyncMock()
        ctx.send = AsyncMock(return_value=status_msg)
        with patch("cogs.ai_core.ai_cog.copy_history", AsyncMock(return_value=0)):
            await cog.link_memory_cmd.callback(cog, ctx, "999")
        status_msg.edit.assert_awaited_once_with(content="❌ ไม่พบประวัติแชทใน channel ต้นทาง")

    @pytest.mark.asyncio
    async def test_confirm_yes_copy_raises(self):
        cog = _make_cog()
        ctx = _make_ctx(channel_id=555)
        confirm = MagicMock()
        confirm.content = "yes"
        cog.bot.wait_for = AsyncMock(return_value=confirm)
        status_msg = MagicMock()
        status_msg.edit = AsyncMock()
        ctx.send = AsyncMock(return_value=status_msg)
        with patch("cogs.ai_core.ai_cog.copy_history", AsyncMock(side_effect=RuntimeError("boom"))):
            await cog.link_memory_cmd.callback(cog, ctx, "999")
        status_msg.edit.assert_awaited_once_with(content="❌ เกิดข้อผิดพลาดในการเชื่อมต่อ memory")

    @pytest.mark.asyncio
    async def test_check_predicate(self):
        """Exercise the inner ``check`` closure for wait_for."""
        cog = _make_cog()
        ctx = _make_ctx(channel_id=555)
        captured = {}

        async def fake_wait_for(_event, check=None, timeout=None):
            captured["check"] = check
            raise TimeoutError()

        cog.bot.wait_for = fake_wait_for
        ctx.author.id = 4242  # confirmation must come from the invoker
        await cog.link_memory_cmd.callback(cog, ctx, "999")
        check = captured["check"]
        good = MagicMock()
        good.author.id = ctx.author.id
        good.channel.id = 555
        good.content = "YES"
        assert check(good) is True
        bad = MagicMock()
        bad.author.id = 999999
        bad.channel.id = 555
        bad.content = "yes"
        assert check(bad) is False


# ============================================================================
# resend_last_message (lines 1179-1300)
# ============================================================================


class TestResendLastMessage:
    @pytest.mark.asyncio
    async def test_no_history(self):
        cog = _make_cog()
        ctx = _make_ctx()
        cog.chat_manager.get_chat_session = AsyncMock(return_value=None)
        await cog.resend_last_message.callback(cog, ctx, None)
        ctx.send.assert_awaited_once()
        assert "ไม่พบประวัติแชท" in ctx.send.call_args.args[0]

    @pytest.mark.asyncio
    async def test_local_id_not_found(self):
        cog = _make_cog()
        ctx = _make_ctx()
        cog.chat_manager.get_chat_session = AsyncMock(return_value={"history": [1]})
        with patch("cogs.ai_core.ai_cog.get_message_by_local_id", AsyncMock(return_value=None)):
            await cog.resend_last_message.callback(cog, ctx, 189)
        assert "local_id=189" in ctx.send.call_args.args[0]

    @pytest.mark.asyncio
    async def test_last_model_message_not_found(self):
        cog = _make_cog()
        ctx = _make_ctx()
        cog.chat_manager.get_chat_session = AsyncMock(return_value={"history": [1]})
        with patch("cogs.ai_core.ai_cog.get_last_model_message", AsyncMock(return_value=None)):
            await cog.resend_last_message.callback(cog, ctx, None)
        assert "ไม่พบข้อความ AI" in ctx.send.call_args.args[0]

    @pytest.mark.asyncio
    async def test_empty_content(self):
        cog = _make_cog()
        ctx = _make_ctx()
        cog.chat_manager.get_chat_session = AsyncMock(return_value={"history": [1]})
        with patch(
            "cogs.ai_core.ai_cog.get_last_model_message",
            AsyncMock(return_value={"parts": ["   "]}),
        ):
            await cog.resend_last_message.callback(cog, ctx, None)
        assert "ข้อความว่างเปล่า" in ctx.send.call_args.args[0]

    @pytest.mark.asyncio
    async def test_output_channel_missing(self):
        cog = _make_cog()
        ctx = _make_ctx()
        cog.chat_manager.get_chat_session = AsyncMock(return_value={"history": [1]})
        status_msg = MagicMock()
        status_msg.edit = AsyncMock()
        ctx.send = AsyncMock(return_value=status_msg)
        cog.bot.get_channel = MagicMock(return_value=None)
        with patch(
            "cogs.ai_core.ai_cog.get_last_model_message",
            AsyncMock(return_value={"parts": ["hello world"]}),
        ):
            await cog.resend_last_message.callback(cog, ctx, None)
        status_msg.edit.assert_awaited_once_with(content="❌ ไม่พบช่อง output")

    @pytest.mark.asyncio
    async def test_output_channel_unsupported_type(self):
        cog = _make_cog()
        ctx = _make_ctx()
        cog.chat_manager.get_chat_session = AsyncMock(return_value={"history": [1]})
        status_msg = MagicMock()
        status_msg.edit = AsyncMock()
        ctx.send = AsyncMock(return_value=status_msg)
        # A plain MagicMock isn't a TextChannel/Thread/DMChannel
        cog.bot.get_channel = MagicMock(return_value=MagicMock())
        with patch(
            "cogs.ai_core.ai_cog.get_last_model_message",
            AsyncMock(return_value={"parts": ["hello world"]}),
        ):
            await cog.resend_last_message.callback(cog, ctx, None)
        edit_content = status_msg.edit.call_args.kwargs["content"]
        assert "ไม่รองรับการส่งข้อความ" in edit_content

    @pytest.mark.asyncio
    async def test_normal_message_chunked(self):
        cog = _make_cog()
        ctx = _make_ctx()
        cog.chat_manager.get_chat_session = AsyncMock(return_value={"history": [1]})
        status_msg = MagicMock()
        status_msg.edit = AsyncMock()
        ctx.send = AsyncMock(return_value=status_msg)
        out = MagicMock(spec=discord.TextChannel)
        out.send = AsyncMock()
        cog.bot.get_channel = MagicMock(return_value=out)
        # content > 2000 to exercise chunk loop; mix str + dict parts
        long_text = "x" * 2500
        with patch(
            "cogs.ai_core.ai_cog.get_last_model_message",
            AsyncMock(return_value={"parts": ["start ", {"text": long_text}]}),
        ):
            await cog.resend_last_message.callback(cog, ctx, None)
        assert out.send.await_count == 2  # 2500+ chars -> 2 chunks
        status_msg.edit.assert_awaited_with(content="✅ ส่งข้อความใหม่สำเร็จ!")

    @pytest.mark.asyncio
    async def test_resend_suppresses_mentions(self):
        """Regression: !resend of stored model text containing @everyone must
        send with AllowedMentions.none() so it can't ping — the raw stored
        content is saved BEFORE logic.py's mention escaping and returned
        verbatim, so the send is the only mention guard on this path."""
        cog = _make_cog()
        ctx = _make_ctx()
        cog.chat_manager.get_chat_session = AsyncMock(return_value={"history": [1]})
        status_msg = MagicMock()
        status_msg.edit = AsyncMock()
        ctx.send = AsyncMock(return_value=status_msg)
        out = MagicMock(spec=discord.TextChannel)
        out.send = AsyncMock()
        cog.bot.get_channel = MagicMock(return_value=out)
        with patch(
            "cogs.ai_core.ai_cog.get_last_model_message",
            AsyncMock(return_value={"parts": ["@everyone hello <@123>"]}),
        ):
            await cog.resend_last_message.callback(cog, ctx, None)
        out.send.assert_awaited_once()
        am = out.send.await_args.kwargs.get("allowed_mentions")
        assert isinstance(am, discord.AllowedMentions)
        # none() disables every mention category — no ping can escape.
        assert am.everyone is False
        assert am.roles is False
        assert am.users is False

    @pytest.mark.asyncio
    async def test_character_tags_webhook(self):
        cog = _make_cog()
        ctx = _make_ctx()
        cog.chat_manager.get_chat_session = AsyncMock(return_value={"history": [1]})
        status_msg = MagicMock()
        status_msg.edit = AsyncMock()
        ctx.send = AsyncMock(return_value=status_msg)
        out = MagicMock(spec=discord.TextChannel)
        out.send = AsyncMock()
        cog.bot.get_channel = MagicMock(return_value=out)
        content = "narration {{Alice}} hi there {{}} {{Bob}} hello"
        with (
            patch(
                "cogs.ai_core.ai_cog.get_last_model_message",
                AsyncMock(return_value={"parts": [content]}),
            ),
            patch("cogs.ai_core.ai_cog.send_as_webhook", AsyncMock()) as webhook,
            patch("cogs.ai_core.ai_cog.asyncio.sleep", AsyncMock()),
        ):
            await cog.resend_last_message.callback(cog, ctx, None)
        # Alice + Bob produce webhook sends; empty {{}} name skipped
        assert webhook.await_count == 2
        # intro narration sent via output_channel.send
        out.send.assert_awaited()

    @pytest.mark.asyncio
    async def test_character_tags_truncated_to_60(self):
        cog = _make_cog()
        ctx = _make_ctx()
        cog.chat_manager.get_chat_session = AsyncMock(return_value={"history": [1]})
        status_msg = MagicMock()
        status_msg.edit = AsyncMock()
        ctx.send = AsyncMock(return_value=status_msg)
        out = MagicMock(spec=discord.TextChannel)
        out.send = AsyncMock()
        cog.bot.get_channel = MagicMock(return_value=out)
        # 40 {{Name}} blocks => 80+ split parts, exceeding the 60 cap
        content = "".join(f"{{{{C{i}}}}} msg{i} " for i in range(40))
        with (
            patch(
                "cogs.ai_core.ai_cog.get_last_model_message",
                AsyncMock(return_value={"parts": [content]}),
            ),
            patch("cogs.ai_core.ai_cog.send_as_webhook", AsyncMock()),
            patch("cogs.ai_core.ai_cog.asyncio.sleep", AsyncMock()),
        ):
            await cog.resend_last_message.callback(cog, ctx, None)
        status_msg.edit.assert_awaited_with(content="✅ ส่งข้อความใหม่สำเร็จ!")

    @pytest.mark.asyncio
    async def test_send_raises_exception(self):
        cog = _make_cog()
        ctx = _make_ctx()
        cog.chat_manager.get_chat_session = AsyncMock(return_value={"history": [1]})
        status_msg = MagicMock()
        status_msg.edit = AsyncMock()
        ctx.send = AsyncMock(return_value=status_msg)
        out = MagicMock(spec=discord.TextChannel)
        out.send = AsyncMock(side_effect=RuntimeError("send fail"))
        cog.bot.get_channel = MagicMock(return_value=out)
        with patch(
            "cogs.ai_core.ai_cog.get_last_model_message",
            AsyncMock(return_value={"parts": ["plain text"]}),
        ):
            await cog.resend_last_message.callback(cog, ctx, None)
        status_msg.edit.assert_awaited_with(content="❌ เกิดข้อผิดพลาดในการส่งข้อความใหม่")

    @pytest.mark.asyncio
    async def test_local_id_found_resends(self):
        cog = _make_cog()
        ctx = _make_ctx()
        cog.chat_manager.get_chat_session = AsyncMock(return_value={"history": [1]})
        status_msg = MagicMock()
        status_msg.edit = AsyncMock()
        ctx.send = AsyncMock(return_value=status_msg)
        out = MagicMock(spec=discord.TextChannel)
        out.send = AsyncMock()
        cog.bot.get_channel = MagicMock(return_value=out)
        with patch(
            "cogs.ai_core.ai_cog.get_message_by_local_id",
            AsyncMock(return_value={"parts": ["from local id"]}),
        ):
            await cog.resend_last_message.callback(cog, ctx, 42)
        out.send.assert_awaited()
        status_msg.edit.assert_awaited_with(content="✅ ส่งข้อความใหม่สำเร็จ!")

    @pytest.mark.asyncio
    async def test_rp_redirect(self):
        cog = _make_cog()
        cog.chat_manager.get_chat_session = AsyncMock(return_value=None)
        with (
            patch("cogs.ai_core.ai_cog.GUILD_ID_RP", 5000),
            patch("cogs.ai_core.ai_cog.CHANNEL_ID_RP_COMMAND", 6000),
            patch("cogs.ai_core.ai_cog.CHANNEL_ID_RP_OUTPUT", 7000),
        ):
            ctx = _make_ctx(channel_id=6000, guild_id=5000)
            await cog.resend_last_message.callback(cog, ctx, None)
        cog.chat_manager.get_chat_session.assert_awaited_once_with(7000, 5000)


# ============================================================================
# move_memory_cmd (lines 1302-1428)
# ============================================================================


class TestMoveMemoryCmd:
    @pytest.mark.asyncio
    async def test_list_empty(self):
        cog = _make_cog()
        ctx = _make_ctx()
        with patch("cogs.ai_core.ai_cog.get_all_channel_ids", AsyncMock(return_value=[])):
            await cog.move_memory_cmd.callback(cog, ctx, "list")
        assert "ไม่พบประวัติแชท" in ctx.send.call_args.args[0]

    @pytest.mark.asyncio
    async def test_list_with_channels(self):
        cog = _make_cog()
        ctx = _make_ctx()
        cog.bot.get_channel = MagicMock(side_effect=lambda cid: MagicMock() if cid == 1 else None)
        with patch("cogs.ai_core.ai_cog.get_all_channel_ids", AsyncMock(return_value=[1, 2])):
            await cog.move_memory_cmd.callback(cog, ctx, "list")
        embed = ctx.send.call_args.kwargs["embed"]
        assert "Unknown Channel" in embed.description

    @pytest.mark.asyncio
    async def test_missing_source(self):
        cog = _make_cog()
        ctx = _make_ctx()
        await cog.move_memory_cmd.callback(cog, ctx, None)
        assert "กรุณาระบุ Channel ID" in ctx.send.call_args.args[0]

    @pytest.mark.asyncio
    async def test_user_mention_rejected(self):
        cog = _make_cog()
        ctx = _make_ctx()
        await cog.move_memory_cmd.callback(cog, ctx, "<@&55>")
        assert "channel mention" in ctx.send.call_args.args[0]

    @pytest.mark.asyncio
    async def test_non_numeric(self):
        cog = _make_cog()
        ctx = _make_ctx()
        await cog.move_memory_cmd.callback(cog, ctx, "xyz")
        assert "ตัวเลข ID" in ctx.send.call_args.args[0]

    @pytest.mark.asyncio
    async def test_negative_id(self):
        cog = _make_cog()
        ctx = _make_ctx()
        await cog.move_memory_cmd.callback(cog, ctx, "-5")
        assert "ตัวเลข ID" in ctx.send.call_args.args[0]

    @pytest.mark.asyncio
    async def test_same_channel(self):
        cog = _make_cog()
        ctx = _make_ctx(channel_id=777)
        await cog.move_memory_cmd.callback(cog, ctx, "777")
        assert "channel เดียวกัน" in ctx.send.call_args.args[0]

    @pytest.mark.asyncio
    async def test_timeout(self):
        cog = _make_cog()
        ctx = _make_ctx(channel_id=777)
        cog.bot.wait_for = AsyncMock(side_effect=TimeoutError())
        await cog.move_memory_cmd.callback(cog, ctx, "888")
        assert "หมดเวลา" in ctx.send.call_args.args[0]

    @pytest.mark.asyncio
    async def test_confirm_no(self):
        cog = _make_cog()
        ctx = _make_ctx(channel_id=777)
        confirm = MagicMock()
        confirm.content = "n"
        cog.bot.wait_for = AsyncMock(return_value=confirm)
        await cog.move_memory_cmd.callback(cog, ctx, "888")
        assert "ยกเลิก" in ctx.send.call_args.args[0]

    @pytest.mark.asyncio
    async def test_move_success(self):
        cog = _make_cog()
        ctx = _make_ctx(channel_id=777)
        confirm = MagicMock()
        confirm.content = "yes"
        cog.bot.wait_for = AsyncMock(return_value=confirm)
        status_msg = MagicMock()
        status_msg.edit = AsyncMock()
        ctx.send = AsyncMock(return_value=status_msg)
        cog.chat_manager.chats = {777: {}, 888: {}}
        with patch("cogs.ai_core.ai_cog.move_history", AsyncMock(return_value=9)):
            await cog.move_memory_cmd.callback(cog, ctx, "888")
        embed = status_msg.edit.call_args.kwargs["embed"]
        assert "9" in embed.description
        assert 777 not in cog.chat_manager.chats
        assert 888 not in cog.chat_manager.chats

    @pytest.mark.asyncio
    async def test_move_no_history(self):
        cog = _make_cog()
        ctx = _make_ctx(channel_id=777)
        confirm = MagicMock()
        confirm.content = "yes"
        cog.bot.wait_for = AsyncMock(return_value=confirm)
        status_msg = MagicMock()
        status_msg.edit = AsyncMock()
        ctx.send = AsyncMock(return_value=status_msg)
        with patch("cogs.ai_core.ai_cog.move_history", AsyncMock(return_value=0)):
            await cog.move_memory_cmd.callback(cog, ctx, "888")
        status_msg.edit.assert_awaited_once_with(content="❌ ไม่พบประวัติแชทใน channel ต้นทาง")

    @pytest.mark.asyncio
    async def test_move_raises(self):
        cog = _make_cog()
        ctx = _make_ctx(channel_id=777)
        confirm = MagicMock()
        confirm.content = "yes"
        cog.bot.wait_for = AsyncMock(return_value=confirm)
        status_msg = MagicMock()
        status_msg.edit = AsyncMock()
        ctx.send = AsyncMock(return_value=status_msg)
        with patch("cogs.ai_core.ai_cog.move_history", AsyncMock(side_effect=RuntimeError("x"))):
            await cog.move_memory_cmd.callback(cog, ctx, "888")
        status_msg.edit.assert_awaited_once_with(content="❌ เกิดข้อผิดพลาดในการย้าย memory")

    @pytest.mark.asyncio
    async def test_check_predicate(self):
        cog = _make_cog()
        ctx = _make_ctx(channel_id=777)
        captured = {}

        async def fake_wait_for(_event, check=None, timeout=None):
            captured["check"] = check
            raise TimeoutError()

        cog.bot.wait_for = fake_wait_for
        ctx.author.id = 4242  # confirmation must come from the invoker
        await cog.move_memory_cmd.callback(cog, ctx, "888")
        check = captured["check"]
        m = MagicMock()
        m.author.id = ctx.author.id
        m.channel.id = 777
        m.content = "no"
        assert check(m) is True
        m.content = "maybe"
        assert check(m) is False


# ============================================================================
# reload_config_cmd (lines 1432-1462)
# ============================================================================


class TestReloadConfigCmd:
    @pytest.mark.asyncio
    async def test_reload_success(self):
        cog = _make_cog()
        ctx = _make_ctx()
        with patch("utils.reliability.rate_limiter.rate_limiter") as rl:
            rl.reload_limits = MagicMock()
            await cog.reload_config_cmd.callback(cog, ctx)
            rl.reload_limits.assert_called_once()
        assert "reloaded" in ctx.send.call_args.args[0]

    @pytest.mark.asyncio
    async def test_reload_failure(self):
        cog = _make_cog()
        ctx = _make_ctx()
        with patch("utils.reliability.rate_limiter.rate_limiter") as rl:
            rl.reload_limits = MagicMock(side_effect=RuntimeError("nope"))
            await cog.reload_config_cmd.callback(cog, ctx)
        assert "Failed to reload" in ctx.send.call_args.args[0]


# ============================================================================
# dashboard_cmd (lines 1464-1567)
# ============================================================================


class TestDashboardCmd:
    @pytest.mark.asyncio
    async def test_dashboard_full(self):
        cog = _make_cog()
        ctx = _make_ctx()
        cog.chat_manager.chats = {1: {"history": [1, 2]}, 2: {"history": [3]}}
        cog.chat_manager.get_performance_stats = MagicMock(
            return_value={"api_call": {"count": 2, "avg_ms": 12.0}}
        )

        cache_stats = MagicMock()
        cache_stats.total_entries = 5
        cache_stats.hit_rate = 0.5
        cache_stats.memory_estimate_kb = 100.0
        with (
            patch("cogs.ai_core.cache.ai_cache.ai_cache") as ai_cache,
            patch("cogs.ai_core.memory.rag.rag_system") as rag,
            patch("utils.reliability.rate_limiter.rate_limiter") as rl,
            patch("utils.reliability.circuit_breaker.gemini_circuit") as cb,
        ):
            ai_cache.get_stats.return_value = cache_stats
            rag.get_stats.return_value = {
                "faiss_available": True,
                "index_size": 10,
                "memories_cached": 3,
            }
            rl.get_stats.return_value = {"active_buckets": 1, "total_blocked": 0}
            cb.state.value = "closed"
            await cog.dashboard_cmd.callback(cog, ctx)

        embed = ctx.send.call_args.kwargs["embed"]
        names = [f.name for f in embed.fields]
        assert "🧠 AI Sessions" in names
        assert "⚡ Performance" in names

    @pytest.mark.asyncio
    async def test_dashboard_half_open_circuit(self):
        cog = _make_cog()
        ctx = _make_ctx()
        cog.chat_manager.chats = {}
        cog.chat_manager.get_performance_stats = MagicMock(return_value={})
        cache_stats = MagicMock()
        cache_stats.total_entries = 0
        cache_stats.hit_rate = 0.0
        cache_stats.memory_estimate_kb = 0.0
        with (
            patch("cogs.ai_core.cache.ai_cache.ai_cache") as ai_cache,
            patch("cogs.ai_core.memory.rag.rag_system") as rag,
            patch("utils.reliability.rate_limiter.rate_limiter") as rl,
            patch("utils.reliability.circuit_breaker.gemini_circuit") as cb,
        ):
            ai_cache.get_stats.return_value = cache_stats
            rag.get_stats.return_value = {
                "faiss_available": False,
                "index_size": 0,
                "memories_cached": 0,
            }
            rl.get_stats.return_value = {}
            cb.state.value = "half_open"
            await cog.dashboard_cmd.callback(cog, ctx)
        ctx.send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_dashboard_long_perf_truncated(self):
        cog = _make_cog()
        ctx = _make_ctx()
        cog.chat_manager.chats = {}
        long_key = "k" * 2000
        cog.chat_manager.get_performance_stats = MagicMock(
            return_value={long_key: {"count": 1, "avg_ms": 1.0}}
        )
        cache_stats = MagicMock()
        cache_stats.total_entries = 0
        cache_stats.hit_rate = 0.0
        cache_stats.memory_estimate_kb = 0.0
        with (
            patch("cogs.ai_core.cache.ai_cache.ai_cache") as ai_cache,
            patch("cogs.ai_core.memory.rag.rag_system") as rag,
            patch("utils.reliability.rate_limiter.rate_limiter") as rl,
            patch("utils.reliability.circuit_breaker.gemini_circuit") as cb,
        ):
            ai_cache.get_stats.return_value = cache_stats
            rag.get_stats.return_value = {
                "faiss_available": True,
                "index_size": 0,
                "memories_cached": 0,
            }
            rl.get_stats.return_value = {}
            cb.state.value = "open"
            await cog.dashboard_cmd.callback(cog, ctx)
        embed = ctx.send.call_args.kwargs["embed"]
        perf_field = next(f for f in embed.fields if f.name == "⚡ Performance")
        assert perf_field.value.endswith("...")


# ============================================================================
# audit_export_cmd (lines 1569-1613)
# ============================================================================


class TestAuditExportCmd:
    @pytest.mark.asyncio
    async def test_db_unavailable(self):
        cog = _make_cog()
        ctx = _make_ctx()
        with patch("utils.database.db", None):
            await cog.audit_export_cmd.callback(cog, ctx, 7)
        assert "Database not available" in ctx.send.call_args.args[0]

    @pytest.mark.asyncio
    async def test_no_logs(self):
        cog = _make_cog()
        ctx = _make_ctx()
        shared_db = MagicMock()
        shared_db.get_audit_logs = AsyncMock(return_value=[])
        with patch("utils.database.db", shared_db):
            await cog.audit_export_cmd.callback(cog, ctx, 7)
        assert "No audit logs" in ctx.send.call_args.args[0]

    @pytest.mark.asyncio
    async def test_export_success_and_days_clamped(self):
        cog = _make_cog()
        ctx = _make_ctx()
        shared_db = MagicMock()
        shared_db.get_audit_logs = AsyncMock(return_value=[{"a": 1}, {"b": 2}])
        with patch("utils.database.db", shared_db):
            # days way out of range -> clamped to 365
            await cog.audit_export_cmd.callback(cog, ctx, 999999)
        shared_db.get_audit_logs.assert_awaited_once_with(days=365)
        assert "Exported 2 audit entries" in ctx.send.call_args.args[0]
        assert "file" in ctx.send.call_args.kwargs

    @pytest.mark.asyncio
    async def test_export_exception(self):
        cog = _make_cog()
        ctx = _make_ctx()
        shared_db = MagicMock()
        shared_db.get_audit_logs = AsyncMock(side_effect=RuntimeError("db fail"))
        with patch("utils.database.db", shared_db):
            await cog.audit_export_cmd.callback(cog, ctx, 7)
        assert "Failed to export" in ctx.send.call_args.args[0]


# ============================================================================
# auto_summarize_cmd (lines 1615-1682)
# ============================================================================


class TestAutoSummarizeCmd:
    @pytest.mark.asyncio
    async def test_no_session(self):
        cog = _make_cog()
        ctx = _make_ctx()
        cog.chat_manager.chats = {}
        await cog.auto_summarize_cmd.callback(cog, ctx, 500000)
        assert "No active session" in ctx.send.call_args.args[0]

    @pytest.mark.asyncio
    async def test_no_history(self):
        cog = _make_cog()
        ctx = _make_ctx()
        cog.chat_manager.chats = {ctx.channel.id: {"history": []}}
        await cog.auto_summarize_cmd.callback(cog, ctx, 500000)
        assert "No history to summarize" in ctx.send.call_args.args[0]

    @pytest.mark.asyncio
    async def test_summarize_success(self):
        cog = _make_cog()
        ctx = _make_ctx()
        history = [{"m": i} for i in range(10)]
        cog.chat_manager.chats = {ctx.channel.id: {"history": history}}
        cog.chat_manager.processing_locks = {}
        status_msg = MagicMock()
        status_msg.edit = AsyncMock()
        ctx.send = AsyncMock(return_value=status_msg)

        hm = MagicMock()
        hm.estimate_tokens = MagicMock(side_effect=[1000, 200])
        hm.smart_trim_by_tokens = AsyncMock(return_value=history[:3])
        with (
            patch("cogs.ai_core.memory.history_manager.history_manager", hm),
            patch("cogs.ai_core.storage.save_history", AsyncMock()),
        ):
            await cog.auto_summarize_cmd.callback(cog, ctx, 500000)
        status_msg.edit.assert_awaited()
        assert "Summarization complete" in status_msg.edit.call_args.kwargs["content"]

    @pytest.mark.asyncio
    async def test_summarize_exception(self):
        cog = _make_cog()
        ctx = _make_ctx()
        history = [{"m": i} for i in range(10)]
        cog.chat_manager.chats = {ctx.channel.id: {"history": history}}
        cog.chat_manager.processing_locks = {}
        status_msg = MagicMock()
        status_msg.edit = AsyncMock()
        ctx.send = AsyncMock(return_value=status_msg)
        hm = MagicMock()
        hm.estimate_tokens = MagicMock(return_value=1000)
        hm.smart_trim_by_tokens = AsyncMock(side_effect=RuntimeError("trim fail"))
        with patch("cogs.ai_core.memory.history_manager.history_manager", hm):
            await cog.auto_summarize_cmd.callback(cog, ctx, 500000)
        assert "❌ Failed:" in status_msg.edit.call_args.kwargs["content"]

    @pytest.mark.asyncio
    async def test_summarize_existing_lock_reused(self):
        cog = _make_cog()
        ctx = _make_ctx()
        history = [{"m": i} for i in range(5)]
        cog.chat_manager.chats = {ctx.channel.id: {"history": history}}
        existing_lock = asyncio.Lock()
        cog.chat_manager.processing_locks = {ctx.channel.id: existing_lock}
        status_msg = MagicMock()
        status_msg.edit = AsyncMock()
        ctx.send = AsyncMock(return_value=status_msg)
        hm = MagicMock()
        hm.estimate_tokens = MagicMock(side_effect=[500, 100])
        hm.smart_trim_by_tokens = AsyncMock(return_value=history[:2])
        with (
            patch("cogs.ai_core.memory.history_manager.history_manager", hm),
            patch("cogs.ai_core.storage.save_history", AsyncMock()),
        ):
            await cog.auto_summarize_cmd.callback(cog, ctx, 1000)
        # lock object must not be replaced
        assert cog.chat_manager.processing_locks[ctx.channel.id] is existing_lock


# ============================================================================
# channel_ratelimit_cmd (lines 1684-1709)
# ============================================================================


class TestChannelRatelimitCmd:
    @pytest.mark.asyncio
    async def test_view_current(self):
        cog = _make_cog()
        ctx = _make_ctx()
        with patch("utils.reliability.rate_limiter.rate_limiter") as rl:
            rl.get_channel_limit = MagicMock(return_value=15)
            await cog.channel_ratelimit_cmd.callback(cog, ctx, None)
        assert "15 requests/minute" in ctx.send.call_args.args[0]

    @pytest.mark.asyncio
    async def test_set_limit(self):
        cog = _make_cog()
        ctx = _make_ctx()
        with patch("utils.reliability.rate_limiter.rate_limiter") as rl:
            rl.set_channel_limit = AsyncMock()
            await cog.channel_ratelimit_cmd.callback(cog, ctx, 20)
            rl.set_channel_limit.assert_awaited_once_with(ctx.channel.id, 20)
        assert "set to: 20" in ctx.send.call_args.args[0]

    @pytest.mark.asyncio
    async def test_not_supported(self):
        cog = _make_cog()
        ctx = _make_ctx()
        with patch("utils.reliability.rate_limiter.rate_limiter") as rl:
            rl.get_channel_limit = MagicMock(side_effect=AttributeError())
            await cog.channel_ratelimit_cmd.callback(cog, ctx, None)
        assert "doesn't support per-channel" in ctx.send.call_args.args[0]


# ============================================================================
# unrestricted_mode_cmd (lines 1711-1816)
# ============================================================================


class TestUnrestrictedModeCmd:
    @pytest.mark.asyncio
    async def test_unrestricted_unavailable(self):
        cog = _make_cog()
        ctx = _make_ctx()
        with patch("cogs.ai_core.ai_cog.UNRESTRICTED_AVAILABLE", False):
            await cog.unrestricted_mode_cmd.callback(cog, ctx, None)
        assert "Unrestricted module not available" in ctx.send.call_args.args[0]

    @pytest.mark.asyncio
    async def test_status_empty(self):
        cog = _make_cog()
        ctx = _make_ctx()
        with (
            patch("cogs.ai_core.ai_cog.GUARDRAILS_AVAILABLE", True),
            patch("cogs.ai_core.ai_cog.unrestricted_channels", set()),
            patch("cogs.ai_core.ai_cog.unrestricted_all_enabled", MagicMock(return_value=False)),
        ):
            await cog.unrestricted_mode_cmd.callback(cog, ctx, "status")
        assert "No channels are individually marked unrestricted" in ctx.send.call_args.args[0]

    @pytest.mark.asyncio
    async def test_status_global_override_active(self):
        """When AI_UNRESTRICTED_ALL is on, status surfaces the global override note."""
        cog = _make_cog()
        ctx = _make_ctx()
        with (
            patch("cogs.ai_core.ai_cog.GUARDRAILS_AVAILABLE", True),
            patch("cogs.ai_core.ai_cog.unrestricted_channels", set()),
            patch("cogs.ai_core.ai_cog.unrestricted_all_enabled", MagicMock(return_value=True)),
        ):
            await cog.unrestricted_mode_cmd.callback(cog, ctx, "status")
        assert "Global override ACTIVE" in ctx.send.call_args.args[0]

    @pytest.mark.asyncio
    async def test_status_with_channels(self):
        cog = _make_cog()
        ctx = _make_ctx()
        cog.bot.get_channel = MagicMock(side_effect=lambda cid: MagicMock() if cid == 10 else None)
        with (
            patch("cogs.ai_core.ai_cog.GUARDRAILS_AVAILABLE", True),
            patch("cogs.ai_core.ai_cog.unrestricted_channels", {10, 20}),
        ):
            await cog.unrestricted_mode_cmd.callback(cog, ctx, "status")
        embed = ctx.send.call_args.kwargs["embed"]
        assert "Unknown Channel" in embed.description

    @pytest.mark.asyncio
    async def test_invalid_mode(self):
        cog = _make_cog()
        ctx = _make_ctx()
        with (
            patch("cogs.ai_core.ai_cog.GUARDRAILS_AVAILABLE", True),
            patch("cogs.ai_core.ai_cog.is_unrestricted", MagicMock(return_value=False)),
        ):
            await cog.unrestricted_mode_cmd.callback(cog, ctx, "bogus")
        assert "กรุณาระบุ" in ctx.send.call_args.args[0]

    @pytest.mark.asyncio
    async def test_toggle_enable(self):
        cog = _make_cog()
        ctx = _make_ctx()
        set_mock = MagicMock()
        with (
            patch("cogs.ai_core.ai_cog.GUARDRAILS_AVAILABLE", True),
            patch("cogs.ai_core.ai_cog.is_unrestricted", MagicMock(return_value=False)),
            patch("cogs.ai_core.ai_cog.set_unrestricted", set_mock),
        ):
            await cog.unrestricted_mode_cmd.callback(cog, ctx, None)
        set_mock.assert_called_once_with(ctx.channel.id, True)
        embed = ctx.send.call_args.kwargs["embed"]
        assert "ENABLED" in embed.title

    @pytest.mark.asyncio
    async def test_toggle_disable(self):
        cog = _make_cog()
        ctx = _make_ctx()
        set_mock = MagicMock()
        with (
            patch("cogs.ai_core.ai_cog.GUARDRAILS_AVAILABLE", True),
            patch("cogs.ai_core.ai_cog.is_unrestricted", MagicMock(return_value=True)),
            patch("cogs.ai_core.ai_cog.set_unrestricted", set_mock),
        ):
            await cog.unrestricted_mode_cmd.callback(cog, ctx, None)
        set_mock.assert_called_once_with(ctx.channel.id, False)
        embed = ctx.send.call_args.kwargs["embed"]
        assert "Disabled" in embed.title

    @pytest.mark.asyncio
    async def test_mode_on_explicit(self):
        cog = _make_cog()
        ctx = _make_ctx()
        set_mock = MagicMock()
        with (
            patch("cogs.ai_core.ai_cog.GUARDRAILS_AVAILABLE", True),
            patch("cogs.ai_core.ai_cog.is_unrestricted", MagicMock(return_value=False)),
            patch("cogs.ai_core.ai_cog.set_unrestricted", set_mock),
        ):
            await cog.unrestricted_mode_cmd.callback(cog, ctx, "yes")
        set_mock.assert_called_once_with(ctx.channel.id, True)

    @pytest.mark.asyncio
    async def test_mode_off_explicit(self):
        cog = _make_cog()
        ctx = _make_ctx()
        set_mock = MagicMock()
        with (
            patch("cogs.ai_core.ai_cog.GUARDRAILS_AVAILABLE", True),
            patch("cogs.ai_core.ai_cog.is_unrestricted", MagicMock(return_value=True)),
            patch("cogs.ai_core.ai_cog.set_unrestricted", set_mock),
        ):
            await cog.unrestricted_mode_cmd.callback(cog, ctx, "off")
        set_mock.assert_called_once_with(ctx.channel.id, False)


# ============================================================================
# setup (lines 1819-1829)
# ============================================================================


class TestSetup:
    @pytest.mark.asyncio
    async def test_setup_adds_cogs(self):
        from cogs.ai_core.ai_cog import setup

        bot = MagicMock()
        bot.add_cog = AsyncMock()
        await setup(bot)
        # AI + AIDebug + MemoryCommands
        assert bot.add_cog.await_count == 3


# ============================================================================
# region 500-944: message pipeline (on_message + handlers), channel cleanup,
# prefix resolution, reset_ai cli reset, and the scattered ImportError
# fallbacks in dashboard/audit/auto_summarize.
#
# These are exercised by calling the listener/handler coroutines directly
# (they are plain async methods, not decorated commands), with discord.py +
# the whole ai_core stack mocked. No network / no real voice / no real sleep.
# ============================================================================


def _make_message(
    *,
    content="hello",
    guild_id=111222333,
    channel_id=987654321,
    author_id=42,
    author_bot=False,
    webhook_id=None,
    is_dm=False,
    mentions=None,
    reference=None,
):
    """Build a mock discord.Message for the on_message pipeline."""
    msg = MagicMock()
    msg.content = content
    msg.webhook_id = webhook_id
    msg.id = 555000111
    msg.attachments = []
    msg.mentions = mentions if mentions is not None else []
    msg.reference = reference

    author = MagicMock()
    author.id = author_id
    author.bot = author_bot
    msg.author = author

    if is_dm:
        msg.guild = None
        # DM channel
        ch = MagicMock(spec=discord.DMChannel)
        ch.id = channel_id
        ch.send = AsyncMock()
        msg.channel = ch
    else:
        guild = MagicMock()
        guild.id = guild_id
        msg.guild = guild
        ch = MagicMock(spec=discord.TextChannel)
        ch.id = channel_id
        ch.name = "general"
        ch.send = AsyncMock()
        msg.channel = ch
    return msg


def _bot_user(bot, user_id=999):
    u = MagicMock()
    u.id = user_id
    bot.user = u
    return u


# ----------------------------------------------------------------------------
# reset_ai cli-mode session reset (lines 498-505)
# ----------------------------------------------------------------------------


class TestResetAiCliMode:
    @pytest.mark.asyncio
    async def test_cli_mode_resets_session(self):
        cog = _make_cog()
        ctx = _make_ctx(channel_id=4242)
        cog.chat_manager.chats = {4242: {}}
        cog.chat_manager.seen_users = {}
        cog.chat_manager.last_accessed = {}
        cog.chat_manager.processing_locks = {}
        cog.chat_manager.streaming_enabled = {}
        cog.chat_manager._message_queue = MagicMock()
        cog.chat_manager.cli_mode = True

        reset_mock = MagicMock()
        import sys
        from types import ModuleType

        fake_mod = ModuleType("cogs.ai_core.api.discord_chat_claude_cli")
        fake_mod.reset_channel_session = reset_mock
        with (
            patch.dict(
                sys.modules,
                {"cogs.ai_core.api.discord_chat_claude_cli": fake_mod},
            ),
            patch("cogs.ai_core.ai_cog.delete_history", AsyncMock()),
        ):
            await cog.reset_ai.callback(cog, ctx)

        reset_mock.assert_called_once_with(4242)
        ctx.send.assert_awaited_once()
        assert "ล้างความจำ" in ctx.send.call_args.args[0]

    @pytest.mark.asyncio
    async def test_non_cli_mode_skips_session_reset(self):
        cog = _make_cog()
        ctx = _make_ctx(channel_id=4243)
        cog.chat_manager.chats = {}
        cog.chat_manager.seen_users = {}
        cog.chat_manager.last_accessed = {}
        cog.chat_manager.processing_locks = {}
        cog.chat_manager.streaming_enabled = {}
        cog.chat_manager._message_queue = MagicMock()
        cog.chat_manager.cli_mode = False

        with patch("cogs.ai_core.ai_cog.delete_history", AsyncMock()):
            await cog.reset_ai.callback(cog, ctx)

        ctx.send.assert_awaited_once()
        cog.chat_manager._message_queue.clear_channel.assert_called_once_with(4243)


# ----------------------------------------------------------------------------
# reset_ai_error (lines 507-513)
# ----------------------------------------------------------------------------


class TestResetAiError:
    @pytest.mark.asyncio
    async def test_not_owner_error(self):
        from discord.ext import commands

        cog = _make_cog()
        ctx = _make_ctx()
        await cog.reset_ai_error(ctx, commands.NotOwner())
        assert "เจ้าของบอท" in ctx.send.call_args.args[0]

    @pytest.mark.asyncio
    async def test_other_error_reraised(self):
        cog = _make_cog()
        ctx = _make_ctx()
        boom = RuntimeError("other")
        with pytest.raises(RuntimeError):
            await cog.reset_ai_error(ctx, boom)
        ctx.send.assert_not_called()


# ----------------------------------------------------------------------------
# on_guild_channel_delete (lines 515-537)
# ----------------------------------------------------------------------------


class TestOnGuildChannelDelete:
    @pytest.mark.asyncio
    async def test_cleans_all_per_channel_state(self):
        cog = _make_cog()
        cid = 70707
        cog.chat_manager.chats = {cid: {}, 1: {}}
        cog.chat_manager.seen_users = {cid: {}}
        cog.chat_manager.last_accessed = {cid: 0}
        cog.chat_manager.processing_locks = {cid: object()}
        cog.chat_manager.streaming_enabled = {cid: True}
        cog.chat_manager._message_queue = MagicMock()

        channel = MagicMock()
        channel.id = cid
        with patch("cogs.ai_core.ai_cog.invalidate_webhook_cache_on_channel_delete") as inval:
            await cog.on_guild_channel_delete(channel)

        inval.assert_called_once_with(cid)
        assert cid not in cog.chat_manager.chats
        assert 1 in cog.chat_manager.chats  # untouched
        assert cid not in cog.chat_manager.seen_users
        cog.chat_manager._message_queue.clear_channel.assert_called_once_with(cid)

    @pytest.mark.asyncio
    async def test_cli_mode_resets_server_side_session(self):
        # When cli_mode is on, channel deletion must also evict the server-side
        # CLI session so a recreated channel id doesn't replay the wiped
        # conversation (lines 668-673). The default _make_cog() pins cli_mode
        # False, so this branch only runs when explicitly enabled.
        cog = _make_cog()
        cog.chat_manager.cli_mode = True
        cog.chat_manager.chats = {}
        cog.chat_manager.seen_users = {}
        cog.chat_manager.last_accessed = {}
        cog.chat_manager.streaming_enabled = {}
        cog.chat_manager._message_queue = MagicMock()

        channel = MagicMock()
        channel.id = 80808
        with (
            patch("cogs.ai_core.ai_cog.invalidate_webhook_cache_on_channel_delete"),
            patch(
                "cogs.ai_core.api.discord_chat_claude_cli.reset_channel_session"
            ) as reset_session,
        ):
            await cog.on_guild_channel_delete(channel)

        reset_session.assert_called_once_with(80808)

    @pytest.mark.asyncio
    async def test_non_cli_mode_skips_server_side_reset(self):
        # The default cog has cli_mode False, so the CLI session reset import +
        # call must be skipped entirely.
        cog = _make_cog()
        cog.chat_manager.chats = {}
        cog.chat_manager.seen_users = {}
        cog.chat_manager.last_accessed = {}
        cog.chat_manager.streaming_enabled = {}
        cog.chat_manager._message_queue = MagicMock()

        channel = MagicMock()
        channel.id = 90909
        with (
            patch("cogs.ai_core.ai_cog.invalidate_webhook_cache_on_channel_delete"),
            patch(
                "cogs.ai_core.api.discord_chat_claude_cli.reset_channel_session"
            ) as reset_session,
        ):
            await cog.on_guild_channel_delete(channel)

        reset_session.assert_not_called()


# ----------------------------------------------------------------------------
# _resolve_prefix_tuple (lines 539-570)
# ----------------------------------------------------------------------------


class TestResolvePrefixTuple:
    @pytest.mark.asyncio
    async def test_str_prefix(self):
        cog = _make_cog()
        cog.bot.command_prefix = "?"
        msg = _make_message()
        assert await cog._resolve_prefix_tuple(msg) == ("?",)

    @pytest.mark.asyncio
    async def test_empty_str_prefix_falls_back(self):
        cog = _make_cog()
        cog.bot.command_prefix = ""
        msg = _make_message()
        assert await cog._resolve_prefix_tuple(msg) == ("!",)

    @pytest.mark.asyncio
    async def test_list_prefix_cleaned(self):
        cog = _make_cog()
        cog.bot.command_prefix = ["!", "", "?"]
        msg = _make_message()
        assert await cog._resolve_prefix_tuple(msg) == ("!", "?")

    @pytest.mark.asyncio
    async def test_none_prefix_falls_back(self):
        cog = _make_cog()
        cog.bot.command_prefix = None
        msg = _make_message()
        assert await cog._resolve_prefix_tuple(msg) == ("!",)

    @pytest.mark.asyncio
    async def test_callable_returns_str(self):
        cog = _make_cog()
        cog.bot.command_prefix = lambda bot, message: "$"
        msg = _make_message()
        assert await cog._resolve_prefix_tuple(msg) == ("$",)

    @pytest.mark.asyncio
    async def test_callable_returns_list(self):
        cog = _make_cog()
        cog.bot.command_prefix = lambda bot, message: ["a", "b"]
        msg = _make_message()
        assert await cog._resolve_prefix_tuple(msg) == ("a", "b")

    @pytest.mark.asyncio
    async def test_callable_returns_other_type(self):
        cog = _make_cog()
        cog.bot.command_prefix = lambda bot, message: 12345  # not str/list/tuple
        msg = _make_message()
        assert await cog._resolve_prefix_tuple(msg) == ("!",)

    @pytest.mark.asyncio
    async def test_callable_coroutine(self):
        cog = _make_cog()

        async def prefix(bot, message):
            return "%%"

        cog.bot.command_prefix = prefix
        msg = _make_message()
        assert await cog._resolve_prefix_tuple(msg) == ("%%",)

    @pytest.mark.asyncio
    async def test_callable_raises_falls_back(self):
        cog = _make_cog()

        def prefix(bot, message):
            raise ValueError("boom")

        cog.bot.command_prefix = prefix
        msg = _make_message()
        assert await cog._resolve_prefix_tuple(msg) == ("!",)


# ----------------------------------------------------------------------------
# on_message dispatch (lines 572-590)
# ----------------------------------------------------------------------------


class TestOnMessageDispatch:
    @pytest.mark.asyncio
    async def test_webhook_routed(self):
        cog = _make_cog()
        cog._handle_webhook_message = AsyncMock()
        msg = _make_message(webhook_id=123)
        await cog.on_message(msg)
        cog._handle_webhook_message.assert_awaited_once_with(msg)

    @pytest.mark.asyncio
    async def test_own_message_ignored(self):
        cog = _make_cog()
        cog._handle_guild_message = AsyncMock()
        bot_user = _bot_user(cog.bot)
        msg = _make_message()
        msg.author = bot_user  # author == bot.user
        await cog.on_message(msg)
        cog._handle_guild_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_bot_author_ignored(self):
        cog = _make_cog()
        cog._handle_guild_message = AsyncMock()
        _bot_user(cog.bot)
        msg = _make_message(author_bot=True)
        await cog.on_message(msg)
        cog._handle_guild_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_dm_routed(self):
        cog = _make_cog()
        cog._handle_dm_message = AsyncMock()
        _bot_user(cog.bot)
        msg = _make_message(is_dm=True)
        await cog.on_message(msg)
        cog._handle_dm_message.assert_awaited_once_with(msg)

    @pytest.mark.asyncio
    async def test_guild_routed(self):
        cog = _make_cog()
        cog._handle_guild_message = AsyncMock()
        _bot_user(cog.bot)
        msg = _make_message()
        await cog.on_message(msg)
        cog._handle_guild_message.assert_awaited_once_with(msg)


# ----------------------------------------------------------------------------
# _handle_webhook_message (lines 592-781)
# ----------------------------------------------------------------------------


class TestHandleWebhookMessage:
    @pytest.mark.asyncio
    async def test_dm_safety_returns(self):
        cog = _make_cog()
        msg = _make_message(is_dm=True, webhook_id=5)
        msg.guild = None
        await cog._handle_webhook_message(msg)  # returns, no error

    @pytest.mark.asyncio
    async def test_webhook_id_none_returns(self):
        cog = _make_cog()
        msg = _make_message(webhook_id=None)
        await cog._handle_webhook_message(msg)

    @pytest.mark.asyncio
    async def test_unsupported_channel_type_returns(self):
        cog = _make_cog()
        msg = _make_message(webhook_id=5)
        # channel not TextChannel/Thread -> webhook_channel None
        msg.channel = MagicMock()  # plain mock, not a spec'd TextChannel
        msg.channel.id = 1
        await cog._handle_webhook_message(msg)

    @pytest.mark.asyncio
    async def test_thread_parent_resolution_not_textchannel(self):
        cog = _make_cog()
        msg = _make_message(webhook_id=5)
        thread = MagicMock(spec=discord.Thread)
        thread.id = 1
        thread.parent = MagicMock()  # parent not a TextChannel
        msg.channel = thread
        await cog._handle_webhook_message(msg)

    @pytest.mark.asyncio
    async def test_cache_hit_known_proxy_allowed_main_guild(self):
        cog = _make_cog()
        cog.chat_manager.process_chat = AsyncMock()
        msg = _make_message(webhook_id=777, content="!chat hi there")
        # cache says known proxy, not expired
        cog._webhook_verify_cache = {777: (True, time.time() + 1000)}
        registered = MagicMock()
        registered.cog_name = cog.__class__.__name__
        registered.name = "chat"
        cog.bot.get_command = MagicMock(return_value=registered)
        with (
            patch("cogs.ai_core.ai_cog.GUILD_ID_MAIN", msg.guild.id),
            patch("cogs.ai_core.ai_cog.check_rate_limit", AsyncMock(return_value=True)),
        ):
            await cog._handle_webhook_message(msg)
        cog.chat_manager.process_chat.assert_awaited_once()
        # user_msg parsed after "!chat "
        assert cog.chat_manager.process_chat.call_args.args[2] == "hi there"

    @pytest.mark.asyncio
    async def test_custom_channel_limit_called_silently_on_webhook_path(self):
        # Regression (Fix E): the webhook proxy path MUST invoke the owner-set
        # custom-channel limit check with send_message=False, matching its two
        # sibling rate-limit checks above, so an exceeded per-channel limit never
        # posts a visible rate-limit notice in reply to a Tupperbox/PluralKit
        # proxied message. Pre-fix the call passed no send_message kwarg.
        cog = _make_cog()
        cog.chat_manager.process_chat = AsyncMock()
        cog._check_custom_channel_limit = AsyncMock(return_value=True)
        msg = _make_message(webhook_id=777, content="!chat hi there")
        cog._webhook_verify_cache = {777: (True, time.time() + 1000)}
        registered = MagicMock()
        registered.cog_name = cog.__class__.__name__
        registered.name = "chat"
        cog.bot.get_command = MagicMock(return_value=registered)
        with (
            patch("cogs.ai_core.ai_cog.GUILD_ID_MAIN", msg.guild.id),
            patch("cogs.ai_core.ai_cog.check_rate_limit", AsyncMock(return_value=True)),
        ):
            await cog._handle_webhook_message(msg)
        cog._check_custom_channel_limit.assert_awaited_once_with(msg, send_message=False)
        cog.chat_manager.process_chat.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_not_known_proxy_returns(self):
        cog = _make_cog()
        cog.chat_manager.process_chat = AsyncMock()
        msg = _make_message(webhook_id=777)
        cog._webhook_verify_cache = {777: (False, time.time() + 1000)}
        await cog._handle_webhook_message(msg)
        cog.chat_manager.process_chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_verify_via_webhooks_application_id(self):
        cog = _make_cog()
        cog.chat_manager.process_chat = AsyncMock()
        msg = _make_message(webhook_id=777, content="!chat hello")
        cog._webhook_verify_cache = {}
        # craft a webhook entry whose application_id is in the allowlist
        allowed_id = next(iter(cog._ALLOWED_WEBHOOK_BOT_IDS))
        wh = MagicMock()
        wh.id = 777
        wh.user = MagicMock()
        wh.user.bot = True
        wh.user.id = 111
        wh.application_id = allowed_id
        msg.channel.webhooks = AsyncMock(return_value=[wh])
        registered = MagicMock()
        registered.cog_name = cog.__class__.__name__
        registered.name = "chat"
        cog.bot.get_command = MagicMock(return_value=registered)
        with (
            patch("cogs.ai_core.ai_cog.GUILD_ID_MAIN", msg.guild.id),
            patch("cogs.ai_core.ai_cog.check_rate_limit", AsyncMock(return_value=True)),
        ):
            await cog._handle_webhook_message(msg)
        cog.chat_manager.process_chat.assert_awaited_once()
        # cached as known proxy now
        assert cog._webhook_verify_cache[777][0] is True

    @pytest.mark.asyncio
    async def test_verify_via_creator_id_fallback(self):
        cog = _make_cog()
        cog.chat_manager.process_chat = AsyncMock()
        msg = _make_message(webhook_id=778, content="!ask hi")
        cog._webhook_verify_cache = {}
        allowed_id = next(iter(cog._ALLOWED_WEBHOOK_BOT_IDS))
        wh = MagicMock()
        wh.id = 778
        wh.user = MagicMock()
        wh.user.bot = True
        wh.user.id = allowed_id
        wh.application_id = None  # no app id -> creator fallback
        msg.channel.webhooks = AsyncMock(return_value=[wh])
        registered = MagicMock()
        registered.cog_name = cog.__class__.__name__
        registered.name = "ask"
        cog.bot.get_command = MagicMock(return_value=registered)
        with (
            patch("cogs.ai_core.ai_cog.GUILD_ID_MAIN", msg.guild.id),
            patch("cogs.ai_core.ai_cog.check_rate_limit", AsyncMock(return_value=True)),
        ):
            await cog._handle_webhook_message(msg)
        cog.chat_manager.process_chat.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_webhook_creator_not_bot_no_match(self):
        cog = _make_cog()
        cog.chat_manager.process_chat = AsyncMock()
        msg = _make_message(webhook_id=779)
        cog._webhook_verify_cache = {}
        wh = MagicMock()
        wh.id = 779
        wh.user = MagicMock()
        wh.user.bot = False  # creator_id stays None
        wh.user.id = 111
        wh.application_id = 222  # not in allowlist
        msg.channel.webhooks = AsyncMock(return_value=[wh])
        with patch("cogs.ai_core.ai_cog.GUILD_ID_MAIN", msg.guild.id):
            await cog._handle_webhook_message(msg)
        # not a known proxy -> dropped, cached False
        assert cog._webhook_verify_cache[779][0] is False
        cog.chat_manager.process_chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_forbidden_logs_once_and_returns(self):
        cog = _make_cog()
        msg = _make_message(webhook_id=780)
        cog._webhook_verify_cache = {}
        msg.channel.webhooks = AsyncMock(side_effect=discord.Forbidden(MagicMock(), "no"))
        await cog._handle_webhook_message(msg)
        # logged set created and populated
        assert msg.channel.id in cog._webhook_forbidden_logged
        # second call: already logged path
        msg.channel.webhooks = AsyncMock(side_effect=discord.Forbidden(MagicMock(), "no"))
        await cog._handle_webhook_message(msg)

    @pytest.mark.asyncio
    async def test_http_exception_no_cache(self):
        cog = _make_cog()
        msg = _make_message(webhook_id=781)
        cog._webhook_verify_cache = {}
        msg.channel.webhooks = AsyncMock(side_effect=discord.HTTPException(MagicMock(), "boom"))
        with patch("cogs.ai_core.ai_cog.GUILD_ID_MAIN", msg.guild.id):
            await cog._handle_webhook_message(msg)
        # should_cache False -> nothing cached
        assert 781 not in cog._webhook_verify_cache

    @pytest.mark.asyncio
    async def test_cache_eviction_when_full(self):
        cog = _make_cog()
        msg = _make_message(webhook_id=782)
        now = time.time()
        # Fill cache to max with a mix of expired + live entries
        cog._WEBHOOK_CACHE_MAX_SIZE = 3
        cog._webhook_verify_cache = {
            1: (False, now - 10),  # expired
            2: (False, now + 1000),  # live, soonest expiry among live
            3: (False, now + 5000),  # live
        }
        wh = MagicMock()
        wh.id = 999  # no match -> is_known_proxy False but should_cache True
        wh.user = None
        wh.application_id = None
        msg.channel.webhooks = AsyncMock(return_value=[wh])
        with patch("cogs.ai_core.ai_cog.GUILD_ID_MAIN", msg.guild.id):
            await cog._handle_webhook_message(msg)
        # expired key 1 pruned; new key 782 inserted
        assert 1 not in cog._webhook_verify_cache
        assert 782 in cog._webhook_verify_cache

    @pytest.mark.asyncio
    async def test_cache_eviction_oldest_when_still_full(self):
        cog = _make_cog()
        msg = _make_message(webhook_id=783)
        now = time.time()
        cog._WEBHOOK_CACHE_MAX_SIZE = 2
        # no expired entries -> must evict oldest (soonest expiry)
        cog._webhook_verify_cache = {
            10: (False, now + 100),  # oldest expiry
            11: (False, now + 5000),
        }
        wh = MagicMock()
        wh.id = 999
        wh.user = None
        wh.application_id = None
        msg.channel.webhooks = AsyncMock(return_value=[wh])
        with patch("cogs.ai_core.ai_cog.GUILD_ID_MAIN", msg.guild.id):
            await cog._handle_webhook_message(msg)
        assert 10 not in cog._webhook_verify_cache  # evicted
        assert 783 in cog._webhook_verify_cache

    @pytest.mark.asyncio
    async def test_not_allowed_restriction_returns(self):
        cog = _make_cog()
        cog.chat_manager.process_chat = AsyncMock()
        msg = _make_message(webhook_id=784, guild_id=424242, channel_id=999)
        cog._webhook_verify_cache = {784: (True, time.time() + 1000)}
        # No guild/channel matches the restriction constants -> not allowed
        with (
            patch("cogs.ai_core.ai_cog.GUILD_ID_RESTRICTED", 1),
            patch("cogs.ai_core.ai_cog.CHANNEL_ID_ALLOWED", 2),
            patch("cogs.ai_core.ai_cog.GUILD_ID_MAIN", 3),
            patch("cogs.ai_core.ai_cog.GUILD_ID_RP", 4),
        ):
            await cog._handle_webhook_message(msg)
        cog.chat_manager.process_chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_restricted_guild_allowed_channel(self):
        cog = _make_cog()
        cog.chat_manager.process_chat = AsyncMock()
        msg = _make_message(webhook_id=785, guild_id=1, channel_id=2, content="!chat yo")
        cog._webhook_verify_cache = {785: (True, time.time() + 1000)}
        registered = MagicMock()
        registered.cog_name = cog.__class__.__name__
        registered.name = "chat"
        cog.bot.get_command = MagicMock(return_value=registered)
        with (
            patch("cogs.ai_core.ai_cog.GUILD_ID_RESTRICTED", 1),
            patch("cogs.ai_core.ai_cog.CHANNEL_ID_ALLOWED", 2),
            patch("cogs.ai_core.ai_cog.check_rate_limit", AsyncMock(return_value=True)),
        ):
            await cog._handle_webhook_message(msg)
        cog.chat_manager.process_chat.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_prefix_match_returns(self):
        cog = _make_cog()
        cog.chat_manager.process_chat = AsyncMock()
        msg = _make_message(webhook_id=786, content="just chatting no prefix")
        cog._webhook_verify_cache = {786: (True, time.time() + 1000)}
        with patch("cogs.ai_core.ai_cog.GUILD_ID_MAIN", msg.guild.id):
            await cog._handle_webhook_message(msg)
        cog.chat_manager.process_chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_command_returns(self):
        cog = _make_cog()
        cog.chat_manager.process_chat = AsyncMock()
        msg = _make_message(webhook_id=787, content="! ")  # prefix then space => empty cmd
        cog._webhook_verify_cache = {787: (True, time.time() + 1000)}
        cog.bot.command_prefix = "!"
        with patch("cogs.ai_core.ai_cog.GUILD_ID_MAIN", msg.guild.id):
            await cog._handle_webhook_message(msg)
        cog.chat_manager.process_chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_command_not_registered_returns(self):
        cog = _make_cog()
        cog.chat_manager.process_chat = AsyncMock()
        msg = _make_message(webhook_id=788, content="!unknown hi")
        cog._webhook_verify_cache = {788: (True, time.time() + 1000)}
        cog.bot.get_command = MagicMock(return_value=None)
        with patch("cogs.ai_core.ai_cog.GUILD_ID_MAIN", msg.guild.id):
            await cog._handle_webhook_message(msg)
        cog.chat_manager.process_chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_command_wrong_cog_returns(self):
        cog = _make_cog()
        cog.chat_manager.process_chat = AsyncMock()
        msg = _make_message(webhook_id=789, content="!chat hi")
        cog._webhook_verify_cache = {789: (True, time.time() + 1000)}
        registered = MagicMock()
        registered.cog_name = "SomeOtherCog"
        registered.name = "chat"
        cog.bot.get_command = MagicMock(return_value=registered)
        with patch("cogs.ai_core.ai_cog.GUILD_ID_MAIN", msg.guild.id):
            await cog._handle_webhook_message(msg)
        cog.chat_manager.process_chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_command_not_chat_or_ask_returns(self):
        cog = _make_cog()
        cog.chat_manager.process_chat = AsyncMock()
        msg = _make_message(webhook_id=790, content="!dashboard")
        cog._webhook_verify_cache = {790: (True, time.time() + 1000)}
        registered = MagicMock()
        registered.cog_name = cog.__class__.__name__
        registered.name = "dashboard"
        cog.bot.get_command = MagicMock(return_value=registered)
        with patch("cogs.ai_core.ai_cog.GUILD_ID_MAIN", msg.guild.id):
            await cog._handle_webhook_message(msg)
        cog.chat_manager.process_chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_rate_limit_api_blocks(self):
        cog = _make_cog()
        cog.chat_manager.process_chat = AsyncMock()
        msg = _make_message(webhook_id=791, content="!chat hi")
        cog._webhook_verify_cache = {791: (True, time.time() + 1000)}
        registered = MagicMock()
        registered.cog_name = cog.__class__.__name__
        registered.name = "chat"
        cog.bot.get_command = MagicMock(return_value=registered)
        with (
            patch("cogs.ai_core.ai_cog.GUILD_ID_MAIN", msg.guild.id),
            patch("cogs.ai_core.ai_cog.check_rate_limit", AsyncMock(return_value=False)),
        ):
            await cog._handle_webhook_message(msg)
        cog.chat_manager.process_chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_rate_limit_global_blocks(self):
        cog = _make_cog()
        cog.chat_manager.process_chat = AsyncMock()
        msg = _make_message(webhook_id=792, content="!chat hi")
        cog._webhook_verify_cache = {792: (True, time.time() + 1000)}
        registered = MagicMock()
        registered.cog_name = cog.__class__.__name__
        registered.name = "chat"
        cog.bot.get_command = MagicMock(return_value=registered)
        # first call (api) True, second (global) False
        rl = AsyncMock(side_effect=[True, False])
        with (
            patch("cogs.ai_core.ai_cog.GUILD_ID_MAIN", msg.guild.id),
            patch("cogs.ai_core.ai_cog.check_rate_limit", rl),
        ):
            await cog._handle_webhook_message(msg)
        cog.chat_manager.process_chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_rp_command_channel_routes_to_output(self):
        cog = _make_cog()
        cog.chat_manager.process_chat = AsyncMock()
        msg = _make_message(webhook_id=793, guild_id=5000, channel_id=6000, content="!chat hey")
        cog._webhook_verify_cache = {793: (True, time.time() + 1000)}
        registered = MagicMock()
        registered.cog_name = cog.__class__.__name__
        registered.name = "chat"
        cog.bot.get_command = MagicMock(return_value=registered)
        out = MagicMock(spec=discord.TextChannel)
        cog.bot.get_channel = MagicMock(return_value=out)
        with (
            patch("cogs.ai_core.ai_cog.GUILD_ID_RP", 5000),
            patch("cogs.ai_core.ai_cog.CHANNEL_ID_RP_COMMAND", 6000),
            patch("cogs.ai_core.ai_cog.CHANNEL_ID_RP_OUTPUT", 7000),
            patch("cogs.ai_core.ai_cog.check_rate_limit", AsyncMock(return_value=True)),
        ):
            await cog._handle_webhook_message(msg)
        cog.chat_manager.process_chat.assert_awaited_once()
        assert cog.chat_manager.process_chat.call_args.kwargs["output_channel"] is out

    @pytest.mark.asyncio
    async def test_rp_output_channel_rejected(self):
        # The OUTPUT channel is write-only — even a valid !chat from a proxy
        # webhook must not be processed there.
        cog = _make_cog()
        cog.chat_manager.process_chat = AsyncMock()
        msg = _make_message(webhook_id=795, guild_id=5000, channel_id=7000, content="!chat yo")
        cog._webhook_verify_cache = {795: (True, time.time() + 1000)}
        registered = MagicMock()
        registered.cog_name = cog.__class__.__name__
        registered.name = "chat"
        cog.bot.get_command = MagicMock(return_value=registered)
        with (
            patch("cogs.ai_core.ai_cog.GUILD_ID_RP", 5000),
            patch("cogs.ai_core.ai_cog.CHANNEL_ID_RP_COMMAND", 6000),
            patch("cogs.ai_core.ai_cog.CHANNEL_ID_RP_OUTPUT", 7000),
            patch("cogs.ai_core.ai_cog.check_rate_limit", AsyncMock(return_value=True)),
        ):
            await cog._handle_webhook_message(msg)
        cog.chat_manager.process_chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_chat_channel_none_returns(self):
        cog = _make_cog()
        cog.chat_manager.process_chat = AsyncMock()
        msg = _make_message(webhook_id=794, content="!chat hi")
        cog._webhook_verify_cache = {794: (True, time.time() + 1000)}
        registered = MagicMock()
        registered.cog_name = cog.__class__.__name__
        registered.name = "chat"
        cog.bot.get_command = MagicMock(return_value=registered)
        # Make _as_chat_channel return None
        with (
            patch("cogs.ai_core.ai_cog.GUILD_ID_MAIN", msg.guild.id),
            patch("cogs.ai_core.ai_cog.check_rate_limit", AsyncMock(return_value=True)),
            patch.object(cog, "_as_chat_channel", return_value=None),
        ):
            await cog._handle_webhook_message(msg)
        cog.chat_manager.process_chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_thread_parent_textchannel_verifies(self):
        cog = _make_cog()
        cog.chat_manager.process_chat = AsyncMock()
        msg = _make_message(webhook_id=796, content="!chat hi")
        cog._webhook_verify_cache = {796: (True, time.time() + 1000)}
        thread = MagicMock(spec=discord.Thread)
        thread.id = 3030
        parent = MagicMock(spec=discord.TextChannel)
        parent.id = 4040
        thread.parent = parent
        msg.channel = thread
        registered = MagicMock()
        registered.cog_name = cog.__class__.__name__
        registered.name = "chat"
        cog.bot.get_command = MagicMock(return_value=registered)
        with (
            patch("cogs.ai_core.ai_cog.GUILD_ID_MAIN", msg.guild.id),
            patch("cogs.ai_core.ai_cog.check_rate_limit", AsyncMock(return_value=True)),
        ):
            await cog._handle_webhook_message(msg)
        cog.chat_manager.process_chat.assert_awaited_once()


# ----------------------------------------------------------------------------
# _handle_dm_message (lines 783-847)
# ----------------------------------------------------------------------------


class TestHandleDmMessage:
    @pytest.mark.asyncio
    async def test_non_owner_returns(self):
        cog = _make_cog()
        cog.chat_manager.process_chat = AsyncMock()
        msg = _make_message(is_dm=True, author_id=cog.OWNER_ID + 1)
        await cog._handle_dm_message(msg)
        cog.chat_manager.process_chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_command_prefix_skipped(self):
        cog = _make_cog()
        cog.chat_manager.process_chat = AsyncMock()
        cog.chat_manager.parse_voice_command = MagicMock(return_value=(None, None))
        cog.bot.command_prefix = "!"
        msg = _make_message(is_dm=True, author_id=cog.OWNER_ID, content="!chat hi")
        await cog._handle_dm_message(msg)
        cog.chat_manager.process_chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_voice_join_with_channel(self):
        cog = _make_cog()
        cog.chat_manager.parse_voice_command = MagicMock(return_value=("join", 12345))
        cog.chat_manager.join_voice_channel = AsyncMock(return_value=(True, "joined!"))
        msg = _make_message(is_dm=True, author_id=cog.OWNER_ID, content="join 12345")
        await cog._handle_dm_message(msg)
        msg.channel.send.assert_awaited_once_with("joined!")

    @pytest.mark.asyncio
    async def test_voice_join_no_channel(self):
        cog = _make_cog()
        cog.chat_manager.parse_voice_command = MagicMock(return_value=("join", None))
        msg = _make_message(is_dm=True, author_id=cog.OWNER_ID, content="join")
        await cog._handle_dm_message(msg)
        assert "Channel ID" in msg.channel.send.call_args.args[0]

    @pytest.mark.asyncio
    async def test_voice_leave_with_clients(self):
        cog = _make_cog()
        cog.chat_manager.parse_voice_command = MagicMock(return_value=("leave", None))
        vc = MagicMock()
        vc.disconnect = AsyncMock()
        cog.bot.voice_clients = [vc]
        msg = _make_message(is_dm=True, author_id=cog.OWNER_ID, content="leave")
        await cog._handle_dm_message(msg)
        vc.disconnect.assert_awaited_once_with(force=False)
        assert "ออกจากห้องเสียง" in msg.channel.send.call_args.args[0]

    @pytest.mark.asyncio
    async def test_voice_leave_disconnect_raises(self):
        cog = _make_cog()
        cog.chat_manager.parse_voice_command = MagicMock(return_value=("leave", None))
        vc = MagicMock()
        vc.disconnect = AsyncMock(side_effect=RuntimeError("fail"))
        cog.bot.voice_clients = [vc]
        msg = _make_message(is_dm=True, author_id=cog.OWNER_ID, content="leave")
        await cog._handle_dm_message(msg)
        # still sends the success-ish summary after suppressing the error
        assert "ออกจากห้องเสียง" in msg.channel.send.call_args.args[0]

    @pytest.mark.asyncio
    async def test_voice_leave_no_clients(self):
        cog = _make_cog()
        cog.chat_manager.parse_voice_command = MagicMock(return_value=("leave", None))
        cog.bot.voice_clients = []
        msg = _make_message(is_dm=True, author_id=cog.OWNER_ID, content="leave")
        await cog._handle_dm_message(msg)
        assert "ไม่ได้อยู่ในห้องเสียง" in msg.channel.send.call_args.args[0]

    @pytest.mark.asyncio
    async def test_rate_limit_blocks_dm(self):
        cog = _make_cog()
        cog.chat_manager.process_chat = AsyncMock()
        cog.chat_manager.parse_voice_command = MagicMock(return_value=(None, None))
        cog.bot.command_prefix = "!"
        msg = _make_message(is_dm=True, author_id=cog.OWNER_ID, content="hello there")
        with patch("cogs.ai_core.ai_cog.check_rate_limit", AsyncMock(return_value=False)):
            await cog._handle_dm_message(msg)
        cog.chat_manager.process_chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_dm_happy_path_with_trace(self):
        cog = _make_cog()
        cog.chat_manager.process_chat = AsyncMock()
        cog.chat_manager.parse_voice_command = MagicMock(return_value=(None, None))
        cog.bot.command_prefix = "!"
        msg = _make_message(is_dm=True, author_id=cog.OWNER_ID, content="hello there")
        with patch("cogs.ai_core.ai_cog.check_rate_limit", AsyncMock(return_value=True)):
            await cog._handle_dm_message(msg)
        cog.chat_manager.process_chat.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_dm_trace_import_error(self):
        cog = _make_cog()
        cog.chat_manager.process_chat = AsyncMock()
        cog.chat_manager.parse_voice_command = MagicMock(return_value=(None, None))
        cog.bot.command_prefix = "!"
        msg = _make_message(is_dm=True, author_id=cog.OWNER_ID, content="hello")
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "utils.monitoring.tracing":
                raise ImportError("no tracing")
            return real_import(name, *args, **kwargs)

        with (
            patch("cogs.ai_core.ai_cog.check_rate_limit", AsyncMock(return_value=True)),
            patch("builtins.__import__", side_effect=fake_import),
        ):
            await cog._handle_dm_message(msg)
        cog.chat_manager.process_chat.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_dm_chat_channel_none_returns(self):
        cog = _make_cog()
        cog.chat_manager.process_chat = AsyncMock()
        cog.chat_manager.parse_voice_command = MagicMock(return_value=(None, None))
        cog.bot.command_prefix = "!"
        msg = _make_message(is_dm=True, author_id=cog.OWNER_ID, content="hi")
        with (
            patch("cogs.ai_core.ai_cog.check_rate_limit", AsyncMock(return_value=True)),
            patch.object(cog, "_as_chat_channel", return_value=None),
        ):
            await cog._handle_dm_message(msg)
        cog.chat_manager.process_chat.assert_not_called()


# ----------------------------------------------------------------------------
# _handle_guild_message (lines 849-950)
# ----------------------------------------------------------------------------


class TestHandleGuildMessage:
    @pytest.mark.asyncio
    async def test_command_only_guild_returns(self):
        cog = _make_cog()
        cog.chat_manager.process_chat = AsyncMock()
        msg = _make_message(guild_id=8888)
        with patch("cogs.ai_core.ai_cog.GUILD_ID_COMMAND_ONLY", 8888):
            await cog._handle_guild_message(msg)
        cog.chat_manager.process_chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_rp_command_channel_no_autorespond(self):
        # RP guild now requires an explicit !chat/!ask command (handled by the
        # command framework). Plain text in the COMMAND channel must NOT trigger
        # the AI via the passive on_message path.
        cog = _make_cog()
        cog.chat_manager.process_chat = AsyncMock()
        msg = _make_message(guild_id=5000, channel_id=6000, content="story")
        out = MagicMock(spec=discord.TextChannel)
        cog.bot.get_channel = MagicMock(return_value=out)
        with (
            patch("cogs.ai_core.ai_cog.GUILD_ID_RP", 5000),
            patch("cogs.ai_core.ai_cog.CHANNEL_ID_RP_COMMAND", 6000),
            patch("cogs.ai_core.ai_cog.CHANNEL_ID_RP_OUTPUT", 7000),
            patch("cogs.ai_core.ai_cog.check_rate_limit", AsyncMock(return_value=True)),
        ):
            await cog._handle_guild_message(msg)
        cog.chat_manager.process_chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_rp_output_channel_no_autorespond(self):
        # The OUTPUT channel is write-only: plain text there must never trigger
        # the AI either.
        cog = _make_cog()
        cog.chat_manager.process_chat = AsyncMock()
        msg = _make_message(guild_id=5000, channel_id=7000, content="reply")
        with (
            patch("cogs.ai_core.ai_cog.GUILD_ID_RP", 5000),
            patch("cogs.ai_core.ai_cog.CHANNEL_ID_RP_COMMAND", 6000),
            patch("cogs.ai_core.ai_cog.CHANNEL_ID_RP_OUTPUT", 7000),
            patch("cogs.ai_core.ai_cog.check_rate_limit", AsyncMock(return_value=True)),
        ):
            await cog._handle_guild_message(msg)
        cog.chat_manager.process_chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_rp_other_channel_returns(self):
        cog = _make_cog()
        cog.chat_manager.process_chat = AsyncMock()
        msg = _make_message(guild_id=5000, channel_id=8080, content="hi")
        with (
            patch("cogs.ai_core.ai_cog.GUILD_ID_RP", 5000),
            patch("cogs.ai_core.ai_cog.CHANNEL_ID_RP_COMMAND", 6000),
            patch("cogs.ai_core.ai_cog.CHANNEL_ID_RP_OUTPUT", 7000),
        ):
            await cog._handle_guild_message(msg)
        cog.chat_manager.process_chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_mention_triggers_response(self):
        cog = _make_cog()
        cog.chat_manager.process_chat = AsyncMock()
        bot_user = _bot_user(cog.bot)
        msg = _make_message(content="hey bot", mentions=[bot_user])
        cog.bot.command_prefix = "!"
        with patch("cogs.ai_core.ai_cog.check_rate_limit", AsyncMock(return_value=True)):
            await cog._handle_guild_message(msg)
        cog.chat_manager.process_chat.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_reply_to_bot_triggers_response_resolved(self):
        cog = _make_cog()
        cog.chat_manager.process_chat = AsyncMock()
        bot_user = _bot_user(cog.bot)
        ref = MagicMock()
        ref.message_id = 333
        resolved = MagicMock(spec=discord.Message)
        resolved.author.id = bot_user.id
        ref.resolved = resolved
        msg = _make_message(content="thanks", reference=ref)
        cog.bot.command_prefix = "!"
        with patch("cogs.ai_core.ai_cog.check_rate_limit", AsyncMock(return_value=True)):
            await cog._handle_guild_message(msg)
        cog.chat_manager.process_chat.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_reply_fetches_message_when_not_resolved(self):
        cog = _make_cog()
        cog.chat_manager.process_chat = AsyncMock()
        bot_user = _bot_user(cog.bot)
        ref = MagicMock()
        ref.message_id = 333
        ref.resolved = None  # not a Message -> fetch
        fetched = MagicMock(spec=discord.Message)
        fetched.author.id = bot_user.id
        msg = _make_message(content="thanks", reference=ref)
        msg.channel.fetch_message = AsyncMock(return_value=fetched)
        cog.bot.command_prefix = "!"
        with patch("cogs.ai_core.ai_cog.check_rate_limit", AsyncMock(return_value=True)):
            await cog._handle_guild_message(msg)
        msg.channel.fetch_message.assert_awaited_once_with(333)
        cog.chat_manager.process_chat.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_reply_channel_not_fetchable(self):
        cog = _make_cog()
        cog.chat_manager.process_chat = AsyncMock()
        _bot_user(cog.bot)
        ref = MagicMock()
        ref.message_id = 333
        ref.resolved = None
        msg = _make_message(content="thanks", reference=ref)
        cog.bot.command_prefix = "!"
        # _as_fetchable_channel returns None -> ref_msg None -> not a reply
        with (
            patch("cogs.ai_core.ai_cog.check_rate_limit", AsyncMock(return_value=True)),
            patch.object(cog, "_as_fetchable_channel", return_value=None),
        ):
            await cog._handle_guild_message(msg)
        cog.chat_manager.process_chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_reply_fetch_raises_notfound(self):
        cog = _make_cog()
        cog.chat_manager.process_chat = AsyncMock()
        _bot_user(cog.bot)
        ref = MagicMock()
        ref.message_id = 333
        ref.resolved = None
        msg = _make_message(content="thanks", reference=ref)
        msg.channel.fetch_message = AsyncMock(side_effect=discord.NotFound(MagicMock(), "gone"))
        cog.bot.command_prefix = "!"
        with patch("cogs.ai_core.ai_cog.check_rate_limit", AsyncMock(return_value=True)):
            await cog._handle_guild_message(msg)
        cog.chat_manager.process_chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_response_when_not_mentioned(self):
        cog = _make_cog()
        cog.chat_manager.process_chat = AsyncMock()
        _bot_user(cog.bot)
        msg = _make_message(content="random chatter")
        cog.bot.command_prefix = "!"
        await cog._handle_guild_message(msg)
        cog.chat_manager.process_chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_mention_but_command_no_response(self):
        cog = _make_cog()
        cog.chat_manager.process_chat = AsyncMock()
        bot_user = _bot_user(cog.bot)
        # mention + a command (prefix after stripping mention) -> is_command True
        msg = _make_message(content="<@999> !chat hi", mentions=[bot_user])
        cog.bot.command_prefix = "!"
        await cog._handle_guild_message(msg)
        cog.chat_manager.process_chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_mention_response_rate_limited(self):
        cog = _make_cog()
        cog.chat_manager.process_chat = AsyncMock()
        bot_user = _bot_user(cog.bot)
        msg = _make_message(content="hey bot", mentions=[bot_user])
        cog.bot.command_prefix = "!"
        with patch("cogs.ai_core.ai_cog.check_rate_limit", AsyncMock(return_value=False)):
            await cog._handle_guild_message(msg)
        cog.chat_manager.process_chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_mention_response_chat_channel_none(self):
        cog = _make_cog()
        cog.chat_manager.process_chat = AsyncMock()
        bot_user = _bot_user(cog.bot)
        msg = _make_message(content="hey bot", mentions=[bot_user])
        cog.bot.command_prefix = "!"
        with (
            patch("cogs.ai_core.ai_cog.check_rate_limit", AsyncMock(return_value=True)),
            patch.object(cog, "_as_chat_channel", return_value=None),
        ):
            await cog._handle_guild_message(msg)
        cog.chat_manager.process_chat.assert_not_called()


# ----------------------------------------------------------------------------
# resend empty char_name continue (line 1282)
# ----------------------------------------------------------------------------


class TestResendEmptyCharName:
    @pytest.mark.asyncio
    async def test_whitespace_only_char_name_skipped(self):
        cog = _make_cog()
        ctx = _make_ctx()
        cog.chat_manager.get_chat_session = AsyncMock(return_value={"history": [1]})
        status_msg = MagicMock()
        status_msg.edit = AsyncMock()
        ctx.send = AsyncMock(return_value=status_msg)
        out = MagicMock(spec=discord.TextChannel)
        out.send = AsyncMock()
        cog.bot.get_channel = MagicMock(return_value=out)
        # "{{ }}" -> name matches [^}]+ (a space) but strips to empty -> continue
        content = "intro {{ }} body {{Bob}} hi"
        with (
            patch(
                "cogs.ai_core.ai_cog.get_last_model_message",
                AsyncMock(return_value={"parts": [content]}),
            ),
            patch("cogs.ai_core.ai_cog.send_as_webhook", AsyncMock()) as webhook,
            patch("cogs.ai_core.ai_cog.asyncio.sleep", AsyncMock()),
        ):
            await cog.resend_last_message.callback(cog, ctx, None)
        # only Bob produces a webhook send; the " " name is skipped
        assert webhook.await_count == 1
        status_msg.edit.assert_awaited_with(content="✅ ส่งข้อความใหม่สำเร็จ!")


# ----------------------------------------------------------------------------
# ImportError fallbacks in dashboard / audit / auto_summarize
# (lines 1499-1500, 1513-1514, 1610, 1642-1643)
# ----------------------------------------------------------------------------


def _import_blocker(*blocked):
    """Return an __import__ replacement that raises ImportError for blocked names."""
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name in blocked:
            raise ImportError(f"blocked: {name}")
        return real_import(name, *args, **kwargs)

    return fake_import


class TestDashboardImportFallbacks:
    @pytest.mark.asyncio
    async def test_cache_and_rag_import_error(self):
        cog = _make_cog()
        ctx = _make_ctx()
        cog.chat_manager.chats = {}
        cog.chat_manager.get_performance_stats = MagicMock(return_value={})
        blocker = _import_blocker(
            "cogs.ai_core.cache.ai_cache",
            "cogs.ai_core.memory.rag",
        )
        with patch("builtins.__import__", side_effect=blocker):
            await cog.dashboard_cmd.callback(cog, ctx)
        embed = ctx.send.call_args.kwargs["embed"]
        cache_field = next(f for f in embed.fields if f.name == "💾 Cache")
        assert "N/A" in cache_field.value
        rag_field = next(f for f in embed.fields if f.name == "🧠 RAG Memory")
        assert "N/A" in rag_field.value


class TestAuditExportImportFallback:
    @pytest.mark.asyncio
    async def test_audit_import_error(self):
        cog = _make_cog()
        ctx = _make_ctx()
        blocker = _import_blocker("utils.database")
        with patch("builtins.__import__", side_effect=blocker):
            await cog.audit_export_cmd.callback(cog, ctx, 7)
        assert "Audit logging not available" in ctx.send.call_args.args[0]


class TestAutoSummarizeImportFallback:
    @pytest.mark.asyncio
    async def test_estimate_tokens_import_error(self):
        cog = _make_cog()
        ctx = _make_ctx()
        history = [{"m": i} for i in range(4)]
        cog.chat_manager.chats = {ctx.channel.id: {"history": history}}
        cog.chat_manager.processing_locks = {}
        status_msg = MagicMock()
        status_msg.edit = AsyncMock()

        # ctx.send returns status_msg only for the second send (status line);
        # the first error sends won't happen here.
        ctx.send = AsyncMock(return_value=status_msg)

        # Block only the FIRST history_manager import (for estimate_tokens),
        # then allow it so the trim path proceeds.
        import builtins

        real_import = builtins.__import__
        state = {"blocked_once": False}

        def fake_import(name, *args, **kwargs):
            if name == "cogs.ai_core.memory.history_manager" and not state["blocked_once"]:
                state["blocked_once"] = True
                raise ImportError("blocked first import")
            return real_import(name, *args, **kwargs)

        hm = MagicMock()
        hm.estimate_tokens = MagicMock(return_value=10)
        hm.smart_trim_by_tokens = AsyncMock(return_value=history[:2])
        with (
            patch("builtins.__import__", side_effect=fake_import),
            patch("cogs.ai_core.memory.history_manager.history_manager", hm),
            patch("cogs.ai_core.storage.save_history", AsyncMock()),
        ):
            await cog.auto_summarize_cmd.callback(cog, ctx, 1000)
        # current_tokens fell back to len(history)*50 = 200; status line sent
        assert "200" in ctx.send.call_args_list[0].args[0]


# ----------------------------------------------------------------------------
# Remaining rate-limit return branches (lines 820, 822, 824, 861, 882, 938)
# ----------------------------------------------------------------------------


class TestRemainingRateLimitBranches:
    @pytest.mark.asyncio
    async def test_dm_global_limit_blocks(self):
        cog = _make_cog()
        cog.chat_manager.process_chat = AsyncMock()
        cog.chat_manager.parse_voice_command = MagicMock(return_value=(None, None))
        cog.bot.command_prefix = "!"
        msg = _make_message(is_dm=True, author_id=cog.OWNER_ID, content="hi there")
        # gemini_api True, gemini_global False -> line 820
        rl = AsyncMock(side_effect=[True, False])
        with patch("cogs.ai_core.ai_cog.check_rate_limit", rl):
            await cog._handle_dm_message(msg)
        cog.chat_manager.process_chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_dm_ai_user_limit_blocks(self):
        cog = _make_cog()
        cog.chat_manager.process_chat = AsyncMock()
        cog.chat_manager.parse_voice_command = MagicMock(return_value=(None, None))
        cog.bot.command_prefix = "!"
        msg = _make_message(is_dm=True, author_id=cog.OWNER_ID, content="hi there")
        # api True, global True, ai_user False -> line 822
        rl = AsyncMock(side_effect=[True, True, False])
        with patch("cogs.ai_core.ai_cog.check_rate_limit", rl):
            await cog._handle_dm_message(msg)
        cog.chat_manager.process_chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_dm_ai_guild_limit_blocks(self):
        cog = _make_cog()
        cog.chat_manager.process_chat = AsyncMock()
        cog.chat_manager.parse_voice_command = MagicMock(return_value=(None, None))
        cog.bot.command_prefix = "!"
        msg = _make_message(is_dm=True, author_id=cog.OWNER_ID, content="hi there")
        # api, global, ai_user True; ai_guild False -> line 824
        rl = AsyncMock(side_effect=[True, True, True, False])
        with patch("cogs.ai_core.ai_cog.check_rate_limit", rl):
            await cog._handle_dm_message(msg)
        cog.chat_manager.process_chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_rp_command_global_limit_blocks(self):
        cog = _make_cog()
        cog.chat_manager.process_chat = AsyncMock()
        msg = _make_message(guild_id=5000, channel_id=6000, content="story")
        # gemini_api True, gemini_global False -> line 861
        rl = AsyncMock(side_effect=[True, False])
        with (
            patch("cogs.ai_core.ai_cog.GUILD_ID_RP", 5000),
            patch("cogs.ai_core.ai_cog.CHANNEL_ID_RP_COMMAND", 6000),
            patch("cogs.ai_core.ai_cog.CHANNEL_ID_RP_OUTPUT", 7000),
            patch("cogs.ai_core.ai_cog.check_rate_limit", rl),
        ):
            await cog._handle_guild_message(msg)
        cog.chat_manager.process_chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_rp_output_global_limit_blocks(self):
        cog = _make_cog()
        cog.chat_manager.process_chat = AsyncMock()
        msg = _make_message(guild_id=5000, channel_id=7000, content="reply")
        # gemini_api True, gemini_global False -> line 882
        rl = AsyncMock(side_effect=[True, False])
        with (
            patch("cogs.ai_core.ai_cog.GUILD_ID_RP", 5000),
            patch("cogs.ai_core.ai_cog.CHANNEL_ID_RP_COMMAND", 6000),
            patch("cogs.ai_core.ai_cog.CHANNEL_ID_RP_OUTPUT", 7000),
            patch("cogs.ai_core.ai_cog.check_rate_limit", rl),
        ):
            await cog._handle_guild_message(msg)
        cog.chat_manager.process_chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_mention_global_limit_blocks(self):
        cog = _make_cog()
        cog.chat_manager.process_chat = AsyncMock()
        bot_user = _bot_user(cog.bot)
        msg = _make_message(content="hey bot", mentions=[bot_user])
        cog.bot.command_prefix = "!"
        # gemini_api True, gemini_global False -> line 938
        rl = AsyncMock(side_effect=[True, False])
        with patch("cogs.ai_core.ai_cog.check_rate_limit", rl):
            await cog._handle_guild_message(msg)
        cog.chat_manager.process_chat.assert_not_called()


# ----------------------------------------------------------------------------
# dashboard rate_limiter / circuit_breaker import-or-attr fallbacks
# (lines 1549-1550, 1563-1564)
# ----------------------------------------------------------------------------


class TestDashboardRateLimiterCircuitFallback:
    @pytest.mark.asyncio
    async def test_rate_limiter_and_circuit_import_error(self):
        cog = _make_cog()
        ctx = _make_ctx()
        cog.chat_manager.chats = {}
        cog.chat_manager.get_performance_stats = MagicMock(return_value={})
        cache_stats = MagicMock()
        cache_stats.total_entries = 0
        cache_stats.hit_rate = 0.0
        cache_stats.memory_estimate_kb = 0.0
        blocker = _import_blocker(
            "utils.reliability.rate_limiter",
            "utils.reliability.circuit_breaker",
        )
        with (
            patch("cogs.ai_core.cache.ai_cache.ai_cache") as ai_cache,
            patch("cogs.ai_core.memory.rag.rag_system") as rag,
            patch("builtins.__import__", side_effect=blocker),
        ):
            ai_cache.get_stats.return_value = cache_stats
            rag.get_stats.return_value = {
                "faiss_available": False,
                "index_size": 0,
                "memories_cached": 0,
            }
            await cog.dashboard_cmd.callback(cog, ctx)
        # Rate Limiter + Circuit Breaker fields are skipped on import failure
        ctx.send.assert_awaited_once()
        embed = ctx.send.call_args.kwargs["embed"]
        names = [f.name for f in embed.fields]
        assert "🚦 Rate Limiter" not in names
        assert "⚡ Circuit Breaker" not in names
