# Release Notes v3.3.14

**Release Date:** March 13, 2026

## 🛡️ Security Fixes (6 fixes)

### Critical
- **Fix: AI could ping @everyone/@here via generated responses** — Bot had no default `AllowedMentions`, meaning AI-generated `@everyone` or `@here` would actually mass-ping. Added `AllowedMentions(everyone=False, roles=False)` to `create_bot()` plus inline `@everyone`/`@here` sanitization in all AI response send paths. (`bot.py`, `cogs/ai_core/logic.py`)

- **Fix: `safe_delete()` path traversal vulnerability** — `safe_delete()` in music cog accepted any filename and called `Path(filename).unlink()` without validation. An attacker could craft a filename like `../../config.py` to delete arbitrary files. Now validates path is within `temp/` directory using `Path.resolve()` and `is_relative_to()`. (`cogs/music/cog.py`)

- **Fix: SQL column name injection in `increment_user_stat()`** — Used f-string interpolation for column names (`f"UPDATE ... SET {stat_name} = {stat_name} + 1"`). Now uses a whitelist dict mapping stat names to bracket-quoted column names. (`utils/database/database.py`)

### Medium
- **Fix: Guardrails import failure was silent** — If `guardrails` module failed to import, the bot silently fell back to no safety checks. Now logs `logging.critical()` so the failure is visible. (`cogs/ai_core/logic.py`)

- **Fix: Logger could leak tokens/API keys** — Added `SensitiveDataFilter` with regex patterns matching Discord bot tokens, API keys (`key=`, `token=`, `secret=`), and generic secrets. Filter applied to all log handlers. (`utils/monitoring/logger.py`)

- **Fix: URL cache race condition** — `_url_cache` dict had no locking, allowing concurrent coroutines to read/write/evict simultaneously. Added `asyncio.Lock` for all cache operations. (`utils/web/url_fetcher.py`)

## 🔧 Reliability Fixes (5 fixes)

- **Fix: Circuit breaker mixed `asyncio.Lock` + `threading.Lock`** — Async methods used `asyncio.Lock` while sync methods used `threading.Lock`, creating a race condition window. Removed `asyncio.Lock`; async methods now delegate directly to sync methods using only `threading.Lock`. (`utils/reliability/circuit_breaker.py`)

- **Fix: Music queue had no locking** — `save_queue()` operated on shared `self.queues` and `self.volumes` dicts without synchronization. Added per-guild `asyncio.Lock` via `_get_lock(guild_id)`. (`cogs/music/queue.py`)

- **Fix: `error_recovery` double-locking risked deadlock** — `_get_backoff_state_async()` acquired both `_backoff_states_async_lock` (asyncio.Lock) and `_backoff_states_lock` (threading.Lock). Removed the redundant asyncio.Lock. (`utils/reliability/error_recovery.py`)

- **Fix: Self-healer process detection used substring matching** — `"bot.py" in cmdline_str` would match unrelated processes like `my_bot.py` or paths containing `bot.py`. Now uses `PureWindowsPath(arg).name` to compare exact filenames. (`utils/reliability/self_healer.py`)

- **Fix: `asyncio.TimeoutError` not caught on Python 3.10** — `except TimeoutError:` in dashboard chat handler didn't catch `asyncio.TimeoutError` on Python 3.10 (where they are separate classes). Changed to `except (TimeoutError, asyncio.TimeoutError):`. (`cogs/ai_core/api/dashboard_chat.py`)

## 🧪 Test Fixes (2 fixes)

- **Fix: `test_dashboard_chat.py` mock spec failures** — `FakeChunk` used `MagicMock()` for parts, which auto-created truthy `function_call` attributes and failed Pydantic validation in `google-genai`. Replaced with real `genai_types.Part` and `genai_types.Content` objects. (`tests/test_dashboard_chat.py`)

- **Fix: `test_thought_as_string` used invalid `types.Part` constructor** — `types.Part(thought="string")` fails Pydantic validation since `thought` is strictly boolean. Changed to `SimpleNamespace` for this edge-case test. (`tests/test_dashboard_chat.py`)

## 📊 Test Suite
- **2,926 passed**, 0 failed, 2 warnings (harmless aiosqlite DeprecationWarning)

## Files Changed
- **Modified:** 11 source files, 1 test file, 6 docs
- **Security:** 6 fixes | **Reliability:** 5 fixes | **Tests:** 2 fixes
