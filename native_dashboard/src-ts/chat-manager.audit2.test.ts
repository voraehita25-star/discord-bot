/**
 * Audit-2 regression test for chat-manager.ts.
 *
 * dash-ts-app-3: renderChatFilesModal mapped `docs` (a TYPE CAST of an
 * untrusted WS frame, no runtime validation) and called d.file_kind.toUpperCase()
 * and chatFileIconFor(d.file_kind, d.filename) (which does name.slice(...)) on
 * RAW values. A non-string file_kind/filename (null/number/object) threw a
 * TypeError that aborted the whole docs.map — leaving the Files modal blank with
 * no error surfaced. The fix coerces with String(... ?? '') before any string
 * method, mirroring the failover/health-check renderers. The same blank-modal
 * bug class also reached the NUMERIC fields: a malformed char_count/page_count
 * (Object.create(null) / a string) is truthy under `(x || 0)`, so a later
 * .toLocaleString() threw — the fix coerces those with Number(...) || 0 too.
 *
 * We instantiate a real ChatManager (Tauri invoke mocked, DOMPurify stubbed —
 * same approach as chat-manager.test.ts) and drive renderChatFilesModal with a
 * malformed frame, asserting it does NOT throw and that valid rows still render.
 */

import { describe, it, expect, beforeAll, beforeEach, vi } from 'vitest';

vi.mock('@tauri-apps/api/core', () => ({ invoke: vi.fn().mockResolvedValue('') }));

beforeAll(async () => {
    const DOMPurify = (await import('dompurify')).default;
    (window as unknown as { DOMPurify: unknown }).DOMPurify = DOMPurify(window);
    if (!Element.prototype.scrollIntoView) {
        Element.prototype.scrollIntoView = function () { /* no-op */ };
    }
    if (!Element.prototype.scrollTo) {
        Element.prototype.scrollTo = function () { /* no-op */ } as unknown as typeof Element.prototype.scrollTo;
    }
});

// Minimal DOM: the chat-files modal nodes renderChatFilesModal reads, plus the
// toast container ChatManager's constructor/helpers may touch.
const FILES_DOM = `
    <div id="toast-container"></div>
    <div id="chat-files-modal">
        <span id="chat-files-subtitle"></span>
        <div id="chat-files-list"></div>
        <div id="chat-files-empty" class="hidden"></div>
        <span id="chat-files-badge" class="hidden"></span>
    </div>
`;

let ChatManager: typeof import('./chat-manager.js').ChatManager;

beforeAll(async () => {
    const mod = await import('./chat-manager.js');
    ChatManager = mod.ChatManager;
});

beforeEach(() => {
    document.body.innerHTML = FILES_DOM;
});

type AnyConv = import('./chat-manager.js').ChatManager['currentConversation'];

function mkCm(convId: string) {
    document.body.innerHTML = FILES_DOM;
    const cm = new ChatManager();
    cm.wsClient.send = vi.fn();
    cm.currentConversation = { id: convId } as unknown as NonNullable<AnyConv>;
    return cm;
}

// renderChatFilesModal is typed as (id, ChatFileEntry[]) but parses untrusted
// JSON at runtime — cast a deliberately-malformed payload through `unknown`.
function callRender(cm: ReturnType<typeof mkCm>, convId: string, docs: unknown[]): void {
    (cm.renderChatFilesModal as (id: string, docs: unknown) => void)(convId, docs);
}

describe('renderChatFilesModal — dash-ts-app-3 (malformed frame coercion)', () => {
    it('does NOT throw when file_kind/filename are non-string (null/number/object)', () => {
        const cm = mkCm('c1');
        const malformed = [
            { id: 1, file_kind: null, filename: 123, char_count: 10, page_count: null, created_at: '' },
            { id: 2, file_kind: 42, filename: { x: 1 }, char_count: 5, page_count: 2, created_at: '' },
            { id: 3, file_kind: undefined, filename: undefined, char_count: 0, page_count: null, created_at: '' },
        ];
        expect(() => callRender(cm, 'c1', malformed)).not.toThrow();
        const list = document.getElementById('chat-files-list')!;
        // The list must NOT be blank — every malformed row still produced a row
        // (coerced to '' rather than throwing and aborting the whole map).
        expect((list.innerHTML.match(/class="chat-file-row"/g) ?? []).length).toBe(3);
    });

    it('renders a valid row that follows a malformed one (one bad row does not blank the list)', () => {
        const cm = mkCm('c1');
        const docs = [
            // Malformed first row — pre-fix this threw and aborted the map.
            { id: 1, file_kind: null, filename: null, char_count: 0, page_count: null, created_at: '' },
            // Valid row that must still appear.
            { id: 2, file_kind: 'pdf', filename: 'report.pdf', char_count: 1234, page_count: 3, created_at: '' },
        ];
        callRender(cm, 'c1', docs);
        const list = document.getElementById('chat-files-list')!;
        expect((list.innerHTML.match(/class="chat-file-row"/g) ?? []).length).toBe(2);
        // The valid row's data survived (filename + uppercased kind in the meta).
        expect(list.innerHTML).toContain('report.pdf');
        expect(list.innerHTML).toContain('PDF');
        // data-id attributes for both rows are present.
        expect(list.innerHTML).toContain('data-id="1"');
        expect(list.innerHTML).toContain('data-id="2"');
    });

    it('does NOT throw when char_count/page_count are non-numeric (object/string)', () => {
        const cm = mkCm('c1');
        // char_count as a null-prototype object is the worst case: `(x || 0)` is
        // truthy so returns the object, and the old `.toLocaleString()` call on it
        // throws a TypeError that aborts the whole map and blanks the modal. The
        // Number(...) || 0 coercion must turn each into a real number first.
        const malformed = [
            { id: 1, file_kind: 'pdf', filename: 'a.pdf', char_count: Object.create(null), page_count: Object.create(null), created_at: '' },
            { id: 2, file_kind: 'text', filename: 'b.md', char_count: 'not-a-number', page_count: 'also-bad', created_at: '' },
            { id: 3, file_kind: 'pdf', filename: 'c.pdf', char_count: { toLocaleString: undefined }, page_count: {}, created_at: '' },
        ];
        expect(() => callRender(cm, 'c1', malformed)).not.toThrow();
        const list = document.getElementById('chat-files-list')!;
        // All three rows must still render (no throw aborting the map).
        expect((list.innerHTML.match(/class="chat-file-row"/g) ?? []).length).toBe(3);
        // The subtitle's total-chars sum is also Number()-coerced — non-numeric
        // counts collapse to 0, so the sum is "0" (never NaN, never a throw).
        const subtitle = document.getElementById('chat-files-subtitle')!;
        expect(subtitle.textContent).toContain('0 chars in persistent memory');
        // A non-numeric page_count must coerce to 0 -> the "page(s)" chip is
        // omitted, never rendered as "[object Object] page(s)" or "NaN page(s)".
        expect(list.innerHTML).not.toContain('page(s)');
        expect(list.innerHTML).not.toContain('NaN');
        expect(list.innerHTML).not.toContain('[object Object]');
    });

    it('still renders a normal well-formed frame correctly', () => {
        const cm = mkCm('c1');
        const docs = [
            { id: 7, file_kind: 'text', filename: 'notes.md', char_count: 50, page_count: null, created_at: '' },
        ];
        callRender(cm, 'c1', docs);
        const list = document.getElementById('chat-files-list')!;
        expect(list.innerHTML).toContain('notes.md');
        expect(list.innerHTML).toContain('TEXT');
        expect(list.innerHTML).toContain('data-id="7"');
    });
});
