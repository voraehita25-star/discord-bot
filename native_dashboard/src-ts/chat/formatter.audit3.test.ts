/**
 * Audit-3 regression tests for chat/formatter.ts.
 *
 * Covers two low-severity rendering-correctness findings (NO security impact —
 * DOMPurify stays the authoritative gate; hrefs stay pinned to /^https:/i):
 *   - dash-ts-chat-L2: a markdown link whose visible label contains inline tags
 *     (bold / italic / inline-code, emitted by the earlier passes) PLUS a bare
 *     https:// URL defeated PROTECTED_SPLIT_RE's [^<]* anchor-body matcher —
 *     [^<]* stops at the first nested '<', never reaches </a>, so the anchor
 *     went unprotected and the in-label URL got double-wrapped into its own <a>
 *     (rendered as two sibling links after DOMPurify de-nested them). The fix
 *     makes the anchor body lazy ([\s\S]*? up to the first </a>).
 *   - dash-ts-chat-L3: splitTrailingPunctuation only walked a leading ')' run,
 *     so a '.' immediately before a balanced ')' at the very end of a URL (e.g.
 *     .../page(v1.) ) made the walk exit on the '.' and strip the balanced ')'.
 *     The fix walks the ENTIRE trailing run with a keep-cursor.
 *
 * Uses the real DOMPurify bundle (same approach as formatter.audit2.test.ts) so
 * the sanitize/de-nesting behavior is production-accurate.
 */

import { describe, it, expect, beforeAll } from 'vitest';

beforeAll(async () => {
    const DOMPurify = (await import('dompurify')).default;
    (window as unknown as { DOMPurify: unknown }).DOMPurify = DOMPurify(window);
});

import { formatMessage } from './formatter.js';

describe('formatMessage — dash-ts-chat-L2 (inline-tagged link label + bare URL)', () => {
    it('renders exactly ONE anchor and keeps the in-label URL inert (bold label)', () => {
        const html = formatMessage('[**Docs** see https://evil.com](https://good.com)');
        expect((html.match(/<a /g) || []).length).toBe(1);
        expect(html).toContain('href="https://good.com"');
        expect(html).not.toMatch(/href="https:\/\/evil\.com"/);
        expect(html).toContain('<strong>Docs</strong>');
    });

    it('renders exactly ONE anchor when the label has inline `code` + a bare URL', () => {
        const html = formatMessage('[`code` https://evil.com](https://good.com)');
        expect((html.match(/<a /g) || []).length).toBe(1);
        expect(html).not.toMatch(/href="https:\/\/evil\.com"/);
    });

    it('OVER-PROTECTION GUARD: a bare URL after a real link is still autolinked', () => {
        // Proves the lazy anchor body stops at the FIRST </a> and does not merge
        // the trailing bare URL into the protected span.
        const html = formatMessage('[x](https://good.com) then https://after.com');
        expect((html.match(/<a /g) || []).length).toBe(2);
        expect(html).toMatch(/href="https:\/\/after\.com"/);
    });
});

describe('formatMessage — dash-ts-chat-L3 (balanced ) preceded by . at URL end)', () => {
    it('keeps a balanced ) even when a . immediately precedes it (bare URL)', () => {
        const html = formatMessage('see https://site.example/page(v1.)');
        expect(html).toContain('href="https://site.example/page(v1.)"');
    });

    it('keeps a balanced ) preceded by . in a markdown link URL', () => {
        const html = formatMessage('[v](https://site.example/page(v1.))');
        expect(html).toContain('href="https://site.example/page(v1.)"');
    });

    it('NO-REGRESSION: still strips a bare trailing .', () => {
        const html = formatMessage('see https://site.example/page.');
        expect(html).toContain('href="https://site.example/page"');
        expect(html).not.toMatch(/href="[^"]*page\."/);
    });

    it('NO-REGRESSION: still strips an unmatched ) and trailing .', () => {
        const html = formatMessage('(see https://site.example/a).');
        expect(html).toContain('href="https://site.example/a"');
        expect(html).not.toContain('href="https://site.example/a)');
    });
});
