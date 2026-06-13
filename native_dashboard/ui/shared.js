/**
 * Shared utilities and state for the dashboard application.
 * Imported by both app.ts and chat-manager.ts — no circular dependencies.
 */
import { DEFAULT_AI_AVATAR } from './faust_avatar.js';
// Resolve invoke at call time. ``withGlobalTauri`` is OFF (tauri.conf.json), so
// the app no longer exposes ``window.__TAURI__`` to every script context — a
// same-origin XSS can't reach ``invoke`` to call privileged commands. IPC goes
// through the dynamic ``import('@tauri-apps/api/core')`` below, which the webview
// resolves via the import map in ``index.html`` (the bare specifier → the locally
// vendored ESM build under ``ui/vendor/tauri/``; the inline import map is
// hash-allowlisted in the CSP). A failed import is caught and surfaced as a clear
// rejection, not a crashed module — and reverting is just flipping
// ``withGlobalTauri`` back to true (the window branch below then serves IPC).
//
// The ``window.__TAURI__`` branch is kept FIRST for Playwright e2e fixtures
// (``mock-tauri.ts``) that inject a fake global before page scripts; in the real
// app it's undefined and we fall through to the import.
export const invoke = async (cmd, args) => {
    // Guard `typeof window` — vitest can fire setTimeout callbacks after
    // the JSDOM environment has been torn down, leaving `window` undefined.
    if (typeof window !== 'undefined' && window.__TAURI__?.core?.invoke) {
        return window.__TAURI__.core.invoke(cmd, args);
    }
    try {
        const tauriCore = await import('@tauri-apps/api/core');
        return tauriCore.invoke(cmd, args);
    }
    catch {
        console.warn('Tauri not available, using mock');
        return Promise.reject(new Error('Tauri not available'));
    }
};
// ============================================================================
// Error Logger - Logs frontend errors to file for debugging
// ============================================================================
export class ErrorLogger {
    static getInstance() {
        if (!ErrorLogger.instance) {
            ErrorLogger.instance = new ErrorLogger();
        }
        return ErrorLogger.instance;
    }
    // Private: must use getInstance() to avoid duplicate console.error wrappers
    // (each new instance would re-wrap and could cause infinite recursion).
    constructor() {
        this.errorQueue = [];
        this.isProcessing = false;
        this.maxQueueSize = 100; // Prevent unbounded growth
        this.setupGlobalErrorHandlers();
    }
    setupGlobalErrorHandlers() {
        // Use ``addEventListener`` rather than ``window.onerror = ...``.
        // The assignment form REPLACES any prior handler (Tauri's own
        // dev error reporter, third-party telemetry shims, browser
        // devtools). addEventListener stacks alongside them, so the
        // dashboard's logger doesn't blackhole errors that the host
        // tooling expects to see.
        window.addEventListener('error', (event) => {
            const error = event.error;
            this.log('UNCAUGHT_ERROR', String(event.message), error?.stack || `at ${event.filename}:${event.lineno}:${event.colno}`);
        });
        window.addEventListener('unhandledrejection', (event) => {
            const reason = event.reason;
            const message = reason?.message || String(reason);
            const stack = reason?.stack || 'No stack trace';
            this.log('UNHANDLED_REJECTION', message, stack);
        });
        // Override console.error to also log to file. The override
        // can recurse into itself if any code path inside the
        // ``catch`` triggers a fresh ``console.error`` (e.g. an Error
        // toString that throws, or a JSON serialization helper that
        // logs). The ``inOverride`` re-entry guard breaks the loop —
        // when re-entrance is detected we fall straight through to
        // the original ``console.error`` without any of our extra
        // bookkeeping.
        const originalConsoleError = console.error;
        let inOverride = false;
        console.error = (...args) => {
            if (inOverride) {
                originalConsoleError.apply(console, args);
                return;
            }
            inOverride = true;
            try {
                originalConsoleError.apply(console, args);
                const message = args.map(arg => {
                    if (arg instanceof Error)
                        return arg.message;
                    if (typeof arg === 'object') {
                        try {
                            return JSON.stringify(arg).substring(0, 500);
                        }
                        catch {
                            return '[Object]';
                        }
                    }
                    return String(arg).substring(0, 500);
                }).join(' ');
                const stack = args.find(arg => arg instanceof Error)?.stack?.substring(0, 1000);
                this.log('CONSOLE_ERROR', message, stack);
            }
            catch {
                originalConsoleError.apply(console, ['ErrorLogger override failed']);
            }
            finally {
                inOverride = false;
            }
        };
    }
    async log(errorType, message, stack) {
        // Drop oldest errors if queue is full to prevent memory leak
        if (this.errorQueue.length >= this.maxQueueSize) {
            this.errorQueue.shift(); // Remove oldest
        }
        this.errorQueue.push({ type: errorType, message, stack });
        this.processQueue().catch(() => { });
    }
    async processQueue() {
        if (this.isProcessing || this.errorQueue.length === 0)
            return;
        this.isProcessing = true;
        while (this.errorQueue.length > 0) {
            const error = this.errorQueue.shift();
            if (error) {
                try {
                    // Defer the invoke onto a fresh task so any synchronous
                    // console.error inside the IPC path can't recurse back
                    // into this loop while we're still draining it.
                    await new Promise((resolve) => {
                        setTimeout(() => {
                            invoke('log_frontend_error', {
                                errorType: error.type,
                                message: error.message,
                                stack: error.stack || null,
                            }).then(() => resolve()).catch(() => resolve());
                        }, 0);
                    });
                }
                catch (_e) {
                    // Unreachable in practice — the awaited executor resolves on
                    // both the .then and .catch of invoke(), so it never rejects.
                    // Kept as defence in depth; errors are already swallowed above.
                }
            }
        }
        this.isProcessing = false;
    }
    async getErrors(count = 20) {
        try {
            return await invoke('get_dashboard_errors', { count });
        }
        catch {
            return ['Failed to fetch errors'];
        }
    }
    async clearErrors() {
        try {
            await invoke('clear_dashboard_errors');
        }
        catch (e) {
            console.warn('Failed to clear error log:', e);
        }
    }
}
// Initialize error logger early
export const errorLogger = ErrorLogger.getInstance();
// ============================================================================
// HTML Escape Utility
// ============================================================================
export function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML.replace(/"/g, '&quot;').replace(/'/g, '&#39;').replace(/`/g, '&#96;');
}
/**
 * Test whether a URL is safe to use as an <img src>. Allows data:image/,
 * https:, tauri/asset schemes, and same-origin relative paths. Rejects
 * javascript:, vbscript:, file: and other dangerous schemes.
 *
 * Defense-in-depth: avatars in this app come from canvas.toDataURL() locally,
 * but localStorage can be tampered with, so we validate before rendering.
 *
 * CAVEAT — validator allowlist is WIDER than the effective CSP. The app CSP
 * (img-src 'self' data: blob:, in tauri.conf.json and ui/index.html) only
 * permits data:, blob: and same-origin paths. So an avatar that passes this
 * check with an https:/asset:/tauri: scheme is silently blocked by CSP at
 * render and never displays, even though isSafeAvatarUrl returns true. Only
 * data:/blob:/same-origin actually render (canvas data: URIs are the working
 * path today). If you ever need https/asset/tauri avatars to show, widen
 * img-src in BOTH CSP locations to match; otherwise keep them in sync to avoid
 * 'valid but invisible' avatars.
 */
export function isSafeAvatarUrl(url) {
    if (!url || typeof url !== 'string')
        return false;
    const trimmed = url.trim();
    const lower = trimmed.toLowerCase();
    if (!lower)
        return false;
    // Tauri custom-protocol URLs need a stricter allowlist than http/https.
    // Restrict the path portion to a known prefix so a tampered avatar string
    // can't read arbitrary files on disk (e.g. ``asset://localhost/c:/...``).
    if (lower.startsWith('asset://') || lower.startsWith('tauri://')) {
        try {
            // Validate the ORIGINAL-cased trimmed URL — the exact string
            // safeAvatarUrl renders — and lowercase only the host/prefix
            // comparisons, so we never validate one string and render another.
            const parsed = new URL(trimmed);
            const path = parsed.pathname || '';
            // Reject Windows drive letters, parent-dir traversal, and any
            // host other than localhost. Only allow paths under ``avatars/``.
            if (parsed.hostname && parsed.hostname.toLowerCase() !== 'localhost')
                return false;
            if (/[a-z]:/i.test(path))
                return false;
            if (path.includes('..'))
                return false;
            const stripped = path.replace(/^\/+/, '');
            return stripped.toLowerCase().startsWith('avatars/');
        }
        catch {
            return false;
        }
    }
    // SVG data URIs are dangerous: <svg onload=...> embedded in src
    // doesn't execute in <img>, but if the same URL ever flows to a
    // background-image, iframe.src, or a future component that fetches
    // and inlines, the script in the SVG runs. Reject explicitly so the
    // allowlist is unambiguous and future-proof.
    if (lower.startsWith('data:image/svg+xml') ||
        lower.startsWith('data:image/svg ') ||
        lower.startsWith('data:image/svg;')) {
        return false;
    }
    // No plain http:// — a tampered/server-pushed avatar string of
    // http://attacker/pixel becomes a plaintext IP+User-Agent beacon on the
    // next render (no script needed). Legit avatars are local canvas data:
    // URIs or https; keep those plus same-origin relative paths only.
    // Same-origin relative paths only. Reject '../' — it serves no legitimate
    // avatar purpose and is a traversal-shaped string we don't want flowing
    // into an <img src> within the webview's asset scope. Legit avatars are
    // local canvas data: URIs, https, or './'/'/' same-origin paths.
    // Reject protocol-relative URLs ('//host/...') BEFORE the single-'/'
    // same-origin check: '//attacker.com/pixel' starts with '/' but resolves
    // to an EXTERNAL host, defeating the no-external-beacon rule above.
    // Normalize backslashes to forward slashes first: under WHATWG special
    // schemes (http/https — what Tauri's WebView2 uses, http://tauri.localhost)
    // the URL parser treats '\\' as '/', so '/\\evil.com/pixel' would NOT start
    // with '//' yet resolves to the external host evil.com. Test the normalized
    // form against both the '//' reject and the '/' same-origin allow.
    const norm = lower.replace(/\\/g, '/');
    if (norm.startsWith('//')) {
        return false;
    }
    return (lower.startsWith('data:image/') ||
        lower.startsWith('https://') ||
        norm.startsWith('/') ||
        lower.startsWith('./'));
}
/**
 * Returns the URL HTML-escaped for safe use inside an innerHTML template
 * attribute (e.g. `<img src="${safeAvatarUrl(x)}">`). Returns empty string
 * for unsafe schemes. Do NOT use this for `element.src = ...` (use
 * `isSafeAvatarUrl` + raw value for property assignment).
 */
export function safeAvatarUrl(url) {
    if (!isSafeAvatarUrl(url))
        return '';
    return escapeHtml(url.trim());
}
// ============================================================================
// Settings
// ============================================================================
export let settings = {
    theme: 'dark',
    refreshInterval: 2000,
    autoScroll: true,
    notifications: true,
    chartHistory: 60,
    userName: 'You',
    userAvatar: '',
    aiAvatar: DEFAULT_AI_AVATAR,
    isCreator: false,
    sakuraEnabled: true,
    soundEnabled: false,
    hapticEnabled: false,
    lastConversationId: null,
};
export function loadSettings() {
    try {
        const saved = localStorage.getItem('dashboard-settings');
        if (saved) {
            const defaultAiAvatar = settings.aiAvatar; // Keep default Faust avatar
            settings = { ...settings, ...JSON.parse(saved) };
            // Defensive: a corrupt/tampered localStorage blob must not poison
            // runtime. Coerce the fields that drive timers / the theme attr /
            // chart buffers, so e.g. a string or negative refreshInterval can't
            // become setInterval(…, NaN) → a 0ms runaway loop, or an unknown
            // theme silently break styling. (try/catch above only guards the
            // JSON parse, not the shape.)
            const VALID_INTERVALS = [1000, 2000, 5000, 10000];
            if (typeof settings.refreshInterval !== 'number' ||
                !VALID_INTERVALS.includes(settings.refreshInterval)) {
                settings.refreshInterval = 2000;
            }
            if (settings.theme !== 'dark' && settings.theme !== 'light') {
                settings.theme = 'dark';
            }
            if (typeof settings.chartHistory !== 'number' ||
                !Number.isFinite(settings.chartHistory) ||
                settings.chartHistory < 10 ||
                settings.chartHistory > 600) {
                settings.chartHistory = 60;
            }
            // Migration: Only set default Faust avatar if saved aiAvatar is empty/undefined
            // Don't override custom avatars that users have set
            if (!settings.aiAvatar) {
                settings.aiAvatar = defaultAiAvatar;
                saveSettings(); // Save the migration
            }
        }
    }
    catch (e) {
        console.warn('Failed to load settings:', e);
    }
}
export function saveSettings() {
    try {
        localStorage.setItem('dashboard-settings', JSON.stringify(settings));
    }
    catch (e) {
        // Quota exceeded usually means avatar(s) blew the localStorage cap
        // (~5-10MB depending on engine). Drop them so the rest of the settings
        // still persist; user-set avatars can be re-uploaded.
        if (e instanceof DOMException && (e.name === 'QuotaExceededError' || e.code === 22)) {
            console.warn('Settings quota exceeded — clearing avatars and retrying');
            settings.userAvatar = '';
            settings.aiAvatar = '';
            try {
                localStorage.setItem('dashboard-settings', JSON.stringify(settings));
                showToast('Storage full — avatars were cleared to free space.', { type: 'warning' });
            }
            catch {
                console.warn('Failed to save settings even after dropping avatars');
            }
        }
        else {
            console.warn('Failed to save settings:', e);
        }
    }
}
// ============================================================================
// Toast Notification System
// ============================================================================
export function initToastContainer() {
    if (!document.getElementById('toast-container')) {
        const container = document.createElement('div');
        container.id = 'toast-container';
        document.body.appendChild(container);
    }
}
/**
 * Show a confirmation dialog that works reliably in Tauri v2 WebView2.
 * Falls back to Tauri's dialog plugin command, then to native confirm().
 */
export async function showConfirmDialog(message) {
    try {
        // Try Tauri dialog plugin first (most reliable in desktop apps)
        const result = await invoke('show_confirm_dialog', { message });
        return result;
    }
    catch {
        // Fallback to browser confirm() if Tauri command not available
        return confirm(message);
    }
}
export function showToast(message, options = { type: 'info' }) {
    // Errors and warnings always surface — they report real failures (bot
    // start failed, load failed, connection lost, …) the user must see even
    // with notifications muted. Only info/success toasts respect the toggle.
    if (!settings.notifications && options.type !== 'error' && options.type !== 'warning') {
        return;
    }
    const container = document.getElementById('toast-container');
    if (!container)
        return;
    const toast = document.createElement('div');
    toast.className = `toast toast-${options.type}`;
    // a11y: errors interrupt (assertive alert); the container's polite
    // live region announces the rest. Without any role, AT users never hear
    // success/error feedback.
    if (options.type === 'error') {
        toast.setAttribute('role', 'alert');
        toast.setAttribute('aria-live', 'assertive');
    }
    const icons = {
        success: '\u2705',
        error: '\u274C',
        warning: '\u26A0\uFE0F',
        info: '\u2139\uFE0F'
    };
    // ?? '' so an unknown ``options.type`` doesn't render the literal
    // string "undefined" into the toast \u2014 falls back to a silent icon.
    toast.innerHTML = `
        <span class="toast-icon">${icons[options.type] ?? ''}</span>
        <span class="toast-message">${escapeHtml(message)}</span>
        <button class="toast-close" aria-label="Dismiss">\u00D7</button>
    `;
    // Use addEventListener instead of inline onclick (CSP blocks inline scripts)
    toast.querySelector('.toast-close')?.addEventListener('click', () => toast.remove());
    container.appendChild(toast);
    // Animate in
    requestAnimationFrame(() => {
        toast.classList.add('toast-visible');
    });
    // Auto remove
    const duration = options.duration ?? 4000;
    setTimeout(() => {
        toast.classList.remove('toast-visible');
        toast.classList.add('toast-hiding');
        setTimeout(() => toast.remove(), 300);
    }, duration);
}
const _interactionState = { bound: false };
/**
 * Bind all 3D interaction handlers exactly once. Call from app init after
 * DOMContentLoaded. Idempotent — subsequent calls no-op.
 *
 * Bundled: click ripple, cursor-tracking card tilt, send-button pulse,
 * sakura parallax, optional click sound, optional haptic feedback.
 */
export function setup3DInteractions() {
    if (_interactionState.bound)
        return;
    _interactionState.bound = true;
    setupButtonRipple();
    setupCardTilt();
    setupSendButtonPulse();
    setupSakuraParallax();
}
/**
 * Click ripple: delegated at document level. Works for any button-like element
 * currently on the page OR added later. Skips disabled buttons.
 *
 * Also fires optional sound + haptic feedback (respects user settings).
 */
// Per-element marker: any element we've already checked + patched once gets
// added to this set, so we skip the (expensive) ``getComputedStyle`` call on
// subsequent clicks. ``WeakSet`` lets garbage collection reclaim removed
// elements automatically.
const _rippleCheckedElements = new WeakSet();
function setupButtonRipple() {
    document.addEventListener('click', (e) => {
        const target = e.target;
        if (!target)
            return;
        const btn = target.closest('.btn, .nav-item, .modal-close, .btn-icon, .role-card');
        if (!btn)
            return;
        // Respect disabled state (both HTML attr and aria-disabled)
        if (btn.hasAttribute('disabled') || btn.getAttribute('aria-disabled') === 'true')
            return;
        const rect = btn.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;
        const size = Math.max(rect.width, rect.height) * 1.6;
        const ripple = document.createElement('span');
        ripple.className = 'btn-ripple';
        ripple.style.width = `${size}px`;
        ripple.style.height = `${size}px`;
        ripple.style.left = `${x - size / 2}px`;
        ripple.style.top = `${y - size / 2}px`;
        // position:absolute ripple needs a positioned parent — ensure buttons
        // without explicit position still contain the ripple. Most already do
        // via .btn { position: relative } in the base styles.
        // ``getComputedStyle`` forces layout, so we only call it the first
        // time we see each element; the WeakSet remembers the verdict.
        if (!_rippleCheckedElements.has(btn)) {
            const computedPos = getComputedStyle(btn).position;
            if (computedPos === 'static')
                btn.style.position = 'relative';
            _rippleCheckedElements.add(btn);
        }
        btn.appendChild(ripple);
        ripple.addEventListener('animationend', () => ripple.remove(), { once: true });
        // Backstop in case animationend never fires (browser tab suspend, animation
        // interrupted by reflow, prefers-reduced-motion). Without this the ripple
        // <span> would linger in the DOM forever and slowly leak nodes.
        setTimeout(() => ripple.remove(), 1000);
        // Concurrent sensory feedback (both cheap, both no-op if disabled)
        playClickSound();
        hapticTick();
    });
}
/**
 * Mouse-follow 3D tilt for `.stat-card` and `.role-card`.
 *
 * Uses rAF-throttled pointermove so we only touch the transform once per
 * frame even if events fire faster. Skipped on coarse (touch-only) pointers
 * to avoid unwanted tilt when scrolling with a finger.
 */
function setupCardTilt() {
    if (window.matchMedia('(hover: none)').matches)
        return;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches)
        return;
    const selector = '.stat-card, .role-card';
    // ``WeakMap<card, AbortController>`` so both the listeners AND the
    // bookkeeping entry are GC'd together when the card element drops out
    // of the DOM and any other reference dies. Without an AbortController
    // the per-card pointermove/leave listeners kept the card alive in
    // memory even after it had been detached from the document, so a long
    // session that re-rendered role cards N times retained N×listeners
    // worth of closure state.
    const controllers = new WeakMap();
    const bindTo = (card) => {
        if (controllers.has(card))
            return;
        const ctrl = new AbortController();
        controllers.set(card, ctrl);
        let raf = 0;
        const onMove = (e) => {
            const rect = card.getBoundingClientRect();
            const nx = (e.clientX - rect.left) / rect.width; // 0..1
            const ny = (e.clientY - rect.top) / rect.height;
            const tiltX = (ny - 0.5) * -10; // X rotation in deg
            const tiltY = (nx - 0.5) * 10;
            cancelAnimationFrame(raf);
            raf = requestAnimationFrame(() => {
                card.style.transform =
                    `perspective(1000px) rotateX(${tiltX.toFixed(2)}deg) ` +
                        `rotateY(${tiltY.toFixed(2)}deg) translateZ(12px)`;
            });
        };
        const onLeave = () => {
            cancelAnimationFrame(raf);
            card.style.transform = '';
        };
        const opts = { signal: ctrl.signal };
        card.addEventListener('pointermove', onMove, opts);
        card.addEventListener('pointerleave', onLeave, opts);
    };
    const unbindFrom = (card) => {
        const ctrl = controllers.get(card);
        if (ctrl) {
            ctrl.abort();
            controllers.delete(card);
        }
        card.style.transform = '';
    };
    // Bind to existing + observe for new ones added by dynamic rendering.
    document.querySelectorAll(selector).forEach(bindTo);
    const observer = new MutationObserver((mutations) => {
        for (const m of mutations) {
            m.addedNodes.forEach((node) => {
                if (!(node instanceof HTMLElement))
                    return;
                if (node.matches?.(selector))
                    bindTo(node);
                node.querySelectorAll?.(selector).forEach(bindTo);
            });
            m.removedNodes.forEach((node) => {
                // Detached cards drag listeners along; abort the per-card
                // signal so the closure can be GC'd. The browser already
                // disconnects listeners when an element is removed, but the
                // listener closure keeps the element reachable from the
                // observer's perspective until aborted.
                if (!(node instanceof HTMLElement))
                    return;
                if (node.matches?.(selector))
                    unbindFrom(node);
                node.querySelectorAll?.(selector).forEach(unbindFrom);
            });
        }
    });
    // Scope the observer to the dynamic regions that actually render new
    // role/status cards instead of the entire <body>. Observing all of
    // document.body fires the callback on every chat re-render, every sakura
    // petal append/remove, every toast, every log refresh — pure CPU waste
    // that grows with session length. Falling back to body only if no
    // narrower target is found.
    const scope = document.getElementById('role-cards-container') ||
        document.getElementById('main-content') ||
        document.body;
    observer.observe(scope, { childList: true, subtree: true });
    // Disconnect on unload so the observer + its closure aren't held for the
    // page lifetime.
    window.addEventListener('beforeunload', () => observer.disconnect(), { once: true });
}
/**
 * Toggle `.has-content` on the send button so its glow pulses when the
 * chat input isn't empty. Cheap state sync on every keystroke.
 */
function setupSendButtonPulse() {
    const input = document.getElementById('chat-input');
    const btn = document.getElementById('btn-send');
    if (!input || !btn)
        return;
    const update = () => {
        btn.classList.toggle('has-content', input.value.trim().length > 0);
    };
    input.addEventListener('input', update);
    update();
}
/**
 * Sakura parallax — petals drift slightly opposite to the cursor so the
 * falling animation feels like it's floating in a 3D world. We set CSS
 * custom properties on the container; the container has
 * `transform: translate(var(--parallax-x), var(--parallax-y))` so all
 * petals shift in unison. rAF-throttled; only runs if sakura is enabled.
 */
function setupSakuraParallax() {
    if (window.matchMedia('(hover: none)').matches)
        return;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches)
        return;
    const container = document.getElementById('sakura-container');
    if (!container)
        return;
    // AbortController so the global pointermove listener can be unbound on
    // page tear-down. Without it the listener (+ its closure capturing
    // ``container``) stays alive for the document's whole lifetime even
    // after navigating away from the chat page, keeping every petal-field
    // DOM node it referenced reachable.
    let raf = 0;
    const STRENGTH = 20; // max px the whole petal field shifts by
    const ctrl = new AbortController();
    window.addEventListener('pointermove', (e) => {
        const nx = (e.clientX / window.innerWidth) - 0.5; // -0.5..0.5
        const ny = (e.clientY / window.innerHeight) - 0.5;
        cancelAnimationFrame(raf);
        raf = requestAnimationFrame(() => {
            // Negative so petals drift OPPOSITE to mouse — feels like parallax layers behind
            container.style.setProperty('--parallax-x', `${(-nx * STRENGTH).toFixed(2)}px`);
            container.style.setProperty('--parallax-y', `${(-ny * STRENGTH * 0.5).toFixed(2)}px`);
        });
    }, { passive: true, signal: ctrl.signal });
    window.addEventListener('beforeunload', () => {
        ctrl.abort();
        cancelAnimationFrame(raf);
    }, { once: true });
}
export function animateNumber(el, to, options = {}) {
    if (!el)
        return;
    if (!Number.isFinite(to))
        return;
    const duration = options.duration ?? 700;
    const prefix = options.prefix ?? '';
    const suffix = options.suffix ?? '';
    const useLocale = options.locale !== false;
    // Auto-detect decimals from target value if not specified. Clamp to 2 so a
    // float artifact (e.g. 85.40000000000001 → ~14 digits) can't blow up the
    // rendered fraction-digit count; 2 covers the dashboard's display needs.
    const decimals = options.decimals ?? (Number.isInteger(to) ? 0 : Math.min(to.toString().split('.')[1]?.length ?? 0, 2));
    // Read the current value from a stored numeric attribute, NOT by parsing
    // the rendered text. formatN uses the OS locale, so on locales that group
    // with '.' (de-DE, pt-BR, id-ID…) re-parsing "1.234" gave 1.234 and the
    // no-op check below never matched → perpetual re-animation.
    const current = Number(el.dataset.animValue ?? '') || 0;
    if (current === to) {
        el.dataset.animValue = String(to);
        return;
    }
    el.dataset.animValue = String(to);
    // Respect reduced motion — just set the final value
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
        el.textContent = prefix + formatN(to, decimals, useLocale) + suffix;
        return;
    }
    const start = performance.now();
    const step = (now) => {
        const t = Math.min((now - start) / duration, 1);
        // ease-out-expo: matches CSS motion system
        const eased = t === 1 ? 1 : 1 - Math.pow(2, -10 * t);
        const v = current + (to - current) * eased;
        el.textContent = prefix + formatN(v, decimals, useLocale) + suffix;
        if (t < 1)
            requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
}
function formatN(v, decimals, locale) {
    if (locale) {
        return v.toLocaleString(undefined, {
            minimumFractionDigits: decimals,
            maximumFractionDigits: decimals,
        });
    }
    return v.toFixed(decimals);
}
// ============================================================================
// Skeleton Loader — shimmer placeholder toggle
// ============================================================================
/**
 * Show/hide a shimmer placeholder on an element. Toggles `.is-loading` which
 * is defined in styles.css. Useful for stat values or log containers while
 * initial data is being fetched.
 *
 * Example:
 *   setSkeleton('stat-memory', true);
 *   const data = await fetchData();
 *   setSkeleton('stat-memory', false);
 *   animateNumber(document.getElementById('stat-memory'), data.memory);
 */
export function setSkeleton(el, loading) {
    const element = typeof el === 'string' ? document.getElementById(el) : el;
    if (!element)
        return;
    element.classList.toggle('is-loading', loading);
}
// ============================================================================
// Sound Feedback — Web Audio synthesis (no asset files)
// ============================================================================
let _audioCtx = null;
function getAudioCtx() {
    if (_audioCtx)
        return _audioCtx;
    try {
        const Ctor = window.AudioContext || window.webkitAudioContext;
        if (!Ctor)
            return null;
        _audioCtx = new Ctor();
        return _audioCtx;
    }
    catch {
        return null;
    }
}
/**
 * Synthesize a short percussive click via oscillator. No external asset files.
 * Noop unless `settings.soundEnabled` is true. ~10ms tone; enveloped to avoid
 * audible pops. Safe to call at high frequency (each click allocates one
 * short-lived oscillator which is auto-disposed by the Web Audio runtime).
 */
export function playClickSound() {
    if (!settings.soundEnabled)
        return;
    const ctx = getAudioCtx();
    if (!ctx)
        return;
    // Some browsers start AudioContext suspended; resume on first user gesture.
    if (ctx.state === 'suspended')
        ctx.resume().catch(() => { });
    try {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.type = 'triangle';
        osc.frequency.setValueAtTime(1400, ctx.currentTime);
        osc.frequency.exponentialRampToValueAtTime(700, ctx.currentTime + 0.08);
        gain.gain.setValueAtTime(0.0001, ctx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.08, ctx.currentTime + 0.005);
        gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.1);
        // Disconnect on completion so the audio graph nodes are eligible for
        // GC instead of lingering on the destination chain. Forgetting to
        // disconnect for every click was a slow leak in the WebAudio worker.
        osc.onended = () => {
            try {
                osc.disconnect();
            }
            catch { /* already gone */ }
            try {
                gain.disconnect();
            }
            catch { /* already gone */ }
        };
        osc.start(ctx.currentTime);
        osc.stop(ctx.currentTime + 0.1);
    }
    catch {
        /* ignore — audio is pure polish */
    }
}
// ============================================================================
// Haptic Feedback — navigator.vibrate (mobile/touch devices only)
// ============================================================================
/**
 * Short vibration for button clicks. Noop if:
 *  - `settings.hapticEnabled` is false (default)
 *  - Browser doesn't support `navigator.vibrate` (most desktops)
 *  - Device has no vibration hardware (vibrate just returns false)
 */
export function hapticTick() {
    if (!settings.hapticEnabled)
        return;
    if (typeof navigator === 'undefined' || typeof navigator.vibrate !== 'function')
        return;
    try {
        navigator.vibrate(8);
    }
    catch {
        /* some WebViews throw on vibrate; ignore */
    }
}
//# sourceMappingURL=shared.js.map