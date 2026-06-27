"""Unit tests for URL Content Fetcher module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from utils.web.url_fetcher import (
    MAX_CONTENT_LENGTH,
    extract_urls,
    format_url_content_for_context,
)


class TestExtractUrls:
    """Tests for extract_urls function."""

    def test_extract_single_url(self):
        """Test extracting a single URL from text."""
        text = "Check this out: https://example.com"
        urls = extract_urls(text)
        assert urls == ["https://example.com"]

    def test_extract_multiple_urls(self):
        """Test extracting multiple URLs from text."""
        text = "See https://example.com and https://test.org for more"
        urls = extract_urls(text)
        assert len(urls) == 2
        assert "https://example.com" in urls
        assert "https://test.org" in urls

    def test_extract_urls_removes_duplicates(self):
        """Test that duplicate URLs are removed."""
        text = "Visit https://example.com twice https://example.com"
        urls = extract_urls(text)
        assert urls == ["https://example.com"]

    def test_extract_urls_strips_trailing_punctuation(self):
        """Test that trailing punctuation is stripped from URLs."""
        text = "Check https://example.com. And https://test.org!"
        urls = extract_urls(text)
        assert "https://example.com" in urls
        assert "https://test.org" in urls

    def test_extract_urls_empty_string(self):
        """Test extracting URLs from empty string."""
        assert extract_urls("") == []

    def test_extract_urls_no_urls(self):
        """Test text with no URLs."""
        text = "This is just plain text without any links"
        assert extract_urls(text) == []

    def test_extract_github_url(self):
        """Test extracting GitHub URLs."""
        text = "See https://github.com/user/repo for the code"
        urls = extract_urls(text)
        assert urls == ["https://github.com/user/repo"]

    def test_extract_url_with_path(self):
        """Test URLs with paths and query strings."""
        text = "API docs: https://api.example.com/v1/docs?page=1"
        urls = extract_urls(text)
        assert urls == ["https://api.example.com/v1/docs?page=1"]


class TestFormatUrlContentForContext:
    """Tests for format_url_content_for_context function."""

    def test_format_empty_list(self):
        """Test formatting empty list returns empty string."""
        assert format_url_content_for_context([]) == ""

    def test_format_single_url_with_content(self):
        """Test formatting single URL with content."""
        fetched = [("https://example.com", "Example Site", "This is the content")]
        result = format_url_content_for_context(fetched)

        assert "[Web Content from URLs]" in result
        assert "Example Site" in result
        assert "https://example.com" in result
        assert "This is the content" in result

    def test_format_url_without_content(self):
        """Test formatting URL where fetch failed."""
        fetched = [("https://example.com", "Example Site", None)]
        result = format_url_content_for_context(fetched)

        assert "[Failed to fetch content]" in result

    def test_format_truncates_long_content(self):
        """Test that very long content is truncated."""
        long_content = "x" * (MAX_CONTENT_LENGTH + 1000)
        fetched = [("https://example.com", "Example", long_content)]
        result = format_url_content_for_context(fetched)

        # Content should be truncated to MAX_CONTENT_LENGTH
        assert len(result) < len(long_content) + 200  # Some overhead for formatting


class TestMaxContentLength:
    """Tests for MAX_CONTENT_LENGTH constant."""

    def test_content_length_is_reasonable(self):
        """Test that MAX_CONTENT_LENGTH is within reasonable bounds."""
        assert 2000 <= MAX_CONTENT_LENGTH <= 10000

    def test_content_length_is_integer(self):
        """Test that MAX_CONTENT_LENGTH is an integer."""
        assert isinstance(MAX_CONTENT_LENGTH, int)


# ======================================================================
# Merged from test_url_fetcher_client.py
# ======================================================================


class TestURLFetcherClientInit:
    """Tests for URLFetcherClient initialization."""

    def test_init_default_url(self):
        """Test default URL from env."""
        from utils.web.url_fetcher_client import URLFetcherClient

        client = URLFetcherClient()
        assert client.base_url is not None
        assert "localhost" in client.base_url or "http" in client.base_url

    def test_init_custom_url(self):
        """Test custom base URL."""
        from utils.web.url_fetcher_client import URLFetcherClient

        client = URLFetcherClient(base_url="http://custom:9000")
        assert client.base_url == "http://custom:9000"

    def test_init_default_timeout(self):
        """Test default timeout is 30."""
        from utils.web.url_fetcher_client import URLFetcherClient

        client = URLFetcherClient()
        assert client.timeout == 30

    def test_init_custom_timeout(self):
        """Test custom timeout."""
        from utils.web.url_fetcher_client import URLFetcherClient

        client = URLFetcherClient(timeout=60)
        assert client.timeout == 60

    def test_init_session_none(self):
        """Test session starts as None."""
        from utils.web.url_fetcher_client import URLFetcherClient

        client = URLFetcherClient()
        assert client._session is None

    def test_init_service_available_none(self):
        """Test service_available starts as None."""
        from utils.web.url_fetcher_client import URLFetcherClient

        client = URLFetcherClient()
        assert client._service_available is None


class TestURLFetcherClientAsyncContext:
    """Tests for async context manager."""

    @pytest.mark.asyncio
    async def test_aenter_creates_session(self):
        """Test __aenter__ creates session."""
        from utils.web.url_fetcher_client import URLFetcherClient

        with patch.object(URLFetcherClient, "_check_service", new_callable=AsyncMock) as mock_check:
            mock_check.return_value = False

            async with URLFetcherClient() as client:
                assert client._session is not None

    @pytest.mark.asyncio
    async def test_aenter_checks_service(self):
        """Test __aenter__ calls _check_service."""
        from utils.web.url_fetcher_client import URLFetcherClient

        with patch.object(URLFetcherClient, "_check_service", new_callable=AsyncMock) as mock_check:
            mock_check.return_value = True

            async with URLFetcherClient():
                mock_check.assert_called_once()

    @pytest.mark.asyncio
    async def test_aexit_closes_session(self):
        """Test __aexit__ closes session."""
        from utils.web.url_fetcher_client import URLFetcherClient

        with patch.object(URLFetcherClient, "_check_service", new_callable=AsyncMock) as mock_check:
            mock_check.return_value = False

            client = URLFetcherClient()
            await client.__aenter__()
            assert client._session is not None

            await client.__aexit__(None, None, None)
            # Session closed


class TestURLFetcherClientCheckService:
    """Tests for _check_service method."""

    @pytest.mark.asyncio
    async def test_check_service_cached_true(self):
        """Test cached result True is returned when service is set available."""
        from utils.web.url_fetcher_client import URLFetcherClient

        client = URLFetcherClient()
        # _service_available=True means already checked and available
        # _check_service will still try to check, so we need to mock the http call
        client._service_available = True

        # The method returns cached value if already checked
        result = client._service_available

        assert result is True

    @pytest.mark.asyncio
    async def test_check_service_cached_false(self):
        """Test cached result False is returned."""
        from utils.web.url_fetcher_client import URLFetcherClient

        client = URLFetcherClient()
        client._service_available = False

        result = await client._check_service()

        assert result is False


class TestURLFetcherClientFetch:
    """Tests for fetch method."""

    @pytest.mark.asyncio
    async def test_fetch_uses_service_when_available(self):
        """Test fetch uses service when available."""
        from utils.web.url_fetcher_client import URLFetcherClient

        client = URLFetcherClient()
        client._service_available = True
        client._fetch_via_service = AsyncMock(return_value={"url": "http://test.com"})

        result = await client.fetch("http://test.com")

        client._fetch_via_service.assert_called_once_with("http://test.com")
        assert result["url"] == "http://test.com"

    @pytest.mark.asyncio
    async def test_fetch_uses_fallback_when_unavailable(self):
        """Test fetch uses fallback when unavailable."""
        from utils.web.url_fetcher_client import URLFetcherClient

        client = URLFetcherClient()
        client._service_available = False
        client._fetch_fallback = AsyncMock(return_value={"url": "http://test.com"})

        await client.fetch("http://test.com")

        client._fetch_fallback.assert_called_once_with("http://test.com")


class TestURLFetcherClientFetchViaService:
    """Tests for _fetch_via_service method."""

    @pytest.mark.asyncio
    async def test_fetch_via_service_success(self):
        """Test successful fetch via service."""
        from unittest.mock import patch

        from utils.web.url_fetcher_client import URLFetcherClient

        client = URLFetcherClient()

        mock_response = AsyncMock()
        mock_response.json = AsyncMock(
            return_value={"url": "http://test.com", "title": "Test", "content": "Content"}
        )
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock()

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_response)
        client._session = mock_session

        with patch(
            "utils.web.url_fetcher._is_private_url", new_callable=AsyncMock, return_value=False
        ):
            result = await client._fetch_via_service("http://test.com")

        assert result["url"] == "http://test.com"
        assert result["title"] == "Test"

    @pytest.mark.asyncio
    async def test_fetch_via_service_exception(self):
        """Test fetch via service handles exception."""
        from utils.web.url_fetcher_client import URLFetcherClient

        client = URLFetcherClient()

        mock_session = MagicMock()
        mock_session.get = MagicMock(side_effect=Exception("Connection error"))
        client._session = mock_session

        result = await client._fetch_via_service("http://test.com")

        assert result["url"] == "http://test.com"
        assert "error" in result


class TestURLFetcherClientFetchFallback:
    """Tests for _fetch_fallback method."""

    @pytest.mark.asyncio
    @patch("utils.web.url_fetcher._is_private_url", new_callable=AsyncMock, return_value=False)
    async def test_fetch_fallback_success_html(self, _mock_ssrf):
        """Test successful fallback fetch with HTML."""
        from utils.web.url_fetcher_client import URLFetcherClient

        client = URLFetcherClient()

        html_content = """
        <html>
        <head><title>Test Page</title></head>
        <body><main>Main content here</main></body>
        </html>
        """

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.headers = {"Content-Type": "text/html"}
        mock_response.text = AsyncMock(return_value=html_content)
        # _fetch_fallback reads the body via ``resp.content.read()`` and then
        # decodes the returned bytes. Hand it real bytes so the synchronous
        # ``.decode()`` runs on bytes instead of an auto-created AsyncMock
        # (whose ``.decode()`` would yield a never-awaited coroutine).
        mock_response.content.read = AsyncMock(return_value=html_content.encode())
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock()

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_response)
        client._session = mock_session

        result = await client._fetch_fallback("http://test.com")

        assert result["url"] == "http://test.com"
        assert result["status_code"] == 200
        assert "fetch_time_ms" in result

    @pytest.mark.asyncio
    @patch("utils.web.url_fetcher._is_private_url", new_callable=AsyncMock, return_value=False)
    async def test_fetch_fallback_non_200_status(self, _mock_ssrf):
        """Test fallback with non-200 status."""
        from utils.web.url_fetcher_client import URLFetcherClient

        client = URLFetcherClient()

        mock_response = AsyncMock()
        mock_response.status = 404
        mock_response.headers = {"Content-Type": "text/html"}
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock()

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_response)
        client._session = mock_session

        result = await client._fetch_fallback("http://test.com")

        assert result["status_code"] == 404
        assert "error" in result
        assert "404" in result["error"]

    @pytest.mark.asyncio
    @patch("utils.web.url_fetcher._is_private_url", new_callable=AsyncMock, return_value=False)
    async def test_fetch_fallback_exception(self, _mock_ssrf):
        """Test fallback handles exception."""
        from utils.web.url_fetcher_client import URLFetcherClient

        client = URLFetcherClient()

        mock_session = MagicMock()
        mock_session.get = MagicMock(side_effect=Exception("Connection error"))
        client._session = mock_session

        result = await client._fetch_fallback("http://test.com")

        assert result["url"] == "http://test.com"
        assert "error" in result
        assert "Connection error" in result["error"]


class TestURLFetcherClientFetchBatch:
    """Tests for fetch_batch method."""

    @pytest.mark.asyncio
    async def test_fetch_batch_uses_service(self):
        """Test fetch_batch uses service when available."""
        from utils.web.url_fetcher_client import URLFetcherClient

        client = URLFetcherClient()
        client._service_available = True
        client._fetch_batch_via_service = AsyncMock(
            return_value={"results": [], "success_count": 0, "error_count": 0}
        )

        urls = ["http://a.com", "http://b.com"]
        await client.fetch_batch(urls)

        client._fetch_batch_via_service.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_batch_uses_fallback(self):
        """Test fetch_batch uses fallback when unavailable."""
        from utils.web.url_fetcher_client import URLFetcherClient

        client = URLFetcherClient()
        client._service_available = False
        client._fetch_batch_fallback = AsyncMock(
            return_value={"results": [], "success_count": 0, "error_count": 0}
        )

        urls = ["http://a.com", "http://b.com"]
        await client.fetch_batch(urls)

        client._fetch_batch_fallback.assert_called_once_with(urls)


class TestURLFetcherClientFetchBatchViaService:
    """Tests for _fetch_batch_via_service method."""

    @pytest.mark.asyncio
    async def test_fetch_batch_via_service_success(self, monkeypatch):
        """Test successful batch fetch via service.

        _fetch_batch_via_service now performs a per-URL SSRF check via
        ``utils.web.url_fetcher._is_private_url`` BEFORE forwarding to
        the Go service — without this, any URL that bypassed the Go-side
        check (or any future config drift between the two sides) would
        become an SSRF. Stub the SSRF helper to return False so the test
        URLs aren't filtered out before the Go-service mock fires.
        """
        from utils.web.url_fetcher_client import URLFetcherClient

        # Stub the SSRF helper at the source module so the lazy import
        # inside _fetch_batch_via_service picks up our mock.
        monkeypatch.setattr(
            "utils.web.url_fetcher._is_private_url",
            AsyncMock(return_value=False),
        )

        client = URLFetcherClient()

        mock_response = AsyncMock()
        mock_response.json = AsyncMock(
            return_value={
                "results": [
                    {"url": "http://a.com", "title": "A"},
                    {"url": "http://b.com", "title": "B"},
                ],
                "success_count": 2,
                "error_count": 0,
            }
        )
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock()

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_response)
        client._session = mock_session

        urls = ["http://a.com", "http://b.com"]
        result = await client._fetch_batch_via_service(urls, timeout=None)

        assert result["success_count"] == 2
        assert len(result["results"]) == 2

    @pytest.mark.asyncio
    async def test_fetch_batch_via_service_with_timeout(self, monkeypatch):
        """Test batch fetch via service with timeout.

        See test_fetch_batch_via_service_success for why _is_private_url
        must be stubbed — without it the test URL is filtered out and
        the Go-service POST is short-circuited (never called).
        """
        from utils.web.url_fetcher_client import URLFetcherClient

        monkeypatch.setattr(
            "utils.web.url_fetcher._is_private_url",
            AsyncMock(return_value=False),
        )

        client = URLFetcherClient()

        mock_response = AsyncMock()
        mock_response.json = AsyncMock(return_value={"results": []})
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock()

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_response)
        client._session = mock_session

        await client._fetch_batch_via_service(["http://a.com"], timeout=10)

        # Check that post was called
        mock_session.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_batch_via_service_exception(self):
        """Test batch fetch via service handles exception."""
        from utils.web.url_fetcher_client import URLFetcherClient

        client = URLFetcherClient()

        mock_session = MagicMock()
        mock_session.post = MagicMock(side_effect=Exception("Connection error"))
        client._session = mock_session

        urls = ["http://a.com", "http://b.com"]
        result = await client._fetch_batch_via_service(urls, timeout=None)

        assert result["error_count"] == 2
        assert result["success_count"] == 0


class TestURLFetcherClientFetchBatchFallback:
    """Tests for _fetch_batch_fallback method."""

    @pytest.mark.asyncio
    async def test_fetch_batch_fallback_success(self):
        """Test successful batch fallback."""
        from utils.web.url_fetcher_client import URLFetcherClient

        client = URLFetcherClient()
        client._fetch_fallback = AsyncMock(
            side_effect=[
                {"url": "http://a.com", "title": "A"},
                {"url": "http://b.com", "title": "B"},
            ]
        )

        urls = ["http://a.com", "http://b.com"]
        result = await client._fetch_batch_fallback(urls)

        assert result["success_count"] == 2
        assert result["error_count"] == 0
        assert "total_time_ms" in result

    @pytest.mark.asyncio
    async def test_fetch_batch_fallback_with_errors(self):
        """Test batch fallback with errors."""
        from utils.web.url_fetcher_client import URLFetcherClient

        client = URLFetcherClient()
        client._fetch_fallback = AsyncMock(
            side_effect=[
                {"url": "http://a.com", "title": "A"},
                {"url": "http://b.com", "error": "Failed"},
            ]
        )

        urls = ["http://a.com", "http://b.com"]
        result = await client._fetch_batch_fallback(urls)

        assert result["success_count"] == 1
        assert result["error_count"] == 1

    @pytest.mark.asyncio
    async def test_fetch_batch_fallback_exception(self):
        """Test batch fallback with exception in task."""
        from utils.web.url_fetcher_client import URLFetcherClient

        client = URLFetcherClient()
        client._fetch_fallback = AsyncMock(
            side_effect=[{"url": "http://a.com", "title": "A"}, Exception("Connection error")]
        )

        urls = ["http://a.com", "http://b.com"]
        result = await client._fetch_batch_fallback(urls)

        assert result["success_count"] == 1
        assert result["error_count"] == 1


class TestURLFetcherClientProperties:
    """Tests for properties."""

    def test_is_service_available_true(self):
        """Test is_service_available property True."""
        from utils.web.url_fetcher_client import URLFetcherClient

        client = URLFetcherClient()
        client._service_available = True

        assert client.is_service_available is True

    def test_is_service_available_false(self):
        """Test is_service_available property False."""
        from utils.web.url_fetcher_client import URLFetcherClient

        client = URLFetcherClient()
        client._service_available = False

        assert client.is_service_available is False

    def test_is_service_available_none(self):
        """Test is_service_available property when None."""
        from utils.web.url_fetcher_client import URLFetcherClient

        client = URLFetcherClient()
        client._service_available = None

        assert client.is_service_available is False


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    @pytest.mark.asyncio
    async def test_fetch_url_function(self):
        """Test fetch_url convenience function."""
        from utils.web.url_fetcher_client import fetch_url

        with patch("utils.web.url_fetcher_client.URLFetcherClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.fetch = AsyncMock(return_value={"url": "http://test.com"})
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock()
            MockClient.return_value = mock_client

            result = await fetch_url("http://test.com")

            assert result["url"] == "http://test.com"
            mock_client.fetch.assert_called_once_with("http://test.com")

    @pytest.mark.asyncio
    async def test_fetch_urls_function(self):
        """Test fetch_urls convenience function."""
        from utils.web.url_fetcher_client import fetch_urls

        with patch("utils.web.url_fetcher_client.URLFetcherClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.fetch_batch = AsyncMock(return_value={"results": [], "success_count": 0})
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock()
            MockClient.return_value = mock_client

            urls = ["http://a.com", "http://b.com"]
            await fetch_urls(urls)

            mock_client.fetch_batch.assert_called_once_with(urls)


class TestConstants:
    """Tests for module constants."""

    def test_url_fetcher_url_format(self):
        """Test URL format."""
        from utils.web.url_fetcher_client import URL_FETCHER_URL

        assert URL_FETCHER_URL.startswith("http://")
        assert ":" in URL_FETCHER_URL

    def test_url_fetcher_host_defined(self):
        """Test host is defined."""
        from utils.web.url_fetcher_client import URL_FETCHER_HOST

        assert URL_FETCHER_HOST is not None

    def test_url_fetcher_port_defined(self):
        """Test port is defined."""
        from utils.web.url_fetcher_client import URL_FETCHER_PORT

        assert URL_FETCHER_PORT is not None


class TestModuleImports:
    """Tests for module structure."""

    def test_import_url_fetcher_client(self):
        """Test URLFetcherClient can be imported."""
        from utils.web.url_fetcher_client import URLFetcherClient

        assert URLFetcherClient is not None

    def test_import_fetch_url(self):
        """Test fetch_url can be imported."""
        from utils.web.url_fetcher_client import fetch_url

        assert fetch_url is not None

    def test_import_fetch_urls(self):
        """Test fetch_urls can be imported."""
        from utils.web.url_fetcher_client import fetch_urls

        assert fetch_urls is not None


# ======================================================================
# Deepened coverage for utils/web/url_fetcher.py — SSRF guards, redirect
# handling, content-type/size limits, DNS-rebind/IPv6, error paths.
# All hermetic: no real network, DNS, sleeps, or sessions.
# ======================================================================


def _make_resp(status=200, headers=None, body=b"", encoding="utf-8", url="http://t.example/"):
    """Build an awaitable-style aiohttp response mock.

    Mirrors the standard-fetch path which does ``await session.get(...)``
    (the response is used directly, not as an async context manager) and
    reads the body via ``response.content.read(...)``.
    """
    from unittest.mock import AsyncMock, MagicMock

    import yarl

    resp = MagicMock()
    resp.status = status
    resp.headers = headers or {}
    resp.url = yarl.URL(url)
    content = MagicMock()
    content.read = AsyncMock(return_value=body)
    resp.content = content
    resp.get_encoding = MagicMock(return_value=encoding)
    resp.close = MagicMock()
    return resp


def _make_cm_resp(status=200, headers=None, body=b"", json_data=None):
    """Build a response mock usable as an async context manager.

    Mirrors the GitHub-API path which does ``async with session.get(...)``.
    """
    from unittest.mock import AsyncMock, MagicMock

    resp = MagicMock()
    resp.status = status
    resp.headers = headers or {}
    resp.json = AsyncMock(return_value=json_data or {})
    resp.text = AsyncMock(return_value=body.decode("utf-8", "replace"))
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=resp)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _patch_fetch(session, *, private=False):
    """Context manager stack: stub SSRF check + shared session for a fetch.

    ``private`` controls the bool returned by ``_is_private_url``; pass a
    callable to vary per-URL.
    """
    from contextlib import ExitStack
    from unittest.mock import AsyncMock, patch

    from utils.web import url_fetcher as uf

    stack = ExitStack()
    if callable(private):
        ssrf = private
    else:
        ssrf = AsyncMock(return_value=private)
    stack.enter_context(patch.object(uf, "_is_private_url", new=ssrf))
    stack.enter_context(
        patch.object(uf, "_get_shared_session", new=AsyncMock(return_value=session))
    )
    return stack


@pytest.fixture(autouse=True)
def _clear_url_cache():
    """Clear the module-level URL cache before each new test in this section."""
    from utils.web import url_fetcher as uf

    uf._url_cache.clear()
    yield
    uf._url_cache.clear()


class TestIpIsBlocked:
    """Tests for _ip_is_blocked SSRF address classification."""

    def test_public_ipv4_allowed(self):
        from utils.web.url_fetcher import _ip_is_blocked

        assert _ip_is_blocked("8.8.8.8") is False

    def test_loopback_blocked(self):
        from utils.web.url_fetcher import _ip_is_blocked

        assert _ip_is_blocked("127.0.0.1") is True

    def test_private_class_a_blocked(self):
        from utils.web.url_fetcher import _ip_is_blocked

        assert _ip_is_blocked("10.0.0.5") is True

    def test_cloud_metadata_link_local_blocked(self):
        """169.254.169.254 (AWS/GCP/Azure metadata) must be blocked."""
        from utils.web.url_fetcher import _ip_is_blocked

        assert _ip_is_blocked("169.254.169.254") is True

    def test_invalid_ip_string_blocked(self):
        """Unparseable IPs fail closed (return True)."""
        from utils.web.url_fetcher import _ip_is_blocked

        assert _ip_is_blocked("not-an-ip") is True

    def test_ipv4_mapped_loopback_blocked(self):
        """::ffff:127.0.0.1 must be unwrapped and blocked (ipv4_mapped branch)."""
        from utils.web.url_fetcher import _ip_is_blocked

        assert _ip_is_blocked("::ffff:127.0.0.1") is True

    def test_ipv4_mapped_private_blocked(self):
        """IPv4-mapped private address bypass is closed."""
        from utils.web.url_fetcher import _ip_is_blocked

        assert _ip_is_blocked("::ffff:10.0.0.1") is True

    def test_ipv6_loopback_blocked(self):
        from utils.web.url_fetcher import _ip_is_blocked

        assert _ip_is_blocked("::1") is True

    def test_ipv4_mapped_address_blocked_wholesale(self):
        """The whole ::ffff:0:0/96 mapped range is blocked as hardening.

        Even a mapped *public* address is rejected because the entire
        IPv4-mapped IPv6 range is in _BLOCKED_NETWORKS — clients should
        never legitimately reach the fetcher via the mapped form.
        """
        from utils.web.url_fetcher import _ip_is_blocked

        assert _ip_is_blocked("::ffff:8.8.8.8") is True

    def test_ipv6_unspecified_blocked(self):
        """:: (the IPv6 twin of 0.0.0.0) must be blocked — on Linux/dual-stack
        a connect to :: routes to loopback, reaching internal listeners."""
        from utils.web.url_fetcher import _ip_is_blocked

        assert _ip_is_blocked("::") is True

    def test_nat64_embedded_loopback_blocked(self):
        """NAT64 64:ff9b::/96 embedding 127.0.0.1 must be blocked."""
        from utils.web.url_fetcher import _ip_is_blocked

        assert _ip_is_blocked("64:ff9b::7f00:1") is True

    def test_nat64_embedded_metadata_blocked(self):
        """NAT64 64:ff9b::/96 embedding 169.254.169.254 (cloud metadata) blocked."""
        from utils.web.url_fetcher import _ip_is_blocked

        assert _ip_is_blocked("64:ff9b::a9fe:a9fe") is True

    def test_6to4_embedded_loopback_blocked(self):
        """6to4 2002::/16 embedding 127.0.0.1 must be blocked."""
        from utils.web.url_fetcher import _ip_is_blocked

        assert _ip_is_blocked("2002:7f00:1::") is True

    def test_6to4_embedded_metadata_blocked(self):
        """6to4 2002::/16 embedding 169.254.169.254 (cloud metadata) blocked."""
        from utils.web.url_fetcher import _ip_is_blocked

        assert _ip_is_blocked("2002:a9fe:a9fe::") is True

    def test_nat64_local_use_embedded_metadata_blocked(self):
        """NAT64 local-use 64:ff9b:1::/48 (RFC 8215, is_reserved) embedding metadata."""
        from utils.web.url_fetcher import _ip_is_blocked

        assert _ip_is_blocked("64:ff9b:1::a9fe:a9fe") is True

    def test_teredo_blocked(self):
        """Teredo 2001::/32 (is_private) must be blocked."""
        from utils.web.url_fetcher import _ip_is_blocked

        assert _ip_is_blocked("2001::1") is True

    def test_reserved_documentation_blocked(self):
        """Reserved/documentation IPv6 (ORCHID 2001:10::, doc 3fff::, 2001:db8::,
        discard 100::) must be blocked — parity with the Go CIDR list."""
        from utils.web.url_fetcher import _ip_is_blocked

        assert _ip_is_blocked("2001:10::1") is True
        assert _ip_is_blocked("3fff::1") is True
        assert _ip_is_blocked("2001:db8::1") is True
        assert _ip_is_blocked("100::1") is True

    def test_public_ipv6_allowed(self):
        """A genuine public IPv6 (Google DNS) must NOT be blocked — confirms the
        is_unspecified/is_reserved/is_private short-circuit didn't over-block."""
        from utils.web.url_fetcher import _ip_is_blocked

        assert _ip_is_blocked("2001:4860:4860::8888") is False


class TestSSRFSafeResolver:
    """Tests for _SSRFSafeResolver connect-time DNS-rebind guard."""

    @pytest.mark.asyncio
    async def test_public_addresses_pass_through(self):
        from unittest.mock import AsyncMock, MagicMock

        from utils.web.url_fetcher import _SSRFSafeResolver

        base = MagicMock()
        base.resolve = AsyncMock(return_value=[{"host": "8.8.8.8", "port": 80}])
        resolver = _SSRFSafeResolver(base)

        result = await resolver.resolve("example.com", 80)

        assert result == [{"host": "8.8.8.8", "port": 80}]
        base.resolve.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_private_address_raises_oserror(self):
        """A host that resolves to a private IP at connect time is rejected."""
        from unittest.mock import AsyncMock, MagicMock

        from utils.web.url_fetcher import _SSRFSafeResolver

        base = MagicMock()
        base.resolve = AsyncMock(return_value=[{"host": "127.0.0.1"}])
        resolver = _SSRFSafeResolver(base)

        with pytest.raises(OSError, match="SSRF blocked"):
            await resolver.resolve("evil.example", 80)

    @pytest.mark.asyncio
    async def test_empty_host_entry_skipped(self):
        """Address entries with no host are skipped (the ``if not ip_str`` branch)."""
        from unittest.mock import AsyncMock, MagicMock

        from utils.web.url_fetcher import _SSRFSafeResolver

        base = MagicMock()
        base.resolve = AsyncMock(return_value=[{"host": ""}, {"host": "1.2.3.4"}])
        resolver = _SSRFSafeResolver(base)

        result = await resolver.resolve("x.example", 80)

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_unparseable_ip_blocked_fail_closed(self):
        """A malformed IP string is now BLOCKED (fail-closed).

        The resolver delegates to ``_ip_is_blocked``, which returns True on a
        ValueError, so an unparseable host raises instead of being skipped. A
        real aiohttp resolver only ever yields valid IP strings, so this never
        rejects legitimate traffic — it only removes a fail-open edge.
        """
        from unittest.mock import AsyncMock, MagicMock

        from utils.web.url_fetcher import _SSRFSafeResolver

        base = MagicMock()
        base.resolve = AsyncMock(return_value=[{"host": "garbage"}])
        resolver = _SSRFSafeResolver(base)

        with pytest.raises(OSError, match="SSRF blocked"):
            await resolver.resolve("x.example", 80)

    @pytest.mark.asyncio
    async def test_nat64_local_use_blocked_at_connect(self):
        """NAT64 local-use 64:ff9b:1::/48 embedding metadata is blocked at connect.

        Regression for the DNS-rebind gap: the connect-time resolver used a
        bare CIDR loop that only listed the NAT64 *well-known* prefix, so a host
        re-resolving to the NAT64 *local-use* prefix (RFC 8215, is_reserved,
        embeds 169.254.169.254) slipped through. Now it routes through
        _ip_is_blocked's is_reserved classification.
        """
        from unittest.mock import AsyncMock, MagicMock

        from utils.web.url_fetcher import _SSRFSafeResolver

        base = MagicMock()
        base.resolve = AsyncMock(return_value=[{"host": "64:ff9b:1::a9fe:a9fe"}])
        resolver = _SSRFSafeResolver(base)

        with pytest.raises(OSError, match="SSRF blocked"):
            await resolver.resolve("rebind.example", 80)

    @pytest.mark.asyncio
    async def test_teredo_blocked_at_connect(self):
        """Teredo 2001::/32 (is_private, embeds an IPv4 endpoint) blocked at connect."""
        from unittest.mock import AsyncMock, MagicMock

        from utils.web.url_fetcher import _SSRFSafeResolver

        base = MagicMock()
        base.resolve = AsyncMock(return_value=[{"host": "2001::1"}])
        resolver = _SSRFSafeResolver(base)

        with pytest.raises(OSError, match="SSRF blocked"):
            await resolver.resolve("rebind.example", 80)

    @pytest.mark.asyncio
    async def test_close_delegates_to_base(self):
        from unittest.mock import AsyncMock, MagicMock

        from utils.web.url_fetcher import _SSRFSafeResolver

        base = MagicMock()
        base.close = AsyncMock()
        resolver = _SSRFSafeResolver(base)

        await resolver.close()

        base.close.assert_awaited_once()


class TestIsPrivateUrl:
    """Tests for _is_private_url scheme + DNS resolution SSRF gate."""

    @pytest.mark.asyncio
    async def test_disallowed_scheme_blocked(self):
        """file:// (and other non-http schemes) are blocked."""
        from utils.web.url_fetcher import _is_private_url

        assert await _is_private_url("file:///etc/passwd") is True

    @pytest.mark.asyncio
    async def test_gopher_scheme_blocked(self):
        from utils.web.url_fetcher import _is_private_url

        assert await _is_private_url("gopher://internal/") is True

    @pytest.mark.asyncio
    async def test_missing_hostname_blocked(self):
        from utils.web.url_fetcher import _is_private_url

        assert await _is_private_url("http://") is True

    @pytest.mark.asyncio
    async def test_public_host_allowed(self, monkeypatch):
        """A host resolving only to a public IP returns False (allowed)."""
        import socket

        from utils.web.url_fetcher import _is_private_url

        fake = [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("8.8.8.8", 0))]
        monkeypatch.setattr("socket.getaddrinfo", lambda *a, **k: fake)

        assert await _is_private_url("https://public.example/") is False

    @pytest.mark.asyncio
    async def test_private_host_blocked(self, monkeypatch):
        """A host resolving to a private IP is blocked."""
        import socket

        from utils.web.url_fetcher import _is_private_url

        fake = [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("10.0.0.5", 0))]
        monkeypatch.setattr("socket.getaddrinfo", lambda *a, **k: fake)

        assert await _is_private_url("http://internal.example/") is True

    @pytest.mark.asyncio
    async def test_ipv6_unspecified_host_blocked(self, monkeypatch):
        """http://[::]/ must be blocked end-to-end (IPv6 twin of 0.0.0.0)."""
        import socket

        from utils.web.url_fetcher import _is_private_url

        fake = [(socket.AF_INET6, socket.SOCK_STREAM, 0, "", ("::", 0, 0, 0))]
        monkeypatch.setattr("socket.getaddrinfo", lambda *a, **k: fake)

        assert await _is_private_url("http://[::]/") is True

    @pytest.mark.asyncio
    async def test_dns_failure_blocked(self, monkeypatch):
        """DNS resolution failure fails closed (blocks)."""
        import socket

        from utils.web.url_fetcher import _is_private_url

        def boom(*a, **k):
            raise socket.gaierror("no such host")

        monkeypatch.setattr("socket.getaddrinfo", boom)

        assert await _is_private_url("http://nodns.example/") is True

    @pytest.mark.asyncio
    async def test_dns_timeout_blocked(self, monkeypatch):
        """A DNS resolution timeout fails closed (blocks)."""
        from utils.web import url_fetcher as uf

        async def slow_wait_for(*_a, **_k):
            raise TimeoutError

        monkeypatch.setattr(uf.asyncio, "wait_for", slow_wait_for)

        assert await uf._is_private_url("http://slow.example/") is True


class TestGetSharedSession:
    """Tests for the lazily-built shared SSRF-safe session lifecycle."""

    @pytest.mark.asyncio
    async def test_session_created_once_and_reused(self, monkeypatch):
        from unittest.mock import MagicMock

        from utils.web import url_fetcher as uf

        monkeypatch.setattr(uf, "_shared_session", None)
        created = MagicMock()
        created.closed = False
        cs = MagicMock(return_value=created)
        monkeypatch.setattr("aiohttp.ClientSession", cs)
        monkeypatch.setattr("aiohttp.TCPConnector", MagicMock())
        monkeypatch.setattr("aiohttp.ThreadedResolver", MagicMock())

        s1 = await uf._get_shared_session()
        s2 = await uf._get_shared_session()

        assert s1 is s2
        assert cs.call_count == 1
        # trust_env=False hardening must be applied.
        assert cs.call_args.kwargs.get("trust_env") is False

    @pytest.mark.asyncio
    async def test_closed_session_recreated(self, monkeypatch):
        """A session that reports ``closed`` is rebuilt rather than reused."""
        from unittest.mock import MagicMock

        from utils.web import url_fetcher as uf

        stale = MagicMock()
        stale.closed = True
        monkeypatch.setattr(uf, "_shared_session", stale)
        fresh = MagicMock()
        fresh.closed = False
        cs = MagicMock(return_value=fresh)
        monkeypatch.setattr("aiohttp.ClientSession", cs)
        monkeypatch.setattr("aiohttp.TCPConnector", MagicMock())
        monkeypatch.setattr("aiohttp.ThreadedResolver", MagicMock())

        result = await uf._get_shared_session()

        assert result is fresh
        assert cs.call_count == 1


class TestCloseSharedSession:
    """Tests for close_shared_session."""

    @pytest.mark.asyncio
    async def test_closes_open_session_and_nulls_global(self, monkeypatch):
        from unittest.mock import AsyncMock, MagicMock

        from utils.web import url_fetcher as uf

        session = MagicMock()
        session.closed = False
        session.close = AsyncMock()
        monkeypatch.setattr(uf, "_shared_session", session)

        await uf.close_shared_session()

        session.close.assert_awaited_once()
        assert uf._shared_session is None

    @pytest.mark.asyncio
    async def test_already_closed_session_not_reclosed(self, monkeypatch):
        from unittest.mock import AsyncMock, MagicMock

        from utils.web import url_fetcher as uf

        session = MagicMock()
        session.closed = True
        session.close = AsyncMock()
        monkeypatch.setattr(uf, "_shared_session", session)

        await uf.close_shared_session()

        session.close.assert_not_called()
        assert uf._shared_session is None

    @pytest.mark.asyncio
    async def test_none_session_is_noop(self, monkeypatch):
        from utils.web import url_fetcher as uf

        monkeypatch.setattr(uf, "_shared_session", None)

        await uf.close_shared_session()  # must not raise

        assert uf._shared_session is None


class TestUrlCacheLockLazyInit:
    """Tests for the lazily-built URL-cache lock."""

    def test_lock_created_and_memoized(self, monkeypatch):
        import asyncio

        from utils.web import url_fetcher as uf

        monkeypatch.setattr(uf, "_url_cache_lock", None)

        lock1 = uf._get_url_cache_lock()
        lock2 = uf._get_url_cache_lock()

        assert isinstance(lock1, asyncio.Lock)
        assert lock1 is lock2


class TestFetchUrlContentCache:
    """Tests for fetch_url_content caching behavior."""

    @pytest.mark.asyncio
    async def test_cache_hit_returns_without_network(self):
        """A fresh cache entry short-circuits before any SSRF/session work."""
        import time

        from utils.web import url_fetcher as uf

        uf._url_cache["http://cached.example/"] = ("Cached", "cached body", time.time())

        title, content = await uf.fetch_url_content("http://cached.example/")

        assert title == "Cached"
        assert content == "cached body"

    @pytest.mark.asyncio
    async def test_expired_cache_entry_evicted(self):
        """A stale entry (older than TTL) is deleted and re-fetched."""
        import time
        from unittest.mock import AsyncMock, patch

        from utils.web import url_fetcher as uf

        uf._url_cache["http://exp.example/"] = ("Old", "old body", time.time() - 10_000)

        # Make the re-fetch path bail at SSRF so we stay hermetic.
        with patch.object(uf, "_is_private_url", new=AsyncMock(return_value=True)):
            title, content = await uf.fetch_url_content("http://exp.example/")

        assert content is None
        assert "http://exp.example/" not in uf._url_cache


class TestFetchUrlContentSSRF:
    """Tests for fetch_url_content SSRF blocking at request entry."""

    @pytest.mark.asyncio
    async def test_private_url_blocked_returns_none(self):
        from unittest.mock import AsyncMock, patch

        from utils.web import url_fetcher as uf

        with patch.object(uf, "_is_private_url", new=AsyncMock(return_value=True)):
            title, content = await uf.fetch_url_content("http://internal.example/")

        assert title == "http://internal.example/"
        assert content is None

    @pytest.mark.asyncio
    async def test_caller_session_ignored(self):
        """A caller-supplied session is dropped in favour of the shared one."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from utils.web import url_fetcher as uf

        # If the caller session were used, this assertion would fail because
        # we never wire it in; instead the shared session must be requested.
        shared = MagicMock()
        shared.get = AsyncMock(
            return_value=_make_resp(
                200,
                {"Content-Type": "text/html"},
                b"<html><title>Ok</title><body>hi</body></html>",
            )
        )
        caller = MagicMock()
        caller.get = MagicMock(side_effect=AssertionError("caller session must not be used"))

        with (
            patch.object(uf, "_is_private_url", new=AsyncMock(return_value=False)),
            patch.object(uf, "_get_shared_session", new=AsyncMock(return_value=shared)),
        ):
            title, content = await uf.fetch_url_content("http://ok.example/", session=caller)

        assert content == "hi"


class TestFetchUrlContentStandard:
    """Tests for the standard (non-GitHub) webpage fetch path."""

    @pytest.mark.asyncio
    async def test_html_title_and_main_content(self):
        from unittest.mock import AsyncMock, MagicMock

        from utils.web import url_fetcher as uf

        html = (
            b"<html><head><title>Hello World</title></head>"
            b"<body><main>The main article body.</main></body></html>"
        )
        session = MagicMock()
        resp = _make_resp(200, {"Content-Type": "text/html; charset=utf-8"}, html)
        session.get = AsyncMock(return_value=resp)

        with _patch_fetch(session):
            title, content = await uf.fetch_url_content("http://page.example/x")

        assert title == "Hello World"
        assert content == "The main article body."
        # Response must be closed in the finally block.
        resp.close.assert_called_once()
        # Result cached.
        assert "http://page.example/x" in uf._url_cache

    @pytest.mark.asyncio
    async def test_empty_title_falls_back_to_url(self):
        from unittest.mock import AsyncMock, MagicMock

        from utils.web import url_fetcher as uf

        html = b"<html><head><title></title></head><body>some text</body></html>"
        session = MagicMock()
        session.get = AsyncMock(return_value=_make_resp(200, {"Content-Type": "text/html"}, html))

        with _patch_fetch(session):
            title, content = await uf.fetch_url_content("http://notitle.example/")

        assert title == "http://notitle.example/"
        assert content == "some text"

    @pytest.mark.asyncio
    async def test_body_fallback_when_no_main_container(self):
        """With no article/main/etc selector, content comes from <body>."""
        from unittest.mock import AsyncMock, MagicMock

        from utils.web import url_fetcher as uf

        html = b"<html><head><title>T</title></head><body><div>plain body</div></body></html>"
        session = MagicMock()
        session.get = AsyncMock(return_value=_make_resp(200, {"Content-Type": "text/html"}, html))

        with _patch_fetch(session):
            _title, content = await uf.fetch_url_content("http://body.example/")

        assert "plain body" in content

    @pytest.mark.asyncio
    async def test_scripts_and_nav_stripped(self):
        from unittest.mock import AsyncMock, MagicMock

        from utils.web import url_fetcher as uf

        html = (
            b"<html><head><title>T</title></head><body>"
            b"<nav>NAVLINKS</nav><script>var x=1;</script>"
            b"<main>real content</main><footer>FOOTERJUNK</footer>"
            b"</body></html>"
        )
        session = MagicMock()
        session.get = AsyncMock(return_value=_make_resp(200, {"Content-Type": "text/html"}, html))

        with _patch_fetch(session):
            _title, content = await uf.fetch_url_content("http://strip.example/")

        assert "real content" in content
        assert "NAVLINKS" not in content
        assert "FOOTERJUNK" not in content
        assert "var x" not in content

    @pytest.mark.asyncio
    async def test_long_content_truncated(self):
        from unittest.mock import AsyncMock, MagicMock

        from utils.web import url_fetcher as uf
        from utils.web.url_fetcher import MAX_CONTENT_LENGTH

        big = "A" * (MAX_CONTENT_LENGTH + 500)
        html = f"<html><head><title>T</title></head><body><main>{big}</main></body></html>".encode()
        session = MagicMock()
        session.get = AsyncMock(return_value=_make_resp(200, {"Content-Type": "text/html"}, html))

        with _patch_fetch(session):
            _title, content = await uf.fetch_url_content("http://big.example/")

        assert content.endswith("[Content truncated...]")
        assert len(content) <= MAX_CONTENT_LENGTH + len("\n[Content truncated...]")

    @pytest.mark.asyncio
    async def test_non_text_content_type_summarized(self):
        from unittest.mock import AsyncMock, MagicMock

        from utils.web import url_fetcher as uf

        session = MagicMock()
        session.get = AsyncMock(
            return_value=_make_resp(200, {"Content-Type": "application/json"}, b"{}")
        )

        with _patch_fetch(session):
            _title, content = await uf.fetch_url_content("http://json.example/")

        assert content == "[Non-text content: application/json]"

    @pytest.mark.asyncio
    async def test_content_type_exact_match_not_substring(self):
        """A spoofed MIME embedding text/html as a substring is NOT treated as HTML."""
        from unittest.mock import AsyncMock, MagicMock

        from utils.web import url_fetcher as uf

        session = MagicMock()
        session.get = AsyncMock(
            return_value=_make_resp(
                200, {"Content-Type": "application/text/html-weird"}, b"<body>x</body>"
            )
        )

        with _patch_fetch(session):
            _title, content = await uf.fetch_url_content("http://spoof.example/")

        assert content.startswith("[Non-text content:")

    @pytest.mark.asyncio
    async def test_content_length_header_too_large(self):
        from unittest.mock import AsyncMock, MagicMock

        from utils.web import url_fetcher as uf
        from utils.web.url_fetcher import MAX_RESPONSE_SIZE

        session = MagicMock()
        session.get = AsyncMock(
            return_value=_make_resp(
                200,
                {"Content-Type": "text/html", "Content-Length": str(MAX_RESPONSE_SIZE + 1)},
                b"x",
            )
        )

        with _patch_fetch(session):
            _title, content = await uf.fetch_url_content("http://huge.example/")

        assert "Content too large" in content
        assert str(MAX_RESPONSE_SIZE + 1) in content

    @pytest.mark.asyncio
    async def test_streamed_body_over_limit_rejected(self):
        """No/incorrect Content-Length but an oversized streamed body is rejected."""
        from unittest.mock import AsyncMock, MagicMock

        from utils.web import url_fetcher as uf
        from utils.web.url_fetcher import MAX_RESPONSE_SIZE

        session = MagicMock()
        session.get = AsyncMock(
            return_value=_make_resp(
                200, {"Content-Type": "text/html"}, b"x" * (MAX_RESPONSE_SIZE + 1)
            )
        )

        with _patch_fetch(session):
            _title, content = await uf.fetch_url_content("http://stream.example/")

        assert content == f"[Content too large: >{MAX_RESPONSE_SIZE} bytes]"

    @pytest.mark.asyncio
    async def test_binary_pdf_rejected_despite_html_content_type(self):
        from unittest.mock import AsyncMock, MagicMock

        from utils.web import url_fetcher as uf

        session = MagicMock()
        session.get = AsyncMock(
            return_value=_make_resp(200, {"Content-Type": "text/html"}, b"%PDF-1.7 binary junk")
        )

        with _patch_fetch(session):
            _title, content = await uf.fetch_url_content("http://pdf.example/")

        assert content.startswith("[Binary content despite Content-Type=")

    @pytest.mark.asyncio
    async def test_binary_pe_executable_rejected(self):
        """A Windows PE (MZ magic) is rejected even when served as text/html."""
        from unittest.mock import AsyncMock, MagicMock

        from utils.web import url_fetcher as uf

        session = MagicMock()
        session.get = AsyncMock(
            return_value=_make_resp(200, {"Content-Type": "text/html"}, b"MZ\x90\x00rest")
        )

        with _patch_fetch(session):
            _title, content = await uf.fetch_url_content("http://exe.example/")

        assert content.startswith("[Binary content despite Content-Type=")

    @pytest.mark.asyncio
    async def test_non_200_status_returns_none(self):
        from unittest.mock import AsyncMock, MagicMock

        from utils.web import url_fetcher as uf

        session = MagicMock()
        session.get = AsyncMock(
            return_value=_make_resp(404, {"Content-Type": "text/html"}, b"nope")
        )

        with _patch_fetch(session):
            title, content = await uf.fetch_url_content("http://missing.example/")

        assert title == "http://missing.example/"
        assert content is None

    @pytest.mark.asyncio
    async def test_decode_fallback_to_latin1(self):
        """Undecodable bytes fall back to latin-1 (LookupError/UnicodeDecodeError branch)."""
        from unittest.mock import AsyncMock, MagicMock

        from utils.web import url_fetcher as uf

        # Bytes invalid as utf-8; declare a bogus encoding to trigger LookupError.
        html = b"<html><head><title>caf\xe9</title></head><body>b\xe9dy</body></html>"
        session = MagicMock()
        resp = _make_resp(200, {"Content-Type": "text/html"}, html, encoding="not-a-real-encoding")
        session.get = AsyncMock(return_value=resp)

        with _patch_fetch(session):
            title, content = await uf.fetch_url_content("http://latin.example/")

        # latin-1 decodes every byte; we should get usable (non-None) content.
        assert content is not None
        assert "dy" in content


class TestFetchUrlContentRedirects:
    """Tests for manual redirect following + per-hop SSRF re-checks."""

    @pytest.mark.asyncio
    async def test_redirect_followed_to_final_200(self):
        from unittest.mock import AsyncMock, MagicMock

        from utils.web import url_fetcher as uf

        r1 = _make_resp(302, {"Location": "http://final.example/dest"}, url="http://start.example/")
        html = b"<html><head><title>Final</title></head><body>final body</body></html>"
        r2 = _make_resp(200, {"Content-Type": "text/html"}, html, url="http://final.example/dest")
        session = MagicMock()
        session.get = AsyncMock(side_effect=[r1, r2])

        with _patch_fetch(session):
            title, content = await uf.fetch_url_content("http://start.example/")

        assert title == "Final"
        assert content == "final body"
        # Both opened responses must be closed.
        r1.close.assert_called_once()
        r2.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_circular_redirect_blocked(self):
        from unittest.mock import AsyncMock, MagicMock

        from utils.web import url_fetcher as uf

        r1 = _make_resp(301, {"Location": "http://loop.example/"}, url="http://loop.example/")
        session = MagicMock()
        session.get = AsyncMock(side_effect=[r1])

        with _patch_fetch(session):
            title, content = await uf.fetch_url_content("http://loop.example/")

        assert content is None
        assert title == "http://loop.example/"

    @pytest.mark.asyncio
    async def test_redirect_to_private_blocked(self):
        """A redirect whose target resolves private is blocked mid-chain."""
        from unittest.mock import AsyncMock, MagicMock

        from utils.web import url_fetcher as uf

        r1 = _make_resp(302, {"Location": "http://internal.example/"}, url="http://start.example/")
        session = MagicMock()
        session.get = AsyncMock(side_effect=[r1])

        async def ssrf(url):
            return url == "http://internal.example/"

        with _patch_fetch(session, private=ssrf):
            title, content = await uf.fetch_url_content("http://start.example/")

        assert content is None
        assert title == "http://start.example/"

    @pytest.mark.asyncio
    async def test_redirect_without_location_stops(self):
        """A 3xx with no Location header breaks the loop -> non-200 -> None."""
        from unittest.mock import AsyncMock, MagicMock

        from utils.web import url_fetcher as uf

        r1 = _make_resp(302, {}, url="http://noloc.example/")
        session = MagicMock()
        session.get = AsyncMock(side_effect=[r1])

        with _patch_fetch(session):
            _title, content = await uf.fetch_url_content("http://noloc.example/")

        assert content is None

    @pytest.mark.asyncio
    async def test_redirect_limit_caps_hops(self):
        """More than 5 redirects stops; the loop exits with a 3xx -> None."""
        from unittest.mock import AsyncMock, MagicMock

        from utils.web import url_fetcher as uf

        # Build a long chain of distinct redirect targets (avoid circular block).
        chain = []
        for i in range(8):
            chain.append(
                _make_resp(
                    302,
                    {"Location": f"http://hop{i + 1}.example/"},
                    url=f"http://hop{i}.example/",
                )
            )
        session = MagicMock()
        session.get = AsyncMock(side_effect=chain)

        with _patch_fetch(session):
            _title, content = await uf.fetch_url_content("http://hop0.example/")

        # After 5 hops the loop exits while still on a 3xx response.
        assert content is None


class TestFetchUrlContentGitHub:
    """Tests for the GitHub-API special-case path."""

    @pytest.mark.asyncio
    async def test_github_repo_api_with_readme(self):
        from unittest.mock import AsyncMock, MagicMock

        from utils.web import url_fetcher as uf

        api_cm = _make_cm_resp(
            200,
            json_data={
                "full_name": "octocat/Hello-World",
                "description": "My first repository",
                "language": "Python",
                "stargazers_count": 42,
                "forks_count": 7,
                "topics": ["demo", "test"],
                "default_branch": "main",
            },
        )
        readme_cm = _make_cm_resp(200, body=b"# Hello\nThis is the readme.")
        session = MagicMock()
        session.get = MagicMock(side_effect=[api_cm, readme_cm])

        with _patch_fetch(session):
            title, content = await uf.fetch_url_content("https://github.com/octocat/Hello-World")

        assert title == "octocat/Hello-World"
        assert "Repository: octocat/Hello-World" in content
        assert "Stars: 42 | Forks: 7" in content
        assert "This is the readme." in content

    @pytest.mark.asyncio
    async def test_github_api_blocked_by_ssrf_recheck(self):
        """If the transformed api.github.com URL is flagged private, return None."""
        from unittest.mock import AsyncMock, MagicMock

        from utils.web import url_fetcher as uf

        session = MagicMock()
        session.get = MagicMock(side_effect=AssertionError("must not fetch when api URL blocked"))

        async def ssrf(url):
            # Allow the original github.com URL, block the transformed api URL.
            return "api.github.com" in url

        with _patch_fetch(session, private=ssrf):
            title, content = await uf.fetch_url_content("https://github.com/owner/repo")

        assert content is None
        assert title == "https://github.com/owner/repo/"

    @pytest.mark.asyncio
    async def test_github_api_failure_falls_through_to_standard_fetch(self):
        """When the GitHub API call raises, the code degrades to a normal page fetch."""
        from unittest.mock import AsyncMock, MagicMock

        from utils.web import url_fetcher as uf

        # First .get is the GitHub API (context-manager) and raises;
        # the except logs+falls through to the standard ``await session.get``.
        html = b"<html><head><title>Repo Page</title></head><body>page body</body></html>"
        std_resp = _make_resp(200, {"Content-Type": "text/html"}, html)

        call_state = {"n": 0}

        def get(url, *a, **k):
            call_state["n"] += 1
            if call_state["n"] == 1:
                raise RuntimeError("github api down")

            # Standard path awaits the coroutine returned by session.get.
            async def _coro():
                return std_resp

            return _coro()

        session = MagicMock()
        session.get = MagicMock(side_effect=get)

        with _patch_fetch(session):
            title, content = await uf.fetch_url_content("https://github.com/owner/repo")

        assert title == "Repo Page"
        assert content == "page body"


class TestFetchUrlContentErrors:
    """Tests for top-level exception handlers in fetch_url_content."""

    @pytest.mark.asyncio
    async def test_timeout_returns_none(self):
        from unittest.mock import AsyncMock, MagicMock

        from utils.web import url_fetcher as uf

        session = MagicMock()
        session.get = AsyncMock(side_effect=TimeoutError())

        with _patch_fetch(session):
            title, content = await uf.fetch_url_content("http://to.example/")

        assert title == "http://to.example/"
        assert content is None

    @pytest.mark.asyncio
    async def test_client_error_returns_none(self):
        from unittest.mock import AsyncMock, MagicMock

        import aiohttp

        from utils.web import url_fetcher as uf

        session = MagicMock()
        session.get = AsyncMock(side_effect=aiohttp.ClientError("connection reset"))

        with _patch_fetch(session):
            title, content = await uf.fetch_url_content("http://ce.example/")

        assert content is None

    @pytest.mark.asyncio
    async def test_unexpected_error_returns_none(self):
        from unittest.mock import AsyncMock, MagicMock

        from utils.web import url_fetcher as uf

        session = MagicMock()
        session.get = AsyncMock(side_effect=ValueError("boom"))

        with _patch_fetch(session):
            title, content = await uf.fetch_url_content("http://err.example/")

        assert content is None


class TestFetchAllUrls:
    """Tests for fetch_all_urls concurrent orchestration."""

    @pytest.mark.asyncio
    async def test_empty_list_returns_empty(self):
        from utils.web.url_fetcher import fetch_all_urls

        assert await fetch_all_urls([]) == []

    @pytest.mark.asyncio
    async def test_collects_results_and_honors_max_urls(self):
        from unittest.mock import patch

        from utils.web import url_fetcher as uf

        async def fake(url):
            return (f"Title-{url}", "body")

        with patch.object(uf, "fetch_url_content", new=fake):
            out = await uf.fetch_all_urls(
                ["http://a/", "http://b/", "http://c/", "http://d/"], max_urls=2
            )

        assert len(out) == 2
        assert out[0] == ("http://a/", "Title-http://a/", "body")
        assert out[1] == ("http://b/", "Title-http://b/", "body")

    @pytest.mark.asyncio
    async def test_exception_in_one_url_recorded_as_failure(self):
        from unittest.mock import patch

        from utils.web import url_fetcher as uf

        async def fake(url):
            if url == "http://boom/":
                raise ValueError("kaboom")
            return ("OK", "body")

        with patch.object(uf, "fetch_url_content", new=fake):
            out = await uf.fetch_all_urls(["http://ok/", "http://boom/"])

        ok_row = next(r for r in out if r[0] == "http://ok/")
        boom_row = next(r for r in out if r[0] == "http://boom/")
        assert ok_row == ("http://ok/", "OK", "body")
        # Failures fall back to (url, url, None).
        assert boom_row == ("http://boom/", "http://boom/", None)
