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


def check_syntax(directory: Path) -> bool:
    """Check Python syntax for all files in the directory (compile-only)."""
    print(f"Checking syntax in {directory}...")
    success = True
    for path in directory.rglob("*.py"):
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
