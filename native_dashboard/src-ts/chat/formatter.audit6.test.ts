/**
 * Audit-6 regression tests for chat/formatter.ts — the second pass over the
 * markdown the renderer was showing as literal text.
 *
 *   - Task lists. `- [ ] thing` / `- [x] thing` put the brackets on screen. The
 *     marker now belongs to the item, drawn from CSS (<input> is not
 *     allow-listed, and a checkbox nobody can click would be worse than a drawn
 *     one), with the state also carried as visually-hidden text because the box
 *     is decorative to a screen reader.
 *   - Underscore emphasis. `__bold__` / `_em_` rendered literally, held back
 *     because the naive regex destroys snake_case. CommonMark's own rule — `_`
 *     cannot open or close emphasis intra-word — is the fix, so identifiers are
 *     safe and the syntax works.
 *   - Setext `Title\n=====` printed the underline. Only the `===` form is
 *     supported: `---` is already a horizontal rule here with a test pinning
 *     it, and a divider is the likelier intent for a row of dashes.
 *   - ATX closing sequences. `## Heading ##` kept its trailing hashes.
 *   - Nested blockquotes. `> > inner` kept one marker as literal text, because
 *     the pass wrapped each line once and then glued neighbours together —
 *     which flattened depth instead of nesting it.
 */

import { describe, it, expect, beforeAll } from 'vitest';

beforeAll(async () => {
    const DOMPurify = (await import('dompurify')).default;
    (window as unknown as { DOMPurify: unknown }).DOMPurify = DOMPurify(window);
});

import { formatMessage } from './formatter.js';

describe('formatMessage — task lists', () => {
    it('draws a checkbox instead of printing the brackets', () => {
        const html = formatMessage('- [ ] unchecked\n- [x] checked');
        expect(html).not.toContain('[ ]');
        expect(html).not.toContain('[x]');
        expect(html).toContain('<li class="task-item">');
        expect(html).toContain('<li class="task-item task-done">');
        expect(html).toContain('<span class="task-box" aria-hidden="true"></span>');
    });

    it('carries the state as text, since the box is hidden from a screen reader', () => {
        const html = formatMessage('- [ ] a\n- [x] b');
        expect(html).toContain('<span class="task-state">To do: </span>a');
        expect(html).toContain('<span class="task-state">Done: </span>b');
    });

    it('accepts a capital X', () => {
        expect(formatMessage('- [X] done')).toContain('task-done');
    });

    it('nests task items like any other list item', () => {
        const html = formatMessage('- [ ] parent\n  - [x] child');
        expect(html.match(/<ul>/g)).toHaveLength(2);
        expect(html).toContain('task-done');
    });

    it('leaves brackets that are not a task marker alone', () => {
        expect(formatMessage('- [note] not a task')).toBe('<ul><li>[note] not a task</li></ul>');
        expect(formatMessage('- [] empty')).toBe('<ul><li>[] empty</li></ul>');
    });
});

describe('formatMessage — underscore emphasis', () => {
    it('renders __bold__ and _em_', () => {
        expect(formatMessage('some __bold__ and _em_ text')).toBe(
            'some <strong>bold</strong> and <em>em</em> text',
        );
    });

    it('leaves snake_case identifiers completely alone', () => {
        // The whole reason this syntax was withheld. CommonMark's intra-word
        // rule is what makes it safe to add.
        expect(formatMessage('call my_var_name and other_thing_here')).toBe(
            'call my_var_name and other_thing_here',
        );
        expect(formatMessage('see /tmp/a_b_c/x.py')).toBe('see /tmp/a_b_c/x.py');
    });

    it('does not disturb the asterisk forms', () => {
        expect(formatMessage('**star** and *s*')).toBe('<strong>star</strong> and <em>s</em>');
    });

    it('does not corrupt the internal block placeholders', () => {
        // The placeholder tokens (\x00…\x04) are full of underscores; the
        // intra-word guard is what keeps the emphasis passes off them.
        const html = formatMessage('a `one` and `two` and ```\nx\n```');
        expect(html).toContain('<code>one</code>');
        expect(html).toContain('<code>two</code>');
        expect(html).toContain('code-block-wrapper');
        expect(html).not.toContain('<em>');
    });
});

describe('formatMessage — setext and ATX headings', () => {
    it('renders a === underline as an h1 instead of printing it', () => {
        expect(formatMessage('Title\n=====\n\nbody')).toBe(
            '<h1 class="md-heading">Title</h1>body',
        );
    });

    it('leaves --- as a horizontal rule, which is what it means here', () => {
        expect(formatMessage('before\n---\nafter')).toMatch(/<hr[^>]*>/);
    });

    it('does not underline something that already opened a block', () => {
        expect(formatMessage('# Already\n=====')).toContain('<h1 class="md-heading">Already</h1>');
        expect(formatMessage('- item\n=====')).toContain('<li>item</li>');
    });

    it('strips an ATX closing sequence', () => {
        expect(formatMessage('## Heading ##')).toBe('<h2 class="md-heading">Heading</h2>');
    });

    it('keeps a # that is not a closing sequence', () => {
        expect(formatMessage('## C#')).toBe('<h2 class="md-heading">C#</h2>');
        expect(formatMessage('## Tags #tag')).toBe('<h2 class="md-heading">Tags #tag</h2>');
    });
});

describe('formatMessage — nested blockquotes', () => {
    it('nests a quoted quote instead of leaking its marker', () => {
        const html = formatMessage('> outer\n> > inner');
        expect(html).not.toContain('&gt; inner');
        expect(html).toBe('<blockquote>outer<blockquote>inner</blockquote></blockquote>');
    });

    it('nests three levels', () => {
        expect(formatMessage('> l1\n> > l2\n> > > l3')).toBe(
            '<blockquote>l1<blockquote>l2<blockquote>l3</blockquote></blockquote></blockquote>',
        );
    });

    it('still merges same-level lines into one quote', () => {
        expect(formatMessage('> a\n> b')).toBe('<blockquote>a<br>b</blockquote>');
    });

    it('still turns a bare > continuation into a blank line inside the quote', () => {
        expect(formatMessage('> a\n>\n> b')).toBe('<blockquote>a<br><br>b</blockquote>');
    });

    it('comes back out to the outer quote after a nested one', () => {
        expect(formatMessage('> outer\n> > inner\n> back')).toBe(
            '<blockquote>outer<blockquote>inner</blockquote>back</blockquote>',
        );
    });
});
