# build-tauri.ps1
$ErrorActionPreference = "Stop"
$OutputEncoding = [System.Text.Encoding]::UTF8

# Ensure we're in the native_dashboard directory
$ScriptDir = Split-Path -Parent $PSScriptRoot
Import-Module (Join-Path $PSScriptRoot "_deploy.psm1") -Force
Push-Location $ScriptDir

try {
    Write-Host "Building Tauri app..." -ForegroundColor Cyan

    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) {
        Write-Host "TypeScript build failed!" -ForegroundColor Red
        exit 1
    }

    cargo tauri build
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Tauri build failed!" -ForegroundColor Red
        exit 1
    }

    $releaseDir = Join-Path $ScriptDir "target\release"
    $botDir = Split-Path -Parent $ScriptDir

    Write-Host ""
    Write-Host "Copying executables..." -ForegroundColor Yellow
    if (-not (Publish-DashboardExe -ReleaseDir $releaseDir -BotDir $botDir)) {
        exit 1
    }

    Write-Host ""
    Write-Host "Build complete!" -ForegroundColor Green
    Write-Host ""
    Write-Host "Files created:" -ForegroundColor Cyan
    Get-ChildItem "$releaseDir\*.exe" | ForEach-Object { Write-Host "  [release] $($_.Name)" }
    Get-ChildItem "$botDir\*.exe" | ForEach-Object { Write-Host "  [BOT] $($_.Name)" }
} finally {
    Pop-Location
}
