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
import contextlib
import logging
import os
import threading
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import anthropic

logger = logging.getLogger(__name__)


def _safe_error_summary(err: BaseException, max_len: int = 200) -> str:
    """Render an exception as a redacted, length-bounded string for storage.

    SDK exception strings can include the request URL (which on some proxy
    configs embeds an auth token), the rendered Authorization header, or
    response headers carrying API keys. ``health.last_error`` is broadcast
    to every dashboard WS client via ``get_status()``, so any unredacted
    leakage propagates to the UI. Funnel through the project-wide
    secret-redaction filter and fall back gracefully if the import isn't
    available (e.g. during test isolation).
    """
    raw = str(err)[:max_len]
    try:
        from utils.monitoring.logger import _redact_sensitive

        return _redact_sensitive(raw)[:max_len]
    except Exception:
        # Fail safe: if redaction itself raises, drop everything past
        # the exception type name. Better to lose context than leak a
        # bearer token through this surface.
        return type(err).__name__


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
        # Reach into ``APIFailoverManager`` lazily so this dataclass
        # doesn't carry a hard import-order coupling to the manager
        # class — the previous shape worked only because the property
        # is evaluated lazily, but a static analyser can't tell that
        # apart from a real circular reference. ``_FAILURE_THRESHOLD``
        # is a module-level constant mirroring the manager's class
        # attribute so the comparison stays decoupled.
        return self.consecutive_failures < _FAILURE_THRESHOLD

    @property
    def failure_rate(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.total_failures / self.total_requests


# Module-level mirror of ``APIFailoverManager.FAILURE_THRESHOLD`` so
# ``EndpointHealth.is_healthy`` can be evaluated without reaching back
# into the manager class. The two MUST stay in sync — the manager
# constructor reads from this constant.
_FAILURE_THRESHOLD = 3


# Status codes that should NOT trigger failover. 429 belongs here: rate
# limits are usually account-wide and ALSO apply to the proxy endpoint, so
# a per-token rate cap would otherwise oscillate the active endpoint
# back and forth on every retry. The retry/backoff logic at the call-site
# is the right place to handle 429.
# NOTE: 401/403 ARE failover-worthy because they indicate a bad/expired key
# on that specific endpoint, not a user error.
_NON_FAILOVER_CODES = {400, 404, 422, 429}


def _should_failover(error: Exception) -> bool:
    """Determine if an error warrants failover to another endpoint."""
    # OSError covers raw network-stack failures (DNS resolution, connection
    # refused, socket reset) that the SDK surfaces directly without wrapping
    # in APIConnectionError. Check before anything else so plain network
    # outages reliably trigger failover.
    if isinstance(error, OSError):
        return True
    # RateLimitError is a subclass of APIStatusError; check it explicitly
    # so the intent reads correctly even if its status_code attribute
    # ever changes shape.
    if isinstance(error, anthropic.RateLimitError):
        return False
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
    # ``FAILURE_THRESHOLD`` mirrors the module-level ``_FAILURE_THRESHOLD``
    # consumed by ``EndpointHealth.is_healthy`` — change both together.
    FAILURE_THRESHOLD = _FAILURE_THRESHOLD  # consecutive failures before switching
    # Grace period before closing a popped client. Long enough for the
    # average ``messages.create`` round-trip to complete; short enough
    # that we don't leak file descriptors after a real switch. 5s is
    # the largest p99 we've seen for non-stream Anthropic requests.
    _CLIENT_CLOSE_GRACE_SECONDS = 5.0

    def __init__(self) -> None:
        self._endpoints: dict[EndpointType, EndpointConfig] = {}
        self._health: dict[EndpointType, EndpointHealth] = {}
        self._active: EndpointType = EndpointType.DIRECT
        self._clients: dict[EndpointType, anthropic.AsyncAnthropic] = {}
        self._lock = asyncio.Lock()
        # Sync lock for the sync get_client() path — keeps concurrent
        # callers from racing on _clients dict mutations.
        self._sync_clients_lock = threading.Lock()
        self._listeners: list[Callable[[EndpointType, str], Coroutine[Any, Any, None]]] = []
        self._initialized = False
        # Strong references to in-flight client.close() tasks so an
        # endpoint switch's fire-and-forget task isn't GC'd mid-close.
        self._pending_close_tasks: set[asyncio.Task[Any]] = set()

    def initialize(self) -> None:
        """Load endpoint configs from environment variables.

        No-op when CLAUDE_BACKEND=cli — under that mode all paid-API
        AI surfaces are disabled and the manager stays inert (no
        endpoints, no Anthropic clients). The dashboard chat falls
        through to the CLI subprocess handler instead.
        """
        if self._initialized:
            return
        if os.getenv("CLAUDE_BACKEND", "cli").strip().lower() == "cli":
            logger.info(
                "🚫 API failover disabled (CLAUDE_BACKEND=cli) — "
                "Anthropic SDK calls are short-circuited; only the Claude "
                "CLI subscription path is active."
            )
            self._initialized = True
            return
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
            # Legacy fallback: triggered when NEITHER the multi-endpoint
            # ANTHROPIC_DIRECT_API_KEY nor ANTHROPIC_PROXY_API_KEY env vars
            # are present (older deployments only set ANTHROPIC_API_KEY).
            # Routes the single legacy key through whichever endpoint type
            # the legacy base URL hints at (PROXY if set, DIRECT otherwise).
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

        # Serialize the read-create-write sequence so two threads can't both
        # see "no client" and each create one (leaking the loser).
        with self._sync_clients_lock:
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
        switched_to: EndpointType | None = None
        switched_reason: str = ""
        async with self._lock:
            health = self._health.get(self._active)
            if health:
                health.consecutive_failures += 1
                health.last_failure_time = time.monotonic()
                health.last_error = _safe_error_summary(error)
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
            last_error = health.last_error if health else _safe_error_summary(error)

            if immediate or failure_count >= self.FAILURE_THRESHOLD:
                other = self._get_other_endpoint()
                if other:
                    other_health = self._health.get(other)
                    # Don't switch to an endpoint that also recently failed
                    if other_health and not other_health.is_healthy:
                        cooldown_elapsed = (
                            time.monotonic() - other_health.last_failure_time
                        ) > self.RECOVERY_COOLDOWN
                        if not cooldown_elapsed:
                            logger.warning(
                                "⚠️ Both API endpoints unhealthy, staying on %s", self._active.value
                            )
                            return False
                    # Perform switch inside the lock to avoid TOCTOU race condition
                    switched_reason = f"auto-failover after {failure_count} failures: {last_error}"
                    await self._switch_to_locked(other, reason=switched_reason)
                    switched_to = other

        if switched_to is not None:
            # Notify outside the lock so slow listeners don't block other
            # failover/health operations.
            await self._notify_listeners(switched_to, switched_reason)
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
        # Listeners run OUTSIDE the lock so a slow callback (e.g. dashboard
        # broadcast to many WS clients) can't block other failover/health
        # operations.
        await self._notify_listeners(target, reason)

    async def _switch_to_locked(self, target: EndpointType, reason: str) -> None:
        """Internal: switch active endpoint (caller must already hold self._lock).

        Note: this does NOT dispatch listeners — the public _switch_to wrapper
        runs them after releasing the lock. Callers that hold the lock
        themselves should call _notify_listeners after release.
        """
        old = self._active
        self._active = target

        # Clear old client so a new one is created on next get_client().
        # Schedule a *delayed* .close() on each popped client so its httpx
        # connection pool is released — but only after a short grace
        # period so any in-flight ``messages.create`` calls already
        # holding a reference can complete. Closing immediately would
        # raise ``httpx.RuntimeError: This client has been closed``
        # inside the in-flight call's read path.
        # Keep a strong reference so the close task can't be GC'd before
        # the actual close completes (an unawaited fire-and-forget task is
        # eligible for collection mid-run).
        # Drop the OUTGOING client so any next ``get_client()`` builds a fresh
        # one for the new endpoint. Keep the TARGET client (if cached) — its
        # connection pool and prompt cache are useful for the next call.
        # Previously we popped both, forcing the new endpoint to start from
        # cold every switchover.
        old_client = self._clients.pop(old, None)
        if old_client is not None:
            with contextlib.suppress(Exception):
                task = asyncio.create_task(self._graceful_close(old_client))
                self._pending_close_tasks.add(task)
                task.add_done_callback(self._pending_close_tasks.discard)

        logger.info(
            "🔀 API endpoint switched: %s → %s (reason: %s)",
            old.value,
            target.value,
            reason,
        )

    async def _maybe_failover_from_probe(
        self, failed: EndpointType, reason: str
    ) -> None:
        """Drive auto-failover when a health probe trips the threshold.

        Mirrors the real-traffic failover path so probes participate in
        the same state machine. No-op if the failed endpoint isn't the
        active one or if no fallback is configured.
        """
        async with self._lock:
            if self._active != failed:
                return
            other_endpoints = [t for t in self._endpoints if t != failed]
            target = next(iter(other_endpoints), None)
            if target is None:
                return
            await self._switch_to_locked(target, f"probe-failover: {reason}")
        await self._notify_listeners(target, f"probe-failover: {reason}")

    async def _graceful_close(self, client: anthropic.AsyncAnthropic) -> None:
        """Close a popped client after a brief grace window.

        Background: closing a client immediately while a coroutine is mid
        ``messages.create`` raises ``httpx.RuntimeError: This client has
        been closed`` inside the in-flight call's read path. The grace
        delay gives in-flight requests time to finish naturally; new
        requests already routed to the new endpoint via the swapped
        ``self._active``.
        """
        try:
            await asyncio.sleep(self._CLIENT_CLOSE_GRACE_SECONDS)
        except asyncio.CancelledError:
            # On shutdown, skip the wait and close immediately.
            pass
        with contextlib.suppress(Exception):
            await client.close()

    async def _notify_listeners(self, target: EndpointType, reason: str) -> None:
        """Run all registered listeners (caller must NOT hold self._lock)."""
        # Snapshot the list so listener registration during dispatch is safe.
        for listener in list(self._listeners):
            try:
                await listener(target, reason)
            except Exception:
                logger.exception("Failover listener error")

    def add_listener(
        self, callback: Callable[[EndpointType, str], Coroutine[Any, Any, None]]
    ) -> None:
        """Register a callback for endpoint change events."""
        self._listeners.append(callback)

    def remove_listener(
        self,
        callback: Callable[[EndpointType, str], Coroutine[Any, Any, None]],
    ) -> None:
        # Use equality (==) rather than identity (is). Bound methods like
        # ``self._on_endpoint_changed`` create a fresh wrapper object on
        # every attribute access, so ``cb is callback`` is always False
        # for two references to the same bound method — the previous
        # ``is not`` filter silently kept stale listeners after WS
        # restart, which produced log spam on every endpoint switch.
        self._listeners = [cb for cb in self._listeners if cb != callback]

    async def health_check(self, endpoint: EndpointType | None = None) -> dict[str, Any]:
        """Perform a lightweight health check on an endpoint (or the active one)."""
        target = endpoint or self._active
        config = self._endpoints.get(target)
        if not config:
            return {"endpoint": target.value, "healthy": False, "error": "not configured"}

        # Reuse the existing client for the target endpoint instead of
        # spinning up a fresh ``AsyncAnthropic`` per probe. Per-probe
        # clients defeat both prompt cache (cold start each time) and
        # the connection pool. Fall back to a transient client if the
        # endpoint hasn't been used yet (no cached client).
        client = self._clients.get(target)
        transient = False
        if client is None:
            kwargs: dict[str, Any] = {"api_key": config.api_key}
            if config.base_url:
                kwargs["base_url"] = config.base_url
            client = anthropic.AsyncAnthropic(**kwargs)
            transient = True

        try:
            start = time.monotonic()
            # Use a minimal count_tokens call as health check (cheapest API call)
            await asyncio.wait_for(
                client.messages.count_tokens(
                    model=os.getenv("CLAUDE_MODEL", "claude-opus-4-8"),
                    messages=[{"role": "user", "content": "ping"}],
                ),
                timeout=15,
            )
            latency_ms = (time.monotonic() - start) * 1000

            # Mutate the health bucket under the manager lock — record_failure/
            # record_success on the real-request path hold self._lock for the
            # same fields, so an unlocked write here races them and can corrupt
            # consecutive_failures / double-trip the threshold.
            async with self._lock:
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
        except asyncio.CancelledError:
            # Don't swallow cancellation as a "health failure" — re-raise so
            # the surrounding probe-loop task can exit cleanly. Without
            # this, shutting down the bot would record bogus failures on
            # every endpoint and mark them all unhealthy.
            raise
        except Exception as e:
            redacted = _safe_error_summary(e)
            # Mutate the health bucket under the manager lock (see the success
            # path above) so this probe failure can't race record_failure on
            # the real-request path.
            async with self._lock:
                health = self._health.get(target)
                if health:
                    health.consecutive_failures += 1
                    health.last_failure_time = time.monotonic()
                    health.last_error = redacted
                    # Mirror the failure into the state machine so a
                    # failing probe drives auto-failover the same way a
                    # failing real request would. Previously the health
                    # bucket recorded the failure but never tripped the
                    # threshold check, so probes that all failed left the
                    # active endpoint stuck even when a healthy fallback
                    # existed. Use the locked path so listener dispatch
                    # respects the same ordering as real failures.
                    if health.consecutive_failures >= self.FAILURE_THRESHOLD:
                        # Keep a strong reference (added to
                        # ``_pending_close_tasks`` even though it's not a
                        # close — the set acts as a generic "tasks the
                        # manager spawned, mustn't be GC'd" anchor) so the
                        # task isn't reclaimed mid-await. create_task only
                        # schedules; _maybe_failover_from_probe acquires
                        # self._lock when it runs, after we release it here.
                        failover_task = asyncio.create_task(
                            self._maybe_failover_from_probe(target, redacted)
                        )
                        self._pending_close_tasks.add(failover_task)
                        failover_task.add_done_callback(
                            self._pending_close_tasks.discard
                        )

            return {
                "endpoint": target.value,
                "label": config.display_name,
                "healthy": False,
                "error": redacted,
            }
        finally:
            # Only close the client we created here. Closing the cached
            # client would defeat the whole point of pooling and break
            # any in-flight ``messages.create`` referencing it.
            if transient:
                with contextlib.suppress(Exception):
                    await client.close()

    def get_status(self) -> dict[str, Any]:
        """Get current failover status for dashboard display."""
        endpoints_info = []
        for ep_type, config in self._endpoints.items():
            health = self._health.get(ep_type, EndpointHealth())
            endpoints_info.append(
                {
                    "type": ep_type.value,
                    "label": config.display_name,
                    "active": ep_type == self._active,
                    "healthy": health.is_healthy,
                    "consecutive_failures": health.consecutive_failures,
                    "last_error": health.last_error,
                    "total_requests": health.total_requests,
                    "failure_rate": round(health.failure_rate * 100, 1),
                }
            )

        return {
            "active_endpoint": self._active.value,
            "has_failover": self.has_failover,
            "endpoints": endpoints_info,
        }


# Module-level singleton
api_failover = APIFailoverManager()
