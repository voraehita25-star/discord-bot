/**
 * 디스코드 봇 대시보드 - Enhanced TypeScript Frontend
 * Tauri v2 Desktop Application
 * 
 * Main application module — UI, navigation, charts, bot control, settings.
 * Chat & memory management extracted to chat-manager.ts.
 * Shared utilities in shared.ts.
 */

import type { BotStatus, StartProgress, DbStats, ChannelInfo, UserInfo, ChartDataPoint, CacheEntry, Settings, ApiFailoverStatusDetail, ApiHealthResultDetail } from './types.js';
import {
    invoke,
    escapeHtml,
    isSafeAvatarUrl,
    settings,
    loadSettings,
    saveSettings,
    initToastContainer,
    setup3DInteractions,
    animateNumber,
    setSkeleton,
    showToast,
    showConfirmDialog,
    icon,
} from './shared.js';
import {
    chatManager,
    initChatManager,
} from './chat-manager.js';
import { HistoryManager } from './history-manager.js';

// ============================================================================
// Performance Cache System
// ============================================================================

// Exported so app.test.ts exercises the SHIPPED cache (TTL expiry + capacity
// eviction), not a copy. Production still uses the module-level `dataCache`.
export class DataCache {
    private cache: Map<string, CacheEntry<unknown>> = new Map();
    private readonly maxSize = 200;

    set<T>(key: string, data: T, ttlMs: number = 5000): void {
        // Evict oldest entries if at capacity
        if (this.cache.size >= this.maxSize && !this.cache.has(key)) {
            const oldest = this.cache.keys().next().value;
            if (oldest !== undefined) this.cache.delete(oldest);
        }
        this.cache.set(key, {
            data,
            timestamp: Date.now(),
            ttl: ttlMs
        });
    }

    get<T>(key: string): T | null {
        const entry = this.cache.get(key);
        if (!entry) return null;
        
        if (Date.now() - entry.timestamp > entry.ttl) {
            this.cache.delete(key);
            return null;
        }
        
        return entry.data as T;
    }

    invalidate(key: string): void {
        this.cache.delete(key);
    }

    clear(): void {
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
export const PAGE_ALIASES: Record<string, string> = { config: 'settings' };

// Pure resolution of a requested page id to a canonical one: aliases map
// through, then anything not in VALID_PAGES is rejected (returns null). Shared
// by switchPage so the guard logic has a single source of truth that unit
// tests can exercise without driving the DOM.
export function resolvePage(page: string): string | null {
    const resolved = PAGE_ALIASES[page] ?? page;
    if (!VALID_PAGES.includes(resolved)) return null;
    return resolved;
}

let currentPage = 'status';
let historyManager: HistoryManager | null = null;
let refreshInterval: number | null = null;
let logsRefreshInterval: number | null = null;
let logsAutoScrollEnabled = true;
let lastLogSignature: string | null = null;
// True after the failure toast for the CURRENT get_logs failure streak has
// been shown; reset on the next successful load (1s poll — see loadLogs).
let logsLoadFailedToastShown = false;

// Chart data history
const memoryHistory: ChartDataPoint[] = [];
const messagesHistory: ChartDataPoint[] = [];

// Settings with defaults

const debounceTimers: Map<string, number> = new Map();

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
const modalReturnFocus = new WeakMap<HTMLElement, HTMLElement | null>();

// Modals that called setAppInert(true) via openModal. inert lifts only when
// every owned modal has closed — so a chat modal toggling .active directly
// (it lives INSIDE .app and never owns inert) can't pin inert on.
const inertModals = new Set<HTMLElement>();

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
let _chatOverlayObserver: MutationObserver | null = null;

function syncChatOverlayInert(): void {
    const overlay = document.getElementById('chat-not-running-overlay');
    const chatLayout = document.querySelector<HTMLElement>('#page-chat .chat-layout');
    if (!overlay || !chatLayout) return;
    if (overlay.classList.contains('visible')) {
        chatLayout.setAttribute('inert', '');
        chatLayout.setAttribute('aria-hidden', 'true');
    } else {
        chatLayout.removeAttribute('inert');
        chatLayout.removeAttribute('aria-hidden');
    }
}

function initChatOverlayA11y(): void {
    const overlay = document.getElementById('chat-not-running-overlay');
    if (!overlay || _chatOverlayObserver) return;
    _chatOverlayObserver = new MutationObserver(() => syncChatOverlayInert());
    _chatOverlayObserver.observe(overlay, { attributes: true, attributeFilter: ['class'] });
    syncChatOverlayInert();  // apply the initial state
}

function setAppInert(inert: boolean): void {
    // Modals are siblings of `.app` (they live after </div> for .app), so
    // toggling inert/aria-hidden on the app shell never touches the open modal.
    const app = document.querySelector<HTMLElement>('.app');
    if (!app) return;
    if (inert) {
        // `inert` is the correct primitive (removes from tab order + AT tree).
        // aria-hidden is a belt-and-suspenders fallback for older WebView2.
        app.setAttribute('inert', '');
        app.setAttribute('aria-hidden', 'true');
    } else {
        app.removeAttribute('inert');
        app.removeAttribute('aria-hidden');
    }
}

function getFirstFocusable(modal: HTMLElement): HTMLElement | null {
    const focusables = Array.from(
        modal.querySelectorAll<HTMLElement>(
            'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ),
    ).filter(el => el.offsetWidth > 0 || el.offsetHeight > 0 || el === document.activeElement);
    return focusables[0] ?? null;
}

export function openModal(modal: HTMLElement | null): void {
    if (!modal) return;
    // Record the trigger so closeModal can restore focus to it. Skip <body>
    // (the default activeElement) — restoring focus there is a no-op anyway.
    const active = document.activeElement;
    modalReturnFocus.set(
        modal,
        active instanceof HTMLElement && active !== document.body ? active : null,
    );
    modal.classList.add('active');
    inertModals.add(modal);   // Set => add ซ้ำไม่มีผล (idempotent re-open)
    setAppInert(true);
    // Prefer the first interactive control; fall back to the close button, then
    // the modal element itself (made programmatically focusable) so focus never
    // stays stranded behind the overlay.
    const target =
        getFirstFocusable(modal) ??
        modal.querySelector<HTMLElement>('.modal-close, [data-close-shortcuts], [data-close-avatar-crop]');
    if (target) {
        target.focus();
    } else if (typeof modal.focus === 'function') {
        if (!modal.hasAttribute('tabindex')) modal.setAttribute('tabindex', '-1');
        modal.focus();
    }
}

export function closeModal(modal: HTMLElement | null): void {
    if (!modal) return;
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
export function _resetModalInertState(): void {
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
    if (sakuraEnabled) initSakuraAnimation();
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
    } catch {
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
export function pickTopmostModal(): HTMLElement | null {
    const actives = document.querySelectorAll<HTMLElement>('.modal.active');
    return actives.length ? actives[actives.length - 1] : null;
}

function initKeyboardShortcuts(): void {
    document.addEventListener('keydown', (e) => {
        // Single dispatch per keystroke. Each branch early-returns so a key that
        // matches one shortcut can't fall through into another (e.g. the old
        // chain re-evaluated `e.ctrlKey && …` for every shortcut, and a future
        // overlapping binding would double-fire). Ctrl chords switch on the
        // normalized key; plain keys are handled after.
        if (e.ctrlKey) {
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
                const focusables = Array.from(
                    modal.querySelectorAll<HTMLElement>(
                        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
                    ),
                ).filter(el => el.offsetWidth > 0 || el.offsetHeight > 0 || el === document.activeElement);
                if (focusables.length > 0) {
                    const first = focusables[0];
                    const last = focusables[focusables.length - 1];
                    const activeEl = document.activeElement as HTMLElement | null;
                    if (e.shiftKey && (activeEl === first || !modal.contains(activeEl))) {
                        e.preventDefault();
                        last.focus();
                    } else if (!e.shiftKey && (activeEl === last || !modal.contains(activeEl))) {
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
function hasStoredTheme(): boolean {
    try {
        const saved = localStorage.getItem('dashboard-settings');
        if (!saved) return false;
        const parsed = JSON.parse(saved) as { theme?: unknown };
        return parsed.theme === 'dark' || parsed.theme === 'light';
    } catch {
        return false;
    }
}

// Exported as a test seam (like _resetModalInertState) so the first-run
// prefers-color-scheme default (A11Y-05) can be asserted in app.test.ts.
export function initTheme(): void {
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

function toggleTheme(): void {
    settings.theme = settings.theme === 'dark' ? 'light' : 'dark';
    applyTheme(settings.theme);
    saveSettings();
    showToast(`Theme: ${settings.theme === 'dark' ? 'Dark' : 'Light'}`, { type: 'info', duration: 1500 });
}

function applyTheme(theme: 'dark' | 'light'): void {
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
function applyDensity(compact: boolean): void {
    if (compact) {
        document.documentElement.setAttribute('data-density', 'compact');
    } else {
        document.documentElement.removeAttribute('data-density');
    }
}


// ============================================================================
// Settings Management
// ============================================================================

function updateAiAvatars(): void {
    const safeAvatar = isSafeAvatarUrl(settings.aiAvatar) ? settings.aiAvatar : '';
    // Update empty state avatar
    const emptyAvatar = document.getElementById('chat-empty-avatar') as HTMLImageElement | null;
    if (emptyAvatar) {
        if (safeAvatar) {
            emptyAvatar.src = safeAvatar;
            emptyAvatar.classList.remove('hidden');
        } else {
            emptyAvatar.removeAttribute('src');
            emptyAvatar.classList.add('hidden');
        }
    }
    // Update chat header avatar
    const headerAvatar = document.getElementById('chat-role-avatar') as HTMLImageElement | null;
    if (headerAvatar) {
        if (safeAvatar) {
            headerAvatar.src = safeAvatar;
            headerAvatar.classList.remove('hidden');
        } else {
            headerAvatar.removeAttribute('src');
            headerAvatar.classList.add('hidden');
        }
    }
}

function updateSetting<K extends keyof Settings>(key: K, value: Settings[K]): void {
    settings[key] = value;
    saveSettings();
    
    // Apply changes
    if (key === 'refreshInterval') {
        restartRefreshLoop();
    } else if (key === 'theme') {
        applyTheme(value as 'dark' | 'light');
    }
}

// ============================================================================
// Lightweight Charts (Canvas-based for performance)
// ============================================================================

function initCharts(): void {
    // Charts will be initialized when the status page loads
    window.addEventListener('resize', debounce(updateCharts, 'resize', 250));
}

// Exported so app.test.ts exercises the SHIPPED chart-history capping (which
// caps at the live `settings.chartHistory`), not a re-implementation.
export function addChartDataPoint(history: ChartDataPoint[], value: number): void {
    history.push({
        timestamp: Date.now(),
        value
    });

    while (history.length > settings.chartHistory) {
        history.shift();
    }
}

function drawChart(canvasId: string, data: ChartDataPoint[], color: string, label: string): void {
    const canvas = document.getElementById(canvasId) as HTMLCanvasElement | null;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    // Read theme colors from CSS tokens at draw time (SHARED CONTRACT #1) so a
    // light/dark toggle re-colors the canvas — it can't pick up CSS like real
    // DOM does. Cache the lookups for the duration of this single draw; they're
    // re-read on the next draw (updateCharts runs on every status tick + the
    // post-toggle redraw below).
    const tokens = getComputedStyle(document.documentElement);
    const gridColor = tokens.getPropertyValue('--chart-grid').trim() || 'rgba(72,196,232,.10)';
    const fillTop = tokens.getPropertyValue('--chart-fill-top').trim() || 'rgba(61,245,255,.30)';
    const fillBot = tokens.getPropertyValue('--chart-fill-bot').trim() || 'rgba(61,245,255,.05)';
    const placeholderColor = tokens.getPropertyValue('--text-tertiary').trim() || 'rgba(255,255,255,0.3)';

    // Fade-in entrance on the very first draw (CSS handles the transition;
    // .chart-ready flips opacity from 0→1 and translateY from 16px→0).
    if (!canvas.classList.contains('chart-ready')) {
        requestAnimationFrame(() => canvas.classList.add('chart-ready'));
    }

    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();

    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);

    const width = rect.width;
    const height = rect.height;
    const padding = 30;

    ctx.clearRect(0, 0, width, height);

    if (data.length < 2) {
        ctx.fillStyle = placeholderColor;
        ctx.font = '12px sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('Collecting data...', width / 2, height / 2);
        return;
    }

    const values = data.map(d => d.value);
    // Use reduce instead of spread to prevent stack overflow with large arrays
    const rawMin = values.reduce((a, b) => Math.min(a, b), Infinity);
    const rawMax = values.reduce((a, b) => Math.max(a, b), -Infinity);
    // Padded versions are used for scaling so the line never grazes the
    // chart edge; the raw values are shown as axis labels because a
    // memory chart that never dipped below 42 MB shouldn't claim it
    // bottomed out at 37.8 MB.
    const minVal = rawMin * 0.9;
    let maxVal = rawMax * 1.1 || 1;
    // Prevent division by zero when all values are identical
    if (maxVal === minVal) maxVal = minVal + 1;

    // Draw grid
    ctx.strokeStyle = gridColor;
    ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i++) {
        const y = padding + (height - padding * 2) * (i / 4);
        ctx.beginPath();
        ctx.moveTo(padding, y);
        ctx.lineTo(width - padding, y);
        ctx.stroke();
    }

    // Draw gradient fill from the area-fill tokens (top → bottom) instead of
    // deriving alphas off the line color, so the fill is theme-driven too.
    const gradient = ctx.createLinearGradient(0, padding, 0, height - padding);
    gradient.addColorStop(0, fillTop);
    gradient.addColorStop(1, fillBot);

    ctx.beginPath();
    ctx.moveTo(padding, height - padding);

    data.forEach((point, i) => {
        const x = padding + (width - padding * 2) * (i / (data.length - 1));
        const y = height - padding - ((point.value - minVal) / (maxVal - minVal)) * (height - padding * 2);
        ctx.lineTo(x, y);
    });

    ctx.lineTo(width - padding, height - padding);
    ctx.closePath();
    ctx.fillStyle = gradient;
    ctx.fill();

    // Draw line
    ctx.beginPath();
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';

    data.forEach((point, i) => {
        const x = padding + (width - padding * 2) * (i / (data.length - 1));
        const y = height - padding - ((point.value - minVal) / (maxVal - minVal)) * (height - padding * 2);
        
        if (i === 0) {
            ctx.moveTo(x, y);
        } else {
            ctx.lineTo(x, y);
        }
    });
    ctx.stroke();

    // Draw current value
    const currentValue = data[data.length - 1]?.value ?? 0;
    ctx.fillStyle = color;
    ctx.font = 'bold 14px sans-serif';
    ctx.textAlign = 'right';
    ctx.fillText(`${label}: ${currentValue.toFixed(1)}`, width - padding, 20);

    // Draw min/max labels — also token-driven so they stay legible in light
    // mode (the old hardcoded white vanished against the light Blueprint bg).
    ctx.fillStyle = placeholderColor;
    ctx.font = '10px sans-serif';
    ctx.textAlign = 'left';
    ctx.fillText(rawMax.toFixed(1), 5, padding + 10);
    ctx.fillText(rawMin.toFixed(1), 5, height - padding);
}

function updateCharts(): void {
    // Line colors come from CSS tokens too (SHARED CONTRACT #1: --chart-line),
    // so both charts re-color on a theme toggle. Memory uses the canonical
    // chart line; the messages series uses --chart-line-2 (the dedicated second
    // series token). Fall back through the old --accent-purple, then a hardcoded
    // blue, so an unstyled build still renders distinguishable lines.
    const tokens = getComputedStyle(document.documentElement);
    const lineColor = tokens.getPropertyValue('--chart-line').trim() || '#3df5ff';
    const messagesColor =
        tokens.getPropertyValue('--chart-line-2').trim() ||
        tokens.getPropertyValue('--accent-purple').trim() ||
        '#6aa6ff';
    drawChart('memory-chart', memoryHistory, lineColor, 'Memory MB');
    drawChart('messages-chart', messagesHistory, messagesColor, 'Messages');

    // Fill the in-header readout chips (CONTRACT) with the latest sample so the
    // current value is legible even before the canvas line is read. Memory keeps
    // one decimal + unit; message count is an integer with thousands grouping.
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
// Sakura Petals Animation (Optimized with Object Pool)
// ============================================================================

let sakuraEnabled: boolean = true;
let sakuraInterval: number | null = null;
let sakuraDisposers: Array<() => void> = [];

function stopSakura(): void {
    if (sakuraInterval !== null) {
        clearInterval(sakuraInterval);
        sakuraInterval = null;
    }
    for (const dispose of sakuraDisposers) dispose();
    sakuraDisposers = [];
    const c = document.getElementById('sakura-container');
    if (c) c.innerHTML = '';
}

/** Called by Settings UI toggle. Enables or disables the animation at runtime. */
export function setSakuraEnabled(enabled: boolean): void {
    sakuraEnabled = enabled;
    if (enabled) {
        if (sakuraInterval === null) initSakuraAnimation();
    } else {
        stopSakura();
    }
}

function initSakuraAnimation(): void {
    const container = document.getElementById('sakura-container');
    if (!container) return;
    if (!sakuraEnabled) return;
    // Respect prefers-reduced-motion: the CSS zeroes animation durations, but
    // without this the JS would still churn ~30 DOM nodes/sec for zero visible
    // payoff. Bail entirely so reduced-motion users pay no animation cost.
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

    // All five shapes are unmistakably sakura: two full five-petal blossoms and
    // three single petals — every petal carries the signature notched (cleft)
    // outer tip. (The old set mixed in plain ellipses and a diamond sparkle.)
    const BLOSSOM_LOBE =
        'M20 20 C15 15 13.6 8.4 16.4 5.2 C18 3.4 19.5 4.8 20 7 C20.5 4.8 22 3.4 23.6 5.2 C26.4 8.4 25 15 20 20 Z';
    const BLOSSOM_LOBE_ROUND =
        'M20 20 C14.6 15.2 13 9 16 5.6 C17.8 3.6 19.4 5 20 7.4 C20.6 5 22.2 3.6 24 5.6 C27 9 25.4 15.2 20 20 Z';
    const blossom = (lobe: string, center: string): string =>
        `<svg viewBox="0 0 40 40"><g fill="currentColor">` +
        [0, 72, 144, 216, 288]
            .map(a => `<path d="${lobe}" transform="rotate(${a} 20 20)"/>`)
            .join('') +
        `</g>${center}</svg>`;
    const petalShapes: string[] = [
        // full blossom with a pale stamen dot
        blossom(BLOSSOM_LOBE, '<circle cx="20" cy="20" r="2.2" fill="rgba(255,255,255,0.85)"/>'),
        // full blossom, rounder lobes, no center
        blossom(BLOSSOM_LOBE_ROUND, ''),
        // single wide petal (notched tip)
        `<svg viewBox="0 0 40 40"><path d="M20 37 C10.5 30.5 6.8 20.5 9.2 12.5 C11.2 6 16 3 18.7 5.6 C19.8 6.7 20 9.2 20 11.2 C20 9.2 20.2 6.7 21.3 5.6 C24 3 28.8 6 30.8 12.5 C33.2 20.5 29.5 30.5 20 37 Z" fill="currentColor"/></svg>`,
        // single narrow petal (notched tip)
        `<svg viewBox="0 0 40 40"><path d="M20 37 C14.3 30.6 11.8 21.4 13.1 13.6 C14.2 7 17 4 18.9 5.9 C19.7 6.8 20 9.3 20 11.4 C20 9.3 20.3 6.8 21.1 5.9 C23 4 25.8 7 26.9 13.6 C28.2 21.4 25.7 30.6 20 37 Z" fill="currentColor"/></svg>`,
        // single petal fluttering edge-on (asymmetric)
        `<svg viewBox="0 0 40 40"><path d="M23 35.5 C13 32 7.5 23.5 9.5 15 C11.2 8 16 4.2 19.3 6.4 C20.8 7.5 21.1 10 20.5 12.3 C21.6 10.3 23.6 8.9 25.6 9.8 C29.6 11.6 30.6 17.6 28.6 23.8 C26.9 29.2 25.2 32.8 23 35.5 Z" fill="currentColor"/></svg>`,
    ];

    const colors: string[] = [
        'rgba(255, 183, 197, 0.9)',
        'rgba(255, 145, 175, 0.85)',
        'rgba(255, 107, 157, 0.8)',
        'rgba(255, 192, 203, 0.9)',
        'rgba(255, 174, 201, 0.85)',
    ];

    const petalPool: HTMLDivElement[] = [];
    const activePetals: Set<HTMLDivElement> = new Set();
    const MAX_PETALS = 30;

    /** Per-petal physical state — integrated per frame by the simulation loop
     *  below (which owns transform + opacity; no CSS keyframes involved). */
    interface PetalPhysics {
        x: number; y: number;       // px, container space
        vx: number; vy: number;     // px/s
        angle: number;              // deg
        size: number;               // px
        life: number;               // s since spawn (drives the fade-in)
        flutterPhase: number;       // rad, de-syncs petals from each other
        flutterFreq: number;        // Hz — how fast this petal rocks
        flutterAmp: number;         // px/s² lateral rocking force
        terminal: number;           // px/s fall speed where gravity ⇄ drag balance
        spin: number;               // deg/s slow tumble bias
    }
    const physics = new WeakMap<HTMLDivElement, PetalPhysics>();

    function getPetal(): HTMLDivElement {
        let petal = petalPool.pop();
        if (!petal) {
            petal = document.createElement('div');
            petal.className = 'sakura-petal';
        }
        return petal;
    }

    function returnPetal(petal: HTMLDivElement): void {
        activePetals.delete(petal);
        petal.remove();
        petalPool.push(petal);
    }

    function createPetal(): void {
        if (activePetals.size >= MAX_PETALS) return;

        const petal = getPetal();
        activePetals.add(petal);

        const size = Math.random() * 15 + 10;
        const color = colors[Math.floor(Math.random() * colors.length)];
        const shape = petalShapes[Math.floor(Math.random() * petalShapes.length)];

        petal.innerHTML = shape;
        // position:absolute (not fixed) so the container's overflow:hidden
        // actually clips petals — fixed escapes any ancestor clip and would
        // push past the viewport, creating phantom horizontal scroll. The
        // simulation drives position via transform; left/top stay 0.
        petal.style.position = 'absolute';
        petal.style.width = `${size}px`;
        petal.style.height = `${size}px`;
        petal.style.left = '0';
        petal.style.top = '0';
        petal.style.color = color;
        petal.style.pointerEvents = 'none';
        petal.style.zIndex = '1';
        petal.style.opacity = '0';
        petal.style.willChange = 'transform, opacity';

        // Spawn above the viewport with a touch of initial drift; heavier
        // (larger) petals get a slightly higher terminal speed, like the real
        // thing. Lifetime is position-based — the sim recycles at the floor.
        physics.set(petal, {
            x: Math.random() * Math.max(0, window.innerWidth - size),
            y: -40 - Math.random() * 80,
            vx: (Math.random() - 0.5) * 24,
            vy: 10 + Math.random() * 20,
            angle: Math.random() * 360,
            size,
            life: 0,
            flutterPhase: Math.random() * Math.PI * 2,
            flutterFreq: 0.9 + Math.random() * 1.3,
            flutterAmp: 26 + Math.random() * 34,
            terminal: 30 + size * 1.7 + Math.random() * 16,
            spin: (Math.random() - 0.5) * 50,
        });

        // Capture container reference; if the element was removed from the DOM
        // after init (e.g. page swap), abort instead of throwing in setInterval.
        const target = document.getElementById('sakura-container');
        if (!target) {
            returnPetal(petal);
            return;
        }
        target.appendChild(petal);
    }

    // Gate the initial burst + interval on visibility so re-enabling sakura
    // while the window is hidden doesn't churn petals in the background — the
    // visibilityHandler below restarts the interval on the next show event.
    if (!document.hidden) {
        for (let i = 0; i < 15; i++) {
            setTimeout(createPetal, i * 300);
        }
        sakuraInterval = window.setInterval(createPetal, 1000);
    }

    // Pause animation when window is hidden to save CPU.
    const visibilityHandler = (): void => {
        if (document.hidden) {
            if (sakuraInterval !== null) {
                clearInterval(sakuraInterval);
                sakuraInterval = null;
            }
        } else if (sakuraInterval === null && sakuraEnabled) {
            sakuraInterval = window.setInterval(createPetal, 1000);
        }
    };
    document.addEventListener('visibilitychange', visibilityHandler);
    sakuraDisposers.push(() => document.removeEventListener('visibilitychange', visibilityHandler));

    // ---- Physics simulation -------------------------------------------------
    // Real falling-petal model, integrated per frame (semi-implicit Euler):
    //   · vertical — velocity relaxes toward each petal's TERMINAL speed (the
    //     gravity ⇄ air-drag balance); the flutter modulates that target, so
    //     petals visibly hesitate when they rock flat: the falling-leaf effect
    //   · horizontal — flutter rocking force + entrainment into a slow
    //     two-sine breeze + linear air drag
    //   · rotation — banks into lateral motion, rocks with the flutter, and
    //     carries a per-petal tumble bias
    //   · cursor — a radial force field (quadratic falloff) PLUS entrained air
    //     from the cursor's own velocity: flick the mouse and petals gust
    //     away, then drag settles them back into a gentle fall. All forces
    //     feed VELOCITY, so every reaction is a continuous curve.
    const V_RELAX = 2.1;            // 1/s vertical relaxation toward terminal
    const H_DRAG = 1.5;             // 1/s horizontal air drag
    const BREEZE_PULL = 0.55;       // 1/s entrainment into the breeze
    const CURSOR_RADIUS = 130;      // px
    const CURSOR_FORCE = 1150;      // px/s² at the cursor, quadratic falloff
    const CURSOR_WIND = 0.9;        // fraction of cursor velocity entrained

    let pointerX = -9999;
    let pointerY = -9999;
    let pointerVX = 0;
    let pointerVY = 0;
    let lastPointerT = 0;

    const pointerMoveHandler = (e: MouseEvent): void => {
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
    const pointerLeaveHandler = (): void => {
        pointerX = -9999;
        pointerY = -9999;
        pointerVX = 0;
        pointerVY = 0;
        lastPointerT = 0;
    };

    let simTime = 0;
    let lastFrame = performance.now();
    let rafId: number | null = requestAnimationFrame(function simTick(now: number) {
        rafId = requestAnimationFrame(simTick);
        let dt = (now - lastFrame) / 1000;
        lastFrame = now;
        if (dt <= 0) return;
        if (dt > 0.05) dt = 0.05; // clamp tab-switch / hidden-window spikes
        simTime += dt;

        // the cursor's gust decays between mouse events
        const gustDecay = Math.exp(-3 * dt);
        pointerVX *= gustDecay;
        pointerVY *= gustDecay;

        // slow two-sine breeze — smooth, never-quite-repeating lateral drift
        const breeze = 18 * Math.sin(simTime * 0.31) + 12 * Math.sin(simTime * 0.117 + 1.7);
        const floor = (container.clientHeight || window.innerHeight) + 60;
        const width = container.clientWidth || window.innerWidth;

        for (const petal of Array.from(activePetals)) {
            const p = physics.get(petal);
            if (!p) continue;
            p.life += dt;

            const flutterArg = simTime * p.flutterFreq * 2 * Math.PI + p.flutterPhase;
            const flutter = Math.sin(flutterArg);

            // lateral: rocking force + breeze entrainment
            let ax = flutter * p.flutterAmp + (breeze - p.vx) * BREEZE_PULL;
            let ay = 0;

            // cursor force field + entrained air
            if (pointerX > -999) {
                const dx = p.x + p.size / 2 - pointerX;
                const dy = p.y + p.size / 2 - pointerY;
                const dist = Math.hypot(dx, dy);
                if (dist < CURSOR_RADIUS && dist > 0.01) {
                    const fall = 1 - dist / CURSOR_RADIUS;
                    const push = CURSOR_FORCE * fall * fall;
                    ax += (dx / dist) * push + pointerVX * CURSOR_WIND * fall;
                    ay += (dy / dist) * push + pointerVY * CURSOR_WIND * fall;
                }
            }

            // integrate: horizontal drag; vertical relaxes toward a flutter-
            // modulated terminal speed (petals hesitate when rocking flat)
            p.vx += ax * dt;
            p.vx -= p.vx * H_DRAG * dt;
            const vyTarget = p.terminal * (0.82 + 0.28 * Math.cos(flutterArg * 2));
            p.vy += ay * dt + (vyTarget - p.vy) * V_RELAX * dt;

            p.x += p.vx * dt;
            p.y += p.vy * dt;

            // banking into motion + flutter rock + tumble bias
            p.angle += (p.spin + flutter * 55 + p.vx * 0.55) * dt;

            // blown off one side → drift in from the other
            if (p.x < -60) p.x = width + 20;
            else if (p.x > width + 60) p.x = -20;

            // recycle at the floor
            if (p.y > floor) {
                returnPetal(petal);
                continue;
            }

            const fadeIn = Math.min(1, p.life * 1.6);
            petal.style.opacity = (0.92 * fadeIn).toFixed(3);
            petal.style.transform =
                `translate3d(${p.x.toFixed(2)}px, ${p.y.toFixed(2)}px, 0) rotate(${(p.angle % 360).toFixed(2)}deg)`;
        }
    });

    document.addEventListener('mousemove', pointerMoveHandler, { passive: true });
    document.addEventListener('mouseleave', pointerLeaveHandler);
    sakuraDisposers.push(() => {
        document.removeEventListener('mousemove', pointerMoveHandler);
        document.removeEventListener('mouseleave', pointerLeaveHandler);
        if (rafId !== null) cancelAnimationFrame(rafId);
        rafId = null;
    });
}

// ============================================================================
// Navigation
// ============================================================================

function initNavigation(): void {
    document.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', () => {
            const page = (item as HTMLElement).dataset.page;
            if (page) switchPage(page);
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
        const value = parseInt((e.target as HTMLSelectElement).value);
        updateSetting('refreshInterval', value);
        showToast(`Refresh interval: ${value / 1000}s`, { type: 'info' });
    });
    
    document.getElementById('notifications-toggle')?.addEventListener('change', (e) => {
        updateSetting('notifications', (e.target as HTMLInputElement).checked);
    });

    document.getElementById('sakura-toggle')?.addEventListener('change', (e) => {
        const enabled = (e.target as HTMLInputElement).checked;
        updateSetting('sakuraEnabled', enabled);
        setSakuraEnabled(enabled);
    });

    // Density toggle (CONTRACT): compact mode tightens card/section padding via
    // <html data-density="compact"> (CSS already maps that to --density:.7).
    document.getElementById('setting-density')?.addEventListener('change', (e) => {
        const compact = (e.target as HTMLInputElement).checked;
        updateSetting('densityCompact', compact);
        applyDensity(compact);
    });

    document.getElementById('sound-toggle')?.addEventListener('change', (e) => {
        const enabled = (e.target as HTMLInputElement).checked;
        updateSetting('soundEnabled', enabled);
        if (enabled) showToast('Click sounds enabled', { type: 'info', duration: 2000 });
    });

    document.getElementById('haptic-toggle')?.addEventListener('change', (e) => {
        const enabled = (e.target as HTMLInputElement).checked;
        updateSetting('hapticEnabled', enabled);
        if (enabled) showToast('Haptic feedback enabled', { type: 'info', duration: 2000 });
    });

    document.getElementById('telemetry-toggle')?.addEventListener('change', async (e) => {
        const enabled = (e.target as HTMLInputElement).checked;
        try {
            await invoke('set_telemetry_enabled', { enabled });
            showToast(
                enabled
                    ? 'Crash reports enabled (restart bot to take effect)'
                    : 'Crash reports disabled (restart bot to take effect)',
                { type: 'info', duration: 3000 },
            );
        } catch (err) {
            console.error('set_telemetry_enabled failed:', err);
            showToast('Failed to update telemetry preference', { type: 'error' });
        }
    });

    // User name input handler
    document.getElementById('user-name-input')?.addEventListener('input', (e) => {
        const value = (e.target as HTMLInputElement).value.trim();
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
        const file = (e.target as HTMLInputElement).files?.[0];
        if (file) handleAvatarUpload(file, 'user');
    });
    
    document.getElementById('btn-remove-avatar')?.addEventListener('click', () => {
        removeAvatar('user');
    });
    
    // AI Avatar upload handlers
    document.getElementById('btn-change-ai-avatar')?.addEventListener('click', () => {
        document.getElementById('ai-avatar-input')?.click();
    });
    
    document.getElementById('ai-avatar-input')?.addEventListener('change', (e) => {
        const file = (e.target as HTMLInputElement).files?.[0];
        if (file) handleAvatarUpload(file, 'ai');
    });
    
    document.getElementById('btn-remove-ai-avatar')?.addEventListener('click', () => {
        removeAvatar('ai');
    });
    
    // Creator toggle handler
    document.getElementById('creator-toggle')?.addEventListener('change', (e) => {
        settings.isCreator = (e.target as HTMLInputElement).checked;
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
function initHistoryManager(): void {
    historyManager = new HistoryManager({
        send: (data) => chatManager?.send(data) ?? false,
        isConnected: () => chatManager?.connected ?? false,
        connect: () => chatManager?.connect(),
    });
    historyManager.init();
    if (chatManager) chatManager.historyManager = historyManager;
}

function switchPage(page: string): void {
    // Resolve stale aliases (config→settings) then reject anything unknown, so
    // a bad page id can't blank the UI by deactivating every .page section.
    const resolved = resolvePage(page);
    if (resolved === null) return;
    page = resolved;
    currentPage = page;

    document.querySelectorAll('.nav-item').forEach(item => {
        const itemPage = (item as HTMLElement).dataset.page;
        const isActive = itemPage === page;
        item.classList.toggle('active', isActive);
        // a11y: expose the selected page to assistive tech, not just visually.
        if (isActive) {
            item.setAttribute('aria-current', 'page');
        } else {
            item.removeAttribute('aria-current');
        }
    });

    document.querySelectorAll('.page').forEach(p => {
        p.classList.toggle('active', p.id === `page-${page}`);
    });

    if (page === 'logs') {
        loadLogs();
        startLogsRefresh();
    } else {
        stopLogsRefresh();
    }

    if (page === 'database') loadDbStats();
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
        } else {
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

function startRefreshLoop(): void {
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

function stopRefreshLoop(): void {
    if (refreshInterval !== null) {
        clearInterval(refreshInterval);
        refreshInterval = null;
    }
}

function restartRefreshLoop(): void {
    startRefreshLoop();
}

// Debounce helper for performance
export function debounce(fn: () => void, key: string, delay: number): () => void {
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
function batchDOMUpdate(updates: (() => void)[]): void {
    requestAnimationFrame(() => {
        updates.forEach(update => update());
    });
}

async function updateStatus(): Promise<void> {
    // Check cache first
    const cachedStatus = dataCache.get<BotStatus>('status');
    const cachedDbStats = dataCache.get<DbStats>('dbStats');

    try {
        // Parallel fetch, settled independently: a transient rejection on one
        // endpoint (IPC/Mutex contention) must not stall the other half for a
        // whole tick. Fall back to the last cached value for a rejected half.
        const [statusRes, dbStatsRes] = await Promise.allSettled([
            cachedStatus ?? invoke<BotStatus>('get_status'),
            cachedDbStats ?? invoke<DbStats>('get_db_stats')
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
        } else if (status) {
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
        if (!status) return;

        // Cache status. The TTL MUST stay below the refresh interval — a fixed
        // 1500ms cache meant that at a 1s refresh the in-between tick kept
        // hitting a still-valid cache, so fresh status (uptime, memory) only
        // arrived every ~2s and uptime jumped 0→2→4→6 instead of ticking by 1.
        // Tie it to the interval (half, min 250ms) so every tick gets fresh data
        // while still deduping a manual Ctrl+R that coincides with a tick.
        const statusTtl = Math.max(250, Math.floor(settings.refreshInterval / 2));
        if (!cachedStatus) dataCache.set('status', status, statusTtl);
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
                dataCache.set('dbStats', dbStats, 3000);
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

    } catch (error) {
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
async function populatePathsCard(): Promise<void> {
    if (pathsCardPopulated) return;
    const botScript = document.getElementById('info-bot-script');
    const logFile = document.getElementById('info-log-file');
    const database = document.getElementById('info-database');
    if (!botScript && !logFile && !database) return;
    try {
        const [base, logsDir, dataDir] = await Promise.all([
            invoke<string>('get_base_path'),
            invoke<string>('get_logs_path'),
            invoke<string>('get_data_path'),
        ]);
        if (botScript && base) botScript.textContent = `${base}\\bot.py`;
        if (logFile && logsDir) logFile.textContent = `${logsDir}\\bot.log`;
        if (database && dataDir) database.textContent = `${dataDir}\\bot_database.db`;
        pathsCardPopulated = true;
    } catch (error) {
        // Backend unreachable — keep the static defaults and retry next visit.
        console.warn('Failed to resolve paths card:', error);
    }
}

function noteStatusTick(ok: boolean): void {
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
function setDisconnectedCue(show: boolean): void {
    const existing = document.getElementById('ipc-disconnected-banner');
    if (show) {
        if (existing) return;
        const banner = document.createElement('div');
        banner.id = 'ipc-disconnected-banner';
        banner.className = 'ipc-disconnected-banner';
        banner.setAttribute('role', 'alert');
        banner.setAttribute('aria-live', 'assertive');
        banner.innerHTML =
            '<svg class="ic" aria-hidden="true"><use href="#i-alert"/></svg>' +
            '<span>Disconnected — can\'t reach the dashboard backend. Retrying…</span>';
        document.body.appendChild(banner);
    } else if (existing) {
        existing.remove();
    }
}

function updateStatusBadge(status: BotStatus): void {
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

function updateStatusText(status: BotStatus): void {
    const botStatusText = document.getElementById('bot-status-text');
    if (botStatusText) {
        botStatusText.textContent = status.is_running ? 'Status: Online' : 'Status: Offline';
    }
}

function updateButtons(status: BotStatus): void {
    // Don't override button states while a bot command is in progress
    if (botCommandInProgress) return;

    const btnStart = document.getElementById('btn-start') as HTMLButtonElement | null;
    const btnDev = document.getElementById('btn-dev') as HTMLButtonElement | null;
    const btnStop = document.getElementById('btn-stop') as HTMLButtonElement | null;
    const btnRestart = document.getElementById('btn-restart') as HTMLButtonElement | null;

    if (btnStart) btnStart.disabled = status.is_running;
    if (btnDev) btnDev.disabled = status.is_running;
    if (btnStop) btnStop.disabled = !status.is_running;
    if (btnRestart) btnRestart.disabled = !status.is_running;
}

// dbStats is nullable: get_db_stats can reject (SQLITE_BUSY / uninitialized DB)
// while get_status keeps succeeding, and the caller now renders the status-only
// fields regardless. Skip the message/channel counts when it's absent rather
// than crashing on `.total_messages` of null.
function updateStats(status: BotStatus, dbStats: DbStats | null): void {
    // Strings that don't animate naturally (uptime, mode) — just set textContent.
    const stringUpdates: [string, string][] = [
        ['stat-uptime', status.uptime],
        ['stat-mode', status.mode],
    ];
    stringUpdates.forEach(([id, value]) => {
        const el = document.getElementById(id);
        if (el) {
            setSkeleton(el, false);
            if (el.textContent !== value) el.textContent = value;
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

function setBotControlBusy(busy: boolean): void {
    botCommandInProgress = busy;
    const btnStart = document.getElementById('btn-start') as HTMLButtonElement | null;
    const btnDev = document.getElementById('btn-dev') as HTMLButtonElement | null;
    const btnStop = document.getElementById('btn-stop') as HTMLButtonElement | null;
    const btnRestart = document.getElementById('btn-restart') as HTMLButtonElement | null;

    if (busy) {
        if (btnStart) btnStart.disabled = true;
        if (btnDev) btnDev.disabled = true;
        if (btnStop) btnStop.disabled = true;
        if (btnRestart) btnRestart.disabled = true;
    }
}

async function startBot(): Promise<void> {
    if (botCommandInProgress) return;
    try {
        setBotControlBusy(true);
        showToast('Starting bot...', { type: 'info', duration: 10000 });
        // Backend now returns immediately after Command::spawn (~50ms) instead
        // of holding the lock for up to 10s waiting on bot.pid. We pick up the
        // Running transition ourselves with a tight 200ms poll below — total
        // perceived latency on the happy path drops from ~1s to ~250ms.
        await invoke<string>('start_bot');
        await waitForStart();
    } catch (error) {
        showToast(String(error), { type: 'error' });
    } finally {
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
async function waitForStart(
    intervalMs = 250,
    softNoticeMs = 12000,
    handoffMs = 60000,
): Promise<void> {
    const startTime = performance.now();
    let softNoticeShown = false;
    while (performance.now() - startTime < handoffMs) {
        await new Promise((r) => setTimeout(r, intervalMs));
        let progress: StartProgress;
        try {
            progress = await invoke<StartProgress>('get_start_progress');
        } catch {
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
                const codeSuffix =
                    progress.code === null ? '' : ` (exit code ${progress.code})`;
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

async function stopBot(): Promise<void> {
    if (botCommandInProgress) return;
    try {
        setBotControlBusy(true);
        showToast('Stopping bot...', { type: 'info', duration: 5000 });
        const result = await invoke<string>('stop_bot');
        showToast(result, { type: 'success' });
    } catch (error) {
        showToast(String(error), { type: 'error' });
    } finally {
        // In finally (not the try) so a failed stop still re-enables the four
        // control buttons via updateStatus()->updateButtons(); otherwise they
        // stay disabled until the next periodic refresh tick. Mirrors startBot.
        setBotControlBusy(false);
        dataCache.invalidate('status');
        updateStatus();
    }
}

async function restartBot(): Promise<void> {
    if (botCommandInProgress) return;
    try {
        setBotControlBusy(true);
        showToast('Restarting bot...', { type: 'info', duration: 12000 });
        const result = await invoke<string>('restart_bot');
        showToast(result, { type: 'success' });
    } catch (error) {
        showToast(String(error), { type: 'error' });
    } finally {
        // In finally so a failed restart re-enables the control buttons too.
        setBotControlBusy(false);
        dataCache.invalidate('status');
        updateStatus();
    }
}

async function startDevBot(): Promise<void> {
    if (botCommandInProgress) return;
    try {
        setBotControlBusy(true);
        showToast('Starting dev mode...', { type: 'info', duration: 8000 });
        const result = await invoke<string>('start_dev_bot');
        showToast(result, { type: 'success' });
    } catch (error) {
        showToast(String(error), { type: 'error' });
    } finally {
        // In finally so a failed dev-start re-enables the control buttons too.
        setBotControlBusy(false);
        dataCache.invalidate('status');
        updateStatus();
    }
}

// ============================================================================
// Logs - Optimized Real-time Streaming
// ============================================================================

let lastLogFilter: string | null = null;

async function loadLogs(): Promise<void> {
    try {
        const logs = await invoke<string[]>('get_logs', { count: 200 });
        // Fetch succeeded — arm the failure toast for the next streak.
        logsLoadFailedToastShown = false;
        const container = document.getElementById('log-content');
        const filterElement = document.getElementById('log-filter') as HTMLSelectElement | null;
        const filter = filterElement?.value || 'all';

        if (!container) return;

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

        // Continuation lines (traceback bodies, wrapped messages) carry no
        // level token of their own — they belong to the last tagged entry.
        // Carrying that level forward keeps a filtered ERROR view showing its
        // traceback instead of dropping the most useful part of the error.
        let carriedLevelToken: string | undefined;
        logs.forEach((line: string) => {
            // Anchor the level to a standalone token (the structured log-level
            // column) rather than a whole-line substring match, so message text
            // that incidentally contains a level word (e.g. an INFO line "no
            // ERROR found") is neither mis-colored nor wrongly selected by the
            // level filter. The first token wins, matching the column order.
            const ownLevelToken = /\b(ERROR|WARNING|DEBUG|INFO)\b/.exec(line)?.[1];
            if (ownLevelToken) carriedLevelToken = ownLevelToken;
            const levelToken = ownLevelToken ?? carriedLevelToken;
            const level = levelToken ? levelToken.toLowerCase() : 'info';

            if (filter === 'all' || levelToken === filter) {
                const div = document.createElement('div');
                div.className = `log-line ${level}`;
                div.textContent = line;
                fragment.appendChild(div);
            }
        });

        container.innerHTML = '';
        container.appendChild(fragment);

        if (!container.firstChild) {
            // Iconographic empty state (SHARED CONTRACT #2): fixed, trusted
            // markup — no user content, no inline style. Classes only; the
            // .empty-state / .ic sizing lives in orbital.css.
            container.innerHTML =
                '<div class="empty-state">' +
                '<svg class="ic" aria-hidden="true"><use href="#i-logs"/></svg>' +
                '<h3>No logs found</h3>' +
                '<p>Logs will appear here once the bot starts running.</p>' +
                '</div>';
        }

        // Auto-scroll on new logs OR when the filter changes — switching from
        // ERROR to ALL with auto-scroll on previously left the view on a
        // mid-scroll position from the prior filter instead of snapping back
        // to the bottom of the rebuilt list.
        if (logsAutoScrollEnabled && (hasNewLogs || filterChanged)) {
            container.scrollTop = container.scrollHeight;
        }
    } catch (error) {
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

function startLogsRefresh(): void {
    if (logsRefreshInterval) {
        clearInterval(logsRefreshInterval);
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

function stopLogsRefresh(): void {
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
    } else {
        // Restart the status loop unconditionally (it drives every page's
        // header badge), and the logs poll only when the logs page is open.
        startRefreshLoop();
        if (currentPage === 'logs') {
            startLogsRefresh();
        }
    }
});

function applyAutoScrollButtonState(): void {
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
}

function toggleAutoScroll(): void {
    logsAutoScrollEnabled = !logsAutoScrollEnabled;
    // Persist the pause/resume preference so it survives a reload.
    settings.autoScroll = logsAutoScrollEnabled;
    saveSettings();
    applyAutoScrollButtonState();
    showToast(`Auto-scroll ${logsAutoScrollEnabled ? 'enabled' : 'disabled'}`, { type: 'info', duration: 1500 });
}

async function clearLogs(): Promise<void> {
    // Pause the 1s logs poller so an in-flight loadLogs() tick cannot
    // re-read the not-yet-truncated backend tail and repopulate stale
    // logs while the backend clear is in flight.
    stopLogsRefresh();
    try {
        const result = await invoke('clear_logs');
        const container = document.getElementById('log-content');
        if (container) container.innerHTML = '';
        lastLogSignature = null;
        showToast(String(result), { type: 'success', duration: 1500 });
    } catch (err) {
        showToast('Failed to clear logs: ' + err, { type: 'error' });
    } finally {
        if (currentPage === 'logs') startLogsRefresh();
    }
}

// ============================================================================
// Database
// ============================================================================

async function loadDbStats(): Promise<void> {
    try {
        const stats = await invoke<DbStats>('get_db_stats');
        // Same defensive guard as updateStatus: backend can legitimately
        // return null before the DB is initialized; treat as "no data yet"
        // and let the next poll fill it in instead of crashing the page.
        if (!stats) return;

        batchDOMUpdate([
            () => {
                const dbMessages = document.getElementById('db-messages');
                const dbChannels = document.getElementById('db-channels');
                const dbEntities = document.getElementById('db-entities');
                const dbRag = document.getElementById('db-rag');

                // animateNumber handles reduced-motion fallback internally,
                // and setSkeleton clears any loading placeholder the first
                // time real data arrives.
                if (dbMessages) { setSkeleton(dbMessages, false); animateNumber(dbMessages, stats.total_messages); }
                if (dbChannels) { setSkeleton(dbChannels, false); animateNumber(dbChannels, stats.active_channels); }
                if (dbEntities) { setSkeleton(dbEntities, false); animateNumber(dbEntities, stats.total_entities); }
                if (dbRag)      { setSkeleton(dbRag, false);      animateNumber(dbRag, stats.rag_memories); }
            }
        ]);

        // Load channels and users in parallel. Coerce nulls (which the
        // backend can return before the bot has indexed anything) to empty
        // arrays so the .length / .forEach calls below don't crash and
        // leave the UI in a half-rendered state.
        const [channelsRaw, usersRaw] = await Promise.all([
            invoke<ChannelInfo[]>('get_recent_channels', { limit: 10 }),
            invoke<UserInfo[]>('get_top_users', { limit: 10 })
        ]);
        const channels = channelsRaw ?? [];
        const users = usersRaw ?? [];

        const channelsList = document.getElementById('channels-list');
        if (channelsList) {
            if (channels.length === 0) {
                channelsList.innerHTML = '<p class="no-data">No channels found.</p>';
                updateChannelSelectionUI();
            } else {
                channelsList.innerHTML = '';
                channels.forEach((ch: ChannelInfo) => {
                    const item = document.createElement('div');
                    item.className = 'data-item';
                    item.dataset.channelId = String(ch.channel_id);

                    const leftDiv = document.createElement('div');
                    leftDiv.className = 'data-item-left';

                    const checkbox = document.createElement('input');
                    checkbox.type = 'checkbox';
                    checkbox.className = 'data-item-checkbox';
                    checkbox.dataset.channelId = String(ch.channel_id);
                    checkbox.addEventListener('change', () => {
                        item.classList.toggle('selected', checkbox.checked);
                        updateChannelSelectionUI();
                    });

                    const idSpan = document.createElement('span');
                    idSpan.className = 'data-item-id';
                    idSpan.textContent = String(ch.channel_id);

                    leftDiv.appendChild(checkbox);
                    leftDiv.appendChild(idSpan);

                    const valSpan = document.createElement('span');
                    valSpan.className = 'data-item-value';
                    valSpan.textContent = `${ch.message_count.toLocaleString()} messages`;

                    item.appendChild(leftDiv);
                    item.appendChild(valSpan);

                    // Click row to toggle checkbox
                    item.addEventListener('click', (e) => {
                        if ((e.target as HTMLElement).tagName !== 'INPUT') {
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
            } else {
                usersList.innerHTML = '';
                users.forEach((u: UserInfo) => {
                    const item = document.createElement('div');
                    item.className = 'data-item';
                    const idSpan = document.createElement('span');
                    idSpan.className = 'data-item-id';
                    idSpan.textContent = String(u.user_id);
                    const valSpan = document.createElement('span');
                    valSpan.className = 'data-item-value';
                    valSpan.textContent = `${u.message_count.toLocaleString()} messages`;
                    item.appendChild(idSpan);
                    item.appendChild(valSpan);
                    usersList.appendChild(item);
                });
            }
        }

    } catch (error) {
        console.error('Failed to load DB stats:', error);
        showToast('Failed to load database stats', { type: 'error' });
    }
}

async function clearHistory(): Promise<void> {
    const confirmed = await showConfirmDialog('This will permanently delete ALL chat history. Continue?');
    if (!confirmed) {
        return;
    }

    try {
        const count = await invoke<number>('clear_history');
        showToast(`Deleted ${count.toLocaleString()} messages`, { type: 'success' });
        dataCache.invalidate('dbStats');
        loadDbStats();
    } catch (error) {
        showToast(String(error), { type: 'error' });
    }
}

function getSelectedChannelIds(): string[] {
    const checkboxes = document.querySelectorAll<HTMLInputElement>('.data-item-checkbox:checked');
    return Array.from(checkboxes).map(cb => cb.dataset.channelId!).filter(Boolean);
}

function updateChannelSelectionUI(): void {
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

async function deleteSelectedChannels(): Promise<void> {
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
        const count = await invoke<number>('delete_channels_history', { channelIds: channelIds });
        showToast(`Deleted ${count.toLocaleString()} messages from ${channelIds.length} channel(s)`, { type: 'success' });
        dataCache.invalidate('dbStats');
        loadDbStats();
    } catch (error) {
        showToast(String(error), { type: 'error' });
    }
}

// ============================================================================
// Settings UI
// ============================================================================

function loadSettingsUI(): void {
    const refreshSelect = document.getElementById('refresh-interval') as HTMLSelectElement | null;
    if (refreshSelect) {
        refreshSelect.value = settings.refreshInterval.toString();
    }
    
    const notificationsToggle = document.getElementById('notifications-toggle') as HTMLInputElement | null;
    if (notificationsToggle) {
        notificationsToggle.checked = settings.notifications;
    }

    const sakuraToggleEl = document.getElementById('sakura-toggle') as HTMLInputElement | null;
    if (sakuraToggleEl) {
        sakuraToggleEl.checked = settings.sakuraEnabled !== false;
    }

    const densityToggleEl = document.getElementById('setting-density') as HTMLInputElement | null;
    if (densityToggleEl) {
        densityToggleEl.checked = settings.densityCompact === true;
    }

    const soundToggleEl = document.getElementById('sound-toggle') as HTMLInputElement | null;
    if (soundToggleEl) {
        soundToggleEl.checked = settings.soundEnabled === true;
    }

    const hapticToggleEl = document.getElementById('haptic-toggle') as HTMLInputElement | null;
    if (hapticToggleEl) {
        hapticToggleEl.checked = settings.hapticEnabled === true;
    }

    // Telemetry toggle is stored outside localStorage — it's a file on disk
    // so the Python bot can read the same source of truth. Fetch the current
    // state from the Rust side.
    const telemetryToggleEl = document.getElementById('telemetry-toggle') as HTMLInputElement | null;
    if (telemetryToggleEl) {
        invoke<boolean>('get_telemetry_enabled')
            .then((enabled) => { telemetryToggleEl.checked = enabled; })
            .catch(() => { /* default stays checked */ });
    }

    const userNameInput = document.getElementById('user-name-input') as HTMLInputElement | null;
    if (userNameInput) {
        userNameInput.value = settings.userName === 'You' ? '' : settings.userName;
    }
    
    // Load AI + user avatar previews via the shared tri-state helper. It uses
    // the transparent-gif placeholder internally so a missing avatar never
    // flashes the browser's broken-image glyph.
    setAvatarPreview('ai', settings.aiAvatar);
    setAvatarPreview('user', settings.userAvatar);

    // Load creator checkbox
    const creatorCheckbox = document.getElementById('creator-toggle') as HTMLInputElement | null;
    if (creatorCheckbox) {
        creatorCheckbox.checked = settings.isCreator;
    }
    
    // Load profile from server
    if (chatManager?.connected) {
        chatManager.send({ type: 'get_profile' });
    }
}

// Track which avatar we're editing
let currentAvatarTarget: 'user' | 'ai' = 'user';

// 1x1 transparent gif — used instead of an empty src so the browser doesn't
// flash its broken-image glyph even while the <img> is hidden by class.
const BLANK_AVATAR_GIF =
    'data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==';

// Single source of truth for the user/AI avatar preview tri-state (image,
// placeholder, remove button). Replaces the three near-identical inline blocks
// that lived in loadSettingsUI / saveCroppedAvatar / removeAvatar. Pass a data
// URL (or http(s) avatar URL) to show it; pass '' to clear back to placeholder.
function setAvatarPreview(target: 'user' | 'ai', dataUrl: string): void {
    const ids =
        target === 'ai'
            ? { img: 'ai-avatar-image', preview: '#ai-avatar-preview', remove: 'btn-remove-ai-avatar' }
            : { img: 'avatar-image', preview: '#avatar-preview', remove: 'btn-remove-avatar' };

    const avatarImage = document.getElementById(ids.img) as HTMLImageElement | null;
    const placeholder = document.querySelector(`${ids.preview} .avatar-placeholder`) as HTMLElement | null;
    const removeBtn = document.getElementById(ids.remove) as HTMLElement | null;

    const hasAvatar = isSafeAvatarUrl(dataUrl);
    if (avatarImage) {
        avatarImage.src = hasAvatar ? dataUrl : BLANK_AVATAR_GIF;
        avatarImage.classList.toggle('visible', hasAvatar);
    }
    if (placeholder) placeholder.classList.toggle('hidden', hasAvatar);
    if (removeBtn) removeBtn.classList.toggle('hidden', !hasAvatar);
}

function handleAvatarUpload(file: File, target: 'user' | 'ai' = 'user'): void {
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
        const dataUrl = e.target?.result as string;
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
let boundOnDrag: ((e: MouseEvent) => void) | null = null;
let boundOnDragTouch: ((e: TouchEvent) => void) | null = null;
let boundEndDrag: (() => void) | null = null;
let cropEscBound = false;  // ESC-to-close handler is bound once for the page lifetime
let boundStartDrag: ((e: MouseEvent) => void) | null = null;
let boundStartDragTouch: ((e: TouchEvent) => void) | null = null;
let cropListenersAttached = false;

function openAvatarCropModal(imageUrl: string): void {
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
    const cropImage = document.getElementById('crop-image') as HTMLImageElement;
    const zoomSlider = document.getElementById('crop-zoom') as HTMLInputElement;
    
    if (!modal || !cropImage || !zoomSlider) return;
    
    // Load image to get dimensions
    cropImage.onload = () => {
        const cropArea = document.getElementById('crop-area');
        if (!cropArea) return;

        const areaSize = 280;
        // Guard against a broken image (naturalWidth/Height === 0). Without
        // this, ``areaSize / 0`` produces Infinity, which then poisons every
        // subsequent crop calculation with NaN and silently saves a blank
        // canvas.
        if (cropImage.naturalWidth <= 0 || cropImage.naturalHeight <= 0) {
            showToast('ไม่สามารถโหลดรูปภาพได้', { type: 'error' });
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

function setupCropEventListeners(): void {
    const cropArea = document.getElementById('crop-area');
    const zoomSlider = document.getElementById('crop-zoom') as HTMLInputElement;
    const saveBtn = document.getElementById('btn-crop-save');
    const cancelBtn = document.getElementById('btn-crop-cancel');
    const closeBtn = document.getElementById('avatar-crop-close');
    const modal = document.getElementById('avatar-crop-modal');
    
    if (!cropArea || !zoomSlider || !saveBtn || !cancelBtn || !closeBtn || !modal) return;

    // Detach previously-bound handlers from the live elements rather than
    // cloning the node (cloning silently drops every listener that was
    // attached BEFORE this function ran, which leaks the document-level
    // mousemove/touchmove/mouseup/touchend handlers from prior opens).
    if (cropListenersAttached) {
        if (boundStartDrag) cropArea.removeEventListener('mousedown', boundStartDrag);
        if (boundStartDragTouch) cropArea.removeEventListener('touchstart', boundStartDragTouch);
        if (boundOnDrag) document.removeEventListener('mousemove', boundOnDrag);
        if (boundOnDragTouch) document.removeEventListener('touchmove', boundOnDragTouch);
        if (boundEndDrag) {
            document.removeEventListener('mouseup', boundEndDrag);
            document.removeEventListener('touchend', boundEndDrag);
        }
    }

    // Create bound functions for proper cleanup
    boundStartDrag = startDrag;
    boundStartDragTouch = startDragTouch;
    boundOnDrag = onDrag;
    boundOnDragTouch = onDragTouch;
    boundEndDrag = endDrag;

    // Mouse/touch drag
    cropArea.addEventListener('mousedown', boundStartDrag);
    cropArea.addEventListener('touchstart', boundStartDragTouch, { passive: false });
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
        modal.querySelector<HTMLElement>('[data-close-avatar-crop]')?.addEventListener('click', closeCropModal);
    }
    // Fallback: clicking the modal element itself (outside both content + overlay)
    // also closes — keeps backwards compat with the previous click-target check.
    modal.onclick = (e) => {
        if (e.target === modal) closeCropModal();
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
        document.addEventListener('keydown', (e: KeyboardEvent) => {
            if (e.key !== 'Escape') return;
            const m = document.getElementById('avatar-crop-modal');
            if (m && m.classList.contains('active')) closeCropModal();
        });
    }
}

function startDrag(e: MouseEvent): void {
    cropState.isDragging = true;
    cropState.startX = e.clientX - cropState.offsetX;
    cropState.startY = e.clientY - cropState.offsetY;
}

function startDragTouch(e: TouchEvent): void {
    if (!e.touches || e.touches.length === 0) return;
    e.preventDefault();
    cropState.isDragging = true;
    const touch = e.touches[0];
    cropState.startX = touch.clientX - cropState.offsetX;
    cropState.startY = touch.clientY - cropState.offsetY;
}

function onDrag(e: MouseEvent): void {
    if (!cropState.isDragging) return;
    cropState.offsetX = e.clientX - cropState.startX;
    cropState.offsetY = e.clientY - cropState.startY;
    updateCropPreview();
}

function onDragTouch(e: TouchEvent): void {
    if (!cropState.isDragging) return;
    if (!e.touches || e.touches.length === 0) return;
    e.preventDefault();
    const touch = e.touches[0];
    cropState.offsetX = touch.clientX - cropState.startX;
    cropState.offsetY = touch.clientY - cropState.startY;
    updateCropPreview();
}

function endDrag(): void {
    cropState.isDragging = false;
}

function updateCropPreview(): void {
    const cropImage = document.getElementById('crop-image') as HTMLImageElement;
    if (!cropImage) return;
    
    const scale = cropState.zoom / 100;
    const width = cropState.imgWidth * scale;
    const height = cropState.imgHeight * scale;
    
    cropImage.style.width = `${width}px`;
    cropImage.style.height = `${height}px`;
    cropImage.style.left = `${cropState.offsetX}px`;
    cropImage.style.top = `${cropState.offsetY}px`;
}

function saveCroppedAvatar(): void {
    const cropImage = document.getElementById('crop-image') as HTMLImageElement;
    if (!cropImage) return;

    // Guard the not-yet-loaded state: cropState.imgWidth/imgHeight stay 0 until
    // cropImage.onload runs. Saving before then divides by 0, making
    // srcX/srcY/srcSize NaN, so drawImage is a no-op and a blank canvas would be
    // persisted as the avatar with no error.
    if (
        !cropState.imgWidth ||
        !cropState.imgHeight ||
        cropImage.naturalWidth <= 0 ||
        cropImage.naturalHeight <= 0
    ) {
        showToast('รูปภาพยังโหลดไม่เสร็จ กรุณาลองอีกครั้ง', { type: 'error' });
        return;
    }

    // Create canvas to crop the circular area
    const canvas = document.createElement('canvas');
    const size = 200; // Output size
    canvas.width = size;
    canvas.height = size;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    
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
    } else {
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

function closeCropModal(): void {
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
    if (cropArea && boundStartDrag) cropArea.removeEventListener('mousedown', boundStartDrag);
    if (cropArea && boundStartDragTouch) cropArea.removeEventListener('touchstart', boundStartDragTouch);
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
}

function removeAvatar(target: 'user' | 'ai' = 'user'): void {
    if (target === 'ai') {
        settings.aiAvatar = '';
        saveSettings();
        setAvatarPreview('ai', '');
        // Keep the chat page in sync (see saveCroppedAvatar).
        updateAiAvatars();
        showToast('AI Avatar removed', { type: 'info' });
    } else {
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

function saveProfileToAI(): void {
    // Empty-name fallback must match the input handler + settings default
    // ('You') — a divergent 'User' here silently flipped settings.userName
    // depending on which code path ran last.
    const displayName = (document.getElementById('user-name-input') as HTMLInputElement)?.value?.trim() || 'You';
    const bio = (document.getElementById('user-bio-input') as HTMLTextAreaElement)?.value?.trim() || '';
    const preferences = (document.getElementById('user-preferences-input') as HTMLTextAreaElement)?.value?.trim() || '';
    const isCreator = (document.getElementById('creator-toggle') as HTMLInputElement)?.checked || false;

    if (chatManager?.connected) {
        chatManager.send({
            type: 'save_profile',
            profile: { display_name: displayName, bio, preferences, is_creator: isCreator }
        });

        // Also update local settings
        settings.userName = displayName;
        settings.isCreator = isCreator;
        saveSettings();
    } else {
        showToast('Not connected to AI server', { type: 'error' });
    }
}

// ============================================================================
// Helpers
// ============================================================================

async function openFolder(type: string): Promise<void> {
    let path: string;
    
    try {
        if (type === 'logs') {
            path = await invoke<string>('get_logs_path');
        } else if (type === 'data') {
            path = await invoke<string>('get_data_path');
        } else {
            showToast('Unknown folder type', { type: 'error' });
            return;
        }

        await invoke('open_folder', { path });
    } catch (error) {
        showToast(`Failed to open folder: ${error}`, { type: 'error' });
    }
}

function loadAllData(): void {
    dataCache.clear();
    updateStatus();
    loadLogs();
    loadDbStats();
}
// ============================================================================
// API Failover UI
// ============================================================================

let apiFailoverReadinessRequested = false;

function initApiFailoverUI(): void {
    // Listen for failover status updates from chat-manager. The detail payloads
    // are typed (ApiFailoverStatusDetail / ApiHealthResultDetail) and shape-
    // checked before use, so a malformed/empty frame can't throw on a bad
    // destructure — it's simply ignored.
    window.addEventListener('api-failover-status', ((e: CustomEvent<ApiFailoverStatusDetail>) => {
        const detail = e.detail;
        if (!detail || typeof detail !== 'object') return;
        renderApiFailoverUI(detail);
    }) as EventListener);

    window.addEventListener('api-health-result', ((e: CustomEvent<ApiHealthResultDetail>) => {
        const detail = e.detail;
        if (!detail || typeof detail !== 'object' || !Array.isArray(detail.results)) return;
        renderHealthCheckResults(detail.results);
    }) as EventListener);

    // Health check button
    document.getElementById('btn-health-check')?.addEventListener('click', () => {
        if (chatManager?.connected) {
            chatManager.send({ type: 'health_check_endpoint' });
            showToast('Running health check...', { type: 'info', duration: 2000 });
        } else {
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

function renderApiFailoverUI(data: Record<string, unknown>): void {
    const section = document.getElementById('api-failover-section');
    const container = document.getElementById('api-endpoints');
    if (!section || !container) return;

    // Hide only on an EXPLICIT "not available". The api_endpoint_switched
    // frames (manual switch + auto-failover broadcast) carry endpoints but
    // no `available` key — treating that as unavailable hid the panel the
    // moment the user clicked a standby endpoint.
    if (data.available === false) {
        section.style.display = 'none';
        return;
    }
    if (!Array.isArray(data.endpoints)) {
        // Frame without endpoint data (e.g. the unauthenticated
        // safe-notification variant) — leave the panel as-is.
        return;
    }

    section.style.display = '';
    const endpoints = data.endpoints as Array<Record<string, unknown>>;
    container.innerHTML = '';

    for (const ep of endpoints) {
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
            const doSwitch = (): void => {
                if (chatManager?.connected) {
                    chatManager.send({ type: 'switch_api_endpoint', endpoint: ep.type });
                    showToast(`Switching to ${epType}...`, { type: 'info', duration: 2000 });
                }
            };
            item.style.cursor = 'pointer';
            item.title = `คลิกเพื่อสลับไปใช้ ${epType}`;
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

function renderHealthCheckResults(results: Array<Record<string, unknown>>): void {
    // Remove existing result
    const existing = document.getElementById('api-health-results');
    if (existing) existing.remove();

    const section = document.getElementById('api-failover-section');
    if (!section || !results?.length) return;

    const div = document.createElement('div');
    div.id = 'api-health-results';
    div.className = 'api-health-result';
    div.innerHTML = results.map(r => {
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
