#!/usr/bin/env python3
"""Sync the volatile *numbers* in the project docs to the live repo.

The READMEs and `docs/*.md` quote a lot of counts that drift every time a test
or source file is added — Python/vitest/Playwright test counts, test-file and
source-file counts, the app version, big-module line counts, the ruff version.
Hand-editing them one-by-one after each change is tedious and error-prone (the
2026-06 doc audit found ~25 stale numbers across 8 files).

This script recomputes each number from the live repo and rewrites it in place
across every doc that quotes it, in one pass.

Usage (run from the repo root)::

    python scripts/maintenance/sync_doc_stats.py            # rewrite docs in place
    python scripts/maintenance/sync_doc_stats.py --check    # report drift, exit 1 if any
    make docs-sync     /     make docs-check                # Makefile shortcuts

Design notes:
  * Each (file, regex, stat) entry in REPLACEMENTS has exactly ONE capture group
    around the number/string to replace; only that span is rewritten, so the
    surrounding prose is preserved.
  * A registry entry whose regex matches ZERO times is reported as an error
    (the doc wording drifted away from the pattern — update the registry), so
    a silent no-op can't hide a stale number.
  * Stats that need an external tool (pytest/node/ruff) are best-effort: if the
    tool isn't on PATH the stat is skipped (its doc occurrences are left as-is)
    rather than failing the whole run. File/JSON-based stats always compute.
  * Historical snapshots (docs/reviews/**, docs/release-notes/**) are NOT touched
    — they are point-in-time records, not living docs.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DASH = ROOT / "native_dashboard"


def _which(name: str) -> str | None:
    """Resolve a CLI by name, tolerating Windows `.cmd`/`.exe` shims (npm/npx)."""
    found = shutil.which(name)
    if found:
        return found
    if os.name == "nt":
        for ext in (".cmd", ".exe", ".bat"):
            found = shutil.which(name + ext)
            if found:
                return found
    return None


# --------------------------------------------------------------------------- #
# Stat computation
# --------------------------------------------------------------------------- #
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


def _run(cmd: list[str], cwd: Path | None = None, timeout: int = 180) -> str | None:
    """Run a command, returning combined stdout/stderr (ANSI-stripped), or None.

    Tools like vitest emit ANSI colour codes even when their output is captured
    (e.g. ``Tests \\x1b[1m\\x1b[32m298 passed``), which would break the count
    regexes — strip them so parsing sees plain text.
    """
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd or ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return _ANSI_RE.sub("", (proc.stdout or "") + (proc.stderr or ""))


def _count_glob(base: Path, pattern: str) -> int:
    return len(list(base.glob(pattern)))


def _git_py_count() -> int | None:
    out = _run(["git", "ls-files", "*.py"], timeout=30)
    if out is None:
        return None
    return sum(1 for ln in out.splitlines() if ln.strip())


def _version() -> str | None:
    try:
        conf = json.loads((DASH / "tauri.conf.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    v = conf.get("version")
    return str(v) if v else None


def _pytest_total() -> int | None:
    out = _run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/",
            "--collect-only",
            "-q",
            "--override-ini=addopts=",
        ],
        timeout=180,
    )
    if out is None:
        return None
    m = re.search(r"(\d+)\s+tests?\s+collected", out)
    return int(m.group(1)) if m else None


def _vitest_total(spec: str | None = None) -> int | None:
    """Total vitest cases (optionally for one spec file). Best-effort via npx."""
    npx = _which("npx")
    if not npx:
        return None
    full = [npx, "vitest", "run"]
    if spec:
        full.append(spec)
    out = _run(full, cwd=DASH, timeout=240)
    if not out:
        return None
    # vitest prints e.g. "Tests  298 passed (298)"
    m = re.search(r"Tests\s+(\d+)\s+passed", out)
    return int(m.group(1)) if m else None


def _playwright_total() -> int | None:
    npx = _which("npx")
    if not npx:
        return None
    out = _run([npx, "playwright", "test", "--list"], cwd=DASH, timeout=120)
    if out is None:
        return None
    m = re.search(r"Total:\s+(\d+)\s+test", out)
    return int(m.group(1)) if m else None


def _ruff_version() -> str | None:
    # Prefer the repo venv's ruff, then PATH ruff.
    venv_ruff = ROOT / ".venv" / "Scripts" / "ruff.exe"
    cmd = [str(venv_ruff)] if venv_ruff.exists() else ["ruff"]
    out = _run([*cmd, "--version"], timeout=30)
    if out is None:
        return None
    m = re.search(r"ruff\s+([0-9][0-9.]*)", out)
    return m.group(1) if m else None


def _line_count_k(rel: str) -> str | None:
    p = ROOT / rel
    try:
        n = sum(1 for _ in p.open("rb"))
    except OSError:
        return None
    return f"{n / 1000:.1f}"  # e.g. "2.1", "3.1"


def compute_stats() -> dict[str, object | None]:
    """Compute every synced stat. None means 'could not compute — leave doc as-is'."""
    return {
        # File / JSON based — always available.
        "version": _version(),
        "pytest_test_files": _count_glob(ROOT / "tests", "test_*.py"),
        "python_files": _git_py_count(),
        "vitest_files": _count_glob(DASH / "src-ts", "**/*.test.ts"),
        "vitest_chat_files": _count_glob(DASH / "src-ts" / "chat", "*.test.ts"),
        "playwright_files": _count_glob(DASH / "tests-e2e", "*.spec.ts"),
        "app_ts_lines": _line_count_k("native_dashboard/src-ts/app.ts"),
        "chat_manager_ts_lines": _line_count_k("native_dashboard/src-ts/chat-manager.ts"),
        # Tool based — best-effort (skipped if the toolchain is absent).
        "pytest_tests": _pytest_total(),
        "vitest_tests": _vitest_total(),
        "playwright_tests": _playwright_total(),
        "chat_manager_tests": _vitest_total("src-ts/chat-manager.test.ts"),
        "ruff_version": _ruff_version(),
    }


# Integer stats render with a thousands separator (only adds a comma >= 1000,
# so "298" stays "298" and 5066 becomes "5,066"). String stats render verbatim.
_INT_STATS = {
    "pytest_tests",
    "pytest_test_files",
    "python_files",
    "vitest_tests",
    "vitest_files",
    "vitest_chat_files",
    "playwright_tests",
    "playwright_files",
    "chat_manager_tests",
}


def render(stat: str, value: object) -> str:
    if stat in _INT_STATS:
        return f"{int(value):,}"
    return str(value)


# --------------------------------------------------------------------------- #
# Replacement registry: (file, regex with ONE capture group, stat key)
# The capture group's span is the only text rewritten.
# --------------------------------------------------------------------------- #
REPLACEMENTS: list[tuple[str, str, str]] = [
    # README.md
    ("README.md", r"Python suite \(([\d,]+) pytest\)", "pytest_tests"),
    ("README.md", r"Playwright \(([\d,]+) spec files", "playwright_files"),
    ("README.md", r"vitest ✅ \+ ([\d,]+) Playwright ✅", "playwright_tests"),
    ("README.md", r"\*\*Tests:\*\* ([\d,]+) pytest", "pytest_tests"),
    ("README.md", r"pytest ✅ \+ ([\d,]+) vitest", "vitest_tests"),
    ("README.md", r"\*\*Version:\*\* ([\d.]+) ", "version"),
    # CONTRIBUTING.md
    ("CONTRIBUTING.md", r"pytest \(~([\d,]+) Python tests\)", "pytest_tests"),
    ("CONTRIBUTING.md", r"`npm test` \(([\d,]+) vitest\)", "vitest_tests"),
    ("CONTRIBUTING.md", r"test:e2e` \(([\d,]+) Playwright\)", "playwright_tests"),
    # CLAUDE.md
    ("CLAUDE.md", r"\(ruff ([0-9][0-9.]*)\)", "ruff_version"),
    ("CLAUDE.md", r"~([\d,]+) pytest", "pytest_tests"),
    ("CLAUDE.md", r"\| ([\d,]+) vitest \+ [\d,]+ Playwright", "vitest_tests"),
    ("CLAUDE.md", r"vitest \+ ([\d,]+) Playwright", "playwright_tests"),
    # native_dashboard/README.md
    # File-count spans are captured separately from test-count spans (one group
    # per entry), so both halves of e.g. "467 tests across 19 vitest files" sync.
    ("native_dashboard/README.md", r"([\d,]+) tests across [\d,]+ vitest files", "vitest_tests"),
    ("native_dashboard/README.md", r"tests across ([\d,]+) vitest files", "vitest_files"),
    ("native_dashboard/README.md", r"\+ ([\d,]+) in `src-ts/chat/`", "vitest_chat_files"),
    (
        "native_dashboard/README.md",
        r"\(([\d,]+) tests total across all [\d,]+\)",
        "vitest_tests",
    ),
    ("native_dashboard/README.md", r"tests total across all ([\d,]+)\)", "vitest_files"),
    (
        "native_dashboard/README.md",
        r"# ([\d,]+) vitest files \([\d,]+ tests total",
        "vitest_chat_files",
    ),
    ("native_dashboard/README.md", r"Run all ([\d,]+) vitest tests", "vitest_tests"),
    (
        "native_dashboard/README.md",
        r"([\d,]+) Playwright tests across [\d,]+ spec files",
        "playwright_tests",
    ),
    (
        "native_dashboard/README.md",
        r"Playwright tests across ([\d,]+) spec files",
        "playwright_files",
    ),
    ("native_dashboard/README.md", r"Run all ([\d,]+) Playwright tests", "playwright_tests"),
    (
        "native_dashboard/README.md",
        r"state-transition tests \(([\d,]+) tests\)",
        "chat_manager_tests",
    ),
    ("native_dashboard/README.md", r"대시보드_([\d.]+)_x64-setup", "version"),
    ("native_dashboard/README.md", r"app\.ts[^\n]*\(~([0-9.]+)k lines\)", "app_ts_lines"),
    (
        "native_dashboard/README.md",
        r"chat-manager\.ts[^\n]*\(~([0-9.]+)k lines\)",
        "chat_manager_ts_lines",
    ),
    # docs/DEVELOPER_GUIDE.md
    ("docs/DEVELOPER_GUIDE.md", r"\*\*Version:\*\* ([\d.]+)\n", "version"),
    ("docs/DEVELOPER_GUIDE.md", r"([\d,]+) Python test files", "pytest_test_files"),
    ("docs/DEVELOPER_GUIDE.md", r"Python test files \(([\d,]+) tests\)", "pytest_tests"),
    ("docs/DEVELOPER_GUIDE.md", r"\(([\d,]+) frontend tests\)", "vitest_tests"),
    ("docs/DEVELOPER_GUIDE.md", r"Directory Structure \(([\d,]+) Python Files\)", "python_files"),
    ("docs/DEVELOPER_GUIDE.md", r"test suite \(([\d,]+) tests in", "pytest_tests"),
    ("docs/DEVELOPER_GUIDE.md", r"tests in ([\d,]+) files\)", "pytest_test_files"),
    ("docs/DEVELOPER_GUIDE.md", r"([\d,]+) Python tests \+ [\d,]+ frontend vitest", "pytest_tests"),
    ("docs/DEVELOPER_GUIDE.md", r"Python tests \+ ([\d,]+) frontend vitest", "vitest_tests"),
    ("docs/DEVELOPER_GUIDE.md", r"vitest files total \(([\d,]+) tests\)", "vitest_tests"),
    ("docs/DEVELOPER_GUIDE.md", r"([\d,]+) vitest files total", "vitest_files"),
    ("docs/DEVELOPER_GUIDE.md", r"\+ ([\d,]+) vitest files \([\d,]+ frontend", "vitest_files"),
    ("docs/DEVELOPER_GUIDE.md", r"([\d,]+) Playwright spec files", "playwright_files"),
    ("docs/DEVELOPER_GUIDE.md", r"Playwright spec files \(([\d,]+) e2e", "playwright_tests"),
    ("docs/DEVELOPER_GUIDE.md", r"static UI \(([\d,]+) tests, incl", "playwright_tests"),
    ("docs/DEVELOPER_GUIDE.md", r"vitest tests \+ ([\d,]+) Playwright", "playwright_tests"),
    (
        "docs/DEVELOPER_GUIDE.md",
        r"ChatManager dispatcher \+ state \(([\d,]+) tests\)",
        "chat_manager_tests",
    ),
    ("docs/DEVELOPER_GUIDE.md", r"Version ([\d.]+) \| Full-project", "version"),
    # docs/INSTALL.md
    ("docs/INSTALL.md", r"Version: ([\d.]+)\*", "version"),
    # docs/TESTING.md
    ("docs/TESTING.md", r"Python Tests: ([\d,]+) ✅", "pytest_tests"),
    ("docs/TESTING.md", r"Python Tests: [\d,]+ ✅ \(([\d,]+) files\)", "pytest_test_files"),
    ("docs/TESTING.md", r"Frontend Tests: ([\d,]+) ✅", "vitest_tests"),
    ("docs/TESTING.md", r"Frontend Tests: [\d,]+ ✅ \(([\d,]+) vitest files\)", "vitest_files"),
    ("docs/TESTING.md", r"\+ ([\d,]+) ✅ \([\d,]+ Playwright spec files", "playwright_tests"),
    ("docs/TESTING.md", r"\(([\d,]+) Playwright spec files", "playwright_files"),
    ("docs/TESTING.md", r"Current count: \*\*([\d,]+) files\*\*", "pytest_test_files"),
    ("docs/TESTING.md", r"Test Structure \(([\d,]+) Python files", "pytest_test_files"),
    ("docs/TESTING.md", r"Python files, ([\d,]+) tests\)", "pytest_tests"),
    ("docs/TESTING.md", r"Frontend Test Structure \(([\d,]+) vitest files", "vitest_files"),
    (
        "docs/TESTING.md",
        r"Frontend Test Structure \([\d,]+ vitest files, ([\d,]+) tests\)",
        "vitest_tests",
    ),
    ("docs/TESTING.md", r"dispatcher \+ state \(([\d,]+) tests\)", "chat_manager_tests"),
    ("docs/TESTING.md", r"Headless E2E Tests \(([\d,]+) Playwright files", "playwright_files"),
    ("docs/TESTING.md", r"Playwright files, ([\d,]+) tests\)", "playwright_tests"),
    ("docs/TESTING.md", r"All ([\d,]+) tests, headless", "playwright_tests"),
    # docs/CODE_AUDIT_GUIDE.md
    ("docs/CODE_AUDIT_GUIDE.md", r"\*\*Tests:\*\* ([\d,]+) Python ✅", "pytest_tests"),
    ("docs/CODE_AUDIT_GUIDE.md", r"Python ✅ \+ ([\d,]+) frontend vitest", "vitest_tests"),
    ("docs/CODE_AUDIT_GUIDE.md", r"vitest ✅ \+ ([\d,]+) Playwright ✅", "playwright_tests"),
    ("docs/CODE_AUDIT_GUIDE.md", r"\*\*Python Test Files:\*\* ([\d,]+)", "pytest_test_files"),
    (
        "docs/CODE_AUDIT_GUIDE.md",
        r"\*\*Frontend Test Files:\*\* ([\d,]+) vitest",
        "vitest_files",
    ),
    ("docs/CODE_AUDIT_GUIDE.md", r"vitest \+ ([\d,]+) Playwright e2e", "playwright_files"),
    ("docs/CODE_AUDIT_GUIDE.md", r"tests/ \(([\d,]+) ไฟล์\)", "pytest_test_files"),
]


# --------------------------------------------------------------------------- #
# Apply
# --------------------------------------------------------------------------- #
def apply(check: bool) -> int:
    stats = compute_stats()
    skipped = [k for k, v in stats.items() if v is None]
    if skipped:
        print(f"⚠️  could not compute (left as-is): {', '.join(sorted(skipped))}")

    by_file: dict[str, list[tuple[str, str]]] = {}
    for rel, pat, stat in REPLACEMENTS:
        by_file.setdefault(rel, []).append((pat, stat))

    drift = 0
    errors = 0
    for rel, rules in by_file.items():
        path = ROOT / rel
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            print(f"❌ {rel}: cannot read")
            errors += 1
            continue
        new_text = text
        # Collect (stat, old, new) for each span actually rewritten so the drift
        # report reflects the applied diff (not a second scan of the original).
        changes: list[tuple[str, str, str]] = []
        for pat, stat in rules:
            value = stats.get(stat)
            rx = re.compile(pat)
            matches = list(rx.finditer(new_text))
            if not matches:
                print(f"❌ {rel}: pattern for '{stat}' matched nothing — registry stale: {pat!r}")
                errors += 1
                continue
            if value is None:
                continue  # uncomputable stat — leave occurrences untouched
            repl = render(stat, value)
            # Rebuild right-to-left so earlier spans stay valid.
            for m in reversed(matches):
                old = m.group(1)
                if old != repl:
                    new_text = new_text[: m.start(1)] + repl + new_text[m.end(1) :]
                    changes.append((stat, old, repl))
        if new_text != text:
            for stat, old, new in changes:
                print(f"  {rel}: {stat}  {old} → {new}")
            drift += 1
            if not check:
                path.write_text(new_text, encoding="utf-8")

    if errors:
        print(f"\n❌ {errors} registry/IO error(s) — fix before relying on the sync.")
        return 2
    if check:
        if drift:
            print(f"\n❌ {drift} file(s) out of sync. Run: make docs-sync")
            return 1
        if skipped:
            print(
                "✅ docs in sync with the live repo "
                f"(but {len(skipped)} stat(s) unchecked — toolchain absent)."
            )
        else:
            print("✅ docs in sync with the live repo.")
        return 0
    print(f"\n✅ docs synced ({drift} file(s) updated).")
    return 0


def main() -> int:
    # The status output uses ✅/❌/→; force UTF-8 so it can't crash on a
    # legacy code page (Windows cmd defaults to cp1252).
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(
        description="Sync volatile numbers in project docs to the live repo."
    )
    ap.add_argument(
        "--check", action="store_true", help="report drift and exit 1 if any (no writes)"
    )
    args = ap.parse_args()
    return apply(check=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
