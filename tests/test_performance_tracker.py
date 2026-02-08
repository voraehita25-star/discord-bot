# pylint: disable=protected-access
"""
Unit Tests for Performance Tracker Module.
Tests timing, percentiles, and trending.
"""

from __future__ import annotations

import time


class TestPerformanceStats:
    """Tests for PerformanceStats class."""

    def test_record_updates_stats(self):
        """Test recording updates all statistics."""
        from utils.monitoring.performance_tracker import PerformanceStats

        stats = PerformanceStats()
        stats.record(0.1)
        stats.record(0.2)
        stats.record(0.3)

        assert stats.count == 3
        assert abs(stats.total_time - 0.6) < 0.001
        assert stats.min_time == 0.1
        assert stats.max_time == 0.3

    def test_avg_time_calculation(self):
        """Test average time calculation."""
        from utils.monitoring.performance_tracker import PerformanceStats

        stats = PerformanceStats()
        stats.record(0.1)
        stats.record(0.2)
        stats.record(0.3)

        assert abs(stats.avg_time - 0.2) < 0.001

    def test_percentiles(self):
        """Test percentile calculations."""
        from utils.monitoring.performance_tracker import PerformanceStats

        stats = PerformanceStats()
        # Record 100 values from 0.01 to 1.0
        for i in range(1, 101):
            stats.record(i / 100.0)

        # P50 should be ~0.5
        assert 0.45 < stats.p50 < 0.55
        # P95 should be ~0.95
        assert 0.90 < stats.p95 < 1.0
        # P99 should be ~0.99
        assert 0.95 < stats.p99 <= 1.0

    def test_to_dict_format(self):
        """Test dictionary export format."""
        from utils.monitoring.performance_tracker import PerformanceStats

        stats = PerformanceStats()
        stats.record(0.1)

        result = stats.to_dict()

        assert "count" in result
        assert "avg_ms" in result
        assert "p50_ms" in result
        assert "p95_ms" in result
        assert "p99_ms" in result


class TestPerformanceTracker:
    """Tests for PerformanceTracker class."""

    def test_measure_context_manager(self):
        """Test timing via context manager."""
        from utils.monitoring.performance_tracker import PerformanceTracker

        tracker = PerformanceTracker()

        with tracker.measure("test_op"):
            time.sleep(0.025)  # 25ms - longer delay for reliable Windows timing

        stats = tracker.get_stats("test_op")
        assert stats["count"] == 1
        assert stats["avg_ms"] >= 1  # Very lenient check - just verify timing was recorded

    def test_manual_timing(self):
        """Test manual timing with start_timer and record."""
        from utils.monitoring.performance_tracker import PerformanceTracker

        tracker = PerformanceTracker()

        start = tracker.start_timer()
        time.sleep(0.01)
        duration = tracker.record("manual_op", start)

        assert duration >= 0.01
        assert tracker.get_stats("manual_op")["count"] == 1

    def test_get_all_stats(self):
        """Test getting stats for all operations."""
        from utils.monitoring.performance_tracker import PerformanceTracker

        tracker = PerformanceTracker()

        with tracker.measure("op1"):
            pass
        with tracker.measure("op2"):
            pass

        all_stats = tracker.get_all_stats()

        assert "op1" in all_stats
        assert "op2" in all_stats

    def test_get_summary(self):
        """Test summary generation."""
        from utils.monitoring.performance_tracker import PerformanceTracker

        tracker = PerformanceTracker()

        with tracker.measure("test"):
            pass

        summary = tracker.get_summary()

        assert summary["operations"] >= 1
        assert summary["total_measurements"] >= 1
        assert "stats" in summary


class TestPerformanceTrackerSingleton:
    """Tests for perf_tracker singleton."""

    def test_singleton_exists(self):
        """Test that perf_tracker singleton is accessible."""
        from utils.monitoring.performance_tracker import perf_tracker

        assert perf_tracker is not None

    def test_singleton_has_measure(self):
        """Test singleton has measure method."""
        from utils.monitoring.performance_tracker import perf_tracker

        assert hasattr(perf_tracker, "measure")
        assert callable(perf_tracker.measure)


class TestCorePerformanceTracker:
    """Tests for PerformanceTracker in cogs.ai_core.core.performance."""

    def test_init_creates_default_metrics(self):
        """Test initialization creates default metric categories."""
        from cogs.ai_core.core.performance import PerformanceTracker

        tracker = PerformanceTracker()

        assert "rag_search" in tracker._metrics
        assert "api_call" in tracker._metrics
        assert "streaming" in tracker._metrics
        assert "post_process" in tracker._metrics
        assert "total" in tracker._metrics
        assert "context_build" in tracker._metrics
        assert "response_send" in tracker._metrics

    def test_record_timing(self):
        """Test recording timing adds to list."""
        from cogs.ai_core.core.performance import PerformanceTracker

        tracker = PerformanceTracker()
        tracker.record_timing("api_call", 0.5)

        assert len(tracker._metrics["api_call"]) == 1
        assert tracker._metrics["api_call"][0] == 0.5

    def test_record_timing_new_step(self):
        """Test recording timing for new step creates list."""
        from cogs.ai_core.core.performance import PerformanceTracker

        tracker = PerformanceTracker()
        tracker.record_timing("custom_step", 1.0)

        assert "custom_step" in tracker._metrics
        assert tracker._metrics["custom_step"] == [1.0]

    def test_record_timing_respects_max_samples(self):
        """Test recording respects max samples limit."""
        from cogs.ai_core.core.performance import PerformanceTracker
        from cogs.ai_core.data.constants import PERFORMANCE_SAMPLES_MAX

        tracker = PerformanceTracker()

        # Add more than max samples
        for i in range(PERFORMANCE_SAMPLES_MAX + 10):
            tracker.record_timing("api_call", float(i))

        assert len(tracker._metrics["api_call"]) == PERFORMANCE_SAMPLES_MAX

    def test_get_stats_empty(self):
        """Test get_stats with no data."""
        from cogs.ai_core.core.performance import PerformanceTracker

        tracker = PerformanceTracker()
        stats = tracker.get_stats()

        assert stats["api_call"]["count"] == 0
        assert stats["api_call"]["avg_ms"] == 0

    def test_get_stats_with_data(self):
        """Test get_stats with recorded data."""
        from cogs.ai_core.core.performance import PerformanceTracker

        tracker = PerformanceTracker()
        tracker.record_timing("api_call", 0.1)
        tracker.record_timing("api_call", 0.2)
        tracker.record_timing("api_call", 0.3)

        stats = tracker.get_stats()

        assert stats["api_call"]["count"] == 3
        assert stats["api_call"]["avg_ms"] == 200.0  # (100+200+300)/3 = 200
        assert stats["api_call"]["min_ms"] == 100.0
        assert stats["api_call"]["max_ms"] == 300.0

    def test_get_step_stats(self):
        """Test get_step_stats for specific step."""
        from cogs.ai_core.core.performance import PerformanceTracker

        tracker = PerformanceTracker()
        tracker.record_timing("streaming", 0.5)
        tracker.record_timing("streaming", 1.0)

        stats = tracker.get_step_stats("streaming")

        assert stats["count"] == 2
        assert stats["avg_ms"] == 750.0  # (500+1000)/2 = 750

    def test_get_step_stats_unknown_step(self):
        """Test get_step_stats for unknown step."""
        from cogs.ai_core.core.performance import PerformanceTracker

        tracker = PerformanceTracker()
        stats = tracker.get_step_stats("nonexistent")

        assert stats["count"] == 0
        assert stats["avg_ms"] == 0

    def test_clear_metrics_all(self):
        """Test clearing all metrics."""
        from cogs.ai_core.core.performance import PerformanceTracker

        tracker = PerformanceTracker()
        tracker.record_timing("api_call", 0.1)
        tracker.record_timing("streaming", 0.2)

        tracker.clear_metrics()

        assert tracker._metrics["api_call"] == []
        assert tracker._metrics["streaming"] == []

    def test_clear_metrics_specific_step(self):
        """Test clearing specific step metrics."""
        from cogs.ai_core.core.performance import PerformanceTracker

        tracker = PerformanceTracker()
        tracker.record_timing("api_call", 0.1)
        tracker.record_timing("streaming", 0.2)

        tracker.clear_metrics("api_call")

        assert tracker._metrics["api_call"] == []
        assert tracker._metrics["streaming"] == [0.2]

    def test_get_summary_with_data(self):
        """Test get_summary with recorded data."""
        from cogs.ai_core.core.performance import PerformanceTracker

        tracker = PerformanceTracker()
        tracker.record_timing("api_call", 0.1)

        summary = tracker.get_summary()

        assert "📊 Performance Summary:" in summary
        assert "api_call" in summary

    def test_get_summary_empty(self):
        """Test get_summary with no data."""
        from cogs.ai_core.core.performance import PerformanceTracker

        tracker = PerformanceTracker()
        summary = tracker.get_summary()

        assert "No performance data available" in summary


class TestRequestDeduplicator:
    """Tests for RequestDeduplicator class."""

    def test_init(self):
        """Test initialization."""
        from cogs.ai_core.core.performance import RequestDeduplicator

        dedup = RequestDeduplicator()
        assert dedup._pending_requests == {}

    def test_is_duplicate_false(self):
        """Test is_duplicate returns False for new request."""
        from cogs.ai_core.core.performance import RequestDeduplicator

        dedup = RequestDeduplicator()
        result = dedup.is_duplicate("new_key")

        assert result is False

    def test_is_duplicate_true(self):
        """Test is_duplicate returns True for existing request."""
        from cogs.ai_core.core.performance import RequestDeduplicator

        dedup = RequestDeduplicator()
        dedup.add_request("existing_key")

        result = dedup.is_duplicate("existing_key")

        assert result is True

    def test_add_request(self):
        """Test adding a request."""
        from cogs.ai_core.core.performance import RequestDeduplicator

        dedup = RequestDeduplicator()
        dedup.add_request("test_key")

        assert "test_key" in dedup._pending_requests

    def test_remove_request(self):
        """Test removing a request."""
        from cogs.ai_core.core.performance import RequestDeduplicator

        dedup = RequestDeduplicator()
        dedup.add_request("test_key")
        dedup.remove_request("test_key")

        assert "test_key" not in dedup._pending_requests

    def test_remove_request_nonexistent(self):
        """Test removing nonexistent request doesn't error."""
        from cogs.ai_core.core.performance import RequestDeduplicator

        dedup = RequestDeduplicator()
        dedup.remove_request("nonexistent")  # Should not raise

    def test_cleanup_removes_old_requests(self):
        """Test cleanup removes old requests."""
        import time

        from cogs.ai_core.core.performance import RequestDeduplicator

        dedup = RequestDeduplicator()
        # Manually set old timestamp
        dedup._pending_requests["old_key"] = time.time() - 120  # 2 minutes ago
        dedup._pending_requests["new_key"] = time.time()

        cleaned = dedup.cleanup(max_age=60.0)

        assert cleaned == 1
        assert "old_key" not in dedup._pending_requests
        assert "new_key" in dedup._pending_requests

    def test_get_pending_count(self):
        """Test getting pending count."""
        from cogs.ai_core.core.performance import RequestDeduplicator

        dedup = RequestDeduplicator()
        dedup.add_request("key1")
        dedup.add_request("key2")

        assert dedup.get_pending_count() == 2

    def test_generate_key(self):
        """Test generating request key."""
        from cogs.ai_core.core.performance import RequestDeduplicator

        key = RequestDeduplicator.generate_key(123, 456, "Hello world")

        assert "123" in key
        assert "456" in key
        assert ":" in key

    def test_generate_key_empty_message(self):
        """Test generating key with empty message."""
        from cogs.ai_core.core.performance import RequestDeduplicator

        key = RequestDeduplicator.generate_key(123, 456, "")

        assert isinstance(key, str)
        assert "123" in key

    def test_generate_key_long_message(self):
        """Test generating key with long message uses only first 100 chars."""
        from cogs.ai_core.core.performance import RequestDeduplicator

        long_msg = "A" * 200
        key1 = RequestDeduplicator.generate_key(123, 456, long_msg)
        key2 = RequestDeduplicator.generate_key(123, 456, long_msg[:100])

        # Should produce same key since only first 100 chars used
        assert key1 == key2


class TestCorePerformanceSingletons:
    """Tests for module-level singletons."""

    def test_performance_tracker_singleton(self):
        """Test performance_tracker singleton exists."""
        from cogs.ai_core.core.performance import performance_tracker

        assert performance_tracker is not None

    def test_request_deduplicator_singleton(self):
        """Test request_deduplicator singleton exists."""
        from cogs.ai_core.core.performance import request_deduplicator

        assert request_deduplicator is not None
