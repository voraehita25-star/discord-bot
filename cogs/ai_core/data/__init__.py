"""
AI Core Data - Persona and configuration data.

This module provides fallback to example files if the real data files don't exist.
Users who clone the repo should copy the .example.py files to create their own:
    - faust_data.example.py -> faust_data.py
    - roleplay_data.example.py -> roleplay_data.py
"""

from .constants import (
    CHANNEL_ID_ALLOWED,
    CHANNEL_ID_RP_COMMAND,
    CHANNEL_ID_RP_OUTPUT,
    CREATOR_ID,
    GAME_SEARCH_KEYWORDS,
    GEMINI_API_KEY,
    GEMINI_MODEL,
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
except ImportError:
    # Fallback to example file
    from .faust_data_example import (
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
except ImportError:
    # Fallback to example file
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
    # Constants
    "CHANNEL_ID_ALLOWED",
    "CHANNEL_ID_RP_COMMAND",
    "CHANNEL_ID_RP_OUTPUT",
    "CREATOR_ID",
    "ENI_ESCALATION_FRAMING",
    "ESCALATION_FRAMINGS",
    "FAUST_CODE_OVERRIDE",
    "FAUST_DM_INSTRUCTION",
    "FAUST_DM_MODE",
    "FAUST_INSTRUCTION",
    # Faust data
    "FAUST_PERSONA",
    "FAUST_ROLEPLAY",
    "FAUST_SANDBOX",
    "GAME_SEARCH_KEYWORDS",
    "GEMINI_API_KEY",
    "GEMINI_MODEL",
    "GUILD_ID_COMMAND_ONLY",
    "GUILD_ID_MAIN",
    "GUILD_ID_RESTRICTED",
    "GUILD_ID_RP",
    "UNRESTRICTED_MODE_INSTRUCTION",
    # Roleplay data
    "ROLEPLAY_ASSISTANT_INSTRUCTION",
    "ROLEPLAY_PROMPT",
    "SERVER_AVATARS",
    "SERVER_CHARACTER_NAMES",
    "SERVER_CHARACTERS",
    "SERVER_LORE",
    "WORLD_LORE",
]
