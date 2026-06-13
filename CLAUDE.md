# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this is

A **polyglot monorepo** for a production Discord AI bot (v3.4.6). One repo, four tech stacks:

| Area | Path | Stack | Tests |
| --- | --- | --- | --- |
| Bot core | `bot.py`, `cogs/`, `utils/`, `config.py` | Python 3.14+ — discord.py, Anthropic Claude (`claude-opus-4-8`), Gemini, FAISS RAG, yt-dlp/spotipy | ~5,050+ pytest |
| Rust extensions | `rust_extensions/` | Rust 2021 + PyO3 — `rag_engine` (SIMD vector search), `media_processor`; compiled to `.pyd` | `cargo test` |
| Go services | `go_services/` | Go 1.25 — `url_fetcher` (:8081), `health_api` (:8082, Prometheus) | `go test` |
| Native dashboard | `native_dashboard/` | Tauri 2 + TypeScript 6 — Korean UI | 294 vitest + 72 Playwright |

The AI core (`cogs/ai_core/`) is deeply nested: `api/ core/ response/ commands/ tools/ memory/ processing/ cache/ data/`.

## ⚠️ Read before doing anything

- **Docs & comments are mostly Thai (ภาษาไทย).** This is intentional — don't "fix" or translate it. Ruff's `RUF001/RUF003` (ambiguous-unicode) are disabled for this reason.
- **A freshly spawned sandbox shell may not inherit the User PATH.** The toolchains below are installed and on the persistent User PATH, but a new Bash/PowerShell tool shell can start with a stripped PATH (Git + Windows only). If a bare `node`/`go`/`cargo`/`npm` says "command not found", prepend the dirs in-process first:
  ```powershell
  $U=$env:USERPROFILE; $env:PATH="$U\.local\node;$U\.local\go\bin;$U\go\bin;$U\.cargo\bin;$env:PATH"
  ```
  Installed toolchain locations:
  - **Python 3.14.4** — `C:\Users\ME\AppData\Local\Programs\Python\Python314`; use the venv: `.venv\Scripts\python.exe`
  - **Ruff** — `.venv\Scripts\ruff.exe` (also at `C:\Users\ME\AppData\Local\Zed\languages\ruff\ruff-0.15.0\ruff.exe`)
  - **Node v24 / npm** — `C:\Users\ME\.local\node` (also holds npm-global LSP shims)
  - **Go 1.26** — `C:\Users\ME\.local\go\bin` (GOROOT); `go install` tools land in `C:\Users\ME\go\bin`
  - **Rust** — `C:\Users\ME\.cargo\bin` (cargo/rustc 1.95). ⚠️ Installed *without* MSVC build tools, so `cargo build`/`cargo test` of the `.pyd` extensions needs VS Build Tools (`link.exe`) before it will link.
- **Never run raw `pytest -v` — it can hang.** Use the wrapper, which clears the `-v` from `pyproject.toml` and avoids the pipe freeze:
  ```powershell
  .\scripts\run_tests.ps1                 # all tests
  .\scripts\run_tests.ps1 -Fast           # skip @pytest.mark.slow (~8.5s)
  .\scripts\run_tests.ps1 database        # files matching *database*
  .\scripts\run_tests.ps1 -File test_ai_core.py
  .\scripts\run_tests.ps1 -Coverage
  ```
- **Persona files are git-ignored** and must be copied from examples before the bot runs fully: `cogs/ai_core/data/faust_data.py` (from `faust_data_example.py`) and `roleplay_data.py`. The README warns the repo is intentionally incomplete ("some assembly required").

## Commands

```powershell
# --- Python (run from repo root) ---
.\scripts\run_tests.ps1                      # tests (preferred — see warning above)
.venv\Scripts\ruff.exe check .               # lint
.venv\Scripts\ruff.exe check . --fix         # lint + autofix
.venv\Scripts\ruff.exe format .              # format (double quotes, line-length 100)
.venv\Scripts\python.exe -m bandit -c pyproject.toml -r cogs/ utils/ -ll   # security scan
.venv\Scripts\python.exe bot.py              # run the bot
.venv\Scripts\python.exe scripts\dev_watcher.py   # hot-reload dev mode

# --- Go (cd go_services) ---
go test ./... -v -race
golangci-lint run ./...
.\scripts\build_go.ps1 -Release              # build services

# --- Rust (cd rust_extensions) ---
cargo test --all
cargo clippy --all -- -D warnings
.\scripts\build_rust.ps1 -Release            # builds .pyd next to wrappers
.\scripts\build_all.ps1 -Release             # Rust + Go in one shot

# --- Dashboard (cd native_dashboard) ---
npm test                  # vitest
npm run test:e2e          # Playwright e2e + a11y + visual
npm run build             # tsc
npm run dev               # tsc + cargo tauri dev
npm run release           # production build → Korean-named .exe
```

A cross-platform `Makefile` mirrors most of these (`make test`, `make lint-all`, `make build-all`, `make test-all`) if GNU Make is available.

## Conventions

- **Python**: 3.14+, ruff (line-length 100, double quotes, isort), mypy (`python_version = 3.14`), bandit. Lint config and the full ignore rationale live in `pyproject.toml` — respect the existing ignores rather than re-enabling them.
- **Security posture is a feature.** The codebase hardens against SSRF (DNS-rebind + IPv6), path traversal (`safe_delete` confined to `temp/`), secret leakage (regex log redaction), and Discord mention abuse (sanitization + `AllowedMentions`). Preserve these when editing `utils/web/`, `utils/reliability/`, and `cogs/ai_core/sanitization.py`. Pickle/`.npy` RAG loading is gated behind `RAG_ALLOW_LEGACY_PICKLE` (off by default) — keep it off. The dashboard CLI backend's autonomous file-write mode is similarly gated behind `DASHBOARD_CLI_ALLOW_WRITE` (off by default): when on, the embedded `claude -p` may create/edit files non-interactively, but only inside `DASHBOARD_CLI_WRITE_DIRS` (default the user's Desktop/Documents/Downloads). It is files-only (Bash/web/NotebookEdit/Task denied) and confined by the `cogs/ai_core/api/cli_write_guard.py` PreToolUse hook (fail-closed, exit 2) — preserve that hook as the authoritative path boundary.
- **Claude backend** defaults to `cli` mode (spawns `claude -p`, uses Max-subscription quota, no per-token billing). `api` mode (Anthropic SDK) is opt-in via `CLAUDE_BACKEND=api`. CLI turns `--resume` the server-side session and send only the new message (delta-on-resume); full flattened history goes out only on fresh sessions and the stale-session retry.
- Tests are the source of truth for behavior; update them alongside code changes.

## Claude Code tooling installed for this repo

Plugins (project scope, `claude-plugins-official`): `frontend-design`, `security-guidance` (auto-reviews edits for injection/SSRF/XSS/secrets), `pyright-lsp`, `rust-analyzer-lsp`, `gopls-lsp`, `typescript-lsp`, `sentry`, `context7`.

The four LSP server binaries are **installed** and on the User PATH: `pyright-langserver` + `typescript-language-server` (`~\.local\node`), `gopls` (`~\go\bin`), `rust-analyzer` (`~\.cargo\bin`). They activate in Claude Code after a session restart (the host must pick up the new PATH).
