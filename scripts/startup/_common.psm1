# ============================================================================
#                    Startup Scripts - Common Functions v4.0
#                         Shared PowerShell Functions
# ============================================================================

# Get script directory and project root
$script:StartupDir = $PSScriptRoot
$script:ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)

# Load configuration
$script:ConfigPath = Join-Path $PSScriptRoot "startup.json"
# Default config (mirror the shipped startup.json so the no-config path keeps
# the same safe defaults — notably check_dependencies, which start.ps1 gates
# the dependency check on; omitting it silently disables that gate).
$script:Config = @{
    bot     = @{ max_restarts = 50; restart_delay_seconds = 10; check_dependencies = $true }
    health  = @{ min_disk_space_gb = 1; min_memory_mb = 1024 }
    display = @{ box_width = 69; show_banner = $true; colored_output = $true }
}
if (Test-Path $ConfigPath) {
    # A truncated or hand-edited startup.json used to throw straight out of
    # Import-Module, so a single stray comma bricked start / dev / manager all
    # at once with a raw ConvertFrom-Json error. Fall back to the defaults above
    # and say so instead.
    try {
        $Loaded = Get-Content $ConfigPath -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
        if ($Loaded) { $script:Config = $Loaded }
    }
    catch {
        Write-Warning "startup.json is unreadable ($($_.Exception.Message)) - using built-in defaults"
    }
}

# Paths
$script:LogsDir = Join-Path $ProjectRoot "logs"
$script:DataDir = Join-Path $ProjectRoot "data"
$script:ScriptsDir = Join-Path $ProjectRoot "scripts"
$script:CrashLogsDir = Join-Path $LogsDir "crashes"

# Ensure directories exist
@($LogsDir, $DataDir, $CrashLogsDir) | ForEach-Object {
    if (-not (Test-Path $_)) { New-Item -ItemType Directory -Path $_ -Force | Out-Null }
}

# ============================================================================
# Interpreter resolution
# ============================================================================
# The bot's dependencies live in the repo venv, NOT in the system Python. A
# bare `python` resolves through PATH — which, per CLAUDE.md, a freshly spawned
# shell may not even inherit, and which on this machine points at a bare
# 3.14 install with no discord.py. The launchers used to run the bot that way,
# so Test-Environment reported "Python installed" and the bot then died on its
# first import. Prefer the venv interpreter; fall back to PATH only if it's
# genuinely absent (a checkout that hasn't been provisioned yet).
$script:VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$script:BotPython = if (Test-Path $script:VenvPython) { $script:VenvPython } else { "python" }
$script:UsingVenvPython = (Test-Path $script:VenvPython)

# ============================================================================
# Colors (ANSI Escape Codes)
# ============================================================================
$script:ESC = [char]27
$script:C = @{
    Reset   = "$ESC[0m"
    Bold    = "$ESC[1m"
    Dim     = "$ESC[2m"
    Red     = "$ESC[91m"
    Green   = "$ESC[92m"
    Yellow  = "$ESC[93m"
    Blue    = "$ESC[94m"
    Magenta = "$ESC[95m"
    Cyan    = "$ESC[96m"
    White   = "$ESC[97m"
    Gray    = "$ESC[90m"
}

# Disable colors if configured. Snapshot the keys with @() first: piping the
# live KeyCollection while assigning back into the same hashtable is a
# modify-during-enumeration pattern that only happens to be safe today.
if (-not $Config.display.colored_output) {
    @($C.Keys) | ForEach-Object { $C[$_] = "" }
}

# ============================================================================
# Logging Functions
# ============================================================================
$script:StartupLog = Join-Path $LogsDir "startup.log"
$script:StartupLogMaxBytes = 2MB

function Invoke-StartupLogRotation {
    <#
    .SYNOPSIS
        Roll startup.log once it passes the size cap.
    .DESCRIPTION
        Every launch appends here and nothing ever truncated it, so on a machine
        that restarts the bot often the file grew without bound. Keep one
        previous generation (startup.log.1) and start fresh.
    #>
    try {
        $Existing = Get-Item -LiteralPath $script:StartupLog -ErrorAction Stop
        if ($Existing.Length -lt $script:StartupLogMaxBytes) { return }
        Move-Item -LiteralPath $script:StartupLog -Destination "$($script:StartupLog).1" -Force -ErrorAction Stop
    }
    catch {
        # Missing (nothing to rotate) or locked by a concurrent launcher —
        # logging is best-effort and must never block startup.
    }
}

function Write-Log {
    param(
        [string]$Message,
        [ValidateSet("INFO", "OK", "WARN", "ERROR", "DEBUG")]
        [string]$Level = "INFO"
    )

    $Time = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $LogFile = $script:StartupLog

    $Colors = @{
        INFO  = $C.Cyan
        OK    = $C.Green
        WARN  = $C.Yellow
        ERROR = $C.Red
        DEBUG = $C.Gray
    }
    $Icons = @{
        INFO  = "[*]"
        OK    = "[OK]"
        WARN  = "[!]"
        ERROR = "[X]"
        DEBUG = "[D]"
    }

    Write-Host "  $($Colors[$Level])$($Icons[$Level])$($C.Reset) $Message"
    "[$Time] [$Level] $Message" | Add-Content -Path $LogFile -Encoding UTF8
}

function Write-LogHeader {
    param([string]$Title)
    Invoke-StartupLogRotation
    $Time = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $LogFile = $script:StartupLog
    # -Encoding UTF8 on EVERY write. Write-Log already used it; these four did
    # not, so on Windows PowerShell they fell back to the ANSI code page and the
    # single file ended up holding two encodings — which renders the Thai in
    # later entries as mojibake in any UTF-8 reader.
    $Header = @(
        ""
        "================================================================"
        "[$Time] Starting: $Title"
        "================================================================"
    )
    $Header | Add-Content -Path $LogFile -Encoding UTF8
}

# ============================================================================
# Box Drawing Functions
# ============================================================================
$script:BoxWidth = $Config.display.box_width

function Get-DisplayWidth {
    param([string]$Text)
    $Clean = $Text -replace '\x1b\[[0-9;]*m', ''
    $Width = 0
    # Iterate by Unicode code point, not UTF-16 code unit: astral-plane chars
    # (emoji >= 0x10000) are stored as surrogate pairs, so ToCharArray() would
    # split them and never reach the 0x1F300-0x1F9FF wide-char branch below.
    # Char.ConvertToUtf32 combines the high/low surrogate into the real code point.
    $Chars = $Clean.ToCharArray()
    for ($i = 0; $i -lt $Chars.Length; $i++) {
        $Char = $Chars[$i]
        if ([char]::IsHighSurrogate($Char) -and ($i + 1) -lt $Chars.Length -and
            [char]::IsLowSurrogate($Chars[$i + 1])) {
            $Code = [char]::ConvertToUtf32($Char, $Chars[$i + 1])
            $i++  # consumed the low surrogate as well
        }
        else {
            $Code = [int]$Char
        }
        if ($Code -in @(0x200B, 0x200C, 0x200D) -or
            ($Code -ge 0x0E31 -and $Code -le 0x0E3A) -or
            ($Code -ge 0x0E47 -and $Code -le 0x0E4E)) {
            continue
        }
        if (($Code -ge 0x4E00 -and $Code -le 0x9FFF) -or
            ($Code -ge 0x1F300 -and $Code -le 0x1F9FF)) {
            $Width += 2
        }
        else {
            $Width += 1
        }
    }
    return $Width
}

function Write-BoxLine {
    param(
        [string]$Text,
        [string]$Align = "Left"
    )
    $ContentWidth = $BoxWidth - 4
    $TextWidth = Get-DisplayWidth -Text $Text
    $Padding = $ContentWidth - $TextWidth
    if ($Padding -lt 0) { $Padding = 0 }

    switch ($Align) {
        "Center" {
            $Left = [math]::Floor($Padding / 2)
            $Right = $Padding - $Left
            $Text = (" " * $Left) + $Text + (" " * $Right)
        }
        "Right" { $Text = (" " * $Padding) + $Text }
        default { $Text = $Text + (" " * $Padding) }
    }
    Write-Host "$($C.Cyan)|$($C.Reset) $Text $($C.Cyan)|$($C.Reset)"
}

function Write-BoxTop {
    Write-Host "$($C.Cyan)+$("=" * ($BoxWidth - 2))+$($C.Reset)"
}

function Write-BoxBottom {
    Write-BoxTop
}

function Write-BoxSeparator {
    Write-Host "  $($C.Gray)$("-" * ($BoxWidth - 4))$($C.Reset)"
}

# ============================================================================
# Health Check Functions
# ============================================================================
function Test-Environment {
    Write-Host ""
    Write-BoxTop
    Write-BoxLine -Text "$($C.Bold)$($C.White)Health Checks$($C.Reset)" -Align "Center"
    Write-BoxBottom

    # Python — report which interpreter will actually run the bot, because the
    # venv one and a PATH one have completely different package sets.
    if ($UsingVenvPython) {
        Write-Log "Python: repo venv (.venv\Scripts\python.exe)" -Level OK
    }
    elseif ($null -ne (Get-Command python -ErrorAction SilentlyContinue)) {
        Write-Log "No .venv found - falling back to PATH python (deps may be missing)" -Level WARN
        Write-Log "Create it with: python -m venv .venv; .venv\Scripts\pip install -r requirements.txt" -Level INFO
    }
    else {
        Write-Log "Python not found (no .venv and nothing named python on PATH)" -Level ERROR
        return $false
    }

    # .env file
    $EnvFile = Join-Path $ProjectRoot ".env"
    if (Test-Path $EnvFile) {
        Write-Log ".env file found" -Level OK
    }
    else {
        Write-Log ".env file missing - using defaults" -Level WARN
    }

    # Disk space
    $Drive = (Get-Item $ProjectRoot).PSDrive
    $FreeGB = [math]::Round($Drive.Free / 1GB, 2)
    $MinGB = $Config.health.min_disk_space_gb
    if ($FreeGB -ge $MinGB) {
        Write-Log "Disk space: ${FreeGB}GB free" -Level OK
    }
    else {
        Write-Log "Low disk space: ${FreeGB}GB (min: ${MinGB}GB)" -Level WARN
    }

    # Memory
    $FreeMB = [math]::Round((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1KB, 0)
    $MinMB = $Config.health.min_memory_mb
    if ($FreeMB -ge $MinMB) {
        Write-Log "Memory: ${FreeMB}MB available" -Level OK
    }
    else {
        Write-Log "Low memory: ${FreeMB}MB (min: ${MinMB}MB)" -Level WARN
    }

    return $true
}

function Test-Dependencies {
    Write-Log "Checking dependencies..." -Level INFO
    # Probe the SAME interpreter that will run the bot (see $BotPython above);
    # probing PATH python while launching the venv one — or vice versa — makes
    # this gate meaningless.
    & $BotPython -c "import discord, google.genai" 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Log "Core dependencies installed" -Level OK
        return $true
    }
    else {
        Write-Log "Missing dependencies - run: pip install -r requirements.txt" -Level ERROR
        return $false
    }
}

# ============================================================================
# Process Management
# ============================================================================
function Stop-ExistingBot {
    $PidFile = Join-Path $ProjectRoot "bot.pid"
    if (Test-Path $PidFile) {
        # An empty bot.pid (the bot was killed between create and write) makes
        # Get-Content -Raw return $null, and `$null.Trim()` throws a
        # method-invocation error mid-startup. Read defensively and let the
        # invalid-contents branch below delete the useless file.
        $RawPid = Get-Content $PidFile -Raw -ErrorAction SilentlyContinue
        $OldPid = if ($null -eq $RawPid) { "" } else { [string]$RawPid }
        $OldPid = $OldPid.Trim()
        if ($OldPid -match "^\d+$") {
            $Process = Get-Process -Id $OldPid -ErrorAction SilentlyContinue
            # The OS can recycle a dead bot's PID onto an unrelated python.exe
            # (another bot, a Jupyter kernel, the dashboard CLI backend). A bare
            # ProcessName -match "python" guard would force-kill that innocent
            # process. bot.pid stores only the PID, so confirm identity via the
            # recorded command line: a genuine instance is "python ... bot.py".
            if ($Process -and $Process.ProcessName -match "python") {
                $CmdLine = (Get-CimInstance Win32_Process -Filter "ProcessId = $OldPid" -ErrorAction SilentlyContinue).CommandLine
                if ($CmdLine -and $CmdLine -match "bot\.py") {
                    Write-Log "Stopping existing bot (PID: $OldPid)..." -Level WARN
                    Stop-Process -Id $OldPid -Force -ErrorAction SilentlyContinue
                    Start-Sleep -Seconds 2
                    Write-Log "Old instance stopped" -Level OK
                }
                else {
                    Write-Log "PID $OldPid is python but not the bot (recycled PID?) - leaving it alone" -Level WARN
                }
            }
            Remove-Item $PidFile -ErrorAction SilentlyContinue
        }
        else {
            # Non-numeric / empty / whitespace contents (corrupt or partially
            # written): the file is unusable, so delete it instead of letting the
            # garbage pid file persist across every subsequent launch.
            Write-Log "bot.pid has invalid contents - removing stale pid file" -Level WARN
            Remove-Item $PidFile -ErrorAction SilentlyContinue
        }
    }
}

function Save-CrashReport {
    param(
        [int]$ExitCode,
        [string]$ErrorMessage,
        [TimeSpan]$Runtime
    )

    $Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $CrashFile = Join-Path $CrashLogsDir "crash_$Timestamp.log"
    $RuntimeStr = $Runtime.ToString("hh\:mm\:ss")
    $DateStr = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $OSInfo = [System.Environment]::OSVersion.VersionString
    $PSVer = $PSVersionTable.PSVersion
    $MemFree = [math]::Round((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1MB, 2)

    $Report = @"
================================================================
CRASH REPORT - $DateStr
================================================================

Exit Code: $ExitCode
Error: $ErrorMessage
Runtime: $RuntimeStr

--- System Info ---
OS: $OSInfo
PowerShell: $PSVer
Memory: $MemFree GB free

--- Last Bot Log Lines ---
"@

    $BotLog = Join-Path $LogsDir "bot.log"
    if (Test-Path $BotLog) {
        $Report += "`n" + (Get-Content $BotLog -Tail 50 | Out-String)
    }

    $Report | Out-File -FilePath $CrashFile -Encoding UTF8
    Write-Log "Crash report saved: $CrashFile" -Level ERROR

    # Keep only the 50 most recent reports. A crash-looping bot writes one per
    # restart (max_restarts defaults to 50, and the loop can be re-entered
    # forever), and nothing ever cleaned logs/crashes up.
    try {
        Get-ChildItem -LiteralPath $CrashLogsDir -Filter "crash_*.log" -File -ErrorAction Stop |
            Sort-Object LastWriteTime -Descending |
            Select-Object -Skip 50 |
            Remove-Item -Force -ErrorAction SilentlyContinue
    }
    catch {
        # Pruning is housekeeping; never let it break crash reporting.
    }

    return $CrashFile
}

# ============================================================================
# Banner Display
# ============================================================================
function Show-Banner {
    param([string]$Mode = "Production")

    Clear-Host
    Write-Host ""

    $Art = @(
        " ____  _                       _   ____        _   "
        "|  _ \(_)___  ___ ___  _ __ __| | | __ )  ___ | |_ "
        "| | | | / __|/ __/ _ \| '__/ _' | |  _ \ / _ \| __|"
        "| |_| | \__ \ (_| (_) | | | (_| | | |_) | (_) | |_ "
        "|____/|_|___/\___\___/|_|  \__,_| |____/ \___/ \__|"
    )

    Write-BoxTop
    Write-BoxLine -Text "" -Align "Center"
    foreach ($Line in $Art) {
        Write-BoxLine -Text "$($C.Magenta)$Line$($C.Reset)" -Align "Center"
    }
    Write-BoxLine -Text "" -Align "Center"
    Write-BoxBottom

    $Time = Get-Date -Format "HH:mm:ss"
    $ModeColor = if ($Mode -eq "Dev") { $C.Yellow } else { $C.Green }
    $StatusText = "$($C.Green)[*]$($C.Reset) STATUS: ONLINE | $($ModeColor)MODE: $Mode$($C.Reset) | $($C.Cyan)$Time$($C.Reset)"
    Write-BoxLine -Text $StatusText
    Write-BoxBottom
    Write-Host ""
}

# Export functions. BotPython/UsingVenvPython are exported so every launcher
# runs the bot through the same interpreter this module resolved.
Export-ModuleMember -Function * -Variable Config, ProjectRoot, LogsDir, C, BoxWidth, ScriptsDir, BotPython, UsingVenvPython
