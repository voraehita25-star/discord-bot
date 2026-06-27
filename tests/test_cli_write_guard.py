"""Runtime tests for the dashboard CLI PreToolUse write-guard hook.

Unlike the argv-shape assertions in test_dashboard_chat_claude_cli_helpers.py,
these run the actual ``cli_write_guard.py`` script the way Claude Code does — pipe
a PreToolUse JSON payload to stdin, set ``DASHBOARD_CLI_WRITE_DIRS_RESOLVED`` on
the env, and assert the exit code (0 = allow, 2 = deny). This is the test that
actually verifies the security boundary holds, which the original (broken)
implementation lacked.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from cogs.ai_core.api import cli_write_guard

SCRIPT = cli_write_guard.__file__

ALLOW = 0
DENY = 2


def run_guard(payload, roots) -> subprocess.CompletedProcess:
    """Run the guard with a payload (dict or raw str) and resolved roots."""
    env = dict(os.environ)
    if roots is None:
        env.pop("DASHBOARD_CLI_WRITE_DIRS_RESOLVED", None)
    else:
        env["DASHBOARD_CLI_WRITE_DIRS_RESOLVED"] = os.pathsep.join(str(r) for r in roots)
    stdin = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run(
        [sys.executable, SCRIPT],
        input=stdin,
        text=True,
        capture_output=True,
        env=env,
        timeout=30,
        check=False,
    )


def write_payload(path, tool="Write"):
    key = "notebook_path" if tool == "NotebookEdit" else "file_path"
    return {"tool_name": tool, "tool_input": {key: str(path)}}


class TestWriteGuardAllows:
    def test_allows_write_directly_in_root(self, tmp_path):
        root = tmp_path / "out"
        root.mkdir()
        res = run_guard(write_payload(root / "note.txt"), [root])
        assert res.returncode == ALLOW

    def test_allows_write_in_nested_subdir_of_root(self, tmp_path):
        root = tmp_path / "out"
        (root / "deep" / "deeper").mkdir(parents=True)
        res = run_guard(write_payload(root / "deep" / "deeper" / "f.txt"), [root])
        assert res.returncode == ALLOW

    def test_allows_when_path_under_one_of_several_roots(self, tmp_path):
        a = tmp_path / "a"
        a.mkdir()
        b = tmp_path / "b"
        b.mkdir()
        res = run_guard(write_payload(b / "x.txt"), [a, b])
        assert res.returncode == ALLOW

    @pytest.mark.parametrize("tool", ["Write", "Edit", "MultiEdit"])
    def test_allows_each_edit_tool_in_root(self, tmp_path, tool):
        root = tmp_path / "out"
        root.mkdir()
        res = run_guard(write_payload(root / "f.txt", tool=tool), [root])
        assert res.returncode == ALLOW

    @pytest.mark.skipif(sys.platform != "win32", reason="NTFS case-insensitive path semantics")
    def test_allows_case_divergent_path_within_root_windows(self, tmp_path):
        # _is_within relies on PureWindowsPath case-insensitive equality; a
        # future refactor to a casefold-unaware string-prefix check would
        # silently start denying legitimate writes like this one.
        root = tmp_path / "Out"
        root.mkdir()
        # Divergent case both in the existing dir and a not-yet-existing tail.
        res = run_guard(write_payload(tmp_path / "out" / "NewDir" / "f.txt"), [root])
        assert res.returncode == ALLOW

    def test_passthrough_for_non_guarded_tool(self, tmp_path):
        # A non-mutating tool gets no opinion (exit 0) even with no roots set.
        res = run_guard({"tool_name": "Bash", "tool_input": {"command": "ls"}}, None)
        assert res.returncode == ALLOW


class TestWriteGuardDenies:
    def test_denies_write_outside_root(self, tmp_path):
        root = tmp_path / "out"
        root.mkdir()
        res = run_guard(write_payload(tmp_path / "outside.txt"), [root])
        assert res.returncode == DENY

    def test_denies_parent_traversal_escape(self, tmp_path):
        root = tmp_path / "out"
        root.mkdir()
        escape = root / ".." / "secret.txt"  # resolves to tmp_path/secret.txt
        res = run_guard(write_payload(escape), [root])
        assert res.returncode == DENY

    def test_denies_home_root_write(self, tmp_path):
        root = tmp_path / "out"
        root.mkdir()
        # A classic injection target (~/.bashrc / PowerShell profile territory).
        res = run_guard(write_payload(tmp_path / "home" / ".bashrc"), [root])
        assert res.returncode == DENY

    def test_denies_when_no_roots_configured(self, tmp_path):
        # Fail closed: env var absent → deny even a plausible path.
        res = run_guard(write_payload(tmp_path / "out" / "f.txt"), None)
        assert res.returncode == DENY

    def test_denies_empty_roots_value(self, tmp_path):
        res = run_guard(write_payload(tmp_path / "f.txt"), [])
        assert res.returncode == DENY

    def test_denies_unparseable_payload(self, tmp_path):
        root = tmp_path / "out"
        root.mkdir()
        res = run_guard("this is not json", [root])
        assert res.returncode == DENY

    def test_denies_edit_tool_with_no_path(self, tmp_path):
        root = tmp_path / "out"
        root.mkdir()
        res = run_guard({"tool_name": "Write", "tool_input": {}}, [root])
        assert res.returncode == DENY

    def test_denies_notebook_edit_outside_root(self, tmp_path):
        root = tmp_path / "out"
        root.mkdir()
        res = run_guard(write_payload(tmp_path / "nb.ipynb", tool="NotebookEdit"), [root])
        assert res.returncode == DENY

    def test_denies_sibling_prefix_lookalike(self, tmp_path):
        # "out-evil" shares a string prefix with "out" but is NOT under it.
        root = tmp_path / "out"
        root.mkdir()
        sibling = tmp_path / "out-evil"
        sibling.mkdir()
        res = run_guard(write_payload(sibling / "f.txt"), [root])
        assert res.returncode == DENY

    @pytest.mark.skipif(
        sys.platform == "win32", reason="symlink creation often needs admin on Windows"
    )
    def test_denies_symlink_escape(self, tmp_path):
        root = tmp_path / "out"
        root.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        link = root / "link"
        link.symlink_to(outside, target_is_directory=True)
        # Path resolves through the symlink to outside the root → denied.
        res = run_guard(write_payload(link / "f.txt"), [root])
        assert res.returncode == DENY

    @pytest.mark.skipif(sys.platform != "win32", reason="junctions are Windows reparse points")
    def test_denies_junction_escape_windows(self, tmp_path):
        # Junctions need NO admin rights (unlike symlinks) and are the
        # realistic escape primitive on the deployment platform — a junction
        # planted inside a write root must still resolve to its target and
        # be denied. _winapi.CreateJunction is the same private-but-stable
        # API CPython's own test suite uses.
        import _winapi

        root = tmp_path / "out"
        root.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        link = root / "link"
        try:
            _winapi.CreateJunction(str(outside), str(link))
        except OSError as exc:  # e.g. non-NTFS temp volume
            pytest.skip(f"cannot create junction here: {exc}")
        # resolve() traverses the junction to outside the root → denied.
        res = run_guard(write_payload(link / "f.txt"), [root])
        assert res.returncode == DENY


class TestWriteGuardDeniedSubtrees:
    """The repo / ~/.ssh / ~/.claude denylist holds INSIDE allowed roots.

    These run the real guard subprocess; it only reads env + stdin, so using
    real paths (repo root, home) is safe — nothing is ever written.
    """

    def test_denies_repo_tree_even_when_repo_is_the_allowed_root(self):
        repo_root = Path(SCRIPT).resolve().parents[3]
        res = run_guard(write_payload(repo_root / "newfile.txt"), [repo_root])
        assert res.returncode == DENY

    def test_denies_env_file_via_ancestor_root(self):
        # The documented "an injected write cannot reach .env" guarantee must
        # hold even when an operator points a write root at a repo ancestor
        # (e.g. the repo cloned under ~/Documents).
        repo_root = Path(SCRIPT).resolve().parents[3]
        res = run_guard(write_payload(repo_root / ".env"), [repo_root.parent])
        assert res.returncode == DENY

    def test_denies_overwriting_guard_script_itself(self):
        # The guard is re-read from disk per edit — overwriting it would
        # neutralise the boundary for every later in-root write.
        script = Path(SCRIPT).resolve()
        res = run_guard(write_payload(script), [script.parent])
        assert res.returncode == DENY

    def test_denies_dot_claude_inside_allowed_root(self):
        home = Path.home()
        res = run_guard(write_payload(home / ".claude" / "settings.json"), [home])
        assert res.returncode == DENY

    def test_denies_dot_ssh_inside_allowed_root(self):
        home = Path.home()
        res = run_guard(write_payload(home / ".ssh" / "authorized_keys"), [home])
        assert res.returncode == DENY

    def test_denies_dot_claude_json_inside_allowed_root(self):
        # ~/.claude.json is Claude Code's global MCP-server config; writing a
        # malicious mcpServers entry is an RCE/persistence vector. The denylist
        # must cover the FILE (sibling of ~/.claude/) even when a write root is
        # at/above home — see audit finding #4.
        home = Path.home()
        res = run_guard(write_payload(home / ".claude.json"), [home])
        assert res.returncode == DENY


class TestWriteGuardUnits:
    def test_is_within_self_and_child(self, tmp_path):
        from pathlib import Path

        root = (tmp_path / "r").resolve()
        assert cli_write_guard._is_within(root, root) is True
        assert cli_write_guard._is_within(root / "a" / "b", root) is True
        assert cli_write_guard._is_within(Path(tmp_path / "other").resolve(), root) is False

    def test_allowed_roots_parses_pathsep(self, tmp_path, monkeypatch):
        a = tmp_path / "a"
        a.mkdir()
        b = tmp_path / "b"
        b.mkdir()
        monkeypatch.setenv(
            "DASHBOARD_CLI_WRITE_DIRS_RESOLVED", os.pathsep.join([str(a), "", str(b)])
        )
        roots = cli_write_guard._allowed_roots()
        assert a.resolve() in roots and b.resolve() in roots
