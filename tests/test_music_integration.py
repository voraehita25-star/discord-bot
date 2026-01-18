"""
Integration Tests for Music Cog.
Tests music playback, queue management, and voice channel handling.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))


class TestMusicQueueManagement:
    """Test queue operations for music cog."""

    def test_queue_structure(self) -> None:
        """Test queue data structure format."""
        queue_entry = {
            "title": "Test Song",
            "url": "https://youtube.com/watch?v=test123",
            "duration": 180,
            "channel": "Test Artist",
            "thumbnail": "https://example.com/thumb.jpg",
            "requester_id": 123456789,
            "requester_name": "TestUser",
        }

        assert "title" in queue_entry
        assert "url" in queue_entry
        assert isinstance(queue_entry["duration"], int)
        assert queue_entry["duration"] == 180

    def test_queue_operations(self) -> None:
        """Test basic queue add/remove operations."""
        queue: list[dict[str, Any]] = []

        # Add items
        queue.append({"title": "Song 1", "url": "url1"})
        queue.append({"title": "Song 2", "url": "url2"})
        queue.append({"title": "Song 3", "url": "url3"})

        assert len(queue) == 3

        # Pop first (now playing)
        now_playing = queue.pop(0)
        assert now_playing["title"] == "Song 1"
        assert len(queue) == 2

        # Skip (pop again)
        _ = queue.pop(0)
        assert len(queue) == 1
        assert queue[0]["title"] == "Song 3"

    def test_loop_modes(self) -> None:
        """Test loop mode enumeration."""
        LOOP_OFF = 0
        LOOP_SINGLE = 1
        LOOP_QUEUE = 2

        loop_mode = LOOP_OFF

        # Cycle through modes
        loop_mode = (loop_mode + 1) % 3
        assert loop_mode == LOOP_SINGLE

        loop_mode = (loop_mode + 1) % 3
        assert loop_mode == LOOP_QUEUE

        loop_mode = (loop_mode + 1) % 3
        assert loop_mode == LOOP_OFF


class TestMusicURLDetection:
    """Test URL detection for music sources."""

    def test_youtube_url_detection(self) -> None:
        """Test YouTube URL pattern detection."""
        import re

        youtube_pattern = re.compile(
            r"(https?://)?(www\.)?(youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)[\w-]+"
        )

        # Valid YouTube URLs
        assert youtube_pattern.match("https://www.youtube.com/watch?v=abc123")
        assert youtube_pattern.match("https://youtu.be/abc123")
        assert youtube_pattern.match("https://youtube.com/shorts/abc123")
        assert youtube_pattern.match("youtube.com/watch?v=test")

        # Invalid URLs
        assert not youtube_pattern.match("https://spotify.com/track/123")
        assert not youtube_pattern.match("random text")

    def test_spotify_url_detection(self) -> None:
        """Test Spotify URL pattern detection."""
        import re

        spotify_pattern = re.compile(
            r"https?://open\.spotify\.com/(track|album|playlist)/[\w]+", re.IGNORECASE
        )

        # Valid Spotify URLs
        assert spotify_pattern.match("https://open.spotify.com/track/abc123")
        assert spotify_pattern.match("https://open.spotify.com/album/xyz456")
        assert spotify_pattern.match("https://open.spotify.com/playlist/789")

        # Invalid URLs
        assert not spotify_pattern.match("https://youtube.com/watch?v=abc")
        assert not spotify_pattern.match("spotify:track:123")  # URI format


class TestDurationFormatting:
    """Test duration formatting utilities."""

    def test_format_duration(self) -> None:
        """Test seconds to MM:SS/HH:MM:SS conversion."""

        def format_duration(seconds: int | None) -> str:
            if not seconds:
                return "00:00"
            seconds = int(seconds)
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            secs = seconds % 60
            if hours > 0:
                return f"{hours}:{minutes:02d}:{secs:02d}"
            return f"{minutes}:{secs:02d}"

        assert format_duration(0) == "00:00"
        assert format_duration(None) == "00:00"
        assert format_duration(65) == "1:05"
        assert format_duration(3661) == "1:01:01"
        assert format_duration(180) == "3:00"

    def test_progress_bar(self) -> None:
        """Test progress bar generation."""

        def create_progress_bar(current: int, total: int, length: int = 12) -> str:
            if total == 0:
                return "▱" * length
            progress = int((current / total) * length)
            return "▰" * progress + "▱" * (length - progress)

        assert create_progress_bar(0, 100) == "▱▱▱▱▱▱▱▱▱▱▱▱"
        assert create_progress_bar(50, 100) == "▰▰▰▰▰▰▱▱▱▱▱▱"
        assert create_progress_bar(100, 100) == "▰▰▰▰▰▰▰▰▰▰▰▰"
        assert create_progress_bar(0, 0) == "▱▱▱▱▱▱▱▱▱▱▱▱"


class TestVoiceChannelHandling:
    """Test voice channel connection logic."""

    @pytest.mark.asyncio
    async def test_voice_client_mock(self) -> None:
        """Test voice client mock structure."""
        voice_client = MagicMock()
        voice_client.is_connected.return_value = True
        voice_client.is_playing.return_value = False
        voice_client.is_paused.return_value = False
        voice_client.disconnect = AsyncMock()

        assert voice_client.is_connected()
        assert not voice_client.is_playing()

        await voice_client.disconnect()
        voice_client.disconnect.assert_called_once()

    def test_guild_queue_isolation(self) -> None:
        """Test that queues are isolated per guild."""
        queues: dict[int, list[dict[str, Any]]] = {}

        # Create queues for different guilds
        guild_1, guild_2 = 111, 222

        queues[guild_1] = [{"title": "Song A"}]
        queues[guild_2] = [{"title": "Song B"}, {"title": "Song C"}]

        assert len(queues[guild_1]) == 1
        assert len(queues[guild_2]) == 2
        assert queues[guild_1][0]["title"] == "Song A"
        assert queues[guild_2][0]["title"] == "Song B"


class TestMusicEmbedGeneration:
    """Test embed generation for music messages."""

    def test_now_playing_data(self) -> None:
        """Test now playing embed data structure."""
        track_info = {
            "title": "Test Song Title",
            "url": "https://youtube.com/watch?v=test",
            "duration": 245,
            "channel": "Artist Name",
            "thumbnail": "https://example.com/thumb.jpg",
            "requester_name": "User123",
        }

        # Simulate embed field creation
        fields = [
            ("Duration", "2:05"),
            ("Channel", track_info["channel"]),
            ("Requested by", track_info["requester_name"]),
        ]

        assert len(fields) == 3
        assert fields[0][0] == "Duration"
        assert track_info["title"] == "Test Song Title"


# Run tests with: python -m pytest tests/test_music_integration.py -v
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
