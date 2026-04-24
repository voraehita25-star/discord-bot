# 디스코드 봇 대시보드 v2.0 (Discord Bot Dashboard)

🎮 **Enhanced Edition** - Tauri-based native desktop dashboard for managing Discord Bot.

## ✨ New Features (v2.0)

| Feature | Description |
|---------|-------------|
| 🔔 **Toast Notifications** | Beautiful animated notifications for all actions |
| 📈 **Performance Charts** | Real-time memory & message count graphs |
| 🌙 **Dark/Light Theme** | Toggle theme with localStorage persistence |
| 🌸 **Sakura Animation** | Beautiful falling cherry blossom petals |
| ⚡ **Performance Caching** | Smart caching reduces API calls by 50% |
| ⌨️ **Keyboard Shortcuts** | Ctrl+1-6 navigation, Ctrl+R refresh, Ctrl+T theme, Ctrl+Enter to send |
| 💬 **AI Chat** | Streaming WebSocket chat (Gemini + Claude); Claude can run via SDK or `claude -p` subprocess (subscription) |
| 🧠 **Long-term Memory** | Add / browse / delete memories the bot uses for context |
| 🧪 **Unit Tests** | 26 tests with vitest |
| 📊 **Enhanced Settings** | Configurable refresh interval, notifications, avatars |
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

## 🏗️ Tech Stack

| Component | Technology |
|-----------|------------|
| Backend | Rust + Tauri v2 |
| Frontend | HTML + CSS + **TypeScript** |
| Testing | Vitest + jsdom |
| Database | SQLite (rusqlite) |
| Process Control | sysinfo, std::process |

## 📊 Performance

| Metric | Value |
|--------|-------|
| Executable Size | ~17 MB (release build) |
| Memory Usage | ~30 MB idle |
| Startup Time | < 1 second |
| API Call Reduction | 50% (with caching) |

## 📁 Project Structure

```
native_dashboard/
├── Cargo.toml              # Rust dependencies
├── tauri.conf.json         # Tauri config
├── build.rs                # Build script
├── package.json            # npm dependencies (v2.0.0)
├── tsconfig.json           # TypeScript config
├── vitest.config.ts        # Test configuration
├── src/
│   ├── main.rs             # App entry + Tauri commands
│   ├── lib.rs              # Module exports
│   ├── bot_manager.rs      # Bot process control
│   └── database.rs         # SQLite queries
├── src-ts/
│   ├── app.ts              # Main TS — UI, charts, bot control, settings (~1.6k lines)
│   ├── chat-manager.ts     # AI Chat & Memory WebSocket client (~2.5k lines)
│   ├── shared.ts           # Shared utils (invoke wrapper, errors, settings, toasts)
│   ├── types.ts            # Shared TypeScript interfaces
│   ├── faust_avatar.ts     # Default AI avatar (base64)
│   └── app.test.ts         # Unit tests (26 tests)
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
npm run build        # Compile TypeScript
npm test             # Run unit tests
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
npm test             # Run tests once
npm run test:watch   # Watch mode
npm run test:coverage # With coverage report
```

### Output Files

```
target/release/디스코드 봇 대시보드.exe           # Main executable
target/release/bundle/nsis/디스코드 봇 대시보드_1.0.0_x64-setup.exe  # Installer
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
