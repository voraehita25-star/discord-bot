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
| ⌨️ **Keyboard Shortcuts** | Ctrl+1-4 navigation, Ctrl+R refresh, Ctrl+T theme |
| 🧪 **Unit Tests** | 26 tests with vitest |
| 📊 **Enhanced Settings** | Configurable refresh interval, notifications |
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
| `Ctrl+2` | Go to Logs |
| `Ctrl+3` | Go to Database |
| `Ctrl+4` | Go to Settings |
| `Ctrl+R` | Refresh All Data |
| `Ctrl+T` | Toggle Dark/Light Theme |

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
| Executable Size | ~12 MB |
| Memory Usage | ~30 MB |
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
│   ├── app.ts              # TypeScript source (959 lines)
│   └── app.test.ts         # Unit tests (26 tests)
├── scripts/
│   ├── build-tauri.ps1     # Build + auto-rename script
│   └── create_desktop_shortcut.py  # Create Korean-named shortcut
├── ui/
│   ├── index.html          # Main UI (with charts, sakura)
│   ├── styles.css          # Dark/Light theme styling
│   └── app.js              # Compiled JS
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
| `get_status` | Get bot running status |
| `start_bot` | Start bot (hidden console) |
| `start_dev_bot` | Start bot in dev mode |
| `stop_bot` | Stop bot process |
| `restart_bot` | Restart bot |
| `get_logs` | Read recent log lines |
| `get_db_stats` | Get database statistics |
| `get_recent_channels` | Get active channels |
| `get_top_users` | Get top message users |
| `clear_history` | Delete all chat history |
| `open_folder` | Open folder in Explorer |

## 🔧 Configuration

Bot paths are hardcoded in `main.rs`:
```rust
let base_path = PathBuf::from(r"C:\Users\ME\BOT");
```

## 📜 License

MIT
