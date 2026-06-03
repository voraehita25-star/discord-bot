# pylint: disable=protected-access
"""
Unit Tests for AI Core Performance Module.
Tests PerformanceTracker timing/stats and RequestDeduplicator key generation,
including a regression test for the status-block stripping bug (find vs rfind).
"""

from __future__ import annotations


class TestPerformanceTracker:
    """Tests for PerformanceTracker timing and statistics."""

    def test_record_and_get_step_stats(self):
        """Recording timings produces correct count and ms aggregates."""
        from cogs.ai_core.core.performance import PerformanceTracker

        tracker = PerformanceTracker()
        tracker.record_timing("api_call", 0.1)
        tracker.record_timing("api_call", 0.3)

        stats = tracker.get_step_stats("api_call")
        assert stats["count"] == 2
        # 0.1s and 0.3s -> avg 0.2s -> 200ms
        assert stats["avg_ms"] == 200.0
        assert stats["max_ms"] == 300.0
        assert stats["min_ms"] == 100.0

    def test_empty_step_stats_are_zeroed(self):
        """An untouched / unknown step returns zeroed stats, not a crash."""
        from cogs.ai_core.core.performance import PerformanceTracker

        tracker = PerformanceTracker()
        stats = tracker.get_step_stats("never_recorded")
        assert stats == {"count": 0, "avg_ms": 0, "max_ms": 0, "min_ms": 0}

    def test_dynamic_step_is_tracked(self):
        """Recording a non-predefined step creates a new bucket."""
        from cogs.ai_core.core.performance import PerformanceTracker

        tracker = PerformanceTracker()
        tracker.record_timing("custom_step", 0.05)

        assert tracker.get_step_stats("custom_step")["count"] == 1

    def test_max_tracked_steps_is_bounded(self):
        """New step types are ignored once MAX_TRACKED_STEPS is reached."""
        from cogs.ai_core.core.performance import PerformanceTracker

        tracker = PerformanceTracker()
        # Fill up to the cap with unique step names.
        existing = len(tracker._metrics)
        to_add = tracker.MAX_TRACKED_STEPS - existing
        for i in range(to_add):
            tracker.record_timing(f"fill_{i}", 0.01)
        assert len(tracker._metrics) == tracker.MAX_TRACKED_STEPS

        # One more new step type must be rejected (bucket count unchanged).
        tracker.record_timing("overflow_step", 0.01)
        assert "overflow_step" not in tracker._metrics
        assert len(tracker._metrics) == tracker.MAX_TRACKED_STEPS

    def test_clear_metrics_resets_counts(self):
        """clear_metrics() empties the recorded samples."""
        from cogs.ai_core.core.performance import PerformanceTracker

        tracker = PerformanceTracker()
        tracker.record_timing("total", 0.2)
        assert tracker.get_step_stats("total")["count"] == 1

        tracker.clear_metrics("total")
        assert tracker.get_step_stats("total")["count"] == 0

    def test_get_summary_reports_recorded_steps(self):
        """get_summary() includes a line for steps with samples."""
        from cogs.ai_core.core.performance import PerformanceTracker

        tracker = PerformanceTracker()
        tracker.record_timing("rag_search", 0.05)
        summary = tracker.get_summary()
        assert "rag_search" in summary
        assert "samples=1" in summary

    def test_get_summary_empty(self):
        """get_summary() with no data returns the placeholder string."""
        from cogs.ai_core.core.performance import PerformanceTracker

        tracker = PerformanceTracker()
        assert tracker.get_summary() == "No performance data available"


class TestRequestDeduplicatorGenerateKey:
    """Tests for RequestDeduplicator.generate_key()."""

    HEADER = "[สถานะปัจจุบันของตัวละคร]"

    def test_identical_inputs_same_key(self):
        """Same channel + user + message yields an identical key."""
        from cogs.ai_core.core.performance import RequestDeduplicator

        k1 = RequestDeduplicator.generate_key(987, 123, "hello there")
        k2 = RequestDeduplicator.generate_key(987, 123, "hello there")
        assert k1 == k2

    def test_different_messages_different_keys(self):
        """Different messages (same channel/user) yield different keys."""
        from cogs.ai_core.core.performance import RequestDeduplicator

        k1 = RequestDeduplicator.generate_key(987, 123, "first message")
        k2 = RequestDeduplicator.generate_key(987, 123, "second message")
        assert k1 != k2

    def test_different_channel_or_user_changes_key(self):
        """Channel and user IDs are part of the key namespace."""
        from cogs.ai_core.core.performance import RequestDeduplicator

        base = RequestDeduplicator.generate_key(1, 2, "msg")
        assert RequestDeduplicator.generate_key(9, 2, "msg") != base
        assert RequestDeduplicator.generate_key(1, 9, "msg") != base

    def test_key_format_is_channel_user_hash(self):
        """Key is 'channel:user:<16-hex>' for non-empty content."""
        from cogs.ai_core.core.performance import RequestDeduplicator

        key = RequestDeduplicator.generate_key(42, 7, "some content")
        prefix, _, msg_hash = key.split(":")
        assert prefix == "42"
        assert key.startswith("42:7:")
        assert len(msg_hash) == 16
        # 16 hex chars
        int(msg_hash, 16)

    def test_empty_message_returns_stable_key_no_crash(self):
        """Empty message produces a stable ':empty' key without crashing."""
        from cogs.ai_core.core.performance import RequestDeduplicator

        k1 = RequestDeduplicator.generate_key(5, 6, "")
        k2 = RequestDeduplicator.generate_key(5, 6, "")
        assert k1 == k2
        assert k1 == "5:6:empty"

    def test_message_without_status_header_keyed_on_full_content(self):
        """A message lacking the status header is keyed on its whole content.

        Two plain messages that differ only in a trailing fragment must still
        produce distinct keys (full content is hashed, not a sliced suffix).
        """
        from cogs.ai_core.core.performance import RequestDeduplicator

        k1 = RequestDeduplicator.generate_key(1, 2, "tell me about weather")
        k2 = RequestDeduplicator.generate_key(1, 2, "tell me about music")
        assert k1 != k2

    def test_status_block_strip_uses_first_blank_line_not_last(self):
        """Regression: status stripping must use the FIRST blank line after the
        header, not the last (the old rfind bug).

        Both messages start with the same status block, then carry DIFFERENT
        user prompts that each end with the SAME trailing fragment preceded by a
        blank line. With the correct ``find`` the differing prompt bodies are
        retained, so the keys differ. The old ``rfind`` would slice down to the
        shared trailing fragment, collapsing both to one key (a false duplicate).
        """
        from cogs.ai_core.core.performance import RequestDeduplicator

        status_block = f"{self.HEADER}\nHP: 100\nMP: 50"
        shared_tail = "\n\nSHARED TAIL FRAGMENT"

        msg1 = f"{status_block}\n\nplease tell me about the weather{shared_tail}"
        msg2 = f"{status_block}\n\nplease tell me about the music{shared_tail}"

        k1 = RequestDeduplicator.generate_key(1, 2, msg1)
        k2 = RequestDeduplicator.generate_key(1, 2, msg2)

        # Correct (find) behavior: distinct prompts -> distinct keys.
        assert k1 != k2

    def test_status_block_strip_ignores_status_contents(self):
        """Two messages with different status blocks but the same user prompt
        after the first blank line collide (status block is intentionally
        stripped before hashing)."""
        from cogs.ai_core.core.performance import RequestDeduplicator

        prompt = "what is the time?"
        msg_a = f"{self.HEADER}\nHP: 100\n\n{prompt}"
        msg_b = f"{self.HEADER}\nHP: 1\nMP: 999\n\n{prompt}"

        k_a = RequestDeduplicator.generate_key(1, 2, msg_a)
        k_b = RequestDeduplicator.generate_key(1, 2, msg_b)
        assert k_a == k_b

    def test_system_info_header_is_stripped(self):
        """A [System Info] preamble is dropped; the real prompt drives the key."""
        from cogs.ai_core.core.performance import RequestDeduplicator

        with_preamble = "[System Info]\ntime=12:00\n\nactual user prompt"
        plain = "actual user prompt"
        assert RequestDeduplicator.generate_key(1, 2, with_preamble) == (
            RequestDeduplicator.generate_key(1, 2, plain)
        )

    def test_command_prefix_is_stripped(self):
        """'!chat <text>' keys the same as the bare text."""
        from cogs.ai_core.core.performance import RequestDeduplicator

        assert RequestDeduplicator.generate_key(1, 2, "!chat hello") == (
            RequestDeduplicator.generate_key(1, 2, "hello")
        )

    def test_surrogate_content_does_not_crash(self):
        """Malformed surrogate input is encoded with errors='replace', no crash."""
        from cogs.ai_core.core.performance import RequestDeduplicator

        bad = "valid\ud800text"  # lone surrogate
        key = RequestDeduplicator.generate_key(1, 2, bad)
        assert key.startswith("1:2:")


class TestRequestDeduplicatorBehavior:
    """Tests for the dedup add/check lifecycle (uses generate_key keys)."""

    def test_check_and_add_detects_duplicate(self):
        """First check_and_add is False, second for same key is True."""
        from cogs.ai_core.core.performance import RequestDeduplicator

        dedup = RequestDeduplicator()
        key = RequestDeduplicator.generate_key(1, 2, "hi")

        assert dedup.check_and_add(key) is False
        assert dedup.check_and_add(key) is True
        assert dedup.is_duplicate(key) is True
        assert dedup.get_pending_count() == 1

    def test_remove_request_clears_pending(self):
        """Removing a key makes it eligible again."""
        from cogs.ai_core.core.performance import RequestDeduplicator

        dedup = RequestDeduplicator()
        key = RequestDeduplicator.generate_key(1, 2, "hi")
        dedup.add_request(key)
        assert dedup.is_duplicate(key) is True

        dedup.remove_request(key)
        assert dedup.is_duplicate(key) is False
        assert dedup.get_pending_count() == 0

    def test_cleanup_removes_stale_entries(self, monkeypatch):
        """cleanup() drops entries older than max_age (no real sleep)."""
        import cogs.ai_core.core.performance as perf
        from cogs.ai_core.core.performance import RequestDeduplicator

        fake_now = [1000.0]
        monkeypatch.setattr(perf.time, "time", lambda: fake_now[0])

        dedup = RequestDeduplicator()
        dedup.add_request("old_key")

        # Advance virtual clock well past max_age.
        fake_now[0] = 1000.0 + 120.0
        removed = dedup.cleanup(max_age=60.0)

        assert removed == 1
        assert dedup.get_pending_count() == 0

    def test_cleanup_keeps_fresh_entries(self, monkeypatch):
        """cleanup() leaves entries younger than max_age intact."""
        import cogs.ai_core.core.performance as perf
        from cogs.ai_core.core.performance import RequestDeduplicator

        fake_now = [2000.0]
        monkeypatch.setattr(perf.time, "time", lambda: fake_now[0])

        dedup = RequestDeduplicator()
        dedup.add_request("fresh_key")

        fake_now[0] = 2000.0 + 5.0  # within max_age
        removed = dedup.cleanup(max_age=60.0)

        assert removed == 0
        assert dedup.get_pending_count() == 1
