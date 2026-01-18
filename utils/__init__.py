"""
Utils Package
Provides utility modules for the Discord Bot.
Reorganized into subdirectories for better organization.
"""

# Backward compatibility re-exports from new locations
from .media.ytdl_source import YTDLSource, get_ffmpeg_options
from .monitoring.logger import cleanup_cache, setup_smart_logging
from .reliability.self_healer import SelfHealer

__all__ = [
    # Self healer
    "SelfHealer",
    # YTDL
    "YTDLSource",
    "cleanup_cache",
    "get_ffmpeg_options",
    # Logger
    "setup_smart_logging",
]
