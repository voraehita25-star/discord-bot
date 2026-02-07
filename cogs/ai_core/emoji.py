"""
Discord Emoji Processing Module.
Handles Discord custom emoji extraction, conversion, and fetching.
"""

from __future__ import annotations

import io
import logging
import re

from PIL import Image

# Discord custom emoji pattern - <:name:id> or <a:name:id> (animated)
PATTERN_DISCORD_EMOJI = re.compile(r"<(a?):(\w+):(\d+)>")


def convert_discord_emojis(text: str) -> str:
    """Convert Discord custom emojis to readable format.

    <:smile:123456789> -> [:smile:]
    <a:dance:987654321> -> [:dance:]
    """
    return re.sub(r"<a?:(\w+):\d+>", r"[:\1:]", text)


def extract_discord_emojis(text: str) -> list[dict]:
    """Extract Discord custom emoji info from text.

    Returns list of dicts with: name, id, animated, url
    """
    emojis = []
    seen_ids = set()

    for match in PATTERN_DISCORD_EMOJI.finditer(text):
        animated = match.group(1) == "a"
        name = match.group(2)
        emoji_id = match.group(3)

        # Avoid duplicates
        if emoji_id in seen_ids:
            continue
        seen_ids.add(emoji_id)

        # Discord CDN URL
        ext = "gif" if animated else "png"
        url = f"https://cdn.discordapp.com/emojis/{emoji_id}.{ext}?size=64"

        emojis.append({"name": name, "id": emoji_id, "animated": animated, "url": url})

    return emojis


async def fetch_emoji_images(
    emojis: list[dict], session: "aiohttp.ClientSession | None" = None
) -> list[tuple[str, Image.Image]]:
    """Fetch emoji images from Discord CDN.

    Args:
        emojis: List of emoji dicts with 'url' and 'name' keys.
        session: Optional aiohttp session to reuse. If None, a new session is created.

    Returns list of (name, PIL.Image) tuples.
    """
    import aiohttp

    results = []

    async def _fetch_with_session(s: aiohttp.ClientSession) -> None:
        for emoji in emojis[:5]:  # Limit to 5 emojis to avoid overload
            img = None
            try:
                async with s.get(
                    emoji["url"], timeout=aiohttp.ClientTimeout(total=3)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        img = Image.open(io.BytesIO(data))
                        # Convert to RGB if needed (for GIFs, take first frame)
                        if img.mode in ("RGBA", "P"):
                            converted_img = img.convert("RGB")
                            img.close()  # Close original after conversion
                            img = converted_img
                        results.append((emoji["name"], img))
                        img = None  # Transferred to results, don't close
            except Exception as e:
                logging.debug("Failed to fetch emoji %s: %s", emoji.get("name", "unknown"), e)
            finally:
                # Close image if not transferred to results (error occurred)
                if img is not None:
                    img.close()

    if session is not None:
        await _fetch_with_session(session)
    else:
        async with aiohttp.ClientSession() as new_session:
            await _fetch_with_session(new_session)

    return results
