/**
 * Audit-2 regression tests for chat/formatter.ts.
 *
 * Covers two findings:
 *   - dash-ts-chat-M1: splitTrailingPunctuation was O(n^2) over a trailing
 *     balanced-paren run (re-`match()`-ed the growing prefix each iteration),
 *     freezing the render thread for seconds on a long bare URL. The fix uses
 *     running counters (single pass). We assert a long balanced-paren URL
 *     formats within a few ms AND that paren-balancing semantics are unchanged.
 *   - dash-ts-chat-1: degraded/fail-closed formatMessage output (DOMPurify
 *     momentarily missing) was written to the content-keyed cache and served
 *     stale after DOMPurify recovered. The fix only memoizes on the happy path.
 *     The happy-path memo is asserted OBSERVABLY (spy on DOMPurify.sanitize and
 *     prove it runs once across two identical calls) — a bare `second===first`
 *     check would pass even with caching off, since formatMessage is pure.
 *
 * Uses the real DOMPurify bundle (same approach as formatter.test.ts) so the
 * sanitize/paren behavior is production-accurate.
 */

import { describe, it, expect, beforeAll, vi } from 'vitest';

beforeAll(async () => {
    const DOMPurify = (await import('dompurify')).default;
    (window as unknown as { DOMPurify: unknown }).DOMPurify = DOMPurify(window);
});

import { formatMessage } from './formatter.js';

type WinWithPurify = { DOMPurify: unknown };

describe('formatMessage — dash-ts-chat-M1 (O(n^2) paren-balancing DoS)', () => {
    it('formats a long balanced-paren bare URL within a few ms (no quadratic blowup)', () => {
        // BARE_URL_RE captures '(' and ')' as URL chars, so a balanced-paren run
        // glued to a bare https:// URL reaches the paren-balance scan. 30k parens
        // (~60KB) took ~3.5s with the old O(n^2) loop; the O(n) fix is sub-ms.
        const N = 30000;
        const url = 'https://example.com/' + '('.repeat(N) + ')'.repeat(N);
        const content = 'see ' + url;
        const t0 = performance.now();
        const html = formatMessage(content);
        const elapsed = performance.now() - t0;
        // Generous bound: the fix is ~single-digit ms; the old code was seconds.
        // 250ms still fails the quadratic path (30k was 3477ms) while leaving
        // ample headroom for slow CI.
        expect(elapsed).toBeLessThan(250);
        // Sanity: it produced a sanitized anchor for the URL.
        expect(html).toContain('<a href="https://example.com/');
    });

    it('formats a long balanced-paren markdown link within a few ms', () => {
        const N = 30000;
        const inner = 'https://example.com/' + '('.repeat(N) + ')'.repeat(N);
        const content = `[link](${inner})`;
        const t0 = performance.now();
        const html = formatMessage(content);
        const elapsed = performance.now() - t0;
        expect(elapsed).toBeLessThan(250);
        expect(html).toContain('<a href="https://example.com/');
    });

    it('keeps a single balanced trailing ) inside the URL (Wikipedia-style)', () => {
        // The fix must preserve the original semantics: a ')' closing an earlier
        // '(' is part of the URL, not stripped as sentence punctuation.
        const html = formatMessage('https://en.wikipedia.org/wiki/Foo_(bar)');
        expect(html).toContain('href="https://en.wikipedia.org/wiki/Foo_(bar)"');
    });

    it('strips an unmatched trailing ) (and a sentence dot) out of the URL', () => {
        // "(see https://x.com/a)." — the ')' is unmatched within the captured URL
        // and must be split off so the link is not a broken 404.
        const html = formatMessage('(see https://x.com/a).');
        expect(html).toContain('href="https://x.com/a"');
        // The unmatched ')' and the '.' must not be inside the href.
        expect(html).not.toContain('href="https://x.com/a)');
        expect(html).not.toContain('href="https://x.com/a).');
    });
});

describe('formatMessage — dash-ts-chat-1 (no caching of fail-closed output)', () => {
    it('re-renders markdown after DOMPurify recovers (degraded output not memoized)', () => {
        const win = window as unknown as WinWithPurify;
        const realPurify = win.DOMPurify;
        // Unique content so we don't collide with any cache entry from another test.
        const content = '**audit2-recover-' + Math.random().toString(36).slice(2) + '**';
        try {
            // 1. Yank DOMPurify -> fail-closed path returns escaped plain text.
            win.DOMPurify = undefined;
            const degraded = formatMessage(content);
            expect(degraded).not.toContain('<strong>');
        } finally {
            // 2. Restore DOMPurify.
            win.DOMPurify = realPurify;
        }
        // 3. Same content again -> must RE-RENDER (real <strong>), proving the
        //    degraded value was never written to the cache.
        const recovered = formatMessage(content);
        expect(recovered).toContain('<strong>');
        expect(recovered).not.toBe('');
    });

    it('memoizes happy-path output: DOMPurify.sanitize runs ONCE across two identical calls', () => {
        // The previous version only asserted `second === first`, which passes even
        // with caching DISABLED because formatMessage is a pure function of its
        // input — so it didn't actually prove the memo. Make the cache OBSERVABLE
        // by spying on DOMPurify.sanitize: the uncached path calls it exactly once
        // per format, so a working cache means it fires ONCE across two identical
        // calls (the 2nd call short-circuits on the cache hit before sanitizing).
        const win = window as unknown as { DOMPurify: { sanitize: (...a: unknown[]) => string } };
        const purify = win.DOMPurify;
        const spy = vi.spyOn(purify, 'sanitize');
        try {
            // Unique content so a prior test's cache entry can't pre-satisfy the hit.
            const content = '**audit2-cache-' + Math.random().toString(36).slice(2) + '**';
            const first = formatMessage(content);
            const callsAfterFirst = spy.mock.calls.length;
            const second = formatMessage(content);
            // 1st call sanitizes; 2nd is served from cache without re-sanitizing.
            expect(callsAfterFirst).toBe(1);
            expect(spy.mock.calls.length).toBe(1);
            // Same string still comes back, and it's the real sanitized markdown.
            expect(second).toBe(first);
            expect(first).toContain('<strong>');
        } finally {
            spy.mockRestore();
        }
    });
});
