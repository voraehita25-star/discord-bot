# Architecture Overview

## System Diagram

```text
┌─────────────────────────────────────────────────────────────┐
│                       Discord API                            │
└──────────────────────────┬──────────────────────────────────┘
                           │ WebSocket / HTTP
┌──────────────────────────▼──────────────────────────────────┐
│                    MusicBot (Python 3.14)                     │
│  commands.AutoShardedBot                                     │
│                                                              │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │  AI Core    │  │  Music Cog   │  │  Other Cogs       │  │
│  │  (Claude +  │  │  (FFmpeg +   │  │  (spotify, etc.)  │  │
│  │   Gemini)   │  │   yt-dlp)    │  │                   │  │
│  └──────┬──────┘  └──────────────┘  └───────────────────┘  │
│         │                                                    │
│  ┌──────▼──────────────────────────────────────────────┐    │
│  │  Shared Infrastructure                               │    │
│  │  SQLite (WAL) │ Cache │ Rate Limiter │ Circuit Breaker│   │
│  └──────────────────────────────────────────────────────┘    │
└────┬──────────┬──────────┬──────────┬───────────────────────┘
     │ FFI      │ FFI      │ HTTP     │ HTTP
┌────▼────┐ ┌──▼────────┐ │    ┌─────▼──────┐
│rag_engine│ │media_proc.│ │    │url_fetcher │
│ (Rust)   │ │ (Rust)    │ │    │ (Go:8081)  │
└──────────┘ └───────────┘ │    └────────────┘
                           │
          ┌────────────────┼───────────────┐
     ┌────▼────┐  ┌────────▼───┐  ┌────────▼──────┐
     │Health API│  │Prometheus  │  │Dashboard WS   │
     │(:8080)   │  │(:9090)     │  │(:8765)        │
     └──────────┘  └────────────┘  └───────┬───────┘
                                           │ WebSocket
                                   ┌───────▼───────┐
                                   │Native Dashboard│
                                   │(Tauri + Rust)  │
                                   └───────────────┘
```

## Startup Flow

1. `load_dotenv()` — โหลด `.env`
2. `setup_smart_logging()` — ตั้งค่า logging
3. `smart_startup_check()` — ตรวจ duplicate process
4. `bootstrap()` — สร้าง directories, ตรวจ FFmpeg
5. `create_bot()` → `MusicBot(AutoShardedBot)`
6. `setup_hook()`:
   - ThreadPoolExecutor (2× CPU cores)
   - โหลด cogs จาก `cogs/` directory
   - เริ่ม Dashboard WebSocket Server
7. `on_ready()`:
   - Health API (port 8080)
   - Prometheus metrics (port 9090)
   - Memory Monitor

## Cog Structure

| Cog | Path | Description |
| ----- | ------ | ------------- |
| AI Core | `cogs/ai_core/ai_cog.py` | AI chat ด้วย Claude/Gemini + context management |
| Music | `cogs/music/cog.py` | เล่นเพลงจาก YouTube/Spotify ด้วย FFmpeg |
| Spotify | `cogs/spotify_handler.py` | Spotify integration |

### AI Core Submodules

| Module | Purpose |
| -------- | --------- |
| `api/` | API failover (direct/proxy), WebSocket dashboard, chat handlers |
| `cache/` | AI response caching |
| `commands/` | Slash commands (debug, memory, server) |
| `core/` | Context builder, message queue, performance |
| `data/` | Constants, env vars, roleplay data |
| `memory/` | Entity memory, RAG, summarizer, state tracker, conversation branching |
| `processing/` | Content safety guardrails |
| `prompts/` | System prompt templates (YAML) |
| `response/` | Response formatting mixin |
| `tools/` | AI tool definitions and executor |

## External Services

| Service | Language | Port | Protocol | Purpose |
| --------- | ---------- | ------ | ---------- | --------- |
| url_fetcher | Go | 8081 | HTTP | URL content extraction with SSRF protection |
| health_api | Go | 8082 | HTTP | Prometheus metrics for external monitoring |
| media_processor | Rust (PyO3) | FFI | In-process | Image encode/resize/GIF (JPEG, PNG, GIF, WebP) |
| rag_engine | Rust (PyO3) | FFI | In-process | Cosine similarity, SIMD-optimized vector search |
| native_dashboard | Rust (Tauri 2) | Desktop | WebSocket | Desktop dashboard with WebView2 |

## Communication Patterns

| From → To | Protocol | Details |
| ----------- | ---------- | --------- |
| Bot ↔ Discord | WS/HTTP | discord.py AutoShardedBot |
| Bot → Claude API | HTTP | api_failover.py — direct + proxy failover; hybrid prompt caching (explicit system + automatic history, 5-min ephemeral). Used by the Discord AI cog and by the dashboard chat when `CLAUDE_BACKEND=api` (default). |
| Dashboard → Claude CLI | subprocess | Optional subscription-based path (`CLAUDE_BACKEND=cli`): spawns `claude -p --output-format stream-json` and bills against the user's Claude Code Max plan instead of per-token API. Dashboard chat only — Discord-side AI features still use the SDK path above. |
| Bot → Gemini API | HTTP | RAG embeddings, dashboard chat |
| Dashboard ↔ Bot | WebSocket | :8765, HMAC auth via `DASHBOARD_WS_TOKEN` |
| Bot → url_fetcher | HTTP | Python → Go service on :8081 |
| Bot → media_processor | FFI (PyO3) | Direct Python ↔ Rust calls |
| Bot → rag_engine | FFI (PyO3) | Direct Python ↔ Rust calls |
| Bot ↔ SQLite | aiosqlite | WAL mode, 32-slot connection pool |
| Dashboard ↔ SQLite | rusqlite | Direct read of `bot_database.db` |

## Database

SQLite at `data/bot_database.db` with WAL mode, `mmap_size=2GB`, 32-connection pool, write serialization lock. See [SCHEMA.md](SCHEMA.md) for full schema.

## Reliability Stack

| Component | Module |
| ----------- | -------- |
| Self-Healer | `utils/reliability/self_healer.py` |
| Memory Monitor | `utils/reliability/memory_manager.py` |
| Circuit Breaker | `utils/reliability/circuit_breaker.py` |
| Rate Limiter | `utils/reliability/rate_limiter.py` |
| Error Recovery | `utils/reliability/error_recovery.py` |
| Shutdown Manager | `utils/reliability/shutdown_manager.py` |

## Monitoring

| Service | Port | Description |
| --------- | ------ | ------------- |
| Health API | 8080 | HTTP health endpoint (Python, stdlib) |
| Prometheus | 9090 | prometheus_client metrics |
| Go Health | 8082 | Go Prometheus + health checks |
| Sentry | — | Error tracking (optional) |
| Discord Webhook | — | Critical failure alerts |
