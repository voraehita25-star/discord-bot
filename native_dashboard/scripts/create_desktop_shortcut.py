# -*- coding: utf-8 -*-
"""Create desktop shortcut for 디스코드 봇 대시보드 using IShellLink"""
from pathlib import Path

def create_shortcut_via_pythoncom():
    """Use pythoncom with IShellLink directly"""
    try:
        import pythoncom  # type: ignore
        from win32com.shell import shell  # type: ignore
    except ImportError:
        print("ERROR: pywin32 is required. Install with: pip install pywin32")
        return False
    
    korean_name = "디스코드 봇 대시보드"
    
    # Resolve paths relative to this script instead of hardcoding
    script_dir = Path(__file__).resolve().parent
    dashboard_dir = script_dir.parent  # native_dashboard/
    bot_dir = dashboard_dir.parent     # BOT/
    
    exe_path = dashboard_dir / "target" / "release" / f"{korean_name}.exe"
    desktop = Path.home() / "Desktop"
    shortcut_path = desktop / f"{korean_name}.lnk"
    icon_path = dashboard_dir / "icons" / "icon.ico"
    work_dir = bot_dir
    
    print(f"Korean name: {korean_name}")
    print(f"Exe path: {exe_path}")
    print(f"Exe exists: {exe_path.exists()}")
    
    if not exe_path.exists():
        print("ERROR: Exe not found!")
        return False
    
    # Validate icon exists
    if not icon_path.exists():
        print(f"WARNING: Icon not found at {icon_path}, shortcut will use default icon")
    
    # Remove existing
    if shortcut_path.exists():
        shortcut_path.unlink()
        print("Removed existing shortcut")
    
    # Create IShellLink
    shortcut = pythoncom.CoCreateInstance(
        shell.CLSID_ShellLink,
        None,
        pythoncom.CLSCTX_INPROC_SERVER,
        shell.IID_IShellLink
    )
    
    shortcut.SetPath(str(exe_path))
    shortcut.SetWorkingDirectory(str(work_dir))
    if icon_path.exists():
        shortcut.SetIconLocation(str(icon_path), 0)
    shortcut.SetDescription("Discord Bot Dashboard")
    
    # Save via IPersistFile
    persist_file = shortcut.QueryInterface(pythoncom.IID_IPersistFile)
    persist_file.Save(str(shortcut_path), 0)
    
    if shortcut_path.exists():
        print(f"\n✅ Shortcut created successfully!")
        print(f"   Location: {shortcut_path}")
        return True
    else:
        print("❌ Failed to create shortcut")
        return False

if __name__ == "__main__":
    create_shortcut_via_pythoncom()
