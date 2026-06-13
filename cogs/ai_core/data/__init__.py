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

# Try to import from faust_data.py, fallback to example
try:
    from .faust_data import (
        ENI_ESCALATION_FRAMING,
        ESCALATION_FRAMINGS,
        FAUST_CODE_OVERRIDE,
        FAUST_DM_INSTRUCTION,
        FAUST_INSTRUCTION,
        FAUST_SANDBOX,
        UNRESTRICTED_MODE_INSTRUCTION,
    )

    # Backward compatibility aliases
    try:
        from .faust_data import FAUST_DM_MODE, FAUST_PERSONA, FAUST_ROLEPLAY
    except ImportError:
        FAUST_DM_MODE = FAUST_DM_INSTRUCTION
        FAUST_PERSONA = FAUST_INSTRUCTION
        FAUST_ROLEPLAY = FAUST_INSTRUCTION
except ImportError as _faust_exc:
    # Fallback to example file. Log it: a REAL faust_data.py that exists but
    # raises ImportError (e.g. one renamed symbol in the import list) would
    # otherwise silently swap the entire live persona for the generic
    # example with no signal. A genuinely-absent file is the expected
    # "some assembly required" case, so keep it at WARNING, not ERROR.
    import logging as _logging

    _logging.getLogger(__name__).warning(
        "faust_data import failed (%s) — falling back to faust_data_example", _faust_exc
    )
    from .faust_data_example import (  # type: ignore[assignment]
        ENI_ESCALATION_FRAMING,
        ESCALATION_FRAMINGS,
        FAUST_CODE_OVERRIDE,
        FAUST_DM_INSTRUCTION,
        FAUST_INSTRUCTION,
        FAUST_SANDBOX,
        UNRESTRICTED_MODE_INSTRUCTION,
    )

    FAUST_DM_MODE = FAUST_DM_INSTRUCTION
    FAUST_PERSONA = FAUST_INSTRUCTION
    FAUST_ROLEPLAY = FAUST_INSTRUCTION

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
