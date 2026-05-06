# Master Audit Table — 2026-05-04

ขอบเขต: ทุกไฟล์ source ในโปรเจกต์ (ไม่รวม tests/) — รวม 130 ไฟล์ Python (49,914 บรรทัด) + 13 ไฟล์ Rust + 4 ไฟล์ Go + 25 ไฟล์ TypeScript + Tauri config + scripts ทั้งหมด ≈ 62,000 บรรทัด

ตรวจโดย 13 subagents, อ่านทุกบรรทัดด้วยตา (ไม่พึ่ง linter อย่างเดียว) แล้วบันทึกผลลง `docs/reviews/audit_2026_05/G[1-13]_*.md`

## สรุปยอด (จากรายงานรายกลุ่ม)

| Group | ไฟล์ | บรรทัด | CRIT | HIGH | MED | LOW/INFO |
|---|---|---|---|---|---|---|
| G1 Core entry | 11 | 3,000 | 0 | 0 | 9 | ~140 |
| G2 ai_cog + logic | 2 | 3,019 | 0 | 0 | 17 | ~100+ |
| G3 API + dashboards | 11 | 8,400 | 0 | 8 | 30+ | ~50 |
| G4 cache/commands/core | 12 | 4,700 | 0 | 7 | 11 | ~30 |
| G5 data/processing/etc | 21 | 7,400 | 0 | 5 | 12 | ~80 |
| G6 memory | 11 | 5,160 | 0 | 0 | 10 | ~110 |
| G7 music/spotify | 6 | 3,128 | 1 | 9 | 20+ | ~30 |
| G8 utils db/web/media | 13 | 5,300 | 0 | 5 | 16 | ~30 |
| G9 monitoring | 14 | 5,000 | 0 | 3 | 17 | ~25 |
| G10 reliability | 7 | 3,544 | 1 | 14 | 30 | 25 |
| G11 scripts | 24 | 4,300 | 0 | 5 | 30 | ~30 |
| G12 native dashboard | 25 | 9,500 | 1 | 4 | 17 | ~70 |
| G13 rust + go | 17 | 3,000 | 0 | 4 | 14 | ~20 |
| **รวม** | **174** | **~65,000** | **3** | **64** | **233** | **~720** |

(รวมประมาณ 1,020 issues ทุกระดับความรุนแรง)

## CRITICAL — แก้ทันที

| # | File:Line | Description | Fix |
|---|---|---|---|
| C1 | `utils/reliability/self_healer.py:399-418` | `kill_all_bots(kill_launchers=True)` + `--kill-all` CLI ฆ่า process tree โดยไม่มี confirmation, ใครก็ตามที่ import module ได้เรียก `kill_everything()` ได้เลย | Gate ด้วย `os.environ.get("SELF_HEALER_ALLOW_KILL")=="1"` หรือ `--force`; CLI `--kill-all` ต้อง interactive y/N |
| C2 | `cogs/music/views.py:129` | `on_timeout` ใช้ `hasattr(self, "message")` ซึ่ง True เสมอ (`message=None` ใน `__init__`) แล้ว `await self.message.edit(...)` raises `AttributeError` ที่ไม่อยู่ใน except list | เปลี่ยนเป็น `if self.message:` |
| C3 | `native_dashboard/ui/vendor/dompurify/purify.min.js` | DOMPurify **3.3.3** มี CVE-2026-41238 (prototype-pollution → XSS bypass), CVE-2026-0540 (rawtext element bypass), CVE-2025-26791 (mXSS); เป็น sanitizer ตัวเดียวสำหรับ AI markdown | Upgrade เป็น ≥3.3.4 |

## HIGH — แก้ภายในรอบนี้ (เลือก top items)

| # | File:Line | Description | Fix complexity |
|---|---|---|---|
| H1 | `cogs/ai_core/api/dashboard_chat_claude_cli.py:686-693` | `_make_subprocess_env()` strip แค่ `ANTHROPIC_*` แต่ subprocess inherit `DISCORD_TOKEN`/`OPENAI_API_KEY`/etc. ทั้งหมด รวมกับ `--allowedTools "Read"` = ลีคได้ทุกความลับผ่าน prompt injection ใน PDF | Allowlist env: PATH, HOME, USERPROFILE, APPDATA, LOCALAPPDATA, TEMP/TMP, LANG เท่านั้น |
| H2 | `cogs/ai_core/api/dashboard_chat_claude_cli.py:280` | `_SUPPORTED_DOC_TEXT_EXT` มี `.env` — frontend อัปโหลด .env แล้ว bot อ่านส่งกลับได้ | ลบ `.env` ออกจาก allowlist |
| H3 | `cogs/ai_core/api/dashboard_chat_claude_cli.py:901-1169` | `unrestricted_mode` ทำงานโดยไม่ตรวจ `DASHBOARD_ALLOW_UNRESTRICTED` env (ต่างจาก SDK / Gemini paths) — bypass safety control | เพิ่มการตรวจ env เหมือน path อื่น |
| H4 | `cogs/ai_core/api/dashboard_chat_claude.py:211` + ทุกที่ใน dashboard_handlers.py | `^[a-zA-Z0-9_\-]+$` ไม่จำกัดความยาว, ลูกค้าส่ง multi-MB id ได้ | เพิ่ม `len(conversation_id) <= 128` |
| H5 | `cogs/ai_core/api/ws_dashboard.py:532-558` | Pre-auth WS message อ่านได้ขนาด ~43MB (ใช้ chat path's `max_msg_size`) — pre-auth attacker push 40MB JSON หมด RAM ได้ | ใช้ `max_msg_size=4096` จนกว่าจะ auth |
| H6 | `requirements.txt` (`pypdf>=5.0.0`) | pypdf 5.x มี CVE หลายตัว (28351, 27888, 31826, 27628, 33123, 40260, 24688) DoS ผ่าน PDF | Pin `pypdf>=6.8.0` |
| H7 | `cogs/ai_core/api/document_extractor.py:211-232` | `python-docx` ไม่กัน zip bomb (DOCX = zip-of-XML) | ใช้ zipfile + เช็ค ZipInfo.file_size cap 50MB ก่อนส่งให้ python-docx |
| H8 | `cogs/ai_core/cache/ai_cache.py:794-816` | `flush_l2_pending` ถูก define แต่ไม่เคยถูกเรียกที่ไหน — L2 SQLite write หาย หาก shutdown | เรียกจาก `bot.close()` / `cog_unload()` |
| H9 | `cogs/ai_core/cache/analytics.py:685-686, 547-579` | `_record_response_time` mutate list ไม่มี lock; concurrent access raises `RuntimeError: list changed size during iteration` | wrap ด้วย `_stats_lock` |
| H10 | `cogs/ai_core/cache/analytics.py:86, 533` | `CHARS_PER_TOKEN=4` ผิดสำหรับไทย (ควร ~2.5); analytics ทุกที่ under-report ~30-40% | ใช้ tokenizer จริง หรือ calibrate ตามภาษา; lock `reset_stats` |
| H11 | `cogs/ai_core/cache/token_tracker.py:95-96` | Non-Anthropic, non-Gemini models charged at Gemini-Flash rates (off ~100x) | เพิ่ม explicit gemini check + warning |
| H12 | `cogs/ai_core/tools/tool_executor.py:130-146` | `remember` ใน `_READ_ONLY_TOOLS` แต่เขียน RAG ได้ — user ใดก็ตามใส่ข้อมูลเท็จได้ | ย้าย out of read-only set + scope per-user |
| H13 | `cogs/ai_core/media_processor.py:17-18` | `Image.MAX_IMAGE_PIXELS` ไม่ได้ตั้ง — เปิดภาพ 100MP ผ่าน warning ไม่ block | `Image.MAX_IMAGE_PIXELS = 30_000_000` + simplefilter('error', DecompressionBombWarning) |
| H14 | `cogs/ai_core/processing/guardrails.py:264-279` | `_check_repetition` gate `> 10` words — response 5 คำซ้ำกันไม่ flagged | เปลี่ยนเป็น `>= MAX_SINGLE_WORD_REPEAT` |
| H15 | `cogs/ai_core/storage.py:438-440` | `_save_history_db` swallow `aiosqlite.Error` แล้ว return success — silent data loss | re-raise หรือ return False ที่ caller เช็ค |
| H16 | `cogs/ai_core/storage.py:619-625, 627-633` | `load_metadata` cache hit returns shallow copy, miss returns ref ตรง — caller mutate metadata = corrupt cache | ใช้ `copy.deepcopy` ทั้งสอง path |
| H17 | `cogs/ai_core/data/constants.py:87-88` ↔ `response_sender.py:19-25` | `data/constants.py` ตั้ง `DISCORD_MESSAGE_LIMIT` แต่ `response_sender.py` import `MAX_DISCORD_LENGTH` ที่ไม่มีอยู่ → fallback hardcoded ตลอด | rename หรือ alias ทั้งสองชื่อ |
| H18 | `cogs/ai_core/data/roleplay_data_example.py:116, 118-122` | Comment บอก `display_name` แต่จริง schema ต้องเป็น `image_path` (ตรง real `roleplay_data.py:286` + `media_processor.load_character_image:321`) | แก้ comment + value เป็น path |
| H19 | `cogs/music/cog.py:1181` | `!play` ขาด `@commands.guild_only()` — DM crashes ที่ line 1206 | เพิ่ม decorator |
| H20 | `cogs/music/cog.py:587-621` | `asyncio.shield(_acquire_task)` lock leak บน cancel — guild lock deadlock ถาวร | restructure: cancel inner task ด้วย; release ใน finally |
| H21 | `cogs/music/cog.py:730` | yt-dlp blocking ใน play_lock 30s+ — `!play` ซ้อนๆ bounce | release lock ระหว่าง download, lock เฉพาะ `voice_client.play(...)` |
| H22 | `cogs/music/cog.py:138 + 244-263` | `_periodic_queue_save` ไม่อ่าน `_queue_save_pending` set, save ทุก guild ทุก 5 นาที | save เฉพาะ guild ใน pending set |
| H23 | `cogs/music/cog.py:302-351` | `load_queue` ลบ JSON ก่อนเขียน DB — ถ้า DB load คืน empty (อยู่ใน JSON เท่านั้น) ข้อมูลหาย | ใช้ pattern `queue.py:284-296` (verify-then-delete) |
| H24 | `cogs/music/cog.py` (5 จุด) | FFmpeg subprocess leaks เมื่อ exception ระหว่าง constructor + `voice_client.play` | call `player.cleanup()` ใน except ทุกที่ |
| H25 | `utils/web/url_fetcher.py:136-148` | SSRF — `::ffff:127.0.0.1` (IPv4-mapped IPv6) bypass blocklist | เพิ่ม `::ffff:0:0/96` หรือเช็ค `ip.ipv4_mapped` |
| H26 | `utils/web/url_fetcher.py:113, 218, 354-358` | scheme allowlist ไม่ enforce ที่ redirect target — `gopher://`, `dict://`, `ldap://` slip past | re-validate scheme ทุก redirect |
| H27 | `utils/web/url_fetcher_client.py:105-130` | SSRF check skip เมื่อ url_fetcher import fail — ส่งผ่าน Go service raw | hard-fail import |
| H28 | `utils/media/ytdl_source.py:209-302` | `data["url"]` post-extract ไม่ re-validate path-traversal เมื่อ stream=False | check resolved filename อยู่ใน temp/ |
| H29 | `utils/fast_json.py:45-50` | orjson branch drop `default=`, `sort_keys=` — caller ที่ใช้ `default=str` จะ TypeError บน datetime/UUID | translate kwargs หรือ raise NotImplementedError ชัดเจน |
| H30 | `utils/monitoring/audit_log.py:12-18, 49-65, 89, 96-127` | DB ไม่มี ⇒ log_action returns True เฉยๆ — audit history หายเงียบ | เขียน `logs/audit_fallback.jsonl` |
| H31 | `utils/monitoring/audit_log.py:27-95` | audit_log ไม่มี append-only / hash chain / signed entries — แก้ไขได้ทันที | trigger BEFORE UPDATE/DELETE หรือ prev_hash chain |
| H32 | `utils/monitoring/sentry_integration.py:80-83` | `attach_stacktrace=True` + locals → ลีค API key ใน frame variables | before_send hook scrub stack vars |
| H33 | `utils/monitoring/token_tracker.py` ⊕ `cogs/ai_core/cache/token_tracker.py` | TokenTracker คนละตัว ใช้ทั้งคู่ — record ซ้ำ + drift | เลือก cache version (มี DB + cost), ลบ monitoring version |
| H34 | `utils/reliability/circuit_breaker.py:156-158` | HALF_OPEN→CLOSED บน success ตัวแรก ไม่นับ probes ที่ flying | track `_half_open_successes >= half_open_max_calls` |
| H35 | `utils/reliability/rate_limiter.py:308-317` | ถ้าทุก bucket locked → fall back เป็น shared `__overflow__` bucket = DoS amplifier | deny + retry_after high แทน |
| H36 | `utils/reliability/error_recovery.py:358-369` | `retry_async` honor แค่ `gemini_circuit` hard-coded — service อื่นไม่ได้ | lookup จาก registry |
| H37 | `utils/reliability/memory_manager.py:629-633` | warning_mb=8192, critical_mb=16384 — ใหญ่กว่า bot ทั่วไป 10-100x, OOM killer มาก่อน | ลด default หรืออ่านจาก env |
| H38 | `utils/reliability/shutdown_manager.py:306-322` | handlers run sequential within phase — 10 handlers x 5s = 50s เกิน 30s budget | parallel ด้วย `asyncio.gather` หรือ doc serial |
| H39 | `utils/reliability/shutdown_manager.py:343-373, 461-472` | signal handler doesn't block until shutdown done; SIGINT คู่ → `sys.exit(1)` unsafe | use `os._exit(1)` หรือ flag + event loop poll |
| H40 | `scripts/bot_manager.py:581-587` | `auto_stop_existing_bot()` ฆ่า production bot โดยไม่ถามทุก start | y/n prompt unless `--force` |
| H41 | `scripts/bot_manager.py:642-664` | `STOP_FLAG` CWD-dependent + ไม่ถูกลบ — stale flag block start ครั้งหน้า | absolute path + cleanup on success |
| H42 | `scripts/dev_watcher.py:493-508` | Bot child + `CREATE_NEW_PROCESS_GROUP` ไม่มี Job Object — orphan บน Windows ถ้า watcher ตาย | `AssignProcessToJobObject` + `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` |
| H43 | `scripts/maintenance/add_local_id.py:29-65` | Migration ไม่ wrap ใน BEGIN/COMMIT — partial fail ทิ้ง DB ครึ่งๆ | `BEGIN IMMEDIATE` |
| H44 | `scripts/maintenance/migrate_to_db.py:266-287` | `--delete-json` ลบ source ไม่มี extra confirm; `--backup` optional | require `--backup` หรือ `--yes-delete-json` |
| H45 | `scripts/maintenance/reindex_db.py:161` | `RENAME TO ai_history` ทิ้ง FOREIGN KEYs ที่ table อื่นมีถึง ai_history.id | doc loud + check FK preservation |
| H46 | `scripts/verify_system.py:35-81` | `check_imports()` import จริง — fire side effects (DB, listeners, signals) | drop import phase, ใช้ `compile()` อย่างเดียว |
| H47 | `native_dashboard/tauri.conf.json` (capabilities/default.json) | `core:default` กว้างไป — IPC surface ใหญ่; `connect-src ws://localhost:*` ทุก port | tighten ให้เฉพาะที่ใช้จริง |
| H48 | `rust_extensions/rag_engine/src/lib.rs:283-329` | `save()` ไม่ `f.sync_all()` ก่อน rename — power loss = file empty | เพิ่ม `f.sync_all()` ก่อน drop |
| H49 | `go_services/health_api/main.go:254-260, 290` | bind 0.0.0.0 ผ่าน `GO_HEALTH_API_HOST` ไม่มี auth — `/metrics/push` write surface เปิด | bearer token middleware หรือลบ env |
| H50 | `cogs/ai_core/api/ws_dashboard.py:387-488` | ไม่มี per-IP failed-auth backoff — attacker ตี `/ws` ด้วย bad token ไม่จำกัด | rate-limit ก่อน auth |

## MEDIUM (highlights — ดูรายละเอียดในไฟล์รายกลุ่ม)

233 รายการ — ครอบคลุม: race conditions, blocking I/O ใน async, prompt injection ใน RAG/entity strings, datetime tz inconsistency, magic numbers, unbounded growth ใน caches/sessions, missing per-shard differences, etc.

## ขั้นต่อไป

ผม fix ตามลำดับความรุนแรง:
1. CRITICAL ทั้ง 3 ตัว (self_healer gating, on_timeout, DOMPurify upgrade)
2. HIGH ที่ผม fix ได้ทันที (~30 ตัว) — ส่วนที่ต้อง upgrade dependency หรือออกแบบใหม่จะแยก ticket
3. รัน `python -m pytest tests/` ยืนยัน
