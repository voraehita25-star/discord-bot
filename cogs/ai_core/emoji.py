"""
Discord Emoji Processing Module.
Handles Discord custom emoji extraction, conversion, and fetching.
"""

from __future__ import annotations

import io
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


async def fetch_emoji_images(emojis: list[dict]) -> list[tuple[str, Image.Image]]:
    """Fetch emoji images from Discord CDN.

    Returns list of (name, PIL.Image) tuples.
    """
    import aiohttp

    results = []

    async with aiohttp.ClientSession() as session:
        for emoji in emojis[:5]:  # Limit to 5 emojis to avoid overload
            try:
                async with session.get(
                    emoji["url"], timeout=aiohttp.ClientTimeout(total=3)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        img = Image.open(io.BytesIO(data))
                        # Convert to RGB if needed (for GIFs, take first frame)
                        if img.mode in ("RGBA", "P"):
                            img = img.convert("RGB")
                        results.append((emoji["name"], img))
            except Exception:
                pass  # Skip failed emoji fetches

    return results
