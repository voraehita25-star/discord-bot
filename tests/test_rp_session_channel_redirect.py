# pylint: disable=protected-access
"""Regression: the delete/edit mirrors never applied the RP channel redirect.

On the RP guild the COMMAND channel is input-only — ``!chat`` is typed there and
``process_chat`` redirects the reply to OUTPUT, keying the session AND every
stored row under the OUTPUT id while the user's own message stays in COMMAND.

Five commands already open-coded that redirect. The three raw mirror handlers did
not: ``on_raw_message_delete``, ``on_raw_bulk_message_delete`` and
``on_raw_message_edit`` all passed ``payload.channel_id`` straight through, so
deleting or editing a ``!chat`` message searched COMMAND's history and found
nothing — the row was under OUTPUT. The "memory mirrors what is actually
visible" guarantee was absent on the one guild that uses the redirect.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

RP_GUILD = 700100
RP_COMMAND = 700200
RP_OUTPUT = 700300


def _make_cog():
    from cogs.ai_core.ai_cog import AI

    bot = MagicMock()
    with (
        patch("cogs.ai_core.ai_cog.ChatManager") as mock_cm,
        patch("cogs.ai_core.ai_cog.rate_limiter"),
    ):
        cm = MagicMock()
        cm.cli_mode = False
        cm.remove_message_from_history = AsyncMock(return_value=True)
        cm.edit_message_in_history = AsyncMock(return_value=True)
        mock_cm.return_value = cm
        cog = AI(bot)
    return cog


def _rp_env():
    return (
        patch("cogs.ai_core.ai_cog.GUILD_ID_RP", RP_GUILD),
        patch("cogs.ai_core.ai_cog.CHANNEL_ID_RP_COMMAND", RP_COMMAND),
        patch("cogs.ai_core.ai_cog.CHANNEL_ID_RP_OUTPUT", RP_OUTPUT),
    )


class TestSessionChannelId:
    def test_rp_command_redirects_to_output(self):
        cog = _make_cog()
        with _rp_env()[0], _rp_env()[1], _rp_env()[2]:
            assert cog._session_channel_id(RP_GUILD, RP_COMMAND) == RP_OUTPUT

    def test_rp_output_is_already_the_session_channel(self):
        cog = _make_cog()
        with _rp_env()[0], _rp_env()[1], _rp_env()[2]:
            assert cog._session_channel_id(RP_GUILD, RP_OUTPUT) == RP_OUTPUT

    def test_other_rp_channels_are_untouched(self):
        cog = _make_cog()
        with _rp_env()[0], _rp_env()[1], _rp_env()[2]:
            assert cog._session_channel_id(RP_GUILD, 999) == 999

    def test_other_guilds_are_untouched(self):
        cog = _make_cog()
        with _rp_env()[0], _rp_env()[1], _rp_env()[2]:
            assert cog._session_channel_id(555, RP_COMMAND) == RP_COMMAND

    def test_a_dm_is_untouched(self):
        cog = _make_cog()
        with _rp_env()[0], _rp_env()[1], _rp_env()[2]:
            assert cog._session_channel_id(None, RP_COMMAND) == RP_COMMAND


class TestMirrorsUseTheSessionChannel:
    @pytest.mark.asyncio
    async def test_delete_in_the_command_channel_reaches_the_output_row(self):
        cog = _make_cog()
        payload = MagicMock()
        payload.channel_id = RP_COMMAND
        payload.guild_id = RP_GUILD
        payload.message_id = 4242
        payload.cached_message = MagicMock(content="ลบอันนี้")

        with _rp_env()[0], _rp_env()[1], _rp_env()[2]:
            await cog.on_raw_message_delete(payload)

        called_channel, called_msg, called_text = (
            cog.chat_manager.remove_message_from_history.await_args.args
        )
        assert called_channel == RP_OUTPUT, (
            "the row is stored under OUTPUT; searching COMMAND finds nothing, so "
            "the deleted message keeps feeding future prompts"
        )
        assert called_msg == 4242
        assert called_text == "ลบอันนี้"

    @pytest.mark.asyncio
    async def test_bulk_delete_in_the_command_channel_too(self):
        cog = _make_cog()
        payload = MagicMock()
        payload.channel_id = RP_COMMAND
        payload.guild_id = RP_GUILD
        payload.message_ids = {11, 12}
        payload.cached_messages = []

        with _rp_env()[0], _rp_env()[1], _rp_env()[2]:
            await cog.on_raw_bulk_message_delete(payload)

        channels = {
            call.args[0] for call in cog.chat_manager.remove_message_from_history.await_args_list
        }
        assert channels == {RP_OUTPUT}

    @pytest.mark.asyncio
    async def test_edit_in_the_command_channel_too(self):
        cog = _make_cog()
        cog.bot.user = MagicMock(id=1)
        payload = MagicMock()
        payload.channel_id = RP_COMMAND
        payload.guild_id = RP_GUILD
        payload.message_id = 4242
        payload.data = {"content": "แก้แล้ว", "author": {"id": "42"}}

        with _rp_env()[0], _rp_env()[1], _rp_env()[2]:
            await cog.on_raw_message_edit(payload)

        called_channel, called_msg, called_text = (
            cog.chat_manager.edit_message_in_history.await_args.args
        )
        assert called_channel == RP_OUTPUT
        assert called_msg == 4242
        assert called_text == "แก้แล้ว"

    @pytest.mark.asyncio
    async def test_an_ordinary_guild_is_unaffected(self):
        """Every non-RP channel must keep passing its own id through."""
        cog = _make_cog()
        payload = MagicMock()
        payload.channel_id = 8888
        payload.guild_id = 555
        payload.message_id = 1
        payload.cached_message = None

        with _rp_env()[0], _rp_env()[1], _rp_env()[2]:
            await cog.on_raw_message_delete(payload)

        assert cog.chat_manager.remove_message_from_history.await_args.args[0] == 8888
