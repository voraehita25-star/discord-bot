# pylint: disable=protected-access
"""Tests for the backend-agnostic memory extraction helper.

Before this existed, ``consolidator`` and ``summarizer`` both reached a model
only through an Anthropic SDK client — which under ``CLAUDE_BACKEND=cli``, the
DEFAULT, is never constructed. So the consolidator never extracted a fact, the
summarizer never produced a summary, and combined with the MCP ``remember`` tool
being withheld at minimal tool scope, ``!remember`` was the only writer any
long-term store had. The bot could be told things but never noticed anything.

Nothing here spawns a real ``claude -p``: ``_run_claude_subprocess`` is mocked.
The suite-wide conftest fixture pins the backend to ``sdk`` for exactly that
reason, so every test that wants the CLI branch opts in explicitly.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _sdk_client(text: str):
    """A stand-in Anthropic client whose reply is split across two text blocks."""
    client = MagicMock()
    response = MagicMock()
    half = len(text) // 2
    blocks = []
    for part in (text[:half], text[half:]):
        block = MagicMock()
        block.type = "text"
        block.text = part
        blocks.append(block)
    response.content = blocks
    client.messages.create = AsyncMock(return_value=response)
    return client


class TestBackendSelection:
    @staticmethod
    def _mode():
        from cogs.ai_core.memory.extraction_backend import _backend_mode

        return _backend_mode()

    def test_default_is_auto(self, monkeypatch):
        monkeypatch.delenv("MEMORY_EXTRACTION_BACKEND", raising=False)
        assert self._mode() == "auto"

    def test_unknown_value_falls_back_to_auto(self, monkeypatch):
        monkeypatch.setenv("MEMORY_EXTRACTION_BACKEND", "banana")
        assert self._mode() == "auto"

    @pytest.mark.parametrize("mode", ["auto", "sdk", "cli", "off"])
    def test_known_values_pass_through(self, monkeypatch, mode):
        monkeypatch.setenv("MEMORY_EXTRACTION_BACKEND", mode.upper() + " ")
        assert self._mode() == mode


class TestAvailability:
    @staticmethod
    def _available(client):
        from cogs.ai_core.memory.extraction_backend import extraction_available

        return extraction_available(client)

    def test_off_means_no_backend_even_with_a_client(self, monkeypatch):
        monkeypatch.setenv("MEMORY_EXTRACTION_BACKEND", "off")
        assert self._available(object()) is False

    def test_a_client_is_enough(self, monkeypatch):
        monkeypatch.setenv("MEMORY_EXTRACTION_BACKEND", "auto")
        assert self._available(object()) is True

    def test_sdk_mode_never_reaches_the_cli(self, monkeypatch):
        """``sdk`` is what the test suite pins itself to, so this has to hold
        without stubbing the probe — the refusal lives inside it."""
        from cogs.ai_core.memory.extraction_backend import cli_extraction_available

        monkeypatch.setenv("MEMORY_EXTRACTION_BACKEND", "sdk")

        assert cli_extraction_available() is False
        assert self._available(None) is False

    def test_the_cli_alone_is_enough(self, monkeypatch):
        from cogs.ai_core.memory import extraction_backend

        monkeypatch.setenv("MEMORY_EXTRACTION_BACKEND", "auto")
        monkeypatch.setattr(extraction_backend, "cli_extraction_available", lambda: True)
        assert self._available(None) is True

    def test_a_broken_cli_probe_answers_no(self, monkeypatch):
        """An import failure inside the probe must not raise into a caller."""
        from cogs.ai_core.memory.extraction_backend import cli_extraction_available

        monkeypatch.setenv("MEMORY_EXTRACTION_BACKEND", "auto")
        with patch.dict("sys.modules", {"cogs.ai_core.api.dashboard_chat_claude_cli": None}):
            assert cli_extraction_available() is False


class TestCompleteText:
    @staticmethod
    async def _complete(**kwargs):
        from cogs.ai_core.memory.extraction_backend import complete_text

        return await complete_text(**kwargs)

    @pytest.mark.asyncio
    async def test_sdk_path_joins_every_text_block(self, monkeypatch):
        """A reply split across blocks must not be truncated to the first."""
        monkeypatch.setenv("MEMORY_EXTRACTION_BACKEND", "auto")
        client = _sdk_client('{"entities": []}')

        out = await self._complete(prompt="p", max_tokens=100, client=client, model="m")

        assert out == '{"entities": []}'

    @pytest.mark.asyncio
    async def test_off_returns_empty_without_calling_anything(self, monkeypatch):
        monkeypatch.setenv("MEMORY_EXTRACTION_BACKEND", "off")
        client = _sdk_client("should not be used")

        out = await self._complete(prompt="p", max_tokens=100, client=client, model="m")

        assert out == ""
        client.messages.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_an_empty_prompt_short_circuits(self, monkeypatch):
        monkeypatch.setenv("MEMORY_EXTRACTION_BACKEND", "auto")
        client = _sdk_client("x")
        assert await self._complete(prompt="", max_tokens=10, client=client, model="m") == ""
        client.messages.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_an_sdk_failure_degrades_to_empty(self, monkeypatch):
        """The contract the callers rely on: a failure is 'nothing this round',
        never an exception into a background task."""
        monkeypatch.setenv("MEMORY_EXTRACTION_BACKEND", "auto")
        client = MagicMock()
        client.messages.create = AsyncMock(side_effect=RuntimeError("boom"))

        assert await self._complete(prompt="p", max_tokens=10, client=client, model="m") == ""

    @pytest.mark.asyncio
    async def test_an_sdk_timeout_degrades_to_empty(self, monkeypatch):
        monkeypatch.setenv("MEMORY_EXTRACTION_BACKEND", "auto")
        client = MagicMock()
        client.messages.create = AsyncMock(side_effect=TimeoutError())

        assert await self._complete(prompt="p", max_tokens=10, client=client, model="m") == ""


class TestCliPath:
    """The branch that makes the default backend work at all."""

    @staticmethod
    def _patch_cli(monkeypatch, *, chunks, session_id="sess-123", captured=None):
        from cogs.ai_core.api import dashboard_chat_claude_cli as cli_mod

        monkeypatch.setenv("MEMORY_EXTRACTION_BACKEND", "cli")
        monkeypatch.setattr(cli_mod, "is_cli_backend_ready", lambda: (True, ""))
        monkeypatch.setattr(cli_mod, "_resolve_claude_executable", lambda: "claude")

        async def fake_run(argv, prompt, **kwargs):
            if captured is not None:
                captured["argv"] = argv
                captured["prompt"] = prompt
            on_text = kwargs["on_text_delta"]
            for chunk in chunks:
                await on_text(chunk)
            return session_id, {"input_tokens": 1}

        monkeypatch.setattr(cli_mod, "_run_claude_subprocess", fake_run)
        unlink = AsyncMock(return_value=True)
        monkeypatch.setattr(cli_mod, "_unlink_session_file_by_id", unlink)
        return unlink

    @pytest.mark.asyncio
    async def test_it_returns_the_streamed_text(self, monkeypatch):
        from cogs.ai_core.memory.extraction_backend import complete_text

        self._patch_cli(monkeypatch, chunks=['{"enti', 'ties": []}'])

        assert await complete_text(prompt="p", max_tokens=100) == '{"entities": []}'

    @pytest.mark.asyncio
    async def test_the_argv_is_narrow(self, monkeypatch):
        """Extraction must not resume a session, browse, or carry MCP tools."""
        from cogs.ai_core.memory.extraction_backend import complete_text

        captured: dict = {}
        self._patch_cli(monkeypatch, chunks=["ok"], captured=captured)

        await complete_text(prompt="the prompt", max_tokens=100)

        argv = captured["argv"]
        assert "--resume" not in argv, "each extraction is independent"
        assert not any(a.startswith("mcp__") for a in argv)
        # Web tools would let an extraction browse on untrusted conversation text.
        assert "WebSearch" not in argv and "WebFetch" not in argv
        assert captured["prompt"] == "the prompt"

    @pytest.mark.asyncio
    async def test_reasoning_depth_is_pinned_deep_by_default(self, monkeypatch):
        """Extraction writes into long-term memory, so it does not economise on
        depth — an operator decision, pinned independently of CLAUDE_EFFORT.

        (An earlier ``low`` pin was removed: it rested on a failure mode that
        needs a ``--max-tokens`` the CLI does not expose, and measured identical
        input tokens with overlapping output/latency against ``max``.)
        """
        from cogs.ai_core.memory.extraction_backend import complete_text

        captured: dict = {}
        self._patch_cli(monkeypatch, chunks=["ok"], captured=captured)

        await complete_text(prompt="p", max_tokens=100)

        argv = captured["argv"]
        assert argv[argv.index("--effort") + 1] == "max"

    @pytest.mark.asyncio
    async def test_the_depth_is_tunable(self, monkeypatch):
        from cogs.ai_core.memory.extraction_backend import complete_text

        captured: dict = {}
        self._patch_cli(monkeypatch, chunks=["ok"], captured=captured)
        monkeypatch.setenv("MEMORY_EXTRACTION_EFFORT", "high")

        await complete_text(prompt="p", max_tokens=100)

        argv = captured["argv"]
        assert argv[argv.index("--effort") + 1] == "high"

    @pytest.mark.asyncio
    async def test_inherit_follows_the_operators_setting(self, monkeypatch):
        """The escape hatch back to "depth is an operator setting"."""
        from cogs.ai_core.api.dashboard_chat_claude_cli import _CLI_EFFORT
        from cogs.ai_core.memory.extraction_backend import complete_text

        captured: dict = {}
        self._patch_cli(monkeypatch, chunks=["ok"], captured=captured)
        monkeypatch.setenv("MEMORY_EXTRACTION_EFFORT", "inherit")

        await complete_text(prompt="p", max_tokens=100)

        argv = captured["argv"]
        assert argv[argv.index("--effort") + 1] == _CLI_EFFORT

    def test_a_bad_depth_falls_back_to_the_default(self, monkeypatch):
        from cogs.ai_core.memory.extraction_backend import _extraction_effort

        monkeypatch.setenv("MEMORY_EXTRACTION_EFFORT", "banana")
        assert _extraction_effort() == "max"
        monkeypatch.setenv("MEMORY_EXTRACTION_EFFORT", "  XHIGH ")
        assert _extraction_effort() == "xhigh"

    @pytest.mark.asyncio
    async def test_the_transcript_is_unlinked(self, monkeypatch):
        """Otherwise every consolidation orphans a .jsonl on disk."""
        from cogs.ai_core.memory.extraction_backend import complete_text

        unlink = self._patch_cli(monkeypatch, chunks=["ok"], session_id="sess-abc")

        await complete_text(prompt="p", max_tokens=100)

        unlink.assert_awaited_once_with("sess-abc")

    @pytest.mark.asyncio
    async def test_the_transcript_is_unlinked_even_when_the_run_fails(self, monkeypatch):
        from cogs.ai_core.api import dashboard_chat_claude_cli as cli_mod
        from cogs.ai_core.memory.extraction_backend import complete_text

        monkeypatch.setenv("MEMORY_EXTRACTION_BACKEND", "cli")
        monkeypatch.setattr(cli_mod, "is_cli_backend_ready", lambda: (True, ""))
        monkeypatch.setattr(cli_mod, "_resolve_claude_executable", lambda: "claude")

        async def boom(argv, prompt, **kwargs):
            raise RuntimeError("claude -p exit 1")

        monkeypatch.setattr(cli_mod, "_run_claude_subprocess", boom)
        unlink = AsyncMock(return_value=True)
        monkeypatch.setattr(cli_mod, "_unlink_session_file_by_id", unlink)

        assert await complete_text(prompt="p", max_tokens=100) == ""

    @pytest.mark.asyncio
    async def test_a_missing_binary_degrades_to_empty(self, monkeypatch):
        from cogs.ai_core.api import dashboard_chat_claude_cli as cli_mod
        from cogs.ai_core.memory.extraction_backend import complete_text

        monkeypatch.setenv("MEMORY_EXTRACTION_BACKEND", "cli")
        monkeypatch.setattr(cli_mod, "is_cli_backend_ready", lambda: (True, ""))
        monkeypatch.setattr(cli_mod, "_resolve_claude_executable", lambda: None)

        assert await complete_text(prompt="p", max_tokens=100) == ""

    @pytest.mark.asyncio
    async def test_concurrent_extractions_are_capped(self, monkeypatch):
        """A burst of channels crossing the threshold together must not fork a
        process per channel."""
        from cogs.ai_core.api import dashboard_chat_claude_cli as cli_mod
        from cogs.ai_core.memory import extraction_backend
        from cogs.ai_core.memory.extraction_backend import complete_text

        monkeypatch.setattr(extraction_backend, "_cli_slots", None)
        monkeypatch.setenv("MEMORY_EXTRACTION_BACKEND", "cli")
        monkeypatch.setattr(cli_mod, "is_cli_backend_ready", lambda: (True, ""))
        monkeypatch.setattr(cli_mod, "_resolve_claude_executable", lambda: "claude")
        monkeypatch.setattr(cli_mod, "_unlink_session_file_by_id", AsyncMock(return_value=True))

        live = 0
        peak = 0
        release = asyncio.Event()

        async def fake_run(argv, prompt, **kwargs):
            nonlocal live, peak
            live += 1
            peak = max(peak, live)
            await release.wait()
            live -= 1
            await kwargs["on_text_delta"]("ok")
            return "s", None

        monkeypatch.setattr(cli_mod, "_run_claude_subprocess", fake_run)

        tasks = [asyncio.create_task(complete_text(prompt="p", max_tokens=10)) for _ in range(6)]
        await asyncio.sleep(0.05)
        in_flight_before_release = peak
        release.set()
        await asyncio.gather(*tasks)

        assert in_flight_before_release <= extraction_backend._MAX_CONCURRENT_CLI_EXTRACTIONS
