# build-tauri.ps1
$ErrorActionPreference = "Stop"
$OutputEncoding = [System.Text.Encoding]::UTF8

# Ensure we're in the native_dashboard directory
$ScriptDir = Split-Path -Parent $PSScriptRoot
Push-Location $ScriptDir

try {
    Write-Host "Building Tauri app..." -ForegroundColor Cyan

    npm run build
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
    $sourceExe = Join-Path $releaseDir "bot-dashboard.exe"
    $koreanName = [char]0xB514 + [char]0xC2A4 + [char]0xCF54 + [char]0xB4DC + " " + [char]0xBD07 + " " + [char]0xB300 + [char]0xC2DC + [char]0xBCF4 + [char]0xB4DC + ".exe"

    if (Test-Path $sourceExe) {
        Write-Host ""
        Write-Host "Copying executables..." -ForegroundColor Yellow
        
        # Copy to release folder with Korean name
        $koreanExeRelease = Join-Path $releaseDir $koreanName
        Copy-Item $sourceExe $koreanExeRelease -Force
        Write-Host "  -> $releaseDir\$koreanName" -ForegroundColor Green
        
        # Copy to BOT folder (English name)
        $englishExeBot = Join-Path $botDir "bot-dashboard.exe"
        Copy-Item $sourceExe $englishExeBot -Force
        Write-Host "  -> BOT\bot-dashboard.exe" -ForegroundColor Green
        
        # Copy to BOT folder (Korean name)
        $koreanExeBot = Join-Path $botDir $koreanName
        Copy-Item $sourceExe $koreanExeBot -Force
        Write-Host "  -> BOT\$koreanName" -ForegroundColor Green
        
        Write-Host ""
        Write-Host "Build complete!" -ForegroundColor Green
        Write-Host ""
        Write-Host "Files created:" -ForegroundColor Cyan
        Get-ChildItem "$releaseDir\*.exe" | ForEach-Object { Write-Host "  [release] $($_.Name)" }
        Get-ChildItem "$botDir\*.exe" | ForEach-Object { Write-Host "  [BOT] $($_.Name)" }
    } else {
        Write-Host "bot-dashboard.exe not found!" -ForegroundColor Red
        exit 1
    }
} finally {
    Pop-Location
}
