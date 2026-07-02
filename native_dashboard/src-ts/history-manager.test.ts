/**
 * Tests for HistoryManager — the AI History page delegate that ChatManager
 * forwards the ai_channels_list / ai_history_loaded / ai_history_message_edited
 * / ai_history_message_deleted WS frames to.
 *
 * Same recipe as chat-manager.test.ts: Tauri invoke mocked at module-import
 * time (shared.ts reads it), a jsdom DOM scaffold mirroring the #page-history
 * ids from index.html, a vi.fn() send stub instead of a real socket, and
 * handleMessage() driven directly.
 */

import { describe, it, expect, beforeEach, beforeAll, vi } from 'vitest';

// Tauri invoke is mocked at module-import time because shared.ts reads it.
vi.mock('@tauri-apps/api/core', () => ({ invoke: vi.fn().mockResolvedValue('') }));

// Minimal mirror of the #page-history DOM from ui/index.html.
const HISTORY_DOM = `
    <div id="toast-container"></div>
    <section id="page-history" class="page">
        <aside class="history-sidebar">
            <button id="ai-history-refresh"></button>
            <div id="ai-channel-list"></div>
        </aside>
        <div class="history-main">
            <div id="ai-history-header"></div>
            <div id="ai-history-messages"></div>
            <div id="ai-history-load-all-container" class="hidden">
                <button id="ai-history-load-all">Load all</button>
            </div>
            <div class="history-undo">
                <button id="ai-history-undo" disabled>↶ Undo</button>
            </div>
        </div>
    </section>
`;

// Late import — AFTER the mock is registered.
let HistoryManager: typeof import('./history-manager.js').HistoryManager;

beforeAll(async () => {
    const mod = await import('./history-manager.js');
    HistoryManager = mod.HistoryManager;
});

beforeEach(() => {
    // jsdom doesn't implement scrollIntoView — stub it so focusing a find
    // match (focusFind → scrollIntoView) doesn't throw.
    if (!Element.prototype.scrollIntoView) {
        Element.prototype.scrollIntoView = function () { /* no-op */ };
    }
    document.body.innerHTML = HISTORY_DOM;
});

function mountHistory(): {
    hm: import('./history-manager.js').HistoryManager;
    send: ReturnType<typeof vi.fn>;
    isConnected: ReturnType<typeof vi.fn>;
    connect: ReturnType<typeof vi.fn>;
    confirmDialog: ReturnType<typeof vi.fn>;
} {
    const send = vi.fn(() => true);
    const isConnected = vi.fn(() => true);
    const connect = vi.fn();
    // Injected via the callback bag (like notify) — accepts by default.
    const confirmDialog = vi.fn(async () => true);
    const hm = new HistoryManager({ send, isConnected, connect, confirmDialog });
    hm.init();
    return { hm, send, isConnected, connect, confirmDialog };
}

/** Settle the await-points inside requestDelete (confirm dialog hop). */
const flushAsync = () => new Promise<void>(resolve => setTimeout(resolve, 0));

const CHANNEL_A = '111111111111111111';
const CHANNEL_B = '222222222222222222';

function makeMessage(overrides: Partial<{
    id: number; local_id: number; role: 'user' | 'model'; content: string;
    message_id: string | null; timestamp: string | null; user_id: string | null;
}> = {}): Record<string, unknown> {
    return {
        id: 1,
        local_id: 1,
        role: 'user',
        content: 'hello',
        message_id: null,
        timestamp: null,
        user_id: null,
        ...overrides,
    };
}

// ============================================================================
// Channel list
// ============================================================================

describe('handleMessage — ai_channels_list', () => {
    it('renders channels with name, count badge, and last_active', () => {
        const { hm } = mountHistory();
        hm.handleMessage({
            type: 'ai_channels_list',
            channels: [
                { channel_id: CHANNEL_A, name: 'Guild / #general', message_count: 42, last_active: '2026-06-10T12:00:00Z' },
                { channel_id: CHANNEL_B, name: `Channel ${CHANNEL_B}`, message_count: 7, last_active: null },
            ],
        });
        const list = document.getElementById('ai-channel-list')!;
        const items = list.querySelectorAll('.history-channel-item');
        expect(items.length).toBe(2);
        expect(items[0].textContent).toContain('Guild / #general');
        expect(items[0].textContent).toContain('42');
        expect(items[1].textContent).toContain('no activity');
    });

    it('escapes hostile channel names (no live <script> node)', () => {
        const { hm } = mountHistory();
        hm.handleMessage({
            type: 'ai_channels_list',
            channels: [
                { channel_id: CHANNEL_A, name: 'evil <script>alert(1)</script> "x" <img src=x onerror=alert(1)>', message_count: 1, last_active: null },
            ],
        });
        const list = document.getElementById('ai-channel-list')!;
        expect(list.querySelector('script')).toBeNull();
        expect(list.querySelector('img')).toBeNull();
        // The hostile string survives as inert TEXT.
        expect(list.textContent).toContain('<script>alert(1)</script>');
    });

    it('shows the empty state when there are no channels', () => {
        const { hm } = mountHistory();
        hm.handleMessage({ type: 'ai_channels_list', channels: [] });
        expect(document.getElementById('ai-channel-list')!.textContent).toContain('No channels');
    });

    it('caps the channel render at 200 with an overflow note', () => {
        const { hm } = mountHistory();
        const channels = Array.from({ length: 201 }, (_, i) => ({
            channel_id: String(100000 + i),
            name: `channel ${i}`,
            message_count: 1,
            last_active: null,
        }));
        hm.handleMessage({ type: 'ai_channels_list', channels });
        const list = document.getElementById('ai-channel-list')!;
        expect(list.querySelectorAll('.history-channel-item').length).toBe(200);
        expect(list.querySelector('.history-overflow-note')!.textContent)
            .toContain('1 more channels hidden');
    });
});

// ============================================================================
// Opening a channel
// ============================================================================

describe('openChannel', () => {
    it('clicking a channel row sends load_ai_history with limit 200', () => {
        const { hm, send } = mountHistory();
        hm.handleMessage({
            type: 'ai_channels_list',
            channels: [{ channel_id: CHANNEL_A, name: 'Guild / #general', message_count: 42, last_active: null }],
        });
        // Click a CHILD of the row to prove the delegated closest() lookup.
        const name = document.querySelector('.history-channel-name') as HTMLElement;
        name.click();
        expect(send).toHaveBeenCalledWith({
            type: 'load_ai_history',
            channel_id: CHANNEL_A,
            limit: 200,
        });
        expect(hm.currentChannelId).toBe(CHANNEL_A);
    });

    it('keeps the snowflake channel_id as a STRING in the outgoing frame', () => {
        const { hm, send } = mountHistory();
        hm.openChannel('918273645546372819'); // > Number.MAX_SAFE_INTEGER territory
        const frame = send.mock.calls[0][0] as { channel_id: unknown };
        expect(typeof frame.channel_id).toBe('string');
    });
});

// ============================================================================
// Loading history
// ============================================================================

describe('handleMessage — ai_history_loaded', () => {
    it('renders messages with role badges and escaped content', () => {
        const { hm } = mountHistory();
        hm.openChannel(CHANNEL_A);
        hm.handleMessage({
            type: 'ai_history_loaded',
            channel_id: CHANNEL_A,
            messages: [
                makeMessage({ id: 1, local_id: 1, role: 'user', content: 'hi <script>alert(1)</script>', user_id: '333', timestamp: '2026-06-10T12:00:00Z' }),
                makeMessage({ id: 2, local_id: 2, role: 'model', content: 'hello back' }),
            ],
            total_count: 2,
            has_more: false,
        });
        const container = document.getElementById('ai-history-messages')!;
        const rows = container.querySelectorAll('.history-msg');
        expect(rows.length).toBe(2);
        expect(rows[0].querySelector('.history-role-badge')!.textContent).toBe('User');
        expect(rows[1].querySelector('.history-role-badge')!.textContent).toBe('Model');
        expect(container.querySelector('script')).toBeNull();
        expect(rows[0].textContent).toContain('<script>alert(1)</script>');
        // has_more=false → Load-all stays hidden.
        expect(document.getElementById('ai-history-load-all-container')!.classList.contains('hidden')).toBe(true);
    });

    it('neutralizes a hostile string `id` (attribute breakout / no live <img>)', () => {
        const { hm } = mountHistory();
        hm.openChannel(CHANNEL_A);
        // A mis-built / hostile frame can send `id` as a string even though the
        // wire contract says it's a number. A breakout payload in data-id="…"
        // would otherwise inject a live <img onerror>. The id-coercion at the
        // frame door drops the un-numberable row; the valid row still renders.
        const hostileId = '7"><img src=x onerror=alert(1)>' as unknown as number;
        expect(() => hm.handleMessage({
            type: 'ai_history_loaded',
            channel_id: CHANNEL_A,
            messages: [
                makeMessage({ id: hostileId, role: 'user', content: 'breakout' }),
                makeMessage({ id: 8, local_id: 2, role: 'model', content: 'survivor' }),
            ],
            total_count: 2,
            has_more: false,
        })).not.toThrow();
        const container = document.getElementById('ai-history-messages')!;
        // No live node escaped from the data-id breakout attempt…
        expect(container.querySelector('img')).toBeNull();
        // …and the well-formed row still renders.
        const rows = container.querySelectorAll('.history-msg');
        expect(rows.length).toBe(1);
        expect(rows[0].textContent).toContain('survivor');
    });

    it('drops a stale frame for a channel the user already switched away from', () => {
        const { hm } = mountHistory();
        hm.openChannel(CHANNEL_A);
        hm.openChannel(CHANNEL_B);
        // Late frame for A arrives AFTER B was opened — must be dropped.
        hm.handleMessage({
            type: 'ai_history_loaded',
            channel_id: CHANNEL_A,
            messages: [makeMessage({ content: 'STALE' })],
            total_count: 1,
            has_more: false,
        });
        expect(document.getElementById('ai-history-messages')!.textContent).not.toContain('STALE');
        expect(hm.messages.length).toBe(0);
        // The frame for the CURRENT channel still lands.
        hm.handleMessage({
            type: 'ai_history_loaded',
            channel_id: CHANNEL_B,
            messages: [makeMessage({ content: 'FRESH' })],
            total_count: 1,
            has_more: false,
        });
        expect(document.getElementById('ai-history-messages')!.textContent).toContain('FRESH');
    });

    it('shows the "Load all (N)" button when has_more, and it re-requests with limit 2000', () => {
        const { hm, send } = mountHistory();
        hm.openChannel(CHANNEL_A);
        hm.handleMessage({
            type: 'ai_history_loaded',
            channel_id: CHANNEL_A,
            messages: [makeMessage()],
            total_count: 1234,
            has_more: true,
        });
        const wrap = document.getElementById('ai-history-load-all-container')!;
        const btn = document.getElementById('ai-history-load-all')!;
        expect(wrap.classList.contains('hidden')).toBe(false);
        expect(btn.textContent).toContain('1234');
        send.mockClear();
        (btn as HTMLElement).click();
        expect(send).toHaveBeenCalledWith({
            type: 'load_ai_history',
            channel_id: CHANNEL_A,
            limit: 2000,
        });
    });

    it('caps the message render at 500 and keeps data-idx mapped to the absolute index', () => {
        const { hm } = mountHistory();
        hm.openChannel(CHANNEL_A);
        const msgs = Array.from({ length: 501 }, (_, i) =>
            makeMessage({ id: i + 1, local_id: i + 1, content: `msg ${i}` }));
        hm.handleMessage({
            type: 'ai_history_loaded',
            channel_id: CHANNEL_A,
            messages: msgs,
            total_count: 501,
            has_more: false,
        });
        const container = document.getElementById('ai-history-messages')!;
        const rows = container.querySelectorAll('.history-msg');
        expect(rows.length).toBe(500);
        expect(container.querySelector('.history-overflow-note')!.textContent)
            .toContain('newest 500');
        // The oldest row was sliced off, so the FIRST rendered row is
        // messages[1] (absolute idx 1). Clicking its edit button must open
        // the editor on THAT entry, not on messages[0].
        (rows[0].querySelector('.history-edit-btn') as HTMLElement).click();
        const ta = document.querySelector('.edit-textarea') as HTMLTextAreaElement;
        expect(ta).not.toBeNull();
        expect(ta.value).toBe('msg 1');
    });

    it('relabels Load-all to "Load newest 2000 of N" when the total exceeds the server cap', () => {
        const { hm } = mountHistory();
        hm.openChannel(CHANNEL_A);
        hm.handleMessage({
            type: 'ai_history_loaded',
            channel_id: CHANNEL_A,
            messages: [makeMessage()],
            total_count: 5000,
            has_more: true,
        });
        const wrap = document.getElementById('ai-history-load-all-container')!;
        const btn = document.getElementById('ai-history-load-all')!;
        expect(wrap.classList.contains('hidden')).toBe(false);
        expect(btn.textContent).toBe('Load newest 2000 of 5000');
    });

    it('hides Load-all once the loaded rows reach the server cap (dead-end loop guard)', () => {
        const { hm } = mountHistory();
        hm.openChannel(CHANNEL_A);
        const msgs = Array.from({ length: 2000 }, (_, i) =>
            makeMessage({ id: i + 1, local_id: i + 1 }));
        hm.handleMessage({
            type: 'ai_history_loaded',
            channel_id: CHANNEL_A,
            messages: msgs,
            total_count: 5000,
            has_more: true,
        });
        expect(document.getElementById('ai-history-load-all-container')!
            .classList.contains('hidden')).toBe(true);
    });

    it('hides Load-all when the server clipped the payload (truncated:true)', () => {
        const { hm } = mountHistory();
        hm.openChannel(CHANNEL_A);
        hm.handleMessage({
            type: 'ai_history_loaded',
            channel_id: CHANNEL_A,
            messages: [makeMessage()],
            total_count: 5000,
            has_more: true,
            truncated: true,
        });
        expect(document.getElementById('ai-history-load-all-container')!
            .classList.contains('hidden')).toBe(true);
    });
});

// ============================================================================
// Edit flow
// ============================================================================

function loadOneMessage(hm: import('./history-manager.js').HistoryManager): void {
    hm.openChannel(CHANNEL_A);
    hm.handleMessage({
        type: 'ai_history_loaded',
        channel_id: CHANNEL_A,
        messages: [makeMessage({ id: 7, local_id: 5, role: 'model', content: 'old text' })],
        total_count: 1,
        has_more: false,
    });
}

describe('edit flow', () => {
    it('openChannel is blocked while an edit is open and UNSAVED, allowed once the save ack is in flight', () => {
        const { hm, send } = mountHistory();
        loadOneMessage(hm);
        (document.querySelector('.history-edit-btn') as HTMLElement).click();
        (document.querySelector('.edit-textarea') as HTMLTextAreaElement).value = 'typed but not saved';
        send.mockClear();
        // Unsaved editor open → the switch is refused (typed text protected):
        // no load frame goes out and the textarea survives with its content.
        hm.openChannel(CHANNEL_B);
        expect(send).not.toHaveBeenCalled();
        expect((document.querySelector('.edit-textarea') as HTMLTextAreaElement).value)
            .toBe('typed but not saved');
        // Click Save (ack in flight) → switching away is the supported flow
        // again (the ack is keyed by channel+id — see the undo-scoping test).
        (document.querySelector('.edit-save-btn') as HTMLElement).click();
        send.mockClear();
        hm.openChannel(CHANNEL_B);
        expect(send).toHaveBeenCalledWith(expect.objectContaining({
            type: 'load_ai_history',
            channel_id: CHANNEL_B,
        }));
    });

    it('edit button swaps content for a textarea pre-filled with the original', () => {
        const { hm } = mountHistory();
        loadOneMessage(hm);
        (document.querySelector('.history-edit-btn') as HTMLElement).click();
        const ta = document.querySelector('.edit-textarea') as HTMLTextAreaElement;
        expect(ta).not.toBeNull();
        expect(ta.value).toBe('old text');
        expect(document.querySelector('.edit-save-btn')).not.toBeNull();
        expect(document.querySelector('.edit-cancel-btn')).not.toBeNull();
    });

    it('save sends the exact edit_ai_history_message frame and disables Save while in flight', () => {
        const { hm, send } = mountHistory();
        loadOneMessage(hm);
        (document.querySelector('.history-edit-btn') as HTMLElement).click();
        const ta = document.querySelector('.edit-textarea') as HTMLTextAreaElement;
        ta.value = 'new text';
        send.mockClear();
        const saveBtn = document.querySelector('.edit-save-btn') as HTMLButtonElement;
        saveBtn.click();
        expect(send).toHaveBeenCalledWith({
            type: 'edit_ai_history_message',
            channel_id: CHANNEL_A,
            id: 7,
            content: 'new text',
        });
        expect(saveBtn.disabled).toBe(true);
    });

    it('ai_history_message_edited updates the row and exits edit mode', () => {
        const { hm } = mountHistory();
        loadOneMessage(hm);
        (document.querySelector('.history-edit-btn') as HTMLElement).click();
        (document.querySelector('.edit-textarea') as HTMLTextAreaElement).value = 'new text';
        (document.querySelector('.edit-save-btn') as HTMLElement).click();
        hm.handleMessage({
            type: 'ai_history_message_edited',
            channel_id: CHANNEL_A,
            id: 7,
            content: 'new text',
            live_session_patched: true,
        });
        expect(document.querySelector('.edit-textarea')).toBeNull();
        expect(document.getElementById('ai-history-messages')!.textContent).toContain('new text');
        expect(hm.messages[0].content).toBe('new text');
        expect(hm.editingIdx).toBeNull();
    });

    it('keeps the editor open (Save re-enabled) when send() returns false', () => {
        const { hm, send } = mountHistory();
        loadOneMessage(hm);
        (document.querySelector('.history-edit-btn') as HTMLElement).click();
        (document.querySelector('.edit-textarea') as HTMLTextAreaElement).value = 'new text';
        send.mockReturnValueOnce(false); // socket down for the save only
        const saveBtn = document.querySelector('.edit-save-btn') as HTMLButtonElement;
        saveBtn.click();
        expect(document.querySelector('.edit-textarea')).not.toBeNull();
        expect((document.querySelector('.edit-textarea') as HTMLTextAreaElement).value).toBe('new text');
        expect(saveBtn.disabled).toBe(false);
    });

    it('onError (server rejected the save) re-enables Save and keeps the text', () => {
        const { hm } = mountHistory();
        loadOneMessage(hm);
        (document.querySelector('.history-edit-btn') as HTMLElement).click();
        (document.querySelector('.edit-textarea') as HTMLTextAreaElement).value = 'new text';
        const saveBtn = document.querySelector('.edit-save-btn') as HTMLButtonElement;
        saveBtn.click();
        expect(saveBtn.disabled).toBe(true);
        hm.onError(); // ChatManager forwards the {type:'error'} envelope
        expect(saveBtn.disabled).toBe(false);
        expect((document.querySelector('.edit-textarea') as HTMLTextAreaElement).value).toBe('new text');
        // A save can be retried afterwards.
        saveBtn.click();
        expect(saveBtn.disabled).toBe(true);
    });

    it('onError outside an in-flight edit is a no-op', () => {
        const { hm } = mountHistory();
        loadOneMessage(hm);
        expect(() => hm.onError()).not.toThrow();
    });

    it('live_session=no_match surfaces the stale-RAM warning toast', () => {
        const { hm } = mountHistory();
        loadOneMessage(hm);
        hm.handleMessage({
            type: 'ai_history_message_edited',
            channel_id: CHANNEL_A,
            id: 7,
            content: 'patched in db only',
            live_session: 'no_match',
            live_session_patched: false,
        });
        expect(document.getElementById('toast-container')!.textContent)
            .toContain('Edited in DB, but the bot\'s live memory may still hold the old text until reload');
    });

    it('empty content after trim is rejected without sending', () => {
        const { hm, send } = mountHistory();
        loadOneMessage(hm);
        (document.querySelector('.history-edit-btn') as HTMLElement).click();
        (document.querySelector('.edit-textarea') as HTMLTextAreaElement).value = '   ';
        send.mockClear();
        (document.querySelector('.edit-save-btn') as HTMLElement).click();
        expect(send).not.toHaveBeenCalled();
        // Editor stays open for correction.
        expect(document.querySelector('.edit-textarea')).not.toBeNull();
    });

    it('cancel restores the original content', () => {
        const { hm } = mountHistory();
        loadOneMessage(hm);
        (document.querySelector('.history-edit-btn') as HTMLElement).click();
        (document.querySelector('.edit-textarea') as HTMLTextAreaElement).value = 'discarded';
        (document.querySelector('.edit-cancel-btn') as HTMLElement).click();
        expect(document.querySelector('.edit-textarea')).toBeNull();
        expect(document.getElementById('ai-history-messages')!.textContent).toContain('old text');
    });

    it('rejects oversize content client-side (toast, no send, editor stays open)', () => {
        const { hm, send } = mountHistory();
        loadOneMessage(hm);
        (document.querySelector('.history-edit-btn') as HTMLElement).click();
        (document.querySelector('.edit-textarea') as HTMLTextAreaElement).value = 'x'.repeat(200001);
        send.mockClear();
        (document.querySelector('.edit-save-btn') as HTMLElement).click();
        expect(send).not.toHaveBeenCalled();
        expect(document.getElementById('toast-container')!.textContent)
            .toContain('Content too long');
        expect(document.querySelector('.edit-textarea')).not.toBeNull();
    });

    it('unchanged content cancels the edit without sending', () => {
        const { hm, send } = mountHistory();
        loadOneMessage(hm);
        (document.querySelector('.history-edit-btn') as HTMLElement).click();
        // The textarea is pre-filled with the original — save it untouched.
        send.mockClear();
        (document.querySelector('.edit-save-btn') as HTMLElement).click();
        expect(send).not.toHaveBeenCalled();
        expect(document.querySelector('.edit-textarea')).toBeNull();
        expect(document.getElementById('ai-history-messages')!.textContent).toContain('old text');
    });

    it('loadAll is blocked while an editor is open (warning toast, no send)', () => {
        const { hm, send } = mountHistory();
        loadOneMessage(hm);
        (document.querySelector('.history-edit-btn') as HTMLElement).click();
        (document.querySelector('.edit-textarea') as HTMLTextAreaElement).value = 'typed mid-edit';
        send.mockClear();
        hm.loadAll();
        expect(send).not.toHaveBeenCalled();
        expect(document.getElementById('toast-container')!.textContent)
            .toContain('Finish or cancel the edit first');
        // The editor (and the typed draft) survives.
        expect((document.querySelector('.edit-textarea') as HTMLTextAreaElement).value)
            .toBe('typed mid-edit');
    });

    it('startEdit bails while a channel load is in flight', () => {
        const { hm } = mountHistory();
        loadOneMessage(hm);
        hm.loadAll(); // pendingChannelLoadId set until ai_history_loaded lands
        (document.querySelector('.history-edit-btn') as HTMLElement).click();
        expect(document.querySelector('.edit-textarea')).toBeNull();
    });

    it('onConnected unsticks an in-flight edit after a reconnect (ack can never arrive)', () => {
        const { hm } = mountHistory();
        loadOneMessage(hm);
        (document.querySelector('.history-edit-btn') as HTMLElement).click();
        (document.querySelector('.edit-textarea') as HTMLTextAreaElement).value = 'new text';
        const saveBtn = document.querySelector('.edit-save-btn') as HTMLButtonElement;
        saveBtn.click(); // send() returns true — ack now in flight
        expect(saveBtn.disabled).toBe(true);
        // Socket dropped + reconnected: the backend replies only on the
        // originating connection, so the ack is gone for good.
        hm.onConnected();
        expect(saveBtn.disabled).toBe(false);
        expect((document.querySelector('.edit-textarea') as HTMLTextAreaElement).value).toBe('new text');
    });
});

// ============================================================================
// Delete flow
// ============================================================================

function loadTwoMessages(hm: import('./history-manager.js').HistoryManager): void {
    hm.openChannel(CHANNEL_A);
    hm.handleMessage({
        type: 'ai_history_loaded',
        channel_id: CHANNEL_A,
        messages: [
            makeMessage({ id: 7, local_id: 1, role: 'user', content: 'first message' }),
            makeMessage({ id: 8, local_id: 2, role: 'model', content: 'second message' }),
        ],
        total_count: 2,
        has_more: false,
    });
}

describe('delete flow', () => {
    it('renders a delete button with an accessible name next to Edit', () => {
        const { hm } = mountHistory();
        loadOneMessage(hm);
        const actions = document.querySelector('.history-msg-actions')!;
        const btn = actions.querySelector('.history-delete-btn') as HTMLButtonElement;
        expect(btn).not.toBeNull();
        expect(btn.getAttribute('aria-label')).toBe('Delete message');
        // It sits in the same actions span as the edit button.
        expect(actions.querySelector('.history-edit-btn')).not.toBeNull();
    });

    it('confirm-accept sends the EXACT delete frame (string channel_id, number id)', async () => {
        const { hm, send, confirmDialog } = mountHistory();
        loadOneMessage(hm);
        send.mockClear();
        // Click a CHILD path through the delegated container handler.
        (document.querySelector('.history-delete-btn') as HTMLElement).click();
        await flushAsync();
        expect(confirmDialog).toHaveBeenCalledWith('Delete this message?');
        expect(send).toHaveBeenCalledWith({
            type: 'delete_ai_history_message',
            channel_id: CHANNEL_A,
            id: 7,
        });
        const frame = send.mock.calls[0][0] as { channel_id: unknown; id: unknown };
        expect(typeof frame.channel_id).toBe('string');
        expect(typeof frame.id).toBe('number');
        // The clicked button is disabled while the ack is in flight.
        expect((document.querySelector('.history-delete-btn') as HTMLButtonElement).disabled).toBe(true);
    });

    it('confirm-cancel sends nothing and keeps the row', async () => {
        const { hm, send, confirmDialog } = mountHistory();
        loadOneMessage(hm);
        send.mockClear();
        confirmDialog.mockResolvedValueOnce(false);
        await hm.requestDelete(0);
        expect(confirmDialog).toHaveBeenCalledTimes(1);
        expect(send).not.toHaveBeenCalled();
        expect(document.getElementById('ai-history-messages')!.textContent).toContain('old text');
        expect((document.querySelector('.history-delete-btn') as HTMLButtonElement).disabled).toBe(false);
    });

    it('a delete in flight blocks a second delete AND a new edit', async () => {
        const { hm, send, confirmDialog } = mountHistory();
        loadTwoMessages(hm);
        await hm.requestDelete(0); // ack now in flight
        send.mockClear();
        confirmDialog.mockClear();
        await hm.requestDelete(1);
        expect(confirmDialog).not.toHaveBeenCalled();
        expect(send).not.toHaveBeenCalled();
        // startEdit is gated by the same single-mutation-in-flight flag.
        (document.querySelectorAll('.history-edit-btn')[1] as HTMLElement).click();
        expect(document.querySelector('.edit-textarea')).toBeNull();
    });

    it('an edit ack in flight blocks delete', async () => {
        const { hm, send, confirmDialog } = mountHistory();
        loadOneMessage(hm);
        (document.querySelector('.history-edit-btn') as HTMLElement).click();
        (document.querySelector('.edit-textarea') as HTMLTextAreaElement).value = 'new text';
        (document.querySelector('.edit-save-btn') as HTMLElement).click(); // edit ack in flight
        send.mockClear();
        await hm.requestDelete(0);
        expect(confirmDialog).not.toHaveBeenCalled();
        expect(send).not.toHaveBeenCalled();
    });

    it('drops a confirmed delete when the channel switched while the dialog was open', async () => {
        const { hm, send, confirmDialog } = mountHistory();
        loadOneMessage(hm);
        let resolveDialog!: (v: boolean) => void;
        confirmDialog.mockImplementationOnce(
            () => new Promise<boolean>((r) => { resolveDialog = r; }),
        );
        send.mockClear();
        const pending = hm.requestDelete(0); // dialog now open
        hm.openChannel(CHANNEL_B);           // user switches channel mid-dialog
        send.mockClear();                    // drop the load_ai_history frame
        resolveDialog(true);
        await pending;
        expect(send).not.toHaveBeenCalled(); // stale delete never sent
    });

    it('drops a confirmed delete when an editor was opened while the dialog was open', async () => {
        const { hm, send, confirmDialog } = mountHistory();
        loadTwoMessages(hm);
        let resolveDialog!: (v: boolean) => void;
        confirmDialog.mockImplementationOnce(
            () => new Promise<boolean>((r) => { resolveDialog = r; }),
        );
        const pending = hm.requestDelete(1); // dialog now open on row 1
        // User opens an editor on row 0 while the (non-modal) dialog is up.
        (document.querySelectorAll('.history-edit-btn')[0] as HTMLElement).click();
        (document.querySelector('.edit-textarea') as HTMLTextAreaElement).value = 'mid-dialog draft';
        send.mockClear();
        resolveDialog(true);
        await pending;
        expect(send).not.toHaveBeenCalled(); // delete dropped, not the draft
        expect(document.getElementById('toast-container')!.textContent)
            .toContain('Finish or cancel the edit first');
        expect((document.querySelector('.edit-textarea') as HTMLTextAreaElement).value)
            .toBe('mid-dialog draft');
    });

    it('an open editor on ANOTHER row blocks delete with a warning (no confirm, editor survives)', async () => {
        const { hm, send, confirmDialog } = mountHistory();
        loadTwoMessages(hm);
        (document.querySelectorAll('.history-edit-btn')[0] as HTMLElement).click();
        (document.querySelector('.edit-textarea') as HTMLTextAreaElement).value = 'typed mid-edit';
        send.mockClear();
        await hm.requestDelete(1);
        expect(confirmDialog).not.toHaveBeenCalled();
        expect(send).not.toHaveBeenCalled();
        expect(document.getElementById('toast-container')!.textContent)
            .toContain('Finish or cancel the edit first');
        expect((document.querySelector('.edit-textarea') as HTMLTextAreaElement).value)
            .toBe('typed mid-edit');
    });

    it('deleting the actively-edited row cancels the editor first, then confirms and sends', async () => {
        const { hm, send, confirmDialog } = mountHistory();
        loadTwoMessages(hm);
        (document.querySelectorAll('.history-edit-btn')[0] as HTMLElement).click();
        (document.querySelector('.edit-textarea') as HTMLTextAreaElement).value = 'doomed draft';
        send.mockClear();
        await hm.requestDelete(0);
        // Editor was closed BEFORE the dialog, and the frame went out.
        expect(document.querySelector('.edit-textarea')).toBeNull();
        expect(confirmDialog).toHaveBeenCalledWith('Delete this message?');
        expect(send).toHaveBeenCalledWith({
            type: 'delete_ai_history_message',
            channel_id: CHANNEL_A,
            id: 7,
        });
        expect(hm.editingIdx).toBeNull();
    });

    it('ai_history_message_deleted removes the row, updates header/total and toasts', async () => {
        const { hm, send } = mountHistory();
        loadTwoMessages(hm);
        await hm.requestDelete(0);
        hm.handleMessage({
            type: 'ai_history_message_deleted',
            channel_id: CHANNEL_A,
            id: 7,
            live_session_patched: true,
            total_count: 1,
        });
        expect(hm.messages.length).toBe(1);
        expect(hm.messages[0].id).toBe(8);
        expect(hm.totalCount).toBe(1);
        const pane = document.getElementById('ai-history-messages')!;
        expect(pane.textContent).not.toContain('first message');
        expect(pane.textContent).toContain('second message');
        expect(document.getElementById('ai-history-header')!.textContent)
            .toContain('1 of 1 messages');
        expect(document.getElementById('toast-container')!.textContent)
            .toContain('Message deleted');
        // The in-flight flag cleared — the next mutation goes straight out.
        send.mockClear();
        await hm.requestDelete(0);
        expect(send).toHaveBeenCalledWith({
            type: 'delete_ai_history_message',
            channel_id: CHANNEL_A,
            id: 8,
        });
    });

    it('falls back to a local decrement when the ack omits total_count', async () => {
        const { hm } = mountHistory();
        loadTwoMessages(hm);
        await hm.requestDelete(0);
        hm.handleMessage({
            type: 'ai_history_message_deleted',
            channel_id: CHANNEL_A,
            id: 7,
            live_session_patched: true,
        });
        expect(hm.totalCount).toBe(1);
    });

    it('live_session=no_match surfaces the stale-RAM warning toast', async () => {
        const { hm } = mountHistory();
        loadTwoMessages(hm);
        await hm.requestDelete(0);
        hm.handleMessage({
            type: 'ai_history_message_deleted',
            channel_id: CHANNEL_A,
            id: 7,
            live_session: 'no_match',
            live_session_patched: false,
            total_count: 1,
        });
        expect(document.getElementById('toast-container')!.textContent)
            .toContain('Deleted from DB, but the bot\'s live memory may still hold it until reload');
    });

    it('a stale ack for a channel that is no longer open leaves the rows untouched', async () => {
        const { hm } = mountHistory();
        loadTwoMessages(hm);
        await hm.requestDelete(0);
        // Ack tagged with a DIFFERENT channel — same guard shape as
        // ai_history_message_edited: drop it, but clear the in-flight flag.
        hm.handleMessage({
            type: 'ai_history_message_deleted',
            channel_id: CHANNEL_B,
            id: 7,
            live_session_patched: true,
            total_count: 0,
        });
        expect(hm.messages.length).toBe(2);
        expect(hm.totalCount).toBe(2);
        expect(document.getElementById('ai-history-messages')!.textContent).toContain('first message');
        expect(document.getElementById('toast-container')!.textContent).not.toContain('Message deleted');
    });

    it('keeps the delete retryable when send() returns false', async () => {
        const { hm, send } = mountHistory();
        loadOneMessage(hm);
        send.mockClear();
        send.mockReturnValueOnce(false); // socket died between confirm and send
        await hm.requestDelete(0);
        const btn = document.querySelector('.history-delete-btn') as HTMLButtonElement;
        expect(btn.disabled).toBe(false);
        // A retry goes out normally.
        send.mockClear();
        await hm.requestDelete(0);
        expect(send).toHaveBeenCalledWith({
            type: 'delete_ai_history_message',
            channel_id: CHANNEL_A,
            id: 7,
        });
    });

    it('onError (server rejected the delete) unsticks the pending delete for a retry', async () => {
        const { hm, send } = mountHistory();
        loadOneMessage(hm);
        await hm.requestDelete(0); // ack in flight, button disabled
        const btn = document.querySelector('.history-delete-btn') as HTMLButtonElement;
        expect(btn.disabled).toBe(true);
        hm.onError(); // ChatManager forwards the {type:'error', scope:'ai_history'} envelope
        expect(btn.disabled).toBe(false);
        send.mockClear();
        await hm.requestDelete(0);
        expect(send).toHaveBeenCalledWith({
            type: 'delete_ai_history_message',
            channel_id: CHANNEL_A,
            id: 7,
        });
    });

    it('onConnected unsticks an in-flight delete after a reconnect (ack can never arrive)', async () => {
        const { hm, send } = mountHistory();
        loadOneMessage(hm);
        await hm.requestDelete(0); // ack in flight
        const btn = document.querySelector('.history-delete-btn') as HTMLButtonElement;
        expect(btn.disabled).toBe(true);
        hm.onConnected();
        expect(btn.disabled).toBe(false);
        send.mockClear();
        await hm.requestDelete(0);
        expect(send).toHaveBeenCalledWith({
            type: 'delete_ai_history_message',
            channel_id: CHANNEL_A,
            id: 7,
        });
    });
});

// ============================================================================
// live_session toast mapping (edit + delete acks)
// ============================================================================

describe('live_session toast mapping', () => {
    /**
     * Drive ONE edited/deleted ack (with the given live-session fields) for
     * the open channel and return the resulting toast element. Row id 7
     * exists in both loadTwoMessages fixtures, so both ack types apply.
     */
    function ackToast(op: 'edit' | 'delete', fields: Record<string, unknown>): HTMLElement {
        const { hm } = mountHistory();
        loadTwoMessages(hm);
        hm.handleMessage(op === 'edit'
            ? { type: 'ai_history_message_edited', channel_id: CHANNEL_A, id: 7, content: 'updated', ...fields }
            : { type: 'ai_history_message_deleted', channel_id: CHANNEL_A, id: 7, total_count: 1, ...fields });
        const toast = document.querySelector('#toast-container .toast') as HTMLElement | null;
        expect(toast).not.toBeNull();
        return toast!;
    }

    for (const op of ['edit', 'delete'] as const) {
        const success = op === 'edit' ? 'Message edited' : 'Message deleted';

        it(`${op}: live_session=patched → plain success toast`, () => {
            const toast = ackToast(op, { live_session: 'patched', live_session_patched: true });
            expect(toast.classList.contains('toast-success')).toBe(true);
            expect(toast.textContent).toContain(success);
            expect(toast.textContent).not.toContain('channel not active');
        });

        // Benign: the channel's session just isn't in bot RAM (bot restarted
        // / evicted after idle) — the DB is the source of truth, so SUCCESS.
        for (const state of ['not_loaded', 'unavailable'] as const) {
            it(`${op}: live_session=${state} → SUCCESS toast, not a warning`, () => {
                const toast = ackToast(op, { live_session: state, live_session_patched: false });
                expect(toast.classList.contains('toast-success')).toBe(true);
                expect(toast.classList.contains('toast-warning')).toBe(false);
                expect(toast.textContent)
                    .toContain(`${success} (DB updated; channel not active in bot)`);
            });
        }

        // Genuinely warning-worthy: the session IS loaded but the in-memory
        // patch missed — stale RAM can clobber the DB change on next save.
        for (const state of ['no_match', 'error'] as const) {
            it(`${op}: live_session=${state} → WARNING toast about live memory`, () => {
                const toast = ackToast(op, { live_session: state, live_session_patched: false });
                expect(toast.classList.contains('toast-warning')).toBe(true);
                expect(toast.textContent).toContain('live memory');
                expect(toast.textContent).toContain(op === 'edit'
                    ? 'Edited in DB, but the bot\'s live memory may still hold the old text until reload'
                    : 'Deleted from DB, but the bot\'s live memory may still hold it until reload');
            });
        }

        it(`${op}: missing live_session + live_session_patched=false → legacy warning`, () => {
            const toast = ackToast(op, { live_session_patched: false });
            expect(toast.classList.contains('toast-warning')).toBe(true);
            expect(toast.textContent).toContain(op === 'edit'
                ? 'Edited in DB; live session not loaded'
                : 'Deleted from DB; live session not loaded');
        });

        it(`${op}: missing live_session + live_session_patched=true → legacy success`, () => {
            const toast = ackToast(op, { live_session_patched: true });
            expect(toast.classList.contains('toast-success')).toBe(true);
            expect(toast.textContent).toContain(success);
        });
    }
});

// ============================================================================
// Connection lifecycle
// ============================================================================

describe('onEnter / onConnected', () => {
    it('onEnter sends list_ai_channels when connected', () => {
        const { hm, send } = mountHistory();
        hm.onEnter();
        expect(send).toHaveBeenCalledWith({ type: 'list_ai_channels' });
    });

    it('queues the channels request while disconnected and flushes on connected', () => {
        const { hm, send } = mountHistory();
        send.mockReturnValueOnce(false); // socket down on page enter
        hm.onEnter();
        expect(document.getElementById('ai-channel-list')!.textContent).toContain('Not connected');
        send.mockClear();
        hm.onConnected();
        expect(send).toHaveBeenCalledWith({ type: 'list_ai_channels' });
        // A second connected event must NOT re-send (queue already flushed).
        send.mockClear();
        hm.onConnected();
        expect(send).not.toHaveBeenCalled();
    });

    it('refresh button re-sends list_ai_channels and toasts "Refreshed" on the response', () => {
        const { hm, send } = mountHistory();
        send.mockClear();
        (document.getElementById('ai-history-refresh') as HTMLElement).click();
        expect(send).toHaveBeenCalledWith({ type: 'list_ai_channels' });
        // Feedback arrives with the listing — even when nothing changed.
        hm.handleMessage({ type: 'ai_channels_list', channels: [] });
        expect(document.getElementById('toast-container')!.textContent).toContain('Refreshed');
    });

    it('a page-enter listing does NOT toast "Refreshed" (feedback is click-scoped)', () => {
        const { hm } = mountHistory();
        hm.onEnter();
        hm.handleMessage({ type: 'ai_channels_list', channels: [] });
        expect(document.getElementById('toast-container')!.textContent).not.toContain('Refreshed');
    });

    it('refresh also reloads the open channel with the SAME limit window (2000 after Load all)', () => {
        const { hm, send } = mountHistory();
        hm.openChannel(CHANNEL_A);
        hm.handleMessage({
            type: 'ai_history_loaded',
            channel_id: CHANNEL_A,
            messages: [makeMessage({ id: 7 })],
            total_count: 3000,
            has_more: true,
        });
        hm.loadAll(); // limit window is now 2000
        hm.handleMessage({
            type: 'ai_history_loaded',
            channel_id: CHANNEL_A,
            messages: [makeMessage({ id: 7 })],
            total_count: 3000,
            has_more: true,
        });
        send.mockClear();
        hm.refresh();
        expect(send).toHaveBeenCalledWith({ type: 'list_ai_channels' });
        expect(send).toHaveBeenCalledWith({
            type: 'load_ai_history',
            channel_id: CHANNEL_A,
            limit: 2000,
        });
    });

    it('refresh skips the message reload while an editor is open (draft survives)', () => {
        const { hm, send } = mountHistory();
        loadOneMessage(hm);
        (document.querySelector('.history-edit-btn') as HTMLElement).click();
        (document.querySelector('.edit-textarea') as HTMLTextAreaElement).value = 'draft text';
        send.mockClear();
        hm.refresh();
        expect(send).toHaveBeenCalledWith({ type: 'list_ai_channels' });
        expect(send).not.toHaveBeenCalledWith(expect.objectContaining({ type: 'load_ai_history' }));
        expect((document.querySelector('.edit-textarea') as HTMLTextAreaElement).value)
            .toBe('draft text');
    });

    it('refresh while disconnected kicks off a reconnect, notifies, and flushes on connected', () => {
        const { hm, send, isConnected, connect } = mountHistory();
        isConnected.mockReturnValue(false);
        hm.refresh();
        expect(send).not.toHaveBeenCalled();
        expect(connect).toHaveBeenCalledTimes(1);
        expect(document.getElementById('toast-container')!.textContent).toContain('Reconnecting');
        // Reconnect lands: queued listing flushes, then the response confirms.
        isConnected.mockReturnValue(true);
        hm.onConnected();
        expect(send).toHaveBeenCalledWith({ type: 'list_ai_channels' });
        hm.handleMessage({ type: 'ai_channels_list', channels: [] });
        expect(document.getElementById('toast-container')!.textContent).toContain('Refreshed');
    });

    it('onEnter while disconnected renders the disconnected state without sending (no toast)', () => {
        const { hm, send, isConnected } = mountHistory();
        isConnected.mockReturnValue(false);
        hm.onEnter();
        // send() is never reached — the real ChatManager.send would toast a
        // spurious "Not connected" error even though the request is queued.
        expect(send).not.toHaveBeenCalled();
        expect(document.getElementById('ai-channel-list')!.textContent).toContain('Not connected');
        expect(document.getElementById('toast-container')!.textContent).toBe('');
        // The queued request flushes once the socket is up.
        isConnected.mockReturnValue(true);
        hm.onConnected();
        expect(send).toHaveBeenCalledWith({ type: 'list_ai_channels' });
    });

    it('openChannel while disconnected renders a not-connected pane and onConnected flushes the load', () => {
        const { hm, send, isConnected } = mountHistory();
        isConnected.mockReturnValue(false);
        hm.openChannel(CHANNEL_A);
        expect(send).not.toHaveBeenCalled();
        const pane = document.getElementById('ai-history-messages')!;
        expect(pane.textContent).toContain('Not connected');
        expect(pane.textContent).not.toContain('Loading messages');
        isConnected.mockReturnValue(true);
        hm.onConnected();
        expect(send).toHaveBeenCalledWith({
            type: 'load_ai_history',
            channel_id: CHANNEL_A,
            limit: 200,
        });
    });

    it('openChannel queues the load when send() itself fails and flushes on connected', () => {
        const { hm, send } = mountHistory();
        send.mockReturnValueOnce(false); // socket died between check and send
        hm.openChannel(CHANNEL_A);
        expect(document.getElementById('ai-history-messages')!.textContent)
            .toContain('Not connected');
        send.mockClear();
        hm.onConnected();
        expect(send).toHaveBeenCalledWith({
            type: 'load_ai_history',
            channel_id: CHANNEL_A,
            limit: 200,
        });
        // A second connected event must NOT re-send (queue already flushed).
        send.mockClear();
        hm.onConnected();
        expect(send).not.toHaveBeenCalled();
    });

    it('switching channels before reconnect drops the stale queued load', () => {
        const { hm, send, isConnected } = mountHistory();
        isConnected.mockReturnValue(false);
        hm.openChannel(CHANNEL_A);
        hm.openChannel(CHANNEL_B);
        isConnected.mockReturnValue(true);
        send.mockClear();
        hm.onConnected();
        // Only the CURRENT channel's load is replayed — never A's.
        expect(send).toHaveBeenCalledTimes(1);
        expect(send).toHaveBeenCalledWith({
            type: 'load_ai_history',
            channel_id: CHANNEL_B,
            limit: 200,
        });
    });

    it('a queued loadAll flush re-sends with the stored 2000 limit', () => {
        const { hm, send, isConnected } = mountHistory();
        hm.openChannel(CHANNEL_A);
        hm.handleMessage({
            type: 'ai_history_loaded',
            channel_id: CHANNEL_A,
            messages: [makeMessage()],
            total_count: 1234,
            has_more: true,
        });
        isConnected.mockReturnValue(false);
        hm.loadAll();
        send.mockClear();
        isConnected.mockReturnValue(true);
        hm.onConnected();
        expect(send).toHaveBeenCalledWith({
            type: 'load_ai_history',
            channel_id: CHANNEL_A,
            limit: 2000,
        });
    });
});

// ============================================================================
// Undo flow — edit-undo via the reverse edit, delete-undo via the new
// restore_ai_history_message op. Entries are pushed ACK-CONFIRMED only.
// ============================================================================

const undoBtn = (): HTMLButtonElement =>
    document.getElementById('ai-history-undo') as HTMLButtonElement;

/** Open the editor on row 0, save `newContent`, and deliver the edited ack
 *  (which ack-pushes the undo entry). Leaves no editor open. */
function confirmEdit(
    hm: import('./history-manager.js').HistoryManager,
    id: number,
    newContent: string,
): void {
    (document.querySelector('.history-edit-btn') as HTMLElement).click();
    (document.querySelector('.edit-textarea') as HTMLTextAreaElement).value = newContent;
    (document.querySelector('.edit-save-btn') as HTMLElement).click();
    hm.handleMessage({
        type: 'ai_history_message_edited',
        channel_id: CHANNEL_A,
        id,
        content: newContent,
        live_session: 'patched',
        live_session_patched: true,
    });
}

function loadThreeMessages(hm: import('./history-manager.js').HistoryManager): void {
    hm.openChannel(CHANNEL_A);
    hm.handleMessage({
        type: 'ai_history_loaded',
        channel_id: CHANNEL_A,
        messages: [
            makeMessage({ id: 7, local_id: 1, role: 'user', content: 'first message' }),
            makeMessage({ id: 8, local_id: 2, role: 'model', content: 'second message' }),
            makeMessage({ id: 9, local_id: 3, role: 'user', content: 'third message' }),
        ],
        total_count: 3,
        has_more: false,
    });
}

describe('undo flow', () => {
    it('starts disabled with an empty stack, and undo() sends nothing', () => {
        const { hm, send } = mountHistory();
        loadOneMessage(hm);
        expect(undoBtn().disabled).toBe(true);
        send.mockClear();
        hm.undo();
        expect(send).not.toHaveBeenCalled();
    });

    it('an edit ack enables undo, and undo sends the reverse edit (then disables while in flight)', () => {
        const { hm, send } = mountHistory();
        loadOneMessage(hm); // id 7, content 'old text'
        expect(undoBtn().disabled).toBe(true);
        confirmEdit(hm, 7, 'new text');
        expect(undoBtn().disabled).toBe(false);
        send.mockClear();
        undoBtn().click();
        expect(send).toHaveBeenCalledWith({
            type: 'edit_ai_history_message',
            channel_id: CHANNEL_A,
            id: 7,
            content: 'old text',
        });
        expect(undoBtn().disabled).toBe(true);
    });

    it('a second undo after the redo-push behaves as redo', () => {
        const { hm, send } = mountHistory();
        loadOneMessage(hm);
        confirmEdit(hm, 7, 'new text');
        undoBtn().click(); // reverse edit ('old text') now in flight
        // Its ack pops the undone entry AND ack-pushes the redo entry whose
        // prevContent is the just-undone text.
        hm.handleMessage({
            type: 'ai_history_message_edited',
            channel_id: CHANNEL_A,
            id: 7,
            content: 'old text',
            live_session: 'patched',
            live_session_patched: true,
        });
        expect(hm.messages[0].content).toBe('old text');
        expect(undoBtn().disabled).toBe(false);
        send.mockClear();
        undoBtn().click();
        expect(send).toHaveBeenCalledWith({
            type: 'edit_ai_history_message',
            channel_id: CHANNEL_A,
            id: 7,
            content: 'new text',
        });
    });

    it('a delete ack enables undo, and undo sends restore with the EXACT stored message', async () => {
        const { hm, send } = mountHistory();
        hm.openChannel(CHANNEL_A);
        const original = {
            id: 7,
            local_id: 5,
            role: 'model',
            content: 'doomed text',
            message_id: '918273645546372819', // > Number.MAX_SAFE_INTEGER territory
            timestamp: '2026-06-10 12:00:00',
            user_id: '123456789012345678',
        };
        hm.handleMessage({
            type: 'ai_history_loaded',
            channel_id: CHANNEL_A,
            messages: [original, makeMessage({ id: 9, local_id: 6, content: 'survivor' })],
            total_count: 2,
            has_more: false,
        });
        await hm.requestDelete(0);
        expect(undoBtn().disabled).toBe(true); // delete ack still in flight
        hm.handleMessage({
            type: 'ai_history_message_deleted',
            channel_id: CHANNEL_A,
            id: 7,
            live_session: 'patched',
            live_session_patched: true,
            total_count: 1,
        });
        expect(undoBtn().disabled).toBe(false);
        send.mockClear();
        undoBtn().click();
        expect(send).toHaveBeenCalledWith({
            type: 'restore_ai_history_message',
            channel_id: CHANNEL_A,
            message: { ...original },
        });
        // Snowflakes survive as STRINGS — byte-for-byte what the server sent.
        const frame = send.mock.calls[0][0] as { message: Record<string, unknown> };
        expect(typeof frame.message.message_id).toBe('string');
        expect(typeof frame.message.user_id).toBe('string');
        expect(undoBtn().disabled).toBe(true); // restore ack in flight
    });

    it('the restored ack re-inserts at the id-sorted position, toasts, and pops the entry', async () => {
        const { hm } = mountHistory();
        loadThreeMessages(hm);
        await hm.requestDelete(1); // id 8, the MIDDLE row
        hm.handleMessage({
            type: 'ai_history_message_deleted',
            channel_id: CHANNEL_A,
            id: 8,
            live_session: 'patched',
            live_session_patched: true,
            total_count: 2,
        });
        undoBtn().click(); // restore in flight
        hm.handleMessage({
            type: 'ai_history_message_restored',
            channel_id: CHANNEL_A,
            id: 8,
            live_session: 'patched',
            live_session_patched: true,
            total_count: 3,
        });
        // Re-inserted BETWEEN ids 7 and 9 — original position, not appended.
        expect(hm.messages.map(m => m.id)).toEqual([7, 8, 9]);
        expect(hm.totalCount).toBe(3);
        const contents = document.querySelectorAll('#ai-history-messages .history-msg-content');
        expect(contents[1].textContent).toBe('second message');
        expect(document.getElementById('ai-history-header')!.textContent)
            .toContain('3 of 3 messages');
        expect(document.getElementById('toast-container')!.textContent)
            .toContain('Message restored');
        // Entry popped — the stack is empty again, so the button disables.
        expect(undoBtn().disabled).toBe(true);
    });

    it('a late restored ack after an unrelated error frame still re-inserts the row and pops the entry', async () => {
        const { hm, send } = mountHistory();
        loadThreeMessages(hm);
        await hm.requestDelete(1); // id 8, the MIDDLE row
        hm.handleMessage({
            type: 'ai_history_message_deleted',
            channel_id: CHANNEL_A,
            id: 8,
            live_session: 'patched',
            live_session_patched: true,
            total_count: 2,
        });
        undoBtn().click(); // restore in flight
        // An unrelated CODELESS error frame on the shared socket (e.g. a
        // failing chat stream) spuriously clears the in-flight undo marker…
        hm.onError();
        // …but the restore was still genuinely in flight: its late success
        // ack must recover the entry from the stack, re-insert the row at
        // its id-sorted spot, and pop the entry.
        hm.handleMessage({
            type: 'ai_history_message_restored',
            channel_id: CHANNEL_A,
            id: 8,
            live_session: 'patched',
            live_session_patched: true,
            total_count: 3,
        });
        expect(hm.messages.map(m => m.id)).toEqual([7, 8, 9]);
        expect(document.getElementById('toast-container')!.textContent)
            .toContain('Message restored');
        // Entry popped — the stack is empty again, so the button disables
        // and a further undo sends nothing.
        expect(undoBtn().disabled).toBe(true);
        send.mockClear();
        hm.undo();
        expect(send).not.toHaveBeenCalled();
    });

    it('restore live_session=no_match surfaces the restore-specific stale-RAM warning', async () => {
        const { hm } = mountHistory();
        loadThreeMessages(hm);
        await hm.requestDelete(1);
        hm.handleMessage({
            type: 'ai_history_message_deleted',
            channel_id: CHANNEL_A,
            id: 8,
            live_session: 'patched',
            live_session_patched: true,
            total_count: 2,
        });
        undoBtn().click();
        hm.handleMessage({
            type: 'ai_history_message_restored',
            channel_id: CHANNEL_A,
            id: 8,
            live_session: 'no_match',
            live_session_patched: false,
            total_count: 3,
        });
        const toast = document.querySelector('#toast-container .toast:last-child') as HTMLElement;
        expect(toast.classList.contains('toast-warning')).toBe(true);
        expect(toast.textContent)
            .toContain('Restored in DB, but the bot\'s live memory may not show it until reload');
        // Restored in the DB regardless — the row IS back locally.
        expect(hm.messages.map(m => m.id)).toEqual([7, 8, 9]);
    });

    it('an error envelope keeps the entry and re-enables undo for a retry', async () => {
        const { hm, send } = mountHistory();
        loadThreeMessages(hm);
        await hm.requestDelete(1);
        hm.handleMessage({
            type: 'ai_history_message_deleted',
            channel_id: CHANNEL_A,
            id: 8,
            live_session: 'patched',
            live_session_patched: true,
            total_count: 2,
        });
        undoBtn().click(); // restore in flight
        expect(undoBtn().disabled).toBe(true);
        hm.onError(); // server rejected the restore (e.g. rate limit / DB_UNAVAILABLE)
        expect(undoBtn().disabled).toBe(false);
        send.mockClear();
        undoBtn().click(); // retry goes out with the SAME stored message
        expect(send).toHaveBeenCalledWith(expect.objectContaining({
            type: 'restore_ai_history_message',
            channel_id: CHANNEL_A,
            message: expect.objectContaining({ id: 8, content: 'second message' }),
        }));
    });

    it('ROW_CONFLICT drops the doomed entry, reloads the channel, and unblocks older entries', async () => {
        const { hm, send } = mountHistory();
        loadThreeMessages(hm);
        // Two ack-confirmed deletes → two stack entries (id 8 older, id 9 newer).
        await hm.requestDelete(1); // id 8
        hm.handleMessage({
            type: 'ai_history_message_deleted',
            channel_id: CHANNEL_A,
            id: 8,
            live_session: 'patched',
            live_session_patched: true,
            total_count: 2,
        });
        await hm.requestDelete(1); // id 9 (messages are [7, 9] now)
        hm.handleMessage({
            type: 'ai_history_message_deleted',
            channel_id: CHANNEL_A,
            id: 9,
            live_session: 'patched',
            live_session_patched: true,
            total_count: 1,
        });
        // Undo targets the NEWEST entry (id 9); the backend rejects it
        // permanently — e.g. "History was rewritten since this undo was
        // recorded" after a force-replace save staled the entry.
        send.mockClear();
        undoBtn().click();
        expect(send).toHaveBeenCalledWith(expect.objectContaining({
            type: 'restore_ai_history_message',
            message: expect.objectContaining({ id: 9 }),
        }));
        send.mockClear();
        hm.onError('ROW_CONFLICT');
        // The doomed entry is dropped and the open channel reloads (same
        // window as the last load) so the view re-syncs.
        expect(send).toHaveBeenCalledWith({
            type: 'load_ai_history',
            channel_id: CHANNEL_A,
            limit: 200,
        });
        hm.handleMessage({
            type: 'ai_history_loaded',
            channel_id: CHANNEL_A,
            messages: [makeMessage({ id: 7, local_id: 1, content: 'first message' })],
            total_count: 1,
            has_more: false,
        });
        // The OLDER entry (id 8) is no longer shadowed — undo reaches it.
        expect(undoBtn().disabled).toBe(false);
        send.mockClear();
        undoBtn().click();
        expect(send).toHaveBeenCalledWith(expect.objectContaining({
            type: 'restore_ai_history_message',
            message: expect.objectContaining({ id: 8 }),
        }));
        // A retry of the conflicted id 9 restore was NOT re-sent.
        expect(send).not.toHaveBeenCalledWith(expect.objectContaining({
            message: expect.objectContaining({ id: 9 }),
        }));
    });

    it('a TRANSIENT error code (DB_UNAVAILABLE) keeps the entry for a retry', async () => {
        const { hm, send } = mountHistory();
        loadThreeMessages(hm);
        await hm.requestDelete(1);
        hm.handleMessage({
            type: 'ai_history_message_deleted',
            channel_id: CHANNEL_A,
            id: 8,
            live_session: 'patched',
            live_session_patched: true,
            total_count: 2,
        });
        undoBtn().click(); // restore in flight
        send.mockClear();
        hm.onError('DB_UNAVAILABLE');
        // Kept: no reload triggered, button re-enabled, retry goes out.
        expect(send).not.toHaveBeenCalled();
        expect(undoBtn().disabled).toBe(false);
        undoBtn().click();
        expect(send).toHaveBeenCalledWith(expect.objectContaining({
            type: 'restore_ai_history_message',
            message: expect.objectContaining({ id: 8 }),
        }));
    });

    it('a reconnect (onConnected) keeps the entry and re-enables undo', async () => {
        const { hm, send } = mountHistory();
        loadThreeMessages(hm);
        await hm.requestDelete(1);
        hm.handleMessage({
            type: 'ai_history_message_deleted',
            channel_id: CHANNEL_A,
            id: 8,
            live_session: 'patched',
            live_session_patched: true,
            total_count: 2,
        });
        undoBtn().click(); // restore in flight — its ack can never arrive now
        hm.onConnected();
        expect(undoBtn().disabled).toBe(false);
        send.mockClear();
        undoBtn().click();
        expect(send).toHaveBeenCalledWith(expect.objectContaining({
            type: 'restore_ai_history_message',
        }));
    });

    it('keeps the entry when send() itself returns false (dead socket)', () => {
        const { hm, send } = mountHistory();
        loadOneMessage(hm);
        confirmEdit(hm, 7, 'new text');
        send.mockClear();
        send.mockReturnValueOnce(false);
        undoBtn().click();
        // Rolled back: not in flight, entry kept, button re-enabled.
        expect(undoBtn().disabled).toBe(false);
        send.mockClear();
        undoBtn().click();
        expect(send).toHaveBeenCalledWith({
            type: 'edit_ai_history_message',
            channel_id: CHANNEL_A,
            id: 7,
            content: 'old text',
        });
    });

    it('is blocked with a warning while an editor is open', () => {
        const { hm, send } = mountHistory();
        loadTwoMessages(hm);
        confirmEdit(hm, 7, 'edited first');
        // Re-open an editor, then try to undo.
        (document.querySelectorAll('.history-edit-btn')[1] as HTMLElement).click();
        (document.querySelector('.edit-textarea') as HTMLTextAreaElement).value = 'draft';
        send.mockClear();
        undoBtn().click();
        expect(send).not.toHaveBeenCalled();
        expect(document.getElementById('toast-container')!.textContent)
            .toContain('Finish or cancel the edit first');
        // The draft survives.
        expect((document.querySelector('.edit-textarea') as HTMLTextAreaElement).value).toBe('draft');
    });

    it('is silently gated while another mutation ack is in flight', async () => {
        const { hm, send } = mountHistory();
        loadTwoMessages(hm);
        confirmEdit(hm, 7, 'edited first'); // stack entry exists
        await hm.requestDelete(1);          // delete ack now in flight
        send.mockClear();
        hm.undo();
        expect(send).not.toHaveBeenCalled();
    });

    it('is gated while a channel load is pending', () => {
        const { hm, send } = mountHistory();
        loadOneMessage(hm);
        confirmEdit(hm, 7, 'new text');
        hm.loadAll(); // pendingChannelLoadId set until ai_history_loaded lands
        send.mockClear();
        hm.undo();
        expect(send).not.toHaveBeenCalled();
    });

    it('the button DISABLES while a normal edit ack is in flight (no dead affordance)', () => {
        const { hm } = mountHistory();
        loadTwoMessages(hm);
        confirmEdit(hm, 7, 'edited first'); // non-empty stack
        expect(undoBtn().disabled).toBe(false);
        // Start a second edit save — its ack is now in flight.
        (document.querySelectorAll('.history-edit-btn')[1] as HTMLElement).click();
        (document.querySelector('.edit-textarea') as HTMLTextAreaElement).value = 'second draft';
        (document.querySelector('.edit-save-btn') as HTMLElement).click();
        expect(undoBtn().disabled).toBe(true);
        // The settling ack re-enables it.
        hm.handleMessage({
            type: 'ai_history_message_edited',
            channel_id: CHANNEL_A,
            id: 8,
            content: 'second draft',
            live_session: 'patched',
            live_session_patched: true,
        });
        expect(undoBtn().disabled).toBe(false);
    });

    it('the button re-enables when an edit save send() fails (rollback renders)', () => {
        const { hm, send } = mountHistory();
        loadTwoMessages(hm);
        confirmEdit(hm, 7, 'edited first'); // non-empty stack
        (document.querySelectorAll('.history-edit-btn')[1] as HTMLElement).click();
        (document.querySelector('.edit-textarea') as HTMLTextAreaElement).value = 'second draft';
        send.mockReturnValueOnce(false);
        (document.querySelector('.edit-save-btn') as HTMLElement).click();
        // Rolled back — the undo is immediately available again.
        expect(undoBtn().disabled).toBe(false);
    });

    it('the button DISABLES while a delete ack is in flight, and on its send() rollback re-enables', async () => {
        const { hm, send } = mountHistory();
        loadTwoMessages(hm);
        confirmEdit(hm, 7, 'edited first'); // non-empty stack
        expect(undoBtn().disabled).toBe(false);
        // Dead socket first: requestDelete rolls back and re-renders.
        send.mockReturnValueOnce(false);
        await hm.requestDelete(1);
        expect(undoBtn().disabled).toBe(false);
        // Live socket: the delete ack is in flight until it settles.
        await hm.requestDelete(1);
        expect(undoBtn().disabled).toBe(true);
        hm.handleMessage({
            type: 'ai_history_message_deleted',
            channel_id: CHANNEL_A,
            id: 8,
            live_session: 'patched',
            live_session_patched: true,
            total_count: 1,
        });
        expect(undoBtn().disabled).toBe(false);
    });

    it('the button DISABLES while a channel load is pending (loadAll)', () => {
        const { hm } = mountHistory();
        loadOneMessage(hm);
        confirmEdit(hm, 7, 'new text');
        expect(undoBtn().disabled).toBe(false);
        hm.loadAll();
        expect(undoBtn().disabled).toBe(true);
        // The arriving load re-enables it (the stack still has the entry).
        hm.handleMessage({
            type: 'ai_history_loaded',
            channel_id: CHANNEL_A,
            messages: [makeMessage({ id: 7, local_id: 5, role: 'model', content: 'new text' })],
            total_count: 1,
            has_more: false,
        });
        expect(undoBtn().disabled).toBe(false);
    });

    it('scopes entries per channel, and a foreign-channel ack still pushes', () => {
        const { hm, send } = mountHistory();
        loadOneMessage(hm); // channel A, id 7, 'old text'
        // Start an edit save on A…
        (document.querySelector('.history-edit-btn') as HTMLElement).click();
        (document.querySelector('.edit-textarea') as HTMLTextAreaElement).value = 'new text';
        (document.querySelector('.edit-save-btn') as HTMLElement).click(); // ack in flight
        // …and switch to B BEFORE the ack arrives.
        hm.openChannel(CHANNEL_B);
        hm.handleMessage({
            type: 'ai_history_loaded',
            channel_id: CHANNEL_B,
            messages: [makeMessage({ id: 50, content: 'b text' })],
            total_count: 1,
            has_more: false,
        });
        // The A-ack lands while B is open: the DB write DID happen, so the
        // undo entry is pushed for A (keyed by channel+id, not current view)…
        hm.handleMessage({
            type: 'ai_history_message_edited',
            channel_id: CHANNEL_A,
            id: 7,
            content: 'new text',
            live_session: 'patched',
            live_session_patched: true,
        });
        // …but B offers no undo for it.
        expect(undoBtn().disabled).toBe(true);
        send.mockClear();
        hm.undo();
        expect(send).not.toHaveBeenCalled();
        // Back on A the entry is offered, and the reverse edit goes out.
        hm.openChannel(CHANNEL_A);
        hm.handleMessage({
            type: 'ai_history_loaded',
            channel_id: CHANNEL_A,
            messages: [makeMessage({ id: 7, content: 'new text' })],
            total_count: 1,
            has_more: false,
        });
        expect(undoBtn().disabled).toBe(false);
        send.mockClear();
        undoBtn().click();
        expect(send).toHaveBeenCalledWith({
            type: 'edit_ai_history_message',
            channel_id: CHANNEL_A,
            id: 7,
            content: 'old text',
        });
    });

    it('caps the stack at 20 — the oldest entry is shifted out', async () => {
        const { hm, send } = mountHistory();
        hm.openChannel(CHANNEL_A);
        const msgs = Array.from({ length: 21 }, (_, i) =>
            makeMessage({ id: i + 1, local_id: i + 1, content: `m${i + 1}` }));
        hm.handleMessage({
            type: 'ai_history_loaded',
            channel_id: CHANNEL_A,
            messages: msgs,
            total_count: 21,
            has_more: false,
        });
        // 21 ack-confirmed deletes, oldest row first each time.
        for (let id = 1; id <= 21; id++) {
            await hm.requestDelete(0);
            hm.handleMessage({
                type: 'ai_history_message_deleted',
                channel_id: CHANNEL_A,
                id,
                live_session: 'patched',
                live_session_patched: true,
                total_count: 21 - id,
            });
        }
        // Unwind: 20 restores succeed (newest delete first: ids 21 → 2)…
        for (let id = 21; id >= 2; id--) {
            send.mockClear();
            undoBtn().click();
            expect(send).toHaveBeenCalledWith(expect.objectContaining({
                type: 'restore_ai_history_message',
                channel_id: CHANNEL_A,
                message: expect.objectContaining({ id }),
            }));
            hm.handleMessage({
                type: 'ai_history_message_restored',
                channel_id: CHANNEL_A,
                id,
                live_session: 'patched',
                live_session_patched: true,
                total_count: 22 - id,
            });
        }
        // …but the 21st (the oldest delete, id 1) was shifted out by the cap.
        expect(undoBtn().disabled).toBe(true);
        send.mockClear();
        hm.undo();
        expect(send).not.toHaveBeenCalled();
        expect(hm.messages.map(m => m.id)).toEqual(Array.from({ length: 20 }, (_, i) => i + 2));
    });

    it('an edit-undo settling AT the 20-cap keeps the oldest entry (pop frees the slot before the redo push)', () => {
        const { hm, send } = mountHistory();
        // One confirmed edit on channel B — the eventual OLDEST entry.
        hm.openChannel(CHANNEL_B);
        hm.handleMessage({
            type: 'ai_history_loaded',
            channel_id: CHANNEL_B,
            messages: [makeMessage({ id: 50, local_id: 1, content: 'b original' })],
            total_count: 1,
            has_more: false,
        });
        (document.querySelector('.history-edit-btn') as HTMLElement).click();
        (document.querySelector('.edit-textarea') as HTMLTextAreaElement).value = 'b edited';
        (document.querySelector('.edit-save-btn') as HTMLElement).click();
        hm.handleMessage({
            type: 'ai_history_message_edited',
            channel_id: CHANNEL_B,
            id: 50,
            content: 'b edited',
            live_session: 'patched',
            live_session_patched: true,
        });
        // Then 19 confirmed edits on channel A fill the stack to the cap.
        hm.openChannel(CHANNEL_A);
        hm.handleMessage({
            type: 'ai_history_loaded',
            channel_id: CHANNEL_A,
            messages: [makeMessage({ id: 7, local_id: 1, content: 'v0' })],
            total_count: 1,
            has_more: false,
        });
        for (let i = 1; i <= 19; i++) confirmEdit(hm, 7, `v${i}`);
        // Undo the newest A edit; its edited ack settles AT the cap: the pop
        // must free a slot for the redo push instead of evicting B's entry.
        send.mockClear();
        undoBtn().click();
        expect(send).toHaveBeenCalledWith(expect.objectContaining({
            type: 'edit_ai_history_message',
            channel_id: CHANNEL_A,
            id: 7,
            content: 'v18',
        }));
        hm.handleMessage({
            type: 'ai_history_message_edited',
            channel_id: CHANNEL_A,
            id: 7,
            content: 'v18',
            live_session: 'patched',
            live_session_patched: true,
        });
        // Back on B, the oldest entry survived the cap and is still undoable.
        hm.openChannel(CHANNEL_B);
        hm.handleMessage({
            type: 'ai_history_loaded',
            channel_id: CHANNEL_B,
            messages: [makeMessage({ id: 50, local_id: 1, content: 'b edited' })],
            total_count: 1,
            has_more: false,
        });
        expect(undoBtn().disabled).toBe(false);
        send.mockClear();
        undoBtn().click();
        expect(send).toHaveBeenCalledWith({
            type: 'edit_ai_history_message',
            channel_id: CHANNEL_B,
            id: 50,
            content: 'b original',
        });
    });
});

// ============================================================================
// Keyboard-accessible channel list (role=listbox / role=option, roving
// tabindex, Enter/Space activation, arrow-key navigation).
// ============================================================================

function loadChannels(
    hm: import('./history-manager.js').HistoryManager,
    n = 3,
): void {
    hm.handleMessage({
        type: 'ai_channels_list',
        channels: Array.from({ length: n }, (_, i) => ({
            channel_id: String(100000 + i),
            name: `channel ${i}`,
            message_count: i + 1,
            last_active: null,
        })),
    });
}

describe('channel list — keyboard accessibility', () => {
    it('renders the list as a listbox with option rows', () => {
        const { hm } = mountHistory();
        loadChannels(hm);
        const list = document.getElementById('ai-channel-list')!;
        expect(list.getAttribute('role')).toBe('listbox');
        const options = list.querySelectorAll('[role="option"]');
        expect(options.length).toBe(3);
        // Every option is reachable by AT and carries a selection state.
        options.forEach(o => {
            expect(o.getAttribute('aria-selected')).toBe('false');
            expect(o.hasAttribute('tabindex')).toBe(true);
        });
    });

    it('uses a roving tabindex — exactly one option is tabbable', () => {
        const { hm } = mountHistory();
        loadChannels(hm);
        const list = document.getElementById('ai-channel-list')!;
        const tabbable = list.querySelectorAll('[role="option"][tabindex="0"]');
        expect(tabbable.length).toBe(1);
        // With nothing selected, the FIRST option is the tab stop.
        expect((tabbable[0] as HTMLElement).dataset.channelId).toBe('100000');
    });

    it('marks the active channel aria-selected and points aria-activedescendant at it', () => {
        const { hm } = mountHistory();
        loadChannels(hm);
        hm.openChannel('100001');
        const list = document.getElementById('ai-channel-list')!;
        const active = list.querySelector('[aria-selected="true"]') as HTMLElement;
        expect(active).not.toBeNull();
        expect(active.dataset.channelId).toBe('100001');
        // The active option is the roving tab stop, and activedescendant tracks it.
        expect(active.getAttribute('tabindex')).toBe('0');
        expect(list.getAttribute('aria-activedescendant')).toBe(active.id);
        expect(active.id).toBe('ai-channel-opt-100001');
    });

    it('Enter on a focused option opens that channel', () => {
        const { hm, send } = mountHistory();
        loadChannels(hm);
        const list = document.getElementById('ai-channel-list')!;
        const row = list.querySelectorAll('[role="option"]')[1] as HTMLElement;
        send.mockClear();
        row.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
        expect(hm.currentChannelId).toBe('100001');
        expect(send).toHaveBeenCalledWith({
            type: 'load_ai_history',
            channel_id: '100001',
            limit: 200,
        });
    });

    it('Space on a focused option opens that channel (and is prevented from scrolling)', () => {
        const { hm, send } = mountHistory();
        loadChannels(hm);
        const list = document.getElementById('ai-channel-list')!;
        const row = list.querySelectorAll('[role="option"]')[2] as HTMLElement;
        send.mockClear();
        const ev = new KeyboardEvent('keydown', { key: ' ', bubbles: true, cancelable: true });
        row.dispatchEvent(ev);
        expect(ev.defaultPrevented).toBe(true);
        expect(hm.currentChannelId).toBe('100002');
        expect(send).toHaveBeenCalledWith(expect.objectContaining({
            type: 'load_ai_history', channel_id: '100002',
        }));
    });

    it('ArrowDown roves focus to the next option without changing selection', () => {
        const { hm, send } = mountHistory();
        loadChannels(hm);
        const list = document.getElementById('ai-channel-list')!;
        const rows = list.querySelectorAll('[role="option"]');
        const first = rows[0] as HTMLElement;
        first.focus();
        send.mockClear();
        first.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }));
        // Focus + the tabindex anchor moved to row 1; NO channel was opened.
        expect(document.activeElement).toBe(rows[1]);
        expect((rows[1] as HTMLElement).getAttribute('tabindex')).toBe('0');
        expect((rows[0] as HTMLElement).getAttribute('tabindex')).toBe('-1');
        expect(send).not.toHaveBeenCalled();
        expect(hm.currentChannelId).toBeNull();
    });

    it('ArrowUp at the top stays put; End jumps to the last option', () => {
        const { hm } = mountHistory();
        loadChannels(hm);
        const list = document.getElementById('ai-channel-list')!;
        const rows = list.querySelectorAll('[role="option"]');
        (rows[0] as HTMLElement).focus();
        (rows[0] as HTMLElement).dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowUp', bubbles: true }));
        expect(document.activeElement).toBe(rows[0]);
        (rows[0] as HTMLElement).dispatchEvent(new KeyboardEvent('keydown', { key: 'End', bubbles: true }));
        expect(document.activeElement).toBe(rows[2]);
    });
});

// ============================================================================
// Channel filter (debounced) + transcript find box
// ============================================================================

describe('channel filter', () => {
    it('builds a filter input and narrows the rendered channels (debounced)', () => {
        vi.useFakeTimers();
        try {
            const { hm } = mountHistory();
            hm.handleMessage({
                type: 'ai_channels_list',
                channels: [
                    { channel_id: '1', name: 'general', message_count: 1, last_active: null },
                    { channel_id: '2', name: 'support', message_count: 1, last_active: null },
                    { channel_id: '3', name: 'general-2', message_count: 1, last_active: null },
                ],
            });
            const input = document.getElementById('ai-history-channel-filter') as HTMLInputElement;
            expect(input).not.toBeNull();
            input.value = 'gener';
            input.dispatchEvent(new Event('input'));
            vi.advanceTimersByTime(120); // flush the debounce
            const list = document.getElementById('ai-channel-list')!;
            const rows = list.querySelectorAll('.history-channel-item');
            expect(rows.length).toBe(2);
            expect(list.textContent).toContain('general');
            expect(list.textContent).not.toContain('support');
        } finally {
            vi.useRealTimers();
        }
    });

    it('shows a no-matches empty state when the filter excludes everything', () => {
        vi.useFakeTimers();
        try {
            const { hm } = mountHistory();
            loadChannels(hm, 3);
            const input = document.getElementById('ai-history-channel-filter') as HTMLInputElement;
            input.value = 'zzzz-nope';
            input.dispatchEvent(new Event('input'));
            vi.advanceTimersByTime(120);
            const list = document.getElementById('ai-channel-list')!;
            expect(list.querySelectorAll('.history-channel-item').length).toBe(0);
            expect(list.textContent).toContain('No matching channels');
            expect(list.textContent).toContain('zzzz-nope');
        } finally {
            vi.useRealTimers();
        }
    });
});

describe('transcript find', () => {
    it('openFind reveals the bar; typing wraps matches and reports the count', () => {
        vi.useFakeTimers();
        try {
            const { hm } = mountHistory();
            hm.openChannel(CHANNEL_A);
            hm.handleMessage({
                type: 'ai_history_loaded',
                channel_id: CHANNEL_A,
                messages: [
                    makeMessage({ id: 1, content: 'alpha needle beta' }),
                    makeMessage({ id: 2, role: 'model', content: 'gamma needle needle' }),
                ],
                total_count: 2,
                has_more: false,
            });
            hm.openFind();
            const bar = document.getElementById('ai-history-search-bar')!;
            expect(bar.classList.contains('hidden')).toBe(false);
            const input = document.getElementById('ai-history-search-input') as HTMLInputElement;
            input.value = 'needle';
            input.dispatchEvent(new Event('input'));
            vi.advanceTimersByTime(120);
            const marks = document.querySelectorAll('#ai-history-messages mark.chat-search-hit');
            expect(marks.length).toBe(3); // 1 + 2 occurrences
            expect(document.getElementById('ai-history-search-count')!.textContent).toBe('1 / 3');
        } finally {
            vi.useRealTimers();
        }
    });

    it('closeFind hides the bar and strips the highlights', () => {
        vi.useFakeTimers();
        try {
            const { hm } = mountHistory();
            hm.openChannel(CHANNEL_A);
            hm.handleMessage({
                type: 'ai_history_loaded',
                channel_id: CHANNEL_A,
                messages: [makeMessage({ id: 1, content: 'find me here' })],
                total_count: 1,
                has_more: false,
            });
            hm.openFind();
            const input = document.getElementById('ai-history-search-input') as HTMLInputElement;
            input.value = 'find';
            input.dispatchEvent(new Event('input'));
            vi.advanceTimersByTime(120);
            expect(document.querySelectorAll('#ai-history-messages mark.chat-search-hit').length).toBe(1);
            hm.closeFind();
            expect(document.getElementById('ai-history-search-bar')!.classList.contains('hidden')).toBe(true);
            expect(document.querySelectorAll('#ai-history-messages mark.chat-search-hit').length).toBe(0);
            // The original text survives intact after unwrapping.
            expect(document.getElementById('ai-history-messages')!.textContent).toContain('find me here');
        } finally {
            vi.useRealTimers();
        }
    });

    it('find skips the meta/badge chrome (role badge, user id, timestamp)', () => {
        vi.useFakeTimers();
        try {
            const { hm } = mountHistory();
            hm.openChannel(CHANNEL_A);
            hm.handleMessage({
                type: 'ai_history_loaded',
                channel_id: CHANNEL_A,
                messages: [makeMessage({ id: 1, content: 'plain body', user_id: 'zzuseridzz' })],
                total_count: 1,
                has_more: false,
            });
            // Sanity: the user id IS rendered, but only inside the meta chrome.
            expect(
                document.querySelector('#ai-history-messages .history-msg-user-id')!.textContent,
            ).toContain('zzuseridzz');
            hm.openFind();
            const input = document.getElementById('ai-history-search-input') as HTMLInputElement;
            input.value = 'zzuseridzz';
            input.dispatchEvent(new Event('input'));
            vi.advanceTimersByTime(120);
            // The only match lives in the meta chrome, so nothing should highlight.
            expect(document.querySelectorAll('#ai-history-messages mark.chat-search-hit').length).toBe(0);
            expect(document.getElementById('ai-history-search-count')!.textContent).toBe('0 / 0');
        } finally {
            vi.useRealTimers();
        }
    });
});

// ============================================================================
// List semantics + loading / empty states
// ============================================================================

describe('message viewer semantics + states', () => {
    it('the viewer is a role=log and rows are role=listitem with a role-conveying aria-label', () => {
        const { hm } = mountHistory();
        hm.openChannel(CHANNEL_A);
        hm.handleMessage({
            type: 'ai_history_loaded',
            channel_id: CHANNEL_A,
            messages: [
                makeMessage({ id: 1, role: 'user', content: 'hi' }),
                makeMessage({ id: 2, role: 'model', content: 'yo' }),
            ],
            total_count: 2,
            has_more: false,
        });
        const container = document.getElementById('ai-history-messages')!;
        expect(container.getAttribute('role')).toBe('log');
        const rows = container.querySelectorAll('.history-msg[role="listitem"]');
        expect(rows.length).toBe(2);
        expect(rows[0].getAttribute('aria-label')).toBe('User message');
        expect(rows[1].getAttribute('aria-label')).toBe('Model message');
    });

    it('shows a spinner/skeleton loading pane while a channel load is in flight', () => {
        const { hm } = mountHistory();
        hm.openChannel(CHANNEL_A); // load now in flight (loaded frame not delivered)
        const container = document.getElementById('ai-history-messages')!;
        expect(container.querySelector('.loading-spinner')).not.toBeNull();
        expect(container.querySelector('[role="status"]')).not.toBeNull();
        expect(container.textContent).toContain('Loading messages');
        // The loaded frame clears the loading pane.
        hm.handleMessage({
            type: 'ai_history_loaded',
            channel_id: CHANNEL_A,
            messages: [makeMessage({ id: 1, content: 'done' })],
            total_count: 1,
            has_more: false,
        });
        expect(container.querySelector('.loading-spinner')).toBeNull();
        expect(container.textContent).toContain('done');
    });

    it('shows an iconographic empty state for a channel with no messages', () => {
        const { hm } = mountHistory();
        hm.openChannel(CHANNEL_A);
        hm.handleMessage({
            type: 'ai_history_loaded',
            channel_id: CHANNEL_A,
            messages: [],
            total_count: 0,
            has_more: false,
        });
        const container = document.getElementById('ai-history-messages')!;
        expect(container.querySelector('.empty-state')).not.toBeNull();
        expect(container.querySelector('.empty-state svg use')!.getAttribute('href')).toBe('#i-inbox');
        expect(container.textContent).toContain('No messages');
    });

    it('the overflow/cap note is a status region', () => {
        const { hm } = mountHistory();
        hm.openChannel(CHANNEL_A);
        const msgs = Array.from({ length: 501 }, (_, i) =>
            makeMessage({ id: i + 1, content: `m${i}` }));
        hm.handleMessage({
            type: 'ai_history_loaded',
            channel_id: CHANNEL_A,
            messages: msgs,
            total_count: 501,
            has_more: false,
        });
        const note = document.querySelector('#ai-history-messages .history-overflow-note')!;
        expect(note.getAttribute('role')).toBe('status');
        expect(note.textContent).toContain('newest 500');
    });
});

// ============================================================================
// In-place row updates (no full-list rebuild per single-row mutation)
// ============================================================================

describe('in-place row updates', () => {
    /** A capped 4-message channel where each row carries a stable data-id. */
    function loadFour(hm: import('./history-manager.js').HistoryManager): void {
        hm.openChannel(CHANNEL_A);
        hm.handleMessage({
            type: 'ai_history_loaded',
            channel_id: CHANNEL_A,
            messages: [
                makeMessage({ id: 7, role: 'user', content: 'one' }),
                makeMessage({ id: 8, role: 'model', content: 'two' }),
                makeMessage({ id: 9, role: 'user', content: 'three' }),
                makeMessage({ id: 10, role: 'model', content: 'four' }),
            ],
            total_count: 4,
            has_more: false,
        });
    }

    it('an edit ack patches only the affected row node (same node identity)', () => {
        const { hm } = mountHistory();
        loadFour(hm);
        const container = document.getElementById('ai-history-messages')!;
        const rowBefore = container.querySelector('.history-msg[data-id="8"]') as HTMLElement;
        const otherBefore = container.querySelector('.history-msg[data-id="7"]') as HTMLElement;
        hm.handleMessage({
            type: 'ai_history_message_edited',
            channel_id: CHANNEL_A,
            id: 8,
            content: 'two-edited',
            live_session: 'patched',
            live_session_patched: true,
        });
        const rowAfter = container.querySelector('.history-msg[data-id="8"]') as HTMLElement;
        const otherAfter = container.querySelector('.history-msg[data-id="7"]') as HTMLElement;
        // Same DOM nodes survived — no full rebuild.
        expect(rowAfter).toBe(rowBefore);
        expect(otherAfter).toBe(otherBefore);
        expect(rowAfter.querySelector('.history-msg-content')!.textContent).toBe('two-edited');
        expect(hm.messages.find(m => m.id === 8)!.content).toBe('two-edited');
    });

    it('a delete ack removes only the affected row and re-indexes the tail', async () => {
        const { hm } = mountHistory();
        loadFour(hm);
        const container = document.getElementById('ai-history-messages')!;
        const survivor = container.querySelector('.history-msg[data-id="7"]') as HTMLElement;
        await hm.requestDelete(1); // id 8
        hm.handleMessage({
            type: 'ai_history_message_deleted',
            channel_id: CHANNEL_A,
            id: 8,
            live_session: 'patched',
            live_session_patched: true,
            total_count: 3,
        });
        // The id-8 node is gone; the id-7 node is the SAME (no rebuild).
        expect(container.querySelector('.history-msg[data-id="8"]')).toBeNull();
        expect(container.querySelector('.history-msg[data-id="7"]')).toBe(survivor);
        // The rows after the deletion re-indexed down so data-idx stays the
        // absolute model index — clicking row id 9's edit opens messages[1].
        const row9 = container.querySelector('.history-msg[data-id="9"]') as HTMLElement;
        expect(row9.dataset.idx).toBe('1');
        (row9.querySelector('.history-edit-btn') as HTMLElement).click();
        expect((document.querySelector('.edit-textarea') as HTMLTextAreaElement).value).toBe('three');
    });

    it('a restore ack inserts only the affected row at its id-sorted spot', async () => {
        const { hm } = mountHistory();
        loadFour(hm);
        const container = document.getElementById('ai-history-messages')!;
        await hm.requestDelete(1); // id 8 (middle)
        hm.handleMessage({
            type: 'ai_history_message_deleted',
            channel_id: CHANNEL_A,
            id: 8,
            live_session: 'patched',
            live_session_patched: true,
            total_count: 3,
        });
        const survivor7 = container.querySelector('.history-msg[data-id="7"]') as HTMLElement;
        undoBtn().click(); // restore in flight
        hm.handleMessage({
            type: 'ai_history_message_restored',
            channel_id: CHANNEL_A,
            id: 8,
            live_session: 'patched',
            live_session_patched: true,
            total_count: 4,
        });
        // id 8 came back BETWEEN 7 and 9 (DOM order), and the untouched id-7
        // node is the same one (single-node insert, not a rebuild).
        const ids = Array.from(container.querySelectorAll('.history-msg[data-id]'))
            .map(r => (r as HTMLElement).dataset.id);
        expect(ids).toEqual(['7', '8', '9', '10']);
        expect(container.querySelector('.history-msg[data-id="7"]')).toBe(survivor7);
        // data-idx is re-synced to the absolute model index.
        expect((container.querySelector('.history-msg[data-id="9"]') as HTMLElement).dataset.idx).toBe('2');
    });
});
