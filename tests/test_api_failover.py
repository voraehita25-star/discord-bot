"""Tests for cogs.ai_core.api.api_failover.

Targets:
  - `_should_failover` decision logic
  - `EndpointConfig.display_name` fallback
  - `EndpointHealth.is_healthy` / `failure_rate`
  - `APIFailoverManager.initialize` env-driven setup
  - Status reporter shape
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import anthropic

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
        err = MagicMock(spec=anthropic.RateLimitError)
        # spec via MagicMock won't pass isinstance check unless we use real class.
        # Construct via the exception class hierarchy — anthropic exceptions need
        # message + response/body args; use side_effect-style stub via subclass.

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
        monkeypatch.setenv("ANTHROPIC_DIRECT_API_KEY", "direct-key")
        monkeypatch.delenv("ANTHROPIC_PROXY_API_KEY", raising=False)
        m = APIFailoverManager()
        m.initialize()
        assert EndpointType.DIRECT in m._endpoints
        assert EndpointType.PROXY not in m._endpoints
        assert m.has_failover is False

    def test_initialize_with_both_endpoints(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_DIRECT_API_KEY", "direct-key")
        monkeypatch.setenv("ANTHROPIC_PROXY_API_KEY", "proxy-key")
        monkeypatch.setenv("ANTHROPIC_PROXY_BASE_URL", "https://proxy.example/v1")
        m = APIFailoverManager()
        m.initialize()
        assert EndpointType.DIRECT in m._endpoints
        assert EndpointType.PROXY in m._endpoints
        assert m.has_failover is True

    def test_initialize_idempotent(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_DIRECT_API_KEY", "direct-key")
        m = APIFailoverManager()
        m.initialize()
        m.initialize()  # second call must be a no-op
        assert m._initialized is True


class TestGetStatus:
    def test_status_reports_endpoints(self, monkeypatch):
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
