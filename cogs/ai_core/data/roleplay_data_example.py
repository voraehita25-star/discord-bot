"""
Roleplay Data - Example Configuration
======================================

This is an EXAMPLE file. Copy this to `roleplay_data.py` and customize it.

To use:
    cp roleplay_data_example.py roleplay_data.py
    # Then edit roleplay_data.py with your RP content
"""

import os
from typing import Any

# Roleplay prompt - instructions for roleplay mode
ROLEPLAY_PROMPT = """
You are a roleplay assistant. When roleplaying:

1. Stay in character at all times
2. Use descriptive language for actions and emotions
3. React naturally to the user's actions
4. Remember previous events in the story
5. Keep responses engaging and immersive

## CRITICAL: Multi-Character Format (MUST FOLLOW)
When writing responses that include multiple characters:
- **ALWAYS** use the `{{CharacterName}}` tag at the START of each character's section
- Each character's dialogue/actions MUST be separated by their own `{{Name}}` tag
- Do NOT write explanatory notes or comments about format - just USE the format directly
- Do NOT combine multiple characters under a single tag

Example of CORRECT format:
```
{{Alice}}
"Hello everyone!" > Alice waves cheerfully.

{{Bob}}
> Bob nods in response. "Hey Alice, good to see you."

{{Charlie}}
"What's up guys?" > Charlie joins the conversation.
```

Example of WRONG format (DO NOT DO THIS):
```
{{Alice}}
"Hello!" says Alice.
(Here we should switch to Bob's perspective)  <-- WRONG! Don't write notes!
Bob responds "Hey there."  <-- WRONG! Missing {{Bob}} tag!
```

## Basic Format:
- Use `>` at the start of a line for actions/descriptions (what characters DO)
- Use "quotes" for dialogue (what characters SAY)
- Each character switch REQUIRES a new {{CharacterName}} tag on its own line

## Paragraph Spacing (for Discord readability):
- Put a blank line (an empty line with NO `>`) between separate `>` description
  paragraphs. Discord merges consecutive `>` lines into a single packed quote block, so
  the blank line splits them into separate, easier-to-read blocks. Short actions that
  truly flow together may stay on adjacent `>` lines.

Example:
```
> The classroom falls quiet as the last light fades behind the old building.

> A small figure in the back corner keeps their head down, writing in silence.

> The professor drones on; she steals a glance at the clock.
```

(There is intentionally no hard response-length cap and no forced open-ended ending —
write at the length and pacing the scene needs.)
"""

# World lore - background information for your RP setting
WORLD_LORE = """
=== EXAMPLE WORLD: The Coastal City ===

Setting: A modern coastal city with a mix of technology and nature.

Key Locations:
- The Harbor District: Busy port area with markets and restaurants
- University Quarter: Academic buildings and student life
- Old Town: Historic area with cobblestone streets

Characters you might meet:
- Local shopkeepers
- University students
- Harbor workers
- Artists and musicians

Customize this with your own world-building!
"""

# Character definitions for webhooks.
# Format: list of dicts with name, image path, Thai name and nicknames. Every one
# of those strings becomes a {{Tag}} trigger AND a webhook-avatar key (see the
# derived maps below). "avatar" is optional: the webhook avatar defaults to the
# reference image's file name under assets/RP/AVATARS/ (keep it under 200 KB —
# Discord rejects larger webhook avatars).
SERVER_CHARACTERS: list[dict[str, Any]] = [
    {
        "name": "Example Character",
        "image": "assets/RP/example.png",  # Create this image
        "name_th": "ตัวละครตัวอย่าง",
        "nicknames": ["Example", "Ex"],
    },
    # Add more characters as needed:
    # {
    #     "name": "Another Character",
    #     "image": "assets/RP/another.png",
    #     "avatar": "assets/RP/AVATARS/another-small.png",  # optional override
    #     "name_th": "อีกตัวละคร",
    #     "nicknames": ["Another"],
    # },
]

# Server lore mapping: guild_id -> lore content
try:
    _GUILD_ID_RP = int(os.getenv("GUILD_ID_RP", "0"))
except (ValueError, TypeError):
    _GUILD_ID_RP = 0

SERVER_LORE: dict[int, str] = {}
if _GUILD_ID_RP:
    SERVER_LORE[_GUILD_ID_RP] = WORLD_LORE


def _character_keys(char: dict[str, Any]) -> list[str]:
    """Every string a response may use for ``char``: name, Thai name, nicknames.

    ONE definition feeds both maps below, so a name that becomes a ``{{Tag}}``
    (SERVER_CHARACTER_NAMES) always also resolves to a webhook avatar
    (SERVER_AVATARS). A hand-written avatar map drifts: on a real server it
    covered 8 of the 17 tag keys, so a ``{{nickname}}`` tag went out avatar-less.
    """
    nicknames = char.get("nicknames") or []
    return [str(k) for k in (char.get("name"), char.get("name_th"), *nicknames) if k]


def _avatar_path(char: dict[str, Any]) -> str:
    """Webhook avatar for ``char``: its explicit ``avatar`` entry, else the
    reference image's file name under ``assets/RP/AVATARS/``."""
    explicit = char.get("avatar")
    if explicit:
        return str(explicit)
    return "assets/RP/AVATARS/" + os.path.basename(str(char["image"]))


# Per-guild character image map.
# Format: guild_id -> {character_name: image_path_relative_to_project_root}
# Used by cogs.ai_core.media_processor.load_character_image to find a
# character image when {{Name}} appears in the AI response, and by
# cogs.ai_core.character_tags to turn a bare name line into a {{Name}} tag.
# Keys are matched case-insensitively against the message text; values must be
# paths under the project directory (path traversal is blocked).
SERVER_CHARACTER_NAMES: dict[int, dict[str, str]] = {}
# Webhook avatar paths (smaller images for Discord webhook avatars).
# Format: guild_id -> {character_name: avatar_path} — same keys as above.
SERVER_AVATARS: dict[int, dict[str, str]] = {}
if _GUILD_ID_RP:
    SERVER_CHARACTER_NAMES[_GUILD_ID_RP] = {}
    SERVER_AVATARS[_GUILD_ID_RP] = {}
    for _char in SERVER_CHARACTERS:
        _image = str(_char["image"])
        _avatar = _avatar_path(_char)
        for _key in _character_keys(_char):
            SERVER_CHARACTER_NAMES[_GUILD_ID_RP][_key] = _image
            SERVER_AVATARS[_GUILD_ID_RP][_key] = _avatar

# Backward compatibility aliases
ROLEPLAY_ASSISTANT_INSTRUCTION = ROLEPLAY_PROMPT
