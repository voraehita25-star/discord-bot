/**
 * Audit-4 regression tests for chat/formatter.ts.
 *
 * Two rendering-correctness findings (NO security impact — DOMPurify stays the
 * authoritative gate):
 *   - code-fence lang: the fenced-code extractor used ```(\w*)\n, and \w cannot
 *     match '+' / '#' / '-', so ```c++ / ```c# / ```objective-c fences failed to
 *     match at all. The block was never turned into a code card; the stray
 *     backticks survived and the inline-code fallback garbled the output (and any
 *     $…$ inside the block was eaten as LaTeX). Fixed by widening the lang class
 *     to [\w+#.-]* (the label is still sanitized to [A-Za-z0-9_-] afterwards).
 *   - heading newline: the ATX-heading passes used ^#{n}\s+(.+)$ with the m flag;
 *     \s matches a newline, so a bare "##" line promoted the FOLLOWING line into
 *     a heading. Fixed by requiring horizontal whitespace ([ \t]+).
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

describe('formatMessage — code-fence languages with non-\\w tags', () => {
    it('extracts a ```c++ block into a code card instead of garbling it', () => {
        const html = formatMessage('```c++\nint main(){ return 0; }\n```');
        expect(html).toContain('code-block-wrapper');
        expect(html).toMatch(/<pre><code class="language-c[^"]*">/);
        expect(html).toContain('int main');
        // No stray literal fence and no inline-code fallback garble.
        expect(html).not.toContain('```');
    });

    it('extracts a ```c# block into a code card', () => {
        const html = formatMessage('```c#\nvar x = 1;\n```');
        expect(html).toContain('code-block-wrapper');
        expect(html).toContain('var x = 1;');
        expect(html).not.toContain('```');
    });

    it('extracts a ```objective-c block (hyphenated lang)', () => {
        const html = formatMessage('```objective-c\nNSLog(@"hi");\n```');
        expect(html).toContain('code-block-wrapper');
        expect(html).toMatch(/<pre><code class="language-objective-c">/);
        expect(html).not.toContain('```');
    });

    it('keeps $…$ inside a ```c++ block literal (not eaten as LaTeX math)', () => {
        const html = formatMessage('```c++\nauto s = "$PATH costs $5";\n```');
        expect(html).toContain('code-block-wrapper');
        expect(html).toContain('$PATH costs $5');
        expect(html).not.toContain('math-inline');
    });

    it('NO-REGRESSION: a plain ```python block still renders', () => {
        const html = formatMessage('```python\nprint(1)\n```');
        expect(html).toMatch(/<pre><code class="language-python">/);
        expect(html).toContain('print(1)');
    });
});

describe('formatMessage — bare ATX heading marker does not promote the next line', () => {
    it('does NOT turn the line after a bare "##" into a heading', () => {
        const html = formatMessage('##\nHello world');
        expect(html).not.toContain('<h2');
        expect(html).toContain('Hello world');
    });

    it('does NOT turn the line after a bare "#" into a heading', () => {
        const html = formatMessage('#\nJust a paragraph');
        expect(html).not.toContain('<h1');
        expect(html).toContain('Just a paragraph');
    });

    it('NO-REGRESSION: "## Heading" (with space) still becomes an h2', () => {
        const html = formatMessage('## Heading');
        expect(html).toContain('<h2 class="md-heading">Heading</h2>');
    });

    it('NO-REGRESSION: "# Title" (with space) still becomes an h1', () => {
        const html = formatMessage('# Title');
        expect(html).toContain('<h1 class="md-heading">Title</h1>');
    });
});
