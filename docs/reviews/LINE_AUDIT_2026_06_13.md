# Repo line-by-line audit — confirmed findings

**155 confirmed** across 84 files (1 high · 13 medium · 81 low · 60 nit). 242/242 source files examined.

## 🟠 HIGH (1)

| File | Line | Cat | Detail |
|---|---|---|---|
| `cogs/ai_core/media_processor.py` | 728 | error-handling | The module sets `warnings.filterwarnings("error", category=Image.DecompressionBombWarning)` (line 33) and `Image.MAX_IMAGE_PIXELS = 30_000_000` (line 32). Pillow's `_decompression_bomb_check` raises `DecompressionBombEr… |

## 🟡 MED (13)

| File | Line | Cat | Detail |
|---|---|---|---|
| `.claude/skills/repo-audit/SKILL.md` | 19, 23 | doc-accuracy | The repo-audit skill's stated green baselines are stale and contradict every authoritative doc. Line 19: Python baseline 'green baseline: 3143 passed, 1 skipped'. Line 23: vitest 'baseline 190 passed' and Playwright 'ba… |
| `.dockerignore` | 81 | bug | The .dockerignore excludes the entire scripts/ directory from the Docker build context. utils/database/migrations.py:26 sets MIGRATIONS_DIR = Path(__file__).parent.parent.parent / 'scripts' / 'maintenance' / 'migrations… |
| `cogs/ai_core/media_processor.py` | 246 | error-handling | Same root cause as the line-728 finding. `is_animated_gif` runs `Image.open(...)` then `img.seek(1)` on raw bytes and catches only `(OSError, ValueError, Image.DecompressionBombError)`. A 30-60MP image (or anything with… |
| `cogs/music/cog.py` | 2468-2472 | bug | The nowplaying elapsed-position math assumes `pause_start` is set whenever the voice client is paused. That invariant only holds for the text `!pause` command (line 1336 sets `pause_start = time.time()`). The button pat… |
| `cogs/music/cog.py` | 1369-1374 | bug | `resume` (and the button-resume) only shifts `current_track['start_time']` forward by the paused duration when `pause_start is not None` (lines 1369-1374). Because the button-pause path never sets `pause_start`, a butto… |
| `docs/DEVELOPER_GUIDE.md` | 455-456 | doc-accuracy | The Processing Limits table states STREAMING_TIMEOUT_INITIAL = 30s (line 455) and MAX_HISTORY_ITEMS = 2000 (line 456). The actual values in cogs/ai_core/data/constants.py are STREAMING_TIMEOUT_INITIAL = 120.0 (line 59) … |
| `docs/TROUBLESHOOTING.md` | 77-78 | doc-accuracy | The 'AI Not Responding' section documents the rate limiter configs as `ai_user: 10 req/min per user` and `ai_guild: 30 req/min per guild`. The actual values in utils/reliability/rate_limiter.py are ai_user requests=60 (… |
| `native_dashboard/README.md` | 59 | doc-accuracy | The File Attachments table lists 'Images \| PNG, JPEG, GIF, WebP (20 MB cap)'. The actual per-image limit is 10 MB everywhere in code: ws_dashboard.py line 161 MAX_IMAGE_SIZE_BYTES = 10*1024*1024, and the default max_ima… |
| `native_dashboard/src-ts/chat-manager.ts` | 1739 | bug | renderMessages() unconditionally calls this.scrollToBottom() (non-force, line 1739). scrollToBottom (line 2043-2059) only suppresses scrolling when this.userScrolledUp is true. userScrolledUp is only ever set to a non-f… |
| `native_dashboard/src/bot_manager.rs` | 442-443 | correctness | is_running() (line 442-443), the mirrored check in get_status() (line 499-505), and kill_orphan_bot_processes() (line 309) all require the joined process cmdline to contain base_path_str (lowercased base_path). In dev m… |
| `scripts/maintenance/migrations/002_sync_defaults.sqlite.sql` | 6-35 | data-loss | Migration 002 unconditionally DROPs and recreates token_usage (lines 6-20) and conversation_summaries (lines 23-35) with NO `INSERT ... SELECT` to copy existing rows. The only safeguard is a comment asserting the table … |
| `scripts/startup/start.ps1` | 106-120 | bug | Auto-restart limit only enforced on crashes. On clean exit (ExitCode==0) RestartCount is not incremented (lines 110-113 only log via Write-Log), and the loop has no break on clean exit (only breaks on stop_loop.flag at … |
| `utils/monitoring/health_client.py` | 277-300 | data-loss | In _flush_buffer_locked the buffer is chunked into 900-item POSTs in a loop (lines 280-290). If an early chunk POSTs successfully and a later chunk raises (network drop mid-iteration), the except handler at line 300 re-… |

## 🔵 LOW (81)

| File | Line | Cat | Detail |
|---|---|---|---|
| `cogs/ai_core/ai_cog.py` | 1903-1906 | error-handling | channel_ratelimit_cmd passes the user-supplied `limit` straight to `rate_limiter.set_channel_limit(channel_id, limit)` with no lo… |
| `cogs/ai_core/ai_cog.py` | 1807-1850 | concurrency | auto_summarize_cmd captures `chat_data = self.chat_manager.chats.get(channel_id)` at line 1807 OUTSIDE any lock, then after await… |
| `cogs/ai_core/api/ai_tools_ipc.py` | 290 | error-handling | The broad-except fallback at line 290 returns f"Tool '{tool}' failed: {e}" with the raw exception interpolated, and this string i… |
| `cogs/ai_core/api/dashboard_chat_claude_cli.py` | 496 | resource-leak | _load_persisted_sessions (475-500) copies every str->str entry from the sidecar JSON into _CONVERSATION_SESSIONS (lines 496-498) … |
| `cogs/ai_core/api/dashboard_chat_claude_cli.py` | 2050 | api-misuse | `proc.stdout._limit = MAX_STDOUT_LINE_BYTES` (line 2050) mutates a private asyncio.StreamReader attribute inside `contextlib.supp… |
| `cogs/ai_core/api/discord_chat_claude_cli.py` | 349-503 | bug | Interactive over-limit warning views can stack. _OVERLIMIT_WARN_COOLDOWN is 120s but _OverlimitChoiceView's timeout is 600.0s (li… |
| `cogs/ai_core/api/discord_chat_claude_cli.py` | 483-503 | bug | In _send_overlimit_warning the entire body — including the cooldown-timestamp write _OVERLIMIT_LAST_WARN[key] = now (line 492) an… |
| `cogs/ai_core/api/discord_chat_claude_cli.py` | 474-503 | correctness | When call_claude_cli_streaming is invoked with channel_id=None (documented as a real possibility — see _FALLBACK_LOCK at lines 83… |
| `cogs/ai_core/cache/token_tracker.py` | 345 | error-handling | stop_cleanup_task() does `await task` inside `except (asyncio.CancelledError, Exception)`. Catching asyncio.CancelledError here a… |
| `cogs/ai_core/commands/memory_commands.py` | 255 | error-handling | In force_consolidate, the broad `except Exception` handler (246) recovers by calling status_msg.edit(content=msg, embed=None) at … |
| `cogs/ai_core/commands/server_commands.py` | 1085-1099 | error-handling | cmd_get_user_info builds a user-info block including the full role list (roles joined at line 1086) and sends it via a single ori… |
| `cogs/ai_core/commands/server_commands.py` | 500-512 | bug | cmd_delete_role resolves by NAME first (matches = roles where name.lower()==role_name.lower(), line 500; role = matches[0] if mat… |
| `cogs/ai_core/emoji.py` | 79-85 | performance | In fetch_emoji_images._fetch_with_session, after the awaited network read (await resp.read()), the synchronous CPU-bound PIL work… |
| `cogs/ai_core/logic.py` | 1546-1567 | performance | Once len(history) exceeds MAX_HISTORY_ITEMS+500, summarizer.compress_history runs on every turn on the hot message path with a 60… |
| `cogs/ai_core/media_processor.py` | 391 | error-handling | Same type-mismatch: `convert_gif_to_video`'s `except (OSError, ValueError, Image.DecompressionBombError, RuntimeError)` at line 3… |
| `cogs/ai_core/media_processor.py` | 355 | resource-leak | `video_buffer = io.BytesIO()` (line 355) is explicitly closed only on the success path (line 388). On the timeout path (line 370)… |
| `cogs/ai_core/memory/consolidator.py` | 680 | error-handling | `detect_contradictions` does `if facts.get("relationships"):` (line 680) then `for related_name, relation in facts["relationships… |
| `cogs/ai_core/memory/entity_memory.py` | 632-636 | correctness | In _row_to_entity, `confidence=row["confidence"] or 1.0` coerces a legitimately stored 0.0 confidence back to full 1.0 via the fa… |
| `cogs/ai_core/memory/history_manager.py` | 382-395 | performance | smart_trim_by_tokens (async, line 359) calls estimate_tokens(history) at line 382 and estimate_message_tokens(msg) per message at… |
| `cogs/ai_core/memory/long_term_memory.py` | 829-844 | performance | deduplicate_facts opens a fresh db.get_write_connection() (acquiring the global write lock) inside the per-duplicate loop (line 8… |
| `cogs/ai_core/memory/memory_consolidator.py` | 114-118 | resource-leak | _get_channel_lock / _channel_locks grows one asyncio.Lock per distinct channel forever and is never pruned. The sibling LongTermM… |
| `cogs/ai_core/memory/memory_consolidator.py` | 244-254 | performance | The SELECT that pulls rows to summarize has no LIMIT, and _generate_summary then joins every row's content into a single all_text… |
| `cogs/ai_core/memory/rag.py` | 1232 | error-handling | add_memory() returns True at line 1232 even when save_rag_memory returned 0 (failed/empty lastrowid). When result is 0, memory_id… |
| `cogs/ai_core/memory/rag_rust.py` | 256-285 | correctness | load() (Python fallback) builds new_entries validating only `isinstance(entry, dict) and "id" in entry` (line 278); it never chec… |
| `cogs/ai_core/memory/rag_rust.py` | 36-41 | error-handling | RUST_AVAILABLE is set True solely on RustRagEngine (RagEngine) being truthy (lines 39-40). MemoryEntry and SearchResult are fetch… |
| `cogs/ai_core/storage.py` | 485, 788 | data-loss | Both _replace_history_db (line 485) and _save_history_db (line 788) call db.save_ai_metadata(channel_id=..., thinking_enabled=...… |
| `cogs/ai_core/storage.py` | 112, 271, 294, 882 | resource-leak | The module-level maps _cache_generations (112), _history_locks (271), _post_replace_min_id (294), and _db_loaded_channels (882) a… |
| `cogs/ai_core/storage.py` | 1228-1231 | correctness | restore_message_by_row's stale guard (storage.py:1230) only rejects row ids below _post_replace_min_id, which is set solely by _r… |
| `cogs/ai_core/storage.py` | 782-784 | concurrency | The count-then-prune (storage.py:782-784) plus the trailing save_ai_metadata (788) and invalidate_cache (789) run OUTSIDE the get… |
| `docker/Dockerfile.prod` | 58-61 | bug | The dependency-caching stub writes `echo "fn main() {}" > rust_extensions/media_processor/src/lib.rs` (and same for rag_engine) i… |
| `docs/CODE_AUDIT_GUIDE.md` | 97, 102 | doc-accuracy | The 'cogs/ai_core/ (10 ไฟล์)' table lists `tools.py` (line 97) and `memory_commands.py` (line 102) as files at the cogs/ai_core/ … |
| `docs/DEVELOPER_GUIDE.md` | 871 | doc-accuracy | Known Gotcha #3 says "Streaming Timeout: 30s for the initial chunk (STREAMING_TIMEOUT_INITIAL)". This contradicts the actual cons… |
| `docs/DEVELOPER_GUIDE.md` | 450-452 | doc-accuracy | The table describes HISTORY_LIMIT_DEFAULT/MAIN/RP as an "Approx token budget per channel". In the code these are a stored-message… |
| `docs/DEVELOPER_GUIDE.md` | 1141 | doc-accuracy | The HTML-comment footer says "Version 3.4.5" while the document header (line 4) says Version 3.4.7 and pyproject.toml reports ver… |
| `docs/INSTALL.md` | 366 | doc-accuracy | Footer reads "Last Updated: June 2026 \| Version: 3.4.5" but the current project version is 3.4.7 (pyproject.toml, DEVELOPER_GUIDE… |
| `go_services/health_api/main.go` | 164-168 | concurrency | GetStatus() acquires h.mu.RLock() at line 164 (deferred RUnlock at 165) and then calls runtime.ReadMemStats(&m) at line 168 while… |
| `go_services/url_fetcher/main.go` | 113-128 | performance | isPrivateURL() calls net.LookupIP(hostname) at line 113, and ssrfSafeDialContext() then calls resolver.LookupIPAddr(ctx, host) at… |
| `native_dashboard/README.md` | 244-251 | doc-accuracy | The 'Manual build (if needed — must copy both exes)' block copies the source exe to the Korean name in target/release plus ..\bot… |
| `native_dashboard/src-ts/chat-manager.ts` | 815-827 | error-handling | In the 'error' WS case, data.message is passed unguarded to showToast(data.message as string) and errorLogger.log on both the his… |
| `native_dashboard/src-ts/chat-manager.ts` | 382-388 | correctness | On the 'connected' frame, when no saved provider is valid the code sets `this.aiProvider = data.default_provider \|\| availableProv… |
| `native_dashboard/src-ts/chat-manager.ts` | 1678 | error-handling | finalizeEditStreaming(fullResponse, targetMessageId) resolves the target via this.messages.findIndex(m => m.id === targetMessageI… |
| `native_dashboard/src-ts/chat-manager.ts` | 1897-1901 | correctness | The pin handler's connected branch flips local state optimistically (targetMsg.is_pinned = nextPinned at 1900; renderMessages at … |
| `native_dashboard/src-ts/chat/export-picker.ts` | 62-98 | resource-leak | promptExportFormat() shows a process-wide singleton modal (ensureModal, lines 17-19) and binds a fresh per-call set of click/keyd… |
| `native_dashboard/src-ts/chat/ws-client.ts` | 295 | correctness | When reconnectAttempts first reaches maxReconnectAttempts, onConnectStateChange?.(false) fires twice in quick succession for the … |
| `native_dashboard/src-ts/chat/ws-client.ts` | 132-136 | resource-leak | withTimeout races the invoke() promise against a bare setTimeout(...,8000) whose id is never captured or cleared. When the real p… |
| `native_dashboard/src-ts/shared.ts` | 279-287 | security | isSafeAvatarUrl rejects protocol-relative URLs via `lower.startsWith('//')` (line 279) to uphold its no-external-beacon guarantee… |
| `native_dashboard/src-ts/shared.ts` | 238-288 | correctness | isSafeAvatarUrl returns true for `asset://`/`tauri://` (lines 238-255) and `https://` (line 284), but the effective CSP — identic… |
| `native_dashboard/src/main.rs` | 634-639 | correctness | normalize_ws_connect_host() (line 634-639) only special-cases the empty string and the loopback/bind-all literals "0.0.0.0", "::"… |
| `pyproject.toml` | 40-42 | doc-accuracy | The comment at lines 40-41 claims target-version='py313' is used because 'pre-commit ruff is pinned to v0.9.7 which doesn't recog… |
| `rust_extensions/rag_engine/src/lib.rs` | 204-208 | performance | search() deep-copies the entire entry store (id String, text String, and full embedding Vec<f32> for every entry) into entries_sn… |
| `rust_extensions/rag_engine/src/lib.rs` | 154-169 | error-handling | add_batch() silently drops entries that fail dimension/finite-importance/finite-embedding validation and returns only the inserte… |
| `rust_extensions/rag_engine/src/lib.rs` | 298-389 | data-loss | save() fsyncs the temp file (line 349) and, on the copy fallback, the destination file (line 364), but never fsyncs the containin… |
| `scripts/build_go.ps1` | 46-50 | bug | `go mod tidy` runs on every build (L46-50). tidy mutates go.mod/go.sum and may reach the network to resolve/prune; in offline/pin… |
| `scripts/dev/validate_ipc.py` | 76-81 | resource-leak | `td_err = tempfile.TemporaryFile()` is opened at line 76 immediately before `subprocess.Popen(...)` at line 77, with no try/final… |
| `scripts/dev_watcher.py` | 174-176 | bug | setup_logging() constructs and configures `console_handler` (StreamHandler) at lines 175-176 and sets its level, but never calls … |
| `scripts/dev_watcher.py` | 352-358 | portability | clear_screen() runs `subprocess.run([...'clear'], shell=False, check=False)` on non-Windows. `check=False` only suppresses a non-… |
| `scripts/install_all.ps1` | 197-199 | error-handling | After Expand-Archive, `$ffmpegDir = Get-ChildItem "$DownloadDir\ffmpeg_temp" -Directory \| Select-Object -First 1` (L197). If the … |
| `scripts/maintenance/clean_history.py` | 98 | error-handling | The atomic-write block catches bare `except Exception`, unlinks the temp file, then re-raises (lines 98-103). The outer per-file … |
| `scripts/maintenance/migrate_to_db.py` | 372 | correctness | The --delete-json cleanup block at line 372 is gated solely on `migrated_files > 0`, which counts only successfully migrated HIST… |
| `scripts/maintenance/migrations/003_fix_user_facts.sqlite.sql` | 29-36 | error-handling | The `INSERT INTO user_facts_new SELECT ... FROM user_facts` at lines 29-36 references columns by name (is_user_defined, source_me… |
| `scripts/maintenance/rollback_migration.py` | 148-149 | data-loss | `cmd_diff` reads both the current DB and the backup via `_table_row_counts`/`_get_schema_version`, which both call `sqlite3.conne… |
| `scripts/startup/_common.psm1` | 232-234 | error-handling | Stop-ExistingBot reads PID via `$OldPid = Get-Content $PidFile` (L232). If bot.pid contains multiple lines, Get-Content returns a… |
| `utils/database/database.py` | 1207 | performance | Per-connection `PRAGMA cache_size=250000` is a positive value, which SQLite interprets as 250,000 pages. No `PRAGMA page_size` is… |
| `utils/database/database.py` | 1174 | resource-leak | When a connection is pulled from the pool, liveness is validated with `await conn.execute("SELECT 1")` (L1174) with no per-statem… |
| `utils/database/database.py` | 2597 | style | delete_dashboard_conversation hardcodes the export path as Path("data/db_export/dashboard_chats") instead of deriving it from the… |
| `utils/database/database.py` | 2398 | correctness | get_audit_logs builds the SQLite datetime modifier as f"-{int(days)} days" (line 2398) and passes it to datetime('now', ?) (line … |
| `utils/fast_json.py` | 68-78 | dead-code | The `indent=0` handling and its comment at lines 69-72 is misleading/partially dead. Line 60 raises ValueError for any indent not… |
| `utils/media/ytdl_source.py` | 57 | correctness | max_filesize (300 MiB disk-fill DoS guard, line 57) is a yt-dlp download-side option. In stream mode, from_url calls extract_info… |
| `utils/monitoring/audit_log.py` | 146 | performance | _write_fallback_entry_locked() runs `_FALLBACK_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)` (line 146) and `json.dumps(...… |
| `utils/monitoring/health_api.py` | 728-732 | correctness | The HTML /health endpoint (lines 728-732) always sends status 200 (default of _send_html_response) regardless of bot health, only… |
| `utils/monitoring/performance_tracker.py` | 334-360 | performance | _get_or_create_histogram() mints one permanent Prometheus Histogram per distinct sanitized operation name and caches it in _prom_… |
| `utils/monitoring/performance_tracker.py` | 367-369 | dead-code | get_prometheus_metrics() and the private bridge registry _prom_registry (line 325) are never referenced outside their own definit… |
| `utils/monitoring/performance_tracker.py` | 163-176 | concurrency | record() is called from worker contexts (api_handler.py:1239) and the sync decorator path, but self._stats[operation] / self._hou… |
| `utils/monitoring/structured_logger.py` | 237 | error-handling | HumanReadableFormatter.format does ctx['request_id'][:8] after only a truthiness check (line 236-237). The contextvar is populate… |
| `utils/reliability/error_recovery.py` | 121-135 | correctness | A freshly created BackoffState has last_failure_time=0.0 (dataclass default, line 97). In _cleanup_old_backoff_states the first e… |
| `utils/reliability/error_recovery.py` | 233-244 | concurrency | calculate_delay_sync acquires the module-global non-reentrant _backoff_states_lock (threading.Lock, line 102) inside the DECORREL… |
| `utils/reliability/memory_manager.py` | 443-449 | api-misuse | _run_cleanups invokes each registered callback synchronously (`cleaned = callback()`, line 445) and treats the result as an int t… |
| `utils/reliability/rate_limiter.py` | 553-568 | correctness | reload_limits() calls _setup_defaults() which calls add_config(); add_config (line 260-262) only assigns self._configs[name] = co… |
| `utils/reliability/self_healer.py` | 210-218 | correctness | In find_all_bot_processes, is_bot is set by an exact basename match (name.lower() == 'bot.py') at line 214, but the ignore_list [… |
| `utils/reliability/self_healer.py` | 361 | correctness | find_all_bot_processes (lines 248-264) removes venv-launcher PIDs (those whose ppid is itself in the bot set) from the returned l… |
| `utils/web/url_fetcher.py` | 377 | correctness | In the GitHub repo branch, `url` is mutated in place at lines 377-378 (`if not url.endswith('/'): url += '/'`) before the api_url… |

## ⚪ NIT (60)

| File | Line | Cat | Detail |
|---|---|---|---|
| `.github/workflows/ci.yml` | 178 | style | ci.yml:178 runs `python -m pytest tests/ -v ...` while pyproject.toml addopts (line 16) already contains `-v`, so verbosity is du… |
| `Makefile` | 29 | doc-accuracy | The `test` target comment hardcodes '~15s, 3143 tests' while CLAUDE.md states ~5,050+ pytest tests at v3.4.7, so the count is sta… |
| `cogs/ai_core/ai_cog.py` | 675-677 | correctness | on_raw_message_edit reads `new_content = data.get('content')` and returns early when `not new_content`. An edit that clears a mes… |
| `cogs/ai_core/api/dashboard_chat_claude_cli.py` | 933 | error-handling | In _save_inline_images, the per-image base64 decode is guarded (lines 918-921, continue on ValueError/binascii.Error) and oversiz… |
| `cogs/ai_core/api/dashboard_chat_claude_cli.py` | 1046 | error-handling | Same unguarded-write pattern in _save_inline_documents: base64 decode is caught at 1034-1037 (continue) but the binary write path… |
| `cogs/ai_core/api/dashboard_chat_claude_cli.py` | 2367 | doc-accuracy | The timeout-budget rationale comment at line 2366-2368 says 'Opus 4.7 reasoning silently before any stdout event', but CLAUDE_MOD… |
| `cogs/ai_core/api/dashboard_chat_claude_cli.py` | 2420 | style | The start breadcrumb logs `len(documents_raw) if isinstance(documents_raw, list) else 0` (line 2420 — uncapped submitted doc coun… |
| `cogs/ai_core/api/discord_chat_claude_cli.py` | 862-864 | resource-leak | On a genuine external CancelledError (not the user-cancel path) re-raised at line 744, the exception is BaseException-level and i… |
| `cogs/ai_core/api/discord_chat_claude_cli.py` | 161-169 | performance | _get_channel_lock's LRU eviction loop breaks out of the entire while-loop the first time the oldest entry is a currently-held loc… |
| `cogs/ai_core/cache/token_tracker.py` | 447-448 | concurrency | _persist_usage releases _persist_lock (end of the `async with` at 440-442) then, when queue_len >= PERSIST_BATCH_SIZE, calls _flu… |
| `cogs/ai_core/cache/token_tracker.py` | 608-613 | correctness | get_global_stats reports unique_users as len(user_records) where user_records is the user: subset of the cache snapshot (line 611… |
| `cogs/ai_core/commands/debug_commands.py` | 131-133 | error-handling | In ai_debug the Performance panel iterates perf.items() and reads data["count"]/data["avg_ms"] with raw subscripting (lines 131-1… |
| `cogs/ai_core/logic.py` | 2004-2017 | correctness | In the multi-character ({{Name}}) webhook path, the model turn is persisted by save_history() at lines 1831-1833 before the per-c… |
| `cogs/ai_core/logic.py` | 1770 | data-loss | On the cancelled-after-API path, a STREAMING reply's partial text is intentionally not persisted (guard `model_text and model_tex… |
| `cogs/ai_core/memory/entity_memory.py` | 424 | correctness | In the update_access branch of get_entity, `row` is fetched at line 416, the UPDATE `access_count = access_count + 1` runs at lin… |
| `cogs/ai_core/memory/rag_rust.py` | 51 | doc-accuracy | Docstring example comment says 'dimension=768 # text-embedding-004 / 005' but the project migrated embeddings to gemini-embedding… |
| `cogs/ai_core/memory/summarizer.py` | 192 | error-handling | In the broad `except Exception` branch (lines 168-193), a retryable Anthropic error (e.g. RateLimitError) on the FINAL attempt ha… |
| `cogs/ai_core/sanitization.py` | 111 | bug | For pathologically small max_length (< 3) with len(content) > max_length, `cut = max_length - 3` is 0 or negative. rewind_limit =… |
| `cogs/music/cog.py` | 103 | style | Function-local re-imports that shadow module-level imports already present at the top of the file: line 103 `import time as _time… |
| `docs/CODE_AUDIT_GUIDE.md` | 47 | doc-accuracy | The 'Run All Tests' snippet recommends `python -m pytest tests/ -v` (line 47, repeated at line 367 in Quick Commands), which cont… |
| `docs/DEVELOPER_GUIDE.md` | 890 | doc-accuracy | Gotcha #22 says dashboard chat catches both TimeoutError and asyncio.TimeoutError "for Python 3.10 compatibility". The project re… |
| `docs/INSTALL.md` | 217 | doc-accuracy | The Tauri and Rust Prerequisites lists restart numbering at "1." for every item (lines 208, 217, 224 under Tauri; 259 under Rust)… |
| `docs/INSTALL.md` | 294 | doc-accuracy | Verify-installation steps recommend `python -m pytest tests/ -v` (lines 294 and 351). CLAUDE.md explicitly warns 'Never run raw p… |
| `docs/TROUBLESHOOTING.md` | 84 | doc-accuracy | On lines 84 and 115 the inline comment is placed before the pipe: `curl http://localhost:9090/metrics # Python metrics (PROMETHEU… |
| `go_services/health_api/main.go` | 550-552 | error-handling | In /metrics/batch, entries with an unknown metric type or unknown/disallowed name are silently skipped (line 501-503 skips unknow… |
| `go_services/url_fetcher/main.go` | 250 | style | The Fetch method's parameter `url string` (line 250) shadows the imported net/url package within Fetch's scope. It compiles becau… |
| `native_dashboard/playwright.config.ts` | 45 | portability | reuseExistingServer is true on non-CI (dev) machines and webServer.port is 5173, the Vite default (confirmed lines 43-45, baseURL… |
| `native_dashboard/playwright.config.ts` | 43 | portability | webServer.command invokes a bare 'python' (confirmed line 43). CLAUDE.md warns a freshly spawned Windows shell may start without … |
| `native_dashboard/src-ts/app.ts` | 2086 | style | failure_rate is coerced via `Number(ep.failure_rate) \|\| 0` (line 2074) and interpolated raw as `${failureRate}%` (line 2086). A s… |
| `native_dashboard/src-ts/chat-manager.ts` | 684-693 | style | The 'conversation_starred' case declares `const conv` directly in the switch body (line 685) without a wrapping block `{ }`, unli… |
| `native_dashboard/src-ts/chat-manager.ts` | 781 | style | `(this.currentConversation as unknown as Record<string, unknown>).tags = data.tags as string[]` double-casts through unknown to a… |
| `native_dashboard/src-ts/chat-manager.ts` | 2421 | correctness | saveChatFileEditor guards with `if (!this.editingDocId \|\| ...)` (line 2421). editingDocId is `number\|null` (line 2322). A documen… |
| `native_dashboard/src-ts/chat/conversation-list.ts` | 76-83 | resource-leak | The empty-conversations branch (lines 61-69) and the no-match branch (lines 76-83) replace container.innerHTML and return early W… |
| `native_dashboard/src-ts/chat/document-attach.ts` | 35-38 | doc-accuracy | MAX_DOC_SIZE (32 MB, line 37) and MAX_ATTACHED_DOCS (5, line 38) are hand-duplicated from the Python backend with a 'keep in sync… |
| `native_dashboard/src/bot_manager.rs` | 368-371 | correctness | read_logs() estimates ~1KB/line via (count as u64).saturating_mul(1024) then hard-caps max_read at 1MB (line 369-370). When the c… |
| `rust_extensions/media_processor/media_processor.pyi` | 1-43 | doc-accuracy | The .pyi stub omits the module-level attributes the Rust extension actually exports. In media_processor/src/lib.rs the #[pymodule… |
| `rust_extensions/media_processor/src/gif.rs` | 39 | style | In is_animated_gif the 0x21 (extension) branch does i += 2 unconditionally (gif.rs:39), whereas the otherwise-identical get_gif_f… |
| `rust_extensions/media_processor/src/lib.rs` | 121, 140, 156 | performance | resize(), resize_exact() and thumbnail() each call check_bomb_dimensions(bytes) (lib.rs:121/140/156), which builds an image::Imag… |
| `rust_extensions/rag_engine/rag_engine.pyi` | 1-39 | doc-accuracy | The rag_engine.pyi stub omits the module-level `__version__` and `__author__` the Rust extension exports. In rag_engine/src/lib.r… |
| `rust_extensions/rag_engine/src/cosine.rs` | 23-25 | correctness | The zero-vector guard short-circuits only exactly-zero vectors (x == 0.0 for all components). A vector with tiny nonzero componen… |
| `scripts/bot_manager.py` | 461 | performance | get_bot_status() calls pr.cpu_percent(interval=0.05) inside the for p in all_bot_pids loop (line 461), so each status refresh blo… |
| `scripts/build_rust.ps1` | 48-50 | portability | `$IsWindows -or $env:OS -match "Windows"` (L48-50): on Windows PowerShell 5.1 the automatic $IsWindows variable does not exist ($… |
| `scripts/install_all.ps1` | 85-87 | style | Function `Refresh-Path` (L85) uses the unapproved verb 'Refresh' (triggers PSUseApprovedVerbs on script/module analysis). Purely … |
| `scripts/maintenance/clean_cli_orphans.py` | 99 | correctness | When a session DIRECTORY is deleted (the os.walk loop at lines 99-118), the bytes of the files inside it are never added to `dele… |
| `scripts/maintenance/convert_log015.py` | 37 | correctness | `_CALL_RE` anchors each match with a leading `(^\|\r?\n)` group that is CONSUMED by the match, and `re.subn` resumes scanning afte… |
| `scripts/maintenance/migrate_to_db.py` | 160 | correctness | The migration INSERT (lines 160-166) omits the `user_id` column, whereas the production write path (utils/database/database.py:15… |
| `scripts/maintenance/watch_history.py` | 143 | correctness | `_one_line` truncates with `text[: width - 1] + '…'`. With `--width 0` (or negative), `width-1` becomes -1 and `text[:-1]` drops … |
| `utils/database/database.py` | 3521 | correctness | The unlink lambda `lambda p: (p.unlink(), True)[1] if p.exists() else False` (line 3521) has a TOCTOU window between p.exists() a… |
| `utils/database/database.py` | 2388 | dead-code | get_audit_logs sets `conn.row_factory = aiosqlite.Row` at line 2388, but get_connection already sets row_factory to aiosqlite.Row… |
| `utils/database/database.py` | 2635 | correctness | save_dashboard_message serializes images only when truthy: `images_json = json.dumps(images, ensure_ascii=False) if images else N… |
| `utils/localization.py` | 231-237 | api-misuse | `LocalizedMessages.__getattr__` returns `self.get(key)` for any non-underscore attribute, even unknown keys (only logs a warning)… |
| `utils/monitoring/alerting.py` | 106 | doc-accuracy | _try_acquire_cooldown is annotated to return tuple[bool, float, float \| None] and the body returns 3-tuples at line 121 (False, l… |
| `utils/monitoring/health_api.py` | 1288 | concurrency | setup_health_hooks' on_ready listener does health_data.is_ready = True off-lock (line 1288), whereas update_from_bot writes is_re… |
| `utils/monitoring/health_api.py` | 1190 | concurrency | health_data.feature_flags is reassigned off-lock at line 1190 and again at line 1228, while to_dict() copies it under _data_lock … |
| `utils/monitoring/logger.py` | 23 | correctness | EMOJI_MAP keys '⚠️' (line 23) and 'ℹ️' (line 38) include the U+FE0F variation selector. safe_ascii/safe_unicode do literal str.re… |
| `utils/reliability/circuit_breaker.py` | 216 | correctness | In record_failure (line 216-218) and async_record_failure (line 352-353), when a HALF_OPEN probe fails the breaker transitions to… |
| `utils/reliability/memory_manager.py` | 134-136 | performance | _estimate_size (line 136) returns sys.getsizeof(value), the shallow size of the top-level container only (e.g. dict/list header),… |
| `utils/reliability/self_healer.py` | 335 | correctness | diagnose() (line 335) and auto_heal() (line 671) set 'timestamp': datetime.datetime.now().isoformat(), producing a naive local-ti… |
| `utils/web/url_fetcher.py` | 63-103 | security | _SSRFSafeResolver (the connect-time DNS-rebind guard installed on the shared session at line 122) is only invoked by aiohttp's TC… |
| `utils/web/url_fetcher.py` | 42-60 | concurrency | _get_session_lock() (lines 42-52) and _get_url_cache_lock() (lines 55-60) lazily construct their asyncio.Lock with a plain `if x … |
