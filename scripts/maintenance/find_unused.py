"""
Analyze imports and find unused Python files in the project.
"""

import os
import re
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path()
EXCLUDE_DIRS = {"__pycache__", ".git", "venv", ".venv", "node_modules", "data"}


def find_python_files():
    """Find all Python files in the project."""
    files = []
    for root, dirs, filenames in os.walk(PROJECT_ROOT):
        # Skip excluded directories
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]

        for filename in filenames:
            if filename.endswith(".py"):
                filepath = Path(root) / filename
                files.append(filepath)
    return files


def extract_imports(filepath):
    """Extract all imports from a Python file."""
    imports = set()
    try:
        content = filepath.read_text(encoding="utf-8")

        # Match: from X import Y and import X
        patterns = [
            r"^from\s+([\w.]+)\s+import",  # from X import Y
            r"^import\s+([\w.]+)",  # import X
        ]

        for pattern in patterns:
            for match in re.finditer(pattern, content, re.MULTILINE):
                module = match.group(1)
                imports.add(module)
    except Exception as e:
        print(f"Error reading {filepath}: {e}")

    return imports


def module_to_file(module_name, project_files):
    """Convert a module name to a file path."""
    # Try different variations
    variations = [
        module_name.replace(".", "/") + ".py",
        module_name.replace(".", "/") + "/__init__.py",
    ]

    for var in variations:
        for pf in project_files:
            if str(pf).replace("\\", "/").endswith(var):
                return pf
    return None


def main():
    print("=" * 60)
    print("Unused File Analyzer")
    print("=" * 60)

    # Find all Python files
    all_files = find_python_files()
    print(f"\n[INFO] Found {len(all_files)} Python files")

    # Track which files are imported by something
    imported_files = set()
    import_map = defaultdict(set)  # file -> set of files that import it

    # Analyze imports in each file
    for filepath in all_files:
        imports = extract_imports(filepath)
        for imp in imports:
            # Check if this is a local import
            target = module_to_file(imp, all_files)
            if target:
                imported_files.add(target)
                import_map[target].add(filepath)

    # Find entry points (files that should be run directly)
    entry_points = {
        Path("bot.py"),
        Path("config.py"),
    }

    # Scripts are typically run directly
    Path("scripts")
    Path("tools")

    # Find unused files
    unused = []
    for filepath in all_files:
        # Skip entry points
        if filepath in entry_points:
            continue

        # Skip scripts (they're meant to be run directly)
        if str(filepath).startswith("scripts"):
            continue

        # Skip tools (they're meant to be run directly)
        if str(filepath).startswith("tools"):
            continue

        # Skip __init__.py files (they're package markers)
        if filepath.name == "__init__.py":
            continue

        # Check if this file is imported anywhere
        if filepath not in imported_files:
            unused.append(filepath)

    # Report
    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)

    if unused:
        print(f"\n[WARN] Found {len(unused)} potentially unused files:\n")
        for f in sorted(unused):
            print(f"  - {f}")
    else:
        print("\n[OK] No unused files found!")

    # Also check for files that are only imported by one file
    print("\n" + "-" * 60)
    print("Files imported by only 1 other file (potential candidates to merge):")
    print("-" * 60)
    single_import = []
    for filepath, importers in import_map.items():
        if len(importers) == 1 and filepath.name != "__init__.py":
            single_import.append((filepath, next(iter(importers))))

    if single_import:
        for f, importer in sorted(single_import):
            print(f"  - {f}")
            print(f"    (only by: {importer})")
    else:
        print("  None")

    # Show import graph for reference
    print("\n" + "-" * 60)
    print("Import summary:")
    print("-" * 60)
    for filepath in sorted(all_files):
        if filepath in imported_files:
            count = len(import_map[filepath])
            if count > 0:
                print(f"  {filepath}: imported by {count} files")


if __name__ == "__main__":
    main()
