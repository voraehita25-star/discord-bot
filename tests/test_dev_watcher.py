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
        # The crash-retry path now defers the health check OUTSIDE the lock and
        # resets consecutive_crashes only when the retried bot is confirmed
        # healthy (mirrors start_bot; keeps _lock off the multi-second health
        # sleep). Here the retried bot is NOT healthy, so the counter must stay
        # at 1 (VE#21 — the cap can still be reached).
        restarter, _ = _make_restarter(
            auto_retry_on_crash=True, max_crash_retries=3, health_check_enabled=True
        )
        restarter.process = MagicMock()
        restarter.process.poll.return_value = 1  # crashed
        restarter.consecutive_crashes = 0

        with (
            patch.object(dev_watcher.time, "sleep"),
            patch.object(restarter, "_start_bot_unlocked", return_value=True) as restart_mock,
            patch.object(restarter, "_perform_health_check", return_value=False) as health_mock,
        ):
            result = restarter.check_for_crash()

        assert result is True
        assert restarter.consecutive_crashes == 1
        assert restarter.stats.crash_count == 1
        # Under the cap -> auto-retry path is taken (with the health check deferred).
        restart_mock.assert_called_once()
        assert restart_mock.call_args.kwargs.get("run_health_check") is False
        # Health check ran OUTSIDE the lock and failed, so no reset.
        health_mock.assert_called_once()
        # Under-cap path must NOT null out the process.
        assert restarter.process is not None

    def test_crash_retry_resets_counter_when_retried_bot_is_healthy(self):
        # Companion to the above: when the retried bot comes up healthy, the
        # consecutive-crash counter resets to 0 (so a transient crash doesn't
        # erode the retry budget).
        restarter, _ = _make_restarter(
            auto_retry_on_crash=True, max_crash_retries=3, health_check_enabled=True
        )
        restarter.process = MagicMock()
        restarter.process.poll.return_value = 1  # crashed
        restarter.consecutive_crashes = 1

        with (
            patch.object(dev_watcher.time, "sleep"),
            patch.object(restarter, "_start_bot_unlocked", return_value=True),
            patch.object(restarter, "_perform_health_check", return_value=True),
        ):
            result = restarter.check_for_crash()

        assert result is True
        # Incremented to 2 by the crash, then reset to 0 once confirmed healthy.
        assert restarter.consecutive_crashes == 0

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

    def test_auto_retry_disabled_counts_crash_and_clears_handle(self):
        # With auto-retry off, the crash is counted/returned True AND the dead
        # process handle is cleared, so subsequent 0.5s ticks don't re-detect
        # the same crash (which would grow crash_count without bound and spam
        # [CRASH]). A file-save restart reassigns self.process.
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
        # Dead handle cleared — no auto-retry means it must not linger.
        assert restarter.process is None
        # A subsequent tick is a no-op (hits the `if not self.process` guard)
        # and does NOT re-count the same crash.
        assert restarter.check_for_crash() is False
        assert restarter.stats.crash_count == 1


class TestTrailingEdgeDebounce:
    """Trailing-edge debounce: an edit dropped by the leading-edge debounce
    guard is remembered and later flushed by the main loop, so the final save
    of a rapid multi-save still restarts the bot instead of being lost."""

    def test_debounced_start_records_pending_reason_and_returns_false(self):
        # An edit landing inside the debounce window can't restart now; it must
        # record the owed restart so a later flush can fire it.
        restarter, _ = _make_restarter()
        restarter.last_event_time = 10_000.0
        restarter._pending_restart_reason = None

        # now - last_event_time = 0.5 < 1.5 (default debounce) -> debounced.
        with patch.object(dev_watcher.time, "time", return_value=10_000.5):
            result = restarter._start_bot_unlocked("File changed: b.py")

        assert result is False
        assert restarter._pending_restart_reason == "File changed: b.py"

    def test_successful_start_clears_pending_reason(self):
        # A restart that actually fires owes nothing afterwards, so the pending
        # flag left by an earlier debounced edit must be cleared.
        restarter, _ = _make_restarter()
        restarter._pending_restart_reason = "File changed: stale.py"
        restarter.last_event_time = 0.0

        with (
            patch.object(dev_watcher.subprocess, "Popen", return_value=MagicMock()),
            patch.object(dev_watcher.time, "sleep"),
            patch.object(dev_watcher.time, "time", return_value=10_000.0),
        ):
            result = restarter._start_bot_unlocked("File changed: fresh.py")

        assert result is True
        assert restarter._pending_restart_reason is None

    def test_flush_is_noop_when_nothing_pending(self):
        restarter, _ = _make_restarter()
        restarter._pending_restart_reason = None

        with patch.object(restarter, "_start_bot_unlocked") as restart_mock:
            restarter.flush_pending_restart()

        restart_mock.assert_not_called()

    def test_flush_is_noop_while_burst_still_active(self):
        # The debounce window has NOT elapsed since the last event, so we keep
        # coalescing (a later tick flushes it) rather than restarting mid-burst.
        restarter, _ = _make_restarter()
        restarter._pending_restart_reason = "File changed: b.py"
        restarter.last_event_time = 10_000.0

        with (
            patch.object(dev_watcher.time, "time", return_value=10_000.5),
            patch.object(restarter, "_start_bot_unlocked") as restart_mock,
        ):
            restarter.flush_pending_restart()

        restart_mock.assert_not_called()
        # Still owed — the flag must survive so a later tick can flush it.
        assert restarter._pending_restart_reason == "File changed: b.py"

    def test_flush_after_window_calls_start_with_pending_reason(self):
        # Once the window has elapsed, flush hands the owed reason to
        # _start_bot_unlocked with the health check deferred (run outside _lock).
        restarter, _ = _make_restarter()
        restarter._pending_restart_reason = "File changed: b.py"
        restarter.last_event_time = 10_000.0

        with (
            patch.object(dev_watcher.time, "time", return_value=10_002.0),
            patch.object(restarter, "_start_bot_unlocked", return_value=True) as restart_mock,
        ):
            restarter.flush_pending_restart()

        restart_mock.assert_called_once_with("File changed: b.py", run_health_check=False)

    def test_flush_after_window_restarts_and_clears_pending(self):
        # End-to-end (real _start_bot_unlocked, mocked Popen): the flush fires a
        # real restart, advances last_event_time, and clears the pending flag.
        restarter, _ = _make_restarter()
        restarts_before = restarter.stats.restart_count
        restarter._pending_restart_reason = "File changed: b.py"
        restarter.last_event_time = 10_000.0

        with (
            patch.object(dev_watcher.subprocess, "Popen", return_value=MagicMock()),
            patch.object(dev_watcher.time, "sleep"),
            patch.object(dev_watcher.time, "time", return_value=10_002.0),
        ):
            restarter.flush_pending_restart()

        assert restarter.stats.restart_count == restarts_before + 1
        assert restarter._pending_restart_reason is None
        assert restarter.last_event_time == 10_002.0
