# build-release.ps1 - Quick build without Tauri installer
$ErrorActionPreference = "Stop"
$OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Building Dashboard (Release Mode)" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Build TypeScript
Write-Host "[1/3] Compiling TypeScript..." -ForegroundColor Yellow
npm run build
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

$releaseDir = "target\release"
$botDir = ".."
$sourceExe = "$releaseDir\bot-dashboard.exe"
$koreanName = [char]0xB514 + [char]0xC2A4 + [char]0xCF54 + [char]0xB4DC + " " + [char]0xBD07 + " " + [char]0xB300 + [char]0xC2DC + [char]0xBCF4 + [char]0xB4DC + ".exe"

if (Test-Path $sourceExe) {
    # Copy to release folder with Korean name
    $koreanExeRelease = Join-Path $releaseDir $koreanName
    Copy-Item $sourceExe $koreanExeRelease -Force
    
    # Copy to BOT folder (English name)
    $englishExeBot = Join-Path $botDir "bot-dashboard.exe"
    Copy-Item $sourceExe $englishExeBot -Force
    
    # Copy to BOT folder (Korean name)
    $koreanExeBot = Join-Path $botDir $koreanName
    Copy-Item $sourceExe $koreanExeBot -Force
    
    Write-Host "      Executables copied!" -ForegroundColor Green
} else {
    Write-Host "bot-dashboard.exe not found!" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Build Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Files created:" -ForegroundColor Cyan
Write-Host "  [release] bot-dashboard.exe" -ForegroundColor White
Write-Host "  [release] $koreanName" -ForegroundColor White
Write-Host "  [BOT] bot-dashboard.exe" -ForegroundColor White
Write-Host "  [BOT] $koreanName" -ForegroundColor White
Write-Host ""
