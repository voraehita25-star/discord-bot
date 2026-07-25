"""Per-generation Claude model capability rules.

The Messages API changes its *defaults* between generations, so a bare model-id
swap can silently change behaviour. Two rules matter for this repo:

1. ``budget_tokens`` (manual extended thinking) was removed on Opus 4.6+,
   Sonnet 4.6+, Opus 5 / Sonnet 5, and the Fable/Mythos 5 family — sending it
   returns a 400. Those generations use ``thinking: {"type": "adaptive"}``.
2. **Omitting** ``thinking`` meant "no thinking" through Opus 4.8, but Claude
   Opus 5 / Sonnet 5 / Fable / Mythos run adaptive thinking when the field is
   absent. Turning thinking OFF on those models has to be *explicit*, or a
   ``!thinking off`` / dashboard toggle stops having any effect.

Both tables are hardcoded generation allowlists — extend them whenever a new
Claude generation ships. They live here, rather than next to one handler, so
the Discord SDK path and the two dashboard SDK paths cannot drift apart.
"""

from __future__ import annotations

# Models that use adaptive thinking (``thinking: {"type": "adaptive"}``) rather
# than the deprecated manual ``budget_tokens`` form. Older extended-thinking-only
# models (Opus 4.5/4.1, Sonnet 4.5) are absent on purpose: callers fall through
# to the budget_tokens branch for backward compatibility.
ADAPTIVE_THINKING_MODELS: tuple[str, ...] = (
    "opus-5",
    "opus-4-8",
    "opus-4-7",
    "opus-4-6",
    "sonnet-5",
    "sonnet-4-6",
    "fable",
    "mythos",
)

# Models where omitting ``thinking`` still runs adaptive thinking, so "off"
# must be sent as an explicit ``{"type": "disabled"}``.
THINKING_ON_BY_DEFAULT_MODELS: tuple[str, ...] = (
    "opus-5",
    "sonnet-5",
    "fable",
    "mythos",
)

# Models that reject ``{"type": "disabled"}`` outright (thinking is always on and
# cannot be turned off at any effort). Requests must simply omit the field.
THINKING_ALWAYS_ON_MODELS: tuple[str, ...] = ("fable", "mythos")

# Claude Opus 5 accepts ``{"type": "disabled"}`` only at effort ``high`` or
# below — pairing it with ``xhigh``/``max`` is a 400. The cap is applied to every
# model rather than kept as a second per-model table: ``high`` is a valid effort
# everywhere, and a disabled-thinking turn has no deep reasoning to fund anyway.
DISABLED_THINKING_MAX_EFFORT = "high"

# Ascending reasoning depth; used only to decide whether an effort exceeds the cap.
_EFFORT_RANK: dict[str, int] = {"low": 0, "medium": 1, "high": 2, "xhigh": 3, "max": 4}


def _matches(model: str, tags: tuple[str, ...]) -> bool:
    model_lower = (model or "").lower()
    return any(tag in model_lower for tag in tags)


def uses_adaptive_thinking(model: str) -> bool:
    """True if the model uses adaptive thinking instead of manual ``budget_tokens``."""
    return _matches(model, ADAPTIVE_THINKING_MODELS)


def thinking_can_be_disabled(model: str) -> bool:
    """False when the model refuses to stop thinking at any effort.

    Fable/Mythos 400 on an explicit ``{"type": "disabled"}`` and think anyway
    when the field is omitted, so a "thinking off" toggle cannot be honoured on
    them at all. Callers use this to tell the user instead of failing silently.

    Note this is a *model* property. The Claude Code CLI backend has its own
    limitation — it exposes reasoning depth only through ``--effort``, with no
    way to switch thinking off — which is a property of that backend, not of
    the model, and is handled at those call sites.
    """
    return not _matches(model, THINKING_ALWAYS_ON_MODELS)


def thinking_off_config(model: str) -> dict[str, str] | None:
    """The ``thinking`` payload needed to actually turn thinking OFF.

    Returns ``{"type": "disabled"}`` for generations that would otherwise think
    by default, and ``None`` when omitting the field is already correct (Opus 4.8
    and earlier) or when the model refuses to be disabled at all (Fable/Mythos).
    """
    if _matches(model, THINKING_ALWAYS_ON_MODELS):
        return None
    if _matches(model, THINKING_ON_BY_DEFAULT_MODELS):
        return {"type": "disabled"}
    return None


def effort_with_thinking_off(effort: str | None) -> str | None:
    """Clamp an effort tier to what ``{"type": "disabled"}`` accepts.

    Unrecognised tiers pass through untouched — ``CLAUDE_EFFORT`` is already
    validated upstream, and guessing at an unknown tier's depth would be worse
    than forwarding it.
    """
    if effort is None:
        return None
    rank = _EFFORT_RANK.get(effort)
    if rank is None or rank <= _EFFORT_RANK[DISABLED_THINKING_MAX_EFFORT]:
        return effort
    return DISABLED_THINKING_MAX_EFFORT
