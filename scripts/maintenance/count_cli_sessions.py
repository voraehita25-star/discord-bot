"""Count Claude CLI session jsonl files for the dashboard's dedicated workdir.

Surveys every Claude Code project folder under ~/.claude/projects/ that could
hold dashboard-spawned sessions, plus the bot's sidecar tracking JSON, and
flags mismatches (e.g. the encoder bug where `_` is not replaced by `-`).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKDIR = (ROOT / "data" / "claude_cli_workdir").resolve()
PROJECTS = Path.home() / ".claude" / "projects"


def encode_bot_style(path: Path) -> str:
    """Match cogs/ai_core/api/dashboard_chat_claude_cli.py:_encode_claude_project_dirname."""
    s = str(path)
    for ch in (":", "\\", "/", " "):
        s = s.replace(ch, "-")
    return s


def encode_claude_actual(path: Path) -> str:
    """Claude Code's actual encoding also replaces `_` with `-`."""
    s = str(path)
    for ch in (":", "\\", "/", " ", "_"):
        s = s.replace(ch, "-")
    return s


def list_jsonl(folder: Path) -> list[Path]:
    if not folder.exists():
        return []
    return sorted(folder.glob("*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)


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
repo_root_folder = PROJECTS / "C--Users-ME-BOT-Discord"

surveys = [
    ("Bot-expected workdir folder (encoder uses underscore)", bot_folder),
    ("Claude actual workdir folder (encoder dashes underscore)", claude_folder),
    ("Repo-root folder (legacy pre-isolation orphans)", repo_root_folder),
]

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
if sidecar.exists():
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    print(f"Tracked      : {len(data)} conversation(s)")
    for cid, sid in data.items():
        target = claude_folder / f"{sid}.jsonl"
        status = "✓ exists" if target.exists() else "✗ missing"
        print(f"  conv={cid}")
        print(f"  sess={sid}  ({status} at {target.parent.name})")
else:
    print("(no sidecar)")

print()
orphans = total - (len(data) if sidecar.exists() and isinstance(data, dict) else 0)
print(f"Orphaned (untracked by sidecar) : {orphans}")
