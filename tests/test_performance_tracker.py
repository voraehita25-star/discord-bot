# pylint: disable=protected-access
"""
Unit Tests for Performance Tracker Module.
Tests timing, percentiles, and trending.
"""

from __future__ import annotations

import time

import pytest


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
            time.sleep(0.015)  # 15ms - slightly longer for timing tolerance

        stats = tracker.get_stats("test_op")
        assert stats["count"] == 1
        assert stats["avg_ms"] >= 9  # At least 9ms (with tolerance for Windows timing)

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
