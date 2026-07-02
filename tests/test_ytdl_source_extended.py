"""
Extended tests for YTDL Source module.
Tests configuration and constants.
"""

import pytest


class TestYtdlOptsHq:
    """Tests for ytdl_opts_hq configuration."""

    def test_ytdl_opts_hq_exists(self):
        """Test ytdl_opts_hq is defined."""
        from utils.media.ytdl_source import ytdl_opts_hq

        assert ytdl_opts_hq is not None

    def test_ytdl_opts_hq_is_dict(self):
        """Test ytdl_opts_hq is a dictionary."""
        from utils.media.ytdl_source import ytdl_opts_hq

        assert isinstance(ytdl_opts_hq, dict)

    def test_ytdl_opts_hq_has_format(self):
        """Test ytdl_opts_hq has format key."""
        from utils.media.ytdl_source import ytdl_opts_hq

        assert "format" in ytdl_opts_hq

    def test_ytdl_opts_hq_format_contains_opus(self):
        """Test ytdl_opts_hq format prefers opus."""
        from utils.media.ytdl_source import ytdl_opts_hq

        assert "opus" in ytdl_opts_hq["format"]

    def test_ytdl_opts_hq_has_noplaylist(self):
        """Test ytdl_opts_hq has noplaylist True."""
        from utils.media.ytdl_source import ytdl_opts_hq

        assert ytdl_opts_hq.get("noplaylist") is True

    def test_ytdl_opts_hq_has_quiet(self):
        """Test ytdl_opts_hq has quiet True."""
        from utils.media.ytdl_source import ytdl_opts_hq

        assert ytdl_opts_hq.get("quiet") is True

    def test_ytdl_opts_hq_has_extractor_args(self):
        """Test ytdl_opts_hq has extractor_args."""
        from utils.media.ytdl_source import ytdl_opts_hq

        assert "extractor_args" in ytdl_opts_hq

    def test_ytdl_opts_hq_has_postprocessors(self):
        """Test ytdl_opts_hq has postprocessors."""
        from utils.media.ytdl_source import ytdl_opts_hq

        assert "postprocessors" in ytdl_opts_hq

    def test_ytdl_opts_hq_geo_bypass(self):
        """Test ytdl_opts_hq has geo_bypass True."""
        from utils.media.ytdl_source import ytdl_opts_hq

        assert ytdl_opts_hq.get("geo_bypass") is True


class TestGetCookieOpts:
    """Tests for get_cookie_opts function."""

    def test_get_cookie_opts_exists(self):
        """Test get_cookie_opts function exists."""
        from utils.media.ytdl_source import get_cookie_opts

        assert callable(get_cookie_opts)

    def test_get_cookie_opts_returns_dict(self):
        """Test get_cookie_opts returns a dict."""
        from utils.media.ytdl_source import get_cookie_opts

        result = get_cookie_opts()
        assert isinstance(result, dict)


class TestGetFfmpegOptions:
    """Tests for get_ffmpeg_options function."""

    def test_get_ffmpeg_options_exists(self):
        """Test get_ffmpeg_options function exists."""
        from utils.media.ytdl_source import get_ffmpeg_options

        assert callable(get_ffmpeg_options)

    def test_get_ffmpeg_options_returns_dict(self):
        """Test get_ffmpeg_options returns a dict."""
        from utils.media.ytdl_source import get_ffmpeg_options

        result = get_ffmpeg_options()
        assert isinstance(result, dict)

    def test_get_ffmpeg_options_has_before_options(self):
        """Test get_ffmpeg_options has before_options."""
        from utils.media.ytdl_source import get_ffmpeg_options

        result = get_ffmpeg_options()
        assert "before_options" in result

    def test_get_ffmpeg_options_has_options(self):
        """Test get_ffmpeg_options has options."""
        from utils.media.ytdl_source import get_ffmpeg_options

        result = get_ffmpeg_options()
        assert "options" in result


class TestYtdlSourceClass:
    """Tests for YTDLSource class."""

    def test_ytdl_source_class_exists(self):
        """Test YTDLSource class exists."""
        from utils.media.ytdl_source import YTDLSource

        assert YTDLSource is not None

    def test_ytdl_source_is_class(self):
        """Test YTDLSource is a class."""
        from utils.media.ytdl_source import YTDLSource

        assert isinstance(YTDLSource, type)


class TestModuleDocstring:
    """Tests for module documentation."""

    def test_module_docstring_mentions_youtube(self):
        """Test ytdl_source module docstring mentions YouTube."""
        from utils.media import ytdl_source

        assert "YouTube" in ytdl_source.__doc__ or "youtube" in ytdl_source.__doc__


class TestYtdlOptsQuality:
    """Tests for YTDL options quality settings."""

    def test_retries_value(self):
        """Test retries is set to a reasonable value."""
        from utils.media.ytdl_source import ytdl_opts_hq

        assert ytdl_opts_hq.get("retries") is not None
        assert isinstance(ytdl_opts_hq.get("retries"), int)

    def test_socket_timeout_value(self):
        """Test socket_timeout is set."""
        from utils.media.ytdl_source import ytdl_opts_hq

        assert ytdl_opts_hq.get("socket_timeout") is not None

    def test_buffersize_value(self):
        """Test buffersize is set."""
        from utils.media.ytdl_source import ytdl_opts_hq

        assert ytdl_opts_hq.get("buffersize") is not None


class TestDefaultSearch:
    """Tests for default search setting."""

    def test_default_search_is_ytsearch(self):
        """Test default_search is ytsearch."""
        from utils.media.ytdl_source import ytdl_opts_hq

        assert ytdl_opts_hq.get("default_search") == "ytsearch"


class TestUserAgent:
    """Tests for the User-Agent header.

    The embedded YoutubeDL API has no 'user_agent' param (that spelling is
    the --user-agent CLI flag only, silently ignored in params) — the real
    param is http_headers['User-Agent']. These pin the corrected form.
    """

    def test_user_agent_header_exists(self):
        from utils.media.ytdl_source import ytdl_opts_hq

        assert "user_agent" not in ytdl_opts_hq  # dead CLI-only key must stay gone
        assert "User-Agent" in ytdl_opts_hq.get("http_headers", {})

    def test_user_agent_contains_chrome(self):
        from utils.media.ytdl_source import ytdl_opts_hq

        assert "Chrome" in ytdl_opts_hq.get("http_headers", {}).get("User-Agent", "")


class TestSearchSourceQueryBuilding:
    """Tests for YTDLSource.search_source query construction.

    These are regression tests for the case-insensitive direct-URL check:
    an uppercase-scheme URL ('HTTP://...') must be routed through the
    direct-URL branch (SSRF-guarded), NOT mis-wrapped as a literal
    'ytsearch:HTTP://...' search term. Plain text still becomes a ytsearch
    query, and a normal lowercase http(s) URL stays a direct URL.

    Everything is mocked so no real network/yt-dlp work happens:
    - get_ytdl_hq() is patched to return a fake YoutubeDL whose
      extract_info() records the query string it was handed.
    - _is_private_url is patched to return False so the direct-URL
      branch's SSRF guard passes for the test URLs.
    """

    @staticmethod
    def _make_recorder():
        """Return (fake_ytdl, recorded) where recorded['query'] captures
        the exact string passed to extract_info()."""
        from unittest.mock import MagicMock

        recorded: dict[str, object] = {}

        def _extract_info(query, download=False):
            recorded["query"] = query
            # Minimal, valid yt-dlp-shaped result (no 'entries' so it is
            # returned as-is by search_source).
            return {"title": "stub", "url": "http://example.com/audio"}

        fake_ytdl = MagicMock()
        fake_ytdl.extract_info.side_effect = _extract_info
        return fake_ytdl, recorded

    @pytest.mark.asyncio
    async def test_uppercase_scheme_url_is_not_wrapped_as_ytsearch(self):
        """Regression: 'HTTP://...' is treated as a direct URL, not a search.

        The case-sensitive startswith bug would turn this into
        'ytsearch:HTTP://example.com/x'. The fixed code lowercases before
        the check, so the query handed to yt-dlp must remain the raw URL.
        """
        from unittest.mock import AsyncMock, patch

        from utils.media.ytdl_source import YTDLSource

        fake_ytdl, recorded = self._make_recorder()
        url = "HTTP://example.com/x"

        with (
            patch("utils.media.ytdl_source.get_ytdl_hq", return_value=fake_ytdl),
            patch(
                "utils.web.url_fetcher._is_private_url",
                new_callable=AsyncMock,
                return_value=False,
            ),
        ):
            result = await YTDLSource.search_source(url)

        assert result is not None
        # The recorded query must be the raw URL, NOT a ytsearch-wrapped one.
        assert recorded["query"] == url
        assert not str(recorded["query"]).startswith("ytsearch:")

    @pytest.mark.asyncio
    async def test_plain_text_becomes_ytsearch_query(self):
        """A plain text search term (no scheme) becomes 'ytsearch:<term>'."""
        from unittest.mock import patch

        from utils.media.ytdl_source import YTDLSource

        fake_ytdl, recorded = self._make_recorder()
        term = "never gonna give you up"

        # No _is_private_url patch needed: plain text never hits the SSRF
        # branch. If it did, that would itself be a bug.
        with patch("utils.media.ytdl_source.get_ytdl_hq", return_value=fake_ytdl):
            result = await YTDLSource.search_source(term)

        assert result is not None
        assert recorded["query"] == f"ytsearch:{term}"

    @pytest.mark.asyncio
    async def test_colon_text_query_is_not_rejected_as_url(self):
        """A 'word: rest' query (urlparse sees a scheme) still searches.

        'C418: Sweden' has a urlparse scheme of 'c418' but no '://', so the
        guard must NOT reject it and it must be wrapped as a ytsearch term.
        """
        from unittest.mock import patch

        from utils.media.ytdl_source import YTDLSource

        fake_ytdl, recorded = self._make_recorder()
        term = "C418: Sweden"

        with patch("utils.media.ytdl_source.get_ytdl_hq", return_value=fake_ytdl):
            result = await YTDLSource.search_source(term)

        assert result is not None
        assert recorded["query"] == f"ytsearch:{term}"

    @pytest.mark.asyncio
    async def test_lowercase_http_url_is_treated_as_direct_url(self):
        """A normal lowercase http URL stays a direct URL (no ytsearch wrap)."""
        from unittest.mock import AsyncMock, patch

        from utils.media.ytdl_source import YTDLSource

        fake_ytdl, recorded = self._make_recorder()
        url = "http://example.com/song.mp3"

        with (
            patch("utils.media.ytdl_source.get_ytdl_hq", return_value=fake_ytdl),
            patch(
                "utils.web.url_fetcher._is_private_url",
                new_callable=AsyncMock,
                return_value=False,
            ),
        ):
            result = await YTDLSource.search_source(url)

        assert result is not None
        assert recorded["query"] == url
        assert not str(recorded["query"]).startswith("ytsearch:")

    @pytest.mark.asyncio
    async def test_lowercase_https_url_is_treated_as_direct_url(self):
        """A normal lowercase https URL stays a direct URL (no ytsearch wrap)."""
        from unittest.mock import AsyncMock, patch

        from utils.media.ytdl_source import YTDLSource

        fake_ytdl, recorded = self._make_recorder()
        url = "https://example.com/track"

        with (
            patch("utils.media.ytdl_source.get_ytdl_hq", return_value=fake_ytdl),
            patch(
                "utils.web.url_fetcher._is_private_url",
                new_callable=AsyncMock,
                return_value=False,
            ),
        ):
            result = await YTDLSource.search_source(url)

        assert result is not None
        assert recorded["query"] == url
        assert not str(recorded["query"]).startswith("ytsearch:")

    @pytest.mark.asyncio
    async def test_direct_url_resolving_to_private_ip_is_rejected(self):
        """A direct URL whose host resolves private/internal is refused (SSRF)."""
        from unittest.mock import AsyncMock, patch

        from utils.media.ytdl_source import YTDLSource

        fake_ytdl, recorded = self._make_recorder()

        with (
            patch("utils.media.ytdl_source.get_ytdl_hq", return_value=fake_ytdl),
            patch(
                "utils.web.url_fetcher._is_private_url",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            result = await YTDLSource.search_source("http://127.0.0.1/internal")

        # Refused before any extract_info call.
        assert result is None
        assert "query" not in recorded


# ============================================================================
# NEW TESTS APPENDED BELOW — deepening coverage of uncovered branches.
# Everything is hermetic: no real network, no real yt-dlp, no real ffmpeg.
# ============================================================================


def _fake_audio_source():
    """Build a MagicMock that passes discord.PCMVolumeTransformer.__init__.

    The base constructor requires ``isinstance(src, discord.AudioSource)``
    and that ``src.is_opus()`` is falsy (PCM, not opus). A bare MagicMock
    fails the isinstance check and returns a truthy is_opus(), so we spec
    it to AudioSource and force is_opus() -> False.
    """
    from unittest.mock import MagicMock

    import discord

    src = MagicMock(spec=discord.AudioSource)
    src.is_opus.return_value = False
    return src


class TestGetCookieOptsBranches:
    """Cover both branches of get_cookie_opts (cookies.txt present vs absent)."""

    def test_returns_empty_when_cookies_file_absent(self):
        """No cookies.txt -> empty dict (the common production case)."""
        from unittest.mock import MagicMock, patch

        import utils.media.ytdl_source as mod

        fake_path = MagicMock()
        fake_path.exists.return_value = False
        with patch.object(mod, "Path", return_value=fake_path):
            result = mod.get_cookie_opts()
        assert result == {}

    def test_includes_cookiefile_when_cookies_file_exists(self):
        """cookies.txt present -> cookie_opts carries the cookiefile key."""
        from unittest.mock import MagicMock, patch

        import utils.media.ytdl_source as mod

        fake_path = MagicMock()
        fake_path.exists.return_value = True
        with patch.object(mod, "Path", return_value=fake_path):
            result = mod.get_cookie_opts()
        assert result == {"cookiefile": "cookies.txt"}


class TestGetYtdlOptionBuilders:
    """Cover get_ytdl_with_cookies / get_ytdl_fallback_opts and the factories."""

    def test_with_cookies_strips_postprocessors_and_merges_cookies(self):
        """Download-mode opts drop postprocessors and merge cookie opts in."""
        from unittest.mock import patch

        import utils.media.ytdl_source as mod

        with patch.object(mod, "get_cookie_opts", return_value={"cookiefile": "cookies.txt"}):
            opts = mod.get_ytdl_with_cookies()
        # postprocessors removed (we let ffmpeg handle audio)
        assert "postprocessors" not in opts
        # cookie opts merged in
        assert opts["cookiefile"] == "cookies.txt"
        # base config preserved
        assert opts["format"] == mod.ytdl_opts_hq["format"]
        # original config not mutated (copy() was used)
        assert "postprocessors" in mod.ytdl_opts_hq

    def test_fallback_opts_use_safe_format_and_drop_postprocessors(self):
        """Fallback opts override format to the safer m4a/webm chain."""
        from unittest.mock import patch

        import utils.media.ytdl_source as mod

        with patch.object(mod, "get_cookie_opts", return_value={}):
            opts = mod.get_ytdl_fallback_opts()
        assert "postprocessors" not in opts
        assert opts["format"] == "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best"

    def test_get_ytdl_hq_constructs_youtubedl_with_cookie_opts(self):
        """get_ytdl_hq passes the merged opts into the YoutubeDL constructor."""
        from unittest.mock import patch

        import utils.media.ytdl_source as mod

        sentinel_opts = {"format": "x"}
        with (
            patch.object(mod, "get_ytdl_with_cookies", return_value=sentinel_opts),
            patch.object(mod.yt_dlp, "YoutubeDL", return_value="YTDL_INSTANCE") as ctor,
        ):
            result = mod.get_ytdl_hq()
        assert result == "YTDL_INSTANCE"
        ctor.assert_called_once_with(sentinel_opts)

    def test_get_ytdl_fallback_constructs_youtubedl_with_fallback_opts(self):
        """get_ytdl_fallback builds a YoutubeDL from the fallback opts."""
        from unittest.mock import patch

        import utils.media.ytdl_source as mod

        sentinel_opts = {"format": "fb"}
        with (
            patch.object(mod, "get_ytdl_fallback_opts", return_value=sentinel_opts),
            patch.object(mod.yt_dlp, "YoutubeDL", return_value="FB_INSTANCE") as ctor,
        ):
            result = mod.get_ytdl_fallback()
        assert result == "FB_INSTANCE"
        ctor.assert_called_once_with(sentinel_opts)


class TestGetFfmpegOptionsBranches:
    """Cover the stream / download / start_time branches of get_ffmpeg_options."""

    def test_download_mode_has_bufsize_and_no_reconnect(self):
        """Default (stream=False) adds -bufsize and omits the reconnect flags."""
        from utils.media.ytdl_source import get_ffmpeg_options

        opts = get_ffmpeg_options(stream=False)
        assert "-bufsize" in opts["options"]
        assert "1024k" in opts["options"]
        # No streaming reconnect flags when not streaming.
        assert "-reconnect" not in opts["before_options"]

    def test_stream_mode_adds_reconnect_and_probe_flags(self):
        """stream=True populates before_options with reconnect/probe flags."""
        from utils.media.ytdl_source import get_ffmpeg_options

        opts = get_ffmpeg_options(stream=True)
        bo = opts["before_options"]
        assert "-reconnect" in bo
        assert "-reconnect_streamed" in bo
        assert "-reconnect_delay_max" in bo
        assert "-probesize" in bo
        assert "-analyzeduration" in bo
        # Streaming should NOT carry the download-only bufsize flag.
        assert "-bufsize" not in opts["options"]

    def test_start_time_adds_seek_flag(self):
        """A positive start_time appends -ss <int> to before_options."""
        from utils.media.ytdl_source import get_ffmpeg_options

        opts = get_ffmpeg_options(stream=False, start_time=42)
        assert "-ss" in opts["before_options"]
        assert "42" in opts["before_options"]

    def test_start_time_zero_has_no_seek_flag(self):
        """start_time == 0 must NOT add a seek flag."""
        from utils.media.ytdl_source import get_ffmpeg_options

        opts = get_ffmpeg_options(stream=False, start_time=0)
        assert "-ss" not in opts["before_options"]

    def test_options_always_include_pcm_format(self):
        """Both modes output 48kHz stereo s16le PCM."""
        from utils.media.ytdl_source import get_ffmpeg_options

        opts = get_ffmpeg_options()
        assert "-vn" in opts["options"]
        assert "48000" in opts["options"]
        assert "s16le" in opts["options"]


class TestYTDLSourceInit:
    """Cover YTDLSource.__init__ field assignment from the data dict."""

    def test_init_populates_title_url_filename_from_data(self):
        """__init__ pulls title/url out of data and stores filename."""
        from utils.media.ytdl_source import YTDLSource

        data = {"title": "My Song", "url": "http://cdn/audio.opus"}
        src = YTDLSource(_fake_audio_source(), data=data, volume=0.7, filename="temp/song.opus")
        assert src.title == "My Song"
        assert src.url == "http://cdn/audio.opus"
        assert src.filename == "temp/song.opus"
        assert src.data is data
        assert src.volume == 0.7

    def test_init_handles_missing_optional_fields(self):
        """Missing title/url default to None; filename defaults to None."""
        from utils.media.ytdl_source import YTDLSource

        src = YTDLSource(_fake_audio_source(), data={})
        assert src.title is None
        assert src.url is None
        assert src.filename is None


class TestFromUrlSchemeGuard:
    """Cover from_url's scheme allowlist + no-hostname rejections."""

    @pytest.mark.asyncio
    async def test_non_http_scheme_raises_downloaderror(self):
        """A file:// URL is rejected before any network work."""
        import yt_dlp

        from utils.media.ytdl_source import YTDLSource

        with pytest.raises(yt_dlp.DownloadError, match="not allowed"):
            await YTDLSource.from_url("file:///etc/passwd")

    @pytest.mark.asyncio
    async def test_ftp_scheme_raises_downloaderror(self):
        """An ftp:// URL is also rejected by the scheme allowlist."""
        import yt_dlp

        from utils.media.ytdl_source import YTDLSource

        with pytest.raises(yt_dlp.DownloadError, match="not allowed"):
            await YTDLSource.from_url("ftp://example.com/file")

    @pytest.mark.asyncio
    async def test_http_url_without_hostname_raises_valueerror(self):
        """An http URL with no host (e.g. 'http:///path') is rejected."""
        from utils.media.ytdl_source import YTDLSource

        with pytest.raises(ValueError, match="no hostname"):
            await YTDLSource.from_url("http:///just/a/path")


class TestFromUrlSsrfGuard:
    """Cover from_url's SSRF guard: helper path + ImportError fallback path."""

    @pytest.mark.asyncio
    async def test_private_url_rejected_via_helper(self):
        """When _is_private_url returns True, from_url refuses the URL."""
        from unittest.mock import AsyncMock, patch

        from utils.media.ytdl_source import YTDLSource

        with patch(
            "utils.web.url_fetcher._is_private_url",
            new_callable=AsyncMock,
            return_value=True,
        ):
            with pytest.raises(ValueError, match="private/internal IP"):
                await YTDLSource.from_url("http://127.0.0.1/internal")

    @pytest.mark.asyncio
    async def test_importerror_fallback_resolves_public_ip_then_proceeds(self):
        """If the SSRF helper import fails, the fallback getaddrinfo path runs.

        A public IP must pass the fallback check and let extraction proceed.
        """
        import builtins
        import socket
        from unittest.mock import MagicMock, patch

        from utils.media.ytdl_source import YTDLSource

        real_import = builtins.__import__

        def _blocked_import(name, *args, **kwargs):
            if name == "utils.web.url_fetcher":
                raise ImportError("simulated bootstrap circular import")
            return real_import(name, *args, **kwargs)

        # Fake YoutubeDL that returns a valid stream result.
        fake_ytdl = MagicMock()
        fake_ytdl.extract_info.return_value = {
            "title": "ok",
            "url": "https://cdn.example.com/audio.opus",
        }
        # Build the audio mock BEFORE patching __import__ (it imports discord).
        audio = _fake_audio_source()

        # getaddrinfo tuple shape: (family, type, proto, canonname, sockaddr)
        public_info = [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("8.8.8.8", 0))]

        with (
            patch.object(builtins, "__import__", side_effect=_blocked_import),
            patch("utils.media.ytdl_source.get_ytdl_hq", return_value=fake_ytdl),
            patch("socket.getaddrinfo", return_value=public_info),
            patch("utils.media.ytdl_source.discord.FFmpegPCMAudio", return_value=audio),
        ):
            result = await YTDLSource.from_url("https://example.com/song", stream=True)
        assert result.title == "ok"
        assert result.filename == "https://cdn.example.com/audio.opus"

    @pytest.mark.asyncio
    async def test_importerror_fallback_rejects_private_ip(self):
        """Fallback path refuses a host that resolves to a loopback IP."""
        import builtins
        import socket
        from unittest.mock import patch

        from utils.media.ytdl_source import YTDLSource

        real_import = builtins.__import__

        def _blocked_import(name, *args, **kwargs):
            if name == "utils.web.url_fetcher":
                raise ImportError("simulated")
            return real_import(name, *args, **kwargs)

        loopback_info = [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 0))]

        with (
            patch.object(builtins, "__import__", side_effect=_blocked_import),
            patch("socket.getaddrinfo", return_value=loopback_info),
        ):
            with pytest.raises(ValueError, match="non-public IP"):
                await YTDLSource.from_url("http://evil.example.com/x")

    @pytest.mark.asyncio
    async def test_importerror_fallback_unresolvable_host_raises(self):
        """Fallback path raises when DNS resolution fails (gaierror)."""
        import builtins
        import socket
        from unittest.mock import patch

        from utils.media.ytdl_source import YTDLSource

        real_import = builtins.__import__

        def _blocked_import(name, *args, **kwargs):
            if name == "utils.web.url_fetcher":
                raise ImportError("simulated")
            return real_import(name, *args, **kwargs)

        with (
            patch.object(builtins, "__import__", side_effect=_blocked_import),
            patch("socket.getaddrinfo", side_effect=socket.gaierror("no such host")),
        ):
            with pytest.raises(ValueError, match="Could not resolve hostname"):
                await YTDLSource.from_url("http://nonexistent.invalid/x")


class TestFromUrlExtraction:
    """Cover from_url extraction: HQ success, fallback, playlist, validation."""

    @staticmethod
    def _public_ssrf_patch():
        """Patch the SSRF helper to treat all URLs as public (not private)."""
        from unittest.mock import AsyncMock, patch

        return patch(
            "utils.web.url_fetcher._is_private_url",
            new_callable=AsyncMock,
            return_value=False,
        )

    @pytest.mark.asyncio
    async def test_stream_success_returns_source_with_stream_url(self):
        """Happy path streaming: data['url'] becomes the ffmpeg input filename."""
        from unittest.mock import MagicMock, patch

        from utils.media.ytdl_source import YTDLSource

        fake_ytdl = MagicMock()
        fake_ytdl.extract_info.return_value = {
            "title": "Track",
            "url": "https://cdn.example.com/stream.opus",
        }

        with (
            self._public_ssrf_patch(),
            patch("utils.media.ytdl_source.get_ytdl_hq", return_value=fake_ytdl),
            patch(
                "utils.media.ytdl_source.discord.FFmpegPCMAudio",
                return_value=_fake_audio_source(),
            ) as ffmpeg,
        ):
            result = await YTDLSource.from_url("https://youtu.be/x", stream=True)

        assert result.title == "Track"
        assert result.filename == "https://cdn.example.com/stream.opus"
        # extract_info called WITHOUT downloading for stream mode.
        fake_ytdl.extract_info.assert_called_once_with("https://youtu.be/x", download=False)
        # ffmpeg fed the stream URL.
        assert ffmpeg.call_args.args[0] == "https://cdn.example.com/stream.opus"

    @pytest.mark.asyncio
    async def test_download_success_uses_prepared_filename_under_temp(self):
        """Download path uses prepare_filename and validates it under temp/."""
        from pathlib import Path
        from unittest.mock import MagicMock, patch

        from utils.media.ytdl_source import YTDLSource

        expected = str(Path("temp").resolve() / "yt-id-title.opus")
        fake_ytdl = MagicMock()
        fake_ytdl.extract_info.return_value = {"title": "Track", "id": "id"}
        fake_ytdl.prepare_filename.return_value = expected

        with (
            self._public_ssrf_patch(),
            patch("utils.media.ytdl_source.get_ytdl_hq", return_value=fake_ytdl),
            patch(
                "utils.media.ytdl_source.discord.FFmpegPCMAudio",
                return_value=_fake_audio_source(),
            ) as ffmpeg,
        ):
            result = await YTDLSource.from_url("https://youtu.be/x", stream=False)

        assert result.filename == expected
        # download=True for non-stream mode.
        fake_ytdl.extract_info.assert_called_once_with("https://youtu.be/x", download=True)
        assert ffmpeg.call_args.args[0] == expected

    @pytest.mark.asyncio
    async def test_hq_failure_falls_back_to_fallback_ytdl(self):
        """When HQ raises DownloadError, the fallback YoutubeDL is used."""
        from unittest.mock import MagicMock, patch

        import yt_dlp

        from utils.media.ytdl_source import YTDLSource

        hq = MagicMock()
        hq.extract_info.side_effect = yt_dlp.DownloadError("hq boom")
        fb = MagicMock()
        fb.extract_info.return_value = {
            "title": "FB Track",
            "url": "https://cdn.example.com/fb.opus",
        }

        with (
            self._public_ssrf_patch(),
            patch("utils.media.ytdl_source.get_ytdl_hq", return_value=hq),
            patch("utils.media.ytdl_source.get_ytdl_fallback", return_value=fb),
            patch(
                "utils.media.ytdl_source.discord.FFmpegPCMAudio",
                return_value=_fake_audio_source(),
            ),
        ):
            result = await YTDLSource.from_url("https://youtu.be/x", stream=True)

        assert result.title == "FB Track"
        fb.extract_info.assert_called_once()

    @pytest.mark.asyncio
    async def test_both_attempts_fail_raises_last_error(self):
        """If both HQ and fallback fail, the fallback's error propagates."""
        from unittest.mock import MagicMock, patch

        import yt_dlp

        from utils.media.ytdl_source import YTDLSource

        hq = MagicMock()
        hq.extract_info.side_effect = yt_dlp.DownloadError("hq boom")
        fb = MagicMock()
        fb.extract_info.side_effect = yt_dlp.DownloadError("fb boom")

        with (
            self._public_ssrf_patch(),
            patch("utils.media.ytdl_source.get_ytdl_hq", return_value=hq),
            patch("utils.media.ytdl_source.get_ytdl_fallback", return_value=fb),
        ):
            with pytest.raises(yt_dlp.DownloadError, match="fb boom"):
                await YTDLSource.from_url("https://youtu.be/x", stream=True)

    @pytest.mark.asyncio
    async def test_none_data_raises_downloaderror(self):
        """extract_info returning None -> DownloadError('No data returned')."""
        from unittest.mock import MagicMock, patch

        import yt_dlp

        from utils.media.ytdl_source import YTDLSource

        fake_ytdl = MagicMock()
        fake_ytdl.extract_info.return_value = None

        with (
            self._public_ssrf_patch(),
            patch("utils.media.ytdl_source.get_ytdl_hq", return_value=fake_ytdl),
        ):
            with pytest.raises(yt_dlp.DownloadError, match="No data returned"):
                await YTDLSource.from_url("https://youtu.be/x", stream=True)

    @pytest.mark.asyncio
    async def test_playlist_takes_first_entry(self):
        """An 'entries' result uses the first entry."""
        from unittest.mock import MagicMock, patch

        from utils.media.ytdl_source import YTDLSource

        fake_ytdl = MagicMock()
        fake_ytdl.extract_info.return_value = {
            "entries": [
                {"title": "First", "url": "https://cdn.example.com/first.opus"},
                {"title": "Second", "url": "https://cdn.example.com/second.opus"},
            ]
        }

        with (
            self._public_ssrf_patch(),
            patch("utils.media.ytdl_source.get_ytdl_hq", return_value=fake_ytdl),
            patch(
                "utils.media.ytdl_source.discord.FFmpegPCMAudio",
                return_value=_fake_audio_source(),
            ),
        ):
            result = await YTDLSource.from_url("https://youtu.be/list", stream=True)

        assert result.title == "First"

    @pytest.mark.asyncio
    async def test_empty_playlist_raises_valueerror(self):
        """An empty 'entries' list raises 'Playlist or search result is empty'."""
        from unittest.mock import MagicMock, patch

        from utils.media.ytdl_source import YTDLSource

        fake_ytdl = MagicMock()
        fake_ytdl.extract_info.return_value = {"entries": []}

        with (
            self._public_ssrf_patch(),
            patch("utils.media.ytdl_source.get_ytdl_hq", return_value=fake_ytdl),
        ):
            with pytest.raises(ValueError, match="empty"):
                await YTDLSource.from_url("https://youtu.be/list", stream=True)

    @pytest.mark.asyncio
    async def test_first_entry_none_raises_valueerror(self):
        """A playlist whose first entry is None raises 'First entry is None'."""
        from unittest.mock import MagicMock, patch

        from utils.media.ytdl_source import YTDLSource

        fake_ytdl = MagicMock()
        fake_ytdl.extract_info.return_value = {"entries": [None]}

        with (
            self._public_ssrf_patch(),
            patch("utils.media.ytdl_source.get_ytdl_hq", return_value=fake_ytdl),
        ):
            with pytest.raises(ValueError, match="First entry is None"):
                await YTDLSource.from_url("https://youtu.be/list", stream=True)

    @pytest.mark.asyncio
    async def test_stream_missing_url_raises_valueerror(self):
        """stream=True but no 'url' field -> 'Streaming URL not found'."""
        from unittest.mock import MagicMock, patch

        from utils.media.ytdl_source import YTDLSource

        fake_ytdl = MagicMock()
        fake_ytdl.extract_info.return_value = {"title": "no url here"}

        with (
            self._public_ssrf_patch(),
            patch("utils.media.ytdl_source.get_ytdl_hq", return_value=fake_ytdl),
        ):
            with pytest.raises(ValueError, match="Streaming URL not found"):
                await YTDLSource.from_url("https://youtu.be/x", stream=True)


class TestFromUrlFilenameValidation:
    """Cover from_url's ffmpeg-input filename validation branches."""

    @staticmethod
    def _public_ssrf_patch():
        from unittest.mock import AsyncMock, patch

        return patch(
            "utils.web.url_fetcher._is_private_url",
            new_callable=AsyncMock,
            return_value=False,
        )

    @pytest.mark.asyncio
    async def test_filename_starting_with_dash_rejected(self):
        """A download filename starting with '-' (ffmpeg flag injection) is rejected."""
        from unittest.mock import MagicMock, patch

        from utils.media.ytdl_source import YTDLSource

        fake_ytdl = MagicMock()
        fake_ytdl.extract_info.return_value = {"title": "x", "id": "id"}
        fake_ytdl.prepare_filename.return_value = "-i /etc/passwd"

        with (
            self._public_ssrf_patch(),
            patch("utils.media.ytdl_source.get_ytdl_hq", return_value=fake_ytdl),
        ):
            with pytest.raises(ValueError, match="suspicious filename"):
                await YTDLSource.from_url("https://youtu.be/x", stream=False)

    @pytest.mark.asyncio
    async def test_non_string_filename_rejected(self):
        """A non-string prepared filename is rejected as invalid."""
        from unittest.mock import MagicMock, patch

        from utils.media.ytdl_source import YTDLSource

        fake_ytdl = MagicMock()
        fake_ytdl.extract_info.return_value = {"title": "x", "id": "id"}
        fake_ytdl.prepare_filename.return_value = None

        with (
            self._public_ssrf_patch(),
            patch("utils.media.ytdl_source.get_ytdl_hq", return_value=fake_ytdl),
        ):
            with pytest.raises(ValueError, match="Invalid filename"):
                await YTDLSource.from_url("https://youtu.be/x", stream=False)

    @pytest.mark.asyncio
    async def test_stream_non_http_url_rejected(self):
        """A stream URL that is not http(s) (e.g. file://) is rejected."""
        from unittest.mock import MagicMock, patch

        from utils.media.ytdl_source import YTDLSource

        fake_ytdl = MagicMock()
        fake_ytdl.extract_info.return_value = {
            "title": "x",
            "url": "file:///etc/shadow",
        }

        with (
            self._public_ssrf_patch(),
            patch("utils.media.ytdl_source.get_ytdl_hq", return_value=fake_ytdl),
        ):
            with pytest.raises(ValueError, match="non-http"):
                await YTDLSource.from_url("https://youtu.be/x", stream=True)

    @pytest.mark.asyncio
    async def test_download_filename_outside_temp_rejected(self):
        """A download path resolving outside temp/ is refused (path traversal)."""
        from pathlib import Path
        from unittest.mock import MagicMock, patch

        from utils.media.ytdl_source import YTDLSource

        # A path that resolves clearly outside the temp/ download dir.
        outside = str(Path("definitely_not_temp_dir").resolve() / "evil.opus")
        fake_ytdl = MagicMock()
        fake_ytdl.extract_info.return_value = {"title": "x", "id": "id"}
        fake_ytdl.prepare_filename.return_value = outside

        with (
            self._public_ssrf_patch(),
            patch("utils.media.ytdl_source.get_ytdl_hq", return_value=fake_ytdl),
        ):
            with pytest.raises(ValueError, match="outside the temp"):
                await YTDLSource.from_url("https://youtu.be/x", stream=False)


class TestSearchSourceExtraction:
    """Cover search_source extraction branches not exercised by the URL tests."""

    @staticmethod
    def _make_recorder(result):
        """Fake YoutubeDL returning a fixed result and recording the query."""
        from unittest.mock import MagicMock

        recorded: dict[str, object] = {}

        def _extract_info(query, download=False):
            recorded["query"] = query
            return result

        fake = MagicMock()
        fake.extract_info.side_effect = _extract_info
        return fake, recorded

    @pytest.mark.asyncio
    async def test_search_returns_first_entry_of_results(self):
        """A ytsearch result with entries returns the first entry."""
        from unittest.mock import patch

        from utils.media.ytdl_source import YTDLSource

        fake, _ = self._make_recorder({"entries": [{"title": "Top Hit"}, {"title": "Second"}]})
        with patch("utils.media.ytdl_source.get_ytdl_hq", return_value=fake):
            result = await YTDLSource.search_source("some song")
        assert result == {"title": "Top Hit"}

    @pytest.mark.asyncio
    async def test_search_empty_entries_returns_none(self):
        """A search with an empty entries list returns None."""
        from unittest.mock import patch

        from utils.media.ytdl_source import YTDLSource

        fake, _ = self._make_recorder({"entries": []})
        with patch("utils.media.ytdl_source.get_ytdl_hq", return_value=fake):
            result = await YTDLSource.search_source("nothing matches")
        assert result is None

    @pytest.mark.asyncio
    async def test_search_none_data_returns_none(self):
        """extract_info returning None yields a None search result."""
        from unittest.mock import patch

        from utils.media.ytdl_source import YTDLSource

        fake, _ = self._make_recorder(None)
        with patch("utils.media.ytdl_source.get_ytdl_hq", return_value=fake):
            result = await YTDLSource.search_source("query")
        assert result is None

    @pytest.mark.asyncio
    async def test_search_hq_failure_falls_back(self):
        """HQ DownloadError makes search_source retry via the fallback YoutubeDL."""
        from unittest.mock import MagicMock, patch

        import yt_dlp

        from utils.media.ytdl_source import YTDLSource

        hq = MagicMock()
        hq.extract_info.side_effect = yt_dlp.DownloadError("search hq fail")
        fb = MagicMock()
        fb.extract_info.return_value = {"title": "From Fallback"}

        with (
            patch("utils.media.ytdl_source.get_ytdl_hq", return_value=hq),
            patch("utils.media.ytdl_source.get_ytdl_fallback", return_value=fb),
        ):
            result = await YTDLSource.search_source("retry me")
        assert result == {"title": "From Fallback"}
        fb.extract_info.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_source_fallback_nondownloaderror_returns_none(self):
        """Fix A: a NON-DownloadError from the fallback extractor returns None.

        HQ raises DownloadError to trigger the fallback; the fallback then
        raises a bare ValueError (the kind a hostile/third-party extractor can
        emit — NOT a DownloadError). Pre-fix the inner handler only caught
        ``(TimeoutError, yt_dlp.DownloadError)``, so a ValueError raised inside
        that handler's suite escaped the whole try statement (the sibling broad
        ``except Exception`` only guards the try BODY, not another handler) and
        propagated out of search_source — violating its documented
        ``dict | None`` contract and freezing the music-cog caller's queue.
        The broadened ``except Exception`` must normalize it to None.

        A plain search term never enters the SSRF branch (that only fires for
        raw URLs), so no _is_private_url patch is needed here.
        """
        from unittest.mock import MagicMock, patch

        import yt_dlp

        from utils.media.ytdl_source import YTDLSource

        hq = MagicMock()
        hq.extract_info.side_effect = yt_dlp.DownloadError("hq boom")
        fb = MagicMock()
        fb.extract_info.side_effect = ValueError("hostile extractor")

        with (
            patch("utils.media.ytdl_source.get_ytdl_hq", return_value=hq),
            patch("utils.media.ytdl_source.get_ytdl_fallback", return_value=fb),
        ):
            # Must RETURN None, not raise.
            result = await YTDLSource.search_source("never gonna give you up")

        assert result is None
        fb.extract_info.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_rejects_non_http_url_scheme(self):
        """A real non-http(s) URL scheme (with '://') is rejected, returns None."""
        from utils.media.ytdl_source import YTDLSource

        result = await YTDLSource.search_source("ftp://example.com/song.mp3")
        assert result is None

    @pytest.mark.asyncio
    async def test_search_direct_url_importerror_fails_closed(self):
        """If the SSRF helper import fails for a direct URL, search returns None."""
        import builtins
        from unittest.mock import MagicMock, patch

        from utils.media.ytdl_source import YTDLSource

        real_import = builtins.__import__

        def _blocked_import(name, *args, **kwargs):
            if name == "utils.web.url_fetcher":
                raise ImportError("simulated")
            return real_import(name, *args, **kwargs)

        # get_ytdl_hq patched too, but it must never be reached (fail-closed).
        with (
            patch.object(builtins, "__import__", side_effect=_blocked_import),
            patch("utils.media.ytdl_source.get_ytdl_hq", return_value=MagicMock()) as hq,
        ):
            result = await YTDLSource.search_source("http://example.com/song")
        assert result is None
        hq.assert_not_called()


class TestUrlparseExceptionBranches:
    """Cover the defensive try/except wrapping urlparse() in both methods.

    urlparse() rarely raises for normal str input, so we patch it to raise
    and assert the documented fall-through behaviour (scheme treated as
    unknown/empty).
    """

    @pytest.mark.asyncio
    async def test_from_url_urlparse_raising_yields_scheme_rejection(self):
        """If urlparse raises, scheme is '' and from_url rejects the URL."""
        from unittest.mock import patch

        import yt_dlp

        from utils.media.ytdl_source import YTDLSource

        # from_url does `from urllib.parse import urlparse`, so patch the
        # canonical attribute the import binds to.
        with patch("urllib.parse.urlparse", side_effect=ValueError("boom")):
            with pytest.raises(yt_dlp.DownloadError, match="not allowed"):
                await YTDLSource.from_url("http://example.com/x")

    @pytest.mark.asyncio
    async def test_search_urlparse_raising_falls_through_to_ytsearch(self):
        """If urlparse raises in search, scheme='' and plain text -> ytsearch."""
        from unittest.mock import MagicMock, patch

        from utils.media.ytdl_source import YTDLSource

        recorded: dict[str, object] = {}

        def _extract_info(query, download=False):
            recorded["query"] = query
            return {"title": "ok"}

        fake = MagicMock()
        fake.extract_info.side_effect = _extract_info

        with (
            patch("urllib.parse.urlparse", side_effect=TypeError("boom")),
            patch("utils.media.ytdl_source.get_ytdl_hq", return_value=fake),
        ):
            result = await YTDLSource.search_source("some plain query")

        assert result == {"title": "ok"}
        # No "://" in the query, so it is wrapped as a ytsearch term.
        assert recorded["query"] == "ytsearch:some plain query"
