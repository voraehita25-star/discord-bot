# G18: Frontend Assets — Security Re-Audit (HTML / CSS / Vendored JS)

**Auditor pass:** Read every line of every assigned file. `index.html` (864 lines) and `styles.css` (5205 lines) read in full. Every vendored JS/CSS banner inspected; SRI hashes recomputed locally and cross-checked against `index.html`. DOMPurify CVE state re-verified via web search (today: 2026-05-24).

**Read-only confirmation:** No source file was modified. Only this report was written.

## Scope

| Path | Lines / Size | Notes |
|---|---:|---|
| `native_dashboard/ui/index.html` | 864 | CSP meta, vendor `<script>` + SRI, UI shell |
| `native_dashboard/ui/styles.css` | 5205 | full theming + 3D polish + noise texture |
| `native_dashboard/ui/assets/faust_base64.txt` | 1 line / 15541 B | single JPEG data URI (Faust avatar) |
| `native_dashboard/ui/vendor/dompurify/purify.min.js` | 23274 B | **DOMPurify 3.3.3** |
| `native_dashboard/ui/vendor/katex/katex.min.js` | 277038 B | KaTeX 0.16.9 |
| `native_dashboard/ui/vendor/katex/auto-render.min.js` | 3478 B | KaTeX auto-render 0.16.9 |
| `native_dashboard/ui/vendor/katex/katex.min.css` | 23196 B | KaTeX stylesheet + 20 woff2 fonts |
| `native_dashboard/ui/vendor/prism/prism-tomorrow.min.css` | 1313 B | Prism theme CSS (NO Prism JS vendored) |

## Severity-count summary

| Severity | Count |
|---|---:|
| CRITICAL | 1 |
| HIGH | 2 |
| MEDIUM | 3 |
| LOW | 7 |
| INFO | 6 |
| **Total** | **19** |

## VENDOR VERSION TABLE

| Library | Vendored version | Latest-safe | CVE status | SRI in index.html |
|---|---|---|---|---|
| **DOMPurify** | **3.3.3** (banner L1 of purify.min.js: `@license DOMPurify 3.3.3`) | **3.4.0+** | **VULNERABLE** — CVE-2026-41238 (prototype-pollution → XSS via CUSTOM_ELEMENT_HANDLING fallback, affects 3.0.1–3.3.3), CVE-2026-0540 (rawtext bypass 3.1.3–3.3.1), CVE-2025-26791 (SAFE_FOR_TEMPLATES mXSS). **Fixed in 3.4.0** (NOT 3.3.4 — see note below). | ✅ matches file (`sha384-pcBjn…`) |
| KaTeX | 0.16.9 (internal `version:"0.16.9"`) | 0.16.x current line | No known *critical* CVE applicable to this offline render path at audit time. `trust:false` is KaTeX default; bot does not override. Needs-verification: confirm no `\href`/`trust` enablement downstream. | ✅ matches file |
| KaTeX auto-render | 0.16.9 (bundled with katex) | 0.16.x | none known | ✅ matches file |
| Prism (theme CSS) | unversioned (`prism-tomorrow.min.css`) | — | CSS only, no JS executes. No CVE surface. | ✅ matches file |
| Prism core JS | **MISSING FILE** | — | `index.html:36-38` references `vendor/prism/prism-core.min.js` **which does not exist** in `vendor/prism/` (only the `.css` is present). See finding G18-02. | SRI present for a non-existent file |

> **Correction vs. prior audit (MASTER C3 / G12):** The prior audit's remediation note said "Upgrade to ≥3.3.4". That is WRONG — **3.3.4 is NOT the fixed release**. Per the GitHub Advisory (GHSA-v9jr-rg53-9pgp) and SentinelOne/Snyk databases, **CVE-2026-41238 is fixed in DOMPurify 3.4.0**. The vendored `package.json` already declares `"dompurify": "^3.4.2"` (line 36), but the **actual vendored bundle was never rebuilt** — it is still 3.3.3. The dependency manifest and the shipped artifact have drifted.

---

## Findings table

| File | Line(s) | Severity | Category | Issue | Prior | Suggested fix |
|---|---|---|---|---|---|---|
| `ui/vendor/dompurify/purify.min.js` | banner L1 | **CRITICAL** | Vulnerable dependency | Vendored DOMPurify is **3.3.3** (license banner: `DOMPurify 3.3.3 \| (c) Cure53 … github.com/cure53/DOMPurify/blob/3.3.3/LICENSE`). Internal `version="3.3.3"`. This is the sole sanitizer for AI-generated markdown rendered via `innerHTML` (formatter.ts → `DOMPurify.sanitize`; sinks at chat-manager.ts L1290/L1331 and message-template.ts). Default config does not set `CUSTOM_ELEMENT_HANDLING`, so it falls back to `{}` (inherits `Object.prototype`) — the exact gadget CVE-2026-41238 exploits: an attacker who pollutes `Object.prototype.tagNameCheck`/`attributeNameCheck` (regex-permissive) bypasses the allowlist and lands `onclick`/`onerror` XSS. `package.json` claims `^3.4.2` but the bundle was not rebuilt. | **STILL-PRESENT** (was C3 / G12 CRIT, marked "thought-fixed"). Prior remediation text "≥3.3.4" is itself incorrect. | Rebuild/copy DOMPurify **3.4.0+** into the vendor dir, **regenerate the SRI hash** at index.html:30, and consider hardening config (`CUSTOM_ELEMENT_HANDLING: { tagNameCheck: null, attributeNameCheck: null, allowCustomizedBuiltInElements: false }` + freeze, or pass an `Object.create(null)`-rooted config). Verify with the `python -c hashlib.sha384…` one-liner already in the index.html comment. |
| `ui/index.html` | 36–38 | **HIGH** | Missing resource / SRI on absent file | `<script defer src="vendor/prism/prism-core.min.js" integrity="sha384-MXyb…">` references a file that **does not exist** — `vendor/prism/` contains only `prism-tomorrow.min.css`. Effect: (a) a console-level load failure on every startup; (b) syntax highlighting silently never initializes its core (chat-manager lazy-loads language files `vendor/prism/prism-<lang>.min.js` per prior audit G12 L149, which also won't exist, but those are guarded by a whitelist). The SRI hash here is for a file no auditor can validate because it's not in the tree — it could mask a future drop-in of an unverified file. Confirms a build/packaging gap: the Prism JS bundles were never vendored, only the theme CSS was. | NEW (prior audit listed Prism among "4 vendor bundles" in CSP notes but did not catch that the JS file is absent). | Either vendor the real `prism-core.min.js` (+ the per-language files chat-manager expects) and regenerate SRI, OR remove the dead `<script>` tag at L36-38 and the lazy-loader if Prism highlighting is not actually shipped. Decide intentionally — right now code highlighting is dead. |
| `ui/index.html` | 12 | **HIGH** | CSP weakening (regression) | CSP `style-src 'self' 'unsafe-inline'`. The prior audit (G12 §CSP review, L186) recorded `style-src 'self'` with **no** `'unsafe-inline'` and explicitly listed "No `'unsafe-inline'`" as a strength. The current meta has **added** `'unsafe-inline'` to style-src. This re-opens CSS-injection vectors (e.g. an attacker who lands HTML through a DOMPurify bypass — see CRIT row — can now also use inline `style=` for data-exfil via `background:url()` or layout-based attacks) and broadens the surface that DOMPurify's own `style` allowance (formatter.ts ALLOWED_ATTR) sits behind. It is present because the app sets element `.style.cssText`/inline styles from JS and uses `style="display:none"` attributes (e.g. index.html:172) — but those are same-origin first-party and could use classes or a nonce instead. | **REGRESSED** (was `style-src 'self'` per G12; now `'self' 'unsafe-inline'`). | Drop `'unsafe-inline'` from `style-src`; convert the handful of inline `style=` attributes to classes (`.hidden` already exists at styles.css:7) and set dynamic styles via CSSOM property setters (which do not require `'unsafe-inline'`). If unavoidable, move to a per-load style nonce. |
| `ui/index.html` | 12 | MEDIUM | CSP hardening gaps | CSP is missing `base-uri`, `form-action`, `script-src 'strict-dynamic'`/nonce, and (intentionally, per L6-11 comment) `frame-ancestors`. Without `base-uri 'none'`, a `<base href>` injected through any same-origin XSS (gated today only by DOMPurify — see CRIT) could repoint every relative URL (including the vendor `<script src>`… though those are already loaded, and the WS endpoint is absolute). `object-src 'none'` ✅ is present. `default-src 'self'` ✅. No `'unsafe-eval'` ✅. | **PARTIALLY-FIXED / carried** (prior G12 flagged "No `base-uri 'none'`" and "No `form-action 'none'`" as CSP weaknesses; still absent). | Add `base-uri 'none'; form-action 'none';` to the meta — both are zero-risk in this app (no forms, no base tag) and close the directives. |
| `ui/index.html` | 12 | MEDIUM | CSP — WS allowlist too broad | `connect-src` allows `ws://localhost:* ws://127.0.0.1:* wss://localhost:* wss://127.0.0.1:*` — **any port** on loopback. The bot's WS default is `ws://127.0.0.1:8765/ws` (ws-client.ts L35). A malicious local listener on any high port could impersonate the dashboard backend after the user launches the app, and the client's fallback candidate list (G12 L145-158) will happily try it. | **STILL-PRESENT** (prior G12 HIGH "connect-src allows any port"; unchanged, downgraded to MED here as local-only threat in a desktop WebView). | Pin to the resolved port at build time: `connect-src 'self' ws://127.0.0.1:8765 wss://127.0.0.1:8765` (or template the `WS_DASHBOARD_PORT`). |
| `ui/index.html` | 22–38 | MEDIUM | SRI lock pins a vulnerable artifact | All four vendor SRI hashes were recomputed locally and **match the on-disk files exactly** (good integrity hygiene). The side effect: the SRI at L30 cryptographically **locks in the vulnerable DOMPurify 3.3.3** — any safe rebuild MUST also update this hash, and a reviewer who trusts "SRI present = safe" is misled. This is a process note, not a flaw in SRI itself. | NEW framing (prior audit recommended *adding* SRI; it was added but to the wrong version). | When fixing the CRIT row, regenerate the L30 hash in the same change. Add a CI check that the vendored DOMPurify banner version ≥ a floor (e.g. fail build if banner reads `3.3.x` or lower). |
| `ui/styles.css` | 5100 | LOW | Inline SVG data URI in `background-image` | `.sidebar::before` (+ 8 sibling selectors) sets `background-image: url("data:image/svg+xml;utf8,<svg …><feTurbulence …/>…</svg>")` — a hardcoded fractal-noise texture. SVG referenced via CSS `background-image` does **not** execute scripts (unlike `<object>`/`<iframe>`/inline `<svg>` in DOM), and the string is a literal constant with no interpolation, so there is no injection vector. Requires `img-src data:` (present, index.html:12) — the comment at L5085 correctly notes this. Flagged for completeness only. | NEW (not in prior scope). | None required. Optionally externalize to a `.svg` file to keep CSP tightenable, but not necessary. |
| `ui/styles.css` | 12 (and `:root` at 4328) | INFO | Two `:root` blocks | A second `:root{…}` (L4328) defines the 3D shadow/motion tokens, separate from the theme `:root` at L11. Valid CSS (both apply), but split definitions can confuse maintenance. | NEW | None; consider merging or commenting the split (already partially commented at L4319-4326). |
| `ui/styles.css` | 2660 & 5190 | INFO | Duplicate `.setting-hint-inline` rule | `.setting-hint-inline` is fully defined twice (L2660 `display:block; … margin-top:2px` and L5190 `margin-left:6px; …`). The later block wins for overlapping props (`margin-left` added, `display:block` from L2660 retained since not overridden). Produces a slightly inconsistent box model depending on which props cascade. Cosmetic. | NEW | Merge into one rule. |
| `ui/styles.css` | 2357–2372, 2548–2553, 2562–2371 region | INFO | Unindented rule blocks | A few rule bodies (`.delete-message-btn:hover`, `.edit-message-btn/.delete-message-btn`, `.message-images`) are written flush-left with no indentation, unlike the rest of the file. Purely stylistic; no functional impact. | NEW | Reformat for consistency. |
| `ui/styles.css` | 465, 2654, 3864, 3869, 5364-region | INFO | `:has()` selector reliance | Several rules use `:has()` (`.content:has(#page-chat.active)`, `.chat-message:has(.pin-message-btn.pinned)`, `#chat-files-edit-view .setting-row:has(...)`). Supported in Tauri's WebView2 (Chromium) so fine here; would degrade silently on very old engines. The `color-mix()` usage at L1744 already has an `@supports` fallback (L1755) — `:has()` does not, but it's non-critical styling. | NEW | None for this target; note if ever ported off WebView2. |
| `ui/styles.css` | 4799–4831, 4876–4889 | INFO | Focus-ring handling | `:focus { outline:none }` on inputs is correctly paired with `:focus-visible { outline: 2px solid … }` re-assertion (good a11y practice, explicitly commented L4818-4821). No issue — noted positively. | NEW | None. |
| `ui/assets/faust_base64.txt` | 1 | LOW | Unreferenced asset / supply-chain surface | Single-line valid `data:image/jpeg;base64,…` (decodes to a JPEG; magic bytes `/9j/4AAQ…` = JFIF). **Not referenced by index.html** (`grep` = 0 hits); consumed by `faust_avatar.ts`/`faust_avatar.js`. It is user-controlled-by-build static data; benign. Only risk: a 15 KB base64 blob committed as a raw `.txt` is easy to swap unnoticed (no SRI on JS-imported data). | NEW (sanity check requested). | None required. If avatar integrity matters, hash-check at load. |
| `ui/index.html` | 308–312 | INFO | "Unrestricted" toggle wording | `#chat-unrestricted` checkbox labeled "Unrestricted Mode - Bypass AI restrictions" (and CSS styling at styles.css:3509-3516 turns it red). Not a frontend-asset vulnerability, but worth flagging to the backend reviewer: the UI exposes a guardrail-bypass toggle to the local user; ensure the WS backend authorizes it and that it cannot be driven by a server-pushed message. | NEW (cross-cutting note). | Verify backend gating (out of scope for this file set). |
| `ui/index.html` | 624, 641, 845 | INFO | Inline base64 GIF dataURIs | Three identical 1×1 transparent GIF `src=` placeholders (avatar broken-image defusers). Static constants — safe. Same observation as prior G12 L1340/1674/1692 for the TS side. | carried (INFO) | Optional: extract to a shared constant. |
| `ui/index.html` | 861 | INFO | Module entry at body end | `<script type="module" src="app.js">` loads first-party bundle (not in vendor, not SRI'd — acceptable since it's the app's own code under `'self'`). No inline script anywhere in the document (`grep` for `onclick`/`onerror`/`onload`/`javascript:`/`target=` = 0 hits). ✅ | NEW (positive) | None. |
| `ui/index.html` | 6–11 | INFO | `frame-ancestors` omission documented | The comment correctly explains `frame-ancestors` is ignored in `<meta>` CSP and that the Tauri WebView is not iframe-embeddable. Accurate; intentional omission. | carried | None. |
| `ui/styles.css` | 3076, 3075, 5085 | INFO | `code-copy` / `data-code-copy` styling | CSS styles `.code-copy-btn` etc.; the actual data lives in `data-code-copy` attributes the TS side fills (prior G12 L138 flagged the ~50MB attribute bloat). No CSS-side issue. | carried (TS-side) | None for CSS. |

---

## Cross-check against prior audit (`docs/reviews/audit_2026_05/`)

| Prior ref | Subject | Current status | Current location |
|---|---|---|---|
| MASTER **C3** / G12 CRIT (DOMPurify) | DOMPurify 3.3.3 CVEs | **STILL-PRESENT** | `vendor/dompurify/purify.min.js` banner L1. Bundle still 3.3.3 despite `package.json ^3.4.2`. **Prior fix text "≥3.3.4" is incorrect — real fix is 3.4.0.** |
| G12 HIGH (`tauri.conf.json` CSP `script-src 'self'`, no SRI) | vendor scripts unprotected | **PARTIALLY-FIXED** | SRI now present on all 3 existing vendor scripts (KaTeX×2, DOMPurify) + 2 CSS — verified matching. BUT one SRI (prism-core L37) points to a missing file, and SRI locks the *vulnerable* DOMPurify. |
| G12 HIGH (`connect-src` any-port loopback) | WS allowlist too broad | **STILL-PRESENT** | index.html:12 (`ws://…:* wss://…:*`). |
| G12 §CSP "No `'unsafe-inline'`" (strength) | style-src hardening | **REGRESSED** | index.html:12 now has `style-src 'self' 'unsafe-inline'`. |
| G12 §CSP "No `base-uri 'none'`" / "No `form-action 'none'`" | CSP gaps | **STILL-PRESENT** | index.html:12 still lacks both. |
| G12 §"Vendor versions" (KaTeX/Prism "recommend re-check") | version stamps unknown | **RESOLVED (this audit)** | KaTeX = **0.16.9**; Prism = theme CSS only, **no JS vendored** (and the referenced prism-core.min.js is missing). |

> Note: `tauri.conf.json`'s CSP (prior G12 quoted it) and the `index.html` `<meta>` CSP are two different surfaces. The values now **diverge** on `style-src` (`<meta>` adds `'unsafe-inline'`). Whichever applies at runtime, the auditor should confirm both are aligned and the *effective* policy is the intended one. `tauri.conf.json` was outside this G18 file set — flagged for the Tauri-config reviewer.

---

## Confirmation

I read every line of `index.html` (864) and `styles.css` (5205) in full, inspected the banner/version of every vendored JS and CSS file under `native_dashboard/ui/vendor/`, recomputed all five SRI hashes locally (all match on-disk bytes), confirmed `prism-core.min.js` is absent, and re-verified the DOMPurify fix version (3.4.0, not 3.3.4) against current advisories. `faust_base64.txt` decodes to a benign JPEG and is unreferenced by the HTML. No source file was modified.

### Sources
- [CVE-2026-41238 — GitHub Advisory GHSA-v9jr-rg53-9pgp (fixed in DOMPurify 3.4.0)](https://github.com/advisories/GHSA-v9jr-rg53-9pgp)
- [CVE-2026-41238 — SentinelOne vulnerability DB](https://www.sentinelone.com/vulnerability-database/cve-2026-41238/)
- [CVE-2026-41238 — Snyk SNYK-JS-DOMPURIFY-16132234](https://security.snyk.io/vuln/SNYK-JS-DOMPURIFY-16132234)
- [CVE-2026-41238 — trace37 labs technical write-up (CUSTOM_ELEMENT_HANDLING fallback)](https://labs.trace37.com/blog/dompurify-pp-ceh-bypass/)
- [IBM Security Bulletin — DOMPurify CVE-2026-41238/41239/41240](https://www.ibm.com/support/pages/node/7272438)
