"""
Tests for utils/web/url_fetcher_client.py

Comprehensive tests for URLFetcherClient.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


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
        """Test cached result True is returned."""
        from utils.web.url_fetcher_client import URLFetcherClient

        client = URLFetcherClient()
        client._service_available = True

        result = await client._check_service()

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
        from utils.web.url_fetcher_client import URLFetcherClient

        client = URLFetcherClient()

        mock_response = AsyncMock()
        mock_response.json = AsyncMock(return_value={
            "url": "http://test.com",
            "title": "Test",
            "content": "Content"
        })
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock()

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_response)
        client._session = mock_session

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
    async def test_fetch_fallback_success_html(self):
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
    async def test_fetch_fallback_non_200_status(self):
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
    async def test_fetch_fallback_exception(self):
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
        client._fetch_batch_via_service = AsyncMock(return_value={
            "results": [],
            "success_count": 0,
            "error_count": 0
        })

        urls = ["http://a.com", "http://b.com"]
        await client.fetch_batch(urls)

        client._fetch_batch_via_service.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_batch_uses_fallback(self):
        """Test fetch_batch uses fallback when unavailable."""
        from utils.web.url_fetcher_client import URLFetcherClient

        client = URLFetcherClient()
        client._service_available = False
        client._fetch_batch_fallback = AsyncMock(return_value={
            "results": [],
            "success_count": 0,
            "error_count": 0
        })

        urls = ["http://a.com", "http://b.com"]
        await client.fetch_batch(urls)

        client._fetch_batch_fallback.assert_called_once_with(urls)


class TestURLFetcherClientFetchBatchViaService:
    """Tests for _fetch_batch_via_service method."""

    @pytest.mark.asyncio
    async def test_fetch_batch_via_service_success(self):
        """Test successful batch fetch via service."""
        from utils.web.url_fetcher_client import URLFetcherClient

        client = URLFetcherClient()

        mock_response = AsyncMock()
        mock_response.json = AsyncMock(return_value={
            "results": [
                {"url": "http://a.com", "title": "A"},
                {"url": "http://b.com", "title": "B"}
            ],
            "success_count": 2,
            "error_count": 0
        })
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
    async def test_fetch_batch_via_service_with_timeout(self):
        """Test batch fetch via service with timeout."""
        from utils.web.url_fetcher_client import URLFetcherClient

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
        client._fetch_fallback = AsyncMock(side_effect=[
            {"url": "http://a.com", "title": "A"},
            {"url": "http://b.com", "title": "B"}
        ])

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
        client._fetch_fallback = AsyncMock(side_effect=[
            {"url": "http://a.com", "title": "A"},
            {"url": "http://b.com", "error": "Failed"}
        ])

        urls = ["http://a.com", "http://b.com"]
        result = await client._fetch_batch_fallback(urls)

        assert result["success_count"] == 1
        assert result["error_count"] == 1

    @pytest.mark.asyncio
    async def test_fetch_batch_fallback_exception(self):
        """Test batch fallback with exception in task."""
        from utils.web.url_fetcher_client import URLFetcherClient

        client = URLFetcherClient()
        client._fetch_fallback = AsyncMock(side_effect=[
            {"url": "http://a.com", "title": "A"},
            Exception("Connection error")
        ])

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
            mock_client.fetch_batch = AsyncMock(return_value={
                "results": [],
                "success_count": 0
            })
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

    def test_module_imports(self):
        """Test module can be imported."""
        import utils.web.url_fetcher_client

        assert utils.web.url_fetcher_client is not None

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
