# Master Audit Table — 2026-05-24

ขอบเขต: **ทั้ง repo (ไม่รวม tests/ + generated)** — 281 ไฟล์ source, ~96,000 บรรทัด, อ่านครบทุกบรรทัดด้วย 20 subagents (ต่อยอดจาก audit 2026-05-04).
ภาษา: Python (ai_core, utils, scripts), Rust (rust_extensions + Tauri backend), Go (url_fetcher, health_api), TypeScript/HTML/CSS (Tauri dashboard), SQL migrations, PowerShell/batch, docs.

รายงานรายกลุ่มเต็ม: `docs/reviews/audit_2026_05_24/G{1..20}_*.md`

## สรุปยอดต่อกลุ่ม

| Group | ไฟล์ | CRIT | HIGH | MED | LOW | INFO |
|---|---|---|---|---|---|---|
| G1 core entry + config | bot/config/imports/requirements/CI | 0 | 3 | 7 | 19 | 12 |
| G2 ai_cog + logic | ai_cog.py, logic.py | 0 | 2 | 11 | 30 | 9 |
| G3 Claude/CLI chat paths | dashboard_chat_claude*/chat/payloads | 0 | 3 | 13 | 12 | 6 |
| G4 API/WS handlers | handlers/ws/api/failover/document_extractor | 0 | 2 | 11 | 14 | 6 |
| G5 cache/core/response/session | cache/core/response/session_mixin | 0 | 3 | 11 | 18 | 7 |
| G6 memory | rag/long_term/entity/consolidators/branch/etc | 0 | 2-3 | 9 | 24 | 11 |
| G7 processing/tools/data/commands | guardrails/tools/data/commands | 0 | 3 | 9 | 22 | 7 |
| G8 music/spotify/media/voice | music/*, spotify, media_processor, voice | 1 | 4 | 12 | 17 | 4 |
| G9 utils database | database.py, migrations.py | 0 | 2 | 9 | 16 | 7 |
| G10 utils web/media/misc | url_fetcher*, ytdl, fast_json, localization | 0 | 0 | 6 | 11 | 9 |
| G11 monitoring | health_api/sentry/audit/loggers/tokens | 0 | 2 | 9 | 31 | 6 |
| G12 reliability | rate_limiter/self_healer/shutdown/circuit | 0 | 3 | 11 | 16 | 7 |
| G13 scripts (python) | bot_manager/dev_watcher/maintenance | 0 | 0 | 7 | 18 | 13 |
| G14 SQL + shell | migrations *.sql, *.ps1/*.bat | 0 | 2 | 7 | 12 | 11 |
| G15 dashboard TS core | app/chat-manager/shared.ts | 1* | 2 | 9 | 17 | 6 |
| G16 dashboard TS chat | formatter/message-template/ws-client/etc | 1* | 2 | 9 | 13 | 7 |
| G17 dashboard Rust + config | main/bot_manager/database.rs, tauri.conf | 0 | 0 | 7 | 18 | 11 |
| G18 frontend assets + vendor | index.html, styles.css, vendor/* | 1* | 2 | 3 | 7 | 6 |
| G19 rust + go extensions | media_processor, rag_engine, go services | 0 | 0 | 6 | 17 | 12 |
| G20 docs | README, docs/*.md, schema docs | 0 | 0 | 1 | 22 | 11 |
| **รวม (ดิบ)** | **281** | **2 unique** | **~32 unique** | **~167** | **~354** | **~168** |

*C2 (DOMPurify) ถูกพบโดย G15/G16/G18 = issue เดียวกัน นับ unique 1 ตัว → **CRITICAL unique = 2**

## CRITICAL — แก้ทันที (2 unique)

| # | File:Line | ปัญหา | Prior | Fix |
|---|---|---|---|---|
| **C1** | `cogs/music/cog.py:793,817,829-837` | `play_lock` รั่วถาวรเมื่อ outer task โดน cancel (ไม่ใช่ timeout): `wait_for(shield(_acquire_task))` — done-callback ปล่อย lock เฉพาะ branch `_timed_out_flag` (TimeoutError) เท่านั้น; CancelledError → shielded task ได้ lock แต่ไม่มีใครปล่อย → **per-guild deadlock ถาวร** | H20 มาร์ค "fixed" แต่ branch cancel ไม่เคยถูกเพิ่ม → STILL-PRESENT, re-escalate | เพิ่ม `except asyncio.CancelledError: _acquire_task.cancel(); await…; raise` หรือใช้ `async with asyncio.timeout(): async with lock:` |
| **C2** | `native_dashboard/ui/vendor/dompurify/purify.min.js` (โหลดที่ `index.html:29-30`) | DOMPurify ที่ webview โหลดจริง **ยังเป็น 3.3.3** (CVE-2026-41238 prototype-pollution→XSS, CVE-2026-0540, CVE-2025-26791) เป็น sanitizer ตัวเดียวของ AI/markdown ที่ลง innerHTML; `package.json` bump เป็น ^3.4.2 แต่ vendored bundle ไม่ถูก rebuild + SRI ยัง pin 3.3.3 | C3 มาร์ค "fixed" แต่ของจริงไม่ถูกแก้ (fix version ที่เขียนไว้ "≥3.3.4" ผิด — ต้อง **≥3.4.0**) → STILL-PRESENT | re-vendor purify.min.js เป็น ≥3.4.2, regenerate SRI ที่ index.html:30, + ตั้ง `CUSTOM_ELEMENT_HANDLING` ชัดเจน |

## HIGH — แก้ในรอบนี้ (~32 unique)

### Security / data-exfil
| # | File:Line | ปัญหา | Fix |
|---|---|---|---|
| H1 | `dashboard_chat_claude_cli.py:960-961,1541-1550` | `Read` tool เปิดให้ทุก attachment โดยไม่ scope path; prompt ส่ง absolute path ให้ Claude อ่าน → PDF/doc ที่ถูก prompt-inject อ่าน `~/.claude/.credentials.json`/`.env`/`*.db` แล้ว stream กลับได้ | `--add-dir <temp_root>` confinement + deny-outside permission mode หรือ inline doc text แบบ SDK path |
| H2 | `dashboard_chat_claude_cli.py:456-495,948` | `_track_session` เก็บ session_id เช็คแค่ truthiness แล้วส่งเป็น `--resume <id>` ไม่มี `--` end-of-options → id ขึ้นต้น `-` ถูก parse เป็น flag (argv injection) | validate ด้วย `_SESSION_ID_PATTERN` ตอน store + ใส่ `--` |
| H3 | `dashboard_chat_claude_cli.py:258-292` | `delete_session_file` pop+persist conversation entry **ก่อน** เช็ค `_SESSION_ID_PATTERN` → id ปลอมทำข้อมูลหายก่อน validate; ไม่มี `resolve().is_relative_to` containment | validate ก่อน pop + containment check |
| H4 | `self_healer.py:606-647` | `ensure_single_instance(kill_existing=True)` (path startup จริงของ bot.py) ฆ่า bot+watcher อื่น **โดยข้าม** `_kill_authorized` gate; ไม่มี lockfile → 2 start พร้อมกันฆ่ากันเอง | route ผ่าน `_kill_authorized` หรือ OS exclusive lockfile ก่อนตัดสินใจ kill |
| H5 | `shared.ts:38-64` + `tauri.conf.json:9` | `withGlobalTauri:true` → `window.__TAURI__.core.invoke` เรียกได้จากทุก script context; XSS ใดๆ (เปิดทางโดย C2) เรียก `start_bot`/`clear_history`/`delete_channels_history` ได้ | ปิด `withGlobalTauri`, ใช้ import-map; pin vendor ด้วย SRI |
| H6 | `tauri.conf.json` + `index.html:12` connect-src | `connect-src ws://127.0.0.1:*` ทุก port → rogue loopback listener ปลอมเป็น backend รับ `DASHBOARD_WS_TOKEN` ที่ส่งใน onopen | pin `ws://127.0.0.1:8765` |
| H7 ✅ DONE (รอบ 12) | `index.html:12` | CSP regressed: `style-src 'self' 'unsafe-inline'` (รอบก่อนเป็น `'self'`) → เปิด CSS-injection | **แก้แล้ว**: ตัด `'unsafe-inline'` → `style-src 'self'`. thinking/edit inline→class, image-popup+sakura=CSSOM (exempt), KaTeX→MathML. e2e 72/1 + guard `h7-csp.spec.ts` (style-src violation=0) — ดู FIX_LOG รอบ 12 |
| H8 | `formatter.ts:266-277` | whitelisted `'style'` attr บน sanitized chat body; DOMPurify CSS sanitizer เคยมี bypass + ประกอบกับ C2 ขยาย surface | ตัด `'style'`, ใช้ fixed CSS class |
| H9 | `shared.ts:263-270` (avatar) | `isSafeAvatarUrl` ยอม `http://` + ทุก host → server push ตั้ง avatar = `http://attacker/pixel` = beacon IP+UA | ตัด `http://`, จำกัด host allowlist / `data:image/` |
| H10 | `install_all.ps1:35-61 + call sites` | download-and-run ทุก installer (Git/Python/FFmpeg/rustup/Go/Node/Docker) **ไม่มี SHA-256** (ExpectedHash ว่าง = warn เฉยๆ) → CDN/DNS โดน = admin RCE | pin SHA-256 สำหรับ URL ที่ version-locked |
| H11 | `audit_log.py:76-149` + `database.py:594-603` | audit log ไม่มี tamper resistance (ไม่มี trigger/prev_hash chain, created_at = local time); JSONL fallback append เฉยๆ → แก้/ลบได้ไม่ทิ้งร่องรอย | immutability trigger + HMAC prev_hash chain (DB+JSONL); created_at เป็น UTC |

### Dependencies / supply chain
| # | File:Line | ปัญหา | Fix |
|---|---|---|---|
| H12 | `requirements.txt:24` | `pypdf>=5.0.0` เปิดช่วง 5.x และ 6.x<6.9.2 ที่มี CVE (CVE-2026-33699 infinite-loop DoS CVSS 8.2, +27628/24688/28351) บน PDF จากผู้ใช้; installed 6.10.2 ปลอดภัยแต่ spec ไม่; `pip-audit` ใน CI audit เฉพาะ installed → ปกปิด | pin `pypdf>=6.10.2` (G1+G4) |
| H13 | `requirements.txt` (absent) | `defusedxml` เป็น XXE defense **ตัวเดียว** ของ DOCX (document_extractor.py:46-60 ปิด DOCX ถ้า import fail) แต่ไม่ถูกประกาศ (มีแค่ transitively) | เพิ่ม `defusedxml>=0.7.1` (G1+G4) |
| H14 | `requirements.txt:17` | `anthropic>=0.99.0,<1.0` ไม่ตรง installed 0.98.1 (env unsatisfied) + ตามหลัง 0.104.1 | reconcile pin/env แล้ว re-test SDK paths |

### Correctness / data-loss / lifecycle
| # | File:Line | ปัญหา | Fix |
|---|---|---|---|
| H15 | `database.py:1541-1546` (+col default :393) | `save_ai_message` เขียน `datetime.now(tz).isoformat()` (T+offset) ลงคอลัมน์ที่ DEFAULT = `CURRENT_TIMESTAMP` (space, no offset) → sort lexically ไม่ตรง → ORDER BY บน timestamp index + partial index ของ consolidator เพี้ยน | normalize ทุก writer เป็น SQLite text หรือ insert ผ่าน CURRENT_TIMESTAMP |
| H16 | `database.py:1553-1608` | `save_ai_messages_batch` ทิ้ง msg ที่ channel_id falsy เงียบๆ แต่ return `len(messages)` (data loss เงียบ); `msg.get("timestamp")` ขาด key → NULL; ขาด content → executemany ล้มทั้ง batch | reject/raise บน falsy channel_id + missing content/role, default timestamp, return count จริง |
| H17 | `cogs/music/cog.py` (DB `database.py:1888-1923`) | field `type` หายตอน save/load queue; Spotify track เก็บ url เป็น search string → หลัง restart `type` หาย → ส่ง bare string เข้า `from_url` → DownloadError → **ทุก Spotify track ใน persisted queue พังหลัง restart** | เพิ่มคอลัมน์ `track_type` + migration หรือ resolve เป็น webpage_url ตอน enqueue |
| H18 | `cogs/music/cog.py:354-373` | `Music.save_queue` ไม่มี per-guild lock (QueueManager ตัวที่มี lock ไม่ถูกใช้) → concurrent popleft/append ระหว่าง `list(queue)` เขียน queue ขาด/เพี้ยนลง DB | guard ด้วย per-guild lock หรือ route ผ่าน QueueManager |
| H19 | `cogs/ai_core/voice.py:174,181` | `get_voice_status` อ่าน `music_cog.current_track` ที่ถูก refactor ไปเป็น `gs.current_track` แล้ว → AttributeError เมื่อกำลังเล่น/หยุด (REGRESSED) | ใช้ `music_cog._gs(guild_id).current_track` ผ่าน getattr guard |
| H20 | `cogs/music/cog.py:740-765,1064` | `play_retries` ถูก mutate นอก play_lock โดยทั้ง wrapper และ `_play_next_once` → concurrent calls interleave นับ → cap 10-retry พัง | ย้ายนับเข้า lock หรือใช้ local counter |
| H21 | `logic.py:1276-1311` | บน cancellation กลางสตรีม ข้อความ partial (`model_text`) ถูก save ลง history → poison เทิร์นถัดไปด้วยคำตอบที่โมเดลยังไม่จบ | อย่า persist model turn เมื่อ `was_cancelled` (save แค่ user msg) หรือ tag `partial` แล้ว exclude |
| H22 | `logic.py:270` ↔ `core/message_queue.py:41` | มี `processing_locks` 2 dict: ChatManager ใช้ตัวของมันจริง แต่ MessageQueue lock API ไม่เคยถูกเรียก → MAX_CHANNELS eviction "skip locked channel" ส่อง dict ผิด → evict channel ที่กำลัง serialize อยู่ | ให้ ChatManager ใช้ MessageQueue lock API เป็น source of truth หรือลบ dict/API ที่ไม่ใช้ |
| H23 | `guardrails.py:583-621` | input guardrails (`validate_input_for_channel` — Thai+EN injection detection, jailbreak score, secret redaction) **ไม่มี caller ใน production** → input ผู้ใช้ถึงโมเดลดิบ | wire `validate_input_for_channel` เข้า inbound path ก่อน text เข้า prompt |
| H24 | `tool_executor.py:109` | `args = tool_call.args` ไม่มี `or {}` → tool call ที่ args=None ทำทุก `args.get()` raise AttributeError | `args = getattr(tool_call,"args",None) or {}` |
| H25 | `memory_consolidator.py:108-133,538-567` | ตาราง `conversation_summaries` ถูกสร้างใน `SummaryArchiver.init_schema()` ที่ไม่เคยถูกเรียกตอน startup → `!consolidate` INSERT เจอ "no such table" | เรียก `summary_archiver.init_schema()` จาก `init_database()` หรือเพิ่มตารางใน `Database.init_schema()` |
| H26 | `memory_consolidator.py:135-141` | `SummaryArchiver.start_background_task()` (loop archive/trim ai_history ทุก 6 ชม.) ไม่เคยถูกเรียก → ai_history โตไม่จำกัด | start ใน `cog_load`, stop ใน `cog_unload` หลัง schema init |
| H27 | `cache/token_tracker.py:212-221,377-414` + `utils/monitoring/token_tracker.py` | TokenTracker ทั้ง 2 ตัว inert: `record_usage`/`record_token_usage`/`start_cleanup_task` ไม่ถูกเรียกจาก live path → analytics/quota ว่างเปล่า + misleading (H33 dead-wiring) | เลือก 1 ตัวเป็น authoritative, wire จริง (start/stop + record จาก response path), ลบอีกตัว |
| H28 | `cache/ai_cache.py:771-778,797` | `L2SqliteCache.close()` มีแต่ไม่เคยถูกเรียก; flush wired แล้ว (H8 fixed) แต่ connection+WAL ปล่อยถึง process exit; synchronous=NORMAL + hard crash = commit สุดท้ายหาย | เรียก `_l2_cache.close()` ใน cog_unload หลัง flush + `wal_checkpoint(TRUNCATE)` |
| H29 | `cache/analytics.py:178-184` | `threading.Lock` ถูกถือใน async path; sync readers (get_summary/percentiles) บน thread อื่นถือ lock เดียวกัน → event-loop thread block จริง (sort 1000 floats + confusion matrix ใต้ lock) | snapshot-then-release ก่อนทำงานหนัก |
| H30 | `self_healer.py:365-395,638` | `kill_duplicate_bots(keep_newest=False)` (default ของ auto_heal) เก็บตัว**เก่า** ฆ่าตัว**ใหม่** → git pull+restart ฆ่า process ใหม่ที่ถูกต้อง; `clean_pid_file()` ไม่ force → ปฏิเสธพลาดหลัง kill | default `keep_newest=True` สำหรับ restart หรือระบุ policy ต่อ call site |
| H31 | `shutdown_manager.py:235-256,419-477` | sync cleanup handlers รันผ่าน `run_in_executor`+`wait_for`; timeout cancel future แต่ thread ยังรันต่อ mutate state เข้า phase ถัดไป (executor futures cancel ไม่ได้); `_atexit_handler` เหมือนกัน | cooperatively-cancellable handlers หรือ terminable process pool; ไม่งั้น doc ว่า sync handler ต้องเร็ว+idempotent |
| H32 | `start.ps1:64` | production launcher บนพาธมีช่องว่าง: `Start-Process -FilePath "python" -ArgumentList $BotScript` ส่ง `C:\BOT Discord\bot.py` ไม่ quote → Python เห็น `C:\BOT` → บอตไม่สตาร์ท | quote arg หรือ `& python $BotScript` |
| H33 | `index.html:36-38` | `<script src="vendor/prism/prism-core.min.js" integrity=…>` ชี้ไฟล์ที่**ไม่มีอยู่** (vendor/prism/ มีแต่ CSS) → code highlighting ตาย + SRI การ์ดไฟล์ที่หายไป | vendor Prism JS จริง + regen SRI หรือลบ script tag ที่ตาย |

> หมายเหตุ: `rag.py` RAG-injection (channel-scoped cross-user) ถูกจัดเป็น HIGH ใน G6 แต่ปัจจุบัน **bounded** (ตัวเขียน production เดียว scrub ตอน write) → จัดเป็น defense-in-depth, อยู่กลุ่ม "fix ถ้าเหลือเวลา"; `tool_definitions.py` dead-code จัด HIGH เชิง misleading แต่จริงๆ ใกล้ INFO

## MEDIUM (~167) — สรุปธีม (รายละเอียดในไฟล์รายกลุ่ม)
- **Concurrency/async**: blocking I/O บน event loop (analytics sync readers, inline history compression 60s, gc.collect, sqlite copy), races (cache invalidation, rate_limiter bucket eviction, inflight counter TOCTOU), live-list snapshots ระหว่าง trim/consolidation
- **Resource/durability**: missing fsync (FAISS save), no PRAGMA busy_timeout, export_to_json unbounded fetchall (OOM), pre-auth WS frame buffered ~43MB ก่อน 4KiB check (H5 partial), per-call ClientSession ไม่ pool
- **Security defense-in-depth**: SSRF blocklist gaps (NAT64/CGN/multicast), body-size cap bypass (.json()/.text()), Gemini safety thresholds OFF unconditionally, ALERT_WEBHOOK_URL ไม่มี host allowlist, health_api /metrics+/stats นอก auth group, CORS origin echo, weak control-char normalize
- **Data integrity**: KNOWN_TABLES ขาด 2 ตาราง (JSON backup ตกหล่น), datetime/tz mixing, migration hardcoded column lists (forward-compat drift), token cost over/under-report
- **Lifecycle/dead-wiring**: self_reflection (443 LoC) / conversation_branch / tool_definitions / VectorStorage(unsafe mmap) / VectorIndex ไม่ถูกเรียกใน production
- **Process mgmt**: dev_watcher no Job Object (H42 orphan), bot_manager wscript PATH hijack, start() success-before-liveness, migrate_to_db no ON CONFLICT (dup rows) + copytree fills disk

## LOW (~354) / INFO (~168) — สรุปธีม
LOW: naming/comment drift, dead methods, substring keyword/char-tag matching, magic numbers, time.time() vs monotonic, FIFO-not-LRU caches, broad `except Exception`, doc-vs-code accuracy (env var/port/schema/model/links), CSS cosmetics, type:ignore suppressions, GIL not released on single Rust ops.
INFO: ยืนยัน fix รอบก่อน (เยอะ), positive hardening, deps current.

## Prior-audit (2026-05-04) reconciliation — ภาพรวม
- **FIXED-VERIFIED จำนวนมาก**: C1 self_healer gating (แต่มีรูที่ ensure_single_instance → H4), C2 on_timeout, H1-H5/H7/H50 (api/ws security), H8 flush_l2_pending, H9 analytics iteration lock, H13 MAX_IMAGE_PIXELS, H14 repetition gate, H17 MAX_DISCORD_LENGTH, H18 roleplay image_path, H19/H22/H23/H24 music, H25-H29 SSRF/ytdl/fast_json, H30 audit fallback, H32 sentry scrub, H34-H38 reliability, H40/H41/H43-H46 scripts, H47 capabilities, H48 rag fsync, H49 go auth, Phase 13 db indexes — ของจริงแก้แล้ว
- **STILL-PRESENT/REGRESSED ที่สำคัญ**: **C3 DOMPurify (ไม่แก้จริง → C2)**, H20 music lock (→ C1), H6 pypdf (→ H12), H31 audit tamper (→ H11), H33 token tracker (→ H27), voice.current_track (→ H19), H42 dev_watcher Job Object
- **PARTIALLY-FIXED**: H5 (pre-auth frame ยัง buffer), H10 (CHARS_PER_TOKEN), H12 (remember tool), H39 (double-SIGINT)

## แผนแก้ (disposition)
1. **CRITICAL (2)** — แก้ทันที, verify เองกับโค้ดจริงก่อนแก้
2. **HIGH (~32)** — แก้ทั้งหมดที่ปลอดภัย+scope ชัด (security, dependency pins, correctness/data-loss, lifecycle-wiring); ตัวที่เป็น redesign ใหญ่ (audit hash-chain H11, token tracker unify H27) ทำเวอร์ชัน minimal + flag
3. **MEDIUM** — แก้ที่ verify แล้วว่าจริง+ปลอดภัย
4. **LOW/INFO** — แก้ที่ง่าย/ปลอดภัย (เช่น docs accuracy, dead code), ส่วน subjective/by-design บันทึกไว้
5. รัน `make test` (3007) + `make test-go` + `make test-rust` + `make lint*` + native_dashboard vitest ยืนยัน
