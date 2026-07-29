# build-release.ps1 - Quick build without Tauri installer
$ErrorActionPreference = "Stop"
$OutputEncoding = [System.Text.Encoding]::UTF8

# Ensure we're in the native_dashboard directory
$ScriptDir = Split-Path -Parent $PSScriptRoot
Import-Module (Join-Path $PSScriptRoot "_deploy.psm1") -Force
Push-Location $ScriptDir

try {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "  Building Dashboard (Release Mode)" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host ""

    # Build TypeScript
    Write-Host "[1/3] Compiling TypeScript..." -ForegroundColor Yellow
    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) {
        Write-Host "TypeScript build failed!" -ForegroundColor Red
        exit 1
    }
    Write-Host "      TypeScript compiled!" -ForegroundColor Green

    # Build Rust
    Write-Host "[2/3] Building Rust (release)..." -ForegroundColor Yellow
    cargo build --release
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Rust build failed!" -ForegroundColor Red
        exit 1
    }
    Write-Host "      Rust compiled!" -ForegroundColor Green

    # Copy executables
    Write-Host "[3/3] Copying executables..." -ForegroundColor Yellow

    $releaseDir = Join-Path $ScriptDir "target\release"
    $botDir = Split-Path -Parent $ScriptDir
    $koreanName = Get-DashboardKoreanName

    if (-not (Publish-DashboardExe -ReleaseDir $releaseDir -BotDir $botDir -Quiet)) {
        exit 1
    }
    Write-Host "      Executables copied!" -ForegroundColor Green

    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "  Build Complete!" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "Files created:" -ForegroundColor Cyan
    Write-Host "  [release] bot-dashboard.exe" -ForegroundColor White
    Write-Host "  [release] Discord Bot Dashboard.exe" -ForegroundColor White
    Write-Host "  [release] $koreanName" -ForegroundColor White
    Write-Host "  [BOT] bot-dashboard.exe" -ForegroundColor White
    Write-Host "  [BOT] Discord Bot Dashboard.exe" -ForegroundColor White
    Write-Host "  [BOT] $koreanName" -ForegroundColor White
    Write-Host ""
} finally {
    Pop-Location
}
