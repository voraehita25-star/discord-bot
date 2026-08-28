/**
 * Audit-7 regressions for chat-manager.ts.
 *
 * Six independent defects found by driving the real WS server + the real CLI
 * backend end-to-end (a stand-in `claude` binary speaking the stream-json
 * protocol) rather than by reading the file:
 *
 *  1. `stream_end` with an empty `full_response` was finalized into a message.
 *     BOTH backends gate their assistant-row save on a non-empty response
 *     (`if DB_AVAILABLE and conversation_id and full_response`), so the pushed
 *     bubble was blank, carried live Copy/Edit/Delete buttons, vanished on the
 *     next reload, and rode into the following turn's `history` as an empty
 *     assistant reply. Reproduced with a CLI that emits `system:init` and then
 *     exits without a text block.
 *  2. A stop that landed before any text arrived still claimed "the reply so
 *     far was kept" — nothing was kept, and nothing was persisted.
 *  3. `conversation_loaded.truncated` — set by handle_load_conversation when
 *     the frame exceeds its wire budget and the OLDEST messages are dropped —
 *     had no consumer, so a shortened transcript looked complete.
 *  4. `conversation_created.persisted:false` — set when the DB write failed —
 *     had no consumer, so the user got a normal-looking conversation that
 *     silently evaporated on restart.
 *  5. pin/like frames carried no `conversation_id`; the server-side UPDATE
 *     matched on message id alone, so a client in conversation B could toggle
 *     a message owned by conversation A (verified against a real SQLite DB).
 *  6. `regenerateAfterEdit` replayed abandoned failed-send bubbles as real
 *     history turns; `sendMessage` already filters them.
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

const DOM = `
    <div id="toast-container"></div>
    <div id="chat-empty"></div>
    <div id="chat-container" class="hidden"></div>
    <h3 id="chat-title"></h3>
    <img id="chat-role-avatar" class="hidden" alt="AI">
    <span id="chat-role-name"></span>
    <span id="chat-connection-status"></span>
    <select id="chat-ai-provider"><option value="gemini">G</option><option value="claude">C</option></select>
    <input type="checkbox" id="thinking-toggle">
    <input type="checkbox" id="chat-unrestricted">
    <input type="checkbox" id="chat-use-search">
    <input type="checkbox" id="chat-write-mode">
    <div id="context-window-indicator" style="display:none">
        <div id="context-bar-fill"></div><span id="context-bar-label"></span>
    </div>
    <input type="text" id="conversation-filter-input">
    <div id="conversation-list"></div>
    <div id="chat-tags"></div>
    <div class="chat-messages-wrapper">
        <div id="chat-messages"></div>
        <button id="scroll-to-bottom-fab" class="hidden"><span id="scroll-new-count"></span></button>
    </div>
    <div class="chat-input-area">
        <button id="btn-attach"></button>
        <textarea id="chat-input"></textarea>
        <button id="btn-send"></button>
        <button id="btn-stop-generating" class="hidden"></button>
    </div>
    <span id="chat-files-badge" class="hidden"></span>
    <div id="new-chat-modal" class="modal"><div class="modal-overlay"></div></div>
`;

let ChatManager: typeof import('./chat-manager.js').ChatManager;

beforeAll(async () => {
    ChatManager = (await import('./chat-manager.js')).ChatManager;
});

beforeEach(() => {
    document.body.innerHTML = DOM;
});

type Conv = NonNullable<import('./chat-manager.js').ChatManager['currentConversation']>;

function mkCm(convId = 'conv-1') {
    document.body.innerHTML = DOM;
    const cm = new ChatManager();
    cm.wsClient.send = vi.fn().mockReturnValue(true);
    cm.currentConversation = {
        id: convId, role_preset: 'general', title: 't',
    } as unknown as Conv;
    return cm;
}

function toasts(): string[] {
    return Array.from(document.querySelectorAll('#toast-container *'))
        .map(el => el.textContent || '')
        .filter(Boolean);
}

function sentFrames(cm: import('./chat-manager.js').ChatManager): Record<string, unknown>[] {
    return (cm.wsClient.send as unknown as { mock: { calls: unknown[][] } })
        .mock.calls.map(c => c[0] as Record<string, unknown>);
}

// ---------------------------------------------------------------------------
// 1 + 2. Empty stream_end
// ---------------------------------------------------------------------------

describe('stream_end with an empty full_response', () => {
    function startStream(cm: import('./chat-manager.js').ChatManager): void {
        cm.handleMessage({ type: 'stream_start', conversation_id: 'conv-1', mode: '' });
    }

    it('does NOT push a blank assistant message', () => {
        const cm = mkCm();
        startStream(cm);
        expect(document.getElementById('streaming-message')).not.toBeNull();

        cm.handleMessage({
            type: 'stream_end',
            conversation_id: 'conv-1',
            full_response: '',
            assistant_message_id: null,
        });

        expect(cm.messages).toHaveLength(0);
        expect(document.getElementById('streaming-message')).toBeNull();
        expect(cm.isStreaming).toBe(false);
    });

    it('tells the user the reply was empty instead of leaving a blank bubble', () => {
        const cm = mkCm();
        startStream(cm);
        cm.handleMessage({ type: 'stream_end', conversation_id: 'conv-1', full_response: '' });
        expect(toasts().join(' ')).toContain('empty reply');
    });

    it('does not claim a stopped turn "kept" a reply that never started', () => {
        const cm = mkCm();
        startStream(cm);
        cm.handleMessage({
            type: 'stream_end', conversation_id: 'conv-1', full_response: '', cancelled: true,
        });
        const text = toasts().join(' ');
        expect(text).not.toContain('reply so far was kept');
        expect(text).toContain('Stopped before the reply started');
        expect(cm.messages).toHaveLength(0);
    });

    it('still keeps (and announces) a stopped turn that DID stream text', () => {
        const cm = mkCm();
        startStream(cm);
        cm.handleMessage({
            type: 'stream_end', conversation_id: 'conv-1',
            full_response: 'half an answer', cancelled: true,
        });
        expect(cm.messages).toHaveLength(1);
        expect(cm.messages[0].content).toBe('half an answer');
        expect(toasts().join(' ')).toContain('reply so far was kept');
    });

    it('still finalizes a normal non-empty response', () => {
        const cm = mkCm();
        startStream(cm);
        cm.handleMessage({
            type: 'stream_end', conversation_id: 'conv-1',
            full_response: 'a real answer', assistant_message_id: 7,
        });
        expect(cm.messages).toHaveLength(1);
        expect(cm.messages[0].role).toBe('assistant');
        expect(cm.messages[0].id).toBe(7);
    });
});

// ---------------------------------------------------------------------------
// 3. conversation_loaded.truncated
// ---------------------------------------------------------------------------

describe('conversation_loaded truncation notice', () => {
    it('warns when the server dropped the oldest messages', () => {
        const cm = mkCm();
        cm.handleMessage({
            type: 'conversation_loaded',
            conversation: { id: 'conv-1', role_preset: 'general' },
            messages: [{ role: 'user', content: 'hi', created_at: '2026-01-01 00:00:00' }],
            truncated: true,
        });
        expect(toasts().join(' ')).toContain('too large to load');
    });

    it('stays silent for a complete transcript', () => {
        const cm = mkCm();
        cm.handleMessage({
            type: 'conversation_loaded',
            conversation: { id: 'conv-1', role_preset: 'general' },
            messages: [],
        });
        expect(toasts().join(' ')).not.toContain('too large to load');
    });
});

// ---------------------------------------------------------------------------
// 4. conversation_created.persisted
// ---------------------------------------------------------------------------

describe('conversation_created persistence notice', () => {
    it('warns when the conversation row was not written to the DB', () => {
        const cm = mkCm();
        cm.handleMessage({
            type: 'conversation_created', id: 'conv-new',
            role_preset: 'general', persisted: false,
        });
        expect(toasts().join(' ')).toContain('could not be saved to the database');
    });

    it('stays silent when the row persisted', () => {
        const cm = mkCm();
        cm.handleMessage({
            type: 'conversation_created', id: 'conv-new',
            role_preset: 'general', persisted: true,
        });
        expect(toasts().join(' ')).not.toContain('could not be saved');
    });
});

// ---------------------------------------------------------------------------
// 5. pin/like conversation scope
// ---------------------------------------------------------------------------

describe('pin/like frames carry the conversation scope', () => {
    function renderOneMessage(cm: import('./chat-manager.js').ChatManager): void {
        cm.messages = [{
            role: 'assistant', content: 'x', created_at: '2026-01-01 00:00:00', id: 42,
        }];
        cm.renderMessages();
    }

    it('pin_message includes conversation_id', () => {
        const cm = mkCm();
        Object.defineProperty(cm.wsClient, 'connected', { value: true, configurable: true });
        renderOneMessage(cm);
        document.querySelector<HTMLElement>('.pin-message-btn')?.click();
        const pin = sentFrames(cm).find(f => f.type === 'pin_message');
        expect(pin).toBeDefined();
        expect(pin?.conversation_id).toBe('conv-1');
    });

    it('like_message includes conversation_id', () => {
        const cm = mkCm();
        Object.defineProperty(cm.wsClient, 'connected', { value: true, configurable: true });
        renderOneMessage(cm);
        document.querySelector<HTMLElement>('.like-message-btn')?.click();
        const like = sentFrames(cm).find(f => f.type === 'like_message');
        expect(like).toBeDefined();
        expect(like?.conversation_id).toBe('conv-1');
    });

    it('sends nothing when no conversation is open', () => {
        const cm = mkCm();
        renderOneMessage(cm);
        cm.currentConversation = null;
        document.querySelector<HTMLElement>('.pin-message-btn')?.click();
        document.querySelector<HTMLElement>('.like-message-btn')?.click();
        expect(sentFrames(cm).filter(
            f => f.type === 'pin_message' || f.type === 'like_message',
        )).toHaveLength(0);
    });
});

// ---------------------------------------------------------------------------
// 7. Inline editor: closing restores the bubble it was opened on
//
// Closing an inline editor is a pure DOM operation, but cancelEdit(idx)
// re-derives the element from `idx - visibleStartIdx`. The two halves of that
// mapping go stale independently: the ARRAY index shifts when a stream ends and
// trimLocalMessages() slices off the front past 200, while `visibleStartIdx`
// only moves on the next renderMessages(). The Save handler's "nothing changed"
// branch fed it a freshly RESOLVED array index, so after such a shift it
// repainted the NEIGHBOUR's bubble with this message's text and left the
// editor open. Both close paths now restore by element.
// ---------------------------------------------------------------------------

describe('inline edit close paths', () => {
    function seed(cm: import('./chat-manager.js').ChatManager): void {
        cm.messages = [
            { role: 'user', content: 'first', created_at: '2026-01-01 00:00:00', id: 1 },
            { role: 'user', content: 'second', created_at: '2026-01-01 00:01:00', id: 2 },
            { role: 'user', content: 'third', created_at: '2026-01-01 00:02:00', id: 3 },
        ];
        cm.renderMessages();
    }

    function bubbleTexts(): string[] {
        return Array.from(document.querySelectorAll('.chat-message .message-content'))
            .map(el => (el.textContent || '').trim());
    }

    it('Save with no change restores the edited bubble, not its neighbour', () => {
        const cm = mkCm();
        seed(cm);
        cm.startEditMessage(2);
        expect(document.querySelectorAll('.edit-textarea')).toHaveLength(1);

        // A completed stream pushing past MAX_LOCAL_MESSAGES trims the front of
        // the array WITHOUT re-rendering: index 2 no longer names this message,
        // while the DOM and visibleStartIdx are unchanged.
        cm.messages.shift();

        // Text untouched → the "nothing changed, just close" branch.
        document.querySelector<HTMLElement>('.edit-save-btn')?.click();

        expect(document.querySelectorAll('.edit-textarea')).toHaveLength(0);
        expect(bubbleTexts()).toEqual(['first', 'second', 'third']);
        expect(sentFrames(cm).some(f => f.type === 'edit_message')).toBe(false);
    });

    it('Cancel closes the editor and restores the original text', () => {
        const cm = mkCm();
        seed(cm);
        cm.startEditMessage(1);
        const ta = document.querySelector<HTMLTextAreaElement>('.edit-textarea');
        if (ta) ta.value = 'a draft the user abandoned';
        cm.messages.shift();

        document.querySelector<HTMLElement>('.edit-cancel-btn')?.click();

        expect(document.querySelectorAll('.edit-textarea')).toHaveLength(0);
        expect(bubbleTexts()).toEqual(['first', 'second', 'third']);
    });

    it('Escape closes the editor the same way Cancel does', () => {
        const cm = mkCm();
        seed(cm);
        cm.startEditMessage(2);

        const ta = document.querySelector<HTMLTextAreaElement>('.edit-textarea');
        ta?.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));

        expect(document.querySelectorAll('.edit-textarea')).toHaveLength(0);
        expect(bubbleTexts()).toEqual(['first', 'second', 'third']);
    });
});

// ---------------------------------------------------------------------------
// 6. regenerateAfterEdit drops failed sends
// ---------------------------------------------------------------------------

describe('regenerateAfterEdit history', () => {
    it('omits abandoned failed-send bubbles, as sendMessage does', () => {
        const cm = mkCm();
        const edited = {
            role: 'user' as const, content: 'edited', created_at: '2026-01-01 00:03:00', id: 3,
        };
        cm.messages = [
            { role: 'user', content: 'kept', created_at: '2026-01-01 00:00:00', id: 1 },
            { role: 'assistant', content: 'reply', created_at: '2026-01-01 00:01:00', id: 2 },
            { role: 'user', content: 'never delivered', created_at: '2026-01-01 00:02:00', failed: true },
            edited,
        ];
        cm.regenerateAfterEdit(edited);
        const msg = sentFrames(cm).find(f => f.type === 'message');
        expect(msg).toBeDefined();
        const history = msg?.history as { content: string }[];
        expect(history.map(h => h.content)).toEqual(['kept', 'reply']);
    });
});
