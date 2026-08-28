"""Guard: no test in this suite may be silently unreachable.

Several of these files were assembled by concatenating older ones (the
``# Merged from test_X.py`` markers are still in them). Each merge could
re-declare a class name that already existed at module scope, and Python simply
rebinds the name — the earlier class object, and every test in it, is gone
before pytest ever collects the module. 264 declared tests were dead this way
across 20 files, including the ones covering the AI chat path, while the suite
reported a clean run.

Nothing surfaces that on its own: the count just quietly comes out lower than
what is written down. So assert it here instead.
"""

from __future__ import annotations

import ast
import collections
import pathlib

TESTS_DIR = pathlib.Path(__file__).resolve().parent


def _module_level_definitions(path: pathlib.Path) -> collections.Counter[str]:
    """Names bound at module scope by a class or ``test_*`` function def."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: collections.Counter[str] = collections.Counter()
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            names[node.name] += 1
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.startswith(
            "test"
        ):
            names[node.name] += 1
    return names


def test_no_module_scope_name_is_declared_twice():
    offenders: list[str] = []
    for path in sorted(TESTS_DIR.glob("test_*.py")):
        for name, count in _module_level_definitions(path).items():
            if count > 1:
                offenders.append(f"{path.name}: {name} declared {count}x")
    assert not offenders, (
        "A module-scope test class/function is declared more than once. Python "
        "keeps only the LAST definition, so every test in the earlier one is "
        "unreachable and pytest will never report it as skipped or failed — it "
        "just does not exist. Rename the duplicates:\n  " + "\n  ".join(offenders)
    )


def test_no_class_declares_the_same_test_twice():
    """Same shadowing rule, one level down: a redeclared method wins outright."""
    offenders: list[str] = []
    for path in sorted(TESTS_DIR.glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            methods: collections.Counter[str] = collections.Counter(
                child.name
                for child in node.body
                if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef)
                and child.name.startswith("test")
            )
            for name, count in methods.items():
                if count > 1:
                    offenders.append(f"{path.name}: {node.name}.{name} declared {count}x")
    assert not offenders, "Duplicate test methods shadow each other:\n  " + "\n  ".join(offenders)
