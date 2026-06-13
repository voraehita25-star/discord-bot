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

Write-Host "[GO] Building Go Services..." -ForegroundColor Cyan

# Check Go installation
if (-not (Get-Command go -ErrorAction SilentlyContinue)) {
    Write-Host "[ERROR] Go not found. Install from https://go.dev/dl/" -ForegroundColor Red
    exit 1
}

# Create bin directory
if (-not (Test-Path $BinDir)) {
    New-Item -ItemType Directory -Path $BinDir | Out-Null
}

Push-Location $GoDir

try {
    if ($Clean) {
        Write-Host "[CLEAN] Cleaning..." -ForegroundColor Yellow
        go clean -cache
        Remove-Item (Join-Path $BinDir "*") -Force -ErrorAction SilentlyContinue
    }

    # Download dependencies. $ErrorActionPreference="Stop" does NOT trip on a
    # native exe's non-zero exit, so check $LASTEXITCODE explicitly — otherwise
    # a failed resolution (offline, GOPROXY/checksum error) silently falls
    # through to the build with the real root cause masked.
    Write-Host "[INFO] Downloading dependencies..." -ForegroundColor Yellow
    & go mod download
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] go mod download failed" -ForegroundColor Red
        exit 1
    }
    # `go mod tidy` mutates go.mod/go.sum and may hit the network, so it is NOT
    # run on a normal build (which must stay read-only w.r.t. the committed
    # manifests). Only run it on an explicit -Clean rebuild. `go mod download`
    # above already resolves everything needed to build.
    if ($Clean) {
        & go mod tidy
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[ERROR] go mod tidy failed" -ForegroundColor Red
            exit 1
        }
    }

    $BuildFlags = @()
    if ($Release) {
        $BuildFlags = @("-ldflags", "-s -w")
        Write-Host "[BUILD] Building in RELEASE mode (optimized)" -ForegroundColor Green
    } else {
        Write-Host "[BUILD] Building in DEBUG mode" -ForegroundColor Yellow
    }

    # Build URL Fetcher
    Write-Host "Building url_fetcher..." -ForegroundColor Cyan
    $UrlFetcherExe = Join-Path $BinDir "url_fetcher.exe"
    & go build @BuildFlags -o $UrlFetcherExe "./url_fetcher"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] url_fetcher build failed" -ForegroundColor Red
        exit 1
    }
    Write-Host "[OK] Built $UrlFetcherExe" -ForegroundColor Green

    # Build Health API
    Write-Host "Building health_api..." -ForegroundColor Cyan
    $HealthApiExe = Join-Path $BinDir "health_api.exe"
    & go build @BuildFlags -o $HealthApiExe "./health_api"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] health_api build failed" -ForegroundColor Red
        exit 1
    }
    Write-Host "[OK] Built $HealthApiExe" -ForegroundColor Green

    Write-Host ""
    Write-Host "[OK] Go build complete!" -ForegroundColor Green
    Write-Host ""
    Write-Host "To run services:" -ForegroundColor Cyan
    Write-Host "  URL Fetcher:  .\bin\url_fetcher.exe  (port 8081)"
    Write-Host "  Health API:   .\bin\health_api.exe   (port 8082)"

    if ($Run) {
        Write-Host ""
        Write-Host "[RUN] Starting services..." -ForegroundColor Cyan
        Start-Process -FilePath $UrlFetcherExe -NoNewWindow
        Start-Process -FilePath $HealthApiExe -NoNewWindow
        Write-Host "Services started in background"
    }

} finally {
    Pop-Location
}
