# Build script for Rust extensions
# Run from project root: .\scripts\build_rust.ps1

param(
    [switch]$Release,
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
$RustDir = Join-Path $PSScriptRoot "..\rust_extensions"

Write-Host "[RUST] Building Rust Extensions..." -ForegroundColor Cyan

# Check Rust installation
if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
    Write-Host "[ERROR] Cargo not found. Install Rust from https://rustup.rs" -ForegroundColor Red
    exit 1
}

Push-Location $RustDir

try {
    if ($Clean) {
        Write-Host "[CLEAN] Cleaning..." -ForegroundColor Yellow
        cargo clean
    }

    $BuildArgs = @("build")
    if ($Release) {
        $BuildArgs += "--release"
        Write-Host "[BUILD] Building in RELEASE mode" -ForegroundColor Green
    } else {
        Write-Host "[BUILD] Building in DEBUG mode" -ForegroundColor Yellow
    }

    # Build all workspace members
    & cargo @BuildArgs
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Build failed" -ForegroundColor Red
        exit 1
    }

    # Copy built libraries to Python path
    $TargetDir = if ($Release) { "release" } else { "debug" }
    $SourceDir = Join-Path (Join-Path $RustDir "target") $TargetDir

    # Determine library extension
    $LibExt = if ($IsWindows -or $env:OS -match "Windows") { ".pyd" } else { ".so" }
    $DllExt = if ($IsWindows -or $env:OS -match "Windows") { ".dll" } else { ".so" }
    $LibPrefix = if ($IsWindows -or $env:OS -match "Windows") { "" } else { "lib" }

    # Copy RAG Engine
    $RagSource = Join-Path $SourceDir "${LibPrefix}rag_engine$DllExt"
    $RagDest = Join-Path $PSScriptRoot "..\cogs\ai_core\memory\rag_engine$LibExt"
    if (Test-Path $RagSource) {
        Copy-Item $RagSource $RagDest -Force
        Write-Host "[OK] Copied rag_engine to $RagDest" -ForegroundColor Green
    } else {
        Write-Host "[WARN] rag_engine not found at $RagSource" -ForegroundColor Yellow
    }

    # Copy Media Processor
    $MediaSource = Join-Path $SourceDir "${LibPrefix}media_processor$DllExt"
    $MediaDest = Join-Path $PSScriptRoot "..\utils\media\media_processor$LibExt"
    if (Test-Path $MediaSource) {
        Copy-Item $MediaSource $MediaDest -Force
        Write-Host "[OK] Copied media_processor to $MediaDest" -ForegroundColor Green
    } else {
        Write-Host "[WARN] media_processor not found at $MediaSource" -ForegroundColor Yellow
    }

    Write-Host ""
    Write-Host "[OK] Rust build complete!" -ForegroundColor Green

} finally {
    Pop-Location
}
