# Troubleshooting Guide

## Quick Diagnostics

```bash
# Check health
curl http://localhost:8080/health

# Check Prometheus metrics
curl http://localhost:9090/metrics  # Python metrics (PROMETHEUS_PORT, default 9090)

# Check logs
tail -f logs/bot.log
tail -f logs/bot_errors.log
```

## Common Issues

### Bot Won't Start

**Symptom:** Bot crashes immediately on startup.

1. **Missing `.env` file** — Copy `env.example` (note: no leading dot) and fill in required values:

   ```ini
   DISCORD_TOKEN=...           # required — บอตไม่สตาร์ทถ้าไม่มี
   ANTHROPIC_API_KEY=...       # เฉพาะ CLAUDE_BACKEND=api (ค่าเริ่มต้น cli ไม่ต้องใช้คีย์)
   ```

2. **Duplicate process running** — The self-healer checks for duplicates:

   ```powershell
   # Windows
   Get-Process -Name python | Where-Object { $_.CommandLine -match 'bot.py' }
   # Linux
   pgrep -f "python bot.py"
   ```

3. **Missing FFmpeg** — Music cog requires FFmpeg. Check:

   ```bash
   ffmpeg -version
   ```

   Bot sets an internal `_FFMPEG_MISSING` flag and skips the music cog if not found.

4. **Database locked** — Another process may have the DB open:

   ```bash
   fuser data/bot_database.db  # Linux
   ```

### Dashboard Can't Connect

**Symptom:** Native dashboard shows "Connection failed".

1. **Token mismatch** — `DASHBOARD_WS_TOKEN` must match between bot and dashboard.

2. **Port conflict** — Default is 8765. Check:

   ```bash
   netstat -tlnp | grep 8765
   ```

3. **TLS misconfiguration** — If `WS_REQUIRE_TLS=true`, both cert and key must be valid:

   ```ini
   WS_TLS_CERT_PATH=/path/to/cert.pem
   WS_TLS_KEY_PATH=/path/to/key.pem
   ```

### AI Not Responding

1. **API key invalid** — Check `ANTHROPIC_API_KEY` and `GEMINI_API_KEY`

2. **Rate limited** — Check `utils/reliability/rate_limiter.py` configs:
   - `ai_user`: 60 req/min per user
   - `ai_guild`: 240 req/min per guild

   (both are `adaptive=True` — the effective cap can be lowered dynamically under load)

3. **Circuit breaker open** — After consecutive failures, the circuit opens for 60s:

   ```bash
   # Check in Prometheus
   curl http://localhost:9090/metrics | grep circuit_breaker_state  # Python metrics (PROMETHEUS_PORT, default 9090)
   ```

4. **API failover** — Direct API failed, proxy should take over. Check endpoint URL:

   ```ini
   # Use the Anthropic API directly (this is the default — a sentinel, not a URL)
   ANTHROPIC_API_ENDPOINT=direct
   # Proxy override (whatever URL your proxy exposes)
   ANTHROPIC_PROXY_BASE_URL=https://your-proxy.example/v1
   ```

   The failover layer flips between these two endpoints automatically based on
   error rate; manual override via `ANTHROPIC_API_ENDPOINT` is for sticky pinning.

### High Memory Usage

The memory monitor triggers cache cleanup at configurable RSS thresholds:

- **Warning:** 1 GiB (default — env `BOT_MEMORY_WARNING_MB`)
- **Critical:** 1.5 GiB (default — env `BOT_MEMORY_CRITICAL_MB`)
- **Poll interval:** 30 s (default — env `BOT_MEMORY_CHECK_INTERVAL`)

These defaults target a typical container; raise on a workstation, lower for a
tight 512 MiB container. The previous 8 GiB/16 GiB defaults sat above the OOM
killer on every host the bot actually runs on, so cleanup never fired before the
process was killed — they're now env-tunable per deployment.

Check via:

```bash
curl http://localhost:9090/metrics | grep process_resident_memory  # Python metrics (PROMETHEUS_PORT, default 9090)
# or, for the bot's own report including the configured threshold:
curl http://localhost:8080/health/deep
```

Common causes:

- Large chat history cache (MAX_CACHE_SIZE=2000, CACHE_TTL=900s)
- RAG engine in-memory vectors
- Uncollected attachment data

### Document Attachments (Dashboard)

**Drag-drop doesn't attach files (only the 📎 button works):**

Tauri v2's native drag-drop intercepts file-drop events at the WebView2 layer, leaving the JS `event.dataTransfer.files` array empty. The dashboard ships with `dragDropEnabled: false` in `native_dashboard/tauri.conf.json` to disable the native handler and let the browser deliver drop events normally. If you customise the config, keep that flag off or re-implement using the Tauri drag-drop plugin.

**PDF upload "saved" but AI doesn't see the content:**

1. `pypdf` / `python-docx` must be installed: `pip install pypdf python-docx`
2. Encrypted PDFs are skipped silently — remove the password before uploading
3. Check `logs/bot.log` for lines starting with `📎 Saved document memory` — absence means extraction failed
4. Scanned PDFs with no text layer extract as empty; Claude still sees them as images for the upload turn (no persistence)

**Document memory not persisting across conversations:**

By design. Each conversation has its own scoped document library — uploads in conversation A won't appear in conversation B. If you want the same document visible in multiple conversations, re-upload it there (or edit-then-delete per file via the 📎 button in chat header).

**"Document too large" on a file under 32 MB:**

The post-auth WebSocket frame cap (`max_msg_size` in `ws_dashboard.py`) is sized to hold the worst legal payload in a single frame — every attachment at once: `MAX_DOCUMENTS` (5) × `MAX_DOCUMENT_SIZE_BYTES` (32 MB) + `MAX_IMAGES` (10) × `MAX_IMAGE_SIZE_BYTES` (10 MB) = 260 MB decoded, inflated ~33% for base64 plus content and headroom (≈ 351 MB). So a single sub-32 MB document is well under the frame cap — if you hit "Document too large", it's the per-document **raw** 32 MB limit (`MAX_DOCUMENT_SIZE_BYTES`) that rejects it (base64 size doesn't count against that raw check), and the 10 MB figure is the *per-image* limit (`MAX_IMAGE_SIZE_BYTES`). Split very large PDFs with a PDF editor, or trim the number of simultaneous attachments. (Before authentication the frame cap is only 4 KiB.)

**Storage caps are hit — oldest documents disappearing:**

`dashboard_document_memories` has hard caps in `document_extractor.py`:
- 500,000 chars per file
- 20,000,000 chars across all rows
- 200 rows total

When exceeded, the oldest memory is LRU-evicted. Bump `MAX_TOTAL_CHARS` / `MAX_ROWS` if you have a lot of long-form RP material.

### Database Issues

**Schema migration failed:**

```bash
# Check current schema version
python -c "
import sqlite3
conn = sqlite3.connect('data/bot_database.db')
print(conn.execute('PRAGMA user_version').fetchone())
"

# Migrations apply automatically on the next bot start (init_schema → run_migrations).
# To dump the current schema/tables without starting the bot (sqlite_master):
python scripts/maintenance/inspect_db.py
# (scripts/maintenance/check_db.py instead reports per-channel ai_history row counts.)
```

**WAL file growing large:**

```sql
PRAGMA wal_checkpoint(TRUNCATE);
```

**Database corruption:**

```bash
sqlite3 data/bot_database.db "PRAGMA integrity_check;"
```

## Environment Variables Reference

### Required

| Variable | Description |
| -------- | ----------- |
| `DISCORD_TOKEN` | Discord bot token — บอตไม่สตาร์ทถ้าไม่มี (ตัวเดียวที่ required จริง) |

> **`ANTHROPIC_API_KEY` ไม่ได้ required เสมอไป.** จำเป็นเฉพาะตอน `CLAUDE_BACKEND=api`; ค่าเริ่มต้น `cli`
> ใช้ Claude Code subscription (ไม่ต้องใช้คีย์). ถ้าไม่ตั้งเลย ฟีเจอร์ AI จะถูกปิดแต่บอตยังรันได้
> (ดู `config.py` → `validate_required_secrets` / `validate_optional_secrets`). `GEMINI_API_KEY`
> เป็น optional ล้วน (embeddings/RAG; degrade ได้ถ้าไม่มี).

### AI Configuration

| Variable | Default | Description |
| -------- | ------- | ----------- |
| `CLAUDE_MODEL` | `claude-opus-4-8` | Claude model name |
| `CLAUDE_MAX_TOKENS` | `128000` | Max output tokens per response |
| `CLAUDE_CONTEXT_WINDOW` | `1000000` | Input context window in tokens — Opus 4.8 supports 1M natively (no beta header, no long-context premium) on both the CLI subscription path and the direct API |
| `CLAUDE_BACKEND` | `cli` | Claude path for BOTH Discord chat and dashboard chat: `cli` (`claude -p` subprocess, Max subscription quota — default, no `ANTHROPIC_API_KEY` required) or `api` (Anthropic SDK, per-token billing — needs `ANTHROPIC_API_KEY`) |
| `CLAUDE_CODE_OAUTH_TOKEN` | `""` | Only needed when `CLAUDE_BACKEND=cli` and bot runs as a different OS user than the one logged into Claude Code. Generate with `claude setup-token`. |
| `CLAUDE_SUMMARIZATION_MODEL` | inherits `CLAUDE_MODEL` (`claude-opus-4-8` by default) | History summarisation model. Override with a cheaper model like `claude-haiku-4-5` if you want to trade quality for cost. |
| `CLAUDE_EFFORT` | `xhigh` | Effort level: `low` / `medium` / `high` / `xhigh` / `max`. Defaults to `xhigh` (deep Opus-tier reasoning, one tier below `max`); set `max` for the deepest reasoning, or a lower tier to reduce cost/latency. |
| `GEMINI_API_KEY` | `""` | Gemini API key |
| `GEMINI_MODEL` | `gemini-3.1-pro-preview` | Gemini model name |
| `ANTHROPIC_BASE_URL` | `""` | Custom API base URL |
| `ANTHROPIC_PROXY_BASE_URL` | `""` | Proxy API URL |
| `ANTHROPIC_API_ENDPOINT` | `direct` | Failover *mode* selector (a sentinel, not a URL): `direct` calls the Anthropic API directly; any other value pins the proxy. The failover layer flips between direct and `ANTHROPIC_PROXY_BASE_URL` automatically based on error rate. |
| `DEFAULT_AI_PROVIDER` | auto | Dashboard default (`gemini`/`claude`) |

### Discord IDs

| Variable | Description |
| -------- | ----------- |
| `GUILD_ID_MAIN` | Main server ID |
| `GUILD_ID_RP` | Roleplay server ID |
| `CREATOR_ID` | Bot owner's user ID |

### Dashboard

| Variable | Default | Description |
| -------- | ------- | ----------- |
| `WS_DASHBOARD_HOST` | `127.0.0.1` | Dashboard WS host |
| `WS_DASHBOARD_PORT` | `8765` | Dashboard WS port |
| `DASHBOARD_WS_TOKEN` | `""` | Bearer auth token (shared secret, compared byte-for-byte by the WS handshake). An empty value rejects all WS connections — set this OR enable `DASHBOARD_ALLOW_UNRESTRICTED=true` (NOT recommended outside localhost). |
| `WS_REQUIRE_TLS` | `false` | Require TLS |
| `DASHBOARD_CLI_ALLOW_WRITE` | `false` (off) | `CLAUDE_BACKEND=cli` only. When on, the dashboard's embedded `claude -p` may CREATE/EDIT files non-interactively (the chat UI can't answer an interactive "Allow?" prompt). Files-only: Bash, the web tools, NotebookEdit and subagents are denied. A PreToolUse write-guard hook (`cogs/ai_core/api/cli_write_guard.py`) is the authoritative boundary — it fails closed and denies any write whose canonical path is outside the allowed roots, so the repo, `.env`, `~/.claude`, `~/.ssh` and the home root are all rejected. Enable only on a trusted machine — uploaded documents are a prompt-injection surface. |
| `DASHBOARD_CLI_WRITE_DIRS` | Desktop / Documents / Downloads (+ OneDrive-redirected on Windows) | `os.pathsep`-separated list overriding the auto-approved write roots used by `DASHBOARD_CLI_ALLOW_WRITE`. Only directories that actually exist are honoured. |

### Monitoring

| Variable | Default | Description |
| -------- | ------- | ----------- |
| `HEALTH_API_PORT` | `8080` | Health API port |
| `HEALTH_API_TOKEN` | `""` | Health API bearer token |
| `ALERT_WEBHOOK_URL` | `""` | Discord webhook for alerts |
| `ALERT_COOLDOWN_SECONDS` | `300` | Alert dedup cooldown |

## Startup Scripts

| Script | Purpose |
| ------ | ------- |
| `scripts/startup/start.ps1` | Production (auto-restart, max 50 restarts) |
| `scripts/startup/start_dev.ps1` | Development mode |
| `scripts/startup/dev.bat` | Quick dev launcher |
| `scripts/startup/manager.ps1` | Start/stop/restart manager |

## Docker

```bash
# Production
docker compose -f docker/docker-compose.yml up -d

# Development (relaxed limits, source mounted)
docker compose -f docker/docker-compose.yml -f docker/docker-compose.dev.yml up -d

# Run tests in container
docker compose -f docker/docker-compose.yml -f docker/docker-compose.test.yml run --rm bot

# View logs
docker compose -f docker/docker-compose.yml logs -f bot
```

## Log Files

| File | Content |
| ---- | ------- |
| `logs/bot.log` | Main bot log |
| `logs/bot_errors.log` | Error-level only |
| `logs/dashboard_errors.log` | Dashboard errors |
| `logs/self_healer.log` | Self-healer diagnostics |
| `logs/crashes/` | Crash dumps |
