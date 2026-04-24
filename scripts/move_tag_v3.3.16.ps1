# ============================================================================
# Move tag v3.3.16 to current HEAD on GitHub.
#
# Why: after publishing v3.3.16, we rebuilt the dashboard so the backtick
# fix in chat/formatter.ts would land in the compiled ui/chat/formatter.js
# that the exe bundles. The rebuild added one commit on top of the tagged
# commit — moving the tag makes the v3.3.16 Release on GitHub point at
# the up-to-date state instead of the pre-rebuild one.
#
# This is a force-update of a published tag. Safe here because this is
# a solo-dev project; would be anti-pattern on a shared library.
#
# Usage:
#   Double-click MOVE_TAG_v3.3.16.bat
#   OR from a shell: .\scripts\move_tag_v3.3.16.ps1
# ============================================================================

$ErrorActionPreference = 'Stop'

# Jump to repo root regardless of where the script was invoked from.
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

Write-Host ""
Write-Host "====================================================" -ForegroundColor Cyan
Write-Host " Move tag v3.3.16 to current HEAD" -ForegroundColor Cyan
Write-Host "====================================================" -ForegroundColor Cyan
Write-Host ""

# --- Sanity checks --------------------------------------------------------
Write-Host "Checking repo state..." -ForegroundColor Yellow

$currentBranch = git rev-parse --abbrev-ref HEAD
if ($currentBranch -ne 'master') {
    Write-Host "ERROR: Expected to be on branch 'master', but on '$currentBranch'." -ForegroundColor Red
    exit 1
}

$headSha = git rev-parse HEAD
$tagSha  = git rev-list -n 1 v3.3.16 2>$null
if (-not $tagSha) {
    Write-Host "ERROR: local tag v3.3.16 not found. Expected it to exist from publish step." -ForegroundColor Red
    exit 1
}

Write-Host "  local HEAD:    $headSha"
Write-Host "  v3.3.16 tag:   $tagSha"
if ($headSha -eq $tagSha) {
    Write-Host ""
    Write-Host "Tag already points at HEAD. Nothing to do." -ForegroundColor Green
    exit 0
}
Write-Host "  -> tag will be moved to HEAD" -ForegroundColor Gray
Write-Host ""

# Show user what's between tag and HEAD so they can back out.
Write-Host "Commits between the old tag and HEAD:" -ForegroundColor Yellow
git log --oneline "$tagSha..HEAD"
Write-Host ""

$confirm = Read-Host "Proceed? (y/N)"
if ($confirm -ne 'y') {
    Write-Host "Aborted." -ForegroundColor Yellow
    exit 0
}
Write-Host ""

# --- Step 1: Move local tag -----------------------------------------------
Write-Host "[1/3] Moving local tag to HEAD..." -ForegroundColor Yellow

$tagMsg = @'
v3.3.16: chat-manager modularization + frontend test suite

Highlights:
- Split chat-manager.ts (3,225 -> 2,080 LOC) into 11 focused modules
  under src-ts/chat/ (types, ws-client, formatter, message-template,
  context-window, conversation-list, conversation-modals, search,
  prism, image-attach, export-picker).
- Frontend test suite expanded from 26 -> 189 vitest tests across
  10 files (app, chat-manager + 8 chat/ modules).
- Python test suite now 3,071 tests (91 files).
- Fixed latent bug in chat/formatter.ts where escapeHtml() escaped
  backticks to &#96;, preventing the markdown pipeline from matching
  fenced code blocks. Surfaced by the new formatter test suite.
- Documentation refreshed to reflect the new state.
- Dashboard rebuilt so the formatter fix is baked into the shipped
  ui/chat/formatter.js (picked up by the bundled exe).
'@

# git tag uses GIT_COMMITTER_* env vars for the tagger identity.
$env:GIT_COMMITTER_NAME  = 'voraehita25-star'
$env:GIT_COMMITTER_EMAIL = 'voraehita25@gmail.com'

git tag -fa v3.3.16 -m $tagMsg HEAD
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: tag move failed." -ForegroundColor Red
    exit 1
}
Write-Host "      done." -ForegroundColor Green
Write-Host ""

# --- Step 2: Delete remote tag --------------------------------------------
Write-Host "[2/3] Deleting remote tag on GitHub..." -ForegroundColor Yellow
Write-Host "      (GitHub may prompt for username + Personal Access Token)" -ForegroundColor Gray
Write-Host ""

git push origin :refs/tags/v3.3.16
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: remote tag delete failed." -ForegroundColor Red
    Write-Host "       Common cause: auth failed. Generate a PAT at" -ForegroundColor Red
    Write-Host "       https://github.com/settings/tokens/new (scope: repo)" -ForegroundColor Red
    exit 1
}
Write-Host "      done." -ForegroundColor Green
Write-Host ""

# --- Step 3: Push new tag -------------------------------------------------
Write-Host "[3/3] Pushing new tag to GitHub..." -ForegroundColor Yellow

git push origin v3.3.16
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: push of new tag failed." -ForegroundColor Red
    Write-Host "       Local tag is still valid; just run this script again" -ForegroundColor Red
    Write-Host "       to retry the push." -ForegroundColor Red
    exit 1
}
Write-Host "      done." -ForegroundColor Green
Write-Host ""

# --- Summary --------------------------------------------------------------
Write-Host "====================================================" -ForegroundColor Cyan
Write-Host " Done!" -ForegroundColor Cyan
Write-Host "====================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Tag v3.3.16 now points at:" -ForegroundColor Green
Write-Host "  $headSha" -ForegroundColor White
Write-Host ""
Write-Host "The Release page updates automatically since it tracks the tag:"  -ForegroundColor Gray
Write-Host "  https://github.com/voraehita25-star/discord-bot/releases/tag/v3.3.16" -ForegroundColor White
Write-Host ""
