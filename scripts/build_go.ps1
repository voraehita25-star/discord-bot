# Build script for Go services
# Run from project root: .\scripts\build_go.ps1

param(
    [switch]$Release,
    [switch]$Clean,
    [switch]$Run
)

$ErrorActionPreference = "Stop"
$GoDir = Join-Path $PSScriptRoot "..\go_services"
$BinDir = Join-Path $PSScriptRoot "..\bin"

Write-Host "🐹 Building Go Services..." -ForegroundColor Cyan

# Check Go installation
if (-not (Get-Command go -ErrorAction SilentlyContinue)) {
    Write-Host "❌ Go not found. Install from https://go.dev/dl/" -ForegroundColor Red
    exit 1
}

# Create bin directory
if (-not (Test-Path $BinDir)) {
    New-Item -ItemType Directory -Path $BinDir | Out-Null
}

Push-Location $GoDir

try {
    if ($Clean) {
        Write-Host "🧹 Cleaning..." -ForegroundColor Yellow
        go clean -cache
        Remove-Item (Join-Path $BinDir "*") -Force -ErrorAction SilentlyContinue
    }

    # Download dependencies
    Write-Host "📦 Downloading dependencies..." -ForegroundColor Yellow
    go mod download
    go mod tidy

    $BuildFlags = @()
    if ($Release) {
        $BuildFlags = @("-ldflags", "-s -w")
        Write-Host "📦 Building in RELEASE mode (optimized)" -ForegroundColor Green
    } else {
        Write-Host "🔧 Building in DEBUG mode" -ForegroundColor Yellow
    }

    # Build URL Fetcher
    Write-Host "Building url_fetcher..." -ForegroundColor Cyan
    $UrlFetcherExe = Join-Path $BinDir "url_fetcher.exe"
    & go build @BuildFlags -o $UrlFetcherExe "./url_fetcher"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "❌ url_fetcher build failed" -ForegroundColor Red
        exit 1
    }
    Write-Host "✅ Built $UrlFetcherExe" -ForegroundColor Green

    # Build Health API
    Write-Host "Building health_api..." -ForegroundColor Cyan
    $HealthApiExe = Join-Path $BinDir "health_api.exe"
    & go build @BuildFlags -o $HealthApiExe "./health_api"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "❌ health_api build failed" -ForegroundColor Red
        exit 1
    }
    Write-Host "✅ Built $HealthApiExe" -ForegroundColor Green

    Write-Host ""
    Write-Host "🎉 Go build complete!" -ForegroundColor Green
    Write-Host ""
    Write-Host "To run services:" -ForegroundColor Cyan
    Write-Host "  URL Fetcher:  .\bin\url_fetcher.exe  (port 8081)"
    Write-Host "  Health API:   .\bin\health_api.exe   (port 8082)"

    if ($Run) {
        Write-Host ""
        Write-Host "🚀 Starting services..." -ForegroundColor Cyan
        Start-Process -FilePath $UrlFetcherExe -NoNewWindow
        Start-Process -FilePath $HealthApiExe -NoNewWindow
        Write-Host "Services started in background"
    }

} finally {
    Pop-Location
}
