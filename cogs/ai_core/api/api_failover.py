"""
API Endpoint Failover Manager.

Manages automatic switching between Direct (Anthropic official) and Proxy
API endpoints when one becomes unavailable.

Usage:
    from .api_failover import api_failover
    client = api_failover.get_client()  # returns AsyncAnthropic with active endpoint
"""

from __future__ import annotations

import asyncio
import logging
logger = logging.getLogger(__name__)
import os
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import anthropic


class EndpointType(StrEnum):
    DIRECT = "direct"
    PROXY = "proxy"


@dataclass
class EndpointConfig:
    type: EndpointType
    api_key: str
    base_url: str | None = None  # None = use Anthropic default
    label: str = ""

    @property
    def display_name(self) -> str:
        return self.label or self.type.value.title()


@dataclass
class EndpointHealth:
    consecutive_failures: int = 0
    last_failure_time: float = 0.0
    last_success_time: float = 0.0
    last_error: str = ""
    total_requests: int = 0
    total_failures: int = 0

    @property
    def is_healthy(self) -> bool:
        return self.consecutive_failures < APIFailoverManager.FAILURE_THRESHOLD

    @property
    def failure_rate(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.total_failures / self.total_requests


# Errors that indicate the endpoint itself is down (not user error)
_FAILOVER_ERRORS = (
    anthropic.APIConnectionError,
    anthropic.InternalServerError,
    anthropic.APIStatusError,
)

# Errors that should NOT trigger failover (user-side issues)
# NOTE: 401/403 ARE failover-worthy because they indicate a bad/expired key
# on that specific endpoint, not a user error.
_NON_FAILOVER_CODES = {400, 404, 422}


def _should_failover(error: Exception) -> bool:
    """Determine if an error warrants failover to another endpoint."""
    if isinstance(error, anthropic.APIStatusError):
        # Don't failover for client errors (bad request, not found, etc)
        return error.status_code not in _NON_FAILOVER_CODES
    if isinstance(error, anthropic.APIConnectionError):
        return True
    # In 3.11+ asyncio.TimeoutError is an alias for the builtin TimeoutError.
    return isinstance(error, TimeoutError)


# Status codes that should trigger IMMEDIATE failover (1 failure = switch)
_IMMEDIATE_FAILOVER_CODES = {401, 403}


class APIFailoverManager:
    """Manages failover between direct and proxy Anthropic API endpoints."""

    HEALTH_CHECK_INTERVAL = 120  # seconds between auto health checks
    RECOVERY_COOLDOWN = 60  # seconds before retrying a failed endpoint
    FAILURE_THRESHOLD = 3  # consecutive failures before switching

    def __init__(self) -> None:
        self._endpoints: dict[EndpointType, EndpointConfig] = {}
        self._health: dict[EndpointType, EndpointHealth] = {}
        self._active: EndpointType = EndpointType.DIRECT
        self._clients: dict[EndpointType, anthropic.AsyncAnthropic] = {}
        self._lock = asyncio.Lock()
        self._listeners: list[Callable[[EndpointType, str], Coroutine[Any, Any, None]]] = []
        self._initialized = False

    def initialize(self) -> None:
        """Load endpoint configs from environment variables."""
        direct_key = os.getenv("ANTHROPIC_DIRECT_API_KEY", "")
        proxy_key = os.getenv("ANTHROPIC_PROXY_API_KEY", "")
        proxy_base = os.getenv("ANTHROPIC_PROXY_BASE_URL", "")
        preferred = os.getenv("ANTHROPIC_API_ENDPOINT", "direct").lower()

        if direct_key:
            self._endpoints[EndpointType.DIRECT] = EndpointConfig(
                type=EndpointType.DIRECT,
                api_key=direct_key,
                base_url=None,
                label="Direct (Anthropic)",
            )
            self._health[EndpointType.DIRECT] = EndpointHealth()

        if proxy_key and proxy_base:
            self._endpoints[EndpointType.PROXY] = EndpointConfig(
                type=EndpointType.PROXY,
                api_key=proxy_key,
                base_url=proxy_base,
                label=f"Proxy ({proxy_base.split('//')[1] if '//' in proxy_base else proxy_base})",
            )
            self._health[EndpointType.PROXY] = EndpointHealth()

        if not self._endpoints:
            # Fallback: use legacy ANTHROPIC_API_KEY
            legacy_key = os.getenv("ANTHROPIC_API_KEY", "")
            legacy_base = os.getenv("ANTHROPIC_BASE_URL", "")
            if legacy_key:
                ep_type = EndpointType.PROXY if legacy_base else EndpointType.DIRECT
                self._endpoints[ep_type] = EndpointConfig(
                    type=ep_type,
                    api_key=legacy_key,
                    base_url=legacy_base or None,
                    label="Legacy",
                )
                self._health[ep_type] = EndpointHealth()
                preferred = ep_type.value

        # Set active endpoint
        try:
            self._active = EndpointType(preferred)
        except ValueError:
            self._active = EndpointType.DIRECT

        if self._active not in self._endpoints and self._endpoints:
            self._active = next(iter(self._endpoints))

        self._initialized = True
        logger.info(
            "🔀 API Failover initialized: active=%s, available=[%s]",
            self._active.value,
            ", ".join(e.value for e in self._endpoints),
        )

    @property
    def active_endpoint(self) -> EndpointType:
        return self._active

    @property
    def active_config(self) -> EndpointConfig | None:
        return self._endpoints.get(self._active)

    @property
    def has_failover(self) -> bool:
        """True if there's an alternative endpoint to fail over to."""
        return len(self._endpoints) > 1

    def get_client(self) -> anthropic.AsyncAnthropic:
        """Get or create an AsyncAnthropic client for the active endpoint."""
        if not self._initialized:
            self.initialize()

        if self._active in self._clients:
            return self._clients[self._active]

        config = self._endpoints.get(self._active)
        if not config:
            raise RuntimeError("No API endpoint configured")

        kwargs: dict[str, Any] = {"api_key": config.api_key}
        if config.base_url:
            kwargs["base_url"] = config.base_url

        client = anthropic.AsyncAnthropic(**kwargs)
        self._clients[self._active] = client
        return client

    def _get_other_endpoint(self) -> EndpointType | None:
        """Get the other endpoint type (for failover)."""
        for ep_type in self._endpoints:
            if ep_type != self._active:
                return ep_type
        return None

    async def record_success(self) -> None:
        """Record a successful API call on the active endpoint."""
        async with self._lock:
            health = self._health.get(self._active)
            if health:
                health.consecutive_failures = 0
                health.last_success_time = time.monotonic()
                health.total_requests += 1

    async def record_failure(self, error: Exception) -> bool:
        """Record a failed API call. Returns True if failover was triggered."""
        async with self._lock:
            health = self._health.get(self._active)
            if health:
                health.consecutive_failures += 1
                health.last_failure_time = time.monotonic()
                health.last_error = str(error)[:200]
                health.total_requests += 1
                health.total_failures += 1

            if not _should_failover(error):
                return False

            if not self.has_failover:
                return False

            # Immediate failover for auth errors (invalid/expired key)
            immediate = (
                isinstance(error, anthropic.APIStatusError)
                and error.status_code in _IMMEDIATE_FAILOVER_CODES
            )

            failure_count = health.consecutive_failures if health else 0
            last_error = health.last_error if health else str(error)[:200]

            if immediate or failure_count >= self.FAILURE_THRESHOLD:
                other = self._get_other_endpoint()
                if other:
                    other_health = self._health.get(other)
                    # Don't switch to an endpoint that also recently failed
                    if other_health and not other_health.is_healthy:
                        cooldown_elapsed = (time.monotonic() - other_health.last_failure_time) > self.RECOVERY_COOLDOWN
                        if not cooldown_elapsed:
                            logger.warning("⚠️ Both API endpoints unhealthy, staying on %s", self._active.value)
                            return False
                    # Perform switch inside the lock to avoid TOCTOU race condition
                    await self._switch_to_locked(other, reason=f"auto-failover after {failure_count} failures: {last_error}")
                    return True

        return False

    async def switch_endpoint(self, target: EndpointType, *, reason: str = "manual") -> bool:
        """Manually switch to a specific endpoint. Returns True on success."""
        if target not in self._endpoints:
            logger.warning("⚠️ Cannot switch to %s: not configured", target.value)
            return False
        if target == self._active:
            return True
        await self._switch_to(target, reason=reason)
        return True

    async def _switch_to(self, target: EndpointType, reason: str) -> None:
        """Internal: switch active endpoint and notify listeners."""
        async with self._lock:
            await self._switch_to_locked(target, reason)

    async def _switch_to_locked(self, target: EndpointType, reason: str) -> None:
        """Internal: switch active endpoint (caller must already hold self._lock)."""
        old = self._active
        self._active = target

        # Clear old client so a new one is created on next get_client()
        self._clients.pop(old, None)
        self._clients.pop(target, None)

        logger.info(
            "🔀 API endpoint switched: %s → %s (reason: %s)",
            old.value, target.value, reason,
        )

        # Notify listeners (dashboard WS, etc.)
        for listener in self._listeners:
            try:
                await listener(target, reason)
            except Exception:
                logger.exception("Failover listener error")

    def add_listener(self, callback: Callable[[EndpointType, str], Coroutine[Any, Any, None]]) -> None:
        """Register a callback for endpoint change events."""
        self._listeners.append(callback)

    def remove_listener(
        self,
        callback: Callable[[EndpointType, str], Coroutine[Any, Any, None]],
    ) -> None:
        self._listeners = [cb for cb in self._listeners if cb is not callback]

    async def health_check(self, endpoint: EndpointType | None = None) -> dict[str, Any]:
        """Perform a lightweight health check on an endpoint (or the active one)."""
        target = endpoint or self._active
        config = self._endpoints.get(target)
        if not config:
            return {"endpoint": target.value, "healthy": False, "error": "not configured"}

        kwargs: dict[str, Any] = {"api_key": config.api_key}
        if config.base_url:
            kwargs["base_url"] = config.base_url

        client = anthropic.AsyncAnthropic(**kwargs)
        try:
            start = time.monotonic()
            # Use a minimal count_tokens call as health check (cheapest API call)
            await asyncio.wait_for(
                client.messages.count_tokens(
                    model=os.getenv("CLAUDE_MODEL", "claude-opus-4-7"),
                    messages=[{"role": "user", "content": "ping"}],
                ),
                timeout=15,
            )
            latency_ms = (time.monotonic() - start) * 1000

            health = self._health.get(target)
            if health:
                health.consecutive_failures = 0
                health.last_success_time = time.monotonic()

            return {
                "endpoint": target.value,
                "label": config.display_name,
                "healthy": True,
                "latency_ms": round(latency_ms, 1),
            }
        except Exception as e:
            health = self._health.get(target)
            if health:
                health.consecutive_failures += 1
                health.last_failure_time = time.monotonic()
                health.last_error = str(e)[:200]

            return {
                "endpoint": target.value,
                "label": config.display_name,
                "healthy": False,
                "error": str(e)[:200],
            }
        finally:
            await client.close()

    def get_status(self) -> dict[str, Any]:
        """Get current failover status for dashboard display."""
        endpoints_info = []
        for ep_type, config in self._endpoints.items():
            health = self._health.get(ep_type, EndpointHealth())
            endpoints_info.append({
                "type": ep_type.value,
                "label": config.display_name,
                "active": ep_type == self._active,
                "healthy": health.is_healthy,
                "consecutive_failures": health.consecutive_failures,
                "last_error": health.last_error,
                "total_requests": health.total_requests,
                "failure_rate": round(health.failure_rate * 100, 1),
            })

        return {
            "active_endpoint": self._active.value,
            "has_failover": self.has_failover,
            "endpoints": endpoints_info,
        }


# Module-level singleton
api_failover = APIFailoverManager()
