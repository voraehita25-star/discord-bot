# ============================================================================
#                      Discord Bot Developer Mode v4.0
#                        Hot Reload with File Watching
# ============================================================================

param(
    [switch]$Debug,
    [switch]$Verbose
)

# Import common module
$ModulePath = Join-Path $PSScriptRoot "_common.psm1"
Import-Module $ModulePath -Force

# Setup
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$Host.UI.RawUI.WindowTitle = "Discord Bot - Dev Mode"
Write-LogHeader "start_dev.ps1"

# Set environment for dev_watcher
if ($Debug) { $env:DEV_WATCHER_DEBUG = "1" }
if ($Verbose) { $env:DEV_WATCHER_VERBOSE = "1" }

$DevWatcher = Join-Path $ScriptsDir "dev_watcher.py"

# ============================================================================
# Main
# ============================================================================

while ($true) {
    Show-Banner -Mode "Dev"
    
    Write-BoxTop
    Write-BoxLine -Text "$($C.Bold)$($C.White)Developer Mode Features$($C.Reset)" -Align "Center"
    Write-BoxBottom
    Write-Host ""
    Write-Log "Auto-restart on file save" -Level OK
    Write-Log "Hash-based change detection" -Level OK
    Write-Log "Watches: .py, .json files" -Level OK
    Write-Log "Press Ctrl+C to stop" -Level INFO
    Write-Host ""
    
    # Check dev_watcher exists
    if (-not (Test-Path $DevWatcher)) {
        Write-Log "dev_watcher.py not found at: $DevWatcher" -Level ERROR
        Read-Host "Press Enter to exit"
        exit 1
    }
    
    Write-BoxTop
    Write-BoxLine -Text "$($C.Yellow)[*]$($C.Reset) Starting file watcher..." -Align "Left"
    Write-BoxBottom
    Write-Host ""
    
    # Run dev watcher
    python $DevWatcher
    $ExitCode = $LASTEXITCODE
    
    Write-Host ""
    if ($ExitCode -eq 0) {
        Write-Log "Watcher stopped normally" -Level OK
    }
    else {
        Write-Log "Watcher exited with code: $ExitCode" -Level WARN
    }
    
    # Ask to restart
    Write-Host ""
    $Choice = Read-Host "  Restart watcher? (Y/n)"
    if ($Choice -match "^[nN]") { break }
}

Write-Host ""
Write-Log "Dev mode ended. Goodbye!" -Level INFO
$Host.UI.RawUI.WindowTitle = "Discord Bot - Stopped"
