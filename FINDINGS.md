# Code Review Findings — 2026-05-15

156 source files reviewed across 9 parallel agents (excluding tests). Each file read end-to-end.

Severity: **C**=Critical · **H**=High · **M**=Medium · **L**=Low

---

## CRITICAL (1)

| # | File | Line | Issue | Fix |
|---|------|-----:|-------|-----|
| C1 | cogs/ai_core/memory/rag.py | 398 | `np.load(..., allow_pickle=True)` on legacy `.npy` — RCE if attacker writes to `data/faiss/` | Gate behind `RAG_ALLOW_LEGACY_PICKLE=1` env flag |

## HIGH (40)

| # | File | Line | Issue | Fix |
|---|------|-----:|-------|-----|
| H1 | bot.py | 950 | `while True` around `bot.run()`: `LoginFailure`/`OSError` escapes loop to outer except, no retry actually happens | Catch login/OSError inside loop, or drop misleading loop |
| H2 | bot.py | 974 | Resume path uses `asyncio.run(old_bot.close())` not `graceful_shutdown`; dashboard ws / DB / health leak | Use `graceful_shutdown(bot_instance=old_bot)` |
| H3 | cogs/ai_core/logic.py | 1086 | `generate_response=False` branch leaks dedup key (no `remove_request` before return) | Add `self._deduplicator.remove_request(request_key)` |
| H4 | cogs/ai_core/logic.py | 1196 | Cancellation path saves history then raises; pending-merge pass may double-save same message | Sentinel in `chat_data`, skip re-save |
| H5 | cogs/ai_core/logic.py | 1429-1433 | Thai-combining-mark walk can push `split_at` past 2000 → Discord 400 error | After walk, if `split_at > 2000` fall back to last non-combining before 2000 |
| H6 | cogs/ai_core/ai_cog.py | 1196-1224 | `resend_last_message` no cap on `{{Name}}` blocks (logic.py has 60-cap) | Apply same 60-element cap |
| H7 | cogs/ai_core/storage.py | 484-498 | `_content_key(m)` = first 200 chars; inconsistent with full-content SHA-256 elsewhere; dedup drops divergent messages | Hash full content |
| H8 | cogs/ai_core/media_processor.py | 558, 674 | `process_attachments` runs sync `convert_gif_to_video` inline → blocks entire event loop for 60s+ | `await loop.run_in_executor(None, convert_gif_to_video, ...)` |
| H9 | cogs/ai_core/media_processor.py | 326-368 | Fresh `ThreadPoolExecutor(max_workers=1)` per GIF call | Use module-level shared executor |
| H10 | cogs/ai_core/session_mixin.py | 232-258 | Cleanup race: can evict freshly-loaded session between save and pop | Re-check time delta + presence after save |
| H11 | cogs/ai_core/memory/rag.py | 246, 763-789 | Per-row `add_single` under `_lock` during reconcile starves search | Build fresh index in worker, swap atomically |
| H12 | cogs/ai_core/memory/rag.py | 732-734, 804-806 | `_ensure_index` doesn't catch `TimeoutError` → `_index_built=False` forever, retries on every call | `try/except TimeoutError` around both `wait_for` |
| H13 | cogs/ai_core/memory/rag.py | 942-966 | `add_memory` commits DB before FAISS dim validation → orphan rows that fail re-index forever | Validate dim before DB save |
| H14 | cogs/ai_core/memory/long_term_memory.py | 720-727 | No UNIQUE constraint; duplicate facts can stack via `add_explicit_fact` | UNIQUE on `(user_id, content_hash)` |
| H15 | cogs/ai_core/cache/analytics.py | 222-246 | `_save_to_db` reads module-level `db` without None-check | Add `if db is None: return` |
| H16 | cogs/ai_core/cache/token_tracker.py | 419-430 | `_persist_usage` releases lock then conditionally calls `_flush_persist_queue` → double-flush race (benign but unclear) | Hold lock to swap; minor |
| H17 | cogs/ai_core/core/message_queue.py | 131-169 | Lock eviction while waiters present → orphan `await lock.acquire()` never wakes | Track waiter count; only evict if no waiters |
| H18 | cogs/ai_core/core/message_queue.py | 56, 86 | `asyncio.Lock()` created in sync context may bind to wrong loop | Check running loop in `get_lock` |
| H19 | cogs/ai_core/tools/tool_executor.py | 561-568, 742-749 | Fallback `channel.send` paths missing `allowed_mentions=AllowedMentions.none()` → `<@id>` in name/message can ping | Add `allowed_mentions=discord.AllowedMentions.none()` everywhere |
| H20 | cogs/ai_core/tools/tool_executor.py | 388-456 | `remember` tool denylist bypassable via Cyrillic confusables surviving NFKD→ASCII strip | Use Unicode confusables normalization or stricter allowlist |
| H21 | cogs/ai_core/api/dashboard_chat_claude.py | 919 | Retry prefill resends raw `partial` text as assistant message — prompt-injection echo | Validate or use `build_claude_message` |
| H22 | cogs/ai_core/api/dashboard_chat_claude.py | 1192-1498 | SDK edit path missing empty-content guard (CLI version has it at L2096) | Add `if not final_content or not final_content.strip(): keep original` |
| H23 | cogs/ai_core/api/dashboard_chat_claude_cli.py | 1537, 2030 | Manual `lock.acquire()` + flag pattern leaks lock on CancelledError | Use `async with lock:` |
| H24 | cogs/ai_core/api/document_extractor.py | 302 | Zip entries iterated by `info.filename` without traversal validation | Reject names with `/`, `\`, `..` |
| H25 | cogs/ai_core/api/ws_dashboard.py | 711 | Pre-auth 4 KiB cap only applies to `str` frames; `bytes` bypasses | Cap `(str, bytes)` length |
| H26 | cogs/ai_core/api/ws_dashboard.py | 758, 1106 | `get_client()` may raise `RuntimeError` mid-stream; not caught | Wrap in try/except |
| H27 | cogs/music/cog.py | 1525 | Spotify URL inside `<...>` (Discord suppress-embed) falls through to YouTube search | Strip `<>` before `urlparse` |
| H28 | cogs/music/url_safety.py | 65 | SSRF guard checks literal IPs only — DNS records to private IPs allowed | Resolve via `socket.getaddrinfo` and reject private |
| H29 | cogs/music/cog.py | 686-720 | Lock release helper assumes no exceptions; future-fragile deadlock | Make `_release_if_timed_out` defensive |
| H30 | cogs/music/cog.py | 768, 915, 1292, 2079 | `after_playing*` callbacks call `_gs()` from non-loop thread → `asyncio.Lock()` binds to None loop | Pre-create state, or bounce to loop |
| H31 | cogs/music/cog.py | 787, 938, 1309 | After-callback uses captured `vc_callback` not live `ctx.guild.voice_client` → freezes queue after reconnect | Look up VC at callback time |
| H32 | scripts/check_balance.py | 45 | Author's own warning comment unimplemented: `endswith` allows `evil-openrouter.ai` | Exact match for non-dot entries |
| H33 | scripts/maintenance/dump_cli_prompt.py | 35 | LIKE pattern `%{title_substr}%` doesn't escape `%`/`_` wildcards | `replace("%","\\%")` + `ESCAPE '\'` |
| H34 | scripts/maintenance/find_unused.py | 91-94, 30 | entry_points check dead (relative-vs-absolute mismatch); regex misses relative imports `from .x` | Use absolute paths; use `ast.parse` |
| H35 | scripts/maintenance/reindex_db.py | 41, 242 | No bot.pid guard before backup; `except BaseException` catches Ctrl-C mid-commit | Add PID check; SIG_IGN during critical section |
| H36 | scripts/maintenance/rollback_migration.py | 213-218 | Silent WAL/SHM unlink failure can leave restored DB + stale WAL → SQLite recovery corruption | Abort with clear message if unlink fails |
| H37 | scripts/dev_watcher.py | 23, 846 | Module `logger` separate from `setup_logging`-created `DevWatcher` logger; debug logs to dead logger. `path="."` follows chdir | Use single logger; pass `str(PROJECT_ROOT)` |
| H38 | scripts/verify_system.py | 18, 25 | `rglob` recurses into vendor dirs; `UnicodeDecodeError` uncaught → crash | Exclude `.venv` `node_modules` etc.; add `UnicodeDecodeError` to except |
| H39 | rust_extensions/media_processor/src/lib.rs | 184-202 | `batch_resize` clones every image to owned `Vec<u8>` before releasing GIL → 500MB peak for 100×5MB batch | Process in chunks |
| H40 | rust_extensions/rag_engine/src/storage.rs | 113 | `unsafe MmapOptions::map_mut` — SIGBUS if external process truncates | Document as known-risk |
| H41 | native_dashboard/src-ts/app.ts | 1564 | Avatar-crop Escape handler binds on document, never removed; closure pins modal | Track handler ref, remove in `closeCropModal` |

## MEDIUM (~75)

### Python — AI core orchestration
| File | Line | Issue | Fix |
|------|-----:|-------|-----|
| bot.py | 311 | atexit PID-remove race with another bot instance | Move `_write_pid_file()` earlier; exclusive lock |
| cogs/ai_core/logic.py | 989 | Auto-compress: compressed list used for API only, `chat_data["history"]` not updated → next save sees uncompressed | Assign back `chat_data["history"]` |
| cogs/ai_core/logic.py | 1373/1394/1419/1434 | No try/except around webhook/`send_channel.send`; one HTTPException kills entire split | Wrap each send |
| cogs/ai_core/logic.py | 1505-1512 | `_process_pending_messages` runs after `lock.release()` outside finally lock | Document, no fix needed |
| cogs/ai_core/ai_cog.py | 606 | `hasattr(...) → set()` non-atomic | Init in `__init__` |
| cogs/ai_core/ai_cog.py | 1518-1523 | `days` param unbounded | Cap `1..365` |
| cogs/ai_core/ai_cog.py | 1589-1591 | `if k not in dict` race | Use `setdefault` |
| cogs/ai_core/sanitization.py | 110 | `content[cut]` IndexError when cut == len | Add `min(cut, len-1)` |
| cogs/ai_core/storage.py | 654 | No fsync before atomic replace | Add `os.fsync` |
| cogs/ai_core/storage.py | 16-30 | orjson hard import; no fallback | Wrap try/except or declare hard dep |
| cogs/ai_core/voice.py | 70 | `connect` timeout on Stage channels | None — protocol minimal |
| cogs/ai_core/emoji.py | 86 | Broad `except Exception` | Narrow tuple |
| cogs/ai_core/session_mixin.py | 121, 281 | Wholesale system_instruction replace; metadata-only save inefficient | Add metadata-only helper |
| cogs/ai_core/media_processor.py | 220 | OrderedDict mutation lockless | Document single-loop |

### Python — Memory
| File | Line | Issue | Fix |
|------|-----:|-------|-----|
| cogs/ai_core/memory/entity_memory.py | 243-309 | No try/except/rollback around `BEGIN IMMEDIATE`+INSERT/UPDATE → open tx pollutes pool | Wrap with rollback |
| cogs/ai_core/memory/entity_memory.py | 348-356 | NULL caller may get cross-channel rows via `OR channel_id IS NULL` | Force `channel_id IS NULL` when caller None |
| cogs/ai_core/memory/long_term_memory.py | 558 | `_parse_ts` no try/except aborts entire `get_user_facts` | Wrap |
| cogs/ai_core/memory/long_term_memory.py | 612 | `.days` truncation; 23h confirmed = 0 days | Optional: total_seconds()/86400 |
| cogs/ai_core/memory/rag.py | 437-460 | UUID mismatch keeps `_initialized=True`, later `.ntotal` crashes | Clear `_initialized` |
| cogs/ai_core/memory/summarizer.py | 113 | No `asyncio.wait_for` timeout on Anthropic call | Wrap in 60s timeout |
| cogs/ai_core/memory/summarizer.py | 162-169 | SDK exception detected by class name | Use `isinstance` |
| cogs/ai_core/memory/rag.py | 1064 | Keyword search +0.3 boost exceeds 1.0 | `min(1.0, ...)` |

### Python — Cache/Commands/Processing/Response/Tools
| File | Line | Issue | Fix |
|------|-----:|-------|-----|
| cogs/ai_core/cache/analytics.py | 199-201 | Replace dict mid-iteration leaves readers with stale ref | Mutate in place |
| cogs/ai_core/cache/analytics.py | 168, 174, 178 | Two-lock split: async vs sync don't coordinate | Unify locks |
| cogs/ai_core/cache/token_tracker.py | 391-396 | Slice-replace list allocation | `del list[:-N]` |
| cogs/ai_core/cache/token_tracker.py | 308-337 | `stop_cleanup_task` catches Exception (should be CancelledError only) | Narrow |
| cogs/ai_core/commands/memory_commands.py | 243 | Iterates `_cache` private without lock | Use accessor |
| cogs/ai_core/commands/server_commands.py | 845, 889, 950 | `cmd_list_channels`/`list_members`/`get_user_info` no perm filter → info leak | Filter by view_channel/manage_guild |
| cogs/ai_core/tools/tool_executor.py | 305, 309 | `cmd_list_channels` called with no `user=` → unfiltered access via tool | Thread user through |
| cogs/ai_core/tools/tool_executor.py | 670 | `channel.webhooks()` fetched every uncached send → API rate | Cache short-period |
| cogs/ai_core/tools/tool_executor.py | 455 | No rate limit on `remember` tool → RAG pollution | Per-user rate limit |
| cogs/ai_core/processing/prompt_manager.py | 326-328 | Reload `_load_templates` writes into `self.templates` non-atomically | Build local then swap |
| cogs/ai_core/processing/prompt_manager.py | 220-256 | `template.format()` with user data → potential format-spec attack | `string.Template` or trust YAML |
| cogs/ai_core/processing/guardrails.py | 527-530 | Thai vowels/tones counted as "special" → false-positive risk_score | Use `unicodedata.category` exclude Mn/Mc |
| cogs/ai_core/response/response_sender.py | 280 | `_detect_open_fence` uses `startswith("```")` not regex | Tighten |

### Python — API/Dashboard
| File | Line | Issue | Fix |
|------|-----:|-------|-----|
| cogs/ai_core/api/api_failover.py | 261 | `get_client()` raises sync from handler chain | Wrap callers in try/except |
| cogs/ai_core/api/dashboard_chat.py | 365 | `gemini_client` not re-checked None mid-stream | Local capture + None check |
| cogs/ai_core/api/dashboard_chat_claude_cli.py | 1051 | Access private `_limit`, suppressed silently | Log warning on AttributeError |
| cogs/ai_core/api/dashboard_chat_claude_cli.py | 1192 | `proc.wait()` unbounded after kill | `wait_for(timeout=10)` + second kill |
| cogs/ai_core/api/dashboard_common.py | 207, 351 | Cache clear/iterate without lock → RuntimeError | Snapshot keys |
| cogs/ai_core/api/dashboard_handlers.py | 66 | `_REGEN_LOCKS` unbounded growth | Cap/evict |
| cogs/ai_core/api/dashboard_handlers.py | 308 | `isprintable` allows zero-width chars | Add ZWS to `_BIDI_MARKS` |
| cogs/ai_core/api/document_extractor.py | 50, 271 | `_defused_etree` access on private `_etree`; monkey-patch global | Test fallback; document |
| cogs/ai_core/api/ws_dashboard.py | 246, 268, 325 | Client init sync; deprecated middlewares; blocking socket | Defer init; future fix |
| cogs/ai_core/api/ws_dashboard.py | 869-871 | `_auth_failures` per-IP never cleaned | Periodic eviction |

### Python — Music / Spotify
| File | Line | Issue | Fix |
|------|-----:|-------|-----|
| cogs/music/cog.py | 174-197 | `_safe_run_coroutine`: bare coroutine leak when loop closed; `BaseException` not caught in `_on_done` | `coro.close()`; catch BaseException |
| cogs/music/cog.py | 472, 478-489 | Bot-moved branch doesn't re-arm auto-disconnect | Re-check humans after move |
| cogs/music/cog.py | 524-597 | `_auto_disconnect` doesn't re-check `mode_247` after sleep | Re-check after sleep |
| cogs/music/cog.py | 600-626 | `safe_delete` Path.resolve raises ValueError uncaught from executor | Wrap try/except |
| cogs/music/cog.py | 742, 1260, 2050 | TOCTOU: `exists()` then ffmpeg spawn; cleanup can delete between | Skip files registered as current_track |
| cogs/music/cog.py | 1115-1116 | `pause` no try/except → corrupts pause_start | Mirror views.py guard |
| cogs/music/cog.py | 1812 | `volume` NaN guard missing in hybrid path | Validate finite |
| cogs/music/cog.py | 1837 | Decorator order: `guild_only` should be outermost | Reorder |
| cogs/music/cog.py | 2210 | `OWNER_ID = CREATOR_ID` captured at class-def → stale on env reload | Read dynamically |
| cogs/music/cog.py | 419-442 | `on_guild_remove` cleanup not in finally → leaks VC on disconnect raise | Move to finally |
| cogs/music/cog.py | 162-164 | Pending-saves bag not flushed before unload finishes | Flush in unload |
| cogs/music/views.py | 25, 78-90, 95-107 | `custom_id` without persist add_view; race on resume/pause; no skip debounce | Either persist or drop `custom_id`; defer-then-act |
| cogs/music/queue.py | 113-121 | `remove_track` indexes deque without lock | Wrap in `_get_lock` |
| cogs/spotify_handler.py | 400-413 | `get_all_playlist_tracks` pagination bypasses `_api_call_with_retry` | Wrap each `self.sp.next()` |
| cogs/spotify_handler.py | 165-194 | `_api_call_with_retry` doesn't bound internal retries (60s timeout) | Set `requests_timeout=10` |

### Python — Utils
| File | Line | Issue | Fix |
|------|-----:|-------|-----|
| utils/database/database.py | 1386 | `get_connection_with_retry` no acquire timeout (sibling has DB_CONNECTION_TIMEOUT) | `asyncio.wait_for(timeout=DB_CONNECTION_TIMEOUT)` |
| utils/database/database.py | 1387 | Increment-before-connect ordering inconsistent | Match sibling pattern |
| utils/database/database.py | 2972 | `assert` SQLi defense stripped with `python -O` | `if/raise ValueError` |
| utils/monitoring/health_api.py | 1005 | `MemoryMonitor.DEFAULT_WARNING_MB` doesn't exist → reports hardcoded 8GiB | Use `memory_monitor.warning_mb` |
| utils/monitoring/audit_log.py | 117-137 | DB write failure doesn't fall through to JSONL fallback | Write to JSONL on DB exception |
| utils/monitoring/metrics.py | 194-205 | `start_http_server(addr=)` fallback binds 0.0.0.0 | Hard-fail or warn |
| utils/reliability/rate_limiter.py | 363-365, 484-486 | `if k not in self._locks` race → two coroutines consume tokens simultaneously | Use `setdefault` |
| utils/reliability/error_recovery.py | 283-291 | `extract_retry_after` doesn't clamp to `config.max_delay` → Retry-After: 999999 freezes | Clamp |
| utils/web/url_fetcher_client.py | 19 | `URL_FETCHER_HOST` no validation | Pin localhost or validate |
| utils/media/ytdl_source.py | 280-296 | Fallback cookies comment vs code mismatch | Fix comment or drop cookies |

### Python — Scripts
| File | Line | Issue | Fix |
|------|-----:|-------|-----|
| scripts/check_balance.py | 97-101 | Bare except masks specific httpx errors | Narrow |
| scripts/bot_manager.py | 593-596 | `force kill` reports success even if proc still running | Check `is_running` after wait |
| scripts/bot_manager.py | 902 | Log paths CWD-relative | Anchor to PROJECT_ROOT |
| scripts/dev_watcher.py | 328 | Bare `except Exception → sys.exit(1)` masks AccessDenied | Add `psutil.AccessDenied` |
| scripts/maintenance/clean_cli_orphans.py | 99-109 | Silent unlink failures, misleading "DELETE dir" message | Track per-entry failures |
| scripts/maintenance/convert_log015.py | 75, 90-92 | Mixed line-ending detection; tempfile in source dir | Detect dominant ending; fallback to system temp |
| scripts/maintenance/find_unused.py | 36-49 | Bare Exception masks UnicodeDecodeError | Narrow |
| scripts/maintenance/migrate_to_db.py | 190 | data_dir/backup_dir CWD-relative | Anchor to PROJECT_ROOT |
| scripts/maintenance/rollback_migration.py | 199 | WAL size > 0 false-positive blocks restore | Use lock test |
| scripts/maintenance/schema_smoke.py | 30-32 | Expected version from glob count (fragile) | Read constant |
| scripts/maintenance/add_local_id.py | 88-89 | Silent rollback failures | Log |

### Rust + Native
| File | Line | Issue | Fix |
|------|-----:|-------|-----|
| native_dashboard/src/main.rs | 314-326 | `explorer.exe` path may not exist if SystemRoot unset and `C:\Windows` fails | `Path::exists()` check before spawn |
| native_dashboard/src/main.rs | 397, 392 | `stack_trace` not newline-stripped → log injection | Apply same strip as message/error_type |
| native_dashboard/src/bot_manager.rs | 224 | `cmdline.contains` misses 8.3 short-name paths | Canonicalize or normalize separators |
| native_dashboard/src/bot_manager.rs | 233 | Lowercase clone per process per scan | Cache or comparing without lowercasing |
| native_dashboard/src/bot_manager.rs | 257-260 | `taskkill` blocks BotManager mutex per orphan | Batch /PID flags or spawn+wait |
| native_dashboard/src/bot_manager.rs | 627, 633 | `thread::sleep(3s+2s)` inside mutex → busy state | Release between sleeps |
| native_dashboard/src/database.rs | 134-156 | Stats queries silently swallow errors | Log on error |
| rust_extensions/media_processor/src/resize.rs | 101-102 | `as u32` clamp to u32::MAX → 4B-pixel allocation | Clamp to MAX_ALLOWED_DIMENSION |
| rust_extensions/media_processor/src/gif.rs | 35-46 | Extension-block parser i+=2 then advances sub-blocks — reviewed safe | None |
| rust_extensions/rag_engine/src/lib.rs | 429-440 | `filter_map` drops NaN silently, then dim-check rejects entry without error | Either fail on first non-finite or document |
| rust_extensions/rag_engine/src/storage.rs | 165-174 | mmap sized to existing_len not file_size_u64 on reopen with smaller capacity | Verified bounded; OK |
| rust_extensions/rag_engine/src/storage.rs | 354-363 | Two fsyncs per push caps throughput | Acceptable per design |
| rust_extensions/rag_engine/src/storage.rs | 426-439 | Drop ignores `mmap.flush()` errors | Acceptable per RAII |

### TypeScript Dashboard
| File | Line | Issue | Fix |
|------|-----:|-------|-----|
| native_dashboard/src-ts/chat-manager.ts | 1346, 1389 | Streaming chunk O(n²) `textContent +=` per WS frame | rAF batching like edit-stream |
| native_dashboard/src-ts/chat-manager.ts | 2576 | `editedMsg.documents` always undefined → regenerate loses docs | Persist documents on send or remove branch |
| native_dashboard/src-ts/chat-manager.ts | 2668 | Blob URL 1s setTimeout revoke leaks on quick close | Use `beforeunload` revoke |
| native_dashboard/src-ts/chat-manager.ts | 2301 | `[data-id="${id}"]` selector — number now, fragile | `CSS.escape(String(id))` |
| native_dashboard/src-ts/chat-manager.ts | 1923-1939 | `newMessagesWhileScrolledUp` never incremented → dead badge | Increment in append paths |
| native_dashboard/src-ts/chat/message-template.ts | 204-216 | `data-msg-id="${msgId}"` interpolated without coercion | `Number(msgId) \|\| ''` or setAttribute |
| native_dashboard/src-ts/chat/message-template.ts | 174 | `data:image/` case-sensitive vs lowered SVG check | Normalize both to lowercase |
| native_dashboard/src-ts/chat/formatter.ts | 76, 91 | Unbounded `[^$]+` regex — ReDoS potential | Cap input length pre-parse |
| native_dashboard/src-ts/chat/ws-client.ts | 233-235 | `event.data.length` not checked for non-string types | Return early for non-string |
| native_dashboard/src-ts/chat/ws-client.ts | 270-277 | `reconnectAttempts` never reset on manual `connect()` | Reset on user-initiated |

## LOW (~150)

LOW-severity findings are real-bug-only (style/naming nits excluded). Aggregated by file:

- **bot.py**: port range validation (559)
- **config.py**: dead TypeError catch (17-26)
- **cogs/ai_core/**: 4-pass re.sub (logic.py:1340), webhook_cache LRU (152), `_explicit_fact_locks` unbounded
- **cogs/ai_core/api/**: dead `current_time_str` (dashboard_chat.py:232), broad `as` casts on JSON
- **cogs/ai_core/memory/**: deepcopy in checkpoint (conversation_branch.py:204), legacy `.npy` migration
- **cogs/music/**: ANSI escape mid-slice, Win32 short-name normalization
- **utils/**: Sentry PII (user_id), URL credentials passthrough
- **TypeScript**: case-declaration leak (chat-manager.ts:700/817), `parseInt` without radix (formatter.ts)
- **Rust**: bench-only unused funcs, comment fragility

---

## Fix Plan

1. **CRITICAL** (1): gate legacy pickle with env flag
2. **HIGH** (40): work through in order, verify line numbers, apply fix
3. **MEDIUM impactful** (~30): security/correctness wins
4. **MEDIUM minor + LOW**: select-only when fix is trivial and unambiguous
5. **Skip**: false positives, defense-in-depth that's already covered, items requiring upstream changes
