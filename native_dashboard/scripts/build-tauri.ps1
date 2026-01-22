# build-tauri.ps1
$ErrorActionPreference = "Stop"
$OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "Building Tauri app..." -ForegroundColor Cyan

npm run build
cargo tauri build

$releaseDir = "target\release"
$oldExe = "$releaseDir\bot-dashboard.exe"
$koreanName = [char]0xB514 + [char]0xC2A4 + [char]0xCF54 + [char]0xB4DC + " " + [char]0xBD07 + " " + [char]0xB300 + [char]0xC2DC + [char]0xBCF4 + [char]0xB4DC + ".exe"
$newExe = Join-Path $releaseDir $koreanName

if (Test-Path $oldExe) {
    if (Test-Path $newExe) {
        Remove-Item $newExe -Force
        Write-Host "Removed old Korean exe" -ForegroundColor Yellow
    }
    Move-Item $oldExe $newExe -Force
    Write-Host "Renamed to: $koreanName" -ForegroundColor Green
} else {
    Write-Host "bot-dashboard.exe not found!" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Build complete!" -ForegroundColor Green
Get-ChildItem "$releaseDir\*.exe" | ForEach-Object { Write-Host $_.Name }
