# ============================================================================
#                        Discord Bot Launcher v4.0
#                     Production Mode with Auto-Restart
# ============================================================================

param(
    [switch]$NoRestart,
    [switch]$Debug,
    # Skip interactive Read-Host prompts. Used by bot_manager's hidden mode —
    # in a hidden window a blocked prompt can never be seen or answered, so
    # a failed start would hang an invisible powershell.exe forever.
    [switch]$NoPrompt
)

# Import common module
$ModulePath = Join-Path $PSScriptRoot "_common.psm1"
Import-Module $ModulePath -Force

# Setup
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$Host.UI.RawUI.WindowTitle = "Discord Bot - Starting..."
Write-LogHeader "start.ps1"

# Config
$MaxRestarts = $Config.bot.max_restarts
$RestartDelay = $Config.bot.restart_delay_seconds
$RestartCount = 0
$BotScript = Join-Path $ProjectRoot "bot.py"

# ============================================================================
# Main
# ============================================================================

# Stop existing bot
Stop-ExistingBot

# Health checks
if (-not (Test-Environment)) {
    Write-Log "Health checks failed - aborting" -Level ERROR
    if (-not $NoPrompt) { Read-Host "Press Enter to exit" }
    exit 1
}

# Check dependencies
if ($Config.bot.check_dependencies) {
    if (-not (Test-Dependencies)) {
        if ($NoPrompt) {
            Write-Log "Dependencies missing - skipping install prompt (NoPrompt mode)" -Level WARN
        } else {
            $Install = Read-Host "Install dependencies now? (y/n)"
            if ($Install -eq "y") {
                pip install -r (Join-Path $ProjectRoot "requirements.txt")
            }
        }
    }
}

# Main loop
while ($true) {
    Show-Banner -Mode "Production"

    Write-BoxTop
    Write-BoxLine -Text "$($C.Yellow)[*]$($C.Reset) Starting Discord Bot..." -Align "Left"
    Write-BoxBottom
    Write-Host ""

    $Host.UI.RawUI.WindowTitle = "Discord Bot - Running"
    $StartTime = Get-Date

    # Start bot
    try {
        # Quote the script path — $BotScript contains a space ("C:\BOT Discord\bot.py").
        # -ArgumentList passes its value to the new process verbatim (no auto-quoting),
        # so without the embedded quotes Python receives "C:\BOT" as the script path.
        $BotProcess = Start-Process -FilePath "python" -ArgumentList "`"$BotScript`"" -NoNewWindow -PassThru -WorkingDirectory $ProjectRoot

        # Wait for process
        $BotProcess.WaitForExit()
        $ExitCode = $BotProcess.ExitCode
    }
    catch {
        Write-Log "Failed to start bot: $_" -Level ERROR
        $ExitCode = 1
    }

    $EndTime = Get-Date
    $Runtime = $EndTime - $StartTime

    Write-Host ""
    Write-Log "Session ended after $($Runtime.ToString('hh\:mm\:ss'))" -Level INFO

    # Check stop conditions
    $StopFlag = Join-Path $ProjectRoot "stop_loop.flag"
    if (Test-Path $StopFlag) {
        Remove-Item $StopFlag
        Write-Log "Stop signal received - shutting down" -Level OK
        break
    }

    if ($NoRestart) {
        Write-Log "No-restart mode - exiting" -Level INFO
        break
    }

    # Handle restart logic
    if ($ExitCode -ne 0) {
        # Only count crashes (non-zero exit code) toward restart limit
        $RestartCount++
        Save-CrashReport -ExitCode $ExitCode -ErrorMessage "Unexpected exit" -Runtime $Runtime | Out-Null
    } else {
        # Clean exit — don't count as crash, just restart if configured
        Write-Log "Bot exited cleanly (code 0)" -Level INFO
    }

    if ($RestartCount -ge $MaxRestarts) {
        Save-CrashReport -ExitCode $ExitCode -ErrorMessage "Max restarts reached" -Runtime $Runtime | Out-Null

        Write-Log "Maximum restarts reached ($MaxRestarts) - manual intervention required" -Level ERROR
        break
    }

    # Countdown
    Write-Host ""
    Write-BoxTop
    if ($ExitCode -ne 0) {
        Write-BoxLine -Text "$($C.Red)[!]$($C.Reset) Bot crashed (Exit: $ExitCode) - Restart #$RestartCount" -Align "Left"
    } else {
        Write-BoxLine -Text "$($C.Yellow)[*]$($C.Reset) Bot exited cleanly (Exit: 0) - Restarting..." -Align "Left"
    }
    Write-BoxLine -Text "$($C.Yellow)[*]$($C.Reset) Restarting in $RestartDelay seconds... (Ctrl+C to cancel)" -Align "Left"
    Write-BoxBottom

    $Host.UI.RawUI.WindowTitle = "Discord Bot - Restarting in $RestartDelay s..."

    for ($i = $RestartDelay; $i -gt 0; $i--) {
        Write-Host -NoNewline "`r  Restarting in $i seconds...  "
        Start-Sleep -Seconds 1
    }
    Write-Host ""

    # Re-check the stop flag AFTER the countdown — bot_manager's "Stop Bot"
    # can write it while we sleep here; without this check the flag was only
    # consumed after a whole extra bot session.
    if (Test-Path $StopFlag) {
        Remove-Item $StopFlag
        Write-Log "Stop signal received during countdown - shutting down" -Level OK
        break
    }
}

Write-Host ""
Write-Log "Bot session ended. Goodbye!" -Level INFO
$Host.UI.RawUI.WindowTitle = "Discord Bot - Stopped"
