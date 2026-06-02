# 🤖 Discord AI Bot

[![CI](https://github.com/voraehita25-star/discord-bot/actions/workflows/ci.yml/badge.svg)](https://github.com/voraehita25-star/discord-bot/actions/workflows/ci.yml)

> ⚠️ **Fair Warning:** Most of the documentation and comments are in Thai (ภาษาไทย). Will I translate it to English? *Absolutely not.* Learn Thai or use Google Translate. Good luck! 🇹🇭✨
>
> 🧩 **Another Fair Warning:** This codebase is NOT 100% complete. Some pieces are missing like a puzzle from your childhood that the dog ate. Various files were yeeted into the void for *✨privacy reasons✨*. Can you still use it? Sure! Will it work out of the box? *LOL no.* You'll need to fill in the gaps, fix some paths, and maybe sacrifice a rubber duck to the debugging gods. Consider this a *"some assembly required"* situation. You've been warned! 🔧💀

Production-ready Discord bot with Claude AI chat, music player, and advanced memory system.

## ✨ Features

| Feature | Description |
| ------- | ----------- |
| 🤖 **AI Chat** | Claude (claude-opus-4-8, 1M context, Max thinking) powered conversations with memory + Anthropic prompt caching for ~70-90% input-cost savings on long conversations |
| 🎵 **Music** | YouTube/Spotify playback with queue management |
| 🧠 **Long-term Memory** | RAG-based memory using FAISS for persistent context |
| 📎 **Document Attachments (Dashboard)** | Drag-drop PDF / DOCX / text / code (20+ types, 32 MB cap). Extracted text persists in SQLite per-conversation — no need to re-upload RP material |
| 🔗 **URL Reading** | Auto-fetch and summarize web pages & GitHub repos |
| 📊 **Monitoring** | Built-in health API, token tracking, and metrics |
| 🛡️ **Reliability** | Circuit breaker, rate limiting, auto-recovery, graceful shutdown, memory management |
| 🖥️ **Dashboard** | Native Tauri desktop app — 3D UI polish, PDF attach, persistent doc memory, file editor |
| 🦀 **Native Extensions** | Optional Rust (RAG, media) & Go (URL fetch, metrics) for 5-25x speedup |

## 🚀 Quick Start

### Prerequisites

**Required:**

- Python 3.14+
- Discord Bot Token
- Anthropic API Key (Claude is the primary AI backend)

**Optional:**

- Google Gemini API Key (for embeddings / RAG)
- Spotify Client ID + Secret (for `!play` Spotify links)

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

# 5. (Optional) Customize persona - the bot works without this!
# Copy example files and edit them:
# cp cogs/ai_core/data/faust_data_example.py cogs/ai_core/data/faust_data.py
# cp cogs/ai_core/data/roleplay_data_example.py cogs/ai_core/data/roleplay_data.py

# 6. Run the bot
python bot.py
```

## 🔑 Environment Variables

| Variable | Required | Description |
| -------- | -------- | ----------- |
| `DISCORD_TOKEN` | ✅ | Discord bot token |
| `ANTHROPIC_API_KEY` | ⚠️ | Anthropic API key. Only required when `CLAUDE_BACKEND=api`. The default `cli` mode reads credentials from your Claude Code login instead. |
| `CLAUDE_BACKEND` | ❌ | Claude backend mode: `cli` (default — spawn `claude -p`, uses your Claude Code Max subscription quota, no per-token charge) or `api` (anthropic SDK + per-token billing). Discord AI replies + dashboard chat work in **both** modes; `api` additionally enables the memory consolidator + history summarizer (both disabled under `cli`). |
| `CLAUDE_CODE_OAUTH_TOKEN` | ❌ | Only needed for `CLAUDE_BACKEND=cli` when the bot runs as a different OS user than the one logged into Claude Code. Generate with `claude setup-token`. |
| `GEMINI_API_KEY` | ❌ | Google Gemini API key for embeddings/RAG (only used when `CLAUDE_BACKEND=api`). |
| `RAG_ALLOW_LEGACY_PICKLE` | ❌ | Opt-in flag to load pre-v3.3 FAISS `.npy` (pickle) sidecar files. Off by default — pickle deserialization is an RCE sink. Only enable when migrating a trusted old deployment. |
| `BOT_MEMORY_WARNING_MB` | ❌ | Soft memory threshold in MiB (default: 1024). Tune per-host. |
| `BOT_MEMORY_CRITICAL_MB` | ❌ | Hard memory threshold in MiB (default: 1536). |
| `CREATOR_ID` | ✅ | Your Discord user ID |
| `SPOTIPY_CLIENT_ID` | ❌ | Spotify API client ID |
| `SPOTIPY_CLIENT_SECRET` | ❌ | Spotify API secret |
| `SENTRY_DSN` | ❌ | Sentry error tracking |
| `DASHBOARD_WS_TOKEN` | ❌ | Auth token for WebSocket dashboard |
| `DASHBOARD_ALLOW_UNRESTRICTED` | ❌ | Enable unrestricted mode in dashboard (`1`/`true`) |
| `HEALTH_API_HOST` | ❌ | Bind address for Health API (default: `127.0.0.1`) |
| `HEALTH_API_TOKEN` | ❌ | Bearer token for protected Health API endpoints |

## 📂 Project Structure

```text
discord-bot/
├── bot.py              # Entry point
├── config.py           # Configuration
├── cogs/               # Discord extensions
│   ├── ai_core/        # AI chat system (reorganized v3.3.7, deeper subdir split v3.3.8)
│   │   ├── ai_cog.py       # Main AI cog
│   │   ├── logic.py        # Core AI logic
│   │   ├── api/            # 🔌 AI API integration (Claude + Gemini embeddings)
│   │   ├── core/           # 🏗️ Performance, queue, context
│   │   ├── response/       # 📤 Response handling & webhooks
│   │   ├── commands/       # 🔧 Debug, memory, server commands
│   │   ├── tools/          # ⚡ AI function calling
│   │   ├── memory/         # 🧠 Memory systems (incl. Rust RAG)
│   │   ├── processing/     # 🔄 Guardrails, intent detection
│   │   ├── cache/          # 📊 Caching & analytics
│   │   └── data/           # Prompts & constants
│   ├── music/          # Music player module
│   └── spotify_handler.py
├── utils/              # Utilities
│   ├── database/       # Database handlers
│   ├── media/          # Media processing (Rust backend)
│   ├── monitoring/     # Logging, metrics & Go Health API
│   ├── reliability/    # Circuit breaker, rate limiter
│   └── web/            # URL fetcher (Go backend)
├── rust_extensions/    # 🦀 High-performance Rust modules
│   ├── rag_engine/     # SIMD vector similarity search
│   └── media_processor/# Fast image processing
├── go_services/        # 🐹 Go microservices
│   ├── url_fetcher/    # Concurrent URL fetching (port 8081)
│   └── health_api/     # Prometheus metrics (port 8082)
├── native_dashboard/   # Tauri desktop app
├── docs/               # Documentation
│   ├── reviews/        # Code review reports
│   └── release-notes/  # Version release notes
├── tests/              # Python suite (3,143 pytest); native_dashboard/tests-e2e/ for Playwright (8 spec files: e2e + a11y + visual)
└── scripts/            # Build & maintenance scripts
```

## 🧪 Testing

```powershell
# Recommended: use the test runner script (no hanging, clean output)
.\scripts\run_tests.ps1              # Run all tests
.\scripts\run_tests.ps1 -Fast        # Skip slow tests (~8.5s)
.\scripts\run_tests.ps1 database     # Run tests matching "database"
.\scripts\run_tests.ps1 -File test_ai_core.py
.\scripts\run_tests.ps1 -Coverage    # With coverage report

# Or use pytest directly
python -m pytest tests/ -v
python -m pytest tests/ --cov=cogs --cov=utils --cov-report=html
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
- **Structured Logging** - JSON-formatted logs for ELK/monitoring
- **Sentry Integration** - Error tracking (optional)
- **Go Health Service** - Prometheus-compatible metrics (localhost-only by default)
- **Memory Management** - TTL caches, WeakRef caching, memory monitoring
- **Graceful Shutdown** - Coordinated cleanup with signal handling
- **SSRF Protection** - DNS rebinding protection with IPv6 coverage in Go services
- **Permission Allowlists** - AI server commands restricted to safe permissions only
- **Mention Sanitization** - Webhook/tool messages sanitize role & user mentions
- **AllowedMentions** - Bot-level `@everyone`/`@here` mention blocking
- **Sensitive Data Filter** - Regex-based token/API key redaction in logs
- **Path Traversal Protection** - `safe_delete()` validates within `temp/` directory

## 🦀 Native Extensions (Optional)

High-performance extensions for CPU/IO-intensive operations. **Fully optional** - bot works without them using Python fallbacks.

> **Build Status:** ✅ Rust extensions pre-built (April 2, 2026)
> **Files:** `cogs/ai_core/memory/rag_engine.pyd` (~653 KB), `utils/media/media_processor.pyd` (~1.6 MB)
> Source lives under `rust_extensions/`; the compiled `.pyd` files are copied next to their Python wrappers.

### Rust Extensions

| Component           | Speedup | Features                                |
| ------------------- | ------- | --------------------------------------- |
| **RAG Engine**      | 10-25x  | SIMD cosine similarity, parallel search |
| **Media Processor** | 5-6x    | Lanczos resize, GIF detection           |

### Go Microservices

| Service          | Port | Features                           |
| ---------------- | ---- | ---------------------------------- |
| **URL Fetcher**  | 8081 | Concurrent fetching, rate limiting |
| **Health API**   | 8082 | Prometheus metrics, K8s probes     |

### Building Native Extensions

```powershell
# Prerequisites: Rust 1.75+, Go 1.25+

# Build everything
.\scripts\build_all.ps1 -Release

# Or separately
.\scripts\build_rust.ps1 -Release
.\scripts\build_go.ps1 -Release -Run
```

See [rust_extensions/README.md](rust_extensions/README.md) and [go_services/README.md](go_services/README.md) for details.

## 🖥️ Native Dashboard (디스코드 봇 대시보드)

A Tauri-based desktop application for managing the bot with Korean UI support.

### Features

- 💬 **AI Chat** — WebSocket streaming (Gemini + Claude). Claude runs via SDK or `claude -p` subprocess (Max subscription). 1M-token context active by default on CLI backend. 200K chars/message cap.
- 📎 **Document Attachments** — Drag-drop PDF, DOCX, or any text/code file (20+ types). 32 MB per file, 5 per message. Claude reads PDFs natively (text + embedded images).
- 📂 **Persistent Document Memory** — Extracted text saved to SQLite per-conversation; auto-injected into every AI turn so you don't re-upload RP material.
- ✏️ **File Editor** — 📎 button in chat header shows per-conversation file list. Inline editor for filename + text content, with Ctrl+S save + delete.
- 🎨 **3D UI Polish** — Layered shadows, cursor-tracking tilt, ripple clicks, glassmorphism noise, custom scrollbars, skeleton loaders, number count-up, chart entrance.
- 🌸 **Sakura Animation** — Cherry-blossom petals with mouse parallax (toggleable).
- 🔊 **Sound + Haptic** — Optional synth click + vibration on button press (off by default).
- 🌙 **Dark / Light Theme** — Pink/purple anime palette with localStorage persistence.
- 📈 **Real-time Performance Charts** — Memory & message count graphs.
- 🔔 **Toast Notifications** — Animated slide-in confirmations / errors.
- ⌨️ **Keyboard Shortcuts** — Ctrl+1-5 nav, Ctrl+R refresh, Ctrl+T theme, Ctrl+Enter send, Ctrl+S save-in-editor, Ctrl+F search-in-chat.

### Quick Start

```bash
cd native_dashboard
npm install          # First time
npm run release      # Build + auto-rename to Korean
```

### Output Files

```text
target/release/bot-dashboard.exe
target/release/Discord Bot Dashboard.exe
target/release/디스코드 봇 대시보드.exe
target/release/bundle/nsis/디스코드 봇 대시보드_2.0.0_x64-setup.exe
```

See [native_dashboard/README.md](native_dashboard/README.md) for details.

## 🎭 Customization

The bot includes example persona files that work out of the box. To customize:

### AI Persona

```bash
# Copy the example and customize
cp cogs/ai_core/data/faust_data_example.py cogs/ai_core/data/faust_data.py
```

Edit `faust_data.py` to change:

- `FAUST_INSTRUCTION` - Main personality/behavior
- `FAUST_SANDBOX` - Unrestricted mode behavior
- `ESCALATION_FRAMINGS` - Fallback prompts

### Roleplay System

```bash
cp cogs/ai_core/data/roleplay_data_example.py cogs/ai_core/data/roleplay_data.py
```

Edit `roleplay_data.py` to add:

- `WORLD_LORE` - Your RP universe/setting
- `SERVER_CHARACTERS` - Character definitions
- `SERVER_AVATARS` - Webhook avatar mappings

### Character Images

Create `assets/RP/` and `assets/RP/AVATARS/` folders with character images for RP webhooks.

## 📖 Documentation

See **[DEVELOPER_GUIDE.md](docs/DEVELOPER_GUIDE.md)** for detailed documentation including:

- Architecture overview
- AI system design
- Memory system internals
- Contributing guidelines

## 📜 License

This project is private. All rights reserved.

---

## 👤 Creator

| | |
| --- | --- |
| 💬 **Discord** | `@me_no_you` |
| 🐙 **GitHub** | [@voraehita25-star](https://github.com/voraehita25-star) |

> 📬 *Feel free to DM me on Discord for questions or help with this bot! There's a solid 19.99% chance I'll actually respond. The other 80.01%? I'm either sleeping, gaming, or pretending I didn't see it. Good luck!* 🎲

---

**Version:** 3.4.2 | **Python:** 3.14+ | **Tests:** 3,143 pytest ✅ + 190 vitest ✅ + 70 Playwright ✅ (e2e + axe a11y + visual regression) | **Native Extensions:** Rust + Go | **Dashboard:** document attach + persistent per-conversation doc memory + file editor + 3D UI polish | **Last Update:** June 2, 2026
