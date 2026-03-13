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
# GO_HEALTH_API_PORT controls the Go health service port (default 8082).
# Falls back to HEALTH_API_PORT for backward compatibility, but prefer
# GO_HEALTH_API_PORT to avoid collision with the Python health server
# (which also reads HEALTH_API_PORT, defaulting to 8080).
HEALTH_API_HOST = os.getenv("HEALTH_API_HOST", "localhost")
HEALTH_API_PORT = os.getenv("GO_HEALTH_API_PORT") or os.getenv("HEALTH_API_PORT", "8082")
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
        self._last_service_check: float = 0
        self._retry_count: int = 0  # consecutive unavailable checks, for exponential backoff
        self._metrics_buffer: list[dict] = []
        self._flush_task: asyncio.Task | None = None
        # Lazily initialized to avoid event loop binding issues
        self._buffer_lock: asyncio.Lock | None = None
        self._connect_lock: asyncio.Lock | None = None

    def _get_buffer_lock(self) -> asyncio.Lock:
        """Lazily create buffer lock to avoid event loop binding issues."""
        if self._buffer_lock is None:
            self._buffer_lock = asyncio.Lock()
        return self._buffer_lock

    def _get_connect_lock(self) -> asyncio.Lock:
        """Lazily create connect lock to avoid event loop binding issues."""
        if self._connect_lock is None:
            self._connect_lock = asyncio.Lock()
        return self._connect_lock

    async def connect(self):
        """Initialize the client session."""
        async with self._get_connect_lock():
            if self._session is not None:
                return  # Already connected

            session = None
            try:
                session = aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=5)
                )
                self._session = session
                await self._check_service()
                # Start periodic flush task once connected
                self._flush_task = asyncio.create_task(self._periodic_flush())
            except Exception as e:
                # Clean up session if service check fails
                logging.debug("Health client connection failed: %s", e)
                if session:
                    await session.close()
                self._session = None
                raise

    async def _periodic_flush(self) -> None:
        """Flush metrics buffer every 30 seconds to avoid staleness during low traffic."""
        try:
            while True:
                await asyncio.sleep(30)
                if self._session is not None:
                    await self._flush_buffer()
        except asyncio.CancelledError:
            pass

    async def close(self):
        """Close the client session."""
        # Cancel periodic flush task
        if self._flush_task and not self._flush_task.done():
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        self._flush_task = None

        if self._session:
            # Flush remaining metrics
            await self._flush_buffer()
            await self._session.close()
            self._session = None

    async def _check_service(self) -> bool:
        """Check if Go service is available.

        Uses exponential backoff when unavailable (30s → 60s → 120s → 300s max)
        and a fixed 5-minute interval when available.
        """
        import time as _time
        now = _time.monotonic()
        elapsed = now - self._last_service_check

        if self._service_available is not None:
            if self._service_available:
                if elapsed < 300:  # 5 min when healthy
                    return True
            else:
                # Backoff: 30s * 2^retry_count, capped at 300s
                backoff = min(30 * (2 ** self._retry_count), 300)
                if elapsed < backoff:
                    return False

        if self._session is None:
            self._service_available = False
            self._last_service_check = now
            logger.warning("⚠️ Go Health API session not initialized")
            return False

        try:
            async with self._session.get(f"{self.base_url}/health/live") as resp:
                available = resp.status == 200
                if available and not self._service_available:
                    logger.info("✅ Go Health API service available")
                    self._retry_count = 0  # reset backoff on recovery
                self._service_available = available
                self._last_service_check = now
                return available
        except (TimeoutError, aiohttp.ClientError):
            self._service_available = False
            self._last_service_check = now
            self._retry_count = min(self._retry_count + 1, 4)  # cap at 2^4=16 → 300s
            logger.warning("⚠️ Go Health API not available, metrics disabled")
            return False

    async def get_health(self) -> dict[str, Any]:
        """Get health status."""
        if not self._service_available or self._session is None:
            return {"status": "unknown", "error": "service unavailable"}

        try:
            async with self._session.get(f"{self.base_url}/health") as resp:
                return await resp.json()
        except (TimeoutError, aiohttp.ClientError) as e:
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
            ):
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

        async with self._get_buffer_lock():
            self._metrics_buffer.append(metric)

            # Auto-flush if buffer is large
            if len(self._metrics_buffer) >= 50:
                await self._flush_buffer_locked()

    async def _flush_buffer(self):
        """Flush metrics buffer to service."""
        async with self._get_buffer_lock():
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
            ):
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
_client_lock: asyncio.Lock | None = None


def _get_client_lock() -> asyncio.Lock:
    """Lazily create the client lock."""
    global _client_lock
    if _client_lock is None:
        _client_lock = asyncio.Lock()
    return _client_lock


async def get_health_client() -> HealthAPIClient:
    """Get or create the global health client (race-safe)."""
    global _client
    if _client is not None:
        return _client
    async with _get_client_lock():
        # Double-check after acquiring lock
        if _client is not None:
            return _client
        client = HealthAPIClient()
        try:
            await client.connect()
        except Exception:
            await client.close()
            raise
        _client = client
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
