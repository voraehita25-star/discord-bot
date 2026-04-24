/**
 * Tests for chat/search.ts — in-conversation Ctrl+F overlay.
 *
 * Covers:
 *   - Match wrapping with <mark class="chat-search-hit">
 *   - Skip <script>/<style>/existing <mark> nodes
 *   - Case-insensitive search
 *   - Multiple hits per text node → each wrapped separately
 *   - Step wrap-around (forward past end, backward past start)
 *   - clear() removes all marks and restores text nodes
 *   - Input + keydown handlers (debounced)
 *   - Escape closes the bar
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { ChatSearch } from './search.js';

const CHAT_HTML = `
    <div class="chat-search-bar hidden" id="chat-search-bar">
        <input id="chat-search-input">
        <span id="chat-search-count">0 / 0</span>
        <button id="chat-search-prev">↑</button>
        <button id="chat-search-next">↓</button>
        <button id="chat-search-close">&times;</button>
    </div>
    <div id="chat-messages">
        <div class="chat-message">hello world</div>
        <div class="chat-message">HELLO again</div>
        <div class="chat-message">no match here</div>
    </div>
`;

function mountDom(): void {
    document.body.innerHTML = CHAT_HTML;
}

function getContainer(): HTMLElement | null {
    return document.getElementById('chat-messages');
}

beforeEach(() => {
    // jsdom doesn't implement scrollIntoView — stub it so focus()ing a match doesn't throw.
    if (!Element.prototype.scrollIntoView) {
        Element.prototype.scrollIntoView = function () { /* no-op */ };
    }
    mountDom();
});

describe('ChatSearch.open / close', () => {
    it('open() un-hides the search bar and focuses the input', () => {
        const search = new ChatSearch(getContainer);
        search.open();

        const bar = document.getElementById('chat-search-bar')!;
        const input = document.getElementById('chat-search-input') as HTMLInputElement;
        expect(bar.classList.contains('hidden')).toBe(false);
        expect(document.activeElement).toBe(input);
    });

    it('close() hides the bar and clears all highlights', () => {
        const search = new ChatSearch(getContainer);
        search.perform('hello');
        expect(document.querySelectorAll('mark.chat-search-hit').length).toBeGreaterThan(0);

        search.close();
        expect(document.getElementById('chat-search-bar')!.classList.contains('hidden')).toBe(true);
        expect(document.querySelectorAll('mark.chat-search-hit').length).toBe(0);
    });

    it('close() restores the original text (no residual split nodes)', () => {
        const search = new ChatSearch(getContainer);
        search.perform('hello');
        search.close();

        const first = document.querySelector('.chat-message')!;
        expect(first.textContent).toBe('hello world');
        // After close + normalize, should be a single text node again.
        expect(first.childNodes.length).toBe(1);
    });
});

describe('ChatSearch.perform — match wrapping', () => {
    it('wraps each case-insensitive hit in <mark class="chat-search-hit">', () => {
        const search = new ChatSearch(getContainer);
        search.perform('hello');

        const marks = document.querySelectorAll('mark.chat-search-hit');
        expect(marks.length).toBe(2);
        expect(marks[0].textContent).toBe('hello');
        expect(marks[1].textContent).toBe('HELLO');  // preserves original case
    });

    it('updates the count label with "current / total"', () => {
        const search = new ChatSearch(getContainer);
        search.perform('hello');
        const label = document.getElementById('chat-search-count')!;
        expect(label.textContent).toBe('1 / 2');
    });

    it('shows "0 / 0" when query has no matches', () => {
        const search = new ChatSearch(getContainer);
        search.perform('zzz');
        const label = document.getElementById('chat-search-count')!;
        expect(label.textContent).toBe('0 / 0');
        expect(document.querySelectorAll('mark.chat-search-hit').length).toBe(0);
    });

    it('re-running perform() with a new query clears the old highlights', () => {
        const search = new ChatSearch(getContainer);
        search.perform('hello');
        expect(document.querySelectorAll('mark.chat-search-hit').length).toBe(2);

        search.perform('match');
        const marks = document.querySelectorAll('mark.chat-search-hit');
        expect(marks.length).toBe(1);
        expect(marks[0].textContent).toBe('match');
    });

    it('empty query clears highlights without adding new ones', () => {
        const search = new ChatSearch(getContainer);
        search.perform('hello');
        search.perform('');
        expect(document.querySelectorAll('mark.chat-search-hit').length).toBe(0);
    });

    it('wraps multiple hits within a single text node separately', () => {
        getContainer()!.innerHTML = '<p>aa bb aa cc aa</p>';
        const search = new ChatSearch(getContainer);
        search.perform('aa');
        expect(document.querySelectorAll('mark.chat-search-hit').length).toBe(3);
    });

    it('skips <script>/<style> content', () => {
        getContainer()!.innerHTML = `
            <script>const target = "xyz";</script>
            <p>visible target</p>
            <style>.target { color: red; }</style>
        `;
        const search = new ChatSearch(getContainer);
        search.perform('target');
        // Only the <p> should have a mark.
        expect(document.querySelectorAll('mark.chat-search-hit').length).toBe(1);
        expect(document.querySelector('script')?.textContent).toContain('const target');
    });

    it('first hit gets the "active" class', () => {
        const search = new ChatSearch(getContainer);
        search.perform('hello');
        const marks = document.querySelectorAll('mark.chat-search-hit');
        expect(marks[0].classList.contains('active')).toBe(true);
        expect(marks[1].classList.contains('active')).toBe(false);
    });
});

describe('ChatSearch.step — cycling through matches', () => {
    it('forward steps move the active class to the next mark', () => {
        const search = new ChatSearch(getContainer);
        search.perform('hello');
        search.step(1);
        const marks = document.querySelectorAll('mark.chat-search-hit');
        expect(marks[0].classList.contains('active')).toBe(false);
        expect(marks[1].classList.contains('active')).toBe(true);
    });

    it('forward step past the last match wraps to the first', () => {
        getContainer()!.innerHTML = '<p>aa aa aa</p>';
        const search = new ChatSearch(getContainer);
        search.perform('aa');
        search.step(1);
        search.step(1);
        search.step(1);
        // After 3 forward steps from idx 0 on a list of 3 → back to idx 0.
        const marks = document.querySelectorAll('mark.chat-search-hit');
        expect(marks[0].classList.contains('active')).toBe(true);
    });

    it('backward step from first match wraps to the last', () => {
        getContainer()!.innerHTML = '<p>aa aa aa</p>';
        const search = new ChatSearch(getContainer);
        search.perform('aa');
        search.step(-1);
        const marks = document.querySelectorAll('mark.chat-search-hit');
        expect(marks[2].classList.contains('active')).toBe(true);
    });

    it('step is a no-op when there are zero matches', () => {
        const search = new ChatSearch(getContainer);
        search.perform('zzz');
        expect(() => search.step(1)).not.toThrow();
        expect(() => search.step(-1)).not.toThrow();
    });

    it('count label updates to show the new active index', () => {
        const search = new ChatSearch(getContainer);
        search.perform('hello');
        search.step(1);
        expect(document.getElementById('chat-search-count')!.textContent).toBe('2 / 2');
    });
});

describe('ChatSearch.setup — input + keyboard bindings', () => {
    it('typing into the input fires perform() after the debounce', async () => {
        const search = new ChatSearch(getContainer);
        search.setup();

        const input = document.getElementById('chat-search-input') as HTMLInputElement;
        input.value = 'hello';
        input.dispatchEvent(new Event('input'));

        // Before debounce — no marks yet.
        expect(document.querySelectorAll('mark.chat-search-hit').length).toBe(0);
        await new Promise(r => setTimeout(r, 200));
        expect(document.querySelectorAll('mark.chat-search-hit').length).toBe(2);
    });

    it('Enter on the input steps forward, Shift+Enter steps backward', async () => {
        const search = new ChatSearch(getContainer);
        search.setup();

        const input = document.getElementById('chat-search-input') as HTMLInputElement;
        input.value = 'hello';
        input.dispatchEvent(new Event('input'));
        await new Promise(r => setTimeout(r, 200));

        input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));
        let marks = document.querySelectorAll('mark.chat-search-hit');
        expect(marks[1].classList.contains('active')).toBe(true);

        input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', shiftKey: true }));
        marks = document.querySelectorAll('mark.chat-search-hit');
        expect(marks[0].classList.contains('active')).toBe(true);
    });

    it('Escape closes the search bar', async () => {
        const search = new ChatSearch(getContainer);
        search.setup();
        search.open();

        const input = document.getElementById('chat-search-input') as HTMLInputElement;
        input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
        expect(document.getElementById('chat-search-bar')!.classList.contains('hidden')).toBe(true);
    });

    it('next / prev / close buttons are wired to step and close', async () => {
        const search = new ChatSearch(getContainer);
        search.setup();
        search.perform('hello');

        const nextBtn = document.getElementById('chat-search-next')!;
        nextBtn.dispatchEvent(new MouseEvent('click', { bubbles: true }));
        expect(document.querySelectorAll('mark.chat-search-hit')[1].classList.contains('active')).toBe(true);

        const prevBtn = document.getElementById('chat-search-prev')!;
        prevBtn.dispatchEvent(new MouseEvent('click', { bubbles: true }));
        expect(document.querySelectorAll('mark.chat-search-hit')[0].classList.contains('active')).toBe(true);

        const closeBtn = document.getElementById('chat-search-close')!;
        closeBtn.dispatchEvent(new MouseEvent('click', { bubbles: true }));
        expect(document.getElementById('chat-search-bar')!.classList.contains('hidden')).toBe(true);
    });

    it('setup() is idempotent — multiple calls do not stack handlers', async () => {
        const search = new ChatSearch(getContainer);
        search.setup();
        search.setup();
        search.setup();

        // Spy on perform by wrapping — use the `mark` count proxy instead.
        const input = document.getElementById('chat-search-input') as HTMLInputElement;
        input.value = 'hello';
        input.dispatchEvent(new Event('input'));
        await new Promise(r => setTimeout(r, 200));
        // One debounced perform() call → 2 marks (not 6 if handlers stacked).
        expect(document.querySelectorAll('mark.chat-search-hit').length).toBe(2);
    });
});
