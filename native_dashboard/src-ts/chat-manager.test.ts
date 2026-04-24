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

    it('sends an auth frame when the server requires auth and a token is present', () => {
        const cm = mountDomAndChat();
        // Inject a token into the ws-client.
        (cm.wsClient as unknown as { wsToken: string }).wsToken = 'secret';
        cm.handleMessage({ type: 'connected', requires_auth: true });
        expect(cm.wsClient.send).toHaveBeenCalledWith({ type: 'auth', token: 'secret' });
    });

    it('updates availableProviders from the payload', () => {
        const cm = mountDomAndChat();
        cm.handleMessage({
            type: 'connected',
            available_providers: ['gemini', 'claude'],
        });
        expect(cm.availableProviders).toEqual(['gemini', 'claude']);
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
