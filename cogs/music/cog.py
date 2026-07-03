# pylint: disable=too-many-lines
# pyright: reportAttributeAccessIssue=false
# pyright: reportArgumentType=false
"""
Music Cog Module for Discord Bot.
Provides music playback functionality with YouTube and Spotify support.

Note: Type checker warnings for VoiceProtocol/VoiceClient are suppressed
because discord.py's type stubs don't fully reflect runtime behavior.
"""

from __future__ import annotations

import asyncio
import collections
import contextlib
import itertools
import json
import logging
import math
import os
import random
import tempfile
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import discord
import yt_dlp
from discord.ext import commands

from cogs.ai_core.data.constants import CREATOR_ID
from utils.media import get_ffmpeg_executable
from utils.media.ytdl_source import YTDLSource, get_ffmpeg_options

from .utils import Colors, Emojis, create_progress_bar, format_duration
from .views import MusicControlView  # Import from views module to avoid duplication

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from discord.ext.commands import Bot, Context


@dataclass
class MusicGuildState:
    """Per-guild music state, consolidating 11 scattered dicts into one object."""

    queue: collections.deque[dict[str, Any]] = field(default_factory=collections.deque)
    loop: bool = False
    current_track: dict[str, Any] | None = None
    fixing: bool = False
    # If ``cleanup_guild_data`` arrives while ``fixing=True`` we can't run
    # the cleanup safely — fix is mid-mutation. Setting this flag lets the
    # ``fix`` finally-block trigger a deferred cleanup after it releases.
    cleanup_pending: bool = False
    pause_start: float | None = None
    play_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # Serializes save_queue() for this guild. Distinct from play_lock on
    # purpose: save_queue is reachable from play/cleanup paths, so sharing
    # play_lock would deadlock. mkstemp gives each write a unique SOURCE temp
    # file, but the DEST (data/queue_{gid}.json, data/queue_settings_{gid}.json)
    # is shared — two concurrent same-guild os.replace() onto it still collide
    # on Windows (WinError 5) and the loser's save gets dropped by the OSError
    # catch. This lock serializes the renames per guild so no save is lost.
    save_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    volume: float = 0.5
    auto_disconnect_task: asyncio.Task | None = None
    mode_247: bool = False
    last_text_channel: int | None = None
    # True once load_queue() has been attempted for this guild — the
    # persisted queue is restored lazily on first activity after a restart.
    queue_loaded: bool = False


class Music(commands.Cog):
    """Music Cog - Provides music playback with YouTube and Spotify support."""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot
        # Consolidated per-guild state accessed via self._gs(guild_id)
        self._guild_states: dict[int, MusicGuildState] = {}

        # Lazy import to avoid circular dependency with spotify_handler
        from cogs.spotify_handler import SpotifyHandler

        self.spotify: SpotifyHandler = SpotifyHandler(bot)
        self.auto_disconnect_delay: int = 180  # 3 minutes
        self._temp_cleanup_task: asyncio.Task | None = None
        self._queue_autosave_task: asyncio.Task | None = None
        self._queue_save_pending: set[int] = set()  # guild IDs with pending saves
        # on_ready fires on every reconnect; the startup cache sweep should
        # only run once per process so we don't churn the disk on flaky
        # Discord gateway connections.
        self._cleaned_temp_once: bool = False

    async def cog_load(self) -> None:
        """Called when the cog is loaded. Start background tasks."""
        self._temp_cleanup_task = asyncio.create_task(self._periodic_temp_cleanup())
        self._queue_autosave_task = asyncio.create_task(self._periodic_queue_save())

    async def _periodic_temp_cleanup(self) -> None:
        """Periodically clean up stale files in temp directory.

        Skips files registered as ``current_track`` for any guild — a
        paused/looping track holding a file beyond the 1-hour staleness
        window was previously deleted out from under ffmpeg, breaking
        the playback on next seek (Linux: continues from inode; Windows:
        PermissionError on the next spawn).
        """
        # CWD-relative on purpose — must match safe_delete's temp_root and
        # ytdl_source's download outtmpl (see safe_delete for the full rationale).
        temp_dir = Path("temp")
        stale_threshold = 3600  # 1 hour

        def _collect_in_use() -> set[str]:
            """Snapshot every guild's current_track file path."""
            in_use: set[str] = set()
            # list() snapshot is atomic against a concurrent _gs()/setdefault
            # insert on the AudioPlayer after-callback thread, so this loop-thread
            # read can't raise "dictionary changed size during iteration".
            for gs in list(self._guild_states.values()):
                track_info = gs.current_track
                if track_info and "filename" in track_info:
                    try:
                        in_use.add(str(Path(track_info["filename"]).resolve()))
                    except (OSError, ValueError):
                        # Reserved names / non-existent paths shouldn't
                        # poison the in-use set — just skip them.
                        continue
            return in_use

        def _cleanup_sync(in_use: set[str]) -> int:
            if not temp_dir.exists():
                return 0
            now = time.time()
            cleaned = 0
            for f in temp_dir.iterdir():
                if not f.is_file():
                    continue
                try:
                    abs_path = str(f.resolve())
                except (OSError, ValueError):
                    continue
                # Never delete files actively held by playback. ffmpeg
                # keeps the FD open on POSIX so it would keep playing,
                # but a subsequent loop/seek would fail; on Windows the
                # unlink itself fails noisily.
                if abs_path in in_use:
                    continue
                try:
                    if (now - f.stat().st_mtime) > stale_threshold:
                        f.unlink()
                        cleaned += 1
                except (PermissionError, OSError):
                    pass
            return cleaned

        while True:
            try:
                await asyncio.sleep(1800)  # Run every 30 minutes
                # Snapshot must happen on the loop thread — ``_guild_states``
                # mutation lives there. Then hand the snapshot to the worker
                # for the slow filesystem walk.
                in_use_now = _collect_in_use()
                cleaned = await asyncio.to_thread(_cleanup_sync, in_use_now)
                if cleaned:
                    logger.info("🧹 Temp cleanup: removed %d stale files", cleaned)
            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.debug("Temp cleanup error: %s", e)

    async def _periodic_queue_save(self) -> None:
        """Periodically save all active queues to persist them across restarts."""
        # Add a small per-process jitter to the 5-minute tick so a fleet
        # of bots restarted at the same time (rolling deploy, blue/green
        # cutover) doesn't all hit the DB at exactly the same wall-clock
        # boundary. ``random.uniform`` keeps the offset small enough that
        # the tick still averages 300s.
        while True:
            try:
                jitter = random.uniform(-15.0, 15.0)
                await asyncio.sleep(300 + jitter)
                # Save only guilds whose queue actually changed since the
                # last save — the previous version walked every guild_state
                # every tick, which on a 1000-guild bot meant 1000 redundant
                # DB writes every 5 minutes for queues that hadn't moved.
                # The _queue_save_pending set is populated by mutators
                # (enqueue, skip, etc.) and cleared after we drain it.
                if not self._queue_save_pending:
                    continue
                pending = list(self._queue_save_pending)
                self._queue_save_pending.clear()
                saved = 0
                for guild_id in pending:
                    gs = self._guild_states.get(guild_id)
                    if gs is None:
                        continue
                    # save_queue handles the empty-queue case (clears DB).
                    # Isolate each guild: without a per-iteration guard, a single
                    # guild's transient DB error would propagate to the outer
                    # handler and abandon the rest of the batch — and because the
                    # pending markers were already cleared above, those guilds'
                    # queue changes would be silently lost until a later mutator
                    # re-marked them. Re-queue a failed guild so it retries next
                    # tick instead of being dropped.
                    try:
                        await self.save_queue(guild_id)
                        saved += 1
                    except Exception as e:
                        self._queue_save_pending.add(guild_id)
                        logger.warning("Queue auto-save failed for guild %s: %s", guild_id, e)
                if saved:
                    logger.info("💾 Auto-saved queues for %d guilds", saved)
            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.warning("Queue auto-save error: %s", e)

    def _schedule_queue_save(self, guild_id: int) -> None:
        """Mark a guild's queue as needing save (debounced by periodic task)."""
        self._queue_save_pending.add(guild_id)

    # ----- Guild state helpers -----

    def _gs(self, guild_id: int) -> MusicGuildState:
        """Get or create per-guild state.

        Called from BOTH the main event loop AND the audio after-callback
        thread. The check-then-set pattern used to race: two simultaneous
        first-time lookups (e.g. ``play`` from a command at the same time
        as an after-callback) would both miss the ``not in`` and create
        independent ``MusicGuildState`` objects, dropping one's queue /
        play_lock entirely. ``setdefault`` is dict-level atomic, fixing
        the race at the cost of one needless allocation on already-known
        guilds — cheap at Discord scale.
        """
        existing = self._guild_states.get(guild_id)
        if existing is not None:
            return existing
        return self._guild_states.setdefault(guild_id, MusicGuildState())

    def _safe_run_coroutine(self, coro) -> None:
        """Safely run a coroutine in the bot's event loop.

        This handles the case where the event loop may be closed during shutdown.
        Uses self.bot.loop which always returns the bot's event loop (needed
        because this method is called from non-async callback threads where
        asyncio.get_event_loop() may return the wrong loop).
        """
        try:
            loop = self.bot.loop
            if loop and loop.is_running() and not loop.is_closed():
                # Attach a done callback so coroutine exceptions don't get
                # silently swallowed by a discarded Future.
                def _on_done(fut):
                    try:
                        fut.result()
                    except Exception as e:
                        logger.warning("safe_run_coroutine error: %s", e)

                future = asyncio.run_coroutine_threadsafe(coro, loop)
                future.add_done_callback(_on_done)
            else:
                # Loop unavailable — close the coroutine object explicitly so
                # shutdown doesn't spray "coroutine ... was never awaited"
                # warnings for the dropped cleanup.
                coro.close()
        except (RuntimeError, AttributeError):
            # Event loop closed or bot shutting down - silently ignore the
            # drop, but still close the un-run coroutine object.
            with contextlib.suppress(Exception):
                coro.close()

    async def cog_unload(self) -> None:
        """Cleanup when cog is unloaded."""
        # Cancel + await temp cleanup task. Without the await, the task
        # is cancelled but discord.py's ``cog_unload`` returns before its
        # except-handler runs, producing "Task was destroyed but it is
        # pending!" warnings and leaving any in-flight cleanup half-done.
        if self._temp_cleanup_task is not None:
            self._temp_cleanup_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._temp_cleanup_task
            self._temp_cleanup_task = None
        # Cancel + await queue auto-save task — same reasoning.
        if self._queue_autosave_task is not None:
            self._queue_autosave_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._queue_autosave_task
            self._queue_autosave_task = None
        # Cancel all auto-disconnect tasks (don't bother awaiting — there
        # are potentially many and they don't hold critical state).
        for gs in list(self._guild_states.values()):
            if gs.auto_disconnect_task is not None:
                gs.auto_disconnect_task.cancel()
        # Save queues before clearing to preserve state across reloads
        for guild_id in list(self._guild_states.keys()):
            try:
                await self.save_queue(guild_id)
            except Exception:
                logger.debug("Failed to save queue for guild %s during unload", guild_id)
        # Disconnect only voice clients in guilds where this cog has state,
        # so we don't tear down voice connections owned by other cogs.
        managed_guild_ids = set(self._guild_states.keys())
        for vc in list(self.bot.voice_clients):
            try:
                # discord.py declares ``voice_clients`` as ``list[VoiceProtocol]``
                # which has no ``.guild``; in practice every entry is a
                # ``VoiceClient`` (subclass) which does. Use ``getattr`` so
                # mypy stays happy and a non-VC subclass (e.g. a custom
                # third-party protocol) is handled gracefully.
                guild = getattr(vc, "guild", None)
                if guild and guild.id in managed_guild_ids:
                    await vc.disconnect(force=True)
            except Exception:
                logger.debug("Failed to disconnect voice client during unload")
        # Cleanup Spotify handler
        if hasattr(self, "spotify") and self.spotify:
            self.spotify.cleanup()
        # Clear all stored data to prevent memory leaks
        self._guild_states.clear()
        logger.info("🎵 Music Cog unloaded - all data cleaned up")

    async def cleanup_guild_data(self, guild_id: int) -> None:
        """Clean up all data for a specific guild."""
        # Defer cleanup if the fix command is in progress (race condition
        # prevention). Mark a sticky flag so the fix-command's finally
        # block can drive the cleanup once it's safe — previously the
        # early-return silently dropped the cleanup forever, leaving the
        # guild's state resident in memory after the bot left the voice
        # channel.
        if guild_id in self._guild_states and self._guild_states[guild_id].fixing:
            self._guild_states[guild_id].cleanup_pending = True
            logger.debug(
                "Deferring cleanup for guild %s - fix command in progress",
                guild_id,
            )
            return

        # Save queue before cleanup for persistence. Guarded — a DB failure
        # must not abort the cleanup below (state removal, task cancel).
        try:
            await self.save_queue(guild_id)
        except Exception as e:
            logger.warning("Queue save during cleanup failed for guild %s: %s", guild_id, e)

        if guild_id in self._guild_states:
            gs = self._guild_states[guild_id]
            # Cancel auto-disconnect task
            if gs.auto_disconnect_task is not None:
                gs.auto_disconnect_task.cancel()
            # Preserve mode_247 setting across cleanup.
            # Avoid the previous ``del`` + ``= MusicGuildState(...)`` pattern:
            # in asyncio a concurrent ``_gs(guild_id)`` (which calls
            # ``setdefault``) between the ``del`` and the reassignment would
            # insert a fresh default state (mode_247=False) that our
            # subsequent assignment then clobbers — or worse, the
            # concurrent call wins and 247 is silently dropped. Building
            # the replacement up front and writing once removes the gap.
            keep_247 = gs.mode_247
            if keep_247:
                self._guild_states[guild_id] = MusicGuildState(mode_247=True)
            else:
                del self._guild_states[guild_id]

    async def cog_before_invoke(self, ctx: commands.Context) -> None:
        """Called before every command - track last used text channel."""
        if ctx.guild:
            self._gs(ctx.guild.id).last_text_channel = ctx.channel.id

    async def save_queue(self, guild_id: int) -> None:
        """Save queue to database for persistence across restarts."""
        gs = self._gs(guild_id)

        # Serialize this guild's saves. The settings/queue writers below each
        # os.replace() onto a SHARED per-guild dest path; mkstemp only makes
        # the temp SOURCE unique, so two concurrent same-guild saves still
        # collide on the rename (WinError 5 on Windows) and the loser is
        # silently dropped by the writer's OSError catch. Holding the per-guild
        # save_lock for the whole body (NOT play_lock — would deadlock) makes
        # the renames sequential per guild so every save lands. A RuntimeError
        # raised below on DB failure still releases the lock via async-with.
        async with gs.save_lock:
            queue = gs.queue

            # Import database only when needed
            try:
                from utils.database import db
            except ImportError:
                # Fallback to JSON if database not available. The queue JSON
                # bundles volume/loop/mode_247, BUT _save_queue_json_sync
                # UNLINKS that file when the queue is empty — so an idle 24/7
                # channel (mode_247 on, no tracks queued) would lose its
                # settings on restart in JSON-only mode. Mirror the DB path and
                # also write the queue-independent settings sidecar so those
                # survive an empty-queue save here too.
                await self._save_queue_settings(guild_id)
                await self._save_queue_json(guild_id)
                return

            # The music_queue DB schema only stores the track list, so volume/
            # loop/mode_247 would otherwise be lost on restart when the DB
            # backend is active (the JSON path persists all four). Mirror those
            # settings to a small dedicated sidecar regardless of DB
            # availability so they survive a restart without a schema migration.
            # mode_247 in particular must persist — losing it makes a 24/7
            # channel auto-disconnect after a restart.
            await self._save_queue_settings(guild_id)

            # db.save_music_queue / clear_music_queue never raise — they catch
            # internally and return False. Raising here on failure is what lets
            # _periodic_queue_save's per-guild retry re-mark the pending flag;
            # ignoring the bool made that retry logic unreachable and logged
            # false success while the queue change was silently lost.
            if not queue:
                # Clear queue from database if empty
                if not await db.clear_music_queue(guild_id):
                    raise RuntimeError(f"clear_music_queue failed for guild {guild_id}")
                return

            # Save to database (convert deque to list for serialization)
            if not await db.save_music_queue(guild_id, list(queue)):
                raise RuntimeError(f"save_music_queue failed for guild {guild_id}")
            logger.info("💾 Saved queue for guild %s (%d tracks) to database", guild_id, len(queue))

    async def _save_queue_settings(self, guild_id: int) -> None:
        """Persist volume/loop/mode_247 to a sidecar (DB-path settings safety).

        The ``music_queue`` DB table only holds the track list, so these
        per-guild playback settings would be lost on restart when the DB
        backend is active. This writes them to a dedicated
        ``data/queue_settings_{guild_id}.json`` file (separate from the
        queue JSON so it doesn't interfere with the JSON-to-DB queue
        migration/unlink logic in ``load_queue``). Read back by
        ``_load_queue_settings``.
        """
        gs = self._gs(guild_id)
        snapshot = {
            "volume": gs.volume,
            "loop": gs.loop,
            "mode_247": gs.mode_247,
        }
        await asyncio.to_thread(self._save_queue_settings_sync, guild_id, snapshot)

    def _save_queue_settings_sync(self, guild_id: int, snapshot: dict) -> None:
        """Synchronous settings-sidecar write (atomic via temp + replace)."""
        try:
            # NOTE: the "data/" queue/settings paths here (and in queue.py) are
            # CWD-relative rather than settings.data_dir. They are internally
            # consistent (the same code writes and reads them), so this only
            # diverges from the project-root anchoring under a non-default
            # launcher CWD. Anchoring to settings.data_dir was deliberately NOT
            # applied: settings is a module-level singleton evaluated at import,
            # immune to the tests' monkeypatch.chdir, so doing so would write
            # test artifacts into the real project data/ and break the
            # persistence tests' tmp-dir isolation (test_music_queue_io.py).
            filepath = Path(f"data/queue_settings_{guild_id}.json")
            # All-default settings carry no information beyond the GuildState
            # constructor defaults (volume 0.5, loop False, mode_247 False),
            # which _load_queue_settings already falls back to when the sidecar
            # is absent. Unlink instead of writing so a guild that reverts to
            # defaults doesn't leave a stale per-guild file behind, mirroring
            # the empty-queue unlink in _save_queue_json_sync.
            if (
                snapshot.get("volume") == 0.5
                and not snapshot.get("loop")
                and not snapshot.get("mode_247")
            ):
                with contextlib.suppress(OSError):
                    if filepath.exists():
                        filepath.unlink()
                return
            filepath.parent.mkdir(parents=True, exist_ok=True)
            # Each write goes to a UNIQUE temp file (mkstemp) in the target dir
            # instead of a single fixed ``.json.tmp``. This is defense-in-depth:
            # it removes torn-temp collisions between overlapping writers. It is
            # NOT sufficient on its own — the DEST (``filepath``) is still shared
            # per guild, so two concurrent same-guild ``replace`` calls onto it
            # can still collide (WinError 5 on Windows) and the loser's save is
            # dropped by the OSError catch below. The actual serialization is
            # done by the per-guild ``save_lock`` held across ``save_queue``;
            # this writer assumes it runs under that lock.
            fd, temp_name = tempfile.mkstemp(
                dir=filepath.parent, prefix=f".{filepath.name}.", suffix=".tmp"
            )
            os.close(fd)  # we reuse the path via write_text, not the raw fd
            temp_path = Path(temp_name)
            temp_path.write_text(
                json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            temp_path.replace(filepath)  # Atomic on POSIX; near-atomic on Windows
        except (OSError, TypeError, ValueError):
            # Catch non-OSError too (e.g. json.dumps choking on a non-
            # serializable value) so the unique mkstemp temp is still unlinked
            # instead of being orphaned in data/.
            logger.exception("Failed to save queue settings for guild %s", guild_id)
            # ``temp_path`` is bound only once mkstemp succeeds; guard NameError
            # so an earlier failure doesn't mask the original error.
            with contextlib.suppress(OSError, NameError):
                if temp_path.exists():
                    temp_path.unlink()

    async def _load_queue_settings(self, guild_id: int) -> None:
        """Restore volume/loop/mode_247 from the settings sidecar, if present.

        Counterpart to ``_save_queue_settings`` — used by the DB load path so
        these settings survive a restart even though the DB only stores the
        track list. Values are validated the same way as the queue-JSON path.
        """
        filepath = Path(f"data/queue_settings_{guild_id}.json")
        if not await asyncio.to_thread(filepath.exists):
            return
        try:
            raw = await asyncio.get_running_loop().run_in_executor(
                None, filepath.read_text, "utf-8"
            )
            data = json.loads(raw)
            if not isinstance(data, dict):
                logger.warning("Invalid queue settings file for guild %s — skipping", guild_id)
                return
            # Clamp volume to the same [0.0, 2.0] range !volume enforces and
            # reject NaN/±inf so a corrupt sidecar can't poison the transformer.
            _loaded_vol = float(data.get("volume", 0.5))
            self._gs(guild_id).volume = (
                max(0.0, min(2.0, _loaded_vol)) if math.isfinite(_loaded_vol) else 0.5
            )
            self._gs(guild_id).loop = bool(data.get("loop", False))
            self._gs(guild_id).mode_247 = bool(data.get("mode_247", False))
        except (OSError, json.JSONDecodeError, ValueError, TypeError):
            logger.exception("Failed to load queue settings for guild %s", guild_id)

    async def _save_queue_json(self, guild_id: int) -> None:
        """Legacy JSON save as fallback. Runs blocking I/O in a thread."""
        # Snapshot guild state on the event-loop thread so the worker thread
        # never touches self._guild_states (which _gs() mutates via setdefault).
        # A concurrent cleanup_guild_data/cog_unload on the loop would otherwise
        # race the worker's unsynchronized dict read/setdefault.
        gs = self._gs(guild_id)
        snapshot = {
            "queue": list(gs.queue),
            "volume": gs.volume,
            "loop": gs.loop,
            "mode_247": gs.mode_247,
        }
        await asyncio.to_thread(self._save_queue_json_sync, guild_id, snapshot)

    def _save_queue_json_sync(self, guild_id: int, snapshot: dict | None = None) -> None:
        """Synchronous JSON save implementation.

        With ``snapshot`` (the production path via ``_save_queue_json``) this
        touches NO shared state — safe in a worker thread. ``snapshot=None``
        falls back to reading via ``_gs`` for direct same-thread callers.
        """
        if snapshot is None:
            gs = self._gs(guild_id)
            snapshot = {
                "queue": list(gs.queue),
                "volume": gs.volume,
                "loop": gs.loop,
                "mode_247": gs.mode_247,
            }
        queue = snapshot["queue"]
        if not queue:
            filepath = Path(f"data/queue_{guild_id}.json")
            if filepath.exists():
                with contextlib.suppress(OSError):
                    filepath.unlink()
            return

        data = {
            "queue": list(queue),  # Convert deque to list for JSON serialization
            "volume": snapshot["volume"],
            "loop": snapshot["loop"],
            "mode_247": snapshot["mode_247"],
        }

        try:
            filepath = Path(f"data/queue_{guild_id}.json")
            # Ensure data/ exists — fresh installs may not have it yet,
            # and write_text would raise FileNotFoundError.
            filepath.parent.mkdir(parents=True, exist_ok=True)
            # Unique per-write temp file (see _save_queue_settings_sync):
            # defense-in-depth against torn-temp collisions, since a fixed
            # ``.json.tmp`` was shared by every concurrent same-guild save. It
            # does NOT by itself prevent the dropped-save race: the DEST
            # (``filepath``) is still shared, so concurrent same-guild
            # ``replace`` calls can collide (WinError 5 on Windows). Per-guild
            # serialization comes from ``save_lock`` held across ``save_queue``;
            # this writer assumes it runs under that lock.
            fd, temp_name = tempfile.mkstemp(
                dir=filepath.parent, prefix=f".{filepath.name}.", suffix=".tmp"
            )
            os.close(fd)  # we reuse the path via write_text, not the raw fd
            temp_path = Path(temp_name)
            temp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            temp_path.replace(filepath)  # Atomic on POSIX; near-atomic on Windows
        except (OSError, TypeError, ValueError):
            # Catch non-OSError too (e.g. json.dumps choking on a non-
            # serializable value) so the unique mkstemp temp is still unlinked
            # rather than orphaned in data/.
            logger.exception("Failed to save queue for guild %s", guild_id)
            # Clean up temp file if rename failed. ``temp_path`` is bound only
            # after mkstemp succeeds; guard NameError so an earlier failure
            # doesn't mask the original error.
            with contextlib.suppress(OSError, NameError):
                if temp_path.exists():
                    temp_path.unlink()

    async def load_queue(self, guild_id: int) -> bool:
        """Load queue from database. Returns True if queue was loaded."""
        from .queue import MAX_QUEUE_SIZE

        # Try database first
        try:
            from utils.database import db

            queue = await db.load_music_queue(guild_id)
            # The DB only stores the track LIST — restore volume/loop/mode_247
            # from the settings sidecar whether or not the queue has tracks (a
            # no-op when no sidecar exists). Doing this before the `if queue:`
            # gate is essential: an idle 24/7 channel has an empty DB queue, and
            # skipping the restore would drop mode_247 and auto-disconnect it
            # after a restart. (See _save_queue_settings.)
            await self._load_queue_settings(guild_id)
            if queue:
                # Cap on load — the DB may hold a queue persisted before a cap
                # change (or by another process); mirror the JSON path's limit so
                # an oversized queue can't slip in through the database branch.
                self._gs(guild_id).queue = collections.deque(queue[:MAX_QUEUE_SIZE])
                logger.info(
                    "📂 Loaded queue for guild %s (%d tracks) from database", guild_id, len(queue)
                )
                return True
        except ImportError:
            # No DB layer: line 564's sidecar restore lives inside the DB try,
            # so it didn't run. Restore volume/loop/mode_247 from the sidecar
            # here too, BEFORE the queue-JSON read below — otherwise an empty
            # queue (queue JSON absent/unlinked) drops mode_247 and a 24/7
            # channel auto-disconnects on restart in JSON-only mode. If a queue
            # JSON with tracks exists, its bundled settings (written in the same
            # save) re-apply the identical values below.
            await self._load_queue_settings(guild_id)

        # Fallback to JSON file
        filepath = Path(f"data/queue_{guild_id}.json")
        if not await asyncio.to_thread(filepath.exists):
            return False

        try:
            # Use run_in_executor to avoid blocking the event loop on file I/O
            raw = await asyncio.get_running_loop().run_in_executor(
                None, filepath.read_text, "utf-8"
            )
            data = json.loads(raw)

            # Validate expected JSON structure
            if not isinstance(data, dict) or not isinstance(data.get("queue"), list):
                logger.warning("Invalid queue file format for guild %s — skipping", guild_id)
                return False
            queue = data["queue"]
            if queue:
                self._gs(guild_id).queue = collections.deque(queue[:MAX_QUEUE_SIZE])
                # Clamp the persisted volume to the same [0.0, 2.0] range the
                # !volume command enforces and reject NaN/±inf — a corrupt or
                # hand-edited sidecar must not feed a poisoned value into the
                # PCMVolumeTransformer (min(2.0, nan) returns nan on CPython).
                _loaded_vol = float(data.get("volume", 0.5))
                self._gs(guild_id).volume = (
                    max(0.0, min(2.0, _loaded_vol)) if math.isfinite(_loaded_vol) else 0.5
                )
                self._gs(guild_id).loop = bool(data.get("loop", False))
                self._gs(guild_id).mode_247 = bool(data.get("mode_247", False))
                logger.info(
                    "📂 Loaded queue for guild %s (%d tracks) from JSON", guild_id, len(queue)
                )

                # JSON-to-DB migration: persist to the DB FIRST, then verify
                # the round-trip succeeded, THEN delete the source. The
                # previous code deleted on the optimistic assumption that
                # the in-memory load was enough; if the next save_queue
                # crashed before its DB write, the JSON was already gone
                # and the user lost their queue. We now only unlink after
                # confirmed durable storage.
                try:
                    await self.save_queue(guild_id)
                    db_queue: list = []
                    try:
                        from utils.database import db as _db

                        db_queue = await _db.load_music_queue(guild_id)
                    except ImportError:
                        # No DB layer available — keep the JSON as the
                        # canonical store and skip the unlink.
                        return True
                    if db_queue:
                        await asyncio.to_thread(filepath.unlink)
                    else:
                        logger.warning(
                            "Queue migration for guild %s: DB read-back empty, "
                            "keeping JSON as fallback",
                            guild_id,
                        )
                except Exception:
                    # Save failed — leave JSON in place so we can retry on next boot
                    logger.exception(
                        "Failed to migrate queue for guild %s to DB; JSON retained",
                        guild_id,
                    )
                return True
        except (OSError, json.JSONDecodeError, ValueError, TypeError):
            logger.exception("Failed to load queue for guild %s", guild_id)

        return False

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        """Clean up when bot is removed from a guild."""
        # Look the voice client up via ``self.bot.voice_clients`` rather
        # than ``guild.voice_client``. After a kick/ban discord.py may
        # null ``guild.voice_client`` before this event fires, even
        # though the underlying VoiceClient object is still tracked on
        # the bot. The previous shape silently leaked the connection in
        # that case. Mirror the iteration pattern used by
        # ``on_voice_state_update`` so both paths agree.
        for vc_proto in list(self.bot.voice_clients):
            vc = cast(discord.VoiceClient, vc_proto)
            if not hasattr(vc, "guild") or not vc.guild:
                continue
            if vc.guild.id != guild.id:
                continue
            try:
                await vc.disconnect(force=True)
            except Exception as e:
                logger.warning("Failed to disconnect voice client on guild remove: %s", e)
            # Don't ``break`` — under sharding edge cases a single guild
            # can briefly own more than one VoiceClient (e.g. one
            # disconnecting + a fresh reconnect mid-flight). Disconnect
            # every matching client so none are left orphaned holding a
            # gateway socket open after the guild is gone.

        await self.cleanup_guild_data(guild.id)
        logger.info("🧹 Cleaned up data for guild %s", guild.id)

    @commands.Cog.listener()
    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ) -> None:
        """Handle voice state changes for auto-disconnect and cleanup."""
        # Only process if bot is involved or member left bot's channel
        if not self.bot.user:
            return

        # Check all guilds where bot is connected
        # Create a copy to prevent RuntimeError if list changes during iteration
        for vc_proto in list(self.bot.voice_clients):
            # Cast to VoiceClient for proper type hints
            vc = cast(discord.VoiceClient, vc_proto)
            # Check if voice client has guild and channel
            if not hasattr(vc, "guild") or not vc.guild or not vc.channel:
                continue

            # Only process the voice client for the guild this event belongs to.
            # The event is for member.guild, so VCs in other guilds are unrelated.
            if vc.guild.id != member.guild.id:
                continue

            guild = vc.guild
            guild_id = guild.id

            # Bot was disconnected
            bot_user = self.bot.user
            if (
                bot_user is not None
                and member.id == bot_user.id
                and before.channel
                and not after.channel
            ):
                logger.info("🔌 Bot disconnected from voice in guild %s - cleaning up", guild_id)
                await self.cleanup_guild_data(guild_id)
                continue

            # Bot was moved to another channel
            if (
                bot_user is not None
                and member.id == bot_user.id
                and before.channel != after.channel
                and after.channel
            ):
                # Cancel any pending auto-disconnect
                task = self._gs(guild_id).auto_disconnect_task
                if task is not None:
                    task.cancel()
                    self._gs(guild_id).auto_disconnect_task = None
                continue

            # Check if someone left bot's channel
            if before.channel == vc.channel and after.channel != vc.channel:
                # Skip auto-disconnect if 24/7 mode is enabled
                if self._gs(guild_id).mode_247:
                    continue

                # Capture channel reference once to avoid race condition.
                # VoiceChannel always exposes ``.members`` — no hasattr guard needed.
                bot_channel = vc.channel
                if not bot_channel:
                    continue
                humans = [m for m in bot_channel.members if not m.bot]
                if len(humans) == 0:
                    # Start auto-disconnect countdown. Capture the state ref
                    # once so the check-and-set lands on the same dict entry
                    # (no `await` between read and write keeps it atomic under
                    # asyncio's cooperative scheduler).
                    gs = self._gs(guild_id)
                    if gs.auto_disconnect_task is None:
                        new_task = asyncio.create_task(self._auto_disconnect(guild_id, vc))
                        # Without a done-callback, an exception raised
                        # before the body's main ``await asyncio.sleep``
                        # would be silently swallowed when GC reaped the
                        # task (asyncio warns at "warning" level which is
                        # easy to miss). Log explicitly.
                        new_task.add_done_callback(
                            cast(
                                "collections.abc.Callable[[asyncio.Task[Any]], object]",
                                lambda t, gid=guild_id: (
                                    logger.exception(
                                        "Auto-disconnect task for guild %s failed",
                                        gid,
                                        exc_info=t.exception(),
                                    )
                                    if not t.cancelled() and t.exception()
                                    else None
                                ),
                            )
                        )
                        gs.auto_disconnect_task = new_task
                        logger.info("⏳ Started auto-disconnect timer for guild %s", guild_id)

            # Check if someone joined bot's channel
            if after.channel == vc.channel and before.channel != vc.channel:
                # Cancel auto-disconnect if someone joins
                task = self._gs(guild_id).auto_disconnect_task
                if task is not None:
                    task.cancel()
                    self._gs(guild_id).auto_disconnect_task = None
                    logger.info("✅ Cancelled auto-disconnect for guild %s - user joined", guild_id)

    async def _auto_disconnect(self, guild_id: int, voice_client: discord.VoiceClient) -> None:
        """Auto-disconnect after delay when alone in voice channel."""
        try:
            if voice_client.is_connected() and voice_client.guild:
                guild = voice_client.guild
                text_channel = None

                # Try to use last used text channel first
                gs = self._gs(guild_id)
                if gs.last_text_channel is not None:
                    last_channel_id = gs.last_text_channel
                    last_channel = guild.get_channel(last_channel_id)
                    if last_channel and guild.me:
                        perms = last_channel.permissions_for(guild.me)
                        # embed_links required too — the notification below is
                        # embed-only, so a channel that can't render it should
                        # never be picked.
                        if perms.send_messages and perms.embed_links:
                            text_channel = last_channel

                # Fallback: Find any text channel with send + embed permission
                if not text_channel and guild.me:
                    for channel in guild.text_channels:
                        perms = channel.permissions_for(guild.me)
                        if perms.send_messages and perms.embed_links:
                            text_channel = channel
                            break

                if text_channel:
                    embed = discord.Embed(
                        title=f"{Emojis.WARNING} แจ้งเตือนออกอัตโนมัติ",
                        description=(
                            f"ไม่มีใครในห้องเสียง\n"
                            f"Bot จะออกใน **{self.auto_disconnect_delay // 60} นาที** "
                            "หากไม่มีคนเข้ามา"
                        ),
                        color=Colors.WARNING,
                    )
                    embed.set_footer(text="ใช้ !join เพื่อเชื่อมต่อใหม่")
                    # Notification is best-effort only — this send must NOT
                    # share the outer try. If it raises (e.g. embed_links
                    # revoked after the picker ran, transient 429/5xx), the
                    # outer `except discord.DiscordException` would swallow
                    # it and skip the sleep/recheck/disconnect below, leaving
                    # the bot stuck in an empty voice channel indefinitely.
                    try:
                        await text_channel.send(embed=embed)  # type: ignore[union-attr]
                    except discord.DiscordException:
                        logger.warning("Auto-disconnect notification failed for guild %s", guild_id)

            # Wait for the delay
            await asyncio.sleep(self.auto_disconnect_delay)

            # Re-check 24/7 mode after the sleep — moderator may have
            # flipped it on during the 3-minute warning window. Without
            # this, the bot still disconnects despite the just-set flag.
            if self._gs(guild_id).mode_247:
                logger.info("⏹️ Auto-disconnect cancelled: 24/7 enabled during wait")
                return

            # Double check if still alone
            if voice_client.is_connected() and voice_client.channel:
                humans = [m for m in voice_client.channel.members if not m.bot]
                if len(humans) == 0:
                    # Disconnect FIRST, then cleanup. If `cleanup_guild_data`
                    # ran first and `disconnect()` raised, we'd be left with
                    # a zombie voice client (still connected to Discord) but
                    # no guild state to track it.
                    await voice_client.disconnect()
                    # Detach THIS task from the state before cleanup. We ARE
                    # gs.auto_disconnect_task, and cleanup_guild_data
                    # unconditionally cancels that field — a self-cancel that
                    # would abort the change_presence reset below at the next
                    # await. Clearing it first makes cleanup skip the cancel.
                    self._gs(guild_id).auto_disconnect_task = None
                    await self.cleanup_guild_data(guild_id)

                    # ``change_presence`` is global — only reset to the idle
                    # listening status if no other voice clients are still
                    # active, otherwise we clobber the now-playing presence
                    # of every other guild this bot is serving simultaneously.
                    # ``== 0`` (not <= 1): disconnect() above already removed
                    # THIS VC from bot.voice_clients, so 1 here means one
                    # OTHER guild is still playing.
                    if len(self.bot.voice_clients) == 0:
                        await self.bot.change_presence(
                            activity=discord.Activity(
                                type=discord.ActivityType.listening, name="คำสั่งเพลง"
                            )
                        )

                    logger.info("👋 Auto-disconnected from guild %s due to inactivity", guild_id)

        except asyncio.CancelledError:
            # Task was cancelled (someone joined)
            pass
        except discord.DiscordException:
            logger.exception("Auto-disconnect error")
        finally:
            # Clear the task field WITHOUT _gs() — its setdefault would
            # recreate the state object cleanup_guild_data just deleted,
            # leaking one empty MusicGuildState per auto-disconnect.
            final_gs = self._guild_states.get(guild_id)
            if final_gs is not None:
                final_gs.auto_disconnect_task = None

    async def safe_delete(self, filename):
        """Safely delete a file with exponential backoff (Non-blocking)."""
        filepath = await asyncio.to_thread(lambda: Path(filename).resolve())
        # NOTE: temp root is intentionally CWD-relative (not settings.temp_dir).
        # This confinement boundary, the _periodic_temp_cleanup janitor, and the
        # files yt-dlp actually writes (utils/media/ytdl_source.py outtmpl) all
        # use the SAME relative "temp" root, so they stay mutually consistent.
        # Anchoring only this side to settings.temp_dir while ytdl_source keeps
        # writing CWD-relative would, under a non-default launcher CWD, split the
        # download dir from this guard — yt-dlp files would land outside temp_root
        # and never be deletable/cleanable. Fixing this correctly requires also
        # anchoring ytdl_source's outtmpl (out of scope here); do that together.
        temp_root = await asyncio.to_thread(lambda: Path("temp").resolve())
        if not filepath.is_relative_to(temp_root):
            logger.warning("🛡️ Blocked file deletion outside temp directory: %s", filepath)
            return
        for attempt in range(8):  # 8 retries with exponential backoff
            if not await asyncio.to_thread(filepath.exists):
                return  # Already deleted
            try:
                await asyncio.to_thread(filepath.unlink)
                logger.info("🗑️ Deleted %s", filename)
                return
            except PermissionError:
                # Exponential backoff: 1s, 2s, 4s, 4s, 4s... (capped at 4s)
                delay = min(2**attempt, 4.0)
                if attempt < 7:
                    await asyncio.sleep(delay)
                else:
                    logger.warning(
                        "❌ Could not delete %s after %d retries (PermissionError)",
                        filename,
                        attempt + 1,
                    )
            except OSError as e:
                logger.warning("Failed to delete %s: %s", filename, e)
                return

    def get_queue(self, ctx) -> collections.deque[dict[str, Any]]:
        """Get or create queue for a guild.

        Note: Caller must ensure ctx.guild is not None (use @commands.guild_only()).
        """
        if not ctx.guild:
            raise commands.NoPrivateMessage("This command can only be used in a server.")
        return self._gs(ctx.guild.id).queue

    async def play_next(self, ctx: Context) -> None:
        """Play the next track in the queue.

        Iterative wrapper around the per-call body — previously this method
        recursed via ``await self.play_next(ctx)`` to retry after a failed
        track, which grew the asyncio task stack and was awkward to reason
        about with the lock-acquire dance below. Loop instead with the same
        retry cap.
        """
        if not ctx.voice_client or not ctx.guild:
            return
        guild_id = ctx.guild.id
        max_retries = 10
        # Local retry counter. This previously lived on the shared per-guild
        # state and was read/written here OUTSIDE play_lock, so two concurrent
        # play_next calls for the same guild interleaved the counter and could
        # defeat the 10-retry cap. A local int is private to this invocation
        # and race-free.
        retries = 0
        while True:
            retry_next = await self._play_next_once(ctx)
            if not retry_next:
                return
            if retries >= max_retries:
                logger.warning("play_next retry limit reached for guild %s", guild_id)
                return
            retries += 1

    async def _play_next_once(self, ctx: Context) -> bool:
        """Single attempt of play_next. Returns True if caller should retry.

        Body lifted verbatim from the original recursive ``play_next`` so
        the iterative wrapper above can decide whether to re-enter rather
        than the body recursing into itself.
        """
        # Check if voice_client exists
        if not ctx.voice_client or not ctx.guild:
            return False

        # Cast voice_client to VoiceClient for proper type hints
        voice_client = cast(discord.VoiceClient, ctx.voice_client)
        guild_id = ctx.guild.id

        # Use setdefault for atomic get-or-create to prevent race condition
        lock = self._gs(guild_id).play_lock

        # Atomic lock acquisition with timeout - avoids TOCTOU race condition
        # by not checking lock.locked() separately from acquire().
        # Uses shield + done_callback to avoid CPython #42130 deadlock.

        async def _acquire_lock():
            await lock.acquire()
            return True

        _acquire_task = asyncio.create_task(_acquire_lock())
        # Set if we time out OR the outer task is cancelled — in both cases the
        # shielded helper may still acquire the lock with nobody left to release
        # it. Shared with the done-callback (list for safe mutation from it).
        _abandoned_flag: list[bool] = [False]

        def _release_if_abandoned(task: asyncio.Task) -> None:
            # Cover the cases where the acquired lock would otherwise leak:
            # (1) we abandoned the wait (timeout or cancellation) but the helper
            #     still succeeded in acquiring the lock — nobody owns it;
            # (2) future code in the helper raises AFTER acquire() but before
            #     returning, so we hold the lock with no owner.
            # If the helper task itself was cancelled before acquire() returned,
            # the lock was never taken — skip.
            if task.cancelled():
                return
            should_release = False
            if _abandoned_flag[0] and task.exception() is None:
                should_release = True
            elif task.exception() is not None and lock.locked():
                # Helper raised but the lock IS held — must have been
                # acquired before the raise. Release to avoid deadlock.
                should_release = True
            if should_release:
                try:
                    lock.release()
                except RuntimeError:
                    pass

        _acquire_task.add_done_callback(_release_if_abandoned)

        try:
            # Bumped from 0.1s to 2s. The original 100ms was meant to make
            # this "effectively non-blocking" but it routinely dropped legit
            # play requests during brief contention — yt-dlp can hold the
            # lock for hundreds of ms, which made the second of two
            # back-to-back !play / after-callback calls land in the timeout
            # window and silently no-op, leaving voice_client idle even
            # though the queue had tracks. 2s comfortably covers a normal
            # acquire window without making "another task is processing"
            # detection unreliable.
            acquired = await asyncio.wait_for(asyncio.shield(_acquire_task), timeout=2.0)
            if not acquired:
                logger.debug("play_next lock acquisition failed for guild %s", guild_id)
                return False
        except TimeoutError:
            _abandoned_flag[0] = True
            # Another task is processing - skip this call
            logger.debug("play_next already in progress for guild %s", guild_id)
            return False
        except asyncio.CancelledError:
            # Outer task cancelled while shield() kept _acquire_task alive, so
            # the helper will still acquire the lock with no owner to release it.
            # Mark abandoned so the done-callback frees it, then re-raise to
            # preserve cancellation semantics. Without this the per-guild
            # play_lock leaks permanently and music deadlocks for that guild.
            _abandoned_flag[0] = True
            raise

        _retry_next = False
        try:
            # Check voice_client again inside lock
            if not ctx.voice_client:
                return False

            # Re-cast after null check
            voice_client = cast(discord.VoiceClient, ctx.voice_client)

            # Double check if playing inside lock to prevent race conditions
            if voice_client.is_playing() or voice_client.is_paused():
                return False

            # 1. Check Loop Mode
            track_info = self._gs(guild_id).current_track
            if self._gs(guild_id).loop and track_info is not None:
                # Replay current track
                filename = track_info["filename"]
                data = track_info["data"]

                if await asyncio.to_thread(lambda: Path(filename).exists()):
                    try:
                        # Verify voice_client is still valid
                        if not ctx.voice_client or not voice_client.is_connected():
                            logger.warning("Voice client disconnected during loop replay")
                            return False

                        # Recreate player from existing file
                        current_options = get_ffmpeg_options(stream=False)
                        player = YTDLSource(
                            discord.FFmpegPCMAudio(
                                filename, **current_options, executable=get_ffmpeg_executable()
                            ),
                            data=data,
                            filename=filename,
                        )

                        # Preserve current volume across loop replay
                        player.volume = self._gs(guild_id).volume

                        # Update start time
                        track_info["start_time"] = time.time()

                        def after_playing_loop(error):
                            if self._gs(guild_id).fixing:
                                return  # Skip if fixing

                            # Look up the LIVE voice_client from the guild rather
                            # than the one captured at callback-definition time.
                            # If the user ran ``!leave`` + ``!join`` between
                            # playback start and the after-callback, the captured
                            # reference is stale and ``is_connected()`` returns
                            # False even though a fresh VC is fully playable.
                            live_vc = ctx.guild.voice_client if ctx.guild else None
                            if not live_vc or not live_vc.is_connected():
                                return

                            if not self._gs(guild_id).loop:
                                # Loop disabled during play -> Delete file
                                self._safe_run_coroutine(self.safe_delete(filename))

                            if error:
                                logger.error("Loop error: %s", error)

                            # Guard: Don't schedule if already playing or paused
                            if live_vc.is_playing() or live_vc.is_paused():
                                return

                            self._safe_run_coroutine(self.play_next(ctx))

                        try:
                            voice_client.play(player, after=after_playing_loop)
                        except (discord.DiscordException, OSError):
                            # FFmpegPCMAudio at line 690 already spawned an
                            # ffmpeg subprocess; if play() rejects it, the
                            # process otherwise stays alive holding the
                            # audio file open. cleanup() kills it.
                            try:
                                player.cleanup()
                            except Exception as _e:
                                logger.debug("Loop player cleanup failed: %s", _e)
                            raise

                        # Loop embed — suppress send failures. Playback is
                        # already running at this point; letting a Forbidden/
                        # HTTPException escape fell into the handlers below,
                        # which disabled loop and then fell through to the
                        # normal queue logic, popping and discarding the next
                        # queued track while audio was still playing.
                        with contextlib.suppress(discord.DiscordException):
                            embed = discord.Embed(
                                title=f"{Emojis.LOOP} Looping",
                                description=f"**{player.title}**",
                                color=Colors.LOOP,
                            )
                            embed.set_footer(text="Use !loop to disable • !skip to skip")
                            await ctx.send(embed=embed)
                        return False
                    except discord.DiscordException:
                        logger.exception("Loop replay failed (Discord)")
                        self._gs(guild_id).loop = False  # Disable loop on error
                        # play() never accepted the source, so the after-callback
                        # that would delete this file never runs; the fall-through
                        # to queue logic overwrites current_track and drops the only
                        # reference. Release it now to match the cleanup contract.
                        self._safe_run_coroutine(self.safe_delete(filename))
                    except OSError:
                        logger.exception("Loop replay failed (audio/file)")
                        self._gs(guild_id).loop = False  # Disable loop on error
                        self._safe_run_coroutine(self.safe_delete(filename))
                else:
                    # Loop source file is gone (external temp eviction / race).
                    # Disable loop so the now-playing embed and cleanup
                    # callbacks stay consistent with the track that actually
                    # plays — matches the loop=False resets in the except
                    # handlers above before falling through to queue logic.
                    self._gs(guild_id).loop = False
                    with contextlib.suppress(discord.DiscordException):
                        await ctx.send("⚠️ ไฟล์ลูปหาย — ปิดลูปและเล่นเพลงถัดไป", delete_after=15)

            # 2. Normal Queue Logic
            queue = self.get_queue(ctx)
            if len(queue) > 0:
                # Peek-then-validate so an entry without a URL doesn't
                # vanish from the user's queue silently. We only popleft
                # AFTER we've confirmed the item is dispatchable; for
                # invalid items we drop them with a log line.
                item = queue[0]
                url = item.get("url") if isinstance(item, dict) else item

                if not url:
                    queue.popleft()
                    self._schedule_queue_save(guild_id)
                    logger.warning(
                        "Dropped queue entry without URL for guild %s: %r",
                        guild_id,
                        item,
                    )
                    # Drop-and-continue: tell the play_next wrapper to re-enter
                    # and try the next queued track. Returning False would halt
                    # the loop, stranding every still-valid track behind this
                    # one. Mirrors the search-resolution-failed branch below,
                    # which also returns True to advance; play_next's 10-retry
                    # cap bounds churn on a fully-malformed queue.
                    return True
                queue.popleft()
                self._schedule_queue_save(guild_id)

                # Track whether voice_client.play() actually accepted the
                # player. While False, any exception path must call
                # ``player.cleanup()`` so the FFmpeg subprocess that
                # ``YTDLSource.from_url`` spawned doesn't leak.
                # mypy widens ``player`` to YTDLSource from the loop-replay
                # branch above, so a None reset here needs an explicit cast.
                player: YTDLSource | None = None  # type: ignore[no-redef]
                player_handed_off = False
                try:
                    async with ctx.typing():
                        # Resolve search-type items (e.g. Spotify enqueues
                        # text queries with type="search") to a concrete
                        # YouTube URL before handing off to from_url, which
                        # only accepts http(s) URLs.
                        play_url = url
                        if isinstance(item, dict) and item.get("type") == "search":
                            search_info = await YTDLSource.search_source(
                                url, loop=asyncio.get_running_loop()
                            )
                            if not search_info or not search_info.get("webpage_url"):
                                logger.warning("Search resolution failed for queue item: %r", item)
                                # Notify the user — without this the queue
                                # silently advances and a Spotify track that
                                # failed to resolve via YouTube search just
                                # vanishes with no feedback. Use ctx.send
                                # rather than a fancy embed: the next track
                                # is about to play and we don't want to
                                # spam.
                                with contextlib.suppress(discord.HTTPException):
                                    title = (
                                        item.get("title") if isinstance(item, dict) else None
                                    ) or url
                                    await ctx.send(
                                        f"⚠️ ข้ามเพลงนี้: ไม่พบบน YouTube — `{title}`",
                                        delete_after=15,
                                    )
                                _retry_next = True
                                return _retry_next
                            play_url = search_info["webpage_url"]

                        # Use Download Mode (stream=False)
                        player = await YTDLSource.from_url(
                            play_url, loop=asyncio.get_running_loop(), stream=False
                        )

                        # Apply stored volume to new track
                        player.volume = self._gs(guild_id).volume

                        # Save current track info (only essential data)
                        self._gs(guild_id).current_track = {
                            "filename": player.filename,
                            "data": {
                                "title": player.data.get("title"),
                                "webpage_url": player.data.get("webpage_url"),
                                "thumbnail": player.data.get("thumbnail"),
                                "duration": player.data.get("duration"),
                                "url": player.data.get("url"),
                            },
                            "title": player.title,
                            "start_time": time.time(),
                        }
                        # New track starts fresh — clear any stale pause marker so
                        # skipping a paused track can't leave pause_start pointing at
                        # the previous track (which would corrupt resume / nowplaying
                        # elapsed). Covers both the skip button and the !skip command.
                        self._gs(guild_id).pause_start = None

                        # Snapshot ``player.filename`` into the closure too.
                        # The outer ``player`` binding is reset to None at
                        # the top of the next loop iteration; without this
                        # snapshot, when ``after_playing`` fires after the
                        # next track has already been queued, ``player``
                        # resolves to None and ``player.filename`` raises
                        # AttributeError, breaking the callback chain (and
                        # leaking the FFmpeg subprocess + temp file).
                        player_filename = player.filename

                        def after_playing(error):
                            if self._gs(guild_id).fixing:
                                return  # Skip if fixing

                            # Use the live voice_client (see after_playing_loop
                            # comment) so a !leave+!join cycle between play
                            # start and this callback doesn't freeze the queue.
                            live_vc = ctx.guild.voice_client if ctx.guild else None
                            if not live_vc or not live_vc.is_connected():
                                # Cleanup file even if disconnected
                                if player_filename and not self._gs(guild_id).loop:
                                    self._safe_run_coroutine(self.safe_delete(player_filename))
                                return

                            # Cleanup: Delete file ONLY if loop is OFF
                            if not self._gs(guild_id).loop:
                                if player_filename:
                                    self._safe_run_coroutine(self.safe_delete(player_filename))

                            if error:
                                logger.error("Player error: %s", error)

                            # Guard: Don't schedule if already playing or paused
                            if live_vc.is_playing() or live_vc.is_paused():
                                return

                            self._safe_run_coroutine(self.play_next(ctx))

                        try:
                            voice_client.play(player, after=after_playing)
                            player_handed_off = True
                        except discord.DiscordException:
                            logger.exception("Failed to start playback (Discord)")
                            # Cleanup FFmpeg process
                            try:
                                player.cleanup()
                            except Exception as cleanup_err:
                                logger.debug(
                                    "Player cleanup failed (non-critical): %s", cleanup_err
                                )
                            # Cleanup file on error
                            if player.filename and not self._gs(ctx.guild.id).loop:
                                self._safe_run_coroutine(self.safe_delete(player.filename))
                            _retry_next = True
                            return _retry_next
                        except OSError:
                            logger.exception("Failed to start playback (audio/file)")
                            try:
                                player.cleanup()
                            except Exception as cleanup_err:
                                logger.debug(
                                    "Player cleanup failed (non-critical): %s", cleanup_err
                                )
                            if player.filename and not self._gs(ctx.guild.id).loop:
                                self._safe_run_coroutine(self.safe_delete(player.filename))
                            _retry_next = True
                            return _retry_next

                    # 🎨 PREMIUM NOW PLAYING EMBED
                    # ``or 0`` normalises a yt-dlp None duration (livestream /
                    # missing metadata) so the progress bar / format_duration
                    # take their "unknown" branch instead of raising.
                    duration = player.data.get("duration") or 0
                    embed = discord.Embed(
                        title=f"{Emojis.NOTES} กำลังเล่น",
                        description=(f"**[{player.title}]({player.data.get('webpage_url')})**"),
                        color=Colors.PLAYING,
                    )

                    # Thumbnail
                    if player.data.get("thumbnail"):
                        embed.set_thumbnail(url=player.data.get("thumbnail"))

                    # Duration with progress bar (starts at 0)
                    progress_bar = create_progress_bar(0, duration)
                    embed.add_field(
                        name=f"{Emojis.CLOCK} Duration",
                        value=(f"`{progress_bar}`\n`00:00` / `{format_duration(duration)}`"),
                        inline=True,
                    )

                    # Audio Quality Badge
                    embed.add_field(
                        name=f"{Emojis.VOLUME} Audio",
                        value="`Premium HQ`\n`48kHz Stereo`",
                        inline=True,
                    )

                    # Loop Status
                    loop_status = (
                        f"{Emojis.LOOP} On" if self._gs(ctx.guild.id).loop else f"{Emojis.LOOP} Off"
                    )
                    embed.add_field(name="Loop", value=f"`{loop_status}`", inline=True)

                    embed.set_footer(
                        text=(
                            f"Requested by {ctx.author.display_name} • Use buttons below to control"
                        ),
                        icon_url=ctx.author.display_avatar.url,
                    )

                    # Send embed with interactive controls
                    view = MusicControlView(self, ctx.guild.id)
                    view.message = await ctx.send(embed=embed, view=view)
                    # Only update global presence if bot is in exactly one voice channel
                    if len(self.bot.voice_clients) <= 1:
                        await self.bot.change_presence(
                            activity=discord.Activity(
                                type=discord.ActivityType.listening, name=player.title
                            )
                        )
                except discord.DiscordException as e:
                    embed = discord.Embed(
                        title=f"{Emojis.CROSS} Playback Error",
                        description="ไม่สามารถเล่นเพลงถัดไปได้ กรุณาลองใหม่",
                        color=Colors.ERROR,
                    )
                    # Guard the error-notification send: a failed ctx.send raises
                    # discord.DiscordException from INSIDE this except-suite, which
                    # would escape past the finally blocks and out of
                    # _play_next_once (play_next calls it with no try/except),
                    # freezing the queue and never returning _retry_next. Mirror
                    # the yt_dlp branch's guard below.
                    try:
                        await ctx.send(embed=embed)
                    except discord.DiscordException:
                        pass
                    logger.error("Play error (Discord): %s\n%s", e, traceback.format_exc())
                    _retry_next = True
                except OSError as e:
                    embed = discord.Embed(
                        title=f"{Emojis.CROSS} Playback Error",
                        description="เกิดข้อผิดพลาดกับไฟล์เสียง กรุณาลองใหม่",
                        color=Colors.ERROR,
                    )
                    # Same guard as the Discord branch above: a failed send here
                    # raises discord.DiscordException from inside this except-suite
                    # and would otherwise escape and freeze the queue.
                    try:
                        await ctx.send(embed=embed)
                    except discord.DiscordException:
                        pass
                    logger.error("Play error (audio/file): %s\n%s", e, traceback.format_exc())
                    _retry_next = True
                except (yt_dlp.DownloadError, ValueError) as e:
                    # A bad URL / 4xx from YouTube would otherwise propagate
                    # uncaught, kill _play_next_once, and freeze the queue
                    # behind a now-popped track. Skip to the next item instead.
                    # ValueError covers YTDLSource.from_url's own rejections
                    # (unavailable video, empty playlist, SSRF refusal,
                    # suspicious filename) which previously escaped uncaught
                    # and stalled the queue with no user feedback.
                    embed = discord.Embed(
                        title=f"{Emojis.CROSS} Download Error",
                        description="โหลดเพลงนี้ไม่ได้ ข้ามไปเพลงถัดไป",
                        color=Colors.ERROR,
                    )
                    try:
                        await ctx.send(embed=embed)
                    except discord.DiscordException:
                        pass
                    logger.warning("yt-dlp download error, skipping track: %s", e)
                    _retry_next = True
                finally:
                    # If FFmpeg was spawned but never handed to voice_client
                    # (an exception fired between from_url() and play()),
                    # the subprocess would otherwise stay alive holding the
                    # downloaded audio file open. cleanup() kills it.
                    if player is not None and not player_handed_off:
                        try:
                            player.cleanup()
                        except Exception as _e:
                            logger.debug("Pre-handoff player cleanup failed: %s", _e)
            else:
                # Queue empty
                self._gs(ctx.guild.id).current_track = None  # Clear track info
                # Only update global presence if bot has no other active voice clients
                if len(self.bot.voice_clients) <= 1:
                    await self.bot.change_presence(
                        activity=discord.Activity(
                            type=discord.ActivityType.listening, name="คำสั่งเพลง"
                        )
                    )
        finally:
            # Always release the lock
            lock.release()

        # Retry decision flows back to the iterative ``play_next`` wrapper —
        # it owns the per-guild retry budget so this body stays simple.
        return _retry_next

    @commands.hybrid_command(name="loop", aliases=["l"])  # type: ignore[arg-type]
    @commands.guild_only()
    async def loop(self, ctx):
        """เปิด/ปิด โหมดวนซ้ำเพลงปัจจุบัน."""
        current = self._gs(ctx.guild.id).loop
        self._gs(ctx.guild.id).loop = not current
        # Persist so the toggle survives a non-graceful restart. The sidecar
        # exists precisely for this; without scheduling a save the new value
        # is only written on a clean cog_unload (lost on OOM/kill -9/crash).
        self._schedule_queue_save(ctx.guild.id)

        if not current:
            embed = discord.Embed(
                title=f"{Emojis.LOOP} เปิดโหมดวนซ้ำ",
                description="เพลงปัจจุบันจะเล่นซ้ำหลังจบ",
                color=Colors.LOOP,
            )
            embed.set_footer(text="ใช้ !loop อีกครั้งเพื่อปิด")
        else:
            embed = discord.Embed(
                title=f"{Emojis.LOOP} ปิดโหมดวนซ้ำ",
                description="เล่นเพลงถัดไปต่อตามคิว",
                color=Colors.STOP,
            )
        await ctx.send(embed=embed)

    def mark_pause(self, guild_id: int) -> None:
        """Record the pause instant so elapsed-position math stays correct.

        Shared bookkeeping used by BOTH the text ``!pause`` command and the
        ``MusicControlView`` pause button (views.py). Without going through
        here, a button-initiated pause never set ``pause_start``, so resume /
        fix / nowplaying fell back to ``time.time() - start_time`` and the
        progress kept advancing past the real audio position while paused.
        Idempotent: a second call while already marked keeps the original
        instant so the paused interval isn't shrunk.
        """
        gs = self._gs(guild_id)
        if gs.pause_start is None:
            gs.pause_start = time.time()

    def mark_resume(self, guild_id: int) -> None:
        """Shift ``start_time`` forward by the paused interval, then clear it.

        Shared bookkeeping used by BOTH the text ``!resume`` command and the
        ``MusicControlView`` pause button (views.py). Mirrors the original
        inline resume math so a button-initiated pause/resume corrects
        ``start_time`` the same way the text command does.
        """
        gs = self._gs(guild_id)
        if gs.pause_start is not None:
            paused_duration = time.time() - gs.pause_start
            # Shift start time forward
            if gs.current_track is not None:
                gs.current_track["start_time"] += paused_duration
            gs.pause_start = None

    @commands.hybrid_command(name="pause", aliases=["pa"])  # type: ignore[arg-type]
    @commands.guild_only()
    async def pause(self, ctx):
        """หยุดเล่นเพลงชั่วคราว."""
        if not ctx.voice_client:
            embed = discord.Embed(
                description=f"{Emojis.CROSS} Bot ไม่ได้อยู่ในห้องเสียง", color=Colors.ERROR
            )
            return await ctx.send(embed=embed)

        if ctx.voice_client.is_playing():
            try:
                ctx.voice_client.pause()
            except discord.ClientException as exc:
                # Already paused / not actually playing in a race.
                logger.warning("Pause failed: %s", exc)
                embed = discord.Embed(
                    description=f"{Emojis.CROSS} หยุดเพลงไม่ได้ (state ผิดพลาด)",
                    color=Colors.ERROR,
                )
                return await ctx.send(embed=embed)
            self.mark_pause(ctx.guild.id)

            # Get current track info for embed
            track_info = self._gs(ctx.guild.id).current_track or {}
            title = track_info.get("title", "Unknown Track")

            embed = discord.Embed(
                title=f"{Emojis.PAUSE} หยุดชั่วคราว", description=f"**{title}**", color=Colors.PAUSED
            )
            embed.set_footer(text="ใช้ !resume เพื่อเล่นต่อ")
            await ctx.send(embed=embed)
        elif ctx.voice_client.is_paused():
            embed = discord.Embed(
                description=(f"{Emojis.WARNING} หยุดอยู่แล้ว • ใช้ `!resume` เพื่อเล่นต่อ"),
                color=Colors.WARNING,
            )
            await ctx.send(embed=embed)
        else:
            embed = discord.Embed(description=f"{Emojis.CROSS} ไม่มีเพลงเล่นอยู่", color=Colors.ERROR)
            await ctx.send(embed=embed)

    @commands.hybrid_command(name="resume", aliases=["unpause"])  # type: ignore[arg-type]
    @commands.guild_only()
    async def resume(self, ctx):
        """เล่นเพลงต่อ."""
        if not ctx.voice_client:
            embed = discord.Embed(
                description=f"{Emojis.CROSS} Bot ไม่ได้อยู่ในห้องเสียง", color=Colors.ERROR
            )
            return await ctx.send(embed=embed)

        if ctx.voice_client.is_paused():
            # Calculate paused duration and shift start_time forward (shared
            # bookkeeping so the button-resume path corrects start_time too).
            self.mark_resume(ctx.guild.id)

            ctx.voice_client.resume()

            # Get current track info for embed
            track_info = self._gs(ctx.guild.id).current_track or {}
            title = track_info.get("title", "Unknown Track")

            embed = discord.Embed(
                title=f"{Emojis.PLAY} เล่นต่อ", description=f"**{title}**", color=Colors.RESUMED
            )
            await ctx.send(embed=embed)
        elif ctx.voice_client.is_playing():
            embed = discord.Embed(
                description=f"{Emojis.WARNING} กำลังเล่นอยู่แล้ว", color=Colors.WARNING
            )
            await ctx.send(embed=embed)
        else:
            embed = discord.Embed(description=f"{Emojis.CROSS} ไม่มีเพลงให้เล่นต่อ", color=Colors.ERROR)
            await ctx.send(embed=embed)

    @commands.hybrid_command(name="fix", aliases=["f", "reconnect"])  # type: ignore[arg-type]
    @commands.guild_only()
    async def fix(self, ctx):
        """แก้ไขอาการกระตุกโดยการเชื่อมต่อใหม่และเล่นต่อจากเดิม."""
        if not ctx.voice_client or (
            not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused()
        ):
            embed = discord.Embed(description=f"{Emojis.CROSS} ไม่มีเพลงเล่นอยู่", color=Colors.ERROR)
            return await ctx.send(embed=embed)

        # Validate the reconnect target BEFORE tearing down the live connection.
        # Step 2 below stops playback and disconnects the bot; without this guard
        # a !fix from a user NOT in a voice channel would drop the live session
        # first and only THEN bail at the reconnect step — losing playback and,
        # via the deferred-cleanup path, the queue. The sibling join() validates
        # ctx.author.voice up front for exactly this reason. (The later
        # else-branch at the reconnect step is kept as a defensive TOCTOU guard.)
        if not ctx.author.voice:
            embed = discord.Embed(
                description=f"{Emojis.CROSS} คุณไม่ได้อยู่ในห้องเสียง", color=Colors.ERROR
            )
            return await ctx.send(embed=embed)

        fix_embed = discord.Embed(
            title=f"{Emojis.TOOLS} กำลังแก้ไขการเชื่อมต่อ",
            description="กำลังเชื่อมต่อใหม่และเล่นต่อ...",
            color=Colors.INFO,
        )
        fix_msg = await ctx.send(embed=fix_embed)

        guild_id = ctx.guild.id
        track_info = self._gs(guild_id).current_track
        if not track_info:
            embed = discord.Embed(description=f"{Emojis.CROSS} ไม่พบข้อมูลเพลง", color=Colors.ERROR)
            return await ctx.send(embed=embed)

        # 1. Calculate elapsed time
        start_time = track_info.get("start_time", 0)
        elapsed = 0
        if start_time > 0:
            if ctx.voice_client.is_paused() and self._gs(guild_id).pause_start is not None:
                # If paused, elapsed is time until pause
                elapsed = self._gs(guild_id).pause_start - start_time
            else:
                # If playing, elapsed is time until now
                elapsed = time.time() - start_time

        # Lower-clamp: a backward time.time() step (NTP correction / clock
        # skew) can make elapsed negative, which persists a future start_time
        # at L1523 and renders garbage at format_duration(elapsed) (L1565).
        # Mirrors nowplaying (L2502).
        elapsed = max(0, elapsed)

        # 2. Stop and Disconnect (Set fixing flag)
        self._gs(guild_id).fixing = True

        # Clear pause state if exists (since we will resume playing)
        self._gs(guild_id).pause_start = None

        # Disconnect can throw discord.HTTPException on transient gateway
        # errors. Without the try, ``fixing`` was reset by the outer
        # ``finally`` (line ~1282) but the embed at ``fix_msg`` already
        # promised "เชื่อมต่อใหม่" and the user sees nothing. Surface
        # the failure cleanly so they know to retry.
        try:
            ctx.voice_client.stop()
            await ctx.voice_client.disconnect()
        except (discord.HTTPException, discord.ClientException) as disconnect_err:
            self._gs(guild_id).fixing = False
            logger.warning("fix: disconnect failed: %s", disconnect_err)
            embed = discord.Embed(
                description=(f"{Emojis.CROSS} ไม่สามารถตัดการเชื่อมต่อเดิมได้ ลอง !leave แล้ว !play ใหม่"),
                color=Colors.ERROR,
            )
            with contextlib.suppress(discord.HTTPException):
                await ctx.send(embed=embed)
            # The main try/finally below does NOT run on this early return, so
            # honor any cleanup deferred during the fix here too.
            await self._drain_pending_cleanup(guild_id, ctx)
            return

        try:
            # 3. Reconnect. Match the timeout other connect sites use
            # (join, play) so a stalled gateway doesn't hang the command
            # for the full 60s discord.py default.
            if ctx.author.voice:
                channel = ctx.author.voice.channel
                await channel.connect(timeout=30.0)
            else:
                embed = discord.Embed(
                    description=f"{Emojis.CROSS} คุณไม่ได้อยู่ในห้องเสียง", color=Colors.ERROR
                )
                await ctx.send(embed=embed)
                return

            # 4. Resume
            filename = track_info["filename"]
            data = track_info["data"]

            # Mirror the existence check that ``seek`` does: the previous
            # track's after-callback may have already deleted the file
            # (loop=False path), in which case ffmpeg silently produces no
            # audio. Bail out cleanly so the user can re-issue. Off-loop —
            # a stat on a hung disk would block every guild's playback.
            if not await asyncio.to_thread(Path(filename).exists):
                self._gs(guild_id).fixing = False
                # We've already reconnected above, so the finally-block cleanup
                # guard sees a connected VC and won't run. Clear the stale
                # current_track explicitly — it points at the now-deleted file
                # and the bot is left connected+idle; leaving it populated would
                # let a subsequent !fix/!nowplaying act on a dead reference.
                self._gs(guild_id).current_track = None
                embed = discord.Embed(
                    description=f"{Emojis.CROSS} ไฟล์เพลงถูกลบไปแล้ว ลอง !play ใหม่",
                    color=Colors.ERROR,
                )
                await ctx.send(embed=embed)
                return

            # Seek to elapsed time
            current_options = get_ffmpeg_options(stream=False, start_time=elapsed)

            player = YTDLSource(
                discord.FFmpegPCMAudio(
                    filename, **current_options, executable=get_ffmpeg_executable()
                ),
                data=data,
                filename=filename,
            )

            # Preserve current volume across fix/reconnect
            player.volume = self._gs(guild_id).volume

            # Restore current_track (cleanup may have removed it during disconnect)
            self._gs(guild_id).current_track = track_info

            # Update start time to now - elapsed
            self._gs(guild_id).current_track["start_time"] = time.time() - elapsed

            # Hold a reference for the immediate ``.play()`` call below; the
            # callback itself looks up the LIVE VC each time it fires so a
            # disconnect/reconnect between play-start and end doesn't freeze
            # the queue.
            voice_client_fix = ctx.voice_client

            def after_playing_fix(error):
                if self._gs(guild_id).fixing:
                    return

                live_vc = ctx.guild.voice_client if ctx.guild else None
                if not live_vc or not live_vc.is_connected():
                    # Cleanup file even if disconnected
                    if not self._gs(guild_id).loop and filename:
                        self._safe_run_coroutine(self.safe_delete(filename))
                    return

                # Cleanup logic - use safe_delete
                if not self._gs(guild_id).loop and filename:
                    self._safe_run_coroutine(self.safe_delete(filename))

                if error:
                    logger.error("Fix player error: %s", error)
                self._safe_run_coroutine(self.play_next(ctx))

            try:
                voice_client_fix.play(player, after=after_playing_fix)
            except Exception:
                # If play() rejects the source, the FFmpegPCMAudio subprocess
                # is orphaned holding the file open. Clean it up before
                # propagating so the outer except blocks render the error UI.
                try:
                    player.cleanup()
                except Exception as _e:
                    logger.debug("Fix player cleanup failed (non-critical): %s", _e)
                raise

            # Success embed
            success_embed = discord.Embed(
                title=f"{Emojis.CHECK} แก้ไขสำเร็จ!",
                description=f"เล่นต่อที่ `{format_duration(elapsed)}`",
                color=Colors.RESUMED,
            )
            success_embed.add_field(
                name="เพลง", value=f"**{track_info.get('title', 'Unknown')}**", inline=False
            )
            await fix_msg.edit(embed=success_embed)

        except discord.DiscordException as e:
            error_embed = discord.Embed(
                title=f"{Emojis.CROSS} แก้ไขไม่สำเร็จ",
                description="เกิดข้อผิดพลาดในการเชื่อมต่อใหม่ กรุณาลองอีกครั้ง",
                color=Colors.ERROR,
            )
            await fix_msg.edit(embed=error_embed)
            logger.error("Fix failed (Discord): %s", e)
        except OSError as e:
            error_embed = discord.Embed(
                title=f"{Emojis.CROSS} แก้ไขไม่สำเร็จ",
                description="เกิดข้อผิดพลาดกับไฟล์เสียง กรุณาลองอีกครั้ง",
                color=Colors.ERROR,
            )
            await fix_msg.edit(embed=error_embed)
            logger.error("Fix failed (audio/file): %s", e)
        finally:
            # Always reset fixing flag at the end
            self._gs(guild_id).fixing = False
            # Honor any cleanup deferred (cleanup_pending) while we were mid-fix.
            await self._drain_pending_cleanup(guild_id, ctx)

    async def _drain_pending_cleanup(self, guild_id: int, ctx) -> None:
        """Run a cleanup deferred during !fix, but only when the VC is truly gone.

        Our own stop()/disconnect() during the fix ALSO fires
        on_voice_state_update, which arms cleanup_pending — so on a SUCCESSFUL
        fix (bot reconnected and playing) honoring it would run the destructive
        cleanup_guild_data against the LIVE session, wiping its
        queue/current_track and resetting loop/volume mid-playback. Only run the
        deferred cleanup when the bot is genuinely no longer connected (e.g. a
        real guild-leave during the fix); otherwise just clear the flag,
        discarding our own transient disconnect echo. Shared by the finally
        block and the disconnect-failure early return so neither path leaks a
        pending cleanup.
        """
        state = self._guild_states.get(guild_id)
        if state is None or not state.cleanup_pending:
            return
        state.cleanup_pending = False
        vc = ctx.voice_client
        if vc is None or not vc.is_connected():
            with contextlib.suppress(Exception):
                await self.cleanup_guild_data(guild_id)

    @commands.hybrid_command(name="join", aliases=["j", "connect"])  # type: ignore[arg-type]
    @commands.bot_has_guild_permissions(connect=True, speak=True)
    async def join(self, ctx):
        """เข้าร่วมช่องเสียง."""
        if not ctx.author.voice:
            embed = discord.Embed(
                description=(f"{Emojis.CROSS} คุณต้องอยู่ในห้องเสียงก่อน"), color=Colors.ERROR
            )
            await ctx.send(embed=embed)
            return

        channel = ctx.author.voice.channel

        # Check channel-specific permissions
        permissions = channel.permissions_for(ctx.guild.me)
        if not permissions.connect or not permissions.speak:
            embed = discord.Embed(
                title=f"{Emojis.CROSS} ไม่มีสิทธิ์",
                description=f"Bot ไม่มีสิทธิ์เข้าหรือพูดในห้อง **{channel.name}**\n"
                f"กรุณาให้สิทธิ์ `Connect` และ `Speak` แก่ Bot",
                color=Colors.ERROR,
            )
            await ctx.send(embed=embed)
            return

        # Slash (/join) ต้อง ack ภายใน 3 วินาทีของ Discord แต่ move_to/connect
        # ด้านล่างอาจใช้เวลาถึง 30 วินาที จึง defer ไว้ก่อน ไม่งั้นจะขึ้น
        # "The application did not respond" (prefix !join ไม่มี interaction
        # จึงไม่ได้รับผลกระทบ)
        if ctx.interaction is not None:
            await ctx.defer()

        if ctx.voice_client is not None:
            try:
                await ctx.voice_client.move_to(channel)
            except (TimeoutError, discord.HTTPException) as e:
                embed = discord.Embed(
                    description=f"{Emojis.CROSS} ย้ายไม่สำเร็จ: {e}",
                    color=Colors.ERROR,
                )
                await ctx.send(embed=embed)
                return
            embed = discord.Embed(
                description=f"{Emojis.CHECK} ย้ายไป **{channel.name}**", color=Colors.RESUMED
            )
            await ctx.send(embed=embed)
            return

        try:
            await channel.connect(timeout=30.0)
        except (TimeoutError, discord.ClientException) as e:
            embed = discord.Embed(
                description=f"{Emojis.CROSS} เชื่อมต่อไม่สำเร็จ: {e}", color=Colors.ERROR
            )
            await ctx.send(embed=embed)
            return
        embed = discord.Embed(
            title=f"{Emojis.HEADPHONES} เชื่อมต่อแล้ว",
            description=f"เข้าร่วม **{channel.name}**",
            color=Colors.RESUMED,
        )
        embed.set_footer(text="ใช้ !play <ชื่อเพลง> เพื่อเล่นเพลง")
        await ctx.send(embed=embed)

    @commands.command(name="play", aliases=["p"])
    @commands.guild_only()
    @commands.bot_has_guild_permissions(connect=True, speak=True)
    async def play(self, ctx: Context, *, query: str | None = None) -> None:
        """เล่นเพลงจาก YouTube หรือ Spotify."""
        # Restore any queue persisted before the last restart (lazy, once per
        # guild). The save side has always run (periodic/unload/cleanup), but
        # nothing in production ever called load_queue — persisted queues
        # were write-only and every restart silently started empty.
        if ctx.guild:
            _gs_restore = self._gs(ctx.guild.id)
            if not _gs_restore.queue_loaded:
                _gs_restore.queue_loaded = True
                if not _gs_restore.queue:
                    try:
                        await self.load_queue(ctx.guild.id)
                    except Exception:
                        logger.warning(
                            "Queue restore failed for guild %s", ctx.guild.id, exc_info=True
                        )
        # Validate query parameter
        if query:
            # Strip Discord's "suppress embed" angle brackets — users habitually
            # type ``!play <https://...>`` and the brackets used to fall through
            # to YouTube-search, which then 404'd on the YouTube side.
            query = query.strip()
            if len(query) >= 2 and query.startswith("<") and query.endswith(">"):
                query = query[1:-1].strip()
            query = query[:500]  # Cap length to prevent DoS via extremely long queries
        # SSRF guard: yt-dlp will fetch any URL we hand it, including
        # ``file://``, ``ftp://``, ``http://169.254.169.254/`` (AWS metadata),
        # or other internal addresses. A user typing ``!play file:///etc/passwd``
        # would have yt-dlp open that path. Reject URLs with non-http(s)
        # schemes, and reject http(s) URLs that target loopback / private
        # networks. Plain text searches (no scheme) bypass this — yt-dlp
        # only treats text without ``://`` as a search query.
        if query and ("://" in query or query.lstrip().startswith("//")):
            from .url_safety import is_url_query_safe_async

            ok, reason = await is_url_query_safe_async(query)
            if not ok:
                embed = discord.Embed(
                    description=f"{Emojis.CROSS} URL ไม่ปลอดภัย: {reason}",
                    color=Colors.ERROR,
                )
                await ctx.send(embed=embed)
                return
        if not query or not query.strip():
            embed = discord.Embed(
                title=f"{Emojis.MUSIC} วิธีเล่นเพลง",
                description="ใช้ `!play <ชื่อเพลง หรือ URL>`",
                color=Colors.INFO,
            )
            embed.add_field(
                name="ตัวอย่าง",
                value=(
                    "`!play shape of you`\n"
                    "`!play https://youtube.com/...`\n"
                    "`!play https://open.spotify.com/...`"
                ),
                inline=False,
            )
            await ctx.send(embed=embed)
            return

        if not ctx.author.voice:  # type: ignore[union-attr]
            embed = discord.Embed(
                description=(f"{Emojis.CROSS} คุณต้องอยู่ในห้องเสียงก่อน"), color=Colors.ERROR
            )
            await ctx.send(embed=embed)
            return

        # Check channel-specific permissions before connecting
        channel = ctx.author.voice.channel  # type: ignore[union-attr]
        if not channel or not ctx.guild:
            embed = discord.Embed(description=f"{Emojis.CROSS} ไม่พบช่องเสียง", color=Colors.ERROR)
            await ctx.send(embed=embed)
            return

        permissions = channel.permissions_for(ctx.guild.me)
        if not permissions.connect or not permissions.speak:
            channel_name = channel.name if channel else "unknown"
            embed = discord.Embed(
                title=f"{Emojis.CROSS} ไม่มีสิทธิ์",
                description=f"Bot ไม่มีสิทธิ์เข้าหรือพูดในห้อง **{channel_name}**\n"
                f"กรุณาให้สิทธิ์ `Connect` และ `Speak` แก่ Bot",
                color=Colors.ERROR,
            )
            await ctx.send(embed=embed)
            return

        # Connect if not connected
        if ctx.voice_client is None:
            try:
                await channel.connect(timeout=30.0)
            except (TimeoutError, discord.ClientException) as e:
                embed = discord.Embed(
                    description=f"{Emojis.CROSS} เชื่อมต่อไม่สำเร็จ: {e}", color=Colors.ERROR
                )
                await ctx.send(embed=embed)
                return
        elif ctx.voice_client.channel and ctx.voice_client.channel != channel:
            # Move to user's channel if in different channel. Mirror the
            # connect path's permission check so a Connect-less destination
            # surfaces as a friendly error instead of a silent move
            # failure or mid-playback drop.
            permissions = channel.permissions_for(ctx.guild.me)
            if not (permissions.connect and permissions.speak):
                embed = discord.Embed(
                    description=(
                        f"{Emojis.CROSS} ไม่สามารถย้ายไปห้อง `{channel.name}`. "
                        "กรุณาให้สิทธิ์ `Connect` และ `Speak` แก่ Bot"
                    ),
                    color=Colors.ERROR,
                )
                await ctx.send(embed=embed)
                return
            try:
                await ctx.voice_client.move_to(channel)  # type: ignore[attr-defined]
            except (TimeoutError, discord.ClientException) as e:
                embed = discord.Embed(
                    description=f"{Emojis.CROSS} ย้ายห้องเสียงไม่สำเร็จ: {e}",
                    color=Colors.ERROR,
                )
                await ctx.send(embed=embed)
                return

        queue = self.get_queue(ctx)

        # Check if Spotify URL — match on parsed hostname instead of bare
        # substring so attacker URLs like "https://evil.com/?ref=open.spotify.com"
        # don't get treated as Spotify links.
        from urllib.parse import urlparse as _urlparse

        try:
            _spotify_host = _urlparse(query).hostname or ""
        except (ValueError, TypeError):
            _spotify_host = ""
        is_spotify_url = _spotify_host == "open.spotify.com" or _spotify_host.endswith(
            ".spotify.com"
        )
        if is_spotify_url and self.spotify.is_available():
            success = await self.spotify.process_spotify_url(ctx, query, queue)  # type: ignore[arg-type]
            if not success:
                return
            # Persist the Spotify-added track(s) like the YouTube path does
            # (line below in the else-branch) — otherwise tracks queued via a
            # Spotify link are lost on a restart until some other action saves.
            self._schedule_queue_save(ctx.guild.id)
        elif is_spotify_url:
            # Spotify URL but the integration is unconfigured. Short-circuit
            # with a clear message instead of falling through to the YouTube
            # branch, where yt-dlp would try to extract the raw
            # https://open.spotify.com/... URL directly and surface a confusing
            # generic "No results found".
            embed = discord.Embed(
                description=(
                    f"{Emojis.CROSS} Spotify links aren't available — Spotify "
                    f"integration is not configured."
                ),
                color=Colors.ERROR,
            )
            await ctx.send(embed=embed)
            return
        else:
            # YouTube / Search
            async with ctx.typing():
                # Check queue size limit
                from .queue import MAX_QUEUE_SIZE

                if len(queue) >= MAX_QUEUE_SIZE:
                    embed = discord.Embed(
                        description=f"{Emojis.CROSS} Queue is full (max {MAX_QUEUE_SIZE} tracks)",
                        color=Colors.ERROR,
                    )
                    await ctx.send(embed=embed)
                    return

                try:
                    # Use search_source to get info first
                    info = await YTDLSource.search_source(query, loop=asyncio.get_running_loop())
                    if info:
                        title = info.get("title", "Unknown Title")
                        url = info.get("webpage_url", query)
                        thumbnail = info.get("thumbnail", None)
                        duration = info.get("duration", 0)
                        uploader = info.get("uploader", "Unknown")

                        queue.append({"url": url, "title": title, "type": "url"})
                        self._schedule_queue_save(ctx.guild.id)

                        # 🎨 PREMIUM YOUTUBE EMBED
                        embed = discord.Embed(
                            title=f"{Emojis.MUSIC} Added to Queue",
                            description=f"**[{title}]({url})**",
                            color=Colors.YOUTUBE,
                        )
                        if thumbnail:
                            embed.set_thumbnail(url=thumbnail)

                        # Track Info
                        embed.add_field(
                            name=f"{Emojis.CLOCK} Duration",
                            value=f"`{format_duration(duration)}`",
                            inline=True,
                        )
                        embed.add_field(
                            name=f"{Emojis.QUEUE} Position", value=f"`#{len(queue)}`", inline=True
                        )
                        embed.add_field(
                            name=f"{Emojis.MICROPHONE} Channel", value=uploader[:20], inline=True
                        )

                        embed.set_footer(
                            text=f"Requested by {ctx.author.display_name}",
                            icon_url=ctx.author.display_avatar.url,
                        )

                        await ctx.send(embed=embed)
                    else:
                        # Truncate query for safe embed display
                        safe_query = query[:100] + "..." if len(query) > 100 else query
                        safe_query = discord.utils.escape_markdown(safe_query)
                        embed = discord.Embed(
                            description=(f"{Emojis.CROSS} No results found for: {safe_query}"),
                            color=Colors.ERROR,
                        )
                        await ctx.send(embed=embed)
                        return
                except discord.DiscordException as e:
                    embed = discord.Embed(
                        title=f"{Emojis.CROSS} Error",
                        description="เกิดข้อผิดพลาดในการค้นหา กรุณาลองใหม่",
                        color=Colors.ERROR,
                    )
                    await ctx.send(embed=embed)
                    logger.error("Search error (Discord): %s", e)
                    return
                except OSError as e:
                    embed = discord.Embed(
                        title=f"{Emojis.CROSS} Error",
                        description="เกิดข้อผิดพลาดกับไฟล์ กรุณาลองใหม่",
                        color=Colors.ERROR,
                    )
                    await ctx.send(embed=embed)
                    logger.error("Search error (file): %s", e)
                    return
                except yt_dlp.DownloadError as e:
                    embed = discord.Embed(
                        title=f"{Emojis.CROSS} Error",
                        description="ไม่สามารถดาวน์โหลดได้ กรุณาลองใหม่",
                        color=Colors.ERROR,
                    )
                    await ctx.send(embed=embed)
                    logger.error("Search error (download): %s", e)
                    return

        # If not playing, start playing
        if (
            ctx.voice_client
            and not ctx.voice_client.is_playing()  # type: ignore[attr-defined]
            and not ctx.voice_client.is_paused()  # type: ignore[attr-defined]
        ):
            await self.play_next(ctx)

    @commands.hybrid_command(name="skip", aliases=["s"])  # type: ignore[arg-type]
    @commands.guild_only()
    async def skip(self, ctx):
        """ข้ามเพลงปัจจุบัน."""
        # Accept either is_playing OR is_paused — previously a paused track
        # couldn't be skipped because the gate required is_playing only,
        # forcing the user to !resume first just to !skip.
        if ctx.voice_client and (ctx.voice_client.is_playing() or ctx.voice_client.is_paused()):
            # Disable loop when skipping
            self._gs(ctx.guild.id).loop = False
            # Persist the loop=False change. play_next's queue-advance schedules
            # a save incidentally when more tracks follow, but skipping the LAST
            # track leaves an empty queue that falls through play_next's
            # len(queue)>0 gate without scheduling — so loop would silently
            # revert to ON after a hard restart. Schedule explicitly here.
            self._schedule_queue_save(ctx.guild.id)
            ctx.voice_client.stop()

            queue = self.get_queue(ctx)
            embed = discord.Embed(
                title=f"{Emojis.SKIP} ข้ามเพลง",
                description=(f"ปิดโหมดวนซ้ำ • เหลือ **{len(queue)}** เพลงในคิว"),
                color=Colors.INFO,
            )
            await ctx.send(embed=embed)
        else:
            embed = discord.Embed(description=f"{Emojis.CROSS} ไม่มีเพลงให้ข้าม", color=Colors.ERROR)
            await ctx.send(embed=embed)

    @commands.command(name="queue", aliases=["q"])
    @commands.guild_only()
    async def queue(self, ctx):
        """แสดงรายการเพลงในคิว."""
        queue = self.get_queue(ctx)
        loop_status = f"{Emojis.CHECK}" if self._gs(ctx.guild.id).loop else f"{Emojis.CROSS}"

        if not queue:
            embed = discord.Embed(
                title=f"{Emojis.QUEUE} คิวว่าง",
                description="ไม่มีเพลงในคิว\nใช้ `!play <ชื่อเพลง>` เพื่อเพิ่มเพลง",
                color=Colors.STOP,
            )
            embed.add_field(name=f"{Emojis.LOOP} วนซ้ำ", value=loop_status, inline=True)
            await ctx.send(embed=embed)
        else:
            # Create fancy queue embed
            embed = discord.Embed(title=f"{Emojis.QUEUE} คิวเพลง", color=Colors.QUEUE)

            # Now Playing
            current = self._gs(ctx.guild.id).current_track or {}
            if current:
                now_playing = current.get("title", "Unknown")
                embed.add_field(
                    name=f"{Emojis.NOTES} Now Playing", value=f"**{now_playing}**", inline=False
                )

            # Queue List (with numbers). islice avoids materialising the full
            # deque just to slice the head off it.
            description = ""
            for i, item in enumerate(itertools.islice(queue, 10), 1):
                if isinstance(item, dict):
                    title = item.get("title", "Unknown")
                    title = title[:40] + "..." if len(title) > 40 else title
                    description += f"`{i}.` {title}\n"
                else:
                    description += f"`{i}.` {item[:40]}\n"

            if len(queue) > 10:
                description += f"\n*...and **{len(queue) - 10}** more tracks*"

            embed.add_field(
                name=f"{Emojis.QUEUE} Up Next ({len(queue)} tracks)",
                value=description if description else "No tracks",
                inline=False,
            )

            embed.add_field(name=f"{Emojis.LOOP} Loop", value=loop_status, inline=True)
            embed.add_field(name=f"{Emojis.VOLUME} Audio", value="`Premium HQ`", inline=True)

            embed.set_footer(text="ใช้ !skip เพื่อข้าม • !clear เพื่อล้างคิว")
            await ctx.send(embed=embed)

    @commands.hybrid_command(name="stop", aliases=["st"])  # type: ignore[arg-type]
    @commands.guild_only()
    async def stop(self, ctx):
        """หยุดเล่นและล้างคิว."""
        gs = self._gs(ctx.guild.id)
        gs.queue.clear()  # Clear in place so concurrent play_next sees empty
        gs.loop = False  # Disable loop
        gs.current_track = None
        self._schedule_queue_save(ctx.guild.id)

        # Cancel any pending auto-disconnect timer; otherwise a stop while
        # 24/7 mode is off can still trigger a delayed disconnect after
        # the user starts playing again.
        if gs.auto_disconnect_task is not None:
            gs.auto_disconnect_task.cancel()
            gs.auto_disconnect_task = None

        if ctx.voice_client:
            ctx.voice_client.stop()

        # Only change global presence if this is the last voice client
        if len(self.bot.voice_clients) <= 1:
            await self.bot.change_presence(
                activity=discord.Activity(type=discord.ActivityType.listening, name="คำสั่งเพลง")
            )

        embed = discord.Embed(
            title=f"{Emojis.STOP} หยุดแล้ว", description="หยุดเล่นและล้างคิวแล้ว", color=Colors.STOP
        )
        await ctx.send(embed=embed)

    @commands.command(name="clear", aliases=["cl", "clr"])
    @commands.guild_only()
    async def clear(self, ctx):
        """ล้างคิวเพลงทั้งหมด (แต่ไม่หยุดเพลงที่เล่นอยู่)."""
        gs = self._gs(ctx.guild.id)
        cleared_count = len(gs.queue)
        gs.queue.clear()
        self._schedule_queue_save(ctx.guild.id)

        embed = discord.Embed(
            title=f"{Emojis.CHECK} ล้างคิวแล้ว",
            description=f"ลบ **{cleared_count}** เพลงออกจากคิว",
            color=Colors.INFO,
        )
        embed.set_footer(text="เพลงปัจจุบันจะเล่นต่อ")
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="leave", aliases=["disconnect", "dc"])  # type: ignore[arg-type]
    @commands.guild_only()
    async def leave(self, ctx):
        """ออกจากช่องเสียง."""
        if ctx.voice_client:
            # Cleanup
            gs = self._gs(ctx.guild.id)
            gs.queue.clear()
            gs.loop = False
            gs.current_track = None
            self._schedule_queue_save(ctx.guild.id)

            # Cancel any pending auto-disconnect timer so it doesn't fire
            # against an already-disconnected voice client and re-enter
            # cleanup paths.
            if gs.auto_disconnect_task is not None:
                gs.auto_disconnect_task.cancel()
                gs.auto_disconnect_task = None

            await ctx.voice_client.disconnect()
            # Only change global presence if this was the last voice client.
            # ``== 0`` (not <= 1): disconnect() already removed this VC from
            # bot.voice_clients, so 1 here means another guild is playing.
            if len(self.bot.voice_clients) == 0:
                await self.bot.change_presence(
                    activity=discord.Activity(type=discord.ActivityType.listening, name="คำสั่งเพลง")
                )

            embed = discord.Embed(
                title=f"{Emojis.WAVE} Disconnected",
                description="Left the voice channel",
                color=Colors.STOP,
            )
            embed.set_footer(text="Use !join to reconnect")
            await ctx.send(embed=embed)
        else:
            embed = discord.Embed(
                description=(f"{Emojis.CROSS} Not connected to any voice channel"),
                color=Colors.ERROR,
            )
            await ctx.send(embed=embed)

    @commands.command(name="volume", aliases=["vol", "v"])
    @commands.guild_only()
    async def volume(self, ctx, volume: int | None = None):
        """ปรับระดับเสียง (0-200%)."""
        if volume is None:
            current_vol = int(self._gs(ctx.guild.id).volume * 100)
            embed = discord.Embed(
                title=f"{Emojis.VOLUME} Current Volume",
                description=f"**{current_vol}%**\n\nUse `!volume <0-200>` to adjust",
                color=Colors.INFO,
            )
            return await ctx.send(embed=embed)

        if not 0 <= volume <= 200:
            embed = discord.Embed(
                description=f"{Emojis.CROSS} Volume must be between 0 and 200", color=Colors.ERROR
            )
            return await ctx.send(embed=embed)

        self._gs(ctx.guild.id).volume = volume / 100.0
        # Persist so the new volume survives a non-graceful restart (same
        # sidecar-persistence reason as loop/247).
        self._schedule_queue_save(ctx.guild.id)

        # Apply to current player if playing
        if ctx.voice_client and ctx.voice_client.source:
            if isinstance(ctx.voice_client.source, discord.PCMVolumeTransformer):
                ctx.voice_client.source.volume = volume / 100.0

        # Volume bar visualization
        bar_length = 10
        filled = int((volume / 200) * bar_length)
        volume_bar = "█" * filled + "░" * (bar_length - filled)

        embed = discord.Embed(
            title=f"{Emojis.VOLUME} Volume Set",
            description=f"`[{volume_bar}]` **{volume}%**",
            color=Colors.RESUMED,
        )
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="247", aliases=["24/7", "stay", "nonstop"])  # type: ignore[arg-type]
    @commands.guild_only()
    @commands.has_permissions(manage_channels=True)
    async def mode_247_toggle(self, ctx):
        """เปิด/ปิดโหมด 24/7 - Bot อยู่ในห้องตลอดเวลา."""
        guild_id = ctx.guild.id
        current = self._gs(guild_id).mode_247

        # Toggle mode
        self._gs(guild_id).mode_247 = not current
        new_state = self._gs(guild_id).mode_247
        # Persist immediately: this is the setting whose loss the sidecar was
        # built to prevent (a hard restart with mode_247 silently reverted to
        # False makes a 24/7 channel auto-disconnect).
        self._schedule_queue_save(guild_id)

        if new_state:
            # Cancel any pending auto-disconnect
            task = self._gs(guild_id).auto_disconnect_task
            if task is not None:
                task.cancel()
                self._gs(guild_id).auto_disconnect_task = None

            embed = discord.Embed(
                title=f"{Emojis.CHECK} 24/7 Mode Enabled",
                description=("Bot จะอยู่ในห้องเสียงตลอดเวลา\nไม่ออกอัตโนมัติเมื่อไม่มีคน"),
                color=Colors.RESUMED,
            )
            embed.set_footer(text="Use !247 again to disable")
        else:
            embed = discord.Embed(
                title=f"{Emojis.CROSS} 24/7 Mode Disabled",
                description="Bot จะออกอัตโนมัติเมื่อไม่มีคนในห้อง",
                color=Colors.STOP,
            )

        await ctx.send(embed=embed)

    @mode_247_toggle.error
    async def mode_247_error(self, ctx, error):
        """Handle permission errors for 24/7 command."""
        if isinstance(error, commands.MissingPermissions):
            embed = discord.Embed(
                description=f"{Emojis.CROSS} คุณต้องมีสิทธิ์ `Manage Channels` ในการใช้คำสั่งนี้",
                color=Colors.ERROR,
            )
            await ctx.send(embed=embed)
        else:
            raise error

    @commands.command(name="shuffle", aliases=["sh", "mix"])
    @commands.guild_only()
    async def shuffle(self, ctx):
        """สุ่มลำดับเพลงในคิว."""
        queue = self.get_queue(ctx)

        if len(queue) < 2:
            embed = discord.Embed(
                description=f"{Emojis.CROSS} Need at least 2 tracks in queue to shuffle",
                color=Colors.ERROR,
            )
            return await ctx.send(embed=embed)

        # Convert deque to list for O(n) shuffle, then replace
        items = list(queue)
        random.shuffle(items)
        queue.clear()
        queue.extend(items)
        self._schedule_queue_save(ctx.guild.id)

        embed = discord.Embed(
            title=f"{Emojis.SPARKLES} Queue Shuffled!",
            description=f"Shuffled **{len(queue)}** tracks",
            color=Colors.PLAYING,
        )

        # Show first 3 tracks after shuffle
        preview = ""
        for i, item in enumerate(itertools.islice(queue, 3), 1):
            title = item.get("title", "Unknown") if isinstance(item, dict) else str(item)
            title = title[:30] + "..." if len(title) > 30 else title
            preview += f"`{i}.` {title}\n"
        if len(queue) > 3:
            preview += f"*...and {len(queue) - 3} more*"

        embed.add_field(name="Up Next", value=preview, inline=False)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="remove", aliases=["rm", "del"])  # type: ignore[arg-type]
    @commands.guild_only()
    async def remove(self, ctx, position: int | None = None):
        """ลบเพลงออกจากคิวตามตำแหน่ง."""
        if position is None:
            embed = discord.Embed(
                description=f"{Emojis.CROSS} Please specify position: `!remove <position>`",
                color=Colors.ERROR,
            )
            return await ctx.send(embed=embed)

        queue = self.get_queue(ctx)

        if not queue:
            embed = discord.Embed(description=f"{Emojis.CROSS} Queue is empty", color=Colors.ERROR)
            return await ctx.send(embed=embed)

        if position < 1 or position > len(queue):
            embed = discord.Embed(
                description=f"{Emojis.CROSS} Invalid position. Queue has {len(queue)} tracks",
                color=Colors.ERROR,
            )
            return await ctx.send(embed=embed)

        removed = queue[position - 1]
        del queue[position - 1]
        # Persist the change so a bot restart doesn't bring the removed
        # track back. The shuffle command does the same thing — without
        # this, ``!remove`` was effectively a memory-only operation
        # that silently regressed across the next ``save_queue`` cycle.
        self._schedule_queue_save(ctx.guild.id)
        title = removed.get("title", "Unknown") if isinstance(removed, dict) else str(removed)

        embed = discord.Embed(
            title=f"{Emojis.CHECK} Track Removed",
            description=f"Removed **{title}** from position {position}",
            color=Colors.INFO,
        )
        embed.add_field(name="Queue", value=f"`{len(queue)}` tracks remaining", inline=True)
        await ctx.send(embed=embed)

    @commands.command(name="seek", aliases=["sk"])
    @commands.guild_only()
    async def seek(self, ctx, position: str | None = None):
        """ข้ามไปยังเวลาที่ต้องการ (MM:SS หรือ seconds)."""
        if not position:
            embed = discord.Embed(
                description=f"{Emojis.CROSS} ระบุเวลา: `!seek 1:30` หรือ `!seek 90`",
                color=Colors.ERROR,
            )
            return await ctx.send(embed=embed)

        if not ctx.voice_client or (
            not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused()
        ):
            embed = discord.Embed(
                description=f"{Emojis.CROSS} Nothing is playing", color=Colors.ERROR
            )
            return await ctx.send(embed=embed)

        # Parse time
        try:
            if ":" in position:
                parts = position.split(":")
                if len(parts) == 2:
                    minutes, seconds = map(int, parts)
                    if minutes < 0 or seconds < 0 or seconds >= 60:
                        raise ValueError("Invalid time values")
                    seek_time = minutes * 60 + seconds
                elif len(parts) == 3:
                    hours, minutes, seconds = map(int, parts)
                    if hours < 0 or minutes < 0 or minutes >= 60 or seconds < 0 or seconds >= 60:
                        raise ValueError("Invalid time values")
                    seek_time = hours * 3600 + minutes * 60 + seconds
                else:
                    raise ValueError("Invalid format")
            else:
                seek_time = int(position)
                if seek_time < 0:
                    raise ValueError("Time cannot be negative")
        except ValueError as e:
            error_msg = str(e)
            if "Invalid format" in error_msg or "invalid literal" in error_msg.lower():
                msg = f"{Emojis.CROSS} รูปแบบเวลาไม่ถูกต้อง ใช้: `1:30` หรือ `90`"
            else:
                msg = f"{Emojis.CROSS} ค่าเวลาไม่ถูกต้อง: {error_msg}"
            embed = discord.Embed(description=msg, color=Colors.ERROR)
            return await ctx.send(embed=embed)

        guild_id = ctx.guild.id
        track_info = self._gs(guild_id).current_track

        if not track_info:
            embed = discord.Embed(
                description=f"{Emojis.CROSS} No track info found", color=Colors.ERROR
            )
            return await ctx.send(embed=embed)

        # Get track duration. Use ``or 0`` (not a get-default) because livestreams /
        # malformed metadata store the key with value None, which a ``, 0`` default
        # would NOT normalize — leaving the ``seek_time > duration`` compare below to
        # raise TypeError (int > None) before the try/except is entered.
        duration = track_info.get("data", {}).get("duration") or 0
        if duration == 0:
            embed = discord.Embed(
                description=f"{Emojis.CROSS} Cannot seek in this track (unknown duration)",
                color=Colors.ERROR,
            )
            return await ctx.send(embed=embed)
        if seek_time > duration:
            embed = discord.Embed(
                description=(
                    f"{Emojis.CROSS} Cannot seek beyond track duration "
                    f"({format_duration(duration)})"
                ),
                color=Colors.ERROR,
            )
            return await ctx.send(embed=embed)

        # Stop current playback and restart with seek
        self._gs(guild_id).fixing = True
        try:
            ctx.voice_client.stop()

            filename = track_info["filename"]
            data = track_info["data"]

            # Verify the file still exists. The previous track's
            # after_playing callback may have already deleted it (loop=False
            # path calls safe_delete on track end), in which case ffmpeg
            # would silently produce no audio and the user just sees the
            # "playing" UI without sound. Surface the issue instead.
            from pathlib import Path as _P

            if not filename or not await asyncio.to_thread(_P(filename).exists):
                self._gs(guild_id).fixing = False
                # Honor any cleanup deferred while we held fixing (mirrors fix):
                # a concurrent leave/kick during the exists() await above arms
                # cleanup_pending, which nothing else would drain.
                await self._drain_pending_cleanup(guild_id, ctx)
                embed = discord.Embed(
                    title="Cannot Seek",
                    description=(
                        f"{Emojis.CROSS} Source file is no longer available. "
                        "Re-add the track to the queue and try again."
                    ),
                    color=Colors.ERROR,
                )
                return await ctx.send(embed=embed)

            # Get ffmpeg options with seek
            current_options = get_ffmpeg_options(stream=False, start_time=seek_time)

            player = YTDLSource(
                discord.FFmpegPCMAudio(
                    filename, **current_options, executable=get_ffmpeg_executable()
                ),
                data=data,
                filename=filename,
            )

            player.volume = self._gs(guild_id).volume
            track_info["start_time"] = time.time() - seek_time

            # Capture voice_client reference for the .play() call below;
            # the after-callback must look up the LIVE voice_client via
            # ``ctx.guild.voice_client`` so a leave+rejoin between the
            # ``play`` call and the callback firing doesn't leave us
            # checking ``is_connected()`` on a stale, dead VC and skip
            # the queue-rearm (matches the after_playing / after_playing_fix
            # pattern fixed in the prior audit).
            vc_seek = ctx.voice_client

            def after_seek(error):
                # Same entry guard as every other after-callback: a newer
                # !seek/!fix sets fixing=True and stops THIS player on
                # purpose. Without the guard, this callback fired anyway,
                # clobbered the new command's flag back to False and deleted
                # the very file the new command was about to replay. The
                # success-path reset now happens in the seek command itself,
                # right after vc_seek.play() succeeds.
                if self._gs(guild_id).fixing:
                    return

                # Look up the live voice_client at callback time. The
                # captured ``vc_seek`` reference is only used as a last
                # resort if the lookup fails (e.g. guild went away).
                live_vc = ctx.guild.voice_client if ctx.guild else None
                vc_check = live_vc or vc_seek

                # Guard: Check if voice_client is still valid
                if not vc_check or not vc_check.is_connected():
                    if not self._gs(guild_id).loop and filename:
                        self._safe_run_coroutine(self.safe_delete(filename))
                    return

                if not self._gs(guild_id).loop and filename:
                    self._safe_run_coroutine(self.safe_delete(filename))
                if error:
                    logger.error("Seek player error: %s", error)

                # Guard: Don't schedule if already playing or paused
                if vc_check.is_playing() or vc_check.is_paused():
                    return

                self._safe_run_coroutine(self.play_next(ctx))

            try:
                vc_seek.play(player, after=after_seek)
                # Seek is live — release the flag NOW instead of in the
                # after-callback. Holding it for the whole remainder of the
                # track made cleanup_guild_data defer (cleanup_pending) into
                # a void nothing ever drained, and suppressed every other
                # after-callback for the duration.
                self._gs(guild_id).fixing = False
                # Seek can run while paused (the guard permits is_paused) but
                # leaves the client PLAYING, so clear any stale pause_start —
                # otherwise the next pause/resume would add a bogus paused
                # interval (mark_pause is idempotent) and corrupt elapsed math.
                self._gs(guild_id).pause_start = None
                # Drain any cleanup deferred during the fixing window. On this
                # success path the VC is connected, so _drain only clears the
                # transient flag; a real concurrent leave runs the cleanup.
                await self._drain_pending_cleanup(guild_id, ctx)
            except Exception as e:
                # Reset fixing flag if play() fails
                self._gs(guild_id).fixing = False
                # Clean up the orphaned FFmpegPCMAudio subprocess before re-raising
                try:
                    player.cleanup()
                except Exception as _e:
                    logger.debug("Seek player cleanup failed (non-critical): %s", _e)
                logger.error("Seek play error: %s", e)
                raise
        except Exception as e:
            self._gs(guild_id).fixing = False
            # Honor cleanup deferred during the fixing window before returning.
            await self._drain_pending_cleanup(guild_id, ctx)
            logger.error("Seek failed: %s", e)
            embed = discord.Embed(
                description=f"{Emojis.CROSS} Seek failed — กรุณาลองใหม่อีกครั้ง",
                color=Colors.ERROR,
            )
            await ctx.send(embed=embed)
            return

        embed = discord.Embed(
            title=f"{Emojis.PLAY} Seeking",
            description=f"Jumped to `{format_duration(seek_time)}`",
            color=Colors.RESUMED,
        )
        embed.add_field(
            name="Track", value=f"**{track_info.get('title', 'Unknown')}**", inline=False
        )
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="nowplaying", aliases=["np", "current"])  # type: ignore[arg-type]
    @commands.guild_only()
    async def nowplaying(self, ctx):
        """แสดงเพลงที่กำลังเล่นอยู่พร้อม progress."""
        guild_id = ctx.guild.id
        track_info = self._gs(guild_id).current_track

        if not track_info:
            embed = discord.Embed(
                description=f"{Emojis.CROSS} No track is currently playing", color=Colors.ERROR
            )
            return await ctx.send(embed=embed)

        if not ctx.voice_client or (
            not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused()
        ):
            embed = discord.Embed(
                description=f"{Emojis.CROSS} Nothing is playing", color=Colors.ERROR
            )
            return await ctx.send(embed=embed)

        # Calculate current position
        start_time = track_info.get("start_time", time.time())
        # ``or 0`` guards a persisted None duration (livestream / missing
        # yt-dlp metadata) — mirrors the seek command's guard.
        duration = track_info.get("data", {}).get("duration") or 0

        if ctx.voice_client.is_paused() and self._gs(guild_id).pause_start is not None:
            # If paused, use time when paused
            elapsed = self._gs(guild_id).pause_start - start_time
        else:
            elapsed = time.time() - start_time

        elapsed = min(elapsed, duration) if duration else elapsed
        # Lower-clamp too: clock skew between track start and pause_start can
        # make `elapsed` negative, which format_duration renders as garbage
        # (e.g. -5 -> "59:55"). create_progress_bar already clamps via max(0,…).
        elapsed = max(0, elapsed)

        # Create progress bar
        progress_bar = create_progress_bar(elapsed, duration)

        embed = discord.Embed(
            title=f"{Emojis.NOTES} Now Playing",
            description=f"**[{track_info.get('title', 'Unknown')}]"
            f"({track_info.get('data', {}).get('webpage_url', '')})**",
            color=Colors.PLAYING,
        )

        # Thumbnail
        thumbnail = track_info.get("data", {}).get("thumbnail")
        if thumbnail:
            embed.set_thumbnail(url=thumbnail)

        # Progress bar
        status = "⏸️ Paused" if ctx.voice_client.is_paused() else "▶️ Playing"
        embed.add_field(
            name=status,
            value=(
                f"`{progress_bar}`\n`{format_duration(elapsed)}` / `{format_duration(duration)}`"
            ),
            inline=False,
        )

        # Volume and Loop info
        current_vol = int(self._gs(guild_id).volume * 100)
        loop_status = "🔁 On" if self._gs(guild_id).loop else "🔁 Off"

        embed.add_field(name=f"{Emojis.VOLUME} Volume", value=f"`{current_vol}%`", inline=True)
        embed.add_field(name="Loop", value=f"`{loop_status}`", inline=True)

        # Queue info
        queue = self.get_queue(ctx)
        embed.add_field(name=f"{Emojis.QUEUE} Queue", value=f"`{len(queue)}` tracks", inline=True)

        embed.set_footer(text="Use !help for all commands")
        await ctx.send(embed=embed)

    # Owner ID for special commands visibility - use config value.
    # CREATOR_ID can be 0 if the env var is unset (constants_env.py default).
    # Treating 0 as a sentinel and skipping the check avoids the trap where
    # `if user.id == 0` is meaningless (no Discord user has ID 0) — and more
    # importantly, prevents accidental fail-OPEN if a future check inverted
    # the comparison.
    OWNER_ID = CREATOR_ID

    def _is_owner(self, ctx) -> bool:
        """True only if a real owner ID is configured AND it matches ctx.author."""
        return bool(self.OWNER_ID) and ctx.author.id == self.OWNER_ID

    @commands.command(name="help", aliases=["h"])
    async def help(self, ctx):
        """แสดงคำสั่งช่วยเหลือ."""
        embed = discord.Embed(
            title=f"{Emojis.STAR} Premium Music Bot",
            description="**High Quality Audio Streaming**\nPrefix: `!` • Premium HQ Audio",
            color=Colors.INFO,
        )

        # 🎧 Playback Controls
        embed.add_field(
            name=f"{Emojis.HEADPHONES} Playback Controls",
            value=(
                "`!play` `!p` - เล่นเพลง\n"
                "`!pause` `!pa` - หยุดชั่วคราว\n"
                "`!resume` - เล่นต่อ\n"
                "`!skip` `!s` - ข้ามเพลง\n"
                "`!stop` `!st` - หยุดเล่น\n"
                "`!seek` `!sk` - ข้ามไปเวลา\n"
                "`!loop` `!l` - วนซ้ำ\n"
                "`!fix` `!f` - แก้ไขเสียง"
            ),
            inline=True,
        )

        # 📜 Queue Management
        embed.add_field(
            name=f"{Emojis.QUEUE} Queue & Voice",
            value=(
                "`!queue` `!q` - ดูคิว\n"
                "`!shuffle` `!sh` - สุ่มคิว\n"
                "`!remove` `!rm` - ลบจากคิว\n"
                "`!clear` `!cl` - ล้างคิว\n"
                "`!np` - เพลงปัจจุบัน\n"
                "`!volume` `!v` - ปรับเสียง\n"
                "`!247` - โหมด 24/7\n"
                "`!join` `!j` - เข้าห้อง\n"
                "`!leave` `!dc` - ออก"
            ),
            inline=True,
        )

        # 🧠 AI Commands
        embed.add_field(
            name=f"{Emojis.SPARKLES} AI Assistant",
            value=(
                "`!chat` `!ask` - คุยกับ AI\n"
                "`!thinking` - เปิด/ปิด Thinking\n"
                "`!streaming` - เปิด/ปิด Streaming\n"
                "`!reset_ai` `!rst` - รีเซ็ต AI"
            ),
            inline=True,
        )

        # Audio Quality Info
        embed.add_field(
            name=f"{Emojis.VOLUME} Audio Quality",
            value=("```\n• Codec: Opus/AAC\n• Sample: 48kHz Stereo\n• Quality: Premium HQ\n```"),
            inline=False,
        )

        # 🔧 Owner-only commands (visible only to owner)
        if self._is_owner(ctx):
            embed.add_field(
                name="🔧 Owner Commands",
                value=(
                    "`!link_memory` `!lm` - คัดลอกความจำ AI\n"
                    "`!move_memory` `!mm` - ย้ายความจำ AI\n"
                    "`!resend` `!rs` - ส่งข้อความ AI ใหม่\n"
                    "`!ratelimit` `!rl` - สถิติ Rate Limit"
                ),
                inline=False,
            )

        if self.bot.user and self.bot.user.display_avatar:
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        # No hardcoded version — the old "v3.2" footer drifted from every
        # release (project is versioned in pyproject.toml).
        embed.set_footer(text="Music Bot • !h for help")

        await ctx.send(embed=embed)

    async def cleanup_cache(self):
        """Clean up unused files in temp directory."""
        temp_dir = Path("temp")
        if not await asyncio.to_thread(temp_dir.exists):
            return 0, 0

        # Snapshot current_track filenames on the event loop first — iterating
        # self._guild_states inside a worker thread can raise "dictionary
        # changed size during iteration" if a guild state is added/removed
        # concurrently. The list() around .values() also guards this loop-thread
        # read against a concurrent _gs()/setdefault insert on the AudioPlayer
        # after-callback thread. Only the Path.resolve() filesystem I/O is deferred.
        raw_in_use = [
            gs.current_track["filename"]
            for gs in list(self._guild_states.values())
            if gs.current_track and "filename" in gs.current_track
        ]

        def _resolve_in_use(names: list[str]) -> set[str]:
            # Normalize paths to handle potential differences. Guard each
            # resolve() per-item: a path with OS-rejected chars / reserved
            # names would otherwise abort the whole comprehension and let the
            # exception escape to clearcache / on_ready (mirrors the per-entry
            # guards in _cleanup below and _periodic_temp_cleanup._cleanup_sync).
            resolved: set[str] = set()
            for n in names:
                try:
                    resolved.add(str(Path(n).resolve()))
                except (OSError, ValueError):
                    continue
            return resolved

        in_use_files = await asyncio.to_thread(_resolve_in_use, raw_in_use)

        deleted_count = 0
        freed_bytes = 0

        # Files modified within this grace window are assumed to be in-flight
        # downloads that haven't been registered as current_track yet.
        # Protects against deleting a file between yt-dlp finishing the download
        # and play_next() claiming it.
        mtime_grace_seconds = 120.0
        now_ts = time.time()

        # Run in executor to avoid blocking
        def _cleanup():
            nonlocal deleted_count, freed_bytes
            for filepath in temp_dir.iterdir():
                try:
                    abs_path = str(filepath.resolve())
                except (OSError, ValueError):
                    # A path component is unreadable / has OS-rejected chars —
                    # skip this one entry instead of aborting the whole sweep
                    # (mirrors _periodic_temp_cleanup._cleanup_sync's guard).
                    continue

                # Skip directories
                if filepath.is_dir():
                    continue

                # Check if file is in use
                if abs_path in in_use_files:
                    continue

                # Skip recently-modified files (likely in-flight downloads)
                try:
                    if now_ts - filepath.stat().st_mtime < mtime_grace_seconds:
                        continue
                except OSError:
                    # File was removed between iterdir and stat — move on
                    continue

                try:
                    # Reuse the stat() result from the mtime check above
                    # via filepath.stat() — actually capture it once. We
                    # already passed the mtime check above so the file
                    # existed then; use a fresh stat to read size, but
                    # cheaply tolerate it being deleted in the gap.
                    try:
                        size = filepath.stat().st_size
                    except FileNotFoundError:
                        continue
                    filepath.unlink()
                    deleted_count += 1
                    freed_bytes += size
                except PermissionError:
                    # File is locked by another process — skip silently
                    # This is normal for temp files used by active terminals/tests
                    pass
                except OSError as e:
                    logger.warning("Failed to delete unused file %s: %s", filepath, e)
            return deleted_count, freed_bytes

        return await asyncio.get_running_loop().run_in_executor(None, _cleanup)

    @commands.hybrid_command(name="clearcache", aliases=["cc", "clean"])  # type: ignore[arg-type]
    @commands.has_permissions(manage_guild=True)
    async def clearcache(self, ctx):
        """ล้างไฟล์ขยะที่ไม่ได้ใช้งาน."""
        async with ctx.typing():
            count, size = await self.cleanup_cache()

            # Format size
            if size < 1024:
                size_str = f"{size} B"
            elif size < 1024 * 1024:
                size_str = f"{size / 1024:.2f} KB"
            else:
                size_str = f"{size / (1024 * 1024):.2f} MB"

            embed = discord.Embed(
                title=f"{Emojis.TOOLS} Cache Cleaned",
                description=f"Removed **{count}** unused files\nFreed **{size_str}**",
                color=Colors.INFO,
            )
            await ctx.send(embed=embed)

    # ==================== Error Handlers ====================

    @join.error
    async def join_error(self, ctx, error):
        """Handle errors for join command."""
        if isinstance(error, commands.BotMissingPermissions):
            missing = ", ".join(error.missing_permissions)
            embed = discord.Embed(
                title=f"{Emojis.CROSS} ไม่มีสิทธิ์",
                description=f"Bot ต้องมีสิทธิ์ `{missing}` เพื่อเข้าห้องเสียง\n"
                f"กรุณาตรวจสอบ Role ของ Bot ใน Server Settings",
                color=Colors.ERROR,
            )
            await ctx.send(embed=embed)
        else:
            raise error

    @play.error
    async def play_error(self, ctx, error):
        """Handle errors for play command."""
        if isinstance(error, commands.BotMissingPermissions):
            missing = ", ".join(error.missing_permissions)
            embed = discord.Embed(
                title=f"{Emojis.CROSS} ไม่มีสิทธิ์",
                description=f"Bot ต้องมีสิทธิ์ `{missing}` เพื่อเล่นเพลง\n"
                f"กรุณาตรวจสอบ Role ของ Bot ใน Server Settings",
                color=Colors.ERROR,
            )
            await ctx.send(embed=embed)
        else:
            raise error

    @commands.Cog.listener()
    async def on_ready(self):
        """Called when the cog is ready."""
        # Clean cache on startup — but only once per process. on_ready fires
        # on every reconnect, and re-scanning the temp dir on each ping is
        # wasted I/O.
        if not self._cleaned_temp_once:
            self._cleaned_temp_once = True
            count, size = await self.cleanup_cache()
            logger.info("🧹 Startup Cleanup: Removed %s files (%s bytes)", count, size)

        logger.info("ℹ️  %s is Online.", self.bot.user)


async def setup(bot):
    """Setup function to add the Music cog to the bot."""
    await bot.add_cog(Music(bot))
