"""Tests for dashboard_chat_claude_cli — session isolation + sync-delete.

These cover the forward-facing part of the module (path encoding, persistence,
and .jsonl cleanup). The subprocess-spawn path is deliberately left to
integration tests elsewhere — these tests run without any `claude` binary.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

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
    # Hermetic env: a dev machine's CLAUDE_CONFIG_DIR / OAuth token would
    # otherwise steer _claude_config_dir() (and the projects folder every
    # cleanup test asserts on) at a REAL directory.
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    # The map is module-global; clear before + after to keep tests independent.
    cli_mod._CONVERSATION_SESSIONS.clear()
    yield
    cli_mod._CONVERSATION_SESSIONS.clear()


async def _settle_session_cleanups() -> None:
    """Await any in-flight background .jsonl unlink tasks."""
    if cli_mod._PENDING_SESSION_CLEANUPS:
        await asyncio.gather(*cli_mod._PENDING_SESSION_CLEANUPS, return_exceptions=True)


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

    def test_underscores_replaced_with_dash_to_match_claude_code(self):
        # Claude Code's actual encoder replaces `_` with `-` along with
        # `:`, `\`, `/`, and space. If we don't, delete_session_file()
        # looks for the file in a folder Claude never wrote to, leaving
        # orphan .jsonl behind on every dashboard conversation delete.
        p = Path("/opt/claude_cli_workdir")
        result = cli_mod._encode_claude_project_dirname(p)
        assert "claude_cli_workdir" not in result
        assert "claude-cli-workdir" in result
        assert "_" not in result

    def test_dots_replaced_with_dash_to_match_claude_code(self):
        # Claude Code replaces EVERY non-alphanumeric char with '-', including
        # '.' — not just the ":\\/ _" subset. A path segment with a dot (e.g. a
        # Windows profile "me.name" or a versioned dir) must encode the dot too,
        # or the computed projects folder diverges from the real one and cleanup
        # silently no-ops, leaving orphan .jsonl behind.
        result = cli_mod._encode_claude_project_dirname(Path("/home/me.name/proj.v2"))
        assert "." not in result
        assert "me-name" in result
        assert "proj-v2" in result


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

    def test_refuses_to_track_suspicious_session_id(self, caplog):
        # Defense at the source: a session id that would be parsed as a CLI
        # flag by `claude --resume <id>` (argv injection) must NOT be tracked,
        # so it can never reach the argv builder via the persisted map.
        import logging

        with caplog.at_level(logging.WARNING, logger=cli_mod.logger.name):
            cli_mod._track_session("conv-evil", "--dangerously-skip-permissions")
        assert "conv-evil" not in cli_mod._CONVERSATION_SESSIONS
        assert any("suspicious" in r.message.lower() for r in caplog.records)


# ============================================================================
# _SESSION_ID_PATTERN + _build_claude_argv — argv-injection defense for
# `claude --resume`. A session id beginning with '-' would otherwise be parsed
# as a flag (e.g. --dangerously-skip-permissions); the pattern + the builder's
# drop-and-warn branch are the load-bearing guard.
# ============================================================================


class TestSessionIdPatternArgvGuard:
    @pytest.mark.parametrize(
        "bad",
        [
            "-evil",  # leading dash → argv flag injection
            "--resume",  # another flag
            "-",  # bare dash
            "",  # empty
            "a" * 65,  # > 64 chars (pattern allows 1 + 63)
            "has space",  # disallowed char
            "has/slash",  # path-traversal char
            "has.dot",  # path-traversal char
            "bad!char",  # punctuation outside [A-Za-z0-9_-]
        ],
    )
    def test_pattern_rejects_bad_ids(self, bad):
        assert cli_mod._SESSION_ID_PATTERN.match(bad) is None

    @pytest.mark.parametrize(
        "good",
        [
            "a",  # single alnum (min)
            "0",  # leading digit is allowed
            "abc-123_DEF",
            "f47ac10b-58cc-4372-a567-0e02b2c3d479",  # UUID
            "A" + "z" * 63,  # exactly 64 chars (max)
        ],
    )
    def test_pattern_accepts_good_ids(self, good):
        assert cli_mod._SESSION_ID_PATTERN.match(good) is not None

    def _argv(self, monkeypatch, tmp_path, session_id):
        monkeypatch.setattr(cli_mod, "_EMPTY_MCP_CONFIG_FILE", tmp_path / "empty_mcp.json")
        return cli_mod._build_claude_argv(
            "claude",
            session_id=session_id,
            allow_read_for_images=False,
        )

    def test_builder_drops_resume_for_leading_dash_id(self, monkeypatch, tmp_path, caplog):
        import logging

        with caplog.at_level(logging.WARNING, logger=cli_mod.logger.name):
            argv = self._argv(monkeypatch, tmp_path, "-dangerously-skip-permissions")
        assert "--resume" not in argv
        assert "-dangerously-skip-permissions" not in argv
        assert any("ignoring suspicious" in r.message.lower() for r in caplog.records)

    def test_builder_drops_resume_for_oversized_id(self, monkeypatch, tmp_path, caplog):
        import logging

        oversized = "a" * 65
        with caplog.at_level(logging.WARNING, logger=cli_mod.logger.name):
            argv = self._argv(monkeypatch, tmp_path, oversized)
        assert "--resume" not in argv
        assert oversized not in argv
        assert any("ignoring suspicious" in r.message.lower() for r in caplog.records)

    def test_builder_includes_resume_for_valid_id(self, monkeypatch, tmp_path):
        argv = self._argv(monkeypatch, tmp_path, "good-session-123")
        assert "--resume" in argv
        # --resume must be immediately followed by the validated id.
        i = argv.index("--resume")
        assert argv[i + 1] == "good-session-123"


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

    @pytest.mark.asyncio
    async def test_reset_unlinks_discarded_transcript(self):
        # After the pop the .jsonl is unreachable by every cleanup path
        # (per-turn unlink, LRU eviction, delete_session_file all key off the
        # latest tracked id) — reset must unlink it, best-effort.
        folder = cli_mod._claude_projects_folder()
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / "sess-reset.jsonl"
        target.write_text('{"type":"init"}\n', encoding="utf-8")
        cli_mod._track_session("conv-reset", "sess-reset")

        cli_mod.reset_session("conv-reset")
        await _settle_session_cleanups()

        assert not target.exists()
        assert "conv-reset" not in cli_mod._CONVERSATION_SESSIONS


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

    @pytest.mark.asyncio
    async def test_removes_jsonl_when_session_tracked(self):
        target = self._make_session_file("sess-xyz")
        cli_mod._track_session("conv-42", "sess-xyz")

        removed = await cli_mod.delete_session_file("conv-42")

        assert removed is True
        assert not target.exists()
        assert "conv-42" not in cli_mod._CONVERSATION_SESSIONS

    @pytest.mark.asyncio
    async def test_unknown_conversation_is_noop(self):
        assert await cli_mod.delete_session_file("never-existed") is False

    @pytest.mark.asyncio
    async def test_tracked_session_without_file_still_drops_map_entry(self):
        # Session id was tracked but no .jsonl on disk (e.g. file already
        # deleted manually). Cleanup should still remove the in-memory entry.
        cli_mod._track_session("conv-ghost", "sess-nofile")
        assert await cli_mod.delete_session_file("conv-ghost") is False
        assert "conv-ghost" not in cli_mod._CONVERSATION_SESSIONS

    @pytest.mark.asyncio
    async def test_persists_removal_to_disk(self):
        cli_mod._track_session("conv-p", "sess-p")
        await cli_mod.delete_session_file("conv-p")
        # _save_persisted_sessions dispatches the actual disk I/O to a
        # worker thread via asyncio.to_thread when called from a running
        # loop (which is our case here under pytest-asyncio). Wait for any
        # in-flight persist tasks before reading the file, otherwise the
        # write may not have landed yet and the read raises FileNotFound.
        if cli_mod._PERSIST_TASKS:
            await asyncio.gather(*cli_mod._PERSIST_TASKS, return_exceptions=True)
        saved = json.loads(cli_mod._SESSIONS_FILE.read_text(encoding="utf-8"))
        assert "conv-p" not in saved


# ============================================================================
# _claude_config_dir / _make_subprocess_env — must resolve identically
# ============================================================================


class TestClaudeConfigDirParity:
    """Session-file cleanup must target the same projects dir the child uses."""

    def test_operator_config_dir_wins_in_both(self, monkeypatch, tmp_path):
        op = tmp_path / "opcfg"
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(op))
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "tok-x")
        env = cli_mod._make_subprocess_env()
        assert env.get("CLAUDE_CONFIG_DIR") == str(op)
        assert cli_mod._claude_config_dir() == op

    def test_blank_config_dir_with_oauth_token_redirects_both(self, monkeypatch):
        # A set-but-blank CLAUDE_CONFIG_DIR means "unset" (e.g. a scaffolded
        # `CLAUDE_CONFIG_DIR=` line in .env): the redirect must apply AND
        # cleanup must look at the same redirected dir.
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "tok-x")
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", "   ")
        env = cli_mod._make_subprocess_env()
        clean_cfg = cli_mod._CLAUDE_CLI_WORKDIR / "claude_home"
        assert env.get("CLAUDE_CONFIG_DIR") == str(clean_cfg)
        assert cli_mod._claude_config_dir() == clean_cfg

    def test_mkdir_failure_falls_back_to_home_in_both(self, monkeypatch):
        # If the claude_home mkdir fails at spawn time the child silently uses
        # ~/.claude — _claude_config_dir() must report the same fallback or
        # every cleanup becomes a silent no-op.
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "tok-x")
        cli_mod._CLAUDE_CLI_WORKDIR.mkdir(parents=True, exist_ok=True)
        # A FILE named claude_home makes mkdir(exist_ok=True) raise OSError.
        (cli_mod._CLAUDE_CLI_WORKDIR / "claude_home").write_text("", encoding="utf-8")
        env = cli_mod._make_subprocess_env()
        assert "CLAUDE_CONFIG_DIR" not in env
        assert cli_mod._claude_config_dir() == cli_mod.Path.home() / ".claude"


# ============================================================================
# handle_chat_message_claude_cli — handler-level recovery behavior
# ============================================================================


class _FakeWS:
    """Minimal fake aiohttp WebSocketResponse recording every frame."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, data: dict) -> None:
        self.sent.append(data)

    def find(self, msg_type: str) -> list[dict]:
        return [m for m in self.sent if m.get("type") == msg_type]


def _mock_db() -> MagicMock:
    db = MagicMock()
    db.save_dashboard_message = AsyncMock(return_value=99)
    db.get_dashboard_messages = AsyncMock(return_value=[])
    db.get_dashboard_conversation = AsyncMock(return_value={"title": "set"})
    db.update_dashboard_conversation = AsyncMock()
    return db


@contextlib.contextmanager
def _handler_patches(db, fake_subprocess, prewarm_mock=None):
    with (
        patch.object(cli_mod, "get_db", return_value=db),
        patch.object(cli_mod, "DB_AVAILABLE", True),
        patch.object(cli_mod, "is_cli_backend_ready", return_value=(True, "")),
        patch.object(cli_mod, "_resolve_claude_executable", return_value="claude"),
        patch.object(cli_mod, "_track_session"),
        patch.object(cli_mod, "_schedule_prewarm", new=prewarm_mock or MagicMock()),
        patch.object(cli_mod, "build_user_context", new=AsyncMock(return_value=("ctx", False))),
        patch.object(cli_mod, "_run_claude_subprocess", new=fake_subprocess),
    ):
        yield


class TestHandlerStaleSessionRetry:
    """Pins the four stale-retry behaviors: reset_session, full-history
    prompt rebuild, accumulator reset + second stream_start, and the
    no-duplication guarantee for the persisted body. Mirror of the Discord
    side's test_stale_session_retries_with_fresh_id_once."""

    @pytest.mark.asyncio
    async def test_stale_retry_resets_stream_and_rebuilds_history(self, monkeypatch, tmp_path):
        monkeypatch.setattr(cli_mod, "_SYSTEM_PROMPT_DIR", tmp_path / "sp")
        monkeypatch.setattr(cli_mod, "_EMPTY_MCP_CONFIG_FILE", tmp_path / "empty_mcp.json")
        monkeypatch.delenv("DASHBOARD_CLI_ALLOW_WRITE", raising=False)
        ws = _FakeWS()
        cli_mod._CONVERSATION_SESSIONS["c1"] = "stale-sess"
        calls: list[tuple[list[str], str]] = []

        async def fake_subprocess(
            argv,
            stdin_payload,
            *,
            on_text_delta,
            on_thinking_delta,
            on_thinking_block_start=None,
            on_thinking_block_stop=None,
            timeout,
            extra_env=None,
            proc=None,
        ):
            calls.append((list(argv), stdin_payload))
            if len(calls) == 1:
                await on_text_delta("attempt-1 partial")
                raise cli_mod._StaleSessionError("stale")
            await on_text_delta("attempt-2 final")
            return "fresh-sess", None

        try:
            with _handler_patches(_mock_db(), fake_subprocess):
                await cli_mod.handle_chat_message_claude_cli(
                    ws,
                    {
                        "conversation_id": "c1",
                        "content": "hello",
                        "role_preset": "general",
                        "history": [{"role": "user", "content": "earlier turn"}],
                    },
                    None,
                )
        finally:
            cli_mod._CONVERSATION_SESSIONS.pop("c1", None)
            await _settle_session_cleanups()

        # Client told to clear attempt-1 chunks via a SECOND stream_start.
        assert len(ws.find("stream_start")) == 2
        ends = ws.find("stream_end")
        assert ends and ends[-1]["full_response"] == "attempt-2 final"  # no duplication
        assert len(calls) == 2
        argv1, prompt1 = calls[0]
        argv2, prompt2 = calls[1]
        assert "--resume" in argv1 and "stale-sess" in argv1
        assert "--resume" not in argv2  # session dropped for the retry
        assert "# Conversation so far" not in prompt1  # resumed → minimal prompt
        assert "# Conversation so far" in prompt2  # retry rebuilt full history
        assert cli_mod._CONVERSATION_SESSIONS.get("c1") in (None, "fresh-sess")
        # Retry returned usage=None, so the len//4 fallback estimate runs. It must
        # measure the prompt actually sent — prompt2 (fresh_prompt, WITH history) —
        # not the shorter resume-era prompt1.
        assert ends[-1]["token_usage"]["input_tokens"] == max(1, len(prompt2) // 4)
        # prompt2 carries '# Conversation so far' but prompt1 doesn't, so the two
        # estimates differ; this assert fails without the full_prompt = fresh_prompt fix.
        assert ends[-1]["token_usage"]["input_tokens"] != max(1, len(prompt1) // 4)


class TestHandlerErrorPathsDropSession:
    """Timeout/overload/unclassified failures leave the user's turn in the DB
    but not in the resumed session — the handler must drop the CLI session so
    the next turn rebuilds the history block (which carries the dangling row)."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "exc",
        [
            TimeoutError("stream timed out"),
            cli_mod._OverloadedError("API Error: 529 Overloaded"),
            RuntimeError("claude -p exit 1: boom"),
            ValueError("unclassified"),
        ],
    )
    async def test_error_path_drops_session(self, monkeypatch, tmp_path, exc):
        monkeypatch.setattr(cli_mod, "_SYSTEM_PROMPT_DIR", tmp_path / "sp")
        monkeypatch.setattr(cli_mod, "_EMPTY_MCP_CONFIG_FILE", tmp_path / "empty_mcp.json")
        monkeypatch.delenv("DASHBOARD_CLI_ALLOW_WRITE", raising=False)
        ws = _FakeWS()
        cli_mod._CONVERSATION_SESSIONS["c1"] = "sess-err"

        async def fake_subprocess(*_a, **_k):
            raise exc

        try:
            with _handler_patches(_mock_db(), fake_subprocess):
                await cli_mod.handle_chat_message_claude_cli(
                    ws,
                    {"conversation_id": "c1", "content": "hello", "role_preset": "general"},
                    None,
                )
        finally:
            cli_mod._CONVERSATION_SESSIONS.pop("c1", None)
            await _settle_session_cleanups()

        assert ws.find("error"), "handler must surface an error frame"
        # The stale session id must be gone so the next turn rebuilds fresh.
        assert "c1" not in cli_mod._CONVERSATION_SESSIONS


class TestHandlerPrewarmThinking:
    """The warm argv must carry the turn's thinking flag (conversation-sticky
    in the frontend) or it never matches and every thinking turn wastes a
    ~150MB spawn."""

    @pytest.mark.asyncio
    async def test_prewarm_argv_carries_thinking_flag(self, monkeypatch, tmp_path):
        monkeypatch.setattr(cli_mod, "_SYSTEM_PROMPT_DIR", tmp_path / "sp")
        monkeypatch.setattr(cli_mod, "_EMPTY_MCP_CONFIG_FILE", tmp_path / "empty_mcp.json")
        monkeypatch.delenv("DASHBOARD_CLI_ALLOW_WRITE", raising=False)
        ws = _FakeWS()
        prewarm_mock = MagicMock()

        async def fake_subprocess(*_a, **_k):
            return "sess-think", None

        try:
            with _handler_patches(_mock_db(), fake_subprocess, prewarm_mock=prewarm_mock):
                await cli_mod.handle_chat_message_claude_cli(
                    ws,
                    {
                        "conversation_id": "c1",
                        "content": "think hard",
                        "role_preset": "general",
                        "thinking_enabled": True,
                    },
                    None,
                )
        finally:
            cli_mod._CONVERSATION_SESSIONS.pop("c1", None)
            await _settle_session_cleanups()

        prewarm_mock.assert_called_once()
        warm_argv = prewarm_mock.call_args[0][1]
        assert "--effort" in warm_argv and "xhigh" in warm_argv
        assert "--resume" in warm_argv and "sess-think" in warm_argv
