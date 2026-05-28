/**
 * Pure helpers extracted from app.ts for testability.
 *
 * These functions used to live as private declarations inside app.ts, which
 * meant the unit test suite re-defined inline copies and exercised those —
 * giving zero production-code coverage. Lifting them here lets both app.ts
 * and src-ts/app.test.ts import the same implementation.
 */
import type { ChartDataPoint, CacheEntry } from './types.js';

// ============================================================================
// DataCache — TTL'd key/value cache used for IPC response memoization.
// ============================================================================

export class DataCache {
    private cache: Map<string, CacheEntry<unknown>> = new Map();
    private readonly maxSize: number;

    constructor(maxSize: number = 200) {
        this.maxSize = maxSize;
    }

    set<T>(key: string, data: T, ttlMs: number = 5000): void {
        // Evict oldest entry when at capacity, but only when inserting a new
        // key. Overwriting an existing key just refreshes it in place.
        if (this.cache.size >= this.maxSize && !this.cache.has(key)) {
            const oldest = this.cache.keys().next().value;
            if (oldest !== undefined) this.cache.delete(oldest);
        }
        this.cache.set(key, {
            data,
            timestamp: Date.now(),
            ttl: ttlMs,
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

// ============================================================================
// Chart data — circular buffer of (timestamp, value) points.
// ============================================================================

/**
 * Push `value` (timestamped to now) onto `history` and trim back to
 * `maxPoints` from the head. Mutates `history` in place.
 */
export function addChartDataPoint(
    history: ChartDataPoint[],
    value: number,
    maxPoints: number = 60,
): void {
    history.push({
        timestamp: Date.now(),
        value,
    });
    while (history.length > maxPoints) {
        history.shift();
    }
}

// ============================================================================
// Log filtering — split out of loadLogs() so the level/filter logic is unit-testable.
// ============================================================================

/**
 * Return the lines from `logs` matching `filter`. The sentinel `'all'`
 * returns the full list; any other filter is treated as a literal substring.
 */
export function filterLogs(logs: string[], filter: string): string[] {
    if (filter === 'all') return logs;
    return logs.filter((line) => line.includes(filter));
}

/**
 * Classify a single log line into a level token used as a CSS class
 * suffix (`info`/`warning`/`error`/`debug`).
 */
export function getLogLevel(line: string): 'error' | 'warning' | 'debug' | 'info' {
    if (line.includes('ERROR')) return 'error';
    if (line.includes('WARNING')) return 'warning';
    if (line.includes('DEBUG')) return 'debug';
    return 'info';
}

// ============================================================================
// Debounce — keyed timer map so two callers using different `key`s don't
// fight over the same timer slot. Kept pure: the caller owns the map.
// ============================================================================

/**
 * Build a debounced wrapper around `fn`. `timers` is the shared map used to
 * dedupe by `key` across multiple debounce wrappers; pass a fresh `Map` per
 * application or per test scope.
 *
 * The returned function clears any pending timer for the given key and
 * schedules `fn` to run after `delay` ms.
 */
export function debounce(
    fn: () => void,
    key: string,
    delay: number,
    timers: Map<string, ReturnType<typeof setTimeout>>,
): () => void {
    return () => {
        const existing = timers.get(key);
        if (existing !== undefined) {
            clearTimeout(existing);
        }
        timers.set(
            key,
            setTimeout(() => {
                fn();
                timers.delete(key);
            }, delay),
        );
    };
}
