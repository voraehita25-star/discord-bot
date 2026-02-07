"""
Python client for Go Health API service.

Provides metrics pushing and health status checking.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

# Service configuration
HEALTH_API_HOST = os.getenv("HEALTH_API_HOST", "localhost")
HEALTH_API_PORT = os.getenv("HEALTH_API_PORT", "8082")
HEALTH_API_URL = f"http://{HEALTH_API_HOST}:{HEALTH_API_PORT}"


class HealthAPIClient:
    """
    Client for Go Health API service.

    Usage:
        client = HealthAPIClient()
        await client.push_counter("requests", 1, endpoint="/api")
        await client.push_histogram("response_time", 0.5, endpoint="/api")
        status = await client.get_health()
    """

    def __init__(self, base_url: str | None = None):
        self.base_url = base_url or HEALTH_API_URL
        self._session: aiohttp.ClientSession | None = None
        self._service_available: bool | None = None
        self._metrics_buffer: list[dict] = []
        self._buffer_lock = asyncio.Lock()
        self._connect_lock = asyncio.Lock()

    async def connect(self):
        """Initialize the client session."""
        async with self._connect_lock:
            if self._session is not None:
                return  # Already connected

            session = None
            try:
                session = aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=5)
                )
                self._session = session
                await self._check_service()
            except Exception as e:
                # Clean up session if service check fails
                logging.debug("Health client connection failed: %s", e)
                if session:
                    await session.close()
                self._session = None
                raise

    async def close(self):
        """Close the client session."""
        if self._session:
            # Flush remaining metrics
            await self._flush_buffer()
            await self._session.close()
            self._session = None

    async def _check_service(self) -> bool:
        """Check if Go service is available (re-checks every 5 minutes)."""
        import time as _time
        now = _time.monotonic()
        if self._service_available is not None and (now - getattr(self, '_last_service_check', 0)) < 300:
            return self._service_available

        if self._session is None:
            self._service_available = False
            self._last_service_check = now
            logger.warning("⚠️ Go Health API session not initialized")
            return False

        try:
            async with self._session.get(f"{self.base_url}/health/live") as resp:
                self._service_available = resp.status == 200
                self._last_service_check = now
                if self._service_available:
                    logger.info("✅ Go Health API service available")
                return self._service_available
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            self._service_available = False
            self._last_service_check = now
            logger.warning("⚠️ Go Health API not available, metrics disabled")
            return False

    async def get_health(self) -> dict[str, Any]:
        """Get health status."""
        if not self._service_available or self._session is None:
            return {"status": "unknown", "error": "service unavailable"}

        try:
            async with self._session.get(f"{self.base_url}/health") as resp:
                return await resp.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            return {"status": "error", "error": str(e)}

    async def is_ready(self) -> bool:
        """Check if service is ready."""
        if not self._service_available or self._session is None:
            return True  # Assume ready if no health service

        try:
            async with self._session.get(f"{self.base_url}/health/ready") as resp:
                return resp.status == 200
        except Exception as e:
            logger.debug("Health ready check failed: %s", e)
            return True

    async def set_service_status(self, name: str, healthy: bool):
        """Update a service's health status."""
        if not self._service_available:
            return

        try:
            async with self._session.post(
                f"{self.base_url}/health/service",
                json={"name": name, "healthy": healthy}
            ) as resp:
                pass  # Response is auto-closed by async with
        except Exception as e:
            logger.debug("Failed to set service status for %s: %s", name, e)

    async def push_counter(self, name: str, value: float = 1, **labels):
        """Push a counter metric."""
        await self._push_metric("counter", name, value, labels)

    async def push_histogram(self, name: str, value: float, **labels):
        """Push a histogram metric."""
        await self._push_metric("histogram", name, value, labels)

    async def push_gauge(self, name: str, value: float, **labels):
        """Push a gauge metric."""
        await self._push_metric("gauge", name, value, labels)

    async def _push_metric(self, metric_type: str, name: str, value: float, labels: dict):
        """Push a metric to the buffer."""
        if not self._service_available:
            return

        metric = {
            "type": metric_type,
            "name": name,
            "value": value,
            "labels": labels,
        }

        async with self._buffer_lock:
            self._metrics_buffer.append(metric)

            # Auto-flush if buffer is large
            if len(self._metrics_buffer) >= 50:
                await self._flush_buffer_locked()

    async def _flush_buffer(self):
        """Flush metrics buffer to service."""
        async with self._buffer_lock:
            await self._flush_buffer_locked()

    async def _flush_buffer_locked(self):
        """Flush buffer (must hold lock)."""
        if not self._metrics_buffer or not self._service_available or self._session is None:
            return

        metrics = self._metrics_buffer[:]
        self._metrics_buffer.clear()

        try:
            async with self._session.post(
                f"{self.base_url}/metrics/batch",
                json=metrics
            ) as resp:
                pass  # Response is auto-closed by async with
        except Exception as e:
            # Re-add to buffer on failure (limited)
            logger.debug("Failed to flush metrics batch: %s", e)
            if len(metrics) < 100:
                self._metrics_buffer.extend(metrics)

    @property
    def is_available(self) -> bool:
        """Check if service is available."""
        return self._service_available or False


# Global client instance
_client: HealthAPIClient | None = None


async def get_health_client() -> HealthAPIClient:
    """Get or create the global health client."""
    global _client
    if _client is None:
        _client = HealthAPIClient()
        await _client.connect()
    return _client


async def close_health_client() -> None:
    """Close and cleanup the global health client.
    
    Should be called during bot shutdown to properly close connections
    and flush any pending metrics.
    """
    global _client
    if _client is not None:
        await _client.close()
        _client = None


async def push_request_metric(endpoint: str, status: str = "success", duration: float | None = None):
    """Push request metrics."""
    client = await get_health_client()
    await client.push_counter("requests", 1, endpoint=endpoint, status=status)
    if duration:
        await client.push_histogram("request_duration", duration, endpoint=endpoint)


async def push_ai_response_time(duration: float):
    """Push AI response time metric."""
    client = await get_health_client()
    await client.push_histogram("ai_response_time", duration)


async def push_rate_limit_hit(limit_type: str):
    """Push rate limit hit metric."""
    client = await get_health_client()
    await client.push_counter("rate_limit", 1, type=limit_type)


async def push_cache_metric(hit: bool):
    """Push cache hit/miss metric."""
    client = await get_health_client()
    await client.push_counter("cache", 1, result="hit" if hit else "miss")


async def push_token_usage(input_tokens: int, output_tokens: int):
    """Push token usage metrics."""
    client = await get_health_client()
    await client.push_counter("tokens", input_tokens, type="input")
    await client.push_counter("tokens", output_tokens, type="output")


async def set_circuit_breaker_state(service: str, state: int):
    """Set circuit breaker state (0=closed, 1=half-open, 2=open)."""
    client = await get_health_client()
    await client.push_gauge("circuit_breaker", state, service=service)


async def get_health_status() -> dict[str, Any]:
    """Get current health status."""
    client = await get_health_client()
    return await client.get_health()
