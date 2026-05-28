// ============================================================================
// DataCache — TTL'd key/value cache used for IPC response memoization.
// ============================================================================
export class DataCache {
    constructor(maxSize = 200) {
        this.cache = new Map();
        this.maxSize = maxSize;
    }
    set(key, data, ttlMs = 5000) {
        // Evict oldest entry when at capacity, but only when inserting a new
        // key. Overwriting an existing key just refreshes it in place.
        if (this.cache.size >= this.maxSize && !this.cache.has(key)) {
            const oldest = this.cache.keys().next().value;
            if (oldest !== undefined)
                this.cache.delete(oldest);
        }
        this.cache.set(key, {
            data,
            timestamp: Date.now(),
            ttl: ttlMs,
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
// ============================================================================
// Chart data — circular buffer of (timestamp, value) points.
// ============================================================================
/**
 * Push `value` (timestamped to now) onto `history` and trim back to
 * `maxPoints` from the head. Mutates `history` in place.
 */
export function addChartDataPoint(history, value, maxPoints = 60) {
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
export function filterLogs(logs, filter) {
    if (filter === 'all')
        return logs;
    return logs.filter((line) => line.includes(filter));
}
/**
 * Classify a single log line into a level token used as a CSS class
 * suffix (`info`/`warning`/`error`/`debug`).
 */
export function getLogLevel(line) {
    if (line.includes('ERROR'))
        return 'error';
    if (line.includes('WARNING'))
        return 'warning';
    if (line.includes('DEBUG'))
        return 'debug';
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
export function debounce(fn, key, delay, timers) {
    return () => {
        const existing = timers.get(key);
        if (existing !== undefined) {
            clearTimeout(existing);
        }
        timers.set(key, setTimeout(() => {
            fn();
            timers.delete(key);
        }, delay));
    };
}
//# sourceMappingURL=app-helpers.js.map