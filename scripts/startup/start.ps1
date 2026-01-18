# ============================================================================
#                        Discord Bot Launcher v4.0
#                     Production Mode with Auto-Restart
# ============================================================================

param(
    [switch]$NoRestart,
    [switch]$Debug
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
    Read-Host "Press Enter to exit"
    exit 1
}

# Check dependencies
if ($Config.bot.check_dependencies) {
    if (-not (Test-Dependencies)) {
        $Install = Read-Host "Install dependencies now? (y/n)"
        if ($Install -eq "y") {
            pip install -r (Join-Path $ProjectRoot "requirements.txt")
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
        $BotProcess = Start-Process -FilePath "python" -ArgumentList $BotScript -NoNewWindow -PassThru -WorkingDirectory $ProjectRoot
        
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
    
    # Handle crash
    $RestartCount++
    
    if ($ExitCode -ne 0) {
        Save-CrashReport -ExitCode $ExitCode -ErrorMessage "Unexpected exit" -Runtime $Runtime | Out-Null
    }
    
    if ($RestartCount -ge $MaxRestarts) {
        Save-CrashReport -ExitCode $ExitCode -ErrorMessage "Max restarts reached" -Runtime $Runtime | Out-Null
        
        Write-Log "Maximum restarts reached ($MaxRestarts) - manual intervention required" -Level ERROR
        break
    }
    
    # Countdown
    Write-Host ""
    Write-BoxTop
    Write-BoxLine -Text "$($C.Red)[!]$($C.Reset) Bot crashed (Exit: $ExitCode) - Restart #$RestartCount" -Align "Left"
    Write-BoxLine -Text "$($C.Yellow)[*]$($C.Reset) Restarting in $RestartDelay seconds... (Ctrl+C to cancel)" -Align "Left"
    Write-BoxBottom
    
    $Host.UI.RawUI.WindowTitle = "Discord Bot - Restarting in $RestartDelay s..."
    
    for ($i = $RestartDelay; $i -gt 0; $i--) {
        Write-Host -NoNewline "`r  Restarting in $i seconds...  "
        Start-Sleep -Seconds 1
    }
    Write-Host ""
}

Write-Host ""
Write-Log "Bot session ended. Goodbye!" -Level INFO
$Host.UI.RawUI.WindowTitle = "Discord Bot - Stopped"
