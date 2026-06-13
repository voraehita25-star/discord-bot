"""
Discord Alert System for Critical Failures.

Sends alerts to a configured Discord webhook or channel when:
- Circuit breaker opens (API outage detected)
- Memory exceeds threshold
- Health check fails repeatedly
- Bot errors exceed threshold
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

# Configuration
ALERT_WEBHOOK_URL = os.getenv("ALERT_WEBHOOK_URL", "")


def _safe_int_env(name: str, default: int) -> int:
    """Parse an int env var; fall back to default + log on garbage input.

    Bare ``int(os.getenv(...))`` at module-import time crashes the entire
    bot if a user has set ``ALERT_COOLDOWN_SECONDS=abc`` in .env.
    """
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("Invalid %s=%r — using default %d", name, raw, default)
        return default
    if value < 0:
        # A negative cooldown would make (now - last_sent) >= cooldown always
        # true, silently disabling spam protection. Clamp to 0 (0 = intentional
        # "no cooldown"); a negative value is almost certainly operator error.
        logger.warning("%s=%d is negative — clamping to 0", name, value)
        return 0
    return value


ALERT_COOLDOWN_SECONDS = _safe_int_env("ALERT_COOLDOWN_SECONDS", 300)  # 5 min default


class AlertManager:
    """Manages sending alerts to Discord with cooldowns to prevent spam."""

    # Cap on how many alert_type entries we track. Without this, dynamic
    # alert types (e.g. ``circuit_breaker_<service>``, ``health_<svc>``)
    # could grow the cooldown dict unboundedly across the bot's lifetime.
    _MAX_TRACKED_ALERT_TYPES = 1000

    def __init__(self) -> None:
        self._last_alert_times: dict[str, float] = {}
        self._webhook_url = ALERT_WEBHOOK_URL
        self._cooldown = ALERT_COOLDOWN_SECONDS
        self._session: aiohttp.ClientSession | None = None
        self._session_lock = asyncio.Lock()
        # Async lock guarding the cooldown map so two concurrent senders
        # can't both pass the cooldown check (TOCTOU) and double-fire.
        self._cooldown_lock = asyncio.Lock()
        self._alert_count = 0

    @property
    def webhook_configured(self) -> bool:
        """Check if webhook URL is configured."""
        return bool(self._webhook_url)

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session (async-safe via lock)."""
        async with self._session_lock:
            if self._session is not None and self._session.closed:
                # Session was closed externally — clean up before replacing
                try:
                    await self._session.close()
                except Exception:
                    pass
                self._session = None
            if self._session is None:
                self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))
            return self._session

    def _can_send(self, alert_type: str) -> bool:
        """Check if alert can be sent (respects cooldown).

        Sync read-only check kept for callers / tests that just want to
        peek without committing the cooldown slot. Production sends use
        ``_try_acquire_cooldown`` instead so the check + commit happen
        atomically under the cooldown lock.
        """
        now = time.time()
        last_sent = self._last_alert_times.get(alert_type, 0.0)
        return (now - last_sent) >= self._cooldown

    async def _try_acquire_cooldown(self, alert_type: str) -> tuple[bool, float, float | None]:
        """Atomic check-and-update of the per-type cooldown timestamp.

        Returns ``(acquired, previous_ts)``. ``acquired`` is True if the alert
        is allowed to fire (and the slot is reserved). ``previous_ts`` is the
        timestamp that occupied the slot beforehand — pass it to
        ``_rollback_cooldown`` if the subsequent send FAILS, so a transient
        delivery error doesn't silence the alert for a full cooldown window
        (critical for outage alerts, whose webhook POST is most likely to fail
        exactly when the outage that triggered them is happening).

        The previous split implementation read + wrote the dict in two
        separate steps, so two concurrent callers could both pass the check.
        """
        now = time.time()
        async with self._cooldown_lock:
            last_sent = self._last_alert_times.get(alert_type, 0.0)
            if (now - last_sent) < self._cooldown:
                return False, last_sent, None
            # Evict oldest entry if we're at the cap. This is best-effort —
            # the next caller can always re-add an entry.
            if (
                len(self._last_alert_times) >= self._MAX_TRACKED_ALERT_TYPES
                and alert_type not in self._last_alert_times
            ):
                # Defensive None-safe key: a future bug elsewhere could leave
                # a key with a None value, and `min(... key=dict.get)` would
                # raise TypeError comparing None to a float. Treat None as
                # very-old so it gets evicted first instead of crashing.
                oldest_key = min(
                    self._last_alert_times,
                    key=lambda k: (
                        self._last_alert_times[k] if self._last_alert_times[k] is not None else 0.0
                    ),
                )
                self._last_alert_times.pop(oldest_key, None)
            self._last_alert_times[alert_type] = now
            return True, last_sent, now

    async def _rollback_cooldown(
        self, alert_type: str, previous_ts: float, reserved_ts: float | None
    ) -> None:
        """Undo a cooldown reservation after a failed send so it can retry.

        Restores the prior timestamp (so retries are still gated on the last
        *successful* send, not on a failed attempt), or clears the slot if it
        had none. Compare-and-set against ``reserved_ts`` (the timestamp this
        caller wrote in ``_try_acquire_cooldown``): only mutate when our
        reservation is STILL the current value — otherwise a concurrent caller
        legitimately acquired + sent after us, and overwriting their newer
        timestamp would re-open the cooldown and permit a duplicate alert
        (lost-update race). The docstring previously promised this guard but
        the body restored unconditionally.
        """
        async with self._cooldown_lock:
            if self._last_alert_times.get(alert_type) != reserved_ts:
                # A newer writer took the slot after us — leave it untouched.
                return
            if previous_ts:
                self._last_alert_times[alert_type] = previous_ts
            else:
                self._last_alert_times.pop(alert_type, None)

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

        # Atomic cooldown reservation — also commits the timestamp on
        # success so we don't double-acquire below in the success branch.
        # Keep the prior timestamp so we can roll the reservation back if the
        # send fails (otherwise a transient failure mutes this alert type for
        # a full cooldown window).
        acquired, prev_cooldown_ts, reserved_cooldown_ts = await self._try_acquire_cooldown(
            alert_type
        )
        if not acquired:
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
            "title": f"{icon_map.get(severity, '⚠️')} {title}"[:256],
            "description": description[:4096],
            "color": color_map.get(severity, 0xF39C12),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "footer": {"text": "Bot Alert System"},
        }

        if fields:
            # Discord embed field limits: name ≤256, value ≤1024 chars.
            # Truncate so a long value can't trip a 400 from the API.
            embed["fields"] = [
                {
                    "name": str(f["name"])[:256],
                    "value": str(f["value"])[:1024],
                    "inline": f.get("inline", True),
                }
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
                    # Cooldown timestamp was already set by
                    # _try_acquire_cooldown above; just bump the counter.
                    self._alert_count += 1
                    logger.info("Alert sent: %s", title)
                    return True
                else:
                    logger.warning("Alert failed (HTTP %d): %s", resp.status, title)
                    await self._rollback_cooldown(
                        alert_type, prev_cooldown_ts, reserved_cooldown_ts
                    )
                    return False
        except Exception:
            # Don't put `e` (repr of which may include the webhook URL on
            # some aiohttp errors) into the log line — use exception() so
            # the traceback goes through the secret-redaction filter.
            logger.exception("Failed to send alert (title=%s)", title[:100])
            await self._rollback_cooldown(alert_type, prev_cooldown_ts, reserved_cooldown_ts)
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
        self._session = None

    def close_sync(self) -> None:
        """Best-effort sync close for interpreter shutdown.

        Drops the session reference so the GC can collect it. We don't
        try to manually close the underlying connector — older versions
        of that code reached into ``session._connector._close()`` which
        is private API that aiohttp 3.9+ removed. The "Unclosed session"
        warning we used to fight is harmless during interpreter exit.
        """
        self._session = None

    # No __del__ — running async/private-API code during garbage
    # collection is unreliable (GC ordering at shutdown is undefined,
    # and exceptions in __del__ get printed to stderr without context).
    # Callers should use ``await close()`` from an explicit shutdown path.

    @property
    def alert_count(self) -> int:
        """Total number of alerts sent."""
        return self._alert_count


# Global alert manager instance
alert_manager = AlertManager()
