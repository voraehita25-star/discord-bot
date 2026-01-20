# 📦 Installation Guide

คู่มือติดตั้ง Discord Bot ฉบับสมบูรณ์

---

## 📋 System Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| **OS** | Windows 10 / Ubuntu 20.04 | Windows 11 / Ubuntu 22.04 |
| **Python** | 3.10+ | 3.12+ |
| **RAM** | 2GB | 4GB |
| **Storage** | 500MB | 1GB |
| **FFmpeg** | Required for voice | Required |

---

## 🔧 Prerequisites

### 1. Python 3.10+

**Windows:**
```bash
# ดาวน์โหลดจาก https://python.org
# หรือใช้ winget
winget install Python.Python.3.12
```

**Linux:**
```bash
sudo apt update
sudo apt install python3.12 python3.12-venv python3-pip
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
| `GEMINI_API_KEY` | ✅ | API Key จาก Google AI Studio |
| `CREATOR_ID` | ✅ | Discord User ID ของเจ้าของบอท |
| `SPOTIFY_CLIENT_ID` | ❌ | (Optional) Spotify API Client ID |
| `SPOTIFY_CLIENT_SECRET` | ❌ | (Optional) Spotify API Secret |
| `SENTRY_DSN` | ❌ | (Optional) Sentry Error Tracking |

### Step 5: (Optional) ตั้งค่า Persona

```bash
# คัดลอก example files
cp cogs/ai_core/data/faust_data_example.py cogs/ai_core/data/faust_data.py
cp cogs/ai_core/data/roleplay_data_example.py cogs/ai_core/data/roleplay_data.py
```

### Step 6: รันบอท!

```bash
python bot.py
```

---

## 📦 Dependencies Breakdown

### Core (จำเป็น)

| Package | Version | Purpose |
|---------|---------|---------|
| `discord.py[voice]` | 2.6.4 | Discord API + Voice Support |
| `python-dotenv` | 1.2.1 | อ่านค่าจาก .env |
| `aiohttp` | 3.13.2 | Async HTTP requests |
| `psutil` | 7.1.3 | System monitoring |

### AI (จำเป็น)

| Package | Version | Purpose |
|---------|---------|---------|
| `google-genai` | 1.56.0 | Gemini AI API |
| `Pillow` | 12.0.0 | Image processing |
| `beautifulsoup4` | 4.12.3 | HTML parsing (URL fetching) |
| `lxml` | 5.3.0 | Fast HTML parser |
| `numpy` | 2.2.6 | Numerical ops (RAG) |
| `faiss-cpu` | 1.13.2 | Vector search (RAG memory) |
| `imageio[ffmpeg]` | 2.37.0 | GIF to video conversion |

### Music (จำเป็นสำหรับ Music feature)

| Package | Version | Purpose |
|---------|---------|---------|
| `yt-dlp` | 2025.12.8 | YouTube download |
| `spotipy` | 2.25.2 | Spotify API |
| `PyNaCl` | 1.5.0 | Voice encryption |

### Database

| Package | Version | Purpose |
|---------|---------|---------|
| `aiosqlite` | 0.22.1 | Async SQLite |

### Development & Testing

| Package | Version | Purpose |
|---------|---------|---------|
| `pytest` | 9.0.2 | Testing framework |
| `pytest-asyncio` | 1.3.0 | Async test support |
| `watchdog` | 6.0.0 | Hot reload (dev mode) |
| `colorama` | 0.4.6 | Windows colors |

### Optional (Performance & Monitoring)

| Package | Version | Purpose |
|---------|---------|---------|
| `orjson` | 3.10.14 | 10x faster JSON |
| `uvloop` | 0.21.0 | Faster event loop (Unix only) |
| `sentry-sdk` | 2.49.0 | Error tracking |

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

2. **Tauri CLI:**
```bash
cargo install tauri-cli
```

3. **WebView2 (Windows only):**
   - Windows 10+ มีติดตั้งมาแล้วปกติ
   - ถ้าไม่มี: https://developer.microsoft.com/en-us/microsoft-edge/webview2/

### Build Dashboard

```bash
cd native_dashboard
cargo build --release
```

### Run Dashboard

```bash
./target/release/bot-dashboard.exe  # Windows
./target/release/bot-dashboard      # Linux
```

---

## 🦀 Rust Extensions (Optional)

High-performance native extensions สำหรับ RAG และ Media processing

> **Pre-built Status:** ✅ พร้อมใช้งาน (January 20, 2026)  
> **Files:** `rag_engine.pyd`, `media_processor.pyd`

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

# Build dashboard
cd native_dashboard && cargo build --release
```

---

## 📞 Support

- **GitHub Issues:** https://github.com/voraehita25-star/discord-bot/issues
- **Documentation:** See `docs/` folder

---

*Last Updated: January 2026 | Version: 3.3.0*
