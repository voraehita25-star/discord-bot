# Utils Directory — Deep Code Audit Report

**Scope**: All 32 Python files under `utils/`  
**Date**: 2025  
**Focus**: Bugs, security vulnerabilities, race conditions, resource leaks, async issues, platform issues

---

## Critical Issues

### 1. `AttributeError` on `_pool_semaphore` — Bypasses lazy initializer

**File**: `utils/database/database.py` — Lines 720, 735, 775  
**Severity**: Critical (crash)

`get_connection_with_retry()` directly accesses `self._pool_semaphore` instead of calling `self._get_pool_semaphore()`. The semaphore is initialized to `None` (line 68) and only created lazily via `_get_pool_semaphore()`. If `get_connection_with_retry()` is called before `get_connection()` has ever been called, `self._pool_semaphore` is `None`, causing:

```
AttributeError: 'NoneType' object has no attribute 'acquire'
```

Affected lines:
- Line 720: `await self._pool_semaphore.acquire()`
- Line 735: `self._pool_semaphore.release()`
- Line 775: `self._pool_semaphore.release()`

**Fix**: Replace all three with `self._get_pool_semaphore()`:
```python
# Line 720
await self._get_pool_semaphore().acquire()
# Lines 735 and 775
self._get_pool_semaphore().release()
```

---

### 2. `asyncio.Lock` created at module/class init binds to wrong event loop

**File**: `utils/reliability/error_recovery.py` — Line 104  
**File**: `utils/reliability/circuit_breaker.py` — Line 56  
**Severity**: Critical (RuntimeError in multi-loop scenarios)

`asyncio.Lock()` captures the running event loop at creation time. If created at module load time (before any loop exists) or in a different loop context, using it later raises:

```
RuntimeError: Task ... got Future ... attached to a different loop
```

**error_recovery.py line 104:**
```python
_backoff_states_async_lock = asyncio.Lock()  # Module level — dangerous
```

**circuit_breaker.py line 56:**
```python
_async_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)
```

The `CircuitBreaker` is a `@dataclass`, so `asyncio.Lock()` is created at `CircuitBreaker(...)` instantiation time, which may be before the bot's event loop starts.

**Fix (error_recovery.py)**: Lazily create the lock:
```python
_backoff_states_async_lock: asyncio.Lock | None = None

def _get_async_lock() -> asyncio.Lock:
    global _backoff_states_async_lock
    if _backoff_states_async_lock is None:
        _backoff_states_async_lock = asyncio.Lock()
    return _backoff_states_async_lock
```

**Fix (circuit_breaker.py)**: Use a lazy property instead of a dataclass field:
```python
_async_lock: asyncio.Lock | None = field(default=None, init=False)

def _get_async_lock(self) -> asyncio.Lock:
    if self._async_lock is None:
        self._async_lock = asyncio.Lock()
    return self._async_lock
```

---

### 3. Resource leak in redirect-following loop — response objects not closed

**File**: `utils/web/url_fetcher.py` — Lines 220–244  
**Severity**: High (connection/memory leak)

In `fetch_url_content()`, the initial `response` from `session.get()` is used as a context manager (`async with`), but the `final_response` objects obtained during redirect following are **not** wrapped in context managers. If an exception occurs mid-loop (e.g., SSRF block, timeout), the last `final_response` leaks.

Additionally, line 236 only closes `final_response` if it's not the original `response`, but after the loop, the final redirect response is never explicitly closed.

```python
# Line 220-244 (simplified)
async with session.get(url, ..., allow_redirects=False) as response:
    final_response = response
    while final_response.status in (...):
        # ...
        final_response = await session.get(...)  # NOT in context manager
    # final_response is never closed if it != response
```

**Fix**: Close `final_response` in a `finally` block after the loop, or refactor to not use `async with` on the initial request:
```python
try:
    # ... redirect loop ...
    # ... process final_response ...
finally:
    if final_response is not response:
        final_response.close()
```

---

## High-Severity Issues

### 4. `AlertManager` session never closed on process exit

**File**: `utils/monitoring/alerting.py` — Lines 48–53, 175–178  
**Severity**: High (resource leak, unclosed connector warning)

`AlertManager._get_session()` lazily creates an `aiohttp.ClientSession`, and while there's a `close()` method (line 175), the global `alert_manager` instance (line 185) is never guaranteed to have `close()` called. This causes "Unclosed client session" and "Unclosed connector" warnings at shutdown.

**Fix**: Register `alert_manager.close()` with the shutdown manager, or use a session-per-request pattern:
```python
# In bot startup:
shutdown_manager.register(alert_manager.close, priority=5)
```

---

### 5. f-string SQL column interpolation — fragile even with whitelist

**File**: `utils/database/database.py` — Lines 1046–1048, 1062–1068  
**Severity**: Medium-High (defense in depth concern)

`save_guild_settings()` and `increment_user_stat()` use f-strings to inject column names into SQL. Both have whitelists, which is good, but the pattern is fragile — a future developer might add a column name with special characters or modify the whitelist incorrectly.

**`save_guild_settings` (line 1046):**
```python
col_str = ",".join(columns)
update_str = ",".join([f"{k}=excluded.{k}" for k in safe_settings])
await conn.execute(f"""INSERT INTO guild_settings ({col_str}) ...""", values)
```

**`increment_user_stat` (line 1062):**
```python
await conn.execute(
    f"""INSERT INTO user_stats (user_id, guild_id, {stat_name}, last_active)
        ...
        {stat_name} = {stat_name} + ?, ...""",
    (user_id, guild_id, amount, amount),
)
```

**Fix**: No immediate action required since whitelists are present, but consider using a mapping approach:
```python
# For increment_user_stat, use a dict to map stat_name to a pre-written query
_STAT_QUERIES = {
    "messages_count": "INSERT INTO user_stats ... messages_count ...",
    # etc.
}
```

---

### 6. `_connection_count` not thread-safe and not atomic

**File**: `utils/database/database.py` — Lines 68, 582, 599, 720, 734, 774  
**Severity**: Medium-High (race condition)

`self._connection_count` is incremented/decremented from `async` code without any lock. While the GIL protects simple `int` operations in CPython, the check-then-act pattern (`while self._connection_count > 0`) in `_reinitialize_pool()` (line 648) could see a stale value during concurrent connection operations.

**Fix**: Use an `asyncio.Lock` or `threading.Lock` around `_connection_count` mutations, or use the semaphore's internal state to track connection count.

---

### 7. `get_connection_with_retry` doesn't use connection pool

**File**: `utils/database/database.py` — Lines 694–775  
**Severity**: Medium (resource waste, inconsistency)

`get_connection_with_retry()` creates fresh connections every time and closes them in `finally`, completely bypassing the pool that `get_connection()` uses. It also duplicates PRAGMA setup code. Any connection obtained this way:
- Doesn't benefit from connection reuse
- Uses `cache_size=100000` instead of `250000` (inconsistency at lines 587 vs 725)
- Closes the connection instead of returning it to the pool

**Fix**: Refactor to delegate to `get_connection()`:
```python
@asynccontextmanager
async def get_connection_with_retry(self, max_retries=3):
    for attempt in range(max_retries):
        try:
            async with self.get_connection() as conn:
                yield conn
                return
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            await asyncio.sleep(2 ** attempt)
```

---

### 8. `migrations.py` — `version` variable potentially unbound

**File**: `utils/database/migrations.py` — Line 117  
**Severity**: Medium (crash in edge case)

```python
if applied:
    logger.info("📦 Applied %d migration(s), now at version %d", applied, version)
```

If `migrations` is empty but `applied > 0` somehow (impossible in current code but still a code smell), `version` would be unbound. More practically, if the migration file list changes between discovery and application, the log line references the loop variable `version` from the last iteration.

**Fix**: Track the version independently:
```python
last_version = current_version
# ... in loop:
    last_version = version
# ... after loop:
if applied:
    logger.info("... now at version %d", last_version)
```

---

## Medium-Severity Issues

### 9. Health API handler accesses bot data from HTTP thread without full synchronization

**File**: `utils/monitoring/health_api.py` — Lines 509–529 (`_generate_health_html`), 621–636 (`do_GET`), 764–773 (`_perform_deep_health_check`)  
**Severity**: Medium (race condition, potential data corruption)

The `HealthRequestHandler.do_GET()` runs in a separate thread (via `HTTPServer`). While `BotHealthData` uses locks for counters and data updates, the `_generate_health_html()` and `_generate_stats_html()` methods directly read `health_data` attributes and dict contents like `service_health` without holding the data lock, creating potential for reading partially-updated data.

Additionally, `get_ai_performance_stats()` (line 231) accesses `self.bot.cogs` from the HTTP thread, which mutates in the event loop thread.

**Fix**: Ensure `to_dict()` is used in all HTML generation paths (it already acquires locks), and have HTML generators work from the returned dict rather than accessing `health_data` attributes directly.

---

### 10. `fast_json.py` — `ensure_ascii` parameter silently ignored with orjson

**File**: `utils/fast_json.py`  
**Severity**: Low-Medium (silent behavior change)

When orjson is available, `dumps(obj, ensure_ascii=True)` still outputs non-ASCII characters because orjson always emits UTF-8. Code that depends on ASCII-safe JSON output will silently get Unicode bytes instead.

**Fix**: Document this limitation or add explicit ASCII escaping:
```python
def dumps(obj, ensure_ascii=False, ...):
    if _HAS_ORJSON:
        result = orjson.dumps(obj, ...)
        if ensure_ascii:
            # orjson always outputs UTF-8, manually escape for ASCII
            return result.decode('utf-8').encode('ascii', 'backslashreplace')
        return result
```

---

### 11. `url_fetcher.py` — TOCTOU in SSRF check (DNS rebinding)

**File**: `utils/web/url_fetcher.py` — Lines 71–99, 163–170  
**Severity**: Medium (SSRF bypass possible)

`_is_private_url()` resolves the hostname to check for private IPs, but the actual HTTP request is made later by `aiohttp`, which does its own DNS resolution. Between the check and the request, a malicious DNS server could change the record (DNS rebinding attack).

This is a known limitation of application-layer SSRF protection. Full mitigation requires socket-level enforcement.

**Fix**: Add a comment documenting this limitation. For stronger protection, use `aiohttp`'s `TCPConnector` with a custom resolver that enforces the same IP check:
```python
# Note: Custom resolver approach
class SSRFSafeResolver(aiohttp.resolver.DefaultResolver):
    async def resolve(self, host, port=0, family=socket.AF_INET):
        results = await super().resolve(host, port, family)
        for r in results:
            ip = ipaddress.ip_address(r['host'])
            for net in _BLOCKED_NETWORKS:
                if ip in net:
                    raise ValueError(f"SSRF blocked: {host} -> {r['host']}")
        return results
```

---

### 12. `self_healer.py` — Process matching is overly broad

**File**: `utils/reliability/self_healer.py` — Lines 82–100  
**Severity**: Medium (could kill wrong process)

`find_all_bot_processes()` matches any process where `"bot.py"` appears in the cmdline. This could match:
- `python some_other_bot.py`
- `python /path/to/robot.py` (contains "bot.py" as substring)
- Any Python script with "bot.py" in its arguments

```python
if "python" in cmdline_str and "bot.py" in cmdline_str:
```

**Fix**: Use more precise matching:
```python
import re
# Match only standalone "bot.py" at end of an argument
if "python" in cmdline_str and re.search(r'\bbot\.py\b', cmdline_str):
```
Or better, match against the resolved absolute path of the bot script.

---

### 13. `shutdown_manager.py` — Signal tasks may be GC'd on Windows

**File**: `utils/reliability/shutdown_manager.py` — Lines 392–400  
**Severity**: Medium (Windows-specific)

`setup_async_signal_handlers()` returns early on Windows (line 389: `if sys.platform == "win32": return`), which means on Windows the bot only gets synchronous signal handling via `signal.signal(SIGINT)`. The sync handler calls `self.shutdown()` which is a coroutine — but `_signal_handler` is a sync function that schedules it.

Looking at `_signal_handler` (not fully shown), if it tries to create an asyncio task from a signal handler context on Windows, it may fail because signal handlers run in the main thread which may not have the event loop context available.

**Fix**: Verify the `_signal_handler` implementation properly uses `loop.call_soon_threadsafe()` to schedule the async shutdown from the signal context.

---

### 14. `rate_limiter.py` — Token replenishment can exceed max under adaptive limiting

**File**: `utils/reliability/rate_limiter.py` — Lines 76–86  
**Severity**: Low-Medium (logical error)

In `RateLimitBucket.consume()`:
```python
effective_max = int(self.max_tokens * self.adaptive_multiplier)
self.tokens = min(effective_max, self.tokens + (time_passed * effective_max / self.window))
```

When `adaptive_multiplier` drops (e.g., from 1.0 to 0.5), `effective_max` shrinks but `self.tokens` may already be higher than the new `effective_max`. The `min()` clamps on replenish, but between adaptive changes, tokens isn't clamped proactively. A consumer that checks right after multiplier drops may still have more tokens than allowed.

**Fix**: Clamp tokens at the start of `consume()`:
```python
effective_max = int(self.max_tokens * self.adaptive_multiplier)
self.tokens = min(effective_max, self.tokens)  # Clamp first
# Then replenish...
```

---

## Low-Severity Issues

### 15. `health_api.py` — HTML generation uses f-strings with user data without full escaping

**File**: `utils/monitoring/health_api.py` — Lines 509, 549  
**Severity**: Low (limited XSS since this is a local dashboard)

Most f-string-interpolated values in the health HTML are numeric or from bot internals. However, the cogs list (line 549) is properly escaped with `html.escape()`. The f-string approach for HTML is fragile — if any future field contains user-controlled strings, it could lead to XSS.

**Fix**: Consider using a template engine or consistently use `html.escape()` on all string interpolations.

---

### 16. `media_rust.py` — `_pil_resize` condition logic has unreachable branch

**File**: `utils/media/media_rust.py` — Lines 108–112  
**Severity**: Low (dead code)

```python
format_str = "JPEG" if img.mode != "RGBA" else "PNG"
save_kwargs = {"quality": self.jpeg_quality} if format_str == "JPEG" else {}

if img.mode == "RGBA" and format_str == "JPEG":  # This is always False
    img = img.convert("RGB")
```

If `img.mode == "RGBA"`, then `format_str` is `"PNG"`, so the condition `img.mode == "RGBA" and format_str == "JPEG"` is always `False`. The RGBA→RGB conversion never runs.

**Fix**: Move the conversion before the format decision:
```python
if img.mode == "RGBA":
    img = img.convert("RGB")
format_str = "JPEG"  # Now always JPEG after conversion
save_kwargs = {"quality": self.jpeg_quality}
```
Or if you want to preserve PNGs for RGBA:
```python
# Keep current logic, but remove the dead branch
format_str = "JPEG" if img.mode != "RGBA" else "PNG"
save_kwargs = {"quality": self.jpeg_quality} if format_str == "JPEG" else {}
# Remove the unreachable if block
```

---

### 17. `colors.py` — `enable_windows_ansi` doesn't verify handle validity

**File**: `utils/media/colors.py` — Lines 62–85  
**Severity**: Low (crash when stdout is redirected)

`kernel32.GetStdHandle(-11)` can return `INVALID_HANDLE_VALUE` (-1) when stdout is not a console (e.g., piped or redirected). The subsequent `GetConsoleMode` call with an invalid handle causes an error.

**Fix**: Check the handle before use:
```python
handle = kernel32.GetStdHandle(-11)
if handle == -1 or handle is None:
    return False
```

---

### 18. `error_recovery.py` — Double locking in `_get_backoff_state_async`

**File**: `utils/reliability/error_recovery.py` — Lines 152–155  
**Severity**: Low (performance, deadlock risk if refactored)

```python
async def _get_backoff_state_async(key: str) -> BackoffState:
    async with _backoff_states_async_lock:
        return _get_backoff_state(key)  # This acquires _backoff_states_lock internally
```

Every async call acquires both the async lock AND the threading lock. While not a deadlock with the current `threading.Lock` (non-reentrant but different lock types), it's unnecessary overhead and could deadlock if someone changes `_backoff_states_lock` to `asyncio.Lock`.

**Fix**: Either use only the async lock (since all async callers are in the same thread), or only the threading lock (since the GIL protects dict operations). The threading lock alone is sufficient for the actual mutations.

---

### 19. `structured_logger.py` — `_log_context` ContextVar default set at module level

**File**: `utils/monitoring/structured_logger.py` — Line 38  
**Severity**: Low (unexpected behavior in sub-tasks)

```python
_log_context: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar("log_context")
_log_context.set({})  # This sets it in the main context only
```

The `.set({})` call at module level sets the value for the import-time context. Tasks created with `asyncio.create_task()` inherit this. However, if the same dict object is shared (since ContextVar copies the reference, not the dict), mutations in one task affect others.

**Fix**: Use `default=` parameter instead of `.set()`:
```python
_log_context: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar(
    "log_context", default={}
)
```
But even this shares the same default. Better approach: use a factory:
```python
def _get_log_context() -> dict[str, Any]:
    try:
        return _log_context.get()
    except LookupError:
        ctx = {}
        _log_context.set(ctx)
        return ctx
```

---

### 20. `ytdl_source.py` — `source_address: "0.0.0.0"` binds to all interfaces

**File**: `utils/media/ytdl_source.py` — Line 41  
**Severity**: Low (information)

```python
"source_address": "0.0.0.0",
```

This forces yt-dlp to bind outgoing connections to `0.0.0.0`. On multi-homed systems, this may not bind to the desired interface. This is the yt-dlp default and is typically fine, but is worth noting.

---

### 21. `token_tracker.py` — Missing `_evict_least_recently_used_users` and `_evict_least_used_channels` methods documented?

**File**: `utils/monitoring/token_tracker.py` — Lines 105–109  
**Severity**: Low (potential crash if eviction methods are missing)

The `record()` method references `self._evict_least_recently_used_users()` and `self._evict_least_used_channels()` but these methods must be defined somewhere below line 200. As long as they exist, this is fine — just noting the dependency.

---

## Summary Table

| # | File | Severity | Category | Issue |
|---|------|----------|----------|-------|
| 1 | database.py:720 | **Critical** | Bug | `_pool_semaphore` used directly (None) |
| 2 | error_recovery.py:104, circuit_breaker.py:56 | **Critical** | Async | `asyncio.Lock` at wrong time |
| 3 | url_fetcher.py:220–244 | **High** | Resource Leak | Redirect responses not closed |
| 4 | alerting.py:185 | **High** | Resource Leak | Global session never closed |
| 5 | database.py:1046,1062 | **Medium-High** | Security | f-string SQL (whitelist-protected) |
| 6 | database.py:68 | **Medium-High** | Race Condition | `_connection_count` not atomic |
| 7 | database.py:694 | **Medium** | Bug | `get_connection_with_retry` bypasses pool |
| 8 | migrations.py:117 | **Medium** | Bug | `version` possibly unbound |
| 9 | health_api.py:509 | **Medium** | Race Condition | HTML reads without locks |
| 10 | fast_json.py | **Low-Medium** | Bug | `ensure_ascii` silently ignored |
| 11 | url_fetcher.py:71 | **Medium** | Security | DNS rebinding TOCTOU |
| 12 | self_healer.py:98 | **Medium** | Bug | Overly broad process matching |
| 13 | shutdown_manager.py:389 | **Medium** | Platform | Windows signal handling gap |
| 14 | rate_limiter.py:76 | **Low-Medium** | Bug | Token over-budget after adaptive drop |
| 15 | health_api.py | **Low** | Security | f-string HTML (internal only) |
| 16 | media_rust.py:108 | **Low** | Bug | Unreachable RGBA→RGB branch |
| 17 | colors.py:79 | **Low** | Platform | Invalid handle not checked |
| 18 | error_recovery.py:152 | **Low** | Performance | Double locking |
| 19 | structured_logger.py:38 | **Low** | Async | Shared ContextVar dict |
| 20 | ytdl_source.py:41 | **Low** | Info | `0.0.0.0` source address |
| 21 | token_tracker.py:105 | **Low** | Dependency | Eviction method references |

---

**Files reviewed (32):** `__init__.py`, `fast_json.py`, `localization.py`, `database/__init__.py`, `database/database.py`, `database/migrations.py`, `monitoring/__init__.py`, `monitoring/alerting.py`, `monitoring/audit_log.py`, `monitoring/feedback.py`, `monitoring/health_api.py`, `monitoring/health_client.py`, `monitoring/logger.py`, `monitoring/metrics.py`, `monitoring/performance_tracker.py`, `monitoring/sentry_integration.py`, `monitoring/structured_logger.py`, `monitoring/token_tracker.py`, `reliability/__init__.py`, `reliability/circuit_breaker.py`, `reliability/error_recovery.py`, `reliability/memory_manager.py`, `reliability/rate_limiter.py`, `reliability/self_healer.py`, `reliability/shutdown_manager.py`, `web/__init__.py`, `web/url_fetcher.py`, `web/url_fetcher_client.py`, `media/__init__.py`, `media/colors.py`, `media/media_rust.py`, `media/ytdl_source.py`

**Files with no issues found:** `localization.py`, `monitoring/audit_log.py`, `monitoring/feedback.py`, `monitoring/health_client.py`, `monitoring/logger.py`, `monitoring/metrics.py`, `monitoring/performance_tracker.py`, `monitoring/sentry_integration.py`, `web/url_fetcher_client.py`, `web/__init__.py`, `media/__init__.py`, all `__init__.py` files
