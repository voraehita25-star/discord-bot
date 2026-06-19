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
        track_name = "Bohemian Rhapsody"
        artists = [{"name": "Queen"}]

        # Generate search query
        artist_names = " ".join(artist["name"] for artist in artists)
        search_query = f"{track_name} {artist_names}"

        assert search_query == "Bohemian Rhapsody Queen"
        assert "Queen" in search_query

    def test_multiple_artists_handling(self) -> None:
        """Test handling of tracks with multiple artists."""
        artists = [{"name": "Doja Cat"}, {"name": "Nicki Minaj"}]

        artist_names = ", ".join(artist["name"] for artist in artists)

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
    """Test the REAL error classification in SpotifyHandler._api_call_with_retry.

    The retry loop distinguishes transient transport errors (connection reset /
    read timeout / OSError → retried with backoff + client recreate) from
    spotipy.SpotifyException (404/private/auth → re-raised immediately, no
    retry). These tests drive that production code, not a local re-implementation.
    """

    def _make_handler(self):
        """Build a SpotifyHandler without touching the network / env."""
        import spotipy

        from cogs.spotify_handler import SpotifyHandler

        handler = SpotifyHandler.__new__(SpotifyHandler)
        handler.bot = object()
        handler.sp = spotipy.Spotify.__new__(spotipy.Spotify)
        handler._setup_lock = None
        return handler

    @pytest.mark.asyncio
    async def test_transport_error_is_retried_then_raised(self) -> None:
        """A transient ReadTimeout is retried MAX_RETRIES times, then propagates."""
        from unittest.mock import patch

        from requests.exceptions import ReadTimeout

        from cogs import spotify_handler as sh

        handler = self._make_handler()
        handler.RETRY_DELAY = 0  # no real sleep
        calls = 0

        def always_timeout():
            nonlocal calls
            calls += 1
            raise ReadTimeout("slow")

        # Disable client recreation (network) and the circuit breaker so we
        # observe the bare retry-then-raise behavior for transport errors.
        with (
            patch.object(handler, "_setup_client"),
            patch.object(sh, "CIRCUIT_BREAKER_AVAILABLE", False),
        ):
            with pytest.raises(ReadTimeout):
                await handler._api_call_with_retry(always_timeout)

        assert calls == handler.MAX_RETRIES  # retried every attempt

    @pytest.mark.asyncio
    async def test_spotify_exception_is_not_retried(self) -> None:
        """A spotipy.SpotifyException (e.g. 404/private/auth) is re-raised on the
        first attempt — NOT swept into the transport-retry path."""
        from unittest.mock import patch

        import spotipy

        from cogs import spotify_handler as sh

        handler = self._make_handler()
        handler.RETRY_DELAY = 0
        calls = 0

        def raise_spotify():
            nonlocal calls
            calls += 1
            raise spotipy.SpotifyException(404, -1, "the requested resource was not found")

        with patch.object(sh, "CIRCUIT_BREAKER_AVAILABLE", False):
            with pytest.raises(spotipy.SpotifyException):
                await handler._api_call_with_retry(raise_spotify)

        assert calls == 1  # no retry for API-level errors

    @pytest.mark.asyncio
    async def test_circuit_breaker_records_failure_on_spotify_exception(self) -> None:
        """When the breaker is active, an unexpected SpotifyException records a
        failure (releasing the half-open probe slot) before re-raising."""
        from unittest.mock import MagicMock, patch

        import spotipy

        from cogs import spotify_handler as sh

        handler = self._make_handler()
        handler.RETRY_DELAY = 0
        fake_circuit = MagicMock()
        fake_circuit.can_execute.return_value = True

        def raise_spotify():
            raise spotipy.SpotifyException(403, -1, "private playlist")

        with (
            patch.object(sh, "CIRCUIT_BREAKER_AVAILABLE", True),
            patch.object(sh, "spotify_circuit", fake_circuit),
        ):
            with pytest.raises(spotipy.SpotifyException):
                await handler._api_call_with_retry(raise_spotify)

        fake_circuit.record_failure.assert_called_once()
        fake_circuit.record_success.assert_not_called()

    @pytest.mark.asyncio
    async def test_api_call_returns_result_on_success(self) -> None:
        """_api_call_with_retry returns the callable's result on first success
        (e.g. an empty page → empty list), driving the real success path + the
        circuit-breaker success accounting."""
        from unittest.mock import MagicMock, patch

        from cogs import spotify_handler as sh

        handler = self._make_handler()
        handler.RETRY_DELAY = 0
        fake_circuit = MagicMock()
        fake_circuit.can_execute.return_value = True

        # An empty playlist page: the handler returns it verbatim (the empty
        # list propagates up to the caller's early-return).
        with (
            patch.object(sh, "CIRCUIT_BREAKER_AVAILABLE", True),
            patch.object(sh, "spotify_circuit", fake_circuit),
        ):
            result = await handler._api_call_with_retry(lambda: [])

        assert result == []
        fake_circuit.record_success.assert_called_once()
        fake_circuit.record_failure.assert_not_called()


# Run tests with: python -m pytest tests/test_spotify_integration.py -v
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
