# pylint: disable=protected-access
"""Regression tests for the ``GUILD_ID_RESTRICTED`` single-channel rule.

``env.example`` documents the pair as "Restricted Guild - AI only works in
specific channel". ``_handle_webhook_message`` enforced it for proxied
Tupperbox/PluralKit traffic, but the two paths people actually use — an
@mention/reply, and ``!chat``/``!ask`` — did not, so the restriction only ever
applied to the one path nobody uses.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

RESTRICTED_GUILD = 4242424242
ALLOWED_CHANNEL = 999000111


def _make_cog():
    from cogs.ai_core.ai_cog import AI

    bot = MagicMock()
    with (
        patch("cogs.ai_core.ai_cog.ChatManager") as mock_cm,
        patch("cogs.ai_core.ai_cog.rate_limiter"),
    ):
        cm = MagicMock()
        cm.cli_mode = False
        cm.process_chat = AsyncMock()
        mock_cm.return_value = cm
        cog = AI(bot)
    return cog


def _make_message(*, guild_id: int, channel_id: int, bot_user):
    msg = MagicMock()
    msg.content = "hey"
    msg.webhook_id = None
    msg.id = 777
    msg.attachments = []
    msg.mentions = [bot_user]
    msg.reference = None
    msg.author = MagicMock(id=42, bot=False)
    msg.guild = MagicMock(id=guild_id)
    msg.channel = MagicMock(spec=discord.TextChannel)
    msg.channel.id = channel_id
    return msg


class TestRestrictedGuildPredicate:
    def test_inert_when_unconfigured(self):
        cog = _make_cog()
        with patch("cogs.ai_core.ai_cog.GUILD_ID_RESTRICTED", 0):
            assert cog._restricted_guild_blocks(123, 456) is False
            assert cog._restricted_guild_blocks(None, 456) is False

    def test_other_guilds_untouched(self):
        cog = _make_cog()
        with (
            patch("cogs.ai_core.ai_cog.GUILD_ID_RESTRICTED", RESTRICTED_GUILD),
            patch("cogs.ai_core.ai_cog.CHANNEL_ID_ALLOWED", ALLOWED_CHANNEL),
        ):
            assert cog._restricted_guild_blocks(RESTRICTED_GUILD + 1, 1) is False

    def test_allowed_channel_passes_other_channels_blocked(self):
        cog = _make_cog()
        with (
            patch("cogs.ai_core.ai_cog.GUILD_ID_RESTRICTED", RESTRICTED_GUILD),
            patch("cogs.ai_core.ai_cog.CHANNEL_ID_ALLOWED", ALLOWED_CHANNEL),
        ):
            assert cog._restricted_guild_blocks(RESTRICTED_GUILD, ALLOWED_CHANNEL) is False
            assert cog._restricted_guild_blocks(RESTRICTED_GUILD, ALLOWED_CHANNEL + 1) is True

    def test_misconfiguration_blocks_and_warns_once(self, caplog):
        """Guild set, channel unset: fail closed (what the webhook path already
        does), but say so — a guild that silently went mute has no other clue."""
        from cogs.ai_core.ai_cog import AI

        cog = _make_cog()
        AI._restricted_misconfig_logged = False
        try:
            with (
                patch("cogs.ai_core.ai_cog.GUILD_ID_RESTRICTED", RESTRICTED_GUILD),
                patch("cogs.ai_core.ai_cog.CHANNEL_ID_ALLOWED", 0),
            ):
                with caplog.at_level("WARNING", logger="cogs.ai_core.ai_cog"):
                    assert cog._restricted_guild_blocks(RESTRICTED_GUILD, 5) is True
                    assert cog._restricted_guild_blocks(RESTRICTED_GUILD, 6) is True
            warnings = [r for r in caplog.records if "CHANNEL_ID_ALLOWED" in r.getMessage()]
            assert len(warnings) == 1
        finally:
            AI._restricted_misconfig_logged = False


class TestMentionPathHonoursTheGate:
    @pytest.mark.asyncio
    async def test_mention_in_a_forbidden_channel_is_ignored(self):
        cog = _make_cog()
        bot_user = MagicMock(id=1)
        cog.bot.user = bot_user
        msg = _make_message(
            guild_id=RESTRICTED_GUILD, channel_id=ALLOWED_CHANNEL + 1, bot_user=bot_user
        )
        with (
            patch("cogs.ai_core.ai_cog.GUILD_ID_RESTRICTED", RESTRICTED_GUILD),
            patch("cogs.ai_core.ai_cog.CHANNEL_ID_ALLOWED", ALLOWED_CHANNEL),
            patch("cogs.ai_core.ai_cog.check_rate_limit", AsyncMock(return_value=True)),
        ):
            await cog._handle_guild_message(msg)
        cog.chat_manager.process_chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_mention_in_the_allowed_channel_still_answers(self):
        cog = _make_cog()
        bot_user = MagicMock(id=1)
        cog.bot.user = bot_user
        msg = _make_message(
            guild_id=RESTRICTED_GUILD, channel_id=ALLOWED_CHANNEL, bot_user=bot_user
        )
        cog._check_custom_channel_limit = AsyncMock(return_value=True)
        with (
            patch("cogs.ai_core.ai_cog.GUILD_ID_RESTRICTED", RESTRICTED_GUILD),
            patch("cogs.ai_core.ai_cog.CHANNEL_ID_ALLOWED", ALLOWED_CHANNEL),
            patch("cogs.ai_core.ai_cog.check_rate_limit", AsyncMock(return_value=True)),
        ):
            await cog._handle_guild_message(msg)
        cog.chat_manager.process_chat.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_unrelated_guild_is_unaffected(self):
        cog = _make_cog()
        bot_user = MagicMock(id=1)
        cog.bot.user = bot_user
        msg = _make_message(guild_id=555, channel_id=777, bot_user=bot_user)
        cog._check_custom_channel_limit = AsyncMock(return_value=True)
        with (
            patch("cogs.ai_core.ai_cog.GUILD_ID_RESTRICTED", RESTRICTED_GUILD),
            patch("cogs.ai_core.ai_cog.CHANNEL_ID_ALLOWED", ALLOWED_CHANNEL),
            patch("cogs.ai_core.ai_cog.check_rate_limit", AsyncMock(return_value=True)),
        ):
            await cog._handle_guild_message(msg)
        cog.chat_manager.process_chat.assert_awaited_once()


class TestChatCommandHonoursTheGate:
    @staticmethod
    def _ctx(guild_id: int, channel_id: int):
        ctx = MagicMock()
        ctx.guild = MagicMock(id=guild_id)
        ctx.channel = MagicMock(spec=discord.TextChannel)
        ctx.channel.id = channel_id
        ctx.interaction = None
        ctx.send = AsyncMock()
        ctx.message = MagicMock(attachments=[], id=99, reference=None)
        ctx.author = MagicMock(id=42)
        return ctx

    @pytest.mark.asyncio
    async def test_command_in_a_forbidden_channel_is_refused_with_a_reason(self):
        cog = _make_cog()
        ctx = self._ctx(RESTRICTED_GUILD, ALLOWED_CHANNEL + 1)
        cog._check_custom_channel_limit = AsyncMock(return_value=True)
        with (
            patch("cogs.ai_core.ai_cog.GUILD_ID_RESTRICTED", RESTRICTED_GUILD),
            patch("cogs.ai_core.ai_cog.CHANNEL_ID_ALLOWED", ALLOWED_CHANNEL),
            patch("cogs.ai_core.ai_cog.check_rate_limit", AsyncMock(return_value=True)),
        ):
            await cog.chat_command.callback(cog, ctx, message="hi")
        cog.chat_manager.process_chat.assert_not_called()
        # The user typed a command — refusing silently is what makes a bot look
        # broken; the reply names the channel they should use.
        ctx.send.assert_awaited()
        assert str(ALLOWED_CHANNEL) in ctx.send.call_args.args[0]

    @pytest.mark.asyncio
    async def test_command_in_the_allowed_channel_runs(self):
        cog = _make_cog()
        ctx = self._ctx(RESTRICTED_GUILD, ALLOWED_CHANNEL)
        cog._check_custom_channel_limit = AsyncMock(return_value=True)
        with (
            patch("cogs.ai_core.ai_cog.GUILD_ID_RESTRICTED", RESTRICTED_GUILD),
            patch("cogs.ai_core.ai_cog.CHANNEL_ID_ALLOWED", ALLOWED_CHANNEL),
            patch("cogs.ai_core.ai_cog.check_rate_limit", AsyncMock(return_value=True)),
        ):
            await cog.chat_command.callback(cog, ctx, message="hi")
        cog.chat_manager.process_chat.assert_awaited_once()
