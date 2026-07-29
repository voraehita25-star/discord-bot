# ============================================================================
#            Dashboard executable deployment - shared helper
# ============================================================================
# build-tauri.ps1 and build-release.ps1 both finish by fanning the same
# bot-dashboard.exe out to five destinations under two names. That block was
# duplicated verbatim in both scripts, so a fix to one silently left the other
# behind. It also used a bare Copy-Item, which fails with an unexplained
# "being used by another process" when the dashboard the operator is trying to
# update happens to be running - after a multi-minute Rust build.

Set-StrictMode -Version Latest

# The shipped product name, built from code points so this file stays
# pure-ASCII and cannot be mangled by a non-UTF-8 editor or code page.
function Get-DashboardKoreanName {
    <#
    .SYNOPSIS
        The Korean-named executable filename shipped to users.
    #>
    return [char]0xB514 + [char]0xC2A4 + [char]0xCF54 + [char]0xB4DC + " " +
           [char]0xBD07 + " " +
           [char]0xB300 + [char]0xC2DC + [char]0xBCF4 + [char]0xB4DC + ".exe"
}

function Stop-RunningDashboard {
    <#
    .SYNOPSIS
        Report (and optionally stop) dashboard processes holding the exe open.
    .PARAMETER Force
        Terminate them instead of only listing them.
    #>
    param([switch]$Force)

    $Running = Get-Process -Name "bot-dashboard" -ErrorAction SilentlyContinue
    if (-not $Running) { return $false }

    foreach ($proc in $Running) {
        if ($Force) {
            Write-Host "  [*] Stopping running dashboard (PID $($proc.Id))" -ForegroundColor Yellow
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        } else {
            Write-Host "  [!] Dashboard is running (PID $($proc.Id)) and holds the exe open" -ForegroundColor Yellow
        }
    }
    if ($Force) { Start-Sleep -Milliseconds 500 }
    return $true
}

function Publish-DashboardExe {
    <#
    .SYNOPSIS
        Copy the built exe to every shipping location.
    .DESCRIPTION
        Destinations (all pointing at the same binary):
          target\release\  - bot-dashboard.exe (build output), the Korean name,
                             and the legacy "Discord Bot Dashboard.exe"
          repo root        - the same three, so the app can be launched from
                             next to bot.py
        Returns $true when every copy landed.
    .PARAMETER ReleaseDir
        native_dashboard\target\release
    .PARAMETER BotDir
        The repo root (parent of native_dashboard).
    .PARAMETER Quiet
        Suppress the per-destination lines.
    #>
    param(
        [Parameter(Mandatory)] [string]$ReleaseDir,
        [Parameter(Mandatory)] [string]$BotDir,
        [switch]$Quiet
    )

    $SourceExe = Join-Path $ReleaseDir "bot-dashboard.exe"
    if (-not (Test-Path $SourceExe)) {
        Write-Host "bot-dashboard.exe not found at $SourceExe!" -ForegroundColor Red
        return $false
    }

    $KoreanName = Get-DashboardKoreanName
    $Targets = @(
        @{ Path = (Join-Path $ReleaseDir $KoreanName);                       Label = "[release] $KoreanName" }
        @{ Path = (Join-Path $ReleaseDir "Discord Bot Dashboard.exe");       Label = "[release] Discord Bot Dashboard.exe" }
        @{ Path = (Join-Path $BotDir "bot-dashboard.exe");                   Label = "[BOT] bot-dashboard.exe" }
        @{ Path = (Join-Path $BotDir "Discord Bot Dashboard.exe");           Label = "[BOT] Discord Bot Dashboard.exe" }
        @{ Path = (Join-Path $BotDir $KoreanName);                           Label = "[BOT] $KoreanName" }
    )

    $Locked = @()
    foreach ($t in $Targets) {
        try {
            Copy-Item $SourceExe $t.Path -Force -ErrorAction Stop
            if (-not $Quiet) { Write-Host "  -> $($t.Label)" -ForegroundColor Green }
        } catch [System.IO.IOException] {
            $Locked += $t.Path
        } catch {
            Write-Host "  [ERROR] $($t.Label): $_" -ForegroundColor Red
            return $false
        }
    }

    if ($Locked.Count -gt 0) {
        Write-Host ""
        Write-Host "[ERROR] $($Locked.Count) destination(s) are locked by a running process:" -ForegroundColor Red
        $Locked | ForEach-Object { Write-Host "          $_" -ForegroundColor Red }
        Stop-RunningDashboard | Out-Null
        Write-Host "        Close the dashboard and re-run - the compile output in" -ForegroundColor Yellow
        Write-Host "        target\release is already up to date, so this is fast." -ForegroundColor Yellow
        return $false
    }

    return $true
}

Export-ModuleMember -Function Get-DashboardKoreanName, Stop-RunningDashboard, Publish-DashboardExe
