# 디스코드 봇 대시보드 v2.0 (Discord Bot Dashboard)

🎮 **Enhanced Edition** - Tauri-based native desktop dashboard for managing Discord Bot.

## ✨ Features

| Feature | Description |
|---------|-------------|
| 💬 **AI Chat** | Streaming WebSocket chat (Gemini + Claude). Claude runs via SDK (per-token) or `claude -p` subprocess (Claude Code Max subscription). Opus 4.8 provides a 1M-token context window natively on both backends. 200K chars/message cap (raised from 50K). |
| 📎 **Document Attachments** | Drag-drop or attach **PDF / DOCX / text / code files** (20+ extensions supported). 32 MB per file, 5 files/message. PDFs read natively by Claude — text + embedded images. |
| 📂 **Persistent Document Memory** | Extracted text from uploaded files is saved to SQLite and auto-injected into every future AI turn **in the same conversation**. Survives bot restarts. Per-conversation scope so RP threads stay isolated. |
| ✏️ **File Editor** | 📎 button in chat header opens a per-conversation file list. Edit filename + extracted text inline (big roomy editor, char counter, Ctrl+S). Delete individual files. |
| 🧠 **Long-term Memory** | Add / browse / delete memories the bot uses for context (separate from document memory). |
| 🎨 **3D UI Polish** | Layered shadows, cursor-tracking card tilt, ripple on click, button press feedback, glassmorphism noise overlay, 3D sphere status dot, custom scrollbars, skeleton loaders, number count-up animations, chart entrance fade. |
| 🌸 **Sakura Animation** | Cherry-blossom petals with mouse-parallax drift. Toggleable. |
| 🔊 **Sound + Haptic** | Optional synth click + vibration on button press (off by default). |
| 🌙 **Dark / Light Theme** | Toggle with localStorage persistence — pink/purple anime palette. |
| 🔔 **Toast Notifications** | Animated slide-in for confirmations / errors. |
| 📈 **Performance Charts** | Real-time memory & message count graphs. |
| ⚡ **Performance Caching** | LRU caching reduces repeat API calls ~50%. |
| ⌨️ **Keyboard Shortcuts** | Ctrl+1-6 navigation, Ctrl+R refresh, Ctrl+T theme, Ctrl+Enter to send, Ctrl+S in editors. |
| 🧪 **Unit Tests** | 189 tests across 10 vitest files: `app.test.ts`, `chat-manager.test.ts`, `e2e_smoke.test.ts` + 7 in `src-ts/chat/` (context-window, conversation-list, conversation-modals, formatter, message-template, prism, search). |
| 🤖 **Headless E2E** | 73 Playwright tests across 8 spec files in `tests-e2e/` — UI smoke, user-flow interactions, axe-core a11y audit, visual-regression snapshots, H5 import-map IPC, H7 strict-CSP render, deep UI inspection. Runs in CI on Chromium with python http.server + mocked Tauri IPC. A real (non-mock) Tauri Rust-IPC round-trip is covered by `scripts/dev/validate_ipc.py` (tauri-driver/WebView2). |
| 📊 **Enhanced Settings** | Configurable refresh interval, notifications, avatars, sakura, sound, haptic, telemetry. |
| 🔤 **Korean Name** | Full Korean support: 디스코드 봇 대시보드.exe |

## 📦 Features

- **Bot Control**: Start, Stop, Restart, Dev Mode
- **Real-time Status**: Online/Offline badge, PID, Uptime, Memory
- **Log Viewer**: Live logs with filtering (INFO/WARNING/ERROR)
- **Database Stats**: Messages, Channels, Users, RAG Memories
- **Quick Actions**: Open Logs/Data folders
- **System Tray**: Minimize to tray, quick access menu

## ⌨️ Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+1` | Go to Status |
| `Ctrl+2` | Go to AI Chat |
| `Ctrl+3` | Go to Memories |
| `Ctrl+4` | Go to Logs |
| `Ctrl+5` | Go to Database |
| `Ctrl+6` | Go to Settings |
| `Ctrl+R` | Refresh All Data |
| `Ctrl+T` | Toggle Dark/Light Theme |
| `Ctrl+Enter` | Send Message (in Chat) |
| `Ctrl+S` | Save (inside file editor) |
| `Ctrl+F` | In-chat search (inside chat view) |

## 📎 File Attachments

Drag + drop — or click the 📎 button in the input area — to attach up to
**5 files per message, 32 MB each**:

| Category | Formats |
|----------|---------|
| Images | PNG, JPEG, GIF, WebP (20 MB cap) |
| Documents | PDF, DOCX |
| Text + code | `.txt`, `.md`, `.json`, `.yaml`, `.toml`, `.csv`, `.xml`, `.log`, `.py`, `.js`, `.ts`, `.rs`, `.go`, `.java`, `.html`, `.css`, `.sh`, `.sql`, … |

PDFs and DOCX are parsed via `pypdf` / `python-docx` on the bot side — the
extracted text goes into `dashboard_document_memories` (SQLite), scoped to
the conversation. On every subsequent AI turn it's auto-injected into the
system prompt so you don't need to re-upload the same character sheets.

Click the **📎 (count)** button in the chat header to see every file attached
to the current conversation. Per-row **Edit** opens a roomy editor (filename
+ extracted text) and **Delete** removes the file from memory.

> Tauri's native drag-drop is disabled in `tauri.conf.json` (`dragDropEnabled: false`)
> so browser `dataTransfer.files` works normally inside WebView2. Without this
> flip, the OS would intercept file drops and hand the JS layer empty file
> arrays.

## 🏗️ Tech Stack

| Component | Technology |
|-----------|------------|
| Backend | Rust + Tauri v2 |
| Frontend | HTML + CSS + **TypeScript** |
| Unit tests | Vitest + jsdom |
| Headless E2E | Playwright (Chromium) + axe-core (a11y) + visual-regression screenshots |
| Database | SQLite (rusqlite) |
| Process Control | sysinfo, std::process |

## 📊 Performance

| Metric | Value |
|--------|-------|
| Executable Size | ~17.5 MB (release build) |
| Memory Usage | ~30 MB idle |
| Startup Time | < 1 second |
| API Call Reduction | ~50% (with LRU caching) |
| Per-message ceiling | 200,000 chars (text) + 5 files × 32 MB (attachments) |

## 📁 Project Structure

```
native_dashboard/
├── Cargo.toml              # Rust dependencies
├── tauri.conf.json         # Tauri config
├── build.rs                # Build script
├── package.json            # npm dependencies (v2.0.0)
├── tsconfig.json           # TypeScript config
├── vitest.config.ts        # Vitest (unit) configuration
├── playwright.config.ts    # Playwright (headless e2e) configuration
├── src/
│   ├── main.rs             # App entry + Tauri commands
│   ├── lib.rs              # Module exports
│   ├── bot_manager.rs      # Bot process control
│   └── database.rs         # SQLite queries
├── src-ts/
│   ├── app.ts              # Main TS — UI, charts, bot control, settings, 3D interactions (~1.8k lines)
│   ├── chat-manager.ts     # ChatManager orchestrator (~2.2k lines) — chat + file memory modal + editor
│   ├── shared.ts           # Shared utils (invoke wrapper, errors, settings, toasts, 3D interactions, animateNumber, sound+haptic)
│   ├── types.ts            # Shared TypeScript interfaces
│   ├── faust_avatar.ts     # Default AI avatar (base64)
│   ├── app.test.ts         # app.ts unit tests
│   ├── chat-manager.test.ts # ChatManager handleMessage + state-transition tests (22 tests)
│   ├── e2e_smoke.test.ts   # Smoke-level end-to-end tests
│   └── chat/               # Chat modules extracted from chat-manager.ts
│       ├── types.ts              # Shared chat TypeScript interfaces
│       ├── ws-client.ts          # WebSocket client + ping/pong + reconnect
│       ├── formatter.ts          # Markdown + LaTeX + code-fence renderer
│       ├── message-template.ts   # Message HTML + tail-window virtualization
│       ├── context-window.ts     # Token-usage bar (LRU-capped per-conv cache)
│       ├── conversation-list.ts  # Sidebar render + filter (RENDER_CAP=200) + tag chips
│       ├── conversation-modals.ts # Rename + delete-confirm modals
│       ├── search.ts             # In-chat search + match wrap/step cycle
│       ├── prism.ts              # Prism.js lazy language loader
│       ├── image-attach.ts       # Image attachment + drag-drop + paste; routes docs to DocumentAttachManager
│       ├── document-attach.ts    # PDF / DOCX / text / code file attach (32 MB cap, 5 per msg)
│       ├── export-picker.ts      # Export format picker UI
│       └── *.test.ts             # 10 vitest files (189 tests total)
├── tests-e2e/              # Playwright (Chromium) — headless against the static UI
│   ├── _fixtures/mock-tauri.ts   # Installs window.__TAURI__.core.invoke shim + WS stub + page-error tracker
│   ├── dashboard-smoke.spec.ts   # smoke tests for recent UI fixes (null-guards, sakura, modals, ...)
│   ├── interactions.spec.ts      # user-flow tests (clicks, typing, keyboard nav)
│   ├── a11y.spec.ts              # axe-core audits — zero critical/serious WCAG 2.1 AA violations
│   ├── visual-regression.spec.ts # visual tests + screenshot baselines (chromium-win32, <0.5% pixel diff)
│   ├── visual-regression.spec.ts-snapshots/  # Baseline PNGs (checked into git)
│   ├── h5-importmap.spec.ts      # H5: import-map IPC resolves under withGlobalTauri:false
│   ├── h7-csp.spec.ts            # H7: render under strict style-src 'self' (MathML, CSSOM)
│   ├── dashboard-inspection.spec.ts # deep UI inspection (z-index, layout, console-error vigilance)
│   └── screenshots.spec.ts       # capture targets for manual inspection
├── scripts/
│   ├── build-release.ps1   # Build + copy exes (no installer) — fast iteration
│   ├── build-tauri.ps1     # Build + copies + Tauri NSIS installer
│   └── create_desktop_shortcut.py  # Create Korean-named desktop shortcut
├── ui/
│   ├── index.html          # Main UI (chat, memories, charts, sakura, settings)
│   ├── styles.css          # Dark/Light theme styling
│   ├── app.js              # Compiled from src-ts/app.ts (do not edit)
│   ├── chat-manager.js     # Compiled from src-ts/chat-manager.ts
│   ├── shared.js           # Compiled from src-ts/shared.ts
│   ├── chat/               # Compiled from src-ts/chat/*.ts (do not edit)
│   └── vendor/             # Bundled KaTeX + DOMPurify (CSP-friendly, no CDN)
└── icons/
    ├── icon.ico            # Windows icon
    ├── 32x32.png
    └── 128x128.png
```

## 🚀 Build & Run

### Prerequisites

- Rust toolchain (`rustup`)
- Tauri CLI (`cargo install tauri-cli`)
- Node.js + npm (for TypeScript)

### Development

```bash
cd native_dashboard
npm install          # First time only
npm run build        # Compile TypeScript (tsc → ui/)
npm run watch        # Continuous TS recompile (alternative to one-shot build)
npm test             # Run vitest unit tests
npm run dev          # Shortcut: npm run build && cargo tauri dev
# or run cargo tauri dev manually after npm run build:
cargo tauri dev
```

### Production Build

> ⚠️ **IMPORTANT**: `cargo build --release` only produces `bot-dashboard.exe`.
> The Korean-named exe (`디스코드 봇 대시보드.exe`) is a **copy**, not a separate target.
> **Always use the build scripts** to ensure both exes are updated together.

```bash
cd native_dashboard

# ✅ Recommended: builds TS + Rust + copies both exes automatically
.\scripts\build-release.ps1

# ✅ Alternative: builds TS + Rust + copies + creates Tauri installer
.\scripts\build-tauri.ps1
```

Manual build (if needed — **must copy both exes**):

```bash
npm run build                          # 1. Compile TypeScript
cargo build --release                  # 2. Build Rust
# 3. Copy to Korean name (REQUIRED!)
Copy-Item target\release\bot-dashboard.exe "target\release\디스코드 봇 대시보드.exe"
Copy-Item target\release\bot-dashboard.exe ..\bot-dashboard.exe
Copy-Item target\release\bot-dashboard.exe "..\디스코드 봇 대시보드.exe"
```

### Create Desktop Shortcut

```bash
python scripts/create_desktop_shortcut.py
```

### Testing

```bash
# Unit tests (vitest, ~5s)
npm test                       # Run all 189 vitest tests
npm run test:watch             # Watch mode
npm run test:coverage          # With coverage report

# Headless e2e (Playwright + Chromium, ~30s)
npm run test:e2e               # Run all 73 Playwright tests (smoke + interactions + a11y + visual + h5/h7 + inspection)
npm run test:e2e:ui            # Interactive UI mode for debugging
npm run test:e2e -- --update-snapshots  # Re-bake visual baselines after intentional UI changes
npm run test:e2e:screenshots   # Capture screenshots for manual inspection
```

> Playwright spawns `python -m http.server` against `ui/` and installs a Tauri-IPC shim
> (`tests-e2e/_fixtures/mock-tauri.ts`) so the static dashboard runs in pure Chromium —
> no Tauri runtime required. Visual baselines live in
> `tests-e2e/visual-regression.spec.ts-snapshots/` and are checked into git.

#### Real Tauri Rust-IPC validation (no mock)

To exercise the **actual** Rust IPC bridge (not the Chromium mock) — confirming `invoke()`
round-trips and that the import-map IPC works under `withGlobalTauri: false` (H5) in the real
WebView2 runtime — use the opt-in validator (run from the repo root):

```bash
cargo install tauri-driver --locked
# msedgedriver matching the installed WebView2 runtime -> native_dashboard/.drivers/msedgedriver.exe
pip install selenium
cargo tauri build --no-bundle          # produces target/release/bot-dashboard.exe
python scripts/dev/validate_ipc.py     # drives the built .exe, calls get_base_path + get_status
```

`.drivers/` is git-ignored. See `docs/TESTING.md` → "Opt-in Runtime Validators" for details.

### Output Files

```
target/release/bot-dashboard.exe                  # Source binary (Cargo output)
target/release/Discord Bot Dashboard.exe          # English alias (copy)
target/release/디스코드 봇 대시보드.exe           # Korean alias (copy)
target/release/bundle/nsis/디스코드 봇 대시보드_2.0.0_x64-setup.exe  # NSIS installer
```

## 🎨 UI

- Modern dark theme (Fluent Design inspired)
- Korean title: 디스코드 봇 대시보드
- Custom anime-style icon

## 📝 Commands

| Tauri Command | Description |
|---------------|-------------|
| `get_status` | Get bot running status (PID, uptime, memory, mode) |
| `start_bot` / `start_dev_bot` | Start bot — production / hot-reload dev mode |
| `stop_bot` / `restart_bot` | Stop or restart bot process tree |
| `get_logs` / `clear_logs` | Read tail of `logs/bot.log` / truncate it |
| `get_base_path` / `get_logs_path` / `get_data_path` | Bot base path + key subdirs |
| `get_db_stats` | Total messages / channels / entities / RAG memories |
| `get_recent_channels` / `get_top_users` | DB activity views |
| `get_dashboard_conversations_native` | Native SQLite read of dashboard chats (offline fallback when WS is down) |
| `get_dashboard_conversation_detail_native` | Native SQLite read of a single conversation + messages |
| `delete_channels_history` | Bulk delete history for selected channel IDs |
| `clear_history` | Delete all chat history |
| `open_folder` | Open `logs/` or `data/` in Explorer (path-validated) |
| `show_confirm_dialog` | Native confirm dialog (Tauri plugin) |
| `log_frontend_error` | Receive frontend errors → write to `logs/dashboard_errors.log` (rotated at 5MB) |
| `get_dashboard_errors` / `clear_dashboard_errors` | Read / wipe the frontend error log |
| `get_ws_token` / `get_ws_endpoint` | Read DASHBOARD_WS_TOKEN + WS endpoint from bot's `.env` |

## 🔧 Configuration

Bot base path is **auto-resolved** in `main.rs` (no longer hardcoded). Resolution order:

1. `BOT_BASE_PATH` env var if set
2. Saved path from a prior successful run (`%APPDATA%\com.botdashboard.desktop\bot_path.txt`)
3. Dev-mode detection — when the exe lives under `target/debug` or `target/release`, walk up to the `BOT/` folder containing `bot.py`
4. Common locations: `~/BOT`, `~/bot`, `~/Desktop/BOT`, `~/Documents/BOT`
5. Fallback: directory of the exe

Override at runtime by setting `BOT_BASE_PATH=C:\path\to\bot` before launching the dashboard.

## 📜 License

MIT
