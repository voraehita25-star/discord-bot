"""
System Verification Script
Compile-only static check across the bot codebase. We deliberately do NOT
execute or ``import`` any module — doing so would trigger every cog's
module-level side effects (DB connections, Sentry init, background task
schedulers, HTTP clients, hooks). For a real import-resolution check, use
``pytest --collect-only`` which already wraps modules in test isolation.
"""

import argparse
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

# Directories whose Python files are NOT ours to type-check. Recursing
# into ``.venv`` etc. previously produced false-positive syntax errors
# from third-party code AND slowed verification by tens of seconds.
# These are matched by BARE BASENAME anywhere in the tree.
_EXCLUDED_DIRS = {
    "__pycache__",
    ".git",
    "venv",
    ".venv",
    "node_modules",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "site-packages",
    "build",
    "dist",
    "target",
}

# Runtime/dump dirs to skip ONLY at the project root. Excluding these by
# bare basename (the old behavior) also swallowed first-party SOURCE like
# ``cogs/ai_core/data/`` (5 tracked modules) and any ``RP``-named package,
# so a syntax error in those files was never compiled and the verifier
# falsely reported "passed". ``./data`` is the persisted runtime dump
# (DB files, caches, sessions); ``./RP`` is the roleplay-data dump.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ROOT_ONLY_EXCLUDED = {(_PROJECT_ROOT / name).resolve() for name in ("data", "RP")}


def _iter_project_python(root: Path):
    """Yield .py files under ``root``, skipping vendored / cache dirs."""
    for current_root, dirs, filenames in os.walk(root):
        cur = Path(current_root)
        dirs[:] = [
            d
            for d in dirs
            if d not in _EXCLUDED_DIRS and (cur / d).resolve() not in _ROOT_ONLY_EXCLUDED
        ]
        for filename in filenames:
            if filename.endswith(".py"):
                yield Path(current_root) / filename


def _compile_one(path_str: str) -> str | None:
    """Compile one file. Returns an error line, or None when it's clean.

    Module-level (not a closure) so ProcessPoolExecutor can pickle it.
    """
    path = Path(path_str)
    try:
        # Read file and remove BOM if present
        content = path.read_bytes()
        # Remove BOM (UTF-8 BOM is EF BB BF)
        if content.startswith(b"\xef\xbb\xbf"):
            content = content[3:]
        compile(content.decode("utf-8"), path_str, "exec")
    except SyntaxError as e:
        return f"[X] Syntax error in {path_str}: {e}"
    except UnicodeDecodeError as e:
        # cp1252-saved files on Windows would otherwise crash the
        # whole verifier instead of reporting a per-file failure.
        return f"[X] Non-UTF-8 encoding in {path_str}: {e}"
    except OSError as e:
        return f"[X] Error reading {path_str}: {e}"
    return None


def check_syntax(directory: Path, *, jobs: int | None = None) -> bool:
    """Check Python syntax for project Python files (compile-only).

    ``compile()`` is CPU-bound and releases nothing to other threads, so the
    work is spread over processes. Below the threshold the pool's spawn cost
    (notably on Windows, where every worker re-imports this module) outweighs
    the parse time, so small trees stay serial.
    """
    print(f"Checking syntax in {directory}...")
    paths = [str(p) for p in _iter_project_python(directory)]
    if not paths:
        print("[!] No Python files found — is this the project root?")
        return False

    if jobs is None:
        jobs = min(os.cpu_count() or 1, 8)

    errors: list[str] = []
    if jobs > 1 and len(paths) >= 200:
        try:
            with ProcessPoolExecutor(max_workers=jobs) as pool:
                errors = [e for e in pool.map(_compile_one, paths, chunksize=32) if e]
        except (OSError, RuntimeError, ImportError) as e:
            # Restricted/sandboxed environments can refuse to fork or spawn.
            print(f"[!] Parallel check unavailable ({e}); falling back to serial.")
            errors = [e for e in map(_compile_one, paths) if e]
    else:
        errors = [e for e in map(_compile_one, paths) if e]

    for line in errors:
        print(line)
    if errors:
        return False
    print(f"[OK] Syntax check passed ({len(paths)} files).")
    return True


def main(argv: list[str] | None = None):
    """Main verification entry point."""
    parser = argparse.ArgumentParser(
        description="Compile-only syntax check across the bot codebase."
    )
    # Default to the PROJECT ROOT, not the cwd. _ROOT_ONLY_EXCLUDED is computed
    # from this file's location, so a cwd-rooted scan launched from anywhere
    # else applied the wrong exclusions — running it from scripts/ checked only
    # scripts/ and still called that "System verification passed".
    parser.add_argument(
        "root",
        nargs="?",
        type=Path,
        default=_PROJECT_ROOT,
        help="Directory to check (default: the project root)",
    )
    parser.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=None,
        help="Worker processes (default: min(cpu_count, 8); 1 forces serial)",
    )
    args = parser.parse_args(argv)

    root_dir = args.root.resolve()
    print(f"Starting system verification in {root_dir}")

    syntax_ok = check_syntax(root_dir, jobs=args.jobs)

    if syntax_ok:
        print("\n[OK] System verification passed!")
        print("[INFO] For full import-resolution checking, run:")
        print("       pytest --collect-only")
        sys.exit(0)
    else:
        print("\n[!] System verification failed!")
        sys.exit(1)


if __name__ == "__main__":
    main()
