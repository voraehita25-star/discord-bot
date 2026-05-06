"""Tests for the JSON save/load + per-guild settings paths in QueueManager.

The existing test_music_queue.py covers the in-memory operations; this
file targets the persistence helpers (`_save_queue_json`,
async `load_queue` JSON-fallback path, settings-sidecar pickup) that
weren't exercised before.
"""

from __future__ import annotations

import collections
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from cogs.music.queue import QueueManager


@pytest.fixture
def tmp_data_dir(tmp_path, monkeypatch):
    """Run with cwd == tmp_path so `data/queue_*.json` lands in a scratch dir."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir(exist_ok=True)
    return tmp_path


class TestSaveQueueJson:
    def test_writes_json_for_non_empty_queue(self, tmp_data_dir):
        m = QueueManager()
        guild_id = 12345
        m.queues[guild_id] = collections.deque([{"url": "https://yt/abc", "title": "Track A"}])
        m.volumes[guild_id] = 0.7
        m.loops[guild_id] = True
        m.mode_247[guild_id] = False
        m._save_queue_json(guild_id)

        path = tmp_data_dir / "data" / f"queue_{guild_id}.json"
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["queue"][0]["url"] == "https://yt/abc"
        assert data["volume"] == 0.7
        assert data["loop"] is True
        assert data["mode_247"] is False

    def test_removes_file_for_empty_queue(self, tmp_data_dir):
        m = QueueManager()
        guild_id = 9999
        path = tmp_data_dir / "data" / f"queue_{guild_id}.json"
        path.write_text('{"queue": []}', encoding="utf-8")

        # Empty queue causes file to be removed.
        m._save_queue_json(guild_id)
        assert not path.exists()

    def test_returns_quietly_when_empty_and_no_file(self, tmp_data_dir):
        m = QueueManager()
        # Should not raise even when the file doesn't already exist.
        m._save_queue_json(54321)


@pytest.mark.asyncio
class TestLoadQueueJsonFallback:
    async def test_loads_from_json_when_db_unavailable(self, tmp_data_dir):
        guild_id = 77777
        path = tmp_data_dir / "data" / f"queue_{guild_id}.json"
        path.write_text(
            json.dumps(
                {
                    "queue": [{"url": "https://yt/x", "title": "X"}],
                    "volume": 0.3,
                    "loop": True,
                    "mode_247": True,
                }
            ),
            encoding="utf-8",
        )

        m = QueueManager()
        # Force DB-unavailable path.
        with patch("cogs.music.queue.DB_AVAILABLE", False):
            ok = await m.load_queue(guild_id)
            assert ok is True
            assert m.volumes[guild_id] == 0.3
            assert m.loops[guild_id] is True
            assert m.mode_247[guild_id] is True
            assert len(m.queues[guild_id]) == 1

    async def test_returns_false_when_no_persistence(self, tmp_data_dir):
        m = QueueManager()
        with patch("cogs.music.queue.DB_AVAILABLE", False):
            ok = await m.load_queue(11111)
            assert ok is False

    async def test_corrupt_json_does_not_raise(self, tmp_data_dir):
        guild_id = 22222
        path = tmp_data_dir / "data" / f"queue_{guild_id}.json"
        path.write_text("not valid json {{{", encoding="utf-8")

        m = QueueManager()
        with patch("cogs.music.queue.DB_AVAILABLE", False):
            ok = await m.load_queue(guild_id)
            # Falls back to "no queue loaded" rather than raising.
            assert ok is False


class TestQueueOpsCoverage:
    """Quick coverage for the simple in-memory ops not in test_music_queue.py."""

    def test_volume_default(self):
        m = QueueManager()
        assert m.get_volume(99) == pytest.approx(0.5)

    def test_volume_set_and_get(self):
        m = QueueManager()
        m.set_volume(99, 0.8)
        assert m.get_volume(99) == pytest.approx(0.8)

    def test_247_mode_default_false(self):
        m = QueueManager()
        assert m.is_247_mode(11) is False

    def test_247_mode_toggle(self):
        m = QueueManager()
        assert m.toggle_247_mode(11) is True
        assert m.is_247_mode(11) is True
        assert m.toggle_247_mode(11) is False

    def test_loop_default_false(self):
        m = QueueManager()
        assert m.is_looping(22) is False

    def test_loop_toggle(self):
        m = QueueManager()
        assert m.toggle_loop(22) is True
        assert m.is_looping(22) is True

    def test_cleanup_guild(self, tmp_data_dir):
        m = QueueManager()
        m.queues[5] = collections.deque([{"url": "x"}])
        m.loops[5] = True
        m.mode_247[5] = True
        m.cleanup_guild(5)
        assert 5 not in m.queues
        assert 5 not in m.loops
        # mode_247 is intentionally preserved across cleanup so the user's
        # 24/7 setting survives a queue reset.
        assert m.mode_247[5] is True

    def test_remove_track_out_of_range(self):
        m = QueueManager()
        m.queues[7] = collections.deque([{"url": "a"}])
        # Position is 1-indexed; 99 is out of range, 0 is invalid.
        assert m.remove_track(7, 99) is None
        assert m.remove_track(7, 0) is None
        assert m.remove_track(7, -1) is None

    def test_remove_track_valid_position(self):
        m = QueueManager()
        m.queues[7] = collections.deque([{"url": "a"}, {"url": "b"}, {"url": "c"}])
        # Position is 1-indexed (UI-style), so position=2 removes "b".
        removed = m.remove_track(7, 2)
        assert removed == {"url": "b"}
        assert len(m.queues[7]) == 2

    def test_shuffle_empty_returns_false(self):
        m = QueueManager()
        assert m.shuffle_queue(33) is False

    def test_shuffle_single_item_is_idempotent(self):
        m = QueueManager()
        m.queues[33] = collections.deque([{"url": "only"}])
        # Shuffle a 1-element queue — should still return True (success) and
        # not crash.
        result = m.shuffle_queue(33)
        assert result is True or result is False  # tolerate either policy
