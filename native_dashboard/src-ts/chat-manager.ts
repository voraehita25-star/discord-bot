/**
 * AI Chat Manager - WebSocket Client & Memory Manager
 * Extracted from app.ts for modularity.
 */

import {
    invoke,
    errorLogger,
    escapeHtml,
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
}

export interface ChatMessage {
    id?: number;
    role: 'user' | 'assistant';
    content: string;
    created_at: string;
    images?: string[];  // Base64 encoded images
    thinking?: string;  // AI thought process
    mode?: string;      // Mode used (Thinking, Unrestricted, etc.)
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
            
            if (content) {
                this.saveMemory(content, category);
            } else {
                showToast('Please enter memory content', { type: 'warning' });
            }
        });
    }
}

export const memoryManager = new MemoryManager();

// ============================================================================
// Chat Manager
// ============================================================================

export class ChatManager {
    ws: WebSocket | null = null;
    connected: boolean = false;
    currentConversation: ChatConversation | null = null;
    conversations: ChatConversation[] = [];
    messages: ChatMessage[] = [];
    selectedRole: string = 'general';
    thinkingEnabled: boolean = false;
    isStreaming: boolean = false;
    reconnectAttempts: number = 0;
    maxReconnectAttempts: number = 5;
    presets: Record<string, RolePreset> = {};
    pendingDeleteId: string | null = null;
    pendingRenameId: string | null = null;
    attachedImages: string[] = [];  // Base64 encoded images
    currentMode: string = '';  // Store current mode for the streaming message
    private pingInterval: number | null = null;  // Track ping interval for cleanup
    private reconnectTimeout: number | null = null;  // Track reconnect timeout

    private wsToken: string | null = null;

    connect(): void {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            return;
        }

        try {
            // Get WS token from Rust backend for post-connect authentication
            invoke<string>('get_ws_token').then(token => {
                this.wsToken = token || null;
                // Connect WITHOUT token in URL to avoid leaking via logs/proxies
                this._connectWithUrl('ws://127.0.0.1:8765/ws');
            }).catch(() => {
                this.wsToken = null;
                this._connectWithUrl('ws://127.0.0.1:8765/ws');
            });
        } catch (e) {
            console.error('Failed to create WebSocket:', e);
            errorLogger.log('WEBSOCKET_CREATE_ERROR', 'Failed to create WebSocket', String(e));
            this.scheduleReconnect();
        }
    }

    private _connectWithUrl(wsUrl: string): void {
        try {
            this.ws = new WebSocket(wsUrl);

            this.ws.onopen = () => {
                // Send token as first message for authentication (not in URL)
                if (this.wsToken) {
                    this.ws?.send(JSON.stringify({ type: 'auth', token: this.wsToken }));
                }
                this.connected = true;
                this.reconnectAttempts = 0;
                this.updateConnectionStatus(true);
            };

            this.ws.onclose = () => {
                this.connected = false;
                this.updateConnectionStatus(false);
                this.scheduleReconnect();
            };

            this.ws.onerror = (error) => {
                // Only log first error, not repeated connection failures
                if (this.reconnectAttempts === 0) {
                    console.warn('\uD83D\uDD0C WebSocket connection failed (bot may not be running)');
                }
                this.updateConnectionStatus(false);
            };

            this.ws.onmessage = (event) => {
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
            return;
        }

        this.reconnectAttempts++;
        const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 30000);
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
                this.listConversations();
                break;

            case 'conversations_list':
                this.conversations = (data.conversations as ChatConversation[]) || [];
                this.renderConversationList();
                break;

            case 'conversation_created':
                this.currentConversation = data as unknown as ChatConversation;
                this.messages = [];
                this.showChatContainer();
                this.updateChatHeader();
                this.renderMessages();
                this.listConversations();
                this.closeModal();
                break;

            case 'conversation_loaded':
                this.currentConversation = data.conversation as ChatConversation;
                this.messages = (data.messages as ChatMessage[]) || [];
                this.showChatContainer();
                this.updateChatHeader();
                this.renderMessages();
                break;

            case 'stream_start':
                this.isStreaming = true;
                this.currentMode = data.mode as string || '';  // Store mode for later
                this.appendStreamingMessage(data.mode as string || '');
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
                this.appendChunk(data.content as string);
                break;

            case 'stream_end':
                this.isStreaming = false;
                this.finalizeStreamingMessage(data.full_response as string);
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
                    if (shouldRegenerate && editedMsg) {
                        // Remove all messages after the edited one
                        const editedIdx = this.messages.indexOf(editedMsg);
                        this.messages = this.messages.slice(0, editedIdx + 1);
                        this.renderMessages();
                        // Re-send the edited message to get a new AI response
                        this.regenerateAfterEdit(editedMsg);
                    } else {
                        this.renderMessages();
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
                break;

            case 'pong':
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
        }
    }

    updateConnectionStatus(connected: boolean): void {
        const statusEl = document.getElementById('chat-connection-status');
        if (statusEl) {
            statusEl.className = connected ? 'connected' : 'disconnected';
            statusEl.textContent = connected ? '\uD83D\uDFE2 Connected' : '\uD83D\uDD34 Connecting...';
        }
        // Note: Overlay is now controlled by bot status in updateStatusBadge()
    }

    listConversations(): void {
        this.send({ type: 'list_conversations' });
    }

    createConversation(): void {
        this.send({
            type: 'new_conversation',
            role_preset: this.selectedRole,
            thinking_enabled: this.thinkingEnabled
        });
    }

    loadConversation(id: string): void {
        this.send({ type: 'load_conversation', id });
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

    sendMessage(): void {
        const input = document.getElementById('chat-input') as HTMLTextAreaElement | null;
        const content = input?.value?.trim();

        if (!content || this.isStreaming) return;
        if (!this.currentConversation) {
            showToast('Please start a conversation first', { type: 'warning' });
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
        this.renderMessages();

        if (input) {
            input.value = '';
            this.autoResizeInput();
            input.focus();  // Keep cursor in input
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
            user_name: userName
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
        const avatarHtml = settings.aiAvatar 
            ? `<img src="${escapeHtml(settings.aiAvatar)}" alt="ai" class="user-avatar-img">`
            : (this.currentConversation?.role_emoji || '\uD83E\uDD16');
        
        msgDiv.innerHTML = `
            <div class="message-avatar">${avatarHtml}</div>
            <div class="message-wrapper">
                <div class="message-header">
                    <span class="message-name">${escapeHtml(aiName)}</span>
                    <span class="message-time">${timeStr}</span>
                    ${modeHtml}
                </div>
                <div class="thinking-container" style="display: none;">
                    <div class="thinking-header">\uD83D\uDCAD Thinking...</div>
                    <div class="thinking-content"></div>
                </div>
                <div class="message-content">
                    <span class="streaming-text"></span>
                    <span class="typing-cursor">\u258B</span>
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
                content.innerHTML = this.formatMessage(fullResponse);
            }

            // Add action buttons (copy, edit, delete) at the bottom
            const wrapper = streamingMsg.querySelector('.message-wrapper');
            if (wrapper && !wrapper.querySelector('.message-actions')) {
                const actionsDiv = document.createElement('div');
                actionsDiv.className = 'message-actions';
                const msgIdx = this.messages.length; // Will be pushed below
                actionsDiv.innerHTML = `
                    <button class="copy-message-btn" data-content="${escapeHtml(fullResponse).replace(/"/g, '&quot;')}" title="Copy">\uD83D\uDCCB Copy</button>
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

        this.scrollToBottom();
    }

    renderConversationList(): void {
        const container = document.getElementById('conversation-list');
        if (!container) return;

        if (this.conversations.length === 0) {
            container.innerHTML = `
                <div class="no-conversations">
                    <p>No conversations yet</p>
                    <p>Start a new chat!</p>
                </div>
            `;
            return;
        }

        container.innerHTML = this.conversations.map(conv => {
            const preset = this.presets[conv.role_preset] || {};
            const isActive = this.currentConversation?.id === conv.id;
            const starClass = conv.is_starred ? 'starred' : '';
            const avatarHtml = settings.aiAvatar 
                ? `<img class="conv-avatar" src="${escapeHtml(settings.aiAvatar)}" alt="AI">`
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
        }).join('');
        
        // Use event delegation instead of inline onclick (fixes XSS risk)
        container.querySelectorAll('.conversation-item[data-id]').forEach(item => {
            item.addEventListener('click', () => {
                const id = (item as HTMLElement).dataset.id;
                if (id) this.loadConversation(id);
            });
        });
    }

    renderMessages(): void {
        const container = document.getElementById('chat-messages');
        if (!container) return;

        if (this.messages.length === 0) {
            const emoji = this.currentConversation?.role_emoji || '\uD83E\uDD16';
            const name = this.currentConversation?.role_name || 'AI';
            const welcomeAvatarHtml = settings.aiAvatar 
                ? `<img src="${escapeHtml(settings.aiAvatar)}" alt="AI" class="welcome-avatar">`
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
        const userAvatar = settings.userAvatar;
        const aiAvatar = settings.aiAvatar;
        
        container.innerHTML = this.messages.map(msg => {
            const isUser = msg.role === 'user';
            const displayName = isUser ? userName : aiName;
            const timeStr = this.formatTime(msg.created_at);
            
            // Both user and AI can have custom avatar images
            let avatarHtml: string;
            if (isUser) {
                avatarHtml = userAvatar 
                    ? `<img src="${escapeHtml(userAvatar)}" alt="avatar" class="user-avatar-img">`
                    : '\uD83D\uDC64';
            } else {
                avatarHtml = aiAvatar
                    ? `<img src="${escapeHtml(aiAvatar)}" alt="ai" class="user-avatar-img">`
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
            const copyBtn = `<button class="copy-message-btn" data-content="${escapeHtml(msg.content).replace(/"/g, '&quot;')}" title="Copy">\uD83D\uDCCB Copy</button>`;
            const editBtn = `<button class="edit-message-btn" data-msg-id="${msgId}" data-msg-idx="${this.messages.indexOf(msg)}" title="Edit">\u270F\uFE0F Edit</button>`;
            const deleteBtn = `<button class="delete-message-btn" data-msg-id="${msgId}" data-msg-idx="${this.messages.indexOf(msg)}" data-role="${msg.role}" title="Delete">\uD83D\uDDD1\uFE0F Delete</button>`;
            const actionsHtml = `<div class="message-actions">${copyBtn}${editBtn}${deleteBtn}</div>`;

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
                        <div class="message-content">${this.formatMessage(msg.content)}</div>
                        ${actionsHtml}
                    </div>
                </div>
            `;
        }).join('');

        this.scrollToBottom();
        
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

        // Setup copy button clicks
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

        // Setup edit button clicks
        container.querySelectorAll('.edit-message-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const idx = parseInt((btn as HTMLElement).dataset.msgIdx || '-1');
                if (idx >= 0) this.startEditMessage(idx);
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
        
        // Extract code blocks into placeholders BEFORE converting \n to <br>
        const codeBlocks: string[] = [];
        const codePlaceholder = '\x01CODE_BLOCK_';
        html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (_match, lang, code) => {
            const idx = codeBlocks.length;
            codeBlocks.push(`<pre><code class="language-${lang}">${code}</code></pre>`);
            return `${codePlaceholder}${idx}\x01`;
        });
        html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
        html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
        html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');
        // Blockquotes (> at start of line)
        html = html.replace(/^&gt; (.+)$/gm, '<blockquote>$1</blockquote>');
        // Merge consecutive blockquotes
        html = html.replace(/<\/blockquote>\n?<blockquote>/g, '<br>');
        html = html.replace(/\n/g, '<br>');
        
        // Restore code blocks (newlines preserved inside <pre>)
        html = html.replace(/\x01CODE_BLOCK_(\d+)\x01/g, (_match, idx) => {
            return codeBlocks[parseInt(idx)] || '';
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
        if (avatarEl) avatarEl.src = settings.aiAvatar || '';
        if (nameEl) nameEl.textContent = this.currentConversation.role_name || 'AI';
        if (thinkingToggle) thinkingToggle.checked = this.currentConversation.thinking_enabled || false;

        this.updateStarButton();
    }

    updateStarButton(): void {
        const btn = document.getElementById('btn-star-chat');
        if (btn && this.currentConversation) {
            btn.textContent = this.currentConversation.is_starred ? '\u2B50' : '\u2606';
        }
    }

    showChatContainer(): void {
        document.getElementById('chat-empty')?.style.setProperty('display', 'none');
        document.getElementById('chat-container')?.style.setProperty('display', 'flex');
    }

    hideChatContainer(): void {
        document.getElementById('chat-empty')?.style.setProperty('display', 'flex');
        document.getElementById('chat-container')?.style.setProperty('display', 'none');
    }

    setInputEnabled(enabled: boolean): void {
        const input = document.getElementById('chat-input') as HTMLTextAreaElement | null;
        const btn = document.getElementById('btn-send') as HTMLButtonElement | null;

        if (input) input.disabled = !enabled;
        if (btn) btn.disabled = !enabled;
    }

    scrollToBottom(): void {
        const container = document.getElementById('chat-messages');
        if (container) {
            container.scrollTop = container.scrollHeight;
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
    private static readonly MAX_IMAGE_SIZE = 5 * 1024 * 1024; // 5MB
    private static readonly MAX_ATTACHED_IMAGES = 5;

    attachImage(file: File): void {
        if (file.size > ChatManager.MAX_IMAGE_SIZE) {
            showToast(`Image too large (${(file.size / 1024 / 1024).toFixed(1)}MB). Maximum is 5MB.`, { type: 'warning' });
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
    }

    // ========================================================================
    // Message Edit / Delete
    // ========================================================================

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
        if (contentEl) contentEl.innerHTML = this.formatMessage(originalContent);
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
            is_regeneration: true,  // Skip duplicate user message save in backend
        });
    }

    showNewChatModal(): void {
        const modal = document.getElementById('new-chat-modal');
        if (modal) {
            modal.classList.add('active');
            this.selectedRole = 'general';
            this.thinkingEnabled = false;
            // Reset modal thinking checkbox to match (prevents stale checked state)
            const modalThinking = document.getElementById('modal-thinking') as HTMLInputElement | null;
            if (modalThinking) modalThinking.checked = false;
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
        });

        document.getElementById('btn-send')?.addEventListener('click', () => this.sendMessage());
        document.getElementById('thinking-toggle')?.addEventListener('change', (e) => {
            if (this.currentConversation) {
                this.currentConversation.thinking_enabled = (e.target as HTMLInputElement).checked;
                // Optional: send to backend to persist
            }
        });

        
        // Setup image upload
        this.setupImageUpload();
        
        document.getElementById('btn-star-chat')?.addEventListener('click', () => {
            if (this.currentConversation) {
                this.starConversation(this.currentConversation.id, !this.currentConversation.is_starred);
            }
        });
        document.getElementById('btn-export-chat')?.addEventListener('click', () => {
            if (this.currentConversation) {
                this.exportConversation(this.currentConversation.id, 'json');
            }
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
        input?.addEventListener('input', () => this.autoResizeInput());
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
