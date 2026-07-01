"""Tests for the standalone unrestricted-channel registry.

The unrestricted-mode logic used to live in ``processing/guardrails.py``; after
that module was removed it moved to ``processing/unrestricted.py``. Persistence
is isolated to a temp file via monkeypatch so these never touch real data.
"""

from __future__ import annotations

import json


def _fresh_module(tmp_path, monkeypatch):
    """Return the unrestricted module with persistence pointed at a temp file."""
    import cogs.ai_core.processing.unrestricted as u

    monkeypatch.setattr(u, "_UNRESTRICTED_FILE", tmp_path / "unrestricted_channels.json")
    monkeypatch.setattr(u, "unrestricted_channels", set())
    monkeypatch.delenv("AI_UNRESTRICTED_ALL", raising=False)
    return u


class TestUnrestrictedRegistry:
    def test_available_flag_true(self):
        from cogs.ai_core import imports

        assert imports.UNRESTRICTED_AVAILABLE is True

    def test_unset_channel_is_not_unrestricted(self, tmp_path, monkeypatch):
        u = _fresh_module(tmp_path, monkeypatch)
        assert u.is_unrestricted(999) is False

    def test_set_then_unset_roundtrip(self, tmp_path, monkeypatch):
        u = _fresh_module(tmp_path, monkeypatch)
        assert u.set_unrestricted(999, True) is True  # persisted to temp file
        assert u.is_unrestricted(999) is True
        assert u.set_unrestricted(999, False) is True
        assert u.is_unrestricted(999) is False

    def test_persistence_file_written(self, tmp_path, monkeypatch):
        u = _fresh_module(tmp_path, monkeypatch)
        u.set_unrestricted(42, True)
        target = tmp_path / "unrestricted_channels.json"
        assert target.exists()
        data = json.loads(target.read_text(encoding="utf-8"))
        assert 42 in data["channels"]

    def test_global_override_forces_all_channels(self, tmp_path, monkeypatch):
        u = _fresh_module(tmp_path, monkeypatch)
        monkeypatch.setenv("AI_UNRESTRICTED_ALL", "1")
        assert u.unrestricted_all_enabled() is True
        assert u.is_unrestricted(123456) is True  # any channel, even if not set
        monkeypatch.setenv("AI_UNRESTRICTED_ALL", "0")
        assert u.unrestricted_all_enabled() is False
        assert u.is_unrestricted(123456) is False

    def test_failed_newer_write_blocks_older_reordered_write(self, tmp_path, monkeypatch):
        u = _fresh_module(tmp_path, monkeypatch)
        # Model a reordered write: a newer v5 snapshot ENTERED the write path and
        # FAILED (attempted advanced to 5, saved still 0). A stale v1 write must not
        # persist afterward, or a turned-off channel would re-enable after restart.
        monkeypatch.setattr(u, "_unrestricted_version", 0)
        monkeypatch.setattr(u, "_unrestricted_attempted_version", 5)
        monkeypatch.setattr(u, "_unrestricted_saved_version", 0)
        result = u.set_unrestricted(777, True)  # my_version == 1
        assert result is False  # honest: nothing >= our version reached disk
        # The stale {777} snapshot must NOT have been persisted (channel not re-enabled).
        assert not (tmp_path / "unrestricted_channels.json").exists()

    def test_stale_write_after_successful_newer_reports_true(self, tmp_path, monkeypatch):
        u = _fresh_module(tmp_path, monkeypatch)
        # Model a reordered write where the newer v5 snapshot SUCCEEDED (saved == 5).
        # A stale v1 write is skipped but honestly reports True — a newer state has
        # already subsumed ours on disk.
        monkeypatch.setattr(u, "_unrestricted_version", 0)
        monkeypatch.setattr(u, "_unrestricted_attempted_version", 5)
        monkeypatch.setattr(u, "_unrestricted_saved_version", 5)
        result = u.set_unrestricted(888, True)  # my_version == 1
        assert result is True  # a newer state subsumed ours
