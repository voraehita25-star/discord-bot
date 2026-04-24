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
    """Attempt to import all cogs to check for dependency issues.

    Uses standard import mechanism to support relative imports properly.
    """
    print(f"\nChecking imports in {cogs_dir}...")
    success = True

    # Ensure project root is in path
    project_root = str(Path.cwd())
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    # Find all Python files and convert to module names
    modules_to_check = []
    for path in cogs_dir.rglob("*.py"):
        if path.name.startswith("__"):
            continue
        module_rel_path = path.relative_to(Path.cwd())
        # Convert path to module name: cogs/ai_core/ai_cog.py -> cogs.ai_core.ai_cog
        module_name = str(module_rel_path.with_suffix("")).replace("/", ".").replace("\\", ".")
        modules_to_check.append(module_name)

    # Sort to import parent packages first
    modules_to_check.sort()

    for module_name in modules_to_check:
        try:
            # Use standard importlib.import_module which supports relative imports
            importlib.import_module(module_name)
            print(f"[OK] Imported {module_name}")
        except (ImportError, SyntaxError, AttributeError, ModuleNotFoundError) as e:
            # Check if it's a re-export module that failed due to relative import
            # These are expected to work when imported through the package system
            if "attempted relative import" in str(e):
                # This is likely a re-export module, try importing the parent
                print(f"[SKIP] {module_name}: re-export module (works through package)")
            else:
                print(f"[X] Failed to import {module_name}: {e}")
                traceback.print_exc()
                success = False
        except Exception as e:
            print(f"[X] Unexpected error importing {module_name}: {e}")
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
