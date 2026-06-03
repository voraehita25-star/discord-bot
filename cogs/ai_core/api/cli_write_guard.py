"""PreToolUse write-guard hook for the dashboard's embedded ``claude -p``.

Claude Code runs this script before every ``Write`` / ``Edit`` / ``MultiEdit`` /
``NotebookEdit`` tool call (it is registered as a ``PreToolUse`` hook in the
settings file built by :func:`dashboard_chat_claude_cli._ensure_write_guard_settings`).
It is the AUTHORITATIVE path boundary for the dashboard CLI's file-write mode.

Why a hook and not ``--add-dir`` / ``acceptEdits`` alone: a *bare* tool name in
``--allowedTools`` is treated by Claude Code as unconditionally always-allowed and
short-circuits the workspace-directory boundary, and ``acceptEdits`` auto-approves
the whole cwd subtree. Neither confines an absolute out-of-scope write. This hook
closes that gap deterministically: it DENIES (exit code 2) any edit whose
canonicalised target path is not strictly inside one of the resolved write roots,
so a prompt-injected upload cannot drive a write to ``.env``, ``~/.claude``,
``~/.ssh``, the repo, the home root, or the bot's own workdir.

Contract (Claude Code hooks):
  - stdin  : JSON ``{"tool_name": ..., "tool_input": {...}, ...}``
  - exit 0 : allow / no opinion — normal permission flow proceeds (acceptEdits
             then auto-approves the in-scope write with no prompt).
  - exit 2 : BLOCK the tool call; stderr is surfaced to the model.

The allowed roots arrive via the ``DASHBOARD_CLI_WRITE_DIRS_RESOLVED`` env var
(``os.pathsep``-separated absolute paths), set by the parent on the subprocess
env. The hook fails CLOSED: if that var is missing/empty, if the payload can't be
parsed, or if a path can't be resolved, the edit is denied.

Kept dependency-free (stdlib only) and side-effect-free so it stays fast — it runs
once per edit and must not import the heavy bot package.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Tools whose target path must be inside an allowed root. NotebookEdit is also
# on the subprocess --disallowedTools list, but we still guard it here so the
# boundary holds even if that list ever changes.
_GUARDED_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}

# tool_input keys that carry the destination path, in priority order.
_PATH_KEYS = ("file_path", "notebook_path", "path")


def _deny(reason: str) -> None:
    """Block the tool call: stderr is shown to the model, exit 2 = deny."""
    sys.stderr.write(f"cli_write_guard: {reason}\n")
    raise SystemExit(2)


def _allowed_roots() -> list[Path]:
    raw = os.environ.get("DASHBOARD_CLI_WRITE_DIRS_RESOLVED", "")
    roots: list[Path] = []
    for part in raw.split(os.pathsep):
        part = part.strip()
        if not part:
            continue
        try:
            roots.append(Path(part).resolve())
        except OSError:
            # An unresolvable configured root is simply dropped — never a reason
            # to widen the boundary.
            continue
    return roots


def _is_within(target: Path, root: Path) -> bool:
    """True if ``target`` is ``root`` itself or strictly beneath it."""
    return target == root or root in target.parents


def main() -> None:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        _deny("unparseable PreToolUse payload; denying edit (fail-closed)")

    tool = payload.get("tool_name", "")
    if tool not in _GUARDED_TOOLS:
        # Not a file-mutation tool — no opinion, let normal flow handle it.
        raise SystemExit(0)

    tool_input = payload.get("tool_input") or {}
    target_raw = next((tool_input[k] for k in _PATH_KEYS if tool_input.get(k)), None)
    if not target_raw or not isinstance(target_raw, str):
        _deny(f"{tool} call with no resolvable target path; denying (fail-closed)")

    try:
        # resolve() canonicalises: collapses ``..`` and follows symlinks, so a
        # symlink planted inside a root that points outside it still resolves to
        # the outside target and is denied.
        target = Path(target_raw).resolve()
    except OSError:
        _deny(f"cannot resolve target path {target_raw!r}; denying (fail-closed)")

    roots = _allowed_roots()
    if not roots:
        _deny(
            "no write roots configured (DASHBOARD_CLI_WRITE_DIRS_RESOLVED unset); "
            "denying (fail-closed)"
        )

    if any(_is_within(target, root) for root in roots):
        raise SystemExit(0)  # in-scope — permit; acceptEdits approves w/o prompt

    _deny(
        f"write to {target} is outside the allowed output directories "
        f"({', '.join(str(r) for r in roots)}); denied"
    )


if __name__ == "__main__":
    main()
