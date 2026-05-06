"""Helper-function tests for cogs.ai_core.api.dashboard_chat_claude_cli.

The existing test file already covers the persisted-session lifecycle.
This file targets the pure helpers that aren't exercised there:
inline-image / document save+cleanup, prompt assembly, env allowlist,
argv construction, search/replace patch application, and the conversation
lock LRU.
"""

from __future__ import annotations

import asyncio
import base64
import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from cogs.ai_core.api import dashboard_chat_claude_cli as cli


# ---------------------------------------------------------------------------
# _save_inline_images
# ---------------------------------------------------------------------------


def _data_url(mime: str, payload: bytes) -> str:
    return f"data:{mime};base64,{base64.b64encode(payload).decode()}"


@pytest.fixture(autouse=True)
def isolate_image_root(monkeypatch, tmp_path):
    """Redirect the per-conversation temp roots to a per-test scratch dir."""
    monkeypatch.setattr(cli, "_TEMP_IMAGE_ROOT", tmp_path / "img")
    monkeypatch.setattr(cli, "_TEMP_DOCS_ROOT", tmp_path / "doc")


class TestSaveInlineImages:
    def test_returns_empty_for_no_images(self):
        assert cli._save_inline_images("conv-1", [], 1024) == []

    def test_returns_empty_for_empty_conv_id(self):
        assert cli._save_inline_images("", [_data_url("image/png", b"x")], 1024) == []

    def test_writes_valid_png(self):
        url = _data_url("image/png", b"\x89PNG\r\n\x1a\n" + b"x" * 50)
        result = cli._save_inline_images("conv-1", [url], 1024)
        assert len(result) == 1
        assert result[0].suffix == ".png"
        assert result[0].exists()

    def test_skips_non_string(self):
        result = cli._save_inline_images("conv-1", [12345, None], 1024)
        assert result == []

    def test_skips_missing_data_prefix(self):
        result = cli._save_inline_images("conv-1", ["not-a-data-url"], 1024)
        assert result == []

    def test_skips_unsupported_mime(self):
        url = _data_url("image/svg+xml", b"<svg/>")
        result = cli._save_inline_images("conv-1", [url], 1024)
        assert result == []

    def test_drops_oversized(self):
        url = _data_url("image/jpeg", b"x" * 2048)
        result = cli._save_inline_images("conv-1", [url], 1024)
        assert result == []

    def test_skips_corrupt_base64(self):
        url = "data:image/png;base64,!!!notbase64!!!"
        result = cli._save_inline_images("conv-1", [url], 1024)
        assert result == []

    def test_sanitises_conv_id(self):
        # Path-traversal attempt should be rewritten to safe chars.
        url = _data_url("image/png", b"\x89PNG" + b"x" * 50)
        result = cli._save_inline_images("../../etc/passwd", [url], 1024)
        # Must not have escaped the temp root.
        assert all(cli._TEMP_IMAGE_ROOT in p.parents for p in result)


class TestCleanupImageDir:
    def test_noop_for_empty_conv_id(self):
        # Should not raise.
        cli._cleanup_image_dir("")

    def test_removes_old_files(self, tmp_path):
        conv_dir = cli._TEMP_IMAGE_ROOT / "conv-old"
        conv_dir.mkdir(parents=True)
        old_file = conv_dir / "old.png"
        old_file.write_bytes(b"x")
        # Backdate the file beyond the 60-second cutoff.
        os.utime(old_file, (time.time() - 120, time.time() - 120))

        cli._cleanup_image_dir("conv-old")

        assert not old_file.exists()

    def test_keeps_fresh_files(self):
        conv_dir = cli._TEMP_IMAGE_ROOT / "conv-fresh"
        conv_dir.mkdir(parents=True)
        fresh = conv_dir / "fresh.png"
        fresh.write_bytes(b"x")  # mtime = now, well under 60s cutoff

        cli._cleanup_image_dir("conv-fresh")

        assert fresh.exists()


# ---------------------------------------------------------------------------
# _save_inline_documents
# ---------------------------------------------------------------------------


class TestSaveInlineDocuments:
    def test_returns_empty_for_no_docs(self):
        assert cli._save_inline_documents("conv-1", [], 1024) == []

    def test_writes_text_doc(self):
        result = cli._save_inline_documents(
            "conv-1",
            [{"name": "notes.md", "kind": "text", "data": "# heading"}],
            1024,
        )
        assert len(result) == 1
        assert result[0].read_text(encoding="utf-8") == "# heading"

    def test_writes_binary_pdf(self):
        url = _data_url("application/pdf", b"%PDF-1.4 stub")
        result = cli._save_inline_documents(
            "conv-1",
            [{"name": "spec.pdf", "kind": "binary", "data": url}],
            1024,
        )
        assert len(result) == 1
        assert result[0].read_bytes() == b"%PDF-1.4 stub"

    def test_drops_unsupported_extension(self):
        result = cli._save_inline_documents(
            "conv-1",
            [{"name": "evil.exe", "kind": "binary", "data": "data:application/x-msdownload;base64,QQ=="}],
            1024,
        )
        assert result == []

    def test_drops_oversized_text(self):
        result = cli._save_inline_documents(
            "conv-1",
            [{"name": "big.txt", "kind": "text", "data": "x" * 5000}],
            1024,
        )
        assert result == []

    def test_drops_oversized_binary(self):
        url = _data_url("application/pdf", b"x" * 5000)
        result = cli._save_inline_documents(
            "conv-1",
            [{"name": "big.pdf", "kind": "binary", "data": url}],
            1024,
        )
        assert result == []

    def test_skips_non_dict(self):
        assert cli._save_inline_documents("conv-1", ["not-a-dict", 5], 1024) == []

    def test_skips_missing_name(self):
        assert (
            cli._save_inline_documents("conv-1", [{"kind": "text", "data": "hi"}], 1024) == []
        )

    def test_sanitises_filename(self):
        result = cli._save_inline_documents(
            "conv-1",
            [{"name": "../../escape me.md", "kind": "text", "data": "hi"}],
            1024,
        )
        assert len(result) == 1
        # Filename is sanitised — no path-separator escapes the conv dir.
        # Literal `..` substrings are fine; only `/` and `\` would be exploitable.
        assert cli._TEMP_DOCS_ROOT in result[0].parents
        assert "/" not in result[0].name
        assert "\\" not in result[0].name


# ---------------------------------------------------------------------------
# _build_history_block + _build_full_prompt
# ---------------------------------------------------------------------------


class TestBuildHistoryBlock:
    def test_empty_history(self):
        assert cli._build_history_block([], 10) == ""

    def test_renders_user_and_assistant(self):
        history = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        out = cli._build_history_block(history, 10)
        assert "User:" in out
        assert "Assistant:" in out
        assert "hi" in out
        assert "hello" in out

    def test_respects_limit(self):
        history = [{"role": "user", "content": f"msg {i}"} for i in range(20)]
        out = cli._build_history_block(history, 5)
        # Only the last 5 should appear (msg 15..19).
        assert "msg 19" in out
        assert "msg 15" in out
        assert "msg 14" not in out

    def test_includes_timestamp_when_present(self):
        history = [{"role": "user", "content": "hi", "created_at": "2026-01-01T10:00:00+07:00"}]
        out = cli._build_history_block(history, 10)
        assert "2026-01-01" in out


class TestBuildFullPrompt:
    def test_includes_persona(self):
        out = cli._build_full_prompt(
            persona="Test Persona",
            user_context="",
            memories_context="",
            history=[],
            history_limit=10,
            current_message="hi",
            image_paths=[],
            doc_paths=None,
            is_resumed_session=False,
        )
        assert "Test Persona" in out
        assert "# Persona" in out

    def test_skips_history_when_resumed(self):
        history = [{"role": "user", "content": "earlier message"}]
        out = cli._build_full_prompt(
            persona="P",
            user_context="",
            memories_context="",
            history=history,
            history_limit=10,
            current_message="now",
            image_paths=[],
            doc_paths=None,
            is_resumed_session=True,
        )
        assert "earlier message" not in out

    def test_lists_image_paths(self, tmp_path):
        img = tmp_path / "pic.png"
        img.write_bytes(b"x")
        out = cli._build_full_prompt(
            persona="P",
            user_context="",
            memories_context="",
            history=[],
            history_limit=10,
            current_message="m",
            image_paths=[img],
            doc_paths=None,
            is_resumed_session=False,
        )
        assert "pic.png" in out
        assert "Attached images" in out

    def test_lists_doc_paths(self, tmp_path):
        doc = tmp_path / "spec.pdf"
        doc.write_bytes(b"x")
        out = cli._build_full_prompt(
            persona="P",
            user_context="",
            memories_context="",
            history=[],
            history_limit=10,
            current_message="m",
            image_paths=[],
            doc_paths=[doc],
            is_resumed_session=False,
        )
        assert "spec.pdf" in out
        assert "Attached documents" in out

    def test_current_message_at_end(self):
        out = cli._build_full_prompt(
            persona="P",
            user_context="ctx",
            memories_context="",
            history=[],
            history_limit=10,
            current_message="THE_FINAL_MESSAGE",
            image_paths=[],
            doc_paths=None,
            is_resumed_session=False,
        )
        # Current message is the last block.
        assert out.rfind("THE_FINAL_MESSAGE") > out.rfind("# Persona")


# ---------------------------------------------------------------------------
# _make_subprocess_env
# ---------------------------------------------------------------------------


class TestMakeSubprocessEnv:
    def test_includes_path(self, monkeypatch):
        monkeypatch.setenv("PATH", "/usr/bin")
        env = cli._make_subprocess_env()
        assert env.get("PATH") == "/usr/bin"

    def test_excludes_secrets(self, monkeypatch):
        monkeypatch.setenv("DISCORD_TOKEN", "secret123")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "ak-xxx")
        monkeypatch.setenv("DASHBOARD_WS_TOKEN", "wstok")
        env = cli._make_subprocess_env()
        assert "DISCORD_TOKEN" not in env
        assert "ANTHROPIC_API_KEY" not in env
        assert "DASHBOARD_WS_TOKEN" not in env

    def test_includes_claude_oauth_token(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "tok-x")
        env = cli._make_subprocess_env()
        assert env.get("CLAUDE_CODE_OAUTH_TOKEN") == "tok-x"


# ---------------------------------------------------------------------------
# _build_claude_argv
# ---------------------------------------------------------------------------


class TestBuildClaudeArgv:
    def test_basic_argv_no_session(self):
        argv = cli._build_claude_argv(
            "/usr/bin/claude",
            session_id=None,
            allow_read_for_images=False,
        )
        assert argv[0] == "/usr/bin/claude"
        assert "-p" in argv
        assert "--output-format" in argv
        assert "stream-json" in argv
        assert "--resume" not in argv

    def test_resume_with_session(self):
        argv = cli._build_claude_argv(
            "/usr/bin/claude",
            session_id="sess-abc",
            allow_read_for_images=False,
        )
        assert "--resume" in argv
        assert "sess-abc" in argv

    def test_thinking_flag(self):
        argv = cli._build_claude_argv(
            "/usr/bin/claude",
            session_id=None,
            allow_read_for_images=False,
            enable_thinking=True,
        )
        assert "--effort" in argv
        assert "max" in argv
        assert "interleaved-thinking" in argv

    def test_no_thinking_flag_by_default(self):
        argv = cli._build_claude_argv(
            "/usr/bin/claude",
            session_id=None,
            allow_read_for_images=False,
        )
        assert "--effort" not in argv


# ---------------------------------------------------------------------------
# _apply_search_replace
# ---------------------------------------------------------------------------


class TestApplySearchReplace:
    def test_no_patches_returns_original_response(self):
        result = cli._apply_search_replace("original", "just a plain reply")
        assert result == "just a plain reply"

    def test_applies_single_patch(self):
        original = "line a\nline b\nline c"
        patch_text = "<<<SEARCH\nline b\n>>>\n<<<REPLACE\nline B!\n>>>"
        result = cli._apply_search_replace(original, patch_text)
        assert "line B!" in result
        assert "\nline b\n" not in result

    def test_skips_ambiguous_match(self):
        original = "x\ny\nx\n"
        patch_text = "<<<SEARCH\nx\n>>>\n<<<REPLACE\nz\n>>>"
        result = cli._apply_search_replace(original, patch_text)
        # Skipped because of ambiguity — applied=0 so the function falls back
        # to returning the AI response unchanged (it's not a successful patch).
        assert result == patch_text

    def test_falls_back_to_full_response_when_no_match(self):
        original = "doesn't contain anything useful"
        patch_text = "<<<SEARCH\nMISSING\n>>>\n<<<REPLACE\nNEW\n>>>"
        result = cli._apply_search_replace(original, patch_text)
        assert result == patch_text


# ---------------------------------------------------------------------------
# is_cli_backend_ready / _resolve_claude_executable
# ---------------------------------------------------------------------------


class TestCliBackendReady:
    def test_ok_when_claude_on_path(self):
        with patch.object(cli, "_resolve_claude_executable", return_value="/usr/bin/claude"):
            ok, reason = cli.is_cli_backend_ready()
            assert ok is True
            assert reason == ""

    def test_fail_when_claude_missing(self):
        with patch.object(cli, "_resolve_claude_executable", return_value=None):
            ok, reason = cli.is_cli_backend_ready()
            assert ok is False
            assert "PATH" in reason


# ---------------------------------------------------------------------------
# _get_conversation_lock LRU
# ---------------------------------------------------------------------------


class TestConversationLock:
    def test_returns_lock_instance(self):
        lock = cli._get_conversation_lock("conv-x")
        assert isinstance(lock, asyncio.Lock)

    def test_same_conv_returns_same_lock(self):
        a = cli._get_conversation_lock("conv-y")
        b = cli._get_conversation_lock("conv-y")
        assert a is b

    def test_different_convs_get_different_locks(self):
        a = cli._get_conversation_lock("conv-1")
        b = cli._get_conversation_lock("conv-2")
        assert a is not b


# ---------------------------------------------------------------------------
# _encode_claude_project_dirname (extra cases)
# ---------------------------------------------------------------------------


class TestEncodeProjectDirnameExtra:
    def test_replaces_underscore(self):
        out = cli._encode_claude_project_dirname(Path("/foo_bar/baz_qux"))
        assert "_" not in out

    def test_replaces_space(self):
        out = cli._encode_claude_project_dirname(Path("BOT Discord/data"))
        assert " " not in out

    def test_replaces_colon(self):
        out = cli._encode_claude_project_dirname(Path("c:\\users\\me"))
        assert ":" not in out
