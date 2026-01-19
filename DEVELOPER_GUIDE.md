# 🤖 Discord AI Bot - Project Documentation

> **Last Updated:** January 19, 2026  
> **Python Version:** 3.11+  
> **Framework:** discord.py 2.x  
> **Total Files:** 105 Python files | 204 Tests  
> **Code Quality:** All imports verified ✅ | Circular imports fixed ✅

---

## 📋 Overview

Discord Bot ที่รวม AI Chat (Gemini API) และ Music Player ไว้ด้วยกัน มีระบบ Memory ระดับ Enterprise และ Reliability Patterns ครบครัน

### Key Features
- **AI Chat** - Gemini API integration with RAG, streaming, and context management
- **Music Player** - YouTube/Spotify support with queue, loop, and premium UI
- **Multi-Character Roleplay** - Character state tracking และ entity memory
- **Unrestricted Mode** - Creative writing mode สำหรับ channels ที่เลือก
- **Enterprise Reliability** - Circuit breaker, rate limiting, self-healer

---

## 📁 Directory Structure (105 Python Files)

```
BOT/
├── bot.py                    # 🚀 Main entry point
├── config.py                 # ⚙️ Centralized configuration
├── bot_dashboard.py          # 🖥️ PyQt5 Desktop Dashboard
├── create_shortcut.py        # Desktop shortcut creator
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
│   └── ai_core/              # 🧠 AI Core Module
│       ├── __init__.py
│       ├── ai_cog.py         # ⭐ Main AI cog (commands & events)
│       ├── logic.py          # ⭐ ChatManager - core AI logic
│       ├── storage.py        # History persistence (SQLite)
│       ├── tools.py          # Server tools, webhooks
│       ├── emoji.py          # Discord emoji processing
│       ├── voice.py          # Voice channel management
│       ├── fallback_responses.py  # Fallback when AI fails
│       ├── debug_commands.py # Debug/admin commands
│       ├── memory_commands.py # User memory commands
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
│       │   ├── history_manager.py # Smart history trimming
│       │   ├── summarizer.py # Conversation summarization
│       │   ├── entity_memory.py # Character/entity facts
│       │   ├── long_term_memory.py # Permanent user facts
│       │   ├── memory_consolidator.py # Memory consolidation
│       │   ├── conversation_branch.py # Conversation branching
│       │   ├── state_tracker.py # RP character states
│       │   └── consolidator.py # Fact extraction from history
│       │
│       ├── processing/       # 🔄 Request Processing
│       │   ├── __init__.py
│       │   ├── guardrails.py # ⚠️ Safety & unrestricted mode
│       │   ├── intent_detector.py # Message intent classification
│       │   ├── prompt_manager.py # System prompt templates
│       │   └── self_reflection.py # Response quality checks
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
│   │   └── self_healer.py    # Auto-recovery from issues
│   │
│   ├── monitoring/           # 📈 Monitoring & Metrics
│   │   ├── __init__.py
│   │   ├── health_api.py     # HTTP health check API
│   │   ├── logger.py         # Smart logging system
│   │   ├── metrics.py        # Performance metrics
│   │   ├── structured_logger.py # Structured logging
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
├── tests/                    # 🧪 Test Suite (204 tests)
│   ├── __init__.py
│   ├── conftest.py           # Pytest fixtures
│   ├── test_ai_core.py       # AI core tests
│   ├── test_ai_integration.py # AI integration tests
│   ├── test_circuit_breaker.py
│   ├── test_consolidator.py  # Memory consolidator
│   ├── test_content_processor.py
│   ├── test_database.py
│   ├── test_emoji_voice.py
│   ├── test_error_recovery.py
│   ├── test_guardrails.py
│   ├── test_memory_modules.py
│   ├── test_music_integration.py
│   ├── test_performance_tracker.py
│   ├── test_rate_limiter.py
│   ├── test_spotify_integration.py
│   ├── test_summarizer.py
│   ├── test_tools.py
│   └── test_webhooks.py
│
├── docs/                     # 📚 Documentation
│   └── CODE_AUDIT_GUIDE.md   # Code audit checklist
│
├── native_dashboard/         # 🖥️ Tauri Desktop Dashboard
│   ├── Cargo.toml            # Rust dependencies
│   ├── tauri.conf.json       # Tauri configuration
│   ├── README.md             # Dashboard documentation
│   ├── src/
│   │   ├── main.rs           # Tauri commands
│   │   ├── bot_manager.rs    # Bot process control
│   │   └── database.rs       # SQLite queries
│   ├── ui/
│   │   ├── index.html        # Dashboard UI
│   │   ├── styles.css        # Dark theme
│   │   └── app.js            # Frontend logic
│   └── icons/
│       └── icon.ico          # App icon
│
└── data/                     # 💾 Runtime Data
    ├── bot_database.db       # SQLite database
    └── db_export/            # JSON exports for backup
```

---

## 🏗️ Architecture

### Core Flow

```
User Message
    │
    ▼
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   ai.py     │────▶│  logic.py    │────▶│ Gemini API  │
│ (Discord)   │     │ (Processing) │     │ (Google)    │
└─────────────┘     └──────────────┘     └─────────────┘
                           │
           ┌───────────────┼───────────────┐
           ▼               ▼               ▼
    ┌───────────┐   ┌───────────┐   ┌───────────┐
    │ RAG.py    │   │ guardrails│   │ storage.py│
    │ (Memory)  │   │ (Safety)  │   │ (Persist) │
    └───────────┘   └───────────┘   └───────────┘
```

### Key Classes

| Class | File | Purpose |
|-------|------|---------|
| `ChatManager` | `logic.py` | Main AI chat orchestration |
| `MemorySystem` | `rag.py` | FAISS-based long-term memory |
| `HistoryManager` | `history_manager.py` | Smart context trimming |
| `EntityMemoryManager` | `entity_memory.py` | Character facts storage |
| `Database` | `database.py` | Async SQLite singleton |
| `CircuitBreaker` | `circuit_breaker.py` | API failure protection |
| `RateLimiter` | `rate_limiter.py` | Request throttling |

---

## ⚙️ Configuration

### Environment Variables (.env)

```env
# Discord
DISCORD_TOKEN=your_token
GUILD_ID_MAIN=123456789
GUILD_ID_RP=123456789

# Gemini API
GEMINI_API_KEY=your_api_key
GEMINI_MODEL=gemini-3-pro-preview

# Spotify (Optional)
SPOTIPY_CLIENT_ID=your_client_id
SPOTIPY_CLIENT_SECRET=your_client_secret

# Owner
CREATOR_ID=your_discord_id
```

### constants.py

ไฟล์ `cogs/ai_core/data/constants.py` เก็บ config ที่ load จาก environment:
- `GUILD_ID_*` - Server IDs
- `CHANNEL_ID_*` - Channel IDs  
- `GEMINI_API_KEY` - API key
- `GAME_SEARCH_KEYWORDS` - Keywords ที่ force Google Search

### Persona & Roleplay Files

Bot จะ auto-fallback ไปใช้ `*_example.py` ถ้าไม่มี custom files:

```bash
# Copy examples to create your own
cp cogs/ai_core/data/faust_data_example.py cogs/ai_core/data/faust_data.py
cp cogs/ai_core/data/roleplay_data_example.py cogs/ai_core/data/roleplay_data.py
```

**faust_data.py** - AI Personality:
| Variable | Description |
|----------|-------------|
| `FAUST_INSTRUCTION` | Main system prompt / personality |
| `FAUST_DM_INSTRUCTION` | DM-specific behavior |
| `FAUST_SANDBOX` | Unrestricted mode prompt |
| `FAUST_CODE_OVERRIDE` | Code mode prompt |
| `ESCALATION_FRAMINGS` | Fallback prompts when AI refuses |

**roleplay_data.py** - RP System:
| Variable | Description |
|----------|-------------|
| `WORLD_LORE` | Universe/setting description |
| `ROLEPLAY_PROMPT` | RP assistant instructions |
| `SERVER_CHARACTERS` | Character list with image paths |
| `SERVER_AVATARS` | Guild-specific webhook avatar mappings |
| `SERVER_LORE` | Guild-to-lore mapping |

**Character Images:**
```
assets/RP/              # Large images for AI to see
└── AVATARS/            # Small images for webhook avatars
```

---

## 🧠 AI Core Deep Dive

### 1. Chat Processing (`logic.py`)

**Main method:** `ChatManager.process_chat()`


```
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

### 2. Unrestricted Mode (`guardrails.py`)

Channels ที่เปิด unrestricted mode จะ:
- Bypass all input/output validation
- Get special "Creative Writing" framing in system prompt
- Stored persistently in `unrestricted_channels.json`

```python
# Enable unrestricted
from cogs.ai_core.processing.guardrails import enable_unrestricted
enable_unrestricted(channel_id)

# Check status
from cogs.ai_core.processing.guardrails import is_unrestricted
if is_unrestricted(channel_id):
    # No guardrails
```

### 3. RAG System (`rag.py`)

FAISS-based memory retrieval:
- **Embedding:** sentence-transformers
- **Hybrid Search:** Semantic + keyword + time decay
- **Auto-indexing:** Conversations automatically indexed

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

ป้องกัน cascading failures:
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

Token bucket algorithm:
- Per-user, per-channel, per-guild limits
- Adaptive limits based on circuit state
- Configurable cooldown messages

### Self Healer (`self_healer.py`)

Auto-recovery:
- Detect duplicate bot instances
- Force-reset stuck locks (>120s)
- PID file management

---

## 💾 Database

### Schema (SQLite)

| Table | Purpose |
|-------|---------|
| `ai_history` | Chat history per channel |
| `ai_metadata` | Session settings |
| `entity_memories` | Character/entity facts |
| `long_term_facts` | Permanent user facts |
| `rag_memories` | Vector embeddings |
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
python dev_watcher.py
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
# In cogs/ai.py or new cog file
@commands.command()
async def mycommand(self, ctx):
    await ctx.send("Hello!")
```

### Debug AI Issues

```
!ai-debug     # Show session info
!ai-trace     # Show last request details
!ai-stats     # Show performance metrics
!ai-perf      # Show latency stats
```

---

## ⚠️ Known Gotchas

1. **Lock Timeout:** Locks stuck >120s will auto-reset (see `process_chat`)
2. **Short Response Detection:** `detect_refusal()` only checks patterns, not length
3. **Streaming Timeout:** 45s default, falls back to non-streaming
4. **Memory Cleanup:** Old RAG entries need periodic pruning

---

## 📚 Further Reading

- [discord.py Documentation](https://discordpy.readthedocs.io/)
- [Google Gemini API](https://ai.google.dev/)
- [FAISS Documentation](https://github.com/facebookresearch/faiss)

---

*Documentation last updated: January 19, 2026 - Zero-Bug Baseline Achieved*
