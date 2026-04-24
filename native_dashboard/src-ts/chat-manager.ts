/**
 * AI Chat Manager - WebSocket Client & Memory Manager
 * Extracted from app.ts for modularity.
 */

import {
    invoke,
    errorLogger,
    escapeHtml,
    isSafeAvatarUrl,
    safeAvatarUrl,
    showToast,
    showConfirmDialog,
    settings,
    saveSettings,
} from './shared.js';

// ============================================================================
// Chat Types
// ============================================================================

export interface ChatConversation {
    id: string;
    title: string | null;
    role_preset: string;
    role_name?: string;
    role_emoji?: string;
    role_color?: string;
    thinking_enabled: boolean;
    is_starred: boolean;
    message_count?: number;
    created_at: string;
    updated_at?: string;
    ai_provider?: string;
    tags?: string[];   // #22 — per-conversation tag list
}

export interface ChatMessage {
    id?: number;
    role: 'user' | 'assistant';
    content: string;
    created_at: string;
    images?: string[];  // Base64 encoded images
    thinking?: string;  // AI thought process
    mode?: string;      // Mode used (Thinking, Unrestricted, etc.)
    is_pinned?: boolean;  // Marked important by user (#20)
    liked?: boolean;      // User hit ❤️ on this message (#20b)
}

export interface RolePreset {
    name: string;
    emoji: string;
    color: string;
}

export interface Memory {
    id: string;
    content: string;
    category: string;
    created_at: string;
}

interface NativeConversationDetail {
    conversation: ChatConversation;
    messages: ChatMessage[];
}

// ============================================================================
// Memory Manager
// ============================================================================

export class MemoryManager {
    memories: Memory[] = [];
    currentCategory: string = 'all';

    loadMemories(): void {
        chatManager?.send({ type: 'get_memories', category: this.currentCategory === 'all' ? null : this.currentCategory });
    }

    saveMemory(content: string, category: string): void {
        chatManager?.send({ type: 'save_memory', content, category });
    }

    deleteMemory(id: string): void {
        chatManager?.send({ type: 'delete_memory', id });
    }

    renderMemories(memories: Memory[]): void {
        this.memories = memories;
        const container = document.getElementById('memories-list');
        if (!container) return;

        // Filter by category if needed
        const filteredMemories = this.currentCategory === 'all' 
            ? memories 
            : memories.filter(m => m.category === this.currentCategory);

        if (filteredMemories.length === 0) {
            container.innerHTML = `
                <div class="empty-memories">
                    <span class="empty-icon">\uD83E\uDDE0</span>
                    <p>No memories yet</p>
                    <p class="hint">Add memories to help AI remember important information about you</p>
                </div>
            `;
            return;
        }

        container.innerHTML = filteredMemories.map(memory => `
            <div class="memory-card" data-id="${escapeHtml(String(memory.id))}">
                <div class="memory-card-header">
                    <span class="memory-category-badge">${escapeHtml(memory.category || 'general')}</span>
                </div>
                <div class="memory-card-content">${escapeHtml(memory.content)}</div>
                <div class="memory-card-footer">
                    <span class="memory-timestamp">${this.formatTime(memory.created_at)}</span>
                    <button class="memory-delete-btn" data-id="${escapeHtml(String(memory.id))}">Delete</button>
                </div>
            </div>
        `).join('');

        // Add delete handlers
        container.querySelectorAll('.memory-delete-btn').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const id = (e.target as HTMLElement).dataset.id;
                if (id) {
                    const confirmed = await showConfirmDialog('Delete this memory?');
                    if (confirmed) {
                        this.deleteMemory(id);
                    }
                }
            });
        });
    }

    formatTime(isoString: string): string {
        try {
            return new Date(isoString).toLocaleDateString('en-US', {
                year: 'numeric',
                month: 'short',
                day: 'numeric',
                hour: '2-digit',
                minute: '2-digit'
            });
        } catch {
            return isoString;
        }
    }

    showModal(): void {
        const modal = document.getElementById('add-memory-modal');
        if (modal) {
            modal.classList.add('active');
            (document.getElementById('memory-content') as HTMLTextAreaElement).value = '';
        }
    }

    closeModal(): void {
        const modal = document.getElementById('add-memory-modal');
        if (modal) modal.classList.remove('active');
    }

    setupEventListeners(): void {
        // Category filter buttons
        document.querySelectorAll('.memory-category-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const category = (e.target as HTMLElement).dataset.category || 'all';
                this.currentCategory = category;
                
                // Update active state
                document.querySelectorAll('.memory-category-btn').forEach(b => b.classList.remove('active'));
                (e.target as HTMLElement).classList.add('active');
                
                // Re-render with filter
                this.renderMemories(this.memories);
            });
        });

        // Add memory button
        document.getElementById('btn-add-memory')?.addEventListener('click', () => this.showModal());

        // Modal close buttons
        document.getElementById('memory-modal-close')?.addEventListener('click', () => this.closeModal());
        document.getElementById('memory-modal-cancel')?.addEventListener('click', () => this.closeModal());
        document.getElementById('add-memory-modal')?.querySelector('.modal-overlay')
            ?.addEventListener('click', () => this.closeModal());

        // Save button
        document.getElementById('memory-modal-save')?.addEventListener('click', () => {
            const content = (document.getElementById('memory-content') as HTMLTextAreaElement)?.value?.trim();
            const category = (document.getElementById('memory-category') as HTMLSelectElement)?.value || 'general';
            
            if (!content) {
                showToast('Please enter memory content', { type: 'warning' });
            } else if (content.length > 10000) {
                showToast('Memory content too long (max 10,000 characters)', { type: 'warning' });
            } else {
                this.saveMemory(content, category);
            }
        });
    }
}

export const memoryManager = new MemoryManager();

// ============================================================================
// Chat Manager
// ============================================================================

export class ChatManager {
    // Cap local message history to bound DOM size in long sessions; rendered
    // history is also capped server-side at 20 messages per request.
    private static readonly MAX_LOCAL_MESSAGES = 200;

    ws: WebSocket | null = null;
    connected: boolean = false;
    currentConversation: ChatConversation | null = null;
    conversations: ChatConversation[] = [];
    messages: ChatMessage[] = [];
    selectedRole: string = 'general';
    isStreaming: boolean = false;
    reconnectAttempts: number = 0;
    maxReconnectAttempts: number = 5;
    presets: Record<string, RolePreset> = {};
    pendingDeleteId: string | null = null;
    pendingRenameId: string | null = null;
    attachedImages: string[] = [];  // Base64 encoded images
    currentMode: string = '';  // Store current mode for the streaming message
    aiProvider: string = localStorage.getItem('dashboard_ai_provider') || 'gemini';  // Current AI provider
    availableProviders: string[] = ['gemini'];  // Available providers from server
    thinkingEnabled: boolean = localStorage.getItem('dashboard_thinking') === 'true';  // Persist thinking preference
    isEditStreaming: boolean = false;  // True when AI edit streaming is in progress
    editTargetMessageId: number | null = null;  // DB ID of message being AI-edited
    editStreamContent: string = '';  // Accumulated edit stream content
    private userScrolledUp: boolean = false;  // True when user manually scrolls up during streaming
    private pingInterval: number | null = null;  // Track ping interval for cleanup
    private reconnectTimeout: number | null = null;  // Track reconnect timeout
    private pongPending: boolean = false;  // True after sending ping, cleared on pong
    private missedPongs: number = 0;       // Consecutive missed pongs
    private draftSaveTimer: number | null = null;  // Debounced localStorage draft writer
    private allTagsCache: { tag: string; count: number }[] = [];  // #22 populated by 'all_tags' message

    private wsToken: string | null = null;
    private readonly defaultWsEndpoint = 'ws://127.0.0.1:8765/ws';
    private readonly localhostWsEndpoint = 'ws://localhost:8765/ws';

    private isConnecting: boolean = false;
    private tokenUsageCache: Map<string, { input_tokens: number; output_tokens: number; total_tokens: number; context_window: number }> = new Map();

    private enrichConversation(conversation: ChatConversation): ChatConversation {
        const preset = this.presets[conversation.role_preset] || {};
        return {
            ...conversation,
            role_name: conversation.role_name || preset.name || conversation.role_preset || 'AI',
            role_emoji: conversation.role_emoji || preset.emoji || '\uD83E\uDD16',
            role_color: conversation.role_color || preset.color,
        };
    }

    async loadConversationsFallback(): Promise<void> {
        try {
            const conversations = await invoke<ChatConversation[]>('get_dashboard_conversations_native', { limit: 50 });
            this.conversations = (conversations || []).map(conversation => this.enrichConversation(conversation));
            this.renderConversationList();
        } catch (e) {
            errorLogger.log('NATIVE_CONVERSATIONS_LOAD_ERROR', 'Failed to load dashboard conversations from SQLite fallback', String(e));
        }
    }

    async loadConversationFallback(id: string): Promise<void> {
        try {
            const detail = await invoke<NativeConversationDetail>('get_dashboard_conversation_detail_native', {
                conversationId: id,
            });
            if (!detail.conversation) {
                errorLogger.log('NATIVE_CONVERSATION_LOAD_ERROR', `Conversation ${id} not found in SQLite fallback`);
                showToast('Conversation not found', { type: 'error' });
                return;
            }
            this.currentConversation = this.enrichConversation(detail.conversation);
            this.messages = (detail.messages || []) as ChatMessage[];
            this.showChatContainer();
            this.updateChatHeader();
            this.renderMessages();
            if (this.currentConversation?.id) {
                this.restoreContextWindowIndicator(this.currentConversation.id);
            } else {
                this.resetContextWindowIndicator();
            }
            this.renderConversationList();
        } catch (e) {
            errorLogger.log('NATIVE_CONVERSATION_LOAD_ERROR', `Failed to load dashboard conversation ${id} from SQLite fallback`, String(e));
            showToast('Failed to load conversation history', { type: 'error' });
        }
    }

    connect(): void {
        if (
            this.isConnecting
            || (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING))
        ) {
            return;
        }

        if (this.reconnectTimeout) {
            clearTimeout(this.reconnectTimeout);
            this.reconnectTimeout = null;
        }

        this.isConnecting = true;
        this.loadTokenUsageCache();

        try {
            Promise.all([
                invoke<string>('get_ws_token').catch(() => ''),
                invoke<string>('get_ws_endpoint').catch(() => this.defaultWsEndpoint),
            ]).then(([token, endpoint]) => {
                this.wsToken = token || null;
                const candidates = this.buildWsEndpointCandidates(endpoint || this.defaultWsEndpoint);
                this._connectWithUrl(candidates[0], candidates.slice(1));
            }).catch(() => {
                console.warn('WS config unavailable — falling back to default localhost endpoint');
                this.wsToken = null;
                const candidates = this.buildWsEndpointCandidates(this.defaultWsEndpoint);
                this._connectWithUrl(candidates[0], candidates.slice(1));
            }).finally(() => {
                this.isConnecting = false;
            });
        } catch (e) {
            this.isConnecting = false;
            console.error('Failed to create WebSocket:', e);
            errorLogger.log('WEBSOCKET_CREATE_ERROR', 'Failed to create WebSocket', String(e));
            this.scheduleReconnect();
        }
    }

    private buildWsEndpointCandidates(primaryEndpoint: string): string[] {
        const normalizedPrimary = primaryEndpoint.trim() || this.defaultWsEndpoint;
        const candidates = [normalizedPrimary, this.defaultWsEndpoint, this.localhostWsEndpoint];

        if (normalizedPrimary.includes('127.0.0.1')) {
            candidates.push(normalizedPrimary.replace('127.0.0.1', 'localhost'));
        }
        if (normalizedPrimary.includes('localhost')) {
            candidates.push(normalizedPrimary.replace('localhost', '127.0.0.1'));
        }

        return [...new Set(candidates.map(url => url.trim()).filter(Boolean))];
    }

    private _connectWithUrl(wsUrl: string, fallbackUrls: string[] = []): void {
        try {
            const socket = new WebSocket(wsUrl);
            this.ws = socket;
            let opened = false;

            socket.onopen = () => {
                if (this.ws !== socket) {
                    socket.close();
                    return;
                }

                opened = true;

                // Send token as first message for authentication (not in URL)
                if (this.wsToken) {
                    try {
                        socket.send(JSON.stringify({ type: 'auth', token: this.wsToken }));
                    } catch (e) {
                        console.error('Failed to authenticate WebSocket:', e);
                        errorLogger.log('WEBSOCKET_AUTH_ERROR', 'Failed to send dashboard auth token', String(e));
                        socket.close();
                        return;
                    }
                }
                this.connected = true;
                this.reconnectAttempts = 0;
                this.pongPending = false;
                this.missedPongs = 0;
                this.updateConnectionStatus(true);
            };

            socket.onclose = (event) => {
                if (this.ws !== socket) {
                    return;
                }

                this.ws = null;
                this.connected = false;

                if (!opened && fallbackUrls.length > 0) {
                    const [nextUrl, ...remaining] = fallbackUrls;
                    errorLogger.log(
                        'WEBSOCKET_FALLBACK',
                        `WebSocket connection to ${wsUrl} closed before opening; retrying ${nextUrl}`,
                        JSON.stringify({ code: event.code, reason: event.reason || '' }),
                    );
                    this._connectWithUrl(nextUrl, remaining);
                    return;
                }

                // Reset streaming state to prevent chat input from being permanently locked
                if (this.isStreaming) {
                    this.isStreaming = false;
                    this.isEditStreaming = false;
                    this.editTargetMessageId = null;
                    this.editStreamContent = '';
                    this.setInputEnabled(true);
                    const stuckMsg = document.getElementById('streaming-message');
                    if (stuckMsg) stuckMsg.remove();
                }
                this.updateConnectionStatus(false);
                this.scheduleReconnect();
            };

            socket.onerror = (error) => {
                if (this.ws !== socket) {
                    return;
                }

                // Only log first error, not repeated connection failures
                if (this.reconnectAttempts === 0) {
                    console.warn('\uD83D\uDD0C WebSocket connection failed (bot may not be running)');
                }
                errorLogger.log('WEBSOCKET_ERROR', `WebSocket connection error (${wsUrl})`, String(error));
                this.connected = false;
                this.updateConnectionStatus(false);
            };

            socket.onmessage = (event) => {
                if (this.ws !== socket) {
                    return;
                }

                // Reject excessively large messages to prevent memory exhaustion
                // Note: 50MB limit needed because conversation_loaded can include base64 images
                if (typeof event.data === 'string' && event.data.length > 50 * 1024 * 1024) {
                    console.warn('Dropped oversized WebSocket message:', event.data.length, 'bytes');
                    return;
                }

                try {
                    const data = JSON.parse(event.data);
                    this.handleMessage(data);
                } catch (e) {
                    console.error('Failed to parse WebSocket message:', e);
                    errorLogger.log('WEBSOCKET_PARSE_ERROR', 'Failed to parse message', String(e));
                }
            };
        } catch (e) {
            console.error('Failed to create WebSocket:', e);
            errorLogger.log('WEBSOCKET_CREATE_ERROR', 'Failed to create WebSocket', String(e));
            this.scheduleReconnect();
        }
    }

    scheduleReconnect(): void {
        // Clear existing reconnect timeout to prevent race condition
        if (this.reconnectTimeout) {
            clearTimeout(this.reconnectTimeout);
            this.reconnectTimeout = null;
        }
        
        if (this.reconnectAttempts >= this.maxReconnectAttempts) {
            console.warn('Max reconnect attempts reached');
            this.updateConnectionStatus(false);
            // Surface to the user so they don't sit in front of a frozen UI
            // wondering why messages stop sending.
            showToast(
                'Connection to AI server lost. Please restart the bot and reload the dashboard.',
                { type: 'error', duration: 10000 },
            );
            return;
        }

        this.reconnectAttempts++;
        const baseDelay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 30000);
        const jitter = Math.random() * baseDelay * 0.3;  // Add 0-30% jitter to prevent thundering herd
        const delay = Math.floor(baseDelay + jitter);
        console.debug(`Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts})`);
        this.reconnectTimeout = window.setTimeout(() => {
            this.reconnectTimeout = null;
            this.connect();
        }, delay);
    }

    disconnect(): void {
        // Clear ping interval
        if (this.pingInterval) {
            clearInterval(this.pingInterval);
            this.pingInterval = null;
        }
        // Clear reconnect timeout
        if (this.reconnectTimeout) {
            clearTimeout(this.reconnectTimeout);
            this.reconnectTimeout = null;
        }
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }
        this.connected = false;
    }

    send(data: unknown): void {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify(data));
        } else {
            showToast('Not connected to AI server', { type: 'error' });
        }
    }

    handleMessage(data: Record<string, unknown>): void {
        switch (data.type) {
            case 'connected':
                this.presets = (data.presets as Record<string, RolePreset>) || {};
                if (data.requires_auth) {
                    if (!this.wsToken) {
                        errorLogger.log('WEBSOCKET_AUTH_MISSING', 'Server requires dashboard auth but no token was loaded');
                        showToast('AI chat auth token is missing. Check DASHBOARD_WS_TOKEN.', { type: 'error' });
                        break;
                    }
                    this.send({ type: 'auth', token: this.wsToken });
                }
                // Update available AI providers from server
                if (data.available_providers) {
                    this.availableProviders = data.available_providers as string[];
                    // Use saved preference if valid, otherwise fall back to server default
                    const saved = localStorage.getItem('dashboard_ai_provider');
                    if (saved && this.availableProviders.includes(saved)) {
                        this.aiProvider = saved;
                    } else {
                        this.aiProvider = (data.default_provider as string) || this.availableProviders[0] || 'gemini';
                    }
                    this.updateProviderSelects();
                }
                this.listConversations();
                break;

            case 'conversations_list':
                this.conversations = ((data.conversations as ChatConversation[]) || [])
                    .map(conversation => this.enrichConversation(conversation));
                this.renderConversationList();
                // Auto-restore last-opened conversation if it still exists and
                // we don't already have one loaded.
                if (!this.currentConversation && settings.lastConversationId) {
                    const lastId = settings.lastConversationId;
                    if (this.conversations.some(c => c.id === lastId)) {
                        this.loadConversation(lastId);
                    }
                }
                break;

            case 'conversation_created':
                if (data.id && typeof data.id === 'string') {
                    this.currentConversation = this.enrichConversation(data as unknown as ChatConversation);
                    this.aiProvider = (data.ai_provider as string) || this.aiProvider;
                } else {
                    console.error('Invalid conversation_created data:', data);
                    break;
                }
                this.messages = [];
                this.showChatContainer();
                this.updateChatHeader();
                this.renderMessages();
                this.resetContextWindowIndicator();
                this.listConversations();
                this.closeModal();
                break;

            case 'conversation_loaded':
                this.currentConversation = this.enrichConversation(data.conversation as ChatConversation);
                this.aiProvider = (this.currentConversation as unknown as Record<string, unknown>).ai_provider as string || this.aiProvider;
                this.messages = (data.messages as ChatMessage[]) || [];
                // Reset virtualization window when switching conversations.
                this.visibleMessageCount = ChatManager.VIRT_WINDOW_SIZE;
                this.showChatContainer();
                this.updateChatHeader();
                this.renderMessages();
                if (data.token_usage) {
                    this.updateContextWindowIndicator(data.token_usage as {input_tokens: number; output_tokens: number; total_tokens: number; context_window: number});
                } else {
                    this.restoreContextWindowIndicator(this.currentConversation!.id);
                }
                this.renderConversationList();
                break;

            case 'stream_start':
                this.isStreaming = true;
                this.userScrolledUp = false;  // Reset scroll lock on new stream
                this.currentMode = data.mode as string || '';  // Store mode for later
                if (data.is_edit && data.target_message_id) {
                    // AI edit mode: prepare to update existing message in-place
                    this.isEditStreaming = true;
                    this.editTargetMessageId = data.target_message_id as number;
                    this.editStreamContent = '';
                    this.startEditStreamingUI(this.editTargetMessageId);
                } else if (data._failover_retry) {
                    // Failover retry: reuse existing streaming bubble, just reset its content
                    const existingMsg = document.getElementById('streaming-message');
                    if (existingMsg) {
                        const thinkingContainer = existingMsg.querySelector('.thinking-container') as HTMLElement;
                        const thinkingContent = existingMsg.querySelector('.thinking-content');
                        const streamingText = existingMsg.querySelector('.streaming-text');
                        if (thinkingContainer) { thinkingContainer.style.display = 'none'; }
                        if (thinkingContent) { thinkingContent.textContent = ''; }
                        if (streamingText) { streamingText.textContent = ''; }
                    } else {
                        this.appendStreamingMessage(data.mode as string || '');
                    }
                } else {
                    this.appendStreamingMessage(data.mode as string || '');
                }
                this.setInputEnabled(false);
                break;

            case 'thinking_start':
                this.showThinkingIndicator();
                break;

            case 'thinking_chunk':
                this.appendThinkingChunk(data.content as string);
                break;

            case 'thinking_end':
                this.finalizeThinking(data.full_thinking as string);
                break;

            case 'chunk':
                if (this.isEditStreaming) {
                    this.appendEditStreamChunk(data.content as string);
                } else {
                    this.appendChunk(data.content as string);
                }
                break;

            case 'stream_end':
                this.isStreaming = false;
                this.userScrolledUp = false;  // Reset scroll lock when stream ends

                // Failover cleanup: remove the failed streaming bubble silently
                if (data._failover_cleanup) {
                    const stuckMsg = document.getElementById('streaming-message');
                    if (stuckMsg) stuckMsg.remove();
                    // Also remove the empty assistant message from messages array if it was added
                    if (this.messages.length > 0 && this.messages[this.messages.length - 1].role === 'assistant' && !this.messages[this.messages.length - 1].content) {
                        this.messages.pop();
                    }
                    break;
                }

                if (this.isEditStreaming && data.is_edit) {
                    // AI edit complete: finalize the edited message
                    this.finalizeEditStreaming(data.full_response as string, data.target_message_id as number);
                    this.isEditStreaming = false;
                    this.editTargetMessageId = null;
                    this.editStreamContent = '';
                    this.setInputEnabled(true);
                    showToast('AI edit complete ✏️', { type: 'success' });
                    break;
                }
                this.finalizeStreamingMessage(data.full_response as string);
                // Backfill DB IDs so newly-sent messages become editable/deletable
                if (data.assistant_message_id) {
                    const lastMsg = this.messages[this.messages.length - 1];
                    if (lastMsg && lastMsg.role === 'assistant' && !lastMsg.id) {
                        lastMsg.id = data.assistant_message_id as number;
                    }
                }
                if (data.user_message_id) {
                    for (let i = this.messages.length - 1; i >= 0; i--) {
                        if (this.messages[i].role === 'user' && !this.messages[i].id) {
                            this.messages[i].id = data.user_message_id as number;
                            break;
                        }
                    }
                }
                if (data.user_message_id || data.assistant_message_id) {
                    this.renderMessages();
                }
                // Update context window usage indicator
                if (data.token_usage) {
                    this.updateContextWindowIndicator(data.token_usage as {
                        input_tokens: number;
                        output_tokens: number;
                        total_tokens: number;
                        context_window: number;
                    });
                }
                this.setInputEnabled(true);
                this.listConversations();  // Refresh sidebar message count
                break;

            case 'title_updated':
                {
                    const updatedConv = this.conversations.find(c => c.id === data.conversation_id);
                    if (updatedConv) updatedConv.title = data.title as string;
                    if (this.currentConversation && this.currentConversation.id === data.conversation_id) {
                        this.currentConversation.title = data.title as string;
                        this.updateChatHeader();
                    }
                    this.renderConversationList();
                }
                break;

            case 'conversation_deleted':
                this.conversations = this.conversations.filter(c => c.id !== data.id);
                this.tokenUsageCache.delete(data.id as string);
                this.saveTokenUsageCache();
                this.renderConversationList();
                if (this.currentConversation?.id === data.id) {
                    this.currentConversation = null;
                    this.hideChatContainer();
                }
                showToast('Conversation deleted', { type: 'success' });
                break;

            case 'conversation_starred':
                const conv = this.conversations.find(c => c.id === data.id);
                if (conv) conv.is_starred = data.starred as boolean;
                // Also update currentConversation if it's the same one
                if (this.currentConversation && this.currentConversation.id === data.id) {
                    this.currentConversation.is_starred = data.starred as boolean;
                }
                this.renderConversationList();
                this.updateStarButton();
                break;

            case 'conversation_exported':
                this.downloadExport(data as { id: string; format: string; data: string });
                break;

            case 'conversation_renamed':
                {
                    const renamedConv = this.conversations.find(c => c.id === data.id);
                    if (renamedConv) renamedConv.title = data.title as string;
                    if (this.currentConversation && this.currentConversation.id === data.id) {
                        this.currentConversation.title = data.title as string;
                        this.updateChatHeader();
                    }
                    this.renderConversationList();
                    showToast('Conversation renamed', { type: 'success' });
                }
                break;

            case 'message_edited':
                {
                    const editedId = data.message_id as number;
                    const editedContent = data.content as string;
                    const shouldRegenerate = data.regenerate as boolean;
                    // Update local message
                    const editedMsg = this.messages.find(m => m.id === editedId);
                    if (editedMsg) editedMsg.content = editedContent;
                    // Preserve scroll position so user stays where they are
                    const chatEl = document.getElementById('chat-messages');
                    const savedPos = chatEl?.scrollTop ?? 0;
                    if (shouldRegenerate && editedMsg) {
                        // Remove all messages after the edited one
                        const editedIdx = this.messages.indexOf(editedMsg);
                        this.messages = this.messages.slice(0, editedIdx + 1);
                        this.renderMessages();
                        if (chatEl) chatEl.scrollTop = savedPos;
                        // Re-send the edited message to get a new AI response
                        this.regenerateAfterEdit(editedMsg);
                    } else {
                        this.renderMessages();
                        if (chatEl) chatEl.scrollTop = savedPos;
                        showToast('Message edited', { type: 'success' });
                    }
                }
                break;

            case 'message_deleted':
                {
                    const deletedId = data.message_id as number;
                    const deletedPairId = data.pair_message_id as number | null;
                    this.messages = this.messages.filter(m =>
                        m.id !== deletedId && m.id !== deletedPairId
                    );
                    this.renderMessages();
                    this.listConversations();
                    showToast('Message deleted', { type: 'success' });
                }
                break;

            case 'message_pinned':
                {
                    const pinnedId = Number(data.message_id);
                    const pinned = Boolean(data.pinned);
                    const target = this.messages.find(m => m.id === pinnedId);
                    if (target) {
                        target.is_pinned = pinned;
                        this.renderMessages();
                    }
                    showToast(pinned ? 'Message pinned' : 'Message unpinned', { type: 'success', duration: 1200 });
                }
                break;

            case 'message_liked':
                {
                    const likedId = Number(data.message_id);
                    const liked = Boolean(data.liked);
                    const target = this.messages.find(m => m.id === likedId);
                    if (target) {
                        target.liked = liked;
                        this.renderMessages();
                    }
                }
                break;

            case 'conversation_tagged':
            case 'conversation_untagged':
                if (this.currentConversation
                    && data.conversation_id === this.currentConversation.id) {
                    (this.currentConversation as unknown as Record<string, unknown>).tags = data.tags as string[];
                    this.renderConversationTags();
                }
                break;

            case 'all_tags':
                // Cached for future tag-picker UI; not rendered yet.
                this.allTagsCache = data.tags as { tag: string; count: number }[];
                break;

            case 'status':
                // Informational status message (e.g., "retrying...")
                break;

            case 'error':
                console.error('Server error:', data.message);
                errorLogger.log('AI_SERVER_ERROR', data.message as string, JSON.stringify(data));
                showToast(data.message as string, { type: 'error' });
                this.isStreaming = false;
                this.setInputEnabled(true);
                // Clean up stuck streaming message on error
                const stuckErrorMsg = document.getElementById('streaming-message');
                if (stuckErrorMsg) stuckErrorMsg.remove();
                // Reset edit streaming state on error
                if (this.isEditStreaming) {
                    this.isEditStreaming = false;
                    this.editTargetMessageId = null;
                    this.editStreamContent = '';
                    this.renderMessages();  // Restore original message content
                }
                break;

            case 'pong':
                this.pongPending = false;
                this.missedPongs = 0;
                break;
                
            // Memory handlers
            case 'memories':
                memoryManager.renderMemories(data.memories as Memory[]);
                break;
                
            case 'memory_saved':
                showToast('Memory saved!', { type: 'success' });
                memoryManager.loadMemories();
                memoryManager.closeModal();
                break;
                
            case 'memory_deleted':
                showToast('Memory deleted', { type: 'success' });
                memoryManager.loadMemories();
                break;
                
            case 'profile':
                // Profile loaded - populate settings form
                {
                    const profile = data.profile as { display_name?: string; bio?: string; preferences?: string; is_creator?: boolean } || {};
                    const nameInput = document.getElementById('user-name-input') as HTMLInputElement;
                    const bioInput = document.getElementById('user-bio-input') as HTMLTextAreaElement;
                    const prefsInput = document.getElementById('user-preferences-input') as HTMLTextAreaElement;
                    const creatorToggle = document.getElementById('creator-toggle') as HTMLInputElement;
                    
                    if (nameInput && profile.display_name) nameInput.value = profile.display_name;
                    if (bioInput && profile.bio) bioInput.value = profile.bio;
                    if (prefsInput && profile.preferences) prefsInput.value = profile.preferences;
                    if (creatorToggle) {
                        creatorToggle.checked = profile.is_creator || false;
                        settings.isCreator = profile.is_creator || false;
                        saveSettings();
                    }
                }
                break;
                
            case 'profile_saved':
                showToast('Profile saved! AI will remember you.', { type: 'success' });
                break;

            // API Failover handlers
            case 'api_endpoints':
                window.dispatchEvent(new CustomEvent('api-failover-status', { detail: data }));
                break;

            case 'api_endpoint_switched':
                window.dispatchEvent(new CustomEvent('api-failover-status', { detail: data }));
                showToast(`🔀 API switched to ${(data.endpoint as string || '').toUpperCase()}${data.reason ? ` (${data.reason})` : ''}`, { type: 'info', duration: 4000 });
                break;

            case 'api_health_result':
                window.dispatchEvent(new CustomEvent('api-health-result', { detail: data }));
                break;

            default:
                console.warn('Unknown WebSocket message type:', data.type);
                break;
        }
    }

    updateConnectionStatus(connected: boolean): void {
        const statusEl = document.getElementById('chat-connection-status');
        if (statusEl) {
            statusEl.className = connected ? 'connected' : 'disconnected';
            if (connected) {
                statusEl.textContent = '\uD83D\uDFE2 Connected';
            } else if (this.reconnectAttempts >= this.maxReconnectAttempts) {
                statusEl.textContent = '\uD83D\uDD34 Disconnected';
            } else {
                statusEl.textContent = '\uD83D\uDFE0 Connecting...';
            }
        }
        // Note: Overlay is now controlled by bot status in updateStatusBadge()
    }

    listConversations(): void {
        if (this.connected) {
            this.send({ type: 'list_conversations' });
            return;
        }
        void this.loadConversationsFallback();
    }

    createConversation(): void {
        const providerSelect = document.getElementById('modal-ai-provider') as HTMLSelectElement | null;
        if (providerSelect) {
            this.aiProvider = providerSelect.value;
        }
        this.send({
            type: 'new_conversation',
            role_preset: this.selectedRole,
            thinking_enabled: this.thinkingEnabled,
            ai_provider: this.aiProvider,
        });
    }

    loadConversation(id: string): void {
        // Show loading spinner immediately for responsive feel
        this.showChatLoading();
        // Persist the last-opened conversation so it re-opens next launch.
        try {
            settings.lastConversationId = id;
            saveSettings();
        } catch {
            // Settings save failures are non-fatal — user will just not restore this conversation next launch.
        }
        // Restore any saved draft for this conversation.
        this.restoreDraft(id);
        if (this.connected) {
            this.send({ type: 'load_conversation', id });
            return;
        }
        void this.loadConversationFallback(id);
    }

    /** Per-conversation draft storage — key derived from conversation ID. */
    private draftKey(id: string): string {
        return `dashboard-draft-${id}`;
    }

    saveDraft(id: string, text: string): void {
        try {
            if (text) {
                localStorage.setItem(this.draftKey(id), text);
            } else {
                localStorage.removeItem(this.draftKey(id));
            }
        } catch {
            // Quota exceeded etc — drafts are best-effort, swallow.
        }
    }

    restoreDraft(id: string): void {
        try {
            const draft = localStorage.getItem(this.draftKey(id));
            const input = document.getElementById('chat-input') as HTMLTextAreaElement | null;
            if (input && draft) {
                input.value = draft;
            } else if (input) {
                input.value = '';
            }
        } catch {
            // Swallow — drafts are best-effort.
        }
    }

    clearDraft(id: string): void {
        try {
            localStorage.removeItem(this.draftKey(id));
        } catch {
            // Swallow.
        }
    }

    private showChatLoading(): void {
        const container = document.getElementById('chat-messages');
        if (!container) return;
        this.showChatContainer();
        // Show message-shaped skeleton placeholders instead of a generic spinner.
        const skeleton = (): string => `
            <div class="chat-message-skeleton">
                <div class="skeleton-avatar"></div>
                <div class="skeleton-body">
                    <div class="skeleton-line short"></div>
                    <div class="skeleton-line"></div>
                    <div class="skeleton-line"></div>
                </div>
            </div>`;
        container.innerHTML = skeleton() + skeleton() + skeleton();
    }

    deleteConversation(id: string): void {
        // Prevent double-click issues
        if (this.isStreaming) return;
        
        // Show custom delete confirmation modal
        this.pendingDeleteId = id;
        const modal = document.getElementById('delete-confirm-modal');
        if (modal) {
            modal.classList.add('active');
        }
    }

    confirmDelete(): void {
        if (this.pendingDeleteId) {
            this.send({ type: 'delete_conversation', id: this.pendingDeleteId });
            this.pendingDeleteId = null;
        }
        this.closeDeleteModal();
    }

    closeDeleteModal(): void {
        const modal = document.getElementById('delete-confirm-modal');
        if (modal) {
            modal.classList.remove('active');
        }
        this.pendingDeleteId = null;
    }

    renameConversation(id: string): void {
        if (this.isStreaming) return;
        
        const conv = this.conversations.find(c => c.id === id);
        this.pendingRenameId = id;
        
        const modal = document.getElementById('rename-modal');
        const input = document.getElementById('rename-input') as HTMLInputElement;
        if (modal && input) {
            input.value = conv?.title || '';
            modal.classList.add('active');
            input.focus();
            input.select();
        }
    }

    confirmRename(): void {
        const input = document.getElementById('rename-input') as HTMLInputElement;
        const newTitle = input?.value?.trim();
        
        if (this.pendingRenameId && newTitle) {
            this.send({ type: 'rename_conversation', id: this.pendingRenameId, title: newTitle });
            this.pendingRenameId = null;
        }
        this.closeRenameModal();
    }

    closeRenameModal(): void {
        const modal = document.getElementById('rename-modal');
        if (modal) {
            modal.classList.remove('active');
        }
        this.pendingRenameId = null;
    }

    starConversation(id: string, starred: boolean): void {
        this.send({ type: 'star_conversation', id, starred });
    }

    exportConversation(id: string, format: string = 'json'): void {
        this.send({ type: 'export_conversation', id, format });
    }

    /** Show a small modal letting the user pick an export format. */
    async promptExportFormat(): Promise<string | null> {
        return new Promise(resolve => {
            // Build modal lazily to keep index.html small.
            let modal = document.getElementById('export-format-modal');
            if (!modal) {
                modal = document.createElement('div');
                modal.id = 'export-format-modal';
                modal.className = 'modal';
                modal.innerHTML = `
                    <div class="modal-overlay" data-close-export></div>
                    <div class="modal-content modal-small">
                        <div class="modal-header">
                            <h2>📥 Export Format</h2>
                            <button class="modal-close" data-close-export aria-label="Close">&times;</button>
                        </div>
                        <div class="modal-body">
                            <p>Choose an export format:</p>
                            <div class="export-format-grid">
                                <button class="btn export-format-btn" data-format="json">
                                    <span class="format-icon">📋</span>
                                    <span class="format-name">JSON</span>
                                    <span class="format-desc">Structured data, re-importable</span>
                                </button>
                                <button class="btn export-format-btn" data-format="markdown">
                                    <span class="format-icon">📝</span>
                                    <span class="format-name">Markdown</span>
                                    <span class="format-desc">Human-readable, great for sharing</span>
                                </button>
                                <button class="btn export-format-btn" data-format="html">
                                    <span class="format-icon">🌐</span>
                                    <span class="format-name">HTML</span>
                                    <span class="format-desc">Standalone web page</span>
                                </button>
                                <button class="btn export-format-btn" data-format="txt">
                                    <span class="format-icon">📄</span>
                                    <span class="format-name">Plain Text</span>
                                    <span class="format-desc">Minimal, just the messages</span>
                                </button>
                            </div>
                        </div>
                    </div>
                `;
                document.body.appendChild(modal);
            }
            modal.classList.add('active');

            const cleanup = (result: string | null): void => {
                modal?.classList.remove('active');
                resolve(result);
            };
            modal.querySelectorAll('[data-close-export]').forEach(el => {
                el.addEventListener('click', () => cleanup(null), { once: true });
            });
            modal.querySelectorAll('.export-format-btn').forEach(btn => {
                btn.addEventListener('click', () => {
                    const format = (btn as HTMLElement).dataset.format || 'json';
                    cleanup(format);
                }, { once: true });
            });
        });
    }

    sendMessage(): void {
        const input = document.getElementById('chat-input') as HTMLTextAreaElement | null;
        const content = input?.value?.trim();

        if (!content || this.isStreaming) return;
        if (!this.currentConversation) {
            showToast('Please start a conversation first', { type: 'warning' });
            return;
        }

        // Detect /edit command: AI rewrites its last message based on user instruction
        if (content.startsWith('/edit ')) {
            const instruction = content.substring(6).trim();
            if (!instruction) {
                showToast('Usage: /edit <instruction>', { type: 'warning' });
                return;
            }
            // Find last assistant message with a DB ID
            let targetMsg: ChatMessage | null = null;
            for (let i = this.messages.length - 1; i >= 0; i--) {
                if (this.messages[i].role === 'assistant' && this.messages[i].id) {
                    targetMsg = this.messages[i];
                    break;
                }
            }
            if (!targetMsg || !targetMsg.id) {
                showToast('No AI message to edit', { type: 'warning' });
                return;
            }

            if (input) {
                input.value = '';
                this.autoResizeInput();
            }

            const thinkingToggle = document.getElementById('thinking-toggle') as HTMLInputElement | null;
            const userName = settings.userName || 'User';

            this.send({
                type: 'ai_edit_message',
                conversation_id: this.currentConversation.id,
                target_message_id: targetMsg.id,
                instruction,
                role_preset: this.currentConversation.role_preset,
                thinking_enabled: thinkingToggle?.checked || false,
                user_name: userName,
                ai_provider: this.aiProvider,
            });
            return;
        }

        // Get history BEFORE adding new message (backend will add it)
        // Strip unnecessary fields (images/thinking/mode) to reduce payload size
        const historyToSend = this.messages.slice(-20).map(m => ({
            role: m.role,
            content: m.content,
        }));

        // Add to local messages for display (include images)
        this.messages.push({
            role: 'user',
            content,
            created_at: new Date().toISOString(),
            images: this.attachedImages.length > 0 ? [...this.attachedImages] : undefined
        });
        this.trimLocalMessages();
        this.renderMessages();

        if (input) {
            input.value = '';
            this.autoResizeInput();
            input.focus();  // Keep cursor in input
        }
        // Message sent — draft no longer needed for this conversation.
        if (this.currentConversation) {
            this.clearDraft(this.currentConversation.id);
        }

        const thinkingToggle = document.getElementById('thinking-toggle') as HTMLInputElement | null;
        const searchToggle = document.getElementById('chat-use-search') as HTMLInputElement | null;
        const unrestrictedToggle = document.getElementById('chat-unrestricted') as HTMLInputElement | null;
        const userName = settings.userName || 'User';
        
        this.send({
            type: 'message',
            conversation_id: this.currentConversation.id,
            content,
            role_preset: this.currentConversation.role_preset,
            thinking_enabled: thinkingToggle?.checked || false,
            history: historyToSend,
            // New features
            use_search: searchToggle?.checked ?? true,
            unrestricted_mode: unrestrictedToggle?.checked || false,
            images: this.attachedImages,
            user_name: userName,
            ai_provider: this.aiProvider,
        });
        
        // Clear attached images after sending
        this.attachedImages = [];
        this.renderAttachedImages();
    }

    appendStreamingMessage(mode: string = ''): void {
        const container = document.getElementById('chat-messages');
        const msgDiv = document.createElement('div');
        msgDiv.className = 'chat-message assistant streaming';
        msgDiv.id = 'streaming-message';

        const aiName = this.currentConversation?.role_name || 'AI';
        const timeStr = this.formatTime(new Date().toISOString());
        const modeHtml = mode ? `<span class="message-mode">${escapeHtml(mode)}</span>` : '';
        const safeAi = safeAvatarUrl(settings.aiAvatar);
        const avatarHtml = safeAi
            ? `<img src="${safeAi}" alt="ai" class="user-avatar-img">`
            : (this.currentConversation?.role_emoji || '\uD83E\uDD16');
        
        msgDiv.innerHTML = `
            <div class="message-avatar">${avatarHtml}</div>
            <div class="message-wrapper">
                <div class="message-header">
                    <span class="message-name">${escapeHtml(aiName)}</span>
                    <span class="message-time">${timeStr}</span>
                    ${modeHtml}
                </div>

                <div class="thinking-container" style="display:none">
                    <div class="thinking-header">💭 Thinking...</div>
                    <div class="thinking-content"></div>
                </div>

                <div class="message-content">
                    <span class="streaming-text"></span>
                    <span class="typing-indicator-dots" aria-label="AI is typing"><span></span><span></span><span></span></span>
                </div>
            </div>
        `;

        container?.appendChild(msgDiv);
        this.scrollToBottom();
    }

    showThinkingIndicator(): void {
        const thinkingContainer = document.querySelector('#streaming-message .thinking-container') as HTMLElement;
        if (thinkingContainer) {
            thinkingContainer.style.display = 'block';
        }
    }

    appendThinkingChunk(text: string): void {
        const thinkingContent = document.querySelector('#streaming-message .thinking-content');
        if (thinkingContent) {
            thinkingContent.textContent += text;
            this.scrollToBottom();
        }
    }

    currentThinking: string = '';  // Store current thinking for the streaming message

    finalizeThinking(fullThinking: string): void {
        // Store for later use in finalizeStreamingMessage
        this.currentThinking = fullThinking;
        
        const thinkingContainer = document.querySelector('#streaming-message .thinking-container') as HTMLElement;
        const thinkingHeader = document.querySelector('#streaming-message .thinking-header') as HTMLElement;
        const thinkingContent = document.querySelector('#streaming-message .thinking-content') as HTMLElement;
        
        if (thinkingHeader) {
            thinkingHeader.textContent = '\uD83D\uDCAD Thought Process';
            thinkingHeader.classList.add('collapsible', 'collapsed');  // Start collapsed
            thinkingHeader.onclick = () => {
                thinkingContent?.classList.toggle('collapsed');
                thinkingHeader.classList.toggle('collapsed');
            };
        }
        if (thinkingContent) {
            // Render Markdown formatting (bold, italic, code, etc.)
            thinkingContent.innerHTML = this.formatMessage(fullThinking);
            thinkingContent.classList.add('collapsed');  // Start collapsed
        }
    }

    appendChunk(text: string): void {
        const streamingText = document.querySelector('#streaming-message .streaming-text');
        if (streamingText) {
            streamingText.textContent += text;
            this.scrollToBottom();
        }
    }

    finalizeStreamingMessage(fullResponse: string): void {
        const streamingMsg = document.getElementById('streaming-message');
        if (streamingMsg) {
            streamingMsg.classList.remove('streaming');
            streamingMsg.removeAttribute('id');

            const content = streamingMsg.querySelector('.message-content');
            if (content) {
                content.innerHTML = this.formatMessage(this.stripThinkTags(fullResponse));
                void this.highlightCodeBlocks(content as HTMLElement);
            }

            // Add action buttons (copy, edit, delete) at the bottom
            const wrapper = streamingMsg.querySelector('.message-wrapper');
            if (wrapper && !wrapper.querySelector('.message-actions')) {
                const actionsDiv = document.createElement('div');
                actionsDiv.className = 'message-actions';
                const msgIdx = this.messages.length; // Will be pushed below
                actionsDiv.innerHTML = `
                    <button class="copy-message-btn" data-content="${escapeHtml(fullResponse)}" title="Copy">\uD83D\uDCCB Copy</button>
                    <button class="edit-message-btn" data-msg-idx="${msgIdx}" title="Edit">\u270F\uFE0F Edit</button>
                    <button class="delete-message-btn" data-msg-idx="${msgIdx}" data-role="assistant" title="Delete">\uD83D\uDDD1\uFE0F Delete</button>
                `;
                wrapper.appendChild(actionsDiv);
                
                actionsDiv.querySelector('.copy-message-btn')?.addEventListener('click', async (e) => {
                    const btn = e.target as HTMLElement;
                    const contentAttr = btn.getAttribute('data-content') || '';
                    const textarea = document.createElement('textarea');
                    textarea.innerHTML = contentAttr;
                    const decodedContent = textarea.value;
                    try {
                        await navigator.clipboard.writeText(decodedContent);
                        btn.textContent = '\u2705 Copied';
                        setTimeout(() => { btn.textContent = '\uD83D\uDCCB Copy'; }, 1500);
                    } catch (err) {
                        console.error('Failed to copy:', err);
                    }
                });

                actionsDiv.querySelector('.edit-message-btn')?.addEventListener('click', () => {
                    this.startEditMessage(msgIdx);
                });

                actionsDiv.querySelector('.delete-message-btn')?.addEventListener('click', async () => {
                    const confirmed = await showConfirmDialog('Delete this message?');
                    if (confirmed) this.deleteMessage(msgIdx);
                });
            }
        }

        // Store message with thinking and mode if available
        const newMessage: ChatMessage = {
            role: 'assistant',
            content: fullResponse,
            created_at: new Date().toISOString()
        };
        if (this.currentThinking) {
            newMessage.thinking = this.currentThinking;
            this.currentThinking = '';  // Reset for next message
        }
        if (this.currentMode) {
            newMessage.mode = this.currentMode;
            this.currentMode = '';  // Reset for next message
        }
        this.messages.push(newMessage);
        this.trimLocalMessages();

        this.scrollToBottom();
    }

    private trimLocalMessages(): void {
        if (this.messages.length > ChatManager.MAX_LOCAL_MESSAGES) {
            this.messages = this.messages.slice(-ChatManager.MAX_LOCAL_MESSAGES);
        }
    }

    // ========================================================================
    // AI Edit Streaming — /edit command support
    // ========================================================================

    startEditStreamingUI(targetMessageId: number): void {
        // Find the target message element in DOM and put it into "editing" streaming state
        const msgIdx = this.messages.findIndex(m => m.id === targetMessageId);
        if (msgIdx < 0) return;

        const container = document.getElementById('chat-messages');
        if (!container) return;
        const msgElements = container.querySelectorAll('.chat-message');
        const msgEl = msgElements[msgIdx];
        if (!msgEl) return;

        const contentEl = msgEl.querySelector('.message-content');
        if (!contentEl) return;

        // Replace content with streaming placeholder
        contentEl.innerHTML = `
            <span class="streaming-text edit-streaming-text"></span>
            <span class="typing-indicator-dots" aria-label="AI is typing"><span></span><span></span><span></span></span>
        `;
        msgEl.classList.add('streaming');

        // Show mode badge if present
        const headerEl = msgEl.querySelector('.message-header');
        if (headerEl && this.currentMode) {
            let modeSpan = headerEl.querySelector('.message-mode') as HTMLElement;
            if (modeSpan) {
                modeSpan.textContent = this.currentMode;
            } else {
                modeSpan = document.createElement('span');
                modeSpan.className = 'message-mode';
                modeSpan.textContent = this.currentMode;
                headerEl.appendChild(modeSpan);
            }
        }

        // Hide action buttons during editing
        const actionsEl = msgEl.querySelector('.message-actions') as HTMLElement;
        if (actionsEl) actionsEl.style.display = 'none';
    }

    appendEditStreamChunk(text: string): void {
        const streamingText = document.querySelector('.edit-streaming-text');
        if (streamingText) {
            this.editStreamContent += text;
            streamingText.textContent = this.editStreamContent;
        }
    }

    finalizeEditStreaming(fullResponse: string, targetMessageId: number): void {
        // Update the local message content
        const msgIdx = this.messages.findIndex(m => m.id === targetMessageId);
        if (msgIdx >= 0) {
            this.messages[msgIdx].content = fullResponse;
            if (this.currentMode) {
                this.messages[msgIdx].mode = this.currentMode;
                this.currentMode = '';
            }
        }
        // Preserve scroll position so user stays where they are
        const chatContainer = document.getElementById('chat-messages');
        const savedScroll = chatContainer?.scrollTop ?? 0;
        this.renderMessages();
        if (chatContainer) chatContainer.scrollTop = savedScroll;
    }

    /** Current text typed into the #conversation-filter-input box. */
    private conversationFilter: string = '';

    renderConversationList(): void {
        const container = document.getElementById('conversation-list');
        if (!container) return;

        // Wire up the filter input once — it persists across innerHTML replacements
        // of #conversation-list, so bind it to the separate input element by id.
        this.setupConversationFilter();

        if (this.conversations.length === 0) {
            container.innerHTML = `
                <div class="no-conversations">
                    <p>No conversations yet</p>
                    <p>Start a new chat!</p>
                </div>
            `;
            return;
        }

        const filter = this.conversationFilter.trim().toLowerCase();
        const matches = filter
            ? this.conversations.filter(c => (c.title || '').toLowerCase().includes(filter))
            : this.conversations;

        if (matches.length === 0) {
            container.innerHTML = `
                <div class="no-conversations">
                    <p>No matches for "${escapeHtml(this.conversationFilter)}"</p>
                </div>
            `;
            return;
        }

        // Cap render size to keep innerHTML parse fast even with 1000+ convs.
        // 200 is well above the typical visible window and enough for scrolling.
        const RENDER_CAP = 200;
        const visible = matches.slice(0, RENDER_CAP);
        const overflow = matches.length - visible.length;

        container.innerHTML = visible.map(conv => {
            const preset = this.presets[conv.role_preset] || {};
            const isActive = this.currentConversation?.id === conv.id;
            const starClass = conv.is_starred ? 'starred' : '';
            const safeAi = safeAvatarUrl(settings.aiAvatar);
            const avatarHtml = safeAi
                ? `<img class="conv-avatar" src="${safeAi}" alt="AI">`
                : `<span class="conv-emoji">${escapeHtml(preset.emoji || '\uD83D\uDCAC')}</span>`;

            return `
                <div class="conversation-item ${isActive ? 'active' : ''} ${starClass}" 
                     data-id="${escapeHtml(conv.id)}">
                    ${avatarHtml}
                    <div class="conv-info">
                        <span class="conv-title">${escapeHtml(conv.title || 'New Chat')}</span>
                        <span class="conv-meta">${conv.message_count || 0} messages</span>
                    </div>
                    ${conv.is_starred ? '<span class="conv-star">\u2B50</span>' : ''}
                </div>
            `;
        }).join('') + (overflow > 0 ? `<div class="conversation-overflow-note">${overflow} more hidden — narrow your filter</div>` : '');

        // True event delegation on the container — survives innerHTML replacements
        // Remove old handler before adding new one to avoid duplicates
        if ((container as unknown as Record<string, unknown>)._convClickHandler) {
            container.removeEventListener('click', (container as unknown as Record<string, EventListener>)._convClickHandler);
        }
        const handler = (e: Event) => {
            const target = (e.target as HTMLElement).closest('.conversation-item[data-id]') as HTMLElement | null;
            if (target) {
                const id = target.dataset.id;
                if (id) this.loadConversation(id);
            }
        };
        (container as unknown as Record<string, EventListener>)._convClickHandler = handler;
        container.addEventListener('click', handler);
    }

    private conversationFilterDebounce: number | null = null;

    private setupConversationFilter(): void {
        const input = document.getElementById('conversation-filter-input') as HTMLInputElement | null;
        if (!input || input.dataset.filterBound) return;
        input.addEventListener('input', () => {
            // Debounce — filtering 1000+ conversations on every keystroke is
            // O(n) innerHTML re-render that drops frames during rapid typing.
            if (this.conversationFilterDebounce !== null) {
                clearTimeout(this.conversationFilterDebounce);
            }
            this.conversationFilterDebounce = window.setTimeout(() => {
                this.conversationFilter = input.value;
                const container = document.getElementById('conversation-list');
                const savedScroll = container?.scrollTop ?? 0;
                this.renderConversationList();
                if (container) container.scrollTop = savedScroll;
                this.conversationFilterDebounce = null;
            }, 120);
        });
        input.dataset.filterBound = '1';
    }

    renderMessages(): void {
        const container = document.getElementById('chat-messages');
        if (!container) return;

        if (this.messages.length === 0) {
            const emoji = this.currentConversation?.role_emoji || '\uD83E\uDD16';
            const name = this.currentConversation?.role_name || 'AI';
            const safeAi = safeAvatarUrl(settings.aiAvatar);
            const welcomeAvatarHtml = safeAi
                ? `<img src="${safeAi}" alt="AI" class="welcome-avatar">`
                : `<div class="welcome-emoji">${emoji}</div>`;
            container.innerHTML = `
                <div class="chat-welcome">
                    ${welcomeAvatarHtml}
                    <h3>Chat with ${escapeHtml(name)}</h3>
                    <p>Type a message to start the conversation</p>
                </div>
            `;
            return;
        }

        const aiEmoji = this.currentConversation?.role_emoji || '\uD83E\uDD16';
        const aiName = this.currentConversation?.role_name || 'AI';
        const userName = settings.userName || 'You';
        const safeUserAvatar = safeAvatarUrl(settings.userAvatar);
        const safeAiAvatar = safeAvatarUrl(settings.aiAvatar);

        // Virtualization: render only the tail window for long conversations.
        const _total = this.messages.length;
        const _shouldVirtualize = _total > ChatManager.VIRT_THRESHOLD;
        if (_shouldVirtualize && this.visibleMessageCount <= 0) {
            this.visibleMessageCount = ChatManager.VIRT_WINDOW_SIZE;
        }
        const _windowSize = _shouldVirtualize ? Math.min(this.visibleMessageCount, _total) : _total;
        const _startIdx = _total - _windowSize;
        const _hiddenBefore = _startIdx;
        const _showEarlierBtn = _hiddenBefore > 0
            ? `<button class="show-earlier-btn" id="chat-show-earlier">↑ Show ${Math.min(_hiddenBefore, ChatManager.VIRT_WINDOW_SIZE)} earlier (${_hiddenBefore} hidden)</button>`
            : '';

        container.innerHTML = _showEarlierBtn + this.messages.slice(_startIdx).map((msg, _sliceIdx) => {
            const msgIdx = _startIdx + _sliceIdx;  // absolute index into this.messages
            const isUser = msg.role === 'user';
            const displayName = isUser ? userName : aiName;
            const timeStr = this.formatTime(msg.created_at);

            // Both user and AI can have custom avatar images
            let avatarHtml: string;
            if (isUser) {
                avatarHtml = safeUserAvatar
                    ? `<img src="${safeUserAvatar}" alt="avatar" class="user-avatar-img">`
                    : '\uD83D\uDC64';
            } else {
                avatarHtml = safeAiAvatar
                    ? `<img src="${safeAiAvatar}" alt="ai" class="user-avatar-img">`
                    : aiEmoji;
            }

            // Render attached images for user messages (use data attribute to avoid XSS)
            let imagesHtml = '';
            if (msg.images && msg.images.length > 0) {
                imagesHtml = `<div class="message-images">${msg.images.map((img, idx) => 
                    `<img src="${escapeHtml(img)}" alt="attached" class="message-image" data-img-idx="${idx}">`
                ).join('')}</div>`;
            }

            // Render thinking container for AI messages (collapsed by default)
            let thinkingHtml = '';
            if (!isUser && msg.thinking) {
                thinkingHtml = `
                    <div class="thinking-container">
                        <div class="thinking-header collapsible collapsed">
                            \uD83D\uDCAD Thought Process
                        </div>
                        <div class="thinking-content collapsed">${this.formatMessage(msg.thinking)}</div>
                    </div>
                `;
            }

            // Mode badge for AI messages
            const modeHtml = (!isUser && msg.mode) 
                ? `<span class="message-mode">${escapeHtml(msg.mode)}</span>` 
                : '';

            // Action buttons for all messages
            const msgId = msg.id != null ? msg.id : '';
            const copyBtn = `<button class="copy-message-btn" data-content="${escapeHtml(msg.content)}" title="Copy">\uD83D\uDCCB Copy</button>`;
            const editBtn = `<button class="edit-message-btn" data-msg-id="${msgId}" data-msg-idx="${msgIdx}" title="Edit">\u270F\uFE0F Edit</button>`;
            const aiEditBtn = (!isUser && msgId) ? `<button class="ai-edit-message-btn" data-msg-id="${msgId}" data-msg-idx="${msgIdx}" title="AI Edit">\u2728 AI Edit</button>` : '';
            const deleteBtn = `<button class="delete-message-btn" data-msg-id="${msgId}" data-msg-idx="${msgIdx}" data-role="${msg.role}" title="Delete">\uD83D\uDDD1\uFE0F Delete</button>`;
            const pinLabel = msg.is_pinned ? 'Unpin' : 'Pin';
            const pinBtn = msgId
                ? `<button class="pin-message-btn${msg.is_pinned ? ' pinned' : ''}" data-msg-id="${msgId}" data-pinned="${msg.is_pinned ? '1' : '0'}" title="${pinLabel}" aria-label="${pinLabel} message">\uD83D\uDCCC ${pinLabel}</button>`
                : '';
            const likeBtn = msgId
                ? `<button class="like-message-btn${msg.liked ? ' liked' : ''}" data-msg-id="${msgId}" data-liked="${msg.liked ? '1' : '0'}" title="${msg.liked ? 'Unlike' : 'Like'}" aria-label="${msg.liked ? 'Unlike' : 'Like'} message">${msg.liked ? '\u2764\uFE0F' : '\uD83E\uDD0D'}</button>`
                : '';
            const actionsHtml = `<div class="message-actions">${copyBtn}${likeBtn}${pinBtn}${editBtn}${aiEditBtn}${deleteBtn}</div>`;

            return `
                <div class="chat-message ${msg.role}">
                    <div class="message-avatar">${avatarHtml}</div>
                    <div class="message-wrapper">
                        <div class="message-header">
                            <span class="message-name">${escapeHtml(displayName)}</span>
                            <span class="message-time">${timeStr}</span>
                            ${modeHtml}
                        </div>
                        ${thinkingHtml}
                        ${imagesHtml}
                        <div class="message-content">${this.formatMessage(this.stripThinkTags(msg.content))}</div>
                        ${actionsHtml}
                    </div>
                </div>
            `;
        }).join('');

        this.scrollToBottom();
        this.setupScrollListener();
        // Fire-and-forget: syntax-highlight any code blocks in the new markup.
        // `await` is intentionally omitted so renderMessages() stays synchronous for callers.
        void this.highlightCodeBlocks(container);

        // Hook the "Show N earlier messages" button (virtualization, #16).
        const showEarlier = document.getElementById('chat-show-earlier');
        if (showEarlier) {
            showEarlier.addEventListener('click', () => {
                // Preserve scroll offset so the currently-top visible message stays put.
                const prevScrollHeight = container.scrollHeight;
                const prevScrollTop = container.scrollTop;
                this.visibleMessageCount += ChatManager.VIRT_WINDOW_SIZE;
                this.renderMessages();
                // After re-render, shift scrollTop by the added height so the user's
                // eye stays on the same message they were reading.
                const delta = container.scrollHeight - prevScrollHeight;
                container.scrollTop = prevScrollTop + delta;
            }, { once: true });
        }

        // Setup event delegation for image clicks (avoid inline onclick XSS risk)
        container.querySelectorAll('.message-image[data-img-idx]').forEach(img => {
            img.addEventListener('click', () => {
                const src = (img as HTMLImageElement).src;
                if (src) {
                    // Open image in new window safely (no document.write XSS)
                    const newWindow = window.open('', '_blank');
                    if (newWindow) {
                        const doc = newWindow.document;
                        doc.title = 'Image Preview';
                        const style = doc.createElement('style');
                        style.textContent = 'body{margin:0;display:flex;justify-content:center;align-items:center;min-height:100vh;background:#1a1a1a;}img{max-width:100%;max-height:100vh;object-fit:contain;}';
                        doc.head.appendChild(style);
                        const imgEl = doc.createElement('img');
                        imgEl.src = src;
                        imgEl.alt = 'preview';
                        doc.body.appendChild(imgEl);
                    }
                }
            });
        });

        // Setup thinking header toggle clicks (replaces inline onclick blocked by CSP)
        container.querySelectorAll('.thinking-header.collapsible').forEach(header => {
            header.addEventListener('click', () => {
                header.classList.toggle('collapsed');
                const content = header.nextElementSibling;
                if (content) content.classList.toggle('collapsed');
            });
        });

        // Setup copy button clicks (whole message)
        container.querySelectorAll('.copy-message-btn').forEach(btn => {
            btn.addEventListener('click', async () => {
                const content = (btn as HTMLElement).getAttribute('data-content') || '';
                const textarea = document.createElement('textarea');
                textarea.innerHTML = content;
                const decodedContent = textarea.value;

                try {
                    await navigator.clipboard.writeText(decodedContent);
                    const originalText = btn.textContent;
                    btn.textContent = '\u2705';
                    setTimeout(() => { btn.textContent = originalText; }, 1500);
                } catch (err) {
                    console.error('Failed to copy:', err);
                    showToast('Failed to copy message', { type: 'error' });
                }
            });
        });

        // Setup code-block copy button clicks (per-block inside a message)
        container.querySelectorAll('.code-copy-btn').forEach(btn => {
            btn.addEventListener('click', async () => {
                const encoded = (btn as HTMLElement).getAttribute('data-code-copy') || '';
                // data-code-copy was HTML-escaped at render time \u2014 decode it via textarea.
                const decoder = document.createElement('textarea');
                decoder.innerHTML = encoded;
                try {
                    await navigator.clipboard.writeText(decoder.value);
                    const originalText = btn.textContent;
                    btn.textContent = '\u2705';
                    setTimeout(() => { btn.textContent = originalText; }, 1200);
                } catch (err) {
                    console.error('Failed to copy code:', err);
                    showToast('Failed to copy code', { type: 'error' });
                }
            });
        });

        // Setup edit button clicks
        container.querySelectorAll('.edit-message-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const idx = parseInt((btn as HTMLElement).dataset.msgIdx || '-1');
                if (idx >= 0) this.startEditMessage(idx);
            });
        });

        // Setup AI edit button clicks
        container.querySelectorAll('.ai-edit-message-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const idx = parseInt((btn as HTMLElement).dataset.msgIdx || '-1');
                if (idx >= 0) this.startAiEditMessage(idx);
            });
        });

        // Setup delete button clicks
        container.querySelectorAll('.delete-message-btn').forEach(btn => {
            btn.addEventListener('click', async () => {
                const idx = parseInt((btn as HTMLElement).dataset.msgIdx || '-1');
                if (idx >= 0) {
                    const confirmed = await showConfirmDialog('Delete this message?');
                    if (confirmed) this.deleteMessage(idx);
                }
            });
        });

        // Setup pin/unpin button clicks
        container.querySelectorAll('.pin-message-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const el = btn as HTMLElement;
                const msgId = el.dataset.msgId;
                if (!msgId) return;
                const nextPinned = el.dataset.pinned !== '1';
                this.send({ type: 'pin_message', message_id: parseInt(msgId), pinned: nextPinned });
                // Optimistic local update — server confirmation will re-render.
                const targetMsg = this.messages.find(m => String(m.id) === msgId);
                if (targetMsg) targetMsg.is_pinned = nextPinned;
                this.renderMessages();
            });
        });

        // Setup like/unlike button clicks (#20b)
        container.querySelectorAll('.like-message-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const el = btn as HTMLElement;
                const msgId = el.dataset.msgId;
                if (!msgId) return;
                const nextLiked = el.dataset.liked !== '1';
                this.send({ type: 'like_message', message_id: parseInt(msgId), liked: nextLiked });
                const targetMsg = this.messages.find(m => String(m.id) === msgId);
                if (targetMsg) targetMsg.liked = nextLiked;
                this.renderMessages();
            });
        });
    }

    stripThinkTags(content: string): string {
        return content.replace(/<think>[\s\S]*?<\/think>/g, '').trim();
    }

    // ------------------------------------------------------------------
    // Prism.js syntax highlighting (#11).
    // Languages are loaded once per session, on demand, from vendor/prism/.
    // ------------------------------------------------------------------

    /** Languages we shipped bundles for (see native_dashboard/ui/vendor/prism/). */
    private static readonly PRISM_LANGS: ReadonlySet<string> = new Set([
        'markup', 'css', 'clike', 'javascript', 'js', 'bash', 'shell', 'c',
        'csharp', 'cs', 'cpp', 'diff', 'go', 'ini', 'java', 'json', 'kotlin',
        'lua', 'markdown', 'md', 'powershell', 'ps1', 'python', 'py', 'ruby',
        'rb', 'rust', 'rs', 'sql', 'swift', 'toml', 'typescript', 'ts', 'yaml', 'yml',
    ]);

    private prismLoadPromises: Map<string, Promise<void>> = new Map();

    /** Normalize alias → canonical Prism id (js → javascript, py → python, …). */
    private canonicalPrismLang(lang: string): string {
        const aliases: Record<string, string> = {
            js: 'javascript', ts: 'typescript', py: 'python',
            rb: 'ruby', rs: 'rust', cs: 'csharp', 'c++': 'cpp',
            sh: 'bash', shell: 'bash', md: 'markdown',
            ps1: 'powershell', yml: 'yaml',
        };
        return aliases[lang] || lang;
    }

    /** Lazily load a Prism language component via <script> injection. */
    private async loadPrismLanguage(lang: string): Promise<void> {
        const canon = this.canonicalPrismLang(lang);
        if (!ChatManager.PRISM_LANGS.has(canon)) return;
        const prism = (window as unknown as { Prism?: { languages: Record<string, unknown> } }).Prism;
        if (!prism) return;  // Prism core not loaded (CSP block or load failure).
        if (prism.languages[canon]) return;
        const existing = this.prismLoadPromises.get(canon);
        if (existing) return existing;

        const p = new Promise<void>((resolve) => {
            const script = document.createElement('script');
            script.src = `vendor/prism/prism-${canon}.min.js`;
            script.async = false;  // Preserve load order (markup may depend on clike etc.)
            script.onload = () => resolve();
            script.onerror = () => {
                errorLogger.log('PRISM_LANG_LOAD_FAIL', `Failed to load Prism language: ${canon}`);
                resolve();  // Don't reject — fall back to plain-text code.
            };
            document.head.appendChild(script);
        });
        this.prismLoadPromises.set(canon, p);
        return p;
    }

    /** Walk newly-rendered <pre><code class="language-X"> blocks and highlight them. */
    async highlightCodeBlocks(root: HTMLElement): Promise<void> {
        const prism = (window as unknown as { Prism?: { highlightElement: (el: Element) => void; languages: Record<string, unknown> } }).Prism;
        if (!prism) return;
        const codes = root.querySelectorAll('pre code[class*="language-"]');
        for (const code of Array.from(codes)) {
            if ((code as HTMLElement).dataset.prismDone === '1') continue;
            const cls = code.className.match(/language-(\S+)/);
            if (!cls) continue;
            const lang = cls[1].toLowerCase();
            if (lang === 'code') continue;  // Our fallback marker from formatMessage.
            await this.loadPrismLanguage(lang);
            if (prism.languages[this.canonicalPrismLang(lang)]) {
                try {
                    prism.highlightElement(code);
                } catch (e) {
                    console.debug('Prism highlight failed:', e);
                }
            }
            (code as HTMLElement).dataset.prismDone = '1';
        }
    }

    formatMessage(content: string): string {
        // Extract LaTeX blocks BEFORE HTML escaping so KaTeX gets raw math notation
        const latexBlocks: string[] = [];
        const blockPlaceholder = '\x00BLOCK_LATEX_';
        const inlinePlaceholder = '\x00INLINE_LATEX_';

        // Extract block LaTeX ($$...$$)
        let processed = content.replace(/\$\$([^$]+)\$\$/g, (_match, tex) => {
            const idx = latexBlocks.length;
            try {
                if (typeof window !== 'undefined' && (window as unknown as { katex?: { renderToString: (tex: string, options: object) => string } }).katex) {
                    latexBlocks.push(`<div class="math-block">${(window as unknown as { katex: { renderToString: (tex: string, options: object) => string } }).katex.renderToString(tex.trim(), { displayMode: true, throwOnError: false })}</div>`);
                } else {
                    latexBlocks.push(`<div class="math-block">$$${escapeHtml(tex)}$$</div>`);
                }
            } catch {
                latexBlocks.push(`<div class="math-block">$$${escapeHtml(tex)}$$</div>`);
            }
            return `${blockPlaceholder}${idx}\x00`;
        });

        // Extract inline LaTeX ($...$)
        processed = processed.replace(/(?<!\$)\$(?!\$)([^$]+)\$(?!\$)/g, (_match, tex) => {
            const idx = latexBlocks.length;
            try {
                if (typeof window !== 'undefined' && (window as unknown as { katex?: { renderToString: (tex: string, options: object) => string } }).katex) {
                    latexBlocks.push(`<span class="math-inline">${(window as unknown as { katex: { renderToString: (tex: string, options: object) => string } }).katex.renderToString(tex.trim(), { displayMode: false, throwOnError: false })}</span>`);
                } else {
                    latexBlocks.push(`<span class="math-inline">$${escapeHtml(tex)}$</span>`);
                }
            } catch {
                latexBlocks.push(`<span class="math-inline">$${escapeHtml(tex)}$</span>`);
            }
            return `${inlinePlaceholder}${idx}\x00`;
        });

        // Now HTML-escape the rest (placeholders will be escaped but we restore them below)
        let html = escapeHtml(processed);

        // Restore LaTeX blocks from placeholders
        html = html.replace(/\x00(?:BLOCK_LATEX_|INLINE_LATEX_)(\d+)\x00/g, (_match, idx) => {
            return latexBlocks[parseInt(idx)] || '';
        });
        
        // Extract code blocks into placeholders BEFORE converting \n to <br>.
        // Include a copy button that reads the raw code from data-code-copy.
        // `code` is already HTML-escaped (line 1589 above), so it's safe to
        // embed inside a data attribute — escapeHtml also escapes " and `.
        const codeBlocks: string[] = [];
        const codePlaceholder = '\x01CODE_BLOCK_';
        html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (_match, lang, code) => {
            const idx = codeBlocks.length;
            const langLabel = lang || 'code';
            codeBlocks.push(
                `<div class="code-block-wrapper">` +
                `<div class="code-block-header">` +
                `<span class="code-lang">${langLabel}</span>` +
                `<button class="code-copy-btn" data-code-copy="${code}" title="Copy code">📋</button>` +
                `</div>` +
                `<pre><code class="language-${langLabel}">${code}</code></pre>` +
                `</div>`
            );
            return `${codePlaceholder}${idx}\x01`;
        });
        html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
        html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
        html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');
        // Headings (# to ######) — must be at start of line
        html = html.replace(/^#{6}\s+(.+)$/gm, '<h6 class="md-heading">$1</h6>');
        html = html.replace(/^#{5}\s+(.+)$/gm, '<h5 class="md-heading">$1</h5>');
        html = html.replace(/^#{4}\s+(.+)$/gm, '<h4 class="md-heading">$1</h4>');
        html = html.replace(/^#{3}\s+(.+)$/gm, '<h3 class="md-heading">$1</h3>');
        html = html.replace(/^#{2}\s+(.+)$/gm, '<h2 class="md-heading">$1</h2>');
        html = html.replace(/^#{1}\s+(.+)$/gm, '<h1 class="md-heading">$1</h1>');
        // Horizontal rule (--- or ___ or *** on its own line)
        html = html.replace(/^(?:---+|___+|\*\*\*+)\s*$/gm, '<hr class="md-hr">');
        // Blockquotes (> at start of line)
        html = html.replace(/^&gt; (.+)$/gm, '<blockquote>$1</blockquote>');
        // Merge consecutive blockquotes
        html = html.replace(/<\/blockquote>\n?<blockquote>/g, '<br>');

        // Markdown tables — extract into placeholders before \n → <br>
        const tableBlocks: string[] = [];
        const tablePlaceholder = '\x02TABLE_BLOCK_';
        html = html.replace(
            /(?:^|\n)(\|.+\|\n\|[\s:|-]+\|\n(?:\|.+\|(?:\n|$))+)/g,
            (_match, table: string) => {
                const rows = table.trim().split('\n');
                if (rows.length < 2) return _match;
                const headerCells = rows[0].split('|').filter(c => c.trim() !== '');
                // rows[1] is separator — parse alignment
                const alignCells = rows[1].split('|').filter(c => c.trim() !== '');
                const aligns = alignCells.map(c => {
                    const t = c.trim();
                    if (t.startsWith(':') && t.endsWith(':')) return 'center';
                    if (t.endsWith(':')) return 'right';
                    return 'left';
                });
                let tbl = '<div class="md-table-wrap"><table class="md-table"><thead><tr>';
                headerCells.forEach((cell, i) => {
                    const align = aligns[i] || 'left';
                    tbl += `<th style="text-align:${align}">${cell.trim()}</th>`;
                });
                tbl += '</tr></thead><tbody>';
                for (let r = 2; r < rows.length; r++) {
                    const cells = rows[r].split('|').filter(c => c.trim() !== '');
                    tbl += '<tr>';
                    cells.forEach((cell, i) => {
                        const align = aligns[i] || 'left';
                        tbl += `<td style="text-align:${align}">${cell.trim()}</td>`;
                    });
                    tbl += '</tr>';
                }
                tbl += '</tbody></table></div>';
                const idx = tableBlocks.length;
                tableBlocks.push(tbl);
                return `${tablePlaceholder}${idx}\x02`;
            }
        );

        // Unordered lists: consecutive lines starting with - or *
        const listBlocks: string[] = [];
        const listPlaceholder = '\x03LIST_BLOCK_';
        html = html.replace(/((?:^|\n)(?:[-*]\s+.+(?:\n|$))+)/g, (match) => {
            const items = match.trim().split('\n').map(line => line.replace(/^[-*]\s+/, '').trim());
            const i = listBlocks.length;
            listBlocks.push('<ul>' + items.map(item => `<li>${item}</li>`).join('') + '</ul>');
            return `\n${listPlaceholder}${i}\x03\n`;
        });

        // Ordered lists: consecutive lines starting with 1. 2. etc.
        html = html.replace(/((?:^|\n)(?:\d+\.\s+.+(?:\n|$))+)/g, (match) => {
            const items = match.trim().split('\n').map(line => line.replace(/^\d+\.\s+/, '').trim());
            const i = listBlocks.length;
            listBlocks.push('<ol>' + items.map(item => `<li>${item}</li>`).join('') + '</ol>');
            return `\n${listPlaceholder}${i}\x03\n`;
        });

        // Paragraph breaks: double+ newlines become spaced paragraph break
        html = html.replace(/\n{2,}/g, '<br><div class="paragraph-break"></div>');
        html = html.replace(/\n/g, '<br>');

        // Restore list blocks
        html = html.replace(/\x03LIST_BLOCK_(\d+)\x03/g, (_match, idx) => {
            return listBlocks[parseInt(idx)] || '';
        });

        // Restore table blocks
        html = html.replace(/\x02TABLE_BLOCK_(\d+)\x02/g, (_match, idx) => {
            return tableBlocks[parseInt(idx)] || '';
        });
        
        // Restore code blocks (newlines preserved inside <pre>)
        html = html.replace(/\x01CODE_BLOCK_(\d+)\x01/g, (_match, idx) => {
            return codeBlocks[parseInt(idx)] || '';
        });

        // Sanitize final HTML output with DOMPurify (whitelist approach).
        // DOMPurify is bundled locally in vendor/ and always available — if it
        // ever fails to load, better to throw than render unsanitized HTML.
        const purify = (window as unknown as { DOMPurify?: { sanitize: (html: string, config: object) => string } }).DOMPurify;
        if (!purify) {
            errorLogger.log('DOMPURIFY_MISSING', 'DOMPurify failed to load — rendering aborted to prevent XSS');
            return '';
        }
        html = purify.sanitize(html, {
            ALLOWED_TAGS: [
                'br', 'hr', 'p', 'div', 'span',
                'strong', 'b', 'em', 'i', 'u', 's', 'del',
                'code', 'pre', 'blockquote',
                'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
                'ul', 'ol', 'li',
                'table', 'thead', 'tbody', 'tr', 'th', 'td',
                'img', 'button',
                // KaTeX elements
                'math', 'semantics', 'mrow', 'mi', 'mo', 'mn', 'msup',
                'msub', 'mfrac', 'mover', 'munder', 'msqrt', 'mtext',
                'annotation',
            ],
            ALLOWED_ATTR: [
                'class', 'style', 'src', 'alt',
                'title', 'colspan', 'rowspan',
                // KaTeX attributes
                'mathvariant', 'encoding', 'xmlns', 'display',
                'aria-hidden', 'focusable', 'role',
                'width', 'height', 'viewBox', 'fill', 'stroke',
                'stroke-width', 'stroke-linecap', 'stroke-linejoin', 'd',
            ],
            ADD_ATTR: ['data-img-idx', 'data-code-copy'],
            ALLOW_DATA_ATTR: false,
            ALLOWED_URI_REGEXP: /^(?:(?:https?|data):)/i,
            ADD_DATA_URI_TAGS: ['img'],
        });

        return html;
    }

    updateChatHeader(): void {
        if (!this.currentConversation) return;

        const titleEl = document.getElementById('chat-title');
        const avatarEl = document.getElementById('chat-role-avatar') as HTMLImageElement | null;
        const nameEl = document.getElementById('chat-role-name');
        const thinkingToggle = document.getElementById('thinking-toggle') as HTMLInputElement | null;

        if (titleEl) titleEl.textContent = this.currentConversation.title || 'New Conversation';
        if (avatarEl) {
            // Validate before assigning to .src — same defense-in-depth as renderMessages().
            // localStorage can be tampered with, so never trust avatar URLs blindly.
            // Use isSafeAvatarUrl + raw value (NOT safeAvatarUrl, which HTML-escapes for innerHTML).
            if (isSafeAvatarUrl(settings.aiAvatar)) {
                avatarEl.src = settings.aiAvatar;
                avatarEl.style.display = '';
            } else {
                avatarEl.removeAttribute('src');
                avatarEl.style.display = 'none';
            }
        }
        if (nameEl) nameEl.textContent = this.currentConversation.role_name || 'AI';
        if (thinkingToggle) thinkingToggle.checked = this.currentConversation.thinking_enabled || false;

        // Restore AI provider dropdown to match this conversation
        const providerSelect = document.getElementById('chat-ai-provider') as HTMLSelectElement | null;
        if (providerSelect) {
            providerSelect.value = this.aiProvider;
        }

        // Restore Unrestricted toggle from saved preference
        const unrestrictedToggle = document.getElementById('chat-unrestricted') as HTMLInputElement | null;
        if (unrestrictedToggle) {
            unrestrictedToggle.checked = localStorage.getItem('dashboard_unrestricted') === 'true';
        }

        // Render conversation tags below the header.
        this.renderConversationTags();

        this.updateStarButton();
    }

    /** Render the tag chips + "add tag" input strip under the chat header. */
    renderConversationTags(): void {
        const host = document.getElementById('chat-tags');
        if (!host || !this.currentConversation) return;

        const tags = (this.currentConversation as unknown as Record<string, unknown>).tags as string[] | undefined ?? [];
        const chips = tags.map(t =>
            `<span class="tag-chip" data-tag="${escapeHtml(t)}">#${escapeHtml(t)}<button class="tag-remove" data-tag="${escapeHtml(t)}" aria-label="Remove tag ${escapeHtml(t)}">&times;</button></span>`
        ).join('');
        host.innerHTML =
            chips +
            `<input type="text" class="tag-add-input" id="chat-tag-add" placeholder="+ tag" aria-label="Add tag" maxlength="64">`;

        // Wire remove buttons.
        host.querySelectorAll<HTMLElement>('.tag-remove').forEach(btn => {
            btn.addEventListener('click', () => {
                const tag = btn.dataset.tag;
                if (tag && this.currentConversation) {
                    this.send({ type: 'remove_tag', conversation_id: this.currentConversation.id, tag });
                }
            });
        });

        // Wire add input — Enter commits, Esc cancels.
        const input = document.getElementById('chat-tag-add') as HTMLInputElement | null;
        if (input) {
            input.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    const tag = input.value.trim().toLowerCase();
                    if (tag && this.currentConversation) {
                        this.send({ type: 'add_tag', conversation_id: this.currentConversation.id, tag });
                        input.value = '';
                    }
                } else if (e.key === 'Escape') {
                    input.value = '';
                    input.blur();
                }
            });
        }
    }

    updateStarButton(): void {
        const btn = document.getElementById('btn-star-chat');
        if (btn && this.currentConversation) {
            btn.textContent = this.currentConversation.is_starred ? '\u2B50' : '\u2606';
        }
    }

    updateContextWindowIndicator(usage: {
        input_tokens: number;
        output_tokens: number;
        total_tokens: number;
        context_window: number;
    }): void {
        const indicator = document.getElementById('context-window-indicator');
        const fill = document.getElementById('context-bar-fill');
        const label = document.getElementById('context-bar-label');
        if (!indicator || !fill || !label) return;

        const { input_tokens, output_tokens, context_window } = usage;
        if (!context_window || context_window <= 0) return;

        // Cache per conversation for persistence
        if (this.currentConversation?.id) {
            this.tokenUsageCache.set(this.currentConversation.id, usage);
            this.saveTokenUsageCache();
        }

        const total = input_tokens + output_tokens;
        const pct = Math.min((total / context_window) * 100, 100);

        indicator.style.display = 'flex';
        fill.style.width = `${pct}%`;
        fill.classList.remove('usage-moderate', 'usage-high');
        if (pct >= 80) {
            fill.classList.add('usage-high');
        } else if (pct >= 50) {
            fill.classList.add('usage-moderate');
        }

        // Format token counts for readability
        const fmt = (n: number): string => n >= 1000 ? `${(n / 1000).toFixed(1)}K` : String(n);
        label.textContent = `${fmt(total)} / ${fmt(context_window)} (${pct.toFixed(1)}%)`;
        indicator.title = `Context Window: ${input_tokens.toLocaleString()} input + ${output_tokens.toLocaleString()} output = ${total.toLocaleString()} / ${context_window.toLocaleString()} tokens`;
    }

    resetContextWindowIndicator(): void {
        const indicator = document.getElementById('context-window-indicator');
        if (indicator) indicator.style.display = 'none';
    }

    restoreContextWindowIndicator(conversationId: string): void {
        const cached = this.tokenUsageCache.get(conversationId);
        if (cached) {
            this.updateContextWindowIndicator(cached);
        } else {
            this.resetContextWindowIndicator();
        }
    }

    private saveTokenUsageCache(): void {
        const obj: Record<string, { input_tokens: number; output_tokens: number; total_tokens: number; context_window: number }> = {};
        // Evict oldest entries if cache exceeds 200 conversations
        const MAX_TOKEN_CACHE_SIZE = 200;
        const entries = Array.from(this.tokenUsageCache.entries());
        const toSave = entries.length > MAX_TOKEN_CACHE_SIZE
            ? entries.slice(entries.length - MAX_TOKEN_CACHE_SIZE)
            : entries;
        for (const [k, v] of toSave) { obj[k] = v; }
        localStorage.setItem('dashboard_token_usage', JSON.stringify(obj));
    }

    private loadTokenUsageCache(): void {
        try {
            const raw = localStorage.getItem('dashboard_token_usage');
            if (raw) {
                const obj = JSON.parse(raw) as Record<string, { input_tokens: number; output_tokens: number; total_tokens: number; context_window: number }>;
                this.tokenUsageCache = new Map(Object.entries(obj));
            }
        } catch {
            // Ignore corrupt cache
        }
    }

    showChatContainer(): void {
        const empty = document.getElementById('chat-empty');
        const container = document.getElementById('chat-container');
        if (empty) {
            empty.classList.add('hidden');
            empty.style.setProperty('display', 'none', 'important');
        }
        if (container) {
            container.classList.remove('hidden');
            container.style.setProperty('display', 'flex', 'important');
        }
    }

    hideChatContainer(): void {
        const empty = document.getElementById('chat-empty');
        const container = document.getElementById('chat-container');
        if (empty) {
            empty.classList.remove('hidden');
            empty.style.removeProperty('display');
        }
        if (container) {
            container.classList.add('hidden');
            container.style.setProperty('display', 'none', 'important');
        }
    }

    setInputEnabled(enabled: boolean): void {
        const input = document.getElementById('chat-input') as HTMLTextAreaElement | null;
        const btn = document.getElementById('btn-send') as HTMLButtonElement | null;

        if (input) input.disabled = !enabled;
        if (btn) btn.disabled = !enabled;
    }

    scrollToBottom(force: boolean = false): void {
        if (!force && this.userScrolledUp) return;
        const container = document.getElementById('chat-messages');
        if (container) {
            container.scrollTop = container.scrollHeight;
        }
        // Any explicit scroll-to-bottom resets the "new message" counter.
        this.newMessagesWhileScrolledUp = 0;
        this.updateScrollFab(false);
    }

    /** Count of messages that arrived while the user was scrolled up. */
    newMessagesWhileScrolledUp: number = 0;

    /** Toggle the floating scroll-to-bottom button + optional new-count badge. */
    updateScrollFab(show: boolean): void {
        const fab = document.getElementById('scroll-to-bottom-fab');
        const badge = document.getElementById('scroll-new-count');
        if (!fab) return;
        fab.classList.toggle('hidden', !show);
        if (badge) {
            if (this.newMessagesWhileScrolledUp > 0) {
                badge.textContent = String(this.newMessagesWhileScrolledUp);
                badge.classList.remove('hidden');
            } else {
                badge.classList.add('hidden');
            }
        }
    }

    // ------------------------------------------------------------------
    // In-conversation search (#14) — Ctrl+F overlays a search bar that
    // highlights matches inside the currently-rendered messages and steps
    // through them with ↑/↓.
    // ------------------------------------------------------------------
    private searchMatches: HTMLElement[] = [];
    private searchCurrentIdx: number = -1;

    openChatSearch(): void {
        const bar = document.getElementById('chat-search-bar');
        const input = document.getElementById('chat-search-input') as HTMLInputElement | null;
        if (!bar || !input) return;
        bar.classList.remove('hidden');
        input.focus();
        input.select();
    }

    closeChatSearch(): void {
        const bar = document.getElementById('chat-search-bar');
        if (!bar) return;
        bar.classList.add('hidden');
        this.clearSearchHighlights();
        this.searchMatches = [];
        this.searchCurrentIdx = -1;
    }

    private clearSearchHighlights(): void {
        const container = document.getElementById('chat-messages');
        if (!container) return;
        container.querySelectorAll('mark.chat-search-hit').forEach(mark => {
            const parent = mark.parentNode;
            if (!parent) return;
            // Unwrap <mark> by replacing with its text content.
            parent.replaceChild(document.createTextNode(mark.textContent || ''), mark);
            parent.normalize();
        });
    }

    /** Find all text nodes within a root that contain `query` (case-insensitive). */
    private wrapMatches(root: HTMLElement, query: string): HTMLElement[] {
        if (!query) return [];
        const hits: HTMLElement[] = [];
        const needle = query.toLowerCase();
        // TreeWalker over text nodes, skipping <script>/<style>/<mark> and hidden nodes.
        const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
            acceptNode: (node: Node) => {
                const parent = node.parentElement;
                if (!parent) return NodeFilter.FILTER_REJECT;
                const tag = parent.tagName;
                if (tag === 'SCRIPT' || tag === 'STYLE' || tag === 'MARK') return NodeFilter.FILTER_REJECT;
                if (!node.nodeValue || !node.nodeValue.toLowerCase().includes(needle)) return NodeFilter.FILTER_SKIP;
                return NodeFilter.FILTER_ACCEPT;
            },
        });

        const candidates: Text[] = [];
        // Collect first so we can mutate the DOM without breaking iteration.
        let n: Node | null = walker.nextNode();
        while (n) {
            candidates.push(n as Text);
            n = walker.nextNode();
        }

        for (const textNode of candidates) {
            const text = textNode.nodeValue || '';
            const lower = text.toLowerCase();
            let idx = 0;
            let start = lower.indexOf(needle, idx);
            if (start < 0) continue;
            const fragment = document.createDocumentFragment();
            while (start >= 0) {
                if (start > idx) {
                    fragment.appendChild(document.createTextNode(text.slice(idx, start)));
                }
                const mark = document.createElement('mark');
                mark.className = 'chat-search-hit';
                mark.textContent = text.slice(start, start + query.length);
                fragment.appendChild(mark);
                hits.push(mark);
                idx = start + query.length;
                start = lower.indexOf(needle, idx);
            }
            if (idx < text.length) {
                fragment.appendChild(document.createTextNode(text.slice(idx)));
            }
            textNode.replaceWith(fragment);
        }
        return hits;
    }

    performChatSearch(query: string): void {
        this.clearSearchHighlights();
        this.searchMatches = [];
        this.searchCurrentIdx = -1;
        const container = document.getElementById('chat-messages');
        const countEl = document.getElementById('chat-search-count');
        if (!container) return;

        if (query) {
            this.searchMatches = this.wrapMatches(container, query);
            if (this.searchMatches.length > 0) {
                this.focusSearchMatch(0);
            }
        }
        if (countEl) {
            countEl.textContent = `${this.searchMatches.length ? this.searchCurrentIdx + 1 : 0} / ${this.searchMatches.length}`;
        }
    }

    private focusSearchMatch(idx: number): void {
        if (this.searchMatches.length === 0) return;
        idx = ((idx % this.searchMatches.length) + this.searchMatches.length) % this.searchMatches.length;
        this.searchMatches.forEach(m => m.classList.remove('active'));
        const target = this.searchMatches[idx];
        target.classList.add('active');
        target.scrollIntoView({ block: 'center', behavior: 'smooth' });
        this.searchCurrentIdx = idx;
        const countEl = document.getElementById('chat-search-count');
        if (countEl) countEl.textContent = `${idx + 1} / ${this.searchMatches.length}`;
    }

    stepChatSearch(direction: 1 | -1): void {
        if (this.searchMatches.length === 0) return;
        this.focusSearchMatch(this.searchCurrentIdx + direction);
    }

    private setupChatSearchHandlers(): void {
        const input = document.getElementById('chat-search-input') as HTMLInputElement | null;
        const bar = document.getElementById('chat-search-bar');
        if (!input || !bar || bar.dataset.searchBound) return;

        let debounce: number | null = null;
        input.addEventListener('input', () => {
            if (debounce !== null) clearTimeout(debounce);
            debounce = window.setTimeout(() => {
                this.performChatSearch(input.value);
                debounce = null;
            }, 120);
        });
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                this.stepChatSearch(e.shiftKey ? -1 : 1);
            } else if (e.key === 'Escape') {
                e.preventDefault();
                this.closeChatSearch();
            }
        });
        document.getElementById('chat-search-next')?.addEventListener('click', () => this.stepChatSearch(1));
        document.getElementById('chat-search-prev')?.addEventListener('click', () => this.stepChatSearch(-1));
        document.getElementById('chat-search-close')?.addEventListener('click', () => this.closeChatSearch());
        bar.dataset.searchBound = '1';
    }

    setupScrollListener(): void {
        // Piggy-back: also bind the chat search handlers once, since both are
        // wired up after the chat DOM is available.
        this.setupChatSearchHandlers();

        const container = document.getElementById('chat-messages');
        if (!container) return;

        const FAB_THRESHOLD = 200;   // px from bottom to show FAB
        const AUTO_SCROLL_THRESHOLD = 150; // px from bottom to keep auto-scroll

        container.addEventListener('scroll', () => {
            const distanceFromBottom = container.scrollHeight - container.scrollTop - container.clientHeight;
            // Track whether auto-scroll should pause during streaming
            if (this.isStreaming) {
                this.userScrolledUp = distanceFromBottom > AUTO_SCROLL_THRESHOLD;
            }
            // FAB visibility is independent of streaming
            const shouldShow = distanceFromBottom > FAB_THRESHOLD;
            if (!shouldShow) {
                this.newMessagesWhileScrolledUp = 0;
            }
            this.updateScrollFab(shouldShow);
        });

        // Click FAB → smooth scroll to bottom
        const fab = document.getElementById('scroll-to-bottom-fab');
        if (fab && !fab.dataset.fabBound) {
            fab.addEventListener('click', () => {
                container.scrollTo({ top: container.scrollHeight, behavior: 'smooth' });
                this.newMessagesWhileScrolledUp = 0;
                this.updateScrollFab(false);
            });
            fab.dataset.fabBound = '1';
        }
    }

    formatTime(dateStr: string): string {
        try {
            // JavaScript's Date constructor treats strings without Z suffix as local time,
            // which is the desired behavior for our stored timestamps
            const date = new Date(dateStr);
            
            const now = new Date();
            const isToday = date.toDateString() === now.toDateString();
            
            const timeStr = date.toLocaleTimeString('th-TH', { 
                hour: '2-digit', 
                minute: '2-digit',
                hour12: false
            });
            
            if (isToday) {
                return timeStr;
            } else {
                const dateFormatted = date.toLocaleDateString('th-TH', { 
                    day: 'numeric', 
                    month: 'short' 
                });
                return `${dateFormatted} ${timeStr}`;
            }
        } catch {
            return '';
        }
    }

    autoResizeInput(): void {
        const input = document.getElementById('chat-input') as HTMLTextAreaElement | null;
        if (input) {
            input.style.height = 'auto';
            input.style.height = Math.min(input.scrollHeight, 150) + 'px';
        }
    }

    // Image attachment methods
    private static readonly MAX_IMAGE_SIZE = 20 * 1024 * 1024; // 20MB
    private static readonly MAX_ATTACHED_IMAGES = 5;

    // Virtualization thresholds for renderMessages (#16).
    // Below THRESHOLD we render every message; above it we keep only the tail
    // WINDOW_SIZE in the DOM and put a "show earlier" button at the top.
    private static readonly VIRT_THRESHOLD = 150;
    private static readonly VIRT_WINDOW_SIZE = 100;
    private visibleMessageCount: number = 0;  // initialized on first render

    attachImage(file: File): void {
        if (file.size > ChatManager.MAX_IMAGE_SIZE) {
            showToast(`Image too large (${(file.size / 1024 / 1024).toFixed(1)}MB). Maximum is 20MB.`, { type: 'warning' });
            return;
        }
        if (this.attachedImages.length >= ChatManager.MAX_ATTACHED_IMAGES) {
            showToast(`Maximum ${ChatManager.MAX_ATTACHED_IMAGES} images allowed.`, { type: 'warning' });
            return;
        }
        const reader = new FileReader();
        reader.onload = (e) => {
            const base64 = e.target?.result as string;
            if (base64) {
                // Store full base64 data URL
                this.attachedImages.push(base64);
                this.renderAttachedImages();
            }
        };
        reader.readAsDataURL(file);
    }

    removeImage(index: number): void {
        this.attachedImages.splice(index, 1);
        this.renderAttachedImages();
    }

    renderAttachedImages(): void {
        const container = document.getElementById('attached-images');
        if (!container) return;

        if (this.attachedImages.length === 0) {
            container.innerHTML = '';
            return;
        }

        container.innerHTML = this.attachedImages.map((img, idx) => `
            <div class="attached-image-preview">
                <img src="${escapeHtml(img)}" alt="Attached ${idx + 1}">
                <button class="remove-image" data-idx="${idx}">&times;</button>
            </div>
        `).join('');

        // Add click handlers for remove buttons
        container.querySelectorAll('.remove-image').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const idx = parseInt((e.target as HTMLElement).dataset.idx || '0');
                this.removeImage(idx);
            });
        });
    }

    setupImageUpload(): void {
        const attachBtn = document.getElementById('btn-attach');
        const fileInput = document.getElementById('image-input') as HTMLInputElement | null;

        attachBtn?.addEventListener('click', () => {
            fileInput?.click();
        });

        fileInput?.addEventListener('change', () => {
            const files = fileInput.files;
            if (files) {
                Array.from(files).forEach(file => {
                    if (file.type.startsWith('image/')) {
                        this.attachImage(file);
                    }
                });
            }
            // Reset input so same file can be selected again
            fileInput.value = '';
        });

        // Drag-and-drop: accept image files anywhere over the chat input area
        // or the messages area. We intentionally do not accept drops on the
        // whole window so links being dragged to the address bar still work.
        const dropZones = [
            document.getElementById('chat-messages'),
            document.querySelector('.chat-input-area'),
        ].filter((el): el is HTMLElement => el instanceof HTMLElement);

        const showDropState = (active: boolean): void => {
            dropZones.forEach(z => z.classList.toggle('drop-active', active));
        };

        dropZones.forEach(zone => {
            zone.addEventListener('dragenter', (e) => {
                if (!e.dataTransfer) return;
                if (Array.from(e.dataTransfer.items).some(i => i.kind === 'file')) {
                    e.preventDefault();
                    showDropState(true);
                }
            });
            zone.addEventListener('dragover', (e) => {
                // Needed so drop fires
                if (e.dataTransfer && Array.from(e.dataTransfer.items).some(i => i.kind === 'file')) {
                    e.preventDefault();
                    e.dataTransfer.dropEffect = 'copy';
                }
            });
            zone.addEventListener('dragleave', (e) => {
                // Only clear state when leaving the zone entirely (not its children).
                if (e.target === zone) showDropState(false);
            });
            zone.addEventListener('drop', (e) => {
                if (!e.dataTransfer) return;
                e.preventDefault();
                showDropState(false);
                const files = Array.from(e.dataTransfer.files).filter(f => f.type.startsWith('image/'));
                if (files.length === 0) {
                    showToast('Only image files can be attached', { type: 'warning' });
                    return;
                }
                files.forEach(f => this.attachImage(f));
            });
        });

        // Paste support: Ctrl+V an image from clipboard into the chat input
        document.getElementById('chat-input')?.addEventListener('paste', (e) => {
            const items = (e as ClipboardEvent).clipboardData?.items;
            if (!items) return;
            for (const item of Array.from(items)) {
                if (item.kind === 'file' && item.type.startsWith('image/')) {
                    const file = item.getAsFile();
                    if (file) {
                        e.preventDefault();
                        this.attachImage(file);
                    }
                }
            }
        });
    }

    // ========================================================================
    // Message Edit / Delete
    // ========================================================================

    startAiEditMessage(msgIdx: number): void {
        if (this.isStreaming) return;
        const msg = this.messages[msgIdx];
        if (!msg || msg.role !== 'assistant' || !msg.id) return;

        const container = document.getElementById('chat-messages');
        if (!container) return;
        const msgElements = container.querySelectorAll('.chat-message');
        const msgEl = msgElements[msgIdx];
        if (!msgEl) return;

        const contentEl = msgEl.querySelector('.message-content');
        const actionsEl = msgEl.querySelector('.message-actions');
        if (!contentEl) return;

        // Insert AI edit instruction input below the message content
        const editBar = document.createElement('div');
        editBar.className = 'ai-edit-bar';
        editBar.innerHTML = `
            <div class="ai-edit-label">\u2728 Tell AI how to edit this message:</div>
            <div class="ai-edit-input-row">
                <textarea class="ai-edit-input" rows="1" placeholder="e.g. Make it shorter, Add examples, Translate to English..."></textarea>
                <button class="ai-edit-submit-btn">Send</button>
                <button class="ai-edit-cancel-btn">Cancel</button>
            </div>
        `;

        // Hide action buttons and append bar after content
        if (actionsEl) (actionsEl as HTMLElement).style.display = 'none';
        contentEl.after(editBar);

        const inputEl = editBar.querySelector('.ai-edit-input') as HTMLTextAreaElement;
        inputEl?.focus();

        const submitEdit = () => {
            const instruction = inputEl?.value?.trim();
            if (!instruction) {
                showToast('Please enter an instruction', { type: 'warning' });
                return;
            }
            editBar.remove();
            if (actionsEl) (actionsEl as HTMLElement).style.display = '';

            const thinkingToggle = document.getElementById('thinking-toggle') as HTMLInputElement | null;
            const userName = settings.userName || 'User';

            this.send({
                type: 'ai_edit_message',
                conversation_id: this.currentConversation?.id,
                target_message_id: msg.id,
                instruction,
                role_preset: this.currentConversation?.role_preset || 'general',
                thinking_enabled: thinkingToggle?.checked || false,
                user_name: userName,
                ai_provider: this.aiProvider,
            });
        };

        editBar.querySelector('.ai-edit-submit-btn')?.addEventListener('click', submitEdit);
        editBar.querySelector('.ai-edit-cancel-btn')?.addEventListener('click', () => {
            editBar.remove();
            if (actionsEl) (actionsEl as HTMLElement).style.display = '';
        });
        inputEl?.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                submitEdit();
            }
            if (e.key === 'Escape') {
                editBar.remove();
                if (actionsEl) (actionsEl as HTMLElement).style.display = '';
            }
        });

        // Auto-resize textarea
        inputEl?.addEventListener('input', () => {
            if (inputEl) {
                inputEl.style.height = 'auto';
                inputEl.style.height = Math.min(inputEl.scrollHeight, 120) + 'px';
            }
        });
    }

    startEditMessage(msgIdx: number): void {
        if (this.isStreaming) return;
        const msg = this.messages[msgIdx];
        if (!msg) return;

        // Find the message element in DOM
        const container = document.getElementById('chat-messages');
        if (!container) return;
        const msgElements = container.querySelectorAll('.chat-message');
        const msgEl = msgElements[msgIdx];
        if (!msgEl) return;

        const contentEl = msgEl.querySelector('.message-content');
        const actionsEl = msgEl.querySelector('.message-actions');
        if (!contentEl) return;

        // Replace content with textarea
        const originalContent = msg.content;
        contentEl.innerHTML = `
            <textarea class="edit-textarea">${escapeHtml(originalContent)}</textarea>
            <div class="edit-actions">
                <button class="edit-save-btn">Save</button>
                <button class="edit-save-regen-btn" style="${msg.role === 'user' ? '' : 'display:none'}">Save &amp; Regenerate</button>
                <button class="edit-cancel-btn">Cancel</button>
            </div>
        `;
        if (actionsEl) (actionsEl as HTMLElement).style.display = 'none';

        const textarea = contentEl.querySelector('.edit-textarea') as HTMLTextAreaElement;
        if (textarea) {
            textarea.focus();
            textarea.setSelectionRange(textarea.value.length, textarea.value.length);
            // Auto-resize
            textarea.style.height = Math.min(textarea.scrollHeight, 300) + 'px';
        }

        // Save button (edit only, no regenerate)
        contentEl.querySelector('.edit-save-btn')?.addEventListener('click', () => {
            const newContent = (contentEl.querySelector('.edit-textarea') as HTMLTextAreaElement)?.value?.trim();
            if (newContent && newContent !== originalContent) {
                this.saveEdit(msgIdx, newContent, false);
            } else {
                this.cancelEdit(msgIdx, originalContent);
            }
        });

        // Save & Regenerate button (edit + regenerate AI response)
        contentEl.querySelector('.edit-save-regen-btn')?.addEventListener('click', () => {
            const newContent = (contentEl.querySelector('.edit-textarea') as HTMLTextAreaElement)?.value?.trim();
            if (newContent) {
                this.saveEdit(msgIdx, newContent, true);
            }
        });

        // Cancel button
        contentEl.querySelector('.edit-cancel-btn')?.addEventListener('click', () => {
            this.cancelEdit(msgIdx, originalContent);
        });

        // Escape key to cancel
        textarea?.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                this.cancelEdit(msgIdx, originalContent);
            }
        });
    }

    saveEdit(msgIdx: number, newContent: string, regenerate: boolean): void {
        const msg = this.messages[msgIdx];
        if (!msg) return;

        this.send({
            type: 'edit_message',
            message_id: msg.id,
            content: newContent,
            conversation_id: this.currentConversation?.id,
            regenerate,
        });
    }

    cancelEdit(msgIdx: number, originalContent: string): void {
        // Re-render the single message back to normal
        const container = document.getElementById('chat-messages');
        if (!container) return;
        const msgElements = container.querySelectorAll('.chat-message');
        const msgEl = msgElements[msgIdx];
        if (!msgEl) return;

        const contentEl = msgEl.querySelector('.message-content');
        const actionsEl = msgEl.querySelector('.message-actions');
        if (contentEl) contentEl.innerHTML = this.formatMessage(this.stripThinkTags(originalContent));
        if (actionsEl) (actionsEl as HTMLElement).style.display = '';
    }

    deleteMessage(msgIdx: number): void {
        if (this.isStreaming) return;
        const msg = this.messages[msgIdx];
        if (!msg || msg.id == null) return;

        const isUser = msg.role === 'user';
        // For user messages, also delete the paired AI response (next message)
        let pairId: number | undefined;
        let deletePair = false;
        if (isUser && msgIdx + 1 < this.messages.length) {
            const nextMsg = this.messages[msgIdx + 1];
            if (nextMsg.role === 'assistant' && nextMsg.id != null) {
                pairId = nextMsg.id;
                deletePair = true;
            }
        }
        // For AI messages, also delete the paired user message (previous message)
        if (!isUser && msgIdx - 1 >= 0) {
            const prevMsg = this.messages[msgIdx - 1];
            if (prevMsg.role === 'user' && prevMsg.id != null) {
                pairId = prevMsg.id;
                deletePair = true;
            }
        }

        this.send({
            type: 'delete_message',
            message_id: msg.id,
            delete_pair: deletePair,
            pair_message_id: pairId,
        });
    }

    regenerateAfterEdit(editedMsg: ChatMessage): void {
        if (!this.currentConversation) return;

        // Build history from messages before the edited message
        // Strip unnecessary fields (images/thinking/mode) to reduce payload size
        const editedIdx = this.messages.indexOf(editedMsg);
        const historyToSend = this.messages.slice(0, editedIdx).map(m => ({
            role: m.role,
            content: m.content,
        }));

        const thinkingToggle = document.getElementById('thinking-toggle') as HTMLInputElement | null;
        const searchToggle = document.getElementById('chat-use-search') as HTMLInputElement | null;
        const unrestrictedToggle = document.getElementById('chat-unrestricted') as HTMLInputElement | null;
        const userName = settings.userName || 'User';

        this.send({
            type: 'message',
            conversation_id: this.currentConversation.id,
            content: editedMsg.content,
            role_preset: this.currentConversation.role_preset,
            thinking_enabled: thinkingToggle?.checked || false,
            history: historyToSend,
            use_search: searchToggle?.checked ?? true,
            unrestricted_mode: unrestrictedToggle?.checked || false,
            images: [],
            user_name: userName,
            ai_provider: this.aiProvider,
            is_regeneration: true,  // Skip duplicate user message save in backend
        });
    }

    showNewChatModal(): void {
        const modal = document.getElementById('new-chat-modal');
        if (modal) {
            modal.classList.add('active');
            this.selectedRole = 'general';
            // Restore saved preferences for new chat
            const savedThinking = localStorage.getItem('dashboard_thinking') === 'true';
            this.thinkingEnabled = savedThinking;
            const modalThinking = document.getElementById('modal-thinking') as HTMLInputElement | null;
            if (modalThinking) modalThinking.checked = savedThinking;
            // Restore saved provider preference from localStorage
            // (this.aiProvider may have been overridden by loading a different conversation)
            const savedProvider = localStorage.getItem('dashboard_ai_provider');
            const modalProvider = document.getElementById('modal-ai-provider') as HTMLSelectElement | null;
            if (modalProvider) {
                modalProvider.value = (savedProvider && this.availableProviders.includes(savedProvider))
                    ? savedProvider
                    : this.aiProvider;
            }
            this.updateRoleSelection();
        }
    }

    closeModal(): void {
        const modal = document.getElementById('new-chat-modal');
        if (modal) modal.classList.remove('active');
    }

    selectRole(role: string): void {
        this.selectedRole = role;
        this.updateRoleSelection();
    }

    updateRoleSelection(): void {
        document.querySelectorAll('.role-card').forEach(card => {
            card.classList.toggle('selected', (card as HTMLElement).dataset.role === this.selectedRole);
        });
    }

    updateProviderSelects(): void {
        // Update both the modal and inline header select elements
        const selects = [
            document.getElementById('modal-ai-provider') as HTMLSelectElement | null,
            document.getElementById('chat-ai-provider') as HTMLSelectElement | null,
        ];
        for (const select of selects) {
            if (!select) continue;
            select.innerHTML = '';
            for (const provider of this.availableProviders) {
                const option = document.createElement('option');
                option.value = provider;
                option.textContent = provider === 'gemini' ? '✨ Gemini' : '🟣 Claude';
                select.appendChild(option);
            }
            select.value = this.aiProvider;
        }
    }

    downloadExport(data: { id: string; format: string; data: string }): void {
        const filename = `chat_${data.id.slice(0, 8)}_${Date.now()}.${data.format}`;
        const content = data.data;
        const blob = new Blob([content], { type: data.format === 'json' ? 'application/json' : 'text/markdown' });

        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        a.click();
        URL.revokeObjectURL(url);

        showToast('Conversation exported!', { type: 'success' });
    }

    init(): void {
        this.connect();

        document.getElementById('btn-new-chat')?.addEventListener('click', () => this.showNewChatModal());
        document.getElementById('btn-new-chat-main')?.addEventListener('click', () => this.showNewChatModal());
        document.getElementById('modal-close')?.addEventListener('click', () => this.closeModal());
        document.getElementById('modal-cancel')?.addEventListener('click', () => this.closeModal());
        document.getElementById('modal-create')?.addEventListener('click', () => this.createConversation());

        document.getElementById('new-chat-modal')?.querySelector('.modal-overlay')
            ?.addEventListener('click', () => this.closeModal());

        document.querySelectorAll('.role-card').forEach(card => {
            card.addEventListener('click', () => this.selectRole((card as HTMLElement).dataset.role || 'general'));
        });

        document.getElementById('modal-thinking')?.addEventListener('change', (e) => {
            this.thinkingEnabled = (e.target as HTMLInputElement).checked;
            localStorage.setItem('dashboard_thinking', String(this.thinkingEnabled));
        });

        // AI provider selector in chat header
        document.getElementById('chat-ai-provider')?.addEventListener('change', (e) => {
            this.aiProvider = (e.target as HTMLSelectElement).value;
            localStorage.setItem('dashboard_ai_provider', this.aiProvider);
            if (this.currentConversation) {
                this.send({
                    type: 'update_provider',
                    conversation_id: this.currentConversation.id,
                    ai_provider: this.aiProvider,
                });
            }
        });

        // Unrestricted mode toggle - persist preference
        document.getElementById('chat-unrestricted')?.addEventListener('change', (e) => {
            localStorage.setItem('dashboard_unrestricted', String((e.target as HTMLInputElement).checked));
        });

        document.getElementById('btn-send')?.addEventListener('click', () => this.sendMessage());
        document.getElementById('thinking-toggle')?.addEventListener('change', (e) => {
            if (this.currentConversation) {
                this.currentConversation.thinking_enabled = (e.target as HTMLInputElement).checked;
                localStorage.setItem('dashboard_thinking', String((e.target as HTMLInputElement).checked));
                // Optional: send to backend to persist
            }
        });

        
        // Setup image upload
        this.setupImageUpload();

        // Setup scroll listener for smart auto-scroll during streaming
        this.setupScrollListener();

        document.getElementById('btn-star-chat')?.addEventListener('click', () => {
            if (this.currentConversation) {
                this.starConversation(this.currentConversation.id, !this.currentConversation.is_starred);
            }
        });
        document.getElementById('btn-export-chat')?.addEventListener('click', async () => {
            if (!this.currentConversation) return;
            const format = await this.promptExportFormat();
            if (format) this.exportConversation(this.currentConversation.id, format);
        });
        document.getElementById('btn-export-all')?.addEventListener('click', async () => {
            if (this.conversations.length === 0) {
                showToast('No conversations to export', { type: 'warning' });
                return;
            }
            const format = await this.promptExportFormat();
            if (!format) return;
            this.conversations.forEach(conv => {
                this.exportConversation(conv.id, format);
            });
        });
        document.getElementById('btn-delete-chat')?.addEventListener('click', () => {
            if (this.currentConversation) {
                this.deleteConversation(this.currentConversation.id);
            }
        });

        // Delete confirmation modal handlers
        document.getElementById('delete-confirm')?.addEventListener('click', () => this.confirmDelete());
        document.getElementById('delete-cancel')?.addEventListener('click', () => this.closeDeleteModal());
        document.getElementById('delete-confirm-modal')?.querySelector('.modal-overlay')
            ?.addEventListener('click', () => this.closeDeleteModal());

        // Rename modal handlers
        document.getElementById('btn-rename-chat')?.addEventListener('click', () => {
            if (this.currentConversation) {
                this.renameConversation(this.currentConversation.id);
            }
        });
        document.getElementById('rename-confirm')?.addEventListener('click', () => this.confirmRename());
        document.getElementById('rename-cancel')?.addEventListener('click', () => this.closeRenameModal());
        document.getElementById('rename-modal')?.querySelector('.modal-overlay')
            ?.addEventListener('click', () => this.closeRenameModal());
        document.getElementById('rename-input')?.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                this.confirmRename();
            } else if (e.key === 'Escape') {
                this.closeRenameModal();
            }
        });

        const input = document.getElementById('chat-input');
        input?.addEventListener('input', () => {
            this.autoResizeInput();
            // Debounce draft save per conversation
            if (this.currentConversation) {
                if (this.draftSaveTimer !== null) clearTimeout(this.draftSaveTimer);
                this.draftSaveTimer = window.setTimeout(() => {
                    const el = document.getElementById('chat-input') as HTMLTextAreaElement | null;
                    if (this.currentConversation && el) {
                        this.saveDraft(this.currentConversation.id, el.value);
                    }
                    this.draftSaveTimer = null;
                }, 400);
            }
        });
        input?.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                // Enter = send, Shift+Enter = new line
                e.preventDefault();
                this.sendMessage();
            }
        });

        // Store ping interval for cleanup
        this.pingInterval = window.setInterval(() => {
            if (this.connected) {
                if (this.pongPending) {
                    this.missedPongs++;
                    if (this.missedPongs >= 2) {
                        // Server unresponsive — force reconnect
                        console.warn('🔌 Server unresponsive (missed pongs), forcing reconnect');
                        errorLogger.log('WEBSOCKET_STALE', `Server missed ${this.missedPongs} pongs, forcing reconnect`);
                        this.missedPongs = 0;
                        this.pongPending = false;
                        if (this.ws) {
                            this.ws.close();
                        }
                        return;
                    }
                }
                this.pongPending = true;
                this.send({ type: 'ping' });
            }
        }, 30000);
    }
}

// ============================================================================
// Module-level instances
// ============================================================================

export let chatManager: ChatManager | null = null;

export function initChatManager(): void {
    chatManager = new ChatManager();
    chatManager.init();
    window.chatManager = chatManager;
}

export function initMemoryManager(): void {
    memoryManager.setupEventListeners();
}
