/**
 * 디스코드 봇 대시보드 - Enhanced TypeScript Frontend
 * Tauri v2 Desktop Application
 *
 * Main application module — UI, navigation, charts, bot control, settings.
 * Chat & memory management extracted to chat-manager.ts.
 * Shared utilities in shared.ts.
 */
import { invoke, escapeHtml, isSafeAvatarUrl, settings, loadSettings, saveSettings, initToastContainer, setup3DInteractions, animateNumber, setSkeleton, showToast, showConfirmDialog, icon, countLabel, prefersReducedMotion, } from './shared.js';
import { chatManager, initChatManager, } from './chat-manager.js';
import { HistoryManager } from './history-manager.js';
import { SakuraRenderer } from './sakura-model.js';
// ============================================================================
// Performance Cache System
// ============================================================================
// Exported so app.test.ts exercises the SHIPPED cache (TTL expiry + capacity
// eviction), not a copy. Production still uses the module-level `dataCache`.
export class DataCache {
    cache = new Map();
    maxSize = 200;
    set(key, data, ttlMs = 5000) {
        // Evict oldest entries if at capacity
        if (this.cache.size >= this.maxSize && !this.cache.has(key)) {
            const oldest = this.cache.keys().next().value;
            if (oldest !== undefined)
                this.cache.delete(oldest);
        }
        this.cache.set(key, {
            data,
            timestamp: Date.now(),
            ttl: ttlMs
        });
    }
    get(key) {
        const entry = this.cache.get(key);
        if (!entry)
            return null;
        if (Date.now() - entry.timestamp > entry.ttl) {
            this.cache.delete(key);
            return null;
        }
        return entry.data;
    }
    invalidate(key) {
        this.cache.delete(key);
    }
    clear() {
        this.cache.clear();
    }
}
const dataCache = new DataCache();
// ============================================================================
// State Management
// ============================================================================
// Canonical page ids, shared by the keyboard shortcut path and switchPage so
// the two can't drift. `config` is a stale alias kept for specs/screenshots
// (there is no `page-config` section — the real id is `page-settings`); map it
// through PAGE_ALIASES rather than letting it blank the UI.
export const VALID_PAGES = ['status', 'chat', 'logs', 'database', 'settings', 'history'];
export const PAGE_ALIASES = { config: 'settings' };
// Pure resolution of a requested page id to a canonical one: aliases map
// through, then anything not in VALID_PAGES is rejected (returns null). Shared
// by switchPage so the guard logic has a single source of truth that unit
// tests can exercise without driving the DOM.
export function resolvePage(page) {
    const resolved = PAGE_ALIASES[page] ?? page;
    if (!VALID_PAGES.includes(resolved))
        return null;
    return resolved;
}
let currentPage = 'status';
let historyManager = null;
let refreshInterval = null;
let logsRefreshInterval = null;
// Governs the LIVE state of the log feed, not just scrolling: false pauses
// the 1s poll entirely (startLogsRefresh no-ops) AND the scroll-to-bottom.
// The Pause/Resume button flips it; persisted as settings.autoScroll.
let logsAutoScrollEnabled = true;
let lastLogSignature = null;
// True after the failure toast for the CURRENT get_logs failure streak has
// been shown; reset on the next successful load (1s poll — see loadLogs).
let logsLoadFailedToastShown = false;
// Chart data history
const memoryHistory = [];
const messagesHistory = [];
// Settings with defaults
const debounceTimers = new Map();
// Consecutive failed status ticks → "Disconnected" cue. Both invoke('get_status')
// halves must reject (or the bot must report not-running) before we count a tick
// as a failure; a single transient IPC blip is swallowed by the cached-fallback
// path in updateStatus and never reaches the counter.
let statusFailStreak = 0;
const STATUS_FAIL_THRESHOLD = 3;
// ============================================================================
// Shared Modal Focus Management
// ============================================================================
//
// openModal/closeModal centralise the a11y plumbing every modal needs: remember
// the element that opened it, move focus inside on open, restore it on close,
// and make the rest of the app inert (with an aria-hidden fallback for engines
// without `inert`) so AT and Tab can't wander behind the overlay. The existing
// Tab focus-trap in initKeyboardShortcuts still handles wrap-around; this adds
// the open/close focus handoff the trap assumed but never performed.
// Per-modal record of the trigger to restore focus to on close.
const modalReturnFocus = new WeakMap();
// Modals that called setAppInert(true) via openModal. inert lifts only when
// every owned modal has closed — so a chat modal toggling .active directly
// (it lives INSIDE .app and never owns inert) can't pin inert on.
const inertModals = new Set();
// The "Bot Not Running" overlay (#chat-not-running-overlay) is an opaque,
// ~92%-blurred layer stacked over the whole chat page when the bot is offline.
// Unlike a real .modal it never routed through openModal/setAppInert, so the
// chat sidebar controls (#conversation-filter-input, #btn-new-chat,
// #btn-export-all) and #btn-new-chat-main stayed in the tab order and the AT
// tree DIRECTLY BEHIND the opaque overlay — a keyboard/AT user could Tab to (and
// activate) "New Conversation" on an offline bot with its focus ring hidden
// under the blur (WCAG 2.4.7 / 2.4.11). Keep `.chat-layout` inert + aria-hidden
// exactly while the overlay is visible so only the overlay's "Start Bot" button
// is reachable. Driven by a MutationObserver on the overlay's class so it stays
// correct no matter what toggles `.visible` (updateStatus, or a direct DOM
// change) — no caller needs to remember to sync it.
let _chatOverlayObserver = null;
function syncChatOverlayInert() {
    const overlay = document.getElementById('chat-not-running-overlay');
    const chatLayout = document.querySelector('#page-chat .chat-layout');
    if (!overlay || !chatLayout)
        return;
    if (overlay.classList.contains('visible')) {
        chatLayout.setAttribute('inert', '');
        chatLayout.setAttribute('aria-hidden', 'true');
    }
    else {
        chatLayout.removeAttribute('inert');
        chatLayout.removeAttribute('aria-hidden');
    }
}
function initChatOverlayA11y() {
    const overlay = document.getElementById('chat-not-running-overlay');
    if (!overlay || _chatOverlayObserver)
        return;
    _chatOverlayObserver = new MutationObserver(() => syncChatOverlayInert());
    _chatOverlayObserver.observe(overlay, { attributes: true, attributeFilter: ['class'] });
    syncChatOverlayInert(); // apply the initial state
}
function setAppInert(inert) {
    // Modals are siblings of `.app` (they live after </div> for .app), so
    // toggling inert/aria-hidden on the app shell never touches the open modal.
    const app = document.querySelector('.app');
    if (!app)
        return;
    if (inert) {
        // `inert` is the correct primitive (removes from tab order + AT tree).
        // aria-hidden is a belt-and-suspenders fallback for older WebView2.
        app.setAttribute('inert', '');
        app.setAttribute('aria-hidden', 'true');
    }
    else {
        app.removeAttribute('inert');
        app.removeAttribute('aria-hidden');
    }
}
function getFirstFocusable(modal) {
    const focusables = Array.from(modal.querySelectorAll('a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])')).filter(el => el.offsetWidth > 0 || el.offsetHeight > 0 || el === document.activeElement);
    return focusables[0] ?? null;
}
export function openModal(modal) {
    if (!modal)
        return;
    // Record the trigger so closeModal can restore focus to it. Skip <body>
    // (the default activeElement) — restoring focus there is a no-op anyway.
    const active = document.activeElement;
    modalReturnFocus.set(modal, active instanceof HTMLElement && active !== document.body ? active : null);
    modal.classList.add('active');
    inertModals.add(modal); // Set => add ซ้ำไม่มีผล (idempotent re-open)
    setAppInert(true);
    // Prefer the first interactive control; fall back to the close button, then
    // the modal element itself (made programmatically focusable) so focus never
    // stays stranded behind the overlay.
    const target = getFirstFocusable(modal) ??
        modal.querySelector('.modal-close, [data-close-shortcuts], [data-close-avatar-crop]');
    if (target) {
        target.focus();
    }
    else if (typeof modal.focus === 'function') {
        if (!modal.hasAttribute('tabindex'))
            modal.setAttribute('tabindex', '-1');
        modal.focus();
    }
}
export function closeModal(modal) {
    if (!modal)
        return;
    modal.classList.remove('active');
    inertModals.delete(modal);
    // Lift inert only when every openModal-owned modal has closed. chat modals
    // live inside .app and never own inert, so a stale .active chat modal no
    // longer blocks the lift (was: querySelector('.modal.active')).
    if (inertModals.size === 0) {
        setAppInert(false);
    }
    const trigger = modalReturnFocus.get(modal);
    modalReturnFocus.delete(modal);
    // Restore focus to the opener if it's still in the DOM and focusable.
    if (trigger && document.contains(trigger) && typeof trigger.focus === 'function') {
        trigger.focus();
    }
}
// Test-only: clear inert ownership between cases. Not used in production.
export function _resetModalInertState() {
    inertModals.clear();
}
// ============================================================================
// Initialization
// ============================================================================
document.addEventListener("DOMContentLoaded", () => {
    loadSettings();
    // Restore the persisted logs auto-scroll preference.
    logsAutoScrollEnabled = settings.autoScroll;
    applyAutoScrollButtonState();
    // Restore the persisted density preference before first paint.
    applyDensity(settings.densityCompact === true);
    initNavigation();
    initTheme();
    initToastContainer();
    initCharts();
    startRefreshLoop();
    loadAllData();
    // Respect saved sakuraEnabled preference (defaults to true).
    sakuraEnabled = settings.sakuraEnabled !== false;
    if (sakuraEnabled)
        initSakuraAnimation();
    initKeyboardShortcuts();
    initChatOverlayA11y();
    initChatManager();
    initHistoryManager();
    // Update AI avatars after all init
    updateAiAvatars();
    initApiFailoverUI();
    // Bind avatar-crop modal listeners up front so Escape works even on the
    // first open (the previous lazy bind inside openCropModal meant the very
    // first session had no Escape handler attached yet).
    setupCropEventListeners();
    // 3D polish: ripple, cursor-tracking tilt, send-button pulse.
    // Called last so it can attach to all elements rendered by the inits above.
    setup3DInteractions();
    // Bootstrap-complete signal — MUST stay the last statement here. The e2e
    // suite awaits this instead of a fixed timeout (see the Window declaration
    // in shared.ts for why). Set synchronously, so by the time it is observable
    // every listener above is bound and clicking the nav is guaranteed to work.
    window.__dashboardReady = true;
});
// Cleanup on window unload — clear timers and close WebSocket so dev hot-reload
// (and the rare WebView2 navigation) doesn't leak ghost intervals or duplicate
// chat sockets. The OS reclaims everything on real process exit, so this is
// purely a development-time / restart-time hygiene improvement.
window.addEventListener('beforeunload', () => {
    if (refreshInterval !== null) {
        clearInterval(refreshInterval);
        refreshInterval = null;
    }
    if (logsRefreshInterval !== null) {
        clearInterval(logsRefreshInterval);
        logsRefreshInterval = null;
    }
    try {
        if (chatManager) {
            chatManager.disconnect();
        }
    }
    catch {
        // ignore — page is going away anyway
    }
});
// ============================================================================
// Keyboard Shortcuts
// ============================================================================
// Topmost open modal = the LAST `.modal.active` in DOM order. Sibling modals
// (shortcuts / avatar-crop in ui/index.html) and the dynamically body-appended
// export-format-modal always come AFTER the in-.app chat modals, so last-in-DOM
// is the overlay stacked on top. Exported so app.test.ts asserts the SHIPPED
// selection (returning actives[0] here would reintroduce the first-modal bug
// and MUST fail the unit test) instead of a mirror re-implementation.
// NOTE: relies on index.html modal ordering — keep app-level modals last.
export function pickTopmostModal() {
    const actives = document.querySelectorAll('.modal.active');
    return actives.length ? actives[actives.length - 1] : null;
}
function initKeyboardShortcuts() {
    document.addEventListener('keydown', (e) => {
        // Single dispatch per keystroke. Each branch early-returns so a key that
        // matches one shortcut can't fall through into another (e.g. the old
        // chain re-evaluated `e.ctrlKey && …` for every shortcut, and a future
        // overlapping binding would double-fire). Ctrl chords switch on the
        // normalized key; plain keys are handled after.
        // `e.altKey` excluded deliberately: on Windows, AltGr reports as
        // Ctrl+Alt, and on several layouts AltGr+digit is how you type a common
        // character — AltGr+2 is @ and AltGr+3 is # on Spanish, AltGr+4 is ¢ on
        // Latin-American. Without this guard, typing an email address into the
        // chat composer navigated the user to the AI Chat page mid-word (the
        // e.code branch below reads Digit2 regardless of the character produced).
        // No app shortcut is a Ctrl+Alt chord, so dropping the whole class is safe.
        if (e.ctrlKey && !e.altKey) {
            // Ctrl+1-6 for page navigation. Key off e.code ('Digit1'..'Digit6')
            // so the shortcut is layout-independent — on AZERTY and similar
            // layouts the unmodified top-row keys emit symbols (&é"'(-) and
            // e.key would not be a digit, silently breaking navigation. Fall
            // back to e.key for engines that don't populate e.code.
            const codeMatch = /^Digit([1-6])$/.exec(e.code);
            const digit = codeMatch ? codeMatch[1] : (e.key >= '1' && e.key <= '6' ? e.key : null);
            if (digit) {
                const index = parseInt(digit) - 1;
                if (VALID_PAGES[index]) {
                    e.preventDefault();
                    switchPage(VALID_PAGES[index]);
                }
                return;
            }
            // Normalize the key once (toLowerCase so chords fire under Caps Lock
            // / Shift too) and switch — one branch wins, then we're done.
            switch (e.key.toLowerCase()) {
                case 'r': // Refresh all data
                    e.preventDefault();
                    loadAllData();
                    showToast('Refreshed!', { type: 'info', duration: 1500 });
                    return;
                case 't': // Toggle theme
                    e.preventDefault();
                    toggleTheme();
                    return;
                case 'enter': // Send message (chat only)
                    if (currentPage === 'chat') {
                        e.preventDefault();
                        chatManager?.sendMessage();
                    }
                    return;
                case 'f': // Open in-chat search (chat only)
                    if (currentPage === 'chat') {
                        e.preventDefault();
                        chatManager?.openChatSearch();
                    }
                    return;
                default:
                    return; // Unhandled Ctrl chord — let the browser have it.
            }
        }
        // "?" to show keyboard shortcut help — but only when not typing
        if (e.key === '?' && !e.metaKey) {
            const active = document.activeElement;
            const isTyping = active instanceof HTMLInputElement
                || active instanceof HTMLTextAreaElement
                || (active instanceof HTMLElement && active.isContentEditable);
            // Don't stack the shortcuts modal on top of an already-open modal
            // (e.g. the avatar-crop dialog) — that would double-inert the app.
            if (!isTyping && !document.querySelector('.modal.active')) {
                e.preventDefault();
                openModal(document.getElementById('shortcuts-modal'));
            }
            return;
        }
        // Escape closes the shortcuts modal if open (routed through closeModal so
        // focus is restored to the trigger and app inert is lifted).
        if (e.key === 'Escape') {
            const shortcuts = document.getElementById('shortcuts-modal');
            if (shortcuts?.classList.contains('active')) {
                closeModal(shortcuts);
            }
            return;
        }
        // Focus trap: keep Tab within the open modal (.modal.active) so keyboard
        // focus can't escape behind the overlay. Every modal uses the .active
        // class to show, so this single handler covers all of them.
        if (e.key === 'Tab') {
            // Topmost open modal (last .modal.active in DOM order) — see pickTopmostModal.
            const modal = pickTopmostModal();
            if (modal) {
                const focusables = Array.from(modal.querySelectorAll('a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])')).filter(el => el.offsetWidth > 0 || el.offsetHeight > 0 || el === document.activeElement);
                if (focusables.length > 0) {
                    const first = focusables[0];
                    const last = focusables[focusables.length - 1];
                    const activeEl = document.activeElement;
                    if (e.shiftKey && (activeEl === first || !modal.contains(activeEl))) {
                        e.preventDefault();
                        last.focus();
                    }
                    else if (!e.shiftKey && (activeEl === last || !modal.contains(activeEl))) {
                        e.preventDefault();
                        first.focus();
                    }
                }
            }
        }
    });
    // Close buttons (and overlay) inside the shortcuts modal — routed through
    // closeModal so focus returns to the opener and the app inert state lifts.
    document.querySelectorAll('[data-close-shortcuts]').forEach(el => {
        el.addEventListener('click', () => {
            closeModal(document.getElementById('shortcuts-modal'));
        });
    });
}
// ============================================================================
// Theme System
// ============================================================================
/**
 * Did the user ever persist an explicit theme choice? loadSettings() only
 * applies stored values when `dashboard-settings` exists AND parses, so a
 * missing/corrupt blob or one without a `theme` key means "never chosen" —
 * in which case we honour the OS `prefers-color-scheme` on first run (A11Y-05).
 */
function hasStoredTheme() {
    try {
        const saved = localStorage.getItem('dashboard-settings');
        if (!saved)
            return false;
        const parsed = JSON.parse(saved);
        return parsed.theme === 'dark' || parsed.theme === 'light';
    }
    catch {
        return false;
    }
}
// Exported as a test seam (like _resetModalInertState) so the first-run
// prefers-color-scheme default (A11Y-05) can be asserted in app.test.ts.
export function initTheme() {
    // First run (no stored theme): follow the OS preference instead of always
    // forcing dark. matchMedia is feature-detected so a non-browser/test host
    // without it falls back to the existing `settings.theme` default. Once the
    // user toggles, toggleTheme() persists the choice and this branch stops
    // applying. data-theme stays the single source of truth (no CSS @media).
    if (!hasStoredTheme() && typeof window.matchMedia === 'function') {
        const prefersLight = window.matchMedia('(prefers-color-scheme: light)').matches;
        settings.theme = prefersLight ? 'light' : 'dark';
    }
    applyTheme(settings.theme);
    // Add theme toggle button listeners (sidebar + settings page)
    document.getElementById('theme-toggle')?.addEventListener('click', toggleTheme);
    document.getElementById('theme-toggle-settings')?.addEventListener('click', toggleTheme);
}
function toggleTheme() {
    settings.theme = settings.theme === 'dark' ? 'light' : 'dark';
    applyTheme(settings.theme);
    saveSettings();
    showToast(`Theme: ${settings.theme === 'dark' ? 'Dark' : 'Light'}`, { type: 'info', duration: 1500 });
}
function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    const themeIcon = document.getElementById('theme-icon');
    if (themeIcon) {
        themeIcon.innerHTML = theme === 'dark' ? icon('moon') : icon('sun');
    }
    // Also update the settings page theme icon
    const themeIconSettings = document.getElementById('theme-icon-settings');
    if (themeIconSettings) {
        themeIconSettings.innerHTML = theme === 'dark' ? icon('moon') : icon('sun');
    }
    // Canvas charts read their colors from CSS tokens at draw time and can't
    // pick up the theme swap on their own — repaint so they re-color now.
    // Safe before charts have data (drawChart no-ops without a canvas / draws
    // the placeholder), so this also covers the initial applyTheme() at boot.
    updateCharts();
}
// Density mode (CONTRACT): set/remove data-density="compact" on <html>. The CSS
// recipe [data-density="compact"]{--density:.7} drives the tighter spacing.
function applyDensity(compact) {
    if (compact) {
        document.documentElement.setAttribute('data-density', 'compact');
    }
    else {
        document.documentElement.removeAttribute('data-density');
    }
}
// ============================================================================
// Settings Management
// ============================================================================
function updateAiAvatars() {
    const safeAvatar = isSafeAvatarUrl(settings.aiAvatar) ? settings.aiAvatar : '';
    // Update empty state avatar
    const emptyAvatar = document.getElementById('chat-empty-avatar');
    if (emptyAvatar) {
        if (safeAvatar) {
            emptyAvatar.src = safeAvatar;
            emptyAvatar.classList.remove('hidden');
        }
        else {
            emptyAvatar.removeAttribute('src');
            emptyAvatar.classList.add('hidden');
        }
    }
    // Update chat header avatar
    const headerAvatar = document.getElementById('chat-role-avatar');
    if (headerAvatar) {
        if (safeAvatar) {
            headerAvatar.src = safeAvatar;
            headerAvatar.classList.remove('hidden');
        }
        else {
            headerAvatar.removeAttribute('src');
            headerAvatar.classList.add('hidden');
        }
    }
}
function updateSetting(key, value) {
    settings[key] = value;
    saveSettings();
    // Apply changes
    if (key === 'refreshInterval') {
        restartRefreshLoop();
    }
    else if (key === 'theme') {
        applyTheme(value);
    }
}
// ============================================================================
// Lightweight Charts (Canvas-based for performance)
// ============================================================================
function initCharts() {
    // Charts will be initialized when the status page loads
    window.addEventListener('resize', debounce(updateCharts, 'resize', 250));
    // The x-axis right edge is anchored to the wall clock, so repaint every
    // second — without this the time labels only move when a sample lands
    // (2s status / ~4s dbStats cadence) and the clock visibly skips seconds.
    // Skip the repaint while the tab is hidden or another page is active;
    // the regular status-tick redraw covers reactivation.
    window.setInterval(() => {
        if (document.hidden)
            return;
        if (!document.getElementById('page-status')?.classList.contains('active'))
            return;
        updateCharts();
    }, 1000);
    // Hover layer: a crosshair that snaps to the nearest sample + a tooltip.
    // The whole canvas is the hit target (never just the 2px line), and
    // keyboard focus shows the same readout at the latest sample.
    for (const id of ['memory-chart', 'messages-chart']) {
        const canvas = document.getElementById(id);
        if (!canvas)
            continue;
        canvas.addEventListener('pointermove', (e) => {
            const params = chartDrawParams.get(id);
            if (!params || params.xs.length < 2)
                return;
            const x = e.clientX - canvas.getBoundingClientRect().left;
            // Nearest sample by drawn position — samples sit at uneven x now
            // that the axis is temporal (message samples land every ~4s
            // between 2s memory ticks), so an index-from-fraction formula
            // would snap to the wrong point.
            let idx = 0;
            let best = Infinity;
            params.xs.forEach((px, i) => {
                const d = Math.abs(px - x);
                if (d < best) {
                    best = d;
                    idx = i;
                }
            });
            if (chartHoverIndex.get(id) !== idx) {
                chartHoverIndex.set(id, idx);
                scheduleChartRedraw(id);
            }
        });
        canvas.addEventListener('pointerleave', () => {
            chartHoverIndex.set(id, null);
            scheduleChartRedraw(id);
        });
        canvas.addEventListener('focus', () => {
            // Keyboard focus only (:focus-visible is false for mouse-click
            // focus) — a click on the canvas must not teleport an active
            // pointer crosshair to the latest sample. Set the pin even with
            // <2 samples: Infinity means "always the latest", drawChart
            // clamps it to the live last index once data arrives, so a chart
            // focused during startup still gets its readout.
            if (!canvas.matches(':focus-visible'))
                return;
            chartHoverIndex.set(id, Number.POSITIVE_INFINITY);
            scheduleChartRedraw(id);
        });
        canvas.addEventListener('blur', () => {
            // Only clear the keyboard pin — a finite index belongs to the
            // pointer, which may still be hovering the chart.
            if (chartHoverIndex.get(id) !== Number.POSITIVE_INFINITY)
                return;
            chartHoverIndex.set(id, null);
            scheduleChartRedraw(id);
        });
    }
}
// Test/preview seam (screenshots.spec.ts): replace both chart histories with
// synthetic samples and redraw, so e2e screenshots can capture a populated
// chart without waiting out real status ticks. Stops the live refresh loop
// first — otherwise the next status tick (2s default) would append a real
// sample (0 MB under the e2e mock) onto the seeded series mid-screenshot.
// Not called by production code.
export function seedChartHistories(memoryValues, messageValues, intervalMs = 5000) {
    stopRefreshLoop();
    const now = Date.now();
    memoryHistory.length = 0;
    messagesHistory.length = 0;
    memoryValues.forEach((v, i) => memoryHistory.push({ timestamp: now - (memoryValues.length - 1 - i) * intervalMs, value: v }));
    messageValues.forEach((v, i) => messagesHistory.push({ timestamp: now - (messageValues.length - 1 - i) * intervalMs, value: v }));
    updateCharts();
}
// dbStats cache TTL (used by updateStatus). Also feeds chartMaxWindowMs:
// message-count samples land only when this cache is cold, so their real
// cadence is one tick past the TTL (~4s at the 1s and 2s intervals) — the
// chart window must be sized off that, not the raw tick interval, or the
// prune below silently caps the messages series short of chartHistory.
const DB_STATS_TTL_MS = 3000;
// The widest time span a chart may draw, covering the slowest series at 2×
// slack: worst sample gap = refreshInterval + DB_STATS_TTL_MS.
function chartMaxWindowMs() {
    return Math.max(60_000, settings.chartHistory * (settings.refreshInterval + DB_STATS_TTL_MS) * 2);
}
// Exported so app.test.ts exercises the SHIPPED chart-history capping (which
// caps at the live `settings.chartHistory`), not a re-implementation.
export function addChartDataPoint(history, value) {
    const now = Date.now();
    // Clock stepped backward (NTP/manual change): samples stamped in the
    // future would wreck the temporal axis — tSpan clamps to 1 and the line
    // renders as a garbled band until the count cap cycles them out. They
    // form a suffix (timestamps are appended ascending), so drop from the
    // end. The 1s tolerance ignores sub-second slew corrections.
    while (history.length > 0 && history[history.length - 1].timestamp > now + 1000) {
        history.pop();
    }
    history.push({
        timestamp: now,
        value
    });
    while (history.length > settings.chartHistory) {
        history.shift();
    }
    // Samples that predate the drawable window are dead weight: after a
    // system sleep the [old, now] span would compress every live sample into
    // the left edge of the plot (drawChart also guards, this keeps the
    // arrays clean).
    const cutoff = now - chartMaxWindowMs();
    while (history.length > 0 && history[0].timestamp < cutoff) {
        history.shift();
    }
}
// Last-draw parameters per canvas so pointer-driven redraws (crosshair /
// tooltip) can repaint immediately instead of waiting for the next status
// tick. xs mirrors each sample's drawn x-position for hover hit-testing
// (samples are laid out by timestamp, not index, so spacing is uneven).
const chartDrawParams = new Map();
// Hovered sample index per canvas (null = no crosshair).
const chartHoverIndex = new Map();
const pendingChartRedraw = new Set();
// Coalesce hover redraws to one per animation frame — pointermove can fire
// far faster than the display refreshes.
function scheduleChartRedraw(canvasId) {
    if (pendingChartRedraw.size === 0) {
        requestAnimationFrame(() => {
            for (const id of pendingChartRedraw) {
                const p = chartDrawParams.get(id);
                if (p)
                    drawChart(id, p.data, p.color, p.spec);
            }
            pendingChartRedraw.clear();
        });
    }
    pendingChartRedraw.add(canvasId);
}
function formatChartValue(value, decimals) {
    return decimals === 0 ? Math.round(value).toLocaleString() : value.toFixed(decimals);
}
// Count series always print whole ticks; value series print enough decimals
// to render the step EXACTLY — ceil(-log10(step)) undershoots the 2.5×10⁻ⁿ
// family (step 0.25 → 1 place → the gridline at 230.25 would be labeled
// "230.3", off by a fifth of a step), so derive places from the step's own
// decimal expansion (steps are 1/2/2.5/5 × 10ⁿ, which terminates ≤ 3 places
// in the ranges these charts see).
function formatChartTick(tick, decimals, step) {
    if (decimals === 0)
        return Math.round(tick).toLocaleString();
    if (Number.isInteger(step) && Number.isInteger(tick))
        return tick.toLocaleString();
    const stepDecimals = (step.toString().split('.')[1] ?? '').length;
    const places = Math.min(3, Math.max(1, stepDecimals));
    return tick.toFixed(places);
}
function formatChartTime(timestamp) {
    return new Date(timestamp).toLocaleTimeString('en-GB', { hour12: false });
}
// Y-scale with ticks on "nice" steps (1/2/2.5/5 × 10ⁿ) so the axis reads
// 210 · 215 · 220 instead of the raw min×0.9 / max×1.1 endpoints the old
// chart printed. The drawn span never shrinks below 10% of the value's own
// magnitude: a min/max-hugging domain turns a <2% wobble (memory idling at
// ~232 MB) into a full-height mountain, so sub-threshold series get a window
// centered on their midpoint instead — flat-in-practice data reads as flat,
// while a genuine move (leak, restart) still fills the plot. Span 0 (the
// idle message counter) falls out of the same rule via the absolute floor.
// Exported so app.test.ts exercises the SHIPPED y-domain policy.
export function niceChartScale(rawMin, rawMax, integer) {
    let min = rawMin;
    let max = rawMax;
    const magnitude = Math.max(Math.abs(rawMin), Math.abs(rawMax));
    const minSpan = Math.max(integer ? 4 : 1, magnitude * 0.1);
    if (max - min < minSpan) {
        const mid = (min + max) / 2;
        min = mid - minSpan / 2;
        max = mid + minSpan / 2;
    }
    else {
        const pad = (max - min) * 0.08;
        min -= pad;
        max += pad;
    }
    // A non-negative series never shows a negative axis (memory below 0 MB).
    if (rawMin >= 0 && min < 0)
        min = 0;
    const step0 = (max - min) / 3.5; // aim for ~4 gridlines
    const mag = Math.pow(10, Math.floor(Math.log10(step0)));
    const norm = step0 / mag;
    // Integer series skip the 2.5 slot below mag 10 (2.5/0.25… aren't whole
    // numbers) and never step finer than 1.
    const steps = integer && mag < 10 ? [1, 2, 5, 10] : [1, 2, 2.5, 5, 10];
    let step = (steps.find(s => norm <= s) ?? 10) * mag;
    if (integer)
        step = Math.max(1, step);
    const lo = Math.floor(min / step) * step;
    const hi = Math.ceil(max / step) * step;
    const ticks = [];
    const count = Math.round((hi - lo) / step);
    for (let i = 0; i <= count; i++)
        ticks.push(lo + i * step);
    return { lo, hi, ticks, step };
}
// Monotone-cubic path (harmonic-mean tangents) — smooth without overshoot,
// so a memory spike still tops out exactly at its sampled value instead of
// the curve inventing a higher peak the way naive Catmull-Rom does.
function traceSmoothPath(ctx, pts) {
    const first = pts[0];
    if (!first)
        return;
    ctx.moveTo(first.x, first.y);
    const n = pts.length;
    const slopes = [];
    for (let i = 0; i < n - 1; i++) {
        const dx = pts[i + 1].x - pts[i].x;
        slopes.push(dx === 0 ? 0 : (pts[i + 1].y - pts[i].y) / dx);
    }
    const tangents = [slopes[0]];
    for (let i = 1; i < n - 1; i++) {
        const a = slopes[i - 1];
        const b = slopes[i];
        tangents.push(a * b <= 0 ? 0 : (2 * a * b) / (a + b));
    }
    tangents.push(slopes[n - 2]);
    for (let i = 0; i < n - 1; i++) {
        const p0 = pts[i];
        const p1 = pts[i + 1];
        const dx = (p1.x - p0.x) / 3;
        ctx.bezierCurveTo(p0.x + dx, p0.y + tangents[i] * dx, p1.x - dx, p1.y - tangents[i + 1] * dx, p1.x, p1.y);
    }
}
// Marker with a punched-out ring: 'destination-out' erases a halo around the
// dot so the card background shows through (the canvas is transparent) —
// a surface ring that stays correct in every theme without knowing the
// card's actual color.
function drawChartMarker(ctx, x, y, color) {
    ctx.save();
    ctx.globalCompositeOperation = 'destination-out';
    // destination-out erases dest × srcAlpha, so the punch fill must be fully
    // opaque — inheriting the caller's fillStyle (often the low-alpha area
    // gradient) would leave the halo 95% un-erased.
    ctx.fillStyle = '#000';
    ctx.beginPath();
    ctx.arc(x, y, 6.5, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
    ctx.beginPath();
    ctx.arc(x, y, 4, 0, Math.PI * 2);
    ctx.fillStyle = color;
    ctx.fill();
}
// Exported so app.test.ts exercises the SHIPPED canvas draw sequence (fill
// closure geometry) against a recording 2D-context mock.
export function drawChart(canvasId, data, color, spec) {
    const canvas = document.getElementById(canvasId);
    if (!canvas)
        return;
    const ctx = canvas.getContext('2d');
    if (!ctx)
        return;
    // Read theme colors from CSS tokens at draw time (SHARED CONTRACT #1) so a
    // light/dark toggle re-colors the canvas — it can't pick up CSS like real
    // DOM does. Cache the lookups for the duration of this single draw; they're
    // re-read on the next draw (updateCharts runs on every status tick + the
    // post-toggle redraw below).
    const tokens = getComputedStyle(document.documentElement);
    const gridColor = tokens.getPropertyValue('--chart-grid').trim() || 'rgba(72,196,232,.10)';
    const fillTop = tokens.getPropertyValue('--chart-fill-top').trim() || 'rgba(61,245,255,.30)';
    const fillBot = tokens.getPropertyValue('--chart-fill-bot').trim() || 'rgba(61,245,255,.05)';
    const inkMuted = tokens.getPropertyValue('--text-tertiary').trim() || 'rgba(255,255,255,0.3)';
    const inkStrong = tokens.getPropertyValue('--text-primary').trim() || 'rgba(255,255,255,0.9)';
    const tooltipBg = tokens.getPropertyValue('--chart-tooltip-bg').trim() || 'rgba(22,15,28,0.94)';
    const tooltipBorder = tokens.getPropertyValue('--chart-tooltip-border').trim() || gridColor;
    const monoFont = tokens.getPropertyValue('--font-mono').trim() || 'ui-monospace, monospace';
    // Fade-in entrance on the very first draw (CSS handles the transition;
    // .chart-ready flips opacity from 0→1 and translateY from 16px→0).
    if (!canvas.classList.contains('chart-ready')) {
        requestAnimationFrame(() => canvas.classList.add('chart-ready'));
    }
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    // Hidden page (display:none) → 0×0 rect. Bail BEFORE touching the bitmap:
    // assigning canvas.width = 0 wipes the last frame, and the reader would
    // get a blank canvas for up to a second when switching back to Status.
    if (rect.width === 0 || rect.height === 0)
        return;
    // Samples outside the drawable window would corrupt the temporal axis:
    // too-old ones (system sleep, long stall) compress the live data into the
    // left edge of a huge [old, now] span; future-stamped ones (clock stepped
    // backward) collapse tSpan to 1 and garble the line. Draw only the
    // in-window slice — addChartDataPoint prunes the arrays on the next tick;
    // this covers the frames in between.
    const tNow = Date.now();
    const staleCutoff = tNow - chartMaxWindowMs();
    const futureCutoff = tNow + 1000;
    if (data.length > 0 &&
        (data[0].timestamp < staleCutoff || data[data.length - 1].timestamp > futureCutoff)) {
        data = data.filter(p => p.timestamp >= staleCutoff && p.timestamp <= futureCutoff);
    }
    // Assigning canvas.width/height ALWAYS throws away and re-allocates the
    // backing store — even when the value is identical. This ran on every draw,
    // i.e. ~2x/second for as long as the Status page is open (repaint timer +
    // status tick) plus a burst per hover sample, discarding ~1MB of bitmap each
    // time for a size that never changes. Only touch the bitmap when the target
    // dimensions genuinely differ. Round FIRST and assign the rounded integers:
    // the setter truncates, so comparing a raw `rect.width * dpr` against
    // canvas.width would never match and the guard would never hold.
    const targetW = Math.round(rect.width * dpr);
    const targetH = Math.round(rect.height * dpr);
    if (canvas.width !== targetW || canvas.height !== targetH) {
        canvas.width = targetW;
        canvas.height = targetH;
    }
    // setTransform, NOT scale(): scale() multiplies into the current matrix, and
    // the only thing that used to reset that matrix was the per-draw bitmap
    // re-allocation above. With the realloc gone, scale() would compound every
    // draw and the chart would zoom itself off the canvas.
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const width = rect.width;
    const height = rect.height;
    ctx.clearRect(0, 0, width, height);
    const values = data.map(d => d.value);
    // Use reduce instead of spread to prevent stack overflow with large arrays
    const rawMin = values.reduce((a, b) => Math.min(a, b), Infinity);
    const rawMax = values.reduce((a, b) => Math.max(a, b), -Infinity);
    // A flat-zero series has nothing to plot, and plotting it anyway is worse
    // than plotting nothing: niceChartScale invents a 0.0–0.6 axis for a value
    // that is exactly 0, and a window only seconds wide stamps the same
    // timestamp on all three x-axis labels. The result reads as a broken chart
    // rather than an idle one — which is what the Status page shows for as
    // long as the bot is stopped, i.e. most of the time.
    if (data.length < 2 || (rawMin === 0 && rawMax === 0)) {
        chartDrawParams.set(canvasId, { data, color, spec, xs: [] });
        ctx.fillStyle = inkMuted;
        ctx.font = `12px ${monoFont}`;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(data.length < 2 ? 'Collecting data...' : 'No activity yet', width / 2, height / 2);
        return;
    }
    const { lo, hi, ticks, step } = niceChartScale(rawMin, rawMax, spec.decimals === 0);
    // Layout — the left gutter is sized to the widest tick label so 4-digit
    // message counts never collide with the plot, then quantized to 8px steps
    // so a 1px change in label width between live ticks can't nudge the whole
    // plot sideways.
    ctx.font = `10px ${monoFont}`;
    const tickLabels = ticks.map(t => formatChartTick(t, spec.decimals, step));
    const gutter = Math.ceil((Math.max(30, ...tickLabels.map(l => ctx.measureText(l).width)) + 12) / 8) * 8;
    const plotLeft = gutter;
    const plotTop = 14;
    const plotRight = width - 14;
    const plotBottom = height - 22; // x-axis band lives inside the canvas
    const plotW = plotRight - plotLeft;
    const plotH = plotBottom - plotTop;
    // Temporal x-axis anchored to the wall clock: the right edge is "now",
    // and every sample sits at its true timestamp. Index-based spacing lied
    // twice — message samples land every ~4s (dbStats cache) between 2s
    // memory ticks, and the right edge showed a seconds-old sample as if it
    // were current.
    const tStart = data[0].timestamp;
    const tSpan = Math.max(1, tNow - tStart);
    const xAt = (t) => plotLeft + plotW * Math.min(1, Math.max(0, (t - tStart) / tSpan));
    const yAt = (v) => plotBottom - ((v - lo) / (hi - lo)) * plotH;
    const pts = data.map(p => ({ x: xAt(p.timestamp), y: yAt(p.value) }));
    chartDrawParams.set(canvasId, { data, color, spec, xs: pts.map(p => p.x) });
    // Hold the latest reading out to the clock edge: the right edge is "now",
    // which runs seconds past the last sample (up to refresh + dbStats TTL on
    // the messages series), so a line that halts at the sample leaves a
    // sampleless gap that renders as an artifact — a diagonal fill wedge or a
    // vertical fill cliff, depending on where the polygon closes. The held
    // value IS the latest known reading, and the hold is drawing-only: xs /
    // hover hit-testing stay on real samples, so the tooltip never reports a
    // fabricated timestamp. Skip the sub-pixel case so a fresh sample doesn't
    // grow a zero-length bezier.
    const lastReal = pts[pts.length - 1];
    const linePts = plotRight - lastReal.x > 0.5
        ? [...pts, { x: plotRight, y: lastReal.y }]
        : pts;
    // Grid: solid hairlines at nice ticks, each labeled in the left gutter.
    ctx.strokeStyle = gridColor;
    ctx.lineWidth = 1;
    ctx.fillStyle = inkMuted;
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    ticks.forEach((tick, i) => {
        const y = yAt(tick);
        ctx.beginPath();
        ctx.moveTo(plotLeft, y);
        ctx.lineTo(plotRight, y);
        ctx.stroke();
        ctx.fillText(tickLabels[i], plotLeft - 8, y);
    });
    // Time axis: window start / NOW anchor the edges, so the right label
    // ticks every second like a clock (a 1s repaint timer in initCharts keeps
    // it moving between samples) instead of jumping only when a sample lands.
    // All three labels sit at fixed x positions; the midpoint shows the
    // window's true temporal center.
    // Skip any label that would repeat one already drawn: a window narrower
    // than the clock's resolution printed the SAME time three times across the
    // axis, which reads as a rendering fault.
    ctx.textBaseline = 'alphabetic';
    const tLabelStart = formatChartTime(tStart);
    const tLabelNow = formatChartTime(tNow);
    const tLabelMid = formatChartTime(tStart + tSpan / 2);
    ctx.textAlign = 'right';
    ctx.fillText(tLabelNow, plotRight, height - 7);
    if (tLabelStart !== tLabelNow) {
        ctx.textAlign = 'left';
        ctx.fillText(tLabelStart, plotLeft, height - 7);
        if (plotW > 320 && tLabelMid !== tLabelStart && tLabelMid !== tLabelNow) {
            ctx.textAlign = 'center';
            ctx.fillText(tLabelMid, plotLeft + plotW / 2, height - 7);
        }
    }
    // Area wash from the theme fill tokens (top → bottom). The polygon closes
    // straight down from the drawn line's endpoints (the hold segment carries
    // it to the clock edge), so the fill ends exactly where the line does.
    const gradient = ctx.createLinearGradient(0, plotTop, 0, plotBottom);
    gradient.addColorStop(0, fillTop);
    gradient.addColorStop(1, fillBot);
    ctx.beginPath();
    traceSmoothPath(ctx, linePts);
    ctx.lineTo(linePts[linePts.length - 1].x, plotBottom);
    ctx.lineTo(linePts[0].x, plotBottom);
    ctx.closePath();
    ctx.fillStyle = gradient;
    ctx.fill();
    // Line with a soft neon glow (shadowBlur ignores ctx.scale → × dpr).
    ctx.save();
    ctx.beginPath();
    traceSmoothPath(ctx, linePts);
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.shadowColor = color;
    ctx.shadowBlur = 8 * dpr;
    ctx.stroke();
    ctx.restore();
    // Resolve the hover target first: Infinity is the keyboard-focus pin
    // ("always the latest sample") and clamps to the live last index even as
    // new samples land; a stale pointer index past the end clamps the same
    // way instead of dropping the crosshair.
    const hoverRaw = chartHoverIndex.get(canvasId) ?? null;
    const hoverIdx = hoverRaw === null ? null : Math.min(Math.max(0, hoverRaw), data.length - 1);
    // Endpoint marker + its value in text ink (never the series color — the
    // colored dot beside it carries identity). The header readout chip
    // repeats the number, but here it rides the line it belongs to. Skip the
    // label while the last sample is hovered — the tooltip shows the same
    // value in the same spot.
    const lastPt = linePts[linePts.length - 1];
    drawChartMarker(ctx, lastPt.x, lastPt.y, color);
    if (hoverIdx !== data.length - 1) {
        const current = data[data.length - 1].value;
        const endLabel = `${formatChartValue(current, spec.decimals)}${spec.unit}`;
        ctx.font = `600 11px ${monoFont}`;
        ctx.fillStyle = inkStrong;
        ctx.textAlign = 'right';
        const endLabelY = lastPt.y - 14 < plotTop ? lastPt.y + 20 : lastPt.y - 12;
        // The label follows its dot (riding the hold segment's end at the
        // clock edge), clamped inside the plot.
        const endLabelW = ctx.measureText(endLabel).width;
        const endLabelX = Math.min(plotRight, Math.max(lastPt.x + endLabelW / 2, plotLeft + endLabelW));
        ctx.fillText(endLabel, endLabelX, endLabelY);
    }
    // Hover layer: crosshair snapped to the sample + a value-first tooltip.
    if (hoverIdx !== null && hoverIdx >= 0 && hoverIdx < data.length) {
        const hp = pts[hoverIdx];
        ctx.strokeStyle = inkMuted;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(hp.x, plotTop);
        ctx.lineTo(hp.x, plotBottom);
        ctx.stroke();
        drawChartMarker(ctx, hp.x, hp.y, color);
        const valueLine = `${formatChartValue(data[hoverIdx].value, spec.decimals)}${spec.unit}`;
        const timeLine = formatChartTime(data[hoverIdx].timestamp);
        ctx.font = `700 12px ${monoFont}`;
        const valueW = ctx.measureText(valueLine).width;
        ctx.font = `10px ${monoFont}`;
        const timeW = ctx.measureText(timeLine).width;
        const keyW = 14; // short series-color line key before the value
        const boxW = Math.max(valueW + keyW, timeW) + 20;
        const boxH = 40;
        let boxX = hp.x + 12;
        if (boxX + boxW > plotRight)
            boxX = hp.x - 12 - boxW;
        let boxY = hp.y - boxH - 10;
        if (boxY < plotTop)
            boxY = Math.min(hp.y + 10, plotBottom - boxH);
        ctx.beginPath();
        ctx.roundRect(boxX, boxY, boxW, boxH, 6);
        ctx.fillStyle = tooltipBg;
        ctx.fill();
        ctx.strokeStyle = tooltipBorder;
        ctx.lineWidth = 1;
        ctx.stroke();
        ctx.strokeStyle = color;
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(boxX + 10, boxY + 15);
        ctx.lineTo(boxX + 10 + 8, boxY + 15);
        ctx.stroke();
        ctx.fillStyle = inkStrong;
        ctx.font = `700 12px ${monoFont}`;
        ctx.textAlign = 'left';
        ctx.fillText(valueLine, boxX + 10 + keyW, boxY + 19);
        ctx.fillStyle = inkMuted;
        ctx.font = `10px ${monoFont}`;
        ctx.fillText(timeLine, boxX + 10, boxY + 32);
    }
}
function updateCharts() {
    // Line colors come from CSS tokens too (SHARED CONTRACT #1: --chart-line),
    // so both charts re-color on a theme toggle. Memory uses the canonical
    // chart line; the messages series uses --chart-line-2 (the dedicated second
    // series token). Fall back through the old --accent-purple, then a hardcoded
    // blue, so an unstyled build still renders distinguishable lines.
    const tokens = getComputedStyle(document.documentElement);
    const lineColor = tokens.getPropertyValue('--chart-line').trim() || '#3df5ff';
    const messagesColor = tokens.getPropertyValue('--chart-line-2').trim() ||
        tokens.getPropertyValue('--accent-purple').trim() ||
        '#6aa6ff';
    drawChart('memory-chart', memoryHistory, lineColor, { decimals: 1, unit: ' MB' });
    drawChart('messages-chart', messagesHistory, messagesColor, { decimals: 0, unit: '' });
    // Fill the in-header readout chips (CONTRACT) with the latest sample so the
    // current value is legible even before the canvas line is read. Memory keeps
    // one decimal + unit; message count is an integer with thousands grouping.
    // The chips (normal DOM text) are also the screen-reader channel for the
    // live value — the canvas aria-labels stay static in index.html because
    // renaming a focused element every status tick makes SRs re-announce it.
    const memReadout = document.getElementById('chart-memory-readout');
    if (memReadout) {
        const latest = memoryHistory[memoryHistory.length - 1]?.value;
        memReadout.textContent = latest === undefined ? '' : `${latest.toFixed(1)} MB`;
    }
    const msgReadout = document.getElementById('chart-messages-readout');
    if (msgReadout) {
        const latest = messagesHistory[messagesHistory.length - 1]?.value;
        msgReadout.textContent = latest === undefined ? '' : latest.toLocaleString();
    }
}
// ============================================================================
// Sakura Petals Animation — thin-plate aerodynamics, integrated per frame, and
// drawn as a real 3D surface (see sakura-model.ts for the geometry and the
// shading; this half owns only the motion).
//
// A fixed set of petals sized to the window is recycled in place, so the field
// allocates nothing after the first second. There are no per-petal DOM nodes
// any more: the sim fills a plain array and the renderer draws the lot in two
// instanced calls.
// ============================================================================
let sakuraEnabled = true;
let sakuraRenderer = null;
/** Live field stats. There are no per-petal DOM nodes to count any more, so
 *  this is the only handle the e2e suite has on whether the effect is actually
 *  running — see the sakura tests in ui-invariants.spec.ts. `frames` doubling
 *  its rate is how a second simulation loop would show itself. */
const sakuraStats = { count: 0, frames: 0 };
export function sakuraDebugState() {
    return { running: sakuraRunning, count: sakuraStats.count, frames: sakuraStats.frames };
}
/** True between a successful initSakuraAnimation() and the next stopSakura().
 *  Replaces the old `sakuraInterval !== null` running-check: spawning moved
 *  into the rAF loop, so there is no interval left to test. Without an explicit
 *  flag, toggling the setting off and on would start a SECOND simulation loop
 *  over the same container. */
let sakuraRunning = false;
let sakuraDisposers = [];
function stopSakura() {
    sakuraRunning = false;
    for (const dispose of sakuraDisposers)
        dispose();
    sakuraDisposers = [];
    sakuraRenderer?.dispose();
    sakuraRenderer = null;
    sakuraStats.count = 0;
    const c = document.getElementById('sakura-container');
    if (c)
        c.replaceChildren();
}
/** Called by Settings UI toggle. Enables or disables the animation at runtime. */
export function setSakuraEnabled(enabled) {
    sakuraEnabled = enabled;
    if (enabled) {
        if (!sakuraRunning)
            initSakuraAnimation();
    }
    else {
        stopSakura();
    }
}
function initSakuraAnimation() {
    const container = document.getElementById('sakura-container');
    if (!container)
        return;
    if (!sakuraEnabled)
        return;
    // Respect prefers-reduced-motion: the CSS zeroes animation durations, but
    // without this the JS would still run a physics loop for zero visible
    // payoff. Bail entirely so reduced-motion users pay no animation cost.
    if (prefersReducedMotion())
        return;
    sakuraRunning = true;
    // Colour, as RGB triples the renderer hands straight to the shader. Two
    // palettes, because one never worked: pale blossom reads beautifully on the
    // midnight canvas and disappears completely on dawn paper. The dawn set is
    // the same flower at a depth that survives a near-white backdrop.
    //
    // Alpha is NOT baked in. The per-frame opacity write owns the petal's
    // overall presence, and the shader thins the blade further wherever its own
    // curvature turns a part of it edge-on.
    // The night set used to top out around 15% saturation (#FFD7E4 and paler).
    // On its own that is a fair sakura, but it is not what shipped: the shader
    // dropped an unlit blade to 62% of its body colour, bleached 40% of the rim
    // toward white, and the compositor then thinned the result against a
    // near-black canvas. A #FFD7E4 petal at a typical 0.6 alpha arrived on the
    // deck as #544750 — 8% saturation, which the eye reads as grey debris, not
    // blossom. Same hues, ~2x the chroma, so what survives all three steps is
    // still recognisably pink. See also AMBIENT_NIGHT and the rim wash in
    // sakura-model.ts: this was never a one-number problem.
    const NIGHT_COLORS = [
        [1.000, 0.816, 0.886],
        [1.000, 0.780, 0.860],
        [1.000, 0.706, 0.812],
        [1.000, 0.643, 0.769],
        [1.000, 0.576, 0.722],
    ];
    const DAWN_COLORS = [
        [0.937, 0.561, 0.694],
        [0.898, 0.455, 0.624],
        [0.949, 0.651, 0.757],
        [0.851, 0.416, 0.580],
        [0.973, 0.761, 0.835],
    ];
    const isLight = () => document.documentElement.getAttribute('data-theme') === 'light';
    const pickColor = () => {
        const set = isLight() ? DAWN_COLORS : NIGHT_COLORS;
        return set[Math.floor(Math.random() * set.length)];
    };
    // The renderer owns the two canvases and all the GL state. If the platform
    // cannot give us WebGL2 the field simply does not run: it is decoration,
    // and a second full software renderer kept alive for a case Tauri's own
    // WebView never hits would be more code than the effect is worth.
    const renderer = new SakuraRenderer(container);
    if (!renderer.ok) {
        sakuraRunning = false;
        return;
    }
    sakuraRenderer = renderer;
    // `function` declarations below are hoisted, which drops the null-narrowing
    // the early return above established on `container`. Capture it once.
    const host = container;
    const petals = [];
    const TAU = Math.PI * 2;
    /** Shared empty array for single petals — they have no lobes to jitter, and
     *  handing every one of them its own [] is 30-odd dead allocations. */
    const EMPTY_JITTER = [];
    // Density scales with the window: a fixed 30 was a blizzard at the 800x600
    // floor and a drizzle on a wide monitor. Petals are recycled in place once
    // the sky is full, so this is also the total DOM node count for the effect.
    // Density is per unit AREA, so halving the petal size leaves the same count
    // covering a quarter of the ink and the sky reads empty. The divisor comes
    // down to hold the composition, not to make it busier: 1280x800 goes from
    // 31 petals to 37.
    const MAX_PETALS = Math.max(16, Math.min(44, Math.round(((container.clientWidth || window.innerWidth) *
        (container.clientHeight || window.innerHeight)) / 28000)));
    /**
     * The basal flush, derived from whatever body colour the petal is wearing.
     *
     * Real petals hold more colour where they met the flower, so this is warmed
     * and deepened off the body rather than picked independently — it has to
     * belong to the same blossom. Both callers (a fresh petal, and a live one
     * re-tinted by a theme flip) go through here so the two can never disagree.
     */
    function setBaseTint(p) {
        p.baseR = Math.min(1, p.r * 1.02);
        p.baseG = p.g * 0.76;
        p.baseB = p.b * 0.80;
    }
    /**
     * Give a petal a fresh set of initial conditions.
     *
     * `seeded` spreads it over the whole column instead of dropping it in from
     * above: at start-up the sky used to be empty and took ~15s to fill, so the
     * first thing anyone saw was the one state the effect should never be in.
     */
    function resetPetal(p, width, height, seeded) {
        // Depth is the whole parallax model: a near petal is bigger, falls
        // faster, is more solid, and renders in FRONT of the deck rather than
        // behind it. Very slightly biased near so the front layer is populated.
        const depth = Math.pow(Math.random(), 0.9);
        // 7-17px, down from 9-26px. At the old near size a petal was a
        // palm-sized object drifting across a dashboard. The floor matters as
        // much as the ceiling though: below ~7px the far tier stops being a
        // shape at all and becomes a speck of dust.
        const size = 7 + depth * 10;
        const speed = 0.72 + depth * 0.55;
        p.depth = depth;
        p.size = size;
        p.x = Math.random() * Math.max(1, width) - size / 2;
        p.y = seeded
            ? Math.random() * height
            : -size - 20 - Math.random() * 90;
        p.vx = (Math.random() - 0.5) * 20;
        p.vy = 20 + Math.random() * 25;
        p.angle = Math.random() * 360;
        p.life = seeded ? 3 : 0;
        // A falling plate does one of two things, and which one depends on how
        // heavy it is for its area (the Föppl–von Kármán regime split): light
        // plates FLUTTER — they rock about broadside and never turn over —
        // while heavier ones TUMBLE, rotating continuously and flashing edge-on.
        // A sky of pure tumblers is what the first cut produced, and it read as
        // a scatter of thin white slashes rather than blossom. Real petals are
        // overwhelmingly flutterers, so that is the mix here too.
        // The flip axis is not a fixed hinge: it precesses slowly, so the petal
        // wobbles in three dimensions instead of pivoting like a shop sign.
        // Slowly is the operative word — at the old rate the axis swung far
        // enough DURING a flip that the petal appeared to gyrate, which is a
        // large part of what read as "spinning stupidly". A real plate carries
        // angular momentum and holds its axis; it only drifts.
        p.axisAngle = Math.random() * Math.PI;
        p.precess = (Math.random() - 0.5) * 0.15;
        p.axisX = Math.cos(p.axisAngle);
        p.axisY = Math.sin(p.axisAngle);
        p.sway = Math.random() * TAU;
        p.swayBoost = 0;
        // Weathervaning now owns the in-plane angle almost entirely (see p.spin
        // below), so it is pulled up to match.
        p.vane = 0.38 + Math.random() * 0.5;
        // ---- form. No two bodies are the same object -----------------------
        // These feed the surface in sakura-model.ts, and they are the reason a
        // petal reads as a curved membrane rather than a rotated sheet: the CUP
        // puts a bright crescent down one flank and shadow on the other, and
        // because it is geometry, that highlight slides across the blade as the
        // petal turns instead of turning with it.
        //
        // Signs are randomised rather than mirroring the mesh: a negative scale
        // would invert the surface's own normals and light the petal inside-out.
        p.aspect = 0.90 + Math.random() * 0.22;
        p.cup = (Math.random() < 0.5 ? -1 : 1) * (0.14 + Math.random() * 0.18);
        p.twist = (Math.random() < 0.5 ? -1 : 1) * (0.08 + Math.random() * 0.28);
        // Kept small: past ~0.12 the blade folds into a scoop and reads as a
        // taco shell rather than a petal with a little arc in it.
        p.bend = (Math.random() < 0.5 ? -1 : 1) * (0.03 + Math.random() * 0.08);
        // ---- which sakura -------------------------------------------------
        // One outline for every petal is what makes a field read as wallpaper.
        // The silhouette is a shader parameter now, so a body can be a
        // different FLOWER rather than the same one at a different angle.
        const rgb = pickColor();
        p.r = rgb[0];
        p.g = rgb[1];
        p.b = rgb[2];
        p.lobes = 1;
        p.lobeJitter = EMPTY_JITTER;
        setBaseTint(p);
        const kind = Math.random();
        if (kind < 0.40) {
            // somei-yoshino — the one everybody pictures. Moderate everything.
            p.neck = 1.35 + Math.random() * 0.25;
            p.dome = 0.38 + Math.random() * 0.08;
            p.notch = 0.09 + Math.random() * 0.04;
        }
        else if (kind < 0.62) {
            // a slim, deeply cleft petal — long neck, tighter tip
            p.neck = 1.12 + Math.random() * 0.16;
            p.dome = 0.27 + Math.random() * 0.08;
            p.notch = 0.12 + Math.random() * 0.05;
            p.aspect *= 0.80;
        }
        else if (kind < 0.80) {
            // broad-shouldered, barely cleft — the rounder yaezakura petal,
            // and a deeper pink to go with it
            p.neck = 1.85 + Math.random() * 0.35;
            p.dome = 0.46 + Math.random() * 0.08;
            p.notch = 0.03 + Math.random() * 0.04;
            p.aspect *= 1.12;
            p.g *= 0.90;
            p.b *= 0.94;
        }
        else if (kind < 0.92) {
            // one that has been off the tree a while: a firmer curl and more
            // twist, colour drawn back toward the base. Multipliers kept
            // moderate — much past this the blade folds along its midline and
            // the silhouette pinches into a V, which reads as a torn leaf
            // rather than a curled petal.
            p.neck = 1.30 + Math.random() * 0.30;
            p.dome = 0.34 + Math.random() * 0.10;
            p.notch = 0.08 + Math.random() * 0.05;
            p.cup *= 1.15;
            p.twist *= 1.3;
            p.notch *= 0.7; // a hard curl already deepens the cleft optically
            p.baseG *= 0.90;
            p.baseB *= 0.92;
        }
        else {
            // A WHOLE BLOSSOM: five lobes sharing this body's centre, tumble
            // and fall. They turn about their BASE (pivot, in the model) so the
            // five meet in the middle, and the basal tint becomes the flower's
            // gold throat where they do.
            p.lobes = 5;
            p.neck = 1.45 + Math.random() * 0.25;
            p.dome = 0.42 + Math.random() * 0.08;
            p.notch = 0.09 + Math.random() * 0.04;
            p.aspect *= 1.05;
            // A flower is a bigger object than a loose petal.
            p.size *= 1.5;
            p.cup = 0.20 + Math.random() * 0.10; // lobes cup the same way: a dish
            p.twist *= 0.35;
            p.baseR = 1.0;
            p.baseG = 0.88;
            p.baseB = 0.58;
            p.lobeJitter = [0, 1, 2, 3, 4].map(() => (Math.random() - 0.5) * 0.20);
        }
        if (Math.random() < 0.93) {
            // Flutterer: rocks about broadside and never turns over. Raised from
            // 76% — one petal in four doing continuous revolutions is far more
            // than a real fall shows, and a revolving petal is the one that
            // catches the eye and looks wrong.
            // Slower and much shallower than before: the rock now takes
            // 1.4-3.3s instead of 1.0-2.4s, and reaches 26-49° instead of
            // 40-72°.
            //
            // The amplitude is the important one. tumble = amp·sin(sway) is a
            // sinusoid, and a sinusoid is SLOWEST at its turning points — so a
            // petal spends most of its life near maximum tilt, not near
            // broadside. At 72° maximum that meant most petals, most of the
            // time, were foreshortened to a third of their width: a sky of thin
            // slivers, which is the "flat paper" read. Keeping the extreme
            // shallow means even the dwell attitude still shows a petal.
            p.tumbleAmp = 0.45 + Math.random() * 0.40;
            p.swayFreq = 0.30 + Math.random() * 0.42;
            p.tumble = p.tumbleAmp * Math.sin(p.sway);
            p.tumbleBase = 0;
            p.tumbleRate = 0;
        }
        else {
            // Tumbler: turns over continuously — but at 17-43°/s, not the old
            // 46-132°/s. A petal that takes ~10s to complete a revolution reads
            // as a heavy one turning over; one that took 3s read as a coin flip.
            p.tumbleAmp = 0;
            p.swayFreq = 0.1 + Math.random() * 0.16;
            p.tumble = Math.random() * TAU;
            p.tumbleBase = (Math.random() < 0.5 ? -1 : 1) * (0.30 + Math.random() * 0.45);
            p.tumbleRate = p.tumbleBase;
        }
        // Fall speeds at the two extremes of the plate's attitude. A real petal
        // held broadside sinks; turned edge-on it drops nearly three times as
        // fast. That ratio IS the falling-leaf motion. Eased down with the size:
        // a smaller object crossing the screen at the same px/s reads as moving
        // faster, and these are meant to drift.
        p.vBroad = (20 + Math.random() * 10) * speed;
        p.vEdge = (64 + Math.random() * 28) * speed;
        p.lift = 0.9 + Math.random() * 0.7;
        // In-plane spin, ±5.5°/s — was ±21°/s. A petal turning steadily in the
        // screen plane is a pinwheel, and nothing about falling blossom looks
        // like a pinwheel. What little is left is a bias the weathervane term
        // fights, so the petal leans into its path instead of spinning in it.
        p.spin = (Math.random() - 0.5) * 11;
    }
    /**
     * Which side of the UI a petal passes on.
     *
     * The whole field used to sit at z-index 0 behind `.app` (z-index 1), and
     * once the panels went opaque there was nowhere left for a petal to be
     * seen — the effect was running perfectly and rendering nothing. Depth
     * decides: the far half stays behind the deck and is OCCLUDED by the
     * panels, which is the parallax cue; the near half drifts in front. The
     * split is why there are two canvases — see SakuraRenderer. Both are
     * pointer-events:none, so nothing becomes unclickable, and modals/toasts
     * live far above either (--z-modal / --z-toast).
     *
     * Requires `#sakura-container` to stay stacking-context-free (no transform,
     * no will-change, z-index:auto) — see the sakura block in orbital.css.
     */
    function createPetal(seeded = false) {
        if (petals.length >= MAX_PETALS)
            return;
        const p = {
            x: 0, y: 0, vx: 0, vy: 0, angle: 0, size: 12, life: 0, depth: 0.5,
            tumble: 0, tumbleAmp: 1, tumbleRate: 0, tumbleBase: 0,
            axisAngle: 0, precess: 0, axisX: 1, axisY: 0,
            sway: 0, swayFreq: 0.4, swayBoost: 0, vane: 0.4,
            vBroad: 30, vEdge: 90, lift: 1, spin: 0,
            aspect: 1, cup: 0.2, twist: 0.2, bend: 0.08,
            neck: 1.4, dome: 0.4, notch: 0.1, lobes: 1, lobeJitter: EMPTY_JITTER,
            r: 1, g: 0.8, b: 0.87, baseR: 1, baseG: 0.62, baseB: 0.7,
        };
        resetPetal(p, host.clientWidth || window.innerWidth, host.clientHeight || window.innerHeight, seeded);
        petals.push(p);
    }
    // ---- Physics simulation -------------------------------------------------
    // Thin-plate aerodynamics, integrated per frame (semi-implicit Euler). The
    // one state variable that matters is `tumble` — the petal's attitude to the
    // airflow — and both force laws are read off it:
    //
    //   drag ∝ projected area        area = |cos(tumble)|
    //        broadside (area 1) → sinks at vBroad; edge-on (area 0) → drops at
    //        vEdge, ~3x faster. The petal therefore hesitates, slips, hesitates.
    //   lift ∝ sin(2·tumble)·v
    //        an inclined plate deflects air sideways, hardest at 45°, zero when
    //        flat or edge-on, and it REVERSES as the petal flips through. That
    //        sign change is the zigzag; nothing draws it explicitly.
    //
    // On top of that: a two-sine breeze with an occasional gust envelope (and
    // faster air aloft), linear drag, an in-plane spin, and a cursor field that
    // both pushes radially and swirls tangentially, so a flick of the mouse
    // leaves a small vortex instead of a shove. All forces feed VELOCITY, so
    // every reaction is a continuous curve.
    const V_RELAX = 2.4; // 1/s vertical relaxation toward the drag target
    const H_DRAG = 1.35; // 1/s horizontal air drag
    const BREEZE_PULL = 0.75; // 1/s entrainment into the breeze (at full area)
    const TUMBLE_RELAX = 0.9; // 1/s return of the flip rate to its baseline
    const CURSOR_RADIUS = 145; // px
    const CURSOR_FORCE = 1250; // px/s² at the cursor, quadratic falloff
    const CURSOR_SWIRL = 560; // px/s² tangential component — the vortex
    const CURSOR_WIND = 0.85; // fraction of cursor velocity entrained
    const SPAWN_RATE = 1.4; // petals/s (jittered, see the spawn accumulator)
    // Key light, screen space, y down: upper-left and in front of the deck.
    // Unit length, so the shader's Lambert term needs no normalising per frame.
    const LIGHT_DIR = [-0.46, -0.56, 0.69];
    // How much of its body colour a petal keeps on the side facing away from the
    // key light. It is a per-THEME value, not a per-scene one, because the two
    // canvases fight the shading in opposite directions: source-over onto
    // near-black subtracts value a second time, so the night field needs a high
    // floor to arrive as blossom rather than as a smudge; on dawn paper value is
    // exactly what makes a petal vanish, so the floor stays low and the shading
    // is allowed to do its work. One number for both was why the field only ever
    // looked right in one of them.
    const AMBIENT_NIGHT = 0.82;
    const AMBIENT_DAWN = 0.60;
    let pointerX = -9999;
    let pointerY = -9999;
    let pointerVX = 0;
    let pointerVY = 0;
    let lastPointerT = 0;
    const pointerMoveHandler = (e) => {
        const now = performance.now();
        if (lastPointerT > 0) {
            const pdt = Math.max(8, now - lastPointerT) / 1000;
            // low-pass the cursor velocity so a flick reads as a gust, not a spike
            pointerVX = pointerVX * 0.7 + ((e.clientX - pointerX) / pdt) * 0.3;
            pointerVY = pointerVY * 0.7 + ((e.clientY - pointerY) / pdt) * 0.3;
        }
        pointerX = e.clientX;
        pointerY = e.clientY;
        lastPointerT = now;
    };
    const pointerLeaveHandler = () => {
        pointerX = -9999;
        pointerY = -9999;
        pointerVX = 0;
        pointerVY = 0;
        lastPointerT = 0;
    };
    // Reused every frame: the renderer copies out of it immediately, so there is
    // no allocation in the loop.
    const draw = [];
    // Undebounced ON PURPOSE: SakuraRenderer.resize applies the CSS size (which
    // the shader needs immediately, or petals in the newly exposed strip map off
    // screen) and defers only the drawing-buffer reallocation internally.
    const syncRendererSize = () => {
        renderer.resize(container.clientWidth || window.innerWidth, container.clientHeight || window.innerHeight);
    };
    syncRendererSize();
    const resizeHandler = () => syncRendererSize();
    window.addEventListener('resize', resizeHandler);
    sakuraDisposers.push(() => window.removeEventListener('resize', resizeHandler));
    // A GPU reset (Windows TDR, driver update, RDP session change, hybrid-GPU
    // handoff) kills the context; the layers' programs and buffers die with it,
    // so recovery is a full teardown + rebuild, once, off the restore event.
    // Doing it from the frame loop instead would create and destroy two contexts
    // per frame for the whole length of the reset.
    renderer.onContextRestored(() => {
        // Ignore a late event from a renderer that has already been replaced or
        // switched off (the Settings toggle, a page teardown).
        if (!sakuraEnabled || sakuraRenderer !== renderer)
            return;
        stopSakura();
        initSakuraAnimation();
    });
    let simTime = 0;
    let spawnAcc = 0;
    let lastThemeLight = isLight();
    let lastFrame = performance.now();
    let rafId = requestAnimationFrame(function simTick(now) {
        rafId = requestAnimationFrame(simTick);
        let dt = (now - lastFrame) / 1000;
        lastFrame = now;
        if (dt <= 0)
            return;
        if (dt > 0.05)
            dt = 0.05; // clamp tab-switch / hidden-window spikes
        // The GL context is gone (driver reset). Idle the frame — the loop stays
        // alive so the webglcontextrestored handler above can rebuild, but there
        // is no point integrating 44 bodies that nothing can draw. Rebuilding
        // from HERE is what must not happen: during a TDR a fresh context
        // usually creates and is immediately lost, which turns a per-frame retry
        // into a context create/destroy loop.
        if (!renderer.ok)
            return;
        simTime += dt;
        // the cursor's gust decays between mouse events
        const gustDecay = Math.exp(-3 * dt);
        pointerVX *= gustDecay;
        pointerVY *= gustDecay;
        const height = container.clientHeight || window.innerHeight;
        const width = container.clientWidth || window.innerWidth;
        const floor = height + 60;
        draw.length = 0;
        // One attribute read per frame (not per petal) catches a theme flip and
        // re-tints the whole field at once. Without it, blossom mixed for the
        // midnight canvas would hang around invisibly on dawn paper until every
        // petal had recycled — up to ~15 seconds of a bare sky.
        const lightNow = isLight();
        if (lightNow !== lastThemeLight) {
            lastThemeLight = lightNow;
            for (const p of petals) {
                const rgb = pickColor();
                p.r = rgb[0];
                p.g = rgb[1];
                p.b = rgb[2];
                // The basal flush is DERIVED from the body colour, so re-tinting
                // one without the other left every live petal wearing the new
                // theme's blade over the old theme's throat — a dawn-deep base
                // under a night-pale body, which the shader mixes across the
                // bottom 42% of the blade. Kept in step with resetPetal().
                setBaseTint(p);
            }
        }
        // Spawning lives in the sim now, not a setInterval: one petal exactly
        // every 1000ms is a metronome you can hear, and an interval also keeps
        // firing while the window is hidden. The accumulator is consumed in
        // uneven bites, so arrivals scatter the way real ones do.
        spawnAcc += dt * SPAWN_RATE;
        while (spawnAcc >= 1) {
            spawnAcc -= 0.55 + Math.random() * 0.9;
            createPetal();
        }
        // Breeze: two slow sines that never quite repeat, times a rare gust
        // envelope (^6 keeps it near zero most of the time and then surges).
        const gust = Math.pow(Math.max(0, Math.sin(simTime * 0.079 + 0.9)), 6);
        const breeze = (15 * Math.sin(simTime * 0.27) + 10 * Math.sin(simTime * 0.101 + 1.7))
            * (1 + 2.4 * gust);
        for (const p of petals) {
            p.life += dt;
            // --- attitude to the airflow: the source of both force laws ------
            const cosT = Math.cos(p.tumble);
            const sinT = Math.sin(p.tumble);
            const area = Math.abs(cosT); // 1 = broadside, 0 = edge-on
            // Advance the attitude. Flutterers ride a bounded oscillator;
            // tumblers integrate a rate that rises with fall speed. Disturbed
            // air (the cursor, below) kicks swayBoost, which decays back out.
            p.swayBoost -= p.swayBoost * 1.4 * dt;
            p.sway += (p.swayFreq * TAU + p.swayBoost) * dt;
            if (p.tumbleAmp > 0) {
                p.tumble = p.tumbleAmp * Math.sin(p.sway);
            }
            else {
                p.tumbleRate += (p.tumbleBase - p.tumbleRate) * TUMBLE_RELAX * dt;
                // The sway term rides ON TOP of a continuous revolution, so it
                // is a wobble in the flip, not a flip of its own — at 0.35 it
                // was comparable to the revolution itself and the two beat
                // against each other into something that looked broken.
                p.tumble += (p.tumbleRate * (0.5 + 0.5 * (p.vy / p.vEdge))
                    + 0.16 * Math.sin(p.sway)) * dt;
            }
            // Wind is faster aloft, and a broadside petal is pushed by it far
            // more than an edge-on one. On top of the global breeze sit two
            // travelling waves keyed to POSITION, so the air is not identical
            // everywhere at once: petals a few hundred pixels apart drift on
            // different local eddies, the way real ones do. The vertical
            // component is scaled by the gust, so during a surge it can briefly
            // exceed a petal's broadside sink rate and lift it back up.
            const eddyX = 11 * Math.sin(p.y * 0.0115 + simTime * 0.63)
                + 7 * Math.sin(p.x * 0.0082 - simTime * 0.41);
            const eddyY = (9 * Math.sin(p.x * 0.0134 - simTime * 0.52)
                + 5 * Math.sin(p.y * 0.0093 + simTime * 0.29)) * (1 + 2.2 * gust);
            const windHere = (breeze + eddyX)
                * (0.72 + 0.38 * (1 - Math.min(1, Math.max(0, p.y / height))));
            const lift = p.lift * p.vy * sinT * cosT * 2; // ∝ sin(2·tumble)
            let ax = lift + (windHere - p.vx) * BREEZE_PULL * (0.35 + 0.65 * area);
            let ay = 0;
            // cursor field: radial push + tangential swirl + entrained air
            if (pointerX > -999) {
                const dx = p.x + p.size / 2 - pointerX;
                const dy = p.y + p.size / 2 - pointerY;
                const dist = Math.hypot(dx, dy);
                if (dist < CURSOR_RADIUS && dist > 0.01) {
                    const fall = 1 - dist / CURSOR_RADIUS;
                    const push = CURSOR_FORCE * fall * fall;
                    const swirl = CURSOR_SWIRL * fall * fall;
                    ax += (dx / dist) * push - (dy / dist) * swirl + pointerVX * CURSOR_WIND * fall;
                    ay += (dy / dist) * push + (dx / dist) * swirl + pointerVY * CURSOR_WIND * fall;
                    // disturbed air also spins the petal up — a flutterer rocks
                    // harder, a tumbler turns faster. Both decay back out.
                    p.swayBoost += fall * fall * 26 * dt;
                    if (p.tumbleAmp === 0) {
                        // Halved with the tumble rates themselves — a cursor
                        // sweep used to spin a tumbler up far past anything the
                        // relaxation could pull back in a readable time.
                        p.tumbleRate += Math.sign(p.tumbleBase) * fall * fall * 4 * dt;
                    }
                }
            }
            // integrate: horizontal drag; vertical chases the speed the current
            // projected area allows, offset by the local updraft/downdraft
            p.vx += ax * dt;
            p.vx -= p.vx * H_DRAG * dt;
            const vyTarget = p.vEdge - (p.vEdge - p.vBroad) * area + eddyY;
            p.vy += ay * dt + (vyTarget - p.vy) * V_RELAX * dt;
            p.x += p.vx * dt;
            p.y += p.vy * dt;
            // In-plane orientation. A free plate WEATHERVANES: it turns until its
            // long axis lines up with the airflow it is moving through, which is
            // why a drifting petal visibly leans the way it is travelling. The
            // pull is deliberately weak and fights the petal's own spin, so the
            // result is a lazy oversteer-and-settle rather than a locked arrow.
            const heading = Math.atan2(p.vy, p.vx) * 180 / Math.PI - 90;
            const off = ((heading - p.angle + 540) % 360) - 180;
            p.angle += (p.spin + off * p.vane) * dt;
            // …and the flip axis drifts, so the petal wobbles in 3D rather than
            // pivoting on a fixed hinge.
            p.axisAngle += p.precess * dt;
            p.axisX = Math.cos(p.axisAngle);
            p.axisY = Math.sin(p.axisAngle);
            // Off the floor, or blown clean out of frame → recycle from the top.
            // The old code teleported a petal to the opposite edge at whatever
            // height it had, so one could pop into existence mid-screen.
            if (p.y > floor || p.x < -p.size - 90 || p.x > width + p.size + 90) {
                resetPetal(p, width, height, false);
                continue;
            }
            // Overall presence. Depth sets how solid a petal is; the attitude
            // term is deliberately gentle now, because the SHADER thins each
            // part of the blade by its own local normal — a whole-petal fade on
            // top of that would just grey the field out. That per-fragment
            // thinning is something the sprite could never do: a curled petal
            // stays solid where it faces you and goes to nothing along the
            // edge that has rolled away, in the same frame.
            const fadeIn = Math.min(1, p.life * 1.6);
            const alpha = (0.52 + 0.46 * p.depth) * (0.62 + 0.38 * area) * fadeIn;
            const baseAngle = p.angle * Math.PI / 180;
            const cx = p.x + p.size / 2;
            const cy = p.y + p.size / 2;
            for (let k = 0; k < p.lobes; k++) {
                // A single petal turns about its own middle (pivot 0). A
                // blossom's five lobes turn about their BASE, which is what
                // brings them together into one flower instead of five petals
                // orbiting a hole.
                const theta = p.lobes === 1
                    ? baseAngle
                    : baseAngle + k * (TAU / 5) + p.lobeJitter[k];
                // The shader tumbles FIRST and rotates in-plane second. For a
                // flower that is the wrong order — each lobe would tumble about
                // its own axis and the blossom would come apart. Since
                // Rz(θ)·R_a(t) = R_{Rz(θ)·a}(t), feeding each lobe the axis
                // pre-rotated by -θ makes the whole arrangement tumble about
                // ONE shared axis, as a rigid flower.
                let ax = p.axisX;
                let ay = p.axisY;
                if (p.lobes > 1) {
                    const c = Math.cos(theta);
                    const s = Math.sin(theta);
                    ax = p.axisX * c + p.axisY * s;
                    ay = -p.axisX * s + p.axisY * c;
                }
                // No flower has five identical petals. The angular jitter
                // doubles as a size jitter so the lobes are not a stamped
                // pentagon.
                const lobeScale = p.lobes === 1 ? 1 : 1 + p.lobeJitter[k] * 0.55;
                draw.push({
                    x: cx,
                    y: cy,
                    sizeX: p.size * p.aspect * lobeScale,
                    sizeY: p.size * lobeScale,
                    angle: theta,
                    axisX: ax,
                    axisY: ay,
                    tumble: p.tumble,
                    cup: p.cup,
                    twist: p.twist,
                    bend: p.bend,
                    // -0.44, not -0.52. At -0.52 a lobe's base sits exactly on
                    // the flower's centre — and the base is where the width
                    // profile goes to zero, so five of them met at a point and
                    // left a hole punched through the middle of every blossom.
                    // The extra 0.08 carries each lobe past the centre so they
                    // overlap and close it, which is also where the gold throat
                    // comes from.
                    pivot: p.lobes === 1 ? 0 : -0.44,
                    neck: p.neck,
                    dome: p.dome,
                    notch: p.notch,
                    r: p.r,
                    g: p.g,
                    b: p.b,
                    baseR: p.baseR,
                    baseG: p.baseG,
                    baseB: p.baseB,
                    alpha,
                    depth: p.depth,
                });
            }
        }
        renderer.render(draw, LIGHT_DIR, lastThemeLight ? AMBIENT_DAWN : AMBIENT_NIGHT);
        sakuraStats.count = petals.length;
        sakuraStats.frames++;
    });
    // Seed the sky FULL immediately rather than starting empty and filling over
    // ~20s: the old init dropped 15 petals in from above at 300ms intervals, so
    // the first thing anyone saw was an empty sky and a thin trickle.
    // rAF is paused while the document is hidden, so no visibility gating.
    for (let i = 0; i < MAX_PETALS; i++)
        createPetal(true);
    document.addEventListener('mousemove', pointerMoveHandler, { passive: true });
    document.addEventListener('mouseleave', pointerLeaveHandler);
    sakuraDisposers.push(() => {
        document.removeEventListener('mousemove', pointerMoveHandler);
        document.removeEventListener('mouseleave', pointerLeaveHandler);
        if (rafId !== null)
            cancelAnimationFrame(rafId);
        rafId = null;
    });
}
// ============================================================================
// Navigation
// ============================================================================
function initNavigation() {
    document.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', () => {
            const page = item.dataset.page;
            if (page)
                switchPage(page);
        });
    });
    // Button handlers
    document.getElementById('btn-start')?.addEventListener('click', startBot);
    document.getElementById('btn-dev')?.addEventListener('click', startDevBot);
    document.getElementById('btn-stop')?.addEventListener('click', stopBot);
    document.getElementById('btn-restart')?.addEventListener('click', restartBot);
    // Quick action buttons (replaced inline onclick for CSP compliance)
    document.getElementById('btn-open-logs')?.addEventListener('click', () => openFolder('logs'));
    document.getElementById('btn-open-data')?.addEventListener('click', () => openFolder('data'));
    document.getElementById('btn-overlay-start')?.addEventListener('click', () => { switchPage('status'); startBot(); });
    document.getElementById('btn-auto-scroll')?.addEventListener('click', toggleAutoScroll);
    document.getElementById('btn-clear-logs')?.addEventListener('click', clearLogs);
    document.getElementById('btn-refresh-logs')?.addEventListener('click', loadLogs);
    document.getElementById('btn-clear-history')?.addEventListener('click', clearHistory);
    document.getElementById('btn-delete-selected')?.addEventListener('click', deleteSelectedChannels);
    // Settings handlers
    document.getElementById('refresh-interval')?.addEventListener('change', (e) => {
        const value = parseInt(e.target.value);
        updateSetting('refreshInterval', value);
        showToast(`Refresh interval: ${value / 1000}s`, { type: 'info' });
    });
    document.getElementById('notifications-toggle')?.addEventListener('change', (e) => {
        updateSetting('notifications', e.target.checked);
    });
    document.getElementById('sakura-toggle')?.addEventListener('change', (e) => {
        const enabled = e.target.checked;
        updateSetting('sakuraEnabled', enabled);
        setSakuraEnabled(enabled);
    });
    // Density toggle (CONTRACT): compact mode tightens card/section padding via
    // <html data-density="compact"> (CSS already maps that to --density:.7).
    document.getElementById('setting-density')?.addEventListener('change', (e) => {
        const compact = e.target.checked;
        updateSetting('densityCompact', compact);
        applyDensity(compact);
    });
    document.getElementById('sound-toggle')?.addEventListener('change', (e) => {
        const enabled = e.target.checked;
        updateSetting('soundEnabled', enabled);
        if (enabled)
            showToast('Click sounds enabled', { type: 'info', duration: 2000 });
    });
    document.getElementById('haptic-toggle')?.addEventListener('change', (e) => {
        const enabled = e.target.checked;
        updateSetting('hapticEnabled', enabled);
        if (enabled)
            showToast('Haptic feedback enabled', { type: 'info', duration: 2000 });
    });
    document.getElementById('telemetry-toggle')?.addEventListener('change', async (e) => {
        const enabled = e.target.checked;
        try {
            await invoke('set_telemetry_enabled', { enabled });
            showToast(enabled
                ? 'Crash reports enabled (restart bot to take effect)'
                : 'Crash reports disabled (restart bot to take effect)', { type: 'info', duration: 3000 });
        }
        catch (err) {
            // Unlike every other toggle here, this one is NOT mirrored in
            // localStorage — it is a file on disk the Python bot reads. A failed
            // write (file locked by the running bot, read-only install dir, IPC
            // busy) used to leave the switch sitting in the position the backend
            // rejected, so a privacy-relevant control reported the opposite of
            // the truth until the user navigated away and back. Put it back.
            e.target.checked = !enabled;
            console.error('set_telemetry_enabled failed:', err);
            showToast('Failed to update telemetry preference', { type: 'error' });
        }
    });
    // User name input handler
    document.getElementById('user-name-input')?.addEventListener('input', (e) => {
        const value = e.target.value.trim();
        updateSetting('userName', value || 'You');
    });
    // Save profile to AI button
    document.getElementById('btn-save-profile')?.addEventListener('click', () => {
        saveProfileToAI();
    });
    // Avatar upload handlers
    document.getElementById('btn-change-avatar')?.addEventListener('click', () => {
        document.getElementById('avatar-input')?.click();
    });
    document.getElementById('avatar-input')?.addEventListener('change', (e) => {
        const input = e.target;
        const file = input.files?.[0];
        if (file)
            handleAvatarUpload(file, 'user');
        // Reset so re-selecting the SAME file after cancelling the cropper fires
        // 'change' again — a file input emits it only when the value differs.
        input.value = '';
    });
    document.getElementById('btn-remove-avatar')?.addEventListener('click', () => {
        removeAvatar('user');
    });
    // AI Avatar upload handlers
    document.getElementById('btn-change-ai-avatar')?.addEventListener('click', () => {
        document.getElementById('ai-avatar-input')?.click();
    });
    document.getElementById('ai-avatar-input')?.addEventListener('change', (e) => {
        const input = e.target;
        const file = input.files?.[0];
        if (file)
            handleAvatarUpload(file, 'ai');
        // Reset so re-selecting the SAME file after cancelling the cropper fires
        // 'change' again — a file input emits it only when the value differs.
        input.value = '';
    });
    document.getElementById('btn-remove-ai-avatar')?.addEventListener('click', () => {
        removeAvatar('ai');
    });
    // Creator toggle handler
    document.getElementById('creator-toggle')?.addEventListener('change', (e) => {
        settings.isCreator = e.target.checked;
        saveSettings();
    });
    // Log filter change handler — refresh logs immediately when filter changes
    document.getElementById('log-filter')?.addEventListener('change', () => {
        loadLogs();
    });
}
// AI History page manager — uses ChatManager's WebSocket for transport, so
// it is created right after initChatManager() and wired both ways: outgoing
// frames go through chatManager.send, incoming ai_* frames are forwarded
// back via chatManager.historyManager (see chat-manager.ts handleMessage).
function initHistoryManager() {
    historyManager = new HistoryManager({
        send: (data) => chatManager?.send(data) ?? false,
        isConnected: () => chatManager?.connected ?? false,
        connect: () => chatManager?.connect(),
    });
    historyManager.init();
    if (chatManager)
        chatManager.historyManager = historyManager;
}
function switchPage(page) {
    // Resolve stale aliases (config→settings) then reject anything unknown, so
    // a bad page id can't blank the UI by deactivating every .page section.
    const resolved = resolvePage(page);
    if (resolved === null)
        return;
    page = resolved;
    currentPage = page;
    document.querySelectorAll('.nav-item').forEach(item => {
        const itemPage = item.dataset.page;
        const isActive = itemPage === page;
        item.classList.toggle('active', isActive);
        // a11y: expose the selected page to assistive tech, not just visually.
        if (isActive) {
            item.setAttribute('aria-current', 'page');
        }
        else {
            item.removeAttribute('aria-current');
        }
    });
    document.querySelectorAll('.page').forEach(p => {
        p.classList.toggle('active', p.id === `page-${page}`);
    });
    if (page === 'logs') {
        loadLogs();
        startLogsRefresh();
    }
    else {
        stopLogsRefresh();
    }
    if (page === 'database')
        loadDbStats();
    if (page === 'settings') {
        loadSettingsUI();
        void populatePathsCard();
    }
    if (page === 'chat' && chatManager) {
        // Reconnect if disconnected
        if (!chatManager.connected) {
            chatManager.connect();
        }
        chatManager.listConversations();
        // Ensure correct container visibility based on current state
        if (chatManager.currentConversation) {
            chatManager.showChatContainer();
        }
        else {
            chatManager.hideChatContainer();
        }
    }
    if (page === 'history' && chatManager) {
        // Same WS-readiness mechanism as the chat hook above: reconnect if
        // disconnected, then request data. onEnter() queues the channels
        // request until the 'connected' frame when the socket is still down.
        if (!chatManager.connected) {
            chatManager.connect();
        }
        historyManager?.onEnter();
    }
}
// ============================================================================
// Optimized Refresh Loop
// ============================================================================
function startRefreshLoop() {
    if (refreshInterval) {
        clearInterval(refreshInterval);
        refreshInterval = null;
    }
    // Don't run the status poll while the window is hidden — mirror the logs /
    // sakura pause pattern. The visibilitychange handler restarts the loop on
    // the next show event. A one-shot updateStatus() still runs so a manual
    // startRefreshLoop() (e.g. interval change) refreshes immediately, but only
    // when visible.
    if (document.visibilityState === 'hidden') {
        return;
    }
    refreshInterval = window.setInterval(updateStatus, settings.refreshInterval);
    updateStatus();
}
function stopRefreshLoop() {
    if (refreshInterval !== null) {
        clearInterval(refreshInterval);
        refreshInterval = null;
    }
}
function restartRefreshLoop() {
    startRefreshLoop();
}
// Debounce helper for performance
export function debounce(fn, key, delay) {
    return () => {
        const existing = debounceTimers.get(key);
        if (existing) {
            clearTimeout(existing);
        }
        debounceTimers.set(key, window.setTimeout(() => {
            fn();
            debounceTimers.delete(key);
        }, delay));
    };
}
// Batch DOM updates for performance
function batchDOMUpdate(updates) {
    requestAnimationFrame(() => {
        updates.forEach(update => update());
    });
}
async function updateStatus() {
    // Check cache first
    const cachedStatus = dataCache.get('status');
    const cachedDbStats = dataCache.get('dbStats');
    try {
        // Parallel fetch, settled independently: a transient rejection on one
        // endpoint (IPC/Mutex contention) must not stall the other half for a
        // whole tick. Fall back to the last cached value for a rejected half.
        const [statusRes, dbStatsRes] = await Promise.allSettled([
            cachedStatus ?? invoke('get_status'),
            cachedDbStats ?? invoke('get_db_stats')
        ]);
        const status = statusRes.status === 'fulfilled' ? statusRes.value : cachedStatus;
        const dbStats = dbStatsRes.status === 'fulfilled' ? dbStatsRes.value : cachedDbStats;
        if (statusRes.status === 'rejected') {
            console.error('Failed to fetch status:', statusRes.reason);
        }
        if (dbStatsRes.status === 'rejected') {
            console.error('Failed to fetch db stats:', dbStatsRes.reason);
        }
        // Disconnect tracking. The STATUS half is the IPC liveness signal: if it
        // rejected AND we have no cached value to fall back on, the backend is
        // unreachable (IPC down / Tauri command hung), NOT merely "bot offline"
        // — a stopped bot still returns a valid status with is_running:false.
        // Count those consecutive misses; surface the cue past the threshold.
        if (statusRes.status === 'rejected' && !status) {
            noteStatusTick(false);
        }
        else if (status) {
            noteStatusTick(true);
        }
        // STATUS is the liveness signal and drives the bot-control buttons; it
        // must render on its OWN. Coupling it to dbStats (`if (!status ||
        // !dbStats) return`) was a real freeze: get_status uses a try_lock path
        // and keeps succeeding while get_db_stats REJECTS under SQLITE_BUSY / an
        // uninitialized DB (bot cold-start). With a cold dbStats cache the whole
        // tick bailed, so the Online badge, uptime/memory, and — critically —
        // the Start/Dev/Stop/Restart buttons never updated. setBotControlBusy(
        // false) only clears the busy flag; re-enabling the buttons relies
        // entirely on updateButtons() here, so a rejected dbStats left every
        // control disabled until a lucky tick. Guard the two endpoints apart.
        if (!status)
            return;
        // Cache status. The TTL MUST stay below the refresh interval — a fixed
        // 1500ms cache meant that at a 1s refresh the in-between tick kept
        // hitting a still-valid cache, so fresh status (uptime, memory) only
        // arrived every ~2s and uptime jumped 0→2→4→6 instead of ticking by 1.
        // Tie it to the interval (half, min 250ms) so every tick gets fresh data
        // while still deduping a manual Ctrl+R that coincides with a tick.
        const statusTtl = Math.max(250, Math.floor(settings.refreshInterval / 2));
        if (!cachedStatus)
            dataCache.set('status', status, statusTtl);
        // Only chart fresh samples — adding a point on every call would
        // duplicate the previous reading whenever updateStatus runs against
        // a warm cache (e.g. Ctrl+R immediately followed by the interval
        // tick), compressing the history into bunched-up clusters.
        if (!cachedStatus) {
            addChartDataPoint(memoryHistory, status.memory_mb);
        }
        // dbStats is independent and non-critical (message/channel counts). It
        // may lag (counts aren't time-critical) and stays cached longer to spare
        // the DB. Only touch its cache, its chart sample, and its DOM when it's
        // actually present — a rejected/cold dbStats must not block the status
        // half above.
        if (dbStats) {
            if (!cachedDbStats) {
                dataCache.set('dbStats', dbStats, DB_STATS_TTL_MS);
                addChartDataPoint(messagesHistory, dbStats.total_messages);
            }
        }
        // Batch all DOM updates. updateStats tolerates a null dbStats (renders
        // status-only fields and skips the message/channel counts).
        batchDOMUpdate([
            () => updateStatusBadge(status),
            () => updateStatusText(status),
            () => updateButtons(status),
            () => updateStats(status, dbStats),
            () => updateCharts()
        ]);
    }
    catch (error) {
        // An unexpected throw here (rather than a per-half rejection handled
        // above) also means the tick produced no fresh status — count it.
        console.error('Failed to update status:', error);
        noteStatusTick(false);
    }
}
// Record the outcome of one status tick and drive the disconnected cue. A
// success immediately resets the streak + clears the cue (recovery); failures
// only surface the cue once we've missed STATUS_FAIL_THRESHOLD ticks in a row,
// so a single transient IPC blip never flashes a scary banner.
// Fill the Settings > Paths card with the REAL resolved paths from the backend
// (get_base_path / get_logs_path / get_data_path) instead of the hardcoded
// relative defaults baked into index.html — dev vs installed layouts resolve
// differently, and the static strings were never verified against the running
// backend. Cached after the first success; retried on the next settings visit
// if the backend was unavailable. textContent only — no HTML interpolation.
let pathsCardPopulated = false;
async function populatePathsCard() {
    if (pathsCardPopulated)
        return;
    const botScript = document.getElementById('info-bot-script');
    const logFile = document.getElementById('info-log-file');
    const database = document.getElementById('info-database');
    if (!botScript && !logFile && !database)
        return;
    try {
        const [base, logsDir, dataDir] = await Promise.all([
            invoke('get_base_path'),
            invoke('get_logs_path'),
            invoke('get_data_path'),
        ]);
        // title mirrors textContent on every row: the card is capped at 780px and a
        // Windows path is one unbreakable run for CSS line breaking (UAX#14 LB24
        // forbids a break after `\`), so a deep install path was chopped flat at the
        // card edge with no ellipsis and no way to read the rest. The tooltip keeps
        // the full value reachable whatever the stylesheet does with the overflow.
        if (botScript && base) {
            const p = `${base}\\bot.py`;
            botScript.textContent = p;
            botScript.title = p;
        }
        if (logFile && logsDir) {
            const p = `${logsDir}\\bot.log`;
            logFile.textContent = p;
            logFile.title = p;
        }
        if (database && dataDir) {
            const p = `${dataDir}\\bot_database.db`;
            database.textContent = p;
            database.title = p;
        }
        pathsCardPopulated = true;
    }
    catch (error) {
        // Backend unreachable — keep the static defaults and retry next visit.
        console.warn('Failed to resolve paths card:', error);
    }
}
function noteStatusTick(ok) {
    if (ok) {
        if (statusFailStreak !== 0) {
            statusFailStreak = 0;
            setDisconnectedCue(false);
        }
        return;
    }
    statusFailStreak++;
    if (statusFailStreak === STATUS_FAIL_THRESHOLD) {
        setDisconnectedCue(true);
    }
}
// Persistent "Disconnected" cue: a sticky status banner that stays up until the
// status loop recovers. Distinct from the bot Online/Offline badge — this means
// the dashboard itself can't reach the backend (IPC unreachable), not that the
// bot is merely stopped. Built from trusted static markup (no user content).
function setDisconnectedCue(show) {
    const existing = document.getElementById('ipc-disconnected-banner');
    if (show) {
        if (existing)
            return;
        const banner = document.createElement('div');
        banner.id = 'ipc-disconnected-banner';
        banner.className = 'ipc-disconnected-banner';
        banner.setAttribute('role', 'alert');
        banner.setAttribute('aria-live', 'assertive');
        banner.innerHTML =
            '<svg class="ic" aria-hidden="true"><use href="#i-alert"/></svg>' +
                '<span>Disconnected — can\'t reach the dashboard backend. Retrying…</span>';
        document.body.appendChild(banner);
    }
    else if (existing) {
        existing.remove();
    }
}
function updateStatusBadge(status) {
    const badge = document.getElementById('status-badge');
    const statusText = badge?.querySelector('.status-text');
    if (badge && statusText) {
        badge.classList.toggle('online', status.is_running);
        statusText.textContent = status.is_running ? 'Online' : 'Offline';
    }
    // Update AI Chat overlay based on bot running status
    const chatOverlay = document.getElementById('chat-not-running-overlay');
    if (chatOverlay) {
        chatOverlay.classList.toggle('visible', !status.is_running);
        // Keep the behind-overlay controls inert in lockstep with visibility.
        // (The observer also catches this, but sync synchronously so the tab
        // order is correct within the same frame, not one microtask later.)
        syncChatOverlayInert();
    }
    // If the bot came online while the user is already on the chat page,
    // proactively reconnect the AI Chat WebSocket instead of waiting for a manual page switch.
    if (status.is_running && currentPage === 'chat' && chatManager && !chatManager.connected) {
        chatManager.connect();
    }
}
function updateStatusText(status) {
    const botStatusText = document.getElementById('bot-status-text');
    if (botStatusText) {
        // The readout is a state pill now (v6), so it carries the state as a
        // class too — CSS can't branch on textContent, and "Status: Offline"
        // inside a pill labelled by its own dot said the word twice.
        botStatusText.textContent = status.is_running ? 'Online' : 'Offline';
        botStatusText.classList.toggle('is-online', status.is_running);
    }
}
function updateButtons(status) {
    // Don't override button states while a bot command is in progress
    if (botCommandInProgress)
        return;
    const btnStart = document.getElementById('btn-start');
    const btnDev = document.getElementById('btn-dev');
    const btnStop = document.getElementById('btn-stop');
    const btnRestart = document.getElementById('btn-restart');
    if (btnStart)
        btnStart.disabled = status.is_running;
    if (btnDev)
        btnDev.disabled = status.is_running;
    if (btnStop)
        btnStop.disabled = !status.is_running;
    if (btnRestart)
        btnRestart.disabled = !status.is_running;
}
// dbStats is nullable: get_db_stats can reject (SQLITE_BUSY / uninitialized DB)
// while get_status keeps succeeding, and the caller now renders the status-only
// fields regardless. Skip the message/channel counts when it's absent rather
// than crashing on `.total_messages` of null.
function updateStats(status, dbStats) {
    // Strings that don't animate naturally (uptime, mode) — just set textContent.
    const stringUpdates = [
        ['stat-uptime', status.uptime],
        ['stat-mode', status.mode],
    ];
    stringUpdates.forEach(([id, value]) => {
        const el = document.getElementById(id);
        if (el) {
            setSkeleton(el, false);
            if (el.textContent !== value)
                el.textContent = value;
        }
    });
    // Numeric stats — animate the count so changes feel alive.
    const memEl = document.getElementById('stat-memory');
    if (memEl) {
        setSkeleton(memEl, false);
        animateNumber(memEl, status.memory_mb, { decimals: 1, suffix: ' MB' });
    }
    // Message/channel counts come from dbStats — only update when we have it, so
    // a rejected dbStats leaves the last-known counts in place instead of
    // clearing them or throwing.
    if (dbStats) {
        const msgEl = document.getElementById('stat-messages');
        if (msgEl) {
            setSkeleton(msgEl, false);
            animateNumber(msgEl, dbStats.total_messages);
        }
        const chEl = document.getElementById('stat-channels');
        if (chEl) {
            setSkeleton(chEl, false);
            animateNumber(chEl, dbStats.active_channels);
        }
    }
}
// ============================================================================
// Bot Control
// ============================================================================
let botCommandInProgress = false;
function setBotControlBusy(busy) {
    botCommandInProgress = busy;
    const btnStart = document.getElementById('btn-start');
    const btnDev = document.getElementById('btn-dev');
    const btnStop = document.getElementById('btn-stop');
    const btnRestart = document.getElementById('btn-restart');
    if (busy) {
        if (btnStart)
            btnStart.disabled = true;
        if (btnDev)
            btnDev.disabled = true;
        if (btnStop)
            btnStop.disabled = true;
        if (btnRestart)
            btnRestart.disabled = true;
    }
}
async function startBot() {
    if (botCommandInProgress)
        return;
    try {
        setBotControlBusy(true);
        showToast('Starting bot...', { type: 'info', duration: 10000 });
        // Backend now returns immediately after Command::spawn (~50ms) instead
        // of holding the lock for up to 10s waiting on bot.pid. We pick up the
        // Running transition ourselves with a tight 200ms poll below — total
        // perceived latency on the happy path drops from ~1s to ~250ms.
        await invoke('start_bot');
        await waitForStart();
    }
    catch (error) {
        showToast(String(error), { type: 'error' });
    }
    finally {
        setBotControlBusy(false);
        dataCache.invalidate('status');
        updateStatus();
    }
}
/**
 * Poll the backend's start-progress signal after a Start request until the
 * bot is confirmed up, the spawned process dies, or we hand back to the
 * regular status refresh.
 *
 * Why this isn't a flat timeout: ``bot.py`` only writes its PID file (the
 * "running" signal) *after* a heavy import + startup-check phase, which on a
 * cold start (post-reboot, antivirus scanning the ``.pyd``/``.dll`` files,
 * busy disk) can take far longer than any fixed deadline. The old poll gave
 * up at 15s and fired a "timed out" warning even though the process was alive
 * and finished booting moments later — a false alarm on every slow start.
 *
 * ``get_start_progress`` lets us tell three states apart:
 *   - ``running``  → success, the instant the PID lands.
 *   - ``exited``   → the process we spawned died before becoming ready; a
 *                    *real* failure, surfaced immediately (with exit code)
 *                    instead of after a deadline.
 *   - ``starting`` → still importing/booting; keep waiting, NEVER warn.
 *
 * Only if the process stays alive-but-not-ready past ``handoffMs`` (a hung
 * import, rare) do we stop the tight poll — and even then it's an
 * informational hand-off to the periodic status refresh, not a failure toast.
 *
 * Caller owns setBotControlBusy(true/false); we only emit the outcome toast.
 */
async function waitForStart(intervalMs = 250, softNoticeMs = 12000, handoffMs = 60000) {
    const startTime = performance.now();
    let softNoticeShown = false;
    while (performance.now() - startTime < handoffMs) {
        await new Promise((r) => setTimeout(r, intervalMs));
        let progress;
        try {
            progress = await invoke('get_start_progress');
        }
        catch {
            // Transient IPC error / lock contention — just try the next tick.
            continue;
        }
        switch (progress.state) {
            case 'running':
                showToast('Bot started', { type: 'success' });
                return;
            case 'exited': {
                // The spawned process terminated before it ever became ready —
                // an unambiguous startup failure (bad token sys.exit, an
                // import-time crash, etc.). Report it now, with the exit code
                // when we have one, rather than waiting out a deadline.
                const codeSuffix = progress.code === null ? '' : ` (exit code ${progress.code})`;
                showToast(`Bot failed to start${codeSuffix} — check logs`, { type: 'error' });
                return;
            }
            // 'unknown' (no tracked child — e.g. started outside the dashboard)
            // is treated like 'starting': keep polling so a late 'running' tick
            // still resolves, and let the handoff below release us otherwise.
            case 'unknown':
            case 'starting':
                if (!softNoticeShown && performance.now() - startTime >= softNoticeMs) {
                    softNoticeShown = true;
                    showToast('Bot is taking a while to start (cold start) — still working…', {
                        type: 'info',
                        duration: 6000,
                    });
                }
                break;
        }
    }
    // Still alive but not ready after the ceiling — a hung import, not a crash
    // (a crash would have surfaced as 'exited' above). Hand back to the regular
    // status refresh, which flips the badge to Running once bot.py finishes.
    showToast('Bot is still starting — status will update automatically', {
        type: 'info',
        duration: 6000,
    });
}
async function stopBot() {
    if (botCommandInProgress)
        return;
    try {
        setBotControlBusy(true);
        showToast('Stopping bot...', { type: 'info', duration: 5000 });
        const result = await invoke('stop_bot');
        showToast(result, { type: 'success' });
    }
    catch (error) {
        showToast(String(error), { type: 'error' });
    }
    finally {
        // In finally (not the try) so a failed stop still re-enables the four
        // control buttons via updateStatus()->updateButtons(); otherwise they
        // stay disabled until the next periodic refresh tick. Mirrors startBot.
        setBotControlBusy(false);
        dataCache.invalidate('status');
        updateStatus();
    }
}
async function restartBot() {
    if (botCommandInProgress)
        return;
    try {
        setBotControlBusy(true);
        showToast('Restarting bot...', { type: 'info', duration: 12000 });
        const result = await invoke('restart_bot');
        showToast(result, { type: 'success' });
    }
    catch (error) {
        showToast(String(error), { type: 'error' });
    }
    finally {
        // In finally so a failed restart re-enables the control buttons too.
        setBotControlBusy(false);
        dataCache.invalidate('status');
        updateStatus();
    }
}
async function startDevBot() {
    if (botCommandInProgress)
        return;
    try {
        setBotControlBusy(true);
        showToast('Starting dev mode...', { type: 'info', duration: 8000 });
        const result = await invoke('start_dev_bot');
        showToast(result, { type: 'success' });
    }
    catch (error) {
        showToast(String(error), { type: 'error' });
    }
    finally {
        // In finally so a failed dev-start re-enables the control buttons too.
        setBotControlBusy(false);
        dataCache.invalidate('status');
        updateStatus();
    }
}
// ============================================================================
// Logs - Optimized Real-time Streaming
// ============================================================================
let lastLogFilter = null;
/**
 * Every level token the log viewer recognises, most severe first.
 *
 * MUST stay in sync with the `#log-filter` <option> values in index.html (a
 * level the classifier can produce but the menu can't select is a line the user
 * can see coloured and never filter to) and with the `.log-line.<level>` rules
 * in styles.css / orbital.css. tests-e2e/ui-invariants.spec.ts asserts the
 * first pairing so the three can't drift apart again.
 *
 * CRITICAL is here because bot.py logs its fatals with it — bad or missing
 * DISCORD_TOKEN, network failure contacting Discord, unhandled startup errors —
 * and utils/monitoring/logger.py formats the column as `[%(levelname)s]`. It
 * used to be absent, so the single most severe line the bot can emit inherited
 * the PREVIOUS line's level (or fell back to 'info'): it rendered green, and a
 * user who filtered to ERROR to find out why the bot wouldn't start was shown
 * everything except the reason.
 */
export const LOG_LEVELS = ['CRITICAL', 'ERROR', 'WARNING', 'INFO', 'DEBUG'];
const LOG_LEVEL_RE = new RegExp(`\\b(${LOG_LEVELS.join('|')})\\b`);
/**
 * Split raw log lines into `{line, level}` pairs, dropping anything the filter
 * excludes. Pure, and exported so app.test.ts exercises the SHIPPED classifier
 * rather than a mirror re-implementation — the mirror in the old test happily
 * agreed with the code while both were missing CRITICAL.
 *
 * `filter` is 'all' or one of LOG_LEVELS.
 */
export function classifyLogLines(logs, filter) {
    const out = [];
    // Continuation lines (traceback bodies, wrapped messages) carry no level
    // token of their own — they belong to the last tagged entry. Carrying that
    // level forward keeps a filtered ERROR view showing its traceback instead
    // of dropping the most useful part of the error.
    let carriedLevelToken;
    for (const line of logs) {
        // Anchor the level to a standalone token (the structured log-level
        // column) rather than a whole-line substring match, so message text that
        // incidentally contains a level word (e.g. an INFO line "no ERROR
        // found") is neither mis-coloured nor wrongly selected by the filter.
        // The first token wins, matching the column order.
        const ownLevelToken = LOG_LEVEL_RE.exec(line)?.[1];
        if (ownLevelToken)
            carriedLevelToken = ownLevelToken;
        const levelToken = ownLevelToken ?? carriedLevelToken;
        const level = levelToken ? levelToken.toLowerCase() : 'info';
        if (filter === 'all' || levelToken === filter) {
            out.push({ line, level });
        }
    }
    return out;
}
/**
 * The Logs panel's empty state, as markup.
 *
 * Iconographic empty state (SHARED CONTRACT #2): fixed, trusted markup — no
 * user content, no inline style. Classes only; the .empty-state / .ic sizing
 * lives in orbital.css.
 * <h2>, not <h3>: this state is injected directly under the page's
 * <h1>Log Viewer</h1> with no intervening section heading, so an h3 skipped a
 * level (axe: moderate heading-order). The other empty states in index.html DO
 * sit under an <h2> and correctly use h3.
 *
 * Two distinct states, because "the bot has logged nothing" and "the bot has
 * logged plenty, none of it at this level" are different problems with
 * different next steps. Telling someone who filtered to CRITICAL on a healthy
 * bot to wait for it to start running is a lie, and it was the ONLY message
 * this panel had. Now that the menu offers CRITICAL and DEBUG the empty result
 * is the common case, so it names the filter and points at the way out.
 * `filter` is one of the fixed option values, never user text — safe to
 * interpolate, and escapeHtml() is applied anyway rather than relying on that
 * staying true.
 *
 * Lives in one function because clearLogs() paints it too: it used to just
 * blank the <pre>, which left a featureless black box whenever the feed was
 * paused (the poll that would have repainted is deliberately stopped then).
 */
function logsEmptyState(filter, logCount) {
    const filtered = filter !== 'all' && logCount > 0;
    return filtered
        ? '<div class="empty-state">' +
            '<svg class="ic" aria-hidden="true"><use href="#i-logs"/></svg>' +
            `<h2>No ${escapeHtml(filter)} lines</h2>` +
            `<p>${countLabel(logCount, 'log line')} loaded, none at this level. ` +
            'Pick <em>All Levels</em> to see everything.</p>' +
            '</div>'
        : '<div class="empty-state">' +
            '<svg class="ic" aria-hidden="true"><use href="#i-logs"/></svg>' +
            '<h2>No logs found</h2>' +
            '<p>Logs will appear here once the bot starts running.</p>' +
            '</div>';
}
async function loadLogs() {
    try {
        const logs = await invoke('get_logs', { count: 200 });
        // Fetch succeeded — arm the failure toast for the next streak.
        logsLoadFailedToastShown = false;
        const container = document.getElementById('log-content');
        const filterElement = document.getElementById('log-filter');
        const filter = filterElement?.value || 'all';
        if (!container)
            return;
        // Detect new logs by a content signature, NOT line count: once the bot
        // has logged more than the 200-line backend tail window, logs.length is
        // permanently 200, so a count check never sees the rotating tail and the
        // viewer freezes. length + last line is a cheap, sufficient signature.
        const logSignature = `${logs.length}|${logs[logs.length - 1] ?? ''}`;
        const hasNewLogs = logSignature !== lastLogSignature;
        const filterChanged = filter !== lastLogFilter;
        lastLogSignature = logSignature;
        lastLogFilter = filter;
        // Skip the full DOM rebuild if neither the log buffer nor the filter
        // changed since last tick — this kills the once-per-second flicker
        // when the bot is idle.
        if (!hasNewLogs && !filterChanged && container.childElementCount > 0) {
            return;
        }
        // Use DocumentFragment for better performance
        const fragment = document.createDocumentFragment();
        for (const { line, level } of classifyLogLines(logs, filter)) {
            const div = document.createElement('div');
            div.className = `log-line ${level}`;
            div.textContent = line;
            fragment.appendChild(div);
        }
        container.innerHTML = '';
        container.appendChild(fragment);
        if (!container.firstChild) {
            container.innerHTML = logsEmptyState(filter, logs.length);
        }
        // Auto-scroll on new logs OR when the filter changes — switching from
        // ERROR to ALL with auto-scroll on previously left the view on a
        // mid-scroll position from the prior filter instead of snapping back
        // to the bottom of the rebuilt list.
        //
        // Scroll the CONTAINER, not the <pre>. #log-content has the default
        // `overflow: visible`, so its scrollHeight equals its clientHeight and
        // the assignment clamped to 0 — the tail-following that is the whole
        // point of a log viewer never happened, and neither did the
        // filter-change snap-back described above. #log-container is the element
        // that actually owns the overflow.
        if (logsAutoScrollEnabled && (hasNewLogs || filterChanged)) {
            const scroller = document.getElementById('log-container');
            if (scroller)
                scroller.scrollTop = scroller.scrollHeight;
        }
    }
    catch (error) {
        console.error('Failed to load logs:', error);
        // The logs page polls every second — toast only on the FIRST failure of
        // a streak (reset on success below), or a persistent backend error
        // stacks an identical assertive toast every tick (screen readers get a
        // role=alert announcement per second). Mirrors the statusFailStreak
        // single-cue pattern used by updateStatus.
        if (!logsLoadFailedToastShown) {
            logsLoadFailedToastShown = true;
            showToast('Failed to load logs', { type: 'error' });
        }
    }
}
function startLogsRefresh() {
    if (logsRefreshInterval) {
        clearInterval(logsRefreshInterval);
        logsRefreshInterval = null;
    }
    // The user pressed Pause: every restart path (page switch, tab becoming
    // visible again, post-clearLogs) must respect it, so the gate lives here
    // rather than at each call site. Resume goes through toggleAutoScroll.
    if (!logsAutoScrollEnabled) {
        return;
    }
    // Don't poll while the dashboard tab is hidden — the sakura
    // visibility handler already pauses heavy work on hide; mirroring
    // that here keeps the log path from burning IPC bandwidth and
    // backend Mutex contention when nobody is looking.
    if (document.visibilityState === 'hidden') {
        return;
    }
    logsRefreshInterval = window.setInterval(loadLogs, 1000);
}
function stopLogsRefresh() {
    if (logsRefreshInterval) {
        clearInterval(logsRefreshInterval);
        logsRefreshInterval = null;
    }
}
// Pause/resume polling on visibility change so a backgrounded dashboard window
// stops costing CPU + IPC roundtrips. Covers BOTH the status refresh loop and
// the logs poll (and mirrors the sakura pause inside initSakuraAnimation).
document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') {
        stopRefreshLoop();
        stopLogsRefresh();
    }
    else {
        // Restart the status loop unconditionally (it drives every page's
        // header badge), and the logs poll only when the logs page is open.
        startRefreshLoop();
        if (currentPage === 'logs') {
            startLogsRefresh();
        }
    }
});
function applyAutoScrollButtonState() {
    const btn = document.getElementById('btn-auto-scroll');
    if (btn) {
        // Rebuild innerHTML (icon + label) instead of assigning textContent,
        // which strips the <svg> and leaves a text-only button inconsistent with
        // the icon'd Clear/Refresh buttons beside it. Stop icon when auto-scroll
        // is live (the action pauses it), play icon when paused (the action
        // resumes). icon() emits an inert, aria-hidden sprite reference.
        btn.innerHTML = icon(logsAutoScrollEnabled ? 'stop' : 'play') +
            (logsAutoScrollEnabled ? ' Pause' : ' Resume');
        btn.classList.toggle('paused', !logsAutoScrollEnabled);
    }
    // Keep the LIVE badge honest. It used to be static markup that nothing in
    // the codebase ever touched, so it sat there pulsing "LIVE" even after Pause
    // had genuinely stopped the poll (and while the bot was down). Drive it from
    // the same state as the button. Both strings are literals — no user content.
    const live = document.getElementById('live-indicator');
    if (live) {
        live.innerHTML = icon('pulse') + (logsAutoScrollEnabled ? ' LIVE' : ' PAUSED');
        live.classList.toggle('paused', !logsAutoScrollEnabled);
    }
}
// Pause/Resume the LIVE log feed. Pausing only the scroll position wasn't
// enough — the 1s poll kept rebuilding the list, so the view visibly "kept
// running" after pressing Pause. Pausing now stops the poll itself (also
// saving IPC while the user reads); resuming does an instant catch-up load
// (the backend keeps the 200-line tail, so nothing is missed beyond what
// the tail window itself drops) and restarts the poll.
// Exported so app.test.ts exercises the SHIPPED pause/resume behavior
// against the real 1s poller.
export function toggleAutoScroll() {
    logsAutoScrollEnabled = !logsAutoScrollEnabled;
    // Persist the pause/resume preference so it survives a reload.
    settings.autoScroll = logsAutoScrollEnabled;
    saveSettings();
    applyAutoScrollButtonState();
    if (logsAutoScrollEnabled) {
        // The button lives on the logs page, but guard anyway so a future
        // shortcut can't start a poll that leaks into other pages.
        if (currentPage === 'logs') {
            void loadLogs();
            startLogsRefresh();
        }
    }
    else {
        stopLogsRefresh();
    }
    showToast(`Logs ${logsAutoScrollEnabled ? 'live' : 'paused'}`, { type: 'info', duration: 1500 });
}
async function clearLogs() {
    // Confirm first. This truncates logs/bot.log ON DISK — the only record of a
    // crash, a bad DISCORD_TOKEN or a failed Discord connection — and the button
    // sits between Pause and Refresh, the two harmless controls a reader clicks
    // constantly. Every other destructive action in this app already confirms
    // (clearHistory, deleteSelectedChannels); this one was a single unguarded
    // click with no undo.
    const confirmed = await showConfirmDialog('Clear the log file? logs/bot.log is truncated on disk and cannot be recovered.');
    if (!confirmed)
        return;
    // Pause the 1s logs poller so an in-flight loadLogs() tick cannot
    // re-read the not-yet-truncated backend tail and repopulate stale
    // logs while the backend clear is in flight.
    stopLogsRefresh();
    try {
        const result = await invoke('clear_logs');
        const container = document.getElementById('log-content');
        if (container) {
            // Paint the empty state rather than just blanking. With the feed
            // paused (Pause also stops the poll, by design) nothing would ever
            // repaint, so Clear left a featureless black rectangle with no
            // explanation until the user happened to press Resume or Refresh.
            // Painting it here instead of calling loadLogs() keeps the Pause
            // contract: we must not re-render lines the bot wrote after the
            // clear.
            const filterElement = document.getElementById('log-filter');
            container.innerHTML = logsEmptyState(filterElement?.value || 'all', 0);
        }
        lastLogSignature = null;
        showToast(String(result), { type: 'success', duration: 1500 });
    }
    catch (err) {
        showToast('Failed to clear logs: ' + err, { type: 'error' });
    }
    finally {
        if (currentPage === 'logs')
            startLogsRefresh();
    }
}
// ============================================================================
// Database
// ============================================================================
async function loadDbStats() {
    // Declared OUTSIDE the try: a `const` inside it is not in scope in the
    // catch, which is where the failure state needs them.
    const DB_TILES = ['db-messages', 'db-channels', 'db-entities', 'db-rag'];
    // Cold = the very first load, before animateNumber has stamped
    // dataset.animValue on the tiles. A background refresh must never blank
    // numbers that are already live and correct — only the first paint gets the
    // skeleton, and only the first paint falls back to the em-dash placeholder.
    const cold = !document.getElementById('db-messages')?.dataset.animValue;
    // get_recent_channels / get_top_users share this try and run AFTER the tiles
    // were filled, so a rejection there would otherwise reset four freshly
    // correct numbers to '—'. This flag scopes the tile reset to a genuine
    // get_db_stats failure.
    let statsOk = false;
    // The skeleton markup has always existed (.is-loading in styles.css) and
    // nothing ever switched it on, so a cold fetch that was still in flight —
    // or one that rejected outright — was indistinguishable from a healthy but
    // genuinely empty database: four honest-looking zeros.
    if (cold)
        DB_TILES.forEach(id => setSkeleton(id, true));
    /** Stop the shimmer and say "unknown" rather than "zero". Nothing polls this
     *  page, so a skeleton left running after a failed fetch would shimmer until
     *  the user navigates away and back. */
    const failTiles = () => {
        DB_TILES.forEach(id => {
            const el = document.getElementById(id);
            if (el) {
                setSkeleton(el, false);
                el.textContent = '—';
            }
        });
    };
    try {
        const stats = await invoke('get_db_stats');
        // Same defensive guard as updateStatus: backend can legitimately
        // return null before the DB is initialized; treat as "no data yet"
        // and let the next load fill it in instead of crashing the page.
        if (!stats) {
            if (cold)
                failTiles();
            return;
        }
        batchDOMUpdate([
            () => {
                const dbMessages = document.getElementById('db-messages');
                const dbChannels = document.getElementById('db-channels');
                const dbEntities = document.getElementById('db-entities');
                const dbRag = document.getElementById('db-rag');
                // animateNumber handles reduced-motion fallback internally,
                // and setSkeleton clears any loading placeholder the first
                // time real data arrives.
                if (dbMessages) {
                    setSkeleton(dbMessages, false);
                    animateNumber(dbMessages, stats.total_messages);
                }
                if (dbChannels) {
                    setSkeleton(dbChannels, false);
                    animateNumber(dbChannels, stats.active_channels);
                }
                if (dbEntities) {
                    setSkeleton(dbEntities, false);
                    animateNumber(dbEntities, stats.total_entities);
                }
                if (dbRag) {
                    setSkeleton(dbRag, false);
                    animateNumber(dbRag, stats.rag_memories);
                }
            }
        ]);
        statsOk = true;
        // Load channels and users in parallel. Coerce nulls (which the
        // backend can return before the bot has indexed anything) to empty
        // arrays so the .length / .forEach calls below don't crash and
        // leave the UI in a half-rendered state.
        const [channelsRaw, usersRaw] = await Promise.all([
            invoke('get_recent_channels', { limit: 10 }),
            invoke('get_top_users', { limit: 10 })
        ]);
        const channels = channelsRaw ?? [];
        const users = usersRaw ?? [];
        const channelsList = document.getElementById('channels-list');
        if (channelsList) {
            if (channels.length === 0) {
                channelsList.innerHTML = '<p class="no-data">No channels found.</p>';
                updateChannelSelectionUI();
            }
            else {
                channelsList.innerHTML = '';
                channels.forEach((ch) => {
                    const item = document.createElement('div');
                    item.className = 'data-item';
                    item.dataset.channelId = String(ch.channel_id);
                    const leftDiv = document.createElement('div');
                    leftDiv.className = 'data-item-left';
                    const checkbox = document.createElement('input');
                    checkbox.type = 'checkbox';
                    checkbox.className = 'data-item-checkbox';
                    checkbox.dataset.channelId = String(ch.channel_id);
                    // Accessible name (axe: critical `label`). These checkboxes arm
                    // the destructive "Delete Selected" action, so an unnamed one
                    // left screen-reader users unable to tell WHICH channel they
                    // were about to wipe. No visible <label> to associate with —
                    // the row's text is a sibling span — so name it directly.
                    checkbox.setAttribute('aria-label', `Select channel ${ch.channel_id} for deletion`);
                    checkbox.addEventListener('change', () => {
                        item.classList.toggle('selected', checkbox.checked);
                        updateChannelSelectionUI();
                    });
                    const idSpan = document.createElement('span');
                    idSpan.className = 'data-item-id';
                    idSpan.textContent = String(ch.channel_id);
                    // The id ellipsizes when it outgrows the row (see
                    // .data-item-id in styles.css) — keep the full value hoverable.
                    idSpan.title = String(ch.channel_id);
                    leftDiv.appendChild(checkbox);
                    leftDiv.appendChild(idSpan);
                    const valSpan = document.createElement('span');
                    valSpan.className = 'data-item-value';
                    valSpan.textContent = countLabel(ch.message_count, 'message');
                    item.appendChild(leftDiv);
                    item.appendChild(valSpan);
                    // Click row to toggle checkbox
                    item.addEventListener('click', (e) => {
                        if (e.target.tagName !== 'INPUT') {
                            checkbox.checked = !checkbox.checked;
                            item.classList.toggle('selected', checkbox.checked);
                            updateChannelSelectionUI();
                        }
                    });
                    channelsList.appendChild(item);
                });
                updateChannelSelectionUI();
            }
        }
        const usersList = document.getElementById('users-list');
        if (usersList) {
            if (users.length === 0) {
                usersList.innerHTML = '<p class="no-data">No users found.</p>';
            }
            else {
                usersList.innerHTML = '';
                users.forEach((u) => {
                    const item = document.createElement('div');
                    item.className = 'data-item';
                    const idSpan = document.createElement('span');
                    idSpan.className = 'data-item-id';
                    idSpan.textContent = String(u.user_id);
                    idSpan.title = String(u.user_id); // ellipsized when long
                    const valSpan = document.createElement('span');
                    valSpan.className = 'data-item-value';
                    valSpan.textContent = countLabel(u.message_count, 'message');
                    item.appendChild(idSpan);
                    item.appendChild(valSpan);
                    usersList.appendChild(item);
                });
            }
        }
    }
    catch (error) {
        console.error('Failed to load DB stats:', error);
        // Only when the STATS call itself failed on a cold page: replace the
        // shimmer with '—', the same honest placeholder the uptime/mode tiles
        // use. animateNumber reads dataset.animValue (not textContent), so the
        // next successful load overwrites this cleanly.
        if (cold && !statsOk)
            failTiles();
        // Surface the actual reason (SQLITE_BUSY, a failed open) like every
        // other catch in this file does — the old bare message swallowed it, and
        // it was also wrong whenever the stats succeeded and only the two list
        // fetches rejected.
        showToast(`Failed to load database stats: ${error}`, { type: 'error' });
        const retry = '<p class="no-data">Could not load — press Ctrl+R to retry.</p>';
        for (const id of ['channels-list', 'users-list']) {
            const el = document.getElementById(id);
            if (el && !el.childElementCount)
                el.innerHTML = retry;
        }
    }
}
async function clearHistory() {
    const confirmed = await showConfirmDialog('This will permanently delete ALL chat history. Continue?');
    if (!confirmed) {
        return;
    }
    try {
        const count = await invoke('clear_history');
        showToast(`Deleted ${countLabel(count, 'message')}`, { type: 'success' });
        dataCache.invalidate('dbStats');
        loadDbStats();
    }
    catch (error) {
        showToast(String(error), { type: 'error' });
    }
}
function getSelectedChannelIds() {
    const checkboxes = document.querySelectorAll('.data-item-checkbox:checked');
    return Array.from(checkboxes).map(cb => cb.dataset.channelId).filter(Boolean);
}
function updateChannelSelectionUI() {
    const selected = getSelectedChannelIds();
    const controls = document.getElementById('channel-selection-controls');
    const countEl = document.getElementById('channel-selection-count');
    if (controls) {
        controls.classList.toggle('hidden', selected.length === 0);
    }
    if (countEl) {
        countEl.textContent = `${selected.length} selected`;
    }
}
async function deleteSelectedChannels() {
    const channelIds = getSelectedChannelIds();
    if (channelIds.length === 0) {
        showToast('No channels selected', { type: 'warning' });
        return;
    }
    const confirmed = await showConfirmDialog(`Delete history for ${channelIds.length} channel(s)? This cannot be undone.`);
    if (!confirmed) {
        return;
    }
    try {
        // Pass channel IDs as strings to avoid JavaScript Number precision loss for Discord Snowflake IDs
        const count = await invoke('delete_channels_history', { channelIds: channelIds });
        showToast(`Deleted ${countLabel(count, 'message')} from ${countLabel(channelIds.length, 'channel')}`, { type: 'success' });
        dataCache.invalidate('dbStats');
        loadDbStats();
    }
    catch (error) {
        showToast(String(error), { type: 'error' });
    }
}
// ============================================================================
// Settings UI
// ============================================================================
function loadSettingsUI() {
    const refreshSelect = document.getElementById('refresh-interval');
    if (refreshSelect) {
        refreshSelect.value = settings.refreshInterval.toString();
    }
    const notificationsToggle = document.getElementById('notifications-toggle');
    if (notificationsToggle) {
        notificationsToggle.checked = settings.notifications;
    }
    const sakuraToggleEl = document.getElementById('sakura-toggle');
    if (sakuraToggleEl) {
        sakuraToggleEl.checked = settings.sakuraEnabled !== false;
    }
    const densityToggleEl = document.getElementById('setting-density');
    if (densityToggleEl) {
        densityToggleEl.checked = settings.densityCompact === true;
    }
    const soundToggleEl = document.getElementById('sound-toggle');
    if (soundToggleEl) {
        soundToggleEl.checked = settings.soundEnabled === true;
    }
    const hapticToggleEl = document.getElementById('haptic-toggle');
    if (hapticToggleEl) {
        hapticToggleEl.checked = settings.hapticEnabled === true;
    }
    // Telemetry toggle is stored outside localStorage — it's a file on disk
    // so the Python bot can read the same source of truth. Fetch the current
    // state from the Rust side.
    const telemetryToggleEl = document.getElementById('telemetry-toggle');
    if (telemetryToggleEl) {
        invoke('get_telemetry_enabled')
            .then((enabled) => { telemetryToggleEl.checked = enabled; })
            .catch(() => { });
    }
    const userNameInput = document.getElementById('user-name-input');
    if (userNameInput) {
        userNameInput.value = settings.userName === 'You' ? '' : settings.userName;
    }
    // Load AI + user avatar previews via the shared tri-state helper. It uses
    // the transparent-gif placeholder internally so a missing avatar never
    // flashes the browser's broken-image glyph.
    setAvatarPreview('ai', settings.aiAvatar);
    setAvatarPreview('user', settings.userAvatar);
    // Load creator checkbox
    const creatorCheckbox = document.getElementById('creator-toggle');
    if (creatorCheckbox) {
        creatorCheckbox.checked = settings.isCreator;
    }
    // Load profile from server
    if (chatManager?.connected) {
        chatManager.send({ type: 'get_profile' });
    }
}
// Track which avatar we're editing
let currentAvatarTarget = 'user';
// 1x1 transparent gif — used instead of an empty src so the browser doesn't
// flash its broken-image glyph even while the <img> is hidden by class.
const BLANK_AVATAR_GIF = 'data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==';
// Single source of truth for the user/AI avatar preview tri-state (image,
// placeholder, remove button). Replaces the three near-identical inline blocks
// that lived in loadSettingsUI / saveCroppedAvatar / removeAvatar. Pass a data
// URL (or http(s) avatar URL) to show it; pass '' to clear back to placeholder.
function setAvatarPreview(target, dataUrl) {
    const ids = target === 'ai'
        ? { img: 'ai-avatar-image', preview: '#ai-avatar-preview', remove: 'btn-remove-ai-avatar' }
        : { img: 'avatar-image', preview: '#avatar-preview', remove: 'btn-remove-avatar' };
    const avatarImage = document.getElementById(ids.img);
    const placeholder = document.querySelector(`${ids.preview} .avatar-placeholder`);
    const removeBtn = document.getElementById(ids.remove);
    const hasAvatar = isSafeAvatarUrl(dataUrl);
    if (avatarImage) {
        avatarImage.src = hasAvatar ? dataUrl : BLANK_AVATAR_GIF;
        avatarImage.classList.toggle('visible', hasAvatar);
    }
    if (placeholder)
        placeholder.classList.toggle('hidden', hasAvatar);
    if (removeBtn)
        removeBtn.classList.toggle('hidden', !hasAvatar);
}
function handleAvatarUpload(file, target = 'user') {
    if (!file.type.startsWith('image/')) {
        showToast('Please select an image file', { type: 'error' });
        return;
    }
    if (file.size > 20 * 1024 * 1024) { // 20MB limit for cropping
        showToast('Image must be less than 20MB', { type: 'error' });
        return;
    }
    currentAvatarTarget = target;
    const reader = new FileReader();
    reader.onload = (e) => {
        const dataUrl = e.target?.result;
        openAvatarCropModal(dataUrl);
    };
    reader.onerror = () => {
        showToast('Failed to read image file', { type: 'error' });
    };
    reader.readAsDataURL(file);
}
// Avatar Cropper State
let cropState = {
    imageUrl: '',
    zoom: 100,
    offsetX: 0,
    offsetY: 0,
    isDragging: false,
    startX: 0,
    startY: 0,
    imgWidth: 0,
    imgHeight: 0
};
// Store bound functions for proper cleanup
let boundOnDrag = null;
let boundOnDragTouch = null;
let boundEndDrag = null;
let cropEscBound = false; // ESC-to-close handler is bound once for the page lifetime
let boundStartDrag = null;
let boundStartDragTouch = null;
let boundCropKeyPan = null;
let cropListenersAttached = false;
// px the crop image pans per arrow-key press (Shift = a larger step). Keyboard
// parity for the pointer-drag reposition (WCAG 2.1.1 — the "Drag image to
// position" affordance had no keyboard operation).
const CROP_KEY_STEP = 10;
const CROP_KEY_STEP_LARGE = 40;
function openAvatarCropModal(imageUrl) {
    cropState = {
        imageUrl,
        zoom: 100,
        offsetX: 0,
        offsetY: 0,
        isDragging: false,
        startX: 0,
        startY: 0,
        imgWidth: 0,
        imgHeight: 0
    };
    const modal = document.getElementById('avatar-crop-modal');
    const cropImage = document.getElementById('crop-image');
    const zoomSlider = document.getElementById('crop-zoom');
    if (!modal || !cropImage || !zoomSlider)
        return;
    // Load image to get dimensions
    cropImage.onload = () => {
        const cropArea = document.getElementById('crop-area');
        if (!cropArea)
            return;
        const areaSize = 280;
        // Guard against a broken image (naturalWidth/Height === 0). Without
        // this, ``areaSize / 0`` produces Infinity, which then poisons every
        // subsequent crop calculation with NaN and silently saves a blank
        // canvas.
        if (cropImage.naturalWidth <= 0 || cropImage.naturalHeight <= 0) {
            // English, like every other rendered string in this UI: the document
            // is lang="en", so a Thai literal here was read out by a screen
            // reader with an English pronunciation model and arrived as noise.
            // (The Thai in this repo is the SOURCE COMMENTS, deliberately — not
            // the UI copy.)
            showToast('Could not read that image — it may be corrupt. Try another file.', { type: 'error' });
            closeCropModal();
            return;
        }
        const scale = Math.max(areaSize / cropImage.naturalWidth, areaSize / cropImage.naturalHeight);
        cropState.imgWidth = cropImage.naturalWidth * scale;
        cropState.imgHeight = cropImage.naturalHeight * scale;
        // Center the image
        cropState.offsetX = (areaSize - cropState.imgWidth) / 2;
        cropState.offsetY = (areaSize - cropState.imgHeight) / 2;
        updateCropPreview();
    };
    cropImage.onerror = () => {
        // Without this, a decode failure leaves onload (and its naturalWidth
        // guard) unfired while the modal still opens on a blank image.
        showToast('Failed to load image', { type: 'error' });
        closeCropModal();
    };
    cropImage.src = imageUrl;
    zoomSlider.value = '100';
    // Route through the shared modal helper: records the trigger (the avatar
    // "Change" button), focuses the first control, and makes the app inert.
    openModal(modal);
    // Setup event listeners
    setupCropEventListeners();
}
function setupCropEventListeners() {
    const cropArea = document.getElementById('crop-area');
    const zoomSlider = document.getElementById('crop-zoom');
    const saveBtn = document.getElementById('btn-crop-save');
    const cancelBtn = document.getElementById('btn-crop-cancel');
    const closeBtn = document.getElementById('avatar-crop-close');
    const modal = document.getElementById('avatar-crop-modal');
    if (!cropArea || !zoomSlider || !saveBtn || !cancelBtn || !closeBtn || !modal)
        return;
    // Detach previously-bound handlers from the live elements rather than
    // cloning the node (cloning silently drops every listener that was
    // attached BEFORE this function ran, which leaks the document-level
    // mousemove/touchmove/mouseup/touchend handlers from prior opens).
    if (cropListenersAttached) {
        if (boundStartDrag)
            cropArea.removeEventListener('mousedown', boundStartDrag);
        if (boundStartDragTouch)
            cropArea.removeEventListener('touchstart', boundStartDragTouch);
        if (boundCropKeyPan)
            cropArea.removeEventListener('keydown', boundCropKeyPan);
        if (boundOnDrag)
            document.removeEventListener('mousemove', boundOnDrag);
        if (boundOnDragTouch)
            document.removeEventListener('touchmove', boundOnDragTouch);
        if (boundEndDrag) {
            document.removeEventListener('mouseup', boundEndDrag);
            document.removeEventListener('touchend', boundEndDrag);
        }
    }
    // Create bound functions for proper cleanup
    boundStartDrag = startDrag;
    boundStartDragTouch = startDragTouch;
    boundCropKeyPan = cropKeyPan;
    boundOnDrag = onDrag;
    boundOnDragTouch = onDragTouch;
    boundEndDrag = endDrag;
    // Mouse/touch drag
    cropArea.addEventListener('mousedown', boundStartDrag);
    cropArea.addEventListener('touchstart', boundStartDragTouch, { passive: false });
    // Keyboard pan (arrow keys) — #crop-area is focusable (tabindex=0 in the
    // markup); mirrors the drag offset math so the reposition is operable
    // without a pointer.
    cropArea.addEventListener('keydown', boundCropKeyPan);
    document.addEventListener('mousemove', boundOnDrag);
    document.addEventListener('touchmove', boundOnDragTouch, { passive: false });
    document.addEventListener('mouseup', boundEndDrag);
    document.addEventListener('touchend', boundEndDrag);
    cropListenersAttached = true;
    // Zoom
    zoomSlider.oninput = () => {
        cropState.zoom = parseInt(zoomSlider.value);
        updateCropPreview();
    };
    // Save
    saveBtn.onclick = () => {
        saveCroppedAvatar();
        closeCropModal();
    };
    // Cancel/Close
    cancelBtn.onclick = closeCropModal;
    closeBtn.onclick = closeCropModal;
    // Click on the .modal-overlay backdrop closes the modal. Guard with a
    // dataset flag — without this every avatar-crop session would stack one
    // more click listener and the overlay would call closeCropModal N times
    // per click after N opens. The escape-key listener below already does
    // this; the overlay listener was missing the same protection.
    if (!modal.dataset.overlayCloseBound) {
        modal.dataset.overlayCloseBound = '1';
        modal.querySelector('[data-close-avatar-crop]')?.addEventListener('click', closeCropModal);
    }
    // Fallback: clicking the modal element itself (outside both content + overlay)
    // also closes — keeps backwards compat with the previous click-target check.
    modal.onclick = (e) => {
        if (e.target === modal)
            closeCropModal();
    };
    // Escape-to-close: bind ONCE for the page lifetime. The handler looks the
    // modal up by id (so it pins no element in a closure) and self-guards on
    // ``.active`` (a cheap no-op while the modal is closed). This keeps ESC
    // working no matter how the modal is re-opened — including a direct
    // ``.active`` toggle that doesn't re-run this setup — and can't stack
    // duplicate listeners. (Previously the handler was removed + nulled on
    // close, so any re-open that skipped this setup left ESC dead.)
    if (!cropEscBound) {
        cropEscBound = true;
        document.addEventListener('keydown', (e) => {
            if (e.key !== 'Escape')
                return;
            const m = document.getElementById('avatar-crop-modal');
            if (m && m.classList.contains('active'))
                closeCropModal();
        });
    }
}
function startDrag(e) {
    cropState.isDragging = true;
    cropState.startX = e.clientX - cropState.offsetX;
    cropState.startY = e.clientY - cropState.offsetY;
}
function startDragTouch(e) {
    if (!e.touches || e.touches.length === 0)
        return;
    e.preventDefault();
    cropState.isDragging = true;
    const touch = e.touches[0];
    cropState.startX = touch.clientX - cropState.offsetX;
    cropState.startY = touch.clientY - cropState.offsetY;
}
function onDrag(e) {
    if (!cropState.isDragging)
        return;
    cropState.offsetX = e.clientX - cropState.startX;
    cropState.offsetY = e.clientY - cropState.startY;
    updateCropPreview();
}
function onDragTouch(e) {
    if (!cropState.isDragging)
        return;
    if (!e.touches || e.touches.length === 0)
        return;
    e.preventDefault();
    const touch = e.touches[0];
    cropState.offsetX = touch.clientX - cropState.startX;
    cropState.offsetY = touch.clientY - cropState.startY;
    updateCropPreview();
}
function endDrag() {
    cropState.isDragging = false;
}
// Arrow-key panning of the crop image — keyboard parity for the pointer drag
// (WCAG 2.1.1). Adjusts the same offsetX/offsetY the drag handlers write, then
// repaints. Shift takes a larger step for coarse positioning.
function cropKeyPan(e) {
    let dx = 0;
    let dy = 0;
    const step = e.shiftKey ? CROP_KEY_STEP_LARGE : CROP_KEY_STEP;
    switch (e.key) {
        case 'ArrowUp':
            dy = -step;
            break;
        case 'ArrowDown':
            dy = step;
            break;
        case 'ArrowLeft':
            dx = -step;
            break;
        case 'ArrowRight':
            dx = step;
            break;
        default: return; // not a pan key — let it through (Tab, Enter, …)
    }
    e.preventDefault(); // don't scroll the modal/page while panning
    cropState.offsetX += dx;
    cropState.offsetY += dy;
    updateCropPreview();
}
function updateCropPreview() {
    const cropImage = document.getElementById('crop-image');
    if (!cropImage)
        return;
    const scale = cropState.zoom / 100;
    const width = cropState.imgWidth * scale;
    const height = cropState.imgHeight * scale;
    cropImage.style.width = `${width}px`;
    cropImage.style.height = `${height}px`;
    cropImage.style.left = `${cropState.offsetX}px`;
    cropImage.style.top = `${cropState.offsetY}px`;
}
function saveCroppedAvatar() {
    const cropImage = document.getElementById('crop-image');
    if (!cropImage)
        return;
    // Guard the not-yet-loaded state: cropState.imgWidth/imgHeight stay 0 until
    // cropImage.onload runs. Saving before then divides by 0, making
    // srcX/srcY/srcSize NaN, so drawImage is a no-op and a blank canvas would be
    // persisted as the avatar with no error.
    if (!cropState.imgWidth ||
        !cropState.imgHeight ||
        cropImage.naturalWidth <= 0 ||
        cropImage.naturalHeight <= 0) {
        // English UI copy — see the matching note in openAvatarCropModal.
        showToast('The image is still loading — try again in a moment.', { type: 'error' });
        return;
    }
    // Create canvas to crop the circular area
    const canvas = document.createElement('canvas');
    const size = 200; // Output size
    canvas.width = size;
    canvas.height = size;
    const ctx = canvas.getContext('2d');
    if (!ctx)
        return;
    // Calculate crop area (center of crop-area is 140,140 and circle is 200x200)
    const areaCenter = 140;
    const circleRadius = 100;
    const scale = cropState.zoom / 100;
    // Calculate source position relative to image
    const srcX = (areaCenter - circleRadius - cropState.offsetX) / scale * (cropImage.naturalWidth / cropState.imgWidth);
    const srcY = (areaCenter - circleRadius - cropState.offsetY) / scale * (cropImage.naturalHeight / cropState.imgHeight);
    const srcSize = (circleRadius * 2) / scale * (cropImage.naturalWidth / cropState.imgWidth);
    // Draw circular clip
    ctx.beginPath();
    ctx.arc(size / 2, size / 2, size / 2, 0, Math.PI * 2);
    ctx.closePath();
    ctx.clip();
    // Draw image
    ctx.drawImage(cropImage, srcX, srcY, srcSize, srcSize, 0, 0, size, size);
    // Get data URL
    const croppedDataUrl = canvas.toDataURL('image/png');
    // Save to appropriate setting based on target, then refresh the preview via
    // the shared helper.
    if (currentAvatarTarget === 'ai') {
        settings.aiAvatar = croppedDataUrl;
        saveSettings();
        setAvatarPreview('ai', croppedDataUrl);
        // Also refresh the chat-page avatars (#chat-empty-avatar has no other
        // writer, so it kept showing the OLD avatar until app restart).
        updateAiAvatars();
        showToast('AI Avatar updated!', { type: 'success' });
    }
    else {
        settings.userAvatar = croppedDataUrl;
        saveSettings();
        setAvatarPreview('user', croppedDataUrl);
        showToast('Avatar updated!', { type: 'success' });
    }
    // Refresh chat to show new avatar
    if (chatManager) {
        chatManager.renderMessages();
    }
}
function closeCropModal() {
    const modal = document.getElementById('avatar-crop-modal');
    // Route through the shared modal helper: restores focus to the trigger and
    // lifts the app inert state. (closeModal no-ops on a null/closed modal.)
    closeModal(modal);
    // Clean up listeners using stored bound functions. Detach ALL five bound
    // handlers and reset cropListenersAttached so the attach/detach set stays
    // symmetric — leaving boundStartDrag/boundStartDragTouch non-null while
    // resetting cropListenersAttached=false would silently skip re-detaching
    // the crop-area mousedown/touchstart on the next open if that node were
    // ever replaced. The crop-area handlers are removed via the live node.
    const cropArea = document.getElementById('crop-area');
    if (cropArea && boundStartDrag)
        cropArea.removeEventListener('mousedown', boundStartDrag);
    if (cropArea && boundStartDragTouch)
        cropArea.removeEventListener('touchstart', boundStartDragTouch);
    boundStartDrag = null;
    boundStartDragTouch = null;
    if (boundOnDrag) {
        document.removeEventListener('mousemove', boundOnDrag);
        boundOnDrag = null;
    }
    if (boundEndDrag) {
        document.removeEventListener('mouseup', boundEndDrag);
        document.removeEventListener('touchend', boundEndDrag);
        boundEndDrag = null;
    }
    if (boundOnDragTouch) {
        document.removeEventListener('touchmove', boundOnDragTouch);
        boundOnDragTouch = null;
    }
    cropListenersAttached = false;
    // The Escape handler is bound once for the page lifetime (see
    // setupCropEventListeners) and self-guards on ``.active``, so there is
    // nothing to detach here.
    // Release the full-size source. The file is read as a data URL (base64 is
    // ~1.37x the bytes, so ~27MB at the permitted 20MB maximum) and #crop-image
    // is a STATIC element in index.html that stays in the document — so after a
    // single avatar change, save or cancel, the window held two copies of that
    // string for the rest of the session. Only the 200x200 PNG that
    // saveCroppedAvatar already produced is needed downstream.
    const cropImage = document.getElementById('crop-image');
    if (cropImage) {
        // Null the handlers BEFORE reassigning src: closeCropModal is itself
        // called from inside onload's broken-image guard and from onerror, and
        // the placeholder load would otherwise re-enter them.
        cropImage.onload = null;
        cropImage.onerror = null;
        // The 1x1 placeholder rather than '' — an empty src re-requests the
        // page URL.
        cropImage.src = BLANK_AVATAR_GIF;
    }
    cropState.imageUrl = '';
    cropState.imgWidth = 0;
    cropState.imgHeight = 0;
}
function removeAvatar(target = 'user') {
    if (target === 'ai') {
        settings.aiAvatar = '';
        saveSettings();
        setAvatarPreview('ai', '');
        // Keep the chat page in sync (see saveCroppedAvatar).
        updateAiAvatars();
        showToast('AI Avatar removed', { type: 'info' });
    }
    else {
        settings.userAvatar = '';
        saveSettings();
        setAvatarPreview('user', '');
        showToast('Avatar removed', { type: 'info' });
    }
    // Refresh chat
    if (chatManager) {
        chatManager.renderMessages();
    }
}
function saveProfileToAI() {
    // Empty-name fallback must match the input handler + settings default
    // ('You') — a divergent 'User' here silently flipped settings.userName
    // depending on which code path ran last.
    const displayName = document.getElementById('user-name-input')?.value?.trim() || 'You';
    const bio = document.getElementById('user-bio-input')?.value?.trim() || '';
    const preferences = document.getElementById('user-preferences-input')?.value?.trim() || '';
    const isCreator = document.getElementById('creator-toggle')?.checked || false;
    if (chatManager?.connected) {
        chatManager.send({
            type: 'save_profile',
            profile: { display_name: displayName, bio, preferences, is_creator: isCreator }
        });
        // Also update local settings
        settings.userName = displayName;
        settings.isCreator = isCreator;
        saveSettings();
    }
    else {
        showToast('Not connected to AI server', { type: 'error' });
    }
}
// ============================================================================
// Helpers
// ============================================================================
async function openFolder(type) {
    let path;
    try {
        if (type === 'logs') {
            path = await invoke('get_logs_path');
        }
        else if (type === 'data') {
            path = await invoke('get_data_path');
        }
        else {
            showToast('Unknown folder type', { type: 'error' });
            return;
        }
        await invoke('open_folder', { path });
    }
    catch (error) {
        showToast(`Failed to open folder: ${error}`, { type: 'error' });
    }
}
function loadAllData() {
    dataCache.clear();
    updateStatus();
    loadLogs();
    loadDbStats();
}
// ============================================================================
// API Failover UI
// ============================================================================
let apiFailoverReadinessRequested = false;
function initApiFailoverUI() {
    // Listen for failover status updates from chat-manager. The detail payloads
    // are typed (ApiFailoverStatusDetail / ApiHealthResultDetail) and shape-
    // checked before use, so a malformed/empty frame can't throw on a bad
    // destructure — it's simply ignored.
    window.addEventListener('api-failover-status', ((e) => {
        const detail = e.detail;
        if (!detail || typeof detail !== 'object')
            return;
        renderApiFailoverUI(detail);
    }));
    window.addEventListener('api-health-result', ((e) => {
        const detail = e.detail;
        if (!detail || typeof detail !== 'object' || !Array.isArray(detail.results))
            return;
        renderHealthCheckResults(detail.results);
    }));
    // Health check button
    document.getElementById('btn-health-check')?.addEventListener('click', () => {
        if (chatManager?.connected) {
            chatManager.send({ type: 'health_check_endpoint' });
            showToast('Running health check...', { type: 'info', duration: 2000 });
        }
        else {
            showToast('Bot not connected', { type: 'error' });
        }
    });
    // Request initial status when chat connects. Module-scoped guard (was a
    // window property) so a re-run after a WebView2 navigation can re-arm the
    // readiness poll instead of being permanently suppressed by a stale global.
    if (!apiFailoverReadinessRequested) {
        apiFailoverReadinessRequested = true;
        // Poll for chatManager readiness. We extend the give-up window to 60s
        // because slow first connects (cold WS auth, dev tools attached, etc.)
        // can blow past the previous 30s ceiling and leave the failover panel
        // stuck on "loading…" until the user reloads the page.
        const checkInterval = setInterval(() => {
            if (chatManager?.connected) {
                chatManager.send({ type: 'get_api_endpoints' });
                clearInterval(checkInterval);
                // Stay latched on success so we don't re-poll an already-served
                // panel — cancel the give-up timer too, or its unconditional
                // re-arm below would undo the latch 60s later.
                clearTimeout(giveUpTimer);
            }
        }, 2000);
        // Give-up timeout: stop the poll AND re-arm the guard so a late connect
        // (slower than the 60s ceiling) can start a fresh readiness poll the
        // next time initApiFailoverUI runs, instead of being permanently
        // suppressed by a latched flag after we gave up.
        const giveUpTimer = window.setTimeout(() => {
            clearInterval(checkInterval);
            apiFailoverReadinessRequested = false;
        }, 60000);
    }
}
function renderApiFailoverUI(data) {
    const section = document.getElementById('api-failover-section');
    const container = document.getElementById('api-endpoints');
    if (!section || !container)
        return;
    // Hide only on an EXPLICIT "not available". The api_endpoint_switched
    // frames (manual switch + auto-failover broadcast) carry endpoints but
    // no `available` key — treating that as unavailable hid the panel the
    // moment the user clicked a standby endpoint.
    if (data.available === false) {
        section.classList.add('hidden');
        return;
    }
    if (!Array.isArray(data.endpoints)) {
        // Frame without endpoint data (e.g. the unauthenticated
        // safe-notification variant) — leave the panel as-is.
        return;
    }
    // Toggle the CLASS, not an inline `display`. index.html ships this card as
    // `class="api-failover-card hidden"`, and `.hidden` is `display:none
    // !important` — so the old `style.display = ''` cleared an inline value that
    // was never set and lost to the !important class every time. Nothing else in
    // the file removes `.hidden` from this element, which meant the API Endpoint
    // panel could not be shown at all: every endpoint list, every manual switch
    // and every auto-failover broadcast rendered into a permanently invisible
    // card. (The hide branch above had the mirror-image bug — an inline `none`
    // on something the class already hid.)
    section.classList.remove('hidden');
    const endpoints = data.endpoints;
    container.innerHTML = '';
    for (const ep of endpoints) {
        // A frame element that isn't an object (null, string, number) would
        // throw on the property access below and abort the whole loop AFTER
        // container.innerHTML was cleared, blanking the panel. WS frame contents
        // are untrusted (misbehaving/compromised backend) — skip malformed items.
        if (!ep || typeof ep !== 'object')
            continue;
        const item = document.createElement('div');
        item.className = 'api-endpoint-item' +
            (ep.active ? ' active' : '') +
            (!ep.healthy ? ' unhealthy' : '');
        // Coerce numeric fields BEFORE interpolation. ?? 0 only catches
        // null/undefined — a string from a misbehaving server (or compromised
        // local backend) would be injected raw into innerHTML and execute.
        const totalRequests = Number(ep.total_requests) || 0;
        const failureRate = Number(ep.failure_rate) || 0;
        // Coerce server-provided values to strings BEFORE calling string-only
        // methods (.substring / .toUpperCase). `ep` is Record<string, unknown>,
        // so a non-string value would otherwise throw TypeError and abort the
        // entire endpoint render loop.
        const epType = String(ep.type ?? '').toUpperCase();
        const epLabel = String(ep.label ?? '') || epType;
        const lastError = ep.last_error == null ? '' : String(ep.last_error).substring(0, 80);
        item.innerHTML = `
            <div class="ep-label">${ep.active ? icon('check') + ' ' : ''}${escapeHtml(epLabel)}</div>
            <div class="ep-status">${ep.healthy ? icon('pulse') + ' Healthy' : icon('pulse') + ' Unhealthy'}${lastError ? ` — ${escapeHtml(lastError)}` : ''}</div>
            <span class="ep-badge ${ep.active ? '' : (ep.healthy ? 'healthy' : 'unhealthy-badge')}">${ep.active ? 'ACTIVE' : (ep.healthy ? 'standby' : 'down')}</span>
            <div class="ep-stats">Requests: ${totalRequests} | Fail rate: ${failureRate.toFixed(1)}%</div>
        `;
        // Click / keyboard to switch. The item is a custom control built from a
        // <div>, so it needs role=button + tabindex + an Enter/Space key handler
        // to be operable without a mouse (WCAG 2.1.1 Keyboard, Level A); there is
        // no other UI path to switch endpoints. Space is preventDefault'd so it
        // activates the control instead of scrolling the panel.
        if (!ep.active) {
            const doSwitch = () => {
                if (chatManager?.connected) {
                    chatManager.send({ type: 'switch_api_endpoint', endpoint: ep.type });
                    showToast(`Switching to ${epType}...`, { type: 'info', duration: 2000 });
                }
            };
            item.style.cursor = 'pointer';
            // English, matching the aria-label two lines down — the visible
            // tooltip used to be Thai while the accessible name was English, so
            // the two disagreed about the same control in a lang="en" document.
            item.title = `Click to switch to ${epType}`;
            item.setAttribute('role', 'button');
            item.setAttribute('tabindex', '0');
            item.setAttribute('aria-label', `Switch to ${epType}`);
            item.addEventListener('click', doSwitch);
            item.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ' ' || e.key === 'Spacebar') {
                    e.preventDefault();
                    doSwitch();
                }
            });
        }
        container.appendChild(item);
    }
}
function renderHealthCheckResults(results) {
    // Remove existing result
    const existing = document.getElementById('api-health-results');
    if (existing)
        existing.remove();
    const section = document.getElementById('api-failover-section');
    if (!section || !results?.length)
        return;
    const div = document.createElement('div');
    div.id = 'api-health-results';
    div.className = 'api-health-result';
    div.innerHTML = results.map(r => {
        // Skip a malformed (non-object) entry from an untrusted WS frame — a null
        // r would throw on the property access below and break the whole list.
        if (!r || typeof r !== 'object')
            return '';
        // Coerce latency to a number — escape the rest. r is Record<string, unknown>,
        // so any string from a misbehaving WS frame would otherwise land in
        // innerHTML unescaped. Also coerce label/error to string so a non-string
        // value doesn't throw TypeError on .substring and break the whole list.
        const latencyMs = Number(r.latency_ms) || 0;
        const labelOrEndpoint = String(r.label ?? '') || String(r.endpoint ?? '');
        const errorText = String(r.error ?? 'Failed').substring(0, 100);
        return `<div><strong>${escapeHtml(labelOrEndpoint)}</strong>: ` +
            (r.healthy
                ? `<span class="healthy">${icon('check')} Healthy (${latencyMs}ms)</span>`
                : `<span class="unhealthy">${icon('x')} ${escapeHtml(errorText)}</span>`) +
            '</div>';
    }).join('');
    section.appendChild(div);
    // Auto-remove after 15s
    setTimeout(() => div.remove(), 15000);
}
// ============================================================================
// Export for global access
// ============================================================================
//
// Only the two globals that something OUTSIDE this module actually reads are
// kept. index.html has NO inline on*-handlers (CSP-compliant — every control is
// wired via addEventListener), so the old toggleAutoScroll / clearLogs /
// clearHistory / openFolder / loadLogs / toggleTheme / showToast / startBot
// window exports had zero callers and were removed (dead surface).
//
//   - window.showPage    — driven by the Playwright e2e fixtures (a11y,
//                          visual-regression, dashboard-smoke, h7-csp,
//                          screenshots) to navigate without clicking the nav.
//   - window.chatManager — read by the e2e suites to assert isStreaming etc.;
//                          (re)assigned with the real instance in
//                          initChatManager().
window.chatManager = null; // Updated in initChatManager()
window.showPage = switchPage; // Used by e2e fixtures to drive navigation
//# sourceMappingURL=app.js.map