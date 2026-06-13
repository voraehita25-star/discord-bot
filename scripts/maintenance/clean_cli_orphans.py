"""Delete orphan Claude CLI session files (not tracked by the sidecar).

Pass `--apply` to actually delete; default is dry-run.
"""

from __future__ import annotations

import json
import os
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


def main() -> int:
    apply = "--apply" in sys.argv

    # `--apply` is destructive (unlink + rmtree). Require an explicit "yes" so
    # accidental --apply on the wrong workdir doesn't wipe session data.
    if apply and "--yes" not in sys.argv:
        print("⚠️  --apply will delete files in:")
        print(f"    {PROJECTS}")
        print(f"    {WORKDIR}")
        confirm = input("Type 'yes' to confirm: ").strip().lower()
        if confirm != "yes":
            print("Aborted.")
            return 1

    tracked: set[str] = set()
    if SIDECAR.exists():
        try:
            raw = json.loads(SIDECAR.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            print(f"❌ Failed to read sidecar {SIDECAR}: {exc}")
            print("   Refusing to proceed; a corrupt sidecar would mark every session as orphan.")
            return 2
        if isinstance(raw, dict):
            # Expect dict[str, str] mapping conversation_id -> session_id.
            # Defensive: only keep string values so a corrupt sidecar can't
            # crash this script with AttributeError.
            tracked = {v for v in raw.values() if isinstance(v, str)}

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
                # Reject symlinked dirs — rmtree follows symlinks on POSIX, so
                # an attacker (or accidental symlink) could trick us into
                # deleting tree outside the projects folder.
                if entry.is_symlink():
                    print(f"  SKIP   symlink dir {entry.name} -> {entry.resolve()}")
                    continue
                print(f"  DELETE dir {entry.name}/")
                if apply:
                    # shutil.rmtree follows symlinks-to-dirs by default on
                    # POSIX, so a symlinked subdirectory inside `entry`
                    # could let an attacker (or a stray symlink) delete
                    # files outside our workdir. Walk bottom-up with
                    # followlinks=False instead, unlinking only files
                    # and rmdir'ing only real directories.
                    for root, dirs, files in os.walk(entry, topdown=False, followlinks=False):
                        for name in files:
                            try:
                                os.unlink(os.path.join(root, name))
                            except OSError:
                                pass
                        for name in dirs:
                            full = os.path.join(root, name)
                            try:
                                # A symlink-to-dir appears in `dirs` even with
                                # followlinks=False; on POSIX os.rmdir on it
                                # fails with ENOTDIR. Unlink it (removes the
                                # link, never its target) so the parent can then
                                # be removed; real dirs still go through rmdir.
                                if os.path.islink(full):  # noqa: PTH114 (os.* style; cf. PTH106/108 ignores)
                                    os.unlink(full)
                                else:
                                    os.rmdir(full)
                            except OSError:
                                pass
                    try:
                        os.rmdir(entry)
                    except OSError:
                        pass
                deleted_dirs += 1

    # Stray non-jsonl files in the *bot* workdir (data/claude_cli_workdir/).
    # Restrict to known stray suffixes so we don't accidentally delete legitimate
    # bot temp files / future attachments stored alongside session data.
    # IMPORTANT: do NOT include `.jsonl` here — those are tracked sessions and
    # should only be deleted via the orphan-jsonl path above which consults the
    # sidecar tracker. Including .jsonl here would unconditionally delete every
    # session jsonl that happens to live under WORKDIR.
    _STRAY_ALLOWED_SUFFIXES = {".log", ".tmp", ".bak"}
    if WORKDIR.exists():
        for entry in WORKDIR.iterdir():
            if entry.is_file() and entry.suffix.lower() in _STRAY_ALLOWED_SUFFIXES:
                print(
                    f"  DELETE stray {WORKDIR / entry.name}  ({entry.stat().st_size / 1024:.1f} KB)"
                )
                if apply:
                    entry.unlink()
                stray_files += 1

    print()
    mode = "APPLIED" if apply else "DRY RUN — re-run with --apply to actually delete"
    print(
        f"[{mode}] {deleted_files} jsonl + {deleted_dirs} dir + {stray_files} stray; "
        f"freed {deleted_bytes / (1024 * 1024):.1f} MB"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
