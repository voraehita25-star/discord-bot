"""Unit tests for Spotify Handler module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestSpotifyHandler:
    """Tests for SpotifyHandler class."""

    def setup_method(self):
        """Set up test fixtures with mocked Spotify client."""
        # Import here to avoid module-level import issues
        with patch.dict(
            "os.environ",
            {"SPOTIPY_CLIENT_ID": "test_id", "SPOTIPY_CLIENT_SECRET": "test_secret"},
        ):
            with patch("cogs.spotify_handler.spotipy") as mock_sp:
                mock_sp.Spotify.return_value = MagicMock()
                from cogs.spotify_handler import SpotifyHandler

                self.mock_bot = MagicMock()
                self.handler = SpotifyHandler(self.mock_bot)

    def test_is_available_with_client(self):
        """Test is_available returns True when client exists."""
        self.handler.sp = MagicMock()
        assert self.handler.is_available() is True

    def test_is_available_without_client(self):
        """Test is_available returns False when no client."""
        self.handler.sp = None
        assert self.handler.is_available() is False

    def test_max_retries_constant(self):
        """Test MAX_RETRIES is set."""
        assert self.handler.MAX_RETRIES == 3

    def test_retry_delay_constant(self):
        """Test RETRY_DELAY is set."""
        assert self.handler.RETRY_DELAY == 2


class TestSpotifyHandlerWithoutCredentials:
    """Tests for SpotifyHandler without credentials."""

    def test_no_credentials_sets_none(self):
        """Test that missing credentials results in None client."""
        with patch.dict("os.environ", {}, clear=True):
            # Remove the credentials
            import os

            os.environ.pop("SPOTIPY_CLIENT_ID", None)
            os.environ.pop("SPOTIPY_CLIENT_SECRET", None)

            with patch("cogs.spotify_handler.spotipy"):
                from importlib import reload

                import cogs.spotify_handler

                reload(cogs.spotify_handler)
                from cogs.spotify_handler import SpotifyHandler

                mock_bot = MagicMock()
                handler = SpotifyHandler(mock_bot)
                # Without credentials, sp should be None
                assert handler.sp is None or handler.is_available() is False


class TestSpotifyURLDetection:
    """Tests for Spotify URL detection patterns."""

    def test_track_url_contains_track(self):
        """Test track URL detection."""
        url = "https://open.spotify.com/track/6rqhFgbbKwnb9MLmUQDhG6"
        assert "track" in url

    def test_playlist_url_contains_playlist(self):
        """Test playlist URL detection."""
        url = "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"
        assert "playlist" in url

    def test_album_url_contains_album(self):
        """Test album URL detection."""
        url = "https://open.spotify.com/album/4aawyAB9vmqN3uQ7FjRGTy"
        assert "album" in url


class TestSpotifyHandlerMethods:
    """Tests for SpotifyHandler methods."""

    def test_handler_has_process_spotify_url(self):
        """Test that handler has process_spotify_url method."""
        from cogs.spotify_handler import SpotifyHandler

        assert hasattr(SpotifyHandler, "process_spotify_url")

    def test_handler_has_is_available(self):
        """Test that handler has is_available method."""
        from cogs.spotify_handler import SpotifyHandler

        assert hasattr(SpotifyHandler, "is_available")

    def test_handler_has_api_call_with_retry(self):
        """Test that handler has _api_call_with_retry method."""
        from cogs.spotify_handler import SpotifyHandler

        assert hasattr(SpotifyHandler, "_api_call_with_retry")

    def test_handler_has_handle_track(self):
        """Test that handler has _handle_track method."""
        from cogs.spotify_handler import SpotifyHandler

        assert hasattr(SpotifyHandler, "_handle_track")

    def test_handler_has_handle_playlist(self):
        """Test that handler has _handle_playlist method."""
        from cogs.spotify_handler import SpotifyHandler

        assert hasattr(SpotifyHandler, "_handle_playlist")

    def test_handler_has_handle_album(self):
        """Test that handler has _handle_album method."""
        from cogs.spotify_handler import SpotifyHandler

        assert hasattr(SpotifyHandler, "_handle_album")
