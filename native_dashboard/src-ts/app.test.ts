/**
 * Dashboard Unit Tests
 * Tests for the TypeScript dashboard functionality
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

// Mock the Tauri API
vi.mock('@tauri-apps/api/core', () => ({
    invoke: vi.fn()
}));

import { escapeHtml, normalizeSqliteUtc, loadSettings, saveSettings, settings, showToast } from './shared';
import {
    VALID_PAGES,
    resolvePage,
    debounce,
    openModal,
    closeModal,
    _resetModalInertState,
    DataCache,
    addChartDataPoint,
    niceChartScale,
    drawChart,
    toggleAutoScroll,
    pickTopmostModal,
    initTheme,
} from './app';

// ============================================================================
// Test Data
// ============================================================================

const mockLogs = [
    '[2026-01-22 10:00:00] INFO - Bot started',
    '[2026-01-22 10:00:01] WARNING - Connection slow',
    '[2026-01-22 10:00:02] ERROR - Failed to connect'
];

// ============================================================================
// DataCache Tests
// ============================================================================

describe('DataCache', () => {
    // Exercises the REAL DataCache exported from app.ts (not an inline copy),
    // so a regression in the shipped TTL-expiry / capacity-eviction logic fails.
    let cache: DataCache;

    beforeEach(() => {
        cache = new DataCache();
    });

    it('should store and retrieve data', () => {
        cache.set('test', { value: 42 });
        const result = cache.get<{ value: number }>('test');
        expect(result).toEqual({ value: 42 });
    });

    it('should return null for non-existent keys', () => {
        const result = cache.get('nonexistent');
        expect(result).toBeNull();
    });

    it('should expire data after TTL', async () => {
        cache.set('test', { value: 42 }, 50); // 50ms TTL
        
        // Should exist immediately
        expect(cache.get('test')).toEqual({ value: 42 });
        
        // Wait for expiration
        await new Promise(resolve => setTimeout(resolve, 60));
        
        // Should be expired
        expect(cache.get('test')).toBeNull();
    });

    it('should invalidate specific keys', () => {
        cache.set('key1', 'value1');
        cache.set('key2', 'value2');
        
        cache.invalidate('key1');
        
        expect(cache.get('key1')).toBeNull();
        expect(cache.get('key2')).toBe('value2');
    });

    it('should clear all data', () => {
        cache.set('key1', 'value1');
        cache.set('key2', 'value2');

        cache.clear();

        expect(cache.get('key1')).toBeNull();
        expect(cache.get('key2')).toBeNull();
    });

    it('should evict the oldest entry once at capacity (maxSize=200)', () => {
        // Shipped behavior the old inline copy never had: at 200 live keys, the
        // next NEW key evicts the oldest insertion.
        for (let i = 0; i < 200; i++) cache.set(`k${i}`, i);
        expect(cache.get('k0')).toBe(0); // still present at capacity
        cache.set('k200', 200);          // over capacity → evicts oldest (k0)
        expect(cache.get('k0')).toBeNull();
        expect(cache.get('k200')).toBe(200);
        expect(cache.get('k199')).toBe(199);
    });
});

// ============================================================================
// Chart Data Tests
// ============================================================================

describe('Chart Data Management', () => {
    // Exercises the REAL addChartDataPoint exported from app.ts. It caps the
    // history at the live settings.chartHistory (not a per-call maxPoints arg),
    // so we drive the cap through that setting.
    type ChartDataPoint = { timestamp: number; value: number };

    const originalChartHistory = settings.chartHistory;
    afterEach(() => {
        settings.chartHistory = originalChartHistory;
    });

    it('should add data points to history', () => {
        const history: ChartDataPoint[] = [];

        addChartDataPoint(history, 100);
        addChartDataPoint(history, 200);

        expect(history).toHaveLength(2);
        expect(history[0].value).toBe(100);
        expect(history[1].value).toBe(200);
    });

    it('should limit history to settings.chartHistory points', () => {
        settings.chartHistory = 5;
        const history: ChartDataPoint[] = [];

        for (let i = 0; i < 10; i++) {
            addChartDataPoint(history, i);
        }

        expect(history).toHaveLength(5);
        expect(history[0].value).toBe(5); // First 5 should be removed
        expect(history[4].value).toBe(9);
    });

    it('should include timestamp with each point', () => {
        const history: ChartDataPoint[] = [];
        const before = Date.now();

        addChartDataPoint(history, 100);

        const after = Date.now();

        expect(history[0].timestamp).toBeGreaterThanOrEqual(before);
        expect(history[0].timestamp).toBeLessThanOrEqual(after);
    });
});

// ============================================================================
// Chart Y-scale Tests
// ============================================================================

describe('Chart Y-scale (niceChartScale)', () => {
    // Exercises the REAL niceChartScale exported from app.ts — the y-domain
    // policy that decides how dramatic a series looks. The regression this
    // guards: memory idling at ~232 MB (drifting 228 → 232, a <2% wobble)
    // used to get a min/max-hugging domain, stretching the wobble across the
    // full plot height so a flat-in-practice series read as a runaway surge.

    it('keeps a sub-10% wobble visually small (minimum span rule)', () => {
        const { lo, hi } = niceChartScale(228, 232, false);
        // The axis must open at least 10% of the value's own magnitude…
        expect(hi - lo).toBeGreaterThanOrEqual(232 * 0.1);
        // …so the 4 MB drift occupies well under half the plot height.
        expect((232 - 228) / (hi - lo)).toBeLessThanOrEqual(0.35);
        expect(lo).toBeLessThanOrEqual(228);
        expect(hi).toBeGreaterThanOrEqual(232);
    });

    it('applies the same flatness rule to integer count series', () => {
        const { lo, hi, ticks, step } = niceChartScale(5000, 5010, true);
        expect(hi - lo).toBeGreaterThanOrEqual(5010 * 0.1);
        expect(Number.isInteger(step)).toBe(true);
        expect(ticks[0]).toBe(lo);
        expect(ticks[ticks.length - 1]).toBe(hi);
        ticks.forEach(t => expect(Number.isInteger(t)).toBe(true));
    });

    it('lets a genuine large move fill the plot', () => {
        const { lo, hi } = niceChartScale(100, 400, false);
        // A 3× move is real signal — the minimum-span rule must not dilute it.
        expect((400 - 100) / (hi - lo)).toBeGreaterThanOrEqual(0.5);
        expect(lo).toBeLessThanOrEqual(100);
        expect(hi).toBeGreaterThanOrEqual(400);
    });

    it('opens a window around a perfectly flat series', () => {
        const { lo, hi, ticks } = niceChartScale(232, 232, false);
        expect(hi).toBeGreaterThan(lo);
        expect(lo).toBeLessThanOrEqual(232);
        expect(hi).toBeGreaterThanOrEqual(232);
        expect(ticks.length).toBeGreaterThanOrEqual(2);
    });

    it('never drops a non-negative series below zero', () => {
        const { lo } = niceChartScale(0, 0.2, false);
        expect(lo).toBe(0);
    });
});

// ============================================================================
// Chart Area-fill Closure Tests
// ============================================================================

describe('Chart hold-to-edge rendering (drawChart)', () => {
    // Exercises the SHIPPED drawChart against a recording 2D-context mock.
    // The regressions this guards: the x-axis is clock-anchored (right edge =
    // "now") while the last sample lags seconds behind, and that gap first
    // rendered as a diagonal fill wedge (polygon closed at the plot corner),
    // then as a vertical fill cliff (polygon closed under the last sample).
    // The latest reading must instead HOLD out to the clock edge — line,
    // fill, and endpoint marker all meet at "now".

    function makeRecordingCtx() {
        const calls: Array<{ method: string; args: unknown[] }> = [];
        const record = (method: string) => (...args: unknown[]): void => {
            calls.push({ method, args });
        };
        const ctx = {
            calls,
            scale: record('scale'),
            clearRect: record('clearRect'),
            beginPath: record('beginPath'),
            moveTo: record('moveTo'),
            lineTo: record('lineTo'),
            bezierCurveTo: record('bezierCurveTo'),
            closePath: record('closePath'),
            fill: record('fill'),
            stroke: record('stroke'),
            save: record('save'),
            restore: record('restore'),
            arc: record('arc'),
            fillText: record('fillText'),
            measureText: () => ({ width: 20 }),
            createLinearGradient: () => ({ addColorStop: (): void => undefined }),
        };
        return ctx;
    }

    it('holds the latest reading out to the clock edge (no cliff or wedge)', () => {
        vi.useFakeTimers();
        vi.setSystemTime(new Date('2026-07-11T18:22:05'));
        const originalRaf = window.requestAnimationFrame;
        window.requestAnimationFrame = ((): number => 0) as typeof window.requestAnimationFrame;
        const canvas = document.createElement('canvas');
        canvas.id = 'fill-test-chart';
        document.body.appendChild(canvas);
        canvas.getBoundingClientRect = () =>
            ({ width: 480, height: 200, top: 0, left: 0, right: 480, bottom: 200, x: 0, y: 0, toJSON: () => ({}) }) as DOMRect;
        const ctx = makeRecordingCtx();
        canvas.getContext = (() => ctx) as unknown as typeof canvas.getContext;

        try {
            const now = Date.now();
            // Last sample 5s stale — the messages series lags up to
            // refresh + dbStats TTL behind the clock-anchored right edge,
            // so 25% of this 20s window has no sample yet.
            drawChart('fill-test-chart', [
                { timestamp: now - 20_000, value: 210 },
                { timestamp: now - 10_000, value: 220 },
                { timestamp: now - 5_000, value: 214 },
            ], '#b2a4ff', { decimals: 0, unit: '' });

            // The area polygon is the only closePath'd path: isolate it.
            const closeIdx = ctx.calls.findIndex(c => c.method === 'closePath');
            expect(closeIdx).toBeGreaterThan(-1);
            const beginIdx = ctx.calls.slice(0, closeIdx).map(c => c.method).lastIndexOf('beginPath');
            const areaPath = ctx.calls.slice(beginIdx, closeIdx);
            const pathStart = areaPath.find(c => c.method === 'moveTo');
            const closure = areaPath.filter(c => c.method === 'lineTo');
            expect(closure).toHaveLength(2);

            // The endpoint marker rides the clock edge (x = 480 − 14 = 466),
            // not the stale sample's mid-plot position.
            const arcs = ctx.calls.filter(c => c.method === 'arc');
            const markerX = arcs[arcs.length - 1].args[0] as number;
            expect(markerX).toBeCloseTo(466, 6);

            // The path grows one horizontal hold segment past the 2 sample
            // gaps: its endpoint sits at the edge AT the last sample's y.
            const curves = areaPath.filter(c => c.method === 'bezierCurveTo');
            expect(curves).toHaveLength(3);
            const holdEnd = curves[curves.length - 1].args;
            const lastSampleY = curves[1].args[5] as number;
            expect(holdEnd[4] as number).toBeCloseTo(466, 6);
            expect(holdEnd[5] as number).toBeCloseTo(lastSampleY, 6);

            // Fill closes straight down at the edge under the hold line…
            expect(closure[0].args[0] as number).toBeCloseTo(466, 6);
            // …and returns to where the data starts.
            expect(closure[1].args[0] as number).toBeCloseTo(pathStart!.args[0] as number, 6);
            // Both closure points sit on the plot floor (height 200 − 22).
            expect(closure[0].args[1] as number).toBe(178);
            expect(closure[1].args[1] as number).toBe(178);
        } finally {
            window.requestAnimationFrame = originalRaf;
            canvas.remove();
            vi.useRealTimers();
        }
    });
});

// ============================================================================
// Logs Pause/Resume Tests
// ============================================================================

describe('Logs pause/resume (toggleAutoScroll)', () => {
    // Exercises the SHIPPED toggleAutoScroll + startLogsRefresh against the
    // real 1s poller. The regression this guards: the PAUSE button only
    // gated the scroll-to-bottom while the poll kept fetching and rebuilding
    // the list every second — logs visibly "kept running" after pressing it.

    it('pause freezes the log poll; resume catches up and restarts it', async () => {
        vi.useFakeTimers();
        const invokeMock = vi.fn(async (cmd: string) =>
            cmd === 'get_logs' ? ['[2026-01-01 00:00:00] INFO - line'] : null);
        (window as unknown as { __TAURI__?: unknown }).__TAURI__ = { core: { invoke: invokeMock } };
        const getLogsCalls = (): number =>
            invokeMock.mock.calls.filter(c => c[0] === 'get_logs').length;
        const showPage = (window as unknown as { showPage: (p: string) => void }).showPage;

        try {
            showPage('logs');                               // one-shot load + poll start
            await vi.advanceTimersByTimeAsync(3000);        // 3 poll ticks
            const live = getLogsCalls();
            expect(live).toBeGreaterThanOrEqual(4);         // 1 immediate + 3 ticks

            toggleAutoScroll();                             // PAUSE
            await vi.advanceTimersByTimeAsync(5000);
            expect(getLogsCalls()).toBe(live);              // feed frozen

            toggleAutoScroll();                             // RESUME
            await vi.advanceTimersByTimeAsync(2000);
            expect(getLogsCalls()).toBe(live + 3);          // instant catch-up + 2 ticks
        } finally {
            showPage('status');                             // stops the poll
            delete (window as unknown as { __TAURI__?: unknown }).__TAURI__;
            vi.useRealTimers();
        }
    });
});

// ============================================================================
// Settings Tests
// ============================================================================

describe('Settings Management', () => {
    // Exercises the REAL loadSettings/saveSettings exported from shared.ts and
    // the live `settings` singleton — not an inline merge copy. This catches
    // regressions in the actual persistence + defensive field coercion.
    beforeEach(() => {
        localStorage.clear();
        // Reset the singleton to a known baseline before each case.
        settings.theme = 'dark';
        settings.refreshInterval = 2000;
        settings.notifications = true;
        settings.chartHistory = 60;
    });

    it('should round-trip settings through localStorage (save then load)', () => {
        settings.theme = 'light';
        settings.refreshInterval = 5000;
        saveSettings();

        // Flip in-memory, then load must restore the persisted values.
        settings.theme = 'dark';
        settings.refreshInterval = 2000;
        loadSettings();

        expect(settings.theme).toBe('light');
        expect(settings.refreshInterval).toBe(5000);
    });

    it('should merge partial saved settings over the defaults', () => {
        // Only persist a partial blob; loadSettings spreads it over the existing
        // defaults so untouched fields keep their default values.
        localStorage.setItem('dashboard-settings', JSON.stringify({ theme: 'light' }));
        loadSettings();

        expect(settings.theme).toBe('light');
        expect(settings.refreshInterval).toBe(2000); // default preserved
        expect(settings.notifications).toBe(true);    // default preserved
    });

    it('should coerce a tampered/invalid blob back to safe defaults', () => {
        // Real defensive logic the inline copy never had: a bad refreshInterval
        // (would create a runaway setInterval) and an unknown theme are coerced.
        localStorage.setItem(
            'dashboard-settings',
            JSON.stringify({ theme: 'neon', refreshInterval: -1, chartHistory: 99999 }),
        );
        loadSettings();

        expect(settings.theme).toBe('dark');         // unknown theme -> default
        expect(settings.refreshInterval).toBe(2000); // invalid interval -> default
        expect(settings.chartHistory).toBe(60);      // out-of-range -> default
    });
});

// ============================================================================
// Theme init — first-run prefers-color-scheme default (A11Y-05)
// ============================================================================

describe('initTheme — first-run prefers-color-scheme (A11Y-05)', () => {
    let matchMediaMock: ReturnType<typeof vi.fn>;

    function setPrefersLight(prefersLight: boolean): void {
        matchMediaMock = vi.fn().mockImplementation((query: string) => ({
            matches: query.includes('light') ? prefersLight : !prefersLight,
            media: query,
            addEventListener: vi.fn(),
            removeEventListener: vi.fn(),
            addListener: vi.fn(),
            removeListener: vi.fn(),
            dispatchEvent: vi.fn(),
            onchange: null,
        }));
        (window as unknown as { matchMedia: unknown }).matchMedia = matchMediaMock;
    }

    beforeEach(() => {
        localStorage.clear();
        settings.theme = 'dark';
        // Minimal DOM the theme wiring touches.
        document.body.innerHTML = `
            <button id="theme-toggle"></button>
            <button id="theme-toggle-settings"></button>
            <span id="theme-icon"></span>
            <span id="theme-icon-settings"></span>
            <div id="toast-container"></div>
        `;
    });

    afterEach(() => {
        document.documentElement.removeAttribute('data-theme');
    });

    it('defaults to light when the OS prefers light and no theme is stored', () => {
        setPrefersLight(true);
        initTheme();
        expect(settings.theme).toBe('light');
        expect(document.documentElement.getAttribute('data-theme')).toBe('light');
    });

    it('defaults to dark when the OS prefers dark and no theme is stored', () => {
        setPrefersLight(false);
        initTheme();
        expect(settings.theme).toBe('dark');
        expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
    });

    it('honours a stored theme over the OS preference', () => {
        // User previously chose light; OS prefers dark — the stored choice wins.
        localStorage.setItem('dashboard-settings', JSON.stringify({ theme: 'light' }));
        settings.theme = 'light';  // loadSettings would have applied this
        setPrefersLight(false);    // OS prefers dark
        initTheme();
        expect(settings.theme).toBe('light');
        expect(document.documentElement.getAttribute('data-theme')).toBe('light');
    });
});

// ============================================================================
// Log Filtering Tests
// ============================================================================

describe('Log Filtering', () => {
    function filterLogs(logs: string[], filter: string): string[] {
        if (filter === 'all') return logs;
        return logs.filter(line => line.includes(filter));
    }

    function getLogLevel(line: string): string {
        if (line.includes('ERROR')) return 'error';
        if (line.includes('WARNING')) return 'warning';
        if (line.includes('DEBUG')) return 'debug';
        return 'info';
    }

    it('should return all logs when filter is "all"', () => {
        const result = filterLogs(mockLogs, 'all');
        expect(result).toHaveLength(3);
    });

    it('should filter by INFO level', () => {
        const result = filterLogs(mockLogs, 'INFO');
        expect(result).toHaveLength(1);
        expect(result[0]).toContain('Bot started');
    });

    it('should filter by WARNING level', () => {
        const result = filterLogs(mockLogs, 'WARNING');
        expect(result).toHaveLength(1);
        expect(result[0]).toContain('Connection slow');
    });

    it('should filter by ERROR level', () => {
        const result = filterLogs(mockLogs, 'ERROR');
        expect(result).toHaveLength(1);
        expect(result[0]).toContain('Failed to connect');
    });

    it('should correctly identify log levels', () => {
        expect(getLogLevel(mockLogs[0])).toBe('info');
        expect(getLogLevel(mockLogs[1])).toBe('warning');
        expect(getLogLevel(mockLogs[2])).toBe('error');
    });
});

// ============================================================================
// HTML Escaping Tests
// ============================================================================

describe('HTML Escaping', () => {
    // Exercises the real escapeHtml exported from shared.ts. Unlike a bare
    // textContent round-trip it ALSO escapes ", ' and ` so the result is safe
    // inside a double/single-quoted HTML attribute, not just element text.

    it('should escape HTML special characters', () => {
        const input = '<script>alert("xss")</script>';
        const result = escapeHtml(input);
        expect(result).not.toContain('<script>');
        expect(result).toContain('&lt;script&gt;');
    });

    it('should handle ampersands', () => {
        const input = 'Tom & Jerry';
        const result = escapeHtml(input);
        expect(result).toBe('Tom &amp; Jerry');
    });

    it('should escape double quotes (attribute-safe)', () => {
        expect(escapeHtml('a"b')).toBe('a&quot;b');
        expect(escapeHtml('Say "Hello"')).toBe('Say &quot;Hello&quot;');
    });

    it('should escape single quotes', () => {
        expect(escapeHtml("a'b")).toBe('a&#39;b');
    });

    it('should escape backticks', () => {
        expect(escapeHtml('a`b')).toBe('a&#96;b');
    });

    it('should handle normal text', () => {
        const input = 'Hello World';
        const result = escapeHtml(input);
        expect(result).toBe('Hello World');
    });
});

// ============================================================================
// Debounce Tests
// ============================================================================

describe('Debounce Function', () => {
    beforeEach(() => {
        vi.useFakeTimers();
    });

    afterEach(() => {
        vi.useRealTimers();
    });

    // Exercises the real higher-order debounce exported from app.ts:
    // debounce(fn, key, delay) returns a trigger function; rapid triggers for
    // the same key collapse into a single trailing call after `delay`.

    it('should return a callable trigger function', () => {
        const trigger = debounce(() => {}, 'returns-fn', 100);
        expect(typeof trigger).toBe('function');
    });

    it('should debounce rapid calls into a single trailing invocation', () => {
        const fn = vi.fn();
        const trigger = debounce(fn, 'collapse', 100);

        // Trigger multiple times rapidly
        trigger();
        trigger();
        trigger();

        // Not called until the delay elapses
        expect(fn).not.toHaveBeenCalled();

        vi.advanceTimersByTime(150);

        expect(fn).toHaveBeenCalledTimes(1);
    });

    it('should debounce independently per key', () => {
        const fnA = vi.fn();
        const fnB = vi.fn();
        // Distinct keys must not clear each other's pending timer.
        debounce(fnA, 'key-a', 100)();
        debounce(fnB, 'key-b', 100)();

        vi.advanceTimersByTime(150);

        expect(fnA).toHaveBeenCalledTimes(1);
        expect(fnB).toHaveBeenCalledTimes(1);
    });
});

// ============================================================================
// Toast Notification Tests
// ============================================================================

describe('Toast Notifications', () => {
    // Exercises the REAL showToast exported from shared.ts (DOM injection,
    // HTML-escaping, and the notifications-mute gate) rather than building a
    // toast div by hand.
    beforeEach(() => {
        document.body.innerHTML = '<div id="toast-container"></div>';
        settings.notifications = true;
    });

    afterEach(() => {
        document.body.innerHTML = '';
        settings.notifications = true;
    });

    it('should append a typed toast to the container', () => {
        showToast('Saved', { type: 'success' });
        const container = document.getElementById('toast-container')!;
        expect(container.children).toHaveLength(1);
        expect(container.querySelector('.toast-success')).not.toBeNull();
        expect(container.querySelector('.toast-message')?.textContent).toBe('Saved');
    });

    it('should HTML-escape the toast message (XSS-safe)', () => {
        showToast('<img src=x onerror=alert(1)>', { type: 'info' });
        const msg = document.querySelector('#toast-container .toast-message');
        // The payload is rendered as text, not a live <img> element.
        expect(msg?.querySelector('img')).toBeNull();
        expect(msg?.textContent).toContain('<img src=x onerror=alert(1)>');
    });

    it('should suppress info toasts when notifications are muted', () => {
        settings.notifications = false;
        showToast('quiet', { type: 'info' });
        expect(document.getElementById('toast-container')!.children).toHaveLength(0);
    });

    it('should still surface error toasts even when notifications are muted', () => {
        settings.notifications = false;
        showToast('boom', { type: 'error' });
        const container = document.getElementById('toast-container')!;
        expect(container.children).toHaveLength(1);
        expect(container.querySelector('.toast-error')?.getAttribute('role')).toBe('alert');
    });
});

// ============================================================================
// Number Formatting Tests
// ============================================================================

describe('Number Formatting', () => {
    it('should format large numbers with commas', () => {
        expect((15000).toLocaleString()).toBe('15,000');
        expect((1000000).toLocaleString()).toBe('1,000,000');
    });

    it('should format memory values with one decimal', () => {
        const memory = 256.5;
        expect(memory.toFixed(1)).toBe('256.5');
    });

    it('should handle zero values', () => {
        expect((0).toLocaleString()).toBe('0');
        expect((0).toFixed(1)).toBe('0.0');
    });
});

// ============================================================================
// Page Navigation — alias resolution + validation (switchPage guard)
// ============================================================================

describe('Page Navigation', () => {
    // Exercises the real resolvePage exported from app.ts — the same guard
    // switchPage runs: stale aliases map through, then anything not in
    // VALID_PAGES is rejected so a bad id can't blank the UI. Importing the
    // real symbols means this test fails if the guard logic drifts.

    it('should map the stale "config" alias to "settings"', () => {
        expect(resolvePage('config')).toBe('settings');
    });

    it('should pass through every canonical page id unchanged', () => {
        for (const p of VALID_PAGES) {
            expect(resolvePage(p)).toBe(p);
        }
    });

    it('should reject unknown page ids', () => {
        expect(resolvePage('does-not-exist')).toBeNull();
        expect(resolvePage('')).toBeNull();
        expect(resolvePage('page-settings')).toBeNull();
    });
});

// ============================================================================
// SQLite Timestamp Normalization (normalizeSqliteUtc)
// ============================================================================

describe('SQLite Timestamp Normalization', () => {
    // Exercises the real normalizeSqliteUtc exported from shared.ts: append "Z"
    // to naive timestamps (so JS parses them as UTC, not local) and swap the
    // space separator for "T". Already-zoned strings keep their zone.

    it('should normalize a naive SQLite timestamp to UTC ISO', () => {
        expect(normalizeSqliteUtc('2026-01-22 10:00:00')).toBe('2026-01-22T10:00:00Z');
    });

    it('should leave a string that already ends in Z unchanged apart from the separator', () => {
        expect(normalizeSqliteUtc('2026-01-22T10:00:00Z')).toBe('2026-01-22T10:00:00Z');
    });

    it('should not double-append a zone for explicit offsets', () => {
        expect(normalizeSqliteUtc('2026-01-22 10:00:00+07:00')).toBe('2026-01-22T10:00:00+07:00');
    });

    it('should parse as UTC so the epoch matches an explicit Z', () => {
        const naive = new Date(normalizeSqliteUtc('2026-01-22 10:00:00')).getTime();
        const explicit = new Date('2026-01-22T10:00:00Z').getTime();
        expect(naive).toBe(explicit);
    });

    // Adversarial / malformed input — lock the "never throws" contract. The
    // helper is a pure string transform, so garbage in yields a garbage ISO
    // string that Date parses to NaN rather than blowing up the caller.
    it('should not throw on empty / garbage input and yield an unparseable date', () => {
        expect(() => normalizeSqliteUtc('')).not.toThrow();
        expect(Number.isNaN(new Date(normalizeSqliteUtc('')).getTime())).toBe(true);

        expect(() => normalizeSqliteUtc('garbage')).not.toThrow();
        expect(Number.isNaN(new Date(normalizeSqliteUtc('garbage')).getTime())).toBe(true);
    });

    it('should preserve fractional seconds as a still-parseable UTC ISO', () => {
        const out = normalizeSqliteUtc('2026-01-22 10:00:00.123');
        expect(out).toBe('2026-01-22T10:00:00.123Z');
        expect(Number.isNaN(new Date(out).getTime())).toBe(false);
    });

    it('should treat a colon-less offset as an existing zone (no extra Z)', () => {
        // The tz regex makes the ':' optional, so "+0700" counts as zoned and we
        // must NOT append a second designator — only swap the separator.
        const out = normalizeSqliteUtc('2026-01-22 10:00:00+0700');
        expect(() => normalizeSqliteUtc('2026-01-22 10:00:00+0700')).not.toThrow();
        expect(out).toBe('2026-01-22T10:00:00+0700');
        expect(out.endsWith('Z')).toBe(false);
    });
});

// ============================================================================
// Modal inert ref-counting (#6)
// ============================================================================

describe('Modal inert ref-counting (#6)', () => {
    // openModal/closeModal toggle `inert` + `aria-hidden` on `.app` so the
    // overlay is the only reachable region. inert is now ref-counted by the
    // set of openModal-owned modals, not by a global `.modal.active` query —
    // so a chat modal (which lives INSIDE .app and toggles .active directly,
    // never owning inert) can no longer pin inert on after an owned modal closes.
    let app: HTMLElement;

    beforeEach(() => {
        _resetModalInertState();
        document.body.innerHTML = '';
        app = document.createElement('div');
        app.className = 'app';
        document.body.appendChild(app);
    });

    afterEach(() => {
        document.body.innerHTML = '';
    });

    function addModal(id: string, opts: { active?: boolean; insideApp?: boolean } = {}): HTMLElement {
        const modal = document.createElement('div');
        modal.id = id;
        modal.className = opts.active ? 'modal active' : 'modal';
        // app-level modals are siblings of .app; chat modals live inside it.
        (opts.insideApp ? app : document.body).appendChild(modal);
        return modal;
    }

    it('should set inert + aria-hidden on .app when an owned modal opens', () => {
        const shortcuts = addModal('shortcuts-modal');
        openModal(shortcuts);
        expect(app.hasAttribute('inert')).toBe(true);
        expect(app.getAttribute('aria-hidden')).toBe('true');
    });

    it('should lift inert + aria-hidden when the only owned modal closes', () => {
        const shortcuts = addModal('shortcuts-modal');
        openModal(shortcuts);
        closeModal(shortcuts);
        expect(app.hasAttribute('inert')).toBe(false);
        expect(app.hasAttribute('aria-hidden')).toBe(false);
    });

    it('should lift inert even when a stale .active chat modal remains (the bug)', () => {
        // A chat modal left .active inside .app (it never goes through openModal,
        // so it never owns inert). Under the old `querySelector('.modal.active')`
        // check this stranded inert on and trapped the user. Ref-counting fixes it.
        addModal('delete-confirm-modal', { active: true, insideApp: true });
        const shortcuts = addModal('shortcuts-modal');

        openModal(shortcuts);
        expect(app.hasAttribute('inert')).toBe(true);

        closeModal(shortcuts);
        // The lingering .active chat modal must NOT keep .app inert.
        expect(app.hasAttribute('inert')).toBe(false);
        expect(app.hasAttribute('aria-hidden')).toBe(false);
    });

    it('should keep inert until the last owned modal closes (ref-count stacking)', () => {
        const a = addModal('shortcuts-modal');
        const b = addModal('avatar-crop-modal');

        openModal(a);
        openModal(b);
        expect(app.hasAttribute('inert')).toBe(true);

        closeModal(b);
        // One owned modal still open — inert must stay (size 1).
        expect(app.hasAttribute('inert')).toBe(true);

        closeModal(a);
        // All owned modals closed — inert lifts (size 0).
        expect(app.hasAttribute('inert')).toBe(false);
    });

    it('should treat a repeated open of the same modal idempotently', () => {
        const shortcuts = addModal('shortcuts-modal');
        openModal(shortcuts);
        openModal(shortcuts); // Set => no duplicate owner
        expect(app.hasAttribute('inert')).toBe(true);

        // A single close clears the sole owner and lifts inert.
        closeModal(shortcuts);
        expect(app.hasAttribute('inert')).toBe(false);
    });
});

// ============================================================================
// Modal focus-trap topmost selection (#7)
// ============================================================================

describe('Modal focus-trap topmost (#7)', () => {
    // The Tab focus-trap selects the LAST .modal.active in DOM order (topmost
    // overlay) instead of the first. We import the REAL pickTopmostModal from
    // app.ts (the exact symbol the focus-trap calls), so reverting it to
    // actives[0] would fail these tests — jsdom can't drive native focus, but
    // it CAN assert the production selection at the DOM-query level.
    beforeEach(() => {
        _resetModalInertState();
        document.body.innerHTML = '';
    });

    afterEach(() => {
        document.body.innerHTML = '';
    });

    it('should pick the last-in-DOM active modal when two are stacked', () => {
        // chat modal first (inside .app), app-level shortcuts after — the latter
        // is the overlay stacked on top and must win the focus trap.
        const app = document.createElement('div');
        app.className = 'app';
        const chat = document.createElement('div');
        chat.id = 'delete-confirm-modal';
        chat.className = 'modal active';
        app.appendChild(chat);
        document.body.appendChild(app);

        const shortcuts = document.createElement('div');
        shortcuts.id = 'shortcuts-modal';
        shortcuts.className = 'modal active';
        document.body.appendChild(shortcuts);

        expect(pickTopmostModal()).toBe(shortcuts);
        expect(pickTopmostModal()?.id).toBe('shortcuts-modal');
    });

    it('should equal the lone active modal in the single-modal case', () => {
        // Zero behavior change in the single-modal case: last === first.
        const only = document.createElement('div');
        only.id = 'shortcuts-modal';
        only.className = 'modal active';
        document.body.appendChild(only);

        const single = document.querySelector<HTMLElement>('.modal.active');
        expect(pickTopmostModal()).toBe(single);
        expect(pickTopmostModal()).toBe(only);
    });

    it('should pick nothing when no modal is active', () => {
        const inactive = document.createElement('div');
        inactive.className = 'modal';
        document.body.appendChild(inactive);
        expect(pickTopmostModal()).toBeNull();
    });
});
