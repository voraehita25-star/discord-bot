# 📦 Installation Guide

คู่มือติดตั้ง Discord Bot ฉบับสมบูรณ์

---

## 📋 System Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| **OS** | Windows 10 / Ubuntu 20.04 | Windows 11 / Ubuntu 22.04 |
| **Python** | 3.14+ | 3.14+ |
| **RAM** | 2GB | 4GB |
| **Storage** | 500MB | 1GB |
| **FFmpeg** | Required for voice | Required |

---

## 🔧 Prerequisites

### 1. Python 3.14+

**Windows:**

```bash
# ดาวน์โหลดจาก https://python.org
# หรือใช้ winget
winget install Python.Python.3.14
```

**Linux:**

```bash
sudo apt update
sudo apt install python3.14 python3.14-venv python3-pip
```

### 2. FFmpeg (Required for Voice/Music)

**Windows:**

```bash
# ใช้ winget
winget install ffmpeg

# หรือดาวน์โหลดจาก https://ffmpeg.org/download.html
# แล้วเพิ่มไปที่ PATH
```

**Linux:**

```bash
sudo apt install ffmpeg
```

### 3. Git (Optional แต่แนะนำ)

```bash
# Windows
winget install Git.Git

# Linux
sudo apt install git
```

---

## 🚀 Installation Steps

### Step 1: Clone หรือ Download โปรเจค

```bash
git clone https://github.com/voraehita25-star/discord-bot.git
cd discord-bot
```

### Step 2: สร้าง Virtual Environment

```bash
# สร้าง venv
python -m venv .venv

# Activate (Windows)
.venv\Scripts\activate

# Activate (Linux/Mac)
source .venv/bin/activate
```

### Step 3: ติดตั้ง Dependencies

```bash
pip install -r requirements.txt
```

### Step 4: ตั้งค่า Environment Variables

```bash
# คัดลอก env.example ไปเป็น .env
cp env.example .env

# แก้ไขไฟล์ .env ด้วย editor ที่ชอบ
notepad .env  # Windows
nano .env     # Linux
```

**ค่าที่ต้องกรอก:**

| Variable | Required | Description |
|----------|----------|-------------|
| `DISCORD_TOKEN` | ✅ | Token จาก Discord Developer Portal |
| `ANTHROPIC_API_KEY` | ⚠️ | API Key จาก Anthropic — ต้องตั้งเฉพาะตอน `CLAUDE_BACKEND=api`. โหมดดีฟอลต์ `cli` อ่าน credentials จาก Claude Code login ในเครื่องแทน |
| `CLAUDE_BACKEND` | ❌ | (Optional) Mode การคุยกับ Claude: `cli` (default — spawn `claude -p` ใช้โควต้า Claude Code Max subscription, ไม่เสียค่า per-token) หรือ `api` (anthropic SDK + per-token billing, เปิดใช้ Discord AI replies + memory consolidator + summarizer) |
| `CLAUDE_CODE_OAUTH_TOKEN` | ❌ | (Optional) ตั้งเฉพาะตอนใช้ `CLAUDE_BACKEND=cli` และ bot รันคนละ OS user กับที่ login Claude Code (เช่น service account / Docker) |
| `GEMINI_API_KEY` | ❌ | (Optional) API Key จาก Google AI Studio สำหรับ RAG embeddings (โหลดเฉพาะตอน `CLAUDE_BACKEND=api`) |
| `RAG_ALLOW_LEGACY_PICKLE` | ❌ | (Optional) Opt-in อนุญาตให้โหลด FAISS sidecar `.npy` (pickle) แบบเก่า ปิดดีฟอลต์เพื่อกัน RCE จากไฟล์บนดิสก์ ตั้งเฉพาะตอน migrate deployment เก่าที่เชื่อถือได้ |
| `BOT_MEMORY_WARNING_MB` | ❌ | (Optional) Soft memory threshold เป็น MiB (default: 1024) ปรับตามขนาด container/VM |
| `BOT_MEMORY_CRITICAL_MB` | ❌ | (Optional) Hard memory threshold เป็น MiB (default: 1536) |
| `CREATOR_ID` | ✅ | Discord User ID ของเจ้าของบอท |
| `SPOTIPY_CLIENT_ID` | ❌ | (Optional) Spotify API Client ID |
| `SPOTIPY_CLIENT_SECRET` | ❌ | (Optional) Spotify API Secret |
| `SENTRY_DSN` | ❌ | (Optional) Sentry Error Tracking |
| `DASHBOARD_WS_TOKEN` | ❌ | (Optional) Auth token สำหรับ WebSocket dashboard |
| `DASHBOARD_ALLOW_UNRESTRICTED` | ❌ | (Optional) เปิด unrestricted mode ใน dashboard (`1`/`true`) |
| `HEALTH_API_HOST` | ❌ | (Optional) Bind address สำหรับ Health API (default: `127.0.0.1`) |
| `HEALTH_API_TOKEN` | ❌ | (Optional) Bearer token สำหรับ protected Health API endpoints |

### Step 5: (Optional) ตั้งค่า Persona

```bash
# คัดลอก example files
cp cogs/ai_core/data/faust_data_example.py cogs/ai_core/data/faust_data.py
cp cogs/ai_core/data/roleplay_data_example.py cogs/ai_core/data/roleplay_data.py
```

### Step 6: รันบอท

```bash
python bot.py
```

---

## 📦 Dependencies Breakdown

### Core (จำเป็น)

| Package | Version | Purpose |
|---------|---------|---------|
| `discord.py[voice]` | 2.7.1 | Discord API + Voice Support |
| `python-dotenv` | 1.2.2 | อ่านค่าจาก .env |
| `aiohttp` | 3.13.5 | Async HTTP requests |
| `psutil` | 7.2.2 | System monitoring |

### AI (จำเป็น)

| Package | Version | Purpose |
|---------|---------|---------|
| `google-genai` | 1.75.0 | Gemini AI API |
| `Pillow` | 12.2.0 | Image processing |
| `beautifulsoup4` | 4.14.3 | HTML parsing (URL fetching) |
| `lxml` | 6.1.0 | Fast HTML parser |
| `numpy` | 2.4.4 | Numerical ops (RAG) |
| `faiss-cpu` | 1.13.2 | Vector search (RAG memory) |
| `imageio[ffmpeg]` | 2.37.3 | GIF to video conversion |

### Music (จำเป็นสำหรับ Music feature)

| Package | Version | Purpose |
|---------|---------|---------|
| `yt-dlp` | 2026.3.17 | YouTube download |
| `spotipy` | 2.26.0 | Spotify API |
| `PyNaCl` | >=1.6.2,<2 | Voice encryption |

### Database

| Package | Version | Purpose |
|---------|---------|---------|
| `aiosqlite` | 0.22.1 | Async SQLite |

### Development & Testing

| Package | Version | Purpose |
|---------|---------|---------|
| `pytest` | 9.0.3 | Testing framework |
| `pytest-asyncio` | 1.3.0 | Async test support |
| `pytest-timeout` | 2.4.0 | Test timeout safety net |
| `watchdog` | 6.0.0 | Hot reload (dev mode) |
| `colorama` | 0.4.6 | Windows colors |

### Optional (Performance & Monitoring)

| Package | Version | Purpose |
|---------|---------|---------|
| `orjson` | 3.11.8 | 10x faster JSON |
| `sentry-sdk` | 2.59.0 | Error tracking |

---

## 🖥️ Tauri Dashboard (Optional)

Dashboard สำหรับจัดการบอทแบบ GUI

### Prerequisites

1. **Rust Toolchain:**

```bash
# ติดตั้ง rustup
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

# Windows: ดาวน์โหลดจาก https://rustup.rs
```

1. **Tauri CLI v2:**

```bash
cargo install tauri-cli --version "^2.0"
# Or use the npm script which calls cargo via @tauri-apps/cli
```

1. **WebView2 (Windows only):**
   - Windows 10+ มีติดตั้งมาแล้วปกติ
   - ถ้าไม่มี: <https://developer.microsoft.com/en-us/microsoft-edge/webview2/>

### Build Dashboard

```powershell
cd native_dashboard
npm install              # first time only
npm run release          # full build: tsc + cargo build --release + auto-rename
# or, manually:
npm run build            # tsc → ui/
cargo build --release    # builds target/release/bot-dashboard.exe
```

### Run Dashboard

```powershell
# Windows — pick whichever filename you copied (build script writes all three):
.\target\release\bot-dashboard.exe
.\target\release\"Discord Bot Dashboard.exe"
.\target\release\"디스코드 봇 대시보드.exe"
```

---

## 🦀 Rust Extensions (Optional)

High-performance native extensions สำหรับ RAG และ Media processing

> **Pre-built Status:** ✅ พร้อมใช้งาน (April 2, 2026)
> **Files:** `cogs/ai_core/memory/rag_engine.pyd` (~653 KB), `utils/media/media_processor.pyd` (~1.6 MB)

### Prerequisites

1. **Rust Toolchain:**

```bash
# ติดตั้ง rustup
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

# Windows: ดาวน์โหลดจาก https://rustup.rs
```

### Build Rust Extensions

```powershell
# จาก project root
.\scripts\build_rust.ps1 -Release
```

### Verify

```bash
python -c "import sys; sys.path.insert(0, 'cogs/ai_core/memory'); import rag_engine; print('RAG OK')"
python -c "import sys; sys.path.insert(0, 'utils/media'); import media_processor; print('Media OK')"
```

---

## 🔍 Verify Installation

```bash
# ตรวจสอบ Python version
python --version

# ตรวจสอบว่าติดตั้ง packages ครบ
pip list

# รัน tests
python -m pytest tests/ -v

# ตรวจสอบ FFmpeg
ffmpeg -version

# ตรวจสอบ import หลัก
python -c "import discord; import google.genai; print('All good!')"
```

---

## ⚠️ Common Issues

### "ModuleNotFoundError: No module named 'xxx'"

```bash
# ลองติดตั้งใหม่
pip install -r requirements.txt --force-reinstall
```

### "FFmpeg not found"

- ตรวจสอบว่า FFmpeg อยู่ใน PATH
- Windows: เพิ่ม `C:\ffmpeg\bin` ใน System PATH

### "Voice connection failed"

```bash
# ติดตั้ง PyNaCl อีกครั้ง
pip install PyNaCl --force-reinstall
```

### "FAISS import error"

```bash
# Windows อาจต้องใช้ binary wheel
pip install faiss-cpu --only-binary :all:
```

### "aiohttp SSL error"

```bash
pip install certifi --upgrade
```

---

## 📝 Quick Reference

```bash
# Start bot
python bot.py

# Start in dev mode (hot reload)
python scripts/dev_watcher.py

# Run tests
python -m pytest tests/ -v

# Build dashboard (TypeScript + Rust + auto-rename to all 3 names)
cd native_dashboard && npm run release
```

---

## 📞 Support

- **GitHub Issues:** <https://github.com/voraehita25-star/discord-bot/issues>
- **Documentation:** See `docs/` folder

---

*Last Updated: May 2026 | Version: 3.4.1*
