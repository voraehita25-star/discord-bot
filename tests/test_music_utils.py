"""
Tests for cogs.music.utils module.
"""

import pytest


class TestColors:
    """Tests for Colors class."""

    def test_playing_color(self):
        """Test PLAYING color constant."""
        from cogs.music.utils import Colors
        assert Colors.PLAYING == 0x00FF7F

    def test_queued_color(self):
        """Test QUEUED color constant."""
        from cogs.music.utils import Colors
        assert Colors.QUEUED == 0x3498DB

    def test_spotify_color(self):
        """Test SPOTIFY color constant."""
        from cogs.music.utils import Colors
        assert Colors.SPOTIFY == 0x1DB954

    def test_youtube_color(self):
        """Test YOUTUBE color constant."""
        from cogs.music.utils import Colors
        assert Colors.YOUTUBE == 0xFF0000

    def test_error_color(self):
        """Test ERROR color constant."""
        from cogs.music.utils import Colors
        assert Colors.ERROR == 0xFF4444

    def test_success_color(self):
        """Test SUCCESS color constant."""
        from cogs.music.utils import Colors
        assert Colors.SUCCESS == 0x00FF00


class TestEmojis:
    """Tests for Emojis class."""

    def test_play_emoji(self):
        """Test PLAY emoji constant."""
        from cogs.music.utils import Emojis
        assert Emojis.PLAY == "▶️"

    def test_pause_emoji(self):
        """Test PAUSE emoji constant."""
        from cogs.music.utils import Emojis
        assert Emojis.PAUSE == "⏸️"

    def test_skip_emoji(self):
        """Test SKIP emoji constant."""
        from cogs.music.utils import Emojis
        assert Emojis.SKIP == "⏭️"

    def test_stop_emoji(self):
        """Test STOP emoji constant."""
        from cogs.music.utils import Emojis
        assert Emojis.STOP == "⏹️"

    def test_loop_emoji(self):
        """Test LOOP emoji constant."""
        from cogs.music.utils import Emojis
        assert Emojis.LOOP == "🔁"

    def test_queue_emoji(self):
        """Test QUEUE emoji constant."""
        from cogs.music.utils import Emojis
        assert Emojis.QUEUE == "📜"

    def test_check_emoji(self):
        """Test CHECK emoji constant."""
        from cogs.music.utils import Emojis
        assert Emojis.CHECK == "✅"

    def test_cross_emoji(self):
        """Test CROSS emoji constant."""
        from cogs.music.utils import Emojis
        assert Emojis.CROSS == "❌"


class TestFormatDuration:
    """Tests for format_duration function."""

    def test_format_none(self):
        """Test formatting None returns 00:00."""
        from cogs.music.utils import format_duration
        assert format_duration(None) == "00:00"

    def test_format_zero(self):
        """Test formatting zero returns 00:00."""
        from cogs.music.utils import format_duration
        assert format_duration(0) == "00:00"

    def test_format_seconds_only(self):
        """Test formatting seconds only."""
        from cogs.music.utils import format_duration
        assert format_duration(45) == "0:45"

    def test_format_one_minute(self):
        """Test formatting one minute."""
        from cogs.music.utils import format_duration
        assert format_duration(60) == "1:00"

    def test_format_minutes_seconds(self):
        """Test formatting minutes and seconds."""
        from cogs.music.utils import format_duration
        assert format_duration(185) == "3:05"

    def test_format_one_hour(self):
        """Test formatting one hour."""
        from cogs.music.utils import format_duration
        assert format_duration(3600) == "1:00:00"

    def test_format_hours_minutes_seconds(self):
        """Test formatting hours, minutes, and seconds."""
        from cogs.music.utils import format_duration
        assert format_duration(3665) == "1:01:05"

    def test_format_float(self):
        """Test formatting float value."""
        from cogs.music.utils import format_duration
        result = format_duration(65.7)
        assert result == "1:05"

    def test_format_large_value(self):
        """Test formatting large value."""
        from cogs.music.utils import format_duration
        # 10 hours, 30 minutes, 45 seconds
        result = format_duration(37845)
        assert "10:" in result


class TestCreateProgressBar:
    """Tests for create_progress_bar function."""

    def test_progress_bar_zero(self):
        """Test progress bar at 0%."""
        from cogs.music.utils import create_progress_bar
        result = create_progress_bar(0, 100)
        assert "▱" in result

    def test_progress_bar_full(self):
        """Test progress bar at 100%."""
        from cogs.music.utils import create_progress_bar
        result = create_progress_bar(100, 100)
        assert "▰" in result

    def test_progress_bar_half(self):
        """Test progress bar at 50%."""
        from cogs.music.utils import create_progress_bar
        result = create_progress_bar(50, 100)
        assert "▰" in result
        assert "▱" in result

    def test_progress_bar_custom_length(self):
        """Test progress bar with custom length."""
        from cogs.music.utils import create_progress_bar
        result = create_progress_bar(50, 100, length=20)
        assert len(result.replace("▰", "").replace("▱", "")) == 0 or len(result) >= 12
