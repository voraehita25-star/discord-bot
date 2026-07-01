"""Count Claude CLI session jsonl files for the dashboard's dedicated workdir.

Surveys every Claude Code project folder under ~/.claude/projects/ that could
hold dashboard-spawned sessions, plus the bot's sidecar tracking JSON, and
flags mismatches (e.g. the encoder bug where `_` is not replaced by `-`).
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKDIR = (ROOT / "data" / "claude_cli_workdir").resolve()
PROJECTS = Path.home() / ".claude" / "projects"


def encode_bot_style(path: Path) -> str:
    """The script's *expectation* of the bot's encoder.

    Must match cogs/ai_core/api/dashboard_chat_claude_cli.py
    :func:`_encode_claude_project_dirname`, which replaces *every*
    non-ASCII-alphanumeric char with ``-`` (including ``.`` and ``_``;
    consecutive specials are NOT collapsed). The old fixed-subset
    (``:``, ``\\``, ``/``, space, ``_``) omitted ``.`` and every other
    special, so any path segment containing a dot — a Windows profile like
    ``me.name`` or a versioned dir — pointed at a folder Claude Code never
    writes to, breaking every count below.
    """
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


def encode_claude_actual(path: Path) -> str:
    """Claude Code's actual encoding — delegate to the production encoder.

    Importing the authoritative ``_encode_claude_project_dirname`` (rather
    than re-implementing it) is what makes the MISMATCH warning below a real
    regression detector: it compares this script's *expectation*
    (:func:`encode_bot_style`) against the live production encoder, so the two
    diverge — and the warning fires — the moment production's encoding
    changes. If that heavy module can't be imported (this standalone
    maintenance script may run outside a configured bot env), fall back to the
    same inline formula so the survey still works.
    """
    try:
        from cogs.ai_core.api.dashboard_chat_claude_cli import (
            _encode_claude_project_dirname,
        )

        return _encode_claude_project_dirname(path)
    except Exception:
        return re.sub(r"[^A-Za-z0-9]", "-", str(path))


def list_jsonl(folder: Path) -> list[Path]:
    if not folder.exists():
        return []
    return sorted(folder.glob("*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)


def main() -> None:
    """Run the full survey. Guarded behind ``__main__`` so ``import
    count_cli_sessions`` (e.g. for unit testing the encoder helpers above)
    doesn't trigger ~/.claude scanning, sidecar reads, and stdout prints.
    """
    # The survey output uses ⚠️/✓/✗; force UTF-8 so it can't crash with
    # UnicodeEncodeError on a redirected cp874/cp1252 stdout.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    print("=" * 72)
    print("Claude CLI session-file survey")
    print("=" * 72)

    bot_encoded = encode_bot_style(WORKDIR)
    claude_encoded = encode_claude_actual(WORKDIR)
    print(f"Workdir abs              : {WORKDIR}")
    print(f"Bot encoder produces     : {bot_encoded}")
    print(f"Claude actual produces   : {claude_encoded}")

    if bot_encoded != claude_encoded:
        print()
        print("⚠️  MISMATCH — `delete_session_file()` looks at the wrong folder!")
        print(f"   Bot expects   : {PROJECTS / bot_encoded}")
        print(f"   Claude writes : {PROJECTS / claude_encoded}")

    print()
    print("-" * 72)

    bot_folder = PROJECTS / bot_encoded
    claude_folder = PROJECTS / claude_encoded
    # Compute the legacy-orphan folder from the actual repo root rather
    # than hardcoding the original developer's path. Other contributors
    # would always see "0 results" in this bucket otherwise.
    repo_root_folder = PROJECTS / encode_claude_actual(ROOT)

    # When the script's expectation (``encode_bot_style``) agrees with the
    # live production encoder (``encode_claude_actual``), bot_folder and
    # claude_folder resolve to the SAME directory. Dedupe by resolved path so
    # that folder isn't surveyed — and its jsonl files double-counted into
    # ``total`` — twice. If the two ever diverge, both are surveyed (and the
    # MISMATCH warning above will have already fired).
    candidate_surveys = [
        ("Bot/Claude workdir folder", bot_folder),
        ("Claude actual workdir folder", claude_folder),
        ("Repo-root folder (legacy pre-isolation orphans)", repo_root_folder),
    ]
    surveys: list[tuple[str, Path]] = []
    _seen_paths: set[str] = set()
    for label, folder in candidate_surveys:
        key = str(folder.resolve())
        if key in _seen_paths:
            continue
        _seen_paths.add(key)
        surveys.append((label, folder))

    total = 0
    for label, folder in surveys:
        files = list_jsonl(folder)
        total += len(files)
        print()
        print(f"{label}")
        print(f"  path  : {folder}")
        print(f"  exists: {folder.exists()}  jsonl count: {len(files)}")
        for f in files[:5]:
            size_kb = f.stat().st_size / 1024
            dt = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            print(f"    {f.name}  {size_kb:7.1f} KB  {dt}")
        if len(files) > 5:
            print(f"    ... and {len(files) - 5} more")

    print()
    print("-" * 72)
    print(f"TOTAL .jsonl session files across all dashboard locations: {total}")

    print()
    print("-" * 72)
    sidecar = ROOT / "data" / "claude_cli_sessions.json"
    print(f"Sidecar JSON : {sidecar}")
    data: dict[str, str] = {}
    if sidecar.exists():
        try:
            raw = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            # Don't crash the whole survey on a partially-written or
            # corrupted sidecar — operators run this script precisely to
            # diagnose CLI session state, and an opaque stack trace here
            # hides the file count info above.
            print(f"(sidecar unreadable: {exc})")
            raw = None

        if isinstance(raw, dict):
            data = raw
            print(f"Tracked      : {len(data)} conversation(s)")
            for cid, sid in data.items():
                target = claude_folder / f"{sid}.jsonl"
                status = "✓ exists" if target.exists() else "✗ missing"
                print(f"  conv={cid}")
                print(f"  sess={sid}  ({status} at {target.parent.name})")
        elif raw is not None:
            # Legacy / unexpected schema (e.g. top-level array) — don't
            # iterate ``.items()`` on a non-dict; just report the shape.
            print(f"(sidecar has unexpected shape: {type(raw).__name__})")
    else:
        print("(no sidecar)")

    print()
    # ``total`` counts files on disk; ``data`` counts tracked conversations.
    # A negative result is nonsense (sidecar tracks more than exist on disk
    # = stale entries), so floor at 0 and surface the gap separately.
    tracked = len(data)
    orphans = max(0, total - tracked)
    stale = max(0, tracked - total)
    print(f"Orphaned (untracked by sidecar) : {orphans}")
    if stale:
        print(f"Stale tracked (sidecar > files) : {stale}")


if __name__ == "__main__":
    main()
