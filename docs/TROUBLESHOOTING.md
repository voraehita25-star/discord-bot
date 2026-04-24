# Troubleshooting Guide

## Quick Diagnostics

```bash
# Check health
curl http://localhost:8080/health

# Check Prometheus metrics
curl http://localhost:9090/metrics

# Check logs
tail -f logs/bot.log
tail -f logs/bot_errors.log
```

## Common Issues

### Bot Won't Start

**Symptom:** Bot crashes immediately on startup.

1. **Missing `.env` file** — Copy `.env.example` and fill in required values:

   ```ini
   DISCORD_TOKEN=...
   ANTHROPIC_API_KEY=...
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

   Bot sets `FFMPEG_MISSING=1` and skips music cog if not found.

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
   - `ai_user`: 10 req/min per user
   - `ai_guild`: 30 req/min per guild

3. **Circuit breaker open** — After consecutive failures, the circuit opens for 60s:

   ```bash
   # Check in Prometheus
   curl http://localhost:9090/metrics | grep circuit_breaker_state
   ```

4. **API failover** — Direct API failed, proxy should take over. Check endpoint:

   ```ini
   ANTHROPIC_API_ENDPOINT=direct  # or proxy
   ```

### High Memory Usage

The memory monitor triggers warnings at thresholds:

- **Warning:** 8GB
- **Critical:** 16GB (for 32GB system)

Check via:

```bash
curl http://localhost:9090/metrics | grep process_resident_memory
```

Common causes:

- Large chat history cache (MAX_CACHE_SIZE=2000, CACHE_TTL=900s)
- RAG engine in-memory vectors
- Uncollected attachment data

### Database Issues

**Schema migration failed:**

```bash
# Check current schema version
python -c "
import sqlite3
conn = sqlite3.connect('data/bot_database.db')
print(conn.execute('PRAGMA user_version').fetchone())
"

# Run migrations manually
python scripts/maintenance/check_db.py
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
| `DISCORD_TOKEN` | Discord bot token |
| `ANTHROPIC_API_KEY` | Claude API key |

### AI Configuration

| Variable | Default | Description |
| -------- | ------- | ----------- |
| `CLAUDE_MODEL` | `claude-opus-4-7` | Claude model name |
| `CLAUDE_MAX_TOKENS` | `128000` | Max output tokens |
| `GEMINI_API_KEY` | `""` | Gemini API key |
| `GEMINI_MODEL` | `gemini-3.1-pro-preview` | Gemini model name |
| `ANTHROPIC_BASE_URL` | `""` | Custom API base URL |
| `ANTHROPIC_PROXY_BASE_URL` | `""` | Proxy API URL |
| `ANTHROPIC_API_ENDPOINT` | `direct` | `direct` or `proxy` |
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
| `DASHBOARD_WS_TOKEN` | `""` | Auth token (HMAC) |
| `WS_REQUIRE_TLS` | `false` | Require TLS |

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
