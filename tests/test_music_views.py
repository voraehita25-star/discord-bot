"""
Tests for cogs/music/views.py

Comprehensive tests for MusicControlView.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest


class TestMusicControlViewInit:
    """Tests for MusicControlView initialization."""

    def test_init_stores_cog(self):
        """Test cog is stored."""
        with patch("discord.ui.View.__init__", return_value=None):
            from cogs.music.views import MusicControlView

            mock_cog = MagicMock()
            view = MusicControlView(cog=mock_cog, guild_id=12345)

            assert view.cog is mock_cog

    def test_init_stores_guild_id(self):
        """Test guild_id is stored."""
        with patch("discord.ui.View.__init__", return_value=None):
            from cogs.music.views import MusicControlView

            mock_cog = MagicMock()
            view = MusicControlView(cog=mock_cog, guild_id=12345)

            assert view.guild_id == 12345

    def test_init_default_timeout(self):
        """Test default timeout is 180."""
        with patch("discord.ui.View.__init__") as mock_init:
            mock_init.return_value = None
            from cogs.music.views import MusicControlView

            mock_cog = MagicMock()
            MusicControlView(cog=mock_cog, guild_id=12345)

            # Check that View.__init__ was called with timeout=180.0
            mock_init.assert_called_once_with(timeout=180.0)

    def test_init_custom_timeout(self):
        """Test custom timeout."""
        with patch("discord.ui.View.__init__") as mock_init:
            mock_init.return_value = None
            from cogs.music.views import MusicControlView

            mock_cog = MagicMock()
            MusicControlView(cog=mock_cog, guild_id=12345, timeout=60.0)

            mock_init.assert_called_once_with(timeout=60.0)


class TestInteractionCheck:
    """Tests for interaction_check method."""

    @pytest.mark.asyncio
    async def test_interaction_check_no_voice(self):
        """Test check fails when user not in voice."""
        with patch("discord.ui.View.__init__", return_value=None):
            from cogs.music.views import MusicControlView

            mock_cog = MagicMock()
            view = MusicControlView(cog=mock_cog, guild_id=12345)

            mock_interaction = MagicMock()
            mock_interaction.user.voice = None
            mock_interaction.response.send_message = AsyncMock()

            result = await view.interaction_check(mock_interaction)

            assert result is False
            mock_interaction.response.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_interaction_check_in_voice(self):
        """Test check passes when user shares the bot's voice channel.

        interaction_check now requires a connected voice_client (the bot
        is in a voice channel) AND that the user is in the same channel.
        With voice_client=None the controls have nothing to act on.
        """
        with patch("discord.ui.View.__init__", return_value=None):
            from cogs.music.views import MusicControlView

            mock_cog = MagicMock()
            view = MusicControlView(cog=mock_cog, guild_id=12345)

            shared_channel = MagicMock()
            mock_voice_client = MagicMock(channel=shared_channel)

            mock_interaction = MagicMock()
            mock_interaction.user = MagicMock(spec=discord.Member)
            mock_interaction.user.voice = MagicMock()
            mock_interaction.user.voice.channel = shared_channel
            mock_interaction.guild.voice_client = mock_voice_client
            mock_interaction.response.send_message = AsyncMock()
            mock_interaction.response.edit_message = AsyncMock()

            result = await view.interaction_check(mock_interaction)

            assert result is True


class TestPauseResumeButton:
    """Tests for pause/resume button."""

    @pytest.mark.asyncio
    async def test_pause_resume_no_voice_client(self):
        """Test button when no voice client."""
        with patch("discord.ui.View.__init__", return_value=None):
            from cogs.music.views import MusicControlView

            mock_cog = MagicMock()
            view = MusicControlView(cog=mock_cog, guild_id=12345)

            mock_interaction = MagicMock()
            mock_interaction.guild.voice_client = None
            mock_interaction.response.send_message = AsyncMock()

            mock_button = MagicMock()

            await view.pause_resume_button(mock_interaction, mock_button)

            mock_interaction.response.send_message.assert_called_once()
            args, kwargs = mock_interaction.response.send_message.call_args
            assert "ไม่ได้เล่นเพลงอยู่" in args[0]
            assert kwargs.get("ephemeral") is True

    @pytest.mark.asyncio
    async def test_pause_resume_paused_to_resume(self):
        """Test resume from paused state."""
        with patch("discord.ui.View.__init__", return_value=None):
            from cogs.music.views import MusicControlView

            mock_cog = MagicMock()
            view = MusicControlView(cog=mock_cog, guild_id=12345)

            mock_voice_client = MagicMock()
            mock_voice_client.is_paused.return_value = True
            mock_voice_client.resume = MagicMock()

            mock_interaction = MagicMock()
            mock_interaction.guild.voice_client = mock_voice_client
            mock_interaction.response.edit_message = AsyncMock()

            mock_button = MagicMock()

            await view.pause_resume_button(mock_interaction, mock_button)

            mock_voice_client.resume.assert_called_once()
            assert mock_button.emoji == "⏸️"
            mock_interaction.response.edit_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_pause_resume_playing_to_pause(self):
        """Test pause from playing state."""
        with patch("discord.ui.View.__init__", return_value=None):
            from cogs.music.views import MusicControlView

            mock_cog = MagicMock()
            view = MusicControlView(cog=mock_cog, guild_id=12345)

            mock_voice_client = MagicMock()
            mock_voice_client.is_paused.return_value = False
            mock_voice_client.is_playing.return_value = True
            mock_voice_client.pause = MagicMock()

            mock_interaction = MagicMock()
            mock_interaction.guild.voice_client = mock_voice_client
            mock_interaction.response.edit_message = AsyncMock()

            mock_button = MagicMock()

            await view.pause_resume_button(mock_interaction, mock_button)

            mock_voice_client.pause.assert_called_once()
            assert mock_button.emoji == "▶️"

    @pytest.mark.asyncio
    async def test_pause_resume_not_playing_not_paused(self):
        """Test button when not playing and not paused."""
        with patch("discord.ui.View.__init__", return_value=None):
            from cogs.music.views import MusicControlView

            mock_cog = MagicMock()
            view = MusicControlView(cog=mock_cog, guild_id=12345)

            mock_voice_client = MagicMock()
            mock_voice_client.is_paused.return_value = False
            mock_voice_client.is_playing.return_value = False

            mock_interaction = MagicMock()
            mock_interaction.guild.voice_client = mock_voice_client
            mock_interaction.response.send_message = AsyncMock()

            mock_button = MagicMock()

            await view.pause_resume_button(mock_interaction, mock_button)

            mock_interaction.response.send_message.assert_called_once()
            args, kwargs = mock_interaction.response.send_message.call_args
            assert "ไม่มีเพลงให้หยุด" in args[0]


class TestSkipButton:
    """Tests for skip button."""

    @pytest.mark.asyncio
    async def test_skip_button_playing(self):
        """Test skip when playing."""
        with patch("discord.ui.View.__init__", return_value=None):
            from cogs.music.views import MusicControlView

            mock_cog = MagicMock()
            mock_cog._gs.return_value = MagicMock(loop=False)
            view = MusicControlView(cog=mock_cog, guild_id=12345)

            mock_voice_client = MagicMock()
            mock_voice_client.is_playing.return_value = True
            mock_voice_client.stop = MagicMock()

            mock_interaction = MagicMock()
            mock_interaction.guild.voice_client = mock_voice_client
            mock_interaction.response.send_message = AsyncMock()

            mock_button = MagicMock()

            await view.skip_button(mock_interaction, mock_button)

            assert mock_cog._gs(12345).loop is False
            mock_voice_client.stop.assert_called_once()
            mock_interaction.response.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_skip_button_not_playing(self):
        """Test skip when neither playing nor paused → nothing to skip."""
        with patch("discord.ui.View.__init__", return_value=None):
            from cogs.music.views import MusicControlView

            mock_cog = MagicMock()
            view = MusicControlView(cog=mock_cog, guild_id=12345)

            mock_voice_client = MagicMock()
            mock_voice_client.is_playing.return_value = False
            # Must also be NOT paused — a paused track IS skippable now.
            mock_voice_client.is_paused.return_value = False

            mock_interaction = MagicMock()
            mock_interaction.guild.voice_client = mock_voice_client
            mock_interaction.response.send_message = AsyncMock()

            mock_button = MagicMock()

            await view.skip_button(mock_interaction, mock_button)

            mock_interaction.response.send_message.assert_called_once()
            args, kwargs = mock_interaction.response.send_message.call_args
            assert "ไม่มีเพลงให้ข้าม" in args[0]

    @pytest.mark.asyncio
    async def test_skip_button_paused(self):
        """A paused track must be skippable (parity with the text `skip` command)."""
        with patch("discord.ui.View.__init__", return_value=None):
            from cogs.music.views import MusicControlView

            mock_cog = MagicMock()
            view = MusicControlView(cog=mock_cog, guild_id=12345)

            mock_voice_client = MagicMock()
            mock_voice_client.is_playing.return_value = False
            mock_voice_client.is_paused.return_value = True

            mock_interaction = MagicMock()
            mock_interaction.guild.voice_client = mock_voice_client
            mock_interaction.response.send_message = AsyncMock()

            await view.skip_button(mock_interaction, MagicMock())

            mock_voice_client.stop.assert_called_once()
            args, kwargs = mock_interaction.response.send_message.call_args
            assert "ข้ามเพลง" in args[0]

    @pytest.mark.asyncio
    async def test_skip_button_no_voice_client(self):
        """Test skip when no voice client."""
        with patch("discord.ui.View.__init__", return_value=None):
            from cogs.music.views import MusicControlView

            mock_cog = MagicMock()
            view = MusicControlView(cog=mock_cog, guild_id=12345)

            mock_interaction = MagicMock()
            mock_interaction.guild.voice_client = None
            mock_interaction.response.send_message = AsyncMock()

            mock_button = MagicMock()

            await view.skip_button(mock_interaction, mock_button)

            mock_interaction.response.send_message.assert_called_once()


class TestStopButton:
    """Tests for stop button."""

    @pytest.mark.asyncio
    async def test_stop_button_clears_queue(self):
        """Test stop clears queue."""
        with patch("discord.ui.View.__init__", return_value=None):
            from cogs.music.views import MusicControlView

            mock_cog = MagicMock()
            mock_gs = MagicMock(queue=["song1", "song2"], loop=True, current_track="current")
            mock_cog._gs.return_value = mock_gs

            view = MusicControlView(cog=mock_cog, guild_id=12345)
            view.stop = MagicMock()  # Mock the View.stop method
            # stop_button now disables children before calling stop. With
            # discord.ui.View.__init__ patched out, the View has no
            # `_children` list set up — provide an empty one so the public
            # `self.children` property doesn't AttributeError.
            view._children = []
            # Required by stop_button's `if self.message:` branch.
            view.message = None

            mock_voice_client = MagicMock()
            mock_voice_client.stop = MagicMock()

            mock_interaction = MagicMock()
            mock_interaction.guild.voice_client = mock_voice_client
            mock_interaction.response.send_message = AsyncMock()

            mock_button = MagicMock()

            await view.stop_button(mock_interaction, mock_button)

            assert mock_gs.loop is False
            assert mock_gs.current_track is None
            mock_voice_client.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_button_no_voice_client(self):
        """Test stop when no voice client."""
        with patch("discord.ui.View.__init__", return_value=None):
            from cogs.music.views import MusicControlView

            mock_cog = MagicMock()
            mock_cog._gs.return_value = MagicMock(queue=[], loop=False, current_track=None)

            view = MusicControlView(cog=mock_cog, guild_id=12345)
            view.stop = MagicMock()
            # stop_button now disables children before calling stop. See
            # test_stop_button_clears_queue above for the same workaround
            # reasoning.
            view._children = []
            view.message = None

            mock_interaction = MagicMock()
            mock_interaction.guild.voice_client = None
            mock_interaction.response.send_message = AsyncMock()

            mock_button = MagicMock()

            await view.stop_button(mock_interaction, mock_button)

            # Should still send response
            mock_interaction.response.send_message.assert_called_once()


class TestLoopButton:
    """Tests for loop button."""

    @pytest.mark.asyncio
    async def test_loop_button_enable(self):
        """Test enable loop."""
        with patch("discord.ui.View.__init__", return_value=None):
            with patch("discord.ButtonStyle") as mock_style:
                mock_style.success = "success"
                mock_style.secondary = "secondary"

                from cogs.music.views import MusicControlView

                mock_cog = MagicMock()
                mock_cog._gs.return_value = MagicMock(loop=False)

                view = MusicControlView(cog=mock_cog, guild_id=12345)

                mock_interaction = MagicMock()
                mock_interaction.response.send_message = AsyncMock()
                mock_interaction.response.edit_message = AsyncMock()
                mock_interaction.followup.send = AsyncMock()

                mock_button = MagicMock()

                await view.loop_button(mock_interaction, mock_button)

                assert mock_cog._gs(12345).loop is True

    @pytest.mark.asyncio
    async def test_loop_button_disable(self):
        """Test disable loop."""
        with patch("discord.ui.View.__init__", return_value=None):
            with patch("discord.ButtonStyle") as mock_style:
                mock_style.success = "success"
                mock_style.secondary = "secondary"

                from cogs.music.views import MusicControlView

                mock_cog = MagicMock()
                mock_cog._gs.return_value = MagicMock(loop=True)

                view = MusicControlView(cog=mock_cog, guild_id=12345)

                mock_interaction = MagicMock()
                mock_interaction.response.send_message = AsyncMock()
                mock_interaction.response.edit_message = AsyncMock()
                mock_interaction.followup.send = AsyncMock()

                mock_button = MagicMock()

                await view.loop_button(mock_interaction, mock_button)

                assert mock_cog._gs(12345).loop is False

    @pytest.mark.asyncio
    async def test_loop_button_no_existing_state(self):
        """Test loop when no existing state."""
        with patch("discord.ui.View.__init__", return_value=None):
            with patch("discord.ButtonStyle") as mock_style:
                mock_style.success = "success"
                mock_style.secondary = "secondary"

                from cogs.music.views import MusicControlView

                mock_cog = MagicMock()
                mock_cog._gs.return_value = MagicMock(loop=False)

                view = MusicControlView(cog=mock_cog, guild_id=12345)

                mock_interaction = MagicMock()
                mock_interaction.response.send_message = AsyncMock()
                mock_interaction.response.edit_message = AsyncMock()
                mock_interaction.followup.send = AsyncMock()

                mock_button = MagicMock()

                await view.loop_button(mock_interaction, mock_button)

                # Should default to False, then toggle to True
                assert mock_cog._gs(12345).loop is True


class TestOnTimeout:
    """Tests for on_timeout method."""

    @pytest.mark.asyncio
    async def test_on_timeout_disables_buttons(self):
        """Test on_timeout disables all buttons."""
        with patch("discord.ui.View.__init__", return_value=None):
            from cogs.music.views import MusicControlView

            mock_cog = MagicMock()
            view = MusicControlView(cog=mock_cog, guild_id=12345)

            # Mock buttons with spec to pass isinstance check
            mock_button1 = MagicMock(spec=discord.ui.Button)
            mock_button1.disabled = False
            mock_button2 = MagicMock(spec=discord.ui.Button)
            mock_button2.disabled = False

            # Use _children attribute instead of children property
            view._children = [mock_button1, mock_button2]

            await view.on_timeout()

            assert mock_button1.disabled is True
            assert mock_button2.disabled is True


class TestMusicControlViewClass:
    """Tests for MusicControlView class structure."""

    def test_class_exists(self):
        """Test MusicControlView class exists."""
        from cogs.music.views import MusicControlView

        assert MusicControlView is not None

    def test_has_interaction_check(self):
        """Test has interaction_check method."""
        from cogs.music.views import MusicControlView

        assert hasattr(MusicControlView, "interaction_check")

    def test_has_pause_resume_button(self):
        """Test has pause_resume_button method."""
        from cogs.music.views import MusicControlView

        assert hasattr(MusicControlView, "pause_resume_button")

    def test_has_skip_button(self):
        """Test has skip_button method."""
        from cogs.music.views import MusicControlView

        assert hasattr(MusicControlView, "skip_button")

    def test_has_stop_button(self):
        """Test has stop_button method."""
        from cogs.music.views import MusicControlView

        assert hasattr(MusicControlView, "stop_button")

    def test_has_loop_button(self):
        """Test has loop_button method."""
        from cogs.music.views import MusicControlView

        assert hasattr(MusicControlView, "loop_button")

    def test_has_on_timeout(self):
        """Test has on_timeout method."""
        from cogs.music.views import MusicControlView

        assert hasattr(MusicControlView, "on_timeout")


class TestModuleImports:
    """Tests for module imports."""

    def test_import_music_control_view(self):
        """Test MusicControlView can be imported."""
        from cogs.music.views import MusicControlView

        assert MusicControlView is not None


def _make_http_exception(message="boom"):
    """Build a real discord.HTTPException with a mock HTTP response."""
    resp = MagicMock()
    resp.status = 500
    resp.reason = "err"
    return discord.HTTPException(resp, message)


class TestInteractionCheckBranches:
    """Cover the remaining guard branches of interaction_check."""

    @pytest.mark.asyncio
    async def test_not_a_member_rejected(self):
        """A DM User (not a Member) is rejected before any voice checks."""
        with patch("discord.ui.View.__init__", return_value=None):
            from cogs.music.views import MusicControlView

            view = MusicControlView(cog=MagicMock(), guild_id=12345)

            interaction = MagicMock()
            # user is NOT a discord.Member instance.
            interaction.user = MagicMock(spec=discord.User)
            interaction.response.send_message = AsyncMock()

            result = await view.interaction_check(interaction)

            assert result is False
            args, kwargs = interaction.response.send_message.call_args
            assert "เฉพาะในเซิร์ฟเวอร์" in args[0]
            assert kwargs.get("ephemeral") is True

    @pytest.mark.asyncio
    async def test_bot_not_connected_to_voice(self):
        """Member present but bot has no voice_client → rejected (lines 39-40)."""
        with patch("discord.ui.View.__init__", return_value=None):
            from cogs.music.views import MusicControlView

            view = MusicControlView(cog=MagicMock(), guild_id=12345)

            interaction = MagicMock()
            interaction.user = MagicMock(spec=discord.Member)
            interaction.guild.voice_client = None
            interaction.response.send_message = AsyncMock()

            result = await view.interaction_check(interaction)

            assert result is False
            args, kwargs = interaction.response.send_message.call_args
            assert "not connected to voice" in args[0]
            assert kwargs.get("ephemeral") is True

    @pytest.mark.asyncio
    async def test_no_guild_rejected(self):
        """No guild at all → bot-not-connected branch (lines 39-40)."""
        with patch("discord.ui.View.__init__", return_value=None):
            from cogs.music.views import MusicControlView

            view = MusicControlView(cog=MagicMock(), guild_id=12345)

            interaction = MagicMock()
            interaction.user = MagicMock(spec=discord.Member)
            interaction.guild = None
            interaction.response.send_message = AsyncMock()

            result = await view.interaction_check(interaction)

            assert result is False
            args, kwargs = interaction.response.send_message.call_args
            assert "not connected to voice" in args[0]

    @pytest.mark.asyncio
    async def test_member_not_in_voice(self):
        """Member is a Member, bot connected, but member.voice is None (lines 43-44)."""
        with patch("discord.ui.View.__init__", return_value=None):
            from cogs.music.views import MusicControlView

            view = MusicControlView(cog=MagicMock(), guild_id=12345)

            interaction = MagicMock()
            interaction.user = MagicMock(spec=discord.Member)
            interaction.user.voice = None
            interaction.guild.voice_client = MagicMock()
            interaction.response.send_message = AsyncMock()

            result = await view.interaction_check(interaction)

            assert result is False
            args, kwargs = interaction.response.send_message.call_args
            assert "ห้องเสียงก่อน" in args[0]
            assert kwargs.get("ephemeral") is True

    @pytest.mark.asyncio
    async def test_member_in_different_channel(self):
        """Member in voice but a DIFFERENT channel than the bot (lines 50-53)."""
        with patch("discord.ui.View.__init__", return_value=None):
            from cogs.music.views import MusicControlView

            view = MusicControlView(cog=MagicMock(), guild_id=12345)

            bot_channel = MagicMock()
            user_channel = MagicMock()  # distinct object → != bot_channel

            interaction = MagicMock()
            interaction.user = MagicMock(spec=discord.Member)
            interaction.user.voice = MagicMock()
            interaction.user.voice.channel = user_channel
            interaction.guild.voice_client = MagicMock(channel=bot_channel)
            interaction.response.send_message = AsyncMock()

            result = await view.interaction_check(interaction)

            assert result is False
            args, kwargs = interaction.response.send_message.call_args
            assert "ห้องเสียงเดียวกับบอท" in args[0]
            assert kwargs.get("ephemeral") is True


class TestPauseResumeErrorBranches:
    """Cover the ClientException handlers in pause_resume_button."""

    @pytest.mark.asyncio
    async def test_resume_raises_client_exception(self):
        """resume() raising ClientException restores emoji + notifies user (73-77)."""
        with patch("discord.ui.View.__init__", return_value=None):
            from cogs.music.views import MusicControlView

            view = MusicControlView(cog=MagicMock(), guild_id=12345)

            voice_client = MagicMock()
            voice_client.is_paused.return_value = True
            voice_client.resume.side_effect = discord.ClientException("Not connected")

            interaction = MagicMock()
            interaction.guild.voice_client = voice_client
            interaction.response.send_message = AsyncMock()
            interaction.response.edit_message = AsyncMock()

            button = MagicMock()
            button.emoji = "original"

            await view.pause_resume_button(interaction, button)

            # Emoji restored to the previous value after failure.
            assert button.emoji == "original"
            interaction.response.send_message.assert_called_once()
            args, kwargs = interaction.response.send_message.call_args
            assert "ไม่สามารถเล่นต่อได้" in args[0]
            assert kwargs.get("ephemeral") is True
            # Must have returned before edit_message.
            interaction.response.edit_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_pause_raises_client_exception(self):
        """pause() raising ClientException restores emoji + notifies user (84-89)."""
        with patch("discord.ui.View.__init__", return_value=None):
            from cogs.music.views import MusicControlView

            view = MusicControlView(cog=MagicMock(), guild_id=12345)

            voice_client = MagicMock()
            voice_client.is_paused.return_value = False
            voice_client.is_playing.return_value = True
            voice_client.pause.side_effect = discord.ClientException("Already paused")

            interaction = MagicMock()
            interaction.guild.voice_client = voice_client
            interaction.response.send_message = AsyncMock()
            interaction.response.edit_message = AsyncMock()

            button = MagicMock()
            button.emoji = "original"

            await view.pause_resume_button(interaction, button)

            assert button.emoji == "original"
            interaction.response.send_message.assert_called_once()
            args, kwargs = interaction.response.send_message.call_args
            assert "ไม่สามารถหยุดชั่วคราวได้" in args[0]
            assert kwargs.get("ephemeral") is True
            interaction.response.edit_message.assert_not_called()


class TestStopButtonMessageBranches:
    """Cover the message-edit branches of stop_button (133-139)."""

    @pytest.mark.asyncio
    async def test_disables_children_and_edits_message(self):
        """Children with `disabled` are disabled and message.edit is called (133-138)."""
        with patch("discord.ui.View.__init__", return_value=None):
            from cogs.music.views import MusicControlView

            mock_cog = MagicMock()
            mock_cog._gs.return_value = MagicMock(queue=MagicMock(), loop=True, current_track="t")

            view = MusicControlView(cog=mock_cog, guild_id=12345)
            view.stop = MagicMock()

            child_with_disabled = MagicMock()
            child_with_disabled.disabled = False
            # A child WITHOUT a `disabled` attribute → hasattr is False branch.
            child_without = MagicMock(spec=[])
            view._children = [child_with_disabled, child_without]

            message = MagicMock()
            message.edit = AsyncMock()
            view.message = message

            interaction = MagicMock()
            interaction.guild.voice_client = MagicMock()
            interaction.response.send_message = AsyncMock()

            await view.stop_button(interaction, MagicMock())

            assert child_with_disabled.disabled is True
            message.edit.assert_awaited_once()
            view.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_message_edit_http_exception_suppressed(self):
        """message.edit raising HTTPException is swallowed (139)."""
        with patch("discord.ui.View.__init__", return_value=None):
            from cogs.music.views import MusicControlView

            mock_cog = MagicMock()
            mock_cog._gs.return_value = MagicMock(queue=MagicMock(), loop=False, current_track=None)

            view = MusicControlView(cog=mock_cog, guild_id=12345)
            view.stop = MagicMock()
            view._children = []

            message = MagicMock()
            message.edit = AsyncMock(side_effect=_make_http_exception())
            view.message = message

            interaction = MagicMock()
            interaction.guild.voice_client = None
            interaction.response.send_message = AsyncMock()

            # Should not raise.
            await view.stop_button(interaction, MagicMock())

            message.edit.assert_awaited_once()
            view.stop.assert_called_once()


class TestLoopButtonErrorBranch:
    """Cover the edit_message failure path in loop_button (160-162)."""

    @pytest.mark.asyncio
    async def test_edit_message_http_exception_reverts_loop(self):
        """edit_message raising HTTPException reverts loop and bails (160-162)."""
        with patch("discord.ui.View.__init__", return_value=None):
            from cogs.music.views import MusicControlView

            mock_cog = MagicMock()
            gs = MagicMock()
            gs.loop = False
            mock_cog._gs.return_value = gs

            view = MusicControlView(cog=mock_cog, guild_id=12345)

            interaction = MagicMock()
            interaction.response.edit_message = AsyncMock(side_effect=_make_http_exception())
            interaction.followup.send = AsyncMock()

            await view.loop_button(interaction, MagicMock())

            # loop was toggled to True, then reverted to the original False.
            assert gs.loop is False
            # followup.send must NOT be reached after the early return.
            interaction.followup.send.assert_not_called()


class TestOnTimeoutMessageBranches:
    """Cover the message-edit branches of on_timeout (174-177)."""

    @pytest.mark.asyncio
    async def test_on_timeout_edits_message(self):
        """on_timeout edits the stored message to show disabled buttons (174-175)."""
        with patch("discord.ui.View.__init__", return_value=None):
            from cogs.music.views import MusicControlView

            view = MusicControlView(cog=MagicMock(), guild_id=12345)

            button = MagicMock(spec=discord.ui.Button)
            button.disabled = False
            view._children = [button]

            message = MagicMock()
            message.edit = AsyncMock()
            view.message = message

            await view.on_timeout()

            assert button.disabled is True
            message.edit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_on_timeout_edit_not_found_suppressed(self):
        """on_timeout swallows NotFound/HTTPException/AttributeError (176-177)."""
        with patch("discord.ui.View.__init__", return_value=None):
            from cogs.music.views import MusicControlView

            view = MusicControlView(cog=MagicMock(), guild_id=12345)
            view._children = []

            message = MagicMock()
            message.edit = AsyncMock(side_effect=_make_http_exception())
            view.message = message

            # Should not raise.
            await view.on_timeout()

            message.edit.assert_awaited_once()
