"""Tests for AlertManager (utils/monitoring/alerting.py).

Covers webhook configuration, cooldown logic, alert sending,
convenience methods, and session management.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from utils.monitoring.alerting import AlertManager


class TestAlertManagerInit:
    """Test AlertManager initialization and properties."""

    def test_default_no_webhook(self):
        mgr = AlertManager()
        assert mgr.webhook_configured is False
        assert mgr.alert_count == 0

    def test_webhook_configured(self):
        mgr = AlertManager()
        mgr._webhook_url = "https://discord.com/api/webhooks/test"
        assert mgr.webhook_configured is True


class TestCooldown:
    """Test alert cooldown logic."""

    def test_can_send_first_time(self):
        mgr = AlertManager()
        assert mgr._can_send("test_alert") is True

    def test_cannot_send_during_cooldown(self):
        mgr = AlertManager()
        mgr._cooldown = 300
        mgr._last_alert_times["test_alert"] = time.time()
        assert mgr._can_send("test_alert") is False

    def test_can_send_after_cooldown(self):
        mgr = AlertManager()
        mgr._cooldown = 1
        mgr._last_alert_times["test_alert"] = time.time() - 2
        assert mgr._can_send("test_alert") is True

    def test_different_types_independent(self):
        mgr = AlertManager()
        mgr._cooldown = 300
        mgr._last_alert_times["type_a"] = time.time()
        assert mgr._can_send("type_a") is False
        assert mgr._can_send("type_b") is True


class TestSendAlert:
    """Test send_alert method."""

    @pytest.mark.asyncio
    async def test_skip_no_webhook(self):
        mgr = AlertManager()
        mgr._webhook_url = ""
        result = await mgr.send_alert("Test", "desc")
        assert result is False

    @pytest.mark.asyncio
    async def test_skip_cooldown(self):
        mgr = AlertManager()
        mgr._webhook_url = "https://example.com/webhook"
        mgr._cooldown = 300
        mgr._last_alert_times["general"] = time.time()
        result = await mgr.send_alert("Test", "desc", alert_type="general")
        assert result is False

    @pytest.mark.asyncio
    async def test_send_success(self):
        mgr = AlertManager()
        mgr._webhook_url = "https://example.com/webhook"

        mock_resp = MagicMock()
        mock_resp.status = 200

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_cm)
        mock_session.closed = False
        mgr._session = mock_session

        result = await mgr.send_alert("Test Alert", "Something happened", severity="critical")
        assert result is True
        assert mgr.alert_count == 1

    @pytest.mark.asyncio
    async def test_send_with_fields(self):
        mgr = AlertManager()
        mgr._webhook_url = "https://example.com/webhook"

        mock_resp = MagicMock()
        mock_resp.status = 204

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_cm)
        mock_session.closed = False
        mgr._session = mock_session

        result = await mgr.send_alert(
            "Test", "desc",
            fields=[{"name": "Key", "value": "Val"}],
            severity="info",
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_send_http_error(self):
        mgr = AlertManager()
        mgr._webhook_url = "https://example.com/webhook"

        mock_resp = AsyncMock()
        mock_resp.status = 429
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=mock_resp)
        mgr._session = mock_session

        result = await mgr.send_alert("Test", "rate limited")
        assert result is False
        assert mgr.alert_count == 0

    @pytest.mark.asyncio
    async def test_send_exception(self):
        mgr = AlertManager()
        mgr._webhook_url = "https://example.com/webhook"

        mock_session = AsyncMock()
        mock_session.post = MagicMock(side_effect=Exception("Connection failed"))
        mgr._session = mock_session

        result = await mgr.send_alert("Test", "network error")
        assert result is False


class TestConvenienceMethods:
    """Test convenience alert methods."""

    @pytest.mark.asyncio
    async def test_alert_circuit_breaker_open(self):
        mgr = AlertManager()
        mgr.send_alert = AsyncMock(return_value=True)
        result = await mgr.alert_circuit_breaker_open("gemini_api")
        assert result is True
        mgr.send_alert.assert_called_once()
        call_kwargs = mgr.send_alert.call_args
        assert "gemini_api" in call_kwargs[1]["title"]
        assert call_kwargs[1]["severity"] == "critical"

    @pytest.mark.asyncio
    async def test_alert_memory_threshold(self):
        mgr = AlertManager()
        mgr.send_alert = AsyncMock(return_value=True)
        result = await mgr.alert_memory_threshold(512.0, 400.0)
        assert result is True
        call_kwargs = mgr.send_alert.call_args
        assert call_kwargs[1]["severity"] == "warning"

    @pytest.mark.asyncio
    async def test_alert_health_check_failed_warning(self):
        mgr = AlertManager()
        mgr.send_alert = AsyncMock(return_value=True)
        await mgr.alert_health_check_failed("go_health_api", 3)
        call_kwargs = mgr.send_alert.call_args
        assert call_kwargs[1]["severity"] == "warning"

    @pytest.mark.asyncio
    async def test_alert_health_check_failed_critical(self):
        mgr = AlertManager()
        mgr.send_alert = AsyncMock(return_value=True)
        await mgr.alert_health_check_failed("go_health_api", 5)
        call_kwargs = mgr.send_alert.call_args
        assert call_kwargs[1]["severity"] == "critical"

    @pytest.mark.asyncio
    async def test_alert_error_spike(self):
        mgr = AlertManager()
        mgr.send_alert = AsyncMock(return_value=True)
        result = await mgr.alert_error_spike(50, "5 minutes")
        assert result is True


class TestSessionManagement:
    """Test aiohttp session lifecycle."""

    @pytest.mark.asyncio
    async def test_close_session(self):
        mgr = AlertManager()
        mock_session = AsyncMock()
        mock_session.closed = False
        mgr._session = mock_session
        await mgr.close()
        mock_session.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_no_session(self):
        mgr = AlertManager()
        mgr._session = None
        await mgr.close()  # Should not raise

    @pytest.mark.asyncio
    async def test_close_already_closed(self):
        mgr = AlertManager()
        mock_session = AsyncMock()
        mock_session.closed = True
        mgr._session = mock_session
        await mgr.close()
        mock_session.close.assert_not_called()
