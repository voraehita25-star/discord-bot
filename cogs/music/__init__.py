"""
Music Module for Discord Bot.
Provides music playback functionality with YouTube and Spotify support.
"""

from .cog import Music, MusicControlView
from .utils import Colors, Emojis, create_progress_bar, format_duration

__all__ = [
    "Colors",
    "Emojis",
    "Music",
    "MusicControlView",
    "create_progress_bar",
    "format_duration",
]


async def setup(bot):
    """Setup function to add the Music cog to the bot."""
    await bot.add_cog(Music(bot))
