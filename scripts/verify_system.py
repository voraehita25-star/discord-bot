"""
System Verification Script
Checks for syntax errors and valid imports across the bot codebase.
"""

import importlib.util
import sys
import traceback
from pathlib import Path


def check_syntax(directory: Path) -> bool:
    """Check Python syntax for all files in the directory."""
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


def check_imports(cogs_dir: Path) -> bool:
    """Attempt to import all cogs to check for dependency issues."""
    print(f"\nChecking imports in {cogs_dir}...")
    success = True
    sys.path.append(str(Path.cwd()))

    for path in cogs_dir.rglob("*.py"):
        if path.name.startswith("__"):
            continue
        module_rel_path = path.relative_to(Path.cwd())
        module_name = str(module_rel_path.with_suffix("")).replace("/", ".").replace("\\\\", ".")

        try:
            spec = importlib.util.spec_from_file_location(module_name, path)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
                print(f"[OK] Imported {module_name}")
        except (ImportError, SyntaxError, AttributeError) as e:
            print(f"[X] Failed to import {module_name}: {e}")
            traceback.print_exc()
            success = False
    return success


def main():
    """Main verification entry point."""
    root_dir = Path.cwd()
    print(f"Starting system verification in {root_dir}")

    syntax_ok = check_syntax(root_dir)

    cogs_dir = root_dir / "cogs"
    if cogs_dir.exists():
        imports_ok = check_imports(cogs_dir)
    else:
        print("[!] Cogs directory not found.")
        imports_ok = True

    if syntax_ok and imports_ok:
        print("\n[OK] System verification passed!")
        sys.exit(0)
    else:
        print("\n[!] System verification failed!")
        sys.exit(1)


if __name__ == "__main__":
    main()
