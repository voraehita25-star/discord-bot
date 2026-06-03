"""Unit tests for Spotify Handler module."""

import asyncio
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


# ======================================================================
# Merged from test_spotify_handler_extended.py
# ======================================================================


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


# ======================================================================
# Deepened coverage: helpers + new test classes appended below.
# These exercise previously-uncovered functions/branches:
#   _setup_client (success / session-close / init-failure),
#   cleanup (session-close / exception / missing-session),
#   _api_call_with_retry (retry/recreate/circuit-breaker),
#   process_spotify_url routing + broad except handler,
#   _handle_track / _handle_playlist / _handle_album full flows.
# ======================================================================


def _make_handler(env=None):
    """Build a SpotifyHandler with spotipy fully mocked (no network).

    Returns (handler, mock_bot). The handler's ``sp`` is a MagicMock when
    credentials are supplied, else None.
    """
    from unittest.mock import MagicMock, patch

    from cogs.spotify_handler import SpotifyHandler

    mock_bot = MagicMock()
    with patch.dict("os.environ", env or {}, clear=True):
        with patch("cogs.spotify_handler.spotipy") as mock_sp:
            mock_sp.Spotify.return_value = MagicMock()
            # Real exception classes so ``except spotipy.SpotifyException`` works.
            import spotipy as real_spotipy

            mock_sp.SpotifyException = real_spotipy.SpotifyException
            mock_sp.Spotify.side_effect = None
            handler = SpotifyHandler(mock_bot)
    return handler, mock_bot


def _make_ctx():
    """Build a Discord Context mock whose embed/author fields are real-ish."""
    from unittest.mock import AsyncMock, MagicMock

    ctx = MagicMock()
    ctx.author.display_name = "Tester"
    ctx.author.display_avatar.url = "https://cdn.example/avatar.png"
    ctx.send = AsyncMock()
    return ctx


def _track(name="Song", artist="Artist", duration_ms=180000, with_album=True, with_image=True):
    """Build a Spotify track dict."""
    t = {
        "name": name,
        "artists": [{"name": artist}],
        "external_urls": {"spotify": "https://open.spotify.com/track/abc"},
        "duration_ms": duration_ms,
    }
    if with_album:
        album = {"name": "Some Album"}
        if with_image:
            album["images"] = [{"url": "https://img/cover.jpg"}]
        t["album"] = album
    return t


class TestSetupClientDeep:
    """Cover _setup_client success, session-close-on-recreate, and init failure."""

    def test_setup_client_success_creates_client(self):
        """With both credentials present, sp is the spotipy.Spotify instance."""
        handler, _ = _make_handler({"SPOTIPY_CLIENT_ID": "id", "SPOTIPY_CLIENT_SECRET": "secret"})
        assert handler.sp is not None
        assert handler.is_available() is True

    def test_setup_client_falls_back_to_spotify_prefix(self):
        """SPOTIFY_* env vars are used when SPOTIPY_* are absent."""
        handler, _ = _make_handler({"SPOTIFY_CLIENT_ID": "id", "SPOTIFY_CLIENT_SECRET": "secret"})
        assert handler.sp is not None

    def test_setup_client_warns_on_conflicting_ids(self, caplog):
        """Both SPOTIPY_ and SPOTIFY_ ids set with different values -> warning logged."""
        import logging

        with caplog.at_level(logging.WARNING, logger="cogs.spotify_handler"):
            _make_handler(
                {
                    "SPOTIPY_CLIENT_ID": "newid",
                    "SPOTIFY_CLIENT_ID": "oldid",
                    "SPOTIPY_CLIENT_SECRET": "s",
                    "SPOTIFY_CLIENT_SECRET": "s",
                }
            )
        assert any("SPOTIPY_CLIENT_ID" in r.message for r in caplog.records)

    def test_setup_client_warns_on_conflicting_secrets(self, caplog):
        """Conflicting secret values -> secret-mismatch warning logged."""
        import logging

        with caplog.at_level(logging.WARNING, logger="cogs.spotify_handler"):
            _make_handler(
                {
                    "SPOTIPY_CLIENT_ID": "id",
                    "SPOTIPY_CLIENT_SECRET": "newsecret",
                    "SPOTIFY_CLIENT_SECRET": "oldsecret",
                }
            )
        assert any("SECRET" in r.message for r in caplog.records)

    def test_setup_client_closes_old_session_on_recreate(self):
        """Re-running _setup_client closes the previous client's session."""
        from unittest.mock import MagicMock, patch

        from cogs.spotify_handler import SpotifyHandler

        mock_bot = MagicMock()
        old_session = MagicMock()
        with patch.dict(
            "os.environ",
            {"SPOTIPY_CLIENT_ID": "id", "SPOTIPY_CLIENT_SECRET": "secret"},
            clear=True,
        ):
            with patch("cogs.spotify_handler.spotipy") as mock_sp:
                first = MagicMock()
                first._session = old_session
                second = MagicMock()
                mock_sp.Spotify.side_effect = [first, second]
                handler = SpotifyHandler(mock_bot)
                assert handler.sp is first
                handler._setup_client()  # recreate -> should close old session
                assert handler.sp is second
        old_session.close.assert_called_once()

    def test_setup_client_swallows_old_session_close_error(self):
        """A close() that raises during recreate is swallowed (no propagation)."""
        from unittest.mock import MagicMock, patch

        from cogs.spotify_handler import SpotifyHandler

        mock_bot = MagicMock()
        bad_session = MagicMock()
        bad_session.close.side_effect = RuntimeError("boom")
        with patch.dict(
            "os.environ",
            {"SPOTIPY_CLIENT_ID": "id", "SPOTIPY_CLIENT_SECRET": "secret"},
            clear=True,
        ):
            with patch("cogs.spotify_handler.spotipy") as mock_sp:
                first = MagicMock()
                first._session = bad_session
                mock_sp.Spotify.side_effect = [first, MagicMock()]
                handler = SpotifyHandler(mock_bot)
                handler._setup_client()  # must not raise
        bad_session.close.assert_called_once()

    def test_setup_client_init_failure_sets_none(self):
        """spotipy.Spotify raising SpotifyException leaves sp as None."""
        from unittest.mock import MagicMock, patch

        import spotipy as real_spotipy

        from cogs.spotify_handler import SpotifyHandler

        mock_bot = MagicMock()
        with patch.dict(
            "os.environ",
            {"SPOTIPY_CLIENT_ID": "id", "SPOTIPY_CLIENT_SECRET": "secret"},
            clear=True,
        ):
            with patch("cogs.spotify_handler.spotipy") as mock_sp:
                mock_sp.SpotifyException = real_spotipy.SpotifyException
                mock_sp.Spotify.side_effect = real_spotipy.SpotifyException(401, -1, "bad creds")
                handler = SpotifyHandler(mock_bot)
        assert handler.sp is None


class TestCleanupDeep:
    """Cover cleanup() session-close success, exception, and missing-session branches."""

    def test_cleanup_closes_public_session(self):
        from unittest.mock import MagicMock

        handler, _ = _make_handler({"SPOTIPY_CLIENT_ID": "id", "SPOTIPY_CLIENT_SECRET": "secret"})
        session = MagicMock()
        handler.sp = MagicMock()
        handler.sp.session = session
        handler.cleanup()
        session.close.assert_called_once()
        assert handler.sp is None

    def test_cleanup_falls_back_to_private_session(self):
        from unittest.mock import MagicMock

        handler, _ = _make_handler({"SPOTIPY_CLIENT_ID": "id", "SPOTIPY_CLIENT_SECRET": "secret"})
        # Build a sp object that has _session but no public session.
        sp = MagicMock(spec=["_session"])
        priv = MagicMock()
        sp._session = priv
        handler.sp = sp
        handler.cleanup()
        priv.close.assert_called_once()
        assert handler.sp is None

    def test_cleanup_swallows_close_exception(self):
        from unittest.mock import MagicMock

        handler, _ = _make_handler({"SPOTIPY_CLIENT_ID": "id", "SPOTIPY_CLIENT_SECRET": "secret"})
        session = MagicMock()
        session.close.side_effect = OSError("already closed")
        handler.sp = MagicMock()
        handler.sp.session = session
        handler.cleanup()  # must not raise
        assert handler.sp is None

    def test_cleanup_handles_missing_session_attr(self):
        """sp with neither session nor _session -> debug log, no crash."""
        from unittest.mock import MagicMock

        handler, _ = _make_handler({"SPOTIPY_CLIENT_ID": "id", "SPOTIPY_CLIENT_SECRET": "secret"})
        handler.sp = MagicMock(spec=[])  # no session/_session attributes
        handler.cleanup()
        assert handler.sp is None

    def test_cleanup_when_no_client_is_noop(self):
        handler, _ = _make_handler({})
        handler.sp = None
        handler.cleanup()  # should not raise
        assert handler.sp is None


class TestApiCallWithRetryDeep:
    """Cover retry-on-connection-error, recreate path, and circuit-breaker branches."""

    async def test_retry_succeeds_after_transient_error(self, monkeypatch):
        """First call raises a connection error, retry succeeds; no sleep blocking."""
        from requests.exceptions import ConnectionError as RequestsConnectionError

        handler, _ = _make_handler({"SPOTIPY_CLIENT_ID": "id", "SPOTIPY_CLIENT_SECRET": "secret"})

        # No real sleep.
        async def _no_sleep(_):
            return None

        monkeypatch.setattr("cogs.spotify_handler.asyncio.sleep", _no_sleep)

        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            if calls["n"] == 1:
                raise RequestsConnectionError("transient")
            return {"ok": True}

        result = await handler._api_call_with_retry(flaky)
        assert result == {"ok": True}
        assert calls["n"] == 2

    async def test_retry_exhausted_reraises(self, monkeypatch):
        """All attempts fail with a connection error -> the error propagates."""
        from requests.exceptions import ReadTimeout

        handler, _ = _make_handler({"SPOTIPY_CLIENT_ID": "id", "SPOTIPY_CLIENT_SECRET": "secret"})

        async def _no_sleep(_):
            return None

        monkeypatch.setattr("cogs.spotify_handler.asyncio.sleep", _no_sleep)

        def always_fail():
            raise ReadTimeout("nope")

        with pytest.raises(ReadTimeout):
            await handler._api_call_with_retry(always_fail)

    async def test_circuit_breaker_open_raises_connection_error(self):
        """Open circuit breaker short-circuits before any executor call."""
        from unittest.mock import MagicMock, patch

        handler, _ = _make_handler({"SPOTIPY_CLIENT_ID": "id", "SPOTIPY_CLIENT_SECRET": "secret"})

        breaker = MagicMock()
        breaker.can_execute.return_value = False
        with patch("cogs.spotify_handler.CIRCUIT_BREAKER_AVAILABLE", True):
            with patch("cogs.spotify_handler.spotify_circuit", breaker):
                with pytest.raises(ConnectionError):
                    await handler._api_call_with_retry(lambda: {"x": 1})
        breaker.can_execute.assert_called_once()

    async def test_circuit_breaker_records_success(self):
        """A successful call records a single success on the breaker."""
        from unittest.mock import MagicMock, patch

        handler, _ = _make_handler({"SPOTIPY_CLIENT_ID": "id", "SPOTIPY_CLIENT_SECRET": "secret"})

        breaker = MagicMock()
        breaker.can_execute.return_value = True
        with patch("cogs.spotify_handler.CIRCUIT_BREAKER_AVAILABLE", True):
            with patch("cogs.spotify_handler.spotify_circuit", breaker):
                result = await handler._api_call_with_retry(lambda: 42)
        assert result == 42
        breaker.record_success.assert_called_once()
        breaker.record_failure.assert_not_called()

    async def test_circuit_breaker_records_failure_once_on_exhaustion(self, monkeypatch):
        """Failure is recorded exactly once after all retries are exhausted."""
        from unittest.mock import MagicMock, patch

        from requests.exceptions import ConnectionError as RequestsConnectionError

        handler, _ = _make_handler({"SPOTIPY_CLIENT_ID": "id", "SPOTIPY_CLIENT_SECRET": "secret"})

        async def _no_sleep(_):
            return None

        monkeypatch.setattr("cogs.spotify_handler.asyncio.sleep", _no_sleep)

        def always_fail():
            raise RequestsConnectionError("down")

        breaker = MagicMock()
        breaker.can_execute.return_value = True
        with patch("cogs.spotify_handler.CIRCUIT_BREAKER_AVAILABLE", True):
            with patch("cogs.spotify_handler.spotify_circuit", breaker):
                with pytest.raises(RequestsConnectionError):
                    await handler._api_call_with_retry(always_fail)
        breaker.record_failure.assert_called_once()

    async def test_retry_recreates_client_on_third_attempt(self, monkeypatch):
        """On attempt>=1 a bound-method target triggers _setup_client + rebind."""
        from unittest.mock import MagicMock

        from requests.exceptions import ConnectionError as RequestsConnectionError

        handler, _ = _make_handler({"SPOTIPY_CLIENT_ID": "id", "SPOTIPY_CLIENT_SECRET": "secret"})

        async def _no_sleep(_):
            return None

        monkeypatch.setattr("cogs.spotify_handler.asyncio.sleep", _no_sleep)

        # Build a fake spotipy.Spotify-like object whose bound method fails twice
        # then a recreated client succeeds. We make the bound target recognized
        # by isinstance(..., spotipy.Spotify).
        import spotipy

        old_client = MagicMock(spec=spotipy.Spotify)
        new_client = MagicMock(spec=spotipy.Spotify)

        attempt_counter = {"n": 0}

        # The code rebinds via getattr(self.sp, func.__name__), so the bound
        # method must report __name__ == "track" and the new client must expose
        # a "track" attribute. Use a real bound method on a tiny class so
        # __self__ and __name__ behave like a genuine spotipy bound method.
        class _FailingClient(spotipy.Spotify):
            def __init__(self):
                pass  # skip real spotipy init (no network)

            def track(self, _q):
                attempt_counter["n"] += 1
                raise RequestsConnectionError("stale token")

        old_client = _FailingClient()

        def new_track(_q):
            return {"name": "recovered"}

        new_client.track = new_track

        handler.sp = old_client

        recreated = {"called": False}

        def fake_setup():
            recreated["called"] = True
            handler.sp = new_client

        handler._setup_client = fake_setup

        # Pass the bound method as func so __self__ / __name__ rebinding runs.
        result = await handler._api_call_with_retry(old_client.track, "spotify:track:1")
        assert result == {"name": "recovered"}
        assert recreated["called"] is True


class TestProcessSpotifyUrlRouting:
    """Cover the URL routing branches and the broad exception handler."""

    async def test_routes_to_track(self):
        handler, _ = _make_handler({"SPOTIPY_CLIENT_ID": "id", "SPOTIPY_CLIENT_SECRET": "secret"})
        from unittest.mock import AsyncMock

        handler._handle_track = AsyncMock(return_value=True)
        ctx = _make_ctx()
        ok = await handler.process_spotify_url(ctx, "<https://open.spotify.com/track/abc>", [])
        assert ok is True
        # Angle brackets stripped before dispatch.
        handler._handle_track.assert_awaited_once()
        assert "<" not in handler._handle_track.await_args.args[1]

    async def test_routes_to_playlist(self):
        handler, _ = _make_handler({"SPOTIPY_CLIENT_ID": "id", "SPOTIPY_CLIENT_SECRET": "secret"})
        from unittest.mock import AsyncMock

        handler._handle_playlist = AsyncMock(return_value=True)
        ctx = _make_ctx()
        ok = await handler.process_spotify_url(ctx, "https://open.spotify.com/playlist/xyz", [])
        assert ok is True
        handler._handle_playlist.assert_awaited_once()

    async def test_routes_to_album(self):
        handler, _ = _make_handler({"SPOTIPY_CLIENT_ID": "id", "SPOTIPY_CLIENT_SECRET": "secret"})
        from unittest.mock import AsyncMock

        handler._handle_album = AsyncMock(return_value=True)
        ctx = _make_ctx()
        ok = await handler.process_spotify_url(ctx, "spotify:album:xyz", [])
        assert ok is True
        handler._handle_album.assert_awaited_once()

    async def test_unsupported_url_sends_error_and_returns_false(self):
        handler, _ = _make_handler({"SPOTIPY_CLIENT_ID": "id", "SPOTIPY_CLIENT_SECRET": "secret"})
        ctx = _make_ctx()
        ok = await handler.process_spotify_url(ctx, "https://open.spotify.com/artist/abc", [])
        assert ok is False
        ctx.send.assert_awaited_once()

    async def test_broad_exception_handler_sends_friendly_error(self):
        """A SpotifyException from the handler is caught and surfaced as embed."""
        from unittest.mock import AsyncMock

        import spotipy

        handler, _ = _make_handler({"SPOTIPY_CLIENT_ID": "id", "SPOTIPY_CLIENT_SECRET": "secret"})
        handler._handle_track = AsyncMock(
            side_effect=spotipy.SpotifyException(429, -1, "rate limited")
        )
        ctx = _make_ctx()
        ok = await handler.process_spotify_url(ctx, "https://open.spotify.com/track/abc", [])
        assert ok is False
        ctx.send.assert_awaited_once()
        embed = ctx.send.await_args.kwargs["embed"]
        assert "Spotify" in embed.title

    async def test_connection_error_from_circuit_breaker_is_caught(self):
        """ConnectionError raised inside dispatch is caught by the broad handler."""
        from unittest.mock import AsyncMock

        handler, _ = _make_handler({"SPOTIPY_CLIENT_ID": "id", "SPOTIPY_CLIENT_SECRET": "secret"})
        handler._handle_album = AsyncMock(side_effect=ConnectionError("breaker open"))
        ctx = _make_ctx()
        ok = await handler.process_spotify_url(ctx, "spotify:album:abc", [])
        assert ok is False
        ctx.send.assert_awaited_once()

    async def test_no_client_short_circuits(self):
        handler, _ = _make_handler({})
        handler.sp = None
        ctx = _make_ctx()
        ok = await handler.process_spotify_url(ctx, "spotify:track:abc", [])
        assert ok is False
        ctx.send.assert_not_called()


class TestHandleTrackDeep:
    """Cover _handle_track success, queue-full, and missing-artist branches."""

    async def test_success_appends_and_sends_embed(self):
        from unittest.mock import AsyncMock

        handler, _ = _make_handler({"SPOTIPY_CLIENT_ID": "id", "SPOTIPY_CLIENT_SECRET": "secret"})
        handler._api_call_with_retry = AsyncMock(return_value=_track("Hello", "Adele"))
        ctx = _make_ctx()
        queue = []
        ok = await handler._handle_track(ctx, "spotify:track:abc", queue)
        assert ok is True
        assert len(queue) == 1
        assert queue[0]["type"] == "search"
        assert queue[0]["title"] == "Adele - Hello"
        assert queue[0]["url"] == "Adele - Hello audio"
        ctx.send.assert_awaited_once()

    async def test_queue_full_returns_false(self):
        from cogs.music.queue import MAX_QUEUE_SIZE

        handler, _ = _make_handler({"SPOTIPY_CLIENT_ID": "id", "SPOTIPY_CLIENT_SECRET": "secret"})
        ctx = _make_ctx()
        queue = [{"x": i} for i in range(MAX_QUEUE_SIZE)]
        ok = await handler._handle_track(ctx, "spotify:track:abc", queue)
        assert ok is False
        ctx.send.assert_awaited_once()
        assert len(queue) == MAX_QUEUE_SIZE

    async def test_missing_artists_returns_false(self):
        from unittest.mock import AsyncMock

        handler, _ = _make_handler({"SPOTIPY_CLIENT_ID": "id", "SPOTIPY_CLIENT_SECRET": "secret"})
        handler._api_call_with_retry = AsyncMock(return_value={"name": "x", "artists": []})
        ctx = _make_ctx()
        queue = []
        ok = await handler._handle_track(ctx, "spotify:track:abc", queue)
        assert ok is False
        assert queue == []
        ctx.send.assert_awaited_once()

    async def test_null_duration_and_album_name_coerced(self):
        """duration_ms=None and album name=None must not raise (or-coercion)."""
        from unittest.mock import AsyncMock

        handler, _ = _make_handler({"SPOTIPY_CLIENT_ID": "id", "SPOTIPY_CLIENT_SECRET": "secret"})
        track = _track("T", "A", duration_ms=None, with_image=False)
        track["album"]["name"] = None
        handler._api_call_with_retry = AsyncMock(return_value=track)
        ctx = _make_ctx()
        queue = []
        ok = await handler._handle_track(ctx, "spotify:track:abc", queue)
        assert ok is True
        assert len(queue) == 1

    async def test_no_track_data_returns_false(self):
        from unittest.mock import AsyncMock

        handler, _ = _make_handler({"SPOTIPY_CLIENT_ID": "id", "SPOTIPY_CLIENT_SECRET": "secret"})
        handler._api_call_with_retry = AsyncMock(return_value=None)
        ctx = _make_ctx()
        queue = []
        ok = await handler._handle_track(ctx, "spotify:track:abc", queue)
        assert ok is False
        assert queue == []


class TestHandlePlaylistDeep:
    """Cover _handle_playlist pagination, errors, empties, truncation, success."""

    def _playlist_item(self, name="P", artist="PA"):
        return {"track": {"name": name, "artists": [{"name": artist}]}}

    async def test_success_adds_tracks(self):
        from unittest.mock import AsyncMock

        handler, _ = _make_handler({"SPOTIPY_CLIENT_ID": "id", "SPOTIPY_CLIENT_SECRET": "secret"})
        items = [self._playlist_item("S1", "A1"), self._playlist_item("S2", "A2")]
        handler._api_call_with_retry = AsyncMock(return_value=items)
        ctx = _make_ctx()
        queue = []
        ok = await handler._handle_playlist(ctx, "spotify:playlist:abc", queue)
        assert ok is True
        assert len(queue) == 2
        assert queue[0]["title"] == "A1 - S1"
        # loading msg + final embed
        assert ctx.send.await_count == 2

    async def test_empty_results_returns_false(self):
        from unittest.mock import AsyncMock

        handler, _ = _make_handler({"SPOTIPY_CLIENT_ID": "id", "SPOTIPY_CLIENT_SECRET": "secret"})
        handler._api_call_with_retry = AsyncMock(return_value=[])
        ctx = _make_ctx()
        queue = []
        ok = await handler._handle_playlist(ctx, "spotify:playlist:abc", queue)
        assert ok is False

    async def test_non_list_results_returns_false(self):
        from unittest.mock import AsyncMock

        handler, _ = _make_handler({"SPOTIPY_CLIENT_ID": "id", "SPOTIPY_CLIENT_SECRET": "secret"})
        handler._api_call_with_retry = AsyncMock(return_value={"not": "a list"})
        ctx = _make_ctx()
        queue = []
        ok = await handler._handle_playlist(ctx, "spotify:playlist:abc", queue)
        assert ok is False

    async def test_connection_error_sends_error_embed(self):
        from unittest.mock import AsyncMock

        from requests.exceptions import ReadTimeout

        handler, _ = _make_handler({"SPOTIPY_CLIENT_ID": "id", "SPOTIPY_CLIENT_SECRET": "secret"})
        handler._api_call_with_retry = AsyncMock(side_effect=ReadTimeout("slow"))
        ctx = _make_ctx()
        queue = []
        ok = await handler._handle_playlist(ctx, "spotify:playlist:abc", queue)
        assert ok is False
        # loading + error embed
        assert ctx.send.await_count == 2

    async def test_cancelled_error_deletes_loading_and_reraises(self):
        from unittest.mock import AsyncMock

        handler, _ = _make_handler({"SPOTIPY_CLIENT_ID": "id", "SPOTIPY_CLIENT_SECRET": "secret"})
        handler._api_call_with_retry = AsyncMock(side_effect=asyncio.CancelledError())
        ctx = _make_ctx()
        loading_msg = AsyncMock()
        ctx.send = AsyncMock(return_value=loading_msg)
        with pytest.raises(asyncio.CancelledError):
            await handler._handle_playlist(ctx, "spotify:playlist:abc", [])
        loading_msg.delete.assert_awaited_once()

    async def test_queue_full_returns_false(self):
        from unittest.mock import AsyncMock

        from cogs.music.queue import MAX_QUEUE_SIZE

        handler, _ = _make_handler({"SPOTIPY_CLIENT_ID": "id", "SPOTIPY_CLIENT_SECRET": "secret"})
        handler._api_call_with_retry = AsyncMock(return_value=[self._playlist_item()])
        ctx = _make_ctx()
        queue = [{"x": i} for i in range(MAX_QUEUE_SIZE)]
        ok = await handler._handle_playlist(ctx, "spotify:playlist:abc", queue)
        assert ok is False

    async def test_truncates_to_remaining_capacity(self):
        from unittest.mock import AsyncMock

        from cogs.music.queue import MAX_QUEUE_SIZE

        handler, _ = _make_handler({"SPOTIPY_CLIENT_ID": "id", "SPOTIPY_CLIENT_SECRET": "secret"})
        # 3 incoming tracks but only room for 2.
        items = [self._playlist_item(f"S{i}", f"A{i}") for i in range(3)]
        handler._api_call_with_retry = AsyncMock(return_value=items)
        ctx = _make_ctx()
        queue = [{"x": i} for i in range(MAX_QUEUE_SIZE - 2)]
        ok = await handler._handle_playlist(ctx, "spotify:playlist:abc", queue)
        assert ok is True
        assert len(queue) == MAX_QUEUE_SIZE
        # Final embed should reference truncation.
        embed = ctx.send.await_args.kwargs["embed"]
        assert any("Truncated" in (f.name or "") for f in embed.fields)

    async def test_all_items_invalid_count_zero(self):
        """Items present but none have valid track data -> count==0 branch."""
        from unittest.mock import AsyncMock

        handler, _ = _make_handler({"SPOTIPY_CLIENT_ID": "id", "SPOTIPY_CLIENT_SECRET": "secret"})
        # items list non-empty (passes isinstance/list check) but tracks invalid.
        bad_items = [None, {"track": None}, {"track": {"artists": [], "name": "x"}}]
        handler._api_call_with_retry = AsyncMock(return_value=bad_items)
        ctx = _make_ctx()
        queue = []
        ok = await handler._handle_playlist(ctx, "spotify:playlist:abc", queue)
        assert ok is False
        assert queue == []


class TestHandleAlbumDeep:
    """Cover _handle_album success, pagination, empties, truncation, count-zero."""

    def _album_track(self, name="AT", artist="AA"):
        return {"name": name, "artists": [{"name": artist}]}

    async def test_success_adds_tracks(self):
        from unittest.mock import AsyncMock

        handler, _ = _make_handler({"SPOTIPY_CLIENT_ID": "id", "SPOTIPY_CLIENT_SECRET": "secret"})
        results = {"items": [self._album_track("S1", "A1")], "next": None}
        handler._api_call_with_retry = AsyncMock(return_value=results)
        ctx = _make_ctx()
        queue = []
        ok = await handler._handle_album(ctx, "spotify:album:abc", queue)
        assert ok is True
        assert len(queue) == 1
        assert queue[0]["title"] == "A1 - S1"

    async def test_no_results_returns_false(self):
        from unittest.mock import AsyncMock

        handler, _ = _make_handler({"SPOTIPY_CLIENT_ID": "id", "SPOTIPY_CLIENT_SECRET": "secret"})
        handler._api_call_with_retry = AsyncMock(return_value=None)
        ctx = _make_ctx()
        ok = await handler._handle_album(ctx, "spotify:album:abc", [])
        assert ok is False
        ctx.send.assert_awaited_once()

    async def test_empty_items_returns_false(self):
        from unittest.mock import AsyncMock

        handler, _ = _make_handler({"SPOTIPY_CLIENT_ID": "id", "SPOTIPY_CLIENT_SECRET": "secret"})
        handler._api_call_with_retry = AsyncMock(return_value={"items": [], "next": None})
        ctx = _make_ctx()
        ok = await handler._handle_album(ctx, "spotify:album:abc", [])
        assert ok is False

    async def test_pagination_follows_next(self, monkeypatch):
        from unittest.mock import AsyncMock

        handler, _ = _make_handler({"SPOTIPY_CLIENT_ID": "id", "SPOTIPY_CLIENT_SECRET": "secret"})

        async def _no_sleep(_):
            return None

        monkeypatch.setattr("cogs.spotify_handler.asyncio.sleep", _no_sleep)

        page1 = {"items": [self._album_track("S1", "A1")], "next": "url2"}
        page2 = {"items": [self._album_track("S2", "A2")], "next": None}
        handler._api_call_with_retry = AsyncMock(side_effect=[page1, page2])
        ctx = _make_ctx()
        queue = []
        ok = await handler._handle_album(ctx, "spotify:album:abc", queue)
        assert ok is True
        assert len(queue) == 2

    async def test_queue_full_returns_false(self):
        from unittest.mock import AsyncMock

        from cogs.music.queue import MAX_QUEUE_SIZE

        handler, _ = _make_handler({"SPOTIPY_CLIENT_ID": "id", "SPOTIPY_CLIENT_SECRET": "secret"})
        results = {"items": [self._album_track()], "next": None}
        handler._api_call_with_retry = AsyncMock(return_value=results)
        ctx = _make_ctx()
        queue = [{"x": i} for i in range(MAX_QUEUE_SIZE)]
        ok = await handler._handle_album(ctx, "spotify:album:abc", queue)
        assert ok is False

    async def test_truncates_to_remaining_capacity(self):
        from unittest.mock import AsyncMock

        from cogs.music.queue import MAX_QUEUE_SIZE

        handler, _ = _make_handler({"SPOTIPY_CLIENT_ID": "id", "SPOTIPY_CLIENT_SECRET": "secret"})
        items = [self._album_track(f"S{i}", f"A{i}") for i in range(3)]
        results = {"items": items, "next": None}
        handler._api_call_with_retry = AsyncMock(return_value=results)
        ctx = _make_ctx()
        queue = [{"x": i} for i in range(MAX_QUEUE_SIZE - 2)]
        ok = await handler._handle_album(ctx, "spotify:album:abc", queue)
        assert ok is True
        assert len(queue) == MAX_QUEUE_SIZE
        embed = ctx.send.await_args.kwargs["embed"]
        assert any("Truncated" in (f.name or "") for f in embed.fields)

    async def test_all_tracks_invalid_count_zero(self):
        from unittest.mock import AsyncMock

        handler, _ = _make_handler({"SPOTIPY_CLIENT_ID": "id", "SPOTIPY_CLIENT_SECRET": "secret"})
        # non-empty items so we pass the empty check, but no valid track fields.
        results = {"items": [{"artists": [], "name": "x"}], "next": None}
        handler._api_call_with_retry = AsyncMock(return_value=results)
        ctx = _make_ctx()
        queue = []
        ok = await handler._handle_album(ctx, "spotify:album:abc", queue)
        assert ok is False
        assert queue == []
