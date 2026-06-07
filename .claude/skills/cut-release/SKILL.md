---
name: cut-release
description: Cut a vX.Y.Z release for this repo following its established convention — bump version files, write release notes, commit, fast-forward main, tag, and publish the GitHub release. Use when asked to release, publish a version, tag a version, or "update GitHub and Releases".
---

# Cut a release (vX.Y.Z)

Convention confirmed from prior releases (v3.4.x). Run from a clean-ish working tree.

## 1. Decide the version
Check the latest: `git tag --sort=-v:refname | head` and `gh release list`. If the change set is ambiguous (patch vs minor — e.g. a feature was removed), ASK the user before tagging (a published tag is hard to retract).

## 2. Bump version markers → X.Y.Z
- `version.txt` (whole file)
- `pyproject.toml` (`version = "X.Y.Z"`)
- `CLAUDE.md` (`(vX.Y.Z)` on line ~7)
- Doc headers: `README.md` (`**Version:**`), `docs/DEVELOPER_GUIDE.md`, `cogs/ai_core/README.md`
- Write `docs/release-notes/vX.Y.Z.md` (match the style of the latest existing note: title, Date, sections, a Verification section with current test counts).

## 3. Commit
Stage everything EXCEPT release-prep files and the machine-local config:
```
git add -A
git restore --staged .claude/settings.local.json version.txt pyproject.toml docs/release-notes/vX.Y.Z.md
git commit -F -   # work commit (descriptive)
git add version.txt pyproject.toml docs/release-notes/vX.Y.Z.md
git commit -F -   # release(vX.Y.Z): bump version + notes
```
- **NEVER commit `.claude/settings.local.json`** (machine-specific). The dashboard `.exe` is gitignored.
- End commit messages with the `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>` trailer.

## 4. Merge → main, push, tag (the repo releases from `main`)
```
git fetch origin -q
git merge-base --is-ancestor origin/main <branch>   # must be ancestor → ff-safe; else rebase, don't merge
git checkout main && git merge --ff-only <branch> && git push origin main
git tag -a vX.Y.Z -m "vX.Y.Z — <summary>" && git push origin vX.Y.Z
```

## 5. Publish the GitHub release
`gh` is at `C:\Program Files\GitHub CLI\gh.exe` (already authed as voraehita25-star; prepend `C:\Program Files\GitHub CLI` to PATH or use the full path):
```
gh release create vX.Y.Z --notes-file docs/release-notes/vX.Y.Z.md --title "vX.Y.Z — <title>" --verify-tag
gh release view vX.Y.Z            # confirm draft:false, marked Latest
```
Notes-only release (no `.exe` asset) per convention. To attach the installer, run /build-dashboard + `tauri build` first and `gh release upload`.
