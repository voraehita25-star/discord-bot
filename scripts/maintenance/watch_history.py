#!/usr/bin/env python3
"""Live ``tail -f`` viewer for the Discord AI chat history (``ai_history``).

Reads the bot's SQLite DB **read-only** and streams new rows as the running bot
writes them, formatted for humans (timestamp · channel · role · content).

Standalone by design — stdlib ``sqlite3`` only, no bot-package import — so it
runs from a stripped-PATH shell and can't drag in the heavy persona/RAG deps.

Usage:
    python scripts/maintenance/watch_history.py
    python scripts/maintenance/watch_history.py --channel 123456789012345678
    python scripts/maintenance/watch_history.py --tail 50 --interval 1 --full
    python scripts/maintenance/watch_history.py --no-color --ids

Stop with Ctrl+C.

Safety notes (mirrors the rest of scripts/maintenance/):
  - Opens ``file:<db>?mode=ro`` so it NEVER creates an empty DB and can never
    write/corrupt the live database the bot is using.
  - Anchors the DB path to the repo root via __file__, not the CWD.
  - Reconfigures stdout to UTF-8 up front — the Windows console codepage
    (cp1252/cp874) otherwise raises UnicodeEncodeError on Thai/Korean/emoji.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Repo root: scripts/maintenance/watch_history.py -> parents[2] is the root.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = PROJECT_ROOT / "data" / "bot_database.db"

# ---------------------------------------------------------------------------
# Terminal helpers
# ---------------------------------------------------------------------------


def _enable_utf8_stdout() -> None:
    """Force UTF-8 so non-ASCII content prints instead of crashing.

    The bot's history is mostly Thai (+ Korean dashboard names, emoji). On a
    legacy Windows codepage ``print`` raises UnicodeEncodeError mid-stream and
    kills the viewer. ``errors="replace"`` keeps it alive on any oddball byte.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            # line_buffering=True so each row flushes on its newline — without
            # it a redirected/piped stdout block-buffers and the "live" tail
            # only appears in bursts (or never, if killed before flush).
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass


def _supports_color(no_color: bool) -> bool:
    if no_color:
        return False
    if not sys.stdout.isatty():
        return False
    # Best-effort enable of ANSI on legacy Windows consoles (Win10+ Terminal /
    # conhost with VT). Harmless elsewhere.
    if sys.platform == "win32":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            # -11 = STD_OUTPUT_HANDLE; 0x0004 = ENABLE_VIRTUAL_TERMINAL_PROCESSING
            handle = kernel32.GetStdHandle(-11)
            mode = ctypes.c_uint32()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                kernel32.SetConsoleMode(handle, mode.value | 0x0004)
        except Exception:
            return False
    return True


class _C:
    """ANSI palette; all blanked when color is off."""

    def __init__(self, on: bool) -> None:
        self.dim = "\033[2m" if on else ""
        self.reset = "\033[0m" if on else ""
        self.user = "\033[36m" if on else ""  # cyan
        self.model = "\033[35m" if on else ""  # magenta
        self.chan = "\033[33m" if on else ""  # yellow
        self.bold = "\033[1m" if on else ""
        self.red = "\033[31m" if on else ""
        self.green = "\033[32m" if on else ""


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def _parse_ts(value: object) -> datetime | None:
    """Parse both stored timestamp shapes.

    ai_history mixes ISO-8601 ("2026-06-10T10:01:03+00:00", written by the
    Python save path) and SQLite's space form ("2026-06-10 10:01:03", from the
    CURRENT_TIMESTAMP default). Handle both; return UTC-aware or None.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    text = text.replace(" ", "T", 1) if "T" not in text and " " in text else text
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _fmt_time(value: object) -> str:
    parsed = _parse_ts(value)
    if parsed is None:
        return "  --:--:-- "
    # Show in local time so it lines up with the operator's clock.
    return parsed.astimezone().strftime("%H:%M:%S")


def _short_chan(channel_id: object) -> str:
    s = str(channel_id)
    return s if len(s) <= 8 else f"…{s[-6:]}"


def _one_line(content: object, width: int, full: bool) -> str:
    text = "" if content is None else str(content)
    # Collapse newlines/tabs so each message is one scannable line.
    text = " ".join(text.split())
    if full or len(text) <= width:
        return text
    return text[: width - 1] + "…"


def _render(row: sqlite3.Row, c: _C, width: int, full: bool, show_ids: bool) -> str:
    role = row["role"] or "?"
    if role == "user":
        icon, rcol, label = "👤", c.user, "user "
    elif role == "model":
        icon, rcol, label = "🤖", c.model, "model"
    else:
        icon, rcol, label = "•", "", f"{role:<5.5}"
    parts = [
        f"{c.dim}[{_fmt_time(row['timestamp'])}]{c.reset}",
        f"{c.chan}{_short_chan(row['channel_id']):>8.8}{c.reset}",
        f"{icon} {rcol}{label}{c.reset}",
    ]
    if show_ids:
        uid = row["user_id"]
        mid = row["message_id"]
        parts.append(f"{c.dim}u={uid or '-'} m={mid or '-'} #{row['id']}{c.reset}")
    parts.append(f": {_one_line(row['content'], width, full)}")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# DB access
# ---------------------------------------------------------------------------


def _connect(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise FileNotFoundError(
            f"Database not found: {db_path}\n"
            "Run the bot at least once so it creates data/bot_database.db, "
            "or pass --db <path>."
        )
    # mode=ro: never create, never write. uri=True required for the query
    # string. sqlite3 accepts the native path (backslashes + spaces and all)
    # in the URI filename, so no as_uri()/%20 escaping is needed. A WAL
    # database with an active writer (the running bot) reads fine read-only;
    # busy_timeout smooths over momentary write-locks.
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=3000")
    return conn


_COLUMNS = "id, channel_id, user_id, role, content, message_id, timestamp"


def _fetch(
    conn: sqlite3.Connection,
    after_id: int,
    channel: int | None,
    limit: int | None,
) -> list[sqlite3.Row]:
    # f-string only interpolates the fixed _COLUMNS constant; all user values
    # (after_id, channel, limit) are bound parameters.
    sql = f"SELECT {_COLUMNS} FROM ai_history WHERE id > ?"
    args: list[object] = [after_id]
    if channel is not None:
        sql += " AND channel_id = ?"
        args.append(channel)
    sql += " ORDER BY id ASC"
    if limit is not None:
        sql += " LIMIT ?"
        args.append(limit)
    return conn.execute(sql, args).fetchall()


def _initial_tail(
    conn: sqlite3.Connection, tail: int, channel: int | None
) -> list[sqlite3.Row]:
    """Last ``tail`` rows (chronological) to seed the view with context."""
    sql = f"SELECT {_COLUMNS} FROM ai_history"
    args: list[object] = []
    if channel is not None:
        sql += " WHERE channel_id = ?"
        args.append(channel)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(max(0, tail))
    rows = conn.execute(sql, args).fetchall()
    return list(reversed(rows))


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Live tail of the Discord AI chat history (ai_history).",
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="Path to bot_database.db")
    parser.add_argument(
        "--channel", type=int, default=None, help="Only show this Discord channel_id"
    )
    parser.add_argument(
        "--interval", type=float, default=2.0, help="Poll interval seconds (default 2.0)"
    )
    parser.add_argument(
        "--tail", type=int, default=20, help="Rows of history to print at start (default 20)"
    )
    parser.add_argument("--width", type=int, default=100, help="Max content width before truncation")
    parser.add_argument("--full", action="store_true", help="Never truncate content")
    parser.add_argument("--ids", action="store_true", help="Show user_id/message_id/row id")
    parser.add_argument("--no-color", action="store_true", help="Disable ANSI colors")
    args = parser.parse_args(argv)

    _enable_utf8_stdout()
    c = _C(_supports_color(args.no_color))

    db_path = args.db if args.db.is_absolute() else (PROJECT_ROOT / args.db)
    try:
        conn = _connect(db_path)
    except FileNotFoundError as exc:
        print(f"{c.red}{exc}{c.reset}", file=sys.stderr)
        return 1
    except sqlite3.OperationalError as exc:
        print(
            f"{c.red}Could not open {db_path} read-only: {exc}{c.reset}\n"
            "If the bot is stopped and the WAL wasn't checkpointed, start the "
            "bot once (or copy the DB) and retry.",
            file=sys.stderr,
        )
        return 1

    scope = f" channel {args.channel}" if args.channel is not None else " all channels"
    header = f"Discord AI history{scope} — {db_path.name}  (poll {args.interval}s, Ctrl+C to stop)"
    print(f"{c.bold}{c.green}┌─ {header}{c.reset}")

    try:
        seed = _initial_tail(conn, args.tail, args.channel)
        for row in seed:
            print(_render(row, c, args.width, args.full, args.ids))
        last_id = seed[-1]["id"] if seed else 0
        if not seed:
            print(f"{c.dim}(no history yet — waiting for the first message…){c.reset}")
        print(f"{c.dim}└─ live ●  waiting for new rows…{c.reset}")

        printed_waiting = True
        while True:
            time.sleep(max(0.2, args.interval))
            try:
                # LIMIT caps a catch-up burst (e.g. after a backlog) per tick;
                # remaining rows flush on the next poll because last_id advances.
                rows = _fetch(conn, last_id, args.channel, limit=500)
            except sqlite3.OperationalError as exc:
                # Transient "database is locked" under a write burst — skip this
                # tick, the next one retries. Don't die on a momentary lock.
                if "locked" in str(exc).lower():
                    continue
                raise
            if rows:
                if printed_waiting:
                    printed_waiting = False
                for row in rows:
                    print(_render(row, c, args.width, args.full, args.ids))
                    last_id = max(last_id, row["id"])
    except KeyboardInterrupt:
        print(f"\n{c.dim}stopped.{c.reset}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
