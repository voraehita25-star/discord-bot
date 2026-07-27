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

import { describe, it, expect, beforeEach, afterEach, beforeAll, vi } from 'vitest';

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
    <label class="checkbox-label" id="chat-use-search-label"><input type="checkbox" id="chat-use-search"></label>
    <label class="checkbox-label" id="chat-write-mode-label"><input type="checkbox" id="chat-write-mode"></label>

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

    it('drops a late load frame for a DIFFERENT conversation created just after', () => {
        // Race: user clicks conversation A (loadConversation → pendingLoad='A'),
        // then creates B. conversation_created must re-point the stale-load guard
        // at B so the slow conversation_loaded for A is dropped instead of
        // overwriting the freshly created B.
        const cm = mountDomAndChat();
        (cm as unknown as { pendingConversationLoadId: string | null }).pendingConversationLoadId = 'A';
        cm.handleMessage({ type: 'conversation_created', id: 'B', role_preset: 'general', title: 'B' });
        expect(cm.currentConversation?.id).toBe('B');
        // The guard now names B, so a late load frame for A is ignored.
        cm.handleMessage({
            type: 'conversation_loaded',
            conversation: { id: 'A', title: 'A', role_preset: 'general', thinking_enabled: false, is_starred: false, created_at: '2026-04-01' },
            messages: [{ id: 1, role: 'user', content: 'stale A', created_at: '2026-04-01' }],
        });
        expect(cm.currentConversation?.id, 'late A load must not replace created B').toBe('B');
        expect(cm.messages.length, 'B stays empty; stale A messages dropped').toBe(0);
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

    it('message_pinned updates ONLY the pin button in place (no full window re-render)', () => {
        const cm = mountDomAndChat();
        // Render a real conversation so the pin button exists in the DOM.
        cm.handleMessage({
            type: 'conversation_loaded',
            conversation: { id: 'c', title: 'c', role_preset: 'general', thinking_enabled: false, is_starred: false, created_at: 't' },
            messages: [
                { id: 1, role: 'user', content: 'hi', created_at: 't' },
                { id: 2, role: 'assistant', content: 'hello', created_at: 't', is_pinned: false },
            ],
        });
        const container = document.getElementById('chat-messages')!;
        // Sentinel on an existing node: a full innerHTML rebuild would destroy it,
        // an in-place button update leaves it intact.
        (container.querySelector('.chat-message') as unknown as { __sentinel?: number }).__sentinel = 42;

        cm.handleMessage({ type: 'message_pinned', message_id: 2, pinned: true });

        const btn = container.querySelector('.pin-message-btn[data-msg-id="2"]') as HTMLButtonElement;
        expect(btn.classList.contains('pinned')).toBe(true);
        expect(btn.dataset.pinned).toBe('1');
        expect(btn.getAttribute('aria-label')).toBe('Unpin message');
        expect(btn.textContent).toContain('Unpin');
        // The window was NOT rebuilt — the sentinel survives.
        expect((container.querySelector('.chat-message') as unknown as { __sentinel?: number }).__sentinel).toBe(42);
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

    it('message_deleted with cli_session_diverged surfaces a reload-warning toast', () => {
        // Regression: dashboard_handlers.py emits cli_session_diverged so the UI
        // can warn the user that the next CLI turn may replay deleted content.
        // The consumer previously never read the field, so the warning was silent.
        const cm = mountDomAndChat();
        cm.messages = [
            { id: 1, role: 'user', content: 'hi', created_at: 't' },
            { id: 2, role: 'assistant', content: 'hello', created_at: 't' },
        ];
        cm.handleMessage({
            type: 'message_deleted',
            message_id: 1,
            pair_message_id: 2,
            cli_session_diverged: true,
        });
        // Behavior preserved: messages still removed.
        expect(cm.messages.length).toBe(0);
        // AND the documented divergence warning is now surfaced (was silent before).
        const warn = document.querySelector('#toast-container .toast-warning');
        expect(warn).not.toBeNull();
        expect(warn?.textContent ?? '').toMatch(/reload/i);
    });

    it('message_deleted without cli_session_diverged shows no warning toast', () => {
        const cm = mountDomAndChat();
        cm.messages = [{ id: 1, role: 'user', content: 'hi', created_at: 't' }];
        cm.handleMessage({ type: 'message_deleted', message_id: 1, pair_message_id: null });
        expect(document.querySelector('#toast-container .toast-warning')).toBeNull();
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

describe('createConversation — provider allowlist gate', () => {
    it('accepts an in-allowlist modal provider and persists it', () => {
        const cm = mountDomAndChat();
        cm.availableProviders = ['gemini', 'claude'];
        cm.aiProvider = 'gemini';
        (document.getElementById('modal-ai-provider') as HTMLSelectElement).value = 'claude';
        cm.createConversation();
        expect(cm.aiProvider).toBe('claude');
        expect(localStorage.getItem('dashboard_ai_provider')).toBe('claude');
        expect(cm.wsClient.send).toHaveBeenCalledWith(
            expect.objectContaining({ type: 'new_conversation', ai_provider: 'claude' }),
        );
    });

    it('rejects an out-of-allowlist provider injected into the <select> (keeps current)', () => {
        const cm = mountDomAndChat();
        cm.availableProviders = ['gemini', 'claude'];
        cm.aiProvider = 'gemini';
        localStorage.setItem('dashboard_ai_provider', 'gemini');
        // Simulate a stale/tampered/injected option the server never sent.
        const select = document.getElementById('modal-ai-provider') as HTMLSelectElement;
        const rogue = document.createElement('option');
        rogue.value = 'evil';
        select.appendChild(rogue);
        select.value = 'evil';
        cm.createConversation();
        // The garbage value must NOT propagate to state, localStorage, or the wire.
        expect(cm.aiProvider).toBe('gemini');
        expect(localStorage.getItem('dashboard_ai_provider')).toBe('gemini');
        expect(cm.wsClient.send).toHaveBeenCalledWith(
            expect.objectContaining({ type: 'new_conversation', ai_provider: 'gemini' }),
        );
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
        // The unscoped path no longer touches the history editor: every
        // genuine history rejection is scoped (handlers tag scope:'ai_history',
        // the rate limiter echoes the wire type), so the in-flight edit stays
        // pending until ITS OWN scoped rejection/ack arrives — an unrelated
        // chat error must not drop its undo candidate.
        expect(saveBtn.disabled).toBe(true);
    });

    it.each([
        'rename_conversation',
        'delete_conversation',
        'star_conversation',
        'list_conversations',
        'save_profile',
    ])('management scope %s surfaces as toast-only — no chat-stream teardown', async (scope) => {
        const { cm, saveBtn } = await mountChatWithInFlightHistoryEdit();
        cm.currentConversation = { ...STREAM_CONV };
        cm.handleMessage({ type: 'stream_start' });
        expect(cm.isStreaming).toBe(true);

        cm.handleMessage({
            type: 'error', scope,
            code: 'INTERNAL_ERROR', message: 'Failed',
        });

        // Chat streaming state is fully preserved…
        expect(cm.isStreaming).toBe(true);
        expect(cm.streamingConversationId).toBe('c1');
        expect(document.getElementById('streaming-message')).not.toBeNull();
        // …and the history editor is left alone too (its undo candidate must
        // survive an unrelated management failure).
        expect(saveBtn.disabled).toBe(true);
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

    it('does NOT forward unscoped errors (chat errors carry codes too and would drop undo candidates)', () => {
        const { cm, onError } = mountWithOnErrorSpy();
        // NO_BACKEND_AVAILABLE / INVALID_PROVIDER are unscoped CHAT errors
        // that carry a code; forwarding them made HistoryManager.onError
        // treat them as history rejections and null pendingUndoCandidate.
        cm.handleMessage({
            type: 'error',
            code: 'NO_BACKEND_AVAILABLE',
            message: 'No backend available',
        });
        expect(onError).not.toHaveBeenCalled();
    });

    it('does not forward management-scoped errors either', () => {
        const { cm, onError } = mountWithOnErrorSpy();
        cm.handleMessage({
            type: 'error',
            scope: 'rename_conversation',
            code: 'INVALID_ID',
            message: 'Invalid conversation ID format',
        });
        expect(onError).not.toHaveBeenCalled();
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

// ============================================================================
// updateScrollFab — a11y label + live region (INT-05)
// ============================================================================

describe('updateScrollFab — a11y (INT-05)', () => {
    it('keeps the base aria-label + hidden badge when no new messages', () => {
        const cm = mountDomAndChat();
        cm.newMessagesWhileScrolledUp = 0;
        cm.updateScrollFab(true);
        const fab = document.getElementById('scroll-to-bottom-fab')!;
        const badge = document.getElementById('scroll-new-count')!;
        expect(fab.getAttribute('aria-label')).toBe('Scroll to bottom');
        expect(badge.classList.contains('hidden')).toBe(true);
        // The badge is a polite live region so AT announces count changes.
        expect(badge.getAttribute('aria-live')).toBe('polite');
    });

    it('sets a count-aware aria-label + reveals the live badge when n>0', () => {
        const cm = mountDomAndChat();
        cm.newMessagesWhileScrolledUp = 3;
        cm.updateScrollFab(true);
        const fab = document.getElementById('scroll-to-bottom-fab')!;
        const badge = document.getElementById('scroll-new-count')!;
        expect(fab.getAttribute('aria-label')).toBe('Scroll to latest, 3 new messages');
        expect(badge.textContent).toBe('3');
        expect(badge.classList.contains('hidden')).toBe(false);
        expect(badge.getAttribute('aria-live')).toBe('polite');
    });

    it('uses the singular form for exactly one new message', () => {
        const cm = mountDomAndChat();
        cm.newMessagesWhileScrolledUp = 1;
        cm.updateScrollFab(true);
        const fab = document.getElementById('scroll-to-bottom-fab')!;
        expect(fab.getAttribute('aria-label')).toBe('Scroll to latest, 1 new message');
    });
});

// ============================================================================
// failed-send — keep bubble + inline Retry (INT-04)
// ============================================================================

describe('sendMessage — failed send keeps the bubble (INT-04)', () => {
    function withConversation(): import('./chat-manager.js').ChatManager {
        const cm = mountDomAndChat();
        cm.currentConversation = {
            id: 'c1', title: 't', role_preset: 'general', thinking_enabled: false,
            is_starred: false, created_at: '2026-04-01',
        };
        return cm;
    }

    it('keeps the user message, marks it failed, and restores the draft text', () => {
        const cm = withConversation();
        (cm.wsClient.send as ReturnType<typeof vi.fn>).mockReturnValue(false); // send fails
        const input = document.getElementById('chat-input') as HTMLTextAreaElement;
        input.value = 'will fail';
        cm.sendMessage();
        // Bubble is NOT popped — it stays in the list flagged failed.
        expect(cm.messages.length).toBe(1);
        expect(cm.messages[0].role).toBe('user');
        expect(cm.messages[0].failed).toBe(true);
        // Streaming gate released so the user isn't locked out.
        expect(cm.isStreaming).toBe(false);
        // Draft text restored into the composer.
        expect(input.value).toBe('will fail');
    });

    it('drops an abandoned failed message from the next send history (no phantom turn)', () => {
        const cm = withConversation();
        const sendMock = cm.wsClient.send as ReturnType<typeof vi.fn>;
        sendMock.mockReturnValue(false);  // first send fails -> bubble kept, flagged failed
        (document.getElementById('chat-input') as HTMLTextAreaElement).value = 'phantom';
        cm.sendMessage();
        expect(cm.messages[0].failed).toBe(true);

        // User abandons the failed bubble (no retry) and sends a different message.
        sendMock.mockReturnValue(true);
        (document.getElementById('chat-input') as HTMLTextAreaElement).value = 'real message';
        cm.sendMessage();

        // The successful send's history payload must NOT replay the never-delivered
        // failed turn (historyToSend filters out failed messages).
        const lastCall = sendMock.mock.calls.at(-1)?.[0] as { history?: { content: string }[] };
        const contents = (lastCall.history ?? []).map((h) => h.content);
        expect(contents, 'abandoned failed turn must not appear in outgoing history').not.toContain('phantom');
    });

    it('renders the .send-failed rail + role=alert + a Retry button', () => {
        const cm = withConversation();
        (cm.wsClient.send as ReturnType<typeof vi.fn>).mockReturnValue(false);
        (document.getElementById('chat-input') as HTMLTextAreaElement).value = 'oops';
        cm.sendMessage();
        const failed = document.querySelector('.chat-message.send-failed');
        expect(failed).not.toBeNull();
        expect(failed!.getAttribute('role')).toBe('alert');
        expect(failed!.querySelector('.retry-send')).not.toBeNull();
    });

    it('Retry re-runs the send path and clears the failed flag on success', () => {
        const cm = withConversation();
        const sendMock = cm.wsClient.send as ReturnType<typeof vi.fn>;
        sendMock.mockReturnValue(false);  // first send fails
        (document.getElementById('chat-input') as HTMLTextAreaElement).value = 'retry me';
        cm.sendMessage();
        expect(cm.messages[0].failed).toBe(true);

        sendMock.mockReturnValue(true);   // reconnected — retry succeeds
        const retryBtn = document.querySelector('.retry-send') as HTMLButtonElement;
        retryBtn.click();
        // A single non-failed user message remains (the retried send re-pushed it).
        expect(cm.messages.length).toBe(1);
        expect(cm.messages[0].role).toBe('user');
        expect(cm.messages[0].content).toBe('retry me');
        expect(cm.messages[0].failed).toBeFalsy();
    });

    it('Retry re-marks the bubble failed when the resend also fails', () => {
        const cm = withConversation();
        (cm.wsClient.send as ReturnType<typeof vi.fn>).mockReturnValue(false);
        (document.getElementById('chat-input') as HTMLTextAreaElement).value = 'still down';
        cm.sendMessage();
        const retryBtn = document.querySelector('.retry-send') as HTMLButtonElement;
        retryBtn.click();
        expect(cm.messages.length).toBe(1);
        expect(cm.messages[0].failed).toBe(true);
    });
});

describe('chat toggles — dead controls are disabled, not left lying', () => {
    // Each toggle only controls something under certain backend + config
    // combinations. A live checkbox that silently does nothing is what made the
    // Thinking and Search buttons feel broken; the handshake now says which are
    // real and the UI greys out the rest.
    const $ = (id: string) => document.getElementById(id) as HTMLInputElement;

    it('disables and unchecks the thinking toggle when unsupported', () => {
        const cm = mountDomAndChat();
        $('thinking-toggle').checked = true;
        cm.thinkingEnabled = true;

        cm.applyToggleSupportFromHandshake({
            thinking_toggle: { supported: false, reason: 'CLI always reasons' },
        });

        expect($('thinking-toggle').disabled).toBe(true);
        expect($('thinking-toggle').checked).toBe(false);
        expect(cm.thinkingEnabled).toBe(false);
    });

    it('disables Search and Write independently, each with its own reason', () => {
        const cm = mountDomAndChat();
        cm.applyToggleSupportFromHandshake({
            web_search_toggle: { supported: false, reason: 'web tools off' },
            write_mode_toggle: { supported: true, reason: '', roots: ['C:\Users\ME\Desktop'] },
        });

        expect($('chat-use-search').disabled).toBe(true);
        expect(document.getElementById('chat-use-search-label')!.getAttribute('title'))
            .toBe('web tools off');
        expect($('chat-write-mode').disabled).toBe(false);
    });

    it('names the write roots in the tooltip so the blast radius is visible', () => {
        const cm = mountDomAndChat();
        cm.applyToggleSupportFromHandshake({
            write_mode_toggle: { supported: true, roots: ['C:\Users\ME\Desktop'] },
        });
        expect(document.getElementById('chat-write-mode-label')!.getAttribute('title'))
            .toContain('C:\Users\ME\Desktop');
    });

    it('treats missing fields as supported so an older server still works', () => {
        const cm = mountDomAndChat();
        $('thinking-toggle').disabled = true;
        $('chat-use-search').disabled = true;
        $('chat-write-mode').disabled = true;

        cm.applyToggleSupportFromHandshake({});

        expect($('thinking-toggle').disabled).toBe(false);
        expect($('chat-use-search').disabled).toBe(false);
        expect($('chat-write-mode').disabled).toBe(false);
    });

    it('applies the handshake through handleMessage', () => {
        const cm = mountDomAndChat();
        cm.handleMessage({
            type: 'connected',
            presets: {},
            thinking_toggle: { supported: false, reason: 'nope' },
            write_mode_toggle: { supported: false, reason: 'writes disabled' },
        });
        expect($('thinking-toggle').disabled).toBe(true);
        expect($('chat-write-mode').disabled).toBe(true);
    });
});

describe('resolveSearchWriteConflict — Search wins, and the user is told', () => {
    // The Claude CLI denies WebSearch/WebFetch in write mode, so a turn cannot
    // have both. Dropping write silently would leave the checkbox claiming a
    // capability the turn didn't have.
    const $ = (id: string) => document.getElementById(id) as HTMLInputElement;

    it('drops write mode and unticks the box when both are on', () => {
        const cm = mountDomAndChat();
        $('chat-write-mode').checked = true;

        expect(cm.resolveSearchWriteConflict(true, true)).toBe(false);
        expect($('chat-write-mode').checked).toBe(false);
    });

    it('leaves write mode alone when search is off', () => {
        const cm = mountDomAndChat();
        $('chat-write-mode').checked = true;

        expect(cm.resolveSearchWriteConflict(false, true)).toBe(true);
        expect($('chat-write-mode').checked).toBe(true);
    });

    it('is a no-op when write mode was never requested', () => {
        const cm = mountDomAndChat();
        expect(cm.resolveSearchWriteConflict(true, false)).toBe(false);
        expect(cm.resolveSearchWriteConflict(false, false)).toBe(false);
    });

    it('sends the resolved flags, not the raw checkbox states', () => {
        const cm = mountDomAndChat();
        cm.currentConversation = {
            id: 'c1', title: 't', role_preset: 'general', thinking_enabled: false,
            is_starred: false, created_at: '2026-04-01',
        };
        $('chat-use-search').checked = true;
        $('chat-write-mode').checked = true;
        (document.getElementById('chat-input') as HTMLTextAreaElement).value = 'hi';

        cm.sendMessage();

        const sent = (cm.wsClient.send as ReturnType<typeof vi.fn>).mock.calls
            .map(c => c[0] as Record<string, unknown>)
            .find(p => p.type === 'message');
        expect(sent!.use_search).toBe(true);
        expect(sent!.write_enabled).toBe(false);
    });
});

describe('streaming renders markdown live, not raw source', () => {
    // Chunks used to be appended as plain text nodes, so the live answer showed
    // markdown SOURCE — a literal `>` for a quote, `**` around bold, `- ` on
    // list items — and only became real markup when stream_end swapped in the
    // formatted HTML. The bubble now re-renders the accumulated buffer each
    // frame, so what you read while it types matches what you get when it ends.
    const streamText = () => document.querySelector('#streaming-message .streaming-text');
    const nextFrame = () => new Promise<void>(resolve => requestAnimationFrame(() => resolve()));

    function startStream(): import('./chat-manager.js').ChatManager {
        const cm = mountDomAndChat();
        cm.currentConversation = {
            id: 'c1', title: 't', role_preset: 'general', thinking_enabled: false,
            is_starred: false, created_at: '2026-04-01',
        };
        cm.handleMessage({ type: 'stream_start', mode: '', conversation_id: 'c1' });
        return cm;
    }

    it('renders a blockquote instead of a literal > while typing', async () => {
        const cm = startStream();
        cm.handleMessage({ type: 'chunk', content: '> quoted line' });
        await nextFrame();

        expect(streamText()!.querySelector('blockquote')).not.toBeNull();
        expect(streamText()!.textContent).not.toContain('>');
    });

    it('renders list items as a real list mid-stream', async () => {
        const cm = startStream();
        cm.handleMessage({ type: 'chunk', content: '- first\n- second' });
        await nextFrame();

        expect(streamText()!.querySelectorAll('li').length).toBe(2);
    });

    it('renders a half-written code fence as a code block', async () => {
        // The formatter's unclosed-fence guard is what makes partial input safe:
        // without it the user stares at three literal backticks until the
        // closing fence arrives.
        const cm = startStream();
        cm.handleMessage({ type: 'chunk', content: '```py\nprint(1)' });
        await nextFrame();

        expect(streamText()!.querySelector('pre, code')).not.toBeNull();
        expect(streamText()!.textContent).not.toContain('```');
    });

    it('coalesces many chunks into one render per frame', async () => {
        const cm = startStream();
        for (const part of ['**bo', 'ld** and ', 'more']) {
            cm.handleMessage({ type: 'chunk', content: part });
        }
        await nextFrame();

        // All three chunks are present, and the completed marker rendered.
        expect(streamText()!.querySelector('strong')?.textContent).toBe('bold');
        expect(streamText()!.textContent).toContain('and more');
    });

    it('the finished message replaces the partial, not appends to it', async () => {
        const cm = startStream();
        cm.handleMessage({ type: 'chunk', content: '> partial' });
        await nextFrame();
        cm.handleMessage({ type: 'stream_end', full_response: '> partial and done' });

        expect(document.getElementById('streaming-message')).toBeNull();
        const last = document.querySelectorAll('#chat-messages .message-content');
        const text = last[last.length - 1]?.textContent || '';
        expect(text).toContain('partial and done');
        // A queued frame firing after stream_end must not repaint the shorter
        // buffered partial over the finished answer.
        await nextFrame();
        expect(document.getElementById('streaming-message')).toBeNull();
    });

    it('hides a still-OPEN <think> block instead of painting it as the answer', async () => {
        // stripThinkTags matches CLOSED blocks only, so a backend that inlines
        // reasoning into the `chunk` channel had its raw chain-of-thought
        // rendered as the answer for as long as the reasoning ran, then wiped
        // at stream_end. The streaming variant also drops the open tail.
        const cm = startStream();
        cm.handleMessage({ type: 'chunk', content: 'Answer. <think>secret reasoning' });
        await nextFrame();

        expect(streamText()!.textContent).toContain('Answer.');
        expect(streamText()!.textContent).not.toContain('secret reasoning');
        expect(streamText()!.textContent).not.toContain('<think>');
    });
});

// ============================================================================
// Regression: the transcript renderer's audit fixes.
//
// Five separate defects, all rooted in the same `container.innerHTML = …`
// rebuild: pin/like CLICKS re-rendered the whole window, every re-render
// re-triggered the entrance animation on every bubble and slammed every
// expanded "Thought Process" shut, the disclosure was mouse-only, and
// stream_end released the scroll lock BEFORE the final scroll decision.
// ============================================================================

function mountLoaded(
    messages: Array<Record<string, unknown>>,
): import('./chat-manager.js').ChatManager {
    const cm = mountDomAndChat();
    cm.wsClient.connected = true;
    cm.wsClient.send = vi.fn().mockReturnValue(true);
    cm.handleMessage({
        type: 'conversation_loaded',
        conversation: {
            id: 'c1', title: 't', role_preset: 'general',
            thinking_enabled: false, is_starred: false, created_at: '2026-04-01',
        },
        messages,
    });
    return cm;
}

describe('pin/like clicks update the button in place', () => {
    const PAIR = [
        { id: 1, role: 'user', content: 'hi', created_at: '2026-04-01' },
        { id: 2, role: 'assistant', content: 'hello', created_at: '2026-04-01', is_pinned: false, liked: false },
    ];

    it('a pin click does NOT rebuild the window — the clicked button survives', () => {
        const cm = mountLoaded(PAIR);
        const container = document.getElementById('chat-messages')!;
        const btn = container.querySelector('.pin-message-btn[data-msg-id="2"]') as HTMLButtonElement;
        // Sentinel on the clicked node: a full innerHTML rebuild replaces it
        // (which is also what dropped keyboard focus to <body>).
        (btn as unknown as { __sentinel?: number }).__sentinel = 7;

        btn.click();

        const after = container.querySelector('.pin-message-btn[data-msg-id="2"]') as HTMLButtonElement;
        expect((after as unknown as { __sentinel?: number }).__sentinel).toBe(7);
        expect(after.classList.contains('pinned')).toBe(true);
        expect(after.dataset.pinned).toBe('1');
        expect(after.getAttribute('aria-label')).toBe('Unpin message');
        expect(after.textContent).toContain('Unpin');
        expect(cm.messages[1].is_pinned).toBe(true);
    });

    it('a like click updates the heart in place', () => {
        const cm = mountLoaded(PAIR);
        const container = document.getElementById('chat-messages')!;
        const btn = container.querySelector('.like-message-btn[data-msg-id="2"]') as HTMLButtonElement;
        (btn as unknown as { __sentinel?: number }).__sentinel = 9;

        btn.click();

        const after = container.querySelector('.like-message-btn[data-msg-id="2"]') as HTMLButtonElement;
        expect((after as unknown as { __sentinel?: number }).__sentinel).toBe(9);
        expect(after.classList.contains('liked')).toBe(true);
        expect(after.dataset.liked).toBe('1');
        expect(after.getAttribute('aria-label')).toBe('Unlike message');
        expect(cm.messages[1].liked).toBe(true);
    });
});

describe('"Thought Process" disclosure — keyboard operable, survives re-render', () => {
    const THINKER = [
        { id: 5, role: 'assistant', content: 'answer', thinking: 'because reasons', created_at: '2026-04-01' },
    ];
    const header = () => document.querySelector('.thinking-header') as HTMLElement;
    const content = () => document.querySelector('.thinking-content') as HTMLElement;

    it('Enter expands it — the header used to be a click-only <div>', () => {
        mountLoaded(THINKER);
        expect(header().classList.contains('collapsed')).toBe(true);

        header().dispatchEvent(new KeyboardEvent('keydown', {
            key: 'Enter', bubbles: true, cancelable: true,
        }));

        expect(header().classList.contains('collapsed')).toBe(false);
        expect(header().getAttribute('aria-expanded')).toBe('true');
        expect(content().classList.contains('collapsed')).toBe(false);
        // Collapsed content is only max-height:0, so it stays in the a11y tree
        // unless aria-hidden tracks the state.
        expect(content().getAttribute('aria-hidden')).toBe('false');
    });

    it('Space expands it too, and swallows the page scroll', () => {
        mountLoaded(THINKER);
        const evt = new KeyboardEvent('keydown', { key: ' ', bubbles: true, cancelable: true });
        header().dispatchEvent(evt);

        expect(header().classList.contains('collapsed')).toBe(false);
        expect(evt.defaultPrevented).toBe(true);
    });

    it('an expanded section stays open across a re-render', () => {
        const cm = mountLoaded(THINKER);
        header().click();
        expect(header().classList.contains('collapsed')).toBe(false);

        cm.renderMessages();  // e.g. a pin ack, an edit ack, the next send

        expect(header().classList.contains('collapsed')).toBe(false);
        expect(header().getAttribute('aria-expanded')).toBe('true');
        expect(content().classList.contains('collapsed')).toBe(false);
    });

    it('a collapsed section stays shut across a re-render', () => {
        const cm = mountLoaded(THINKER);
        header().click();   // open
        header().click();   // and close again
        cm.renderMessages();

        expect(header().classList.contains('collapsed')).toBe(true);
        expect(header().getAttribute('aria-expanded')).toBe('false');
    });

    it('forgets the expanded ids when the conversation changes', () => {
        const cm = mountLoaded(THINKER);
        header().click();
        expect((cm as unknown as { expandedThinking: Set<string> }).expandedThinking.size).toBe(1);

        cm.handleMessage({
            type: 'conversation_loaded',
            conversation: {
                id: 'c2', title: 'other', role_preset: 'general',
                thinking_enabled: false, is_starred: false, created_at: '2026-04-02',
            },
            messages: THINKER,
        });

        // Ids are per-conversation: a carried-over id would re-open an unrelated
        // section (and the set would grow without bound over a session).
        expect((cm as unknown as { expandedThinking: Set<string> }).expandedThinking.size).toBe(0);
        expect(header().classList.contains('collapsed')).toBe(true);
    });
});

describe('entrance animation is scoped to genuinely new bubbles', () => {
    it('tags only the tail bubble, and nothing at all on a plain re-render', () => {
        const cm = mountLoaded([
            { id: 1, role: 'user', content: 'hi', created_at: '2026-04-01' },
            { id: 2, role: 'assistant', content: 'hello', created_at: '2026-04-01' },
        ]);
        const container = document.getElementById('chat-messages')!;

        expect(container.querySelectorAll('.chat-message.is-new').length).toBe(1);
        expect((container.lastElementChild as HTMLElement).classList.contains('is-new')).toBe(true);

        // A pin/like/edit/avatar re-render adds no message — nothing animates.
        cm.renderMessages();
        expect(container.querySelectorAll('.chat-message.is-new').length).toBe(0);

        // A genuinely new message animates again, alone.
        cm.messages.push({ id: 3, role: 'user', content: 'more', created_at: '2026-04-01' });
        cm.renderMessages();
        expect(container.querySelectorAll('.chat-message.is-new').length).toBe(1);
    });
});

describe('stream_end releases the scroll lock only AFTER the final scroll', () => {
    it('does not yank a reader who scrolled up mid-stream back to the bottom', () => {
        const cm = mountDomAndChat();
        cm.currentConversation = {
            id: 'c1', title: 't', role_preset: 'general', thinking_enabled: false,
            is_starred: false, created_at: '2026-04-01',
        };
        cm.handleMessage({ type: 'stream_start', mode: '', conversation_id: 'c1' });
        cm.handleMessage({ type: 'chunk', content: 'partial' });
        // The scroll listener would set this when the user scrolls up to re-read.
        (cm as unknown as { userScrolledUp: boolean }).userScrolledUp = true;

        cm.handleMessage({ type: 'stream_end', full_response: 'partial and done' });

        // finalizeStreamingMessage's scrollToBottom() saw the lock still held, so
        // it bumped the "N new" badge instead of moving the viewport. Clearing
        // the flag first (the bug) skipped this branch entirely.
        expect(cm.newMessagesWhileScrolledUp).toBe(1);
        expect(document.getElementById('scroll-to-bottom-fab')!.classList.contains('hidden'))
            .toBe(false);
        // …and the lock is released for the NEXT stream.
        expect((cm as unknown as { userScrolledUp: boolean }).userScrolledUp).toBe(false);
    });
});

describe('Export All emits one summary toast, not one per conversation', () => {
    let anchorClick: ReturnType<typeof vi.spyOn>;
    const infoToasts = () =>
        Array.from(document.querySelectorAll('#toast-container .toast-info'))
            .map(t => t.textContent || '');

    beforeEach(() => {
        // jsdom implements none of these; downloadExport hands the blob to the
        // browser's download flow, which jsdom answers with a "navigation not
        // implemented" console error unless the click is stubbed out.
        URL.createObjectURL = vi.fn(() => 'blob:test');
        URL.revokeObjectURL = vi.fn();
        anchorClick = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    });

    afterEach(() => anchorClick.mockRestore());

    it('suppresses the per-item toast and reports the total once', () => {
        const cm = mountDomAndChat();
        const bulk = cm as unknown as { bulkExportRemaining: number; bulkExportTotal: number };
        bulk.bulkExportTotal = 2;
        bulk.bulkExportRemaining = 2;

        cm.downloadExport({ id: 'a', format: 'json', data: '{}' });
        expect(infoToasts()).toHaveLength(0);   // ~16 of these used to stack up

        cm.downloadExport({ id: 'b', format: 'json', data: '{}' });
        expect(infoToasts()).toHaveLength(1);
        expect(infoToasts()[0]).toContain('2 conversations');
        expect(bulk.bulkExportRemaining).toBe(0);
    });

    it('counts a content-less ack too, so the counter cannot leak', () => {
        const cm = mountDomAndChat();
        const bulk = cm as unknown as { bulkExportRemaining: number; bulkExportTotal: number };
        bulk.bulkExportTotal = 2;
        bulk.bulkExportRemaining = 2;

        // A failed export still consumed one slot of the run. Decrementing only
        // on success left the counter above zero forever, silently swallowing
        // every later single-export toast.
        cm.downloadExport({ id: 'a', format: 'json', data: '' });
        cm.downloadExport({ id: 'b', format: 'json', data: '{}' });

        expect(bulk.bulkExportRemaining).toBe(0);
        expect(infoToasts()).toHaveLength(1);
    });

    it('a single (non-bulk) export still toasts on its own', () => {
        const cm = mountDomAndChat();
        cm.downloadExport({ id: 'a', format: 'json', data: '{}' });
        expect(infoToasts()).toHaveLength(1);
        expect(infoToasts()[0]).toContain('Export sent to your downloads');
    });
});

// ============================================================================
// Copy buttons must survive their own "Copied" confirmation.
//
// The bug: the handler did `btn.textContent = 'Copied'` and restored via
// textContent 1500ms later. `<button><svg class="ic"><use/></svg> Copy</button>`
// has textContent ' Copy' (an <svg> contributes none), and assigning
// textContent replaces EVERY child with one text node — so the first click
// deleted the glyph and the "restore" put back a bare string. From then on the
// button was word-only, misaligned against the Edit/Delete buttons that still
// carried theirs, until the next full renderMessages().
// ============================================================================

describe('copy buttons keep their <svg> icon across repeated clicks', () => {
    let writeText: ReturnType<typeof vi.fn>;

    beforeEach(() => {
        // jsdom ships no navigator.clipboard at all.
        writeText = vi.fn().mockResolvedValue(undefined);
        Object.defineProperty(navigator, 'clipboard', {
            value: { writeText },
            configurable: true,
        });
        vi.useFakeTimers();
    });

    afterEach(() => {
        vi.useRealTimers();
    });

    const iconHref = (btn: Element | null): string | null =>
        btn?.querySelector('svg.ic use')?.getAttribute('href') ?? null;

    describe('renderMessages() path', () => {
        const copyBtn = () => document.querySelector('#chat-messages .copy-message-btn');

        it('swaps to a check GLYPH, then restores the copy glyph — never a bare word', async () => {
            const cm = mountDomAndChat();
            cm.messages = [{ id: 1, role: 'assistant', content: 'hello', created_at: 't' }];
            cm.renderMessages();

            expect(iconHref(copyBtn())).toBe('#i-copy');

            copyBtn()!.dispatchEvent(new MouseEvent('click', { bubbles: true }));
            await vi.advanceTimersByTimeAsync(0);

            expect(writeText).toHaveBeenCalledWith('hello');
            expect(iconHref(copyBtn())).toBe('#i-check');
            expect(copyBtn()!.textContent).toContain('Copied');

            await vi.advanceTimersByTimeAsync(1500);
            // Pre-fix this element had zero children and textContent ' Copy'.
            expect(copyBtn()!.querySelectorAll('svg.ic')).toHaveLength(1);
            expect(iconHref(copyBtn())).toBe('#i-copy');
            expect(copyBtn()!.textContent).toContain('Copy');
        });

        it('a SECOND click still finds an icon to swap (the glyph is not lost for good)', async () => {
            const cm = mountDomAndChat();
            cm.messages = [{ id: 1, role: 'assistant', content: 'hello', created_at: 't' }];
            cm.renderMessages();

            copyBtn()!.dispatchEvent(new MouseEvent('click', { bubbles: true }));
            await vi.advanceTimersByTimeAsync(1500);

            copyBtn()!.dispatchEvent(new MouseEvent('click', { bubbles: true }));
            await vi.advanceTimersByTimeAsync(0);
            expect(iconHref(copyBtn())).toBe('#i-check');

            await vi.advanceTimersByTimeAsync(1500);
            expect(copyBtn()!.querySelectorAll('svg.ic')).toHaveLength(1);
            expect(iconHref(copyBtn())).toBe('#i-copy');
            // Exactly one icon — an innerHTML rebuild must not stack duplicates.
            expect(copyBtn()!.querySelectorAll('use')).toHaveLength(1);
            expect(writeText).toHaveBeenCalledTimes(2);
        });
    });

    describe('finalizeStreamingMessage() path', () => {
        // This bubble is only replaced when stream_end carries a
        // user/assistant message id; without one it stays on screen, so the
        // same stripped-icon bug is reachable here.
        const STREAM_BUBBLE = `
            <div id="streaming-message" class="chat-message streaming">
                <div class="message-wrapper"><div class="message-content"></div></div>
            </div>`;
        const copyBtn = () => document.querySelector('#chat-messages .copy-message-btn');

        it('restores the copy glyph after the confirmation', async () => {
            const cm = mountDomAndChat();
            document.getElementById('chat-messages')!.innerHTML = STREAM_BUBBLE;
            cm.finalizeStreamingMessage('streamed answer');

            expect(iconHref(copyBtn())).toBe('#i-copy');

            copyBtn()!.dispatchEvent(new MouseEvent('click', { bubbles: true }));
            await vi.advanceTimersByTimeAsync(0);
            expect(writeText).toHaveBeenCalledWith('streamed answer');
            expect(iconHref(copyBtn())).toBe('#i-check');

            await vi.advanceTimersByTimeAsync(1500);
            expect(copyBtn()!.querySelectorAll('svg.ic')).toHaveLength(1);
            expect(iconHref(copyBtn())).toBe('#i-copy');
        });

        it('copies the message even when the click lands on the <svg> glyph', async () => {
            // `.ic` has no pointer-events:none, so event.target is the <svg>.
            // The handler used to read data-content off event.target and copy ''.
            const cm = mountDomAndChat();
            document.getElementById('chat-messages')!.innerHTML = STREAM_BUBBLE;
            cm.finalizeStreamingMessage('streamed answer');

            const glyph = copyBtn()!.querySelector('svg.ic')!;
            glyph.dispatchEvent(new MouseEvent('click', { bubbles: true }));
            await vi.advanceTimersByTimeAsync(0);

            expect(writeText).toHaveBeenCalledWith('streamed answer');
            // …and the confirmation landed on the BUTTON, not inside the svg.
            expect(iconHref(copyBtn())).toBe('#i-check');
        });
    });
});

// ============================================================================
// updateChatHeader() — the AI avatar's visibility must ride on the `hidden`
// class, not an inline display.
//
// The bug: this method wrote `style.display='none'` while app.ts's
// updateAiAvatars() drives `classList`. Saving an avatar in Settings called
// updateAiAvatars(), which set .src and removed `hidden` — but the stale
// inline display:none survived, so the header slot stayed blank until the
// user happened to click a conversation row.
// ============================================================================

describe('updateChatHeader — AI avatar visibility uses the `hidden` class', () => {
    const CONV = {
        id: 'c1', title: 't', role_preset: 'general', thinking_enabled: false,
        is_starred: false, created_at: '2026-04-01',
    };
    let savedAvatar: string;
    let settings: typeof import('./shared.js').settings;

    beforeAll(async () => {
        settings = (await import('./shared.js')).settings;
    });

    beforeEach(() => { savedAvatar = settings.aiAvatar; });
    afterEach(() => { settings.aiAvatar = savedAvatar; });

    it('removes `hidden` and leaves NO inline display when a safe avatar is set', () => {
        const cm = mountDomAndChat();
        cm.currentConversation = CONV;
        settings.aiAvatar = 'https://example.com/a.png';

        cm.updateChatHeader();

        const img = document.getElementById('chat-role-avatar') as HTMLImageElement;
        expect(img.classList.contains('hidden')).toBe(false);
        expect(img.getAttribute('src')).toBe('https://example.com/a.png');
        expect(img.style.display).toBe('');
    });

    it('adds `hidden` (and no inline display) when there is no avatar', () => {
        const cm = mountDomAndChat();
        cm.currentConversation = CONV;
        settings.aiAvatar = '';

        cm.updateChatHeader();

        const img = document.getElementById('chat-role-avatar') as HTMLImageElement;
        expect(img.classList.contains('hidden')).toBe(true);
        expect(img.hasAttribute('src')).toBe(false);
        // The regression: this used to be 'none'.
        expect(img.style.display).toBe('');
    });

    it('a later class-only reveal (app.ts updateAiAvatars) actually shows the avatar', () => {
        const cm = mountDomAndChat();
        cm.currentConversation = CONV;
        settings.aiAvatar = '';
        cm.updateChatHeader();   // hides it — pre-fix via inline display:none

        // Exactly what updateAiAvatars() does after saveCroppedAvatar():
        const img = document.getElementById('chat-role-avatar') as HTMLImageElement;
        img.src = 'https://example.com/a.png';
        img.classList.remove('hidden');

        expect(img.classList.contains('hidden')).toBe(false);
        // Pre-fix a stale inline display:none survived here and won outright:
        // `.hidden { display:none !important }` is what the class relies on, and
        // an inline value cannot be cleared by removing a class.
        expect(img.style.display).toBe('');
    });
});
