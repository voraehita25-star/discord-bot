/**
 * Tests for chat/formatter.ts — Markdown + LaTeX + fenced code → sanitized HTML.
 *
 * Uses the real DOMPurify bundle (imported from jsdom's node-friendly dist)
 * so sanitize behavior is production-accurate. KaTeX is NOT loaded — the
 * formatter falls back to `$...$` escape, which is still a safe/visible state
 * and what we'd want to test anyway.
 *
 * Key invariants:
 *   1. `<script>` injection in user content becomes inert text.
 *   2. onerror=/onclick= attributes are stripped.
 *   3. Fenced code blocks preserve their content (escaped) + get a copy button.
 *   4. Inline markdown (**bold**, *em*, `code`, # headings) renders to tags.
 *   5. Tables + lists render to the right structure.
 *   6. stripThinkTags removes <think>…</think> blocks.
 */

import { describe, it, expect, beforeAll } from 'vitest';

// DOMPurify doesn't auto-load in jsdom, so require the npm build explicitly
// and attach to window before formatter.ts's getPurify() call.
beforeAll(async () => {
    const DOMPurify = (await import('dompurify')).default;
    (window as unknown as { DOMPurify: unknown }).DOMPurify = DOMPurify(window);
});

// Import AFTER DOMPurify is attached.
import { formatMessage, stripThinkTags } from './formatter.js';

describe('stripThinkTags', () => {
    it('removes a single <think> block', () => {
        expect(stripThinkTags('<think>reasoning</think>answer')).toBe('answer');
    });

    it('removes multiple <think> blocks', () => {
        expect(stripThinkTags('<think>a</think>one<think>b</think>two')).toBe('onetwo');
    });

    it('handles multiline <think> content', () => {
        const input = '<think>step 1\nstep 2\nstep 3</think>final answer';
        expect(stripThinkTags(input)).toBe('final answer');
    });

    it('leaves text without <think> untouched (just trims)', () => {
        expect(stripThinkTags('  plain answer  ')).toBe('plain answer');
    });
});

describe('formatMessage — security', () => {
    it('neutralizes <script> injection', () => {
        const malicious = '<script>alert("xss")</script>hello';
        const html = formatMessage(malicious);
        expect(html).not.toContain('<script>');
        expect(html).toContain('hello');
    });

    it('neutralizes onerror= and onclick= attributes (escaped as text)', () => {
        // Raw HTML in input is escaped BEFORE markdown parsing, so the
        // onerror= attribute ends up as the text "onerror=&quot;alert(1)&quot;",
        // not an active event handler. We assert the <img tag is escaped
        // (rendered as literal text) — that's what protects from XSS.
        const html = formatMessage('<img src=x onerror="alert(1)">');
        // The img tag is escaped — no active <img> element in the output.
        expect(html).toMatch(/&lt;img/);
        // And no RAW onerror attribute (would look like `onerror="...">` inside a tag).
        // The escaped `onerror=&quot;` form is fine (literal text).
        expect(html).not.toMatch(/<[^>]+\sonerror\s*=/i);
    });

    it('blocks javascript: URL in markdown image syntax (escaped as text)', () => {
        const html = formatMessage('click [me](javascript:alert(1))');
        // We don't render markdown links to <a>, so this stays as text.
        expect(html).not.toMatch(/<a\s+href=["']?javascript/i);
    });
});

describe('formatMessage — inline markdown', () => {
    it('renders **bold** to <strong>', () => {
        expect(formatMessage('**emphasis**')).toContain('<strong>emphasis</strong>');
    });

    it('renders *em* to <em>', () => {
        expect(formatMessage('*slanted*')).toContain('<em>slanted</em>');
    });

    it('renders `code` to inline <code>', () => {
        const html = formatMessage('`const x = 1`');
        expect(html).toContain('<code>const x = 1</code>');
    });

    it('renders # Heading as <h1>', () => {
        expect(formatMessage('# Big Title')).toMatch(/<h1[^>]*>Big Title<\/h1>/);
    });

    it('renders ### for h3', () => {
        expect(formatMessage('### Sub')).toMatch(/<h3[^>]*>Sub<\/h3>/);
    });

    it('renders --- as a horizontal rule', () => {
        expect(formatMessage('before\n---\nafter')).toMatch(/<hr[^>]*>/);
    });
});

describe('formatMessage — fenced code blocks', () => {
    it('wraps ```lang blocks in a code-block-wrapper with a copy button', () => {
        const html = formatMessage('```python\nprint("hi")\n```');
        expect(html).toContain('code-block-wrapper');
        expect(html).toContain('code-block-header');
        expect(html).toContain('code-copy-btn');
        expect(html).toContain('class="code-lang"');  // language label span
        expect(html).toContain('language-python');
    });

    it('falls back to "code" class when no language specified', () => {
        const html = formatMessage('```\nno lang\n```');
        expect(html).toContain('language-code');
    });

    it('keeps content escaped inside the code block', () => {
        const html = formatMessage('```\n<script>alert(1)</script>\n```');
        expect(html).not.toContain('<script>alert(1)</script>');
        // Escaped form should be present.
        expect(html).toMatch(/&lt;script&gt;|alert\(1\)/);
    });
});

describe('formatMessage — LaTeX fallback (no KaTeX)', () => {
    it('preserves block LaTeX visibly when KaTeX is not loaded', () => {
        const html = formatMessage('$$x^2 + y^2 = z^2$$');
        // Without KaTeX, we render `$$...$$` as an escaped math-block div.
        expect(html).toContain('math-block');
    });

    it('preserves inline LaTeX visibly when KaTeX is not loaded', () => {
        const html = formatMessage('Pythagoras: $a^2 + b^2 = c^2$ is famous');
        expect(html).toContain('math-inline');
    });
});

describe('formatMessage — tables', () => {
    it('renders a valid markdown table to <table>', () => {
        const src = [
            '| h1 | h2 |',
            '|----|----|',
            '| a  | b  |',
            '| c  | d  |',
        ].join('\n');
        const html = formatMessage(src);
        expect(html).toContain('md-table');
        expect(html).toContain('<th');
        expect(html).toContain('<td');
        expect(html).toContain('>a<');
        expect(html).toContain('>d<');
    });

    it('honors alignment markers', () => {
        const src = [
            '| L | C | R |',
            '|:--|:-:|--:|',
            '| 1 | 2 | 3 |',
        ].join('\n');
        const html = formatMessage(src);
        expect(html).toMatch(/text-align:\s*left/);
        expect(html).toMatch(/text-align:\s*center/);
        expect(html).toMatch(/text-align:\s*right/);
    });
});

describe('formatMessage — lists', () => {
    it('renders a simple unordered list', () => {
        const html = formatMessage('- apples\n- oranges\n- pears');
        expect(html).toContain('<ul>');
        expect(html).toContain('<li>apples</li>');
        expect(html).toContain('<li>pears</li>');
    });

    it('renders an ordered list', () => {
        const html = formatMessage('1. first\n2. second\n3. third');
        expect(html).toContain('<ol>');
        expect(html).toContain('<li>first</li>');
        expect(html).toContain('<li>third</li>');
    });
});

describe('formatMessage — newline handling', () => {
    it('converts single newlines to <br>', () => {
        expect(formatMessage('line 1\nline 2')).toMatch(/line 1<br>line 2/);
    });

    it('treats double newlines as a paragraph break', () => {
        const html = formatMessage('para 1\n\npara 2');
        expect(html).toContain('paragraph-break');
    });
});

describe('formatMessage — blockquotes', () => {
    it('wraps > prefixed lines in <blockquote>', () => {
        const html = formatMessage('> quoted line');
        expect(html).toContain('<blockquote>');
    });
});
