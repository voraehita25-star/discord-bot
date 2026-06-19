/**
 * Dashboard Unit Tests
 * Tests for the TypeScript dashboard functionality
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

// Mock the Tauri API
vi.mock('@tauri-apps/api/core', () => ({
    invoke: vi.fn()
}));

import { escapeHtml, normalizeSqliteUtc } from './shared';
import {
    VALID_PAGES,
    resolvePage,
    debounce,
    openModal,
    closeModal,
    _resetModalInertState,
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
    // Inline DataCache for testing
    class DataCache {
        private cache: Map<string, { data: unknown; timestamp: number; ttl: number }> = new Map();

        set<T>(key: string, data: T, ttlMs: number = 5000): void {
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
});

// ============================================================================
// Chart Data Tests
// ============================================================================

describe('Chart Data Management', () => {
    interface ChartDataPoint {
        timestamp: number;
        value: number;
    }

    function addChartDataPoint(history: ChartDataPoint[], value: number, maxPoints: number = 60): void {
        history.push({
            timestamp: Date.now(),
            value
        });
        
        while (history.length > maxPoints) {
            history.shift();
        }
    }

    it('should add data points to history', () => {
        const history: ChartDataPoint[] = [];
        
        addChartDataPoint(history, 100);
        addChartDataPoint(history, 200);
        
        expect(history).toHaveLength(2);
        expect(history[0].value).toBe(100);
        expect(history[1].value).toBe(200);
    });

    it('should limit history to max points', () => {
        const history: ChartDataPoint[] = [];
        const maxPoints = 5;
        
        for (let i = 0; i < 10; i++) {
            addChartDataPoint(history, i, maxPoints);
        }
        
        expect(history).toHaveLength(maxPoints);
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
// Settings Tests
// ============================================================================

describe('Settings Management', () => {
    interface Settings {
        theme: 'dark' | 'light';
        refreshInterval: number;
        autoScroll: boolean;
        notifications: boolean;
        chartHistory: number;
    }

    const defaultSettings: Settings = {
        theme: 'dark',
        refreshInterval: 2000,
        autoScroll: true,
        notifications: true,
        chartHistory: 60
    };

    beforeEach(() => {
        localStorage.clear();
    });

    it('should load default settings when none saved', () => {
        const saved = localStorage.getItem('dashboard-settings');
        expect(saved).toBeNull();
    });

    it('should save and load settings from localStorage', () => {
        const settings: Settings = {
            ...defaultSettings,
            theme: 'light',
            refreshInterval: 5000
        };
        
        localStorage.setItem('dashboard-settings', JSON.stringify(settings));
        
        const loaded = JSON.parse(localStorage.getItem('dashboard-settings')!);
        expect(loaded.theme).toBe('light');
        expect(loaded.refreshInterval).toBe(5000);
    });

    it('should merge saved settings with defaults', () => {
        // Only save partial settings
        localStorage.setItem('dashboard-settings', JSON.stringify({ theme: 'light' }));
        
        const saved = JSON.parse(localStorage.getItem('dashboard-settings')!);
        const merged: Settings = { ...defaultSettings, ...saved };
        
        expect(merged.theme).toBe('light');
        expect(merged.refreshInterval).toBe(2000); // default
        expect(merged.notifications).toBe(true); // default
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
    beforeEach(() => {
        document.body.innerHTML = '<div id="toast-container"></div>';
    });

    afterEach(() => {
        document.body.innerHTML = '';
    });

    it('should create toast container if not exists', () => {
        document.body.innerHTML = '';
        
        if (!document.getElementById('toast-container')) {
            const container = document.createElement('div');
            container.id = 'toast-container';
            document.body.appendChild(container);
        }
        
        expect(document.getElementById('toast-container')).not.toBeNull();
    });

    it('should add toast to container', () => {
        const container = document.getElementById('toast-container')!;
        
        const toast = document.createElement('div');
        toast.className = 'toast toast-success';
        toast.innerHTML = '<span>Test message</span>';
        container.appendChild(toast);
        
        expect(container.children).toHaveLength(1);
        expect(container.querySelector('.toast-success')).not.toBeNull();
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
    // The Tab focus-trap now selects the LAST .modal.active in DOM order
    // (topmost overlay) instead of the first. This mirrors the live selector
    // `querySelectorAll('.modal.active')` then `[length - 1]`; we assert the
    // selection at the DOM-query level (jsdom can't drive native focus reliably).
    beforeEach(() => {
        _resetModalInertState();
        document.body.innerHTML = '';
    });

    afterEach(() => {
        document.body.innerHTML = '';
    });

    // Mirror of the focus-trap's modal pick in app.ts (last .modal.active).
    function pickTopmost(): HTMLElement | null {
        const actives = document.querySelectorAll<HTMLElement>('.modal.active');
        return actives.length ? actives[actives.length - 1] : null;
    }

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

        expect(pickTopmost()).toBe(shortcuts);
        expect(pickTopmost()?.id).toBe('shortcuts-modal');
    });

    it('should equal the old querySelector result for a single active modal', () => {
        // Zero behavior change in the single-modal case: last === first.
        const only = document.createElement('div');
        only.id = 'shortcuts-modal';
        only.className = 'modal active';
        document.body.appendChild(only);

        const single = document.querySelector<HTMLElement>('.modal.active');
        expect(pickTopmost()).toBe(single);
        expect(pickTopmost()).toBe(only);
    });

    it('should pick nothing when no modal is active', () => {
        const inactive = document.createElement('div');
        inactive.className = 'modal';
        document.body.appendChild(inactive);
        expect(pickTopmost()).toBeNull();
    });
});
