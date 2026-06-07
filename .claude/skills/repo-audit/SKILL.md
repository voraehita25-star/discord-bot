---
name: repo-audit
description: Run this polyglot repo's full verification (Python ruff+pytest, TypeScript tsc+vitest, Rust cargo check, Go build+vet) and, for deep bug-hunts, a fan-out audit with adversarial verification. Use when asked to audit the repo, review everything, hunt for bugs across the codebase, or confirm all suites pass.
---

# Full repository audit / verification

Polyglot monorepo: Python (`bot.py`, `cogs/`, `utils/`), Rust (`rust_extensions/`,
`native_dashboard/src/`), TypeScript (`native_dashboard/src-ts/`), Go (`go_services/`).

## PATH bootstrap (sandbox shells start with a stripped PATH)
```powershell
$U=$env:USERPROFILE; $env:PATH="$U\.local\node;$U\.local\go\bin;$U\go\bin;$U\.cargo\bin;$env:PATH"
```

## Verify each stack
- **Python** — prepend the venv, then use the wrapper (NEVER raw `pytest -v`, it can hang):
  ```powershell
  $env:PATH="$PWD\.venv\Scripts;$env:PATH"; .\scripts\run_tests.ps1        # green baseline: 3143 passed, 1 skipped
  .venv\Scripts\ruff.exe check .          # and: ruff format --check . (note: many files predate the 100-col config — only fix files you touched)
  ```
  A `socket.gaierror: getaddrinfo failed` line in the pytest log is sandbox no-network noise, not a failure.
- **TypeScript** (`cd native_dashboard`): `npm run typecheck` (strict tsc) + `npm test` (vitest — baseline 190 passed). `npx --no-install playwright test --list` lists e2e (baseline 70 in 8 files; `--list` won't hang, a full run might).
- **Rust** — needs the MSVC env (installed without build tools). Run inside vcvars:
  ```
  cmd /c "set PATH=%USERPROFILE%\.cargo\bin;%PATH% && call \"C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat\" && set PYO3_PYTHON=<repo>\.venv\Scripts\python.exe && cargo check --manifest-path rust_extensions\Cargo.toml --all && cargo check --manifest-path native_dashboard\Cargo.toml"
  ```
- **Go** (`cd go_services`): `go build ./...` + `go vet ./...`.

## Deep bug-hunt (when asked to be exhaustive)
Use the **Workflow** tool: bin-pack the non-test source files into per-file reviewer groups (read every line + grep for dangling refs), then adversarially VERIFY each finding (refute by default). **This repo's audits overstate heavily — verify every finding against the real current code before reporting or fixing.** Watch for truncated greps (`head_limit`): confirm a symbol truly absent before assuming it.

## Reporting
Report findings as a table `[file | line | severity | detail]`. Fix verified issues, then re-run the suites above. Thai (ภาษาไทย) comments/docs are intentional — never translate or flag them.
