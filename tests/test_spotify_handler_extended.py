"""
Extended tests for Spotify Handler module.
Tests Spotify URL processing and API calls.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestSpotifyHandlerInit:
    """Tests for SpotifyHandler initialization."""

    def test_spotify_handler_init_with_mock(self):
        """Test SpotifyHandler initializes correctly."""
        try:
            from cogs.spotify_handler import SpotifyHandler
        except ImportError:
            pytest.skip("spotify_handler not available")
            return

        mock_bot = MagicMock()

        with patch.dict("os.environ", {}, clear=True):
            handler = SpotifyHandler(mock_bot)

        assert handler.bot == mock_bot
        assert handler.sp is None  # No credentials

    def test_spotify_handler_max_retries(self):
        """Test MAX_RETRIES constant."""
        try:
            from cogs.spotify_handler import SpotifyHandler
        except ImportError:
            pytest.skip("spotify_handler not available")
            return

        assert SpotifyHandler.MAX_RETRIES == 3

    def test_spotify_handler_retry_delay(self):
        """Test RETRY_DELAY constant."""
        try:
            from cogs.spotify_handler import SpotifyHandler
        except ImportError:
            pytest.skip("spotify_handler not available")
            return

        assert SpotifyHandler.RETRY_DELAY == 2


class TestIsAvailable:
    """Tests for is_available method."""

    def test_is_available_when_no_client(self):
        """Test is_available returns False when no client."""
        try:
            from cogs.spotify_handler import SpotifyHandler
        except ImportError:
            pytest.skip("spotify_handler not available")
            return

        mock_bot = MagicMock()

        with patch.dict("os.environ", {}, clear=True):
            handler = SpotifyHandler(mock_bot)

        assert handler.is_available() is False

    def test_is_available_when_client_exists(self):
        """Test is_available returns True when client exists."""
        try:
            from cogs.spotify_handler import SpotifyHandler
        except ImportError:
            pytest.skip("spotify_handler not available")
            return

        mock_bot = MagicMock()

        with patch.dict("os.environ", {}, clear=True):
            handler = SpotifyHandler(mock_bot)
            handler.sp = MagicMock()  # Manually set client

        assert handler.is_available() is True


class TestProcessSpotifyUrl:
    """Tests for process_spotify_url method."""

    @pytest.fixture
    def spotify_handler(self):
        """Create a SpotifyHandler with mock bot."""
        try:
            from cogs.spotify_handler import SpotifyHandler
        except ImportError:
            pytest.skip("spotify_handler not available")
            return None

        mock_bot = MagicMock()
        with patch.dict("os.environ", {}, clear=True):
            handler = SpotifyHandler(mock_bot)
        return handler

    async def test_process_spotify_url_no_client(self, spotify_handler):
        """Test process_spotify_url returns False when no client."""
        if spotify_handler is None:
            pytest.skip("spotify_handler not available")
            return

        mock_ctx = MagicMock()
        queue = []

        result = await spotify_handler.process_spotify_url(mock_ctx, "spotify:track:123", queue)

        assert result is False

    async def test_process_spotify_url_unsupported_type(self, spotify_handler):
        """Test process_spotify_url handles unsupported URL types."""
        if spotify_handler is None:
            pytest.skip("spotify_handler not available")
            return

        spotify_handler.sp = MagicMock()

        mock_ctx = MagicMock()
        mock_ctx.send = AsyncMock()
        queue = []

        result = await spotify_handler.process_spotify_url(
            mock_ctx, "https://open.spotify.com/artist/123", queue
        )

        assert result is False
        mock_ctx.send.assert_called_once()


class TestHandleTrack:
    """Tests for _handle_track method."""

    async def test_handle_track_no_track_data(self):
        """Test _handle_track returns False when track not found."""
        try:
            from cogs.spotify_handler import SpotifyHandler
        except ImportError:
            pytest.skip("spotify_handler not available")
            return

        mock_bot = MagicMock()
        with patch.dict("os.environ", {}, clear=True):
            handler = SpotifyHandler(mock_bot)
        handler.sp = MagicMock()

        mock_ctx = MagicMock()
        mock_ctx.send = AsyncMock()
        queue = []

        handler._api_call_with_retry = AsyncMock(return_value=None)

        result = await handler._handle_track(mock_ctx, "https://open.spotify.com/track/123", queue)

        assert result is False


class TestSetupClient:
    """Tests for _setup_client method."""

    def test_setup_client_no_credentials(self):
        """Test _setup_client with no credentials."""
        try:
            from cogs.spotify_handler import SpotifyHandler
        except ImportError:
            pytest.skip("spotify_handler not available")
            return

        mock_bot = MagicMock()

        with patch.dict("os.environ", {}, clear=True):
            handler = SpotifyHandler(mock_bot)

        assert handler.sp is None

    def test_setup_client_partial_credentials(self):
        """Test _setup_client with only client_id."""
        try:
            from cogs.spotify_handler import SpotifyHandler
        except ImportError:
            pytest.skip("spotify_handler not available")
            return

        mock_bot = MagicMock()

        with patch.dict("os.environ", {"SPOTIPY_CLIENT_ID": "test_id"}, clear=True):
            handler = SpotifyHandler(mock_bot)

        assert handler.sp is None


class TestApiCallWithRetry:
    """Tests for _api_call_with_retry method."""

    async def test_api_call_with_retry_success(self):
        """Test _api_call_with_retry successful call."""
        try:
            from cogs.spotify_handler import SpotifyHandler
        except ImportError:
            pytest.skip("spotify_handler not available")
            return

        mock_bot = MagicMock()
        mock_bot.loop = asyncio.new_event_loop()

        with patch.dict("os.environ", {}, clear=True):
            handler = SpotifyHandler(mock_bot)

        mock_func = MagicMock(return_value={"name": "Test Track"})

        with patch.object(handler.bot.loop, "run_in_executor", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = {"name": "Test Track"}
            result = await handler._api_call_with_retry(mock_func, "arg1")

        assert result == {"name": "Test Track"}


class TestCircuitBreakerIntegration:
    """Tests for circuit breaker integration."""

    def test_circuit_breaker_available_defined(self):
        """Test CIRCUIT_BREAKER_AVAILABLE is defined."""
        try:
            from cogs.spotify_handler import CIRCUIT_BREAKER_AVAILABLE
        except ImportError:
            pytest.skip("spotify_handler not available")
            return

        assert isinstance(CIRCUIT_BREAKER_AVAILABLE, bool)


class TestModuleImports:
    """Tests for module imports."""

    def test_colors_imported(self):
        """Test Colors is imported."""
        try:
            from cogs.music.utils import Colors
        except ImportError:
            pytest.skip("music.utils not available")
            return

        assert Colors is not None

    def test_emojis_imported(self):
        """Test Emojis is imported."""
        try:
            from cogs.music.utils import Emojis
        except ImportError:
            pytest.skip("music.utils not available")
            return

        assert Emojis is not None


class TestModuleDocstring:
    """Tests for module documentation."""

    def test_module_has_docstring(self):
        """Test spotify_handler module has docstring."""
        try:
            from cogs import spotify_handler
        except ImportError:
            pytest.skip("spotify_handler not available")
            return

        assert spotify_handler.__doc__ is not None


class TestSpotifyHandlerConstants:
    """Tests for SpotifyHandler class constants."""

    def test_class_has_max_retries(self):
        """Test class has MAX_RETRIES attribute."""
        try:
            from cogs.spotify_handler import SpotifyHandler
        except ImportError:
            pytest.skip("spotify_handler not available")
            return

        assert hasattr(SpotifyHandler, "MAX_RETRIES")
        assert isinstance(SpotifyHandler.MAX_RETRIES, int)

    def test_class_has_retry_delay(self):
        """Test class has RETRY_DELAY attribute."""
        try:
            from cogs.spotify_handler import SpotifyHandler
        except ImportError:
            pytest.skip("spotify_handler not available")
            return

        assert hasattr(SpotifyHandler, "RETRY_DELAY")
        assert isinstance(SpotifyHandler.RETRY_DELAY, int)
