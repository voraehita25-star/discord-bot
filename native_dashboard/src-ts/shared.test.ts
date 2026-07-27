/**
 * Unit tests for the small pure helpers in shared.ts.
 */
import { describe, it, expect, afterEach } from 'vitest';
import {
    countLabel,
    normalizeSqliteUtc,
    prefersReducedMotion,
    scrollBehavior,
} from './shared.js';

describe('countLabel', () => {
    // The bug it replaces: every count in the UI was `${n.toLocaleString()}
    // messages`, so a channel holding one message rendered "1 messages".
    it('uses the singular for exactly one', () => {
        expect(countLabel(1, 'message')).toBe('1 message');
        expect(countLabel(1, 'file')).toBe('1 file');
        expect(countLabel(1, 'channel')).toBe('1 channel');
    });

    it('uses the plural for everything else, zero included', () => {
        expect(countLabel(0, 'message')).toBe('0 messages');
        expect(countLabel(2, 'message')).toBe('2 messages');
        expect(countLabel(42, 'file')).toBe('42 files');
    });

    it('keeps the group separators toLocaleString applies', () => {
        expect(countLabel(1234567, 'message')).toBe('1,234,567 messages');
    });

    it('takes an explicit plural for irregular nouns', () => {
        expect(countLabel(1, 'entity', 'entities')).toBe('1 entity');
        expect(countLabel(3, 'entity', 'entities')).toBe('3 entities');
    });

    it('treats -1 as plural (it is not "one")', () => {
        expect(countLabel(-1, 'message')).toBe('-1 messages');
    });
});

describe('normalizeSqliteUtc', () => {
    it('appends Z and swaps the separator on a naive timestamp', () => {
        expect(normalizeSqliteUtc('2026-01-22 10:00:00')).toBe('2026-01-22T10:00:00Z');
    });

    it('leaves an already-zoned timestamp alone apart from the separator', () => {
        expect(normalizeSqliteUtc('2026-01-22 10:00:00Z')).toBe('2026-01-22T10:00:00Z');
        expect(normalizeSqliteUtc('2026-01-22T10:00:00+07:00')).toBe('2026-01-22T10:00:00+07:00');
    });
});

describe('scrollBehavior', () => {
    // jsdom ships no matchMedia at all, so install one. Saved/restored rather
    // than deleted — other suites in the same worker share this window.
    const realMatchMedia = window.matchMedia;

    function setReducedMotion(reduce: boolean): void {
        (window as unknown as { matchMedia: unknown }).matchMedia = (query: string) => ({
            matches: query === '(prefers-reduced-motion: reduce)' ? reduce : false,
            media: query,
            addEventListener: () => { /* unused */ },
            removeEventListener: () => { /* unused */ },
        });
    }

    afterEach(() => {
        (window as unknown as { matchMedia: unknown }).matchMedia = realMatchMedia;
    });

    it('is "smooth" when the user has not asked for reduced motion', () => {
        setReducedMotion(false);
        expect(prefersReducedMotion()).toBe(false);
        expect(scrollBehavior()).toBe('smooth');
    });

    it('is "auto" under prefers-reduced-motion', () => {
        // CSS cannot cover this: the `behavior` option beats the CSS
        // scroll-behavior property, so a hard-coded 'smooth' animated the whole
        // transcript past the viewport no matter what the stylesheet said.
        setReducedMotion(true);
        expect(prefersReducedMotion()).toBe(true);
        expect(scrollBehavior()).toBe('auto');
    });

    it('re-reads the query on every call (the setting can change at runtime)', () => {
        setReducedMotion(false);
        expect(scrollBehavior()).toBe('smooth');
        setReducedMotion(true);
        expect(scrollBehavior()).toBe('auto');
    });

    it('fails open when matchMedia is unavailable rather than throwing', () => {
        // This runs on the scroll hot path — a throw here would break
        // search-stepping and scroll-to-bottom, not just the preference.
        (window as unknown as { matchMedia: unknown }).matchMedia = undefined;
        expect(prefersReducedMotion()).toBe(false);
        expect(scrollBehavior()).toBe('smooth');
    });
});

describe('loadSettings — the AI avatar migration vs a deliberate removal', () => {
    // The bug: the migration that hands a pre-aiAvatar save the default Faust
    // portrait keyed off `!settings.aiAvatar`, which cannot tell "this blob is
    // older than the key" from "the user pressed Remove AI Avatar". So Remove
    // held until the next launch and then silently undid itself.
    const KEY = 'dashboard-settings';

    afterEach(() => {
        localStorage.clear();
    });

    async function loadFrom(blob: string): Promise<string> {
        localStorage.setItem(KEY, blob);
        const mod = await import('./shared.js');
        mod.loadSettings();
        return mod.settings.aiAvatar;
    }

    it('restores the default for a legacy blob that never had the key', async () => {
        expect(await loadFrom(JSON.stringify({ theme: 'dark' }))).not.toBe('');
    });

    it('honours an explicitly emptied avatar — Remove AI Avatar sticks', async () => {
        expect(await loadFrom(JSON.stringify({ theme: 'dark', aiAvatar: '' }))).toBe('');
    });

    it('leaves a custom avatar alone', async () => {
        const custom = 'data:image/png;base64,iVBORw0KGgo=';
        expect(await loadFrom(JSON.stringify({ aiAvatar: custom }))).toBe(custom);
    });

    it('survives a tampered blob that parses to a primitive (`in` would throw)', async () => {
        // JSON.parse('"nope"') is a string; `'aiAvatar' in "nope"` is a
        // TypeError, which would take the whole settings load down.
        await expect(loadFrom('"nope"')).resolves.toBeTypeOf('string');
        await expect(loadFrom('7')).resolves.toBeTypeOf('string');
        await expect(loadFrom('null')).resolves.toBeTypeOf('string');
    });
});
