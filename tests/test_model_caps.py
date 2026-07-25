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
