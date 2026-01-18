"""
Create Desktop Shortcut for Bot Dashboard
Run this script once to create a shortcut on your desktop.
"""

import os
import sys
from pathlib import Path


def create_shortcut():
    """Create a desktop shortcut for Bot Dashboard."""
    try:
        import winshell
        from win32com.client import Dispatch
    except ImportError:
        print("Installing required packages...")
        os.system("pip install pywin32 winshell")
        import winshell
        from win32com.client import Dispatch

    # Paths
    desktop = winshell.desktop()
    bot_dir = Path(__file__).parent
    target = sys.executable
    script = bot_dir / "bot_dashboard.py"
    bot_dir / "icon.png"

    # Create shortcut (use ASCII filename for Windows compatibility)
    shortcut_path = str(Path(desktop) / "Bot Dashboard.lnk")

    shell = Dispatch("WScript.Shell")
    shortcut = shell.CreateShortCut(shortcut_path)
    shortcut.Targetpath = target
    shortcut.Arguments = f'"{script}"'
    shortcut.WorkingDirectory = str(bot_dir)
    shortcut.Description = "디스코드 봇 대시보드"

    # Try to use ico file if available, otherwise Windows will use default Python icon
    ico_file = bot_dir / "assets" / "icons" / "icon.ico"
    if ico_file.exists():
        shortcut.IconLocation = str(ico_file)

    shortcut.save()

    print(f"[OK] Shortcut created: {shortcut_path}")
    return shortcut_path


if __name__ == "__main__":
    create_shortcut()
