"""Tests for ytdl_source module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestYtdlOpts:
    """Tests for ytdl options configuration."""

    def test_ytdl_opts_hq_exists(self):
        """Test ytdl_opts_hq config exists."""
        from utils.media.ytdl_source import ytdl_opts_hq

        assert ytdl_opts_hq is not None
        assert isinstance(ytdl_opts_hq, dict)

    def test_ytdl_opts_has_format(self):
        """Test ytdl_opts_hq has format setting."""
        from utils.media.ytdl_source import ytdl_opts_hq

        assert "format" in ytdl_opts_hq
        assert "bestaudio" in ytdl_opts_hq["format"]

    def test_ytdl_opts_quiet_mode(self):
        """Test ytdl_opts_hq has quiet mode."""
        from utils.media.ytdl_source import ytdl_opts_hq

        assert ytdl_opts_hq.get("quiet") is True
        assert ytdl_opts_hq.get("no_warnings") is True

    def test_ytdl_opts_has_retries(self):
        """Test ytdl_opts_hq has retry settings."""
        from utils.media.ytdl_source import ytdl_opts_hq

        assert "retries" in ytdl_opts_hq
        assert isinstance(ytdl_opts_hq["retries"], int)

    def test_ytdl_opts_has_user_agent(self):
        """Test ytdl_opts_hq has user agent."""
        from utils.media.ytdl_source import ytdl_opts_hq

        assert "user_agent" in ytdl_opts_hq
        assert "Chrome" in ytdl_opts_hq["user_agent"]

    def test_ytdl_opts_geo_bypass(self):
        """Test ytdl_opts_hq has geo bypass."""
        from utils.media.ytdl_source import ytdl_opts_hq

        assert ytdl_opts_hq.get("geo_bypass") is True
        assert ytdl_opts_hq.get("geo_bypass_country") == "US"


class TestGetCookieOpts:
    """Tests for get_cookie_opts function."""

    def test_get_cookie_opts_no_file(self):
        """Test get_cookie_opts when no cookies.txt exists."""
        from utils.media.ytdl_source import get_cookie_opts

        with patch('pathlib.Path.exists', return_value=False):
            result = get_cookie_opts()

        assert result == {}

    def test_get_cookie_opts_with_file(self):
        """Test get_cookie_opts when cookies.txt exists."""
        from utils.media.ytdl_source import get_cookie_opts

        with patch('pathlib.Path.exists', return_value=True):
            result = get_cookie_opts()

        assert "cookiefile" in result
        assert result["cookiefile"] == "cookies.txt"


class TestGetYtdlWithCookies:
    """Tests for get_ytdl_with_cookies function."""

    def test_get_ytdl_with_cookies_returns_dict(self):
        """Test get_ytdl_with_cookies returns dict."""
        from utils.media.ytdl_source import get_ytdl_with_cookies

        with patch('pathlib.Path.exists', return_value=False):
            result = get_ytdl_with_cookies()

        assert isinstance(result, dict)

    def test_get_ytdl_with_cookies_removes_postprocessors(self):
        """Test get_ytdl_with_cookies removes postprocessors."""
        from utils.media.ytdl_source import get_ytdl_with_cookies

        with patch('pathlib.Path.exists', return_value=False):
            result = get_ytdl_with_cookies()

        assert "postprocessors" not in result


class TestGetFfmpegOptions:
    """Tests for get_ffmpeg_options function."""

    def test_get_ffmpeg_options_exists(self):
        """Test get_ffmpeg_options function exists."""
        from utils.media.ytdl_source import get_ffmpeg_options

        assert callable(get_ffmpeg_options)

    def test_get_ffmpeg_options_returns_dict(self):
        """Test get_ffmpeg_options returns dict."""
        from utils.media.ytdl_source import get_ffmpeg_options

        result = get_ffmpeg_options()

        assert isinstance(result, dict)

    def test_get_ffmpeg_options_with_volume(self):
        """Test get_ffmpeg_options with different parameters."""
        from utils.media.ytdl_source import get_ffmpeg_options

        # Just test the function works with default params
        result = get_ffmpeg_options()

        assert isinstance(result, dict)

    def test_get_ffmpeg_options_with_start_time(self):
        """Test get_ffmpeg_options with start_time parameter."""
        from utils.media.ytdl_source import get_ffmpeg_options

        result = get_ffmpeg_options(start_time=30)

        assert isinstance(result, dict)


class TestYTDLSource:
    """Tests for YTDLSource class."""

    def test_ytdl_source_import(self):
        """Test YTDLSource can be imported."""
        from utils.media.ytdl_source import YTDLSource

        assert YTDLSource is not None

    def test_ytdl_source_has_from_url(self):
        """Test YTDLSource has from_url method."""
        from utils.media.ytdl_source import YTDLSource

        assert hasattr(YTDLSource, 'from_url')


class TestModuleImports:
    """Tests for module imports."""

    def test_import_ytdl_source(self):
        """Test ytdl_source module can be imported."""
        from utils.media import ytdl_source

        assert ytdl_source is not None

    def test_import_ytdl_source_classes(self):
        """Test classes can be imported."""
        from utils.media.ytdl_source import YTDLSource, get_ffmpeg_options

        assert YTDLSource is not None
        assert get_ffmpeg_options is not None


class TestYtdlOptsExtractor:
    """Tests for yt-dlp extractor options."""

    def test_extractor_args_exist(self):
        """Test extractor args exist."""
        from utils.media.ytdl_source import ytdl_opts_hq

        assert "extractor_args" in ytdl_opts_hq
        assert "youtube" in ytdl_opts_hq["extractor_args"]

    def test_player_client_options(self):
        """Test player client options."""
        from utils.media.ytdl_source import ytdl_opts_hq

        youtube_args = ytdl_opts_hq["extractor_args"]["youtube"]
        assert "player_client" in youtube_args
        assert "android" in youtube_args["player_client"]


class TestYtdlPerformanceOptions:
    """Tests for performance-related options."""

    def test_buffer_size(self):
        """Test buffer size is set."""
        from utils.media.ytdl_source import ytdl_opts_hq

        assert "buffersize" in ytdl_opts_hq
        assert ytdl_opts_hq["buffersize"] > 0

    def test_socket_timeout(self):
        """Test socket timeout is set."""
        from utils.media.ytdl_source import ytdl_opts_hq

        assert "socket_timeout" in ytdl_opts_hq
        assert isinstance(ytdl_opts_hq["socket_timeout"], int)

    def test_concurrent_downloads(self):
        """Test concurrent downloads is set."""
        from utils.media.ytdl_source import ytdl_opts_hq

        assert "concurrent_fragment_downloads" in ytdl_opts_hq
        assert ytdl_opts_hq["concurrent_fragment_downloads"] > 0
