# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this is

A **polyglot monorepo** for a production Discord AI bot (v3.5.0). One repo, four tech stacks:

| Area | Path | Stack | Tests |
| --- | --- | --- | --- |
| Bot core | `bot.py`, `cogs/`, `utils/`, `config.py` | Python 3.14+ — discord.py, Anthropic Claude (`claude-opus-5`), Gemini, FAISS RAG, yt-dlp/spotipy | ~5,338 pytest |
| Rust extensions | `rust_extensions/` | Rust 2021 + PyO3 — `rag_engine` (SIMD vector search), `media_processor`; compiled to `.pyd` | `cargo test` |
| Go services | `go_services/` | Go 1.26 — `url_fetcher` (:8081), `health_api` (:8082, Prometheus) | `go test` |
| Native dashboard | `native_dashboard/` | Tauri 2 + TypeScript 6 — English UI, Korean product name/branding | 624 vitest + 164 Playwright |

The AI core (`cogs/ai_core/`) is deeply nested: `api/ core/ response/ commands/ tools/ memory/ processing/ cache/ data/`.

## ⚠️ Read before doing anything

- **Docs & comments are mostly Thai (ภาษาไทย).** This is intentional — don't "fix" or translate it. Ruff's `RUF001/RUF003` (ambiguous-unicode) are disabled for this reason. **New content you write goes in English**, though — comments, docstrings, config notes, docs. Chat replies to the user stay Thai.
- **A freshly spawned sandbox shell may not inherit the User PATH.** The toolchains below are installed and on the persistent User PATH, but a new Bash/PowerShell tool shell can start with a stripped PATH (Git + Windows only). If a bare `node`/`go`/`cargo`/`npm` says "command not found", prepend the dirs in-process first:
  ```powershell
  $U=$env:USERPROFILE; $env:PATH="$U\.local\node;$U\.local\go\bin;$U\go\bin;$U\.cargo\bin;$env:PATH"
  ```
  Installed toolchain locations:
  - **Python 3.14.6** — `C:\Users\ME\AppData\Local\Programs\Python\Python314`; use the venv: `.venv\Scripts\python.exe`
  - **Ruff** — `.venv\Scripts\ruff.exe` (ruff 0.15.17)
  - **Node v24 / npm** — `C:\Users\ME\.local\node` (also holds npm-global LSP shims)
  - **Go 1.26** — `C:\Users\ME\.local\go\bin` (GOROOT); `go install` tools land in `C:\Users\ME\go\bin`
  - **Rust** — `C:\Users\ME\.cargo\bin` (cargo/rustc 1.97). MSVC build tools are installed, so `cargo build`/`cargo test`/`cargo check` of the `.pyd` extensions link and run locally. `cargo test` needs an interpreter for PyO3 — set `PYO3_PYTHON` to the venv python, and keep the base Python dir (which holds `python314.dll`) on PATH or the test binary dies with `STATUS_DLL_NOT_FOUND`.
  - **Docker Desktop** — WSL2 backend, no separate distro. Only needed to reproduce CI's `docker-build` job locally; the engine runs only while Docker Desktop is open.
- **Never run raw `pytest -v` — it can hang.** Use the wrapper, which clears the `-v` from `pyproject.toml` and avoids the pipe freeze:
  ```powershell
  .\scripts\run_tests.ps1                 # all tests
  .\scripts\run_tests.ps1 -Fast           # skip @pytest.mark.slow (~6s)
  .\scripts\run_tests.ps1 database        # files matching *database*
  .\scripts\run_tests.ps1 -File test_ai_core.py
  .\scripts\run_tests.ps1 -Coverage
  ```
- **The pre-commit hook needs the venv on PATH.** `.git/hooks/pre-commit` is installed. Its `pytest-fast` hook is `language: system` and runs a bare `python -m pytest`, so committing from a shell where `python` isn't the venv's fails with a misleading `No module named pytest` — activate `.venv` first (GUI clients like VS Code / GitHub Desktop hit this). CI sets `SKIP: pytest-fast` for the same reason, so use `SKIP=pytest-fast` when reproducing its gate locally. Note the hooks **auto-fix files**, so `pre-commit run --all-files` is not a read-only diagnostic.
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
- **Reasoning depth is an operator setting, not a per-turn one.** `CLAUDE_EFFORT` (`.env`, currently `max`, code default `xhigh`) is passed as `--effort` on every CLI turn; `claude -p` has no flag to turn thinking *off*, which is why the dashboard reports its thinking toggle as unsupported instead of faking it. The value is read only from `.env` — never from `~/.claude/settings.json`, so the bot's behaviour does not track someone's interactive Claude Code preference. That guarantee needs help from `config.reclaim_dotenv_overrides()`, called in `bot.py` right after `load_dotenv()`: Claude Code exports `CLAUDE_EFFORT=<session effort>` into every Bash subprocess it spawns, and `load_dotenv()` leaves an already-set variable alone, so a bot launched from *inside* a Claude Code session would otherwise silently run at that session's depth. The reclaim is scoped to `config._DOTENV_OWNED_KEYS` — every other variable keeps normal precedence, where the real environment beats `.env`.
- Tests are the source of truth for behavior; update them alongside code changes.

## Claude Code tooling installed for this repo

**Reasoning effort is pinned to `max`.** `settings.json` cannot express this: the CLI parses its `effortLevel` key as `v.enum(["low","medium","high","xhigh"]).catch(void 0)`, so `"max"` fails the enum and is dropped **silently, with no warning**. The only source that accepts `max` is the `--effort` flag (resolution order: CLI flag → `ultracode` → `settings.effortLevel`). So `claude` is wrapped by a shell function in `~\Documents\WindowsPowerShell\profile.ps1` and `~/.bashrc` that injects `--effort max`, skipping management subcommands (`mcp`, `plugin`, `update`, …) and any invocation that already passes `--effort`. `~/.claude/settings.json` keeps `effortLevel: "xhigh"` as the floor for launches that bypass the shell (IDE, desktop app). The PowerShell wrapper needs `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` to load at all.

**Plugins.** Project scope (`.claude/settings.json`, all `@claude-plugins-official`): `frontend-design`, `security-guidance` (auto-reviews edits for injection/SSRF/XSS/secrets), `pyright-lsp`, `rust-analyzer-lsp`, `gopls-lsp`, `typescript-lsp`, `context7`, `commit-commands`. `sentry` is listed in `enabledPlugins` but is **not installed**, so it never loads. User scope (`~/.claude/settings.json`, every project): `typescript-lsp` only. `claude-plugins-official` is the sole registered marketplace.

**Repo-local customization.** `.claude/skills/`: `repo-audit`, `build-dashboard`, `cut-release`. `.claude/agents/`: a Thai-labelled handoff chain — `planner` → `coder` → `tester` → `reviewer` → `opposition` — all pinned to `claude-opus-5` at `effort: max`. `.claude/commands/` is empty.

**MCP servers.** No local servers are configured: `~/.claude.json` has an empty `mcpServers`, and the repo ships no `.mcp.json`. What is actually reachable is `context7` (bundled with the plugin), the `claude-in-chrome` browser extension, and the claude.ai account connectors (interactive auth — may be absent in headless/cron runs): Canva, Gmail, Google Calendar, Google Drive. Semgrep MCP was evaluated and skipped for needing Docker/WSL — both are installed now, so that objection no longer applies if it's ever reconsidered.

The four LSP server binaries are **installed** and on the User PATH: `pyright-langserver` + `typescript-language-server` (`~\.local\node`), `gopls` (`~\go\bin`), `rust-analyzer` (`~\.cargo\bin`). They activate in Claude Code after a session restart (the host must pick up the new PATH).
