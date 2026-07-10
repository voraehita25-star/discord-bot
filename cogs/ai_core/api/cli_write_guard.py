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
``~/.ssh``, the repo, the home root, or the bot's own workdir. The repo tree,
``~/.ssh``, and ``~/.claude`` are additionally denylisted INSIDE any allowed
root (see ``_denied_subtrees``), so the exclusion holds even when the repo is
cloned under a write root such as ``~/Documents``.

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
from typing import NoReturn

# Tools whose target path must be inside an allowed root. NotebookEdit is also
# on the subprocess --disallowedTools list, but we still guard it here so the
# boundary holds even if that list ever changes.
_GUARDED_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}

# tool_input keys that carry the destination path, in priority order.
_PATH_KEYS = ("file_path", "notebook_path", "path")


def _deny(reason: str) -> NoReturn:
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


def _powershell_profile_dirs(home: Path) -> list[Path]:
    """PowerShell profile directories — RCE/persistence vectors under Documents.

    The default write roots (see ``_dashboard_cli_write_dirs``) include the
    user's ``Documents`` folder AND its OneDrive-redirected twin. The PowerShell
    profile scripts live directly under Documents:
    ``Documents\\WindowsPowerShell\\`` (PS 5.1) and ``Documents\\PowerShell\\``
    (PS 7+), each holding ``Microsoft.PowerShell_profile.ps1`` / ``profile.ps1``
    which auto-execute on every new shell. A write there resolves strictly
    inside the allowed ``Documents`` root, so — like a malicious ``~/.claude.json``
    mcpServers entry — it would sail past the allow check and get auto-approved.
    This repo drives PowerShell heavily, so the profile is virtually guaranteed
    to be sourced. Deny the whole profile dir (covers every profile filename +
    any module it autoloads), mirroring the ~/.ssh / ~/.claude directory bans.
    """
    dirs = [home / "Documents" / "WindowsPowerShell", home / "Documents" / "PowerShell"]
    # OneDrive-redirected Documents — resolved from the same env vars
    # _dashboard_cli_write_dirs uses to add the OneDrive Documents write root.
    onedrive = os.environ.get("ONEDRIVE") or os.environ.get("ONEDRIVECONSUMER")
    if onedrive:
        od_docs = Path(onedrive) / "Documents"
        dirs += [od_docs / "WindowsPowerShell", od_docs / "PowerShell"]
    return [d.resolve() for d in dirs]


def _denied_subtrees() -> list[Path]:
    """Subtrees that are NEVER writable, even inside an allowed root.

    The allowed roots are a pure whitelist, so the documented exclusion of the
    repo (which contains ``.env``, the bot source, AND this guard script) held
    only positionally — a repo cloned under ``~/Documents`` sat inside a
    default write root and everything in it became auto-approved. Subtract the
    repo tree plus ``~/.ssh`` / ``~/.claude`` (credential/config RCE vectors)
    and the PowerShell profile dirs (a shell-startup RCE vector that likewise
    sits inside the default ``Documents`` write root) here so the promise is
    enforced in code regardless of where the repo lives or what roots an
    operator configures. Fails closed: an unresolvable entry denies via the caller.
    """
    # cogs/ai_core/api/cli_write_guard.py → parents[3] is the repo root.
    repo_root = Path(__file__).resolve().parents[3]
    home = Path.home()
    return [
        repo_root,
        (home / ".ssh").resolve(),
        (home / ".claude").resolve(),
        (home / ".claude.json").resolve(),
        *_powershell_profile_dirs(home),
    ]


def main() -> None:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        _deny("unparseable PreToolUse payload; denying edit (fail-closed)")

    # A valid-JSON non-object (array/string/number) would AttributeError on
    # payload.get below; that escapes as exit 1, which Claude Code treats as
    # NON-blocking (the edit proceeds). Deny instead (fail-closed).
    if not isinstance(payload, dict):
        _deny("PreToolUse payload is not an object; denying edit (fail-closed)")

    tool = payload.get("tool_name", "")
    if tool not in _GUARDED_TOOLS:
        # Not a file-mutation tool — no opinion, let normal flow handle it.
        raise SystemExit(0)

    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        _deny(f"{tool} call with non-object tool_input; denying (fail-closed)")
    target_raw = next((tool_input[k] for k in _PATH_KEYS if tool_input.get(k)), None)
    if not target_raw or not isinstance(target_raw, str):
        _deny(f"{tool} call with no resolvable target path; denying (fail-closed)")

    try:
        # resolve() canonicalises: collapses ``..`` and follows symlinks, so a
        # symlink planted inside a root that points outside it still resolves to
        # the outside target and is denied. ValueError (not just OSError) is
        # caught because an embedded-NUL path raises ValueError on Windows —
        # uncaught it would exit 1 (non-blocking) and let the write through.
        target = Path(target_raw).resolve()
    except (OSError, ValueError):
        _deny(f"cannot resolve target path {target_raw!r}; denying (fail-closed)")

    # Denylist BEFORE the allow check: sensitive subtrees stay protected even
    # when an operator points a write root at an ancestor (e.g. the repo
    # cloned under ~/Documents). Resolution failure here must deny, never
    # widen — the __main__ backstop also converts any escape into exit 2.
    try:
        denied = _denied_subtrees()
    except (OSError, RuntimeError, IndexError):
        _deny("cannot resolve protected locations; denying edit (fail-closed)")
    for sub in denied:
        if _is_within(target, sub):
            _deny(f"write to {target} is inside protected location {sub}; denied")

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
    # Top-level fail-closed backstop: SystemExit (the intentional 0/2 exits)
    # propagates unchanged, but ANY other unhandled exception must BLOCK the
    # edit (exit 2), never fall through to the default exit 1 that Claude
    # Code reads as "no opinion → proceed".
    try:
        main()
    except SystemExit:
        raise
    except BaseException as exc:  # deliberate catch-all fail-closed boundary
        sys.stderr.write(f"cli_write_guard: unexpected error {exc!r}; denying (fail-closed)\n")
        raise SystemExit(2) from exc
