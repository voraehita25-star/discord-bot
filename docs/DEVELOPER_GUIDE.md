# 🤖 Discord AI Bot - Project Documentation

> **Last Updated:** June 15, 2026
> **Version:** 3.4.14
> **Python Version:** 3.14+
> **Framework:** discord.py 2.x
> **Total Files:** 126 Python test files (5,418 tests) + 19 vitest files (467 frontend tests) + 9 Playwright spec files (90 e2e + a11y + visual regression tests)
> **Native Extensions:** Rust (RAG, Media) + Go (URL Fetcher, Health API)
> **Code Quality:** All imports verified ✅ | All tests passing ✅ | Full-project audit complete ✅ | Memory & Shutdown managers ✅ | Security hardening ✅ | Test suite consolidated ✅ | Dead code removed ✅ | CSP hardened ✅ | Anthropic prompt caching ✅ | chat-manager.ts split into 11 focused modules under `src-ts/chat/` ✅ | Headless Playwright + axe-core a11y + visual regression in CI ✅

---

## 📋 Overview

Discord Bot ที่รวม AI Chat (Claude เป็นหลัก + Gemini สำหรับ embeddings/RAG) และ Music Player ไว้ด้วยกัน มีระบบ Memory ระดับ Enterprise และ Reliability Patterns ครบครัน

### Key Features

- **AI Chat** - Claude (opus-4-8, 1M context, Max thinking) เป็นโมเดลหลัก พร้อม Anthropic prompt caching (hybrid: explicit system + automatic history) ลดต้นทุน input ราว 70-90%; Gemini ใช้ทำ embeddings/RAG
- **Music Player** - YouTube/Spotify support with queue, loop, and premium UI
- **Multi-Character Roleplay** - Character state tracking และ entity memory
- **Unrestricted Mode** - Creative writing mode สำหรับ channels ที่เลือก
- **Enterprise Reliability** - Circuit breaker, rate limiting, self-healer

---

## 📁 Directory Structure (269 Python Files)

```text
BOT/
├── bot.py                    # 🚀 Main entry point
├── config.py                 # ⚙️ Centralized configuration
├── requirements.txt          # 📦 Dependencies
│
├── cogs/                     # 🔌 Discord Cogs (Extensions)
│   ├── __init__.py
│   ├── spotify_handler.py    # Spotify integration
│   │
│   ├── music/                # 🎵 Music Module
│   │   ├── __init__.py
│   │   ├── cog.py            # Music player cog
│   │   ├── queue.py          # Queue management
│   │   ├── utils.py          # Colors, emojis, formatting
│   │   └── views.py          # Discord UI components
│   │
│   └── ai_core/              # 🧠 AI Core Module (Reorganized v3.3.8)
│       ├── __init__.py
│       ├── ai_cog.py         # ⭐ Main AI cog (commands & events)
│       ├── logic.py          # ⭐ ChatManager - core AI logic
│       ├── storage.py        # History persistence (SQLite)
│       ├── sanitization.py   # 🛡️ Input sanitization
│       ├── emoji.py          # Discord emoji processing
│       ├── voice.py          # Voice channel management
│       ├── fallback_responses.py  # Fallback when AI fails
│       ├── session_mixin.py  # Session management mixin
│       ├── media_processor.py # Media processing
│       ├── claude_payloads.py # Typed Claude message builders + prompt-cache helpers
│       ├── imports.py        # Centralised optional-dependency imports
│       │
│       ├── api/              # 🔌 AI API Integration (Claude primary + Gemini embeddings) + dashboard backend
│       │   ├── __init__.py
│       │   ├── api_handler.py          # Claude API calls (anthropic SDK), streaming, retry
│       │   ├── api_failover.py         # Direct + proxy failover for Claude
│       │   ├── ws_dashboard.py         # Dashboard WebSocket server (auth, origin check)
│       │   ├── dashboard_chat.py       # Gemini-backed dashboard chat
│       │   ├── dashboard_chat_claude.py     # Claude streaming chat + edit via anthropic SDK (per-token billing)
│       │   ├── dashboard_chat_claude_cli.py # Claude streaming chat + edit via `claude -p` subprocess (Max subscription). Toggle with CLAUDE_BACKEND=cli
│       │   ├── discord_chat_claude_cli.py   # Discord-side Claude CLI backend (delta-on-resume sessions, over-limit owner buttons)
│       │   ├── chat_manager_registry.py     # Weakref registry — dashboard handlers sync the live ChatManager
│       │   ├── cli_write_guard.py      # Fail-closed PreToolUse hook confining CLI file writes
│       │   ├── ai_tools_ipc.py         # Localhost IPC executing CLI tool calls in the bot process
│       │   ├── mcp_tools_server.py     # Stdio MCP proxy spawned by `claude -p` → ai_tools_ipc
│       │   ├── dashboard_common.py     # Shared helpers (timestamps, persona+context builder, memory cache)
│       │   ├── dashboard_config.py     # Dashboard env config
│       │   ├── dashboard_handlers.py   # Conversation CRUD with invalidate_user_context_cache hooks + AI-history browse/edit/delete/restore handlers
│       │   └── document_extractor.py   # PDF/DOCX/text extraction → dashboard_document_memories
│       │
│       ├── core/             # 🏗️ Core Components
│       │   ├── __init__.py
│       │   ├── performance.py # 📊 Performance tracking
│       │   └── message_queue.py # 📬 Message queue
│       │
│       ├── response/         # 📤 Response Handling
│       │   ├── __init__.py
│       │   ├── response_mixin.py  # Response processing mixin
│       │   └── webhook_cache.py   # Webhook caching
│       │
│       ├── commands/         # 🔧 Command Modules
│       │   ├── __init__.py
│       │   ├── debug_commands.py  # Debug/admin commands
│       │   ├── memory_commands.py # User memory commands
│       │   └── server_commands.py # Server management
│       │
│       ├── tools/            # ⚡ AI Function Calling
│       │   ├── __init__.py
│       │   ├── tools.py      # Facade module
│       │   ├── tool_definitions.py # AI tool/function-calling definitions
│       │   └── tool_executor.py   # Tool execution
│       │
│       ├── data/             # Static data & prompts
│       │   ├── __init__.py   # Auto-fallback to example files
│       │   ├── constants.py  # ⚙️ Config constants (from env)
│       │   ├── faust_data_example.py    # 📝 Example persona template
│       │   ├── faust_data.py            # Your custom persona (gitignored)
│       │   ├── roleplay_data_example.py # 📝 Example RP template
│       │   └── roleplay_data.py         # Your custom RP data (gitignored)
│       │
│       ├── memory/           # 🧠 Memory Systems
│       │   ├── __init__.py
│       │   ├── rag.py        # FAISS-based RAG system
│       │   ├── rag_rust.py   # 🦀 Rust RAG wrapper
│       │   ├── history_manager.py # Smart history trimming
│       │   ├── summarizer.py # Conversation summarization
│       │   ├── entity_memory.py # Character/entity facts
│       │   ├── long_term_memory.py # Permanent user facts
│       │   ├── memory_consolidator.py # Memory consolidation
│       │   ├── state_tracker.py # RP character states
│       │   └── consolidator.py # Fact extraction from history
│       │
│       ├── processing/       # 🔄 Request Processing
│       │   ├── __init__.py
│       │   ├── unrestricted.py # Per-channel unrestricted-mode registry (persona injection)
│       │   └── intent_detector.py # Message intent classification
│       │
│       └── cache/            # 📊 Caching & Analytics
│           ├── __init__.py
│           ├── ai_cache.py   # LRU response cache
│           ├── analytics.py  # Usage metrics & logging
│           └── token_tracker.py # Token usage tracking
│
├── utils/                    # 🛠️ Utilities
│   ├── __init__.py           # Re-exports for backward compat
│   ├── localization.py       # Thai/English messages
│   │
│   ├── database/
│   │   ├── __init__.py
│   │   └── database.py       # Async SQLite (aiosqlite)
│   │
│   ├── media/
│   │   ├── __init__.py
│   │   ├── colors.py         # Color constants
│   │   └── ytdl_source.py    # YouTube-DL audio source
│   │
│   ├── reliability/          # 🛡️ Reliability Patterns
│   │   ├── __init__.py
│   │   ├── circuit_breaker.py # API failure protection
│   │   ├── rate_limiter.py   # Token bucket rate limiting
│   │   ├── self_healer.py    # Auto-recovery from issues
│   │   ├── memory_manager.py # 🆕 Memory leak prevention
│   │   └── shutdown_manager.py # 🆕 Graceful shutdown
│   │
│   ├── monitoring/           # 📈 Monitoring & Metrics
│   │   ├── __init__.py
│   │   ├── health_api.py     # HTTP health check API
│   │   ├── logger.py         # Smart logging system
│   │   ├── metrics.py        # Performance metrics
│   │   ├── performance_tracker.py # Response time tracking with percentiles
│   │   ├── structured_logger.py # 🆕 JSON logging with context tracking
│   │   ├── sentry_integration.py # Sentry error tracking
│   │   ├── token_tracker.py  # API token tracking
│   │   ├── audit_log.py      # Audit logging
│   │   └── feedback.py       # User feedback collection
│   │
│   └── web/                  # 🔗 Web Utilities
│       ├── __init__.py
│       └── url_fetcher.py    # URL content extraction
│
├── scripts/                  # 🔧 Management Scripts
│   ├── __init__.py
│   ├── bot_manager.py        # CLI: start/stop/restart bot
│   ├── dev_watcher.py        # Hot-reload development
│   ├── load_test.py          # Load testing
│   ├── verify_system.py      # System verification
│   ├── test_bot_manager.py   # Bot manager tests
│   │
│   ├── maintenance/          # 🔧 Database Maintenance
│   │   ├── add_local_id.py   # Add local IDs to DB
│   │   ├── check_db.py       # Database health check
│   │   ├── clean_history.py  # Clean old history
│   │   ├── find_unused.py    # Find unused code
│   │   ├── migrate_to_db.py  # JSON → SQLite migration
│   │   ├── reindex_db.py     # Reindex database
│   │   └── view_db.py        # View DB contents
│   │
│   └── startup/              # 🚀 Startup Scripts
│       ├── start.ps1         # PowerShell launcher
│       ├── start.bat         # Batch launcher
│       └── manager.ps1       # PowerShell manager
│
├── tests/                    # 🧪 Python test suite (5,418 tests in 126 files)
│   ├── __init__.py
│   ├── conftest.py           # Pytest fixtures
│   ├── test_boilerplate.py   # Parametrized structural tests
│   ├── test_ai_core.py       # AI core tests
│   ├── test_ai_integration.py # AI integration tests
│   ├── test_circuit_breaker.py
│   ├── test_consolidator.py  # Memory consolidator
│   ├── test_content_processor.py
│   ├── test_dashboard_handlers.py # Dashboard handler tests (48 tests)
│   ├── test_dashboard_ai_history.py # AI-history WS handler tests (225 tests)
│   ├── test_database.py
│   ├── test_emoji_voice.py
│   ├── test_error_recovery.py
│   ├── test_fast_json.py     # 🆕 Fast JSON utilities tests
│   ├── test_unrestricted.py  # Unrestricted-mode registry tests
│   ├── test_memory_manager.py # 🆕 TTL/WeakRef cache tests
│   ├── test_memory_modules.py
│   ├── test_music_integration.py
│   ├── test_music_queue.py   # 🆕 QueueManager tests
│   ├── test_performance_tracker.py
│   ├── test_rate_limiter.py
│   ├── test_shutdown_manager.py # 🆕 Graceful shutdown tests
│   ├── test_spotify_handler.py # 🆕 SpotifyHandler tests
│   ├── test_spotify_integration.py
│   ├── test_structured_logger.py # 🆕 Structured logging tests
│   ├── test_summarizer.py
│   ├── test_tools.py
│   └── test_webhooks.py
│
├── docs/                     # 📚 Documentation
│   ├── DEVELOPER_GUIDE.md    # This guide
│   ├── ARCHITECTURE.md       # Architecture overview
│   ├── DATABASE_SCHEMA.md / SCHEMA.md  # DB schema reference
│   ├── INSTALL.md / TESTING.md / TROUBLESHOOTING.md / OWNER_COMMANDS.md / SENTRY.md
│   └── CODE_AUDIT_GUIDE.md   # Code audit checklist
│
├── native_dashboard/         # 🖥️ Tauri Desktop Dashboard v2.0
│   ├── Cargo.toml            # Rust dependencies
│   ├── tauri.conf.json       # Tauri configuration
│   ├── package.json          # npm dependencies (v2.0.0)
│   ├── tsconfig.json         # TypeScript config
│   ├── vitest.config.ts      # Test configuration
│   ├── README.md             # Dashboard documentation
│   ├── src/
│   │   ├── main.rs           # Tauri commands
│   │   ├── bot_manager.rs    # Bot process control
│   │   └── database.rs       # SQLite queries
│   ├── src-ts/
│   │   ├── app.ts            # Status/logs/DB/settings UI (~1,900 lines)
│   │   ├── chat-manager.ts   # ChatManager orchestrator (~2,800 lines after 2026-04 split)
│   │   ├── history-manager.ts # AI History page (Ctrl+6) — browse/edit/delete/undo Discord ai_history
│   │   ├── shared.ts         # Shared utils (invoke wrapper, errors, settings, toasts)
│   │   ├── types.ts          # Shared TypeScript interfaces
│   │   ├── faust_avatar.ts   # Default AI avatar (base64)
│   │   ├── app.test.ts       # app.ts unit tests
│   │   ├── chat-manager.test.ts       # ChatManager dispatcher + state (64 tests)
│   │   ├── history-manager.test.ts    # AI History page (114 tests)
│   │   ├── e2e_smoke.test.ts          # Smoke-level end-to-end
│   │   └── chat/             # Chat modules extracted from chat-manager.ts
│   │       ├── types.ts, ws-client.ts, formatter.ts, message-template.ts,
│   │       ├── context-window.ts, conversation-list.ts, conversation-modals.ts,
│   │       ├── search.ts, prism.ts, image-attach.ts, document-attach.ts, export-picker.ts
│   │       └── *.test.ts     # 19 vitest files total (467 tests)
│   ├── tests-e2e/            # Playwright (Chromium) — headless against the static UI (90 tests, incl. the history page)
│   │   ├── _fixtures/mock-tauri.ts      # Tauri IPC shim + WS mock + page-error tracker
│   │   ├── dashboard-smoke.spec.ts      # 18 smoke tests covering UI fixes
│   │   ├── interactions.spec.ts         # 20 user-flow tests
│   │   ├── a11y.spec.ts                 # 14 axe-core audits
│   │   ├── visual-regression.spec.ts    # 9 baseline screenshots
│   │   ├── dashboard-inspection.spec.ts # 8 deep UI inspections
│   │   ├── h5-importmap.spec.ts         # 1 import-map IPC regression
│   │   ├── h7-csp.spec.ts               # 1 strict-CSP render regression
│   │   ├── upgrade-guards.spec.ts       # 8 upgrade-audit regression guards
│   │   └── screenshots.spec.ts          # 11 manual-inspection captures
│   ├── playwright.config.ts  # Playwright config (python http.server + Chromium)
│   ├── scripts/
│   │   ├── build-tauri.ps1   # Build + auto-rename
│   │   └── create_desktop_shortcut.py
│   ├── ui/
│   │   ├── index.html        # Dashboard UI (charts, sakura)
│   │   ├── styles.css        # Dark/Light theme
│   │   ├── app.js            # Compiled from src-ts/app.ts
│   │   ├── chat-manager.js   # Compiled from src-ts/chat-manager.ts
│   │   ├── shared.js         # Compiled from src-ts/shared.ts
│   │   └── chat/             # Compiled from src-ts/chat/*.ts
│   └── icons/
│       └── icon.ico          # App icon
│
├── rust_extensions/          # 🦀 Rust Native Extensions
│   ├── Cargo.toml            # Workspace config
│   ├── rag_engine/           # SIMD vector similarity
│   │   ├── src/lib.rs        # PyO3 bindings + in-memory store
│   │   └── src/cosine.rs     # SIMD cosine similarity
│   └── media_processor/      # Image processing
│       ├── src/lib.rs        # PyO3 bindings
│       ├── src/resize.rs     # Lanczos resizing
│       └── src/gif.rs        # GIF detection
│
├── go_services/              # 🐹 Go Microservices
│   ├── go.mod                # Go module
│   ├── url_fetcher/          # URL fetching service (port 8081)
│   │   └── main.go           # Rate limiting, HTML extraction
│   └── health_api/           # Health monitoring (port 8082)
│       └── main.go           # Prometheus metrics, health probes
│
└── data/                     # 💾 Runtime Data
    ├── bot_database.db       # SQLite database
    └── db_export/            # JSON exports for backup
```

---

## 🦀 Native Extensions

### Overview

Bot มี native extensions ที่เขียนด้วย **Rust** และ **Go** สำหรับ operations ที่ใช้ CPU/IO เยอะ
Extensions เหล่านี้เป็น **optional** - bot ทำงานได้ปกติด้วย Python fallback

> **Build Status:** ✅ Rust extensions built successfully (March 2, 2026)
> **Files:** `rag_engine.pyd` (651 KB), `media_processor.pyd` (1.7 MB)

### Rust Extensions (PyO3)

| Module | Location | Performance |
| --- | --- | --- |
| RAG Engine | `rust_extensions/rag_engine/` | 10-25x faster cosine similarity |
| Media Processor | `rust_extensions/media_processor/` | 5-6x faster image resize |

**Build Rust:**

```powershell
.\scripts\build_rust.ps1 -Release
```

### Go Microservices

| Service | Port | Features |
| --- | --- | --- |
| URL Fetcher | 8081 | Concurrent fetch, rate limit (50 req/s) |
| Health API | 8082 | Prometheus metrics, K8s probes |

**Build & Run Go:**

```powershell
.\scripts\build_go.ps1 -Release -Run
```

### Python Wrappers

Python wrappers จะ auto-detect และใช้ native extensions ถ้ามี:

```python
# RAG - uses Rust if available, else Python
from cogs.ai_core.memory.rag_rust import RagEngine

# Media - uses Rust if available, else PIL
from utils.media.media_rust import MediaProcessor

# URL Fetch - uses Go service if running, else aiohttp
from utils.web.url_fetcher_client import fetch_url

# Health - uses Go service if running
from utils.monitoring.health_client import push_request_metric
```

---

## 🏗️ Architecture

### Core Flow

```text
User Message
    │
    ▼
┌─────────────┐     ┌──────────────┐     ┌──────────────────┐
│  ai_cog.py  │────▶│  logic.py    │────▶│ Claude API       │
│  (Discord)  │     │ (Processing) │     │ (Anthropic SDK + │
│             │     │              │     │  failover proxy) │
└─────────────┘     └──────────────┘     └──────────────────┘
                           │
           ┌───────────────┼───────────────┐
           ▼               ▼               ▼
    ┌───────────┐   ┌───────────┐   ┌───────────┐
    │ rag.py    │   │ message_  │   │ storage.py│
    │ (Memory + │   │ queue.py  │   │ (Persist) │
    │  Gemini   │   │ (Per-chan │   │           │
    │ embeds)   │   │  locks)   │   │           │
    └───────────┘   └───────────┘   └───────────┘
```

> The bot's primary AI is Claude (Anthropic). Gemini is used for RAG embeddings only,
> not for chat completions. The default backend is the Claude CLI (`CLAUDE_BACKEND=cli`,
> `claude -p` subprocess, Max-subscription quota) for **both** Discord replies and dashboard
> chat — see `cogs/ai_core/api/discord_chat_claude_cli.py` / `dashboard_chat_claude_cli.py`.
> CLI turns resume the server-side session and send only the new message (delta-on-resume);
> full history is sent only on fresh sessions. The Anthropic SDK path above is the
> `CLAUDE_BACKEND=api` opt-in.

### Key Classes

| Class | File | Purpose |
| --- | --- | --- |
| `ChatManager` | `logic.py` | Main AI chat orchestration |
| `MemorySystem` | `rag.py` | FAISS-based long-term memory |
| `HistoryManager` | `history_manager.py` | Smart context trimming |
| `EntityMemoryManager` | `entity_memory.py` | Character facts storage |
| `Database` | `database.py` | Async SQLite singleton |
| `CircuitBreaker` | `circuit_breaker.py` | Thread-safe API failure protection |
| `RateLimiter` | `rate_limiter.py` | Thread-safe request throttling |
| `PerformanceTracker` | `performance_tracker.py` | Response time tracking with auto-cleanup |
| `TTLCache` | `memory_manager.py` | LRU cache with TTL expiration 🆕 |
| `WeakRefCache` | `memory_manager.py` | Auto-release cache using weak refs 🆕 |
| `MemoryMonitor` | `memory_manager.py` | Memory usage monitoring 🆕 |
| `ShutdownManager` | `shutdown_manager.py` | Graceful shutdown coordination 🆕 |
| `StructuredLogger` | `structured_logger.py` | JSON logging with context 🆕 |

---

## ⚙️ Configuration

### Environment Variables (.env)

See `env.example` for the full annotated reference. Minimum viable subset:

```env
# Discord
DISCORD_TOKEN=your_token
GUILD_ID_MAIN=123456789
GUILD_ID_RP=123456789

# Claude (CLI mode is the default — uses your Claude Code subscription;
# leave ANTHROPIC_API_KEY blank in this mode)
CLAUDE_BACKEND=cli
# ANTHROPIC_API_KEY=sk-ant-...   # only when CLAUDE_BACKEND=api

# Gemini (Optional — used for semantic RAG embeddings on ANY backend,
#  incl. the default cli, whenever GEMINI_API_KEY is set; toggle with RAG_EMBEDDINGS=auto|off)
# GEMINI_API_KEY=your_api_key

# Spotify (Optional)
SPOTIPY_CLIENT_ID=your_client_id
SPOTIPY_CLIENT_SECRET=your_client_secret

# Owner
CREATOR_ID=your_discord_id
```

### constants.py

ไฟล์ `cogs/ai_core/data/constants.py` เก็บ config ที่ load จาก environment และค่าคงที่:

**Environment-based:**

- `GUILD_ID_*` - Server IDs
- `CHANNEL_ID_*` - Channel IDs
- `ANTHROPIC_API_KEY` / `CLAUDE_BACKEND` - Claude credentials (see env.example)
- `GEMINI_API_KEY` - Gemini key for RAG embeddings (works on any `CLAUDE_BACKEND` when set; toggle via `RAG_EMBEDDINGS=auto|off`)
- `GAME_SEARCH_KEYWORDS` - Keywords ที่ force search

**Processing Limits:**

| Constant | Default | Description |
| --- | --- | --- |
| `HISTORY_LIMIT_DEFAULT` | 1500 | Max stored history **messages** per channel for kept context |
| `HISTORY_LIMIT_MAIN` | 8000 | Main server (higher traffic) — max stored messages |
| `HISTORY_LIMIT_RP` | 30000 | Roleplay server (critical for continuity) — max stored messages |
| `LOCK_TIMEOUT` | 180s | Max wait for per-channel lock acquisition (`constants.py`; must exceed `API_TIMEOUT`) |
| `API_TIMEOUT` | 120s | Max wait for the upstream chat API (Claude) |
| `STREAMING_TIMEOUT_INITIAL` | 120s | Initial chunk timeout |
| `MAX_HISTORY_ITEMS` | 8000 | Max items in in-memory chat history (env-overridable via `MAX_HISTORY_ITEMS`) |
| `PERFORMANCE_SAMPLES_MAX` | 100 | Max samples per metric |

> History/metadata cache lives in `cogs/ai_core/storage.py` (not `constants.py`). Defaults:
> `MAX_CACHE_SIZE = 2000` (channels) and `CACHE_TTL = 900` seconds.

### Persona & Roleplay Files

Bot จะ auto-fallback ไปใช้ `*_example.py` ถ้าไม่มี custom files:

```bash
# Copy examples to create your own
cp cogs/ai_core/data/faust_data_example.py cogs/ai_core/data/faust_data.py
cp cogs/ai_core/data/roleplay_data_example.py cogs/ai_core/data/roleplay_data.py
```

**faust_data.py** - AI Personality:

| Variable | Description |
| --- | --- |
| `FAUST_INSTRUCTION` | Main system prompt / personality |
| `FAUST_DM_INSTRUCTION` | DM-specific behavior |
| `FAUST_SANDBOX` | Unrestricted mode prompt |
| `FAUST_CODE_OVERRIDE` | Code mode prompt |
| `ESCALATION_FRAMINGS` | Fallback prompts when AI refuses |

**roleplay_data.py** - RP System:

| Variable | Description |
| --- | --- |
| `WORLD_LORE` | Universe/setting description |
| `ROLEPLAY_PROMPT` | RP assistant instructions |
| `SERVER_CHARACTERS` | Character list with image paths |
| `SERVER_AVATARS` | Guild-specific webhook avatar mappings |
| `SERVER_LORE` | Guild-to-lore mapping |

> **RP server message handling.** In the guild set as `GUILD_ID_RP` the AI does **not**
> auto-reply to plain messages — players must run `!chat`/`!ask` in `CHANNEL_ID_RP_COMMAND`
> (the only input room) and the reply is redirected to `CHANNEL_ID_RP_OUTPUT`, which is
> write-only. `SERVER_LORE` is appended to `ROLEPLAY_PROMPT` and capped at **20 000 chars**
> (`session_mixin.py`) — keep `WORLD_LORE` under that or the tail gets truncated.

**Character Images:**

```text
assets/RP/              # Large images for AI to see ([IMAGE:] references)
└── AVATARS/            # Small images for webhook avatars — keep each < 200 KB
```

> Webhook avatars must be **under ~200 KB**: Discord rejects larger avatars with a 400, so
> `send_as_webhook()` skips the avatar (logs a warning) when a file exceeds the cap.
> Downscale replacements (256×256 PNG is plenty). Webhooks created while a file was
> oversized self-heal — the bot backfills the avatar on the next message once the file fits.

---

## 🧠 AI Core Deep Dive

### 1. Chat Processing (`logic.py`)

**Main method:** `ChatManager.process_chat()`

```text
1. Request Deduplication (ป้องกัน double-submit)
2. Lock Management (channel-level concurrency)
3. Session Management (get/create chat session)
4. Context Building:
   - Load history
   - RAG search for relevant memories
   - Entity memory injection
   - State tracking (RP mode)
5. API Call:
   - Regular or Streaming mode
   - Multi-tier fallback on failure
6. Post-processing:
   - Character state extraction
   - Response cleanup
   - History save
```

### 2. Guardrails (removed) + Unrestricted Mode

> **หมายเหตุ:** โมดูล `cogs/ai_core/processing/guardrails.py` ถูกลบออกแล้ว —
> content validation และ secret/token redaction ไม่มีผลอีกต่อไป (ข้อความถูกส่งผ่าน
> โดยไม่กรอง) ฟังก์ชัน validation เดิม (`validate_response`,
> `validate_input_for_channel`, `validate_response_for_channel`, `is_silent_block`)
> ยังคงอยู่เป็น **no-op shim** ใน `cogs/ai_core/imports.py` โดย
> `GUARDRAILS_AVAILABLE` เป็น `False` เสมอ

**Unrestricted mode ยังใช้งานได้** — ถูกย้ายไปเป็นโมดูลของตัวเองที่
`cogs/ai_core/processing/unrestricted.py` (decoupled จาก guardrails) ทำหน้าที่
ควบคุมการฉีด persona `UNRESTRICTED_MODE_INSTRUCTION` ต่อห้อง และจำสถานะถาวรใน
`unrestricted_channels.json`

```python
# เปิด/ปิด unrestricted ต่อห้อง (owner: !unrestricted)
from cogs.ai_core.processing.unrestricted import is_unrestricted, set_unrestricted
set_unrestricted(channel_id, True)
if is_unrestricted(channel_id):
    ...  # session_mixin ฉีด UNRESTRICTED_MODE_INSTRUCTION เข้า system prompt

# global override: ตั้ง env AI_UNRESTRICTED_ALL=1 → ทุกห้องเป็น unrestricted
```

### 3. RAG System (`rag.py`)

FAISS-based memory retrieval:

- **Embedding:** Gemini embeddings (`gemini-embedding-2`, 768-dim via `output_dimensionality`, requested with `GEMINI_API_KEY`) — enabled on any backend when a key + google-genai are present (gate is `RAG_EMBEDDINGS=auto|off`, decoupled from `CLAUDE_BACKEND`). RAG query/search runs regardless of backend; only the LLM-based memory consolidator (fact-extraction writes) no-ops under the default `cli` mode because the Claude SDK client is not initialised. (The previous `text-embedding-004` model was shut down by Google on 2026-01-14.)
- **Backend:** Optional Rust extension (`rag_engine.pyd`, ~10–25× faster) with Python fallback
- **Hybrid Search:** Semantic + keyword + time decay
- **Auto-indexing:** Conversations automatically indexed
- **Persistence:** FAISS index + JSON id-map sidecar in `data/faiss/`. Legacy `.npy` (pickle) sidecars are refused at load unless `RAG_ALLOW_LEGACY_PICKLE=1` — pickle from disk is an RCE sink.

### 4. Streaming (`logic.py`)

Real-time response updates via Discord message editing:

- Chunks merged and sent every ~1-2 seconds
- Fallback to non-streaming on timeout
- Graceful handling of stalled streams

---

## 🎵 Music System

### Key Files

- `cogs/music/cog.py` - Main music cog
- `cogs/music/queue.py` - Queue management
- `cogs/music/utils.py` - Colors, emojis, formatting
- `cogs/music/views.py` - Discord UI components
- `cogs/spotify_handler.py` - Spotify URL processing

> **Note:** `spotify_handler.py` uses lazy import for `SpotifyHandler` to avoid circular import.

### Features

- YouTube/Spotify support
- Queue management
- Loop modes (song/queue)
- Auto-disconnect
- Premium UI with progress bars

---

## 🛡️ Reliability Patterns

### Circuit Breaker (`circuit_breaker.py`)

Thread-safe protection against cascading failures with `threading.Lock`:

```python
from utils.reliability.circuit_breaker import gemini_circuit

if gemini_circuit.can_execute():
    try:
        result = await call_api()
        gemini_circuit.record_success()
    except Exception:
        gemini_circuit.record_failure()
```

### Rate Limiter (`rate_limiter.py`)

Thread-safe token bucket algorithm:

- Per-user, per-channel, per-guild limits
- Adaptive limits based on circuit state
- Configurable cooldown messages
- Atomic cleanup of old buckets

### Self Healer (`self_healer.py`)

Auto-recovery:

- Detect duplicate bot instances
- PID file management

### Performance Tracker (`performance_tracker.py`)

Response time tracking with automatic memory management:

- Percentile calculations (p50, p90, p99)
- Hourly trend analysis
- Auto-cleanup of old samples (prevents memory growth)

### Memory Manager (`memory_manager.py`) 🆕

Memory leak prevention with smart caching:

```python
from utils.reliability.memory_manager import (
    TTLCache, WeakRefCache, MemoryMonitor,
    memory_monitor, cached_with_ttl
)

# TTL Cache - auto-expires entries
cache = TTLCache[str, dict](ttl=300, max_size=1000, name="api_cache")
cache.set("key", {"data": "value"})
result = cache.get("key")

# WeakRef Cache - auto-releases when objects are GC'd
weak_cache = WeakRefCache[str, MyClass]()
weak_cache.set("key", MyObject())

# Decorator for function caching
@cached_with_ttl(ttl=60.0, max_size=100)
async def fetch_user(user_id: int) -> dict:
    return await api.get_user(user_id)

# Memory monitoring
memory_monitor.register_cache("api_cache", cache)
memory_monitor.start()  # Background cleanup at 80% threshold
```

**Features:**

- TTL-based automatic expiration
- LRU eviction when max size reached
- WeakRef caching for auto memory release
- Memory threshold monitoring in absolute MiB (defaults: 1024 warning, 1536 critical; env-tunable via `BOT_MEMORY_WARNING_MB` / `BOT_MEMORY_CRITICAL_MB`)
- Background cleanup tasks

### Shutdown Manager (`shutdown_manager.py`) 🆕

Graceful shutdown with coordinated cleanup:

```python
from utils.reliability.shutdown_manager import (
    shutdown_manager, Priority, on_shutdown
)

# Decorator for cleanup functions
@on_shutdown(priority=Priority.HIGH, timeout=5.0)
async def cleanup_connections():
    await db.close()

# Manual registration
shutdown_manager.register(
    name="flush_cache",
    callback=cache.flush,
    priority=Priority.NORMAL
)

# Trigger shutdown (called automatically on SIGTERM/SIGINT)
await shutdown_manager.shutdown(reason="maintenance")
```

**Features:**

- Priority-based cleanup (CRITICAL → HIGH → NORMAL → LOW → BACKGROUND)
- Per-handler timeout with force-kill fallback
- Signal handling (SIGTERM, SIGINT, atexit)
- Async and sync cleanup support
- Detailed shutdown statistics

### Structured Logging (`structured_logger.py`) 🆕

JSON-formatted logging for ELK/Prometheus/Loki:

```python
from utils.monitoring.structured_logger import (
    StructuredLogger, get_logger, timed
)

# Get a structured logger
logger = get_logger("ai_core")

# Log with context
logger.info("Processing message", extra={
    "user_id": user.id,
    "channel_id": channel.id,
    "message_length": len(message)
})

# Request context tracking
async with logger.request(user_id=123, channel_id=456):
    # All logs in this context include user/channel
    logger.info("Request started")
    await process()
    logger.info("Request completed")

# Performance timing decorator
@timed("process_message")
async def process_message(msg):
    # Automatically logs duration
    ...
```

**Output Format (JSON):**

```json
{
  "timestamp": "2026-01-21T10:30:00.000Z",
  "level": "INFO",
  "logger": "ai_core",
  "message": "Processing message",
  "context": {
    "user_id": 123456789,
    "channel_id": 987654321,
    "correlation_id": "abc-123"
  },
  "extra": {"message_length": 150},
  "source": {"file": "logic.py", "line": 42, "function": "process_chat"}
}
```

**Features:**

- JSON-formatted output for log aggregators
- Request context tracking (correlation IDs)
- Performance timing with `@timed` decorator
- Human-readable colored console output (optional)
- Rotating file output

---

## 💾 Database

### Schema (SQLite)

| Table | Purpose |
| --- | --- |
| `ai_history` | Chat history per channel |
| `ai_metadata` | Session settings |
| `entity_memories` | Character/entity facts |
| `user_facts` | Permanent user facts |
| `ai_long_term_memory` | Vector embeddings (RAG) |
| `music_queue` | Persistent queue |
| `guild_settings` | Per-server config |

### Usage

```python
from utils.database import db

# Get history
history = await db.get_ai_history(channel_id, limit=100)

# Save message
await db.save_ai_message(channel_id, 'user', 'Hello!')
```

---

## 🚀 Running the Bot

### Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run with auto-reload
python scripts/dev_watcher.py
```

### Production

```bash
# Direct run
python bot.py

# Or with nohup
nohup python bot.py > bot.log 2>&1 &
```

---

## 🔧 Common Tasks

### Add New Game Keywords

Edit `cogs/ai_core/data/constants.py`:

```python
GAME_SEARCH_KEYWORDS = [
    # existing...
    'new_keyword',
]
```

### Modify Persona

Edit `cogs/ai_core/data/faust_data.py`:

- `FAUST_INSTRUCTION` - Regular mode
- `FAUST_DM_INSTRUCTION` - DM mode
- `UNRESTRICTED_MODE_INSTRUCTION` - Creative writing prefix

### Add New Command

```python
# In a cog under cogs/ (e.g. cogs/ai_core/ai_cog.py or a new cog file)
@commands.command()
async def mycommand(self, ctx):
    await ctx.send("Hello!")
```

### Debug AI Issues

```text
!ai_debug     # Show session info
!ai_trace     # Show last request details
!ai_stats     # Show performance metrics
!ai_perf      # Show latency stats
```

---

## ⚠️ Known Gotchas

1. **Lock Timeout:** Uses `asyncio.wait_for()` with 180s timeout (see `LOCK_TIMEOUT` in `cogs/ai_core/data/constants.py`)
2. **Refusal Handling:** Refusal detection is pattern-based (keys off response content patterns, not length) — see the refusal guards in `cogs/ai_core/storage.py` / `session_mixin.py` and `call_claude_api`'s retry/refusal logic (no standalone `detect_refusal()` function exists)
3. **Streaming Timeout:** 120s for the initial chunk (`STREAMING_TIMEOUT_INITIAL`), falls back to non-streaming
4. **Memory Cleanup:** Old RAG entries need periodic pruning
5. **Thread Safety:** `CircuitBreaker` and `RateLimiter` use `threading.Lock` for thread-safe operations
6. **Webhook Cache:** Auto-cleared when channels are deleted via `on_guild_channel_delete` listener
7. **History Cache:** Uses `copy.deepcopy()` to prevent mutation of cached nested objects
8. **Cache Size Limit:** Max 2000 channels cached (`MAX_CACHE_SIZE`), oldest entries evicted when exceeded
9. **Permission Checks:** Music commands require `connect` and `speak` permissions in target channel
10. **Memory Bounds:** Rate limiter (10k buckets), message queue (5k channels), state tracker have eviction limits
11. **Specific Exceptions:** All `except Exception` blocks replaced with specific exception types for better debugging
12. **SSRF Protection:** Go services bind to `127.0.0.1` by default and url_fetcher uses `ssrfSafeDialContext` to block DNS rebinding attacks with full IPv6 coverage
13. **Permission Allowlists:** AI server commands validate against `_SAFE_PERMISSIONS` / `_DANGEROUS_PERMISSIONS` frozensets — administrator, manage_guild, ban_members etc. are blocked
14. **Dashboard Auth:** WebSocket dashboard requires `DASHBOARD_WS_TOKEN` env var for authentication; unrestricted mode gated behind `DASHBOARD_ALLOW_UNRESTRICTED`
15. **Lock Safety:** AI-core lock acquisition uses `asyncio.wait_for(lock.acquire(), timeout=LOCK_TIMEOUT)` directly — the CPython #42130 deadlock fix landed in Python 3.12+ (repo requires 3.14+), so the former `asyncio.shield()` workaround was removed (it caused a double-release race); `ShutdownManager` still defers Event/Lock creation to the correct event loop
16. **Mention Sanitization:** Both `sanitization.py` and webhook `send_as_webhook()` sanitize role mentions (`<@&ID>`) and user mentions (`<@ID>`) with zero-width space
17. **Atomic Persistence:** RAG engine persists its in-memory store via temp-file+rename (write to a temp file, then atomic rename) so a crash mid-save can't corrupt the index
18. **AllowedMentions Default:** Bot-level `AllowedMentions(everyone=False, roles=False)` prevents AI-generated @everyone/@here from mass-pinging
19. **Sensitive Data Filter:** Logger filters Discord tokens, API keys, and secrets from all log output via regex patterns
20. **Path Traversal Guard:** `safe_delete()` validates resolved paths are within `temp/` directory before deletion
21. **SQL Injection Guard:** `increment_user_stat()` uses a whitelist dict for column names instead of f-string interpolation
22. **asyncio.TimeoutError Compat:** Dashboard chat defensively catches both `TimeoutError` and `asyncio.TimeoutError` (the two are aliased on Python 3.11+)
23. **Dashboard CLI File-Write Mode:** When `CLAUDE_BACKEND=cli`, the embedded `claude -p` can create/edit files non-interactively only if `DASHBOARD_CLI_ALLOW_WRITE` is on (default off). Writes are confined to `DASHBOARD_CLI_WRITE_DIRS` (default: Desktop/Documents/Downloads, plus OneDrive-redirected Desktop/Documents on Windows). The authoritative path boundary is the PreToolUse hook `cogs/ai_core/api/cli_write_guard.py`, which denies any `Write/Edit/MultiEdit/NotebookEdit` whose canonical path is outside those roots (fails closed) — the repo, `.env`, `~/.ssh`, `~/.claude`, and the home root are excluded. It is files-only: `Bash`, `WebFetch`, `WebSearch`, `NotebookEdit`, and `Task` are denied.

---

## 🛠️ Recent Bug Fixes

### Phase 1 - Code Audit (January 20, 2026)

| Issue | Fix | File |
| --- | --- | --- |
| Duplicate `IMAGEIO_AVAILABLE` import | Removed redundant import | `logic.py` |
| Dead code `knowledge_context` | Removed unused variable | `logic.py` |
| PIL Images NameError in finally | Variables initialized before `async with` | `logic.py` |
| Webhook cache not cleared on channel delete | Added `on_guild_channel_delete` listener | `ai_cog.py`, `tools.py` |
| Background task catches only RuntimeError | Changed to catch all `Exception` with backoff | `tools.py` |
| Missing `guild.me` None check | Added null check in `cmd_add_role`/`cmd_remove_role` | `tools.py` |
| Shallow copy in cache return | Changed to `copy.deepcopy()` | `storage.py` |
| Magic number `max_history = 2000` | Uses `MAX_HISTORY_ITEMS` constant | `logic.py` |
| Cache memory can grow unbounded | Added `MAX_CACHE_SIZE=2000` (current value) + TTL cleanup | `storage.py` |
| Missing permission check in music | Added `@bot_has_guild_permissions(connect, speak)` | `cog.py` |
| No periodic cache cleanup | Added cleanup every 5 min in AI cog | `ai_cog.py` |

### Phase 2 - Full Audit (January 21, 2026)

| Issue | Fix | File |
| --- | --- | --- |
| Race condition in lock creation | Use `setdefault()` instead of check-then-create | `logic.py` |
| Race condition in rate limiter locks | Use `setdefault()` for atomic lock creation | `rate_limiter.py` |
| Silent exception in `is_ready()` | Added `logger.debug()` | `health_client.py` |
| Silent exception in `set_service_status()` | Added `logger.debug()` | `health_client.py` |
| Silent exception in `_flush_buffer_locked()` | Added `logger.debug()` | `health_client.py` |
| Silent exception in `_check_service()` | Added `logger.debug()` | `url_fetcher_client.py` |
| Silent exception in `_get_adaptive_multiplier()` | Added `logging.debug()` | `rate_limiter.py` |
| Silent exception in `capture_exception()` | Added `logging.debug()` | `sentry_integration.py` |
| Silent exception in `capture_message()` | Added `logging.debug()` | `sentry_integration.py` |
| Silent exception in `get_ai_performance_stats()` | Added `logging.debug()` | `health_api.py` |
| Silent exception in `fetch_emoji_images()` | Added `logging.debug()` | `emoji.py` |
| Silent exception in `is_animated_gif()` | Added `logging.debug()` | `media_processor.py`, `content_processor.py` |
| Silent exception in `_pil_is_animated()` | Added `logging.debug()` | `media_rust.py` |
| Silent exception in FAISS temp cleanup | Added `logging.debug()` | `rag.py` |

### Phase 3 - Refactoring & Testing (January 21, 2026)

| Change | Description | Files |
| --- | --- | --- |
| **tools.py refactoring** | Split 1,405 lines into 5 modules | `sanitization.py`, `webhook_cache.py`, `server_commands.py`, `tool_definitions.py`, `tool_executor.py` |
| **New test files** | Added 67 new tests | `test_music_queue.py`, `test_fast_json.py`, `test_self_reflection.py`, `test_spotify_handler.py` |
| **CI/CD improvements** | Added Python 3.10, coverage, Codecov, Dependabot | `.github/workflows/ci.yml`, `.github/dependabot.yml` |
| **Dependency updates** | google-genai 1.59.0, aiohttp 3.13.3, certifi | `requirements.txt` |

### Phase 4 - ai_core Reorganization (January 21, 2026)

| Change | Description | Files |
| --- | --- | --- |
| **logic.py refactoring** | Split into 4 modular components | `performance.py`, `message_queue.py`, `context_builder.py`, `response_sender.py` |
| **ai_core reorganization** | Created 5 new subdirectories | `api/`, `core/`, `response/`, `commands/`, `tools/` |
| **Backward compatibility** | Created 14 re-export files | All moved modules have root-level re-exports |
| **E501 lint fixes** | Fixed 16 line-too-long errors | `api_handler.py`, `debug_commands.py`, `entity_memory.py`, `tool_definitions.py`, `tool_executor.py` |
| **Test count** | Increased from 285 to 362 | New tests for modular components |

### Phase 5 - Reliability & Monitoring Enhancements (January 21, 2026)

| Change | Description | Files |
| --- | --- | --- |
| **Memory Manager** | TTL cache, WeakRef cache, memory monitoring | `utils/reliability/memory_manager.py` |
| **Shutdown Manager** | Graceful shutdown with priority cleanup | `utils/reliability/shutdown_manager.py` |
| **Structured Logging** | JSON logging with context tracking, correlation IDs | `utils/monitoring/structured_logger.py` |
| **Error Recovery** | Smart exponential backoff with jitter | `utils/reliability/error_recovery.py` |
| **New test files** | 90 new tests for new modules | `test_memory_manager.py`, `test_shutdown_manager.py`, `test_structured_logger.py`, `test_error_recovery.py` |
| **Lint fixes** | Fixed 185 whitespace issues with ruff | Various files |
| **Test count** | Increased from 362 to 452 | +90 tests for new reliability modules |

### Phase 6 - Deep Code Audit (January 25, 2026)

| Issue | Fix | File |
| --- | --- | --- |
| Broad `except Exception` in ALTER TABLE | Changed to `except aiosqlite.OperationalError` | `database.py` |
| Broad `except Exception` in datetime parsing | Changed to `except (ValueError, TypeError, AttributeError)` | `rag.py` |
| Broad `except Exception` in Discord views | Changed to `except (discord.NotFound, discord.HTTPException)` | `views.py` |
| Unbounded dict growth in rate limiter | Added `MAX_BUCKETS = 10000` with LRU eviction | `rate_limiter.py` |
| Unbounded dict growth in message queue | Added `MAX_CHANNELS = 5000`, `MAX_PENDING = 50` | `message_queue.py` |
| Unsafe `asyncio.run_coroutine_threadsafe` | Added `_safe_run_coroutine()` helper with error handling | `cog.py` |
| Blanket deprecation warning ignore | Changed to selective (`discord.*`, `aiohttp.*`, `google.*`) | `pyproject.toml` |
| Broad `except Exception` in guardrails | Changed to `except (json.JSONDecodeError, OSError, ValueError)` | `guardrails.py` |
| Broad `except Exception` in consolidator | Split into parsing errors vs unexpected errors | `consolidator.py` |
| Unbounded state tracker | Added `MAX_CHANNELS`, `MAX_CHARACTERS` limits | `state_tracker.py` |
| Broad `except Exception` in summarizer | Split into specific exception types | `summarizer.py` |
| Broad `except Exception` in health client | Changed to `except (aiohttp.ClientError, asyncio.TimeoutError)` | `health_client.py` |
| PIL Image resource leaks | Added `try/finally` blocks for proper cleanup | `media_rust.py` |
| 7 broad exceptions in logic.py | Changed to specific types (aiohttp, asyncio, KeyError, etc.) | `logic.py` |
| Broad exception in response sender | Changed to `except (discord.HTTPException, Forbidden, NotFound)` | `response_sender.py` |
| PIL resource leaks in media processor | Added `try/finally` and specific exception types | `media_processor.py` |
| Missing `import aiohttp` | Added aiohttp import for exception handling | `logic.py` |
| Missing `import discord` | Added discord import for exception handling | `response_sender.py` |

### Phase 7 - Native Dashboard (Tauri) Audit (February 6, 2026)

| Issue | Fix | File |
| --- | --- | --- |
| `Arc<Mutex>` blocking async in Tauri commands | Changed to `Arc<tokio::sync::Mutex>` with `.await` | `main.rs` |
| No CSP headers allowing XSS | Added strict Content-Security-Policy meta tag | `index.html` |
| Database connections leaked on error | Created RAII `ConnectionGuard` for auto-cleanup | `database.rs` |
| Log viewer reads entire file into memory | Changed to reverse-read last N bytes from end | `bot_manager.rs` |
| XSS via unsanitized log/DB content in innerHTML | Added `escapeHtml()` sanitizer to all dynamic content | `app.ts` |
| Toast/notification XSS injection | All toast messages now escaped | `app.ts` |
| Race condition in theme/sakura initialization | Added `DOMContentLoaded` guard | `app.ts` |
| TypeScript `any` types throughout | Replaced with proper interfaces and type annotations | `app.ts` |
| 38 total issues across 9 files | All fixed and verified | `native_dashboard/` |

### Phase 8 - Rust Extensions Audit (February 6, 2026)

| Issue | Fix | File |
| --- | --- | --- |
| No runtime dimension check on `add()` | Added vector length validation with `PyValueError` | `rag_engine/src/lib.rs` |
| Stale references after `remove()` | Clear search cache on entry removal | `rag_engine/src/lib.rs` |
| Integer overflow in similarity calc | Added `.min(1.0)` clamp for floating-point safety | `rag_engine/src/cosine.rs` |
| Crop dimensions could exceed image bounds | Added `min()` clamping before crop | `media_processor/src/resize.rs` |

### Phase 9 - Go Services & Scripts Final Audit (February 6, 2026)

| Issue | Fix | File |
| --- | --- | --- |
| `/metrics/batch` was dead stub (discarded payloads) | Implemented full metric processing with 1MB body limit, 1000 batch cap | `health_api/main.go` |
| `/health/service` no input validation | Added 64KB body limit, service name validation (max 100 chars) | `health_api/main.go` |
| `/metrics/push` no body size limit | Added 64KB body limit | `health_api/main.go` |
| SSRF vulnerability on `/fetch` | Added http/https URL scheme validation | `url_fetcher/main.go` |
| `/fetch/batch` no request body limit | Added 1MB body limit | `url_fetcher/main.go` |
| User timeout unbounded | Capped timeout to 120 seconds max | `url_fetcher/main.go` |
| `check_db.py` connection leak | Converted to `async with` context manager | `check_db.py` |
| `migrate_to_db.py` sync/async mismatch | Converted to `async def` + `asyncio.run()` | `migrate_to_db.py` |
| `migrate_to_db.py` non-existent `db.get_stats()` | Replaced with direct aiosqlite query | `migrate_to_db.py` |

### Phase 10 - Test Verification & Cleanup (February 7, 2026)

| Issue | Fix | File |
| --- | --- | --- |
| `test_create_voice_channel_invalid_name` expected error for sanitized name | Updated to expect `"untitled"` fallback from `sanitize_channel_name` | `test_server_commands_extended.py` |
| `test_create_category_invalid_name` expected error for sanitized name | Updated to expect `create_category("untitled")` | `test_server_commands_extended.py` |
| `test_start_cleanup_task` failed due to `bot.loop.is_closed()` returning truthy mock | Added `mock_bot.loop.is_closed.return_value = False` | `test_webhook_cache.py` |
| 17 tests skipped due to missing `prometheus_client` | Created `_enable_metrics_with_mocks()` helper with fresh MagicMock per test | `test_metrics_module.py` |
| DeprecationWarning from importing deprecated content_processor | Added `pytestmark = pytest.mark.filterwarnings(...)` | `test_content_processor.py` |
| RuntimeWarning: coroutine `stop_background_task` never awaited | Made test async + added `await` | `test_memory_consolidator.py` |
| RuntimeWarning: coroutine `stop_cleanup_task` never awaited | Added `await` to cleanup call | `test_rate_limiter.py` |
| RuntimeWarning: coroutine `_cleanup_expired_webhook_cache` never awaited | Added `coroutine_arg.close()` after assertions | `test_webhook_cache.py` |
| Duplicate `escapeHtml` class method in dashboard | Removed duplicate, unified to standalone `escapeHtml()` | `app.ts` |

### Phase 12 - Security & Reliability Audit (March 13, 2026)

**Security Fixes:**

| Issue | Fix | File |
| --- | --- | --- |
| No default `AllowedMentions` — AI could ping @everyone | Added `AllowedMentions(everyone=False, roles=False)` | `bot.py` |
| `safe_delete()` path traversal vulnerability | Validate path within `temp/` via `Path.resolve()` | `cogs/music/cog.py` |
| SQL column name f-string injection in stats | Whitelist dict with bracket-quoted column names | `utils/database/database.py` |
| Guardrails import failure was silent | Log `logging.critical()` on ImportError | `cogs/ai_core/logic.py` |
| AI response could contain @everyone/@here | Sanitize with zero-width space before all send paths | `cogs/ai_core/logic.py` |
| Logger could leak tokens/API keys | Added `SensitiveDataFilter` with regex patterns | `utils/monitoring/logger.py` |
| URL cache race condition (no locking) | Added `asyncio.Lock` for all cache operations | `utils/web/url_fetcher.py` |

**Reliability Fixes:**

| Issue | Fix | File |
| --- | --- | --- |
| Circuit breaker mixed `asyncio.Lock` + `threading.Lock` | Unified to `threading.Lock` only | `utils/reliability/circuit_breaker.py` |
| Music queue no locking on shared dicts | Added per-guild `asyncio.Lock` | `cogs/music/queue.py` |
| `error_recovery` double-locking deadlock risk | Removed redundant `asyncio.Lock` | `utils/reliability/error_recovery.py` |
| Self-healer substring matching false positives | `PureWindowsPath.name` exact match | `utils/reliability/self_healer.py` |
| `asyncio.TimeoutError` uncaught on Python 3.10 | `except (TimeoutError, asyncio.TimeoutError)` | `cogs/ai_core/api/dashboard_chat.py` |

**Test Fixes:**

| Issue | Fix | File |
| --- | --- | --- |
| `FakeChunk` MagicMock failed Pydantic validation | Use real `genai_types.Part`/`Content` | `tests/test_dashboard_chat.py` |
| `test_thought_as_string` invalid Part constructor | Use `SimpleNamespace` for edge-case | `tests/test_dashboard_chat.py` |

### Phase 13 - Comprehensive Audit (March 25, 2026)

**Security Fixes:**

| Issue | Fix | File |
| --- | --- | --- |
| Path traversal in RAG engine `save()`/`load()` | Added `Component::ParentDir` check rejecting paths containing `..` | `rust_extensions/rag_engine/src/lib.rs` |
| Timestamp comparison without ISO validation in history diff | Added `_ISO_RE` regex validation; logs warning for non-ISO timestamps | `cogs/ai_core/storage.py` |

**Reliability Fixes:**

| Issue | Fix | File |
| --- | --- | --- |
| Task leak on cog hot-reload — old background tasks not cancelled | Added explicit cancellation of `cleanup_task`, `_pending_request_cleanup_task`, `_cache_cleanup_task` before creating new ones | `cogs/ai_core/ai_cog.py` |
| Bot instance memory leak on restart — old bot not closed | Added `old_bot.close()` before creating new bot instance in restart loop | `bot.py` |
| Missing DB indexes — full table scans on knowledge_entries, error_logs | Added indexes: `idx_knowledge_domain`, `idx_knowledge_category`, `idx_knowledge_topic`, `idx_error_logs_type`, `idx_error_logs_created` | `utils/database/database.py` |
| audit_log index not DESC + missing composite index | Changed `idx_audit_log_created` to DESC order; added composite `idx_audit_log_guild_created` | `utils/database/database.py` |

### Phase 11 - Security Hardening & Reliability Fixes (February 10, 2026)

**Security Fixes:**

| Issue | Fix | File |
| --- | --- | --- |
| SSRF via DNS rebinding in url_fetcher | Added `ssrfSafeDialContext()` that checks resolved IPs at connect time | `url_fetcher/main.go` |
| Missing IPv6 SSRF coverage | Pre-parsed `privateNetworks` with IPv4-mapped IPv6 ranges in `init()` | `url_fetcher/main.go` |
| Go services exposed on all interfaces | Bound to `127.0.0.1` (configurable via `HEALTH_API_HOST` env) | `health_api/main.go`, `url_fetcher/main.go` |
| No auth on WebSocket dashboard | Added `DASHBOARD_WS_TOKEN` env var authentication | `ws_dashboard.py` |
| Origin check bypass via subdomain | Fixed to check prefix + delimiter (`:` or `/`) | `ws_dashboard.py` |
| Unrestricted mode exposed without gate | Gated behind `DASHBOARD_ALLOW_UNRESTRICTED` env var | `ws_dashboard.py` |
| AI can set dangerous permissions | Added `_SAFE_PERMISSIONS` / `_DANGEROUS_PERMISSIONS` allowlists | `server_commands.py` |
| Webhook mention injection | Added `re.sub()` for role/user mention sanitization | `tool_executor.py` |
| Path traversal in conversation export | Added regex validation `^[a-zA-Z0-9_-]+$` on `conversation_id` | `database.py` |
| Prometheus cardinality explosion | Added `allowedMetricNames`, `allowedLabelValues`, `safeLabel()` | `health_api/main.go` |

**Reliability Fixes:**

| Issue | Fix | File |
| --- | --- | --- |
| `asyncio.wait_for(lock.acquire())` deadlock (CPython #42130) | Use `asyncio.shield()` for safe lock acquisition | `logic.py` |
| GC deadlock in WeakRefCache | Changed `threading.Lock()` to `threading.RLock()` | `memory_manager.py` |
| Sync `_get_backoff_state()` called in async `retry_async()` | Changed to `await _get_backoff_state_async()` | `error_recovery.py` |
| `asyncio.Event()`/`Lock()` bound to wrong event loop at import | Lazy creation via `_get_shutdown_event()` / `_get_lock()` getters | `shutdown_manager.py` |
| Non-atomic JSON save in RAG engine | Atomic write via temp file + rename with cleanup | `lib.rs` |
| Music queue lost on cog reload | Save all queues before clearing in `cog_unload` | `cog.py` |
| Cross-guild retry state leak | Per-guild retry tracking (`_play_next_retries_{guild_id}`) | `cog.py` |

**Correctness Fixes:**

| Issue | Fix | File |
| --- | --- | --- |
| `CancelledError` conflated with message interrupts | New `_NewMessageInterrupt` exception class | `logic.py` |
| Naive `datetime.now()` in history | Changed to `datetime.now(datetime.timezone.utc)` | `logic.py` |
| O(n²) shuffle on deque | Convert to list, shuffle, extend back — O(n) | `queue.py` |
| Skip-if-smaller applied to Fill/Stretch modes | Restrict check to `Fit` mode only via `matches!()` | `resize.rs` |
| GIF frame detection via GCE only (optional per spec) | Count Image Descriptor (0x2C) blocks instead | `gif.rs` |
| Stale entries accumulate on load | `entries.clear()` before loading from file | `lib.rs` |
| Channel eviction leaks MessageQueue data | Clean up `pending_messages` and `cancel_flags` | `logic.py` |
| Global export debounce drops concurrent exports | Per-channel `_export_pending_keys` set | `database.py` |
| Unbounded response body in url_fetcher | `MAX_RESPONSE_SIZE = 5MB` with `content.read()` | `url_fetcher.py` |
| `ensure_ascii` default mismatch between orjson/stdlib | Aligned both to `False` | `fast_json.py` |
| Redundant `import re` in sanitization | Removed (already imported at top) | `sanitization.py` |

---

## 📚 Further Reading

- [discord.py Documentation](https://discordpy.readthedocs.io/)
- [Google Gemini API](https://ai.google.dev/)
- [FAISS Documentation](https://github.com/facebookresearch/faiss)

---

<!-- Documentation last updated: June 15, 2026 - Version 3.4.14 | Full-project audit complete (196+ issues fixed across Python, Rust, Go, TypeScript, HTML/CSS) | Security hardening: SSRF, auth, permission allowlists, mention sanitization, AllowedMentions, path traversal guard (incl. RAG engine), SQL injection guard, sensitive data filter, ISO timestamp validation | Reliability: asyncio.shield, RLock, atomic persistence, lazy Event/Lock, per-guild queue locks, unified circuit breaker locks, cog reload task cleanup, bot restart cleanup | Memory Manager, Shutdown Manager, Structured Logging | Error Recovery with smart backoff | Database indexes optimized | 5,418 Python tests + 467 frontend vitest tests + 90 Playwright e2e/a11y/visual tests | CI/CD with Codecov & Dependabot | chat-manager.ts split into 11 focused modules (2026-04) | AI Round 1+2 audit: CLI memory parity with API, cache invalidation hooks, tz-aware datetimes, full-content dedup, code-fence-aware splitting (2026-04-27) | Dashboard AI History editor (browse/edit/delete/undo + live-session sync) + Claude CLI overhaul: delta-on-resume, session self-heal on errors, transcript cleanup, CLI_PROMPT_MAX_CHARS over-limit choice flow (2026-06-12) -->
