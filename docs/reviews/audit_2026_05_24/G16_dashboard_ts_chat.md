# G16 — Tauri Dashboard TypeScript CHAT MODULES — Security Re-Audit (2026-05-24)

**Auditor scope:** READ-ONLY security re-audit of the 12 chat-layer `.ts` SOURCE files (the
`native_dashboard/ui/*.js` are tsc-generated — not reviewed). Trust boundary helper
`native_dashboard/src-ts/shared.ts` and the shipped `index.html` script-load block were read
as supporting context. Top concern per brief: XSS via the markdown→HTML path
(`formatter.ts` + `message-template.ts`) and the DOMPurify boundary.

**Method:** Every line of every assigned file read in full (working-tree content, not diff).
Cross-checked against prior audit `docs/reviews/audit_2026_05/G12_native_dashboard.md` and
`MASTER_TABLE.md` (row C3). DOMPurify CVE state verified by web search (CVE-2026-41238 fixed
in 3.4.0; shipped vendored copy is **3.3.3**).

## Files audited (every line)
formatter.ts (285), message-template.ts (263), prism.ts (108), ws-client.ts (329),
image-attach.ts (236), document-attach.ts (207), search.ts (205), export-picker.ts (98),
conversation-list.ts (195), conversation-modals.ts (124), context-window.ts (155), types.ts (58).

## Severity counts
- CRITICAL: 1
- HIGH: 2
- MEDIUM: 9
- LOW: 13
- INFO: 7
- **Total: 32**

Prior-audit reconciliation (prior IDs are G12 table rows referenced by file:line, plus MASTER C3):
- **C3 / G12 "DOMPurify 3.3.3" → STILL-PRESENT** (vendored shipped copy unchanged; node_modules bumped to 3.4.2 but that is NOT the file loaded by index.html).
- G12 "formatter L219-262 HIGH (style attr / DOMPurify CSS)" → STILL-PRESENT (now formatter.ts L245-283).
- G12 SRI weakness (CSP review) → PARTIALLY-FIXED (index.html now ships `integrity=` on katex/dompurify/prism; but the pinned DOMPurify hash pins the *vulnerable* 3.3.3).
- G12 "shared.ts http:// avatar allowlist LOW" → STILL-PRESENT (shared.ts L263-270 still allows `http://`); message-template image path was hardened separately (host allowlist added).
- Most other G12 chat-file LOW rows → FIXED-VERIFIED or unchanged-LOW (see table Prior column).

---

## Findings

| File | Line(s) | Severity | Category | Issue | Prior | Suggested fix |
|---|---|---|---|---|---|---|
| ui/vendor/dompurify/purify.min.js (loaded by formatter.ts via window.DOMPurify) | banner L1; consumed at formatter.ts:245 | **CRITICAL** | Vulnerable dependency / XSS bypass | The **shipped** vendored DOMPurify is still **3.3.3** (license banner confirms). CVE-2026-41238 (prototype-pollution → XSS via `CUSTOM_ELEMENT_HANDLING` fallback reading `tagNameCheck`/`attributeNameCheck` off a polluted `Object.prototype`) affects 3.0.1–3.3.3, fixed in 3.4.0. `formatMessage` calls `purify.sanitize(html, {...})` with **no `CUSTOM_ELEMENT_HANDLING` key** — i.e. exactly the default-config scenario the CVE exploits. DOMPurify is the SOLE sanitizer for AI/server-controlled markdown (WS frame → `formatMessage` → innerHTML). `node_modules/dompurify` is 3.4.2 but index.html loads the vendored 3.3.3 (now SRI-pinned to the vulnerable build). Two pollution gadgets already exist in-tree: KaTeX/Prism are loaded with full `window.__TAURI__` access (`withGlobalTauri:true`), and any same-origin pollution → bypass. | C3 / G12 CRIT (STILL-PRESENT) | Re-vendor `purify.min.js` from the installed 3.4.2 (regenerate the SRI hash in index.html); AND pass an explicit hardened config `CUSTOM_ELEMENT_HANDLING: { tagNameCheck: null, attributeNameCheck: null, allowCustomizedBuiltInElements: false }` to every `sanitize()` call as belt-and-suspenders. |
| formatter.ts | 245-283 (esp. 266-277 `style` in ALLOWED_ATTR) | **HIGH** | Sanitizer whitelist / CSS injection surface | `'style'` is whitelisted on chat body content solely for table-cell `text-align`. DOMPurify's built-in CSS sanitizer has a recurring history of bypasses, and combined with the 3.3.3 CVE above the `style` channel widens the attack surface for `url()`, `expression()`-class, or future CSS-leak gadgets. The alignment use-case does not need arbitrary inline style. | G12 formatter L219-262 HIGH (STILL-PRESENT) | Drop `'style'` from `ALLOWED_ATTR`; render table alignment with three fixed classes (`md-cell-left/center/right`) set in the builder instead of `style="text-align:.."`. |
| shared.ts (consumed by message-template.ts:108-109,157-162 + conversation-list.ts:87 + welcome card) | shared.ts:263-270 | **HIGH** | URL allowlist — privacy / mixed-content | `isSafeAvatarUrl` still permits `http://` (and any `https://`/relative) for avatar `src`. Avatars flow from localStorage AND can be overwritten by a server `profile`/settings push, so a compromised/abusive WS server can set `aiAvatar` to `http://attacker/pixel` → plaintext beacon leaking viewer IP+UA on next load (no script needed). message-template.ts L178-192 added a host allowlist for *message* images but the *avatar* path (`safeAvatarUrl`) has no host restriction and still allows `http:`. | G12 shared.ts L179-193 LOW (REGRESSED in severity — same code, but now reachable via server-set avatar; STILL-PRESENT) | In `isSafeAvatarUrl` drop `http://`; restrict remote avatars to the same trusted-host allowlist used for message images (or `data:image/` + relative only). |
| formatter.ts | 76, 91 | MEDIUM | Regex precision (markdown bleed) | Block-LaTeX `/\$\$((?:[^$]|\\\$)+)\$\$/g` and inline `/(?<!\$)\$(?!\$)([^$]+)\$(?!\$)/g` are greedy across newlines; an unbalanced `$`/`$$` in chat (currency, code) can swallow a span up to the next dollar and feed unintended text to KaTeX. Not an XSS (KaTeX output is re-sanitized by DOMPurify at L245) — a correctness/garbled-render bug. | G12 formatter L68-95 MED (STILL-PRESENT) | Constrain block LaTeX to not cross blank lines; or migrate to a tokenizing markdown lib. Add tests for `$5 and $10`. |
| formatter.ts | 133 | MEDIUM | Fenced-code truncation | `/```(\w*)\n([\s\S]*?)```/g` is non-greedy, so a literal ```` ``` ```` *inside* a fenced block (e.g. model emitting nested fences) is treated as the close and truncates the block; trailing content then re-parses as markdown. Functional/robustness bug, not XSS (all output sanitized). | G12 formatter L119-132 MED (STILL-PRESENT) | Acceptable for a regex formatter; document the limitation or move to a real markdown parser. |
| formatter.ts | 58-59, 117, 132-133, 173, 212, 233-235 | MEDIUM | Placeholder collision via control chars | Placeholders use `\x00/\x01/\x02/\x03`. `escapeHtml` (shared.ts:215-219) does NOT strip NUL/control chars, so server text literally containing `\x01CODE_BLOCK_5\x01` survives escaping and can substitute an out-of-range/empty block (the `|| ''` guards make it render empty). Harmless today (no injection — restored values are themselves sanitized at L245) but a brittle parsing seam. | G12 formatter L109-111 LOW (STILL-PRESENT; widened to all 4 placeholder families) | Strip `[\x00-\x08\x0B\x0C\x0E-\x1F]` from `content` at the top of `formatMessage` before any pass. |
| ws-client.ts | 176-200, 239 | MEDIUM | Auth race / origin | Token is sent as the first frame inside `onopen` (good — not in URL), but there is **no `event.origin` check** in `onmessage`, and the client may emit non-auth frames before the server's `connected` ack if the user acts fast. Backend must reject pre-auth frames; that enforcement is server-side and unverified here. WebSocket has no SOP, so origin/first-frame discipline is the only client guard. | G12 ws-client L173-183 MED (STILL-PRESENT) | Gate `send()` of non-auth frames until a server `connected`/auth-ok frame is observed; confirm backend drops frames received before a valid `auth`. |
| ws-client.ts | 250-252 | MEDIUM | Prototype-pollution defense (partial) | The `JSON.parse` reviver drops `__proto__`/`constructor`/`prototype` **keys**, but a payload like `{"a":{"__proto__":{"polluted":1}}}` is still neutralised only because the key is named `__proto__`; however nested objects reconstructed normally are then passed straight to `onMessage` and spread into app state elsewhere. The reviver does not deep-freeze or `Object.create(null)` the result. Given the CRITICAL DOMPurify PP-gadget, hardening parse output matters. | new | After parse, rebuild critical sub-objects with `Object.create(null)` or validate against a schema before dispatch; keep the reviver. |
| message-template.ts | 231 | MEDIUM | DOM bloat / memory | `data-content="${escapeHtml(msg.content)}"` embeds the FULL message text (up to the 50 MB WS cap) in an attribute on EVERY rendered message. A long conversation duplicates all message text into attributes → large DOM + memory. Not XSS (escaped). | G12 message-template L202 MED (STILL-PRESENT) | Drop `data-content`; on copy-click read the rendered text node / hold content in a JS-side map keyed by msg id. |
| context-window.ts | 71, 87 | MEDIUM | LRU correctness bug | `update()` does `cache.delete(id); cache.set(id, usage)` — but it stores the **`usage` argument**, not a normalized object; meanwhile `load()` normalizes `total_tokens`. More importantly, `restore()` (L120-128) re-`update()`s with the cached value which re-`save()`s on every conversation switch — extra localStorage writes. Minor; values are numbers only (no XSS). | new (file was LOW-only in G12) | In `update`, store a normalized `{input,output,total,context_window}`; skip `save()` on the restore path (read-only touch). |
| document-attach.ts | 165 | MEDIUM | Silent UTF-8 corruption | `reader.readAsText(file, 'utf-8')` decodes invalid bytes to U+FFFD silently; a binary file with a text-like extension (e.g. `.csv` that's actually gzip) is inlined into the prompt as garbage with no user warning. Also `classify()` (L85-89) treats any non-binary-listed file as text, so an unknown-extension binary is read as text. | G12 document-attach L169-177 LOW (STILL-PRESENT) | Detect a high U+FFFD ratio post-decode and warn/reject; or sniff a BOM/NUL-byte heuristic before choosing text vs binary. |
| conversation-list.ts | 115-126 | MEDIUM | Brittle handler storage / type hole | Click handler stashed on the DOM node via `container as unknown as Record<string, EventListener>` (`slot._convClickHandler`). Bypasses TS typing and pollutes the element with an ad-hoc property; correct at runtime but fragile. | G12 conversation-list L115-126 MED (STILL-PRESENT) | Use a `WeakMap<HTMLElement, EventListener>` for the stored handler, or bind via event delegation on a stable ancestor once. |
| formatter.ts | 154-169 | LOW | Markdown regex over trusted KaTeX output | Inline `code`/`**bold**`/`*em*`/heading/blockquote regexes run over `html` AFTER trusted KaTeX HTML was restored (L117-119); a `*` or `` ` `` inside KaTeX markup could be wrapped in `<em>`/`<code>`. Cosmetic only — final DOMPurify pass keeps it well-formed; no injection. | new | Run inline-markdown passes before restoring KaTeX, or exclude restored spans. |
| formatter.ts | 245-265 (ALLOWED_TAGS includes `button`) + 278 ADD_ATTR `data-code-copy` | LOW | Whitelist breadth | `button` is allowed in sanitized chat body and `data-code-copy` is force-allowed; `data-code-copy` can hold a very large escaped string. No `on*` survives DOMPurify so no script, but server markdown could render inert `<button>`s and bloat attributes. | G12 formatter L219-262 (noted) STILL-PRESENT | Consider stripping `<button>` from the markdown whitelist (the copy button is generated by the formatter itself, post-list; could be appended after sanitize instead). |
| formatter.ts | 266-277 | LOW | Dead attribute allowance | SVG presentational attrs (`viewBox`,`fill`,`stroke`,`d`,`width`,`height`,…) are in `ALLOWED_ATTR` but no `svg`/`path` tag is in `ALLOWED_TAGS` — dead allowance (harmless). | G12 formatter L245-256 MED→ (FIXED-VERIFIED as harmless; still dead) | Remove the unused SVG attrs to keep the allowlist minimal. |
| message-template.ts | 193-200 | LOW | Image-src SVG/data filter (verify) | Filter accepts `data:image/` (case-sensitive `startsWith`) excluding `data:image/svg*`, plus a 4-host https allowlist. `<img>` does not execute SVG scripts so even an allowed SVG data URL is inert; the explicit svg exclusion is defense-in-depth. Case-sensitive `data:image/` means `DATA:...` is simply rejected (safe). Looks correct. | G12 message-template L170-179 MED (FIXED-VERIFIED) | None required; keep the svg exclusion comment. |
| message-template.ts | 33 (types) + render | LOW | Attached documents never rendered | `ChatMessage.documents` exists (types.ts:33) and is sent/persisted, but `renderSingleMessage` renders only `images`, never `documents`. Past-message doc attachments are invisible in the transcript. Functional gap, not security. | new | Render a small doc-chip row for `msg.documents` (escaped name/size like document-attach preview). |
| image-attach.ts | 162-164 | LOW | Drag-drop silently inert if `.chat-main` missing | `dropZones = [document.querySelector('.chat-main')]`; if that node is absent the array is empty and drop does nothing with no diagnostic. | G12 image-attach L173 LOW (STILL-PRESENT) | Fall back to a broader container or log once if no drop zone resolves. |
| image-attach.ts | 61, 96 | LOW | Trusted local data URL | `<img src="${escapeHtml(img)}">` for user-picked base64; `escapeHtml` runs even though source is local FileReader output. Correct/defensive. | G12 image-attach L104-109 MED (FIXED-VERIFIED) | None. |
| search.ts | 145-204 | LOW | Highlight injection / ReDoS — none found | Match is a plain `String.prototype.indexOf` on lowercased text (no RegExp from user input → no ReDoS), and hits are inserted via `document.createElement('mark')` + `textContent` (no innerHTML) → no markup injection. `MAX_HITS=1000` caps work. Correct. | G12 search L130-183 LOW (FIXED-VERIFIED) | None. |
| export-picker.ts | 62-97 | LOW | Listener hygiene OK; output-encoding N/A here | Modal uses `AbortController` to drop all listeners on cleanup (good). This module only returns the chosen *format string* (`'json'|'markdown'|'html'|'txt'`) — the actual export serialization/HTML/CSV-injection encoding happens in chat-manager.ts (out of this audit's file scope). Flagging that the CSV/HTML-export encoding boundary lives elsewhere and was not reviewable here. | G12 export-picker L63-96 LOW (FIXED-VERIFIED) | Audit the export serializer in chat-manager.ts for CSV-formula injection (`=`,`+`,`-`,`@` prefixes) and HTML-export escaping separately. |
| conversation-list.ts | 89-110, 135-139 | LOW | innerHTML map — escaping correct | `conv.id`, `conv.title`, `preset.emoji`, tags all `escapeHtml`-wrapped before interpolation; `message_count` rendered as `conv.message_count || 0` (number). Correct. | G12 conversation-list L89 / L138-139 LOW (FIXED-VERIFIED) | None. |
| conversation-modals.ts | 40-53 | LOW | Escape-handler hygiene | Lazy `attachEscape`/`detachEscape` keyed to one handler ref; only one modal open at a time; detached on close. Correct, no leak. | G12 conversation-modals L40-53 LOW (FIXED-VERIFIED) | None. |
| document-attach.ts | 188-205 | LOW | Preview innerHTML — escaping correct | `doc.name`, `formatBytes(size)`, `doc.kind` all `escapeHtml`-wrapped; `iconFor` returns a fixed emoji from extension. Correct. | G12 document-attach L195-227 LOW (FIXED-VERIFIED) | None. |
| ws-client.ts | 42, 244-247 | LOW | 50 MB cap measured in UTF-16 code units | Comment is accurate; worst case ~2× bytes for high-Unicode. Oversized frames dropped before parse. Sufficient guard. | G12 ws-client L42 LOW (FIXED-VERIFIED) | None. |
| ws-client.ts | 275-300 | LOW | Reconnect backoff | Exp backoff (1s→30s) + 30% jitter, capped at 5 attempts then permanent give-up + toast. No storm. Correct. | G12 ws-client L269-287 LOW (FIXED-VERIFIED) | None. |
| context-window.ts | 32-68 | LOW | localStorage shape validation | `load()` rejects non-object/array, drops non-finite numbers — prevents `NaN%`. Good defensive parsing of user-writable storage. | new (positive) | None. |
| prism.ts | 58-82 | LOW | Lazy `<script>` injection — lang whitelisted | `script.src = vendor/prism/prism-${canon}.min.js` where `canon` must pass `PRISM_LANGS.has(canon)` (L60) and originates from a `[a-zA-Z0-9_-]`-restricted class label (formatter L139). No path traversal. Script never removed but cache de-dupes. Safe. | G12 prism L67-82 LOW (FIXED-VERIFIED) | None. |
| prism.ts | 88-105 | LOW | highlightElement on sanitized DOM | `highlightElement` mutates innerHTML of `<code>` blocks Prism tokenizes — but it operates on content that already passed DOMPurify (formatter output), and Prism only re-styles existing text into `<span class>`. No untrusted innerHTML set by prism.ts itself. `dataset.prismDone` guards re-highlight. Safe. | new (positive) | None. |
| export-picker.ts | 86 | INFO | Format cast | `(btn.dataset.format || 'json') as ExportFormat` trusts the static `data-format` values authored in `ensureModal()` (json/markdown/html/txt). Safe since modal HTML is constant. | G12 (n/a) | None. |
| types.ts | 27-39 | INFO | `ChatMessage.id` optional `number` | `id?: number`; message-template.ts:227-229 already coerces via `Number.isFinite`+`Math.trunc` before interpolation — defends against a hostile non-numeric id. Good. | G12 message-template (FIXED-VERIFIED) | None. |
| message-template.ts | 105, 152, 218, 231, 236, 247, 251 | INFO | escapeHtml coverage of WS fields | `role_emoji`, `formatTime` output, `mode`, `role`, `displayName`, `content` (via formatMessage) all escaped/sanitized at each interpolation. Attribute contexts use `escapeHtml` (which also escapes `"`,`'`,`` ` ``). Boundary is consistent. | G12 (FIXED-VERIFIED) | None. |
| formatter.ts | 47-54, 240-244 | INFO | Fail-closed design | Returns `escapeHtml(content)` if DOMPurify missing at entry, and `''` (with errorLogger) if missing at exit — fail-closed, no raw HTML leak. Good design. | G12 (positive) | None. |
| shared.ts | 215-219 | INFO | escapeHtml relies on DOM | `escapeHtml` uses `document.createElement('div').textContent` then escapes `"`,`'`,`` ` ``. Correct for `<`,`>`,`&`,quotes; does not strip control chars (see formatter MED placeholder note). | G12 shared L165-169 LOW (FIXED-VERIFIED) | Optionally strip control chars here to fix the placeholder seam centrally. |
| search.ts | 124-134 | INFO | Unwrap via textContent+normalize | `clearHighlights` replaces `<mark>` with a text node and `normalize()`s — clean, no innerHTML, no leak. | G12 (positive) | None. |

---

## XSS pipeline assessment (re-confirmed)

The single attacker-reachable path to `innerHTML` is unchanged from G12:

```
WS frame → ws-client.ts JSON.parse (proto-key reviver) → onMessage → ChatManager
  → msg.content / msg.thinking / role labels
  → renderMessagesHtml (message-template.ts)  [attr fields escapeHtml'd]
    → deps.formatMessage / stripThinkTags → formatter.ts
      → escapeHtml + markdown passes → DOMPurify.sanitize(...)  ← SOLE sanitizer
  → container.innerHTML = html
```

The *shape* is correct: every server field is either `escapeHtml`'d (attribute/text) or routed
through `formatMessage` → DOMPurify (HTML body). The **single point of failure is DOMPurify**, and
the shipped copy is the vulnerable **3.3.3** called in its exact CVE-2026-41238 default-config form.
That is the CRITICAL. Everything else is defense-in-depth or correctness.

## Positives observed
- Fail-closed formatter (escape on missing DOMPurify entry, `''` on missing exit).
- `ALLOWED_URI_REGEXP: /^https:/i` blocks `javascript:`/`data:`/`http:` hrefs in sanitized body.
- Message-image host allowlist + `data:image/svg` exclusion (new since G12).
- WS: oversized-frame drop, non-object frame reject, proto-key parse reviver, backoff+jitter, ping/pong.
- Attachment managers: size+count caps, `pendingCount` guards against read-flood, data-URL re-validation on render.
- search.ts: no user RegExp (no ReDoS), `mark` via createElement/textContent (no markup injection), MAX_HITS cap.
- SRI now present on all vendor `<script>`/`<link>` in index.html (partial fix of prior CSP weakness).

## Out-of-scope notes (flagged for completeness)
- The export *serializer* (CSV/HTML/Markdown encoding, formula-injection) lives in `chat-manager.ts`,
  not in `export-picker.ts`; not reviewable within assigned files — recommend a dedicated check for
  CSV-formula injection (`=`/`+`/`-`/`@` cell prefixes) and HTML-export escaping there.
- `node_modules/dompurify` is 3.4.2 (patched) but is NOT the file the app loads; only the
  `ui/vendor/dompurify/purify.min.js` (3.3.3) ships. The SRI hash in index.html L30 pins 3.3.3.

Sources:
- [CVE-2026-41238 — DOMPurify Prototype Pollution → XSS (fixed 3.4.0)](https://github.com/advisories/GHSA-v9jr-rg53-9pgp)
- [trace37 labs — DOMPurify PP CEH bypass write-up](https://labs.trace37.com/blog/dompurify-pp-ceh-bypass/)
- [Snyk — CVE-2026-41238 dompurify](https://security.snyk.io/vuln/SNYK-JS-DOMPURIFY-16132234)
