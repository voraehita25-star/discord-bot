# Build all native extensions
# Run from project root: .\scripts\build_all.ps1

param(
    [switch]$Release,
    [switch]$Clean,
    [switch]$RunServices
)

$ErrorActionPreference = "Stop"

Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Magenta
Write-Host "  🔧 Building Native Extensions (Rust + Go)                 " -ForegroundColor Magenta
Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Magenta
Write-Host ""

$ScriptsDir = $PSScriptRoot

# Build Rust
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor DarkGray
& "$ScriptsDir\build_rust.ps1" -Release:$Release -Clean:$Clean
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Rust build failed" -ForegroundColor Red
    exit 1
}

Write-Host ""

# Build Go
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor DarkGray
& "$ScriptsDir\build_go.ps1" -Release:$Release -Clean:$Clean -Run:$RunServices
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Go build failed" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Magenta
Write-Host "  ✅ All native extensions built successfully!              " -ForegroundColor Green
Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Magenta
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Start Go services:    .\bin\url_fetcher.exe & .\bin\health_api.exe"
Write-Host "  2. Run the bot:          python bot.py"
Write-Host ""
Write-Host "The Python code will automatically detect and use native extensions."
Write-Host "If extensions are not available, it falls back to pure Python."
