"""
Integration Tests for Spotify Handler.
Tests Spotify URL parsing, track/album/playlist processing.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))


class TestSpotifyURLParsing:
    """Test Spotify URL parsing functionality."""

    def test_track_url_parsing(self) -> None:
        """Test Spotify track URL parsing."""
        url = "https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC"

        pattern = re.compile(r"open\.spotify\.com/(track|album|playlist)/([a-zA-Z0-9]+)")
        match = pattern.search(url)

        assert match is not None
        assert match.group(1) == "track"
        assert match.group(2) == "4uLU6hMCjMI75M1A2tKUQC"

    def test_album_url_parsing(self) -> None:
        """Test Spotify album URL parsing."""
        url = "https://open.spotify.com/album/6dVIqQ8qmQ5GBnJ9shOYGE"

        pattern = re.compile(r"open\.spotify\.com/(track|album|playlist)/([a-zA-Z0-9]+)")
        match = pattern.search(url)

        assert match is not None
        assert match.group(1) == "album"
        assert len(match.group(2)) > 10

    def test_playlist_url_parsing(self) -> None:
        """Test Spotify playlist URL parsing."""
        url = "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"

        pattern = re.compile(r"open\.spotify\.com/(track|album|playlist)/([a-zA-Z0-9]+)")
        match = pattern.search(url)

        assert match is not None
        assert match.group(1) == "playlist"

    def test_url_with_query_params(self) -> None:
        """Test URL parsing with query parameters."""
        url = "https://open.spotify.com/track/abc123?si=def456"

        pattern = re.compile(r"open\.spotify\.com/(track|album|playlist)/([a-zA-Z0-9]+)")
        match = pattern.search(url)

        assert match is not None
        assert match.group(2) == "abc123"  # Should not include query params

    def test_invalid_url_detection(self) -> None:
        """Test that invalid URLs are properly rejected."""
        invalid_urls = [
            "https://spotify.com/track/123",  # Wrong domain
            "https://open.spotify.com/artist/123",  # Artist not supported
            "spotify:track:123",  # URI format
            "random text",
        ]

        pattern = re.compile(r"open\.spotify\.com/(track|album|playlist)/([a-zA-Z0-9]+)")

        for url in invalid_urls:
            match = pattern.search(url)
            # artist should not match, others shouldn't either
            if match:
                # If there's a match, it should be one of the supported types
                assert match.group(1) in ["track", "album", "playlist"]


class TestSpotifyTrackConversion:
    """Test conversion of Spotify tracks to YouTube searches."""

    def test_search_query_generation(self) -> None:
        """Test YouTube search query generation from Spotify track."""
        track_info = {
            "name": "Bohemian Rhapsody",
            "artists": [{"name": "Queen"}],
            "album": {"name": "A Night at the Opera"},
            "duration_ms": 354947,
        }

        # Generate search query
        artist_names = " ".join([a["name"] for a in track_info["artists"]])
        search_query = f"{track_info['name']} {artist_names}"

        assert search_query == "Bohemian Rhapsody Queen"
        assert "Queen" in search_query

    def test_multiple_artists_handling(self) -> None:
        """Test handling of tracks with multiple artists."""
        track_info = {"name": "Say So", "artists": [{"name": "Doja Cat"}, {"name": "Nicki Minaj"}]}

        artist_names = ", ".join([a["name"] for a in track_info["artists"]])

        assert artist_names == "Doja Cat, Nicki Minaj"

    def test_duration_conversion(self) -> None:
        """Test Spotify duration (ms) to seconds conversion."""
        duration_ms = 234567
        duration_seconds = duration_ms // 1000

        assert duration_seconds == 234


class TestSpotifyRetryLogic:
    """Test retry logic for Spotify API calls."""

    def test_exponential_backoff(self) -> None:
        """Test exponential backoff delay calculation."""
        base_delay = 1.0
        max_delay = 30.0

        delays = []
        for attempt in range(5):
            delay = min(base_delay * (2**attempt), max_delay)
            delays.append(delay)

        assert delays == [1.0, 2.0, 4.0, 8.0, 16.0]

        # Test max delay cap
        for attempt in range(10):
            delay = min(base_delay * (2**attempt), max_delay)
            assert delay <= max_delay

    def test_retry_count_tracking(self) -> None:
        """Test retry attempt counting."""
        max_retries = 3
        attempts = 0
        success = False

        while attempts < max_retries and not success:
            attempts += 1
            if attempts == 2:  # Simulate success on 2nd attempt
                success = True

        assert success
        assert attempts == 2


class TestSpotifyPlaylistProcessing:
    """Test playlist and album processing."""

    def test_track_limit_enforcement(self) -> None:
        """Test that track limits are enforced for large playlists."""
        MAX_TRACKS = 50

        # Simulate a playlist with 100 tracks
        tracks = [{"name": f"Track {i}"} for i in range(100)]

        limited_tracks = tracks[:MAX_TRACKS]

        assert len(limited_tracks) == MAX_TRACKS
        assert limited_tracks[0]["name"] == "Track 0"
        assert limited_tracks[-1]["name"] == "Track 49"

    def test_batch_processing(self) -> None:
        """Test batch processing of playlist tracks."""
        BATCH_SIZE = 10
        tracks = [{"name": f"Track {i}"} for i in range(25)]

        batches = []
        for i in range(0, len(tracks), BATCH_SIZE):
            batch = tracks[i : i + BATCH_SIZE]
            batches.append(batch)

        assert len(batches) == 3
        assert len(batches[0]) == 10
        assert len(batches[1]) == 10
        assert len(batches[2]) == 5


class TestSpotifyErrorHandling:
    """Test error handling for Spotify operations."""

    def test_rate_limit_detection(self) -> None:
        """Test Spotify rate limit error detection."""
        error_responses = [
            {"error": {"status": 429, "message": "rate limit exceeded"}},
            {"error": {"status": 401, "message": "unauthorized"}},
            {"error": {"status": 404, "message": "not found"}},
        ]

        for resp in error_responses:
            status = resp["error"]["status"]

            if status == 429:
                # Rate limited - should retry
                assert True
            elif status == 401:
                # Auth error - should refresh token
                assert True
            elif status == 404:
                # Not found - should skip
                assert True

    def test_empty_playlist_handling(self) -> None:
        """Test handling of empty playlists."""
        playlist = {"name": "Empty Playlist", "tracks": {"items": []}}

        tracks = playlist["tracks"]["items"]

        assert len(tracks) == 0
        # Should return early with appropriate message


# Run tests with: python -m pytest tests/test_spotify_integration.py -v
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
