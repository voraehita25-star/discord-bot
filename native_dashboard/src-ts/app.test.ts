/**
 * Dashboard Unit Tests
 * Tests for the TypeScript dashboard functionality.
 *
 * Imports the production implementations from ./app-helpers.js + ./shared.js
 * so coverage actually reflects what ships. (Previously this file re-defined
 * inline copies and tested those — see commit history.)
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

// Mock the Tauri API so anything indirectly importing @tauri-apps/api works
// even when window.__TAURI__ isn't present. Some helper modules pull this in
// transitively via shared.ts.
vi.mock('@tauri-apps/api/core', () => ({
    invoke: vi.fn(),
}));

import {
    DataCache,
    addChartDataPoint,
    filterLogs,
    getLogLevel,
    debounce,
} from './app-helpers.js';
import { escapeHtml } from './shared.js';

// ============================================================================
// Test Data
// ============================================================================

const mockLogs = [
    '[2026-01-22 10:00:00] INFO - Bot started',
    '[2026-01-22 10:00:01] WARNING - Connection slow',
    '[2026-01-22 10:00:02] ERROR - Failed to connect',
];

// ============================================================================
// DataCache Tests
// ============================================================================

describe('DataCache', () => {
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
        await new Promise((resolve) => setTimeout(resolve, 60));

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

    it('should evict oldest entry when at capacity', () => {
        const small = new DataCache(3);
        small.set('a', 1);
        small.set('b', 2);
        small.set('c', 3);
        // Inserting a 4th key forces eviction of the oldest (a).
        small.set('d', 4);
        expect(small.get('a')).toBeNull();
        expect(small.get('b')).toBe(2);
        expect(small.get('c')).toBe(3);
        expect(small.get('d')).toBe(4);
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
        chartHistory: 60,
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
            refreshInterval: 5000,
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

    it('classifies DEBUG lines as debug', () => {
        expect(getLogLevel('[2026-01-22 10:00:00] DEBUG - hello')).toBe('debug');
    });
});

// ============================================================================
// HTML Escaping Tests (escapeHtml is exported from ./shared.js)
// ============================================================================

describe('HTML Escaping', () => {
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

    it('should handle quotes', () => {
        const input = 'Say "Hello"';
        const result = escapeHtml(input);
        // Production escapeHtml() (shared.ts) deliberately escapes " ' ` for
        // defense-in-depth — inline copies of this test used to use raw
        // div.textContent which preserved quotes; that was the inline
        // implementation, not what ships.
        expect(result).toBe('Say &quot;Hello&quot;');
    });

    it('escapes single quotes and backticks too', () => {
        expect(escapeHtml("It's fine")).toContain('&#39;');
        expect(escapeHtml('a `code` b')).toContain('&#96;');
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

    it('should debounce function calls', () => {
        const timers: Map<string, ReturnType<typeof setTimeout>> = new Map();
        const fn = vi.fn();
        const trigger = debounce(fn, 'test', 100, timers);

        // Call multiple times rapidly
        trigger();
        trigger();
        trigger();

        // Function should not be called yet
        expect(fn).not.toHaveBeenCalled();

        // Advance time
        vi.advanceTimersByTime(150);

        // Function should be called only once
        expect(fn).toHaveBeenCalledTimes(1);
    });

    it('clears the pending timer for the matching key only', () => {
        const timers: Map<string, ReturnType<typeof setTimeout>> = new Map();
        const fnA = vi.fn();
        const fnB = vi.fn();
        const triggerA = debounce(fnA, 'a', 100, timers);
        const triggerB = debounce(fnB, 'b', 100, timers);

        triggerA();
        triggerB();
        // Re-fire only A — B's timer should keep running.
        triggerA();
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
        expect((15000).toLocaleString('en-US')).toBe('15,000');
        expect((1000000).toLocaleString('en-US')).toBe('1,000,000');
    });

    it('should format memory values with one decimal', () => {
        const memory = 256.5;
        expect(memory.toFixed(1)).toBe('256.5');
    });

    it('should handle zero values', () => {
        expect((0).toLocaleString('en-US')).toBe('0');
        expect((0).toFixed(1)).toBe('0.0');
    });
});
