"""
System Verification Script
Compile-only static check across the bot codebase. We deliberately do NOT
execute or ``import`` any module — doing so would trigger every cog's
module-level side effects (DB connections, Sentry init, background task
schedulers, HTTP clients, hooks). For a real import-resolution check, use
``pytest --collect-only`` which already wraps modules in test isolation.
"""

import sys
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
    import os

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


def check_syntax(directory: Path) -> bool:
    """Check Python syntax for project Python files (compile-only)."""
    print(f"Checking syntax in {directory}...")
    success = True
    for path in _iter_project_python(directory):
        try:
            # Read file and remove BOM if present
            content = path.read_bytes()
            # Remove BOM (UTF-8 BOM is EF BB BF)
            if content.startswith(b"\xef\xbb\xbf"):
                content = content[3:]
            compile(content.decode("utf-8"), str(path), "exec")
        except SyntaxError as e:
            print(f"[X] Syntax error in {path}: {e}")
            success = False
        except UnicodeDecodeError as e:
            # cp1252-saved files on Windows would otherwise crash the
            # whole verifier instead of reporting a per-file failure.
            print(f"[X] Non-UTF-8 encoding in {path}: {e}")
            success = False
        except OSError as e:
            print(f"[X] Error reading {path}: {e}")
            success = False
    if success:
        print("[OK] Syntax check passed.")
    return success


def main():
    """Main verification entry point."""
    root_dir = Path.cwd()
    print(f"Starting system verification in {root_dir}")

    syntax_ok = check_syntax(root_dir)

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
