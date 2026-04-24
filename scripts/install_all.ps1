# ============================================================
# Complete Installation Script for Discord Bot Project
# Run as Administrator: powershell -ExecutionPolicy Bypass -File scripts\install_all.ps1
# ============================================================

param(
    [switch]$SkipDocker,
    [switch]$SkipDashboard
)

$ErrorActionPreference = "Continue"
$ProgressPreference = 'SilentlyContinue'
$ProjectRoot = Split-Path $PSScriptRoot -Parent
$DownloadDir = "$env:TEMP\bot_setup"

if (-not (Test-Path $DownloadDir)) {
    New-Item -ItemType Directory -Path $DownloadDir -Force | Out-Null
}

function Write-Step {
    param([string]$Message)
    Write-Host "`n$('=' * 60)" -ForegroundColor Cyan
    Write-Host "  $Message" -ForegroundColor Cyan
    Write-Host "$('=' * 60)" -ForegroundColor Cyan
}

function Write-OK   { param([string]$Msg) Write-Host "  [OK] $Msg" -ForegroundColor Green }
function Write-Skip { param([string]$Msg) Write-Host "  [SKIP] $Msg" -ForegroundColor Yellow }
function Write-Fail { param([string]$Msg) Write-Host "  [FAIL] $Msg" -ForegroundColor Red }
function Write-Info { param([string]$Msg) Write-Host "  [INFO] $Msg" -ForegroundColor White }

function Test-CommandExists {
    param([string]$Command)
    $null -ne (Get-Command $Command -ErrorAction SilentlyContinue)
}

function Refresh-Path {
    $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("PATH", "User")
}

# ============================================================
# 0. WINGET
# ============================================================
Write-Step "0/9 - Checking winget"
Refresh-Path
if (Test-CommandExists "winget") {
    Write-OK "winget already available"
} else {
    Write-Info "Installing winget from GitHub..."
    try {
        # Need VCLibs and UI.Xaml as prerequisites
        $vcLibsUrl = "https://aka.ms/Microsoft.VCLibs.x64.14.00.Desktop.appx"
        $vcLibsFile = "$DownloadDir\vclibs.appx"
        Invoke-WebRequest -Uri $vcLibsUrl -OutFile $vcLibsFile -UseBasicParsing
        Add-AppxPackage -Path $vcLibsFile -ErrorAction SilentlyContinue

        $wingetUrl = "https://github.com/microsoft/winget-cli/releases/latest/download/Microsoft.DesktopAppInstaller_8wekyb3d8bbwe.msixbundle"
        $wingetFile = "$DownloadDir\winget.msixbundle"
        Invoke-WebRequest -Uri $wingetUrl -OutFile $wingetFile -UseBasicParsing
        Add-AppxPackage -Path $wingetFile -ForceApplicationShutdown
        Start-Sleep -Seconds 5
        Refresh-Path
        if (Test-CommandExists "winget") {
            Write-OK "winget installed successfully"
        } else {
            Write-Fail "winget install attempted but not in PATH. Will use direct downloads."
        }
    } catch {
        Write-Fail "Could not install winget: $_"
        Write-Info "Will use direct downloads instead."
    }
}

$useWinget = Test-CommandExists "winget"

# ============================================================
# 1. GIT
# ============================================================
Write-Step "1/9 - Git"
Refresh-Path
if (Test-CommandExists "git") {
    Write-OK "Git already installed: $(git --version)"
} else {
    if ($useWinget) {
        Write-Info "Installing Git via winget..."
        winget install Git.Git --accept-source-agreements --accept-package-agreements -h
    } else {
        Write-Info "Downloading Git installer..."
        $gitUrl = "https://github.com/git-for-windows/git/releases/download/v2.47.1.windows.2/Git-2.47.1.2-64-bit.exe"
        $gitFile = "$DownloadDir\git-installer.exe"
        Invoke-WebRequest -Uri $gitUrl -OutFile $gitFile -UseBasicParsing
        Write-Info "Running Git installer (silent)..."
        Start-Process -FilePath $gitFile -ArgumentList "/VERYSILENT /NORESTART /SP- /SUPPRESSMSGBOXES" -Wait
    }
    Refresh-Path
    if (Test-CommandExists "git") { Write-OK "Git installed: $(git --version)" }
    else { Write-Fail "Git not found in PATH. May need terminal restart." }
}

# ============================================================
# 2. PYTHON 3.14
# ============================================================
Write-Step "2/9 - Python 3.14"
Refresh-Path
$pythonVer = try { python --version 2>&1 } catch { "" }
if ($pythonVer -match "3\.14") {
    Write-OK "Python already installed: $pythonVer"
} else {
    if ($useWinget) {
        Write-Info "Installing Python 3.14 via winget..."
        winget install Python.Python.3.14 --accept-source-agreements --accept-package-agreements -h
    } else {
        Write-Info "Downloading Python 3.14 installer..."
        $pythonUrl = "https://www.python.org/ftp/python/3.14.0/python-3.14.0a3-amd64.exe"
        $pythonFile = "$DownloadDir\python-installer.exe"
        Invoke-WebRequest -Uri $pythonUrl -OutFile $pythonFile -UseBasicParsing
        Write-Info "Running Python installer (silent, adding to PATH)..."
        Start-Process -FilePath $pythonFile -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1 Include_pip=1" -Wait
    }
    Refresh-Path
    $pythonVer = try { python --version 2>&1 } catch { "" }
    if ($pythonVer -match "3\.1") { Write-OK "Python installed: $pythonVer" }
    else { Write-Fail "Python not found in PATH. May need terminal restart." }
}

# ============================================================
# 3. FFMPEG
# ============================================================
Write-Step "3/9 - FFmpeg"
Refresh-Path
if (Test-CommandExists "ffmpeg") {
    Write-OK "FFmpeg already installed"
} else {
    if ($useWinget) {
        Write-Info "Installing FFmpeg via winget..."
        winget install Gyan.FFmpeg --accept-source-agreements --accept-package-agreements -h
    } else {
        Write-Info "Downloading FFmpeg..."
        $ffmpegUrl = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
        $ffmpegZip = "$DownloadDir\ffmpeg.zip"
        $ffmpegInstall = "C:\ffmpeg"
        Invoke-WebRequest -Uri $ffmpegUrl -OutFile $ffmpegZip -UseBasicParsing
        Write-Info "Extracting FFmpeg..."
        Expand-Archive -Path $ffmpegZip -DestinationPath "$DownloadDir\ffmpeg_temp" -Force
        $ffmpegDir = Get-ChildItem "$DownloadDir\ffmpeg_temp" -Directory | Select-Object -First 1
        if (Test-Path $ffmpegInstall) { Remove-Item $ffmpegInstall -Recurse -Force }
        Move-Item $ffmpegDir.FullName $ffmpegInstall
        # Add to PATH permanently
        $currentPath = [System.Environment]::GetEnvironmentVariable("PATH", "Machine")
        if ($currentPath -notlike "*$ffmpegInstall\bin*") {
            [System.Environment]::SetEnvironmentVariable("PATH", "$currentPath;$ffmpegInstall\bin", "Machine")
            Write-Info "Added $ffmpegInstall\bin to system PATH"
        }
    }
    Refresh-Path
    if (Test-CommandExists "ffmpeg") { Write-OK "FFmpeg installed" }
    else { Write-Fail "FFmpeg not in PATH. May need terminal restart." }
}

# ============================================================
# 4. VISUAL STUDIO BUILD TOOLS (C++ for Rust)
# ============================================================
Write-Step "4/9 - Visual Studio Build Tools (C++)"
$vsWhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$hasBuildTools = $false
if (Test-Path $vsWhere) {
    $vsInstalls = & $vsWhere -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property displayName 2>$null
    if ($vsInstalls) { $hasBuildTools = $true }
}

if ($hasBuildTools) {
    Write-OK "VS Build Tools (C++) already installed"
} else {
    if ($useWinget) {
        Write-Info "Installing VS Build Tools via winget..."
        winget install Microsoft.VisualStudio.2022.BuildTools --accept-source-agreements --accept-package-agreements -h
        Write-Info "NOTE: After install, open VS Installer and add 'Desktop development with C++' workload"
    } else {
        Write-Info "Downloading VS Build Tools installer..."
        $vsUrl = "https://aka.ms/vs/17/release/vs_BuildTools.exe"
        $vsFile = "$DownloadDir\vs_BuildTools.exe"
        Invoke-WebRequest -Uri $vsUrl -OutFile $vsFile -UseBasicParsing
        Write-Info "Installing VS Build Tools with C++ workload (this takes a while)..."
        Start-Process -FilePath $vsFile -ArgumentList "--quiet --wait --norestart --nocache --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended" -Wait
    }
    Write-Info "VS Build Tools installation initiated."
}

# ============================================================
# 5. RUST
# ============================================================
Write-Step "5/9 - Rust (via rustup)"
Refresh-Path
if (Test-CommandExists "cargo") {
    Write-OK "Rust already installed: $(cargo --version)"
} else {
    if ($useWinget) {
        Write-Info "Installing Rust via winget..."
        winget install Rustlang.Rustup --accept-source-agreements --accept-package-agreements -h
        Refresh-Path
        if (Test-CommandExists "rustup") {
            rustup default stable
        }
    } else {
        Write-Info "Downloading rustup-init..."
        $rustupUrl = "https://win.rustup.rs/x86_64"
        $rustupFile = "$DownloadDir\rustup-init.exe"
        Invoke-WebRequest -Uri $rustupUrl -OutFile $rustupFile -UseBasicParsing
        Write-Info "Installing Rust (stable)..."
        Start-Process -FilePath $rustupFile -ArgumentList "-y --default-toolchain stable" -Wait
    }
    Refresh-Path
    if (Test-CommandExists "cargo") { Write-OK "Rust installed: $(cargo --version)" }
    else { Write-Fail "Rust not in PATH. May need terminal restart." }
}

# ============================================================
# 6. GO
# ============================================================
Write-Step "6/9 - Go"
Refresh-Path
if (Test-CommandExists "go") {
    Write-OK "Go already installed: $(go version)"
} else {
    if ($useWinget) {
        Write-Info "Installing Go via winget..."
        winget install GoLang.Go --accept-source-agreements --accept-package-agreements -h
    } else {
        Write-Info "Downloading Go installer..."
        $goUrl = "https://go.dev/dl/go1.23.5.windows-amd64.msi"
        $goFile = "$DownloadDir\go-installer.msi"
        Invoke-WebRequest -Uri $goUrl -OutFile $goFile -UseBasicParsing
        Write-Info "Installing Go (silent)..."
        Start-Process -FilePath "msiexec.exe" -ArgumentList "/i `"$goFile`" /quiet /norestart" -Wait
    }
    Refresh-Path
    if (Test-CommandExists "go") { Write-OK "Go installed: $(go version)" }
    else { Write-Fail "Go not in PATH. May need terminal restart." }
}

# ============================================================
# 7. NODE.JS
# ============================================================
Write-Step "7/9 - Node.js LTS"
Refresh-Path
if (Test-CommandExists "node") {
    Write-OK "Node.js already installed: $(node --version)"
} else {
    if ($useWinget) {
        Write-Info "Installing Node.js LTS via winget..."
        winget install OpenJS.NodeJS.LTS --accept-source-agreements --accept-package-agreements -h
    } else {
        Write-Info "Downloading Node.js LTS installer..."
        $nodeUrl = "https://nodejs.org/dist/v22.12.0/node-v22.12.0-x64.msi"
        $nodeFile = "$DownloadDir\node-installer.msi"
        Invoke-WebRequest -Uri $nodeUrl -OutFile $nodeFile -UseBasicParsing
        Write-Info "Installing Node.js (silent)..."
        Start-Process -FilePath "msiexec.exe" -ArgumentList "/i `"$nodeFile`" /quiet /norestart" -Wait
    }
    Refresh-Path
    if (Test-CommandExists "node") { Write-OK "Node.js installed: $(node --version)" }
    else { Write-Fail "Node.js not in PATH. May need terminal restart." }
}

# ============================================================
# 8. DOCKER DESKTOP (Optional)
# ============================================================
Write-Step "8/9 - Docker Desktop"
if ($SkipDocker) {
    Write-Skip "Docker skipped by parameter"
} else {
    Refresh-Path
    if (Test-CommandExists "docker") {
        Write-OK "Docker already installed: $(docker --version)"
    } else {
        if ($useWinget) {
            Write-Info "Installing Docker Desktop via winget..."
            winget install Docker.DockerDesktop --accept-source-agreements --accept-package-agreements -h
        } else {
            Write-Info "Downloading Docker Desktop installer..."
            $dockerUrl = "https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe"
            $dockerFile = "$DownloadDir\docker-installer.exe"
            Invoke-WebRequest -Uri $dockerUrl -OutFile $dockerFile -UseBasicParsing
            Write-Info "Installing Docker Desktop (silent)..."
            Start-Process -FilePath $dockerFile -ArgumentList "install --quiet --accept-license" -Wait
        }
        Write-Info "Docker Desktop installed. Requires restart and WSL2."
    }
}

# ============================================================
# 9. PYTHON ENVIRONMENT SETUP
# ============================================================
Write-Step "9/9 - Python Environment Setup"
Refresh-Path

if (Test-CommandExists "python") {
    Push-Location $ProjectRoot
    
    # Create venv if not exists
    if (-not (Test-Path ".venv")) {
        Write-Info "Creating virtual environment..."
        python -m venv .venv
    } else {
        Write-OK "Virtual environment already exists"
    }
    
    # Activate and install
    Write-Info "Installing Python dependencies..."
    & ".venv\Scripts\python.exe" -m pip install --upgrade pip
    & ".venv\Scripts\pip.exe" install -r requirements.txt
    
    # Install dev tools
    Write-Info "Installing development tools..."
    & ".venv\Scripts\pip.exe" install ruff bandit[toml] pip-audit mypy
    
    Pop-Location
    Write-OK "Python environment setup complete"
} else {
    Write-Fail "Python not available. Skipping venv setup."
}

# ============================================================
# SETUP .env FILE
# ============================================================
Write-Step "Setting up .env file"
Push-Location $ProjectRoot
if (-not (Test-Path ".env")) {
    if (Test-Path "env.example") {
        Copy-Item "env.example" ".env"
        Write-OK "Created .env from env.example"
        Write-Info "IMPORTANT: Edit .env and add your DISCORD_TOKEN, GEMINI_API_KEY, CREATOR_ID"
    }
} else {
    Write-OK ".env already exists"
}
Pop-Location

# ============================================================
# SUMMARY
# ============================================================
Write-Host "`n" 
Write-Step "INSTALLATION SUMMARY"
Refresh-Path

$results = @(
    @{Name="winget";   Check={winget --version 2>$null; $?}},
    @{Name="Git";      Check={git --version 2>$null; $?}},
    @{Name="Python";   Check={python --version 2>$null; $?}},
    @{Name="pip";      Check={pip --version 2>$null; $?}},
    @{Name="FFmpeg";   Check={ffmpeg -version 2>$null; $?}},
    @{Name="Rust";     Check={cargo --version 2>$null; $?}},
    @{Name="Go";       Check={go version 2>$null; $?}},
    @{Name="Node.js";  Check={node --version 2>$null; $?}},
    @{Name="npm";      Check={npm --version 2>$null; $?}},
    @{Name="Docker";   Check={docker --version 2>$null; $?}}
)

$installed = 0
$failed = 0
foreach ($r in $results) {
    try {
        $ok = & $r.Check
        if ($ok) {
            Write-OK "$($r.Name)"
            $installed++
        } else {
            Write-Fail "$($r.Name) - not in PATH (restart terminal or PC)"
            $failed++
        }
    } catch {
        Write-Fail "$($r.Name) - not in PATH (restart terminal or PC)"
        $failed++
    }
}

Write-Host "`n  Installed: $installed / $($results.Count)" -ForegroundColor Cyan
if ($failed -gt 0) {
    Write-Host "  $failed tool(s) may need a terminal/PC restart to appear in PATH" -ForegroundColor Yellow
}

Write-Host "`n  NEXT STEPS:" -ForegroundColor Magenta
Write-Host "  1. Restart your terminal (or PC if tools not found)" -ForegroundColor White
Write-Host "  2. Edit .env file with your API keys" -ForegroundColor White
Write-Host "  3. VS Installer > Add 'Desktop development with C++' workload" -ForegroundColor White
Write-Host "  4. Run: .venv\Scripts\activate" -ForegroundColor White
Write-Host "  5. Run: python bot.py" -ForegroundColor White
Write-Host ""
