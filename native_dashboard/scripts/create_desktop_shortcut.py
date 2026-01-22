# -*- coding: utf-8 -*-
"""Create desktop shortcut for 디스코드 봇 대시보드 using IShellLink"""
import os
from pathlib import Path

def create_shortcut_via_pythoncom():
    """Use pythoncom with IShellLink directly"""
    import pythoncom  # type: ignore
    from win32com.shell import shell  # type: ignore
    
    korean_name = "디스코드 봇 대시보드"
    exe_path = Path(r"C:\Users\ME\BOT\native_dashboard\target\release") / f"{korean_name}.exe"
    desktop = Path.home() / "Desktop"
    shortcut_path = desktop / f"{korean_name}.lnk"
    icon_path = Path(r"C:\Users\ME\BOT\native_dashboard\icons\icon.ico")
    work_dir = Path(r"C:\Users\ME\BOT")
    
    print(f"Korean name: {korean_name}")
    print(f"Exe path: {exe_path}")
    print(f"Exe exists: {exe_path.exists()}")
    
    if not exe_path.exists():
        print("ERROR: Exe not found!")
        return False
    
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
