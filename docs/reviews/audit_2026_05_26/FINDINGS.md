# Full-repo audit — 2026-05-26 (round 14)

วิธีตรวจ: อ่านทุกบรรทัดของ **source ทั้งหมด (ไม่รวม tests)** ด้วย 15 line-by-line subagents
ครอบคลุม Python / TypeScript / Rust / Go / SQL / PowerShell-batch / Docker / CI / configs / docs
แล้ว **verify ทุก CRIT/HIGH/MED กับโค้ดจริงเอง** ก่อนแก้ (subagent overstate เยอะ — ดู
[[feedback_read_source_carefully]]). Baseline ก่อนแตะ: Python **3367 pass / 2 skip**, ruff clean.

## สรุป
โค้ดสะอาดมาก (ผ่าน audit รอบ 1–13 มาแล้ว). จาก ~50 ข้อที่ subagent รายงาน — **เกือบทั้งหมด
false-positive หรือ by-design**. ของจริงที่แก้ = **2 code + 6 docs**, + 1 deprecation defer (มีเหตุผล).

## DONE — แก้ + verify

| ไฟล์ | บรรทัด | ระดับ | รายละเอียด | ยืนยัน |
|---|---|---|---|---|
| `utils/monitoring/sentry_integration.py` | 263–278 | LOW (sec) | `capture_message` ไม่ redact `context` extras ขณะที่ `capture_exception` redact → secret ใน context รั่วไป Sentry. เพิ่ม `_redact_sensitive` ให้เท่ากัน | ✅ +regression test (21 pass) |
| `native_dashboard/src/bot_manager.rs` | 16–34 | LOW/MED (def) | `taskkill_path()` ใช้ `%SystemRoot%` ดิบ ทั้งที่ `main.rs:open_folder` validate แล้ว → `SystemRoot=C:\Attacker` spawn `taskkill.exe` ปลอมได้. mirror การ canonicalize+compare ของ main.rs | ✅ cargo check exit 0 |
| `docs/CODE_AUDIT_GUIDE.md` | 295 | LOW (doc) | "GEMINI_API_KEY Required" ผิด → optional; ANTHROPIC เฉพาะ `CLAUDE_BACKEND=api` (config.py:124–146) | ✅ |
| `docs/TROUBLESHOOTING.md` | 23–28, 186–192 | LOW (doc) | `ANTHROPIC_API_KEY` ใน "Required" — จริง ๆ optional, `cli` (default) ไม่ต้องใช้ | ✅ |
| `docs/DEVELOPER_GUIDE.md` | 445 | LOW (doc) | `LOCK_TIMEOUT` 30s → **180s** (constants.py:54, ต้อง > API_TIMEOUT 120s) | ✅ |
| `docs/DEVELOPER_GUIDE.md` | 852 | LOW (doc) | "Max 1000 channels" → **2000** (storage.py:115; ขัดกับบรรทัด 452 ของไฟล์เดียวกัน) | ✅ |
| `docs/SCHEMA.md` | 362 | LOW (doc) | migration table ขาดแถว `015_ai_history_summarized_at` | ✅ |

## VERIFIED NON-ISSUE (subagent overstate — อ่านโค้ดจริงแล้วไม่ใช่บั๊ก)

| ไฟล์:บรรทัด | claim | ความจริง |
|---|---|---|
| `health_api.py:799` | HIGH `/ai/stats/json` ไม่ auth | **อยู่ใน `_PROTECTED_ENDPOINTS` (172)** + เช็คที่ 691 — protected. (agent ขัดแย้งตัวเอง) |
| `database.py:373` | HIGH `busy_timeout` ไม่ตั้ง | `aiosqlite.connect(timeout=DB_CONNECTION_TIMEOUT)` (1161,1457) = `sqlite3_busy_timeout` แล้ว |
| `__init__.py (db):7` | MED `KNOWN_TABLES` ขาด entity_memories/user_facts | **มีอยู่จริง (26–27)** — hallucinated |
| `ws_dashboard.py:631` | HIGH origin/token ordering bypass | origin+host check รันแยก **หลัง** token (631) ทั้งคู่ต้องผ่าน; empty-origin+localhost-host = intended (Tauri/curl) + token ยัง required |
| `music/cog.py:2202` | HIGH `seek` `fixing=True` no finally→CancelledError ค้าง | **ไม่มี `await` เลย**ระหว่าง fixing=True (2202) ถึง `play()` (2279) → cancel ส่งไม่ได้; ทุก fail branch reset (2217/2282/2291) |
| `audit_log.py:183` | MED `_jsonl_prev_hash` race | `_add_jsonl_chain` เป็น **sync** (atomic ใน asyncio model) + `_FALLBACK_LOCK` รักษา FIFO write order |
| `document_extractor.py:270` | MED monkey-patch `_docx_parser.etree` race | 2 thread เขียน **ค่าเดียวกัน** (`_defused_etree`), ไม่เคย restore → idempotent |
| `message_queue.py:301` | HIGH lock ถูกลบระหว่าง get_lock/acquire | `cleanup_unused_locks` skip locked+pending+recent(<1h); window theoretical + เคยวิเคราะห์แล้ว |
| `ai_cog.py:938` | HIGH bot-mention ไม่ strip ก่อนเข้า AI | `<@id>` ใน prompt = quality nit (โมเดลเข้าใจ), ไม่ใช่ security/correctness → LOW |
| `discord_chat_claude_cli.py:133` | MED lock dict โตไม่จำกัด | bounded ด้วยจำนวน subprocess ที่ทำงานพร้อมกัน (น้อยมาก); break-on-locked = pattern เดิมที่ผ่าน audit |
| `server_commands.py:980,995` | MED `get_user_info` send ไม่มี allowed_mentions | อยู่ใน ` ``` ` code block → Discord ไม่ trigger mention |
| `consolidator.py:362` / `rag.py:912` | MED timeout handling | by-design (retry-on-timeout / index built-empty + periodic rebuild — มี comment อธิบาย) |

## DEFERRED — ของจริงแต่ไม่แก้ blind (มีเหตุผลรูปธรรม)

| ไฟล์:บรรทัด | ระดับ | ทำไมไม่แก้ตอนนี้ | Recipe |
|---|---|---|---|
| `document_extractor.py:47–49` | LOW (deprecation) | `defusedxml.lxml` deprecated upstream (เป็น DeprecationWarning จริงใน test). **ไม่มี XXE test net** (`test_document_extractor.py` ไม่มีเคส entities/XXE) → migrate security control แบบ blind = เสี่ยงทำ XXE defense พังเงียบ ๆ | ย้ายไป native `lxml.etree.XMLParser(resolve_entities=False, no_network=True)` (libxml2 รุ่นใหม่กัน billion-laughs ในตัว) **พร้อมเขียน XXE-rejection test ก่อน** แล้ว verify |
| `chat/formatter.ts:76,96` | LOW | LaTeX regex `(?:[^$]\|\\\$)+` / `[^$]+` ReDoS เชิงทฤษฎีบน dashboard ที่เป็น local single-user (input จาก Claude เป็นหลัก); ต้อง tsc rebuild + regen `ui/*.js` | cap ความยาว input ก่อน parse LaTeX |
| `server_commands.py:860` | INFO | `cmd_list_roles` ไม่ gate (ต่างจาก `list_channels`/`list_members` ที่ gate) — แต่ roles ไม่ใช่ข้อมูล per-channel-private (Discord เปิดให้สมาชิกเห็นอยู่แล้ว) | ถ้าต้องการ consistency: gate ด้วย view/manage_guild |
| `database.py:1554` | LOW | `get_all_rag_memories` ไม่มี `LIMIT` — แต่ caller cap ที่ `MAX_RAG_REBUILD` แล้ว + ตารางเป็น memory ภายในบอต (bounded by usage จริง) | เพิ่ม `LIMIT` ถ้าตารางโตมาก (ระวัง: ไม่มี ORDER BY) |

## Verification
- `python -m pytest tests/` → **3367 pass / 2 skip** (เท่า baseline; +1 test ใหม่ = sentry redaction)
- `ruff check .` → All checks passed
- `cargo check --manifest-path native_dashboard/Cargo.toml` → exit 0
- 2 warnings ที่เหลือ = intentional: `defusedxml.lxml` (defer ด้านบน) + `utils.monitoring.token_tracker` deprecated (ตั้งใจ, ชี้ไป cache.token_tracker)

## Coverage (15 กลุ่ม — ครบทุก non-test source)
core+config · logic+ai_cog · claude/CLI chat · api/ws/handlers · cache/core/response/session/storage ·
memory · processing/tools/data/commands · music+spotify · utils db/web/media · monitoring+reliability ·
scripts+SQL migrations · shell/ps1/docker/CI/configs · dashboard TS+ui · Rust(native+ext)+Go · docs

## รอบ MED/LOW — "แก้ที่เหลือทั้งหมด" (verified)

DONE เพิ่ม · Python **3369 pass/2 skip** · ruff clean · tsc + **vitest 189** · cargo check exit 0:

| ไฟล์ | บรรทัด | ระดับ | แก้ |
|---|---|---|---|
| `cogs/music/cog.py` | ~2481 | MED | `cleanup_cache._collect_in_use` วน `_guild_states` ใน worker thread → "dict changed size during iteration"; snapshot filenames บน event loop ก่อน แล้วทำ `Path.resolve()` (I/O) ใน thread |
| `scripts/bot_manager.py` | 909 | MED | `view_logs` path CWD-relative → anchor `PROJECT_ROOT / f_name` |
| `cogs/ai_core/session_mixin.py` | 201 | LOW | `save_all_sessions` เข้าถึง `self.chats[cid]` หลัง snapshot → KeyError ถ้า cleanup evict ระหว่าง await; ใช้ `.get()` + skip |
| `cogs/ai_core/logic.py` | 215 | LOW | ลบ dead `PATTERN_USER_MENTION` (comment อ้างว่าใช้ใน on_message แต่ grep ทั้ง repo = define เดียว ไม่เคยถูกเรียก) |
| `cogs/ai_core/logic.py` | 1107,1116 | LOW | per-image `try/finally` → `try/except+finally`: รูปแปลงไม่ได้ 1 ใบไม่ล้มทั้ง turn (drop ที่เหลือ) |
| `cogs/ai_core/character_tags.py` | 28 | LOW | `_compile_guild_pattern` guard `if not filtered: return re.compile(r"(?!)")` กัน empty alternation จับทุกบรรทัด |
| `cogs/ai_core/api/document_extractor.py` + `requirements.txt` + test | 40–60,260,337 | LOW | ลบ deprecated `defusedxml.lxml` monkey-patch (เป็น **no-op** — `oxml_parser` ถูกสร้างก่อน patch) → พึ่ง python-docx `resolve_entities=False` (verified ด้วย inspect) + **เพิ่ม XXE regression test** (pin protection) + DOCX_DISABLED gate บน python-docx แทน defusedxml → DeprecationWarning หาย |
| `native_dashboard/src-ts/chat/formatter.ts` | 76 | LOW | block-LaTeX regex `(?:[^$]\|\\\$)+` → `(?:[^$\\]\|\\.)+` (ตัด ambiguity = ReDoS) + rebuild `ui/chat/formatter.js` |

VERIFIED NON-ISSUE (พิสูจน์โค้ดจริง — ไม่แก้):
- `server_commands` direct sends ไม่มี `allowed_mentions` → **bot.py:751 ตั้ง global `AllowedMentions(everyone=False, roles=False, users=True)`** = @everyone/role mass-ping ถูกบล็อกทั้งระบบแล้ว (เหลือแค่ targeted `<@user>` ที่ตั้งใจให้ ping)
- `resize.rs:51` `(w as u64)*(h as u64)` → u32×u32 ≤ ~1.84e19 < u64::MAX **เสมอ** (overflow ไม่ได้) + `check_bomb_dimensions`(checked_mul) gate ก่อนทุก call
- `url_fetcher/main.go:505` X-Trace-ID reflect → Go net/http drop header ที่มี CRLF เอง + context key ไม่เคยถูกอ่าน/log
- `memory_consolidator.init_schema` ใช้ `get_connection` (DDL) → ตรงกับ `database.py:371` (canonical init ก็ใช้ get_connection)
- `_save_queue_json_sync` `list(deque)` = GIL-atomic (stale-by-one ไม่ใช่ corruption)
- `get_all_rag_memories` ไม่มี LIMIT → caller cap `MAX_RAG_REBUILD`; ใส่ LIMIT จะ drop newest = regression → skip
- auto-title (frontend escape แล้ว), fallback `seconds` float-cast (จะ crash ถ้า non-numeric), chat-manager `CSS.escape` (id เป็น type `number` จาก backend) → marginal/guard สิ่งที่ type กันแล้ว

## รอบ Dashboard UI — ตรวจละเอียดทุกไฟล์ (static + behavioral)

อ่าน/triage ทุก injection sink ของ UI ทั้งหมด: `index.html`, 17 ไฟล์ TS (`chat-manager.ts` 2968 ·
`app.ts` 1990 · `shared.ts` 855 · chat/*), `tauri.conf.json`, `capabilities/default.json`,
`styles.css`. **พบบั๊กจริง: 0** — UI harden ระดับสูงมาก.

DONE (polish เดียว, ไม่ใช่ live bug):
| ไฟล์ | บรรทัด | แก้ |
|---|---|---|
| `chat/image-attach.ts` | 103 | `e.target`→`e.currentTarget` + radix 10 (idiom ถูก + ตรงกับ document-attach.ts; ปุ่ม `×` ไม่มี child element จึงยังไม่ใช่บั๊ก แต่กันเหนียว) + rebuild ui |

VERIFIED SECURE (พิสูจน์เอง):
- **CSP/SRI/importmap**: คำนวณ sha384/sha256 ของไฟล์ vendored จริง — **ตรงทุกตัว** (DOMPurify/KaTeX×3/Prism×2 + importmap); `tauri.conf` CSP strict (`object-src 'none'`, `frame-ancestors 'none'`, WS pin 127.0.0.1:8765), `withGlobalTauri:false`, `devtools:false`, `dragDropEnabled:false`
- **capabilities/default.json**: minimal (ไม่เอา `core:default`/dialog file-picker) — IPC surface แคบ
- **ทุก innerHTML sink (~52)**: formatMessage(DOMPurify) สำหรับ AI/markdown · escapeHtml ทุก text/attr · createElement+textContent สำหรับ DB lists (channels/users โชว์แค่ ID ตัวเลข) · static ที่เหลือ
- **core primitives** solid: `escapeHtml` (DOM + quotes/backtick), `isSafeAvatarUrl` (asset/tauri allowlist เข้ม + reject SVG/`http://`/`../`, case-insensitive), `safeAvatarUrl`, `showToast`
- `message-template.ts`: escape ครบ + `msg.id` coerce numeric กัน attribute breakout; copy-btn handler เลี่ยง `textarea.innerHTML` re-parse (กัน `</textarea><img onerror>`)

VERIFIED NON-ISSUE (subagent/old-finding overstate):
- `search.ts` — cap **2 ชั้น** (candidates@164 + hits@189 break) → marks ≤1000 ไม่มี perf bug
- `prism.ts:69` `script.src` — `canon` ผ่าน `PRISM_LANGS.has()` allowlist ก่อน → inject ไม่ได้
- scroll badge increment ที่ 1997 แล้ว (old "dead badge" = fixed) · blob revoke defer 1s = ถูก (freed ตอนปิด) · `editedMsg.documents` handle แล้ว
- `export-picker` cast / `conversation-list` listener-prop / `document-attach` empty-file → local-only / brittle-not-bug / UX cosmetic

Behavioral (real browser): **e2e 36 pass** (h7-csp: style-src violation=0 · h5-importmap: IPC ผ่าน importmap · smoke · interactions) · **vitest 189** · tsc build สะอาด
