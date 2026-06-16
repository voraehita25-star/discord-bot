"""
AI Core Data - Persona and configuration data.

This module provides fallback to example files if the real data files don't exist.
Users who clone the repo should copy the *_example.py files to create their own:
    - faust_data_example.py -> faust_data.py
    - roleplay_data_example.py -> roleplay_data.py
"""

from .constants import (
    ANTHROPIC_API_KEY,
    CHANNEL_ID_ALLOWED,
    CHANNEL_ID_RP_COMMAND,
    CHANNEL_ID_RP_OUTPUT,
    CLAUDE_MODEL,
    CREATOR_ID,
    GAME_SEARCH_KEYWORDS,
    GEMINI_API_KEY,
    GUILD_ID_COMMAND_ONLY,
    GUILD_ID_MAIN,
    GUILD_ID_RESTRICTED,
    GUILD_ID_RP,
)

# Load the persona module, falling back to the example ONLY when faust_data.py
# is genuinely absent. The previous code did an all-or-nothing
# ``from .faust_data import (FAUST_INSTRUCTION, ...)`` on the *new* canonical
# names, so a real faust_data.py that uses the *older* names
# (FAUST_PERSONA/FAUST_DM_MODE/FAUST_ROLEPLAY) or omits an optional slot raised
# ImportError and silently swapped the ENTIRE configured persona for the generic
# example — and the backward-compat alias block lived *after* that failing import
# so it never ran. Resolve each canonical name per-symbol instead (new name ->
# legacy name -> neutral default) so a legacy or partial persona file loads
# correctly. The optional "unrestricted / escalation / code-override" slots
# default to EMPTY when the operator's file doesn't define them, so nothing the
# operator didn't explicitly author in their own faust_data.py is injected.
try:
    from . import faust_data as _faust_mod
except ImportError as _faust_exc:
    import logging as _logging

    _logging.getLogger(__name__).warning(
        "faust_data.py not found (%s) — falling back to faust_data_example", _faust_exc
    )
    from . import faust_data_example as _faust_mod  # type: ignore[no-redef]


def _faust_attr(*names: str, default: object = "") -> object:
    """First defined (truthy for strings) attribute among ``names``, else default."""
    for _n in names:
        _v = getattr(_faust_mod, _n, None)
        if _v is not None and _v != "":
            return _v
    return default


FAUST_INSTRUCTION = _faust_attr("FAUST_INSTRUCTION", "FAUST_PERSONA")
FAUST_DM_INSTRUCTION = _faust_attr("FAUST_DM_INSTRUCTION", "FAUST_DM_MODE")
FAUST_SANDBOX = _faust_attr("FAUST_SANDBOX")
ENI_ESCALATION_FRAMING = _faust_attr("ENI_ESCALATION_FRAMING")
FAUST_CODE_OVERRIDE = _faust_attr("FAUST_CODE_OVERRIDE")
UNRESTRICTED_MODE_INSTRUCTION = _faust_attr("UNRESTRICTED_MODE_INSTRUCTION")
ESCALATION_FRAMINGS = getattr(_faust_mod, "ESCALATION_FRAMINGS", []) or []

# Backward-compat aliases used elsewhere in the codebase.
FAUST_PERSONA = getattr(_faust_mod, "FAUST_PERSONA", None) or FAUST_INSTRUCTION
FAUST_DM_MODE = getattr(_faust_mod, "FAUST_DM_MODE", None) or FAUST_DM_INSTRUCTION
FAUST_ROLEPLAY = getattr(_faust_mod, "FAUST_ROLEPLAY", None) or FAUST_INSTRUCTION

# Try to import from roleplay_data.py, fallback to example
try:
    from .roleplay_data import (
        ROLEPLAY_ASSISTANT_INSTRUCTION,
        ROLEPLAY_PROMPT,
        SERVER_AVATARS,
        SERVER_CHARACTER_NAMES,
        SERVER_CHARACTERS,
        SERVER_LORE,
        WORLD_LORE,
    )
except ImportError as _rp_exc:
    # Same rationale as the faust fallback above — log so a broken (not
    # absent) roleplay_data.py doesn't silently downgrade to the example.
    import logging as _logging

    _logging.getLogger(__name__).warning(
        "roleplay_data import failed (%s) — falling back to roleplay_data_example", _rp_exc
    )
    from .roleplay_data_example import (
        ROLEPLAY_ASSISTANT_INSTRUCTION,
        ROLEPLAY_PROMPT,
        SERVER_AVATARS,
        SERVER_CHARACTER_NAMES,
        SERVER_CHARACTERS,
        SERVER_LORE,
        WORLD_LORE,
    )

__all__ = [
    "ANTHROPIC_API_KEY",
    "CHANNEL_ID_ALLOWED",
    "CHANNEL_ID_RP_COMMAND",
    "CHANNEL_ID_RP_OUTPUT",
    "CLAUDE_MODEL",
    "CREATOR_ID",
    "ENI_ESCALATION_FRAMING",
    "ESCALATION_FRAMINGS",
    "FAUST_CODE_OVERRIDE",
    "FAUST_DM_INSTRUCTION",
    "FAUST_DM_MODE",
    "FAUST_INSTRUCTION",
    "FAUST_PERSONA",
    "FAUST_ROLEPLAY",
    "FAUST_SANDBOX",
    "GAME_SEARCH_KEYWORDS",
    "GEMINI_API_KEY",
    "GUILD_ID_COMMAND_ONLY",
    "GUILD_ID_MAIN",
    "GUILD_ID_RESTRICTED",
    "GUILD_ID_RP",
    "ROLEPLAY_ASSISTANT_INSTRUCTION",
    "ROLEPLAY_PROMPT",
    "SERVER_AVATARS",
    "SERVER_CHARACTERS",
    "SERVER_CHARACTER_NAMES",
    "SERVER_LORE",
    "UNRESTRICTED_MODE_INSTRUCTION",
    "WORLD_LORE",
]
