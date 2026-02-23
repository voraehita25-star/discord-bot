"""
Discord Alert System for Critical Failures.

Sends alerts to a configured Discord webhook or channel when:
- Circuit breaker opens (API outage detected)
- Memory exceeds threshold
- Health check fails repeatedly
- Bot errors exceed threshold
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

# Configuration
ALERT_WEBHOOK_URL = os.getenv("ALERT_WEBHOOK_URL", "")
ALERT_COOLDOWN_SECONDS = int(os.getenv("ALERT_COOLDOWN_SECONDS", "300"))  # 5 min default


class AlertManager:
    """Manages sending alerts to Discord with cooldowns to prevent spam."""

    def __init__(self) -> None:
        self._last_alert_times: dict[str, float] = {}
        self._webhook_url = ALERT_WEBHOOK_URL
        self._cooldown = ALERT_COOLDOWN_SECONDS
        self._session: aiohttp.ClientSession | None = None
        self._alert_count = 0

    @property
    def webhook_configured(self) -> bool:
        """Check if webhook URL is configured."""
        return bool(self._webhook_url)

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))
        return self._session

    def _can_send(self, alert_type: str) -> bool:
        """Check if alert can be sent (respects cooldown)."""
        now = time.time()
        last_sent = self._last_alert_times.get(alert_type, 0)
        return (now - last_sent) >= self._cooldown

    async def send_alert(
        self,
        title: str,
        description: str,
        alert_type: str = "general",
        severity: str = "warning",
        fields: list[dict[str, str]] | None = None,
    ) -> bool:
        """Send an alert to Discord webhook.

        Args:
            title: Alert title
            description: Alert description
            alert_type: Category for cooldown grouping
            severity: One of 'info', 'warning', 'critical'
            fields: Optional embed fields

        Returns:
            True if alert was sent, False if skipped (cooldown) or failed
        """
        if not self.webhook_configured:
            logger.debug("Alert skipped (no webhook configured): %s", title)
            return False

        if not self._can_send(alert_type):
            logger.debug("Alert skipped (cooldown): %s", title)
            return False

        color_map = {
            "info": 0x3498DB,  # Blue
            "warning": 0xF39C12,  # Orange
            "critical": 0xE74C3C,  # Red
        }
        icon_map = {
            "info": "ℹ️",
            "warning": "⚠️",
            "critical": "🚨",
        }

        embed: dict[str, Any] = {
            "title": f"{icon_map.get(severity, '⚠️')} {title}",
            "description": description,
            "color": color_map.get(severity, 0xF39C12),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "footer": {"text": "Bot Alert System"},
        }

        if fields:
            embed["fields"] = [
                {"name": f["name"], "value": f["value"], "inline": f.get("inline", True)}
                for f in fields
            ]

        payload = {
            "embeds": [embed],
            "username": "Bot Alert",
        }

        try:
            session = await self._get_session()
            async with session.post(self._webhook_url, json=payload) as resp:
                if resp.status in (200, 204):
                    self._last_alert_times[alert_type] = time.time()
                    self._alert_count += 1
                    logger.info("Alert sent: %s", title)
                    return True
                else:
                    logger.warning("Alert failed (HTTP %d): %s", resp.status, title)
                    return False
        except Exception as e:
            logger.error("Failed to send alert: %s", e)
            return False

    async def alert_circuit_breaker_open(self, breaker_name: str) -> bool:
        """Alert when a circuit breaker opens."""
        return await self.send_alert(
            title=f"Circuit Breaker OPEN: {breaker_name}",
            description=f"The `{breaker_name}` circuit breaker has tripped. "
            f"API calls are being blocked to prevent cascading failures.",
            alert_type=f"circuit_breaker_{breaker_name}",
            severity="critical",
        )

    async def alert_memory_threshold(self, current_mb: float, threshold_mb: float) -> bool:
        """Alert when memory usage exceeds threshold."""
        return await self.send_alert(
            title="Memory Usage Warning",
            description=f"Memory usage is **{current_mb:.0f} MB** "
            f"(threshold: {threshold_mb:.0f} MB)",
            alert_type="memory_threshold",
            severity="warning",
            fields=[
                {"name": "Current", "value": f"{current_mb:.0f} MB"},
                {"name": "Threshold", "value": f"{threshold_mb:.0f} MB"},
            ],
        )

    async def alert_health_check_failed(self, service: str, consecutive_failures: int) -> bool:
        """Alert when health check fails repeatedly."""
        return await self.send_alert(
            title=f"Health Check Failed: {service}",
            description=f"Service `{service}` has failed {consecutive_failures} "
            f"consecutive health checks.",
            alert_type=f"health_{service}",
            severity="critical" if consecutive_failures >= 5 else "warning",
        )

    async def alert_error_spike(self, error_count: int, time_window: str) -> bool:
        """Alert when error rate spikes."""
        return await self.send_alert(
            title="Error Rate Spike",
            description=f"**{error_count}** errors detected in the last {time_window}.",
            alert_type="error_spike",
            severity="warning",
        )

    async def close(self) -> None:
        """Close the aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()

    @property
    def alert_count(self) -> int:
        """Total number of alerts sent."""
        return self._alert_count


# Global alert manager instance
alert_manager = AlertManager()
