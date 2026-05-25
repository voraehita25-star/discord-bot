# G20 — Documentation Accuracy Re-Audit (2026-05-24)

**Auditor scope:** READ-ONLY accuracy audit of project documentation vs. the actual codebase.
**Working dir:** `C:\BOT Discord`
**Today:** 2026-05-24 | **Repo version:** 3.3.15 (`version.txt`)

## Files audited (30)

README.md, CONTRIBUTING.md, cogs/ai_core/README.md, docs/ARCHITECTURE.md, docs/CODE_AUDIT_GUIDE.md,
docs/DATABASE_SCHEMA.md, docs/DEVELOPER_GUIDE.md, docs/INSTALL.md, docs/OWNER_COMMANDS.md, docs/SCHEMA.md,
docs/SENTRY.md, docs/TESTING.md, docs/TROUBLESHOOTING.md, docs/index.html, docs/style.css,
docs/release-notes/{v3.3.5,v3.3.8,v3.3.9,v3.3.10,v3.3.11,v3.3.13,v3.3.14,v3.3.15}.md,
docs/reviews/{CODE_REVIEW_COGS,CODE_REVIEW_REPORT,CODE_REVIEW_SUMMARY,CODE_REVIEW_SUMMARY_TH,FRONTEND_AUDIT_REPORT,UTILS_AUDIT_REPORT}.md
(Skipped per instructions: docs/reviews/audit_2026_05/* and audit_2026_05_24/*.)

## Severity summary

| Severity | Count |
|----------|-------|
| CRITICAL | 0 |
| HIGH | 0 |
| MEDIUM | 1 |
| LOW | 22 |
| INFO | 11 |
| **Total** | **34** |

- **No real secrets, tokens, or live credentials committed** in any audited doc. All API-key strings are placeholders (`sk-ant-...`, `https://xxx@xxx.ingest.sentry.io/xxx`, `your_token`). The Discord channel IDs in OWNER_COMMANDS.md are illustrative examples, not secrets.
- **No actively dangerous install/setup steps.** The two `curl ... | sh` rustup invocations (INSTALL.md) are the upstream-recommended rustup bootstrap and use `--proto '=https' --tlsv1.2` — standard, not a finding.
- **Model claims are CORRECT.** `claude-opus-4-7` verified as the current GA Anthropic model (released 2026-04-16; 1M context, 128k max output). All `claude-opus-4-7`, 1M-context, `CLAUDE_MAX_TOKENS=128000`, and `claude-haiku-4-5` references are accurate. `gemini-3.1-pro-preview` matches `dashboard_config.py`.
- Most issues are stale counts/versions and one wrong env-var/port pair; the prior `docs/reviews/*` reports are explicitly historical snapshots and are flagged INFO where they now diverge from current code.

---

## Findings

| File | Line(s) | Severity | Category | Issue | Suggested fix |
|------|---------|----------|----------|-------|---------------|
| docs/index.html | 16, 34 | MEDIUM | Outdated arch / contradicts all other docs | Advertises the bot as "Production-ready Discord bot with **Gemini 3 Pro** AI" and feature card "**Gemini 3 Pro** powered conversations". Every other doc (README, DEVELOPER_GUIDE, ARCHITECTURE, ai_core/README) states **Claude (claude-opus-4-7)** is the primary chat backend; Gemini is embeddings/RAG only. Public landing page misrepresents the product. | Change tagline + feature card to "Claude (Opus 4.7) powered conversations with memory" (Gemini for embeddings/RAG). |
| docs/index.html | 58 | LOW | Broken internal link | Developer Guide link points to `https://github.com/voraehita25-star/discord-bot/blob/main/DEVELOPER_GUIDE.md` (repo root) but the file lives at `docs/DEVELOPER_GUIDE.md`. 404. | Point to `blob/main/docs/DEVELOPER_GUIDE.md` (or relative `DEVELOPER_GUIDE.md`). |
| docs/TROUBLESHOOTING.md | 11, 84, 115, 197(implied), 9 | LOW | Wrong env var + wrong port (repeated) | Says "Python metrics (**METRICS_PORT**, default **8000**)" and `curl http://localhost:**8000**/metrics`. Source: bot.py:564 starts prometheus via `PROMETHEUS_PORT` (default **9090**); `metrics.start_server(port=metrics_port)`. `METRICS_PORT` env var does **not exist** anywhere in the codebase; the `8000` is only `metrics.py:start_server`'s unused default. ARCHITECTURE.md correctly lists Prometheus on 9090. | Replace all `METRICS_PORT`/`8000` with `PROMETHEUS_PORT`/`9090`; fix the three curl examples to `http://localhost:9090/metrics`. |
| docs/TROUBLESHOOTING.md | 143-145 | LOW | Outdated behavior (misleading guidance) | "Document too large" entry claims "The WebSocket frame cap is **10 MB** (`max_msg_size` in `ws_dashboard.py`)" and tells users to split PDFs near 10 MB. Source ws_dashboard.py:646-657 explicitly **removed** the old 10 MB cap (its comment: "previous fixed 10 MB cap contradicted MAX_DOCUMENT_SIZE_BYTES=32 MB"); `max_msg_size` is now `32MB + 10MB + MAX_CONTENT_LENGTH + 1MB ≈ 43 MB`. The 10 MB figure in source is `MAX_IMAGE_SIZE_BYTES` (per-image), not the frame cap. Advice to split sub-32MB PDFs is wrong. | Update to ~43 MB frame cap; note 10 MB is the per-image limit. Reframe the symptom around the 32 MB document cap. |
| docs/TROUBLESHOOTING.md | 206, 208 | LOW | Wrong default value | `ANTHROPIC_API_ENDPOINT` documented with default `https://api.anthropic.com` and described as "Anthropic API base URL". Source api_failover.py:190 default is the sentinel string `"direct"` (a mode selector flipping direct↔proxy), not a URL. (Lines 92-97 of the same doc describe the flip behavior correctly — internal contradiction.) | Document default as `direct`; describe it as the failover mode selector, not a base URL. |
| docs/SCHEMA.md | 107-120 | LOW | Schema drift (wrong columns) | `conversation_summaries` table is documented with columns `start_timestamp, end_timestamp, summary, message_count, topics`. Actual table (memory_consolidator.py:115-126) has `id, channel_id, user_id, summary, key_topics, key_decisions, start_time, end_time, message_count, created_at`. SCHEMA.md is missing `user_id, key_topics, key_decisions` and renames `start_time`/`end_time` → `start_timestamp`/`end_timestamp` and `key_topics`→`topics`. **DATABASE_SCHEMA.md (lines 117-128) has the correct columns** — SCHEMA.md is the stale one. | Replace SCHEMA.md `conversation_summaries` block with the actual columns (mirror DATABASE_SCHEMA.md). |
| docs/SCHEMA.md | 7-19 | LOW | Missing column | `ai_history` table omits `summarized_at DATETIME` (added migration 015, present in init_schema database.py:395). Consolidator now MARKs rows via `WHERE summarized_at IS NULL` instead of hard-deleting. | Add `summarized_at DATETIME` row to the `ai_history` table. |
| docs/DATABASE_SCHEMA.md | 20-37 | LOW | Missing column + index | `ai_history` table omits `summarized_at DATETIME` (migration 015) and the partial index `idx_ai_history_pending_summary ON ai_history(channel_id, timestamp) WHERE summarized_at IS NULL`. | Add the `summarized_at` column and the pending-summary partial index. |
| docs/DATABASE_SCHEMA.md | 339-354 | LOW | Migration table incomplete | Migration list stops at 014. Source has **015_ai_history_summarized_at.sqlite.sql**. (Total tables count of 21 also no longer reflects the schema additions cleanly — see INFO row below.) | Add migration 015 row. |
| docs/SCHEMA.md | 334-354 | LOW | Migration table incomplete | Same as above — migration table ends at 014; 015 (`ai_history_summarized_at`) is missing. | Add migration 015 row. |
| docs/DATABASE_SCHEMA.md | 109 | LOW | Index definition drift | Lists `idx_entity_name(guild_id, name)`. Actual (database.py:525) is `idx_entity_name ON entity_memories(name)` — single column. Source also defines `idx_entity_type`, `idx_entity_channel`, `idx_entity_guild` not listed here. | Correct `idx_entity_name` to `(name)`; optionally add the other entity indexes. |
| docs/SCHEMA.md | 105 | LOW | Index definition drift | Same `idx_entity_name(guild_id, name)` vs actual `(name)`. | Correct to `(name)`. |
| docs/SCHEMA.md | 96-103 | LOW | Schema drift (entity_memories) | `entity_memories` block omits the `entity_type TEXT NOT NULL` column (present in init_schema database.py:512 and the UNIQUE(name, channel_id, guild_id) constraint) and lists `created_at/updated_at` as DATETIME; source uses `created_at REAL NOT NULL, updated_at REAL NOT NULL`. DATABASE_SCHEMA.md (88-106) is correct. | Align SCHEMA.md entity_memories with actual columns/types (mirror DATABASE_SCHEMA.md). |
| docs/DEVELOPER_GUIDE.md | 759-761 | LOW | Nonexistent table names | The "Schema (SQLite)" quick table lists tables **`long_term_facts`** and **`rag_memories`** — neither exists. Actual names are `user_facts` and `ai_long_term_memory`. | Rename to `user_facts` and `ai_long_term_memory`. |
| cogs/ai_core/README.md | 124 | LOW | Stale "verified" line count | States `logic.py` is "currently **~1,368 lines** (verified `wc -l cogs/ai_core/logic.py`)". Actual is **1,633 lines**. The explicit "verified" wording makes the staleness more misleading. | Update to ~1,633 (or drop the hard number). |
| docs/INSTALL.md | 148-197 | LOW | Stale dependency versions (many) | Dependency table vs `requirements.txt`: python-dotenv 1.2.1→**1.2.2**; aiohttp 3.13.4→**3.13.5**; google-genai 1.67.0→**1.75.0**; Pillow 12.1.1→**12.2.0**; lxml 6.0.2→**6.1.0**; numpy 2.4.2→**2.4.4**; imageio 2.37.2→**2.37.3**; yt-dlp 2026.3.13→**2026.3.17**; spotipy 2.25.2→**2.26.0**; PyNaCl 1.5.0→**>=1.6.2,<2**; pytest 9.0.2→**9.0.3**; sentry-sdk 2.53.0→**2.59.0**; orjson 3.11.7→**3.11.8**; prometheus-client 0.24.1→**0.25.0**. | Refresh the table from requirements.txt (or replace with a pointer to requirements.txt to avoid future drift). |
| docs/TESTING.md | 81-98 | LOW | Stale Playwright spec count/list | Header + section say "**5 Playwright** spec files" and the tree omits `dashboard-inspection.spec.ts`. Actual: **6** spec files (a11y, dashboard-inspection, dashboard-smoke, interactions, screenshots, visual-regression) — the inspection suite was added (recent commit "track e2e inspection suite"). | Bump to 6 and add `dashboard-inspection.spec.ts` to the tree. |
| README.md | 126, 311 | LOW | Stale Playwright count | "63 Playwright" and "5 Playwright spec files" — spec-file count is 6 now (see above). The "63" test count is unverifiable here but pairs with the stale file list. | Update spec-file count to 6; re-verify the 63 figure. |
| docs/DEVELOPER_GUIDE.md | 7, 248-254 | LOW | Stale Playwright count | "5 Playwright spec files (63 …)" and `tests-e2e/` tree omits `dashboard-inspection.spec.ts`. | Update to 6 spec files; add the inspection spec. |
| docs/CODE_AUDIT_GUIDE.md | 4 | LOW | Stale counts | "Files: ~231 Python", "Python Test Files: 92", "5 Playwright e2e". Actual: 100 git-tracked `tests/test_*.py` files (101 on disk); 6 Playwright spec files. v3.3.15.md itself says "214 Python files, 90 test files". Numbers are internally inconsistent across docs. | Reconcile counts; the doc already says the file list is "a summary, not source of truth" — consider replacing hard numbers with the `git ls-files` instruction. |
| README.md | 126, 311; DEVELOPER_GUIDE.md 7, 190 | LOW | Stale test-file count | "92 Python test files" / "92 files". Actual 100 git-tracked `test_*.py`. Test *count* (3,094) not independently verified. | Re-count via `git ls-files "tests/test_*.py"`; update or de-hard-code. |
| docs/release-notes/v3.3.11.md | 21 | LOW | Wrong migration filename | "Missing semicolon in migration 003 — Last CREATE INDEX in **`003_fix_user_facts.sql`**". Actual file is `003_fix_user_facts.**sqlite.sql**`. (Historical note, but the filename is wrong as written.) | Use `.sqlite.sql` extension. |
| docs/release-notes/v3.3.15.md | 55, 76 | LOW | Wrong migration filename | References created file `scripts/maintenance/migrations/**006_drop_character_profiles.sql**`. Actual: `006_drop_character_profiles.**sqlite.sql**`. | Use `.sqlite.sql` extension. |
| docs/DATABASE_SCHEMA.md / SCHEMA.md | DB_SCHEMA 9,16,426; SCHEMA 335-337 | INFO | Table-count / extension note now needs a tweak | DATABASE_SCHEMA.md states "21 tables (19 at init + lazy conversation_summaries + schema_version)". With migration 015 the schema gained `summarized_at`/partial index (no new table), so the table count stays 21 — but the doc should still reflect mig 015. SCHEMA.md's migration-extension note is accurate (runner accepts both `*.sqlite.sql` and `*.sql`). | Minor: add mig 015 mention; no table-count change needed. |
| docs/reviews/CODE_REVIEW_COGS.md | 1-5, 13 | INFO | Stale prior-audit report | Dated 2025-07; "All 61 Python files under cogs/". Many cited issues are now fixed in current code (e.g., #3 storage.py threading.RLock-in-async; #4 webhook fetch per-message; #5 non-atomic queue write; #8/#23 non-greedy JSON regex). References `content_processor.py` indirectly via media; that file was deleted in v3.3.15. Keep as historical. | Mark as historical/superseded (add a "as-of 2025-07; many items since fixed" banner). |
| docs/reviews/CODE_REVIEW_REPORT.md | 1-18 | INFO | Stale prior-audit report | Dated 2025-01-20; counts CRITICAL 7/HIGH 18 etc. C-6 "4-tier refusal bypass escalation" and L-14 "Unused content_processor.py" are no longer present (removed in v3.3.15 — ESCALATION_FRAMINGS/detect_refusal deleted; content_processor.py deleted). | Mark superseded; note items fixed in v3.3.10–v3.3.15. |
| docs/reviews/CODE_REVIEW_SUMMARY.md | 1-13, 75, 181-184 | INFO | Stale prior-audit report | Dated 2026-02-10, v3.3.10; "Security Vulnerabilities: None"; "discord.py 2.6.4", "Pillow 12.1.0", "numpy 2.2.6", "249 Python files", "3,157 tests". All now drifted (discord.py 2.7.1, Pillow 12.2.0, numpy 2.4.4). Historical. | Mark superseded / add version stamp note. |
| docs/reviews/CODE_REVIEW_SUMMARY_TH.md | 1-4 | INFO | Stale prior-audit report (Thai) | Thai mirror of CODE_REVIEW_SUMMARY (v3.3.10, 2026-02-10). Same staleness. | Same as CODE_REVIEW_SUMMARY. |
| docs/reviews/FRONTEND_AUDIT_REPORT.md | 1-6, 16, 22-31 | INFO | Stale prior-audit report | Dated 2025-07-18. Top "CRITICAL" (`withGlobalTauri: false` breaks IPC) and several `src-ts/app.ts` line refs predate the 2026-04 chat-manager split into `src-ts/chat/*` (DEVELOPER_GUIDE 243-247). Line numbers no longer map. Historical. | Mark superseded; note app.ts was split post-audit. |
| docs/reviews/UTILS_AUDIT_REPORT.md | 1-6 | INFO | Stale prior-audit report | Dated 2025; "32 Python files under utils/". Several issues (e.g., #2 asyncio.Lock at wrong loop, #11 DNS-rebinding TOCTOU) were addressed (lazy locks; Go-side ssrfSafeDialContext per release notes). Historical. | Mark superseded; cross-link to fixes in v3.3.10/v3.3.14. |
| docs/release-notes/v3.3.5.md | 44-49 | INFO | Historical CI claim now outdated | Lists CI matrix "Python 3.10 (3.10, 3.11, 3.12)". Project migrated to Python 3.14-only in v3.3.13 (CI matrix → 3.14 only). Correct for v3.3.5 as written; flag only because readers may take it as current. | No change needed (historical); optionally add "superseded by v3.3.13" note. |
| docs/SENTRY.md | 28-31 | INFO | Unverified env var | `SENTRY_ENVIRONMENT` is documented as "read by bot.py at startup". Not independently confirmed in this audit. (No evidence it is wrong; sentry_integration.py accepts `environment=`.) | Needs verification — confirm bot.py reads `SENTRY_ENVIRONMENT`. |
| docs/OWNER_COMMANDS.md | 316 | INFO | Path needs verification | References `data/db_export/ai_history/` for JSON history export. Source has `EXPORT_DIR = data/db_export` and a `dashboard_chats` subdir; the per-channel `ai_history/` subdir is plausible but not directly confirmed in this pass. | Needs verification — confirm the `ai_history/` export subdir name. |
| CONTRIBUTING.md | 16, 81-86 | INFO | Accurate (verified) | `make install-hooks`, `make lint`, `make test`, `make build-rust`, `make build-go` all exist as Makefile targets — **no issue**. Listed for completeness. | None. |
| README.md / DEVELOPER_GUIDE.md / INSTALL.md | README 61-62,260-272; DG 460-461; INSTALL 132-133 | INFO | Accurate (verified) | `cp faust_data_example.py faust_data.py` flow + `data/__init__.py` auto-fallback-to-`_example` claim is **correct** (try/except ImportError in `cogs/ai_core/data/__init__.py`). Both real and example files exist locally. | None. |

---

## Verification notes (what was checked against source)

- **Makefile targets** (`Makefile`): install-hooks, lint, lint-fix, test, test-fast, test-cov, build-rust, build-go, db-check, db-migrate, db-export, security, audit all present — CONTRIBUTING/CODE_AUDIT_GUIDE/TESTING references valid.
- **conversation_summaries** schema source of truth = `cogs/ai_core/memory/memory_consolidator.py:115`. DATABASE_SCHEMA.md correct; SCHEMA.md drifted.
- **ai_history.summarized_at** = `utils/database/database.py:395` + migration `015_ai_history_summarized_at.sqlite.sql`. Missing from both schema docs.
- **entity_memories** = `utils/database/database.py:509-547` (`entity_type` col, `created_at REAL`, `idx_entity_name(name)`). DATABASE_SCHEMA.md mostly correct (index drift); SCHEMA.md drifted on columns.
- **Ports:** Health API 8080 (`health_api.py:71`), Prometheus 9090 via `PROMETHEUS_PORT` (`bot.py:564,571`), Go Health 8082 (`health_api.py:146`), Dashboard WS 8765. `METRICS_PORT` not present anywhere.
- **ws_dashboard max_msg_size** ≈ 43 MB (`ws_dashboard.py:651-657`), not 10 MB.
- **Model id** `claude-opus-4-7`: confirmed current GA model (web). `gemini-3.1-pro-preview`, `CLAUDE_CONTEXT_WINDOW=1000000`, `CLAUDE_EFFORT∈{low,medium,high,xhigh,max}`, `CLAUDE_BACKEND=cli` default — all match `dashboard_config.py`/`constants_env.py`/`config.py`.
- **ai_core file structure** (README/DEVELOPER_GUIDE): claude_payloads.py, imports.py, session_mixin.py, api/* (incl. dashboard_chat.py, dashboard_chat_claude.py, dashboard_chat_claude_cli.py, document_extractor.py), prompts/base.yaml — all exist.
- **content_processor.py** confirmed deleted (matches v3.3.15.md).
- **Startup scripts** (TROUBLESHOOTING/DEVELOPER_GUIDE): start.ps1, start_dev.ps1, dev.bat, manager.ps1, start.bat — all exist.
- **Document-extractor caps** (DATABASE_SCHEMA/SCHEMA/TROUBLESHOOTING/README): MAX_EXTRACTED_CHARS=500_000, MAX_TOTAL_CHARS=20_000_000, MAX_ROWS=200 — all match `document_extractor.py`.
- **No live secrets** found in any audited file.
