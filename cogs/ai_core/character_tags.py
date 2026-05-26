"""Character-name → ``{{Tag}}`` replacement helpers.

The pattern compiles once per guild and is cached. Without this cache,
each response would call ``re.escape`` and ``re.sub`` once *per character
name*, which scales O(n_chars * len_response) per turn.
"""

from __future__ import annotations

import re
from collections import OrderedDict

from .data import SERVER_CHARACTER_NAMES

# LRU-bounded so guilds joining/leaving don't grow the cache without
# limit. With an ``OrderedDict`` we get O(1) move-to-end + popitem(False)
# eviction.
_MAX_GUILD_PATTERN_CACHE = 256
_GUILD_TAG_PATTERN_CACHE: OrderedDict[int, tuple[tuple[str, ...], re.Pattern[str]]] = (
    OrderedDict()
)


def _compile_guild_pattern(names: tuple[str, ...]) -> re.Pattern[str]:
    # Filter out empty strings — an empty entry in ``names`` would render
    # ``re.escape("") = ""`` which produces ``||`` in the alternation,
    # matching every position in the input and corrupting unrelated text.
    filtered = tuple(n for n in names if n)
    if not filtered:
        # No usable names → return a never-matching pattern. An empty
        # alternation would compile to ``()`` and match every line,
        # corrupting unrelated text. (The public caller already guards
        # this, but keep the helper safe if called directly.)
        return re.compile(r"(?!)")
    sorted_names = sorted(filtered, key=len, reverse=True)
    alternation = "|".join(re.escape(n) for n in sorted_names)
    return re.compile(
        rf"^[ \t]*({alternation})[ \t]*$",
        flags=re.MULTILINE | re.IGNORECASE,
    )


def _replacement(match: re.Match[str]) -> str:
    return f"{{{{{match.group(1)}}}}}"


def replace_character_names(text: str, guild_id: int | None) -> str:
    """Convert standalone character names into ``{{Name}}`` tags."""
    # ``guild_id is None`` is the safe check; ``guild_id == 0`` is rare
    # but valid for system-context messages and shouldn't be conflated
    # with "no guild". The previous ``not guild_id`` falsy check rejected
    # 0 silently.
    if not text or guild_id is None:
        return text
    char_map = SERVER_CHARACTER_NAMES.get(guild_id)
    if not char_map:
        return text
    names = tuple(n for n in char_map if n)
    if not names:
        return text
    cached = _GUILD_TAG_PATTERN_CACHE.get(guild_id)
    if cached is None or cached[0] != names:
        pattern = _compile_guild_pattern(names)
        _GUILD_TAG_PATTERN_CACHE[guild_id] = (names, pattern)
        _GUILD_TAG_PATTERN_CACHE.move_to_end(guild_id)
        while len(_GUILD_TAG_PATTERN_CACHE) > _MAX_GUILD_PATTERN_CACHE:
            _GUILD_TAG_PATTERN_CACHE.popitem(last=False)
    else:
        pattern = cached[1]
        _GUILD_TAG_PATTERN_CACHE.move_to_end(guild_id)
    return pattern.sub(_replacement, text)
