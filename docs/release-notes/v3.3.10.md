# 📋 Release Notes - v3.3.10

**Release Date:** January 25, 2026 (Updated: February 10, 2026)  
**Type:** Patch Release (Security & Reliability Improvements)

---

## 🔒 Security & Reliability - Deep Code Audit

### Exception Handling Improvements
Improved exception handling across the entire project from broad `except Exception` to specific exceptions:
- Prevent hiding unexpected bugs
- Make debugging easier
- Improve code safety

| File | Change |
|------|--------|
| `database.py` | `except Exception` → `except aiosqlite.OperationalError` (ALTER TABLE) |
| `rag.py` | `except Exception` → `except (ValueError, TypeError, AttributeError)` (datetime) |
| `views.py` | `except Exception` → `except (discord.NotFound, discord.HTTPException)` |
| `guardrails.py` | `except Exception` → `except (json.JSONDecodeError, OSError, ValueError)` |
| `consolidator.py` | Split into parsing errors vs unexpected errors |
| `summarizer.py` | Split into specific exception types |
| `health_client.py` | `except Exception` → `except (aiohttp.ClientError, asyncio.TimeoutError)` |
| `logic.py` | 7 broad exceptions → specific types (aiohttp, asyncio, KeyError, etc.) |
| `response_sender.py` | `except Exception` → `except (discord.HTTPException, Forbidden, NotFound)` |
| `media_processor.py` | `except Exception` → `except (OSError, ValueError, Image.DecompressionBombError)` |

### Memory Bounds & Eviction
Added limits to prevent unbounded memory growth:

| Component | Limit | Eviction Strategy |
|-----------|-------|-------------------|
| `RateLimiter` | 10,000 buckets | LRU (oldest first) |
| `MessageQueue` | 5,000 channels, 50 pending/channel | LRU eviction |
| `StateTracker` | 2,000 channels, 100 chars/channel | Oldest eviction |

### Resource Leak Fixes
- **PIL Images:** Added `try/finally` blocks for proper Image cleanup
  - `media_processor.py` - `is_animated_gif()`, `convert_gif_to_video()`
  - `media_rust.py` - Image processing functions

### Safe Shutdown
- `cog.py` (Music): Added `_safe_run_coroutine()` helper for `asyncio.run_coroutine_threadsafe`
- Prevents unhandled exceptions during shutdown

### Configuration
- `pyproject.toml`: Changed from blanket deprecation ignore to selective (`discord.*`, `aiohttp.*`, `google.*`)

---

## 📝 Documentation Updates

- `DEVELOPER_GUIDE.md`: 
  - Added Phase 6 - Deep Code Audit (18 items)
  - Added Known Gotchas #10-11
  - Updated date and version
- `docs/CODE_AUDIT_GUIDE.md`: Updated date

---

## 📊 Test Results

```
===================== 3,157 passed in 10.24s =====================
```

✅ All 3,157 tests passing  
✅ 0 errors after changes  
✅ 126 test files

---

## 📁 Files Changed (18 files)

### Core AI Logic
- `cogs/ai_core/logic.py` - 7 exception fixes + import aiohttp
- `cogs/ai_core/response/response_sender.py` - Exception fix + import discord
- `cogs/ai_core/media_processor.py` - PIL cleanup + exception fixes

### Memory Systems  
- `cogs/ai_core/memory/rag.py` - Datetime exception fix
- `cogs/ai_core/memory/consolidator.py` - Split exceptions
- `cogs/ai_core/memory/state_tracker.py` - Memory bounds
- `cogs/ai_core/memory/summarizer.py` - Split exceptions

### Processing & Safety
- `cogs/ai_core/processing/guardrails.py` - Specific exceptions
- `cogs/ai_core/core/message_queue.py` - Memory bounds

### Music
- `cogs/music/cog.py` - Safe coroutine helper
- `cogs/music/views.py` - Discord exception fix

### Utilities
- `utils/database/database.py` - SQLite exception fix
- `utils/monitoring/health_client.py` - HTTP exception fix
- `utils/reliability/rate_limiter.py` - Memory bounds
- `utils/media/media_rust.py` - PIL cleanup

### Config & Docs
- `config.py` - Documentation clarification
- `pyproject.toml` - Selective deprecation warnings
- `DEVELOPER_GUIDE.md` - Phase 6 updates
- `docs/CODE_AUDIT_GUIDE.md` - Date update

---

## ⬆️ Upgrade Instructions

```bash
# Pull latest changes
git pull origin main

# New optional environment variables (add to .env if needed):
# DASHBOARD_WS_TOKEN=your_secret_token   # Auth for WebSocket dashboard
# DASHBOARD_ALLOW_UNRESTRICTED=false      # Gate unrestricted mode in dashboard
# HEALTH_API_HOST=127.0.0.1              # Now defaults to localhost (was 0.0.0.0)

# No new dependencies required
# Just restart the bot
python bot.py
```

---

## 🔒 Security Hardening (February 10, 2026)

### SSRF Protection (Go Services)
- **DNS rebinding prevention:** `ssrfSafeDialContext()` validates resolved IPs at connect time, not just at request start
- **IPv6 coverage:** Pre-parsed `privateNetworks` now includes IPv4-mapped IPv6 ranges (`::ffff:127.0.0.0/104`, etc.)
- **Localhost binding:** Both Go services (`url_fetcher`, `health_api`) now bind to `127.0.0.1` by default instead of `0.0.0.0`
- **Configurable:** `HEALTH_API_HOST` env var allows overriding bind address when needed

### Dashboard Security
- **WebSocket authentication:** `DASHBOARD_WS_TOKEN` env var required for dashboard connections
- **Origin check hardened:** Prefix matching now requires delimiter (`:` or `/`) to prevent subdomain bypass (e.g., `evil-localhost.com`)
- **Unrestricted mode gated:** Requires `DASHBOARD_ALLOW_UNRESTRICTED=true` env var to activate

### Permission & Injection Protection
- **AI permission allowlists:** `_SAFE_PERMISSIONS` / `_DANGEROUS_PERMISSIONS` frozensets block `administrator`, `manage_guild`, `ban_members`, etc. from AI-controlled server commands
- **Mention sanitization:** Webhook messages and tool executor outputs sanitize `<@&ID>` (role) and `<@ID>` (user) mentions with zero-width space
- **Path traversal:** `conversation_id` validated with `^[a-zA-Z0-9_-]+$` regex before file operations

### Prometheus Hardening
- **Metric allowlist:** `allowedMetricNames` rejects unknown metric names at push endpoints
- **Label allowlist:** `safeLabel()` restricts label values to known sets, preventing cardinality explosion

---

## 🛡️ Reliability Fixes (February 10, 2026)

| Component | Issue | Fix |
|-----------|-------|-----|
| `logic.py` | `asyncio.wait_for(lock.acquire())` deadlock | `asyncio.shield()` wrapper (CPython #42130) |
| `memory_manager.py` | GC can deadlock WeakRefCache | `threading.RLock()` instead of `Lock()` |
| `error_recovery.py` | Sync backoff state in async function | `await _get_backoff_state_async()` |
| `shutdown_manager.py` | Event/Lock bound to wrong loop at import | Lazy creation via getter methods |
| `storage.rs` | Data loss on crash (unflushed mmap) | `mmap.flush()` after every `push()` |
| `lib.rs` | Corrupted save file on crash | Atomic write via temp file + rename |
| `cog.py` | Queue lost on cog reload | Save all queues before clearing in `cog_unload` |
| `cog.py` | Cross-guild retry state leak | Per-guild tracking (`_play_next_retries_{guild_id}`) |

---

## ✅ Correctness Fixes (February 10, 2026)

| Component | Issue | Fix |
|-----------|-------|-----|
| `logic.py` | `CancelledError` conflated with message interrupts | New `_NewMessageInterrupt` exception |
| `logic.py` | Naive timestamps in history | `datetime.now(datetime.timezone.utc)` |
| `queue.py` | O(n²) shuffle on deque | Convert to list → shuffle → extend back |
| `index.rs` | Keywords stale on re-add | Remove old associations, re-index |
| `resize.rs` | Skip-if-smaller on Fill/Stretch | Restrict to `Fit` mode via `matches!()` |
| `gif.rs` | Frames counted by GCE (optional) | Count Image Descriptor (0x2C) blocks |
| `lib.rs` | Stale entries on load | `entries.clear()` before loading |
| `logic.py` | MessageQueue leaks on eviction | Clean up `pending_messages`/`cancel_flags` |
| `database.py` | Global debounce drops exports | Per-channel `_export_pending_keys` |
| `url_fetcher.py` | Unbounded response body | `MAX_RESPONSE_SIZE = 5MB` |
| `fast_json.py` | `ensure_ascii` default mismatch | Aligned both branches to `False` |

---

## ⚠️ Breaking Changes

None - All changes are backward compatible.

> **Note:** `HEALTH_API_HOST` now defaults to `127.0.0.1` (was `0.0.0.0`). If you need external access to the Health API, set `HEALTH_API_HOST=0.0.0.0` in your environment.

---

**Full Changelog:** v3.3.9 → v3.3.10
