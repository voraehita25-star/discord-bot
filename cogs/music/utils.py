"""
Music Utilities Module.
Contains constants and helper functions for the Music cog.
"""


# 🎨 PREMIUM UI/UX COLOR SCHEME
class Colors:
    """Color constants for Discord embeds."""

    PLAYING = 0x00FF7F  # Spring Green - Now Playing
    QUEUED = 0x3498DB  # Blue - Added to Queue
    SPOTIFY = 0x1DB954  # Spotify Green
    YOUTUBE = 0xFF0000  # YouTube Red
    PAUSED = 0xFFD700  # Gold - Paused
    RESUMED = 0x00FF00  # Green - Resumed
    SUCCESS = 0x00FF00  # Green - Success
    ERROR = 0xFF4444  # Red - Error
    WARNING = 0xFFA500  # Orange - Warning
    INFO = 0x7289DA  # Discord Blurple - Info
    QUEUE = 0x9B59B6  # Purple - Queue
    STOP = 0x808080  # Gray - Stopped
    LOOP = 0x00CED1  # Dark Cyan - Loop


class Emojis:
    """Emoji constants for Discord embeds."""

    PLAY = "▶️"
    PAUSE = "⏸️"
    SKIP = "⏭️"
    STOP = "⏹️"
    LOOP = "🔁"
    QUEUE = "📜"
    MUSIC = "🎵"
    HEADPHONES = "🎧"
    SPARKLES = "✨"
    LOADING = "⏳"
    CHECK = "✅"
    CROSS = "❌"
    WARNING = "⚠️"
    VOLUME = "🔊"
    DISC = "💿"
    MICROPHONE = "🎤"
    NOTES = "🎶"
    WAVE = "👋"
    TOOLS = "🔧"
    FIRE = "🔥"
    STAR = "⭐"
    CLOCK = "🕐"


def format_duration(seconds: int | float | None) -> str:
    """Format seconds to MM:SS or HH:MM:SS.

    Args:
        seconds: Duration in seconds, or None.

    Returns:
        Formatted duration string (e.g., "3:45" or "1:23:45").
    """
    if seconds is None:
        return "00:00"
    seconds = int(seconds)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def create_progress_bar(current: int | float, total: int | float, length: int = 12) -> str:
    """Create a visual progress bar ▰▰▰▰▱▱▱▱▱.

    Args:
        current: Current position value.
        total: Total/maximum value.
        length: Length of the progress bar in characters.

    Returns:
        A string progress bar using ▰ (filled) and ▱ (empty) characters.
    """
    if total == 0:
        return "▱" * length
    progress = max(0, min(length, int((current / total) * length)))
    filled = "▰" * progress
    empty = "▱" * (length - progress)
    return filled + empty
