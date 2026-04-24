"""
One-shot LOG015 converter.

For each file listed on stdin:
  1. Find the line that has `import logging` at module top-level.
  2. Insert `logger = logging.getLogger(__name__)` immediately after it
     (if not already present) at indent 0 — this guarantees the `logger`
     name exists before any other module-level code runs, so module-load-time
     `logger.warning(...)` calls inside `except ImportError:` fallbacks work.
  3. Replace indented `logging.(debug|info|warning|error|critical|exception|log)(`
     with `logger.<level>(`.
  4. Preserve the file's original encoding and line endings (we read/write
     bytes to avoid CRLF↔LF drift on Windows).
  5. Syntax-check with `py_compile` — if the result is broken, revert.

Usage:
    python scripts/maintenance/convert_log015.py < list_of_files.txt
"""

from __future__ import annotations

import py_compile
import re
import sys
import tempfile
from pathlib import Path

LOGGER_DECL = b"logger = logging.getLogger(__name__)"

# Match indented `logging.<level>(`. The leading capture group keeps the
# original whitespace (tab, 4-space, 8-space etc.) so we don't reformat.
# We deliberately do NOT match unindented `logging.X(` — those at module
# top-level can fire before `logger` is defined and are rarer. Leave them
# for manual review.
_CALL_RE = re.compile(
    rb"(^|\r?\n)([ \t]+)logging\.(debug|info|warning|error|critical|exception|log)\(",
)


def find_logging_import_line(lines: list[bytes]) -> int | None:
    """Return the index of `import logging` at module level, or None."""
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == b"import logging" or stripped.startswith(b"import logging as "):
            return i
    return None


def convert_file(path: Path) -> tuple[bool, str]:
    """Convert one file. Returns (changed, reason)."""
    original = path.read_bytes()
    if LOGGER_DECL in original:
        # Logger already declared — still do call replacement below.
        pass

    # Split preserving line endings.
    # We want to find the `import logging` line index without losing line endings.
    # Use a simple approach: split on \n, then rejoin.
    text_lines = original.split(b"\n")
    import_idx = find_logging_import_line(text_lines)
    if import_idx is None:
        return (False, "no `import logging` at module level")

    new_lines = list(text_lines)
    inserted = False
    if LOGGER_DECL not in original:
        # Insert right after the import line, preserving the line-ending style of the
        # import line (handled by splitting on \n — \r stays attached to the line above).
        new_lines.insert(import_idx + 1, LOGGER_DECL + b"\r" if text_lines[import_idx].endswith(b"\r") else LOGGER_DECL)
        inserted = True

    new_content = b"\n".join(new_lines)

    # Now replace `logging.<level>(` → `logger.<level>(` on indented lines.
    new_content, n_replaced = _CALL_RE.subn(rb"\1\2logger.\3(", new_content)

    if not inserted and n_replaced == 0:
        return (False, "no changes needed")

    # Syntax-check before overwriting.
    with tempfile.NamedTemporaryFile(
        mode="wb", suffix=".py", delete=False, dir=str(path.parent)
    ) as tmp:
        tmp.write(new_content)
        tmp_path = Path(tmp.name)
    try:
        py_compile.compile(str(tmp_path), doraise=True)
    except py_compile.PyCompileError as e:
        tmp_path.unlink(missing_ok=True)
        return (False, f"syntax error after edit: {e.msg}")

    # Replace atomically.
    path.write_bytes(new_content)
    tmp_path.unlink(missing_ok=True)
    return (True, f"inserted={inserted}, replaced={n_replaced}")


def main() -> int:
    files = [line.strip() for line in sys.stdin if line.strip()]
    ok = 0
    skipped = 0
    failed = 0
    for rel in files:
        path = Path(rel)
        if not path.exists():
            print(f"[MISS] {rel}")
            skipped += 1
            continue
        try:
            changed, reason = convert_file(path)
        except Exception as e:  # noqa: BLE001
            print(f"[ERR ] {rel}: {e}")
            failed += 1
            continue
        if changed:
            print(f"[OK  ] {rel} — {reason}")
            ok += 1
        else:
            print(f"[SKIP] {rel} — {reason}")
            skipped += 1
    print(f"\nSummary: {ok} changed, {skipped} skipped, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
