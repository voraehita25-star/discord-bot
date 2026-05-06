"""FFmpeg executable resolution.

Resolves the FFmpeg binary path with this precedence:
1. ``FFMPEG_PATH`` env var (absolute path or bare name)
2. Bundled ``./ffmpeg/bin/ffmpeg.exe`` next to the bot's working tree
3. ``ffmpeg`` on system PATH

Centralized so callers never hardcode ``"ffmpeg"`` and miss bundled
installs that aren't on the system PATH.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

_BUNDLED_RELATIVE = Path("ffmpeg") / "bin" / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")


def _project_root() -> Path:
    # utils/media/ffmpeg_path.py → project root is parents[2].
    return Path(__file__).resolve().parents[2]


def _looks_like_ffmpeg(p: Path) -> bool:
    """Return True only if ``p`` is a plausible ffmpeg executable.

    ``Path.is_file()`` alone is dangerously permissive — pointing
    ``FFMPEG_PATH`` at ``/etc/passwd`` would happily satisfy it. Require
    that the basename contains 'ffmpeg' (case-insensitive) AND that the
    file is executable. This won't catch every spoofing attempt, but it
    rules out the obvious mistakes/exploits where an attacker controls
    only the path string but not the filesystem layout.
    """
    if not p.is_file():
        return False
    if "ffmpeg" not in p.name.lower():
        return False
    # On Windows, executable bit is implied by .exe; os.access works.
    return os.access(p, os.X_OK)


def get_ffmpeg_executable() -> str:
    """Return the FFmpeg executable to pass to ``discord.FFmpegPCMAudio``.

    Always returns a string. If nothing is found, returns ``"ffmpeg"``
    so the caller's behavior matches the legacy hardcoded value (the
    underlying constructor will then raise its usual error).
    """
    env_val = os.getenv("FFMPEG_PATH", "").strip()
    if env_val:
        candidate = Path(env_val).expanduser()
        if _looks_like_ffmpeg(candidate):
            return str(candidate)
        # Allow a bare name (e.g. "ffmpeg") that's resolved via PATH.
        resolved = shutil.which(env_val)
        if resolved and _looks_like_ffmpeg(Path(resolved)):
            return resolved

    bundled = _project_root() / _BUNDLED_RELATIVE
    if _looks_like_ffmpeg(bundled):
        return str(bundled)

    on_path = shutil.which("ffmpeg")
    if on_path and _looks_like_ffmpeg(Path(on_path)):
        return on_path

    return "ffmpeg"


def is_ffmpeg_available() -> bool:
    """True iff ``get_ffmpeg_executable()`` resolves to an existing file."""
    candidate = get_ffmpeg_executable()
    if Path(candidate).is_file():
        return True
    return shutil.which(candidate) is not None
