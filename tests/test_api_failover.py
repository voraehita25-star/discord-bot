"""Tests for cogs.ai_core.api.api_failover.

Targets:
  - `_should_failover` decision logic
  - `EndpointConfig.display_name` fallback
  - `EndpointHealth.is_healthy` / `failure_rate`
  - `APIFailoverManager.initialize` env-driven setup
  - Status reporter shape
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import anthropic
import pytest

from cogs.ai_core.api.api_failover import (
    APIFailoverManager,
    EndpointConfig,
    EndpointHealth,
    EndpointType,
    _should_failover,
)


class TestShouldFailover:
    def test_oserror_triggers_failover(self):
        assert _should_failover(OSError("connection reset")) is True

    def test_timeout_triggers_failover(self):
        assert _should_failover(TimeoutError("slow")) is True

    def test_rate_limit_does_not_trigger_failover(self):
        # anthropic.RateLimitError takes message + response/body args at runtime;
        # subclass with a no-arg __init__ to keep the test focused on isinstance
        # behaviour inside _should_failover.
        class FakeRateLimit(anthropic.RateLimitError):
            def __init__(self) -> None:  # type: ignore[no-untyped-def]
                pass

        assert _should_failover(FakeRateLimit()) is False

    def test_api_status_400_does_not_trigger(self):
        class FakeStatus(anthropic.APIStatusError):
            def __init__(self) -> None:  # type: ignore[no-untyped-def]
                self.status_code = 400

        assert _should_failover(FakeStatus()) is False

    def test_api_status_500_triggers(self):
        class FakeStatus(anthropic.APIStatusError):
            def __init__(self) -> None:  # type: ignore[no-untyped-def]
                self.status_code = 500

        assert _should_failover(FakeStatus()) is True

    def test_api_status_429_does_not_trigger(self):
        class FakeStatus(anthropic.APIStatusError):
            def __init__(self) -> None:  # type: ignore[no-untyped-def]
                self.status_code = 429

        assert _should_failover(FakeStatus()) is False

    def test_api_status_401_triggers(self):
        # 401 = bad/expired key on this endpoint, failover is correct.
        class FakeStatus(anthropic.APIStatusError):
            def __init__(self) -> None:  # type: ignore[no-untyped-def]
                self.status_code = 401

        assert _should_failover(FakeStatus()) is True

    def test_value_error_does_not_trigger(self):
        # Caller bug, not network — must not failover.
        assert _should_failover(ValueError("bad input")) is False


class TestEndpointConfig:
    def test_display_name_uses_label_when_set(self):
        cfg = EndpointConfig(type=EndpointType.DIRECT, api_key="k", label="Custom Label")
        assert cfg.display_name == "Custom Label"

    def test_display_name_falls_back_to_type(self):
        cfg = EndpointConfig(type=EndpointType.PROXY, api_key="k")
        assert cfg.display_name == "Proxy"


class TestEndpointHealth:
    def test_default_is_healthy(self):
        h = EndpointHealth()
        assert h.is_healthy is True

    def test_unhealthy_after_threshold(self):
        h = EndpointHealth(consecutive_failures=APIFailoverManager.FAILURE_THRESHOLD)
        assert h.is_healthy is False

    def test_failure_rate_zero_when_no_requests(self):
        h = EndpointHealth()
        assert h.failure_rate == 0.0

    def test_failure_rate_calculation(self):
        h = EndpointHealth(total_requests=10, total_failures=3)
        assert h.failure_rate == 0.3


class TestAPIFailoverManagerInit:
    def test_initialize_with_direct_only(self, monkeypatch):
        # CLAUDE_BACKEND=cli short-circuits initialize(); these tests
        # exercise the API-mode codepath so opt back into it explicitly.
        monkeypatch.setenv("CLAUDE_BACKEND", "api")
        monkeypatch.setenv("ANTHROPIC_DIRECT_API_KEY", "direct-key")
        monkeypatch.delenv("ANTHROPIC_PROXY_API_KEY", raising=False)
        m = APIFailoverManager()
        m.initialize()
        assert EndpointType.DIRECT in m._endpoints
        assert EndpointType.PROXY not in m._endpoints
        assert m.has_failover is False

    def test_initialize_with_both_endpoints(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_BACKEND", "api")
        monkeypatch.setenv("ANTHROPIC_DIRECT_API_KEY", "direct-key")
        monkeypatch.setenv("ANTHROPIC_PROXY_API_KEY", "proxy-key")
        monkeypatch.setenv("ANTHROPIC_PROXY_BASE_URL", "https://proxy.example/v1")
        m = APIFailoverManager()
        m.initialize()
        assert EndpointType.DIRECT in m._endpoints
        assert EndpointType.PROXY in m._endpoints
        assert m.has_failover is True

    def test_initialize_idempotent(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_BACKEND", "api")
        monkeypatch.setenv("ANTHROPIC_DIRECT_API_KEY", "direct-key")
        m = APIFailoverManager()
        m.initialize()
        m.initialize()  # second call must be a no-op
        assert m._initialized is True


class TestGetStatus:
    def test_status_reports_endpoints(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_BACKEND", "api")
        monkeypatch.setenv("ANTHROPIC_DIRECT_API_KEY", "direct-key")
        m = APIFailoverManager()
        m.initialize()
        status = m.get_status()
        assert "active_endpoint" in status
        assert "has_failover" in status
        assert "endpoints" in status
        assert len(status["endpoints"]) >= 1
        first = status["endpoints"][0]
        assert "type" in first
        assert "label" in first
        assert "active" in first
        assert "healthy" in first


# ============================================================================
# Deepened coverage: initialize() branches, get_client lifecycle, switch /
# failover state machine, graceful close, listeners, and health_check.
# ============================================================================


def _make_both_manager() -> APIFailoverManager:
    """Build a manager with BOTH endpoints configured, bypassing env/initialize.

    Wiring _endpoints/_health directly keeps these tests hermetic (no env
    juggling) and lets us assert the failover state machine in isolation.
    """
    m = APIFailoverManager()
    m._endpoints[EndpointType.DIRECT] = EndpointConfig(
        type=EndpointType.DIRECT, api_key="direct-key", base_url=None, label="Direct"
    )
    m._endpoints[EndpointType.PROXY] = EndpointConfig(
        type=EndpointType.PROXY,
        api_key="proxy-key",
        base_url="https://proxy.example/v1",
        label="Proxy",
    )
    m._health[EndpointType.DIRECT] = EndpointHealth()
    m._health[EndpointType.PROXY] = EndpointHealth()
    m._active = EndpointType.DIRECT
    m._initialized = True
    return m


class _FakeStatusError(anthropic.APIStatusError):
    """A status error whose __init__ avoids the SDK's response/body requirements."""

    def __init__(self, status_code: int) -> None:  # type: ignore[no-untyped-def]
        self.status_code = status_code


class TestInitializeBranches:
    def test_cli_backend_short_circuits(self, monkeypatch):
        # Under CLI mode initialize() must stay inert: no endpoints, no clients.
        monkeypatch.setenv("CLAUDE_BACKEND", "cli")
        monkeypatch.setenv("ANTHROPIC_DIRECT_API_KEY", "should-be-ignored")
        m = APIFailoverManager()
        m.initialize()
        assert m._initialized is True
        assert m._endpoints == {}
        assert m.active_config is None

    def test_proxy_label_derived_from_base_url(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_BACKEND", "api")
        monkeypatch.delenv("ANTHROPIC_DIRECT_API_KEY", raising=False)
        monkeypatch.setenv("ANTHROPIC_PROXY_API_KEY", "proxy-key")
        monkeypatch.setenv("ANTHROPIC_PROXY_BASE_URL", "https://gw.example.net/anthropic")
        m = APIFailoverManager()
        m.initialize()
        assert EndpointType.PROXY in m._endpoints
        # The label embeds the host portion (after //) of the base URL.
        assert m._endpoints[EndpointType.PROXY].label == "Proxy (gw.example.net/anthropic)"

    def test_preferred_proxy_selected_as_active(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_BACKEND", "api")
        monkeypatch.setenv("ANTHROPIC_DIRECT_API_KEY", "direct-key")
        monkeypatch.setenv("ANTHROPIC_PROXY_API_KEY", "proxy-key")
        monkeypatch.setenv("ANTHROPIC_PROXY_BASE_URL", "https://proxy.example/v1")
        monkeypatch.setenv("ANTHROPIC_API_ENDPOINT", "proxy")
        m = APIFailoverManager()
        m.initialize()
        assert m.active_endpoint == EndpointType.PROXY

    def test_invalid_preferred_falls_back_to_direct(self, monkeypatch):
        # An unknown ANTHROPIC_API_ENDPOINT must not raise — it falls back.
        monkeypatch.setenv("CLAUDE_BACKEND", "api")
        monkeypatch.setenv("ANTHROPIC_DIRECT_API_KEY", "direct-key")
        monkeypatch.delenv("ANTHROPIC_PROXY_API_KEY", raising=False)
        monkeypatch.setenv("ANTHROPIC_API_ENDPOINT", "garbage")
        m = APIFailoverManager()
        m.initialize()
        assert m.active_endpoint == EndpointType.DIRECT

    def test_preferred_not_configured_picks_available(self, monkeypatch):
        # Preferred parses to a valid EndpointType but that endpoint isn't
        # configured (only proxy is) — must fall to the first available.
        monkeypatch.setenv("CLAUDE_BACKEND", "api")
        monkeypatch.delenv("ANTHROPIC_DIRECT_API_KEY", raising=False)
        monkeypatch.setenv("ANTHROPIC_PROXY_API_KEY", "proxy-key")
        monkeypatch.setenv("ANTHROPIC_PROXY_BASE_URL", "https://proxy.example/v1")
        monkeypatch.setenv("ANTHROPIC_API_ENDPOINT", "direct")
        m = APIFailoverManager()
        m.initialize()
        assert m.active_endpoint == EndpointType.PROXY

    def test_legacy_key_with_base_routes_to_proxy(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_BACKEND", "api")
        monkeypatch.delenv("ANTHROPIC_DIRECT_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_PROXY_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_PROXY_BASE_URL", raising=False)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "legacy-key")
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://legacy.proxy/v1")
        m = APIFailoverManager()
        m.initialize()
        assert EndpointType.PROXY in m._endpoints
        cfg = m._endpoints[EndpointType.PROXY]
        assert cfg.label == "Legacy"
        assert cfg.base_url == "https://legacy.proxy/v1"
        assert m.active_endpoint == EndpointType.PROXY

    def test_legacy_key_without_base_routes_to_direct(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_BACKEND", "api")
        monkeypatch.delenv("ANTHROPIC_DIRECT_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_PROXY_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "legacy-key")
        m = APIFailoverManager()
        m.initialize()
        assert EndpointType.DIRECT in m._endpoints
        assert m._endpoints[EndpointType.DIRECT].label == "Legacy"
        assert m._endpoints[EndpointType.DIRECT].base_url is None
        assert m.active_endpoint == EndpointType.DIRECT

    def test_no_keys_at_all_leaves_empty(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_BACKEND", "api")
        for var in (
            "ANTHROPIC_DIRECT_API_KEY",
            "ANTHROPIC_PROXY_API_KEY",
            "ANTHROPIC_PROXY_BASE_URL",
            "ANTHROPIC_API_KEY",
            "ANTHROPIC_BASE_URL",
        ):
            monkeypatch.delenv(var, raising=False)
        m = APIFailoverManager()
        m.initialize()
        assert m._endpoints == {}
        # active stays at the constructor default, not crashing.
        assert m.active_endpoint == EndpointType.DIRECT


class TestActiveProperties:
    def test_active_config_returns_configured(self):
        m = _make_both_manager()
        cfg = m.active_config
        assert cfg is not None
        assert cfg.type == EndpointType.DIRECT

    def test_has_failover_true_with_two(self):
        m = _make_both_manager()
        assert m.has_failover is True

    def test_has_failover_false_with_one(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_BACKEND", "api")
        monkeypatch.setenv("ANTHROPIC_DIRECT_API_KEY", "k")
        monkeypatch.delenv("ANTHROPIC_PROXY_API_KEY", raising=False)
        m = APIFailoverManager()
        m.initialize()
        assert m.has_failover is False

    def test_get_other_endpoint(self):
        m = _make_both_manager()
        assert m._get_other_endpoint() == EndpointType.PROXY
        m._active = EndpointType.PROXY
        assert m._get_other_endpoint() == EndpointType.DIRECT


class TestGetClient:
    def test_get_client_creates_and_caches(self, monkeypatch):
        # Patch the SDK constructor so no real client / network is built.
        from cogs.ai_core.api import api_failover as mod

        fake_client = MagicMock()
        ctor = MagicMock(return_value=fake_client)
        monkeypatch.setattr(mod.anthropic, "AsyncAnthropic", ctor)

        m = _make_both_manager()
        c1 = m.get_client()
        c2 = m.get_client()
        assert c1 is fake_client
        assert c2 is fake_client
        # Constructed exactly once (second call hits the cache).
        ctor.assert_called_once()
        # Direct endpoint has no base_url, so it isn't passed.
        _, kwargs = ctor.call_args
        assert kwargs == {"api_key": "direct-key"}

    def test_get_client_passes_base_url_for_proxy(self, monkeypatch):
        from cogs.ai_core.api import api_failover as mod

        ctor = MagicMock(return_value=MagicMock())
        monkeypatch.setattr(mod.anthropic, "AsyncAnthropic", ctor)

        m = _make_both_manager()
        m._active = EndpointType.PROXY
        m.get_client()
        _, kwargs = ctor.call_args
        assert kwargs == {"api_key": "proxy-key", "base_url": "https://proxy.example/v1"}

    def test_get_client_runs_initialize_when_uninitialized(self, monkeypatch):
        from cogs.ai_core.api import api_failover as mod

        ctor = MagicMock(return_value=MagicMock())
        monkeypatch.setattr(mod.anthropic, "AsyncAnthropic", ctor)
        monkeypatch.setenv("CLAUDE_BACKEND", "api")
        monkeypatch.setenv("ANTHROPIC_DIRECT_API_KEY", "auto-init-key")
        monkeypatch.delenv("ANTHROPIC_PROXY_API_KEY", raising=False)

        m = APIFailoverManager()
        assert m._initialized is False
        client = m.get_client()
        assert m._initialized is True
        assert client is ctor.return_value

    def test_get_client_raises_without_config(self):
        m = APIFailoverManager()
        m._initialized = True  # skip initialize; leave endpoints empty
        with pytest.raises(RuntimeError, match="No API endpoint configured"):
            m.get_client()


class TestRecordSuccessAndFailure:
    async def test_record_success_resets_failures(self):
        m = _make_both_manager()
        m._health[EndpointType.DIRECT].consecutive_failures = 2
        await m.record_success()
        h = m._health[EndpointType.DIRECT]
        assert h.consecutive_failures == 0
        assert h.total_requests == 1
        assert h.last_success_time > 0

    async def test_record_failure_non_failover_error_returns_false(self):
        # ValueError is a caller bug — record it but never failover.
        m = _make_both_manager()
        result = await m.record_failure(ValueError("bad input"))
        assert result is False
        h = m._health[EndpointType.DIRECT]
        # Client errors are recorded in the totals/last_error but must NOT
        # advance the failover trip counter — counting them primed the
        # counter so one later transient error caused an instant switch.
        assert h.consecutive_failures == 0
        assert h.total_failures == 1
        assert h.last_error
        # No switch happened.
        assert m.active_endpoint == EndpointType.DIRECT

    async def test_record_failure_no_failover_when_single_endpoint(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_BACKEND", "api")
        monkeypatch.setenv("ANTHROPIC_DIRECT_API_KEY", "k")
        monkeypatch.delenv("ANTHROPIC_PROXY_API_KEY", raising=False)
        m = APIFailoverManager()
        m.initialize()
        # OSError is failover-worthy, but with one endpoint there's nowhere to go.
        result = await m.record_failure(OSError("conn reset"))
        assert result is False
        assert m.active_endpoint == EndpointType.DIRECT

    async def test_record_failure_below_threshold_no_switch(self):
        m = _make_both_manager()
        # First OSError: failover-worthy but below FAILURE_THRESHOLD (3).
        result = await m.record_failure(OSError("boom"))
        assert result is False
        assert m.active_endpoint == EndpointType.DIRECT
        assert m._health[EndpointType.DIRECT].consecutive_failures == 1

    async def test_record_failure_switches_after_threshold(self):
        m = _make_both_manager()
        listener = AsyncMock()
        m.add_listener(listener)
        results = []
        for _ in range(APIFailoverManager.FAILURE_THRESHOLD):
            results.append(await m.record_failure(OSError("boom")))
        # Only the threshold-tripping call returns True.
        assert results == [False, False, True]
        assert m.active_endpoint == EndpointType.PROXY
        listener.assert_awaited_once()
        target, reason = listener.await_args.args
        assert target == EndpointType.PROXY
        assert "auto-failover" in reason

    async def test_client_error_burst_does_not_prime_failover(self):
        """Regression: a burst of account-wide 429s used to prime
        consecutive_failures to the threshold, so the NEXT single
        transient error instantly switched endpoints — subverting the
        _NON_FAILOVER_CODES intent that 429s be handled by call-site
        backoff. Client errors must not count toward the trip counter."""
        m = _make_both_manager()

        class FakeRateLimit(anthropic.RateLimitError):
            def __init__(self) -> None:  # type: ignore[no-untyped-def]
                pass

        for _ in range(APIFailoverManager.FAILURE_THRESHOLD - 1):
            assert await m.record_failure(FakeRateLimit()) is False
        # One real transient error after the 429 burst: still below the
        # threshold, so NO switch.
        result = await m.record_failure(OSError("transient blip"))
        assert result is False
        assert m.active_endpoint == EndpointType.DIRECT
        h = m._health[EndpointType.DIRECT]
        assert h.consecutive_failures == 1  # only the OSError counted
        assert h.total_failures == APIFailoverManager.FAILURE_THRESHOLD
        # The endpoint stays healthy in get_status() — pure client errors
        # must not flip the dashboard's unhealthy badge.
        assert h.is_healthy is True

    async def test_record_failure_immediate_on_401(self):
        m = _make_both_manager()
        listener = AsyncMock()
        m.add_listener(listener)
        # A single 401 triggers immediate failover (no threshold wait).
        result = await m.record_failure(_FakeStatusError(401))
        assert result is True
        assert m.active_endpoint == EndpointType.PROXY
        listener.assert_awaited_once()

    async def test_record_failure_blocked_when_other_unhealthy_in_cooldown(self):
        m = _make_both_manager()
        # Make the fallback (proxy) freshly-failed and within cooldown.
        ph = m._health[EndpointType.PROXY]
        ph.consecutive_failures = APIFailoverManager.FAILURE_THRESHOLD
        import time as _t

        ph.last_failure_time = _t.monotonic()
        # 401 would normally be immediate, but both endpoints are unhealthy.
        result = await m.record_failure(_FakeStatusError(401))
        assert result is False
        # Stays put — nowhere healthy to go.
        assert m.active_endpoint == EndpointType.DIRECT

    async def test_record_failure_switches_when_other_cooldown_elapsed(self, monkeypatch):
        m = _make_both_manager()
        ph = m._health[EndpointType.PROXY]
        ph.consecutive_failures = APIFailoverManager.FAILURE_THRESHOLD
        # Fallback failed long ago — cooldown has elapsed, so switching is OK.
        ph.last_failure_time = 0.0
        from cogs.ai_core.api import api_failover as mod

        # Pin monotonic well past RECOVERY_COOLDOWN so cooldown_elapsed is True.
        monkeypatch.setattr(mod.time, "monotonic", lambda: 10_000.0)
        result = await m.record_failure(_FakeStatusError(401))
        assert result is True
        assert m.active_endpoint == EndpointType.PROXY


class TestSwitchEndpoint:
    async def test_switch_to_unconfigured_returns_false(self):
        m = APIFailoverManager()
        m._initialized = True
        result = await m.switch_endpoint(EndpointType.PROXY)
        assert result is False

    async def test_switch_to_same_endpoint_is_noop_true(self):
        m = _make_both_manager()
        listener = AsyncMock()
        m.add_listener(listener)
        result = await m.switch_endpoint(EndpointType.DIRECT)
        assert result is True
        assert m.active_endpoint == EndpointType.DIRECT
        # No actual switch => listeners not invoked.
        listener.assert_not_awaited()

    async def test_switch_endpoint_changes_active_and_notifies(self):
        m = _make_both_manager()
        listener = AsyncMock()
        m.add_listener(listener)
        result = await m.switch_endpoint(EndpointType.PROXY, reason="manual-test")
        assert result is True
        assert m.active_endpoint == EndpointType.PROXY
        listener.assert_awaited_once_with(EndpointType.PROXY, "manual-test")

    async def test_switch_pops_and_closes_old_client(self):
        m = _make_both_manager()
        old_client = AsyncMock()
        old_client.close = AsyncMock()
        m._clients[EndpointType.DIRECT] = old_client
        # Speed up the grace window so the close runs immediately.
        m._CLIENT_CLOSE_GRACE_SECONDS = 0
        await m.switch_endpoint(EndpointType.PROXY)
        # Old client removed from the cache immediately on switch.
        assert EndpointType.DIRECT not in m._clients
        # Let the fire-and-forget graceful-close task run.
        import asyncio as _aio

        await _aio.gather(*list(m._pending_close_tasks), return_exceptions=True)
        old_client.close.assert_awaited_once()


class TestGracefulClose:
    async def test_graceful_close_sleeps_then_closes(self, monkeypatch):
        m = _make_both_manager()
        from cogs.ai_core.api import api_failover as mod

        slept = {}

        async def fake_sleep(secs):
            slept["secs"] = secs

        monkeypatch.setattr(mod.asyncio, "sleep", fake_sleep)
        client = AsyncMock()
        client.close = AsyncMock()
        await m._graceful_close(client)
        assert slept["secs"] == m._CLIENT_CLOSE_GRACE_SECONDS
        client.close.assert_awaited_once()

    async def test_graceful_close_handles_cancelled_sleep(self, monkeypatch):
        m = _make_both_manager()
        from cogs.ai_core.api import api_failover as mod

        async def cancel_sleep(_secs):
            raise __import__("asyncio").CancelledError()

        monkeypatch.setattr(mod.asyncio, "sleep", cancel_sleep)
        client = AsyncMock()
        client.close = AsyncMock()
        # CancelledError during the grace wait must NOT propagate; close still runs.
        await m._graceful_close(client)
        client.close.assert_awaited_once()

    async def test_graceful_close_suppresses_close_error(self, monkeypatch):
        m = _make_both_manager()
        from cogs.ai_core.api import api_failover as mod

        async def fake_sleep(_secs):
            return None

        monkeypatch.setattr(mod.asyncio, "sleep", fake_sleep)
        client = AsyncMock()
        client.close = AsyncMock(side_effect=RuntimeError("already closed"))
        # A failing close must be swallowed (contextlib.suppress).
        await m._graceful_close(client)
        client.close.assert_awaited_once()


class TestListeners:
    async def test_add_and_remove_listener(self):
        m = _make_both_manager()

        async def cb(_t, _r):
            return None

        m.add_listener(cb)
        assert cb in m._listeners
        m.remove_listener(cb)
        assert cb not in m._listeners

    async def test_remove_listener_uses_equality_for_bound_methods(self):
        # Bound methods compare equal by ==; the manager must remove by equality.
        m = _make_both_manager()

        class Holder:
            async def on_change(self, _t, _r):
                return None

        h = Holder()
        m.add_listener(h.on_change)
        # A *fresh* attribute access yields a new wrapper object that is `==`.
        m.remove_listener(h.on_change)
        assert m._listeners == []

    async def test_notify_listeners_swallows_listener_exception(self):
        m = _make_both_manager()
        calls = []

        async def bad(_t, _r):
            raise RuntimeError("listener boom")

        async def good(t, r):
            calls.append((t, r))

        m.add_listener(bad)
        m.add_listener(good)
        # One listener raising must not block the others.
        await m._notify_listeners(EndpointType.PROXY, "x")
        assert calls == [(EndpointType.PROXY, "x")]


class TestHealthCheck:
    async def test_health_check_not_configured(self):
        m = APIFailoverManager()
        m._initialized = True  # no endpoints
        result = await m.health_check(EndpointType.PROXY)
        assert result == {
            "endpoint": "proxy",
            "healthy": False,
            "error": "not configured",
        }

    async def test_health_check_healthy_uses_cached_client(self):
        m = _make_both_manager()
        client = MagicMock()
        client.messages = MagicMock()
        client.messages.count_tokens = AsyncMock(return_value=MagicMock())
        client.close = AsyncMock()
        m._clients[EndpointType.DIRECT] = client

        result = await m.health_check(EndpointType.DIRECT)
        assert result["healthy"] is True
        assert result["endpoint"] == "direct"
        assert "latency_ms" in result
        # Cached client must NOT be closed (pooling).
        client.close.assert_not_awaited()
        client.messages.count_tokens.assert_awaited_once()
        # Health bucket reset on success.
        assert m._health[EndpointType.DIRECT].consecutive_failures == 0

    async def test_health_check_creates_transient_client_and_closes_it(self, monkeypatch):
        from cogs.ai_core.api import api_failover as mod

        transient = MagicMock()
        transient.messages = MagicMock()
        transient.messages.count_tokens = AsyncMock(return_value=MagicMock())
        transient.close = AsyncMock()
        ctor = MagicMock(return_value=transient)
        monkeypatch.setattr(mod.anthropic, "AsyncAnthropic", ctor)

        m = _make_both_manager()
        # No cached client for DIRECT => a transient one is built and closed.
        result = await m.health_check(EndpointType.DIRECT)
        assert result["healthy"] is True
        ctor.assert_called_once()
        transient.close.assert_awaited_once()

    async def test_health_check_failure_records_and_returns_unhealthy(self):
        m = _make_both_manager()
        client = MagicMock()
        client.messages = MagicMock()
        client.messages.count_tokens = AsyncMock(side_effect=OSError("network down"))
        client.close = AsyncMock()
        m._clients[EndpointType.DIRECT] = client

        result = await m.health_check(EndpointType.DIRECT)
        assert result["healthy"] is False
        assert result["endpoint"] == "direct"
        assert "error" in result
        h = m._health[EndpointType.DIRECT]
        assert h.consecutive_failures == 1
        assert h.last_error

    async def test_health_check_timeout_marks_unhealthy(self, monkeypatch):
        from cogs.ai_core.api import api_failover as mod

        async def fake_wait_for(_coro, timeout):
            # Close the un-awaited coroutine to avoid a RuntimeWarning.
            if hasattr(_coro, "close"):
                _coro.close()
            raise TimeoutError("probe timed out")

        monkeypatch.setattr(mod.asyncio, "wait_for", fake_wait_for)

        m = _make_both_manager()
        client = MagicMock()
        client.messages = MagicMock()
        client.messages.count_tokens = MagicMock()  # returns a coroutine-ish mock
        client.close = AsyncMock()
        m._clients[EndpointType.DIRECT] = client

        result = await m.health_check(EndpointType.DIRECT)
        assert result["healthy"] is False
        assert m._health[EndpointType.DIRECT].consecutive_failures == 1

    async def test_health_check_reraises_cancelled(self, monkeypatch):
        from cogs.ai_core.api import api_failover as mod

        async def cancel_wait(_coro, timeout):
            if hasattr(_coro, "close"):
                _coro.close()
            raise __import__("asyncio").CancelledError()

        monkeypatch.setattr(mod.asyncio, "wait_for", cancel_wait)

        m = _make_both_manager()
        client = MagicMock()
        client.messages = MagicMock()
        client.messages.count_tokens = MagicMock()
        m._clients[EndpointType.DIRECT] = client

        with pytest.raises(__import__("asyncio").CancelledError):
            await m.health_check(EndpointType.DIRECT)
        # CancelledError must NOT be recorded as a health failure.
        assert m._health[EndpointType.DIRECT].consecutive_failures == 0

    async def test_health_check_failure_at_threshold_triggers_probe_failover(self):
        m = _make_both_manager()
        # Pre-seed two failures so the next failing probe hits the threshold.
        m._health[EndpointType.DIRECT].consecutive_failures = (
            APIFailoverManager.FAILURE_THRESHOLD - 1
        )
        listener = AsyncMock()
        m.add_listener(listener)

        client = MagicMock()
        client.messages = MagicMock()
        client.messages.count_tokens = AsyncMock(side_effect=OSError("down"))
        client.close = AsyncMock()
        m._clients[EndpointType.DIRECT] = client

        result = await m.health_check(EndpointType.DIRECT)
        assert result["healthy"] is False
        # The probe-failover task is fire-and-forget; drain it.
        import asyncio as _aio

        pending = list(m._pending_close_tasks)
        if pending:
            await _aio.gather(*pending, return_exceptions=True)
        assert m.active_endpoint == EndpointType.PROXY
        listener.assert_awaited_once()
        _target, reason = listener.await_args.args
        assert "probe-failover" in reason


class TestMaybeFailoverFromProbe:
    async def test_noop_when_failed_is_not_active(self):
        m = _make_both_manager()
        # DIRECT is active; a probe failure on PROXY must not switch anything.
        await m._maybe_failover_from_probe(EndpointType.PROXY, "boom")
        assert m.active_endpoint == EndpointType.DIRECT

    async def test_noop_when_no_other_endpoint(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_BACKEND", "api")
        monkeypatch.setenv("ANTHROPIC_DIRECT_API_KEY", "k")
        monkeypatch.delenv("ANTHROPIC_PROXY_API_KEY", raising=False)
        m = APIFailoverManager()
        m.initialize()
        # Only one endpoint -> no fallback target -> stays put.
        await m._maybe_failover_from_probe(EndpointType.DIRECT, "boom")
        assert m.active_endpoint == EndpointType.DIRECT

    async def test_switches_and_notifies_on_active_failure(self):
        m = _make_both_manager()
        listener = AsyncMock()
        m.add_listener(listener)
        await m._maybe_failover_from_probe(EndpointType.DIRECT, "probe-down")
        assert m.active_endpoint == EndpointType.PROXY
        listener.assert_awaited_once()
        _t, reason = listener.await_args.args
        assert reason == "probe-failover: probe-down"
