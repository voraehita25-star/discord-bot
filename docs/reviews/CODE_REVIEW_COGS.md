# Deep Code Review — `cogs/` Directory

**Scope:** All 61 Python files under `cogs/`, `cogs/music/`, `cogs/ai_core/` and subdirectories.  
**Focus:** Bugs, security vulnerabilities, type errors, null checks, async issues, Discord.py misuse, memory leaks.  
**Date:** 2025-07

---

## Critical Issues

### 1. [SECURITY] SSRF — No Private-IP Validation on URL Fetch  
**File:** `cogs/ai_core/core/context_builder.py` lines 375-381  
**Category:** Security vulnerability  

The `fetch_url_content` method validates the URL scheme (`http`/`https`) but does **not** block requests to private/internal IPs (`127.0.0.1`, `10.x`, `172.16-31.x`, `192.168.x`, `169.254.x`, `[::1]`, `fd00::/8`). An attacker can craft a message containing `http://169.254.169.254/latest/meta-data/` to access cloud metadata or internal services.

```python
# Current (line 375-378):
parsed = urlparse(url)
if parsed.scheme not in ("http", "https"):
    logging.warning("Blocked non-HTTP URL scheme: %s", url)
    continue
```

**Fix:** Add IP validation after scheme check:
```python
import ipaddress, socket

def _is_private_url(url: str) -> bool:
    parsed = urlparse(url)
    try:
        ip = ipaddress.ip_address(socket.gethostbyname(parsed.hostname or ""))
        return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
    except (socket.gaierror, ValueError):
        return False  # If DNS fails, allow (fetcher will fail anyway)

# In fetch_url_content:
if _is_private_url(url):
    logging.warning("Blocked private/internal URL: %s", url)
    continue
```

---

### 2. [SECURITY] Unrestricted Mode Bypasses Prompt Injection Detection  
**File:** `cogs/ai_core/processing/guardrails.py` lines 507-509  
**Category:** Security vulnerability  

When a channel is in unrestricted mode, `validate_input_for_channel` returns immediately without checking for prompt injection:

```python
# line 507-509
if is_unrestricted(channel_id):
    return True, user_input, 0.0, ["unrestricted_mode"]
```

This means any user in an "unrestricted" channel can use prompt injection attacks (e.g., "ignore all previous instructions") with zero detection or logging.

**Fix:** Still run prompt injection detection even in unrestricted mode, but only log/flag instead of blocking:
```python
if is_unrestricted(channel_id):
    # Still detect injection attempts for auditing
    result = input_guardrails.validate(user_input)
    if not result.is_valid:
        logging.warning("Prompt injection in unrestricted channel %s: flags=%s", channel_id, result.flags)
    return True, user_input, result.risk_score, ["unrestricted_mode"] + result.flags
```

---

### 3. [BUG / ASYNC] `threading.RLock` Blocks the Event Loop in Async Functions  
**File:** `cogs/ai_core/storage.py` line 79, used at lines 91, 111, 137, 144, 399, 418, 428, 486, 496, 504  
**Category:** Async issue — blocking call in async context  

`_cache_lock = threading.RLock()` is a **synchronous** lock used with `with _cache_lock:` inside `async def` functions (e.g., `get_history`, `save_history`). When contended, this blocks the asyncio event loop thread, stalling **all** concurrent async operations.

```python
# line 79
_cache_lock = threading.RLock()

# line 399 (inside async def save_history)
with _cache_lock:
    cached = _history_cache.get(channel_id)
```

**Fix:** Replace with `asyncio.Lock` for all async callers, or use `await asyncio.to_thread(...)` for cache operations:
```python
_cache_lock = asyncio.Lock()

# Usage:
async with _cache_lock:
    cached = _history_cache.get(channel_id)
```

This same pattern also applies to:
- `cogs/ai_core/cache/ai_cache.py` line 96 — `threading.Lock` used in `AICache`
- `cogs/ai_core/cache/ai_cache.py` line 529 — `threading.Lock` in `L2SqliteCache`
- `cogs/ai_core/response/webhook_cache.py` — `threading.Lock` for webhook cache
- `cogs/ai_core/memory/conversation_branch.py` line 85 — `threading.Lock` used alongside asyncio.Lock

**Note:** If the lock must be used from both sync and async contexts, wrap sync lock access in `asyncio.to_thread` from async code.

---

### 4. [BUG / RACE CONDITION] Webhook Fetch on Every Webhook Message — Rate Limit Risk  
**File:** `cogs/ai_core/ai_cog.py` lines 345-353  
**Category:** Bug / Discord.py API misuse  

Every webhook message triggers `await message.channel.webhooks()` to verify the webhook identity. This makes an HTTP API call per message, which can easily hit Discord's rate limits on busy channels.

```python
# line 345
webhooks = await message.channel.webhooks()
for wh in webhooks:
    if wh.id == message.webhook_id:
        if wh.user and wh.user.bot and wh.user.name in ALLOWED_WEBHOOK_NAMES:
            is_known_proxy = True
        break
```

**Fix:** Cache verified webhook IDs with a TTL:
```python
# At class level:
_verified_webhooks: dict[int, float] = {}  # webhook_id -> verification_time
WEBHOOK_VERIFY_TTL = 300  # 5 minutes

# In on_message:
now = time.time()
cached_time = self._verified_webhooks.get(message.webhook_id)
if cached_time and (now - cached_time) < self.WEBHOOK_VERIFY_TTL:
    is_known_proxy = True
else:
    try:
        webhooks = await message.channel.webhooks()
        for wh in webhooks:
            if wh.id == message.webhook_id:
                if wh.user and wh.user.bot and wh.user.name in ALLOWED_WEBHOOK_NAMES:
                    is_known_proxy = True
                    self._verified_webhooks[message.webhook_id] = now
                break
    except (discord.Forbidden, discord.HTTPException):
        pass
```

---

### 5. [BUG] Non-Atomic File Write for Queue JSON  
**File:** `cogs/music/cog.py` lines 335-337  
**Category:** Bug — data corruption on crash  

`_save_queue_json_sync` writes directly to the target file. If the process crashes mid-write, the file is corrupted. Compare with `cogs/music/queue.py` which correctly uses `write_text` on a temp file + `os.replace`.

```python
# line 337
filepath.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
```

**Fix:** Use atomic write pattern:
```python
import tempfile, os

tmp_fd, tmp_path = tempfile.mkstemp(dir=filepath.parent, suffix=".tmp")
try:
    with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, str(filepath))
except BaseException:
    with contextlib.suppress(OSError):
        os.unlink(tmp_path)
    raise
```

---

### 6. [BUG] Fire-and-Forget Tasks During LRU Eviction — Silent Data Loss  
**File:** `cogs/ai_core/logic.py` lines 400-402  
**Category:** Bug — resource leak / data loss  

When `_enforce_channel_limit` evicts channels, it creates fire-and-forget tasks to save history. But immediately after scheduling the task, it deletes the channel data from `self.chats`. If the save task hasn't started yet (which is likely since `create_task` only schedules, doesn't execute), the save function may operate on stale references or the data may already be gone.

```python
# line 402
task = loop.create_task(save_history(self.bot, channel_id, self.chats[channel_id]))
# ... later (line ~415):
self.chats.pop(channel_id, None)
```

However, since `self.chats[channel_id]` is a **list reference** passed to the task, and `pop` only removes the dict entry (not the list), this is actually safe *for the list*. The real risk is: if the bot shuts down before the tasks complete, data is lost.

**Fix:** Track eviction save tasks and await them during shutdown:
```python
self._eviction_tasks: set[asyncio.Task] = set()

# In _enforce_channel_limit:
task = loop.create_task(save_history(...))
self._eviction_tasks.add(task)
task.add_done_callback(self._eviction_tasks.discard)

# In cog_unload or shutdown:
if self._eviction_tasks:
    await asyncio.gather(*self._eviction_tasks, return_exceptions=True)
```

---

### 7. [BUG] `entity_memory.py` — `IS ?` with `None` for DELETE  
**File:** `cogs/ai_core/memory/entity_memory.py` lines 407-408  
**Category:** Bug — SQL correctness  

```python
WHERE name = ? AND channel_id IS ? AND guild_id IS ?
```

In SQLite, `column IS ?` with a non-NULL value works since SQLite 3.23 (2018), but it's non-standard and confusing. More importantly, if `channel_id` or `guild_id` is a valid integer, the query becomes `channel_id IS 12345` which works but is semantically incorrect (IS is meant for NULL comparison). This will fail on other databases and confuses intent.

**Fix:** Use explicit NULL handling:
```python
# Build WHERE clause dynamically
conditions = ["name = ?"]
params = [name]
for col, val in [("channel_id", channel_id), ("guild_id", guild_id)]:
    if val is None:
        conditions.append(f"{col} IS NULL")
    else:
        conditions.append(f"{col} = ?")
        params.append(val)
where = " AND ".join(conditions)
await conn.execute(f"DELETE FROM entity_memories WHERE {where}", params)
```

---

### 8. [BUG] JSON Regex in Consolidator Matches First Brace Pair (Non-Greedy)  
**File:** `cogs/ai_core/memory/consolidator.py` line 293  
**Category:** Bug — logic error  

```python
match = re.search(r"\{[\s\S]*?\}", response_text)
```

The `*?` (non-greedy) quantifier makes this match the **shortest** possible string between `{` and `}`. For nested JSON like `{"entities": [{"name": "Foo"}]}`, this would match only `{"entities": [{"name": "Foo"}` — stopping at the first `}`, which is invalid JSON.

The same issue exists at line ~306 for arrays: `r"\[[\s\S]*?\]"`.

**Fix:** Use a JSON-aware extraction instead:
```python
def _extract_json_object(text: str) -> dict | None:
    """Find the first valid JSON object in text."""
    start = text.find("{")
    while start != -1:
        for end in range(len(text), start, -1):
            try:
                return json.loads(text[start:end])
            except (json.JSONDecodeError, ValueError):
                continue
        start = text.find("{", start + 1)
    return None
```

Or use a bracket-depth counter for O(n) extraction.

---

## High-Priority Issues

### 9. [RESOURCE LEAK] `Database()` Instantiated 16 Times in ws_dashboard.py  
**File:** `cogs/ai_core/api/ws_dashboard.py` lines 448, 503, 515, 549, 783, 841, 864, 900, 922, 945, 966, 992, 1013, 1032, 1053, 1072  
**Category:** Resource leak  

Every handler creates a new `Database()` instance: `db = Database()`. If `Database.__init__` opens a connection or creates a connection pool, this leaks connections. Even if `Database` is a singleton, repeatedly calling the constructor is wasteful.

**Fix:** Store a single instance as a module-level or class-level attribute:
```python
class DashboardWebSocketServer:
    def __init__(self):
        # ...
        self._db = Database() if DB_AVAILABLE else None

    # Then use self._db everywhere instead of db = Database()
```

---

### 10. [SECURITY] All Gemini Safety Settings Set to BLOCK_NONE  
**File:** `cogs/ai_core/api/api_handler.py` lines 94-97  
**File:** `cogs/ai_core/api/ws_dashboard.py` lines ~650-655  
**Category:** Security vulnerability  

All four safety categories are set to `BLOCK_NONE`, meaning the AI will generate any content with zero safety filtering. Combined with unrestricted mode and escalation framings, this can produce harmful content.

```python
{"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
{"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
{"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
{"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
```

**Fix:** At minimum, use `BLOCK_ONLY_HIGH` as a baseline and only relax for unrestricted channels:
```python
def get_safety_settings(unrestricted: bool = False):
    threshold = "BLOCK_NONE" if unrestricted else "BLOCK_ONLY_HIGH"
    return [{"category": cat, "threshold": threshold} for cat in [...]]
```

---

### 11. [ASYNC] L2 SQLite Cache Uses Synchronous `sqlite3` in Event Loop Thread  
**File:** `cogs/ai_core/cache/ai_cache.py` lines 529-545, 556-570  
**Category:** Async issue — blocking I/O  

`L2SqliteCache` uses the synchronous `sqlite3` module with `threading.Lock`. The `store` method is called from `_persist_to_l2` which uses `loop.run_in_executor(None, ...)` — this is correct for the write path. However, `load_recent` (line ~575) is called **at module import time** (line 654) which runs on the main thread. That's acceptable for startup. But if `_evict_excess` inside `store` takes too long (e.g., large DB), it blocks the executor thread pool.

**Partial mitigation already exists** (executor), but consider:
- Adding `PRAGMA busy_timeout=5000` to prevent `OperationalError: database is locked`
- Using WAL journal mode (already done on line 538 — good)

---

### 12. [BUG] Monkey-Patching `AICache.set` is Fragile  
**File:** `cogs/ai_core/cache/ai_cache.py` lines 677-694  
**Category:** Bug — maintenance hazard  

The L2 persist hook is applied via monkey-patch:
```python
AICache.set = _patched_set  # type: ignore[assignment]
```

This breaks if:
- Multiple modules import and monkey-patch
- Someone subclasses `AICache` and calls `super().set()`
- The `set` method signature changes

**Fix:** Use a proper callback/hook pattern:
```python
class AICache:
    def __init__(self, ...):
        self._on_set_hooks: list[Callable] = []

    def add_on_set_hook(self, hook):
        self._on_set_hooks.append(hook)

    def set(self, ...):
        # ... existing set logic ...
        for hook in self._on_set_hooks:
            hook(key, entry)

# Then:
ai_cache.add_on_set_hook(lambda key, entry: _persist_to_l2(key, entry))
```

---

### 13. [BUG] `_DictProxy.__contains__` Fails for `in` Operator in music/cog.py  
**File:** `cogs/music/cog.py` (wherever `_DictProxy` is used)  
**Category:** Bug — logic error  

If `_DictProxy` doesn't implement `__contains__`, `guild_id in self.mode_247` (or similar) will iterate the dict, not check the proxied `_data`. Without seeing the full `_DictProxy` implementation, this is a potential issue if the `MusicGuildState` consolidation broke dict-like behavior.

**Verify:** Ensure `_DictProxy` implements `__contains__`, `__iter__`, `__len__`, `keys()`, `values()`, `items()`, `get()`, `pop()`, `setdefault()`, etc.

---

### 14. [SECURITY] `cmd_read_channel` Allows AI to Read Any Channel  
**File:** `cogs/ai_core/commands/server_commands.py` (cmd_read_channel, near line ~740)  
**Category:** Security vulnerability  

The `read_channel` tool function lets the AI read messages from **any** text channel by name or ID, with no permission check beyond the bot's own Discord permissions. If the AI is prompted to do so (via prompt injection or social engineering), it could exfiltrate private channel content.

**Fix:** Add an explicit check that the command invoker has `view_channel` permission for the target channel:
```python
async def cmd_read_channel(guild, origin_channel, _name, args):
    # ... find target_channel ...
    # Check invoker has permissions (need to pass invoker context)
    # Or restrict to channels the bot's operator explicitly allows
```

---

### 15. [BUG] Token Tracker Stores Triple Copies of Each Usage Record  
**File:** `cogs/ai_core/cache/token_tracker.py` lines 145-160  
**Category:** Memory usage  

Each `record_usage` call stores the same `TokenUsage` object in three separate lists (by user, by channel, by guild). This triples memory usage. With `MAX_RECORDS_PER_KEY = 5000`, for a server with 100 users, 50 channels, this could be up to `(100 + 50 + 1) * 5000 = 755,000` records stored.

**Fix:** Store records once in a flat list and index by key:
```python
self._records: list[TokenUsage] = []
self._index_by_key: dict[str, list[int]] = defaultdict(list)  # key -> list of indices
```

Or accept the memory cost and document it. The current bound of `MAX_RECORDS_PER_KEY = 5000` per key is at least bounded.

---

## Medium-Priority Issues

### 16. [BUG] Missing `await` Guard in `force_release_lock`  
**File:** `cogs/ai_core/core/message_queue.py` lines 300-306  
**Category:** Bug — potential RuntimeError  

```python
def force_release_lock(self, channel_id: int):
    lock = self.processing_locks.get(channel_id)
    if lock and lock.locked():
        lock.release()
```

`asyncio.Lock.release()` raises `RuntimeError` if called by a task that doesn't own the lock. If this is called from a different task (e.g., during cleanup), it will crash.

**Fix:** Wrap in try/except:
```python
def force_release_lock(self, channel_id: int):
    lock = self.processing_locks.get(channel_id)
    if lock and lock.locked():
        try:
            lock.release()
        except RuntimeError:
            logging.warning("Lock for channel %s not owned by this task", channel_id)
```

---

### 17. [BUG] `quality_scores` List in analytics.py Grows and Gets Pop(0)  
**File:** `cogs/ai_core/cache/analytics.py` lines ~305-310  
**Category:** Performance  

```python
if len(self._stats["quality_scores"]) > 1000:
    self._stats["quality_scores"].pop(0)
```

`list.pop(0)` is O(n) — it shifts all remaining elements. With 1000 scores, this creates unnecessary work on every new score after the limit.

**Fix:** Use `collections.deque(maxlen=1000)`:
```python
self._stats["quality_scores"] = deque(maxlen=1000)
```

---

### 18. [BUG] `response_times` List Also Does Inefficient Slicing  
**File:** `cogs/ai_core/cache/analytics.py` line ~535  
**Category:** Performance  

```python
if len(self._stats["response_times"]) > 1000:
    self._stats["response_times"] = self._stats["response_times"][-1000:]
```

Creates a new 1000-element list every time. Same fix: use `deque(maxlen=1000)`.

---

### 19. [NULL CHECK] Missing `guild.me` Check Before `top_role` Access  
**File:** `cogs/ai_core/commands/server_commands.py`  
**Category:** Missing null check  

In `cmd_add_role` and `cmd_remove_role`, there's a check `if guild.me is None`, which is good. But other command functions like `cmd_create_role` don't check `guild.me` before accessing bot member properties. In edge cases during startup or after a reconnect, `guild.me` can be `None`.

---

### 20. [BUG] `conversation_branch.py` — Deep Copy of History May Be Expensive  
**File:** `cogs/ai_core/memory/conversation_branch.py`  
**Category:** Performance  

Checkpoints deep-copy the entire conversation history. For channels with thousands of messages, this is expensive both in CPU and memory.

**Fix:** Consider copy-on-write or storing only diffs.

---

### 21. [SECURITY] `cmd_edit_message` Allows AI to Edit Bot's Webhook Messages  
**File:** `cogs/ai_core/commands/server_commands.py` (`cmd_edit_message`, near line ~680)  
**Category:** Security concern  

The AI can edit any bot-owned message (including webhook messages). If the AI is prompt-injected, it could silently alter previous messages.

**Fix:** Add an audit log entry for every message edit, and optionally require owner confirmation for webhook message edits.

---

### 22. [BUG] Potential Data Race in `_history_cache` / `_metadata_cache`  
**File:** `cogs/ai_core/storage.py`  
**Category:** Race condition  

The cache uses `threading.RLock` but is accessed from async code. Two coroutines could:
1. Coroutine A reads cache, releases lock
2. Coroutine B reads cache, releases lock
3. Both modify the same list reference
4. Both write back

Since both hold references to the **same list object**, concurrent modifications (e.g., `append`) are actually thread-safe in CPython due to the GIL. But logical races (e.g., both saving history with different diffs) can still cause duplicate entries.

**Mitigation:** The duplicate detection via content hashing helps, but it's not a complete solution.

---

### 23. [BUG] `_parse_extraction` Non-Greedy Regex for JSON Arrays  
**File:** `cogs/ai_core/memory/consolidator.py` line ~306  
**Category:** Bug — logic error  

Same issue as #8 but for array pattern:
```python
match = re.search(r"\[[\s\S]*?\]", response_text)
```
This matches the first `[...]` pair with minimal content, which can miss nested arrays.

---

### 24. [MEMORY] `_verified_webhooks` Cache (if implemented per fix #4) Needs Eviction  
**File:** `cogs/ai_core/ai_cog.py`  
**Category:** Memory leak (pre-emptive)  

The current code fetches webhooks on every message (issue #4). Any cache added should include eviction to prevent unbounded growth.

---

### 25. [BUG] `memory_consolidator.py` — Extractions Lost if Summary Quality is Poor  
**File:** `cogs/ai_core/memory/memory_consolidator.py`  
**Category:** Data loss risk  

The extractive summarizer uses heuristic scoring (not LLM). After summarizing, it **deletes** the original messages from the database. If the summary is poor quality, the original data is permanently lost.

**Fix:** Consider a "soft delete" (mark as archived) instead of hard delete, or wait for N days before purging.

---

### 26. [BUG] `long_term_memory.py` — Substring Match False Positives  
**File:** `cogs/ai_core/memory/long_term_memory.py`  
**Category:** Logic error  

`_find_similar_fact` uses substring matching for short strings (>= 5 chars). A fact like "likes cats" would match "he likes cats and dogs" — this is intentional. But it would also match "he dislikes cats", which is a contradiction flagged as a duplicate.

**Mitigation:** The word overlap check (SIMILARITY_THRESHOLD=0.8) runs after substring match, so false positives are partially caught. Still, "likes cats" vs "dislikes cats" has high word overlap.

---

### 27. [SECURITY] `context_builder.py` URL Content Injection  
**File:** `cogs/ai_core/core/context_builder.py` lines 383-386  
**Category:** Security — prompt injection via URL content  

Fetched URL content is injected directly into the AI context:
```python
contents.append(f"[{url}]\n{content}")
```

A malicious URL could contain text like "IGNORE ALL PREVIOUS INSTRUCTIONS" that gets injected into the AI prompt.

**Fix:** Wrap fetched content in clear delimiters and instruct the AI to treat it as untrusted:
```python
contents.append(f"[Fetched URL: {url}]\n<untrusted_content>\n{content}\n</untrusted_content>")
```

---

### 28. [BUG] `state_tracker.py` — Regex-Based State Extraction is Fragile  
**File:** `cogs/ai_core/memory/state_tracker.py`  
**Category:** Logic error  

Character state is extracted from AI responses using regex patterns for Thai language. These patterns are inherently fragile and can produce incorrect extractions or miss valid state changes.

**Impact:** Low — this affects RP flavor, not core functionality. The LRU eviction bounds are correct.

---

### 29. [BUG] `tool_executor.py` — `send_as_webhook` Creates Duplicate Webhooks  
**File:** `cogs/ai_core/tools/tool_executor.py` lines ~380-430  
**Category:** Resource leak  

The `send_as_webhook` function in `tool_executor.py` searches for existing webhooks then creates a new one if none match. On a busy channel this can accumulate webhooks up to Discord's 15-per-channel limit. The fallback to reusing "AI Tupper Proxy" webhook is good, but the primary path can still create excess webhooks.

**Mitigation already exists:** The code checks `len(webhooks) < DISCORD_WEBHOOK_LIMIT` before creating. The real issue is accumulating many character-specific webhooks.

---

### 30. [BUG] `summarizer.py` — No Token Limit Validation on Input  
**File:** `cogs/ai_core/memory/summarizer.py`  
**Category:** Bug  

Conversation text is passed directly to the Gemini summarization API without checking if it exceeds the model's context window. Very long conversations could cause API errors.

**Fix:** Truncate or chunk the input before summarization.

---

## Low-Priority Issues

### 31. [STYLE/BUG] `importlib.reload` in `reload_config`  
**File:** `cogs/ai_core/ai_cog.py` (reload_config_cmd)  
**Category:** Maintenance hazard  

Using `importlib.reload(config)` at runtime may not properly update all references to config values that were imported with `from config import X`.

---

### 32. Fallback `_DictProxy` in music/cog.py  
**File:** `cogs/music/cog.py`  
**Category:** Maintenance  

`_DictProxy` wraps `MusicGuildState` fields as dicts for backward compatibility. If any caller uses dict-specific methods not forwarded by the proxy (`update()`, `popitem()`, etc.), it will raise `AttributeError` at runtime.

---

### 33. `intent_feedback` List Uses `pop` Slicing  
**File:** `cogs/ai_core/cache/analytics.py` line ~581  
**Category:** Performance  

```python
self._stats["intent_feedback"] = self._stats["intent_feedback"][-500:]
```

Same O(n) slicing issue. Use `deque(maxlen=500)` instead.

---

### 34. Dashboard WS Server — Missing Origin Validation Bypass  
**File:** `cogs/ai_core/api/ws_dashboard.py`  
**Category:** Security  

The origin validation was partially read. Verify that `localhost` and `127.0.0.1` origins are the only ones allowed in production, and that the `ALLOWED_ORIGINS` list cannot be overridden via environment variable to include arbitrary origins.

---

### 35. `token_tracker.py` — `_get_usage_in_period` Called Without Lock  
**File:** `cogs/ai_core/cache/token_tracker.py` (line ~225)  
**Category:** Race condition (minor)  

`_get_usage_in_period` accesses `self._usage_cache` without holding `self._lock`. It's documented as "caller should use with lock if needed" and the public methods do acquire the lock. But `_get_usage_in_period` itself iterates a defaultdict list that could be modified concurrently by `record_usage`.

**Current mitigation:** The public async methods like `get_user_usage` already acquire `self._lock` before calling `_get_usage_in_period`. This is fine — just ensure no caller bypasses the lock.

---

## Summary Table

| # | Severity | Category | File | Issue |
|---|----------|----------|------|-------|
| 1 | **CRITICAL** | Security | context_builder.py | SSRF — no private IP validation |
| 2 | **CRITICAL** | Security | guardrails.py | Unrestricted mode bypasses injection detection |
| 3 | **CRITICAL** | Async | storage.py | threading.RLock blocks event loop |
| 4 | **HIGH** | Bug/API | ai_cog.py | Webhook fetch on every webhook message |
| 5 | **HIGH** | Bug | music/cog.py | Non-atomic queue JSON write |
| 6 | **HIGH** | Bug | logic.py | Fire-and-forget save during eviction |
| 7 | **HIGH** | Bug | entity_memory.py | `IS ?` SQL pattern for NULL |
| 8 | **HIGH** | Bug | consolidator.py | Non-greedy JSON regex misses nested objects |
| 9 | **HIGH** | Resource | ws_dashboard.py | 16× Database() instantiation |
| 10 | **HIGH** | Security | api_handler.py | All safety settings BLOCK_NONE |
| 11 | **MEDIUM** | Async | ai_cache.py | Sync SQLite in L2 cache |
| 12 | **MEDIUM** | Bug | ai_cache.py | Fragile monkey-patch pattern |
| 13 | **MEDIUM** | Bug | music/cog.py | _DictProxy completeness |
| 14 | **MEDIUM** | Security | server_commands.py | AI can read any channel |
| 15 | **MEDIUM** | Memory | token_tracker.py | Triple storage of usage records |
| 16 | **MEDIUM** | Bug | message_queue.py | force_release_lock RuntimeError |
| 17 | **MEDIUM** | Perf | analytics.py | O(n) list.pop(0) |
| 18 | **MEDIUM** | Perf | analytics.py | O(n) list slicing |
| 19 | **MEDIUM** | Null | server_commands.py | Missing guild.me check |
| 20 | **MEDIUM** | Perf | conversation_branch.py | Expensive deep copy |
| 21 | **MEDIUM** | Security | server_commands.py | AI can edit bot messages |
| 22 | **MEDIUM** | Race | storage.py | Logical data race in cache |
| 23 | **MEDIUM** | Bug | consolidator.py | Non-greedy regex for arrays |
| 24 | **LOW** | Memory | ai_cog.py | Webhook cache needs eviction |
| 25 | **LOW** | Bug | memory_consolidator.py | Hard delete after extract summary |
| 26 | **LOW** | Bug | long_term_memory.py | Substring false positives |
| 27 | **MEDIUM** | Security | context_builder.py | URL content prompt injection |
| 28 | **LOW** | Bug | state_tracker.py | Fragile regex extraction |
| 29 | **LOW** | Resource | tool_executor.py | Webhook accumulation |
| 30 | **LOW** | Bug | summarizer.py | No input token limit |
| 31 | **LOW** | Maint | ai_cog.py | importlib.reload pitfall |
| 32 | **LOW** | Maint | music/cog.py | DictProxy method coverage |
| 33 | **LOW** | Perf | analytics.py | intent_feedback slicing |
| 34 | **LOW** | Security | ws_dashboard.py | Origin validation config |
| 35 | **LOW** | Race | token_tracker.py | _get_usage_in_period without lock |

---

**Critical fixes recommended first:** #1 (SSRF), #3 (threading lock in async), #4 (webhook rate limit), #5 (non-atomic write), #8 (JSON regex).
