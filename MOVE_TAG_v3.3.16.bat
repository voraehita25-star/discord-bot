@echo off
REM ============================================================================
REM Double-click to move tag v3.3.16 to the current HEAD on GitHub.
REM Wraps scripts\move_tag_v3.3.16.ps1 with ExecutionPolicy bypass.
REM Script will ask for confirmation before touching anything on GitHub.
REM ============================================================================

cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\move_tag_v3.3.16.ps1"

echo.
pause
