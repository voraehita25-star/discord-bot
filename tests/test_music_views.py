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
        """Test check passes when user in voice."""
        with patch("discord.ui.View.__init__", return_value=None):
            from cogs.music.views import MusicControlView

            mock_cog = MagicMock()
            view = MusicControlView(cog=mock_cog, guild_id=12345)

            mock_interaction = MagicMock()
            mock_interaction.user = MagicMock(spec=discord.Member)
            mock_interaction.user.voice = MagicMock()
            mock_interaction.user.voice.channel = MagicMock()  # User's voice channel
            mock_interaction.guild.voice_client = None  # Bot not in voice
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
            mock_cog.loops = {}
            view = MusicControlView(cog=mock_cog, guild_id=12345)

            mock_voice_client = MagicMock()
            mock_voice_client.is_playing.return_value = True
            mock_voice_client.stop = MagicMock()

            mock_interaction = MagicMock()
            mock_interaction.guild.voice_client = mock_voice_client
            mock_interaction.response.send_message = AsyncMock()

            mock_button = MagicMock()

            await view.skip_button(mock_interaction, mock_button)

            assert mock_cog.loops[12345] is False
            mock_voice_client.stop.assert_called_once()
            mock_interaction.response.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_skip_button_not_playing(self):
        """Test skip when not playing."""
        with patch("discord.ui.View.__init__", return_value=None):
            from cogs.music.views import MusicControlView

            mock_cog = MagicMock()
            view = MusicControlView(cog=mock_cog, guild_id=12345)

            mock_voice_client = MagicMock()
            mock_voice_client.is_playing.return_value = False

            mock_interaction = MagicMock()
            mock_interaction.guild.voice_client = mock_voice_client
            mock_interaction.response.send_message = AsyncMock()

            mock_button = MagicMock()

            await view.skip_button(mock_interaction, mock_button)

            mock_interaction.response.send_message.assert_called_once()
            args, kwargs = mock_interaction.response.send_message.call_args
            assert "ไม่มีเพลงให้ข้าม" in args[0]

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
            mock_cog.queues = {12345: ["song1", "song2"]}
            mock_cog.loops = {12345: True}
            mock_cog.current_track = {12345: "current"}

            view = MusicControlView(cog=mock_cog, guild_id=12345)
            view.stop = MagicMock()  # Mock the View.stop method

            mock_voice_client = MagicMock()
            mock_voice_client.stop = MagicMock()

            mock_interaction = MagicMock()
            mock_interaction.guild.voice_client = mock_voice_client
            mock_interaction.response.send_message = AsyncMock()

            mock_button = MagicMock()

            await view.stop_button(mock_interaction, mock_button)

            assert len(mock_cog.queues[12345]) == 0
            assert mock_cog.loops[12345] is False
            assert 12345 not in mock_cog.current_track
            mock_voice_client.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_button_no_voice_client(self):
        """Test stop when no voice client."""
        with patch("discord.ui.View.__init__", return_value=None):
            from cogs.music.views import MusicControlView

            mock_cog = MagicMock()
            mock_cog.queues = {}
            mock_cog.loops = {}
            mock_cog.current_track = {}

            view = MusicControlView(cog=mock_cog, guild_id=12345)
            view.stop = MagicMock()

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
                mock_cog.loops = {12345: False}

                view = MusicControlView(cog=mock_cog, guild_id=12345)

                mock_interaction = MagicMock()
                mock_interaction.response.send_message = AsyncMock()
                mock_interaction.response.edit_message = AsyncMock()
                mock_interaction.followup.send = AsyncMock()

                mock_button = MagicMock()

                await view.loop_button(mock_interaction, mock_button)

                assert mock_cog.loops[12345] is True

    @pytest.mark.asyncio
    async def test_loop_button_disable(self):
        """Test disable loop."""
        with patch("discord.ui.View.__init__", return_value=None):
            with patch("discord.ButtonStyle") as mock_style:
                mock_style.success = "success"
                mock_style.secondary = "secondary"

                from cogs.music.views import MusicControlView

                mock_cog = MagicMock()
                mock_cog.loops = {12345: True}

                view = MusicControlView(cog=mock_cog, guild_id=12345)

                mock_interaction = MagicMock()
                mock_interaction.response.send_message = AsyncMock()
                mock_interaction.response.edit_message = AsyncMock()
                mock_interaction.followup.send = AsyncMock()

                mock_button = MagicMock()

                await view.loop_button(mock_interaction, mock_button)

                assert mock_cog.loops[12345] is False

    @pytest.mark.asyncio
    async def test_loop_button_no_existing_state(self):
        """Test loop when no existing state."""
        with patch("discord.ui.View.__init__", return_value=None):
            with patch("discord.ButtonStyle") as mock_style:
                mock_style.success = "success"
                mock_style.secondary = "secondary"

                from cogs.music.views import MusicControlView

                mock_cog = MagicMock()
                mock_cog.loops = {}  # No existing state

                view = MusicControlView(cog=mock_cog, guild_id=12345)

                mock_interaction = MagicMock()
                mock_interaction.response.send_message = AsyncMock()
                mock_interaction.response.edit_message = AsyncMock()
                mock_interaction.followup.send = AsyncMock()

                mock_button = MagicMock()

                await view.loop_button(mock_interaction, mock_button)

                # Should default to False, then toggle to True
                assert mock_cog.loops[12345] is True


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

    def test_module_imports(self):
        """Test module can be imported."""
        import cogs.music.views

        assert cogs.music.views is not None

    def test_import_music_control_view(self):
        """Test MusicControlView can be imported."""
        from cogs.music.views import MusicControlView

        assert MusicControlView is not None
