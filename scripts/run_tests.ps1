<#
.SYNOPSIS
    Run pytest without hanging. Bypasses pyproject.toml's -v flag
    and avoids PowerShell pipe issues that cause pytest to freeze.

.DESCRIPTION
    Usage:
        .\scripts\run_tests.ps1                    # Run ALL tests
        .\scripts\run_tests.ps1 database           # Run tests matching "database"
        .\scripts\run_tests.ps1 music              # Run tests matching "music"
        .\scripts\run_tests.ps1 -File test_database_extended.py
        .\scripts\run_tests.ps1 -File test_database_extended.py -TestName test_pool
        .\scripts\run_tests.ps1 -Coverage           # Run with coverage report

.PARAMETER Filter
    Keyword filter — matches test filenames containing this string.
    Example: "database" runs test_database.py, test_database_extended.py, etc.

.PARAMETER File
    Specific test file to run (just the filename, no path needed).

.PARAMETER TestName
    Specific test function name pattern (uses pytest -k).

.PARAMETER Coverage
    Enable coverage report.

.PARAMETER Fast
    Skip tests marked @pytest.mark.slow (saves ~6s).

.PARAMETER StopOnFail
    Stop on first failure (default: true).
#>

param(
    [Parameter(Position = 0)]
    [string]$Filter = "",

    [string]$File = "",
    [string]$TestName = "",
    [switch]$Coverage,
    [switch]$Fast,
    [bool]$StopOnFail = $true
)

$ErrorActionPreference = "Continue"
Set-Location -Path (Split-Path -Parent (Split-Path -Parent $PSCommandPath))

# Build pytest args — override pyproject.toml's addopts to remove -v
$args_list = @(
    "-m", "pytest"
    "--override-ini=addopts="     # Clear -v from pyproject.toml
    "--tb=short"
    "-q"                          # Quiet mode — compact output
)

# Determine test target
if ($File) {
    $target = "tests/$File"
    if (-not (Test-Path $target)) {
        Write-Host "ERROR: File not found: $target" -ForegroundColor Red
        exit 1
    }
    $args_list += $target
}
elseif ($Filter) {
    # Find all matching test files
    $matched = Get-ChildItem -Path "tests" -Filter "test_*${Filter}*.py" -Name
    if (-not $matched) {
        Write-Host "ERROR: No test files matching '*${Filter}*'" -ForegroundColor Red
        exit 1
    }
    Write-Host "Matched files:" -ForegroundColor Cyan
    $matched | ForEach-Object { Write-Host "  tests/$_" -ForegroundColor DarkCyan }
    Write-Host ""
    foreach ($f in $matched) { $args_list += "tests/$f" }
}
else {
    $args_list += "tests/"
}

# Optional flags
if ($StopOnFail) { $args_list += "-x" }
if ($TestName)   { $args_list += "-k"; $args_list += $TestName }
if ($Fast)       { $args_list += "-m"; $args_list += "not slow"; $args_list += "-p"; $args_list += "no:warnings"; $args_list += "--tb=no" }
if ($Coverage)   { $args_list += "--cov=cogs"; $args_list += "--cov=utils"; $args_list += "--cov-report=term" }

# Show command
$cmd = "python " + ($args_list -join " ")
Write-Host "Running: $cmd" -ForegroundColor Yellow
Write-Host ("=" * 70) -ForegroundColor DarkGray

# Run pytest directly (NO pipe) to prevent hanging
$sw = [System.Diagnostics.Stopwatch]::StartNew()
& python @args_list
$exitCode = $LASTEXITCODE
$sw.Stop()

# Summary
Write-Host ("=" * 70) -ForegroundColor DarkGray
$elapsed = $sw.Elapsed.TotalSeconds.ToString("F1")
if ($exitCode -eq 0) {
    Write-Host "ALL TESTS PASSED  (${elapsed}s)" -ForegroundColor Green
}
else {
    Write-Host "TESTS FAILED (exit code: $exitCode, ${elapsed}s)" -ForegroundColor Red
}

exit $exitCode
