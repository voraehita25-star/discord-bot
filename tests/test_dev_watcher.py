# pylint: disable=protected-access
"""
Unit Tests for the Dev Watcher (scripts/dev_watcher.py).

Covers the BotRestarter restart/health/crash logic with subprocess.Popen
and time.sleep fully mocked so nothing real launches and no real waits occur.

Regression coverage:
- VE#21: the consecutive-crash counter is only reset to 0 when the launched
  bot is confirmed healthy. If the health check fails, the counter is left
  intact so the retry cap (max_crash_retries) can actually be reached instead
  of looping forever.
- VE#20: once max_crash_retries is exceeded, check_for_crash() clears the dead
  process handle (self.process = None) so a subsequent tick short-circuits via
  the `if not self.process: return False` guard and stops re-detecting the same
  dead process every poll.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# BotRestarter is only defined when the watchdog package is importable.
from scripts import dev_watcher

pytestmark = pytest.mark.skipif(
    not dev_watcher.WATCHDOG_AVAILABLE,
    reason="watchdog not installed; BotRestarter is not defined",
)


def _make_restarter(**config_overrides):
    """Build a BotRestarter with Popen + sleep mocked out.

    The constructor immediately calls start_bot("Initial start"), so we patch
    subprocess.Popen and time.sleep for the whole construction. By default we
    disable the health check during construction so the initial launch is a
    clean, deterministic no-op; individual tests re-enable / stub the health
    check as needed.

    Returns (restarter, popen_mock).
    """
    overrides = {"health_check_enabled": False}
    overrides.update(config_overrides)
    config = dev_watcher.DevWatcherConfig(**overrides)
    logger = MagicMock()

    fake_proc = MagicMock()
    fake_proc.poll.return_value = None  # alive by default

    with (
        patch.object(dev_watcher.subprocess, "Popen", return_value=fake_proc) as popen_mock,
        patch.object(dev_watcher.time, "sleep"),
    ):
        restarter = dev_watcher.BotRestarter(config, logger)

    return restarter, popen_mock


class TestStartBotConstruction:
    """Construction-time behavior of BotRestarter."""

    def test_constructor_launches_bot_via_popen(self):
        restarter, popen_mock = _make_restarter()
        assert popen_mock.call_count == 1
        assert restarter.process is not None
        assert restarter.stats.restart_count == 1

    def test_constructor_passes_no_health_disabled_keeps_counter_zero(self):
        # No prior crashes; counter starts at 0 and stays 0.
        restarter, _ = _make_restarter()
        assert restarter.consecutive_crashes == 0


class TestHealthGatedCounterReset:
    """VE#21: consecutive_crashes only resets when the bot is healthy."""

    def test_unhealthy_does_not_reset_consecutive_crashes(self):
        restarter, _ = _make_restarter(health_check_enabled=True)
        # Simulate accumulated crashes from prior failed launches.
        restarter.consecutive_crashes = 2
        # Bypass debounce so the next launch actually runs.
        restarter.last_event_time = 0.0

        with (
            patch.object(dev_watcher.subprocess, "Popen", return_value=MagicMock()),
            patch.object(dev_watcher.time, "sleep"),
            patch.object(restarter, "_perform_health_check", return_value=False),
            patch.object(dev_watcher.time, "time", return_value=10_000.0),
        ):
            result = restarter._start_bot_unlocked("retry")

        assert result is True
        # The launch happened, but because the bot was NOT healthy the
        # counter must be preserved so the retry cap can be reached.
        assert restarter.consecutive_crashes == 2

    def test_healthy_resets_consecutive_crashes(self):
        restarter, _ = _make_restarter(health_check_enabled=True)
        restarter.consecutive_crashes = 2
        restarter.last_event_time = 0.0

        with (
            patch.object(dev_watcher.subprocess, "Popen", return_value=MagicMock()),
            patch.object(dev_watcher.time, "sleep"),
            patch.object(restarter, "_perform_health_check", return_value=True),
            patch.object(dev_watcher.time, "time", return_value=10_000.0),
        ):
            result = restarter._start_bot_unlocked("retry")

        assert result is True
        assert restarter.consecutive_crashes == 0

    def test_health_check_disabled_treats_as_healthy_and_resets(self):
        # When health check is disabled, healthy defaults to True -> reset.
        restarter, _ = _make_restarter(health_check_enabled=False)
        restarter.consecutive_crashes = 3
        restarter.last_event_time = 0.0

        with (
            patch.object(dev_watcher.subprocess, "Popen", return_value=MagicMock()),
            patch.object(dev_watcher.time, "sleep"),
            patch.object(dev_watcher.time, "time", return_value=10_000.0),
        ):
            result = restarter._start_bot_unlocked("retry")

        assert result is True
        assert restarter.consecutive_crashes == 0


class TestPerformHealthCheck:
    """_perform_health_check reflects the live/dead state of the process."""

    def test_health_check_passes_when_process_alive(self):
        restarter, _ = _make_restarter()
        restarter.process = MagicMock()
        restarter.process.poll.return_value = None  # still running

        with patch.object(dev_watcher.time, "sleep") as sleep_mock:
            assert restarter._perform_health_check() is True
        # It sleeps for the configured health_check_delay before polling.
        sleep_mock.assert_called_once_with(restarter.config.health_check_delay)

    def test_health_check_fails_when_process_exited(self):
        restarter, _ = _make_restarter()
        restarter.process = MagicMock()
        restarter.process.poll.return_value = 1  # exited with error

        with patch.object(dev_watcher.time, "sleep"):
            assert restarter._perform_health_check() is False

    def test_health_check_fails_when_no_process(self):
        restarter, _ = _make_restarter()
        restarter.process = None

        with patch.object(dev_watcher.time, "sleep"):
            assert restarter._perform_health_check() is False


class TestCheckForCrash:
    """VE#20 + crash/retry accounting in check_for_crash()."""

    def test_no_process_returns_false(self):
        restarter, _ = _make_restarter()
        restarter.process = None
        assert restarter.check_for_crash() is False

    def test_running_process_returns_false(self):
        restarter, _ = _make_restarter()
        restarter.process = MagicMock()
        restarter.process.poll.return_value = None  # still running
        assert restarter.check_for_crash() is False

    def test_clean_exit_zero_does_not_count_as_crash(self):
        restarter, _ = _make_restarter()
        restarter.process = MagicMock()
        restarter.process.poll.return_value = 0  # graceful exit
        crash_before = restarter.stats.crash_count
        # exit code 0 -> not a crash, returns False
        assert restarter.check_for_crash() is False
        assert restarter.stats.crash_count == crash_before

    def test_crash_under_cap_triggers_retry_and_increments_counter(self):
        restarter, _ = _make_restarter(auto_retry_on_crash=True, max_crash_retries=3)
        restarter.process = MagicMock()
        restarter.process.poll.return_value = 1  # crashed
        restarter.consecutive_crashes = 0

        with (
            patch.object(dev_watcher.time, "sleep"),
            patch.object(restarter, "_start_bot_unlocked") as restart_mock,
        ):
            result = restarter.check_for_crash()

        assert result is True
        assert restarter.consecutive_crashes == 1
        assert restarter.stats.crash_count == 1
        # Under the cap -> auto-retry path is taken.
        restart_mock.assert_called_once()
        # Under-cap path must NOT null out the process.
        assert restarter.process is not None

    def test_max_retries_exceeded_clears_process_handle(self):
        # VE#20: after exceeding the cap, self.process is set to None so the
        # next tick returns False instead of re-detecting the dead process.
        restarter, _ = _make_restarter(auto_retry_on_crash=True, max_crash_retries=3)
        dead = MagicMock()
        dead.poll.return_value = 1  # crashed
        restarter.process = dead
        # Already at the cap; this crash pushes it over.
        restarter.consecutive_crashes = 3

        with (
            patch.object(dev_watcher.time, "sleep"),
            patch.object(restarter, "_start_bot_unlocked") as restart_mock,
        ):
            result = restarter.check_for_crash()

        assert result is True
        assert restarter.consecutive_crashes == 4  # incremented past the cap
        # Over the cap -> no auto-retry, and the handle is cleared.
        restart_mock.assert_not_called()
        assert restarter.process is None

        # And a subsequent tick short-circuits via the guard.
        assert restarter.check_for_crash() is False

    def test_auto_retry_disabled_still_clears_nothing_but_counts_crash(self):
        # With auto-retry off, the crash is counted/returned True but the
        # retry/give-up branch is skipped entirely (process handle untouched).
        restarter, _ = _make_restarter(auto_retry_on_crash=False, max_crash_retries=3)
        proc = MagicMock()
        proc.poll.return_value = 1
        restarter.process = proc
        restarter.consecutive_crashes = 0

        with patch.object(dev_watcher.time, "sleep"):
            result = restarter.check_for_crash()

        assert result is True
        assert restarter.stats.crash_count == 1
        assert restarter.consecutive_crashes == 1
        # auto_retry_on_crash is False -> neither retry nor process clearing.
        assert restarter.process is proc
