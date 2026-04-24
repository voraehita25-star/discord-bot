# ============================================================================
# One-shot publish script for v3.3.16
#
# Does the two steps that Claude Code couldn't do automatically:
#   1. Force-push local `master` to remote `main` (system blocks this for
#      Claude — safety guard on default-branch rewrites)
#   2. Open the pre-filled GitHub "Create Release" page in your browser
#
# Safe to re-run — nothing is destroyed that isn't already backed up on
# GitHub at branch `archive/pre-audit-v3.3.14`.
#
# Usage:
#   Right-click → Run with PowerShell
#   OR from a shell: .\scripts\publish_v3.3.16.ps1
# ============================================================================

$ErrorActionPreference = 'Stop'

# Jump to repo root regardless of where the script was invoked from.
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

Write-Host ""
Write-Host "====================================================" -ForegroundColor Cyan
Write-Host " Publish v3.3.16 to GitHub" -ForegroundColor Cyan
Write-Host "====================================================" -ForegroundColor Cyan
Write-Host ""

# --- Sanity checks --------------------------------------------------------
Write-Host "Checking repo state..." -ForegroundColor Yellow

$currentBranch = git rev-parse --abbrev-ref HEAD
if ($currentBranch -ne 'master') {
    Write-Host "ERROR: Expected to be on branch 'master', but on '$currentBranch'." -ForegroundColor Red
    Write-Host "       Run 'git checkout master' first." -ForegroundColor Red
    exit 1
}

$tagExists = git tag -l v3.3.16
if (-not $tagExists) {
    Write-Host "ERROR: tag v3.3.16 not found locally. Claude should have created it." -ForegroundColor Red
    exit 1
}

$archiveBranchOk = git ls-remote --heads origin archive/pre-audit-v3.3.14
if (-not $archiveBranchOk) {
    Write-Host "WARNING: archive branch 'archive/pre-audit-v3.3.14' not found on origin." -ForegroundColor Yellow
    Write-Host "         The old main history may not be backed up!" -ForegroundColor Yellow
    $confirm = Read-Host "Continue anyway? (y/N)"
    if ($confirm -ne 'y') { exit 1 }
}

Write-Host "  OK - local branch: master" -ForegroundColor Green
Write-Host "  OK - tag v3.3.16 exists locally" -ForegroundColor Green
Write-Host "  OK - archive branch exists on origin" -ForegroundColor Green
Write-Host ""

# --- Step 2: Force-push master to main ------------------------------------
Write-Host "Step 2: Force-pushing local 'master' to remote 'main'..." -ForegroundColor Yellow
Write-Host "        (GitHub may prompt for username + Personal Access Token)" -ForegroundColor Gray
Write-Host ""

git push origin master:main --force-with-lease=main:origin/main
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "ERROR: push failed. See message above." -ForegroundColor Red
    Write-Host "       Common causes:" -ForegroundColor Red
    Write-Host "         - Auth failed: generate a PAT at https://github.com/settings/tokens/new" -ForegroundColor Red
    Write-Host "           with scope 'repo', then use it as the password." -ForegroundColor Red
    Write-Host "         - 'main' moved on remote since we fetched: run 'git fetch origin' and rerun." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "  OK - master successfully pushed to main" -ForegroundColor Green
Write-Host ""

# --- Step 5: Open pre-filled Create Release page --------------------------
$releaseUrl = "https://github.com/voraehita25-star/discord-bot/releases/new?tag=v3.3.16&title=v3.3.16%20%E2%80%94%20chat-manager%20modularization%20%2B%20frontend%20test%20suite"

Write-Host "Step 5: Opening GitHub 'Create Release' page in your browser..." -ForegroundColor Yellow
Write-Host ""
Write-Host "  On that page:" -ForegroundColor Gray
Write-Host "    1. Click 'Generate release notes' (GitHub fills it for you)" -ForegroundColor Gray
Write-Host "    2. Click the green 'Publish release' button" -ForegroundColor Gray
Write-Host ""

Start-Process $releaseUrl

Write-Host "====================================================" -ForegroundColor Cyan
Write-Host " Done!" -ForegroundColor Cyan
Write-Host "====================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Main branch updated. Release page open in browser." -ForegroundColor Green
Write-Host ""
