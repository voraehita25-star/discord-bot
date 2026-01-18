"""
Roleplay Data - Example Configuration
======================================

This is an EXAMPLE file. Copy this to `roleplay_data.py` and customize it.

To use:
    cp roleplay_data.example.py roleplay_data.py
    # Then edit roleplay_data.py with your RP content
"""

import os

# Roleplay prompt - instructions for roleplay mode
ROLEPLAY_PROMPT = """
You are a roleplay assistant. When roleplaying:

1. Stay in character at all times
2. Use descriptive language for actions and emotions
3. React naturally to the user's actions
4. Remember previous events in the story
5. Keep responses engaging and immersive

Format:
- Use *asterisks* for actions and descriptions
- Use "quotes" for dialogue
- Use (parentheses) for out-of-character notes
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

# Character definitions for webhooks
# Format: list of dicts with name, image path, and nicknames
SERVER_CHARACTERS = [
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
    #     "name_th": "อีกตัวละคร",
    #     "nicknames": ["Another"],
    # },
]

# Server lore mapping: guild_id -> lore content
_GUILD_ID_RP = int(os.getenv("GUILD_ID_RP", "0"))

SERVER_LORE: dict[int, str] = {}
if _GUILD_ID_RP:
    SERVER_LORE[_GUILD_ID_RP] = WORLD_LORE

# Webhook avatar paths (smaller images for Discord webhook avatars)
# Format: guild_id -> {character_name: avatar_path}
SERVER_AVATARS: dict[int, dict[str, str]] = {}
if _GUILD_ID_RP:
    SERVER_AVATARS[_GUILD_ID_RP] = {
        "Example Character": "assets/RP/AVATARS/example.png",
        # Add mappings for each character name and nickname
    }

# Backward compatibility aliases
ROLEPLAY_ASSISTANT_INSTRUCTION = ROLEPLAY_PROMPT
