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
# Collapse the ".." so `go build -o` receives a clean absolute directory.
$BinDirResolved = (Resolve-Path $BinDir).ProviderPath.TrimEnd('\', '/')

Push-Location $GoDir

try {
    # `go` writes its progress and diagnostics to stderr, and Windows
    # PowerShell 5.1 with $ErrorActionPreference="Stop" promotes a native
    # command's stderr lines to TERMINATING errors whenever the stream is
    # redirected — which made a healthy build abort under `2>&1 | Tee-Object`
    # or any CI step that merges streams. See build_rust.ps1 for the same note.
    # $LASTEXITCODE, checked after every call below, is the real gate.
    $ErrorActionPreference = "Continue"

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
        # -trimpath strips the local build path out of the binary: smaller,
        # reproducible, and it stops "C:\BOT Discord\go_services\..." from
        # appearing in any panic trace shipped to a user.
        $BuildFlags = @("-trimpath", "-ldflags", "-s -w")
        Write-Host "[BUILD] Building in RELEASE mode (optimized)" -ForegroundColor Green
    } else {
        Write-Host "[BUILD] Building in DEBUG mode" -ForegroundColor Yellow
    }

    # Build both services in ONE `go build`. Passing multiple packages with -o
    # pointing at a DIRECTORY names each output after its package, and lets the
    # toolchain load, type-check and link the shared dependency graph once
    # instead of twice — the two invocations duplicated all of that work.
    Write-Host "Building url_fetcher + health_api..." -ForegroundColor Cyan
    $UrlFetcherExe = Join-Path $BinDir "url_fetcher.exe"
    $HealthApiExe = Join-Path $BinDir "health_api.exe"
    # NO trailing separator on the -o directory. PowerShell hands native commands
    # a raw Windows command line, where a backslash immediately before the
    # closing quote escapes that quote — "...\bin\" would arrive as
    # `...\bin" ./url_fetcher ./health_api`, swallowing both package arguments
    # and failing with the misleading "no Go files in <go_services>".
    & go build @BuildFlags -o $BinDirResolved "./url_fetcher" "./health_api"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Go build failed" -ForegroundColor Red
        exit 1
    }

    # `go build` can exit 0 without producing an artifact if a package resolves
    # to no main (renamed/moved dir), so confirm both binaries actually landed
    # rather than reporting success on an empty bin/.
    $Missing = @()
    foreach ($exe in @($UrlFetcherExe, $HealthApiExe)) {
        if (Test-Path $exe) {
            Write-Host "[OK] Built $exe" -ForegroundColor Green
        } else {
            $Missing += (Split-Path -Leaf $exe)
        }
    }
    if ($Missing.Count -gt 0) {
        Write-Host "[ERROR] Go build produced no binary for: $($Missing -join ', ')" -ForegroundColor Red
        exit 1
    }

    Write-Host ""
    Write-Host "[OK] Go build complete!" -ForegroundColor Green
    Write-Host ""
    Write-Host "To run services:" -ForegroundColor Cyan
    Write-Host "  URL Fetcher:  .\bin\url_fetcher.exe  (port 8081)"
    Write-Host "  Health API:   .\bin\health_api.exe   (port 8082)"

    if ($Run) {
        Write-Host ""
        Write-Host "[RUN] Starting services..." -ForegroundColor Cyan
        # -ErrorAction Stop explicitly: the relaxed preference set above is for
        # native stderr noise, not for a launch that genuinely failed.
        Start-Process -FilePath $UrlFetcherExe -NoNewWindow -ErrorAction Stop
        Start-Process -FilePath $HealthApiExe -NoNewWindow -ErrorAction Stop
        Write-Host "Services started in background"
    }

} finally {
    Pop-Location
}
