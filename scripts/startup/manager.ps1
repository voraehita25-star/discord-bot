# ============================================================================
#                        Bot Manager Console v4.0
#                      Interactive Management Interface
# ============================================================================

param(
    [switch]$Debug
)

# Import common module
$ModulePath = Join-Path $PSScriptRoot "_common.psm1"
Import-Module $ModulePath -Force

# Setup
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$Host.UI.RawUI.WindowTitle = "Bot Manager"
Write-LogHeader "manager.ps1"

$BotManager = Join-Path $ScriptsDir "bot_manager.py"

# ============================================================================
# Main
# ============================================================================

Show-Banner -Mode "Manager"

Write-BoxTop
Write-BoxLine -Text "$($C.Bold)$($C.White)Bot Management Console$($C.Reset)" -Align "Center"
Write-BoxBottom
Write-Host ""

# Check bot_manager exists
if (-not (Test-Path $BotManager)) {
    Write-Log "bot_manager.py not found at: $BotManager" -Level ERROR
    Read-Host "Press Enter to exit"
    exit 1
}

# Check Python
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Log "Python is not available" -Level ERROR
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Log "Starting Bot Manager..." -Level INFO
Write-Host ""

# Run bot manager
python $BotManager
$ExitCode = $LASTEXITCODE

Write-Host ""
if ($ExitCode -eq 0) {
    Write-Log "Manager exited normally" -Level OK
}
else {
    Write-Log "Manager exited with code: $ExitCode" -Level WARN
}

Start-Sleep -Seconds 2
