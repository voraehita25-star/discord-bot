# G11: Scripts — Audit Report

Audit date: 2026-05-04
Auditor: Claude (Opus 4.7, 1M)
Scope: 24 files under `C:\BOT Discord\scripts\` plus `native_dashboard\scripts\create_desktop_shortcut.py` (every line read by hand).

## Files Reviewed

| File | LOC | Purpose |
|---|---:|---|
| `scripts/__init__.py` | 1 | Package marker |
| `scripts/bot_manager.py` | 876 | Interactive bot supervisor (status, start/stop/restart, logs, self-heal) |
| `scripts/check_balance.py` | 37 | Query Anthropic proxy quota / usage |
| `scripts/dev_watcher.py` | 907 | Watchdog-based hot-reload dev server |
| `scripts/load_test.py` | 281 | Simulated AI request load tester |
| `scripts/maintenance/add_local_id.py` | 98 | DB migration: add per-channel `local_id` |
| `scripts/maintenance/check_db.py` | 23 | DB inspection: per-channel id ranges |
| `scripts/maintenance/clean_cli_orphans.py` | 120 | Delete orphan Claude CLI session files |
| `scripts/maintenance/clean_history.py` | 96 | Strip empty model responses from JSON history |
| `scripts/maintenance/convert_log015.py` | 126 | LOG015 lint fixer (logging.X → logger.X) |
| `scripts/maintenance/count_cli_sessions.py` | 105 | Survey Claude CLI session file folders |
| `scripts/maintenance/dump_cli_prompt.py` | 100 | Dump assembled CLI prompt for a conversation |
| `scripts/maintenance/find_unused.py` | 167 | Static unused-file finder |
| `scripts/maintenance/inspect_dashboard_memories.py` | 43 | Print dashboard_memories table contents |
| `scripts/maintenance/inspect_db.py` | 10 | Print DB schema |
| `scripts/maintenance/migrate_to_db.py` | 325 | One-time JSON-to-SQLite migrator |
| `scripts/maintenance/reindex_db.py` | 206 | Re-number ai_history primary keys |
| `scripts/maintenance/rollback_migration.py` | 242 | Backup-driven migration rollback |
| `scripts/maintenance/schema_smoke.py` | 64 | Smoke test full schema init in temp dir |
| `scripts/maintenance/view_db.py` | 65 | Export every DB table to JSON |
| `scripts/shared/__init__.py` | 7 | Re-exports `Colors` |
| `scripts/shared/colors_fallback.py` | 55 | ANSI fallback when `utils.media.colors` is missing |
| `scripts/verify_system.py` | 107 | Compile check + import sweep of cogs |
| `native_dashboard/scripts/create_desktop_shortcut.py` | 71 | Win32 IShellLink desktop shortcut creator |

Migrations folder lists 14 numbered SQL files (`001_baseline.sqlite.sql` … `014_dashboard_tags_and_likes.sqlite.sql`) — referenced indirectly by `schema_smoke.py` but the migration runner itself lives outside this audit's scope (in `utils/database/`).

---

## Issues Found

| File | Line(s) | Severity | Category | Description |
|---|---|---|---|---|
| `scripts/bot_manager.py` | 72-74 | Medium | Path/CWD | `STATUS_FILE`, `PID_FILE`, `STOP_FLAG` are bare relative paths. They resolve against whatever CWD the user invoked from, NOT against `PROJECT_ROOT`. Running `bot_manager.py` from another folder will silently leave a stale `bot.pid` outside the project and miss the real one. Should be `PROJECT_ROOT / "bot.pid"` etc. |
| `scripts/bot_manager.py` | 242-246 | Low | Subprocess | `clear_screen` uses `subprocess.run(["cmd", "/c", "cls"], ...)`. `os.system("cls")` is the conventional and faster path; spawning `cmd.exe` for every screen refresh is wasteful inside a CLI loop. Not a security bug (`shell=False`, args fixed) but unnecessary process churn. |
| `scripts/bot_manager.py` | 538-548 | Low | Cross-platform | `import signal` is inside the function body, making the SIGINT branch importable-only on POSIX. OK functionally, but the `# On Windows, SIGINT doesn't work well` comment is misleading: `psutil.Process.send_signal(signal.SIGINT)` *does* deliver `CTRL_C_EVENT` to the target on Windows when the target shares the console group. The Windows code path silently jumps straight to `terminate()` without a graceful attempt. |
| `scripts/bot_manager.py` | 581-587 | High | Destructive / no confirm | `auto_stop_existing_bot()` is invoked from `start_bot()` *unconditionally* whenever a bot is running. Hitting menu option 2/3/4 by accident kills the running production bot without ever asking. The function name says "auto" but the only operator-visible warning is one line of yellow text. Should require a `y/n` prompt unless an explicit `--force` flag is set. |
| `scripts/bot_manager.py` | 591-610 | Medium | Subprocess | `_launch_script` calls `subprocess.Popen([path_str], ...)` with no stdout/stderr redirection. On Windows this also uses `os.startfile` for non-hidden mode — which detaches the launched process from the parent entirely. Output is lost; if the launched script crashes immediately, the operator gets a green "Bot start command sent!" with no way to know. |
| `scripts/bot_manager.py` | 602 | Medium | Subprocess | `subprocess.Popen(["wscript", path_str], shell=False, cwd=cwd)` for the hidden launcher. `wscript` is resolved via `PATH`; if a malicious `wscript.exe` lives on `PATH` ahead of `C:\Windows\System32`, this runs it. Should use `shutil.which` or hardcode `C:\Windows\System32\wscript.exe`. (Minor — same exposure as nearly every Windows tool, but auditable.) |
| `scripts/bot_manager.py` | 642-664 | High | Process lifecycle | `stop_bot()` writes `STOP_FLAG = "stop_loop.flag"` (relative path → CWD-dependent, see #1). The bot side that consumes this flag will miss it if invoked from a different CWD. The flag itself is then never deleted on success — stale flag could prevent the next start. |
| `scripts/bot_manager.py` | 685 | Low | Bug | `restart_bot()` returns `start_bot(mode)`'s value implicitly via fall-through, but only `start_bot(mode)` — there's no `return` keyword. Caller can't tell if the restart succeeded. |
| `scripts/bot_manager.py` | 681 | Low | Bug | `restart_bot()` maps `launcher_type == "scheduled"` to `mode = "scheduled"`, but `start_bot()` only handles `"production"`, `"dev"`, `"hidden"`. `"scheduled"` falls into the `else` branch and starts a foreground production process — the intent of preserving "scheduled" is not honored. |
| `scripts/bot_manager.py` | 770-782 | Medium | Destructive / no confirm | `run_kill_all()` confirms with literal `"yes"` but bypasses any backup/log of what was killed. If the user types `yes` on the wrong window, every Python process matching `bot.py` dies with no audit trail. Acceptable for a manual menu option, but consider logging the killed PIDs to `logs/self_healer.log`. |
| `scripts/bot_manager.py` | 802-806 | Low | I/O | `_tail_lines` reads in 64KB chunks but loops `while pos > 0 and data.count(b"\n") <= n`. For a log with very long lines (>64KB single line), this terminates correctly but the resulting decode-and-split throws away anything before the chunk boundary. Edge case only. |
| `scripts/bot_manager.py` | 810-830 | Medium | Path | `view_logs()` reads `Path("bot.log")` etc. — relative to CWD again. If invoked from elsewhere, log files won't be found. Should be `PROJECT_ROOT / "bot.log"`. |
| `scripts/bot_manager.py` | 871-872 | Low | UX | `KeyboardInterrupt` in the input prompt simply breaks the loop; no cleanup of the partially-launched process if Ctrl+C lands during `start_bot`. |
| `scripts/dev_watcher.py` | 21 | Low | Style | `logger = logging.getLogger(__name__)` declared at module-top *before* `logging` is imported on line 19 — wait, no, line 19 *is* `import logging`. But the placement (before `import os`) is unusual; PEP 8 expects logger declaration after all imports. Cosmetic. |
| `scripts/dev_watcher.py` | 109-117 | Low | Validation | `load_from_file` validates value type with `isinstance(value, expected_type)`. `bool` is a subclass of `int`, so `isinstance(True, int)` is True — passing `True` for an `int` config value silently succeeds. Conversely `isinstance(1, bool)` is False so int→bool is rejected. Unlikely to hit in practice. |
| `scripts/dev_watcher.py` | 162 | Low | Logging | `logging.FileHandler` uses default mode `'a'` with no rotation. On a long-running watcher session `dev_watcher.log` grows unbounded. Consider `RotatingFileHandler` (5MB × 3). |
| `scripts/dev_watcher.py` | 180-188 | Low | Cross-platform | Uses `PollingObserver` on Windows. Polling is reliable but inefficient — `watchfiles` (Rust-based, uses native `ReadDirectoryChangesW`) is dramatically faster. Not a bug, just a perf opportunity. |
| `scripts/dev_watcher.py` | 309-326 | Medium | Process lifecycle | `check_and_stop_existing_bot()` fallback path calls `proc.terminate()` then `proc.kill()` but only catches `psutil.NoSuchProcess` and `Exception`. The bare `except Exception as e:` then `sys.exit(1)` will EXIT THE WATCHER on any failure to stop — meaning the operator's invocation of dev mode silently fails with the bot still running. Consider stricter exception handling. |
| `scripts/dev_watcher.py` | 463-466 | Medium | Process lifecycle | `start_bot` calls `self.process.terminate()` then `wait(timeout=5)` then `kill()` — but the second `wait(timeout=2)` after `kill()` has no error handler. If kill-then-wait fails (e.g., zombie), `self.process` is reassigned to a new Popen below, leaking the old handle. |
| `scripts/dev_watcher.py` | 493-508 | High | Windows orphan | The bot child is launched with `subprocess.CREATE_NEW_PROCESS_GROUP`. On Windows this means: if the watcher itself is killed via Task Manager / `taskkill /F`, the bot is *not* killed automatically — Windows job objects are not used. To guarantee tree-cleanup the watcher should `AssignProcessToJobObject` with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`. Currently relies entirely on the explicit `terminate()` in shutdown. |
| `scripts/dev_watcher.py` | 524 | Low | Exception | `except Exception as e:` swallows everything; even `KeyboardInterrupt` is fine here (it's a BaseException) but a broken `Popen` (e.g., invalid `sys.executable`) only gets logged at warning level — the watcher then loops forever calling `check_for_crash` on a None process. |
| `scripts/dev_watcher.py` | 541-579 | Medium | Restart loop | `check_for_crash` triggers `_start_bot_unlocked("Auto-retry after crash")` after a `time.sleep(self.config.crash_retry_delay)` *inside the lock* — for `crash_retry_delay=5s` this freezes the file-event observer for 5s. Acceptable, but documented nowhere. |
| `scripts/dev_watcher.py` | 547-577 | Medium | Restart loop | `consecutive_crashes` is incremented inside the lock but `_start_bot_unlocked` resets it to 0 only on success (line 518). If the bot starts but fails health check (poll() returns non-None within 3s), `consecutive_crashes` is NOT incremented (only `crash_count` is), so a fast-crashing bot can re-spawn forever despite `max_crash_retries=3`. The retry-cap only protects the SIGCHLD path, not the health-check-fail path. |
| `scripts/dev_watcher.py` | 596-627 | Low | Path | `_should_ignore` good-faith fix exists, but `parts` is built from `Path(path).parts` which on Windows gives a drive component (`'C:\\'`) — its lower() is `'c:\\'`. None of the ignore patterns can match a drive letter, so this is OK, but the `bool(any(part.startswith(".") for part in p.parts if part not in ("", "/")))` check at the bottom returns True for any path starting with `.` (e.g., `./bot.py` → first part is `.`, but Path normalizes that away on Windows; on POSIX `Path("./bot.py").parts` is `('bot.py',)` so it's safe by chance). |
| `scripts/dev_watcher.py` | 629-691 | Medium | Race | `_handle_change` calls `start_bot()` which acquires `self._lock`; but the debounce timestamp check `current_time - self.last_event_time < debounce_seconds` happens INSIDE the lock — meaning two near-simultaneous events queue serially on the lock and the second one sees a fresh `last_event_time` and gets debounced correctly. OK, but a third event arriving while a 5-second `crash_retry_delay` is sleeping will block the watchdog observer thread on the lock. |
| `scripts/dev_watcher.py` | 705-720 | Medium | Signal handler | `confirm_shutdown` calls `input()` from inside a signal handler. On POSIX this can deadlock if the signal arrives while the main thread is already inside `input()` (re-entrant readline). Recommended: set a flag, return, and let the main loop poll. |
| `scripts/dev_watcher.py` | 814-816 | Low | Watchdog | `Observer(timeout=config.poll_interval)` then `observer.schedule(handler, path=".", recursive=True)` — the path is `.` (relative to CWD). The `os.chdir(PROJECT_ROOT)` at line 743 makes this work, but the chdir is the only thing keeping it correct. Should pass `str(PROJECT_ROOT)` explicitly. |
| `scripts/dev_watcher.py` | 824-836 | Low | Cross-platform | SIGTERM/SIGINT handlers wired correctly — but `SIGBREAK` only exists on Windows; `SIGTERM` only takes effect on POSIX. The duplication is fine; comment is clear. |
| `scripts/dev_watcher.py` | 839-845 | Low | Loop | `time.sleep(0.5)` polling loop wastes CPU; could use `event_handler.process.wait()` with a short timeout in a thread or `signal.pause()` on POSIX. Not critical. |
| `scripts/dev_watcher.py` | 855-867 | Medium | Process lifecycle | Final shutdown path: `event_handler.process.terminate()` → `wait(5s)` → on TimeoutExpired call `kill()` → `wait(5s)`. But the inner `process.wait(timeout=5)` after `kill()` is wrapped in `try/except subprocess.TimeoutExpired:` only. If `kill()` itself raises (e.g., process already gone — `OSError`), the watcher's clean-shutdown is incomplete and the `observer.join()` below still runs. Logger only records "Process did not exit after kill()" on TimeoutExpired, masking other errors. |
| `scripts/check_balance.py` | 23-24 | Low | Network | `httpx.get(..., timeout=10)` — single-shot, no retry. Fine for a quick CLI but if the proxy is slow this fails noisily. No connection pooling matters for a 2-call CLI. |
| `scripts/check_balance.py` | 19 | Medium | Secret handling | API key passed via `Authorization: Bearer {key}` header. If the script crashes (e.g., bad URL), the traceback could include the URL but key is in headers so likely safe. Output of `print(f"ERROR: {e}")` could leak the response body if proxy returns the key in error. Low risk. |
| `scripts/check_balance.py` | 23 | Low | Schema assumption | Assumes Anthropic-proxy-specific endpoints `/v1/dashboard/billing/subscription` and `/v1/dashboard/billing/usage`. These are OpenAI's endpoints, not Anthropic's. Either the script is mis-named ("Check API proxy balance / usage" — proxy specific) or it will silently fail against real Anthropic API. Should document the expected proxy. |
| `scripts/load_test.py` | 104-134 | Low | Testing | `simulate_ai_request` is purely synthetic — random sleep + random failure. The script is mis-billed as "Load Testing" but it never hits a real endpoint. Docstring says "In a real test, this would call the actual AI endpoint" — should be marked as a smoke test, not load test. |
| `scripts/load_test.py` | 169-170 | Medium | Asyncio | `tasks = [rate_limited_request(i) for i in range(...)]; await asyncio.gather(*tasks)` — for `total_requests=10000` this creates 10k coroutines in memory at once. The semaphore controls concurrency but not coroutine creation. For a true load test this should use `asyncio.Queue` or generator-based fan-out. |
| `scripts/load_test.py` | 246-260 | Low | Argparse | No upper bound on `--requests` or `--concurrency` — `--concurrency 100000` would create that many semaphore slots and OS file descriptors. Add `type=lambda x: max(1, min(int(x), 10000))`. |
| `scripts/load_test.py` | 196 | Low | Coupling | `await rate_limiter.check("gemini_api", user_id=12345)` hardcodes `"gemini_api"` and `user_id=12345`. If the rate limiter is per-user, the test pollutes user 12345's bucket. |
| `scripts/load_test.py` | 232 | Low | Side-effect | `gemini_circuit.record_failure()` mutates the global circuit breaker. If the bot is running in another process this has no effect, but if it shares the same process state (it doesn't here, but the import is the same module), it could trip the breaker for real traffic. Should isolate. |
| `scripts/maintenance/add_local_id.py` | 15 | Medium | Path | `DB_PATH = "data/bot_database.db"` — relative to CWD. If invoked from anywhere except the repo root, `shutil.copy2(DB_PATH, ...)` will fail with FileNotFoundError, and the user will then re-run from the right directory possibly without realizing the backup wasn't created. Use `Path(__file__).resolve().parents[2] / "data" / "bot_database.db"`. |
| `scripts/maintenance/add_local_id.py` | 23-26 | Medium | Backup safety | `shutil.copy2` of a SQLite DB while the file may be open by anyone is unsafe — WAL/SHM siblings are NOT copied. Compare to `reindex_db.py` which DOES copy `-wal`/`-shm`. The `[WARNING] Make sure the bot is STOPPED!` prompt is the only safeguard. Should either: (a) use `sqlite3.Connection.backup()` for a consistent snapshot, or (b) copy WAL/SHM siblings like `reindex_db.py` does. |
| `scripts/maintenance/add_local_id.py` | 29-65 | High | Migration safety | The migration is NOT wrapped in `BEGIN ... COMMIT`. Each `await conn.execute("UPDATE ...")` auto-commits in aiosqlite by default (`isolation_level=""` triggers implicit BEGIN on first DML, but the single `await conn.commit()` at line 65 is the only commit). If the script crashes mid-loop (channel #50 of 100), the DB is left in a half-populated state with no local_id for half the rows and no rollback. Should `BEGIN IMMEDIATE` explicitly. |
| `scripts/maintenance/add_local_id.py` | 36-37 | Low | Idempotency | "if column exists, will update values" — re-running this script overwrites local_id silently. Combined with no transaction, a re-run after partial completion is risky. |
| `scripts/maintenance/add_local_id.py` | 56-61 | Medium | Performance / correctness | `for idx, row in enumerate(rows, start=1): await conn.execute("UPDATE ai_history SET local_id = ? WHERE id = ?", ...)` — N round-trips per row. For 100k rows this is hours. Should use a single SQL: `UPDATE ai_history SET local_id = (SELECT COUNT(*) FROM ai_history h2 WHERE h2.channel_id = ai_history.channel_id AND h2.id <= ai_history.id)` or window function. |
| `scripts/maintenance/add_local_id.py` | 90-98 | Low | Confirmation | Confirms with `confirm.lower() == "yes"` (good) and supports `--force` to skip (also fine). No backup-skip protection if the bot IS running — script doesn't check. |
| `scripts/maintenance/check_db.py` | 7 | Medium | Path | Same hardcoded relative path issue: `aiosqlite.connect("data/bot_database.db")`. CWD-dependent. |
| `scripts/maintenance/clean_cli_orphans.py` | 24 | Medium | Encoding bug surface | `encode()` already replaces `_`. But the bug-hunter script `count_cli_sessions.py` notes the bot's encoder used to NOT replace `_`. If this script ever predates that fix being deployed, it will look for the wrong folder. The header docstring should reference the fix in `dashboard_chat_claude_cli.py`. |
| `scripts/maintenance/clean_cli_orphans.py` | 32-39 | Good | Confirmation | `--apply` requires both `--apply` AND `--yes` OR an interactive `yes` prompt. Solid pattern. |
| `scripts/maintenance/clean_cli_orphans.py` | 88-93 | Good | Symlink safety | Explicitly skips symlinked dirs to prevent `rmtree` escape. |
| `scripts/maintenance/clean_cli_orphans.py` | 93 | Medium | Destructive | `shutil.rmtree(entry, ignore_errors=False)` deletes recursively; if a tracked file is renamed mid-run it will be missed. Acceptable — operator runs this offline. |
| `scripts/maintenance/clean_cli_orphans.py` | 67-79 | Low | Concurrency | `for entry in sorted(PROJECTS.iterdir()):` builds the list once, then iterates — fine for small dirs but with thousands of files this OOMs. Probably fine for this use case. |
| `scripts/maintenance/clean_history.py` | 10 | Medium | Path | `DATA_DIR = Path("data")` — relative. CWD-dependent. |
| `scripts/maintenance/clean_history.py` | 13-93 | Good | Atomic write | Writes to `.tmp` then `replace()`; also creates `.bak` sidecar. Good. |
| `scripts/maintenance/clean_history.py` | 22 | Medium | Confirmation | NO confirmation prompt before mutating user data files. Runs as soon as invoked. The atomic-write + .bak provides recovery, but the operator gets no chance to abort. |
| `scripts/maintenance/clean_history.py` | 65-69 | Low | Backup leak | Each run creates a fresh `.bak` overwriting the previous one. After 2+ runs the original is unrecoverable unless the operator manually copied the first .bak elsewhere. |
| `scripts/maintenance/clean_history.py` | 33-46 | Low | Logic | `if parts: ... else: is_empty = True` — but if `parts` is non-empty and ALL parts are empty/whitespace, falls through with `is_empty=True`. Correct but the dual-branch is confusing; could collapse. |
| `scripts/maintenance/convert_log015.py` | 35-37 | Medium | Regex correctness | `_CALL_RE` matches `^|\r?\n` then indent. `re.MULTILINE` is NOT set; `^` only matches buffer start. So all matches must be preceded by `\r?\n` — meaning the FIRST line of a file containing `    logging.info(...)` will not be replaced. Edge case, but could leave inconsistencies. Add `re.MULTILINE` and use `^[ \t]+logging\.X`. |
| `scripts/maintenance/convert_log015.py` | 69 | Medium | Line ending | The CRLF detection only checks `text_lines[import_idx].endswith(b"\r")` — the inserted line gets `\r` appended IF the import line was CRLF. But if the file is CRLF and the import line happens to be the LAST line of the file (no trailing \n), `split(b"\n")` produces the import line WITHOUT the trailing `\r` because there's no `\n` to split on. Edge case. |
| `scripts/maintenance/convert_log015.py` | 81-90 | Good | Safety | Syntax-checks via `py_compile` BEFORE overwriting — defensive against regex breakage. |
| `scripts/maintenance/convert_log015.py` | 81-94 | Medium | Atomicity | Writes to `tempfile.NamedTemporaryFile(... dir=path.parent)` then `path.write_bytes(new_content)` (NOT `tmp_path.replace(path)`). The temp file is deleted unconditionally after, but the actual swap is `path.write_bytes(...)` which is NON-atomic — a crash mid-write corrupts the source. Should `tmp_path.replace(path)` instead. |
| `scripts/maintenance/convert_log015.py` | 99 | Low | Argparse missing | Reads file list from stdin only; no `--file` arg, no `--dry-run`. Hard to test on a single file. |
| `scripts/maintenance/count_cli_sessions.py` | top-level | Low | Style | All work at module top level, not inside `if __name__ == "__main__":`. Importing this module performs the survey as a side effect. |
| `scripts/maintenance/count_cli_sessions.py` | 104 | Low | Bug | `len(data) if sidecar.exists() and isinstance(data, dict) else 0` — but `data` is referenced unconditionally on line 92's `data = json.loads(...)`. If `sidecar` doesn't exist, `data` is undefined and line 104 throws `UnboundLocalError`. (Top-level → NameError actually.) |
| `scripts/maintenance/dump_cli_prompt.py` | 24-26 | Low | Side effect on import | Imports modules that may pull DB at import time. Mitigated by docstring. |
| `scripts/maintenance/dump_cli_prompt.py` | 31 | Low | Resource | `with sqlite3.connect(db_path)` — but the connect is inside an `async def` and the underlying sync sqlite3 will block the event loop while inside the with-block. Acceptable for a one-shot dump. |
| `scripts/maintenance/dump_cli_prompt.py` | 96-100 | Low | Argparse | Manual sys.argv parsing instead of argparse. The `--full` flag is matched everywhere in argv, so `python dump_cli_prompt.py "--full something"` could be mis-parsed. Trivial. |
| `scripts/maintenance/dump_cli_prompt.py` | 79-81 | Good | Sensitive output | Default redacts the prompt body; `--full` required to print. Good practice for audit/sharing. |
| `scripts/maintenance/find_unused.py` | 13 | Low | Coverage | `EXCLUDE_DIRS = {..., "data"}` excludes data dir. Good. But also skips no test dirs (`tests/`, `tests_*` etc.). If tests import a module via dynamic import (string), the module is reported "unused". |
| `scripts/maintenance/find_unused.py` | 30-49 | Medium | Static analysis correctness | Regex-based import extraction misses: `__import__("foo")`, `importlib.import_module("foo")`, conditional `if x: import y`, dynamic cog loading via `bot.load_extension("cogs.x")`. The Discord.py extension loader uses string keys — half this codebase's cogs would be reported as "unused" without manual whitelisting. The script does not whitelist them. |
| `scripts/maintenance/find_unused.py` | 91-94 | Low | Hardcoded entry points | Only `bot.py` and `config.py` listed. `scripts/*` is skipped via the `rel_parts[0] == "scripts"` check. But `tools/` is also skipped — there is no `tools/` in this repo (verified). Dead branch. |
| `scripts/maintenance/find_unused.py` | 60-64 | Low | Performance | Nested loop `for var in variations: for pf in project_files:` — O(N×M). For 1000 files this is OK; gets sluggish past 10k. |
| `scripts/maintenance/inspect_dashboard_memories.py` | 6-7 | Low | Resource | `conn = sqlite3.connect(DB)` — never explicitly closed (relies on GC). Acceptable for a script but inconsistent with other scripts that use `with`. |
| `scripts/maintenance/inspect_dashboard_memories.py` | top-level | Low | Style | Same module-top-level execution issue as count_cli_sessions.py — importing this runs the queries. |
| `scripts/maintenance/inspect_db.py` | 3 | Medium | Path | `for db in ['data/bot_database.db', 'data/ai_cache_l2.db']:` — relative paths. CWD-dependent. |
| `scripts/maintenance/inspect_db.py` | 9 | Low | Exception | Bare `except Exception` swallows all errors with a one-line message. Should at minimum log the type. |
| `scripts/maintenance/migrate_to_db.py` | 23-27 | Good | CWD comment | Explicitly defers `os.chdir` to `main()`. |
| `scripts/maintenance/migrate_to_db.py` | 38-39 | Medium | Path | Inside `find_json_files()`: `data_dir = Path("data")` — runs AFTER `os.chdir(PROJECT_ROOT)` so it works, but the dependency on chdir is fragile. Should accept the path as parameter. |
| `scripts/maintenance/migrate_to_db.py` | 73-129 | Good | Partial-failure handling | Re-raises mid-migration so caller can detect partial failure and skip `--delete-json` for that file. Solid. |
| `scripts/maintenance/migrate_to_db.py` | 109-115 | Medium | Migration atomicity | `await db.save_ai_message(...)` is called per row WITHOUT an outer transaction. Each save commits independently; if the script crashes after row 50 of 100, the DB has 50 rows committed. The retry-on-rerun is partly handled by `db.save_ai_message` (presumably idempotent on `(message_id, channel_id)`), but this isn't verified or documented here. |
| `scripts/maintenance/migrate_to_db.py` | 152-162 | Medium | Backup | `create_backup()` does `shutil.copytree(data_dir, backup_dir)` — for a multi-GB data dir this duplicates everything including `data/tmp/`, `data/db_export/`, etc. No exclude filter. |
| `scripts/maintenance/migrate_to_db.py` | 159 | Low | Path | `backup_dir = Path(f"data_backup_{timestamp}")` — relative path created in CWD (which is PROJECT_ROOT after chdir). OK after chdir. |
| `scripts/maintenance/migrate_to_db.py` | 266-287 | High | Destructive / no extra confirm | `--delete-json` deletes source files after migration with NO confirmation prompt. The `--backup` flag is optional and not enforced when `--delete-json` is set. Operator could pass `--delete-json` alone and lose source data if migration is buggy. Should require `--backup` when `--delete-json` is used, or a `--yes-delete-json` confirmation. |
| `scripts/maintenance/migrate_to_db.py` | 271-275 | Low | Error swallowing | `try: filepath.unlink(); except OSError: pass` — silent. If unlink fails (e.g., file in use), user thinks it was deleted. |
| `scripts/maintenance/reindex_db.py` | 16 | Medium | Path | `DB_PATH = "data/bot_database.db"` — CWD-dependent. |
| `scripts/maintenance/reindex_db.py` | 36-45 | Good | WAL backup | Copies `-wal`/`-shm` siblings. |
| `scripts/maintenance/reindex_db.py` | 53-73 | Good | FK protection | Refuses to renumber if any other table FKs into ai_history. |
| `scripts/maintenance/reindex_db.py` | 130-179 | Good | Transaction wrapping | Explicit `BEGIN IMMEDIATE` + commit, with `BaseException` rollback. |
| `scripts/maintenance/reindex_db.py` | 134 | Medium | Concurrent access | `BEGIN IMMEDIATE` fails if another connection holds a lock. Script doesn't handle this gracefully — it propagates the error to the rollback handler. Should detect "database is locked" and tell the operator to stop the bot. |
| `scripts/maintenance/reindex_db.py` | 161 | High | Migration semantics | `ALTER TABLE ai_history_new RENAME TO ai_history` — but **this loses any FOREIGN KEYs that other tables had to ai_history.id**. The earlier FK check only refuses to run if FKs EXIST; it doesn't preserve them. After renumbering even with no FKs today, any code that cached `ai_history.id` (e.g., scheduled jobs, cache keys) silently points at wrong rows. Document this very loudly. |
| `scripts/maintenance/reindex_db.py` | 165-170 | Medium | Idempotency | Index recreation: if an index name collides with one that already exists (because `DROP TABLE ai_history` should have dropped the indexes... usually), it warns and continues. SQLite does drop attached indexes on table drop, so usually fine, but the warn-and-continue means partial failures slip past. |
| `scripts/maintenance/reindex_db.py` | 188-189 | Low | VACUUM | VACUUM happens after the commit but inside the same `async with aiosqlite.connect`. aiosqlite may have already closed the implicit transaction; comment says so. OK. |
| `scripts/maintenance/reindex_db.py` | 200-206 | Good | Confirmation | Requires literal "yes" before destructive op. |
| `scripts/maintenance/rollback_migration.py` | 53-55 | Low | Glob | `BACKUP_DIR.glob("bot_database_v*.db")` only matches that prefix. Auto-backups created by other tools (e.g., `bot_before_reindex_*.db`, `pre_rollback_*.db`) are silently invisible to `list`. The operator can't rollback to a renumber backup via this tool. |
| `scripts/maintenance/rollback_migration.py` | 107-123 | Good | Path traversal | Uses `is_relative_to` against resolved BACKUP_DIR — solid. |
| `scripts/maintenance/rollback_migration.py` | 184-190 | Good | Lock check | Refuses restore if `-wal`/`-shm` siblings are non-empty (suggests bot still running). |
| `scripts/maintenance/rollback_migration.py` | 199-206 | Medium | Atomicity | `shutil.copy2(backup, DB_PATH)` overwrites in place — NOT atomic. A crash mid-copy leaves a half-written DB and no original. Should copy to `DB_PATH.with_suffix(".db.tmp")` then `os.replace()`. The "safety snapshot" line above mitigates but doesn't eliminate. |
| `scripts/maintenance/rollback_migration.py` | 200-206 | Low | WAL cleanup | Removes `-wal`/`-shm` after restore — correct. But if `unlink` fails (warning printed) the next bot start will see a stale WAL and may corrupt state. Should be a hard error, not a warning. |
| `scripts/maintenance/rollback_migration.py` | 171-179 | Good | Confirmation | Defaults to interactive YES, supports `--yes` for scripted use. |
| `scripts/maintenance/schema_smoke.py` | 30 | Low | Hardcoded floor | `if len(tables) < 15: raise SystemExit` — magic number. Should track expected table count alongside migrations. |
| `scripts/maintenance/schema_smoke.py` | 31-34 | Medium | CWD restoration | `os.chdir(temp_dir)` then later `os.chdir(original_cwd)` in finally. If the script is interrupted between the two chdirs in a way that bypasses finally (e.g., os._exit), the parent shell is left in a deleted temp dir. Limited risk. |
| `scripts/maintenance/schema_smoke.py` | 30 | Low | Migration count | `expected_version = len(list((REPO_ROOT/"scripts/maintenance/migrations").glob("*.sql")))` — assumes every `.sql` is a numbered migration. A stray helper or notes file would inflate the count. |
| `scripts/maintenance/view_db.py` | 33-41 | Good | Whitelist | Imports `KNOWN_TABLES` and skips unknown tables — defense in depth even though source is `sqlite_master`. |
| `scripts/maintenance/view_db.py` | 41 | Low | f-string in SQL | `cursor.execute(f"SELECT * FROM [{table}]")` — table is whitelisted (good). The `[bracketed]` quoting protects against SQL keywords. |
| `scripts/maintenance/view_db.py` | 50-53 | Low | Memory | `data = [dict(row) for row in rows]` then `output_file.write_text(json.dumps(...))` — for a multi-GB table this OOMs. No streaming. |
| `scripts/shared/colors_fallback.py` | 41-50 | Low | Side effect on import | `enable_windows_ansi()` runs at import time. If the script is imported in an environment that doesn't want ANSI, you can't suppress this. Minor. |
| `scripts/verify_system.py` | 16-23 | Medium | BOM handling | Reads `path.read_bytes()` then strips UTF-8 BOM. Good. But files with UTF-16 BOMs would `decode("utf-8")` and raise. Not a Python file in real life. |
| `scripts/verify_system.py` | 35-81 | High | Side effects | `importlib.import_module(module_name)` — actually IMPORTS every module under cogs/. This means **side-effects fire**: DB connections, network calls, signal handlers, `bot.add_listener` (when called at module-top), etc. Running this script in production could mutate state, register duplicate listeners, hold open file handles, etc. The intent (syntax check) does NOT need a real import — `compile()` already covers it on line 23. Should remove the import phase or run it in a subprocess + temp DB. |
| `scripts/verify_system.py` | 44-46 | Medium | sys.path mutation | `sys.path.insert(0, project_root)` — no cleanup. After this script runs, `sys.path` is permanently altered for the importing process. Fine for a CLI but bites if someone imports `verify_system` into a long-running process. |
| `scripts/verify_system.py` | 86 | Medium | CWD-dependent | `root_dir = Path.cwd()` — the entire script's behavior depends on CWD. If invoked from a subfolder the syntax check examines the wrong tree. Should anchor to `Path(__file__).parent.parent`. |
| `scripts/verify_system.py` | 70-71 | Low | Error swallowing | `if "attempted relative import" in str(e):` — string match against exception messages is fragile across Python versions. |
| `native_dashboard/scripts/create_desktop_shortcut.py` | 41-42 | Low | Idempotency | Removes existing `.lnk` then recreates. If the user has a customized shortcut, it's silently overwritten. No backup of the old shortcut. |
| `native_dashboard/scripts/create_desktop_shortcut.py` | 31-33 | Medium | UX | `if not exe_path.exists(): print("ERROR: Exe not found!"); return False` — the message doesn't say WHERE it looked. Operator running this before the Rust build is unhelpful. Should print `exe_path` in the error. |
| `native_dashboard/scripts/create_desktop_shortcut.py` | 5-12 | Low | Import | `pythoncom` and `win32com.shell` are only imported inside the function — fine, but the function name `create_shortcut_via_pythoncom` advertises an implementation detail in the public API. |
| `native_dashboard/scripts/create_desktop_shortcut.py` | 14 | Low | Hardcoded name | Korean shortcut name `"디스코드 봇 대시보드"` hardcoded; no English fallback or i18n hook. If the user has no Korean fonts installed the desktop icon may render boxes. |
| `native_dashboard/scripts/create_desktop_shortcut.py` | top | Medium | No argparse | No flags. Always installs to `Path.home() / "Desktop"` — fails on Windows where Desktop is OneDrive-redirected (`%USERPROFILE%\OneDrive\Desktop`). Should use Win32 SHGetKnownFolderPath. |

---

## Notes / Cross-cutting

### Destructive scripts inventory (sorted by risk)

| Script | Destructive op | Confirms? | Backup? | Atomicity? |
|---|---|---|---|---|
| `bot_manager.py` (kill_all) | Kills all matching processes | "yes" prompt | No | N/A |
| `bot_manager.py` (auto_stop_existing_bot) | Kills running bot on every `start_bot` | **NO** | No | N/A |
| `dev_watcher.py` (check_and_stop_existing_bot) | Kills bot at startup | **NO** | No | N/A |
| `clean_cli_orphans.py` | Unlink + rmtree session files | `--apply` requires interactive `yes` (or `--yes`) | No | rmtree non-atomic |
| `clean_history.py` | Mutates JSON files | **NO** | `.bak` sidecar (overwritten on rerun) | Atomic via tmp+replace |
| `convert_log015.py` | Rewrites .py files | **NO** | No (syntax-checks first) | **Non-atomic write** |
| `add_local_id.py` | Schema change + UPDATE | "yes" prompt + `--force` | shutil.copy2 (no WAL) | **No transaction** |
| `migrate_to_db.py` | INSERTs + optional file deletion | NO confirm; `--delete-json` flag | `--backup` flag (optional) | Per-row commits |
| `reindex_db.py` | DROP+RENAME table | "yes" prompt | shutil.copy2 + WAL/SHM | Wrapped in BEGIN IMMEDIATE |
| `rollback_migration.py` (restore) | Overwrite live DB | YES prompt + `--yes` | "pre_rollback_*.db" snapshot | **shutil.copy2 not atomic** |

**The biggest gap**: `bot_manager.start_bot()` and `dev_watcher` both kill running bots without ever asking. For a developer this is fine; for a production-deployed bot supervisor this risks downtime from a misclick.

### Windows-only assumptions

- `bot_manager.py` heavily branches on `sys.platform == "win32"` for clear-screen, signals, `wscript`, and `os.startfile`. Posix paths are present but UNTESTED in this codebase given the project lives on Windows (per CLAUDE.md auto-memory).
- `dev_watcher.py` uses `PollingObserver` on Windows (necessary for SMB shares but inefficient on local NTFS). For local dev, `watchfiles` would be ~10× faster.
- `bot_manager.py` line 602: invokes `wscript` via PATH — fragile.
- `create_desktop_shortcut.py` is Windows-only by design.

### POSIX-only assumptions

- `bot_manager.py:540` — SIGINT graceful shutdown only on POSIX. The Windows path skips straight to `terminate()`.
- `dev_watcher.py:836` — SIGTERM handler only registered on POSIX. Operators using `taskkill /F /T` get no graceful path.

### Process orphans on Windows

- `dev_watcher.py` launches the bot with `CREATE_NEW_PROCESS_GROUP` but does NOT use a Job Object. If the watcher itself dies (e.g., killed by Task Manager, OOM), the bot child is orphaned. Recommended: associate the child with a Job Object configured with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` so the OS reaps it automatically. (See [Nikhil — Windows Job Objects for Process Tree Management](https://nikhilism.com/post/2017/windows-job-objects-process-tree-management/).)
- `bot_manager.py` uses `os.startfile()` for Windows non-hidden launch — completely detaches the child from the parent, no cleanup possible.

### Path handling — pervasive CWD-dependence

Multiple maintenance scripts use bare relative `Path("data/...")`. This is a project-wide pattern (every script chdir's to PROJECT_ROOT in main()) that mostly works, but is fragile. A consistent helper:

```python
PROJECT_ROOT = Path(__file__).resolve().parents[N]
DB_PATH = PROJECT_ROOT / "data" / "bot_database.db"
```

is used in some scripts (rollback, schema_smoke, dump_cli_prompt) but not others (add_local_id, check_db, inspect_db, clean_history, view_db's data/db_export). Inconsistent — should be standardized.

### Migration safety summary

- `add_local_id.py` — **no transaction wrapping**. High-risk for partial application.
- `migrate_to_db.py` — per-row commits; relies on idempotent inserts (verify `db.save_ai_message`).
- `reindex_db.py` — properly wrapped in `BEGIN IMMEDIATE`. Best-in-class.
- `rollback_migration.py` — restore uses `shutil.copy2` over live file (non-atomic).
- No applied-only-once tracking in any maintenance script. The actual migration runner (in `utils/database/`, out of scope) handles `schema_version`; these are one-shot historical migrations that predate that system. They should arguably be ARCHIVED, not kept executable.

### Subprocess hygiene

- No `shell=True` anywhere. Good.
- All subprocess args are lists. Good.
- Missing timeouts: `subprocess.Popen(..., creationflags=...)` for the bot child (intentional — long-running), but `subprocess.run(["cmd","/c","cls"])` and `subprocess.Popen(["wscript", ...])` have no timeout. The clear-screen one is fine; the wscript one could hang.

### Argparse coverage

- `bot_manager.py`: no argparse, interactive menu only. OK for design.
- `dev_watcher.py`: no argparse — config is JSON file + env vars. Could benefit from `--debug`, `--verbose` flags.
- `load_test.py`: argparse with reasonable defaults but no upper bounds.
- `add_local_id.py`: `--force` is checked via `if "--force" in sys.argv`, not argparse. Inconsistent.
- `clean_cli_orphans.py`: `--apply`, `--yes` checked via `in sys.argv`. Same.
- `convert_log015.py`: no argparse, stdin only.
- `dump_cli_prompt.py`: manual sys.argv parsing.
- `migrate_to_db.py`: full argparse. Good.
- `reindex_db.py`: no argparse — interactive prompt only.
- `rollback_migration.py`: full argparse with subcommands. Best-in-class.

### Dead / stale

- `find_unused.py:116` — `tools/` exclusion branch but no `tools/` dir in the project.
- `find_unused.py` overall — without dynamic-import awareness (Discord cog loading, `importlib.import_module`), any "unused" report is unreliable.
- `count_cli_sessions.py:104` — `data` referenced when sidecar may not exist → NameError at module level.
- `verify_system.py` — the `check_imports()` step is dangerous (side effects); the `check_syntax()` step alone provides 90% of the value.

### Quality observations

- `bot_manager.py` 876 lines is too large. The Colors fallback (40 lines), emoji ranges table (60 lines), display-width logic (60 lines), and box-drawing helpers (40 lines) belong in `scripts/shared/`.
- `dev_watcher.py` 907 lines duplicates the same Colors fallback. Both files should pull from `scripts/shared/colors_fallback.py` only (and the import-or-fallback dance can shrink).
- Many scripts re-implement "find python files" and "compile-check": `verify_system.py`, `find_unused.py`, `convert_log015.py`. A shared `scripts/shared/python_files.py` would dedupe.

---

## Confirmation

Every line of every assigned file was read in full. Findings are grouped by file with line refs and severity. The destructive-scripts table summarizes the highest-risk areas. No code was modified during this audit.

### Sources consulted
- [Python Subprocess docs (CREATE_NEW_PROCESS_GROUP, Popen)](https://docs.python.org/3/library/subprocess.html)
- [Nikhil — Using Windows Job Objects for Process Tree Management](https://nikhilism.com/post/2017/windows-job-objects-process-tree-management/)
- [Watchdog vs Watchfiles comparison (PipTrends)](https://piptrends.com/compare/watchdog-vs-watchfiles)
- [Watchfiles migration notes (Notify Rust library)](https://watchfiles.helpmanual.io/migrating/)
- [Simple declarative SQLite migrations — David Rothlis](https://david.rothlis.net/declarative-schema-migration-for-sqlite/)
- [SQLite Versioning and Migration Strategies](https://www.sqliteforum.com/p/sqlite-versioning-and-migration-strategies)
