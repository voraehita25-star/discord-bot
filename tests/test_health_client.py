"""
Tests for utils/monitoring/health_client.py

Comprehensive tests for HealthAPIClient and helper functions.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestHealthAPIClientInit:
    """Tests for HealthAPIClient initialization."""

    def test_init_default_url(self):
        """Test default URL from env."""
        from utils.monitoring.health_client import HealthAPIClient

        client = HealthAPIClient()
        assert client.base_url is not None
        assert "localhost" in client.base_url or "http" in client.base_url

    def test_init_custom_url(self):
        """Test custom base URL."""
        from utils.monitoring.health_client import HealthAPIClient

        client = HealthAPIClient(base_url="http://custom:9000")
        assert client.base_url == "http://custom:9000"

    def test_init_session_none(self):
        """Test session starts as None."""
        from utils.monitoring.health_client import HealthAPIClient

        client = HealthAPIClient()
        assert client._session is None

    def test_init_service_available_none(self):
        """Test service_available starts as None."""
        from utils.monitoring.health_client import HealthAPIClient

        client = HealthAPIClient()
        assert client._service_available is None

    def test_init_metrics_buffer_empty(self):
        """Test metrics buffer starts empty."""
        from utils.monitoring.health_client import HealthAPIClient

        client = HealthAPIClient()
        assert client._metrics_buffer == []

    def test_init_buffer_lock_exists(self):
        """Test buffer lock is created."""
        from utils.monitoring.health_client import HealthAPIClient

        client = HealthAPIClient()
        assert client._buffer_lock is not None


class TestHealthAPIClientConnect:
    """Tests for connect method."""

    @pytest.mark.asyncio
    async def test_connect_creates_session(self):
        """Test connect creates aiohttp session."""
        from utils.monitoring.health_client import HealthAPIClient

        client = HealthAPIClient()
        client._check_service = AsyncMock(return_value=False)

        await client.connect()

        assert client._session is not None
        await client.close()

    @pytest.mark.asyncio
    async def test_connect_calls_check_service(self):
        """Test connect calls _check_service."""
        from utils.monitoring.health_client import HealthAPIClient

        client = HealthAPIClient()
        client._check_service = AsyncMock(return_value=True)

        await client.connect()

        client._check_service.assert_called_once()
        await client.close()


class TestHealthAPIClientClose:
    """Tests for close method."""

    @pytest.mark.asyncio
    async def test_close_clears_session(self):
        """Test close clears session."""
        from utils.monitoring.health_client import HealthAPIClient

        client = HealthAPIClient()
        client._check_service = AsyncMock(return_value=False)
        client._flush_buffer = AsyncMock()

        await client.connect()
        await client.close()

        assert client._session is None

    @pytest.mark.asyncio
    async def test_close_flushes_buffer(self):
        """Test close flushes metrics buffer."""
        from utils.monitoring.health_client import HealthAPIClient

        client = HealthAPIClient()
        client._check_service = AsyncMock(return_value=False)
        client._flush_buffer = AsyncMock()

        await client.connect()
        await client.close()

        client._flush_buffer.assert_called_once()


class TestHealthAPIClientCheckService:
    """Tests for _check_service method."""

    @pytest.mark.asyncio
    async def test_check_service_returns_cached(self):
        """Test cached result is returned."""
        from utils.monitoring.health_client import HealthAPIClient

        client = HealthAPIClient()
        client._service_available = True

        result = await client._check_service()

        assert result is True

    @pytest.mark.asyncio
    async def test_check_service_cached_false(self):
        """Test cached False is returned."""
        from utils.monitoring.health_client import HealthAPIClient

        client = HealthAPIClient()
        client._service_available = False

        result = await client._check_service()

        assert result is False


class TestHealthAPIClientGetHealth:
    """Tests for get_health method."""

    @pytest.mark.asyncio
    async def test_get_health_unavailable(self):
        """Test get_health when service unavailable."""
        from utils.monitoring.health_client import HealthAPIClient

        client = HealthAPIClient()
        client._service_available = False

        result = await client.get_health()

        assert result["status"] == "unknown"
        assert "error" in result

    @pytest.mark.asyncio
    async def test_get_health_success(self):
        """Test get_health success."""
        from utils.monitoring.health_client import HealthAPIClient

        client = HealthAPIClient()
        client._service_available = True

        mock_response = AsyncMock()
        mock_response.json = AsyncMock(return_value={"status": "healthy"})
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock()

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_response)
        client._session = mock_session

        result = await client.get_health()

        assert result["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_get_health_exception(self):
        """Test get_health handles exception."""
        from utils.monitoring.health_client import HealthAPIClient

        client = HealthAPIClient()
        client._service_available = True

        mock_session = MagicMock()
        mock_session.get = MagicMock(side_effect=Exception("Connection error"))
        client._session = mock_session

        result = await client.get_health()

        assert result["status"] == "error"
        assert "Connection error" in result["error"]


class TestHealthAPIClientIsReady:
    """Tests for is_ready method."""

    @pytest.mark.asyncio
    async def test_is_ready_unavailable_returns_true(self):
        """Test is_ready returns True when service unavailable."""
        from utils.monitoring.health_client import HealthAPIClient

        client = HealthAPIClient()
        client._service_available = False

        result = await client.is_ready()

        assert result is True

    @pytest.mark.asyncio
    async def test_is_ready_success(self):
        """Test is_ready success."""
        from utils.monitoring.health_client import HealthAPIClient

        client = HealthAPIClient()
        client._service_available = True

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock()

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_response)
        client._session = mock_session

        result = await client.is_ready()

        assert result is True

    @pytest.mark.asyncio
    async def test_is_ready_exception_returns_true(self):
        """Test is_ready returns True on exception."""
        from utils.monitoring.health_client import HealthAPIClient

        client = HealthAPIClient()
        client._service_available = True

        mock_session = MagicMock()
        mock_session.get = MagicMock(side_effect=Exception("Connection error"))
        client._session = mock_session

        result = await client.is_ready()

        assert result is True


class TestHealthAPIClientSetServiceStatus:
    """Tests for set_service_status method."""

    @pytest.mark.asyncio
    async def test_set_service_status_unavailable(self):
        """Test set_service_status returns early when unavailable."""
        from utils.monitoring.health_client import HealthAPIClient

        client = HealthAPIClient()
        client._service_available = False

        # Should not raise any errors
        await client.set_service_status("test", True)

    @pytest.mark.asyncio
    async def test_set_service_status_success(self):
        """Test set_service_status posts correctly."""
        from utils.monitoring.health_client import HealthAPIClient

        client = HealthAPIClient()
        client._service_available = True

        mock_response = AsyncMock()
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock()

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_response)
        client._session = mock_session

        await client.set_service_status("database", True)

        mock_session.post.assert_called_once()


class TestHealthAPIClientPushMethods:
    """Tests for push_* methods."""

    @pytest.mark.asyncio
    async def test_push_counter(self):
        """Test push_counter calls _push_metric."""
        from utils.monitoring.health_client import HealthAPIClient

        client = HealthAPIClient()
        client._push_metric = AsyncMock()

        await client.push_counter("requests", 1, endpoint="/api")

        client._push_metric.assert_called_once_with(
            "counter", "requests", 1, {"endpoint": "/api"}
        )

    @pytest.mark.asyncio
    async def test_push_histogram(self):
        """Test push_histogram calls _push_metric."""
        from utils.monitoring.health_client import HealthAPIClient

        client = HealthAPIClient()
        client._push_metric = AsyncMock()

        await client.push_histogram("latency", 0.5, method="GET")

        client._push_metric.assert_called_once_with(
            "histogram", "latency", 0.5, {"method": "GET"}
        )

    @pytest.mark.asyncio
    async def test_push_gauge(self):
        """Test push_gauge calls _push_metric."""
        from utils.monitoring.health_client import HealthAPIClient

        client = HealthAPIClient()
        client._push_metric = AsyncMock()

        await client.push_gauge("queue_size", 10, queue="main")

        client._push_metric.assert_called_once_with(
            "gauge", "queue_size", 10, {"queue": "main"}
        )


class TestHealthAPIClientPushMetric:
    """Tests for _push_metric method."""

    @pytest.mark.asyncio
    async def test_push_metric_unavailable(self):
        """Test _push_metric returns early when unavailable."""
        from utils.monitoring.health_client import HealthAPIClient

        client = HealthAPIClient()
        client._service_available = False

        await client._push_metric("counter", "test", 1, {})

        assert len(client._metrics_buffer) == 0

    @pytest.mark.asyncio
    async def test_push_metric_adds_to_buffer(self):
        """Test _push_metric adds to buffer."""
        from utils.monitoring.health_client import HealthAPIClient

        client = HealthAPIClient()
        client._service_available = True
        client._flush_buffer_locked = AsyncMock()

        await client._push_metric("counter", "test", 1, {"label": "value"})

        assert len(client._metrics_buffer) == 1
        assert client._metrics_buffer[0]["type"] == "counter"
        assert client._metrics_buffer[0]["name"] == "test"
        assert client._metrics_buffer[0]["value"] == 1

    @pytest.mark.asyncio
    async def test_push_metric_auto_flush_at_50(self):
        """Test auto-flush when buffer reaches 50."""
        from utils.monitoring.health_client import HealthAPIClient

        client = HealthAPIClient()
        client._service_available = True
        client._flush_buffer_locked = AsyncMock()

        # Add 50 metrics
        for i in range(50):
            await client._push_metric("counter", f"test{i}", 1, {})

        client._flush_buffer_locked.assert_called()


class TestHealthAPIClientFlushBuffer:
    """Tests for _flush_buffer and _flush_buffer_locked methods."""

    @pytest.mark.asyncio
    async def test_flush_buffer_empty(self):
        """Test flush_buffer with empty buffer."""
        from utils.monitoring.health_client import HealthAPIClient

        client = HealthAPIClient()
        client._service_available = True
        client._metrics_buffer = []

        # Should not raise
        await client._flush_buffer()

    @pytest.mark.asyncio
    async def test_flush_buffer_unavailable(self):
        """Test flush_buffer when service unavailable."""
        from utils.monitoring.health_client import HealthAPIClient

        client = HealthAPIClient()
        client._service_available = False
        client._metrics_buffer = [{"type": "counter"}]

        await client._flush_buffer()

        # Buffer should remain
        assert len(client._metrics_buffer) == 1


class TestHealthAPIClientProperties:
    """Tests for properties."""

    def test_is_available_true(self):
        """Test is_available property True."""
        from utils.monitoring.health_client import HealthAPIClient

        client = HealthAPIClient()
        client._service_available = True

        assert client.is_available is True

    def test_is_available_false(self):
        """Test is_available property False."""
        from utils.monitoring.health_client import HealthAPIClient

        client = HealthAPIClient()
        client._service_available = False

        assert client.is_available is False

    def test_is_available_none(self):
        """Test is_available property when None."""
        from utils.monitoring.health_client import HealthAPIClient

        client = HealthAPIClient()
        client._service_available = None

        assert client.is_available is False


class TestHelperFunctions:
    """Tests for module-level helper functions."""

    @pytest.mark.asyncio
    async def test_push_request_metric(self):
        """Test push_request_metric helper."""
        from utils.monitoring.health_client import push_request_metric

        with patch("utils.monitoring.health_client.get_health_client") as mock_get:
            mock_client = AsyncMock()
            mock_get.return_value = mock_client

            await push_request_metric("/api", "success", 0.5)

            mock_client.push_counter.assert_called()
            mock_client.push_histogram.assert_called()

    @pytest.mark.asyncio
    async def test_push_request_metric_no_duration(self):
        """Test push_request_metric without duration."""
        from utils.monitoring.health_client import push_request_metric

        with patch("utils.monitoring.health_client.get_health_client") as mock_get:
            mock_client = AsyncMock()
            mock_get.return_value = mock_client

            await push_request_metric("/api", "error")

            mock_client.push_counter.assert_called_once()
            mock_client.push_histogram.assert_not_called()

    @pytest.mark.asyncio
    async def test_push_ai_response_time(self):
        """Test push_ai_response_time helper."""
        from utils.monitoring.health_client import push_ai_response_time

        with patch("utils.monitoring.health_client.get_health_client") as mock_get:
            mock_client = AsyncMock()
            mock_get.return_value = mock_client

            await push_ai_response_time(1.5)

            mock_client.push_histogram.assert_called_once_with(
                "ai_response_time", 1.5
            )

    @pytest.mark.asyncio
    async def test_push_rate_limit_hit(self):
        """Test push_rate_limit_hit helper."""
        from utils.monitoring.health_client import push_rate_limit_hit

        with patch("utils.monitoring.health_client.get_health_client") as mock_get:
            mock_client = AsyncMock()
            mock_get.return_value = mock_client

            await push_rate_limit_hit("user")

            mock_client.push_counter.assert_called_once_with(
                "rate_limit", 1, type="user"
            )

    @pytest.mark.asyncio
    async def test_push_cache_metric_hit(self):
        """Test push_cache_metric for hit."""
        from utils.monitoring.health_client import push_cache_metric

        with patch("utils.monitoring.health_client.get_health_client") as mock_get:
            mock_client = AsyncMock()
            mock_get.return_value = mock_client

            await push_cache_metric(hit=True)

            mock_client.push_counter.assert_called_once_with(
                "cache", 1, result="hit"
            )

    @pytest.mark.asyncio
    async def test_push_cache_metric_miss(self):
        """Test push_cache_metric for miss."""
        from utils.monitoring.health_client import push_cache_metric

        with patch("utils.monitoring.health_client.get_health_client") as mock_get:
            mock_client = AsyncMock()
            mock_get.return_value = mock_client

            await push_cache_metric(hit=False)

            mock_client.push_counter.assert_called_once_with(
                "cache", 1, result="miss"
            )

    @pytest.mark.asyncio
    async def test_push_token_usage(self):
        """Test push_token_usage helper."""
        from utils.monitoring.health_client import push_token_usage

        with patch("utils.monitoring.health_client.get_health_client") as mock_get:
            mock_client = AsyncMock()
            mock_get.return_value = mock_client

            await push_token_usage(100, 50)

            assert mock_client.push_counter.call_count == 2

    @pytest.mark.asyncio
    async def test_set_circuit_breaker_state(self):
        """Test set_circuit_breaker_state helper."""
        from utils.monitoring.health_client import set_circuit_breaker_state

        with patch("utils.monitoring.health_client.get_health_client") as mock_get:
            mock_client = AsyncMock()
            mock_get.return_value = mock_client

            await set_circuit_breaker_state("api", 2)

            mock_client.push_gauge.assert_called_once_with(
                "circuit_breaker", 2, service="api"
            )

    @pytest.mark.asyncio
    async def test_get_health_status(self):
        """Test get_health_status helper."""
        from utils.monitoring.health_client import get_health_status

        with patch("utils.monitoring.health_client.get_health_client") as mock_get:
            mock_client = AsyncMock()
            mock_client.get_health = AsyncMock(return_value={"status": "healthy"})
            mock_get.return_value = mock_client

            result = await get_health_status()

            assert result["status"] == "healthy"


class TestConstants:
    """Tests for module constants."""

    def test_health_api_url_format(self):
        """Test URL format."""
        from utils.monitoring.health_client import HEALTH_API_URL

        assert HEALTH_API_URL.startswith("http://")
        assert ":" in HEALTH_API_URL

    def test_health_api_host_defined(self):
        """Test host is defined."""
        from utils.monitoring.health_client import HEALTH_API_HOST

        assert HEALTH_API_HOST is not None

    def test_health_api_port_defined(self):
        """Test port is defined."""
        from utils.monitoring.health_client import HEALTH_API_PORT

        assert HEALTH_API_PORT is not None
