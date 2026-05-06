# G12: Native Dashboard (Rust + TypeScript) — Audit Report

Auditor pass: every assigned file read in full (chat-manager.ts in 4 chunks). External cross-reference for current Tauri 2 capability semantics and DOMPurify CVEs (May 2026 cycle) was performed.

## Files Reviewed

| Path | LOC | Notes |
|---|---:|---|
| `native_dashboard/build.rs` | 20 | comment-only, calls `tauri_build::build()` |
| `native_dashboard/src/lib.rs` | 2 | re-exports `bot_manager` + `database` |
| `native_dashboard/src/main.rs` | 866 | Tauri app entry — 26 commands, tray, dialog, telemetry flag |
| `native_dashboard/src/bot_manager.rs` | 610 | Windows-only; manages bot subprocess + dev_watcher |
| `native_dashboard/src/database.rs` | 374 | rusqlite cache + dashboard conversation reads |
| `native_dashboard/tauri.conf.json` | 39 | CSP, single window, `withGlobalTauri:true`, `dragDropEnabled:false` |
| `native_dashboard/capabilities/default.json` | 14 | `core:default`, dialog perms, deny-internal-toggle-devtools |
| `native_dashboard/playwright.config.ts` | 50 | Python http.server on 5173 |
| `native_dashboard/vitest.config.ts` | 15 | jsdom env |
| `native_dashboard/src-ts/app.ts` | 1896 | UI shell, charts, sakura, settings, avatar crop, API failover |
| `native_dashboard/src-ts/chat-manager.ts` | 2743 | WS msg dispatch, streaming, edits, files, drafts |
| `native_dashboard/src-ts/chat/context-window.ts` | 106 | token bar + LRU localStorage |
| `native_dashboard/src-ts/chat/conversation-list.ts` | 194 | sidebar render + tag chips |
| `native_dashboard/src-ts/chat/conversation-modals.ts` | 123 | rename / delete confirm |
| `native_dashboard/src-ts/chat/document-attach.ts` | 228 | PDF + text attach manager |
| `native_dashboard/src-ts/chat/export-picker.ts` | 97 | format chooser modal |
| `native_dashboard/src-ts/chat/formatter.ts` | 263 | markdown → sanitized HTML, KaTeX, fenced code |
| `native_dashboard/src-ts/chat/image-attach.ts` | 245 | base64 picker / drag / paste |
| `native_dashboard/src-ts/chat/message-template.ts` | 233 | virtualized message HTML builder |
| `native_dashboard/src-ts/chat/prism.ts` | 107 | lazy syntax loader |
| `native_dashboard/src-ts/chat/search.ts` | 184 | Ctrl+F overlay |
| `native_dashboard/src-ts/chat/types.ts` | 53 | shared chat types |
| `native_dashboard/src-ts/chat/ws-client.ts` | 316 | WS lifecycle, reconnect, ping/pong |
| `native_dashboard/src-ts/faust_avatar.ts` | 1 | base64 default avatar |
| `native_dashboard/src-ts/shared.ts` | 678 | Tauri invoke wrap, settings, toast, error logger, 3D polish |
| `native_dashboard/src-ts/types.ts` | 63 | shared type defs |

Total assigned LOC reviewed: ~9.5k.

## Issues Found

Severity scale: **CRIT** = exploitable / data-loss, **HIGH** = security weakness w/ partial mitigation, **MED** = bug / DoS / quality risk, **LOW** = polish / dead code / style.

| File | Line(s) | Severity | Category | Description |
|---|---|---|---|---|
| `ui/vendor/dompurify/purify.min.js` | banner | **CRIT** | Vulnerable dependency | Bundled DOMPurify is **3.3.3** (confirmed via license banner). [CVE-2026-41238](https://labs.trace37.com/blog/dompurify-pp-ceh-bypass/) (prototype-pollution → XSS gadget) covers 3.0.1–3.3.3 in default config; [CVE-2026-0540](https://www.ibm.com/support/pages/security-bulletin-carbon-chart-dompurify-xss-vulnerabilities-cve-2025-15599-cve-2026-0540) covers 3.1.3–3.3.1. Combined with the formatter's reliance on DOMPurify as the *only* sanitizer for AI-generated markdown, an attacker that can inject prototype pollution anywhere on `window` (third-party script, future plugin, malicious server frame parsed via `JSON.parse` without `Object.create(null)`) can bypass the whitelist. **Action:** upgrade to ≥3.3.4, and consider passing `Object.create(null)` configs. |
| `tauri.conf.json` | 9, 25 | **HIGH** | CSP / IPC surface | `withGlobalTauri: true` exposes `window.__TAURI__` to every script context. The CSP has `script-src 'self'` with **no `'strict-dynamic'`** and (correctly) no `'unsafe-inline'`, but ALL bundled scripts (Prism, KaTeX, DOMPurify) get full IPC access. There is no nonce-based or hash-based CSP; if a vendor file is ever swapped for a malicious copy or a same-origin XSS lands, all 26 invoke handlers (including `delete_channels_history`, `clear_history`, `start_bot`) are reachable. Mitigation: keep DOMPurify current, lock vendor bundles via SRI, or pin them via integrity. |
| `tauri.conf.json` | 25 | **HIGH** | CSP / WebSocket allowlist | `connect-src` allows `ws://localhost:* ws://127.0.0.1:*` plus `wss:` variants on **any port**. A malicious local listener on a high port could pose as the dashboard backend after the user starts the app. The bot defaults to 8765; tightening to `ws://127.0.0.1:8765 wss://127.0.0.1:8765` (or whatever `WS_DASHBOARD_PORT` resolves to at build time) would shrink that surface. |
| `capabilities/default.json` | 6–13 | **HIGH** | Capability scope | `core:default` is requested as-is. Per Tauri 2 docs ([Core Permissions](https://v2.tauri.app/reference/acl/core-permissions/)), `core:default` is a **broad** convenience set — it pulls in event/window/path/menu/etc. The dashboard only needs window-show / window-set-focus / event listen / a small set; the rest is unused IPC surface. Replace with `core:event:default`, `core:window:allow-show`, `core:window:allow-set-focus`, `core:webview:deny-internal-toggle-devtools`, and the dialog perms. |
| `tauri.conf.json` | 20 | LOW | DX gap | `"devtools": false` for prod is correct, but combined with the no-CSP-violations errata above means there is no in-app way to inspect why an XSS payload was blocked — only the `dashboard_errors.log` shows it. Consider gating devtools behind a debug build instead of permanent off. |
| `src/main.rs` | 198–206 | MED | Tauri command — UX/blocking | `show_confirm_dialog` uses `.blocking_show()` synchronously inside a `#[tauri::command]`. The handler is sync (no `async fn`), so this blocks a Tauri worker thread for the entire dialog lifetime. Most of the rest of the file moves heavy work into `spawn_blocking`; this one didn't. Convert to async + the non-blocking `.show(callback)` pattern used by the close-window handler at line 715. |
| `src/main.rs` | 277–283 | MED | TOCTOU | `open_folder` does `canonicalize()` + `starts_with(base_path)` then spawns explorer.exe with the canonicalized path. The comment acknowledges the TOCTOU window. On a multi-user box this lets a local attacker swap a directory for a symlink between check and spawn. Threat model is local-only and the user could navigate manually, but worth pinning by passing the **canonical absolute path** (already done) AND opening with `OpenProcessTokenAndDuplicate`-style verified parent — or simpler, refuse the request if `symlink_metadata` of any ancestor of `canonical` reports a link. |
| `src/main.rs` | 198–206 | MED | Reentrancy | `show_confirm_dialog` uses `app.dialog().…blocking_show()` from a Tauri command. `blocking_show` from a synchronous command in v2 is documented to deadlock under some conditions if the dialog is called while another modal is up. The `showConfirmDialog` wrapper in `shared.ts` has a `confirm()` fallback, so the deadlock would surface as a stuck UI rather than data loss, but this is still a footgun. |
| `src/main.rs` | 198 | MED | i18n | The "Confirm" / "Yes" / "No" labels in `show_confirm_dialog` are English while the rest of the UI is Thai. Inconsistent with the close-confirm at lines 711–714 (Thai). Trivial. |
| `src/main.rs` | 209–223 | LOW | Input validation | `delete_channels_history` parses each ID as `i64` — fine. But the cap of 100 channels is enforced *before* the parse loop; an attacker that sends 100 IDs of which one fails to parse gets a partial-progress error message that leaks the offending ID. Low impact (caller controls those IDs already). |
| `src/main.rs` | 311–313 | LOW | Log injection | Newline / U+2028 / U+2029 stripping is good; consider also stripping U+0085 (NEL). Length cap is fine. |
| `src/main.rs` | 358–363 | MED | Telemetry leak | When Sentry is enabled, **frontend error type + message** are forwarded raw. A buggy/abusive frontend (or any markdown content that happened to land in `console.error`) can ship arbitrary user content (chat messages, file paths, even DB rows from `console.error('Server error:', data.message)` at chat-manager.ts L786) to `*.sentry.io`. Add scrubbing or feature-flag this off until a redaction layer exists. The DSN is allowlisted to `.sentry.io` (good), but the *content* is not filtered. |
| `src/main.rs` | 451–502 | LOW | Env loading | `read_dotenv_value` does not handle quoted values with **embedded** quotes (`KEY="abc\"def"`) or `KEY='it\'s'`. Falls back to env var which is usually fine. |
| `src/main.rs` | 538–580 | LOW | Path discovery | `resolve_production_base_path` walks `~/BOT`, `~/bot`, `~/Desktop/BOT`, `~/Documents/BOT`. If the user has an unrelated folder named `BOT` containing a stray `bot.py`, the dashboard will quietly target it. Consider matching on a sentinel file (`.bot_dashboard_anchor`) instead of bare `bot.py`. |
| `src/main.rs` | 624–629 | LOW | DSN validation | `host_part.ends_with(".sentry.io") || host_part.ends_with(".sentry.io:")` lets `evil.sentry.io.attacker.com` through if a `:port` is appended? No — `ends_with` is a literal suffix match, so `…attacker.com` would not match. ✅ but still the `.ends_with(":")` form is unusual; verify it doesn't allow `https://attacker.com.sentry.io:1234/foo` — the `nth(2).split('@').next_back()` extraction grabs the host portion correctly. **OK as-is.** |
| `src/main.rs` | 644–646 | MED | Mutex contention | `bot_manager` is wrapped in `Arc<Mutex<…>>`, `db_service` in `Mutex<…>`. Several commands (`get_status`, `get_logs`) `try_lock` and gracefully degrade, but `get_db_stats` / `get_recent_channels` / etc. acquire blocking locks on the synchronous DB mutex from the Tauri runtime worker, so a 1s+ slow query stalls every other DB read. Move DB reads into `spawn_blocking` like start/stop/restart already do, OR switch to a connection pool (`r2d2_sqlite`). |
| `src/main.rs` | 755–758 | LOW | Panic | `tauri::generate_context!()` then `unwrap_or_else(\|e\| exit(1))` — fine, but `eprintln!` won't reach the user (no console window in `windows_subsystem = "windows"`). Surface via `MessageDialogKind::Error` before exit. |
| `src/bot_manager.rs` | 142–186 | MED | Process kill heuristic | `kill_orphan_bot_processes` matches on `basename == "bot.py"` and `name.contains("python")`. False positive risk: a **user** running an unrelated `python … some/bot.py` (a common script name) on the same machine gets killed by the dashboard. The "test_" exception only catches names starting with `test_`. Consider matching on the **full canonical script path** == `self.base_path.join("bot.py")`. |
| `src/bot_manager.rs` | 432–488 | MED | Race / pid file | `start()` removes the PID file then spawns Python. Python writes its own PID file once it boots. The 10s polling loop checks `pid_file().exists() && self.is_running()`. If the bot writes its PID then crashes before the next poll, `is_running()` returns false but the PID file is stale → the next poll sees neither, returns "Bot process exited". OK. **But** there is no guard against TOCTOU on `pid_file().exists()` followed by `is_running()` — the bot could be midway through a self-restart and rewrite the PID. Not exploitable, just confusing logs. |
| `src/bot_manager.rs` | 459–460 | MED | Child handle leak fix is correct, BUT… | `drop(child)` releases the Windows handle. Subsequent `is_running()` polls rely on the bot writing `bot.pid` — there's no fallback for "bot was launched, never wrote PID". The 10s poll catches this; good. |
| `src/bot_manager.rs` | 501–540 | MED | Dev watcher PID race | `start_dev()` writes `dev_watcher.pid` AFTER spawning. If the dashboard process is killed in that 1-µs window, the watcher orphans. `kill_orphan_bot_processes` only finds `bot.py` processes, not `dev_watcher.py`. Add `dev_watcher.py` and `self_healer.py` to a kill-orphan equivalent at startup. |
| `src/bot_manager.rs` | 542–589 | MED | Stop ordering | `stop()` checks PID then refreshes processes. If PID was reused between the file-read and the refresh, we'd kill a new Python process. The `name.contains("python")` check at line 553 catches the PID-belongs-to-Python case but not "PID belongs to my OWN dashboard if it happens to be named python.exe" — irrelevant on Windows but worth noting. |
| `src/bot_manager.rs` | 568–571 | LOW | Force kill | `taskkill /F /T` does an unconditional force-kill with no graceful shutdown signal. The Python bot has no opportunity to flush logs or close DB connections cleanly. Consider sending CTRL_BREAK_EVENT first (via `GenerateConsoleCtrlEvent`), wait 2s, then `/F`. |
| `src/bot_manager.rs` | 156 | LOW | Allocation | `cmd.iter().map(\|s\| s.to_string_lossy().to_lowercase().to_string())` runs on every process every refresh. With sysinfo reporting 200+ processes that's 200 lowercased clones per call. Cache or short-circuit on `name.contains("python")`. |
| `src/bot_manager.rs` | 39 | LOW | Memory growth | `sys: System` is held for the lifetime of `BotManager`, and `refresh_processes(All, true)` is called on every status update. sysinfo's `System` retains internal caches. Consider `System::new()` on demand or `refresh_processes(Some(&[pid]), …)` for the targeted lookups. |
| `src/database.rs` | 80 | LOW | `expect()` panic | `ConnectionGuard::conn()` panics with "ConnectionGuard used after take" — only reachable via internal misuse, but the panic occurs inside a Tauri command and would crash the worker thread. Convert to returning `Option<&Connection>` or `Result`. |
| `src/database.rs` | 110–113 | LOW | Mutex poisoning | `lock().unwrap_or_else(\|poisoned\| poisoned.into_inner())` silently recovers from a panic-poisoned mutex, but the connection may be in an inconsistent state (transaction half-rolled-back). Rebuild the connection on poison instead. |
| `src/database.rs` | 116 | LOW | `SELECT 1` waste | The cached connection is validated with `conn.execute("SELECT 1", [])` on every borrow. SQLite never closes a local file handle unexpectedly — this validation costs a few µs per command. Consider only validating after a write error. |
| `src/database.rs` | 134–138, 144–148, 152–158, 178–186, 207–214 | LOW | Silent error swallow | All read paths use `if let Ok(_) = conn.query_row(…) {…}` — when the query fails, the result is silently zero. A schema drift would render the dashboard's stat tiles as zeros with no log. At minimum log the rusqlite error. |
| `src/database.rs` | 263–276 | MED | Fixed query string + `WHERE c.id = ?` | The query interpolates nothing user-controlled; bound params are used. ✅ Confirmed parameterized. |
| `src/database.rs` | 244 | MED | Dynamic query | `format!("DELETE FROM ai_history WHERE channel_id IN ({})", placeholders.join(","))` builds a placeholder list whose **count** is user-controlled (capped at 100 in main.rs). Values are still bound. ✅ Safe. |
| `src/database.rs` | 351 | LOW | JSON parse trust | `images_json` from the DB is parsed via `serde_json::from_str::<Vec<String>>(raw).ok()` — silently drops malformed JSON. Acceptable but should at least log. |
| `src-ts/shared.ts` | 86–106 | MED | console.error wrap | `setupGlobalErrorHandlers` re-wraps `console.error`. The constructor is private and the singleton guard prevents double-wrap *in the same module-instance*, BUT if `shared.ts` is imported from two distinct module graphs (e.g. main bundle + a worker bundle) each gets its own `ErrorLogger.instance` and re-wraps `console.error`. The original ref is captured per call, so back-to-back wraps cause the call to ping-pong via mutual capture, eventually leading to **infinite recursion** when an error occurs inside the wrap. Tauri's WebView2 only loads one bundle so this is theoretical, but still worth a global flag (`if ((console as any)._dashboardWrapped) return`). |
| `src-ts/shared.ts` | 165–169 | LOW | Triple-escape | `escapeHtml` does `textContent` then **also** replaces `"`, `'`, `` ` ``. The `textContent` write already escapes `<`, `>`, `&`. Defensive triple-escape is fine; redundant `'` escape (not needed if you only ever use double-quoted attrs — but defensive is the right call). |
| `src-ts/shared.ts` | 179–193 | LOW | Avatar URL allowlist | Allows `http://`. For a desktop app where settings are locally controlled this is OK, but a malicious server-pushed `aiAvatar` (via `profile` WS message) could write to localStorage, then on next load fetch a tracking pixel. Consider denying `http:` (only `https:` + `data:image/`). |
| `src-ts/shared.ts` | 211–224 | LOW | Settings | Default `userName: 'You'` written to localStorage. The `loadSettings` migration at 230–238 keeps the embedded Faust avatar — fine. |
| `src-ts/shared.ts` | 244–265 | LOW | Quota retry | On `QuotaExceededError` the function clears avatars and retries — silent, surfaces a toast. Good. The `e.code === 22` check is non-portable across browsers. |
| `src-ts/shared.ts` | 449–470 | MED | MutationObserver scope | Scopes the observer to `#role-cards-container` ‖ `#main-content` ‖ `body`. If both elements are missing at init time the observer falls back to body and the comment warns about CPU waste. The `disconnect` fires on `beforeunload` only — single-page reloads don't unbind. Minor. |
| `src-ts/shared.ts` | 511–520 | LOW | Pointer move handler | `setupSakuraParallax` registers a `pointermove` handler on `window` but **never removes** it. With `passive: true` it's cheap, but it survives for the page lifetime. |
| `src-ts/app.ts` | 48 | LOW | Map iteration | `cache.keys().next().value` is the insertion order in modern JS — fine, but documenting "FIFO" vs claiming "oldest" would clarify (LRU would need to re-insert on get). |
| `src-ts/app.ts` | 297–299 | LOW | Window resize debounce | Debounce of 250ms is reasonable; debouncer never cleans up its internal `setTimeout`. The Map (`debounceTimers`) holds the latest timer id but never clears entries when the page unloads. |
| `src-ts/app.ts` | 372–374 | LOW | Color regex | `color.replace(/,\s*[\d.]+\)$/, ', 0.3)')` breaks if the color is `rgb(…)` (no alpha). Currently only `rgba(…)` colors are passed, so this is safe — fragile if extended. |
| `src-ts/app.ts` | 444 | LOW | innerHTML clear | `c.innerHTML = ''` to clear sakura container — fine. Could use `replaceChildren()` for symmetry. |
| `src-ts/app.ts` | 463–467 | LOW | Inline SVG | The petal `<svg>` strings are literal constants — no XSS. But they're injected via `petal.innerHTML = shape;` (line 518). DOMPurify is **not** applied here. Since `shape` comes from a hardcoded array, this is safe today; if anyone ever drives shape from runtime data, it becomes XSS. |
| `src-ts/app.ts` | 533 | LOW | CSS animation name | `animation: sakuraFall${Math.floor(Math.random() * 3)}` — assumes `sakuraFall0/1/2` exist in CSS. If only 2 keyframes are defined the third sometimes silently no-ops. |
| `src-ts/app.ts` | 1022 | LOW | innerHTML overwrite | `container.innerHTML = ''` then `appendChild(fragment)` — fine, but `replaceChildren(fragment)` would be one paint instead of two. |
| `src-ts/app.ts` | 1067–1070 | LOW | clearLogs | Calls `invoke('clear_logs')` and `setSkeleton` — fine. |
| `src-ts/app.ts` | 1122, 1175, 1190 | LOW | innerHTML on data items | Channels/users lists use `appendChild` for individual items but `innerHTML = '<p class="no-data">…</p>'` for empty state. Static literals — safe. |
| `src-ts/app.ts` | 1340, 1674, 1692 | LOW | Inline base64 GIF | 1×1 transparent GIF used to defuse broken-image fallback — three near-identical occurrences; extract to a constant. |
| `src-ts/app.ts` | 1456–1471 | MED | Crop modal listener leak | `setupCropEventListeners` clones the crop area `parentNode?.replaceChild(newCropArea, cropArea)` to drop old listeners, then re-adds `mousemove`/`touchmove`/`mouseup`/`touchend` to **document**. `closeCropModal` removes them, BUT `openCropModal` is called once at init (from line 121's `setupCropEventListeners()`) AND again on every avatar upload (line 1442). Each open registers fresh `boundOnDrag`/etc. and overwrites the stored refs without removing the previous ones. Net: one set of stale handlers leaks per upload session. `boundOnDrag` is a single global so the *named* handlers are correctly removed, but the `mousedown`/`touchstart` listeners on the cloned `newCropArea` are added every time without cleanup of the old `cropArea`'s — though `replaceChild` drops the old node so its listeners die with it. Net effect is mild; documented but messy. |
| `src-ts/app.ts` | 1492–1500 | LOW | Modal click handler | `modal.onclick = (e) => { if (e.target === modal) closeCropModal(); }` overwrites any prior onclick. The dataset.overlayCloseBound flag protects the `.modal-overlay` listener from stacking but not `modal.onclick`. Fine — assignment, not addEventListener. |
| `src-ts/app.ts` | 1506–1511 | MED | Escape key listener leak | `document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && modal.classList.contains('active')) closeCropModal(); })` is registered with **no remove handle**. The `modal.dataset.escBound = '1'` flag prevents stacking *within the same modal element*, but the listener stays bound for the page lifetime even when the modal is closed. Cheap on memory, runs `classList.contains('active')` on every keystroke forever. |
| `src-ts/app.ts` | 1597 | LOW | Avatar size | `canvas.toDataURL('image/png')` at 200×200 — PNGs run ~50–100KB, fits localStorage. ✅ |
| `src-ts/app.ts` | 1814–1850 | MED | innerHTML with WS data | `renderApiFailoverUI` builds endpoint cards with `escapeHtml(epLabel)` and number-coerced fields. **However** line 1834 has `${ep.active ? 'ACTIVE' : (ep.healthy ? 'standby' : 'down')}` and line 1832 has `${ep.active ? '✅ ' : ''}${escapeHtml(epLabel)}` — `ep.active` is used as a truthy/falsy in a template, so a server sending `ep.active = "><script>"` would still produce only `'✅ '` or `''` — not exploitable. ✅ Numeric coercions look correct after the recent fix. |
| `src-ts/app.ts` | 1864–1877 | LOW | Same pattern as above for `renderHealthCheckResults` — values escaped or coerced. ✅ |
| `src-ts/chat-manager.ts` | 211–232 | LOW | Memory render template | Memory cards use `escapeHtml(memory.content)` and `escapeHtml(memory.category)`. ✅ |
| `src-ts/chat-manager.ts` | 248–267 | LOW | formatTime fallback | Returns `escapeHtml(isoString)` on parse failure — good defensive. Also returns `''` on outer catch in `chat-manager` formatter at L1905, which is fine (rendered as empty span). |
| `src-ts/chat-manager.ts` | 343 | LOW | localStorage typed-as-bool | `localStorage.getItem('dashboard_thinking') === 'true'` — fine. |
| `src-ts/chat-manager.ts` | 451–474 | LOW | `connected` handler | Server may send arbitrary `presets` object. Stored as `Record<string, RolePreset>` then later interpolated into `escapeHtml(preset.emoji)` — safe. |
| `src-ts/chat-manager.ts` | 696, 745, 759, 769 | MED | switch/case lexical leak | `case 'conversation_starred': const conv = …` declares `const` inside a `case` without a block. `case 'message_pinned'`, `'message_liked'` use `{ … }` blocks — inconsistent. The bare `const` works in TS but bleeds into the switch's lexical scope; if a future `case` redeclares it the compiler complains. Trivial. |
| `src-ts/chat-manager.ts` | 1224 | LOW | Mode escape | `<span class="message-mode">${escapeHtml(mode)}</span>` — ✅ |
| `src-ts/chat-manager.ts` | 1227–1228 | LOW | safeAi already escaped | `<img src="${safeAi}">` — `safeAvatarUrl` already returns escaped — ✅ |
| `src-ts/chat-manager.ts` | 1290 | MED | innerHTML formatMessage | `thinkingContent.innerHTML = this.formatMessage(fullThinking)` — `formatMessage` runs DOMPurify. Trust transitive. **If DOMPurify is bypassed** (see CRIT row above), this is the closest attacker-controlled XSS sink: `fullThinking` flows from the server's WS frame. |
| `src-ts/chat-manager.ts` | 1331 | MED | innerHTML formatMessage | Same risk surface as above — `content.innerHTML = this.formatMessage(this.stripThinkTags(fullResponse))`. |
| `src-ts/chat-manager.ts` | 1345 | MED | Copy button data attribute | `data-content="${escapeHtml(fullResponse)}"` — `fullResponse` is the AI's full reply. Up to 50MB string fits but balloons DOM. Embedding the full response in an HTML attribute on every message multiplies memory. Bigger sin: the `textarea.innerHTML = contentAttr` round-trip at line 1355 to "decode" via `textarea.value` is a clever-but-fragile XSS surface — relies on browsers not parsing attribute-encoded entities as live HTML. **Confirmed safe** in current browsers because `<textarea>` is rawtext, but it's fragile. Use `htmlDecodeRaw` via `DOMParser('text/html')` instead. |
| `src-ts/chat-manager.ts` | 1538–1546 | LOW | window.open new tab | `window.open('', '_blank')` for the image preview popup. **No `noopener,noreferrer`** specified — but the second arg is the window name and the third (features) is omitted, so by default modern browsers treat target=_blank as opener-isolated only via a feature flag. In a Tauri WebView this opens a Tauri webview window which has limited interaction with the parent. Low risk in this env, would be HIGH in a regular browser. |
| `src-ts/chat-manager.ts` | 1539 | LOW | Inline style in popup | `style.textContent = 'body{margin:0;…}'` — safe; CSS only. |
| `src-ts/chat-manager.ts` | 1554, 1564 | MED | Decode-via-textarea XSS gadget | Several copy handlers do `textarea.innerHTML = encoded; const decoded = textarea.value;` to round-trip HTML entities. This pattern is **known-safe** for `<textarea>` (rawtext element), but it's a footgun: change the wrapper element to anything else and it becomes XSS. Add a comment + helper. |
| `src-ts/chat-manager.ts` | 1739–1741 | LOW | Title interpolation | `titleEl.textContent = …` — ✅ uses textContent. |
| `src-ts/chat-manager.ts` | 1899–1904 | LOW | Locale | Hard-coded `'th-TH'` — intentional per project. |
| `src-ts/chat-manager.ts` | 2001–2024 | MED | Files modal innerHTML | `list.innerHTML = docs.map(d => …).join('')` — `escapeHtml(d.filename)`, `escapeHtml(meta)`. Server-controlled fields (`d.id`, `d.char_count`, `d.page_count`, `d.file_kind`) are coerced to `Number` or `String` then escaped. ✅ Looks correct after the earlier hardening. |
| `src-ts/chat-manager.ts` | 2174 | MED | Selector with template literal | `document.querySelector(\`.chat-file-row[data-id="${id}"]\`)` — `id` is `number` typed but at runtime is a JS value. If a malicious server sent a non-numeric `id` containing `"]:has(…)`, it could form a CSS injection. Use `[CSS.escape(String(id))]` or query then filter. |
| `src-ts/chat-manager.ts` | 2227–2235 | LOW | innerHTML literal | AI edit bar uses static literal HTML — safe. |
| `src-ts/chat-manager.ts` | 2312–2319 | MED | Edit textarea | `${escapeHtml(originalContent)}` — ✅ but **inside `<textarea>`**, only `<` `&` matter for parser-state. The current escape is over-broad and harmless. |
| `src-ts/chat-manager.ts` | 2515–2521 | LOW | Provider option labels | Hardcoded strings — safe. |
| `src-ts/chat-manager.ts` | 2526–2539 | LOW | Blob download | `URL.revokeObjectURL(url)` is called immediately after `a.click()`. In some browsers this races with the actual download fetch; using `setTimeout(…, 100)` would be safer. |
| `src-ts/chat-manager.ts` | 2627–2630 | LOW | Sequential exports | Loops `for (const conv …)` with 250ms gap — good fix from prior parallel-blocked-by-browser bug. |
| `src-ts/chat-manager.ts` | 2733 | LOW | Module-level mutable | `export let chatManager: ChatManager \| null = null;` — shared module state; consumers (app.ts) check for null. Fine. |
| `src-ts/chat/conversation-list.ts` | 89 | LOW | innerHTML map | Conv list built with `escapeHtml(conv.id)` etc. ✅ |
| `src-ts/chat/conversation-list.ts` | 115–126 | MED | Hidden global slot | `const slot = container as unknown as Record<string, EventListener \| undefined>; if (slot._convClickHandler) container.removeEventListener('click', slot._convClickHandler); slot._convClickHandler = handler;` — stores handler reference on DOM node via `as unknown as Record`. Brittle and bypasses TS checks. Use a `WeakMap<HTMLElement, EventListener>` or just unbind+rebind without state. |
| `src-ts/chat/conversation-list.ts` | 138–139 | LOW | Tag chip XSS | `data-tag="${escapeHtml(t)}"…aria-label="Remove tag ${escapeHtml(t)}"` — both escaped. ✅ |
| `src-ts/chat/conversation-modals.ts` | 40–53 | LOW | Escape handler scope | Lazy attach/detach — works correctly; only attaches one at a time. |
| `src-ts/chat/conversation-modals.ts` | 59, 86 | LOW | streaming guard | `isStreaming()` — good. |
| `src-ts/chat/document-attach.ts` | 122–187 | MED | FileReader race + sentinel | `attach()` uses an object `placeholder` reserved before async read. `finalizeData` finds slot via `indexOf(placeholder)` — race-safe. ✅ Good fix. |
| `src-ts/chat/document-attach.ts` | 134 | MED | Limit | 5 docs × 32MB = 160MB per send. Both backend (Claude API) and the WS 50MB-codeunit cap (`ws-client.ts` L42) will reject. Acceptable. |
| `src-ts/chat/document-attach.ts` | 169–177 | LOW | UTF-8 decode strict | `reader.readAsText(file, 'utf-8')` — silently decodes invalid UTF-8 to U+FFFD. Consider warning the user when chunk replacement count is high. |
| `src-ts/chat/document-attach.ts` | 195–227 | LOW | innerHTML map preview | All fields escaped. ✅ |
| `src-ts/chat/export-picker.ts` | 17–58 | LOW | Modal singleton | `ensureModal()` reuses existing node — idempotent. ✅ |
| `src-ts/chat/export-picker.ts` | 63–96 | LOW | AbortController cleanup | Uses `AbortController` to drop all listeners — best-practice. ✅ |
| `src-ts/chat/formatter.ts` | 60–63 | LOW | Streaming fence guard | Adds virtual close ` ``` ` for odd fence count — clean fix. |
| `src-ts/chat/formatter.ts` | 68–95 | MED | Regex precision | `(?:[^$]|\\\$)+` for block LaTeX is greedy and can match across paragraphs. A user typing `$$x$$ … $$y$$` in one paragraph could bleed into `$$x …` if a `$` sits unbalanced before the close. Edge case; KaTeX handles it. |
| `src-ts/chat/formatter.ts` | 109–111 | LOW | Placeholder regex | `\x00BLOCK_LATEX_(\d+)\x00` — relies on user input never containing `\x00`. After `escapeHtml` runs above, `\x00` survives — escapeHtml doesn't escape NUL. If a server pushed text containing `\x00BLOCK_LATEX_999\x00` it could swap an out-of-range index → empty string. Not exploitable; harmless. |
| `src-ts/chat/formatter.ts` | 119–132 | MED | Code block embedded twice | `code` (HTML-escaped) is interpolated at both `data-code-copy="${code}"` and `<code …>${code}</code>` — once for copy attribute, once for display. ✅ Safe per the comment. **Subtle issue:** the regex `/```(\w*)\n([\s\S]*?)```/g` requires a closing fence; the streaming guard at L60 inserts one if missing. But if the AI streams a code block that internally contains "```" as a literal (unlikely from a model but possible), the regex matches the inner triple-backtick as the close, truncating the block. |
| `src-ts/chat/formatter.ts` | 133 | MED | Inline code regex | `/`([^`]+)`/g` doesn't unescape — `<code>$1</code>` injects raw `$1` which is the HTML-escaped content. ✅ |
| `src-ts/chat/formatter.ts` | 219–262 | **HIGH** | DOMPurify whitelist | The `ALLOWED_URI_REGEXP: /^https:/i` is a strong restriction. **However:** `ALLOW_DATA_ATTR: false` plus `ADD_ATTR: ['data-img-idx', 'data-code-copy']` allows those two specific data attrs. `ADD_ATTR` adds to the allowlist; the `data-code-copy` attr can hold up to ~50MB of text — huge but not XSS. **Bigger concern:** `style` is in `ALLOWED_ATTR`. DOMPurify sanitizes CSS, but its CSS sanitizer has historically had bypasses. For chat content, removing `style` and using class-based alignment for tables would be safer. |
| `src-ts/chat/formatter.ts` | 245–256 | MED | SVG attrs | `viewBox`, `fill`, `stroke`, `d`, etc. are in `ALLOWED_ATTR`, but no SVG tags are in `ALLOWED_TAGS` (only KaTeX MathML). So those attrs are dead allowance — harmless. |
| `src-ts/chat/image-attach.ts` | 51–80 | LOW | Reader race | Uses unique sentinel string — race-safe. ✅ |
| `src-ts/chat/image-attach.ts` | 104–109 | MED | Img src in innerHTML | `<img src="${escapeHtml(img)}" alt="Attached ${displayIdx + 1}">` — `img` is base64 data URL set by the user's own FileReader. Locally trusted but `escapeHtml` runs anyway. ✅ |
| `src-ts/chat/image-attach.ts` | 127–144 | LOW | Accept attribute | Verbose, hardcoded — OK. |
| `src-ts/chat/image-attach.ts` | 173 | LOW | dropZones single | `[document.querySelector('.chat-main')]` — if `.chat-main` is missing the array is empty and drag-drop silently does nothing. |
| `src-ts/chat/message-template.ts` | 156–164 | LOW | Avatar HTML | `'👤'` literal fallback — safe. AI fallback uses `aiEmoji` (escaped). ✅ |
| `src-ts/chat/message-template.ts` | 170–179 | MED | Image src filter | `img.startsWith('data:image/') \|\| img.startsWith('https://')` — **no validation** that data URL doesn't contain a script payload. Browsers refuse to execute `data:image/svg+xml;…<script>…</script>`? They DO. SVG embedded as `data:image/svg+xml,…` can contain `<script>` and would execute when rendered as `<img>` — actually no, `<img>` tag does NOT execute scripts in SVG (only `<embed>`/`<object>`/`<iframe>` do). ✅ Safe but worth a comment. |
| `src-ts/chat/message-template.ts` | 188–192 | MED | Thinking innerHTML | `<div class="thinking-content collapsed">${deps.formatMessage(msg.thinking)}</div>` — `formatMessage` runs DOMPurify. ✅ |
| `src-ts/chat/message-template.ts` | 202 | MED | data-content size | Same as chat-manager.ts L1345 — full message content embedded in attribute on every render. For a 100-message conversation with 5KB messages, that's 500KB of duplicated text in attributes alone. |
| `src-ts/chat/message-template.ts` | 228 | MED | innerHTML formatMessage | Trust transitive — DOMPurify gates this. |
| `src-ts/chat/prism.ts` | 67–82 | LOW | Lazy script load | Injects `<script src="vendor/prism/prism-${canon}.min.js">` — `canon` is whitelisted at L60 (`PRISM_LANGS.has(canon)`). ✅ Safe. |
| `src-ts/chat/prism.ts` | 78 | LOW | document.head.appendChild | One script per language, never removed — but the cache at L41 prevents duplicates. Total memory ≤ all PRISM_LANGS. |
| `src-ts/chat/search.ts` | 130–183 | LOW | TreeWalker | Standard DOM API; lowercases for case-insensitive match. Uses `needle.length` (not `query.length`) for cut span — correct fix per the comment. ✅ |
| `src-ts/chat/ws-client.ts` | 35–36 | LOW | Default endpoints | Hardcoded `ws://127.0.0.1:8765/ws` — matches CSP allowlist. ✅ |
| `src-ts/chat/ws-client.ts` | 42 | LOW | 50MB cap | Measured in UTF-16 code units, not bytes — comment is accurate. Effective bound ≤ 100MB raw bytes in worst case (high-Unicode strings). Sufficient. |
| `src-ts/chat/ws-client.ts` | 145–158 | LOW | Endpoint candidates | Tries primary + 127.0.0.1 + localhost variants — good fallback. |
| `src-ts/chat/ws-client.ts` | 173–183 | MED | Auth on ws | Token sent as **first message** (`{type:'auth', token}`) inside `onopen`. Backend must reject any non-auth frame before auth — verify dashboard_chat backend enforces this. The token comes from `.env DASHBOARD_WS_TOKEN`; if empty the client sends no auth, and `connected:true` event from server checks `requires_auth` (L457 chat-manager). This is OK but the client could still send messages BEFORE the server's `connected` reply if the user types fast. |
| `src-ts/chat/ws-client.ts` | 269–287 | LOW | Reconnect | Exp backoff + 30% jitter, max 5 attempts → permanent giveup with toast. ✅ |
| `src-ts/chat/ws-client.ts` | 290–308 | LOW | Ping/pong | 30s ping, 2 missed = force reconnect. ✅ |
| `src-ts/chat/ws-client.ts` | 246–249 | LOW | Frame validation | Rejects non-object frames — defensive. ✅ |
| `playwright.config.ts` | 41–48 | LOW | Test http server | Binds to 127.0.0.1:5173 — fine. `python -u -m http.server` is safe for tests; not used in prod. |
| `vitest.config.ts` | 7 | LOW | Coverage exclude | `*.test.ts` excluded from coverage source — correct. |

## Notes / Cross-cutting (CSP, Tauri capability scope, XSS)

### XSS pipeline summary
There is essentially **one** path from attacker-controlled bytes to `innerHTML`:

```
WS frame → JSON.parse → ChatManager.handleMessage
  → message content / thinking / role labels
  → renderMessages (chat-manager.ts L1481)
    → renderMessagesHtml (message-template.ts)
      → deps.formatMessage / deps.stripThinkTags
        → formatter.ts → DOMPurify.sanitize → returned as HTML string
      → embedded into `${…}` template literals (already sanitized)
    → container.innerHTML = result.html
```

The pipeline is correct in shape: every server-controlled field flows through either `escapeHtml` (for attribute/text contexts) or `formatMessage` → DOMPurify (for HTML body). The single point of failure is **DOMPurify** itself. Bumping it past 3.3.3 closes the most recent CVE wave (see references below).

### Tauri capability scope
`capabilities/default.json` requests `core:default` — per [Tauri 2 Core Permissions](https://v2.tauri.app/reference/acl/core-permissions/) this bundles `allow-listen`, `allow-emit`, `allow-set-position`, `allow-set-size`, `allow-set-title`, `allow-show`, `allow-hide`, `allow-set-focus`, several `path:*`, `event:*`, `image:*`, `tray:*`, `webview:*`, `window:*` defaults. The dashboard only meaningfully uses the dialog plugin (explicit) and tray (set up via `TrayIconBuilder`). **Tightening to a hand-picked subset would shrink the IPC attack surface meaningfully.** None of the unused `core:*` permissions are exploitable on their own, but they keep IPC handlers reachable from the WebView even when not needed.

### CSP review
```
default-src 'self';
script-src 'self';
style-src 'self';
img-src 'self' data: blob:;
font-src 'self';
connect-src 'self' ws://localhost:* ws://127.0.0.1:* wss://localhost:* wss://127.0.0.1:*;
object-src 'none';
frame-ancestors 'none'
```

Strengths:
- No `'unsafe-inline'` / `'unsafe-eval'`
- `object-src 'none'` and `frame-ancestors 'none'`
- Explicit ws/wss schemes only on loopback hosts

Weaknesses:
- `script-src 'self'` admits all 4 vendor bundles (DOMPurify, KaTeX, Prism + langs) without SRI. Vendor swap = silent code execution. Add `<script integrity="sha384-…">` or move to a hash-based CSP.
- `connect-src` allows **any port** on loopback. Tighten to the actual WS port at config time.
- No `base-uri 'none'` — a `<base href>` injection (if XSS landed) could redirect all relative URLs.
- No `form-action 'none'` — irrelevant in this app since there are no forms, but cheap to add.

### Subprocess hardening
`bot_manager.rs` and `main.rs` consistently:
- Resolve `taskkill.exe` and `explorer.exe` via `%SystemRoot%\System32` to prevent PATH poisoning ✅
- Validate `PYTHON_CMD` is an actual `python.exe` after canonicalize ✅
- Use `CREATE_NO_WINDOW` to suppress consoles ✅
- Verify PID belongs to a Python process before kill ✅

The remaining gaps are documented in the table (kill-by-script-name false positives, dev_watcher.pid race, taskkill /F without graceful signal).

### Database
- All queries are parameterized (placeholders for IN clauses are length-controlled, values bound) ✅
- Connection cache is RAII-guarded for panic safety ✅
- Read-only paths swallow rusqlite errors silently → schema drift would render zeros

### Vendor versions

| Library | Bundled | Latest known safe | CVEs in bundled |
|---|---|---|---|
| DOMPurify | **3.3.3** | 3.3.4+ | [CVE-2026-41238](https://labs.trace37.com/blog/dompurify-pp-ceh-bypass/), [CVE-2026-0540](https://www.ibm.com/support/pages/security-bulletin-carbon-chart-dompurify-xss-vulnerabilities-cve-2025-15599-cve-2026-0540), [CVE-2025-26791](https://www.cve.news/cve-2025-26791/) |
| KaTeX | not version-stamped in this audit scope | — | recommend re-check |
| Prism | not version-stamped | — | recommend re-check |

### Memory leak / listener hygiene
The codebase generally uses dataset-flag idempotency (`dataset.escBound`, `dataset.scrollBound`, `dataset.fabBound`, `dataset.searchBound`, `dataset.filterBound`, `dataset.overlayCloseBound`). Most listeners that could leak are guarded. Three exceptions:
1. `setupSakuraParallax` `pointermove` on `window` — never removed.
2. `setupCropEventListeners` Escape `keydown` on `document` — guarded by dataset flag but never removed.
3. `setupCardTilt` MutationObserver — disconnected on `beforeunload` only.

In WebView2 with no SPA navigation these are effectively page-lifetime, so the leak ceiling is bounded. They become real if the dashboard is ever embedded as a sub-iframe or the bundle is reused across navigations.

### Telemetry
`set_telemetry_enabled` writes a flag file at `data/telemetry_optout.flag`. The Python bot is expected to read this same file (`sentry_integration.py`). The Rust side initializes Sentry **at startup** unconditionally if a DSN is present, then later checks `Hub::current().client().is_some_and(\|c\| c.is_enabled())` in `log_frontend_error`. Toggling telemetry off does not actually stop sending — it only changes whether the Python bot opts in next time. The Rust dashboard keeps shipping `log_frontend_error` payloads to Sentry until restart. Document this or honor the flag at runtime.

## Confirmation

I read every line of every assigned file. chat-manager.ts (2743 lines) was read in 4 chunks (lines 1–700, 700–1400, 1400–2100, 2100–2743). External lookups corroborated current Tauri 2 capability semantics and DOMPurify CVE state for the bundled 3.3.3 version. No file was skimmed; per-line review yielded the issue table above.

Sources:
- [Tauri 2 Capabilities](https://v2.tauri.app/security/capabilities/)
- [Tauri 2 Core Permissions](https://v2.tauri.app/reference/acl/core-permissions/)
- [Tauri 2 Security overview](https://v2.tauri.app/security/)
- [CVE-2026-41238 — DOMPurify prototype-pollution → XSS bypass (3.0.1–3.3.3)](https://labs.trace37.com/blog/dompurify-pp-ceh-bypass/)
- [CVE-2026-0540 / CVE-2025-15599 — DOMPurify rawtext element bypass](https://www.ibm.com/support/pages/security-bulletin-carbon-chart-dompurify-xss-vulnerabilities-cve-2025-15599-cve-2026-0540)
- [CVE-2025-26791 — DOMPurify SAFE_FOR_TEMPLATES regex mXSS](https://www.cve.news/cve-2025-26791/)
- [DOMPurify advisories index (Snyk)](https://security.snyk.io/package/npm/dompurify)
