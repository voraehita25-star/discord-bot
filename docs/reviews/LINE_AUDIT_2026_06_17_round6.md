# Line-by-line audit — 2026-06-17 (round 6)

Sixth pass in the v3.4.8–v3.4.13 line-by-line audit series. Every non-test
source file across all four stacks (Python, TypeScript, Rust, Go) plus the
hand-authored UI, scripts, SQL migrations and build/config was re-read
**line-by-line** — bin-packed into **77 work-units / 207 files / 93,910 lines**,
each read by a fan-out auditor and then **independently re-read by an
adversarial, refute-by-default verifier**. **122 agents** produced **62
confirmed findings** (**0 critical, 2 high, 15 medium, 37 low, 8 info**). All 62
were fixed and the full suite re-verified green; a handful of opportunistic
improvements were applied alongside (Go `min` modernization, `hashlib.md5`
`usedforsecurity=False`, a fresh-DB guard on migration 002).

All fixes verified: **Python 5,066 pass / 2 skip**, **TS 298 vitest + tsc**,
**Rust `cargo test`/`clippy`**, **Go `vet`/`test`**, **ruff** + **bandit** (0 high) clean.

| # | Severity | File : line | Category | Finding | Resolution |
|---|---|---|---|---|---|
| 1 | high | `scripts/dev_watcher.py`:76-78, 716, 744 | correctness | `data/` ignore pattern silently disables hot reload for all tracked source under cogs/ai_core/data/ | Fixed |
| 2 | high | `scripts/maintenance/reindex_db.py`:435-436 | api-misuse | conn.isolation_level = None on an aiosqlite connection raises ProgrammingError, crashing the reindex success path after the migration already committed | Fixed |
| 3 | medium | `cogs/ai_core/api/ws_dashboard.py`:300-349 | resource-leak | AppRunner leaked when start() fails after runner.setup() (TLS early-return and site.start() bind failure) | Fixed |
| 4 | medium | `cogs/music/cog.py`:546-567 | correctness | Settings sidecar (volume/loop/mode_247) is never restored when the DB queue is empty on restart — 24/7 mode silently lost | Fixed |
| 5 | medium | `scripts/dev_watcher.py`:666-668 | concurrency | Crash auto-retry holds _lock across the multi-second health-check sleep, stalling the observer thread | Fixed |
| 6 | medium | `scripts/maintenance/migrations/002_sync_defaults.sqlite.sql`:6-35 | data-corruption | Migration 002 DROPs and recreates token_usage and conversation_summaries with no data copy, silently destroying rows on a legacy (pre-migration-system) DB upgrade | Fixed |
| 7 | medium | `cogs/ai_core/api/api_handler.py`:846-876 | error-handling | Streaming path records circuit-breaker + failover SUCCESS on a 200-but-empty stream, masking a sick endpoint | Fixed |
| 8 | medium | `cogs/ai_core/api/dashboard_chat.py`:156, 213, 230 | data-corruption | Gemini handler trusts client-supplied is_regeneration without validation (skips user-message persistence + document extraction) | Fixed |
| 9 | medium | `cogs/ai_core/api/dashboard_chat.py`:194 | correctness | Documents-only message rejected as 'Empty message', dropping uploaded documents (Gemini-vs-Claude asymmetry) | Fixed |
| 10 | medium | `cogs/ai_core/api/dashboard_chat_claude.py`:460-462 | error-handling | Frontend-history fallback loop lacks per-item dict guard — AttributeError hangs the client UI | Fixed |
| 11 | medium | `cogs/ai_core/media_processor.py`:453-470 | error-handling | load_character_image's except only catches OSError, letting PIL decompression-bomb errors escape and fail the whole AI turn | Fixed |
| 12 | medium | `cogs/ai_core/memory/entity_memory.py`:99-101 | error-handling | EntityFacts.to_prompt_text() calls .items() on relationships without isinstance guard | Fixed |
| 13 | medium | `scripts/install_all.ps1`:437-451 | correctness | Final installation summary falsely reports broken tools as [OK] because the Check scriptblock's $? is overridden by stdout output | Fixed |
| 14 | medium | `scripts/install_all.ps1`:55-56 | error-handling | Unhandled throw from Invoke-VerifiedDownload aborts the 'resilient' installer on a transient network error, skipping remaining steps and the summary | Fixed |
| 15 | medium | `scripts/maintenance/clean_cli_orphans.py`:18-25 | api-misuse | Orphan-cleaner path encoder diverges from production Claude-CLI encoder (misses '.', etc.) -> scans wrong folder | Fixed |
| 16 | medium | `scripts/maintenance/count_cli_sessions.py`:19-37 | api-misuse | Survey encoders both use the old fixed-subset encoding; never match production and MISMATCH detector can never fire | Fixed |
| 17 | medium | `utils/monitoring/structured_logger.py`:199-205 | data-corruption | StructuredFormatter redacts AFTER JSON serialization, producing invalid JSON for keyword-prefixed secrets | Fixed |
| 18 | low | `native_dashboard/ui/index.html`:771 | correctness | Stale hardcoded version string (3.4.11 vs actual 3.4.12) | Fixed |
| 19 | low | `cogs/ai_core/api/discord_chat_claude_cli.py`:483-504 | concurrency | _summarize_channel_history captures chat_data before the processing lock and never re-fetches inside it (inconsistent with the hardened !auto_summarize sibling) | Fixed |
| 20 | low | `cogs/ai_core/commands/server_commands.py`:807 | correctness | cmd_set_channel_perm: role lookup is exact-case only and shadows same-named member | Fixed |
| 21 | low | `cogs/ai_core/commands/server_commands.py`:767-769 | error-handling | cmd_set_channel_perm does not strip perm_name/value before parsing (inconsistent with cmd_set_role_perm) | Fixed |
| 22 | low | `cogs/ai_core/commands/server_commands.py`:568-594 | correctness | cmd_add_role / cmd_remove_role have no duplicate-role-name guard (unlike cmd_delete_role) | Fixed |
| 23 | low | `cogs/music/cog.py`:1579-1591 | error-handling | fix command's disconnect-failure early return bypasses the deferred cleanup_pending drain | Fixed |
| 24 | low | `go_services/url_fetcher/main.go`:117 | robustness | isPrivateURL uses context-less net.LookupIP on the request hot path, ignoring request deadline/cancellation | Fixed |
| 25 | low | `go_services/url_fetcher/main.go`:334-342 | error-handling | Charset transcoding failure silently falls back to raw (possibly non-UTF-8) bytes | Fixed |
| 26 | low | `native_dashboard/src-ts/chat-manager.ts`:1277-1285 | correctness | Successful /edit command leaves a stale '/edit ...' draft in localStorage | Fixed |
| 27 | low | `native_dashboard/src-ts/chat-manager.ts`:583-637 | robustness | A stream_end arriving after an error frame for the same turn pushes a phantom assistant message | Fixed |
| 28 | low | `native_dashboard/src-ts/chat/search.ts`:32-42 | correctness | Re-entrant open() (repeated Ctrl+F) clobbers previousFocus with the search input, breaking focus restoration on Escape | Fixed |
| 29 | low | `utils/database/migrations.py`:164-183 | robustness | Statement splitter cannot separate two SQL statements sharing one line; conn.execute then raises 'one statement at a time' | Fixed |
| 30 | low | `utils/media/ytdl_source.py`:446-453 | error-handling | search_source fallback extract_info is not guarded, so it can raise instead of honoring its documented `-> dict \| None` contract | Fixed |
| 31 | low | `utils/media/ytdl_source.py`:363-389 | resource-leak | Downloaded temp file is orphaned when a post-download validation check raises in download mode | Fixed |
| 32 | low | `utils/monitoring/health_api.py`:1044-1052 | concurrency | Filesystem deep-health check races itself across request threads, causing spurious 503 | Fixed |
| 33 | low | `utils/monitoring/health_client.py`:314-317 | error-handling | Metrics chunk silently dropped on recoverable HTTP 4xx/5xx (e.g. 401 after sidecar restart) | Fixed |
| 34 | low | `utils/monitoring/performance_tracker.py`:307-313 | error-handling | Background cleanup loop dies permanently on any non-cancellation exception | Fixed |
| 35 | low | `utils/reliability/shutdown_manager.py`:483-507 | correctness | _atexit_handler join loop degrades to sum(timeouts), not the documented max(timeout) | Fixed |
| 36 | low | `cogs/ai_core/api/dashboard_chat.py`:484, 625, 834 | correctness | LeadingTimestampStripper buffer carries across tool rounds, can splice round-1 partial text into round-2 output | Fixed |
| 37 | low | `cogs/ai_core/api/dashboard_chat_claude_cli.py`:2522-2573 | data-corruption | Empty user-message row persisted to DB when all attachments fail to decode | Fixed |
| 38 | low | `cogs/ai_core/api/dashboard_chat_claude_cli.py`:3048-3079 | resource-leak | finally cleanup partially skipped if the request task is cancelled mid-cleanup, leaking this-turn temp attachment files | Fixed |
| 39 | low | `cogs/ai_core/api/dashboard_handlers.py`:1444-1461 | error-handling | handle_save_profile crashes into INTERNAL_ERROR when client sends a non-dict 'profile' | Fixed |
| 40 | low | `cogs/ai_core/memory/history_manager.py`:424-434 | performance | Importance regex scan for large histories runs synchronously on the event loop despite the token-estimation offload | Fixed |
| 41 | low | `cogs/ai_core/memory/rag_rust.py`:90-97 | api-misuse | Python fallback add() skips the dimension/finite validation the Rust add() enforces | Fixed |
| 42 | low | `cogs/ai_core/tools/tool_executor.py`:367-370 | robustness | list_members appends non-string `query` to cmd_args without str() coercion | Fixed |
| 43 | low | `cogs/music/queue.py`:289-330 | error-handling | DB load path returns True with a silently-emptied queue when every row is invalid | Fixed |
| 44 | low | `cogs/music/queue.py`:194-221 | correctness | QueueManager.save_queue never persists volume/loop/24-7 settings when a DB is available | Fixed |
| 45 | low | `cogs/spotify_handler.py`:362 | error-handling | Unsafe `.get(key, default)` chain on external_urls — explicit Spotify null causes AttributeError | Fixed |
| 46 | low | `cogs/spotify_handler.py`:376-387 | error-handling | `album = track.get("album", {})` does not coerce explicit null; later album.get(...) raises AttributeError | Fixed |
| 47 | low | `cogs/spotify_handler.py`:173-198 | api-misuse | Half-open circuit slot leaked when func raises an exception type outside the retry except tuple | Fixed |
| 48 | low | `scripts/build_rust.ps1`:37-70 | error-handling | Rust build reports overall success even when an expected .pyd is missing (missing copy source only emits a WARN) | Fixed |
| 49 | low | `scripts/maintenance/reindex_db.py`:101 | error-handling | Backup copy raises an unhandled FileNotFoundError with a raw traceback when the DB file is missing | Fixed |
| 50 | low | `scripts/maintenance/view_db.py`:27 | robustness | Missing DB path silently creates an empty database file and exports nothing while printing success | Fixed |
| 51 | low | `scripts/startup/_common.psm1`:17-22 | error-handling | Fallback default config omits bot.check_dependencies, silently disabling the dependency gate when startup.json is absent | Fixed |
| 52 | low | `scripts/startup/_common.psm1`:232-233 | error-handling | Malformed bot.pid contents are never cleaned up by Stop-ExistingBot | Fixed |
| 53 | low | `utils/reliability/error_recovery.py`:128-142 | concurrency | TTL cleanup ignores the in-flight pin that the hard-cap eviction honors | Fixed |
| 54 | low | `utils/reliability/error_recovery.py`:400-404 | concurrency | Gap between fetching backoff state and pinning it allows eviction/recreate race | Fixed |
| 55 | info | `cogs/ai_core/__init__.py`:44-48 | dead-code | except-ImportError fallback for validate_response is unreachable; it can never be None | Fixed |
| 56 | info | `rust_extensions/rag_engine/Cargo.toml`:18-20 | stale-documentation | Cargo.toml comment claims File::lock_exclusive/unlock file locking that does not exist in the crate | Fixed |
| 57 | info | `utils/monitoring/sentry_integration.py`:353-369 | api-misuse | User payload always includes username key even when None | Fixed |
| 58 | info | `utils/reliability/rate_limiter.py`:527-528 | dead-code | Unreachable `else 15` default in get_channel_limit; stale literal vs configured 60 | Fixed |
| 59 | info | `cogs/ai_core/memory/rag_rust.py`:144-192 | api-misuse | _python_search does not reject non-finite query embeddings the way the Rust search() does | Fixed |
| 60 | info | `cogs/ai_core/tools/tool_executor.py`:730-734 | api-misuse | execute_server_command dispatch keys are case-sensitive and mismatch COMMAND_HANDLERS' UPPER_CASE keys | Fixed |
| 61 | info | `cogs/music/utils.py`:66-76 | api-misuse | format_duration raises ValueError on NaN/inf input (latent footgun) | Fixed |
| 62 | info | `scripts/startup/_common.psm1`:116-119 | correctness | Astral-plane (emoji) wide-char branch in Get-DisplayWidth is unreachable; width correct only by coincidence | Fixed |
