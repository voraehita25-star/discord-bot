/**
 * Tests for chat/document-attach.ts — the pure, testable helpers.
 *
 * Focus is on clampTextToCap(): the post-decode 500,000-char guard that keeps a
 * multi-byte text file (which can pass the coarse 32 MB byte check yet decode to
 * far more than the backend's char cap) in sync with what the backend accepts.
 * The FileReader-driven attach() flow itself is exercised by the e2e suite.
 */

import { describe, it, expect } from 'vitest';
import { clampTextToCap } from './document-attach.js';

const CAP = 500_000;

describe('clampTextToCap', () => {
    it('leaves a short string untouched and reports not-truncated', () => {
        const r = clampTextToCap('hello world');
        expect(r.data).toBe('hello world');
        expect(r.truncated).toBe(false);
        expect(r.originalLength).toBe('hello world'.length);
    });

    it('leaves a string exactly at the cap untouched', () => {
        const text = 'a'.repeat(CAP);
        const r = clampTextToCap(text);
        expect(r.truncated).toBe(false);
        expect(r.data.length).toBe(CAP);
        expect(r.data).toBe(text);
    });

    it('truncates a string one char over the cap to exactly the cap', () => {
        const text = 'a'.repeat(CAP + 1);
        const r = clampTextToCap(text);
        expect(r.truncated).toBe(true);
        expect(r.data.length).toBe(CAP);
        expect(r.originalLength).toBe(CAP + 1);
    });

    it('truncates a much-larger string and preserves the leading content', () => {
        const text = 'x'.repeat(CAP + 12_345);
        const r = clampTextToCap(text);
        expect(r.truncated).toBe(true);
        expect(r.data.length).toBe(CAP);
        expect(r.originalLength).toBe(CAP + 12_345);
        // The kept slice is the FRONT of the file (head), not the tail.
        expect(r.data).toBe(text.slice(0, CAP));
    });

    it('handles an empty string', () => {
        const r = clampTextToCap('');
        expect(r.data).toBe('');
        expect(r.truncated).toBe(false);
        expect(r.originalLength).toBe(0);
    });

    it('does not leave a lone high surrogate when an emoji straddles the cap', () => {
        // '😀' (U+1F600) is the surrogate pair 😀. Place the FIRST half
        // exactly on the last kept code unit (index CAP-1): a naive slice(0, CAP)
        // would keep \uD83D alone, which serialises to U+FFFD and corrupts the
        // emoji. The clamp must drop that dangling half.
        const text = 'a'.repeat(CAP - 1) + '😀😀😀';  // length CAP + 5, > cap
        const r = clampTextToCap(text);
        expect(r.truncated).toBe(true);
        expect(r.originalLength).toBe(CAP + 5);
        // One extra unit dropped to avoid splitting the pair.
        expect(r.data.length).toBe(CAP - 1);
        const lastUnit = r.data.charCodeAt(r.data.length - 1);
        // Last kept unit must NOT be a high surrogate (0xD800–0xDBFF).
        expect(lastUnit >= 0xd800 && lastUnit <= 0xdbff).toBe(false);
        // No replacement character introduced by re-encoding a lone surrogate.
        expect(r.data).not.toContain('�');
    });

    it('keeps a whole emoji that ends exactly on the cap boundary', () => {
        // Here the pair sits fully inside the kept region (low surrogate is the
        // last kept unit), so nothing is dropped beyond the normal cut.
        const text = 'a'.repeat(CAP - 2) + '😀' + 'bbbb';  // emoji fully within cap
        const r = clampTextToCap(text);
        expect(r.truncated).toBe(true);
        // Full cap kept; the boundary fell after the low surrogate, no split.
        expect(r.data.length).toBe(CAP);
        const lastUnit = r.data.charCodeAt(r.data.length - 1);
        expect(lastUnit >= 0xd800 && lastUnit <= 0xdbff).toBe(false);
        expect(r.data).not.toContain('�');
        // The emoji survived intact.
        expect(r.data.endsWith('😀')).toBe(true);
    });
});
