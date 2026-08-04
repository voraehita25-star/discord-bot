/**
 * Audit-3 regression test for chat-manager.ts — the Files-modal filename tooltip.
 *
 * `.file-name` is `white-space: nowrap; overflow: hidden; text-overflow: ellipsis`
 * (styles.css) inside a `min-width: 0` flex body, so any name wider than the row
 * is cut with an ellipsis. It carried no `title`, which made the Files modal the
 * ONE file surface in the app where a truncated name could not be read back:
 *
 *   - the composer chip  (.attached-doc-preview) sets title={name}
 *   - the in-message chip (.message-doc-chip)    sets title={name}
 *   - the Settings paths rows                    set  title={path}
 *   - the Files modal row                        set  nothing
 *
 * Measured in the real UI at a 1280px window, a 118-char name rendered 476px of
 * an 856px string: the ellipsis eats the END, which is where the extension and
 * any `-v2-FINAL` suffix live — precisely what tells two uploads of the same
 * document apart before you hit an irreversible Delete.
 *
 * Same harness as chat-manager.audit2.test.ts (real ChatManager, Tauri invoke
 * mocked, DOMPurify stubbed) so the assertion runs against the shipped template.
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

const FILES_DOM = `
    <div id="toast-container"></div>
    <div id="chat-files-modal">
        <span id="chat-files-subtitle"></span>
        <div id="chat-files-list"></div>
        <div id="chat-files-empty" class="hidden"></div>
        <span id="chat-files-badge" class="hidden"></span>
        <div id="chat-files-list-view"></div>
        <div id="chat-files-edit-view" class="hidden">
            <input id="chat-files-edit-name">
            <textarea id="chat-files-edit-text"></textarea>
            <span id="chat-files-edit-counter"></span>
        </div>
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

function callRender(cm: ReturnType<typeof mkCm>, convId: string, docs: unknown[]): void {
    (cm.renderChatFilesModal as (id: string, docs: unknown) => void)(convId, docs);
}

function nameEls(): HTMLElement[] {
    return Array.from(document.querySelectorAll<HTMLElement>('.chat-file-row .file-name'));
}

const LONG_NAME =
    'a-really-extremely-long-document-filename-that-nobody-would-ever-actually-use-'
    + 'but-here-we-are-anyway-final-v2-FINAL.md';

describe('renderChatFilesModal — truncated filename stays readable', () => {
    it('gives every row a title carrying the full, untruncated filename', () => {
        const cm = mkCm('c1');
        callRender(cm, 'c1', [
            { id: 1, file_kind: 'pdf', filename: 'character_sheet.pdf', char_count: 12, page_count: 1, created_at: '' },
            { id: 2, file_kind: 'text', filename: LONG_NAME, char_count: 480000, page_count: null, created_at: '' },
        ]);
        const names = nameEls();
        expect(names).toHaveLength(2);
        expect(names[0].getAttribute('title')).toBe('character_sheet.pdf');
        // The whole 118-char name, not the visible prefix — the tooltip is the
        // only way back to the extension the ellipsis hides.
        expect(names[1].getAttribute('title')).toBe(LONG_NAME);
        expect(names[1].getAttribute('title')).toMatch(/-v2-FINAL\.md$/);
    });

    it('keeps the title and the visible text in sync', () => {
        const cm = mkCm('c1');
        callRender(cm, 'c1', [
            { id: 3, file_kind: 'text', filename: LONG_NAME, char_count: 1, page_count: null, created_at: '' },
        ]);
        const el = nameEls()[0];
        // A tooltip that disagreed with the label would be worse than none at
        // all — it is the value a user reads before pressing Delete.
        expect(el.getAttribute('title')).toBe(el.textContent);
    });

    it('escapes the title so a hostile filename cannot break out of the attribute', () => {
        const cm = mkCm('c1');
        // `filename` comes from a WS frame with no runtime validation; a raw
        // interpolation of this value would close title="" and inject a handler.
        const hostile = '" onmouseover="alert(1)" data-x="<img src=x onerror=alert(2)>.txt';
        callRender(cm, 'c1', [
            { id: 4, file_kind: 'text', filename: hostile, char_count: 1, page_count: null, created_at: '' },
        ]);
        const el = nameEls()[0];
        // Parsed back out of the DOM the value is the literal string — proof the
        // quotes stayed inside the attribute rather than terminating it.
        expect(el.getAttribute('title')).toBe(hostile);
        expect(el.getAttribute('onmouseover')).toBeNull();
        expect(document.querySelector('.chat-file-row img')).toBeNull();
    });

    it('survives a `documents` field that is not an array at all', () => {
        const cm = mkCm('c1');
        const badge = document.getElementById('chat-files-badge')!;
        // Every field in this frame is guarded, but the CONTAINER was only
        // `(data.documents as ChatFileEntry[]) || []` — a truthy non-array walks
        // straight through. `docs.length` is then undefined, so the badge printed
        // the string "undefined" and stayed visible (`undefined <= 0` is false),
        // and the very next `docs.reduce` threw out of handleMessage.
        for (const documents of [{ 0: { id: 1 } }, 'nope', 42, true]) {
            expect(() => cm.handleMessage({
                type: 'conversation_documents', conversation_id: 'c1', documents,
            } as unknown as Record<string, unknown>)).not.toThrow();
            expect(badge.textContent).not.toBe('undefined');
            expect(badge.classList.contains('hidden')).toBe(true);
        }
    });

    it('survives a non-array `documents` on the document_saved frame too', () => {
        const cm = mkCm('c1');
        expect(() => cm.handleMessage({
            type: 'document_saved', conversation_id: 'c1', documents: { filename: 'x' },
        } as unknown as Record<string, unknown>)).not.toThrow();
    });

    it('renders a title even for a malformed (non-string) filename', () => {
        const cm = mkCm('c1');
        // Mirrors audit2: file_kind/filename are coerced with String(x ?? '')
        // before use, so the tooltip must be an empty string, never "null".
        callRender(cm, 'c1', [
            { id: 5, file_kind: 'pdf', filename: null, char_count: 1, page_count: null, created_at: '' },
        ]);
        const el = nameEls()[0];
        expect(el.getAttribute('title')).toBe('');
        expect(el.getAttribute('title')).not.toBe('null');
    });
});

describe('openChatFileEditor — the editor reports a dead socket', () => {
    it('replaces the Loading… placeholder when the request could not be sent', () => {
        const cm = mkCm('c1');
        // The socket can die AFTER the list rendered (a bot restart), which is
        // the only way to have a row to click Edit on with nothing to answer it.
        // The content frame then never arrives and the editor used to sit on
        // 'Loading…' forever — the same dead-end openChatFilesModal already
        // handles for the list view's subtitle.
        cm.wsClient.send = vi.fn().mockReturnValue(false);
        cm.openChatFileEditor(7);
        const ta = document.getElementById('chat-files-edit-text') as HTMLTextAreaElement;
        expect(ta.placeholder).not.toBe('Loading…');
        expect(ta.placeholder).toMatch(/not connected/i);
    });

    it('keeps the Loading… placeholder while the request is in flight', () => {
        const cm = mkCm('c1');
        cm.wsClient.send = vi.fn().mockReturnValue(true);
        cm.openChatFileEditor(7);
        const ta = document.getElementById('chat-files-edit-text') as HTMLTextAreaElement;
        expect(ta.placeholder).toBe('Loading…');
    });
});
