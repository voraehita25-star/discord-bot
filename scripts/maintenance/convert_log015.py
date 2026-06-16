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

import contextlib
import os
import py_compile
import re
import sys
import tempfile
from pathlib import Path

LOGGER_DECL = b"logger = logging.getLogger(__name__)"

# Recognise an existing ``logger = logging.getLogger(...)`` binding regardless
# of whitespace (e.g. ``logger=logging.getLogger(...)``) and only on a real
# code line (leading indentation only — not inside a comment/docstring that
# merely contains the literal). A bare ``LOGGER_DECL in original`` substring
# test missed non-canonical spacing (inserting a duplicate binding) and could
# be fooled by the literal string appearing inside a comment.
_LOGGER_DECL_RE = re.compile(rb"^[ \t]*logger[ \t]*=[ \t]*logging\.getLogger\(")

# Match indented `logging.<level>(`. The leading capture group keeps the
# original whitespace (tab, 4-space, 8-space etc.) so we don't reformat.
# We deliberately do NOT match unindented `logging.X(` — those at module
# top-level can fire before `logger` is defined and are rarer. Leave them
# for manual review.
# Limitation: the leading `(^|\r?\n)` anchor is CONSUMED by each match, and
# subn resumes scanning after it, so a SECOND `logging.<level>(` on the SAME
# physical line (e.g. `    logging.info(x); logging.debug(y)`) is not preceded
# by a newline+indentation and won't be rewritten — only the first call is.
# This is acceptable for our single-statement-per-line scope; such lines are
# rare and the result stays valid syntax (mixed `logger.`/`logging.`), so a
# manual pass can finish them.
# Limitation 2: the rewrite is purely textual (no tokenizer), so an indented
# `logging.<level>(` inside a triple-quoted string/docstring or after a `#`
# comment is rewritten too. py_compile still passes (the edit stays valid),
# so such a false-positive would be committed silently. No first-party source
# in this repo has that shape; review the diff if you re-run on new inputs.
_CALL_RE = re.compile(
    rb"(^|\r?\n)([ \t]+)logging\.(debug|info|warning|error|critical|exception|log)\(",
)


def find_logging_import_line(lines: list[bytes]) -> int | None:
    """Return the index of an unaliased module-level `import logging`, or None.

    Aliased forms (`import logging as X`) are intentionally NOT matched: inserting
    the bare-`logging` LOGGER_DECL after them would reference an unbound `logging`
    name and raise NameError at import (which py_compile can't catch). Skipping
    them makes convert_file report "no import logging" and leave the file alone.
    """
    for i, line in enumerate(lines):
        if line.strip() == b"import logging":
            return i
    return None


def convert_file(path: Path) -> tuple[bool, str]:
    """Convert one file. Returns (changed, reason)."""
    original = path.read_bytes()
    # Logger already declared; skip re-insertion. We still want the
    # ``logging.<level>(`` → ``logger.<level>(`` call rewrite below, so
    # there's nothing to do here — the ``inserted`` flag will simply
    # stay False and ``new_lines.insert`` won't run.
    # (The membership check below is the actual gate for insertion.)

    # Split preserving line endings.
    # We want to find the `import logging` line index without losing line endings.
    # Use a simple approach: split on \n, then rejoin.
    text_lines = original.split(b"\n")
    import_idx = find_logging_import_line(text_lines)
    if import_idx is None:
        return (False, "no `import logging` at module level")

    new_lines = list(text_lines)
    inserted = False
    if not any(_LOGGER_DECL_RE.match(ln) for ln in text_lines):
        # Insert right after the import line, preserving the line-ending style of the
        # import line (handled by splitting on \n — \r stays attached to the line above).
        new_lines.insert(
            import_idx + 1,
            LOGGER_DECL + b"\r" if text_lines[import_idx].endswith(b"\r") else LOGGER_DECL,
        )
        inserted = True

    new_content = b"\n".join(new_lines)

    # Now replace `logging.<level>(` → `logger.<level>(` on indented lines.
    new_content, n_replaced = _CALL_RE.subn(rb"\1\2logger.\3(", new_content)

    if not inserted and n_replaced == 0:
        return (False, "no changes needed")

    # Syntax-check before overwriting.
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", suffix=".py", delete=False, dir=str(path.parent)
        ) as tmp:
            tmp.write(new_content)
            tmp_path = Path(tmp.name)
        try:
            # cfile=os.devnull keeps py_compile from writing a stray
            # ``.pyc`` next to the syntax-check temp — we only care that
            # ``compile()`` doesn't raise; the bytecode is throwaway and
            # would otherwise litter the working directory on every run.
            py_compile.compile(str(tmp_path), cfile=os.devnull, doraise=True)
        except py_compile.PyCompileError as e:
            return (False, f"syntax error after edit: {e.msg}")

        # Atomic replace: rename the verified temp file over the source so
        # a crash mid-write can't corrupt the original. ``Path.write_bytes``
        # was not atomic — a process kill between truncate and write would
        # leave the source partially overwritten with no recovery.
        tmp_path.replace(path)
        tmp_path = None  # ownership transferred via replace
        return (True, f"inserted={inserted}, replaced={n_replaced}")
    finally:
        # Cleanup any leftover temp file from non-PyCompileError exceptions
        # (e.g. OSError from disk full) — without this, the previous code
        # leaked .tmp files in the source tree.
        if tmp_path is not None:
            with contextlib.suppress(OSError):
                tmp_path.unlink()


def _clean_stdin_path(line: str) -> str:
    """Strip whitespace and a single matching pair of surrounding quotes.

    A path shell-quoted to survive spaces (e.g. ``"my dir/file.py"`` or
    ``'my dir/file.py'``) keeps the quote characters after ``str.strip()``,
    so ``Path(...).exists()`` returns False and the file is silently reported
    as ``[MISS]``. Drop one balanced surrounding quote pair so quoted and bare
    paths behave identically; an unbalanced quote is left untouched.
    """
    s = line.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        return s[1:-1]
    return s


def main() -> int:
    files = [cleaned for line in sys.stdin if (cleaned := _clean_stdin_path(line))]
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
        except Exception as e:
            # Include the traceback so an unexpected error mode (e.g.
            # encoding error on a non-UTF-8 source file) surfaces
            # actionable info instead of just an opaque type name.
            import traceback as _tb

            print(f"[ERR ] {rel}: {e}")
            _tb.print_exc()
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
