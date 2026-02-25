# Frontend Security & Code Quality Audit Report

**Scope:** All TypeScript/JavaScript/HTML/CSS files in `native_dashboard/`  
**Date:** 2025-07-18  
**Auditor:** Automated Deep Review  

---

## Summary

| Severity | Count |
|----------|-------|
| CRITICAL | 1 |
| HIGH     | 4 |
| MEDIUM   | 8 |
| LOW      | 5 |

---

## CRITICAL

### 1. `withGlobalTauri: false` breaks ALL Tauri IPC calls

**Files:**  
- `tauri.conf.json` — `"withGlobalTauri": false`  
- `src-ts/app.ts` line 37 — comment says `// Use global Tauri API (withGlobalTauri: true in tauri.conf.json)`  
- `src-ts/app.ts` lines 38-42 — `invoke` function accesses `window.__TAURI__?.core?.invoke`

**Issue:**  
The `invoke()` wrapper on line 38 relies on `window.__TAURI__` being available globally. In Tauri v2, this global is only injected when `withGlobalTauri` is `true` in `tauri.conf.json`. The config currently has it set to `false`, meaning `window.__TAURI__` is `undefined` in production builds. Every single Tauri command (`get_status`, `get_db_stats`, `start_bot`, `stop_bot`, `get_logs`, etc.) will silently reject with "Tauri not available".

The app may work during development if the Tauri dev server injects the global regardless, masking this bug until a production build is created.

**Fix — Option A (recommended):** Set `withGlobalTauri` to `true`:

```jsonc
// tauri.conf.json
"app": {
  "withGlobalTauri": true,
  ...
}
```

**Fix — Option B:** Use ES module imports instead of the global:

```typescript
// src-ts/app.ts
import { invoke } from '@tauri-apps/api/core';
```

This requires a bundler (Vite/esbuild) since the current setup compiles TS → JS without bundling.

---

## HIGH

### 2. `ErrorLogger` constructor is public — singleton pattern violated

**File:** `src-ts/app.ts` lines 52-65

```typescript
class ErrorLogger {
    private static instance: ErrorLogger;
    // ...
    static getInstance(): ErrorLogger { ... }
    constructor() {  // ← public constructor
        this.setupGlobalErrorHandlers();
    }
}
```

**Issue:**  
The constructor is public, allowing `new ErrorLogger()` anywhere. Each instantiation calls `setupGlobalErrorHandlers()`, which *overrides* `window.onerror`, `window.onunhandledrejection`, and wraps `console.error`. Multiple instances would create nested `console.error` wrappers, causing infinite recursion (each wrapped `console.error` calls the original which is now the *previous* wrapper).

**Fix:**

```typescript
private constructor() {
    this.setupGlobalErrorHandlers();
}
```

---

### 3. `messages` array grows unboundedly — memory leak in long conversations

**File:** `src-ts/app.ts` — `ChatManager` class

- Line 827: `sendMessage()` → `this.messages.push({ role: 'user', ... })`
- Line 978: `finalizeStreamingMessage()` → `this.messages.push(newMessage)`

**Issue:**  
Every sent and received message is appended to `this.messages` with no upper bound. In a long conversation (hundreds of messages with image attachments), this array grows indefinitely, consuming memory. The `historyToSend` is correctly limited to 20 messages, but the local array is not.

**Fix:**

```typescript
private static readonly MAX_LOCAL_MESSAGES = 200;

// After pushing to this.messages:
if (this.messages.length > ChatManager.MAX_LOCAL_MESSAGES) {
    this.messages = this.messages.slice(-ChatManager.MAX_LOCAL_MESSAGES);
}
```

---

### 4. Missing cleanup on app unload — intervals and WebSocket leak

**File:** `src-ts/app.ts`

- Line 1576: `this.pingInterval = window.setInterval(...)` — ping every 30s, never cleared
- Line 2175: `refreshInterval = window.setInterval(updateStatus, ...)` — never cleared on unload
- Line 2409: `logsRefreshInterval = window.setInterval(loadLogs, 1000)` — never cleared on unload
- WebSocket (`this.ws`) is never closed on window unload

**Issue:**  
When the Tauri window is closed or the WebView navigates away, active intervals and the WebSocket connection are not cleaned up. While the OS reclaims resources on process exit, in development with hot-reload this causes ghost intervals and duplicate WebSocket connections.

**Fix:** Add a cleanup handler:

```typescript
window.addEventListener('beforeunload', () => {
    if (refreshInterval) clearInterval(refreshInterval);
    if (logsRefreshInterval) clearInterval(logsRefreshInterval);
    if (chatManager) {
        if (chatManager.pingInterval) clearInterval(chatManager.pingInterval);
        if (chatManager.reconnectTimeout) clearTimeout(chatManager.reconnectTimeout);
        chatManager.ws?.close();
    }
});
```

Also make `pingInterval` and `reconnectTimeout` accessible or add a `destroy()` method to `ChatManager`.

---

### 5. No user notification when WebSocket reconnection exhausted

**File:** `src-ts/app.ts` lines 520-535

```typescript
scheduleReconnect(): void {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
        console.warn('Max reconnect attempts reached');
        return;  // silently gives up
    }
    // ...
}
```

**Issue:**  
After 5 failed reconnections, the chat silently stops attempting to connect. The user sees "🔴 Connecting..." forever with no indication that reconnection has been abandoned. The chat input remains enabled but messages will be silently dropped by `send()`.

**Fix:**

```typescript
if (this.reconnectAttempts >= this.maxReconnectAttempts) {
    console.warn('Max reconnect attempts reached');
    showToast('Connection lost. Please restart the bot and refresh.', { type: 'error', duration: 10000 });
    this.setInputEnabled(false);
    return;
}
```

---

## MEDIUM

### 6. Sakura petal `setInterval` never cleared — DOM churn when not visible

**File:** `src-ts/app.ts` line 2016

```typescript
setInterval(createPetal, 1000);
```

**Issue:**  
The petal creation interval runs continuously, even when the page is not visible (e.g., the app is minimized or the user is on a different tab). Each tick creates a DOM element, sets CSS animations, and schedules a cleanup timeout. Over hours, this adds up to thousands of unnecessary DOM operations.

**Fix:** Store the interval ID and clear it when the app is hidden:

```typescript
const petalInterval = setInterval(createPetal, 1000);

document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
        clearInterval(petalInterval);
    } else {
        // restart if needed
    }
});
```

---

### 7. Log viewer causes DOM flickering — full innerHTML reset every second

**File:** `src-ts/app.ts` lines 2417-2440

```typescript
container.innerHTML = '';
container.appendChild(fragment);
```

**Issue:**  
Every 1 second (when on the logs page), the entire log container is cleared via `innerHTML = ''` and rebuilt with a new `DocumentFragment`. Even when no new logs exist (`hasNewLogs` is false), the DOM is still fully reconstructed. This causes visual flickering and unnecessary layout recalculation with 200 log lines.

**Fix:** Skip the rebuild when there are no new logs:

```typescript
if (!hasNewLogs && container.childElementCount > 0) {
    return; // No changes, skip rebuild
}
```

---

### 8. `localStorage` quota risk from base64 avatar storage

**File:** `src-ts/app.ts` lines 1588-1600 (settings defaults) and line 1774 (`saveSettings()`)

**Issue:**  
The `settings` object stores two base64-encoded avatar images (`userAvatar` and `aiAvatar`), each up to ~300KB as PNG data URLs from the 200x200 canvas crop. The default `aiAvatar` alone is ~3KB (JPEG). Combined with other settings, this approaches localStorage limits (typically 5-10MB per origin in most browsers/WebView2). Failed `localStorage.setItem()` throws a `QuotaExceededError` that is only caught generically.

**Fix:** Add explicit size checking:

```typescript
function saveSettings(): void {
    try {
        const json = JSON.stringify(settings);
        if (json.length > 4 * 1024 * 1024) { // 4MB safety limit
            console.warn('Settings too large, skipping avatar data');
            const slimSettings = { ...settings, userAvatar: '', aiAvatar: '' };
            localStorage.setItem('dashboard-settings', JSON.stringify(slimSettings));
            return;
        }
        localStorage.setItem('dashboard-settings', json);
    } catch (e) {
        if (e instanceof DOMException && e.name === 'QuotaExceededError') {
            showToast('Storage full. Avatar removed to save space.', { type: 'warning' });
            settings.userAvatar = '';
            settings.aiAvatar = '';
            localStorage.setItem('dashboard-settings', JSON.stringify(settings));
        } else {
            console.warn('Failed to save settings:', e);
        }
    }
}
```

---

### 9. Unused settings properties — dead code

**File:** `src-ts/app.ts`

- `Settings.chartHistory` (line ~204) — defaults to `60`, but `MAX_CHART_POINTS = 60` is hardcoded at line 1593. The setting is never referenced in chart logic.
- `Settings.autoScroll` (line ~200) — defined in the interface and defaults, but the actual auto-scroll state is the separate variable `logsAutoScrollEnabled` (line 1589). The setting is never read or written.

**Fix:** Either remove the dead properties or wire them up:

```typescript
// Option A: Remove
interface Settings {
    theme: 'dark' | 'light';
    refreshInterval: number;
    // autoScroll: boolean;  ← remove
    notifications: boolean;
    // chartHistory: number; ← remove
    userName: string;
    // ...
}

// Option B: Use them
const MAX_CHART_POINTS = settings.chartHistory;
let logsAutoScrollEnabled = settings.autoScroll;
```

---

### 10. Non-null assertion in closure — potential runtime crash

**File:** `src-ts/app.ts` line 2007

```typescript
container!.appendChild(petal);
```

**Issue:**  
The `container` variable is checked at the top of `initSakuraAnimation()` (line 1920), but the `createPetal()` closure captures it by reference and uses the TypeScript non-null assertion `!`. If the DOM element `#sakura-container` is ever removed after initialization (e.g., during a page transition), this would throw an uncaught error inside a `setInterval` callback.

**Fix:** Replace the assertion with a null check:

```typescript
if (container) {
    container.appendChild(petal);
}
```

---

### 11. Code block regex fragile with embedded triple backticks

**File:** `src-ts/app.ts` lines 1268-1272

```typescript
html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (_match, lang, code) => {
    const idx = codeBlocks.length;
    codeBlocks.push(`<pre><code class="language-${lang}">${code}</code></pre>`);
    return `${codePlaceholder}${idx}\x01`;
});
```

**Issue:**  
The non-greedy `[\s\S]*?` will match the first closing ` ``` `, which is correct in most cases. However:
1. The regex requires `\n` after the opening backticks — a code block like ` ```python ` (space before language) won't match.
2. More critically, the code block content (`code` captured group) is already HTML-escaped from the `escapeHtml()` call on line 1267, but `lang` comes from the same escaped text. If a language identifier somehow contained `&amp;` or similar entities, it would render incorrectly in the class attribute.
3. No handling for code blocks that don't have a closing ` ``` ` — they'll be treated as plain text with visible backticks.

**No immediate security risk** (lang is constrained by `\w*`), but edge cases will render incorrectly.

---

### 12. `cropImage.onload` may not fire for cached images

**File:** `src-ts/app.ts` line 2710

```typescript
cropImage.onload = () => { /* dimension calculation */ };
cropImage.src = imageUrl;
```

**Issue:**  
If the image is already cached by the browser (e.g., user re-opens the crop modal for the same image), `onload` may fire synchronously before the handler is attached, or may not fire at all in some browsers. This would leave `cropState.imgWidth` and `cropState.imgHeight` at 0, making the crop preview invisible.

**Fix:** Check if the image is already loaded:

```typescript
cropImage.onload = () => { /* ... */ };
cropImage.src = imageUrl;
if (cropImage.complete && cropImage.naturalWidth > 0) {
    cropImage.onload(new Event('load')); // or just call the setup logic directly
}
```

---

## LOW

### 13. WebSocket uses unencrypted `ws://` protocol

**File:** `src-ts/app.ts` line 462

```typescript
this._connectWithUrl('ws://127.0.0.1:8765/ws');
```

**Issue:**  
The WebSocket connection is unencrypted. While `127.0.0.1` limits exposure to the local machine, other local processes or users on the same machine could intercept the traffic. The token authentication sent as the first message (line 470) would be visible in plaintext.

**Risk:** Low — this is localhost-only communication. Using `wss://` would require TLS certificate configuration on the bot's WebSocket server.

---

### 14. `DataCache` uses lazy eviction only

**File:** `src-ts/app.ts` lines 216-237

**Issue:**  
Cache entries are only checked for expiry on `get()`. Entries set but never subsequently read will persist in the Map indefinitely. With short TTLs (1.5s for status, 3s for dbStats), this is not a practical memory concern, but it's poor practice.

**Fix (optional):** Add periodic cleanup:

```typescript
constructor() {
    setInterval(() => {
        const now = Date.now();
        for (const [key, entry] of this.cache) {
            if (now - entry.timestamp > entry.ttl) {
                this.cache.delete(key);
            }
        }
    }, 30000);
}
```

---

### 15. Confusing variable naming — `refreshInterval` shadows settings property

**File:** `src-ts/app.ts`

- Line 1588: `let refreshInterval: number | null = null;` — the setInterval timer ID
- `settings.refreshInterval` — the interval duration in ms

Both use the name "refreshInterval" for different things. This increases maintenance risk.

**Fix:** Rename the timer ID:

```typescript
let refreshTimerId: number | null = null;
```

---

### 16. CSP allows CDN script execution

**File:** `tauri.conf.json` — CSP configuration

```
script-src 'self' https://cdn.jsdelivr.net/npm/katex@0.16.9/
```

**Observation:**  
While the KaTeX version is pinned and SRI hashes are used in `index.html` (`integrity="sha384-..."`), the CSP `script-src` directive allows *any* script from the `katex@0.16.9` CDN path. If jsDelivr were compromised, additional scripts under that path prefix could be loaded. The SRI hashes on the existing `<script>` tags only protect those specific tags — dynamically created script elements pointing to other files under the same CDN path would be allowed by CSP.

**Risk:** Low — requires CDN compromise and a way to inject `<script>` tags into the DOM.

---

### 17. `send()` silently drops messages when disconnected

**File:** `src-ts/app.ts` lines 540-544

```typescript
send(data: object): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify(data));
    }
}
```

**Issue:**  
When the WebSocket is not connected, `send()` silently discards the message. Operations like `save_memory`, `delete_memory`, `save_profile`, `new_conversation`, etc. will appear to succeed (no error shown) but the server never receives them.

**Fix:** Show feedback on failed sends:

```typescript
send(data: object): boolean {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify(data));
        return true;
    }
    showToast('Not connected to server', { type: 'warning' });
    return false;
}
```

---

## Build & Configuration Notes

### `tsconfig.json`

- **`sourceMap: true`** — Source maps are generated. For production builds, consider disabling to avoid exposing TypeScript source.
- **`strict: true`** — Good. All strict checks enabled.
- **`moduleResolution: "bundler"`** — Set for a bundler, but no bundler is configured. The project compiles TS directly to JS via `tsc`. This works because "bundler" resolution is lenient, but "node16" or "nodenext" would be more accurate.

### `package.json`

- **All dependencies are `devDependencies`** — `@tauri-apps/api` is listed as a devDependency but is used at runtime (via the global or if bundled). This is fine for the current global-access pattern but would break if switching to ES module imports without a bundler.

### Compiled Output Drift

- `src-ts/app.ts` (3063 lines) compiles to `ui/app.js` (2649 lines). The JS file appears to be a valid compilation of the TS source. However, the JS file includes `//# sourceMappingURL=app.js.map` at the end — ensure `app.js.map` is excluded from production distributions.

---

## Security Posture Summary

| Category | Status |
|----------|--------|
| XSS via innerHTML | **Mitigated** — `escapeHtml()` applied to all user-controlled data before innerHTML insertion. KaTeX `renderToString` with `throwOnError: false` is safe. |
| CSP compliance | **Good** — No inline event handlers, all listeners via `addEventListener`. CSP configured in Tauri config. |
| WebSocket auth | **Acceptable** — Token-based auth sent as first message (not in URL to avoid log leakage). |
| Input validation | **Adequate** — File size limits on avatars (5MB), image count limits (5), error queue size limit (100). |
| DOM sanitization | **Good** — `renderMemories()`, `renderConversationList()`, `renderMessages()`, `showToast()` all escape user content. Code blocks properly handled. |
| Event listener cleanup | **Mostly good** — Crop modal properly cleans up document-level listeners. Petal animation uses object pool. innerHTML replacement handles listener cleanup for re-rendered content. |

---

*End of report.*
