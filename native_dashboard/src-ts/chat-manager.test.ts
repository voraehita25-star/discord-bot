/**
 * Tests for ChatManager — the orchestrator that ties the extracted chat/*
 * modules together. Focus is on the handleMessage() frame dispatcher and
 * the small state transitions (isStreaming, currentConversation, messages,
 * presets) that multiple callers depend on.
 *
 * We NEVER open a real WebSocket: ChatManager.wsClient.send is stubbed to
 * capture what would have been sent. The rest of the DOM surface + shared
 * state is real jsdom + real shared.ts.
 *
 * This isn't a full e2e of ChatManager; that would require bundling the
 * entire Tauri IPC layer. Instead we cover the deterministic frame
 * dispatcher + handler side-effects that the 11 extracted modules rely on.
 */

import { describe, it, expect, beforeEach, beforeAll, vi } from 'vitest';

// Tauri invoke is mocked at module-import time because shared.ts reads it.
vi.mock('@tauri-apps/api/core', () => ({ invoke: vi.fn().mockResolvedValue('') }));

// DOMPurify lives on window; load it once before importing ChatManager.
beforeAll(async () => {
    const DOMPurify = (await import('dompurify')).default;
    (window as unknown as { DOMPurify: unknown }).DOMPurify = DOMPurify(window);
    // jsdom doesn't implement these; ChatManager touches them in scrollToBottom.
    if (!Element.prototype.scrollIntoView) {
        Element.prototype.scrollIntoView = function () { /* no-op */ };
    }
    if (!Element.prototype.scrollTo) {
        Element.prototype.scrollTo = function () { /* no-op */ } as unknown as typeof Element.prototype.scrollTo;
    }
});

// Minimal set of DOM nodes that ChatManager's rendering + wiring touches.
// Mirrors the shape of index.html well enough for its reads to resolve.
const CHAT_DOM = `
    <div id="toast-container"></div>
    <div id="chat-empty"></div>
    <div id="chat-container" class="hidden"></div>
    <h3 id="chat-title"></h3>
    <img id="chat-role-avatar" class="hidden" alt="AI">
    <span id="chat-role-name"></span>
    <span id="chat-connection-status"></span>
    <select id="chat-ai-provider"><option value="gemini">Gemini</option><option value="claude">Claude</option></select>
    <input type="checkbox" id="thinking-toggle">
    <input type="checkbox" id="chat-unrestricted">
    <input type="checkbox" id="chat-use-search">

    <div id="context-window-indicator" style="display:none">
        <div id="context-bar-fill"></div>
        <span id="context-bar-label"></span>
    </div>

    <input type="text" id="conversation-filter-input">
    <div id="conversation-list"></div>
    <div id="chat-tags"></div>

    <div class="chat-messages-wrapper">
        <div class="chat-search-bar hidden" id="chat-search-bar">
            <input id="chat-search-input">
            <span id="chat-search-count">0 / 0</span>
            <button id="chat-search-prev"></button>
            <button id="chat-search-next"></button>
            <button id="chat-search-close"></button>
        </div>
        <div id="chat-messages"></div>
        <button id="scroll-to-bottom-fab" class="hidden"><span id="scroll-new-count"></span></button>
    </div>

    <div class="chat-input-area">
        <button id="btn-attach"></button>
        <input type="file" id="image-input">
        <div id="attached-images"></div>
        <textarea id="chat-input"></textarea>
        <button id="btn-send"></button>
    </div>

    <div id="new-chat-modal" class="modal">
        <button id="modal-close"></button>
        <button id="modal-cancel"></button>
        <button id="modal-create"></button>
        <div class="modal-overlay"></div>
        <input type="checkbox" id="modal-thinking">
        <select id="modal-ai-provider"><option value="gemini">G</option><option value="claude">C</option></select>
        <div class="role-card" data-role="general"></div>
        <div class="role-card" data-role="faust"></div>
    </div>

    <div id="delete-confirm-modal" class="modal">
        <button id="delete-cancel"></button>
        <button id="delete-confirm"></button>
    </div>
    <div id="rename-modal" class="modal">
        <input id="rename-input">
        <button id="rename-cancel"></button>
        <button id="rename-confirm"></button>
    </div>

    <button id="btn-new-chat"></button>
    <button id="btn-new-chat-main"></button>
    <button id="btn-rename-chat"></button>
    <button id="btn-star-chat"></button>
    <button id="btn-export-chat"></button>
    <button id="btn-export-all"></button>
    <button id="btn-delete-chat"></button>
`;

// Late import of ChatManager — AFTER the DOMPurify stub + DOM are in place.
// Vitest resets modules between test files by default, so this is fresh per file.
let ChatManager: typeof import('./chat-manager.js').ChatManager;

beforeAll(async () => {
    const mod = await import('./chat-manager.js');
    ChatManager = mod.ChatManager;
});

function mountDomAndChat(): import('./chat-manager.js').ChatManager {
    document.body.innerHTML = CHAT_DOM;
    const cm = new ChatManager();
    // Stub wsClient.send so assertions can read outgoing frames without needing a socket.
    cm.wsClient.send = vi.fn();
    return cm;
}

beforeEach(() => {
    document.body.innerHTML = CHAT_DOM;
});

// ============================================================================
// handleMessage — frame dispatcher
// ============================================================================

describe('handleMessage — connected frame', () => {
    it('populates presets from the server', () => {
        const cm = mountDomAndChat();
        cm.handleMessage({
            type: 'connected',
            presets: { faust: { name: 'Faust', emoji: '👻', color: '#ffb1b4' } },
        });
        expect(cm.presets.faust).toEqual({ name: 'Faust', emoji: '👻', color: '#ffb1b4' });
    });

    it('does NOT re-send an auth frame on the connected event when a token is present', () => {
        // ws-client already sends `{type:'auth'}` in onopen — the previous
        // double-send was a protocol-violation hazard. The connected event
        // should now be a no-op for auth (just verify token presence).
        const cm = mountDomAndChat();
        (cm.wsClient as unknown as { wsToken: string }).wsToken = 'secret';
        cm.handleMessage({ type: 'connected', requires_auth: true });
        const sendSpy = cm.wsClient.send as unknown as { mock: { calls: unknown[][] } };
        const authCalls = sendSpy.mock.calls.filter(
            (call) => (call[0] as { type?: string } | undefined)?.type === 'auth',
        );
        expect(authCalls).toHaveLength(0);
    });

    it('updates availableProviders from the payload', () => {
        const cm = mountDomAndChat();
        cm.handleMessage({
            type: 'connected',
            available_providers: ['gemini', 'claude'],
        });
        expect(cm.availableProviders).toEqual(['gemini', 'claude']);
    });

    it('re-issues load_conversation for the open conversation on (re)connect', () => {
        const cm = mountDomAndChat();
        cm.currentConversation = {
            id: 'conv-7', title: 't', role_preset: 'general', thinking_enabled: false,
            is_starred: false, created_at: '2026-04-01',
        };
        cm.handleMessage({ type: 'connected', presets: {} });
        // After a reconnect, the persisted final assistant message is re-fetched
        // so a stream-interrupting drop doesn't leave a half-written answer.
        expect(cm.wsClient.send).toHaveBeenCalledWith(
            expect.objectContaining({ type: 'load_conversation', id: 'conv-7' }),
        );
        // And the pending-load guard is armed so the conversation_loaded race
        // logic treats the reload as the current request.
        expect((cm as unknown as { pendingConversationLoadId: string | null })
            .pendingConversationLoadId).toBe('conv-7');
    });

    it('does NOT re-issue load_conversation when no conversation is open', () => {
        const cm = mountDomAndChat();
        cm.handleMessage({ type: 'connected', presets: {} });
        const sendSpy = cm.wsClient.send as unknown as { mock: { calls: unknown[][] } };
        const loadCalls = sendSpy.mock.calls.filter(
            (call) => (call[0] as { type?: string } | undefined)?.type === 'load_conversation',
        );
        expect(loadCalls).toHaveLength(0);
    });
});

describe('handleMessage — conversations_list', () => {
    it('stores the list + renders the sidebar', () => {
        const cm = mountDomAndChat();
        cm.handleMessage({
            type: 'conversations_list',
            conversations: [
                { id: 'a', title: 'First', role_preset: 'general', thinking_enabled: false, is_starred: false, created_at: '2026-01-01' },
                { id: 'b', title: 'Second', role_preset: 'general', thinking_enabled: false, is_starred: false, created_at: '2026-01-02' },
            ],
        });
        expect(cm.conversations.length).toBe(2);
        expect(document.querySelectorAll('.conversation-item').length).toBe(2);
    });

    it('restores last-opened conversation when one is configured and exists', async () => {
        const { settings } = await import('./shared.js');
        const cm = mountDomAndChat();
        // loadConversation() only sends a WS frame when the client is already
        // connected — the `connected` frame handler normally sets this true,
        // but we're calling handleMessage directly for this test.
        (cm.wsClient as unknown as { connected: boolean }).connected = true;
        settings.lastConversationId = 'a';
        cm.handleMessage({
            type: 'conversations_list',
            conversations: [
                { id: 'a', title: 'First', role_preset: 'general', thinking_enabled: false, is_starred: false, created_at: '2026-01-01' },
            ],
        });
        expect(cm.wsClient.send).toHaveBeenCalledWith(expect.objectContaining({ type: 'load_conversation', id: 'a' }));
    });
});

describe('handleMessage — conversation_loaded', () => {
    it('sets currentConversation + messages + renders the chat container', () => {
        const cm = mountDomAndChat();
        cm.handleMessage({
            type: 'conversation_loaded',
            conversation: {
                id: 'c1',
                title: 'Talk',
                role_preset: 'general',
                thinking_enabled: false,
                is_starred: false,
                created_at: '2026-04-01',
            },
            messages: [
                { id: 1, role: 'user', content: 'hi', created_at: '2026-04-01' },
                { id: 2, role: 'assistant', content: 'hello', created_at: '2026-04-01' },
            ],
        });
        expect(cm.currentConversation?.id).toBe('c1');
        expect(cm.messages.length).toBe(2);
        expect(document.getElementById('chat-container')!.classList.contains('hidden')).toBe(false);
    });

    it('resets visibleMessageCount on conversation switch', () => {
        const cm = mountDomAndChat();
        // First conversation loads — 50 msgs.
        cm.handleMessage({
            type: 'conversation_loaded',
            conversation: { id: 'a', title: 'A', role_preset: 'general', thinking_enabled: false, is_starred: false, created_at: '2026-04-01' },
            messages: Array.from({ length: 50 }, (_, i) => ({
                id: i, role: 'user' as const, content: String(i), created_at: '2026-04-01',
            })),
        });

        // Second conversation loads — the visible count should reset to the default window.
        cm.handleMessage({
            type: 'conversation_loaded',
            conversation: { id: 'b', title: 'B', role_preset: 'general', thinking_enabled: false, is_starred: false, created_at: '2026-04-02' },
            messages: Array.from({ length: 5 }, (_, i) => ({
                id: i, role: 'user' as const, content: String(i), created_at: '2026-04-02',
            })),
        });
        // Internal state — not public but exposed on instance.
        expect((cm as unknown as { visibleMessageCount: number }).visibleMessageCount).toBe(100);
    });
});

describe('handleMessage — streaming lifecycle', () => {
    it('stream_start → isStreaming=true and creates a streaming message node', () => {
        const cm = mountDomAndChat();
        cm.currentConversation = {
            id: 'c', title: 't', role_preset: 'general', thinking_enabled: false,
            is_starred: false, created_at: '2026-04-01',
        };
        cm.handleMessage({ type: 'stream_start', mode: 'thinking' });
        expect(cm.isStreaming).toBe(true);
        expect(document.getElementById('streaming-message')).not.toBeNull();
    });

    it('stream_end → isStreaming=false and clears the streaming id', () => {
        const cm = mountDomAndChat();
        cm.currentConversation = {
            id: 'c', title: 't', role_preset: 'general', thinking_enabled: false,
            is_starred: false, created_at: '2026-04-01',
        };
        cm.handleMessage({ type: 'stream_start' });
        cm.handleMessage({ type: 'chunk', content: 'Hello' });
        cm.handleMessage({ type: 'stream_end', full_response: 'Hello there' });
        expect(cm.isStreaming).toBe(false);
        expect(document.getElementById('streaming-message')).toBeNull();
    });

    it('thinking_chunk appends to the thinking block only', () => {
        const cm = mountDomAndChat();
        cm.currentConversation = {
            id: 'c', title: 't', role_preset: 'general', thinking_enabled: false,
            is_starred: false, created_at: '2026-04-01',
        };
        cm.handleMessage({ type: 'stream_start' });
        cm.handleMessage({ type: 'thinking_start' });
        cm.handleMessage({ type: 'thinking_chunk', content: 'reasoning…' });
        const thinkingContent = document.querySelector('#streaming-message .thinking-content');
        expect(thinkingContent?.textContent || '').toContain('reasoning');
    });

    it('preserves an in-progress stream across a conversation switch and restores the partial on return', () => {
        const cm = mountDomAndChat();
        const convA = { id: 'A', title: 'A', role_preset: 'general', thinking_enabled: false, is_starred: false, created_at: '2026-04-01' };
        const convB = { id: 'B', title: 'B', role_preset: 'general', thinking_enabled: false, is_starred: false, created_at: '2026-04-02' };

        // Open A and start streaming a response into it.
        cm.handleMessage({ type: 'conversation_loaded', conversation: convA, messages: [{ id: 1, role: 'user', content: 'hi', created_at: '2026-04-01' }] });
        cm.handleMessage({ type: 'stream_start', mode: '' });
        cm.handleMessage({ type: 'chunk', content: 'Partial answer' });
        expect(cm.isStreaming).toBe(true);

        // Switch to B mid-stream — the response stream is PRESERVED (not abandoned),
        // and its bubble isn't shown in B's view.
        cm.handleMessage({ type: 'conversation_loaded', conversation: convB, messages: [] });
        expect(cm.isStreaming).toBe(true);
        expect(cm.streamingConversationId).toBe('A');
        expect(document.getElementById('streaming-message')).toBeNull();

        // A chunk arriving while viewing B must still buffer.
        cm.handleMessage({ type: 'chunk', content: ' continued' });

        // Switch back to A — the in-progress bubble is restored with the FULL partial.
        cm.handleMessage({ type: 'conversation_loaded', conversation: convA, messages: [{ id: 1, role: 'user', content: 'hi', created_at: '2026-04-01' }] });
        const bubble = document.getElementById('streaming-message');
        expect(bubble).not.toBeNull();
        expect(bubble!.querySelector('.streaming-text')?.textContent).toBe('Partial answer continued');
        expect(cm.isStreaming).toBe(true);

        // Stream completes normally — finalized into messages, bubble cleared.
        cm.handleMessage({ type: 'stream_end', full_response: 'Partial answer continued. Done.' });
        expect(cm.isStreaming).toBe(false);
        expect(document.getElementById('streaming-message')).toBeNull();
        expect(cm.messages[cm.messages.length - 1]).toMatchObject({ role: 'assistant', content: 'Partial answer continued. Done.' });
    });

    it('does NOT paint a stream into the open conversation when it is bound to another (switch-then-start)', () => {
        const cm = mountDomAndChat();
        const convA = { id: 'A', title: 'A', role_preset: 'general', thinking_enabled: false, is_starred: false, created_at: '2026-04-01' };
        const convB = { id: 'B', title: 'B', role_preset: 'general', thinking_enabled: false, is_starred: false, created_at: '2026-04-02' };

        // Open A and queue a user turn (sets the streaming intent for A).
        cm.handleMessage({ type: 'conversation_loaded', conversation: convA, messages: [{ id: 1, role: 'user', content: 'ask A', created_at: '2026-04-01' }] });
        cm.isStreaming = true;
        cm.streamingConversationId = 'A';

        // The user navigates to B BEFORE the server's stream_start lands.
        cm.handleMessage({ type: 'conversation_loaded', conversation: convB, messages: [] });
        expect(cm.currentConversation?.id).toBe('B');

        // stream_start arrives bound to A (server-side id), then a chunk. Because
        // A isn't on screen, no bubble must be drawn into B's #chat-messages —
        // the chunk only buffers (restoreStreamingBubble replays it on return).
        cm.handleMessage({ type: 'stream_start', mode: '', conversation_id: 'A' });
        cm.handleMessage({ type: 'chunk', content: "A's secret answer" });

        const messages = document.getElementById('chat-messages')!;
        expect(document.getElementById('streaming-message')).toBeNull();
        const leaked = Array.from(messages.querySelectorAll('.streaming-text'))
            .some(el => (el.textContent || '').includes("A's secret answer"));
        expect(leaked).toBe(false);

        // The buffer still holds A's partial, so returning to A replays it.
        cm.handleMessage({ type: 'conversation_loaded', conversation: convA, messages: [{ id: 1, role: 'user', content: 'ask A', created_at: '2026-04-01' }] });
        expect(document.querySelector('#streaming-message .streaming-text')?.textContent).toContain("A's secret answer");
    });
});

describe('formatTime — invalid input', () => {
    it('returns the raw string for a malformed timestamp (never "Invalid Date")', () => {
        const cm = mountDomAndChat();
        const out = cm.formatTime('not-a-real-date');
        expect(out).not.toContain('Invalid Date');
        expect(out).toBe('not-a-real-date');
    });

    it('returns the raw (empty) string for an empty timestamp', () => {
        const cm = mountDomAndChat();
        const out = cm.formatTime('');
        expect(out).not.toContain('Invalid Date');
        expect(out).toBe('');
    });
});

describe('handleMessage — tag mutations', () => {
    it('conversation_tagged updates the current conversation tags + re-renders chips', () => {
        const cm = mountDomAndChat();
        cm.currentConversation = {
            id: 'c1', title: 't', role_preset: 'general', thinking_enabled: false,
            is_starred: false, created_at: '2026-04-01', tags: [],
        };
        cm.handleMessage({
            type: 'conversation_tagged',
            conversation_id: 'c1',
            tag: 'important',
            added: true,
            tags: ['important'],
        });
        expect(cm.currentConversation.tags).toEqual(['important']);
        expect(document.querySelectorAll('.tag-chip').length).toBe(1);
    });

    it('does NOT mutate when the tagged conversation is not the current one', () => {
        const cm = mountDomAndChat();
        cm.currentConversation = {
            id: 'c1', title: 't', role_preset: 'general', thinking_enabled: false,
            is_starred: false, created_at: '2026-04-01', tags: [],
        };
        cm.handleMessage({
            type: 'conversation_tagged',
            conversation_id: 'c2',   // a different conversation
            tag: 'work',
            added: true,
            tags: ['work'],
        });
        expect(cm.currentConversation.tags).toEqual([]);
    });
});

describe('handleMessage — message-level mutations', () => {
    it('message_pinned flips is_pinned on the matching local message', () => {
        const cm = mountDomAndChat();
        cm.messages = [
            { id: 1, role: 'user', content: 'hi', created_at: 't' },
            { id: 2, role: 'assistant', content: 'hello', created_at: 't', is_pinned: false },
        ];
        cm.handleMessage({ type: 'message_pinned', message_id: 2, pinned: true });
        expect(cm.messages[1].is_pinned).toBe(true);
    });

    it('message_liked flips liked on the matching local message', () => {
        const cm = mountDomAndChat();
        cm.messages = [
            { id: 1, role: 'user', content: 'hi', created_at: 't' },
            { id: 2, role: 'assistant', content: 'hello', created_at: 't', liked: false },
        ];
        cm.handleMessage({ type: 'message_liked', message_id: 2, liked: true });
        expect(cm.messages[1].liked).toBe(true);
    });

    it('message_deleted removes the message from the local array', () => {
        const cm = mountDomAndChat();
        cm.messages = [
            { id: 1, role: 'user', content: 'hi', created_at: 't' },
            { id: 2, role: 'assistant', content: 'hello', created_at: 't' },
            { id: 3, role: 'user', content: 'follow up', created_at: 't' },
        ];
        cm.handleMessage({ type: 'message_deleted', message_id: 2, pair_message_id: null });
        expect(cm.messages.map(m => m.id)).toEqual([1, 3]);
    });

    it('message_deleted with pair removes both', () => {
        const cm = mountDomAndChat();
        cm.messages = [
            { id: 1, role: 'user', content: 'hi', created_at: 't' },
            { id: 2, role: 'assistant', content: 'hello', created_at: 't' },
        ];
        cm.handleMessage({ type: 'message_deleted', message_id: 1, pair_message_id: 2 });
        expect(cm.messages.length).toBe(0);
    });
});

describe('updateProviderSelects — provider labels', () => {
    it('labels known providers and capitalizes an unknown third provider', () => {
        const cm = mountDomAndChat();
        // A third provider beyond gemini/claude must NOT be mislabelled "Claude".
        cm.availableProviders = ['gemini', 'claude', 'openai'];
        cm.aiProvider = 'gemini';
        cm.updateProviderSelects();

        const select = document.getElementById('chat-ai-provider') as HTMLSelectElement;
        const labels = Array.from(select.options).map(o => o.textContent);
        expect(labels).toEqual(['Gemini', 'Claude', 'Openai']);
    });

    it('keeps the option values as the raw provider ids', () => {
        const cm = mountDomAndChat();
        cm.availableProviders = ['gemini', 'claude', 'openai'];
        cm.aiProvider = 'claude';
        cm.updateProviderSelects();

        const select = document.getElementById('chat-ai-provider') as HTMLSelectElement;
        const values = Array.from(select.options).map(o => o.value);
        expect(values).toEqual(['gemini', 'claude', 'openai']);
        // The current provider stays selected.
        expect(select.value).toBe('claude');
    });
});

describe('handleMessage — connection signalling', () => {
    it('pong clears the ws-client pongPending flag', () => {
        const cm = mountDomAndChat();
        const spy = vi.spyOn(cm.wsClient, 'notePong');
        cm.handleMessage({ type: 'pong' });
        expect(spy).toHaveBeenCalledOnce();
    });

    it('error frame does not throw on missing message field', () => {
        const cm = mountDomAndChat();
        expect(() => cm.handleMessage({ type: 'error' })).not.toThrow();
    });
});

// ============================================================================
// State transitions invoked directly
// ============================================================================

describe('sendMessage — prerequisites', () => {
    it('is a no-op when there is no current conversation', () => {
        const cm = mountDomAndChat();
        (document.getElementById('chat-input') as HTMLTextAreaElement).value = 'hi';
        cm.sendMessage();
        expect(cm.wsClient.send).not.toHaveBeenCalled();
    });

    it('is a no-op when input is empty', () => {
        const cm = mountDomAndChat();
        cm.currentConversation = {
            id: 'c1', title: 't', role_preset: 'general', thinking_enabled: false,
            is_starred: false, created_at: '2026-04-01',
        };
        (document.getElementById('chat-input') as HTMLTextAreaElement).value = '';
        cm.sendMessage();
        expect(cm.wsClient.send).not.toHaveBeenCalled();
    });

    it('emits a message frame with the input content + clears the textarea', () => {
        const cm = mountDomAndChat();
        cm.currentConversation = {
            id: 'c1', title: 't', role_preset: 'general', thinking_enabled: false,
            is_starred: false, created_at: '2026-04-01',
        };
        const input = document.getElementById('chat-input') as HTMLTextAreaElement;
        input.value = 'hello there';
        // Model a SUCCESSFUL send — sendMessage now restores the typed text
        // when send() reports failure, so the default undefined-returning
        // mock would (correctly) leave the input populated.
        (cm.wsClient.send as ReturnType<typeof vi.fn>).mockReturnValue(true);
        cm.sendMessage();
        expect(cm.wsClient.send).toHaveBeenCalledWith(expect.objectContaining({
            type: 'message',
            content: 'hello there',
            conversation_id: 'c1',
        }));
        expect(input.value).toBe('');
    });
});

describe('loadConversation', () => {
    it('persists settings.lastConversationId so it re-opens next launch', async () => {
        const { settings, saveSettings } = await import('./shared.js');
        const cm = mountDomAndChat();
        cm.handleMessage({  // pretend we're connected so loadConversation uses WS path
            type: 'connected',
            presets: {},
        });
        // Force connected state bypassing the real socket.
        Object.defineProperty(cm.wsClient, 'connected', { value: true, configurable: true });
        cm.loadConversation('abc');
        expect(settings.lastConversationId).toBe('abc');
        saveSettings();  // ensure it doesn't throw downstream
    });
});

// ============================================================================
// History-scoped error frames — must NOT cross-fire into chat streaming state
// ============================================================================

// Minimal mirror of the #page-history DOM (same ids history-manager.test.ts
// uses) so a REAL HistoryManager can run its edit flow alongside ChatManager.
const HISTORY_PANE_DOM = `
    <section id="page-history">
        <button id="ai-history-refresh"></button>
        <div id="ai-channel-list"></div>
        <div id="ai-history-header"></div>
        <div id="ai-history-messages"></div>
        <div id="ai-history-load-all-container" class="hidden">
            <button id="ai-history-load-all">Load all</button>
        </div>
    </section>
`;

/**
 * Mounts ChatManager + a real HistoryManager wired as in app.ts, loads one
 * history message and puts an edit ack in flight (Save disabled), so tests
 * can observe whether an incoming error frame unsticks the editor and/or
 * tears down chat streaming state.
 */
async function mountChatWithInFlightHistoryEdit(): Promise<{
    cm: import('./chat-manager.js').ChatManager;
    saveBtn: HTMLButtonElement;
}> {
    const { HistoryManager } = await import('./history-manager.js');
    const cm = mountDomAndChat();
    document.body.insertAdjacentHTML('beforeend', HISTORY_PANE_DOM);
    const hm = new HistoryManager({ send: vi.fn(() => true), isConnected: () => true });
    hm.init();
    cm.historyManager = hm;
    hm.openChannel('111111111111111111');
    hm.handleMessage({
        type: 'ai_history_loaded',
        channel_id: '111111111111111111',
        messages: [{
            id: 7, local_id: 1, role: 'model', content: 'old text',
            message_id: null, timestamp: null, user_id: null,
        }],
        total_count: 1,
        has_more: false,
    });
    (document.querySelector('.history-edit-btn') as HTMLElement).click();
    (document.querySelector('.edit-textarea') as HTMLTextAreaElement).value = 'new text';
    const saveBtn = document.querySelector('.edit-save-btn') as HTMLButtonElement;
    saveBtn.click();
    expect(saveBtn.disabled).toBe(true); // ack in flight
    return { cm, saveBtn };
}

const STREAM_CONV = {
    id: 'c1', title: 't', role_preset: 'general', thinking_enabled: false,
    is_starred: false, created_at: '2026-04-01',
};

describe('handleMessage — history-scoped error frames', () => {
    it('scope:ai_history leaves an in-flight chat stream untouched and unsticks the history editor', async () => {
        const { cm, saveBtn } = await mountChatWithInFlightHistoryEdit();
        cm.currentConversation = { ...STREAM_CONV };
        cm.handleMessage({ type: 'stream_start' });
        expect(cm.isStreaming).toBe(true);
        expect(document.getElementById('streaming-message')).not.toBeNull();

        cm.handleMessage({
            type: 'error', scope: 'ai_history',
            code: 'MSG_NOT_FOUND', message: 'Message not found',
        });

        // Chat streaming state is fully preserved…
        expect(cm.isStreaming).toBe(true);
        expect(cm.streamingConversationId).toBe('c1');
        expect(document.getElementById('streaming-message')).not.toBeNull();
        // …while the history editor is re-enabled for a retry.
        expect(saveBtn.disabled).toBe(false);
        expect((document.querySelector('.edit-textarea') as HTMLTextAreaElement).value).toBe('new text');
    });

    it.each([
        'edit_ai_history_message',
        'restore_ai_history_message',
    ])('rate-limit scope %s (wire msg type echoed by the backend) also skips the teardown', async (scope) => {
        const { cm, saveBtn } = await mountChatWithInFlightHistoryEdit();
        cm.currentConversation = { ...STREAM_CONV };
        cm.handleMessage({ type: 'stream_start' });
        cm.handleMessage({
            type: 'error', scope,
            message: 'Rate limit exceeded. Please wait.',
        });
        expect(cm.isStreaming).toBe(true);
        expect(document.getElementById('streaming-message')).not.toBeNull();
        expect(saveBtn.disabled).toBe(false);
    });

    it('an UNscoped error still runs the full chat-stream teardown', async () => {
        const { cm, saveBtn } = await mountChatWithInFlightHistoryEdit();
        cm.currentConversation = { ...STREAM_CONV };
        cm.handleMessage({ type: 'stream_start' });
        expect(cm.isStreaming).toBe(true);

        cm.handleMessage({ type: 'error', message: 'boom' });

        expect(cm.isStreaming).toBe(false);
        expect(cm.streamingConversationId).toBeNull();
        expect(document.getElementById('streaming-message')).toBeNull();
        // Trailing resilience kept on the unscoped path: the editor is
        // unstuck there too (harmless for chat, vital pre-`scope` clients).
        expect(saveBtn.disabled).toBe(false);
    });
});

// ============================================================================
// Error-code forwarding — HistoryManager.onError must receive the envelope's
// `code` so permanent rejections (ROW_CONFLICT…) can drop their undo entry
// while transient/codeless ones keep it for a retry
// ============================================================================

describe('handleMessage — error-code forwarding to HistoryManager.onError', () => {
    function mountWithOnErrorSpy(): {
        cm: import('./chat-manager.js').ChatManager;
        onError: ReturnType<typeof vi.fn>;
    } {
        const cm = mountDomAndChat();
        const onError = vi.fn();
        cm.historyManager = { onError, handleMessage: vi.fn() } as unknown as
            import('./history-manager.js').HistoryManager;
        return { cm, onError };
    }

    it('forwards the code on a history-SCOPED error frame', () => {
        const { cm, onError } = mountWithOnErrorSpy();
        cm.handleMessage({
            type: 'error', scope: 'ai_history',
            code: 'ROW_CONFLICT',
            message: 'History was rewritten since this undo was recorded',
        });
        expect(onError).toHaveBeenCalledTimes(1);
        expect(onError).toHaveBeenCalledWith('ROW_CONFLICT');
    });

    it('forwards undefined when the scoped frame carries no code (rate-limit envelope)', () => {
        const { cm, onError } = mountWithOnErrorSpy();
        cm.handleMessage({
            type: 'error', scope: 'restore_ai_history_message',
            message: 'Rate limit exceeded. Please wait.',
        });
        expect(onError).toHaveBeenCalledTimes(1);
        expect(onError).toHaveBeenCalledWith(undefined);
    });

    it('forwards the code on the UNSCOPED error path too (trailing resilience call)', () => {
        const { cm, onError } = mountWithOnErrorSpy();
        cm.handleMessage({
            type: 'error',
            code: 'MSG_NOT_FOUND',
            message: 'Message not found',
        });
        expect(onError).toHaveBeenCalledTimes(1);
        expect(onError).toHaveBeenCalledWith('MSG_NOT_FOUND');
    });
});

// ============================================================================
// ai_* frame forwarding — ChatManager owns the socket and hands the History
// page's frames to the HistoryManager delegate verbatim
// ============================================================================

describe('handleMessage — ai_* frame forwarding', () => {
    it.each([
        'ai_channels_list',
        'ai_history_loaded',
        'ai_history_message_edited',
        'ai_history_message_deleted',
        'ai_history_message_restored',
    ])('forwards %s to historyManager.handleMessage', (type) => {
        const cm = mountDomAndChat();
        const handleMessage = vi.fn();
        cm.historyManager = { handleMessage } as unknown as
            import('./history-manager.js').HistoryManager;
        const frame = { type, channel_id: '111111111111111111', id: 7 };
        cm.handleMessage(frame);
        expect(handleMessage).toHaveBeenCalledTimes(1);
        expect(handleMessage).toHaveBeenCalledWith(frame);
    });
});

// ============================================================================
// Regression: renderMessages() must NOT yank a scrolled-up reader to bottom.
//
// The bug: renderMessages() called this.scrollToBottom() UNCONDITIONALLY after
// replacing innerHTML. scrollToBottom only bailed when this.userScrolledUp was
// true, but userScrolledUp is *only ever set while streaming*, so an ordinary
// re-render (a pin/like/ack/tag mutation) while a user read older history
// snapped them back to the bottom. The fix captures `wasNearBottom` from the
// container geometry BEFORE the innerHTML swap and only auto-scrolls when the
// user was already near the bottom (or a stream is feeding chunks):
//     const wasNearBottom = this.isStreaming || distanceFromBottom <= 150;
//     ...
//     if (wasNearBottom) this.scrollToBottom();
// These tests pin that behaviour: scrolled-up => no scroll, near-bottom => scroll.
// ============================================================================

describe('renderMessages — scroll preservation for a scrolled-up reader', () => {
    // jsdom returns 0 for all scroll geometry. Override the three props
    // renderMessages() reads so `distanceFromBottom` is deterministic:
    //   distanceFromBottom = scrollHeight - scrollTop - clientHeight
    function setContainerGeometry(
        el: HTMLElement,
        opts: { scrollHeight: number; scrollTop: number; clientHeight: number },
    ): void {
        Object.defineProperty(el, 'scrollHeight', { value: opts.scrollHeight, configurable: true });
        Object.defineProperty(el, 'clientHeight', { value: opts.clientHeight, configurable: true });
        // scrollTop is writable in jsdom, but pin it via a getter so the
        // innerHTML swap inside renderMessages() can't quietly reset it to 0.
        Object.defineProperty(el, 'scrollTop', {
            value: opts.scrollTop, writable: true, configurable: true,
        });
    }

    function mountWithMessages(): import('./chat-manager.js').ChatManager {
        const cm = mountDomAndChat();
        // A small, deterministic conversation so renderMessages() has real
        // content to lay out (length > 0 means it reaches the scroll branch).
        cm.handleMessage({
            type: 'conversation_loaded',
            conversation: {
                id: 'c1', title: 't', role_preset: 'general',
                thinking_enabled: false, is_starred: false, created_at: '2026-04-01',
            },
            messages: [
                { id: 1, role: 'user', content: 'สวัสดี', created_at: '2026-04-01' },
                { id: 2, role: 'assistant', content: 'hello', created_at: '2026-04-01' },
                { id: 3, role: 'user', content: 'more', created_at: '2026-04-01' },
            ],
        });
        return cm;
    }

    it('does NOT force a scroll to bottom when the reader is scrolled up (not streaming)', () => {
        const cm = mountWithMessages();
        const container = document.getElementById('chat-messages')!;
        // Far from the bottom: distanceFromBottom = 5000 - 100 - 800 = 4100 (> 150).
        setContainerGeometry(container, { scrollHeight: 5000, scrollTop: 100, clientHeight: 800 });
        cm.isStreaming = false;

        const scrollSpy = vi.spyOn(cm, 'scrollToBottom');
        cm.renderMessages();

        // The fix's whole point: a re-render while reading history is a no-op
        // for scrolling. (Reverting the fix makes renderMessages() call
        // scrollToBottom() unconditionally here, failing this assertion.)
        expect(scrollSpy).not.toHaveBeenCalled();
        // And the viewport is left exactly where the reader put it.
        expect(container.scrollTop).toBe(100);
    });

    it('DOES scroll to bottom when the reader is already near the bottom', () => {
        const cm = mountWithMessages();
        const container = document.getElementById('chat-messages')!;
        // Near the bottom: distanceFromBottom = 5000 - 4150 - 800 = 50 (<= 150).
        setContainerGeometry(container, { scrollHeight: 5000, scrollTop: 4150, clientHeight: 800 });
        cm.isStreaming = false;

        const scrollSpy = vi.spyOn(cm, 'scrollToBottom');
        cm.renderMessages();

        // A reader pinned to the live tail should keep following new content.
        expect(scrollSpy).toHaveBeenCalled();
    });

    it('always scrolls while streaming, even if geometry reads as scrolled up', () => {
        const cm = mountWithMessages();
        const container = document.getElementById('chat-messages')!;
        setContainerGeometry(container, { scrollHeight: 5000, scrollTop: 0, clientHeight: 800 });
        cm.isStreaming = true;          // chunks are arriving
        // userScrolledUp is private; reach it through a typed cast for the test seam.
        (cm as unknown as { userScrolledUp: boolean }).userScrolledUp = false;  // user is following the stream

        const scrollSpy = vi.spyOn(cm, 'scrollToBottom');
        cm.renderMessages();

        // isStreaming short-circuits wasNearBottom=true, so chunks keep the
        // tail in view for a user who hasn't manually scrolled up.
        expect(scrollSpy).toHaveBeenCalled();
    });

    it('scrollToBottom() is a no-op when userScrolledUp is true (and force overrides it)', () => {
        const cm = mountWithMessages();
        const container = document.getElementById('chat-messages')!;
        setContainerGeometry(container, { scrollHeight: 5000, scrollTop: 100, clientHeight: 800 });

        // The guard that protects a user who scrolled up DURING a stream.
        // userScrolledUp is private; reach it through a typed cast for the test seam.
        (cm as unknown as { userScrolledUp: boolean }).userScrolledUp = true;
        cm.scrollToBottom();
        expect(container.scrollTop).toBe(100);        // untouched
        expect(cm.newMessagesWhileScrolledUp).toBe(1); // badge counter ticked instead

        // force=true bypasses the guard (used by explicit "jump to bottom").
        cm.scrollToBottom(true);
        expect(container.scrollTop).toBe(5000);        // == scrollHeight
    });
});
