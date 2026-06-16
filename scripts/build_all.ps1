# Build all native extensions
# Run from project root: .\scripts\build_all.ps1

param(
    [switch]$Release,
    [switch]$Clean,
    [switch]$RunServices
)

$ErrorActionPreference = "Stop"

Write-Host "===========================================================" -ForegroundColor Magenta
Write-Host "  Building Native Extensions (Rust + Go)                   " -ForegroundColor Magenta
Write-Host "===========================================================" -ForegroundColor Magenta
Write-Host ""

$ScriptsDir = $PSScriptRoot

# Build Rust
# หมายเหตุ: child script ที่ fail จะเรียก `exit 1` ซึ่งกับ call operator (`&`)
# จะปิด host process ทั้งหมด ดังนั้น failure path จะจบที่นี่อยู่แล้ว เราจึงห่อด้วย
# try/catch ($ErrorActionPreference = "Stop") เพื่อจับ error ที่โยนออกมา และ
# reset $LASTEXITCODE ก่อนเรียกทุกครั้ง เพื่อไม่ให้ค่า nonzero ค้างจาก native
# command ก่อนหน้า ทำให้รายงาน "build failed" ผิดพลาดบน success path
Write-Host "-----------------------------------------------------------" -ForegroundColor DarkGray
$global:LASTEXITCODE = 0
try {
    & "$ScriptsDir\build_rust.ps1" -Release:$Release -Clean:$Clean
} catch {
    Write-Host "[ERROR] Rust build failed: $_" -ForegroundColor Red
    exit 1
}
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Rust build failed (exit code $LASTEXITCODE)" -ForegroundColor Red
    exit 1
}

Write-Host ""

# Build Go
Write-Host "-----------------------------------------------------------" -ForegroundColor DarkGray
$global:LASTEXITCODE = 0
try {
    & "$ScriptsDir\build_go.ps1" -Release:$Release -Clean:$Clean -Run:$RunServices
} catch {
    Write-Host "[ERROR] Go build failed: $_" -ForegroundColor Red
    exit 1
}
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Go build failed (exit code $LASTEXITCODE)" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "===========================================================" -ForegroundColor Magenta
Write-Host "  [OK] All native extensions built successfully!           " -ForegroundColor Green
Write-Host "===========================================================" -ForegroundColor Magenta
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Start Go services:    Start-Process .\bin\url_fetcher.exe; Start-Process .\bin\health_api.exe"
Write-Host "  2. Run the bot:          python bot.py"
Write-Host ""
Write-Host "The Python code will automatically detect and use native extensions."
Write-Host "If extensions are not available, it falls back to pure Python."
