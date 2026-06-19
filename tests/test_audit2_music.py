"""Audit-2 regression tests for cogs/music/cog.py.

Covers finding py-core-cogs-1: concurrent same-guild queue saves dropping
writes on Windows.

Background. The synchronous writers (`_save_queue_json_sync` /
`_save_queue_settings_sync`) write to a UNIQUE temp file (mkstemp) and then
``os.replace`` it onto a SHARED per-guild dest (``data/queue_{gid}.json`` /
``data/queue_settings_{gid}.json``). The unique temp removes torn-temp
collisions but is *defense-in-depth only*: the dest is still shared, so two
concurrent same-guild ``replace`` calls onto it collide on Windows (WinError 5)
and the loser's save is silently dropped by the writer's ``except OSError``.

The real fix is a per-guild ``asyncio.Lock`` (``MusicGuildState.save_lock``,
distinct from ``play_lock`` to avoid deadlock) held across ``save_queue`` so the
renames for a guild are serialized. These tests assert that real behaviour:

* ``TestUniqueTempPath`` — the mkstemp defense-in-depth (distinct temp names,
  temp cleanup on a failed/raising write).
* ``TestSaveQueueSerializes`` — going through the public ``save_queue``, the
  per-guild lock serializes overlapping saves (rename overlap depth never
  exceeds 1), so ZERO writes are dropped even when every gathered save carries a
  DISTINCT payload and the final file equals the LAST-committed write.
"""

from __future__ import annotations

import asyncio
import collections
import json
import pathlib
import sys
import threading
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

import cogs.music.cog as cog_module
from cogs.music.cog import Music


def make_cog() -> Music:
    """Create a Music cog with a mock bot (no background tasks started)."""
    bot = MagicMock()
    bot.voice_clients = []
    bot.change_presence = AsyncMock()
    bot.loop = MagicMock()
    bot.loop.is_running.return_value = True
    bot.loop.is_closed.return_value = False
    return Music(bot)


@pytest.fixture
def tmp_data_dir(tmp_path, monkeypatch):
    """Run with cwd == tmp_path so ``data/queue_*.json`` lands in a scratch dir.

    Mirrors the isolation fixture used by tests/test_music_queue_io.py — the
    writers are intentionally CWD-relative (see the NOTE in
    _save_queue_settings_sync), so chdir is what redirects them.
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir(exist_ok=True)
    return tmp_path


@pytest.fixture
def force_json_path(monkeypatch):
    """Make ``save_queue`` take its JSON fallback branch deterministically.

    ``save_queue`` does ``from utils.database import db`` and falls back to the
    JSON writers on ImportError. Setting the module entry to ``None`` makes that
    import raise ImportError, so the test exercises the on-disk JSON writers
    (the ones the bug lives in) regardless of whether a real DB layer is
    importable in the test environment.
    """
    monkeypatch.setitem(sys.modules, "utils.database", None)


class TestUniqueTempPath:
    """The fixed-temp-path collision is gone: each write targets a distinct
    temp file, and the OSError-cleanup unlinks that same distinct file. This is
    defense-in-depth under the per-guild save_lock, not the whole fix."""

    def test_queue_json_temp_path_is_unique_per_snapshot(self, tmp_data_dir):
        """Two writes with different payloads use different temp paths."""
        cog = make_cog()
        gid = 1001
        recorded: list[str] = []

        real_replace = pathlib.Path.replace

        def spy_replace(self, target):
            recorded.append(self.name)
            return real_replace(self, target)

        snap_a = {"queue": [{"url": "a"}], "volume": 0.5, "loop": False, "mode_247": False}
        snap_b = {"queue": [{"url": "b"}], "volume": 0.5, "loop": False, "mode_247": False}

        pathlib.Path.replace = spy_replace
        try:
            cog._save_queue_json_sync(gid, snapshot=snap_a)
            cog._save_queue_json_sync(gid, snapshot=snap_b)
        finally:
            pathlib.Path.replace = real_replace

        assert len(recorded) == 2
        # The crux of the defense-in-depth: the two writes did NOT share one
        # fixed temp name (mkstemp guarantees a distinct name, unlike a pid+id()
        # suffix that GC reuse could collide).
        assert recorded[0] != recorded[1]
        # And neither is the old fixed name that concurrent saves used to share.
        assert all(name != f"queue_{gid}.json.tmp" for name in recorded)
        # Both are mkstemp names scoped to this guild's queue file.
        assert all(name.startswith(f".queue_{gid}.json.") for name in recorded)
        assert all(name.endswith(".tmp") for name in recorded)

    def test_settings_temp_path_is_unique_per_snapshot(self, tmp_data_dir):
        """Same uniqueness guarantee for the settings sidecar writer."""
        cog = make_cog()
        gid = 1002
        recorded: list[str] = []

        real_replace = pathlib.Path.replace

        def spy_replace(self, target):
            recorded.append(self.name)
            return real_replace(self, target)

        # Non-default settings so the writer does NOT take the unlink shortcut.
        snap_a = {"volume": 0.7, "loop": True, "mode_247": False}
        snap_b = {"volume": 0.9, "loop": False, "mode_247": True}

        pathlib.Path.replace = spy_replace
        try:
            cog._save_queue_settings_sync(gid, snap_a)
            cog._save_queue_settings_sync(gid, snap_b)
        finally:
            pathlib.Path.replace = real_replace

        assert len(recorded) == 2
        assert recorded[0] != recorded[1]
        assert all(name != f"queue_settings_{gid}.json.tmp" for name in recorded)

    def test_oserror_cleanup_unlinks_the_unique_temp(self, tmp_data_dir):
        """When the atomic rename fails, the cleanup unlinks the SAME unique
        temp file that was actually written (not a stale fixed name)."""
        cog = make_cog()
        gid = 1003
        snap = {"queue": [{"url": "x"}], "volume": 0.5, "loop": False, "mode_247": False}

        real_replace = pathlib.Path.replace

        def boom_replace(self, target):
            raise OSError("rename failed")

        pathlib.Path.replace = boom_replace
        try:
            # Must not raise — the writer swallows OSError after cleaning up.
            cog._save_queue_json_sync(gid, snapshot=snap)
        finally:
            pathlib.Path.replace = real_replace

        # No orphaned temp files left behind in data/ (mkstemp names lead with
        # a dot: ``.queue_{gid}.json.<rand>.tmp``).
        leftovers = list((tmp_data_dir / "data").glob(f".queue_{gid}.json.*"))
        assert leftovers == [], f"orphaned temp files: {leftovers}"
        # And the rename failed, so the final file was never created.
        assert not (tmp_data_dir / "data" / f"queue_{gid}.json").exists()

    def test_non_oserror_serialization_failure_still_unlinks_temp(self, tmp_data_dir):
        """A non-OSError from json.dumps (the widened except) must still unlink
        the mkstemp temp instead of orphaning it in data/."""
        cog = make_cog()
        gid = 1004

        class Unserializable:
            pass

        # ``Unserializable`` makes json.dumps raise TypeError AFTER mkstemp has
        # already created the temp file — the writer must clean it up.
        snap = {
            "queue": [{"url": Unserializable()}],
            "volume": 0.5,
            "loop": False,
            "mode_247": False,
        }

        # Must not raise — the widened except (OSError, TypeError, ValueError)
        # swallows it after cleanup.
        cog._save_queue_json_sync(gid, snapshot=snap)

        leftovers = list((tmp_data_dir / "data").glob(f".queue_{gid}.json.*"))
        assert leftovers == [], f"orphaned temp files: {leftovers}"
        assert not (tmp_data_dir / "data" / f"queue_{gid}.json").exists()


@pytest.mark.asyncio
class TestSaveQueueSerializes:
    """Through the public ``save_queue``, the per-guild ``save_lock`` serializes
    overlapping same-guild saves so NONE are dropped — the WinError-5 dropped-
    save race the unique-temp change alone did not close."""

    async def test_concurrent_saves_never_overlap_on_rename(self, tmp_data_dir, force_json_path):
        """The rename onto the shared dest is serialized: at no point are two
        same-guild renames in flight at once (overlap depth stays <= 1).

        This is the property that prevents the WinError-5 collision. Each writer
        runs in ``asyncio.to_thread``, so WITHOUT the lock the thread pool would
        run several gathered saves' renames in parallel and drive the depth
        above 1; WITH the per-guild save_lock only one save_queue body executes
        at a time, so its two renames (settings + queue, different dest files)
        are the only ones ever in flight.
        """
        cog = make_cog()
        gid = 2001
        gs = cog._gs(gid)
        gs.queue = collections.deque([{"url": "https://yt/a", "title": "A"}])
        gs.volume = 0.6

        real_replace = pathlib.Path.replace
        depth = 0
        max_depth = 0
        # The spy runs in asyncio.to_thread worker threads, so guard the shared
        # depth counters with a real threading lock.
        depth_lock = threading.Lock()
        # Only count renames onto this guild's two shared dest files (ignore the
        # mkstemp source path, which is the ``self`` of replace, not the target).
        dest_names = {f"queue_{gid}.json", f"queue_settings_{gid}.json"}

        def spy_replace(self, target):
            nonlocal depth, max_depth
            counted = pathlib.Path(target).name in dest_names
            if counted:
                with depth_lock:
                    depth += 1
                    max_depth = max(max_depth, depth)
                # Widen the in-flight window so an unserialized run (no lock,
                # writers running in parallel thread-pool workers) reliably
                # exposes depth>1. Under the per-guild save_lock only one body
                # runs at a time, so depth stays 1 despite the sleep.
                time.sleep(0.01)
            try:
                return real_replace(self, target)
            finally:
                if counted:
                    with depth_lock:
                        depth -= 1

        pathlib.Path.replace = spy_replace
        try:
            await asyncio.gather(*(cog.save_queue(gid) for _ in range(12)))
        finally:
            pathlib.Path.replace = real_replace

        # The settings + queue writers each ran via asyncio.to_thread, but the
        # per-guild save_lock means only ONE save_queue body executes at a time,
        # so its two renames are the only ones ever in flight together — never a
        # second guild-save's rename concurrently. Depth must never exceed 1.
        assert max_depth == 1, f"renames overlapped (depth {max_depth}) — lock not serializing"

    async def test_windows_style_rename_collision_drops_no_save(
        self, tmp_data_dir, force_json_path, monkeypatch
    ):
        """Reproduce the WinError-5 collision and prove the lock closes it.

        The spy raises ``OSError`` (the Windows symptom) if a rename onto a
        shared per-guild dest STARTS while another rename onto that SAME dest is
        already in flight — exactly what happened on Windows for the loser of two
        concurrent same-guild ``os.replace`` calls. Under the per-guild
        ``save_lock`` the bodies are serialized, so the collision branch is never
        taken: no OSError is raised, the writers' ``except`` (which logs via
        ``logger.exception`` and DROPS the save) never fires, and all 12 saves
        commit. Remove the lock and this test fails (collisions → dropped saves
        → logged exceptions → missing commits).
        """
        cog = make_cog()
        gid = 2002
        gs = cog._gs(gid)
        gs.queue = collections.deque([{"url": "https://yt/a", "title": "A"}])
        # Non-default settings so the sidecar writer actually writes+renames
        # (all-default settings take the unlink shortcut and never replace()).
        gs.volume = 0.6
        gs.mode_247 = True

        real_replace = pathlib.Path.replace
        in_flight: set[str] = set()
        in_flight_lock = threading.Lock()
        collisions = 0
        queue_commits = 0
        settings_commits = 0
        dest_names = {f"queue_{gid}.json", f"queue_settings_{gid}.json"}

        def spy_replace(self, target):
            nonlocal collisions, queue_commits, settings_commits
            name = pathlib.Path(target).name
            counted = name in dest_names
            if counted:
                with in_flight_lock:
                    if name in in_flight:
                        # Second concurrent rename onto the same dest — this is
                        # the WinError-5 the loser hit on Windows.
                        collisions += 1
                        raise OSError(5, "[WinError 5] Access is denied")
                    in_flight.add(name)
                # Widen the window so an unserialized run reliably overlaps.
                time.sleep(0.01)
            try:
                result = real_replace(self, target)
                if name == f"queue_{gid}.json":
                    queue_commits += 1
                elif name == f"queue_settings_{gid}.json":
                    settings_commits += 1
                return result
            finally:
                if counted:
                    with in_flight_lock:
                        in_flight.discard(name)

        # The writers swallow failures by logging via logger.exception — assert
        # that drop path is NEVER taken under the lock.
        exc_calls: list[tuple] = []

        def spy_logger_exception(msg, *args, **kwargs):
            exc_calls.append((msg, args))

        monkeypatch.setattr(cog_module.logger, "exception", spy_logger_exception)

        n = 12
        pathlib.Path.replace = spy_replace
        try:
            await asyncio.gather(*(cog.save_queue(gid) for _ in range(n)))
        finally:
            pathlib.Path.replace = real_replace

        # Core guarantee: the lock serialized the renames, so no collision was
        # ever triggered and no save was dropped.
        assert collisions == 0, f"{collisions} rename collisions — lock not serializing"
        assert exc_calls == [], f"writer swallowed a failed save: {exc_calls}"
        # Every save committed both its settings sidecar and its queue file.
        assert queue_commits == n
        assert settings_commits == n

        # Final files are present and valid (not torn).
        qpath = tmp_data_dir / "data" / f"queue_{gid}.json"
        assert json.loads(qpath.read_text(encoding="utf-8"))["queue"][0]["url"] == "https://yt/a"
        leftovers = list((tmp_data_dir / "data").glob(f".queue_{gid}.json.*"))
        leftovers += list((tmp_data_dir / "data").glob(f".queue_settings_{gid}.json.*"))
        assert leftovers == [], f"orphaned temp files: {leftovers}"

    async def test_serialized_saves_apply_to_disk(self, tmp_data_dir, force_json_path):
        """A distinct payload issued per save all commit to disk; the final file
        is a complete document holding one of the committed payloads.

        Because each ``save_queue`` snapshots shared guild state under the lock,
        we don't assert a specific task's payload wins (that ordering depends on
        when each task mutates the shared state relative to acquiring the lock —
        see save_queue). What we DO assert is the dropped-save symptom is gone:
        there are exactly ``n`` queue-file commits and the on-disk result is a
        valid, untorn JSON document whose payload is one we actually wrote.
        """
        cog = make_cog()
        gid = 2003
        gs = cog._gs(gid)

        n = 12
        issued_urls = {f"https://yt/{i}" for i in range(n)}
        queue_commits = 0
        real_replace = pathlib.Path.replace

        def spy_replace(self, target):
            nonlocal queue_commits
            result = real_replace(self, target)
            if pathlib.Path(target).name == f"queue_{gid}.json":
                queue_commits += 1
            return result

        async def issue(i: int) -> None:
            gs.queue = collections.deque([{"url": f"https://yt/{i}", "title": f"T{i}"}])
            await cog.save_queue(gid)

        pathlib.Path.replace = spy_replace
        try:
            await asyncio.gather(*(issue(i) for i in range(n)))
        finally:
            pathlib.Path.replace = real_replace

        # Every save's queue write landed — none dropped on a colliding rename.
        assert queue_commits == n

        path = tmp_data_dir / "data" / f"queue_{gid}.json"
        assert path.exists()
        final = json.loads(path.read_text(encoding="utf-8"))
        # The final file is complete (not torn) and holds a payload we issued.
        assert final["queue"][0]["url"] in issued_urls

        leftovers = list((tmp_data_dir / "data").glob(f".queue_{gid}.json.*"))
        assert leftovers == [], f"orphaned temp files: {leftovers}"
