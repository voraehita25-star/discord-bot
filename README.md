# 🤖 Discord AI Bot

[![CI](https://github.com/voraehita25-star/discord-bot/actions/workflows/ci.yml/badge.svg)](https://github.com/voraehita25-star/discord-bot/actions/workflows/ci.yml)

> ⚠️ **Fair Warning:** Most of the documentation and comments are in Thai (ภาษาไทย). Will I translate it to English? *Absolutely not.* Learn Thai or use Google Translate. Good luck! 🇹🇭✨

> 🧩 **Another Fair Warning:** This codebase is NOT 100% complete. Some pieces are missing like a puzzle from your childhood that the dog ate. Various files were yeeted into the void for *✨privacy reasons✨*. Can you still use it? Sure! Will it work out of the box? *LOL no.* You'll need to fill in the gaps, fix some paths, and maybe sacrifice a rubber duck to the debugging gods. Consider this a *"some assembly required"* situation. You've been warned! 🔧💀

Production-ready Discord bot with Gemini AI chat, music player, and advanced memory system.

## ✨ Features

| Feature | Description |
|---------|-------------|
| 🤖 **AI Chat** | Gemini 3 Pro powered conversations with context memory |
| 🎵 **Music** | YouTube/Spotify playback with queue management |
| 🧠 **Long-term Memory** | RAG-based memory using FAISS for persistent context |
| 🎤 **Voice Recognition** | Whisper-based speech-to-text for voice commands |
| 📊 **Monitoring** | Built-in health API, token tracking, and metrics |
| 🛡️ **Reliability** | Circuit breaker, rate limiting, and auto-recovery |
| 🖥️ **Dashboard** | Native Tauri desktop dashboard for bot management |

## 🚀 Quick Start

### Prerequisites
- Python 3.11+
- Discord Bot Token
- Google Gemini API Key

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/voraehita25-star/discord-bot.git
cd discord-bot

# 2. Create virtual environment
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Linux/Mac

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp env.example .env
# Edit .env with your tokens

# 5. Run the bot
python bot.py
```

## 🔑 Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DISCORD_TOKEN` | ✅ | Discord bot token |
| `GEMINI_API_KEY` | ✅ | Google Gemini API key |
| `CREATOR_ID` | ✅ | Your Discord user ID |
| `SPOTIFY_CLIENT_ID` | ❌ | Spotify API client ID |
| `SPOTIFY_CLIENT_SECRET` | ❌ | Spotify API secret |
| `SENTRY_DSN` | ❌ | Sentry error tracking |

## 📂 Project Structure

```
discord-bot/
├── bot.py              # Entry point
├── config.py           # Configuration
├── cogs/               # Discord extensions
│   ├── ai_core/        # AI chat system
│   │   ├── ai_cog.py       # Main AI cog
│   │   ├── logic.py        # Core AI logic
│   │   ├── memory/         # Memory systems
│   │   └── tools/          # AI tools
│   ├── music.py        # Music player
│   └── spotify_handler.py
├── utils/              # Utilities
│   ├── database/       # Database handlers
│   ├── monitoring/     # Logging & metrics
│   └── reliability/    # Circuit breaker, rate limiter
├── native_dashboard/   # Tauri desktop app
├── tests/              # Test suite (204 tests)
└── scripts/            # Maintenance & startup scripts
```

## 🧪 Testing

```bash
# Run all tests
python -m pytest tests/ -v

# Run with coverage
python -m pytest tests/ --cov=. --cov-report=html

# Run specific test file
python -m pytest tests/test_ai_core.py -v
```

## 🛠️ Development

```bash
# Hot-reload development mode
python scripts/dev_watcher.py

# Run linter
ruff check .

# Auto-fix lint issues
ruff check . --fix
```

## 📊 Monitoring

The bot includes built-in monitoring capabilities:

- **Health API** - HTTP endpoint for health checks (`/health`)
- **Token Tracking** - Per-user/channel token usage metrics
- **Performance Metrics** - Response times with percentiles
- **Sentry Integration** - Error tracking (optional)

## 🖥️ Native Dashboard

A Tauri-based desktop application for managing the bot:

```bash
cd native_dashboard
cargo tauri dev  # Development
cargo tauri build  # Production build
```

## 📖 Documentation

See **[DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md)** for detailed documentation including:
- Architecture overview
- AI system design
- Memory system internals
- Contributing guidelines

## 📜 License

This project is private. All rights reserved.

---

**Version:** See `version.txt` | **Python:** 3.11+ | **Tests:** 204 passing ✅
