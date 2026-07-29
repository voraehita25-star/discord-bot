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
    # cargo writes ALL of its progress ("Compiling foo v1.2.3") to stderr.
    # Under Windows PowerShell 5.1, an $ErrorActionPreference of "Stop" turns
    # each of those stderr lines into a TERMINATING NativeCommandError the
    # moment the stream is redirected — so `.\scripts\build_all.ps1 2>&1 |
    # Tee-Object build.log`, or any CI step that merges streams, aborted on the
    # first "Compiling ..." line of a perfectly healthy build and reported
    # "Rust build failed". Every native call below is gated on $LASTEXITCODE,
    # which is the check that actually means something. Cmdlets that must still
    # fail hard pass -ErrorAction Stop explicitly (see Copy-Artifact).
    $ErrorActionPreference = "Continue"

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

    # cargo สำเร็จแล้ว artifact ทุกตัวต้องมีจริง มิฉะนั้นถือว่า build ล้มเหลว
    # ติดตามว่าหา .pyd ที่ต้องการได้ครบหรือไม่ เพื่อ exit 1 (ไม่ใช่แค่ WARN)
    # ป้องกัน build_all.ps1 รายงานสำเร็จทั้งที่ extension ไม่ได้ถูกสร้าง/คัดลอก
    $MissingArtifacts = @()

    function Copy-Artifact {
        <#
        .SYNOPSIS
            Copy one built library into place, explaining a locked destination.
        .DESCRIPTION
            Once a running Python has imported rag_engine.pyd, Windows holds the
            file open and Copy-Item fails with a bare "being used by another
            process" that says nothing about WHICH process or what to do. cargo
            has already succeeded at that point, so the operator sees a build
            that "failed" for no visible reason. Name the culprit instead.
        #>
        param(
            [Parameter(Mandatory)] [string]$Source,
            [Parameter(Mandatory)] [string]$Destination,
            [Parameter(Mandatory)] [string]$Name
        )
        try {
            Copy-Item $Source $Destination -Force -ErrorAction Stop
            Write-Host "[OK] Copied $Name to $Destination" -ForegroundColor Green
            return $true
        } catch [System.IO.IOException] {
            Write-Host "[ERROR] Could not overwrite $Destination - the file is in use." -ForegroundColor Red
            $Holders = Get-Process python, pythonw, bot-dashboard -ErrorAction SilentlyContinue
            if ($Holders) {
                Write-Host "        Likely holders (a process that imported the extension):" -ForegroundColor Yellow
                $Holders | ForEach-Object { Write-Host "          PID $($_.Id)  $($_.ProcessName)" -ForegroundColor Yellow }
            }
            Write-Host "        Stop the bot / dashboard (scripts\startup\manager.bat -> Stop Bot) and rebuild." -ForegroundColor Yellow
            return $false
        } catch {
            Write-Host "[ERROR] Could not copy $Name : $_" -ForegroundColor Red
            return $false
        }
    }

    # Copy RAG Engine
    $RagSource = Join-Path $SourceDir "${LibPrefix}rag_engine$DllExt"
    $RagDest = Join-Path $PSScriptRoot "..\cogs\ai_core\memory\rag_engine$LibExt"
    if (-not (Test-Path $RagSource)) {
        Write-Host "[ERROR] rag_engine not found at $RagSource" -ForegroundColor Red
        $MissingArtifacts += "rag_engine"
    } elseif (-not (Copy-Artifact -Source $RagSource -Destination $RagDest -Name "rag_engine")) {
        $MissingArtifacts += "rag_engine"
    }

    # Copy Media Processor
    $MediaSource = Join-Path $SourceDir "${LibPrefix}media_processor$DllExt"
    $MediaDest = Join-Path $PSScriptRoot "..\utils\media\media_processor$LibExt"
    if (-not (Test-Path $MediaSource)) {
        Write-Host "[ERROR] media_processor not found at $MediaSource" -ForegroundColor Red
        $MissingArtifacts += "media_processor"
    } elseif (-not (Copy-Artifact -Source $MediaSource -Destination $MediaDest -Name "media_processor")) {
        $MissingArtifacts += "media_processor"
    }

    # ถ้ามี artifact ใดหายไป ให้จบด้วย non-zero เพื่อไม่ให้ caller เข้าใจผิดว่าสำเร็จ
    if ($MissingArtifacts.Count -gt 0) {
        Write-Host ""
        Write-Host "[ERROR] Rust build incomplete: missing $($MissingArtifacts -join ', ')" -ForegroundColor Red
        exit 1
    }

    Write-Host ""
    Write-Host "[OK] Rust build complete!" -ForegroundColor Green

} finally {
    Pop-Location
}
