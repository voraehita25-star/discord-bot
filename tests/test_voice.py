"""
Tests for cogs/ai_core/voice.py

Comprehensive tests for voice channel management.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest


class TestJoinVoiceChannel:
    """Tests for join_voice_channel function."""

    @pytest.mark.asyncio
    async def test_join_channel_not_found(self):
        """Test join when channel not found."""
        from cogs.ai_core.voice import join_voice_channel

        mock_bot = MagicMock()
        mock_bot.get_channel.return_value = None

        success, message = await join_voice_channel(mock_bot, 12345)

        assert success is False
        assert "ไม่พบ" in message

    @pytest.mark.asyncio
    async def test_join_not_voice_channel(self):
        """Test join when channel is not a voice channel."""
        from cogs.ai_core.voice import join_voice_channel

        mock_channel = MagicMock()
        mock_channel.name = "text-channel"
        # Remove connect method to simulate non-voice channel
        del mock_channel.connect

        mock_bot = MagicMock()
        mock_bot.get_channel.return_value = mock_channel

        success, message = await join_voice_channel(mock_bot, 12345)

        assert success is False
        assert "ไม่ใช่" in message

    @pytest.mark.asyncio
    async def test_join_already_in_channel(self):
        """Test join when already in the same channel."""
        from cogs.ai_core.voice import join_voice_channel

        mock_channel = MagicMock()
        mock_channel.name = "voice-channel"
        mock_channel.id = 12345
        mock_channel.connect = AsyncMock()

        mock_voice_client = MagicMock()
        mock_voice_client.channel.id = 12345

        mock_guild = MagicMock()
        mock_guild.voice_client = mock_voice_client
        mock_channel.guild = mock_guild

        mock_bot = MagicMock()
        mock_bot.get_channel.return_value = mock_channel

        success, message = await join_voice_channel(mock_bot, 12345)

        assert success is True
        assert "อยู่" in message and "แล้ว" in message

    @pytest.mark.asyncio
    async def test_join_move_to_different_channel(self):
        """Test move to different channel when already in one."""
        from cogs.ai_core.voice import join_voice_channel

        mock_channel = MagicMock()
        mock_channel.name = "new-voice-channel"
        mock_channel.id = 12345
        mock_channel.connect = AsyncMock()

        mock_voice_client = MagicMock()
        mock_voice_client.channel.id = 99999  # Different channel
        mock_voice_client.move_to = AsyncMock()

        mock_guild = MagicMock()
        mock_guild.voice_client = mock_voice_client
        mock_channel.guild = mock_guild

        mock_bot = MagicMock()
        mock_bot.get_channel.return_value = mock_channel

        success, message = await join_voice_channel(mock_bot, 12345)

        assert success is True
        assert "ย้าย" in message
        mock_voice_client.move_to.assert_called_once_with(mock_channel)

    @pytest.mark.asyncio
    async def test_join_new_channel(self):
        """Test join new channel when not in any."""
        from cogs.ai_core.voice import join_voice_channel

        mock_channel = MagicMock()
        mock_channel.name = "voice-channel"
        mock_channel.id = 12345
        mock_channel.connect = AsyncMock()

        mock_guild = MagicMock()
        mock_guild.voice_client = None  # Not in any channel
        mock_channel.guild = mock_guild

        mock_bot = MagicMock()
        mock_bot.get_channel.return_value = mock_channel

        success, message = await join_voice_channel(mock_bot, 12345)

        assert success is True
        assert "เข้าไปรอ" in message
        mock_channel.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_join_exception(self):
        """Test join handles exception."""
        from cogs.ai_core.voice import join_voice_channel

        mock_channel = MagicMock()
        mock_channel.name = "voice-channel"
        mock_channel.connect = AsyncMock(side_effect=Exception("Connection error"))

        mock_guild = MagicMock()
        mock_guild.voice_client = None
        mock_channel.guild = mock_guild

        mock_bot = MagicMock()
        mock_bot.get_channel.return_value = mock_channel

        success, message = await join_voice_channel(mock_bot, 12345)

        assert success is False
        assert "ไม่สามารถ" in message


class TestLeaveVoiceChannel:
    """Tests for leave_voice_channel function."""

    @pytest.mark.asyncio
    async def test_leave_guild_not_found(self):
        """Test leave when guild not found."""
        from cogs.ai_core.voice import leave_voice_channel

        mock_bot = MagicMock()
        mock_bot.get_guild.return_value = None

        success, message = await leave_voice_channel(mock_bot, 12345)

        assert success is False
        assert "ไม่ได้อยู่" in message

    @pytest.mark.asyncio
    async def test_leave_not_in_voice(self):
        """Test leave when not in voice channel."""
        from cogs.ai_core.voice import leave_voice_channel

        mock_guild = MagicMock()
        mock_guild.voice_client = None

        mock_bot = MagicMock()
        mock_bot.get_guild.return_value = mock_guild

        success, message = await leave_voice_channel(mock_bot, 12345)

        assert success is False
        assert "ไม่ได้อยู่" in message

    @pytest.mark.asyncio
    async def test_leave_success(self):
        """Test successful leave."""
        from cogs.ai_core.voice import leave_voice_channel

        mock_voice_client = MagicMock()
        mock_voice_client.channel.name = "voice-channel"
        mock_voice_client.disconnect = AsyncMock()

        mock_guild = MagicMock()
        mock_guild.voice_client = mock_voice_client

        mock_bot = MagicMock()
        mock_bot.get_guild.return_value = mock_guild

        success, message = await leave_voice_channel(mock_bot, 12345)

        assert success is True
        assert "ออกจาก" in message
        mock_voice_client.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_leave_exception(self):
        """Test leave handles exception."""
        from cogs.ai_core.voice import leave_voice_channel

        mock_voice_client = MagicMock()
        mock_voice_client.channel.name = "voice-channel"
        mock_voice_client.disconnect = AsyncMock(side_effect=Exception("Disconnect error"))

        mock_guild = MagicMock()
        mock_guild.voice_client = mock_voice_client

        mock_bot = MagicMock()
        mock_bot.get_guild.return_value = mock_guild

        success, message = await leave_voice_channel(mock_bot, 12345)

        assert success is False
        assert "ไม่สามารถ" in message


class TestParseVoiceCommand:
    """Tests for parse_voice_command function."""

    def test_parse_join_thai(self):
        """Test parse join command in Thai."""
        from cogs.ai_core.voice import parse_voice_command

        action, channel_id = parse_voice_command("เข้ามารอใน 123456789012345678")

        assert action == "join"
        assert channel_id == 123456789012345678

    def test_parse_join_english(self):
        """Test parse join command in English."""
        from cogs.ai_core.voice import parse_voice_command

        action, channel_id = parse_voice_command("join vc 123456789012345678")

        assert action == "join"
        assert channel_id == 123456789012345678

    def test_parse_join_no_channel_id(self):
        """Test parse join without channel ID."""
        from cogs.ai_core.voice import parse_voice_command

        action, channel_id = parse_voice_command("join voice")

        assert action == "join"
        assert channel_id is None

    def test_parse_leave_thai(self):
        """Test parse leave command in Thai."""
        from cogs.ai_core.voice import parse_voice_command

        action, channel_id = parse_voice_command("ออกจาก vc")

        assert action == "leave"
        assert channel_id is None

    def test_parse_leave_english(self):
        """Test parse leave command in English."""
        from cogs.ai_core.voice import parse_voice_command

        action, channel_id = parse_voice_command("leave vc")

        assert action == "leave"
        assert channel_id is None

    def test_parse_disconnect(self):
        """Test parse disconnect command."""
        from cogs.ai_core.voice import parse_voice_command

        action, channel_id = parse_voice_command("disconnect")

        assert action == "leave"
        assert channel_id is None

        # "disconnect from vc" still triggers leave (whole word present).
        action, _ = parse_voice_command("please disconnect from the vc")
        assert action == "leave"

    def test_parse_disconnect_word_boundary(self):
        """A narrative mention of disconnecting must NOT force-leave every VC.

        Regression: "disconnect" was matched as a raw substring, so an owner
        DM like "the bot keeps disconnecting, why?" silently disconnected all
        voice clients instead of being answered by the AI.
        """
        from cogs.ai_core.voice import parse_voice_command

        for phrase in (
            "the bot keeps disconnecting from vc, why?",
            "he disconnected from the call earlier",
            "why did it get disconnected",
        ):
            action, _ = parse_voice_command(phrase)
            assert action is None, f"substring false-positive on: {phrase!r}"

    def test_parse_no_command(self):
        """Test parse with no voice command."""
        from cogs.ai_core.voice import parse_voice_command

        action, channel_id = parse_voice_command("hello how are you")

        assert action is None
        assert channel_id is None

    def test_parse_join_variants(self):
        """Join patterns come in two tiers.

        A phrase that names the voice channel stands on its own. A phrase that
        is also ordinary Thai ("เข้าห้อง" = enter the room, "เข้ามาใน" = come
        into) needs the channel id as confirmation — bare, those turned a DM
        like "เดี๋ยวเข้าห้องน้ำก่อนนะ" into a join attempt. See
        TestVoiceCommandDoesNotFireOnOrdinaryThai.
        """
        from cogs.ai_core.voice import parse_voice_command

        explicit = ["join vc", "join voice", "เข้า vc", "เข้าห้องเสียง"]
        for pattern in explicit:
            action, _ = parse_voice_command(pattern)
            assert action == "join", f"Failed for pattern: {pattern}"

        ambiguous = ["เข้าไปรอใน", "มารอใน", "เข้าห้อง", "เข้ามาใน"]
        for pattern in ambiguous:
            assert parse_voice_command(pattern) == (None, None), (
                f"{pattern!r} is ordinary Thai and must not fire on its own"
            )
            action, channel_id = parse_voice_command(f"{pattern} 123456789012345678")
            assert (action, channel_id) == ("join", 123456789012345678), (
                f"Failed for pattern with id: {pattern}"
            )


class TestGetVoiceStatus:
    """Tests for get_voice_status function."""

    def test_no_voice_connections(self):
        """Test when no voice connections."""
        from cogs.ai_core.voice import get_voice_status

        mock_bot = MagicMock()
        mock_bot.voice_clients = []

        result = get_voice_status(mock_bot)

        assert "ไม่ได้เชื่อมต่อ" in result

    def test_with_voice_connection_idle(self):
        """Test with idle voice connection."""
        from cogs.ai_core.voice import get_voice_status

        mock_member = MagicMock()
        mock_member.bot = False
        mock_member.display_name = "TestUser"

        mock_channel = MagicMock()
        mock_channel.name = "test-voice"
        mock_channel.members = [mock_member]

        mock_guild = MagicMock()
        mock_guild.name = "TestServer"
        mock_guild.id = 12345

        mock_vc = MagicMock()
        mock_vc.is_connected.return_value = True
        mock_vc.is_playing.return_value = False
        mock_vc.is_paused.return_value = False
        mock_vc.channel = mock_channel
        mock_vc.guild = mock_guild

        mock_bot = MagicMock()
        mock_bot.voice_clients = [mock_vc]
        mock_bot.get_cog.return_value = None

        result = get_voice_status(mock_bot)

        assert "กำลังเชื่อมต่อ" in result
        assert "TestServer" in result
        assert "test-voice" in result
        assert "ว่าง" in result

    def test_with_voice_connection_playing(self):
        """Test with playing voice connection."""
        from cogs.ai_core.voice import get_voice_status

        mock_channel = MagicMock()
        mock_channel.name = "test-voice"
        mock_channel.members = []

        mock_guild = MagicMock()
        mock_guild.name = "TestServer"
        mock_guild.id = 12345

        mock_vc = MagicMock()
        mock_vc.is_connected.return_value = True
        mock_vc.is_playing.return_value = True
        mock_vc.is_paused.return_value = False
        mock_vc.channel = mock_channel
        mock_vc.guild = mock_guild

        mock_music_cog = MagicMock()
        # current_track lives on the per-guild MusicGuildState returned by
        # _gs(guild_id), not as a dict on the cog itself.
        mock_music_cog._gs.return_value.current_track = {"title": "Test Song"}

        mock_bot = MagicMock()
        mock_bot.voice_clients = [mock_vc]
        mock_bot.get_cog.return_value = mock_music_cog

        result = get_voice_status(mock_bot)

        assert "กำลังเล่นเพลง" in result
        assert "Test Song" in result

    def test_with_voice_connection_paused(self):
        """Test with paused voice connection."""
        from cogs.ai_core.voice import get_voice_status

        mock_channel = MagicMock()
        mock_channel.name = "test-voice"
        mock_channel.members = []

        mock_guild = MagicMock()
        mock_guild.name = "TestServer"
        mock_guild.id = 12345

        mock_vc = MagicMock()
        mock_vc.is_connected.return_value = True
        mock_vc.is_playing.return_value = False
        mock_vc.is_paused.return_value = True
        mock_vc.channel = mock_channel
        mock_vc.guild = mock_guild

        mock_music_cog = MagicMock()
        mock_music_cog._gs.return_value.current_track = {"title": "Paused Song"}

        mock_bot = MagicMock()
        mock_bot.voice_clients = [mock_vc]
        mock_bot.get_cog.return_value = mock_music_cog

        result = get_voice_status(mock_bot)

        assert "หยุดชั่วคราว" in result

    def test_with_many_members(self):
        """Test with many members in channel."""
        from cogs.ai_core.voice import get_voice_status

        mock_members = []
        for i in range(10):
            m = MagicMock()
            m.bot = False
            m.display_name = f"User{i}"
            mock_members.append(m)

        mock_channel = MagicMock()
        mock_channel.name = "test-voice"
        mock_channel.members = mock_members

        mock_guild = MagicMock()
        mock_guild.name = "TestServer"
        mock_guild.id = 12345

        mock_vc = MagicMock()
        mock_vc.is_connected.return_value = True
        mock_vc.is_playing.return_value = False
        mock_vc.is_paused.return_value = False
        mock_vc.channel = mock_channel
        mock_vc.guild = mock_guild

        mock_bot = MagicMock()
        mock_bot.voice_clients = [mock_vc]
        mock_bot.get_cog.return_value = None

        result = get_voice_status(mock_bot)

        # Should show "และอีก X คน" for members > 5
        assert "และอีก" in result


class TestPatternChannelId:
    """Tests for PATTERN_CHANNEL_ID regex."""

    def test_pattern_exists(self):
        """Test pattern exists."""
        from cogs.ai_core.voice import PATTERN_CHANNEL_ID

        assert PATTERN_CHANNEL_ID is not None

    def test_pattern_matches_valid_id(self):
        """Test pattern matches valid Discord ID."""
        from cogs.ai_core.voice import PATTERN_CHANNEL_ID

        text = "join vc 123456789012345678"
        match = PATTERN_CHANNEL_ID.search(text)

        assert match is not None
        assert match.group(1) == "123456789012345678"

    def test_pattern_no_match_short_id(self):
        """Test pattern doesn't match too short ID."""
        from cogs.ai_core.voice import PATTERN_CHANNEL_ID

        text = "join vc 12345"
        match = PATTERN_CHANNEL_ID.search(text)

        assert match is None


class TestModuleImports:
    """Tests for module imports."""

    def test_import_functions(self):
        """Test functions can be imported."""
        from cogs.ai_core.voice import (
            PATTERN_CHANNEL_ID,
            get_voice_status,
            join_voice_channel,
            leave_voice_channel,
            parse_voice_command,
        )

        assert join_voice_channel is not None
        assert leave_voice_channel is not None
        assert parse_voice_command is not None
        assert get_voice_status is not None
        assert PATTERN_CHANNEL_ID is not None


class TestVoiceCommandDoesNotFireOnOrdinaryThai:
    """Regression: the join/leave phrase lists were bare substrings, and several
    of them are ordinary Thai. In the owner's DM — the only path that consults
    this parser — "เดี๋ยวเข้าห้องน้ำก่อนนะ" became a voice-join attempt and
    "ออกจากห้องน้ำแล้ว" force-disconnected every voice client the bot held,
    instead of either being answered as chat.

    This is the same narrative-mention hazard the word-boundary guard on the
    English "disconnect" already covers; the Thai side was never given it.
    """

    @staticmethod
    def _parse(text: str):
        from cogs.ai_core.voice import parse_voice_command

        return parse_voice_command(text)

    @pytest.mark.parametrize(
        "text",
        [
            "เดี๋ยวเข้าห้องน้ำก่อนนะ",
            "เขาเข้าห้องเรียนไปแล้ว",
            "เธอเข้ามาในห้องอย่างเงียบๆ",
            "มารอในสวนนะ",
        ],
    )
    def test_narration_is_not_a_join(self, text):
        assert self._parse(text) == (None, None)

    @pytest.mark.parametrize(
        "text",
        [
            "ออกจากห้องน้ำแล้ว",
            "พวกเราออกจากห้องประชุมกัน",
        ],
    )
    def test_narration_does_not_force_a_disconnect(self, text):
        """Leave is destructive and carries no id, so there is no second signal
        to confirm intent — the phrase itself has to be unambiguous."""
        assert self._parse(text) == (None, None)

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("join vc", ("join", None)),
            ("join voice", ("join", None)),
            ("เข้า vc", ("join", None)),
            ("เข้าห้องเสียง", ("join", None)),
            ("join vc 123456789012345678", ("join", 123456789012345678)),
            ("ออกจาก vc", ("leave", None)),
            ("leave vc", ("leave", None)),
            ("ออกจากห้องเสียง", ("leave", None)),
            ("disconnect", ("leave", None)),
        ],
    )
    def test_explicit_commands_still_work(self, text, expected):
        assert self._parse(text) == expected

    @pytest.mark.parametrize(
        "text",
        [
            "เข้ามารอใน 123456789012345678",
            "เข้าไปรอใน 123456789012345678",
            "เข้าห้อง 123456789012345678",
            "เข้ามาใน 123456789012345678",
            "มารอใน 123456789012345678",
        ],
    )
    def test_an_ambiguous_phrase_still_works_when_it_names_a_channel(self, text):
        """The id is the confirmation — a real command carries one anyway."""
        assert self._parse(text) == ("join", 123456789012345678)
