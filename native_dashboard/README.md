# 디스코드 봇 대시보드 (Discord Bot Dashboard)

Tauri-based native desktop dashboard for managing Discord Bot.

## 📦 Features

- **Bot Control**: Start, Stop, Restart, Dev Mode
- **Real-time Status**: Online/Offline badge, PID, Uptime, Memory
- **Log Viewer**: Live logs with filtering (INFO/WARNING/ERROR)
- **Database Stats**: Messages, Channels, Users, RAG Memories
- **Quick Actions**: Open Logs/Data folders

## 🏗️ Tech Stack

| Component | Technology |
|-----------|------------|
| Backend | Rust + Tauri v2 |
| Frontend | HTML + CSS + JavaScript |
| Database | SQLite (rusqlite) |
| Process Control | sysinfo, std::process |

## 📊 Performance

| Metric | Value |
|--------|-------|
| Executable Size | ~12 MB |
| Memory Usage | ~30 MB |
| Startup Time | < 1 second |

## 📁 Project Structure

```
native_dashboard/
├── Cargo.toml              # Rust dependencies
├── tauri.conf.json         # Tauri config
├── build.rs                # Build script
├── src/
│   ├── main.rs             # App entry + Tauri commands
│   ├── lib.rs              # Module exports
│   ├── bot_manager.rs      # Bot process control
│   └── database.rs         # SQLite queries
├── ui/
│   ├── index.html          # Main UI
│   ├── styles.css          # Dark theme styling
│   └── app.js              # Frontend logic
└── icons/
    ├── icon.ico            # Windows icon
    ├── 32x32.png
    └── 128x128.png
```

## 🚀 Build & Run

### Prerequisites
- Rust toolchain (`rustup`)
- Tauri CLI (`cargo install tauri-cli`)

### Development
```bash
cd native_dashboard
cargo tauri dev
```

### Production Build
```bash
cd native_dashboard
cargo build --release
```

### Run
```bash
.\target\release\bot-dashboard.exe
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
