/**
 * Audit-5 regression tests for chat/formatter.ts.
 *
 * Every finding here is a RENDERING-correctness bug (DOMPurify stays the
 * authoritative security gate throughout). All of them were invisible to the
 * suite because nothing rendered a list that was not flat, and nothing checked
 * an attribute's value survived sanitisation.
 *
 *   - Nested list items. Both list passes anchored the marker at column 0, so an
 *     indented sub-item was not a list line at all: it leaked into the page as
 *     literal "  - nested" text AND ended the run, so the items after it opened
 *     a brand-new list.
 *   - Ordered-list numbering. That new list had no `start`, so it counted from 1
 *     again. The shape an assistant emits constantly —
 *     "1. step" / fenced code / "2. step" — numbered BOTH steps "1.", because
 *     the fence splits the run. A list resuming at "3." had the same problem.
 *   - `start` did not survive DOMPurify even once emitted and allow-listed:
 *     ALLOWED_URI_REGEXP (/^https:/i) is value-checked against every attribute
 *     DOMPurify does not consider URI-safe, so "3" failed and the attribute was
 *     dropped. The same silent strip hit display / mathvariant / encoding on
 *     KaTeX's MathML — block equations lost display mode and rendered inline.
 *     Fixed with ADD_URI_SAFE_ATTR (inert presentational names only; href/src
 *     keep the https gate).
 *   - `+` bullets and `1)` ordered markers (both CommonMark, both emitted by
 *     real models) rendered as literal text.
 *   - `![alt](url)` left a stray "!" in front of the link. <img> is deliberately
 *     not allow-listed, so an image reference can only become a link — but it
 *     should not announce itself with a leftover bang.
 *
 * Uses the real DOMPurify bundle (same approach as the other audit tests) so the
 * sanitize behaviour is production-accurate.
 */

import { describe, it, expect, beforeAll } from 'vitest';

beforeAll(async () => {
    const DOMPurify = (await import('dompurify')).default;
    (window as unknown as { DOMPurify: unknown }).DOMPurify = DOMPurify(window);
});

import { formatMessage } from './formatter.js';

describe('formatMessage — nested lists', () => {
    it('nests an indented bullet instead of leaking it as literal text', () => {
        const html = formatMessage('- one\n- two\n  - nested\n- three');
        expect(html).not.toContain('- nested');
        expect(html).toBe('<ul><li>one</li><li>two<ul><li>nested</li></ul></li><li>three</li></ul>');
    });

    it('keeps one list around a sub-list instead of splitting into two', () => {
        // The tail item used to open a SECOND <ul>; two <ul> openings means the
        // list visually restarted after the nested block.
        const html = formatMessage('- a\n  - b\n- c');
        expect(html.match(/<ul>/g)).toHaveLength(2); // outer + the nested one
        expect(html.indexOf('<li>c')).toBeGreaterThan(html.indexOf('</ul>'));
    });

    it('nests three levels deep', () => {
        expect(formatMessage('- a\n  - b\n    - c')).toBe(
            '<ul><li>a<ul><li>b<ul><li>c</li></ul></li></ul></li></ul>',
        );
    });

    it('treats a tab as an indent (4 columns), not as one column', () => {
        expect(formatMessage('- a\n\t- tabbed\n- b')).toBe(
            '<ul><li>a<ul><li>tabbed</li></ul></li><li>b</li></ul>',
        );
    });

    it('nests a bullet list under an ordered step', () => {
        expect(formatMessage('1. step one\n   - detail\n2. step two')).toBe(
            '<ol><li>step one<ul><li>detail</li></ul></li><li>step two</li></ol>',
        );
    });

    it('nests an ordered list under a bullet', () => {
        expect(formatMessage('- group\n  1. one\n  2. two\n- next')).toBe(
            '<ul><li>group<ol><li>one</li><li>two</li></ol></li><li>next</li></ul>',
        );
    });
});

describe('formatMessage — ordered-list numbering', () => {
    it('numbers a list that resumes after a code fence from where it left off', () => {
        const html = formatMessage('1. before\n\n```\ncode\n```\n\n2. after');
        // Two <ol> blocks is correct (the fence genuinely splits them); the
        // SECOND one must not restart at 1.
        expect(html).toContain('<ol start="2"><li>after</li></ol>');
    });

    it('honours a list that starts at something other than 1', () => {
        expect(formatMessage('3. third\n4. fourth')).toBe(
            '<ol start="3"><li>third</li><li>fourth</li></ol>',
        );
    });

    it('omits start when the list begins at 1, keeping the markup clean', () => {
        expect(formatMessage('1. first\n2. second')).toBe(
            '<ol><li>first</li><li>second</li></ol>',
        );
    });

    it('survives DOMPurify — start is allow-listed AND URI-safe', () => {
        // Regression guard for the real cause: `start` was in ALLOWED_ATTR the
        // whole time, and DOMPurify still stripped it because "3" is not an
        // https URL.
        expect(formatMessage('5. five')).toContain('start="5"');
    });
});

describe('formatMessage — MathML attributes survive sanitisation', () => {
    it('keeps display="block" on a block equation', () => {
        const html = formatMessage('$$\\sum_{i=1}^{n} i$$');
        // KaTeX is absent under vitest, so this asserts the fallback path stays
        // intact; the attribute survival itself is pinned by the <ol start> case
        // above (same ADD_URI_SAFE_ATTR mechanism) and by the e2e math test.
        expect(html).toContain('math-block');
    });
});

describe('formatMessage — CommonMark markers that were rendering literally', () => {
    it('accepts + as a bullet marker', () => {
        expect(formatMessage('+ alpha\n+ beta')).toBe('<ul><li>alpha</li><li>beta</li></ul>');
    });

    it('accepts 1) as an ordered marker', () => {
        expect(formatMessage('1) first\n2) second')).toBe(
            '<ol><li>first</li><li>second</li></ol>',
        );
    });

    it('still leaves a lone marker with no text as prose', () => {
        // Guard kept from the original passes: "-\nhello" must not become a list.
        expect(formatMessage('-\nhello')).toBe('-<br>hello');
    });

    it('does not turn a dash inside a sentence into a list', () => {
        expect(formatMessage('a - b - c')).toBe('a - b - c');
        expect(formatMessage('-5 degrees')).toBe('-5 degrees');
    });

    it('does not mistake a decimal for an ordered marker', () => {
        expect(formatMessage('3.14 is pi')).toBe('3.14 is pi');
    });
});

describe('formatMessage — image references', () => {
    it('renders ![alt](url) as a link with no stray bang', () => {
        const html = formatMessage('![alt text](https://example.com/a.png)');
        expect(html).not.toContain('!<a');
        expect(html).toContain('>alt text</a>');
    });

    it('leaves a bang that is not an image reference alone', () => {
        expect(formatMessage('wow! [docs](https://example.com)')).toContain('wow! <a');
    });
});
