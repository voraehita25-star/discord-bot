@echo off
REM ============================================================================
REM Double-click to publish v3.3.16 to GitHub.
REM Wraps scripts\publish_v3.3.16.ps1 with ExecutionPolicy bypass so the PS1
REM runs even if PowerShell is locked down by default.
REM ============================================================================

cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\publish_v3.3.16.ps1"

echo.
pause
