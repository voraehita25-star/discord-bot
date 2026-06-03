"""Unit tests for Music Queue Manager."""

import pytest

from cogs.music.queue import QueueManager


class TestQueueManager:
    """Tests for QueueManager class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.manager = QueueManager()
        self.guild_id = 123456789

    def test_get_queue_creates_empty(self):
        """Test that get_queue creates an empty queue for new guild."""
        queue = self.manager.get_queue(self.guild_id)
        assert len(queue) == 0
        assert self.guild_id in self.manager.queues

    def test_add_to_queue(self):
        """Test adding tracks to queue."""
        track1 = {"title": "Song 1", "url": "http://example.com/1"}
        track2 = {"title": "Song 2", "url": "http://example.com/2"}

        pos1 = self.manager.add_to_queue(self.guild_id, track1)
        pos2 = self.manager.add_to_queue(self.guild_id, track2)

        assert pos1 == 1
        assert pos2 == 2
        assert len(self.manager.get_queue(self.guild_id)) == 2

    def test_get_next(self):
        """Test getting next track from queue."""
        track1 = {"title": "Song 1"}
        track2 = {"title": "Song 2"}
        self.manager.add_to_queue(self.guild_id, track1)
        self.manager.add_to_queue(self.guild_id, track2)

        next_track = self.manager.get_next(self.guild_id)
        assert next_track == track1
        assert len(self.manager.get_queue(self.guild_id)) == 1

    def test_get_next_empty_queue(self):
        """Test get_next returns None for empty queue."""
        assert self.manager.get_next(self.guild_id) is None

    def test_peek_next(self):
        """Test peeking at next track without removing."""
        track = {"title": "Song 1"}
        self.manager.add_to_queue(self.guild_id, track)

        peeked = self.manager.peek_next(self.guild_id)
        assert peeked == track
        assert len(self.manager.get_queue(self.guild_id)) == 1  # Still there

    def test_peek_next_empty(self):
        """Test peek_next returns None for empty queue."""
        assert self.manager.peek_next(self.guild_id) is None

    def test_clear_queue(self):
        """Test clearing the queue."""
        self.manager.add_to_queue(self.guild_id, {"title": "Song 1"})
        self.manager.add_to_queue(self.guild_id, {"title": "Song 2"})

        count = self.manager.clear_queue(self.guild_id)
        assert count == 2
        assert len(self.manager.get_queue(self.guild_id)) == 0

    def test_shuffle_queue(self):
        """Test shuffling the queue."""
        for i in range(10):
            self.manager.add_to_queue(self.guild_id, {"title": f"Song {i}"})

        original = self.manager.get_queue(self.guild_id).copy()
        result = self.manager.shuffle_queue(self.guild_id)

        assert result is True
        assert len(self.manager.get_queue(self.guild_id)) == 10
        # Highly unlikely to be in same order
        assert self.manager.get_queue(self.guild_id) != original or len(original) < 2

    def test_shuffle_queue_too_small(self):
        """Test shuffle returns False for queue with < 2 items."""
        self.manager.add_to_queue(self.guild_id, {"title": "Song 1"})
        assert self.manager.shuffle_queue(self.guild_id) is False

    def test_remove_track(self):
        """Test removing a track by position."""
        self.manager.add_to_queue(self.guild_id, {"title": "Song 1"})
        self.manager.add_to_queue(self.guild_id, {"title": "Song 2"})
        self.manager.add_to_queue(self.guild_id, {"title": "Song 3"})

        removed = self.manager.remove_track(self.guild_id, 2)  # 1-indexed
        assert removed["title"] == "Song 2"
        assert len(self.manager.get_queue(self.guild_id)) == 2

    def test_remove_track_invalid_position(self):
        """Test remove_track with invalid position."""
        self.manager.add_to_queue(self.guild_id, {"title": "Song 1"})

        assert self.manager.remove_track(self.guild_id, 0) is None
        assert self.manager.remove_track(self.guild_id, 5) is None

    def test_loop_toggle(self):
        """Test loop toggle functionality."""
        assert self.manager.is_looping(self.guild_id) is False

        result = self.manager.toggle_loop(self.guild_id)
        assert result is True
        assert self.manager.is_looping(self.guild_id) is True

        result = self.manager.toggle_loop(self.guild_id)
        assert result is False

    def test_volume_operations(self):
        """Test volume get/set operations."""
        assert self.manager.get_volume(self.guild_id) == 0.5  # Default

        self.manager.set_volume(self.guild_id, 1.0)
        assert self.manager.get_volume(self.guild_id) == 1.0

        # Test clamping
        self.manager.set_volume(self.guild_id, 5.0)
        assert self.manager.get_volume(self.guild_id) == 2.0

        self.manager.set_volume(self.guild_id, -1.0)
        assert self.manager.get_volume(self.guild_id) == 0.0

    def test_247_mode_toggle(self):
        """Test 24/7 mode toggle."""
        assert self.manager.is_247_mode(self.guild_id) is False

        result = self.manager.toggle_247_mode(self.guild_id)
        assert result is True
        assert self.manager.is_247_mode(self.guild_id) is True

    def test_cleanup_guild(self):
        """Test cleanup preserves 24/7 mode."""
        self.manager.add_to_queue(self.guild_id, {"title": "Song 1"})
        self.manager.toggle_loop(self.guild_id)
        self.manager.toggle_247_mode(self.guild_id)
        self.manager.current_track[self.guild_id] = {"title": "Current"}

        self.manager.cleanup_guild(self.guild_id)

        assert self.guild_id not in self.manager.queues
        assert self.guild_id not in self.manager.loops
        assert self.guild_id not in self.manager.current_track
        # 24/7 mode should persist
        assert self.manager.is_247_mode(self.guild_id) is True


class TestQueuePersistence:
    """Tests for queue persistence (JSON fallback)."""

    def setup_method(self):
        """Set up test fixtures."""
        self.manager = QueueManager()
        self.guild_id = 987654321

    def test_save_queue_json_fallback(self):
        """Test JSON save as fallback when database not available."""

        self.manager.add_to_queue(self.guild_id, {"title": "Test Song"})
        self.manager.set_volume(self.guild_id, 0.8)

        # This test just ensures no exceptions are raised
        # Actual file operations would require mocking
        self.manager._save_queue_json(self.guild_id)


# ======================================================================
# Merged from test_music_queue_extended.py
# ======================================================================


class TestQueueManagerInit:
    """Tests for QueueManager initialization."""

    def test_init_empty_queues(self):
        """Test initialization creates empty queues dict."""
        from cogs.music.queue import QueueManager

        manager = QueueManager()
        assert manager.queues == {}

    def test_init_empty_loops(self):
        """Test initialization creates empty loops dict."""
        from cogs.music.queue import QueueManager

        manager = QueueManager()
        assert manager.loops == {}

    def test_init_empty_volumes(self):
        """Test initialization creates empty volumes dict."""
        from cogs.music.queue import QueueManager

        manager = QueueManager()
        assert manager.volumes == {}


class TestGetQueue:
    """Tests for QueueManager.get_queue method."""

    def test_get_queue_creates_new(self):
        """Test get_queue creates new queue for guild."""
        from cogs.music.queue import QueueManager

        manager = QueueManager()
        queue = manager.get_queue(123456)

        assert len(queue) == 0
        assert 123456 in manager.queues

    def test_get_queue_returns_existing(self):
        """Test get_queue returns existing queue."""
        from cogs.music.queue import QueueManager

        manager = QueueManager()
        manager.queues[123456] = [{"title": "Test"}]

        queue = manager.get_queue(123456)
        assert len(queue) == 1


class TestAddToQueue:
    """Tests for QueueManager.add_to_queue method."""

    def test_add_single_track(self):
        """Test adding single track."""
        from cogs.music.queue import QueueManager

        manager = QueueManager()
        track = {"title": "Test Song", "url": "http://example.com"}

        position = manager.add_to_queue(123456, track)

        assert position == 1
        assert len(manager.get_queue(123456)) == 1

    def test_add_multiple_tracks(self):
        """Test adding multiple tracks returns correct positions."""
        from cogs.music.queue import QueueManager

        manager = QueueManager()

        pos1 = manager.add_to_queue(123456, {"title": "Song 1"})
        pos2 = manager.add_to_queue(123456, {"title": "Song 2"})
        pos3 = manager.add_to_queue(123456, {"title": "Song 3"})

        assert pos1 == 1
        assert pos2 == 2
        assert pos3 == 3


class TestGetNext:
    """Tests for QueueManager.get_next method."""

    def test_get_next_empty_queue(self):
        """Test get_next returns None for empty queue."""
        from cogs.music.queue import QueueManager

        manager = QueueManager()
        result = manager.get_next(123456)

        assert result is None

    def test_get_next_removes_track(self):
        """Test get_next removes and returns track."""
        from cogs.music.queue import QueueManager

        manager = QueueManager()
        manager.add_to_queue(123456, {"title": "Song 1"})
        manager.add_to_queue(123456, {"title": "Song 2"})

        result = manager.get_next(123456)

        assert result["title"] == "Song 1"
        assert len(manager.get_queue(123456)) == 1


class TestPeekNext:
    """Tests for QueueManager.peek_next method."""

    def test_peek_next_empty_queue(self):
        """Test peek_next returns None for empty queue."""
        from cogs.music.queue import QueueManager

        manager = QueueManager()
        result = manager.peek_next(123456)

        assert result is None

    def test_peek_next_does_not_remove(self):
        """Test peek_next doesn't remove track."""
        from cogs.music.queue import QueueManager

        manager = QueueManager()
        manager.add_to_queue(123456, {"title": "Song 1"})

        result = manager.peek_next(123456)

        assert result["title"] == "Song 1"
        assert len(manager.get_queue(123456)) == 1


class TestClearQueue:
    """Tests for QueueManager.clear_queue method."""

    def test_clear_empty_queue(self):
        """Test clearing empty queue returns 0."""
        from cogs.music.queue import QueueManager

        manager = QueueManager()
        count = manager.clear_queue(123456)

        assert count == 0

    def test_clear_queue_returns_count(self):
        """Test clearing queue returns count."""
        from cogs.music.queue import QueueManager

        manager = QueueManager()
        manager.add_to_queue(123456, {"title": "Song 1"})
        manager.add_to_queue(123456, {"title": "Song 2"})
        manager.add_to_queue(123456, {"title": "Song 3"})

        count = manager.clear_queue(123456)

        assert count == 3
        assert len(manager.get_queue(123456)) == 0


class TestShuffleQueue:
    """Tests for QueueManager.shuffle_queue method."""

    def test_shuffle_empty_queue(self):
        """Test shuffling empty queue returns False."""
        from cogs.music.queue import QueueManager

        manager = QueueManager()
        result = manager.shuffle_queue(123456)

        assert result is False

    def test_shuffle_single_track(self):
        """Test shuffling single track returns False."""
        from cogs.music.queue import QueueManager

        manager = QueueManager()
        manager.add_to_queue(123456, {"title": "Song 1"})

        result = manager.shuffle_queue(123456)

        assert result is False

    def test_shuffle_multiple_tracks(self):
        """Test shuffling multiple tracks returns True."""
        from cogs.music.queue import QueueManager

        manager = QueueManager()
        for i in range(10):
            manager.add_to_queue(123456, {"title": f"Song {i}"})

        result = manager.shuffle_queue(123456)

        assert result is True


class TestRemoveTrack:
    """Tests for QueueManager.remove_track method."""

    def test_remove_valid_position(self):
        """Test removing track at valid position."""
        from cogs.music.queue import QueueManager

        manager = QueueManager()
        manager.add_to_queue(123456, {"title": "Song 1"})
        manager.add_to_queue(123456, {"title": "Song 2"})
        manager.add_to_queue(123456, {"title": "Song 3"})

        removed = manager.remove_track(123456, 2)  # 1-indexed

        assert removed["title"] == "Song 2"
        assert len(manager.get_queue(123456)) == 2

    def test_remove_invalid_position_zero(self):
        """Test removing at position 0 returns None."""
        from cogs.music.queue import QueueManager

        manager = QueueManager()
        manager.add_to_queue(123456, {"title": "Song 1"})

        removed = manager.remove_track(123456, 0)

        assert removed is None

    def test_remove_invalid_position_too_high(self):
        """Test removing at too high position returns None."""
        from cogs.music.queue import QueueManager

        manager = QueueManager()
        manager.add_to_queue(123456, {"title": "Song 1"})

        removed = manager.remove_track(123456, 99)

        assert removed is None


class TestLooping:
    """Tests for QueueManager looping methods."""

    def test_is_looping_default_false(self):
        """Test is_looping returns False by default."""
        from cogs.music.queue import QueueManager

        manager = QueueManager()
        assert manager.is_looping(123456) is False

    def test_toggle_loop(self):
        """Test toggle_loop switches state."""
        from cogs.music.queue import QueueManager

        manager = QueueManager()

        result1 = manager.toggle_loop(123456)
        assert result1 is True
        assert manager.is_looping(123456) is True

        result2 = manager.toggle_loop(123456)
        assert result2 is False
        assert manager.is_looping(123456) is False


# ======================================================================
# load_queue DB-path cap regression tests
# ======================================================================


class TestLoadQueueDbCap:
    """Regression tests for the MAX_QUEUE_SIZE cap on the DB load path.

    The DB branch of ``load_queue`` previously had no cap, so a DB that
    returned more than MAX_QUEUE_SIZE valid rows would put >500 tracks in
    memory, silently violating the documented invariant. These tests mock
    ``db.load_music_queue`` (the async DB layer) to return controlled row
    sets and assert the in-memory deque is capped/kept correctly.
    """

    @pytest.fixture
    def isolate_cwd(self, tmp_path, monkeypatch):
        """Run with cwd == tmp_path (with an empty data/) so no settings

        sidecar (``data/queue_*.json``) exists to interfere with the
        DB-path assertions.
        """
        monkeypatch.chdir(tmp_path)
        (tmp_path / "data").mkdir(exist_ok=True)
        return tmp_path

    @pytest.mark.asyncio
    async def test_caps_to_max_when_db_returns_more(self, isolate_cwd):
        """DB returning > MAX_QUEUE_SIZE valid rows is capped to MAX_QUEUE_SIZE."""
        from unittest.mock import AsyncMock, patch

        from cogs.music.queue import MAX_QUEUE_SIZE, QueueManager

        guild_id = 4242
        oversized_rows = [
            {"url": f"https://yt/{i}", "title": f"Track {i}"} for i in range(MAX_QUEUE_SIZE + 50)
        ]
        mock_db = AsyncMock()
        mock_db.load_music_queue = AsyncMock(return_value=oversized_rows)

        m = QueueManager()
        with patch("cogs.music.queue.DB_AVAILABLE", True), patch("cogs.music.queue.db", mock_db):
            ok = await m.load_queue(guild_id)

        assert ok is True
        # The in-memory deque must be capped, NOT the full oversized set.
        assert len(m.queues[guild_id]) == MAX_QUEUE_SIZE
        mock_db.load_music_queue.assert_awaited_once_with(guild_id)

    @pytest.mark.asyncio
    async def test_keeps_all_when_db_returns_fewer(self, isolate_cwd):
        """DB returning < MAX_QUEUE_SIZE valid rows keeps every row."""
        from unittest.mock import AsyncMock, patch

        from cogs.music.queue import MAX_QUEUE_SIZE, QueueManager

        guild_id = 4343
        n_rows = 5
        assert n_rows < MAX_QUEUE_SIZE
        rows = [{"url": f"https://yt/{i}", "title": f"Track {i}"} for i in range(n_rows)]
        mock_db = AsyncMock()
        mock_db.load_music_queue = AsyncMock(return_value=rows)

        m = QueueManager()
        with patch("cogs.music.queue.DB_AVAILABLE", True), patch("cogs.music.queue.db", mock_db):
            ok = await m.load_queue(guild_id)

        assert ok is True
        assert len(m.queues[guild_id]) == n_rows
        # Order and content preserved.
        loaded = list(m.queues[guild_id])
        assert loaded[0]["url"] == "https://yt/0"
        assert loaded[-1]["url"] == f"https://yt/{n_rows - 1}"


# ======================================================================
# Full-coverage tests appended (region: ALL)
# ======================================================================


class TestImportFallback:
    """Cover the module-level ``except ImportError`` fallback (lines 22-24)."""

    def test_import_error_sets_db_unavailable(self):
        """When ``utils.database`` can't be imported, DB_AVAILABLE is False and db is None."""
        import builtins
        import importlib

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "utils.database" or name.startswith("utils.database."):
                raise ImportError("simulated missing utils.database")
            return real_import(name, *args, **kwargs)

        import cogs.music.queue as queue_mod

        try:
            builtins.__import__ = fake_import
            reloaded = importlib.reload(queue_mod)
            # The except branch must have run.
            assert reloaded.DB_AVAILABLE is False
            assert reloaded.db is None
        finally:
            # Restore the real import and reload the module back to its
            # normal (DB-available) state so other tests are unaffected.
            builtins.__import__ = real_import
            importlib.reload(queue_mod)


class TestQueueFull:
    """Cover MAX_QUEUE_SIZE guard branches (lines 71-72, 78)."""

    def test_add_to_full_queue_returns_minus_one(self):
        from cogs.music.queue import MAX_QUEUE_SIZE, QueueManager

        manager = QueueManager()
        gid = 555
        # Fill exactly to the cap.
        for i in range(MAX_QUEUE_SIZE):
            assert manager.add_to_queue(gid, {"title": f"s{i}", "url": f"u{i}"}) == i + 1
        # One more must be rejected with -1.
        assert manager.add_to_queue(gid, {"title": "overflow", "url": "over"}) == -1
        assert len(manager.get_queue(gid)) == MAX_QUEUE_SIZE

    def test_is_queue_full_true_and_false(self):
        from cogs.music.queue import MAX_QUEUE_SIZE, QueueManager

        manager = QueueManager()
        gid = 556
        assert manager.is_queue_full(gid) is False
        for i in range(MAX_QUEUE_SIZE):
            manager.add_to_queue(gid, {"title": f"s{i}", "url": f"u{i}"})
        assert manager.is_queue_full(gid) is True


class TestSetVolumeNonFinite:
    """Cover the NaN/inf rejection branch in set_volume (line 149)."""

    def test_nan_volume_becomes_one(self):
        from cogs.music.queue import QueueManager

        manager = QueueManager()
        gid = 600
        manager.set_volume(gid, float("nan"))
        # NaN is replaced by 1.0 then clamped to [0.0, 2.0] → 1.0
        assert manager.get_volume(gid) == 1.0

    def test_positive_inf_volume_becomes_one(self):
        from cogs.music.queue import QueueManager

        manager = QueueManager()
        gid = 601
        manager.set_volume(gid, float("inf"))
        assert manager.get_volume(gid) == 1.0

    def test_negative_inf_volume_becomes_one(self):
        from cogs.music.queue import QueueManager

        manager = QueueManager()
        gid = 602
        manager.set_volume(gid, float("-inf"))
        assert manager.get_volume(gid) == 1.0


class TestSaveQueue:
    """Cover the async save_queue paths (lines 179-206)."""

    @pytest.fixture
    def isolate_cwd(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "data").mkdir(exist_ok=True)
        return tmp_path

    async def test_save_queue_db_with_tracks(self, isolate_cwd):
        """DB available + non-empty queue → db.save_music_queue called."""
        from unittest.mock import AsyncMock, patch

        from cogs.music.queue import QueueManager

        gid = 700
        manager = QueueManager()
        manager.add_to_queue(gid, {"title": "Song", "url": "http://x/1"})
        mock_db = AsyncMock()
        with patch("cogs.music.queue.DB_AVAILABLE", True), patch("cogs.music.queue.db", mock_db):
            await manager.save_queue(gid)
        mock_db.save_music_queue.assert_awaited_once()
        args = mock_db.save_music_queue.await_args.args
        assert args[0] == gid
        assert len(args[1]) == 1
        # Empty path not taken.
        mock_db.clear_music_queue.assert_not_awaited()

    async def test_save_queue_db_empty_clears(self, isolate_cwd):
        """DB available + empty queue → db.clear_music_queue called (lines 201-203)."""
        from unittest.mock import AsyncMock, patch

        from cogs.music.queue import QueueManager

        gid = 701
        manager = QueueManager()
        # Ensure an (empty) deque exists so snapshot is [].
        manager.get_queue(gid)
        mock_db = AsyncMock()
        with patch("cogs.music.queue.DB_AVAILABLE", True), patch("cogs.music.queue.db", mock_db):
            await manager.save_queue(gid)
        mock_db.clear_music_queue.assert_awaited_once_with(gid)
        mock_db.save_music_queue.assert_not_awaited()

    async def test_save_queue_json_fallback_when_db_unavailable(self, isolate_cwd):
        """DB unavailable → JSON fallback via asyncio.to_thread (lines 185-199)."""
        import json
        from pathlib import Path
        from unittest.mock import patch

        from cogs.music.queue import QueueManager

        gid = 702
        manager = QueueManager()
        manager.add_to_queue(gid, {"title": "JsonSong", "url": "http://x/json"})
        manager.set_volume(gid, 0.7)
        manager.toggle_loop(gid)
        manager.toggle_247_mode(gid)

        with patch("cogs.music.queue.DB_AVAILABLE", False), patch("cogs.music.queue.db", None):
            await manager.save_queue(gid)

        out = Path(f"data/queue_{gid}.json")
        assert out.exists()
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["queue"][0]["title"] == "JsonSong"
        assert data["volume"] == 0.7
        assert data["loop"] is True
        assert data["mode_247"] is True

    async def test_save_queue_db_is_none_uses_json(self, isolate_cwd):
        """DB_AVAILABLE True but db is None → still takes JSON fallback (line 185 second clause)."""
        import json
        from pathlib import Path
        from unittest.mock import patch

        from cogs.music.queue import QueueManager

        gid = 703
        manager = QueueManager()
        manager.add_to_queue(gid, {"title": "NoneDb", "url": "http://x/nonedb"})

        with patch("cogs.music.queue.DB_AVAILABLE", True), patch("cogs.music.queue.db", None):
            await manager.save_queue(gid)

        out = Path(f"data/queue_{gid}.json")
        assert out.exists()
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["queue"][0]["title"] == "NoneDb"


class TestSaveQueueJsonSnapshot:
    """Cover _save_queue_json snapshot branch (line 227) and error path (257-261)."""

    @pytest.fixture
    def isolate_cwd(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "data").mkdir(exist_ok=True)
        return tmp_path

    def test_explicit_snapshot_is_used(self, isolate_cwd):
        """Passing queue_snapshot uses it (line 227) instead of self.queues."""
        import json
        from pathlib import Path

        from cogs.music.queue import QueueManager

        gid = 800
        manager = QueueManager()
        # self.queues is empty for gid, but explicit snapshot has a track.
        snapshot = [{"title": "Snap", "url": "http://x/snap"}]
        manager._save_queue_json(gid, snapshot, 1.2, True, True)

        out = Path(f"data/queue_{gid}.json")
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["queue"][0]["title"] == "Snap"
        assert data["volume"] == 1.2
        assert data["loop"] is True
        assert data["mode_247"] is True

    def test_oswrite_failure_cleans_temp(self, isolate_cwd):
        """Write failure triggers OSError except + temp cleanup (lines 257-261)."""
        from pathlib import Path
        from unittest.mock import patch

        from cogs.music.queue import QueueManager

        gid = 801
        manager = QueueManager()
        snapshot = [{"title": "Boom", "url": "http://x/boom"}]

        # Make write_text raise OSError so the except branch runs. unlink in
        # the cleanup is allowed (suppressed) — temp file never created, so
        # unlink will raise FileNotFoundError which is an OSError, suppressed.
        with patch.object(Path, "write_text", side_effect=OSError("disk full")):
            # Should not raise.
            manager._save_queue_json(gid, snapshot, 0.5, False, False)

        # No json file should have been produced.
        assert not Path(f"data/queue_{gid}.json").exists()

    def test_empty_snapshot_unlinks_existing(self, isolate_cwd):
        """Empty queue with an existing file removes it (lines 230-234)."""
        from pathlib import Path

        from cogs.music.queue import QueueManager

        gid = 802
        out = Path(f"data/queue_{gid}.json")
        out.write_text("{}", encoding="utf-8")
        assert out.exists()

        manager = QueueManager()
        manager._save_queue_json(gid, [], 0.5, False, False)
        assert not out.exists()

    def test_empty_snapshot_no_file_noop(self, isolate_cwd):
        """Empty queue with no existing file is a no-op (line 230 false branch)."""
        from pathlib import Path

        from cogs.music.queue import QueueManager

        gid = 803
        manager = QueueManager()
        manager._save_queue_json(gid, [], 0.5, False, False)
        assert not Path(f"data/queue_{gid}.json").exists()


class TestLoadQueueSettingsSidecar:
    """Cover the DB-path settings sidecar reading (lines 291-301)."""

    @pytest.fixture
    def isolate_cwd(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "data").mkdir(exist_ok=True)
        return tmp_path

    async def test_sidecar_settings_applied(self, isolate_cwd):
        """A valid settings sidecar updates volume/loop/mode_247 (lines 291-299)."""
        import json
        from pathlib import Path
        from unittest.mock import AsyncMock, patch

        from cogs.music.queue import QueueManager

        gid = 900
        Path(f"data/queue_{gid}.json").write_text(
            json.dumps({"volume": 1.5, "loop": True, "mode_247": True}),
            encoding="utf-8",
        )
        mock_db = AsyncMock()
        mock_db.load_music_queue = AsyncMock(return_value=[{"url": "http://x/1", "title": "T"}])
        manager = QueueManager()
        with patch("cogs.music.queue.DB_AVAILABLE", True), patch("cogs.music.queue.db", mock_db):
            ok = await manager.load_queue(gid)

        assert ok is True
        assert manager.get_volume(gid) == 1.5
        assert manager.is_looping(gid) is True
        assert manager.is_247_mode(gid) is True

    async def test_sidecar_unreadable_uses_defaults(self, isolate_cwd):
        """A corrupt settings sidecar is caught and defaults retained (lines 300-305)."""
        from pathlib import Path
        from unittest.mock import AsyncMock, patch

        from cogs.music.queue import QueueManager

        gid = 901
        Path(f"data/queue_{gid}.json").write_text("{ this is not json", encoding="utf-8")
        mock_db = AsyncMock()
        mock_db.load_music_queue = AsyncMock(return_value=[{"url": "http://x/1", "title": "T"}])
        manager = QueueManager()
        with patch("cogs.music.queue.DB_AVAILABLE", True), patch("cogs.music.queue.db", mock_db):
            ok = await manager.load_queue(gid)

        assert ok is True
        # Defaults retained because the sidecar parse failed.
        assert manager.get_volume(gid) == 0.5
        assert manager.is_looping(gid) is False

    async def test_sidecar_non_dict_ignored(self, isolate_cwd):
        """A sidecar that parses to a non-dict is ignored (line 296 false branch)."""
        import json
        from pathlib import Path
        from unittest.mock import AsyncMock, patch

        from cogs.music.queue import QueueManager

        gid = 902
        Path(f"data/queue_{gid}.json").write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        mock_db = AsyncMock()
        mock_db.load_music_queue = AsyncMock(return_value=[{"url": "http://x/1", "title": "T"}])
        manager = QueueManager()
        with patch("cogs.music.queue.DB_AVAILABLE", True), patch("cogs.music.queue.db", mock_db):
            ok = await manager.load_queue(gid)

        assert ok is True
        # No settings applied since parsed value isn't a dict.
        assert manager.get_volume(gid) == 0.5


class TestLoadQueueJsonFallback:
    """Cover the JSON fallback path of load_queue (lines 314-374)."""

    @pytest.fixture
    def isolate_cwd(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "data").mkdir(exist_ok=True)
        return tmp_path

    async def test_no_file_returns_false(self, isolate_cwd):
        """No DB and no JSON file → False (lines 314-316)."""
        from unittest.mock import patch

        from cogs.music.queue import QueueManager

        gid = 1000
        manager = QueueManager()
        with patch("cogs.music.queue.DB_AVAILABLE", False), patch("cogs.music.queue.db", None):
            ok = await manager.load_queue(gid)
        assert ok is False

    async def test_db_returns_empty_falls_through_to_json(self, isolate_cwd):
        """DB available but returns empty → falls to JSON branch.

        When the JSON file is also absent this returns False (covers the
        DB-empty fall-through into the JSON section, lines 314-316).
        """
        from unittest.mock import AsyncMock, patch

        from cogs.music.queue import QueueManager

        gid = 1001
        mock_db = AsyncMock()
        mock_db.load_music_queue = AsyncMock(return_value=[])
        manager = QueueManager()
        with patch("cogs.music.queue.DB_AVAILABLE", True), patch("cogs.music.queue.db", mock_db):
            ok = await manager.load_queue(gid)
        assert ok is False

    async def test_invalid_format_returns_false(self, isolate_cwd):
        """JSON file that isn't dict-with-queue-list → False (lines 323-325)."""
        import json
        from pathlib import Path
        from unittest.mock import patch

        from cogs.music.queue import QueueManager

        gid = 1002
        Path(f"data/queue_{gid}.json").write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        manager = QueueManager()
        with patch("cogs.music.queue.DB_AVAILABLE", False), patch("cogs.music.queue.db", None):
            ok = await manager.load_queue(gid)
        assert ok is False

    async def test_queue_list_but_empty(self, isolate_cwd):
        """Valid dict with empty queue list → returns False (line 327 false branch)."""
        import json
        from pathlib import Path
        from unittest.mock import patch

        from cogs.music.queue import QueueManager

        gid = 1003
        Path(f"data/queue_{gid}.json").write_text(
            json.dumps({"queue": [], "volume": 0.9}), encoding="utf-8"
        )
        manager = QueueManager()
        with patch("cogs.music.queue.DB_AVAILABLE", False), patch("cogs.music.queue.db", None):
            ok = await manager.load_queue(gid)
        assert ok is False

    async def test_queue_all_invalid_items_returns_false(self, isolate_cwd):
        """A queue list with no valid (dict+url) items → False (lines 336-339)."""
        import json
        from pathlib import Path
        from unittest.mock import patch

        from cogs.music.queue import QueueManager

        gid = 1004
        Path(f"data/queue_{gid}.json").write_text(
            json.dumps({"queue": [{"title": "no url"}, "string", 5, {"url": ""}]}),
            encoding="utf-8",
        )
        manager = QueueManager()
        with patch("cogs.music.queue.DB_AVAILABLE", False), patch("cogs.music.queue.db", None):
            ok = await manager.load_queue(gid)
        assert ok is False
        # File left alone for future recovery.
        assert Path(f"data/queue_{gid}.json").exists()

    async def test_json_load_no_db_keeps_file(self, isolate_cwd):
        """Valid JSON, no DB → load into memory and keep the file (lines 340-344, 362-370)."""
        import json
        from pathlib import Path
        from unittest.mock import patch

        from cogs.music.queue import QueueManager

        gid = 1005
        Path(f"data/queue_{gid}.json").write_text(
            json.dumps(
                {
                    "queue": [{"url": "http://x/a", "title": "A"}],
                    "volume": 1.1,
                    "loop": True,
                    "mode_247": True,
                }
            ),
            encoding="utf-8",
        )
        manager = QueueManager()
        with patch("cogs.music.queue.DB_AVAILABLE", False), patch("cogs.music.queue.db", None):
            ok = await manager.load_queue(gid)

        assert ok is True
        assert len(manager.queues[gid]) == 1
        assert manager.get_volume(gid) == 1.1
        assert manager.is_looping(gid) is True
        assert manager.is_247_mode(gid) is True
        # No DB → JSON file kept.
        assert Path(f"data/queue_{gid}.json").exists()

    async def test_json_load_with_db_migrates_and_deletes(self, isolate_cwd):
        """Valid JSON + DB → migrate to DB and delete JSON (lines 349-361)."""
        import json
        from pathlib import Path
        from unittest.mock import AsyncMock, patch

        from cogs.music.queue import QueueManager

        gid = 1006
        Path(f"data/queue_{gid}.json").write_text(
            json.dumps({"queue": [{"url": "http://x/b", "title": "B"}]}),
            encoding="utf-8",
        )
        mock_db = AsyncMock()
        # DB load returns empty so we fall to the JSON path; save succeeds.
        mock_db.load_music_queue = AsyncMock(return_value=[])
        mock_db.save_music_queue = AsyncMock(return_value=True)
        manager = QueueManager()
        with patch("cogs.music.queue.DB_AVAILABLE", True), patch("cogs.music.queue.db", mock_db):
            ok = await manager.load_queue(gid)

        assert ok is True
        assert len(manager.queues[gid]) == 1
        mock_db.save_music_queue.assert_awaited_once()
        # JSON deleted after successful migration.
        assert not Path(f"data/queue_{gid}.json").exists()

    async def test_json_load_with_db_save_fails_keeps_file(self, isolate_cwd):
        """Valid JSON + DB but save raises → keep JSON, return True (lines 352-358)."""
        import json
        from pathlib import Path
        from unittest.mock import AsyncMock, patch

        from cogs.music.queue import QueueManager

        gid = 1007
        Path(f"data/queue_{gid}.json").write_text(
            json.dumps({"queue": [{"url": "http://x/c", "title": "C"}]}),
            encoding="utf-8",
        )
        mock_db = AsyncMock()
        mock_db.load_music_queue = AsyncMock(return_value=[])
        mock_db.save_music_queue = AsyncMock(side_effect=RuntimeError("db down"))
        manager = QueueManager()
        with patch("cogs.music.queue.DB_AVAILABLE", True), patch("cogs.music.queue.db", mock_db):
            ok = await manager.load_queue(gid)

        assert ok is True
        assert len(manager.queues[gid]) == 1
        # JSON kept as fallback because migration failed.
        assert Path(f"data/queue_{gid}.json").exists()

    async def test_json_load_read_raises_returns_false(self, isolate_cwd):
        """A read/parse exception in the JSON branch → caught, returns False (lines 371-374)."""
        import json
        from pathlib import Path
        from unittest.mock import patch

        from cogs.music.queue import QueueManager

        gid = 1008
        # Valid structure so we get past existence + format checks, then
        # force json.loads to blow up to exercise the outer except handler.
        Path(f"data/queue_{gid}.json").write_text(
            json.dumps({"queue": [{"url": "http://x/d", "title": "D"}]}),
            encoding="utf-8",
        )
        manager = QueueManager()
        with (
            patch("cogs.music.queue.DB_AVAILABLE", False),
            patch("cogs.music.queue.db", None),
            patch("cogs.music.queue.json.loads", side_effect=ValueError("boom")),
        ):
            ok = await manager.load_queue(gid)
        assert ok is False
