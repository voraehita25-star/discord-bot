"use strict";
/**
 * 디스코드 봇 대시보드 - Enhanced TypeScript Frontend
 * Tauri v2 Desktop Application
 *
 * Features:
 * - Toast Notifications
 * - Real-time Auto-refresh
 * - Performance Charts
 * - Dark/Light Theme
 * - Enhanced Settings Panel
 * - Optimized Performance with Caching
 */
// Use global Tauri API (withGlobalTauri: true in tauri.conf.json)
const invoke = (cmd, args) => {
    if (window.__TAURI__?.core?.invoke) {
        return window.__TAURI__.core.invoke(cmd, args);
    }
    console.warn('Tauri not available, using mock');
    return Promise.reject(new Error('Tauri not available'));
};
// ============================================================================
// Error Logger - Logs frontend errors to file for debugging
// ============================================================================
class ErrorLogger {
    static getInstance() {
        if (!ErrorLogger.instance) {
            ErrorLogger.instance = new ErrorLogger();
        }
        return ErrorLogger.instance;
    }
    constructor() {
        this.errorQueue = [];
        this.isProcessing = false;
        this.maxQueueSize = 100; // Prevent unbounded growth
        this.setupGlobalErrorHandlers();
    }
    setupGlobalErrorHandlers() {
        // Catch unhandled errors
        window.onerror = (message, source, lineno, colno, error) => {
            this.log('UNCAUGHT_ERROR', String(message), error?.stack || `at ${source}:${lineno}:${colno}`);
            return false;
        };
        // Catch unhandled promise rejections
        window.onunhandledrejection = (event) => {
            const reason = event.reason;
            const message = reason?.message || String(reason);
            const stack = reason?.stack || 'No stack trace';
            this.log('UNHANDLED_REJECTION', message, stack);
        };
        // Override console.error to also log to file
        const originalConsoleError = console.error;
        console.error = (...args) => {
            originalConsoleError.apply(console, args);
            const message = args.map(arg => {
                if (arg instanceof Error)
                    return arg.message;
                if (typeof arg === 'object')
                    return JSON.stringify(arg);
                return String(arg);
            }).join(' ');
            const stack = args.find(arg => arg instanceof Error)?.stack;
            this.log('CONSOLE_ERROR', message, stack);
        };
    }
    async log(errorType, message, stack) {
        // Drop oldest errors if queue is full to prevent memory leak
        if (this.errorQueue.length >= this.maxQueueSize) {
            this.errorQueue.shift(); // Remove oldest
        }
        this.errorQueue.push({ type: errorType, message, stack });
        this.processQueue();
    }
    async processQueue() {
        if (this.isProcessing || this.errorQueue.length === 0)
            return;
        this.isProcessing = true;
        while (this.errorQueue.length > 0) {
            const error = this.errorQueue.shift();
            if (error) {
                try {
                    await invoke('log_frontend_error', {
                        errorType: error.type,
                        message: error.message,
                        stack: error.stack || null
                    });
                }
                catch (e) {
                    // Silently fail if logging fails
                }
            }
        }
        this.isProcessing = false;
    }
    async getErrors(count = 20) {
        try {
            return await invoke('get_dashboard_errors', { count });
        }
        catch {
            return ['Failed to fetch errors'];
        }
    }
    async clearErrors() {
        try {
            await invoke('clear_dashboard_errors');
        }
        catch (e) {
            console.warn('Failed to clear error log:', e);
        }
    }
}
// Initialize error logger early
const errorLogger = ErrorLogger.getInstance();
// ============================================================================
// Performance Cache System
// ============================================================================
class DataCache {
    constructor() {
        this.cache = new Map();
    }
    set(key, data, ttlMs = 5000) {
        this.cache.set(key, {
            data,
            timestamp: Date.now(),
            ttl: ttlMs
        });
    }
    get(key) {
        const entry = this.cache.get(key);
        if (!entry)
            return null;
        if (Date.now() - entry.timestamp > entry.ttl) {
            this.cache.delete(key);
            return null;
        }
        return entry.data;
    }
    invalidate(key) {
        this.cache.delete(key);
    }
    clear() {
        this.cache.clear();
    }
}
const dataCache = new DataCache();
// ============================================================================
// Memory Manager
// ============================================================================
class MemoryManager {
    constructor() {
        this.memories = [];
        this.currentCategory = 'all';
    }
    loadMemories() {
        chatManager?.send({ type: 'get_memories', category: this.currentCategory === 'all' ? null : this.currentCategory });
    }
    saveMemory(content, category) {
        chatManager?.send({ type: 'save_memory', content, category });
    }
    deleteMemory(id) {
        chatManager?.send({ type: 'delete_memory', id });
    }
    renderMemories(memories) {
        this.memories = memories;
        const container = document.getElementById('memories-list');
        if (!container)
            return;
        // Filter by category if needed
        const filteredMemories = this.currentCategory === 'all'
            ? memories
            : memories.filter(m => m.category === this.currentCategory);
        if (filteredMemories.length === 0) {
            container.innerHTML = `
                <div class="empty-memories">
                    <span class="empty-icon">🧠</span>
                    <p>No memories yet</p>
                    <p class="hint">Add memories to help AI remember important information about you</p>
                </div>
            `;
            return;
        }
        container.innerHTML = filteredMemories.map(memory => `
            <div class="memory-card" data-id="${this.escapeHtml(String(memory.id))}">
                <div class="memory-card-header">
                    <span class="memory-category-badge">${this.escapeHtml(memory.category || 'general')}</span>
                </div>
                <div class="memory-card-content">${this.escapeHtml(memory.content)}</div>
                <div class="memory-card-footer">
                    <span class="memory-timestamp">${this.formatTime(memory.created_at)}</span>
                    <button class="memory-delete-btn" data-id="${this.escapeHtml(String(memory.id))}">Delete</button>
                </div>
            </div>
        `).join('');
        // Add delete handlers
        container.querySelectorAll('.memory-delete-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const id = e.target.dataset.id;
                if (id && confirm('Delete this memory?')) {
                    this.deleteMemory(id);
                }
            });
        });
    }
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
    formatTime(isoString) {
        try {
            return new Date(isoString).toLocaleDateString('en-US', {
                year: 'numeric',
                month: 'short',
                day: 'numeric',
                hour: '2-digit',
                minute: '2-digit'
            });
        }
        catch {
            return isoString;
        }
    }
    showModal() {
        const modal = document.getElementById('add-memory-modal');
        if (modal) {
            modal.classList.add('active');
            document.getElementById('memory-content').value = '';
        }
    }
    closeModal() {
        const modal = document.getElementById('add-memory-modal');
        if (modal)
            modal.classList.remove('active');
    }
    setupEventListeners() {
        // Category filter buttons
        document.querySelectorAll('.memory-category-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const category = e.target.dataset.category || 'all';
                this.currentCategory = category;
                // Update active state
                document.querySelectorAll('.memory-category-btn').forEach(b => b.classList.remove('active'));
                e.target.classList.add('active');
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
            const content = document.getElementById('memory-content')?.value?.trim();
            const category = document.getElementById('memory-category')?.value || 'general';
            if (content) {
                this.saveMemory(content, category);
            }
            else {
                showToast('Please enter memory content', { type: 'warning' });
            }
        });
    }
}
const memoryManager = new MemoryManager();
class ChatManager {
    constructor() {
        this.ws = null;
        this.connected = false;
        this.currentConversation = null;
        this.conversations = [];
        this.messages = [];
        this.selectedRole = 'general';
        this.thinkingEnabled = false;
        this.isStreaming = false;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 5;
        this.presets = {};
        this.pendingDeleteId = null;
        this.pendingRenameId = null;
        this.attachedImages = []; // Base64 encoded images
        this.currentMode = ''; // Store current mode for the streaming message
        this.pingInterval = null; // Track ping interval for cleanup
        this.reconnectTimeout = null; // Track reconnect timeout
        this.currentThinking = ''; // Store current thinking for the streaming message
    }
    connect() {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            return;
        }
        try {
            this.ws = new WebSocket('ws://127.0.0.1:8765/ws');
            this.ws.onopen = () => {
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
                    console.warn('🔌 WebSocket connection failed (bot may not be running)');
                }
                this.updateConnectionStatus(false);
            };
            this.ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    this.handleMessage(data);
                }
                catch (e) {
                    console.error('Failed to parse WebSocket message:', e);
                    errorLogger.log('WEBSOCKET_PARSE_ERROR', 'Failed to parse message', String(e));
                }
            };
        }
        catch (e) {
            console.error('Failed to create WebSocket:', e);
            errorLogger.log('WEBSOCKET_CREATE_ERROR', 'Failed to create WebSocket', String(e));
            this.scheduleReconnect();
        }
    }
    scheduleReconnect() {
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
    disconnect() {
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
    send(data) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify(data));
        }
        else {
            showToast('Not connected to AI server', { type: 'error' });
        }
    }
    handleMessage(data) {
        switch (data.type) {
            case 'connected':
                this.presets = data.presets || {};
                this.listConversations();
                break;
            case 'conversations_list':
                this.conversations = data.conversations || [];
                this.renderConversationList();
                break;
            case 'conversation_created':
                this.currentConversation = data;
                this.messages = [];
                this.showChatContainer();
                this.updateChatHeader();
                this.renderMessages();
                this.listConversations();
                this.closeModal();
                break;
            case 'conversation_loaded':
                this.currentConversation = data.conversation;
                this.messages = data.messages || [];
                this.showChatContainer();
                this.updateChatHeader();
                this.renderMessages();
                break;
            case 'stream_start':
                this.isStreaming = true;
                this.currentMode = data.mode || ''; // Store mode for later
                this.appendStreamingMessage(data.mode || '');
                this.setInputEnabled(false);
                break;
            case 'thinking_start':
                this.showThinkingIndicator();
                break;
            case 'thinking_chunk':
                this.appendThinkingChunk(data.content);
                break;
            case 'thinking_end':
                this.finalizeThinking(data.full_thinking);
                break;
            case 'chunk':
                this.appendChunk(data.content);
                break;
            case 'stream_end':
                this.isStreaming = false;
                this.finalizeStreamingMessage(data.full_response);
                this.setInputEnabled(true);
                break;
            case 'title_updated':
                {
                    const updatedConv = this.conversations.find(c => c.id === data.conversation_id);
                    if (updatedConv)
                        updatedConv.title = data.title;
                    if (this.currentConversation && this.currentConversation.id === data.conversation_id) {
                        this.currentConversation.title = data.title;
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
                if (conv)
                    conv.is_starred = data.starred;
                // Also update currentConversation if it's the same one
                if (this.currentConversation && this.currentConversation.id === data.id) {
                    this.currentConversation.is_starred = data.starred;
                }
                this.renderConversationList();
                this.updateStarButton();
                break;
            case 'conversation_exported':
                this.downloadExport(data);
                break;
            case 'conversation_renamed':
                {
                    const renamedConv = this.conversations.find(c => c.id === data.id);
                    if (renamedConv)
                        renamedConv.title = data.title;
                    if (this.currentConversation && this.currentConversation.id === data.id) {
                        this.currentConversation.title = data.title;
                        this.updateChatHeader();
                    }
                    this.renderConversationList();
                    showToast('Conversation renamed', { type: 'success' });
                }
                break;
            case 'error':
                console.error('Server error:', data.message);
                errorLogger.log('AI_SERVER_ERROR', data.message, JSON.stringify(data));
                showToast(data.message, { type: 'error' });
                this.isStreaming = false;
                this.setInputEnabled(true);
                break;
            case 'pong':
                break;
            // Memory handlers
            case 'memories':
                memoryManager.renderMemories(data.memories);
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
                    const profile = data.profile || {};
                    const nameInput = document.getElementById('user-name-input');
                    const bioInput = document.getElementById('user-bio-input');
                    const prefsInput = document.getElementById('user-preferences-input');
                    const creatorToggle = document.getElementById('creator-toggle');
                    if (nameInput && profile.display_name)
                        nameInput.value = profile.display_name;
                    if (bioInput && profile.bio)
                        bioInput.value = profile.bio;
                    if (prefsInput && profile.preferences)
                        prefsInput.value = profile.preferences;
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
    updateConnectionStatus(connected) {
        const statusEl = document.getElementById('chat-connection-status');
        if (statusEl) {
            statusEl.className = connected ? 'connected' : 'disconnected';
            statusEl.textContent = connected ? '🟢 Connected' : '🔴 Connecting...';
        }
        // Note: Overlay is now controlled by bot status in updateStatusBadge()
    }
    listConversations() {
        this.send({ type: 'list_conversations' });
    }
    createConversation() {
        this.send({
            type: 'new_conversation',
            role_preset: this.selectedRole,
            thinking_enabled: this.thinkingEnabled
        });
    }
    loadConversation(id) {
        this.send({ type: 'load_conversation', id });
    }
    deleteConversation(id) {
        // Prevent double-click issues
        if (this.isStreaming)
            return;
        // Show custom delete confirmation modal
        this.pendingDeleteId = id;
        const modal = document.getElementById('delete-confirm-modal');
        if (modal) {
            modal.classList.add('active');
        }
    }
    confirmDelete() {
        if (this.pendingDeleteId) {
            this.send({ type: 'delete_conversation', id: this.pendingDeleteId });
            this.pendingDeleteId = null;
        }
        this.closeDeleteModal();
    }
    closeDeleteModal() {
        const modal = document.getElementById('delete-confirm-modal');
        if (modal) {
            modal.classList.remove('active');
        }
        this.pendingDeleteId = null;
    }
    renameConversation(id) {
        if (this.isStreaming)
            return;
        const conv = this.conversations.find(c => c.id === id);
        this.pendingRenameId = id;
        const modal = document.getElementById('rename-modal');
        const input = document.getElementById('rename-input');
        if (modal && input) {
            input.value = conv?.title || '';
            modal.classList.add('active');
            input.focus();
            input.select();
        }
    }
    confirmRename() {
        const input = document.getElementById('rename-input');
        const newTitle = input?.value?.trim();
        if (this.pendingRenameId && newTitle) {
            this.send({ type: 'rename_conversation', id: this.pendingRenameId, title: newTitle });
            this.pendingRenameId = null;
        }
        this.closeRenameModal();
    }
    closeRenameModal() {
        const modal = document.getElementById('rename-modal');
        if (modal) {
            modal.classList.remove('active');
        }
        this.pendingRenameId = null;
    }
    starConversation(id, starred) {
        this.send({ type: 'star_conversation', id, starred });
    }
    exportConversation(id, format = 'json') {
        this.send({ type: 'export_conversation', id, format });
    }
    sendMessage() {
        const input = document.getElementById('chat-input');
        const content = input?.value?.trim();
        if (!content || this.isStreaming)
            return;
        if (!this.currentConversation) {
            showToast('Please start a conversation first', { type: 'warning' });
            return;
        }
        // Get history BEFORE adding new message (backend will add it)
        const historyToSend = this.messages.slice(-20);
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
            input.focus(); // Keep cursor in input
        }
        const thinkingToggle = document.getElementById('thinking-toggle');
        const searchToggle = document.getElementById('chat-use-search');
        const unrestrictedToggle = document.getElementById('chat-unrestricted');
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
    appendStreamingMessage(mode = '') {
        const container = document.getElementById('chat-messages');
        const msgDiv = document.createElement('div');
        msgDiv.className = 'chat-message assistant streaming';
        msgDiv.id = 'streaming-message';
        const aiName = this.currentConversation?.role_name || 'AI';
        const timeStr = this.formatTime(new Date().toISOString());
        const modeHtml = mode ? `<span class="message-mode">${escapeHtml(mode)}</span>` : '';
        const avatarHtml = settings.aiAvatar
            ? `<img src="${settings.aiAvatar}" alt="ai" class="user-avatar-img">`
            : (this.currentConversation?.role_emoji || '🤖');
        msgDiv.innerHTML = `
            <div class="message-avatar">${avatarHtml}</div>
            <div class="message-wrapper">
                <div class="message-header">
                    <span class="message-name">${escapeHtml(aiName)}</span>
                    <span class="message-time">${timeStr}</span>
                    ${modeHtml}
                </div>
                <div class="thinking-container" style="display: none;">
                    <div class="thinking-header">💭 Thinking...</div>
                    <div class="thinking-content"></div>
                </div>
                <div class="message-content">
                    <span class="streaming-text"></span>
                    <span class="typing-cursor">▋</span>
                </div>
            </div>
        `;
        container?.appendChild(msgDiv);
        this.scrollToBottom();
    }
    showThinkingIndicator() {
        const thinkingContainer = document.querySelector('#streaming-message .thinking-container');
        if (thinkingContainer) {
            thinkingContainer.style.display = 'block';
        }
    }
    appendThinkingChunk(text) {
        const thinkingContent = document.querySelector('#streaming-message .thinking-content');
        if (thinkingContent) {
            thinkingContent.textContent += text;
            this.scrollToBottom();
        }
    }
    finalizeThinking(fullThinking) {
        // Store for later use in finalizeStreamingMessage
        this.currentThinking = fullThinking;
        const thinkingContainer = document.querySelector('#streaming-message .thinking-container');
        const thinkingHeader = document.querySelector('#streaming-message .thinking-header');
        const thinkingContent = document.querySelector('#streaming-message .thinking-content');
        if (thinkingHeader) {
            thinkingHeader.textContent = '💭 Thought Process';
            thinkingHeader.classList.add('collapsible', 'collapsed'); // Start collapsed
            thinkingHeader.onclick = () => {
                thinkingContent?.classList.toggle('collapsed');
                thinkingHeader.classList.toggle('collapsed');
            };
        }
        if (thinkingContent) {
            // Render Markdown formatting (bold, italic, code, etc.)
            thinkingContent.innerHTML = this.formatMessage(fullThinking);
            thinkingContent.classList.add('collapsed'); // Start collapsed
        }
    }
    appendChunk(text) {
        const streamingText = document.querySelector('#streaming-message .streaming-text');
        if (streamingText) {
            streamingText.textContent += text;
            this.scrollToBottom();
        }
    }
    finalizeStreamingMessage(fullResponse) {
        const streamingMsg = document.getElementById('streaming-message');
        if (streamingMsg) {
            streamingMsg.classList.remove('streaming');
            streamingMsg.removeAttribute('id');
            const content = streamingMsg.querySelector('.message-content');
            if (content) {
                content.innerHTML = this.formatMessage(fullResponse);
            }
            // Add copy button at the bottom
            const wrapper = streamingMsg.querySelector('.message-wrapper');
            if (wrapper && !wrapper.querySelector('.message-actions')) {
                const actionsDiv = document.createElement('div');
                actionsDiv.className = 'message-actions';
                actionsDiv.innerHTML = `<button class="copy-message-btn" data-content="${escapeHtml(fullResponse).replace(/"/g, '&quot;')}" title="Copy message">📋 Copy</button>`;
                wrapper.appendChild(actionsDiv);
                // Add click event
                actionsDiv.querySelector('.copy-message-btn')?.addEventListener('click', async (e) => {
                    const btn = e.target;
                    const contentAttr = btn.getAttribute('data-content') || '';
                    const textarea = document.createElement('textarea');
                    textarea.innerHTML = contentAttr;
                    const decodedContent = textarea.value;
                    try {
                        await navigator.clipboard.writeText(decodedContent);
                        btn.textContent = '✅ Copied';
                        setTimeout(() => { btn.textContent = '📋 Copy'; }, 1500);
                    }
                    catch (err) {
                        console.error('Failed to copy:', err);
                    }
                });
            }
        }
        // Store message with thinking and mode if available
        const newMessage = {
            role: 'assistant',
            content: fullResponse,
            created_at: new Date().toISOString()
        };
        if (this.currentThinking) {
            newMessage.thinking = this.currentThinking;
            this.currentThinking = ''; // Reset for next message
        }
        if (this.currentMode) {
            newMessage.mode = this.currentMode;
            this.currentMode = ''; // Reset for next message
        }
        this.messages.push(newMessage);
        this.scrollToBottom();
    }
    renderConversationList() {
        const container = document.getElementById('conversation-list');
        if (!container)
            return;
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
                ? `<img class="conv-avatar" src="${settings.aiAvatar}" alt="AI">`
                : `<span class="conv-emoji">${preset.emoji || '💬'}</span>`;
            return `
                <div class="conversation-item ${isActive ? 'active' : ''} ${starClass}" 
                     data-id="${escapeHtml(conv.id)}">
                    ${avatarHtml}
                    <div class="conv-info">
                        <span class="conv-title">${escapeHtml(conv.title || 'New Chat')}</span>
                        <span class="conv-meta">${conv.message_count || 0} messages</span>
                    </div>
                    ${conv.is_starred ? '<span class="conv-star">⭐</span>' : ''}
                </div>
            `;
        }).join('');
        // Use event delegation instead of inline onclick (fixes XSS risk)
        container.querySelectorAll('.conversation-item[data-id]').forEach(item => {
            item.addEventListener('click', () => {
                const id = item.dataset.id;
                if (id)
                    this.loadConversation(id);
            });
        });
    }
    renderMessages() {
        const container = document.getElementById('chat-messages');
        if (!container)
            return;
        if (this.messages.length === 0) {
            const emoji = this.currentConversation?.role_emoji || '🤖';
            const name = this.currentConversation?.role_name || 'AI';
            const welcomeAvatarHtml = settings.aiAvatar
                ? `<img src="${settings.aiAvatar}" alt="AI" class="welcome-avatar">`
                : `<div class="welcome-emoji">${emoji}</div>`;
            container.innerHTML = `
                <div class="chat-welcome">
                    ${welcomeAvatarHtml}
                    <h3>Chat with ${this.escapeHtml(name)}</h3>
                    <p>Type a message to start the conversation</p>
                </div>
            `;
            return;
        }
        const aiEmoji = this.currentConversation?.role_emoji || '🤖';
        const aiName = this.currentConversation?.role_name || 'AI';
        const userName = settings.userName || 'You';
        const userAvatar = settings.userAvatar;
        const aiAvatar = settings.aiAvatar;
        container.innerHTML = this.messages.map(msg => {
            const isUser = msg.role === 'user';
            const displayName = isUser ? userName : aiName;
            const timeStr = this.formatTime(msg.created_at);
            // Both user and AI can have custom avatar images
            let avatarHtml;
            if (isUser) {
                avatarHtml = userAvatar
                    ? `<img src="${userAvatar}" alt="avatar" class="user-avatar-img">`
                    : '👤';
            }
            else {
                avatarHtml = aiAvatar
                    ? `<img src="${aiAvatar}" alt="ai" class="user-avatar-img">`
                    : aiEmoji;
            }
            // Render attached images for user messages (use data attribute to avoid XSS)
            let imagesHtml = '';
            if (msg.images && msg.images.length > 0) {
                imagesHtml = `<div class="message-images">${msg.images.map((img, idx) => `<img src="${escapeHtml(img)}" alt="attached" class="message-image" data-img-idx="${idx}">`).join('')}</div>`;
            }
            // Render thinking container for AI messages (collapsed by default)
            let thinkingHtml = '';
            if (!isUser && msg.thinking) {
                thinkingHtml = `
                    <div class="thinking-container">
                        <div class="thinking-header collapsible collapsed">
                            💭 Thought Process
                        </div>
                        <div class="thinking-content collapsed">${this.formatMessage(msg.thinking)}</div>
                    </div>
                `;
            }
            // Mode badge for AI messages
            const modeHtml = (!isUser && msg.mode)
                ? `<span class="message-mode">${escapeHtml(msg.mode)}</span>`
                : '';
            // Copy button for AI messages (at bottom)
            const copyBtnHtml = !isUser
                ? `<div class="message-actions"><button class="copy-message-btn" data-content="${escapeHtml(msg.content).replace(/"/g, '&quot;')}" title="Copy message">📋 Copy</button></div>`
                : '';
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
                        ${copyBtnHtml}
                    </div>
                </div>
            `;
        }).join('');
        this.scrollToBottom();
        // Setup event delegation for image clicks (avoid inline onclick XSS risk)
        container.querySelectorAll('.message-image[data-img-idx]').forEach(img => {
            img.addEventListener('click', () => {
                const src = img.src;
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
                if (content)
                    content.classList.toggle('collapsed');
            });
        });
        // Setup copy button clicks
        container.querySelectorAll('.copy-message-btn').forEach(btn => {
            btn.addEventListener('click', async () => {
                const content = btn.getAttribute('data-content') || '';
                // Decode HTML entities back to original text
                const textarea = document.createElement('textarea');
                textarea.innerHTML = content;
                const decodedContent = textarea.value;
                try {
                    await navigator.clipboard.writeText(decodedContent);
                    const originalText = btn.textContent;
                    btn.textContent = '✅';
                    setTimeout(() => { btn.textContent = originalText; }, 1500);
                }
                catch (err) {
                    console.error('Failed to copy:', err);
                    showToast('Failed to copy message', { type: 'error' });
                }
            });
        });
    }
    formatMessage(content) {
        let html = escapeHtml(content);
        // Render block LaTeX equations ($$...$$)
        html = html.replace(/\$\$([^$]+)\$\$/g, (_match, tex) => {
            try {
                if (typeof window !== 'undefined' && window.katex) {
                    return `<div class="math-block">${window.katex.renderToString(tex.trim(), { displayMode: true, throwOnError: false })}</div>`;
                }
                return `<div class="math-block">$$${tex}$$</div>`;
            }
            catch {
                return `<div class="math-block">$$${tex}$$</div>`;
            }
        });
        // Render inline LaTeX equations ($...$) - but not $$
        html = html.replace(/(?<!\$)\$(?!\$)([^$]+)\$(?!\$)/g, (_match, tex) => {
            try {
                if (typeof window !== 'undefined' && window.katex) {
                    return `<span class="math-inline">${window.katex.renderToString(tex.trim(), { displayMode: false, throwOnError: false })}</span>`;
                }
                return `<span class="math-inline">$${tex}$</span>`;
            }
            catch {
                return `<span class="math-inline">$${tex}$</span>`;
            }
        });
        html = html.replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code class="language-$1">$2</code></pre>');
        html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
        html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
        html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');
        // Blockquotes (> at start of line)
        html = html.replace(/^&gt; (.+)$/gm, '<blockquote>$1</blockquote>');
        // Merge consecutive blockquotes
        html = html.replace(/<\/blockquote>\n?<blockquote>/g, '<br>');
        html = html.replace(/\n/g, '<br>');
        return html;
    }
    updateChatHeader() {
        if (!this.currentConversation)
            return;
        const titleEl = document.getElementById('chat-title');
        const avatarEl = document.getElementById('chat-role-avatar');
        const nameEl = document.getElementById('chat-role-name');
        const thinkingToggle = document.getElementById('thinking-toggle');
        if (titleEl)
            titleEl.textContent = this.currentConversation.title || 'New Conversation';
        if (avatarEl)
            avatarEl.src = settings.aiAvatar || '';
        if (nameEl)
            nameEl.textContent = this.currentConversation.role_name || 'AI';
        if (thinkingToggle)
            thinkingToggle.checked = this.currentConversation.thinking_enabled || false;
        this.updateStarButton();
    }
    updateStarButton() {
        const btn = document.getElementById('btn-star-chat');
        if (btn && this.currentConversation) {
            btn.textContent = this.currentConversation.is_starred ? '⭐' : '☆';
        }
    }
    showChatContainer() {
        document.getElementById('chat-empty')?.style.setProperty('display', 'none');
        document.getElementById('chat-container')?.style.setProperty('display', 'flex');
    }
    hideChatContainer() {
        document.getElementById('chat-empty')?.style.setProperty('display', 'flex');
        document.getElementById('chat-container')?.style.setProperty('display', 'none');
    }
    setInputEnabled(enabled) {
        const input = document.getElementById('chat-input');
        const btn = document.getElementById('btn-send');
        if (input)
            input.disabled = !enabled;
        if (btn)
            btn.disabled = !enabled;
    }
    scrollToBottom() {
        const container = document.getElementById('chat-messages');
        if (container) {
            container.scrollTop = container.scrollHeight;
        }
    }
    formatTime(dateStr) {
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
            }
            else {
                const dateFormatted = date.toLocaleDateString('th-TH', {
                    day: 'numeric',
                    month: 'short'
                });
                return `${dateFormatted} ${timeStr}`;
            }
        }
        catch {
            return '';
        }
    }
    autoResizeInput() {
        const input = document.getElementById('chat-input');
        if (input) {
            input.style.height = 'auto';
            input.style.height = Math.min(input.scrollHeight, 150) + 'px';
        }
    }
    // Image attachment methods
    attachImage(file) {
        const reader = new FileReader();
        reader.onload = (e) => {
            const base64 = e.target?.result;
            if (base64) {
                // Store full base64 data URL
                this.attachedImages.push(base64);
                this.renderAttachedImages();
            }
        };
        reader.readAsDataURL(file);
    }
    removeImage(index) {
        this.attachedImages.splice(index, 1);
        this.renderAttachedImages();
    }
    renderAttachedImages() {
        const container = document.getElementById('attached-images');
        if (!container)
            return;
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
                const idx = parseInt(e.target.dataset.idx || '0');
                this.removeImage(idx);
            });
        });
    }
    setupImageUpload() {
        const attachBtn = document.getElementById('btn-attach');
        const fileInput = document.getElementById('image-input');
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
    showNewChatModal() {
        const modal = document.getElementById('new-chat-modal');
        if (modal) {
            modal.classList.add('active');
            this.selectedRole = 'general';
            this.thinkingEnabled = false;
            this.updateRoleSelection();
        }
    }
    closeModal() {
        const modal = document.getElementById('new-chat-modal');
        if (modal)
            modal.classList.remove('active');
    }
    selectRole(role) {
        this.selectedRole = role;
        this.updateRoleSelection();
    }
    updateRoleSelection() {
        document.querySelectorAll('.role-card').forEach(card => {
            card.classList.toggle('selected', card.dataset.role === this.selectedRole);
        });
    }
    downloadExport(data) {
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
    init() {
        this.connect();
        document.getElementById('btn-new-chat')?.addEventListener('click', () => this.showNewChatModal());
        document.getElementById('btn-new-chat-main')?.addEventListener('click', () => this.showNewChatModal());
        document.getElementById('modal-close')?.addEventListener('click', () => this.closeModal());
        document.getElementById('modal-cancel')?.addEventListener('click', () => this.closeModal());
        document.getElementById('modal-create')?.addEventListener('click', () => this.createConversation());
        document.getElementById('new-chat-modal')?.querySelector('.modal-overlay')
            ?.addEventListener('click', () => this.closeModal());
        document.querySelectorAll('.role-card').forEach(card => {
            card.addEventListener('click', () => this.selectRole(card.dataset.role || 'general'));
        });
        document.getElementById('modal-thinking')?.addEventListener('change', (e) => {
            this.thinkingEnabled = e.target.checked;
        });
        document.getElementById('btn-send')?.addEventListener('click', () => this.sendMessage());
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
            }
            else if (e.key === 'Escape') {
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
let chatManager = null;
// ============================================================================
// State Management
// ============================================================================
let currentPage = 'status';
let refreshInterval = null;
let logsRefreshInterval = null;
let logsAutoScrollEnabled = true;
let lastLogCount = 0;
// Chart data history
const memoryHistory = [];
const messagesHistory = [];
const MAX_CHART_POINTS = 60;
// Settings with defaults
let settings = {
    theme: 'dark',
    refreshInterval: 2000,
    autoScroll: true,
    notifications: true,
    chartHistory: 60,
    userName: 'You',
    userAvatar: '',
    aiAvatar: 'data:image/jpeg;base64,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',
    isCreator: false
};
// Debounce timers
const debounceTimers = new Map();
// ============================================================================
// Initialization
// ============================================================================
document.addEventListener('DOMContentLoaded', () => {
    loadSettings();
    initNavigation();
    initTheme();
    initToastContainer();
    initCharts();
    startRefreshLoop();
    loadAllData();
    initSakuraAnimation();
    initKeyboardShortcuts();
    initChatManager();
    initMemoryManager();
    // Update AI avatars after all init
    updateAiAvatars();
});
function initChatManager() {
    chatManager = new ChatManager();
    chatManager.init();
    window.chatManager = chatManager;
}
function initMemoryManager() {
    memoryManager.setupEventListeners();
}
// ============================================================================
// Keyboard Shortcuts
// ============================================================================
function initKeyboardShortcuts() {
    document.addEventListener('keydown', (e) => {
        // Ctrl+1-6 for page navigation
        if (e.ctrlKey && e.key >= '1' && e.key <= '6') {
            const pages = ['status', 'chat', 'memories', 'logs', 'database', 'settings'];
            const index = parseInt(e.key) - 1;
            if (pages[index]) {
                e.preventDefault();
                switchPage(pages[index]);
            }
        }
        // Ctrl+R to refresh
        if (e.ctrlKey && e.key === 'r') {
            e.preventDefault();
            loadAllData();
            showToast('Refreshed!', { type: 'info', duration: 1500 });
        }
        // Ctrl+T to toggle theme
        if (e.ctrlKey && e.key === 't') {
            e.preventDefault();
            toggleTheme();
        }
        // Ctrl+Enter to send message (in chat)
        if (e.ctrlKey && e.key === 'Enter' && currentPage === 'chat') {
            e.preventDefault();
            chatManager?.sendMessage();
        }
    });
}
// ============================================================================
// Toast Notification System
// ============================================================================
function initToastContainer() {
    if (!document.getElementById('toast-container')) {
        const container = document.createElement('div');
        container.id = 'toast-container';
        document.body.appendChild(container);
    }
}
function showToast(message, options = { type: 'info' }) {
    if (!settings.notifications)
        return;
    const container = document.getElementById('toast-container');
    if (!container)
        return;
    const toast = document.createElement('div');
    toast.className = `toast toast-${options.type}`;
    const icons = {
        success: '✅',
        error: '❌',
        warning: '⚠️',
        info: 'ℹ️'
    };
    toast.innerHTML = `
        <span class="toast-icon">${icons[options.type]}</span>
        <span class="toast-message">${escapeHtml(message)}</span>
        <button class="toast-close">×</button>
    `;
    // Use addEventListener instead of inline onclick (CSP blocks inline scripts)
    toast.querySelector('.toast-close')?.addEventListener('click', () => toast.remove());
    container.appendChild(toast);
    // Animate in
    requestAnimationFrame(() => {
        toast.classList.add('toast-visible');
    });
    // Auto remove
    const duration = options.duration ?? 4000;
    setTimeout(() => {
        toast.classList.remove('toast-visible');
        toast.classList.add('toast-hiding');
        setTimeout(() => toast.remove(), 300);
    }, duration);
}
// ============================================================================
// Theme System
// ============================================================================
function initTheme() {
    applyTheme(settings.theme);
    // Add theme toggle button listeners (sidebar + settings page)
    document.getElementById('theme-toggle')?.addEventListener('click', toggleTheme);
    document.getElementById('theme-toggle-settings')?.addEventListener('click', toggleTheme);
}
function toggleTheme() {
    settings.theme = settings.theme === 'dark' ? 'light' : 'dark';
    applyTheme(settings.theme);
    saveSettings();
    showToast(`Theme: ${settings.theme === 'dark' ? '🌙 Dark' : '☀️ Light'}`, { type: 'info', duration: 1500 });
}
function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    const themeIcon = document.getElementById('theme-icon');
    if (themeIcon) {
        themeIcon.textContent = theme === 'dark' ? '🌙' : '☀️';
    }
    // Also update the settings page theme icon
    const themeIconSettings = document.getElementById('theme-icon-settings');
    if (themeIconSettings) {
        themeIconSettings.textContent = theme === 'dark' ? '🌙' : '☀️';
    }
}
// ============================================================================
// Settings Management
// ============================================================================
function loadSettings() {
    try {
        const saved = localStorage.getItem('dashboard-settings');
        if (saved) {
            const defaultAiAvatar = settings.aiAvatar; // Keep default Faust avatar
            settings = { ...settings, ...JSON.parse(saved) };
            // Migration: Only set default Faust avatar if saved aiAvatar is empty/undefined
            // Don't override custom avatars that users have set
            if (!settings.aiAvatar) {
                settings.aiAvatar = defaultAiAvatar;
                saveSettings(); // Save the migration
            }
        }
    }
    catch (e) {
        console.warn('Failed to load settings:', e);
    }
    // Update AI avatars in UI
    updateAiAvatars();
}
function updateAiAvatars() {
    // Update empty state avatar
    const emptyAvatar = document.getElementById('chat-empty-avatar');
    if (emptyAvatar && settings.aiAvatar) {
        emptyAvatar.src = settings.aiAvatar;
    }
    // Update chat header avatar
    const headerAvatar = document.getElementById('chat-role-avatar');
    if (headerAvatar && settings.aiAvatar) {
        headerAvatar.src = settings.aiAvatar;
    }
}
function saveSettings() {
    try {
        localStorage.setItem('dashboard-settings', JSON.stringify(settings));
    }
    catch (e) {
        console.warn('Failed to save settings:', e);
    }
}
function updateSetting(key, value) {
    settings[key] = value;
    saveSettings();
    // Apply changes
    if (key === 'refreshInterval') {
        restartRefreshLoop();
    }
    else if (key === 'theme') {
        applyTheme(value);
    }
}
// ============================================================================
// Lightweight Charts (Canvas-based for performance)
// ============================================================================
function initCharts() {
    // Charts will be initialized when the status page loads
    window.addEventListener('resize', debounce(updateCharts, 'resize', 250));
}
function addChartDataPoint(history, value) {
    history.push({
        timestamp: Date.now(),
        value
    });
    while (history.length > MAX_CHART_POINTS) {
        history.shift();
    }
}
function drawChart(canvasId, data, color, label) {
    const canvas = document.getElementById(canvasId);
    if (!canvas)
        return;
    const ctx = canvas.getContext('2d');
    if (!ctx)
        return;
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);
    const width = rect.width;
    const height = rect.height;
    const padding = 30;
    ctx.clearRect(0, 0, width, height);
    if (data.length < 2) {
        ctx.fillStyle = 'rgba(255,255,255,0.3)';
        ctx.font = '12px sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('Collecting data...', width / 2, height / 2);
        return;
    }
    const values = data.map(d => d.value);
    const minVal = Math.min(...values) * 0.9;
    const maxVal = Math.max(...values) * 1.1 || 1;
    // Draw grid
    ctx.strokeStyle = 'rgba(168, 85, 247, 0.15)';
    ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i++) {
        const y = padding + (height - padding * 2) * (i / 4);
        ctx.beginPath();
        ctx.moveTo(padding, y);
        ctx.lineTo(width - padding, y);
        ctx.stroke();
    }
    // Draw gradient fill
    const gradient = ctx.createLinearGradient(0, padding, 0, height - padding);
    gradient.addColorStop(0, color.replace('1)', '0.3)'));
    gradient.addColorStop(1, color.replace('1)', '0.05)'));
    ctx.beginPath();
    ctx.moveTo(padding, height - padding);
    data.forEach((point, i) => {
        const x = padding + (width - padding * 2) * (i / (data.length - 1));
        const y = height - padding - ((point.value - minVal) / (maxVal - minVal)) * (height - padding * 2);
        ctx.lineTo(x, y);
    });
    ctx.lineTo(width - padding, height - padding);
    ctx.closePath();
    ctx.fillStyle = gradient;
    ctx.fill();
    // Draw line
    ctx.beginPath();
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    data.forEach((point, i) => {
        const x = padding + (width - padding * 2) * (i / (data.length - 1));
        const y = height - padding - ((point.value - minVal) / (maxVal - minVal)) * (height - padding * 2);
        if (i === 0) {
            ctx.moveTo(x, y);
        }
        else {
            ctx.lineTo(x, y);
        }
    });
    ctx.stroke();
    // Draw current value
    const currentValue = data[data.length - 1]?.value ?? 0;
    ctx.fillStyle = color;
    ctx.font = 'bold 14px sans-serif';
    ctx.textAlign = 'right';
    ctx.fillText(`${label}: ${currentValue.toFixed(1)}`, width - padding, 20);
    // Draw min/max labels
    ctx.fillStyle = 'rgba(255,255,255,0.5)';
    ctx.font = '10px sans-serif';
    ctx.textAlign = 'left';
    ctx.fillText(maxVal.toFixed(1), 5, padding + 10);
    ctx.fillText(minVal.toFixed(1), 5, height - padding);
}
function updateCharts() {
    drawChart('memory-chart', memoryHistory, 'rgba(255, 107, 157, 1)', 'Memory MB');
    drawChart('messages-chart', messagesHistory, 'rgba(34, 211, 238, 1)', 'Messages');
}
// ============================================================================
// Sakura Petals Animation (Optimized with Object Pool)
// ============================================================================
function initSakuraAnimation() {
    const container = document.getElementById('sakura-container');
    if (!container)
        return;
    const petalShapes = [
        `<svg viewBox="0 0 40 40"><path d="M20 0 C25 10, 35 15, 40 20 C35 25, 25 30, 20 40 C15 30, 5 25, 0 20 C5 15, 15 10, 20 0" fill="currentColor"/></svg>`,
        `<svg viewBox="0 0 40 40"><ellipse cx="20" cy="20" rx="18" ry="12" fill="currentColor"/></svg>`,
        `<svg viewBox="0 0 40 40"><path d="M20 35 C10 25, 0 15, 10 5 C15 0, 20 5, 20 10 C20 5, 25 0, 30 5 C40 15, 30 25, 20 35" fill="currentColor"/></svg>`,
        `<svg viewBox="0 0 40 40"><ellipse cx="20" cy="20" rx="10" ry="18" fill="currentColor"/></svg>`,
        `<svg viewBox="0 0 40 40"><path d="M20 0 C30 15, 30 25, 20 40 C10 25, 10 15, 20 0" fill="currentColor"/></svg>`,
    ];
    const colors = [
        'rgba(255, 183, 197, 0.9)',
        'rgba(255, 145, 175, 0.85)',
        'rgba(255, 107, 157, 0.8)',
        'rgba(255, 192, 203, 0.9)',
        'rgba(255, 174, 201, 0.85)',
    ];
    const petalPool = [];
    const activePetals = new Set();
    const MAX_PETALS = 30;
    function getPetal() {
        let petal = petalPool.pop();
        if (!petal) {
            petal = document.createElement('div');
            petal.className = 'sakura-petal';
        }
        return petal;
    }
    function returnPetal(petal) {
        activePetals.delete(petal);
        petal.remove();
        petalPool.push(petal);
    }
    function createPetal() {
        if (activePetals.size >= MAX_PETALS)
            return;
        const petal = getPetal();
        activePetals.add(petal);
        const size = Math.random() * 15 + 10;
        const startX = Math.random() * window.innerWidth;
        const duration = Math.random() * 6 + 6;
        const delay = Math.random() * 2;
        const rotateStart = Math.random() * 360;
        const rotateEnd = rotateStart + (Math.random() * 720 - 360);
        const swayAmount = Math.random() * 80 + 40;
        const color = colors[Math.floor(Math.random() * colors.length)];
        const shape = petalShapes[Math.floor(Math.random() * petalShapes.length)];
        petal.innerHTML = shape;
        petal.style.cssText = `
            position: fixed;
            width: ${size}px;
            height: ${size}px;
            left: ${startX}px;
            top: -40px;
            color: ${color};
            pointer-events: none;
            z-index: 1;
            opacity: 0;
            will-change: transform, opacity;
            animation: sakuraFall${Math.floor(Math.random() * 3)} ${duration}s linear ${delay}s;
            --sway: ${swayAmount}px;
            --rotate-start: ${rotateStart}deg;
            --rotate-end: ${rotateEnd}deg;
        `;
        container.appendChild(petal);
        setTimeout(() => returnPetal(petal), (duration + delay) * 1000);
    }
    for (let i = 0; i < 15; i++) {
        setTimeout(createPetal, i * 300);
    }
    setInterval(createPetal, 1000);
}
// ============================================================================
// Navigation
// ============================================================================
function initNavigation() {
    document.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', () => {
            const page = item.dataset.page;
            if (page)
                switchPage(page);
        });
    });
    // Button handlers
    document.getElementById('btn-start')?.addEventListener('click', startBot);
    document.getElementById('btn-dev')?.addEventListener('click', startDevBot);
    document.getElementById('btn-stop')?.addEventListener('click', stopBot);
    document.getElementById('btn-restart')?.addEventListener('click', restartBot);
    // Quick action buttons (replaced inline onclick for CSP compliance)
    document.getElementById('btn-open-logs')?.addEventListener('click', () => openFolder('logs'));
    document.getElementById('btn-open-data')?.addEventListener('click', () => openFolder('data'));
    document.getElementById('btn-overlay-start')?.addEventListener('click', () => { switchPage('status'); startBot(); });
    document.getElementById('btn-auto-scroll')?.addEventListener('click', toggleAutoScroll);
    document.getElementById('btn-clear-logs')?.addEventListener('click', clearLogs);
    document.getElementById('btn-refresh-logs')?.addEventListener('click', loadLogs);
    document.getElementById('btn-clear-history')?.addEventListener('click', clearHistory);
    // Settings handlers
    document.getElementById('refresh-interval')?.addEventListener('change', (e) => {
        const value = parseInt(e.target.value);
        updateSetting('refreshInterval', value);
        showToast(`Refresh interval: ${value / 1000}s`, { type: 'info' });
    });
    document.getElementById('notifications-toggle')?.addEventListener('change', (e) => {
        updateSetting('notifications', e.target.checked);
    });
    // User name input handler
    document.getElementById('user-name-input')?.addEventListener('input', (e) => {
        const value = e.target.value.trim();
        updateSetting('userName', value || 'You');
    });
    // Save profile to AI button
    document.getElementById('btn-save-profile')?.addEventListener('click', () => {
        saveProfileToAI();
    });
    // Avatar upload handlers
    document.getElementById('btn-change-avatar')?.addEventListener('click', () => {
        document.getElementById('avatar-input')?.click();
    });
    document.getElementById('avatar-input')?.addEventListener('change', (e) => {
        const file = e.target.files?.[0];
        if (file)
            handleAvatarUpload(file, 'user');
    });
    document.getElementById('btn-remove-avatar')?.addEventListener('click', () => {
        removeAvatar('user');
    });
    // AI Avatar upload handlers
    document.getElementById('btn-change-ai-avatar')?.addEventListener('click', () => {
        document.getElementById('ai-avatar-input')?.click();
    });
    document.getElementById('ai-avatar-input')?.addEventListener('change', (e) => {
        const file = e.target.files?.[0];
        if (file)
            handleAvatarUpload(file, 'ai');
    });
    document.getElementById('btn-remove-ai-avatar')?.addEventListener('click', () => {
        removeAvatar('ai');
    });
    // Creator toggle handler
    document.getElementById('creator-toggle')?.addEventListener('change', (e) => {
        settings.isCreator = e.target.checked;
        saveSettings();
    });
}
function switchPage(page) {
    currentPage = page;
    document.querySelectorAll('.nav-item').forEach(item => {
        const itemPage = item.dataset.page;
        item.classList.toggle('active', itemPage === page);
    });
    document.querySelectorAll('.page').forEach(p => {
        p.classList.toggle('active', p.id === `page-${page}`);
    });
    if (page === 'logs') {
        loadLogs();
        startLogsRefresh();
    }
    else {
        stopLogsRefresh();
    }
    if (page === 'database')
        loadDbStats();
    if (page === 'settings')
        loadSettingsUI();
    if (page === 'memories' && chatManager && chatManager.connected) {
        memoryManager.loadMemories();
    }
    if (page === 'chat' && chatManager) {
        // Reconnect if disconnected
        if (!chatManager.connected) {
            chatManager.connect();
        }
    }
}
// ============================================================================
// Optimized Refresh Loop
// ============================================================================
function startRefreshLoop() {
    if (refreshInterval) {
        clearInterval(refreshInterval);
    }
    refreshInterval = window.setInterval(updateStatus, settings.refreshInterval);
    updateStatus();
}
function restartRefreshLoop() {
    startRefreshLoop();
}
// Debounce helper for performance
function debounce(fn, key, delay) {
    return () => {
        const existing = debounceTimers.get(key);
        if (existing) {
            clearTimeout(existing);
        }
        debounceTimers.set(key, window.setTimeout(() => {
            fn();
            debounceTimers.delete(key);
        }, delay));
    };
}
// Batch DOM updates for performance
function batchDOMUpdate(updates) {
    requestAnimationFrame(() => {
        updates.forEach(update => update());
    });
}
async function updateStatus() {
    // Check cache first
    const cachedStatus = dataCache.get('status');
    const cachedDbStats = dataCache.get('dbStats');
    try {
        // Parallel fetch
        const [status, dbStats] = await Promise.all([
            cachedStatus ?? invoke('get_status'),
            cachedDbStats ?? invoke('get_db_stats')
        ]);
        // Cache the results
        if (!cachedStatus)
            dataCache.set('status', status, 1500);
        if (!cachedDbStats)
            dataCache.set('dbStats', dbStats, 3000);
        // Add to chart history
        addChartDataPoint(memoryHistory, status.memory_mb);
        addChartDataPoint(messagesHistory, dbStats.total_messages);
        // Batch all DOM updates
        batchDOMUpdate([
            () => updateStatusBadge(status),
            () => updateStatusText(status),
            () => updateButtons(status),
            () => updateStats(status, dbStats),
            () => updateCharts()
        ]);
    }
    catch (error) {
        console.error('Failed to update status:', error);
    }
}
function updateStatusBadge(status) {
    const badge = document.getElementById('status-badge');
    const statusText = badge?.querySelector('.status-text');
    if (badge && statusText) {
        badge.classList.toggle('online', status.is_running);
        statusText.textContent = status.is_running ? 'Online' : 'Offline';
    }
    // Update AI Chat overlay based on bot running status
    const chatOverlay = document.getElementById('chat-not-running-overlay');
    if (chatOverlay) {
        chatOverlay.classList.toggle('visible', !status.is_running);
    }
}
function updateStatusText(status) {
    const botStatusText = document.getElementById('bot-status-text');
    if (botStatusText) {
        botStatusText.textContent = status.is_running ? 'Status: 🟢 Online' : 'Status: 🔴 Offline';
    }
}
function updateButtons(status) {
    // Don't override button states while a bot command is in progress
    if (botCommandInProgress)
        return;
    const btnStart = document.getElementById('btn-start');
    const btnDev = document.getElementById('btn-dev');
    const btnStop = document.getElementById('btn-stop');
    const btnRestart = document.getElementById('btn-restart');
    if (btnStart)
        btnStart.disabled = status.is_running;
    if (btnDev)
        btnDev.disabled = status.is_running;
    if (btnStop)
        btnStop.disabled = !status.is_running;
    if (btnRestart)
        btnRestart.disabled = !status.is_running;
}
function updateStats(status, dbStats) {
    const updates = [
        ['stat-uptime', status.uptime],
        ['stat-mode', status.mode],
        ['stat-memory', `${status.memory_mb.toFixed(1)} MB`],
        ['stat-messages', dbStats.total_messages.toLocaleString()],
        ['stat-channels', dbStats.active_channels.toString()]
    ];
    updates.forEach(([id, value]) => {
        const el = document.getElementById(id);
        if (el && el.textContent !== value) {
            el.textContent = value;
        }
    });
}
// ============================================================================
// Bot Control
// ============================================================================
let botCommandInProgress = false;
function setBotControlBusy(busy) {
    botCommandInProgress = busy;
    const btnStart = document.getElementById('btn-start');
    const btnDev = document.getElementById('btn-dev');
    const btnStop = document.getElementById('btn-stop');
    const btnRestart = document.getElementById('btn-restart');
    if (busy) {
        if (btnStart)
            btnStart.disabled = true;
        if (btnDev)
            btnDev.disabled = true;
        if (btnStop)
            btnStop.disabled = true;
        if (btnRestart)
            btnRestart.disabled = true;
    }
}
async function startBot() {
    if (botCommandInProgress)
        return;
    try {
        setBotControlBusy(true);
        showToast('Starting bot...', { type: 'info', duration: 10000 });
        const result = await invoke('start_bot');
        showToast(result, { type: 'success' });
        dataCache.invalidate('status');
        updateStatus();
    }
    catch (error) {
        showToast(String(error), { type: 'error' });
    }
    finally {
        setBotControlBusy(false);
    }
}
async function stopBot() {
    if (botCommandInProgress)
        return;
    try {
        setBotControlBusy(true);
        showToast('Stopping bot...', { type: 'info', duration: 5000 });
        const result = await invoke('stop_bot');
        showToast(result, { type: 'success' });
        dataCache.invalidate('status');
        updateStatus();
    }
    catch (error) {
        showToast(String(error), { type: 'error' });
    }
    finally {
        setBotControlBusy(false);
    }
}
async function restartBot() {
    if (botCommandInProgress)
        return;
    try {
        setBotControlBusy(true);
        showToast('Restarting bot...', { type: 'info', duration: 12000 });
        const result = await invoke('restart_bot');
        showToast(result, { type: 'success' });
        dataCache.invalidate('status');
        updateStatus();
    }
    catch (error) {
        showToast(String(error), { type: 'error' });
    }
    finally {
        setBotControlBusy(false);
    }
}
async function startDevBot() {
    if (botCommandInProgress)
        return;
    try {
        setBotControlBusy(true);
        showToast('Starting dev mode...', { type: 'info', duration: 8000 });
        const result = await invoke('start_dev_bot');
        showToast(result, { type: 'success' });
        dataCache.invalidate('status');
        updateStatus();
    }
    catch (error) {
        showToast(String(error), { type: 'error' });
    }
    finally {
        setBotControlBusy(false);
    }
}
// ============================================================================
// Logs - Optimized Real-time Streaming
// ============================================================================
async function loadLogs() {
    try {
        const logs = await invoke('get_logs', { count: 200 });
        const container = document.getElementById('log-content');
        const filterElement = document.getElementById('log-filter');
        const filter = filterElement?.value || 'all';
        if (!container)
            return;
        const hasNewLogs = logs.length !== lastLogCount;
        lastLogCount = logs.length;
        // Use DocumentFragment for better performance
        const fragment = document.createDocumentFragment();
        logs.forEach((line) => {
            let level = 'info';
            if (line.includes('ERROR'))
                level = 'error';
            else if (line.includes('WARNING'))
                level = 'warning';
            else if (line.includes('DEBUG'))
                level = 'debug';
            if (filter === 'all' || line.includes(filter)) {
                const div = document.createElement('div');
                div.className = `log-line ${level}`;
                div.textContent = line;
                fragment.appendChild(div);
            }
        });
        container.innerHTML = '';
        container.appendChild(fragment);
        if (!container.firstChild) {
            container.textContent = 'No logs found.';
        }
        if (logsAutoScrollEnabled && hasNewLogs) {
            container.scrollTop = container.scrollHeight;
        }
    }
    catch (error) {
        console.error('Failed to load logs:', error);
        showToast('Failed to load logs', { type: 'error' });
    }
}
function startLogsRefresh() {
    if (logsRefreshInterval) {
        clearInterval(logsRefreshInterval);
    }
    logsRefreshInterval = window.setInterval(loadLogs, 1000);
}
function stopLogsRefresh() {
    if (logsRefreshInterval) {
        clearInterval(logsRefreshInterval);
        logsRefreshInterval = null;
    }
}
function toggleAutoScroll() {
    logsAutoScrollEnabled = !logsAutoScrollEnabled;
    const btn = document.getElementById('btn-auto-scroll');
    if (btn) {
        btn.textContent = logsAutoScrollEnabled ? '⏸ Pause' : '▶️ Resume';
        btn.classList.toggle('paused', !logsAutoScrollEnabled);
    }
    showToast(`Auto-scroll ${logsAutoScrollEnabled ? 'enabled' : 'disabled'}`, { type: 'info', duration: 1500 });
}
function clearLogs() {
    const container = document.getElementById('log-content');
    if (container)
        container.innerHTML = '';
    lastLogCount = 0;
    // Also clear the actual log file
    invoke('clear_logs').then(result => {
        showToast(String(result), { type: 'success', duration: 1500 });
    }).catch(err => {
        showToast('Failed to clear logs: ' + err, { type: 'error' });
    });
}
// ============================================================================
// Database
// ============================================================================
async function loadDbStats() {
    try {
        const stats = await invoke('get_db_stats');
        batchDOMUpdate([
            () => {
                const dbMessages = document.getElementById('db-messages');
                const dbChannels = document.getElementById('db-channels');
                const dbEntities = document.getElementById('db-entities');
                const dbRag = document.getElementById('db-rag');
                if (dbMessages)
                    dbMessages.textContent = stats.total_messages.toLocaleString();
                if (dbChannels)
                    dbChannels.textContent = stats.active_channels.toString();
                if (dbEntities)
                    dbEntities.textContent = stats.total_entities.toString();
                if (dbRag)
                    dbRag.textContent = stats.rag_memories.toString();
            }
        ]);
        // Load channels and users in parallel
        const [channels, users] = await Promise.all([
            invoke('get_recent_channels', { limit: 10 }),
            invoke('get_top_users', { limit: 10 })
        ]);
        const channelsList = document.getElementById('channels-list');
        if (channelsList) {
            if (channels.length === 0) {
                channelsList.innerHTML = '<p class="no-data">No channels found.</p>';
            }
            else {
                channelsList.innerHTML = '';
                channels.forEach((ch) => {
                    const item = document.createElement('div');
                    item.className = 'data-item';
                    const idSpan = document.createElement('span');
                    idSpan.className = 'data-item-id';
                    idSpan.textContent = String(ch.channel_id);
                    const valSpan = document.createElement('span');
                    valSpan.className = 'data-item-value';
                    valSpan.textContent = `${ch.message_count.toLocaleString()} messages`;
                    item.appendChild(idSpan);
                    item.appendChild(valSpan);
                    channelsList.appendChild(item);
                });
            }
        }
        const usersList = document.getElementById('users-list');
        if (usersList) {
            if (users.length === 0) {
                usersList.innerHTML = '<p class="no-data">No users found.</p>';
            }
            else {
                usersList.innerHTML = '';
                users.forEach((u) => {
                    const item = document.createElement('div');
                    item.className = 'data-item';
                    const idSpan = document.createElement('span');
                    idSpan.className = 'data-item-id';
                    idSpan.textContent = String(u.user_id);
                    const valSpan = document.createElement('span');
                    valSpan.className = 'data-item-value';
                    valSpan.textContent = `${u.message_count.toLocaleString()} messages`;
                    item.appendChild(idSpan);
                    item.appendChild(valSpan);
                    usersList.appendChild(item);
                });
            }
        }
    }
    catch (error) {
        console.error('Failed to load DB stats:', error);
        showToast('Failed to load database stats', { type: 'error' });
    }
}
async function clearHistory() {
    if (!confirm('⚠️ This will permanently delete ALL chat history. Continue?')) {
        return;
    }
    try {
        const count = await invoke('clear_history');
        showToast(`Deleted ${count.toLocaleString()} messages`, { type: 'success' });
        dataCache.invalidate('dbStats');
        loadDbStats();
    }
    catch (error) {
        showToast(String(error), { type: 'error' });
    }
}
// ============================================================================
// Settings UI
// ============================================================================
function loadSettingsUI() {
    const refreshSelect = document.getElementById('refresh-interval');
    if (refreshSelect) {
        refreshSelect.value = settings.refreshInterval.toString();
    }
    const notificationsToggle = document.getElementById('notifications-toggle');
    if (notificationsToggle) {
        notificationsToggle.checked = settings.notifications;
    }
    const userNameInput = document.getElementById('user-name-input');
    if (userNameInput) {
        userNameInput.value = settings.userName === 'You' ? '' : settings.userName;
    }
    // Load AI avatar preview
    const aiAvatarImage = document.getElementById('ai-avatar-image');
    const aiAvatarPlaceholder = document.querySelector('#ai-avatar-preview .avatar-placeholder');
    const aiRemoveBtn = document.getElementById('btn-remove-ai-avatar');
    if (settings.aiAvatar) {
        if (aiAvatarImage) {
            aiAvatarImage.src = settings.aiAvatar;
            aiAvatarImage.classList.add('visible');
        }
        if (aiAvatarPlaceholder)
            aiAvatarPlaceholder.style.display = 'none';
        if (aiRemoveBtn)
            aiRemoveBtn.style.display = 'inline-block';
    }
    else {
        if (aiAvatarImage) {
            aiAvatarImage.src = '';
            aiAvatarImage.classList.remove('visible');
        }
        if (aiAvatarPlaceholder)
            aiAvatarPlaceholder.style.display = 'flex';
        if (aiRemoveBtn)
            aiRemoveBtn.style.display = 'none';
    }
    // Load user avatar preview
    const avatarImage = document.getElementById('avatar-image');
    const avatarPlaceholder = document.querySelector('#avatar-preview .avatar-placeholder');
    const removeBtn = document.getElementById('btn-remove-avatar');
    if (settings.userAvatar) {
        if (avatarImage) {
            avatarImage.src = settings.userAvatar;
            avatarImage.classList.add('visible');
        }
        if (avatarPlaceholder)
            avatarPlaceholder.style.display = 'none';
        if (removeBtn)
            removeBtn.style.display = 'inline-block';
    }
    else {
        if (avatarImage) {
            avatarImage.src = '';
            avatarImage.classList.remove('visible');
        }
        if (avatarPlaceholder)
            avatarPlaceholder.style.display = 'flex';
        if (removeBtn)
            removeBtn.style.display = 'none';
    }
    // Load creator checkbox
    const creatorCheckbox = document.getElementById('creator-toggle');
    if (creatorCheckbox) {
        creatorCheckbox.checked = settings.isCreator;
    }
    // Load profile from server
    if (chatManager?.connected) {
        chatManager.send({ type: 'get_profile' });
    }
}
// Track which avatar we're editing
let currentAvatarTarget = 'user';
function handleAvatarUpload(file, target = 'user') {
    if (!file.type.startsWith('image/')) {
        showToast('Please select an image file', { type: 'error' });
        return;
    }
    if (file.size > 5 * 1024 * 1024) { // 5MB limit for cropping
        showToast('Image must be less than 5MB', { type: 'error' });
        return;
    }
    currentAvatarTarget = target;
    const reader = new FileReader();
    reader.onload = (e) => {
        const dataUrl = e.target?.result;
        openAvatarCropModal(dataUrl);
    };
    reader.readAsDataURL(file);
}
// Avatar Cropper State
let cropState = {
    imageUrl: '',
    zoom: 100,
    offsetX: 0,
    offsetY: 0,
    isDragging: false,
    startX: 0,
    startY: 0,
    imgWidth: 0,
    imgHeight: 0
};
// Store bound functions for proper cleanup
let boundOnDrag = null;
let boundOnDragTouch = null;
let boundEndDrag = null;
function openAvatarCropModal(imageUrl) {
    cropState = {
        imageUrl,
        zoom: 100,
        offsetX: 0,
        offsetY: 0,
        isDragging: false,
        startX: 0,
        startY: 0,
        imgWidth: 0,
        imgHeight: 0
    };
    const modal = document.getElementById('avatar-crop-modal');
    const cropImage = document.getElementById('crop-image');
    const zoomSlider = document.getElementById('crop-zoom');
    if (!modal || !cropImage || !zoomSlider)
        return;
    // Load image to get dimensions
    cropImage.onload = () => {
        const cropArea = document.getElementById('crop-area');
        if (!cropArea)
            return;
        const areaSize = 280;
        const scale = Math.max(areaSize / cropImage.naturalWidth, areaSize / cropImage.naturalHeight);
        cropState.imgWidth = cropImage.naturalWidth * scale;
        cropState.imgHeight = cropImage.naturalHeight * scale;
        // Center the image
        cropState.offsetX = (areaSize - cropState.imgWidth) / 2;
        cropState.offsetY = (areaSize - cropState.imgHeight) / 2;
        updateCropPreview();
    };
    cropImage.src = imageUrl;
    zoomSlider.value = '100';
    modal.style.display = 'flex';
    // Setup event listeners
    setupCropEventListeners();
}
function setupCropEventListeners() {
    const cropArea = document.getElementById('crop-area');
    const zoomSlider = document.getElementById('crop-zoom');
    const saveBtn = document.getElementById('btn-crop-save');
    const cancelBtn = document.getElementById('btn-crop-cancel');
    const closeBtn = document.getElementById('avatar-crop-close');
    const modal = document.getElementById('avatar-crop-modal');
    if (!cropArea || !zoomSlider || !saveBtn || !cancelBtn || !closeBtn || !modal)
        return;
    // Remove old listeners by cloning
    const newCropArea = cropArea.cloneNode(true);
    cropArea.parentNode?.replaceChild(newCropArea, cropArea);
    // Create bound functions for proper cleanup
    boundOnDrag = onDrag;
    boundOnDragTouch = onDragTouch;
    boundEndDrag = endDrag;
    // Mouse/touch drag
    newCropArea.addEventListener('mousedown', startDrag);
    newCropArea.addEventListener('touchstart', startDragTouch, { passive: false });
    document.addEventListener('mousemove', boundOnDrag);
    document.addEventListener('touchmove', boundOnDragTouch, { passive: false });
    document.addEventListener('mouseup', boundEndDrag);
    document.addEventListener('touchend', boundEndDrag);
    // Zoom
    zoomSlider.oninput = () => {
        cropState.zoom = parseInt(zoomSlider.value);
        updateCropPreview();
    };
    // Save
    saveBtn.onclick = () => {
        saveCroppedAvatar();
        closeCropModal();
    };
    // Cancel/Close
    cancelBtn.onclick = closeCropModal;
    closeBtn.onclick = closeCropModal;
    modal.onclick = (e) => {
        if (e.target === modal)
            closeCropModal();
    };
}
function startDrag(e) {
    cropState.isDragging = true;
    cropState.startX = e.clientX - cropState.offsetX;
    cropState.startY = e.clientY - cropState.offsetY;
}
function startDragTouch(e) {
    e.preventDefault();
    cropState.isDragging = true;
    const touch = e.touches[0];
    cropState.startX = touch.clientX - cropState.offsetX;
    cropState.startY = touch.clientY - cropState.offsetY;
}
function onDrag(e) {
    if (!cropState.isDragging)
        return;
    cropState.offsetX = e.clientX - cropState.startX;
    cropState.offsetY = e.clientY - cropState.startY;
    updateCropPreview();
}
function onDragTouch(e) {
    if (!cropState.isDragging)
        return;
    e.preventDefault();
    const touch = e.touches[0];
    cropState.offsetX = touch.clientX - cropState.startX;
    cropState.offsetY = touch.clientY - cropState.startY;
    updateCropPreview();
}
function endDrag() {
    cropState.isDragging = false;
}
function updateCropPreview() {
    const cropImage = document.getElementById('crop-image');
    if (!cropImage)
        return;
    const scale = cropState.zoom / 100;
    const width = cropState.imgWidth * scale;
    const height = cropState.imgHeight * scale;
    cropImage.style.width = `${width}px`;
    cropImage.style.height = `${height}px`;
    cropImage.style.left = `${cropState.offsetX}px`;
    cropImage.style.top = `${cropState.offsetY}px`;
}
function saveCroppedAvatar() {
    const cropImage = document.getElementById('crop-image');
    if (!cropImage)
        return;
    // Create canvas to crop the circular area
    const canvas = document.createElement('canvas');
    const size = 200; // Output size
    canvas.width = size;
    canvas.height = size;
    const ctx = canvas.getContext('2d');
    if (!ctx)
        return;
    // Calculate crop area (center of crop-area is 140,140 and circle is 200x200)
    const areaCenter = 140;
    const circleRadius = 100;
    const scale = cropState.zoom / 100;
    const imgWidth = cropState.imgWidth * scale;
    const imgHeight = cropState.imgHeight * scale;
    // Calculate source position relative to image
    const srcX = (areaCenter - circleRadius - cropState.offsetX) / scale * (cropImage.naturalWidth / cropState.imgWidth);
    const srcY = (areaCenter - circleRadius - cropState.offsetY) / scale * (cropImage.naturalHeight / cropState.imgHeight);
    const srcSize = (circleRadius * 2) / scale * (cropImage.naturalWidth / cropState.imgWidth);
    // Draw circular clip
    ctx.beginPath();
    ctx.arc(size / 2, size / 2, size / 2, 0, Math.PI * 2);
    ctx.closePath();
    ctx.clip();
    // Draw image
    ctx.drawImage(cropImage, srcX, srcY, srcSize, srcSize, 0, 0, size, size);
    // Get data URL
    const croppedDataUrl = canvas.toDataURL('image/png');
    // Save to appropriate setting based on target
    if (currentAvatarTarget === 'ai') {
        settings.aiAvatar = croppedDataUrl;
        saveSettings();
        // Update AI avatar preview
        const avatarImage = document.getElementById('ai-avatar-image');
        const avatarPlaceholder = document.querySelector('#ai-avatar-preview .avatar-placeholder');
        const removeBtn = document.getElementById('btn-remove-ai-avatar');
        if (avatarImage) {
            avatarImage.src = croppedDataUrl;
            avatarImage.classList.add('visible');
        }
        if (avatarPlaceholder)
            avatarPlaceholder.style.display = 'none';
        if (removeBtn)
            removeBtn.style.display = 'inline-block';
        showToast('AI Avatar updated! 🤖', { type: 'success' });
    }
    else {
        settings.userAvatar = croppedDataUrl;
        saveSettings();
        // Update user avatar preview
        const avatarImage = document.getElementById('avatar-image');
        const avatarPlaceholder = document.querySelector('#avatar-preview .avatar-placeholder');
        const removeBtn = document.getElementById('btn-remove-avatar');
        if (avatarImage) {
            avatarImage.src = croppedDataUrl;
            avatarImage.classList.add('visible');
        }
        if (avatarPlaceholder)
            avatarPlaceholder.style.display = 'none';
        if (removeBtn)
            removeBtn.style.display = 'inline-block';
        showToast('Avatar updated! 🎉', { type: 'success' });
    }
    // Refresh chat to show new avatar
    if (chatManager) {
        chatManager.renderMessages();
    }
}
function closeCropModal() {
    const modal = document.getElementById('avatar-crop-modal');
    if (modal)
        modal.style.display = 'none';
    // Clean up listeners using stored bound functions
    if (boundOnDrag) {
        document.removeEventListener('mousemove', boundOnDrag);
        boundOnDrag = null;
    }
    if (boundEndDrag) {
        document.removeEventListener('mouseup', boundEndDrag);
        document.removeEventListener('touchend', boundEndDrag);
        boundEndDrag = null;
    }
    if (boundOnDragTouch) {
        document.removeEventListener('touchmove', boundOnDragTouch);
        boundOnDragTouch = null;
    }
}
function removeAvatar(target = 'user') {
    if (target === 'ai') {
        settings.aiAvatar = '';
        saveSettings();
        const avatarImage = document.getElementById('ai-avatar-image');
        const avatarPlaceholder = document.querySelector('#ai-avatar-preview .avatar-placeholder');
        const removeBtn = document.getElementById('btn-remove-ai-avatar');
        if (avatarImage) {
            avatarImage.src = '';
            avatarImage.classList.remove('visible');
        }
        if (avatarPlaceholder)
            avatarPlaceholder.style.display = 'flex';
        if (removeBtn)
            removeBtn.style.display = 'none';
        showToast('AI Avatar removed', { type: 'info' });
    }
    else {
        settings.userAvatar = '';
        saveSettings();
        const avatarImage = document.getElementById('avatar-image');
        const avatarPlaceholder = document.querySelector('#avatar-preview .avatar-placeholder');
        const removeBtn = document.getElementById('btn-remove-avatar');
        if (avatarImage) {
            avatarImage.src = '';
            avatarImage.classList.remove('visible');
        }
        if (avatarPlaceholder)
            avatarPlaceholder.style.display = 'flex';
        if (removeBtn)
            removeBtn.style.display = 'none';
        showToast('Avatar removed', { type: 'info' });
    }
    // Refresh chat
    if (chatManager) {
        chatManager.renderMessages();
    }
}
function saveProfileToAI() {
    const displayName = document.getElementById('user-name-input')?.value?.trim() || 'User';
    const bio = document.getElementById('user-bio-input')?.value?.trim() || '';
    const preferences = document.getElementById('user-preferences-input')?.value?.trim() || '';
    const isCreator = document.getElementById('creator-toggle')?.checked || false;
    if (chatManager?.connected) {
        chatManager.send({
            type: 'save_profile',
            profile: { display_name: displayName, bio, preferences, is_creator: isCreator }
        });
        // Also update local settings
        settings.userName = displayName;
        settings.isCreator = isCreator;
        saveSettings();
    }
    else {
        showToast('Not connected to AI server', { type: 'error' });
    }
}
// ============================================================================
// Helpers
// ============================================================================
async function openFolder(type) {
    let path;
    try {
        if (type === 'logs') {
            path = await invoke('get_logs_path');
        }
        else if (type === 'data') {
            path = await invoke('get_data_path');
        }
        else {
            path = type; // Allow direct path
        }
        await invoke('open_folder', { path });
    }
    catch (error) {
        showToast(`Failed to open folder: ${error}`, { type: 'error' });
    }
}
function loadAllData() {
    dataCache.clear();
    updateStatus();
    loadLogs();
    loadDbStats();
}
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
// ============================================================================
// Export for global access (Tauri needs these on window)
// ============================================================================
window.toggleAutoScroll = toggleAutoScroll;
window.clearLogs = clearLogs;
window.clearHistory = clearHistory;
window.openFolder = openFolder;
window.loadLogs = loadLogs;
window.toggleTheme = toggleTheme;
window.showToast = showToast;
window.chatManager = null; // Updated in initChatManager()
window.showPage = switchPage; // Alias for HTML onclick handlers
window.startBot = startBot;
//# sourceMappingURL=app.js.map