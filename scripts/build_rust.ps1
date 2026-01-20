# Build script for Rust extensions
# Run from project root: .\scripts\build_rust.ps1

param(
    [switch]$Release,
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
$RustDir = Join-Path $PSScriptRoot "..\rust_extensions"

Write-Host "🦀 Building Rust Extensions..." -ForegroundColor Cyan

# Check Rust installation
if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
    Write-Host "❌ Cargo not found. Install Rust from https://rustup.rs" -ForegroundColor Red
    exit 1
}

Push-Location $RustDir

try {
    if ($Clean) {
        Write-Host "🧹 Cleaning..." -ForegroundColor Yellow
        cargo clean
    }

    $BuildArgs = @("build")
    if ($Release) {
        $BuildArgs += "--release"
        Write-Host "📦 Building in RELEASE mode" -ForegroundColor Green
    } else {
        Write-Host "🔧 Building in DEBUG mode" -ForegroundColor Yellow
    }

    # Build all workspace members
    & cargo @BuildArgs
    if ($LASTEXITCODE -ne 0) {
        Write-Host "❌ Build failed" -ForegroundColor Red
        exit 1
    }

    # Copy built libraries to Python path
    $TargetDir = if ($Release) { "release" } else { "debug" }
    $SourceDir = Join-Path $RustDir "target" $TargetDir

    # Determine library extension
    $LibExt = if ($IsWindows -or $env:OS -match "Windows") { ".pyd" } else { ".so" }
    $DllExt = if ($IsWindows -or $env:OS -match "Windows") { ".dll" } else { ".so" }

    # Copy RAG Engine
    $RagSource = Join-Path $SourceDir "rag_engine$DllExt"
    $RagDest = Join-Path $PSScriptRoot "..\cogs\ai_core\memory\rag_engine$LibExt"
    if (Test-Path $RagSource) {
        Copy-Item $RagSource $RagDest -Force
        Write-Host "✅ Copied rag_engine to $RagDest" -ForegroundColor Green
    }

    # Copy Media Processor
    $MediaSource = Join-Path $SourceDir "media_processor$DllExt"
    $MediaDest = Join-Path $PSScriptRoot "..\utils\media\media_processor$LibExt"
    if (Test-Path $MediaSource) {
        Copy-Item $MediaSource $MediaDest -Force
        Write-Host "✅ Copied media_processor to $MediaDest" -ForegroundColor Green
    }

    Write-Host ""
    Write-Host "🎉 Rust build complete!" -ForegroundColor Green

} finally {
    Pop-Location
}
