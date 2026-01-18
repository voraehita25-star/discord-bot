# ============================================================================
#                    Startup Scripts - Common Functions v4.0
#                         Shared PowerShell Functions
# ============================================================================

# Get script directory and project root
$script:StartupDir = $PSScriptRoot
$script:ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)

# Load configuration
$script:ConfigPath = Join-Path $PSScriptRoot "startup.json"
if (Test-Path $ConfigPath) {
    $script:Config = Get-Content $ConfigPath -Raw | ConvertFrom-Json
}
else {
    # Default config
    $script:Config = @{
        bot     = @{ max_restarts = 50; restart_delay_seconds = 10 }
        health  = @{ min_disk_space_gb = 1; min_memory_mb = 1024 }
        display = @{ box_width = 69; colored_output = $true }
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

# Disable colors if configured
if (-not $Config.display.colored_output) {
    $C.Keys | ForEach-Object { $C[$_] = "" }
}

# ============================================================================
# Logging Functions
# ============================================================================
function Write-Log {
    param(
        [string]$Message,
        [ValidateSet("INFO", "OK", "WARN", "ERROR", "DEBUG")]
        [string]$Level = "INFO"
    )
    
    $Time = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $LogFile = Join-Path $LogsDir "startup.log"
    
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
    $Time = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $LogFile = Join-Path $LogsDir "startup.log"
    "" | Add-Content -Path $LogFile
    "================================================================" | Add-Content -Path $LogFile
    "[$Time] Starting: $Title" | Add-Content -Path $LogFile
    "================================================================" | Add-Content -Path $LogFile
}

# ============================================================================
# Box Drawing Functions
# ============================================================================
$script:BoxWidth = $Config.display.box_width

function Get-DisplayWidth {
    param([string]$Text)
    $Clean = $Text -replace '\x1b\[[0-9;]*m', ''
    $Width = 0
    foreach ($Char in $Clean.ToCharArray()) {
        $Code = [int]$Char
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
    
    # Python
    $PythonOK = $null -ne (Get-Command python -ErrorAction SilentlyContinue)
    if ($PythonOK) {
        Write-Log "Python installed" -Level OK
    }
    else {
        Write-Log "Python not found" -Level ERROR
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
    python -c "import discord, google.genai" 2>&1 | Out-Null
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
        $OldPid = Get-Content $PidFile
        if ($OldPid -match "^\d+$") {
            $Process = Get-Process -Id $OldPid -ErrorAction SilentlyContinue
            if ($Process -and $Process.ProcessName -match "python") {
                Write-Log "Stopping existing bot (PID: $OldPid)..." -Level WARN
                Stop-Process -Id $OldPid -Force -ErrorAction SilentlyContinue
                Start-Sleep -Seconds 2
                Write-Log "Old instance stopped" -Level OK
            }
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

# Export functions
Export-ModuleMember -Function * -Variable Config, ProjectRoot, LogsDir, C, BoxWidth, ScriptsDir
