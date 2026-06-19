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

    it('blocks javascript: URL in markdown link syntax (not rendered as <a>)', () => {
        const html = formatMessage('click [me](javascript:alert(1))');
        // Only https:// links are linkified — a javascript: URL never becomes
        // a live anchor (the markdown-link regex simply doesn't match it).
        expect(html).not.toMatch(/<a\s+href=["']?javascript/i);
    });

    it('does not linkify an http:// (non-https) markdown link as a live href', () => {
        const html = formatMessage('see [here](http://insecure.example.com)');
        // http:// is intentionally not linkified; DOMPurify would strip the
        // href anyway. No live anchor pointing at an http: URL.
        expect(html).not.toMatch(/<a\s+href=["']?http:/i);
    });

    it('strips a data: URL from a markdown link (DOMPurify https-only gate)', () => {
        const html = formatMessage('[x](data:text/html,<script>alert(1)</script>)');
        expect(html).not.toMatch(/<a\s+href=["']?data:/i);
    });
});

describe('formatMessage — markdown links', () => {
    it('renders [text](https://url) as an anchor with the right text + href', () => {
        const html = formatMessage('go to [Anthropic](https://www.anthropic.com)');
        expect(html).toMatch(/<a [^>]*href="https:\/\/www\.anthropic\.com"[^>]*>Anthropic<\/a>/);
    });

    it('forces target=_blank and rel=noopener noreferrer on links', () => {
        const html = formatMessage('[ai](https://example.com/page)');
        expect(html).toMatch(/target="_blank"/);
        expect(html).toMatch(/rel="noopener noreferrer"/);
    });

    it('autolinks a bare https:// URL', () => {
        const html = formatMessage('visit https://example.com for more');
        expect(html).toMatch(/<a [^>]*href="https:\/\/example\.com"[^>]*>https:\/\/example\.com<\/a>/);
    });

    it('does not swallow trailing sentence punctuation into the autolink', () => {
        const html = formatMessage('see https://example.com.');
        // The trailing period stays OUTSIDE the anchor.
        expect(html).toMatch(/href="https:\/\/example\.com"/);
        expect(html).not.toMatch(/href="https:\/\/example\.com\."/);
    });

    it('does not double-wrap a URL already inside a markdown link', () => {
        const html = formatMessage('[click](https://example.com/path)');
        // Exactly one anchor — the bare-URL pass must not re-wrap the href/text.
        const anchorCount = (html.match(/<a /g) || []).length;
        expect(anchorCount).toBe(1);
    });

    it('keeps a balanced closing paren inside a markdown-link href (Wikipedia case)', () => {
        const html = formatMessage('[wiki](https://en.wikipedia.org/wiki/Foo_(bar))');
        // The ')' that closes '(bar' belongs to the URL — it must NOT be stripped.
        expect(html).toContain('href="https://en.wikipedia.org/wiki/Foo_(bar)"');
    });

    it('keeps a balanced closing paren inside a bare autolinked URL', () => {
        const html = formatMessage('see https://en.wikipedia.org/wiki/Foo_(bar) now');
        expect(html).toMatch(/href="https:\/\/en\.wikipedia\.org\/wiki\/Foo_\(bar\)"/);
    });

    it('still strips a trailing sentence period after a balanced-paren URL', () => {
        const html = formatMessage('see https://en.wikipedia.org/wiki/Foo_(bar).');
        // ')' kept (balanced), '.' dropped (sentence punctuation).
        expect(html).toContain('href="https://en.wikipedia.org/wiki/Foo_(bar)"');
        expect(html).not.toMatch(/href="[^"]*\)\."/);
    });

    it('does not linkify a URL inside a fenced code block', () => {
        const html = formatMessage('```\ncurl https://example.com\n```');
        // URLs in code stay literal — no anchor inside the <pre><code>.
        expect(html).not.toMatch(/<a [^>]*href=/);
        expect(html).toContain('https://example.com');
    });

    it('does not linkify a URL inside inline code', () => {
        const html = formatMessage('run `https://example.com` now');
        expect(html).not.toMatch(/<a [^>]*href=/);
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

    it('keeps the data-code-copy attribute (with the code) through DOMPurify', () => {
        // Regression: DOMPurify drops data-* unless ALLOW_DATA_ATTR is true.
        // ADD_ATTR/ALLOWED_ATTR don't whitelist data-*, so if this regresses the
        // per-block copy button loses data-code-copy and the handler copies ''.
        const html = formatMessage('```js\nconst answer = 42;\n```');
        expect(html).toContain('data-code-copy=');
        // The actual code (escaped) must live inside the attribute.
        expect(html).toMatch(/data-code-copy="[^"]*const answer = 42;[^"]*"/);
    });

    it('does not treat $ inside a code block as LaTeX (shell vars survive)', () => {
        // Regression: code blocks are extracted BEFORE the LaTeX passes, so the
        // inline-LaTeX regex must not consume `$HOME and $` and corrupt the code.
        const html = formatMessage('```bash\necho $HOME and $USER\n```');
        expect(html).toContain('language-bash');
        expect(html).not.toContain('math-inline');
        expect(html).toContain('echo $HOME and $USER');
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
        // Alignment is emitted as CSS classes (md-ta-*) rather than inline
        // style="text-align:…" so the chat body needs no inline-style CSP grant.
        expect(html).toMatch(/md-ta-left/);
        expect(html).toMatch(/md-ta-center/);
        expect(html).toMatch(/md-ta-right/);
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
