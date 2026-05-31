"""Manual probe for AI subsystem behavior — exercise each recent fix and a handful
of corner cases that the regular test suite doesn't directly cover.

Run: python scripts/dev/probe_ai_fixes.py
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure repo root on sys.path when run as a script
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


PASS = 0
FAIL = 0
ERRORS: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [OK]   {label}")
    else:
        FAIL += 1
        msg = f"  [FAIL] {label}"
        if detail:
            msg += f" — {detail}"
        ERRORS.append(msg)
        print(msg)


# ---------------------------------------------------------------------------
# rag.py tz-aware vs naive datetime fix
# ---------------------------------------------------------------------------
def probe_rag_age_days() -> None:
    print("\n[rag.py] tz-aware vs naive datetime")
    from cogs.ai_core.memory.rag import MemoryResult  # noqa: F401

    # Reproduce the inner block from hybrid_search:
    def calc_age(created_at: str) -> int:
        age_days = 0
        try:
            created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            now = datetime.now(created.tzinfo)
            age_days = (now - created).days
        except (ValueError, TypeError, AttributeError):
            pass
        return age_days

    # Legacy naive timestamp ~10 days ago
    naive = (datetime.now() - __import__("datetime").timedelta(days=10)).isoformat()
    age = calc_age(naive)
    check("naive timestamp 10d ago -> age_days≈10", 8 <= age <= 12, f"got {age}")

    # ISO with Z suffix (UTC)
    z_ts = (
        (datetime.now(timezone.utc) - __import__("datetime").timedelta(days=5))
        .isoformat()
        .replace("+00:00", "Z")
    )
    age = calc_age(z_ts)
    check("'Z'-suffix UTC 5d ago -> age_days≈5", 3 <= age <= 7, f"got {age}")

    # Bad input shouldn't crash
    age = calc_age("")
    check("empty string -> age_days=0 (no crash)", age == 0)
    age = calc_age("not-a-date")
    check("garbage string -> age_days=0 (no crash)", age == 0)


# ---------------------------------------------------------------------------
# rag.py FAISSIndex add_single zero-norm guard
# ---------------------------------------------------------------------------
def probe_rag_zero_norm() -> None:
    print("\n[rag.py] FAISSIndex.add_single zero-norm rejection")
    try:
        import numpy as np

        from cogs.ai_core.memory.rag import FAISS_AVAILABLE, FAISSIndex
    except ImportError as e:
        print(f"  [SKIP] FAISS unavailable: {e}")
        return
    if not FAISS_AVAILABLE:
        print("  [SKIP] FAISS_AVAILABLE=False")
        return

    idx = FAISSIndex(dimension=4)
    zero = np.zeros(4, dtype=np.float32)
    raised = False
    try:
        idx.add_single(zero, memory_id=42)
    except ValueError:
        raised = True
    check("zero-norm vector raises ValueError (no silent skip)", raised)

    # Non-zero still works
    nonzero = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
    idx.add_single(nonzero, memory_id=1)
    check("non-zero vector adds successfully", idx.is_initialized)
    check("id_map updated for first add", idx.id_map == [1])

    # Wrong dim still raises ValueError
    raised = False
    try:
        idx.add_single(np.zeros(8, dtype=np.float32), memory_id=2)
    except ValueError:
        raised = True
    check("wrong-dim vector raises ValueError", raised)


# ---------------------------------------------------------------------------
# tool_executor None-arg validation
# ---------------------------------------------------------------------------
async def probe_tool_executor_none_args() -> None:
    print("\n[tool_executor] None / missing arg validation")
    from types import SimpleNamespace

    from cogs.ai_core.tools.tool_executor import execute_tool_call

    class _DummyGuild:
        def __init__(self):
            self.id = 1
            self.name = "test"
            self.text_channels = []
            self.categories = []
            self.roles = []
            self.members = []

        def get_channel(self, _id):
            return None

        async def fetch_member(self, _id):
            return None

    class _DummyChannel:
        def __init__(self):
            self.id = 999
            self.guild = _DummyGuild()
            self.name = "general"
            self.sent: list[str] = []

        async def send(self, *args, **kwargs):
            content = args[0] if args else kwargs.get("content", "")
            self.sent.append(content)

    class _DummyUser:
        display_name = "tester"
        guild_permissions = type("P", (), {"administrator": True})()

    ch = _DummyChannel()
    bot = object()

    def call(name: str, args: dict):
        return SimpleNamespace(name=name, args=args)

    # get_user_info with None target -> should NOT crash with AttributeError;
    # should return a string explaining the failure.
    try:
        result = await execute_tool_call(
            bot, ch, _DummyUser(), call("get_user_info", {"target": None})
        )
        ok = isinstance(result, str) and ("Failed" in result or "required" in result.lower())
        check("get_user_info(target=None) returns error string (no crash)", ok, f"got: {result!r}")
    except (AttributeError, TypeError) as e:
        check("get_user_info(target=None) returns error string (no crash)", False, f"raised: {e}")

    # read_channel with missing channel_name
    try:
        result = await execute_tool_call(bot, ch, _DummyUser(), call("read_channel", {}))
        ok = isinstance(result, str) and ("Failed" in result or "required" in result.lower())
        check(
            "read_channel(no channel_name) returns error string (no crash)", ok, f"got: {result!r}"
        )
    except (AttributeError, TypeError) as e:
        check(
            "read_channel(no channel_name) returns error string (no crash)", False, f"raised: {e}"
        )

    # get_user_info with whitespace-only target
    try:
        result = await execute_tool_call(
            bot, ch, _DummyUser(), call("get_user_info", {"target": "   "})
        )
        ok = isinstance(result, str) and ("Failed" in result or "required" in result.lower())
        check("get_user_info(target='   ') rejected (no crash)", ok, f"got: {result!r}")
    except (AttributeError, TypeError) as e:
        check("get_user_info(target='   ') rejected (no crash)", False, f"raised: {e}")


# ---------------------------------------------------------------------------
# state_tracker.from_dict locking
# ---------------------------------------------------------------------------
def probe_state_tracker_locking() -> None:
    print("\n[state_tracker] from_dict acquires the lock")
    import threading

    from cogs.ai_core.memory.state_tracker import CharacterStateTracker

    tracker = CharacterStateTracker()

    # Hammer from_dict + cleanup_old_states from multiple threads to make sure
    # neither corrupts the dict (would surface as RuntimeError or wrong size).
    def writer(i: int):
        for _ in range(100):
            tracker.from_dict(
                channel_id=i,
                data={"states": {"alpha": {"name": "alpha", "last_accessed": 0}}, "scene": f"s{i}"},
            )

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # If from_dict didn't lock, dict size could be off
    check(
        "concurrent from_dict on 8 channels yields exactly 8 entries",
        len(tracker._states) == 8,
        f"got {len(tracker._states)}",
    )


# ---------------------------------------------------------------------------
# session_mixin: timeout path keeps chat in memory
# ---------------------------------------------------------------------------
async def probe_session_save_timeout() -> None:
    print("\n[session_mixin] save timeout doesn't evict")
    from unittest.mock import AsyncMock, MagicMock, patch

    from cogs.ai_core.session_mixin import SessionMixin

    # SessionMixin expects various dict attrs; build a stub holder
    class Holder(SessionMixin):
        def __init__(self):
            self.bot = MagicMock()
            self.bot.is_closed = MagicMock(return_value=False)
            self.chats = {123: {"history": [{"role": "user", "parts": ["hello"]}]}}
            self.last_accessed = {123: 0.0}  # very stale
            self.seen_users = {123: set()}
            self.processing_locks = {}
            self.pending_messages = {}
            self.cancel_flags = {}
            self.streaming_enabled = {}
            self.current_typing_msg = {}

    h = Holder()

    async def slow_save(*_args, **_kwargs):
        await asyncio.sleep(60)  # will hit the wait_for(30s) timeout

    with patch("cogs.ai_core.session_mixin.save_history", new=AsyncMock(side_effect=slow_save)):
        # Drive one iteration of cleanup_inactive_sessions then break out.
        # The function is an infinite loop; we simulate with wait_for short timeout.
        h.bot.is_closed = MagicMock(side_effect=[False, True])  # one pass then exit
        try:
            await asyncio.wait_for(h.cleanup_inactive_sessions(), timeout=35)
        except (TimeoutError, asyncio.CancelledError):
            pass

    check(
        "channel kept in self.chats after save timeout (no data loss)",
        123 in h.chats,
        f"chats keys: {list(h.chats.keys())}",
    )


# ---------------------------------------------------------------------------
# media_processor GIF: pre-check + iteration cap
# ---------------------------------------------------------------------------
def probe_media_processor_gif() -> None:
    print("\n[media_processor] GIF iteration cap (no decompression bomb)")
    try:
        import io as _io

        from PIL import Image

        from cogs.ai_core.media_processor import (
            _MAX_GIF_FRAMES,
            IMAGEIO_AVAILABLE,
            convert_gif_to_video,
        )
    except ImportError as e:
        print(f"  [SKIP] dependency missing: {e}")
        return
    if not IMAGEIO_AVAILABLE:
        print("  [SKIP] imageio unavailable")
        return

    # Build a tiny GIF that has a few frames (enough to exercise the loop
    # without actually trying to bomb memory).
    frames = []
    for i in range(8):
        img = Image.new("RGB", (8, 8), color=(i * 30, 0, 0))
        frames.append(img)
    buf = _io.BytesIO()
    frames[0].save(
        buf,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=80,
        loop=0,
    )
    gif_bytes = buf.getvalue()

    out = convert_gif_to_video(gif_bytes)
    check(
        "convert_gif_to_video returns mp4 bytes for 8-frame gif",
        isinstance(out, bytes | bytearray) and len(out) > 100,
    )

    # Verify _MAX_GIF_FRAMES is sane (sanity check the cap is in place)
    check(
        "_MAX_GIF_FRAMES is reasonable cap", 4 <= _MAX_GIF_FRAMES <= 1000, f"got {_MAX_GIF_FRAMES}"
    )


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------
async def main_async() -> None:
    probe_rag_age_days()
    probe_rag_zero_norm()
    await probe_tool_executor_none_args()
    probe_state_tracker_locking()
    await probe_session_save_timeout()
    probe_media_processor_gif()


def main() -> int:
    asyncio.run(main_async())
    print(f"\n========== Result: {PASS} passed, {FAIL} failed ==========")
    if ERRORS:
        for e in ERRORS:
            print(e)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
