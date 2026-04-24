"""Tests for dashboard_chat_claude_cli — session isolation + sync-delete.

These cover the forward-facing part of the module (path encoding, persistence,
and .jsonl cleanup). The subprocess-spawn path is deliberately left to
integration tests elsewhere — these tests run without any `claude` binary.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cogs.ai_core.api import dashboard_chat_claude_cli as cli_mod


@pytest.fixture(autouse=True)
def _isolated_sessions(tmp_path, monkeypatch):
    """Redirect the module's filesystem paths + clear in-memory state per test.

    The module caches _CLAUDE_CLI_WORKDIR, _SESSIONS_FILE, and _CONVERSATION_SESSIONS
    at import time. Patching them per-test keeps tests hermetic and parallel-safe.
    """
    workdir = tmp_path / "workdir"
    sessions_file = tmp_path / "sessions.json"
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()

    monkeypatch.setattr(cli_mod, "_CLAUDE_CLI_WORKDIR", workdir)
    monkeypatch.setattr(cli_mod, "_SESSIONS_FILE", sessions_file)
    monkeypatch.setattr(cli_mod.Path, "home", classmethod(lambda cls: fake_home))
    # The map is module-global; clear before + after to keep tests independent.
    cli_mod._CONVERSATION_SESSIONS.clear()
    yield
    cli_mod._CONVERSATION_SESSIONS.clear()


# ============================================================================
# _encode_claude_project_dirname — path → Claude Code project folder name
# ============================================================================


class TestEncodeProjectDirname:
    def test_windows_style_path(self):
        p = Path(r"c:\Users\ME\BOT Discord")
        # Path normalizes backslashes; str(Path) on POSIX may use /, so
        # assert on both possible outputs.
        result = cli_mod._encode_claude_project_dirname(p)
        # Either way, spaces, colons, and separators must all be dashes.
        assert " " not in result
        assert ":" not in result
        assert "\\" not in result
        assert "/" not in result

    def test_no_special_chars_stays_clean(self):
        # Path with no spaces/colons — just path separators.
        p = Path("/tmp/foo/bar")
        assert cli_mod._encode_claude_project_dirname(p) == "-tmp-foo-bar"

    def test_preserves_underscores_and_letters(self):
        p = Path("/opt/claude_cli_workdir")
        result = cli_mod._encode_claude_project_dirname(p)
        assert "claude_cli_workdir" in result


# ============================================================================
# _claude_projects_folder — where Claude Code logs our sessions
# ============================================================================


class TestClaudeProjectsFolder:
    def test_points_under_fake_home_dot_claude(self, tmp_path):
        folder = cli_mod._claude_projects_folder()
        # From the fixture, Path.home() → tmp_path/fake_home
        assert folder.parent.parent.name == ".claude"
        assert folder.parent.name == "projects"

    def test_folder_name_matches_workdir_encoding(self):
        expected_encoded = cli_mod._encode_claude_project_dirname(cli_mod._CLAUDE_CLI_WORKDIR)
        assert cli_mod._claude_projects_folder().name == expected_encoded


# ============================================================================
# _load_persisted_sessions / _save_persisted_sessions — sidecar JSON roundtrip
# ============================================================================


class TestPersistence:
    def test_save_then_load_roundtrip(self):
        cli_mod._CONVERSATION_SESSIONS["conv-a"] = "sess-111"
        cli_mod._CONVERSATION_SESSIONS["conv-b"] = "sess-222"
        cli_mod._save_persisted_sessions()

        # Wipe in-memory + reload from disk.
        cli_mod._CONVERSATION_SESSIONS.clear()
        cli_mod._load_persisted_sessions()

        assert cli_mod._CONVERSATION_SESSIONS == {"conv-a": "sess-111", "conv-b": "sess-222"}

    def test_load_silently_ignores_missing_file(self):
        # No file exists yet — should not raise.
        cli_mod._load_persisted_sessions()
        assert cli_mod._CONVERSATION_SESSIONS == {}

    def test_load_silently_ignores_corrupt_json(self):
        cli_mod._SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        cli_mod._SESSIONS_FILE.write_text("{ not valid json ", encoding="utf-8")
        # Must not raise.
        cli_mod._load_persisted_sessions()
        assert cli_mod._CONVERSATION_SESSIONS == {}

    def test_load_ignores_non_string_values(self):
        cli_mod._SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        cli_mod._SESSIONS_FILE.write_text(
            json.dumps({"good": "abc", "bad": 42, "also-bad": None}),
            encoding="utf-8",
        )
        cli_mod._load_persisted_sessions()
        assert cli_mod._CONVERSATION_SESSIONS == {"good": "abc"}


# ============================================================================
# _track_session — persists on every change
# ============================================================================


class TestTrackSession:
    def test_persists_to_disk(self):
        cli_mod._track_session("conv-x", "sess-abc")
        # Reload into a different dict to prove it hit disk.
        saved = json.loads(cli_mod._SESSIONS_FILE.read_text(encoding="utf-8"))
        assert saved == {"conv-x": "sess-abc"}

    def test_no_op_for_empty_ids(self):
        cli_mod._track_session("", "sess-1")
        cli_mod._track_session("conv-1", "")
        assert cli_mod._CONVERSATION_SESSIONS == {}


# ============================================================================
# reset_session — drops + persists
# ============================================================================


class TestResetSession:
    def test_drops_entry_and_updates_disk(self):
        cli_mod._track_session("conv-a", "sess-a")
        cli_mod.reset_session("conv-a")
        assert "conv-a" not in cli_mod._CONVERSATION_SESSIONS
        # Disk mirrors memory.
        saved = json.loads(cli_mod._SESSIONS_FILE.read_text(encoding="utf-8"))
        assert "conv-a" not in saved

    def test_reset_unknown_conversation_is_noop(self):
        # Must not raise when the conv has no tracked session.
        cli_mod.reset_session("never-tracked")


# ============================================================================
# delete_session_file — removes the .jsonl + drops from map
# ============================================================================


class TestDeleteSessionFile:
    def _make_session_file(self, session_id: str) -> Path:
        """Create a fake Claude Code .jsonl exactly where the module will look."""
        folder = cli_mod._claude_projects_folder()
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{session_id}.jsonl"
        path.write_text('{"type":"init"}\n', encoding="utf-8")
        return path

    def test_removes_jsonl_when_session_tracked(self):
        target = self._make_session_file("sess-xyz")
        cli_mod._track_session("conv-42", "sess-xyz")

        removed = cli_mod.delete_session_file("conv-42")

        assert removed is True
        assert not target.exists()
        assert "conv-42" not in cli_mod._CONVERSATION_SESSIONS

    def test_unknown_conversation_is_noop(self):
        assert cli_mod.delete_session_file("never-existed") is False

    def test_tracked_session_without_file_still_drops_map_entry(self):
        # Session id was tracked but no .jsonl on disk (e.g. file already
        # deleted manually). Cleanup should still remove the in-memory entry.
        cli_mod._track_session("conv-ghost", "sess-nofile")
        assert cli_mod.delete_session_file("conv-ghost") is False
        assert "conv-ghost" not in cli_mod._CONVERSATION_SESSIONS

    def test_persists_removal_to_disk(self):
        cli_mod._track_session("conv-p", "sess-p")
        cli_mod.delete_session_file("conv-p")
        saved = json.loads(cli_mod._SESSIONS_FILE.read_text(encoding="utf-8"))
        assert "conv-p" not in saved
