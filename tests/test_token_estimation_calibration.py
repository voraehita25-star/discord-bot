# pylint: disable=protected-access
"""Regression: the token math was calibrated for a language the bot doesn't speak.

Both numbers below were measured with cl100k_base against this bot's own stored
history (267,614 chars of Thai RP), not assumed:

    non-ASCII alone : 229,304 chars -> 219,187 tokens = 1.046 chars/token
    ASCII alone     :  38,310 chars ->  15,050 tokens = 2.546 chars/token
    English prose   :     900 chars ->     201 tokens = 4.48  chars/token

Two things were built on the wrong figure:

1. ``_estimate_tokens_fallback`` divided non-ASCII by 2.5 and called that "more
   conservative" — it under-counted Thai by ~58%. It drives
   ``smart_trim_by_tokens``, which the over-limit "📝 ย่อประวัติแชท" button runs,
   so an over-window history looked like it already fit: the trim removed
   nothing, reported success, and the next turn was over the limit again.

2. ``_prompt_max_chars_from_env`` defaulted to 1,200,000 chars, justified as
   "roughly a full 1M-token window for Thai text at ~1-2 chars/token". At the
   real 1.116 that is ~1,075,000 tokens — about 75,000 OVER the window, before
   the reply gets any room. The ceiling whose stated purpose is preventing
   context overflow was permitting it.
"""

from __future__ import annotations

import pytest


class TestFallbackEstimatorMatchesThai:
    @staticmethod
    def _fallback(text: str) -> int:
        from cogs.ai_core.memory.history_manager import history_manager

        return history_manager._estimate_tokens_fallback(text)

    @staticmethod
    def _tiktoken(text: str) -> int | None:
        from cogs.ai_core.memory.history_manager import (
            _TIKTOKEN_ENCODER,
            TIKTOKEN_AVAILABLE,
        )

        if not TIKTOKEN_AVAILABLE or _TIKTOKEN_ENCODER is None:
            return None
        return len(_TIKTOKEN_ENCODER.encode(text))

    def test_thai_is_close_to_the_real_rate(self):
        """The old 2.5 divisor put this at ~44% of the truth."""
        thai = "สวัสดีครับวันนี้อากาศเป็นอย่างไรบ้าง" * 40
        real = self._tiktoken(thai)
        if real is None:
            pytest.skip("tiktoken unavailable — nothing to calibrate against")

        estimate = self._fallback(thai)
        assert 0.75 * real <= estimate <= 1.35 * real, (
            f"fallback {estimate} vs tiktoken {real} for Thai — the fallback "
            f"drives a trim that permanently deletes rows"
        )

    def test_english_prose_stays_reasonable(self):
        """ASCII is unchanged at 4 chars/token; prose measures 4.48."""
        english = "The quick brown fox jumps over the lazy dog. " * 40
        real = self._tiktoken(english)
        if real is None:
            pytest.skip("tiktoken unavailable")

        estimate = self._fallback(english)
        assert 0.75 * real <= estimate <= 1.5 * real

    def test_mixed_thai_english_is_close(self):
        mixed = "ผมชอบ programming และ machine learning มากครับ " * 40
        real = self._tiktoken(mixed)
        if real is None:
            pytest.skip("tiktoken unavailable")

        estimate = self._fallback(mixed)
        assert 0.75 * real <= estimate <= 1.35 * real

    def test_the_old_divisor_would_fail_this(self):
        """Pins WHY the constant moved, so a future edit back to 2.5 is caught."""
        from cogs.ai_core.memory.history_manager import history_manager

        assert history_manager._NON_ASCII_CHARS_PER_TOKEN <= 1.2, (
            "non-ASCII measures 1.046 chars/token; anything near the old 2.5 "
            "under-counts Thai badly enough to make the over-limit trim a no-op"
        )

    def test_empty_content_is_zero(self):
        assert self._fallback("") == 0


class TestPromptCeilingFitsTheWindow:
    # Measured overall rate on the real corpus; Thai alone is denser still.
    MEASURED_CHARS_PER_TOKEN = 1.116
    MODEL_WINDOW_TOKENS = 1_000_000

    def test_the_default_leaves_room_for_a_reply(self):
        from cogs.ai_core.api.dashboard_chat_claude_cli import _prompt_max_chars_from_env

        cap = _prompt_max_chars_from_env()
        implied_tokens = cap / self.MEASURED_CHARS_PER_TOKEN

        assert implied_tokens < self.MODEL_WINDOW_TOKENS, (
            f"{cap:,} chars is ~{implied_tokens:,.0f} tokens at the measured "
            f"Thai rate — over the {self.MODEL_WINDOW_TOKENS:,}-token window, so "
            f"the ceiling meant to prevent context overflow permits it"
        )
        # And not so tight that ordinary long RP channels start tripping it.
        assert implied_tokens > 0.5 * self.MODEL_WINDOW_TOKENS

    def test_the_env_override_still_wins(self, monkeypatch):
        from cogs.ai_core.api.dashboard_chat_claude_cli import _prompt_max_chars_from_env

        monkeypatch.setenv("CLI_PROMPT_MAX_CHARS", "12345")
        assert _prompt_max_chars_from_env() == 12345

    def test_zero_still_disables_the_clip(self, monkeypatch):
        from cogs.ai_core.api.dashboard_chat_claude_cli import _prompt_max_chars_from_env

        monkeypatch.setenv("CLI_PROMPT_MAX_CHARS", "0")
        assert _prompt_max_chars_from_env() == 0
