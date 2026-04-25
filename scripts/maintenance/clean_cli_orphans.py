"""Delete orphan Claude CLI session files (not tracked by the sidecar).

Pass `--apply` to actually delete; default is dry-run.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKDIR = (ROOT / "data" / "claude_cli_workdir").resolve()
SIDECAR = ROOT / "data" / "claude_cli_sessions.json"


def encode(path: Path) -> str:
    s = str(path)
    for ch in (":", "\\", "/", " ", "_"):
        s = s.replace(ch, "-")
    return s


PROJECTS = Path.home() / ".claude" / "projects" / encode(WORKDIR)

apply = "--apply" in sys.argv

tracked: set[str] = set()
if SIDECAR.exists():
    tracked = set(json.loads(SIDECAR.read_text(encoding="utf-8")).values())

print(f"Workdir folder      : {PROJECTS}")
print(f"Tracked session ids : {len(tracked)}")
for sid in tracked:
    print(f"  protect: {sid}")
print()

deleted_files = 0
deleted_dirs = 0
deleted_bytes = 0
stray_files = 0

if PROJECTS.exists():
    for entry in sorted(PROJECTS.iterdir()):
        if entry.is_file() and entry.suffix == ".jsonl":
            sid = entry.stem
            if sid in tracked:
                print(f"  KEEP   {entry.name}  (tracked)")
                continue
            size = entry.stat().st_size
            print(f"  DELETE {entry.name}  ({size / 1024:.1f} KB)")
            deleted_bytes += size
            if apply:
                entry.unlink()
            deleted_files += 1
        elif entry.is_dir():
            sid = entry.name
            if sid in tracked:
                print(f"  KEEP   dir {entry.name}/  (tracked)")
                continue
            print(f"  DELETE dir {entry.name}/")
            if apply:
                shutil.rmtree(entry)
            deleted_dirs += 1

# Stray non-jsonl files in the *bot* workdir (data/claude_cli_workdir/)
if WORKDIR.exists():
    for entry in WORKDIR.iterdir():
        if entry.is_file():
            print(f"  DELETE stray {WORKDIR / entry.name}  ({entry.stat().st_size / 1024:.1f} KB)")
            if apply:
                entry.unlink()
            stray_files += 1

print()
mode = "APPLIED" if apply else "DRY RUN — re-run with --apply to actually delete"
print(f"[{mode}] {deleted_files} jsonl + {deleted_dirs} dir + {stray_files} stray; "
      f"freed {deleted_bytes / (1024 * 1024):.1f} MB")
