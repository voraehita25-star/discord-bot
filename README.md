# 🤖 Discord AI Bot

Production-ready Discord bot with Gemini AI chat and music player.

## ✨ Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure environment
cp env.example .env
# Edit .env with your tokens

# 3. Run the bot
python bot.py
```

## 🔑 Required Environment Variables

| Variable | Description |
|----------|-------------|
| `DISCORD_TOKEN` | Discord bot token |
| `GEMINI_API_KEY` | Google Gemini API key |
| `CREATOR_ID` | Your Discord user ID |

## 📋 Features

- **🤖 AI Chat** - Gemini-powered conversations with context memory
- **🎵 Music** - YouTube/Spotify playback with queue management
- **🧠 Memory** - Long-term memory via RAG (FAISS)
- **🛡️ Reliability** - Circuit breaker, rate limiting, auto-recovery

## 📂 Project Structure

```
bot.py          # Entry point
config.py       # Configuration
cogs/           # Discord extensions
├── ai_core/    # AI chat system
└── music.py    # Music player
utils/          # Utilities
tests/          # Test suite (177 tests)
```

## 🧪 Testing

```bash
python -m pytest tests/ -v
```

## 📖 Documentation

See **[DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md)** for detailed documentation.

## 📊 Monitoring

The bot includes built-in monitoring:

- **Health API** - HTTP endpoint for health checks
- **Token Tracking** - Per-user/channel token usage
- **Performance Metrics** - Response times with percentiles
- **Sentry Integration** - Error tracking (optional)

## 🛠️ Development

```bash
# Hot-reload development
python scripts/dev_watcher.py

# Run linter
ruff check .

# Run tests
python -m pytest tests/ -q
```

---

**Version:** See `version.txt` | **Python:** 3.11+ | **Tests:** 177 passing ✅
