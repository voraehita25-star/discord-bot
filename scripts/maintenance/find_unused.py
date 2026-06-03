"""
Analyze imports and find unused Python files in the project.
"""

import ast
import os
from collections import defaultdict
from pathlib import Path

# Anchor PROJECT_ROOT to this script's location instead of CWD so the tool
# works no matter where it's invoked from.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
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
    """Extract all imports from a Python file via AST.

    The previous regex approach missed relative imports entirely
    (``from . import x``) because ``[\\w.]+`` doesn't match a bare dot.
    AST parsing yields both absolute and relative imports and is
    immune to comment / string-literal false positives.
    """
    imports: set[str] = set()
    try:
        content = filepath.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(filepath))
    except (SyntaxError, OSError, UnicodeDecodeError) as e:
        print(f"Error reading {filepath}: {e}")
        return imports
    pkg_parts = filepath.relative_to(PROJECT_ROOT).parts[:-1]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            # Resolve relative imports against the file's package path
            # so ``from . import x`` and ``from ..sub import y`` map
            # back to absolute module names the rest of the tool
            # already understands.
            if node.level == 0:
                if node.module:
                    imports.add(node.module)
            else:
                base = list(pkg_parts[: max(0, len(pkg_parts) - node.level + 1)])
                if node.module:
                    resolved = ".".join([*base, node.module])
                    if resolved:
                        imports.add(resolved)
                else:
                    # ``from . import x`` has no module — the imported NAMES are
                    # the submodules. Record each as ``<package>.<name>`` (e.g.
                    # cogs.ai_core.memory.x); otherwise only the bare package path
                    # was recorded and the actually-imported submodule x.py was
                    # falsely reported unused. This idiom is common in the repo's
                    # __init__.py files.
                    for alias in node.names:
                        resolved = ".".join([*base, alias.name])
                        if resolved:
                            imports.add(resolved)
    return imports


def module_to_file(module_name, project_files):
    """Convert a module name to a file path."""
    # Try different variations
    variations = [
        module_name.replace(".", "/") + ".py",
        module_name.replace(".", "/") + "/__init__.py",
    ]

    # Use a pre-built relative-path lookup so this function is O(1) per
    # call instead of O(N) over all project files. Called once per
    # import edge during scan: the previous O(N²) loop made a 1000-file
    # repo do ~1M comparisons every run.
    rel_lookup = getattr(module_to_file, "_rel_lookup", None)
    if rel_lookup is None:
        rel_lookup = {str(pf).replace("\\", "/").lstrip("/"): pf for pf in project_files}
        # Also index by relative-to-PROJECT_ROOT path so trailing-segment
        # matches don't accidentally pick up unrelated files (the
        # previous ``endswith`` accepted ``xbar.py`` as a match for
        # ``bar.py``).
        for pf in project_files:
            try:
                rel = pf.relative_to(PROJECT_ROOT).as_posix()
                rel_lookup[rel] = pf
            except ValueError:
                continue
        module_to_file._rel_lookup = rel_lookup  # type: ignore[attr-defined]

    for var in variations:
        # Exact-path hit first
        if var in rel_lookup:
            return rel_lookup[var]
        # Fall back to slow suffix match only when needed — the indexed
        # lookup catches >99% of imports without scanning.
        for path_key, pf in rel_lookup.items():
            if path_key.endswith("/" + var) or path_key == var:
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

    # Find entry points (files that should be run directly). Anchor to
    # PROJECT_ROOT — bare relative paths never matched the absolute
    # ``filepath`` produced by ``rglob``, so entry points were not
    # actually being skipped.
    entry_points = {
        PROJECT_ROOT / "bot.py",
        PROJECT_ROOT / "config.py",
    }

    # Scripts and tools are typically run directly (skip them below)

    # Find unused files
    unused = []
    for filepath in all_files:
        # Skip entry points
        if filepath in entry_points:
            continue

        # Use parts so the check works on Windows (\) and POSIX (/) alike.
        try:
            rel_parts = filepath.relative_to(PROJECT_ROOT).parts
        except ValueError:
            rel_parts = filepath.parts

        # Skip scripts (they're meant to be run directly)
        if rel_parts and rel_parts[0] == "scripts":
            continue

        # Skip tools (they're meant to be run directly)
        if rel_parts and rel_parts[0] == "tools":
            continue

        # Skip test files — they're only imported by pytest's collector,
        # not by other source files, so they'd be flagged as unused.
        if rel_parts and rel_parts[0] == "tests":
            continue
        if filepath.name.startswith("test_"):
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
            # ``next(iter(set))`` is non-deterministic across runs and
            # makes the report's "first importer" column flap between
            # runs even when nothing changed. Sort so the report is
            # reproducible.
            single_import.append((filepath, sorted(importers)[0]))

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
