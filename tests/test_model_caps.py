"""Tests for the Claude generation-capability tables (``data/model_caps.py``).

These guard the Opus 5 migration's non-obvious half. Swapping the model id is
harmless on its own; what silently changes behaviour is that **omitting** the
``thinking`` field stopped meaning "no thinking":

* Through Opus 4.8, a request with no ``thinking`` key ran without thinking, so
  the ``!thinking off`` / dashboard toggle worked by simply not setting it.
* On Opus 5 / Sonnet 5 the same request runs adaptive thinking, so "off" has to
  be sent as an explicit ``{"type": "disabled"}`` or the toggle does nothing.
* Opus 5 then rejects that payload above ``high`` effort with a 400, and the
  repo default is ``xhigh`` — hence the clamp.

Fable/Mythos are the third case: they reject ``disabled`` at *any* effort, so
the only correct request is to omit the field entirely.
"""

from __future__ import annotations

import pytest

from cogs.ai_core.data.model_caps import (
    DISABLED_THINKING_MAX_EFFORT,
    effort_with_thinking_off,
    thinking_can_be_disabled,
    thinking_off_config,
    uses_adaptive_thinking,
)


class TestUsesAdaptiveThinking:
    """``budget_tokens`` is a 400 on these generations — they must match."""

    @pytest.mark.parametrize(
        "model",
        [
            "claude-opus-5",
            "claude-opus-5[1m]",
            "claude-opus-4-8",
            "claude-opus-4-7",
            "claude-opus-4-6",
            "claude-sonnet-5",
            "claude-sonnet-4-6",
            "claude-fable-5",
            "claude-mythos-5",
        ],
    )
    def test_adaptive_generations(self, model: str) -> None:
        assert uses_adaptive_thinking(model) is True

    @pytest.mark.parametrize("model", ["claude-opus-4-5", "claude-sonnet-4-5", "claude-haiku-4-5"])
    def test_legacy_generations_keep_budget_tokens(self, model: str) -> None:
        assert uses_adaptive_thinking(model) is False

    def test_empty_model_is_not_adaptive(self) -> None:
        assert uses_adaptive_thinking("") is False


class TestThinkingOffConfig:
    """Turning thinking OFF is only implicit on pre-Opus-5 generations."""

    @pytest.mark.parametrize(
        "model",
        ["claude-opus-5", "claude-opus-5[1m]", "CLAUDE-OPUS-5", "claude-sonnet-5"],
    )
    def test_thinks_by_default_needs_explicit_disable(self, model: str) -> None:
        assert thinking_off_config(model) == {"type": "disabled"}

    @pytest.mark.parametrize("model", ["claude-opus-4-8[1m]", "claude-opus-4-7", "claude-opus-4-5"])
    def test_older_generations_omit_the_field(self, model: str) -> None:
        assert thinking_off_config(model) is None

    @pytest.mark.parametrize("model", ["claude-fable-5", "claude-mythos-5"])
    def test_always_on_models_must_not_send_disabled(self, model: str) -> None:
        # Fable/Mythos 400 on an explicit disable at any effort, so the only
        # valid request omits the field — even though they think by default.
        assert thinking_off_config(model) is None


class TestThinkingCanBeDisabled:
    """Drives the user-facing "this toggle can't apply here" warnings."""

    @pytest.mark.parametrize("model", ["claude-opus-5", "claude-opus-4-8", "claude-sonnet-5"])
    def test_normal_models_can_be_disabled(self, model: str) -> None:
        assert thinking_can_be_disabled(model) is True

    @pytest.mark.parametrize("model", ["claude-fable-5", "claude-mythos-5"])
    def test_always_on_models_cannot(self, model: str) -> None:
        assert thinking_can_be_disabled(model) is False

    def test_agrees_with_thinking_off_config(self) -> None:
        # A model that can't be disabled must never get a disable payload.
        for model in ("claude-fable-5", "claude-mythos-5"):
            assert thinking_off_config(model) is None


class TestEffortWithThinkingOff:
    """Opus 5 rejects disabled thinking above ``high``."""

    @pytest.mark.parametrize("effort", ["xhigh", "max"])
    def test_clamps_tiers_above_the_cap(self, effort: str) -> None:
        assert effort_with_thinking_off(effort) == DISABLED_THINKING_MAX_EFFORT

    @pytest.mark.parametrize("effort", ["low", "medium", "high"])
    def test_leaves_permitted_tiers_alone(self, effort: str) -> None:
        assert effort_with_thinking_off(effort) == effort

    def test_none_stays_none(self) -> None:
        assert effort_with_thinking_off(None) is None

    def test_unknown_tier_passes_through(self) -> None:
        # CLAUDE_EFFORT is validated upstream; guessing at an unknown tier's
        # depth would be worse than forwarding it untouched.
        assert effort_with_thinking_off("ludicrous") == "ludicrous"


class TestBuildApiConfigThinkingOff:
    """``build_api_config`` wires the explicit disable for the Discord SDK path."""

    def _config(self, monkeypatch: pytest.MonkeyPatch, model: str) -> dict:
        from cogs.ai_core.api import api_handler

        monkeypatch.setattr(api_handler, "CLAUDE_MODEL", model)
        # A plain (non-Faust, non-RP) instruction never enables thinking.
        return api_handler.build_api_config({"system_instruction": "Test"})

    def test_opus_5_gets_explicit_disable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        result = self._config(monkeypatch, "claude-opus-5")
        assert result["thinking"] == {"type": "disabled"}

    def test_opus_4_8_leaves_thinking_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        result = self._config(monkeypatch, "claude-opus-4-8")
        assert "thinking" not in result

    def test_rp_mode_still_thinks_adaptively(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from cogs.ai_core.api import api_handler

        monkeypatch.setattr(api_handler, "CLAUDE_MODEL", "claude-opus-5")
        result = api_handler.build_api_config(
            {
                "system_instruction": api_handler.ROLEPLAY_ASSISTANT_INSTRUCTION,
                "thinking_enabled": True,
            }
        )
        assert result["thinking"] == {"type": "adaptive"}


class TestThinkingToggleHandshake:
    """The dashboard is told up front whether the toggle controls anything.

    Without this the UI showed a live checkbox on the CLI backend that could
    never take effect — the whole reason the toggle read as broken.
    """

    def _support(self, monkeypatch: pytest.MonkeyPatch, backend: str, model: str) -> dict:
        from cogs.ai_core.api import ws_dashboard

        monkeypatch.setattr(ws_dashboard, "_CLAUDE_BACKEND", backend)
        monkeypatch.setattr(ws_dashboard, "CLAUDE_MODEL", model)
        return ws_dashboard._thinking_toggle_support()

    def test_cli_backend_reports_unsupported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        result = self._support(monkeypatch, "cli", "claude-opus-5")
        assert result["supported"] is False
        assert result["reason"]

    def test_sdk_backend_with_a_disableable_model_is_supported(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result = self._support(monkeypatch, "api", "claude-opus-5")
        assert result["supported"] is True

    def test_sdk_backend_with_always_on_model_reports_unsupported(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result = self._support(monkeypatch, "api", "claude-fable-5")
        assert result["supported"] is False
        assert "claude-fable-5" in result["reason"]


class TestSearchWriteToggleHandshake:
    """Search and Write report their own support, like Thinking does."""

    def _mod(self, monkeypatch: pytest.MonkeyPatch, **attrs):
        from cogs.ai_core.api import ws_dashboard

        for k, v in attrs.items():
            monkeypatch.setattr(ws_dashboard, k, v)
        return ws_dashboard

    def test_search_supported_on_cli_with_web_tools_on(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        w = self._mod(
            monkeypatch,
            _CLAUDE_BACKEND="cli",
            _CLI_WEB_TOOLS_ENABLED=True,
            AVAILABLE_PROVIDERS=["claude"],
        )
        assert w._web_search_toggle_support()["supported"] is True

    def test_search_unsupported_when_web_tools_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        w = self._mod(
            monkeypatch,
            _CLAUDE_BACKEND="cli",
            _CLI_WEB_TOOLS_ENABLED=False,
            AVAILABLE_PROVIDERS=["claude"],
        )
        result = w._web_search_toggle_support()
        assert result["supported"] is False
        assert "DASHBOARD_CLI_WEB_TOOLS" in result["reason"]

    def test_search_supported_whenever_gemini_is_available(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The Gemini handler reads use_search for grounding regardless of the
        # Claude backend, so the control is live even with Claude web tools off.
        w = self._mod(
            monkeypatch,
            _CLAUDE_BACKEND="api",
            _CLI_WEB_TOOLS_ENABLED=False,
            AVAILABLE_PROVIDERS=["claude", "gemini"],
        )
        assert w._web_search_toggle_support()["supported"] is True

    def test_write_unsupported_when_env_flag_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        w = self._mod(monkeypatch, _CLAUDE_BACKEND="cli")
        monkeypatch.setattr(w, "_dashboard_cli_write_enabled", lambda: False)
        result = w._write_mode_toggle_support()
        assert result["supported"] is False
        assert "DASHBOARD_CLI_ALLOW_WRITE" in result["reason"]

    def test_write_unsupported_when_no_root_resolves(self, monkeypatch: pytest.MonkeyPatch) -> None:
        w = self._mod(monkeypatch, _CLAUDE_BACKEND="cli")
        monkeypatch.setattr(w, "_dashboard_cli_write_enabled", lambda: True)
        monkeypatch.setattr(w, "_dashboard_cli_write_dirs", list)
        result = w._write_mode_toggle_support()
        assert result["supported"] is False
        assert "DASHBOARD_CLI_WRITE_DIRS" in result["reason"]

    def test_write_supported_reports_its_roots(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from pathlib import Path

        w = self._mod(monkeypatch, _CLAUDE_BACKEND="cli")
        monkeypatch.setattr(w, "_dashboard_cli_write_enabled", lambda: True)
        monkeypatch.setattr(w, "_dashboard_cli_write_dirs", lambda: [Path("/tmp/out")])
        result = w._write_mode_toggle_support()
        assert result["supported"] is True
        # The tooltip states the blast radius before the user ticks the box.
        assert result["roots"] == [str(Path("/tmp/out"))]


class TestOpus5Pricing:
    """Opus 5 bills at the Opus tier — not the Sonnet fallback."""

    def test_opus_5_has_an_explicit_rate(self) -> None:
        from cogs.ai_core.cache.token_tracker import TokenUsage

        rates = dict(TokenUsage._CLAUDE_PRICING)
        assert rates["claude-opus-5"] == (5.0, 25.0)

    def test_estimated_cost_matches_opus_rates(self) -> None:
        from datetime import datetime

        from cogs.ai_core.cache.token_tracker import TokenUsage

        usage = TokenUsage(
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            timestamp=datetime.now(),
            user_id=1,
            channel_id=2,
            model="claude-opus-5[1m]",
        )
        assert usage.estimated_cost == pytest.approx(30.0)


class TestThinkingOffKwargsOnUtilityCalls:
    """The non-conversational helpers must send thinking OFF explicitly.

    They run on tiny ``max_tokens`` budgets (10 for the search-intent
    classifier, 1000 for the summarizer and the fact extractor), and on the
    generations that reason by DEFAULT (Opus 5 / Sonnet 5 — the repo default)
    an omitted ``thinking`` field means adaptive thinking while ``max_tokens``
    caps thinking PLUS visible text. Without the explicit disable the budget is
    spent on reasoning and these calls return empty or truncated output.
    """

    def test_kwargs_disable_thinking_on_think_by_default_models(self) -> None:
        from cogs.ai_core.data.model_caps import thinking_off_kwargs

        for model in ("claude-opus-5", "claude-opus-5[1m]", "claude-sonnet-5"):
            assert thinking_off_kwargs(model) == {"thinking": {"type": "disabled"}}

    def test_kwargs_empty_where_omitting_already_means_off(self) -> None:
        from cogs.ai_core.data.model_caps import thinking_off_kwargs

        # Opus 4.8 and earlier: omitting the field genuinely means "no thinking".
        for model in ("claude-opus-4-8", "claude-opus-4-7", "claude-opus-4-6"):
            assert thinking_off_kwargs(model) == {}

    def test_kwargs_empty_for_always_on_models(self) -> None:
        from cogs.ai_core.data.model_caps import thinking_off_kwargs

        # Fable/Mythos 400 on an explicit disable — the field must be omitted.
        for model in ("claude-fable-5", "claude-mythos-5"):
            assert thinking_off_kwargs(model) == {}

    def test_no_output_config_emitted(self) -> None:
        from cogs.ai_core.data.model_caps import thinking_off_kwargs

        # The API's default effort is `high`, which is exactly what a
        # disabled-thinking request accepts — emitting one would change
        # reasoning depth rather than only switching thinking off.
        assert "output_config" not in thinking_off_kwargs("claude-opus-5")

    @pytest.mark.asyncio
    async def test_search_intent_classifier_disables_thinking(self) -> None:
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, MagicMock

        from cogs.ai_core.api.api_handler import detect_search_intent

        client = MagicMock()
        client.messages = MagicMock()
        client.messages.create = AsyncMock(
            return_value=SimpleNamespace(content=[SimpleNamespace(type="text", text="SEARCH")])
        )

        assert await detect_search_intent(client, "claude-opus-5", "what is the latest patch?")
        kwargs = client.messages.create.await_args.kwargs
        assert kwargs["thinking"] == {"type": "disabled"}
        # A 10-token budget shared with adaptive thinking returns no text at all.
        assert kwargs["max_tokens"] == 10

    @pytest.mark.asyncio
    async def test_summarizer_disables_thinking(self) -> None:
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, MagicMock

        from cogs.ai_core.memory.summarizer import ConversationSummarizer

        summarizer = ConversationSummarizer()
        summarizer.model = "claude-opus-5"
        summarizer.client = MagicMock()
        summarizer.client.messages = MagicMock()
        summarizer.client.messages.create = AsyncMock(
            return_value=SimpleNamespace(
                content=[SimpleNamespace(type="text", text="A summary of the chat.")]
            )
        )

        history = [
            {"role": "user", "parts": [f"message number {i} with enough text to pass the floor"]}
            for i in range(12)
        ]
        assert await summarizer.summarize(history) == "A summary of the chat."
        assert summarizer.client.messages.create.await_args.kwargs["thinking"] == {
            "type": "disabled"
        }
