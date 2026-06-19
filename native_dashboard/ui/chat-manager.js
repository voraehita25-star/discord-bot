/**
 * AI Chat Manager - WebSocket Client
 * Extracted from app.ts for modularity.
 */
import { invoke, errorLogger, escapeHtml, isSafeAvatarUrl, safeAvatarUrl, showToast, showConfirmDialog, settings, saveSettings, icon, normalizeSqliteUtc, } from './shared.js';
import { highlightCodeBlocks } from './chat/prism.js';
import { formatMessage, stripThinkTags } from './chat/formatter.js';
import { ChatSearch } from './chat/search.js';
import { promptExportFormat } from './chat/export-picker.js';
import { WebSocketClient } from './chat/ws-client.js';
import { renderMessagesHtml, VIRT_WINDOW_SIZE } from './chat/message-template.js';
import { ConversationList } from './chat/conversation-list.js';
import { ImageAttachManager } from './chat/image-attach.js';
import { DocumentAttachManager } from './chat/document-attach.js';
import { ContextWindowIndicator } from './chat/context-window.js';
import { ConversationModals } from './chat/conversation-modals.js';
// Error-frame `scope` values the backend tags onto AI-History-originated
// failures (the five ai-history handlers send scope:'ai_history'; the WS
// rate-limiter echoes the rejected wire msg type). Errors carrying one of
// these must NOT run the chat-stream teardown — they belong to the History
// page, not to an in-flight chat response.
const HISTORY_ERROR_SCOPES = new Set([
    'ai_history',
    'list_ai_channels',
    'load_ai_history',
    'edit_ai_history_message',
    'delete_ai_history_message',
    'restore_ai_history_message',
]);
function chatFileIconFor(kind, name) {
    const ext = name.slice(name.lastIndexOf('.') + 1).toLowerCase();
    if (ext === 'pdf')
        return icon('file');
    if (ext === 'docx')
        return icon('file');
    if (kind === 'text') {
        if (['json', 'yaml', 'yml', 'toml'].includes(ext))
            return icon('chip');
        if (['md', 'markdown'].includes(ext))
            return icon('pencil');
        if (['csv', 'tsv', 'xml'].includes(ext))
            return icon('gauge');
    }
    return icon('file');
}
/** Coerce an untrusted char_count/page_count from a `conversation_documents`
 * WS frame to a safe finite number (non-numeric/NaN/Infinity/null -> 0).
 *
 * The frame is a TYPE CAST with no runtime validation, so the field can be a
 * string/object/null. A bare `Number(x) || 0` is NOT safe here: Number() on a
 * null-prototype object (Object.create(null)) THROWS "Cannot convert object to
 * primitive value", which would abort renderChatFilesModal's docs.map and blank
 * the Files modal — the exact bug class the file_kind/filename String() coercion
 * fixed. typeof + isFinite never throws and matches the guard the other
 * documents-frame handler already uses. */
function chatFileCount(value) {
    return typeof value === 'number' && isFinite(value) ? value : 0;
}
/** Conservative PDF reflow: merges only obvious per-glyph orphan lines
 * (1-4 Thai / 1-3 Latin chars sandwiched between longer lines). Mirrors
 * the Python backend's `_rejoin_pdf_lines` which now runs alongside
 * `extraction_mode="layout"` — the combination preserves real line
 * breaks from the PDF while cleaning up orphan glyphs.
 *
 * Intentionally NOT aggressive: the previous implementation merged
 * every prose line into long paragraphs and stripped all spaces between
 * Thai characters, which destroyed the layout-mode output the backend
 * now produces. If a user's file really has legacy-mangled data, they
 * should delete the document memory entry and re-upload — the fresh
 * extraction with layout mode will produce correct output.
 */
function reflowPdfText(text) {
    if (!text)
        return text;
    const CONTINUOUS = '฀-๿຀-໿ក-៿぀-ヿㇰ-ㇿ一-鿿㐀-䶿豈-﫿가-힯';
    const reContinuous = new RegExp('[' + CONTINUOUS + ']');
    const reHeading = /^#{1,6}\s/;
    const reList = /^(?:[-*•◦▪■]\s|\d+[.)]\s|>\s?)/;
    const reSeparator = /^[\s\-⎯—━═*._=·‧…]+$/;
    const reHasSepChar = /[\-⎯—━═_=]/;
    const isStructural = (line) => {
        const s = line.trim();
        if (!s)
            return false;
        if (reHeading.test(s))
            return true;
        if (reList.test(s))
            return true;
        if (reSeparator.test(s) && reHasSepChar.test(s))
            return true;
        return false;
    };
    const isShortOrphan = (stripped, resultSoFar, allLines, idx) => {
        if (isStructural(stripped))
            return false;
        const first = stripped[0];
        const maxLen = reContinuous.test(first) ? 4 : 3;
        if (stripped.length > maxLen)
            return false;
        if (!resultSoFar.length || !resultSoFar[resultSoFar.length - 1].trim())
            return false;
        const prevStripped = resultSoFar[resultSoFar.length - 1].trim();
        if (isStructural(prevStripped))
            return false;
        if (prevStripped.length <= maxLen)
            return false;
        if (idx + 1 >= allLines.length)
            return true;
        const nextStripped = allLines[idx + 1].trim();
        if (!nextStripped)
            return true;
        if (isStructural(nextStripped))
            return false;
        return nextStripped.length > maxLen;
    };
    const lines = text.split('\n');
    const result = [];
    for (let i = 0; i < lines.length; i++) {
        const current = lines[i];
        const stripped = current.trim();
        if (!stripped) {
            result.push('');
            continue;
        }
        if (isShortOrphan(stripped, result, lines, i)) {
            const prev = result[result.length - 1];
            const last = prev[prev.length - 1] || '';
            const first = stripped[0];
            let sep = '';
            if (!(reContinuous.test(last) && reContinuous.test(first))) {
                sep = (prev && !prev.endsWith(' ') && !prev.endsWith('	')) ? ' ' : '';
            }
            result[result.length - 1] = prev + sep + stripped;
        }
        else {
            result.push(current);
        }
    }
    let out = result.join('\n');
    out = out.replace(/\n{3,}/g, '\n\n');
    return out.trim();
}
function formatChatFileDate(iso) {
    if (!iso)
        return '';
    try {
        // SQLite naive timestamps are UTC — append Z so JS doesn't misread
        // them as local time (would render hours off in non-UTC zones).
        const d = new Date(normalizeSqliteUtc(iso));
        if (Number.isNaN(d.getTime()))
            return iso;
        // Short absolute format — works in any locale without being verbose.
        // e.g. "Apr 24, 15:32". Users mainly care about "was this today".
        return d.toLocaleString(undefined, {
            month: 'short', day: 'numeric',
            hour: '2-digit', minute: '2-digit',
        });
    }
    catch {
        return iso;
    }
}
// Human-readable labels for AI providers shown in the provider <select>s. The
// previous inline `provider === 'gemini' ? 'Gemini' : 'Claude'` mislabelled any
// third provider as "Claude"; this map + capitalize fallback keeps known
// providers branded correctly while degrading gracefully for unknown ids.
const PROVIDER_LABELS = {
    gemini: 'Gemini',
    claude: 'Claude',
};
/** Display label for a provider id — mapped name, or the id capitalized. */
function providerLabel(provider) {
    const mapped = PROVIDER_LABELS[provider];
    if (mapped)
        return mapped;
    if (!provider)
        return provider;
    return provider.charAt(0).toUpperCase() + provider.slice(1);
}
// ============================================================================
// Chat Manager
// ============================================================================
export class ChatManager {
    // Cap local message history to bound DOM size in long sessions; rendered
    // history is also capped server-side at 20 messages per request.
    static MAX_LOCAL_MESSAGES = 200;
    currentConversation = null;
    conversations = [];
    messages = [];
    selectedRole = 'general';
    isStreaming = false;
    presets = {};
    currentMode = ''; // Store current mode for the streaming message
    // ``localStorage`` is tampering-trivial via devtools, so validate the
    // restored value against the allowlist of known providers and fall
    // back to ``gemini`` on garbage. Before this, a hand-edited entry
    // like ``{"$": 1}`` would propagate through every WS frame as the
    // ``ai_provider`` field and confuse the server-side dispatcher.
    aiProvider = (() => {
        const stored = localStorage.getItem('dashboard_ai_provider');
        const allowed = new Set(['gemini', 'claude']);
        return stored && allowed.has(stored) ? stored : 'gemini';
    })();
    availableProviders = ['gemini']; // Available providers from server
    thinkingEnabled = localStorage.getItem('dashboard_thinking') === 'true'; // Persist thinking preference
    isEditStreaming = false; // True when AI edit streaming is in progress
    editTargetMessageId = null; // DB ID of message being AI-edited
    editStreamContent = ''; // Accumulated edit stream content
    // Id of the conversation a stream belongs to, captured at stream_start.
    // If the user switches conversations mid-stream, late chunk/stream_end
    // frames for the OLD conversation must not mutate the NEW one.
    streamingConversationId = null;
    // Set true when the current turn is torn down by an `error` frame. Guards
    // against a server that emits BOTH error and a late stream_end for the same
    // turn: the error handler nulls streamingConversationId, so the stream_end
    // mid-switch guard is skipped and the non-edit branch would otherwise fall
    // through to finalizeStreamingMessage and push a phantom assistant bubble.
    // Reset on stream_start (a fresh turn begins).
    streamErrored = false;
    // Buffered partial of the in-progress RESPONSE stream, kept independently of
    // the #streaming-message DOM so it survives a conversation switch. The
    // partial isn't persisted to the DB until stream_end, so without this,
    // navigating away from a streaming chat and back showed an empty view.
    // ``restoreStreamingBubble`` replays these into a fresh bubble on return.
    // Stored as arrays + join()'d on demand to keep append O(1) (same rationale
    // as the appendChunk text-node approach).
    streamPartialChunks = [];
    streamPartialThinkingChunks = [];
    streamThinkingActive = false;
    // rAF id for pending edit-stream textContent flush. We accumulate chunks
    // into ``editStreamContent`` and only push to the DOM once per frame to
    // avoid O(n²) string concatenation costs as the response grows.
    editStreamRafId = null;
    userScrolledUp = false; // True when user manually scrolls up during streaming
    draftSaveTimer = null; // Debounced localStorage draft writer
    // Most-recent conversation id passed to ``loadConversation``. The
    // ``conversation_loaded`` WS handler compares against this to drop
    // stale frames when the user switches conversations rapidly.
    pendingConversationLoadId = null;
    // AI History page delegate (history-manager.ts), wired by app.ts after
    // construction. ChatManager owns the single dashboard WebSocket, so the
    // incoming ai_* frames are forwarded to it instead of being handled here.
    historyManager = null;
    enrichConversation(conversation) {
        const preset = this.presets[conversation.role_preset] || {};
        return {
            ...conversation,
            role_name: conversation.role_name || preset.name || conversation.role_preset || 'AI',
            role_emoji: conversation.role_emoji || preset.emoji || '\uD83E\uDD16',
            role_color: conversation.role_color || preset.color,
        };
    }
    async loadConversationsFallback() {
        try {
            const conversations = await invoke('get_dashboard_conversations_native', { limit: 50 });
            this.conversations = (conversations || []).map(conversation => this.enrichConversation(conversation));
            this.renderConversationList();
        }
        catch (e) {
            errorLogger.log('NATIVE_CONVERSATIONS_LOAD_ERROR', 'Failed to load dashboard conversations from SQLite fallback', String(e));
        }
    }
    async loadConversationFallback(id) {
        try {
            const detail = await invoke('get_dashboard_conversation_detail_native', {
                conversationId: id,
            });
            // Drop a late-arriving fallback load if the user already switched to
            // a different conversation while this invoke was in flight. Mirrors
            // the ``conversation_loaded`` WS-path guard so the offline/SQLite
            // path can't replace the now-current view with a stale one.
            if (this.pendingConversationLoadId !== null && this.pendingConversationLoadId !== id) {
                return;
            }
            if (!detail.conversation) {
                errorLogger.log('NATIVE_CONVERSATION_LOAD_ERROR', `Conversation ${id} not found in SQLite fallback`);
                showToast('Conversation not found', { type: 'error' });
                return;
            }
            this.currentConversation = this.enrichConversation(detail.conversation);
            this.messages = (detail.messages || []);
            this.showChatContainer();
            this.updateChatHeader();
            this.renderMessages();
            if (this.currentConversation?.id) {
                this.restoreContextWindowIndicator(this.currentConversation.id);
            }
            else {
                this.resetContextWindowIndicator();
            }
            this.renderConversationList();
        }
        catch (e) {
            errorLogger.log('NATIVE_CONVERSATION_LOAD_ERROR', `Failed to load dashboard conversation ${id} from SQLite fallback`, String(e));
            showToast('Failed to load conversation history', { type: 'error' });
        }
    }
    // WebSocket lifecycle (connect/disconnect/send/reconnect/ping) now lives
    // in ./chat/ws-client.ts. ChatManager holds one WebSocketClient and exposes
    // the same method surface (connect, disconnect, send, scheduleReconnect) +
    // the same read-only fields (ws, connected, reconnectAttempts) so all call
    // sites in this file keep working without rewrite.
    wsClient = new WebSocketClient({
        onMessage: (data) => this.handleMessage(data),
        onConnectStateChange: (connected) => this.updateConnectionStatus(connected),
        onDisconnect: () => {
            // Reset streaming state to prevent chat input from being permanently locked.
            if (this.isStreaming) {
                const wasEditStreaming = this.isEditStreaming;
                this.isStreaming = false;
                this.isEditStreaming = false;
                this.editTargetMessageId = null;
                this.editStreamContent = '';
                // Stream is dead on disconnect — drop the guard + partial buffers
                // so a reconnect + switch can't replay a stale half-response.
                this.streamingConversationId = null;
                this.clearStreamBuffers();
                this.setInputEnabled(true);
                // Re-enable auto-scroll (only stream_start/end reset this; a
                // mid-stream disconnect left it stuck on for the session).
                this.userScrolledUp = false;
                if (wasEditStreaming) {
                    // /edit stream uses an in-place .edit-streaming-text on an
                    // existing message rather than #streaming-message, so the
                    // generic stuckMsg.remove() below misses it. Restore the
                    // affected message to its normal display state.
                    document.querySelectorAll('.chat-message.streaming').forEach(el => {
                        el.classList.remove('streaming');
                        const actions = el.querySelector('.message-actions');
                        if (actions)
                            actions.style.display = '';
                    });
                    // Re-render to drop the typing indicator + restore original
                    // content from `this.messages`.
                    this.renderMessages();
                }
                const stuckMsg = document.getElementById('streaming-message');
                if (stuckMsg)
                    stuckMsg.remove();
            }
        },
    });
    // Field-style forwarders so existing call sites (this.ws, this.connected, etc.)
    // keep working. TS getters are fine here since the fields were public before.
    get ws() { return this.wsClient.ws; }
    get connected() { return this.wsClient.connected; }
    get reconnectAttempts() { return this.wsClient.reconnectAttempts; }
    connect() {
        this.loadTokenUsageCache();
        this.wsClient.connect();
    }
    disconnect() { this.wsClient.disconnect(); }
    send(data) { return this.wsClient.send(data); }
    handleMessage(data) {
        switch (data.type) {
            case 'connected':
                this.presets = data.presets || {};
                // ws-client already sends `{type:'auth'}` in onopen — sending
                // it a second time on the server's `connected` event was
                // duplicative and could be interpreted as a protocol error.
                // Just verify a token exists when the server requires auth.
                if (data.requires_auth && !this.wsClient.token) {
                    errorLogger.log('WEBSOCKET_AUTH_MISSING', 'Server requires dashboard auth but no token was loaded');
                    showToast('AI chat auth token is missing. Check DASHBOARD_WS_TOKEN.', { type: 'error' });
                    break;
                }
                // Update available AI providers from server
                if (data.available_providers) {
                    this.availableProviders = data.available_providers;
                    // Use saved preference if valid, otherwise fall back to server default
                    const saved = localStorage.getItem('dashboard_ai_provider');
                    if (saved && this.availableProviders.includes(saved)) {
                        this.aiProvider = saved;
                    }
                    else {
                        this.aiProvider = data.default_provider || this.availableProviders[0] || 'gemini';
                        // Persist the resolved default so the field initializer can
                        // restore it next launch instead of falling back to 'gemini'.
                        try {
                            localStorage.setItem('dashboard_ai_provider', this.aiProvider);
                        }
                        catch {
                            // localStorage write failures are non-fatal — the
                            // connected handler re-derives the provider each session.
                        }
                    }
                    this.updateProviderSelects();
                }
                this.listConversations();
                // Re-fetch the OPEN conversation after a (re)connect. A reconnect
                // that interrupts a response stream drops the in-flight assistant
                // chunks (the disconnect handler clears the streaming buffers), but
                // the backend persists the final assistant message once the turn
                // completes server-side. Re-issuing load_conversation pulls that
                // persisted final message back so the user isn't left staring at a
                // half-written / vanished answer. Guard with pendingConversationLoadId
                // so the conversation_loaded race-drop in its handler treats this as
                // the current request (and a rapid user switch still wins).
                {
                    // Prefer an already-pending switch target over the
                    // currently-shown conversation: if the user was switching to
                    // B when the socket dropped, reload B (not the stale current
                    // A) and don't drop B's pending request.
                    const reloadId = this.pendingConversationLoadId ?? this.currentConversation?.id ?? null;
                    if (reloadId !== null) {
                        this.pendingConversationLoadId = reloadId;
                        this.send({ type: 'load_conversation', id: reloadId });
                    }
                }
                // Re-request the API-failover endpoint list on every connect,
                // including reconnects. app.ts only fires get_api_endpoints once
                // per page load, so after a WS drop/reconnect the failover panel
                // would otherwise stay stale until a full page reload.
                this.send({ type: 'get_api_endpoints' });
                // Let the AI History page flush a channels-list request that
                // was queued while the socket was down (incl. reconnects).
                this.historyManager?.onConnected();
                break;
            case 'conversations_list':
                this.conversations = (data.conversations || [])
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
                    this.currentConversation = this.enrichConversation(data);
                    this.aiProvider = data.ai_provider || this.aiProvider;
                }
                else {
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
            case 'conversation_loaded': {
                // Guard against a race when the user switches conversations
                // rapidly: A's load frame can arrive AFTER B was opened and
                // would otherwise replace the now-current B's view. Compare
                // the incoming frame's id to the conversation we last asked
                // for; if it doesn't match, drop the frame.
                if (!data.conversation || typeof data.conversation !== 'object') {
                    console.error('Invalid conversation_loaded data (missing conversation):', data);
                    break;
                }
                const incoming = this.enrichConversation(data.conversation);
                const requestedId = this.pendingConversationLoadId;
                if (requestedId !== null && requestedId !== incoming.id) {
                    break;
                }
                // An EDIT stream edits an existing message in-place and can't be
                // cleanly re-rendered after a switch, so abandon it (it sets
                // isStreaming too, so clear both). A normal RESPONSE stream is
                // instead PRESERVED: isStreaming / streamingConversationId and the
                // buffered partial are kept so that returning to the still-streaming
                // conversation can replay the live answer (see restoreStreamingBubble
                // below). Chunks keep buffering regardless of which view is open.
                if (this.isEditStreaming) {
                    this.isStreaming = false;
                    this.isEditStreaming = false;
                    this.editTargetMessageId = null;
                    this.editStreamContent = '';
                    this.streamingConversationId = null;
                    this.clearStreamBuffers();
                    this.setInputEnabled(true);
                }
                this.currentConversation = incoming;
                this.aiProvider = this.currentConversation.ai_provider || this.aiProvider;
                this.messages = data.messages || [];
                // Reset virtualization window when switching conversations.
                this.visibleMessageCount = VIRT_WINDOW_SIZE;
                this.showChatContainer();
                this.updateChatHeader();
                this.renderMessages();
                // If we navigated BACK to a conversation whose response is still
                // streaming, re-create the in-progress bubble from the buffered
                // partial so the live answer is visible again. Otherwise keep the
                // input locked while a stream is still running elsewhere (single
                // stream at a time, matching the send() gate).
                if (this.isStreaming && !this.isEditStreaming
                    && this.streamingConversationId !== null
                    && this.streamingConversationId === incoming.id) {
                    this.restoreStreamingBubble();
                    this.setInputEnabled(false);
                }
                else if (!this.isEditStreaming) {
                    this.setInputEnabled(!this.isStreaming);
                }
                if (data.token_usage) {
                    this.updateContextWindowIndicator(data.token_usage);
                }
                else {
                    this.restoreContextWindowIndicator(this.currentConversation.id);
                }
                this.renderConversationList();
                // Refresh the 📎 badge count for the newly-opened conversation.
                // A fresh list request is cheap (metadata-only SQL + WS frame)
                // and keeps the badge accurate without adding payload to the
                // conversation_loaded frame itself.
                this.updateChatFilesBadge(0);
                this.refreshChatFilesBadge();
                break;
            }
            case 'stream_start':
                this.isStreaming = true;
                // Fresh turn — clear the error teardown guard so this stream's
                // stream_end is allowed to finalize normally.
                this.streamErrored = false;
                // Bind the stream to the SERVER-provided conversation id —
                // the user can switch conversations between sendMessage()
                // and stream_start (seconds on the CLI backend while it
                // extracts attachments), and binding to the currently-open
                // conversation mis-attributed the whole stream.
                this.streamingConversationId =
                    typeof data.conversation_id === 'string'
                        ? data.conversation_id
                        : (this.currentConversation?.id ?? null);
                // Fresh stream — reset the cross-switch partial buffers.
                this.clearStreamBuffers();
                this.currentThinking = '';
                this.userScrolledUp = false; // Reset scroll lock on new stream
                // Narrow with ``typeof`` instead of an unchecked ``as`` cast so a
                // malformed frame from the bot can't poison ``currentMode`` with
                // a non-string (e.g. ``null`` becoming the literal "null").
                this.currentMode = typeof data.mode === 'string' ? data.mode : '';
                if (data.is_edit && typeof data.target_message_id === 'number') {
                    // AI edit mode: prepare to update existing message in-place
                    this.isEditStreaming = true;
                    this.editTargetMessageId = data.target_message_id;
                    this.editStreamContent = '';
                    this.startEditStreamingUI(this.editTargetMessageId);
                }
                else {
                    // Reuse + reset an existing bubble whether this is a
                    // failover retry OR the CLI stale-session retry (which
                    // re-sends a plain stream_start and expects the rendered
                    // chunks to be cleared). Unconditionally appending here
                    // created a SECOND #streaming-message div: the duplicate
                    // id made every chunk land in the stale first bubble.
                    const existingMsg = document.getElementById('streaming-message');
                    if (existingMsg) {
                        const thinkingContainer = existingMsg.querySelector('.thinking-container');
                        const thinkingContent = existingMsg.querySelector('.thinking-content');
                        const streamingText = existingMsg.querySelector('.streaming-text');
                        if (thinkingContainer) {
                            thinkingContainer.style.display = 'none';
                        }
                        if (thinkingContent) {
                            thinkingContent.textContent = '';
                        }
                        if (streamingText) {
                            streamingText.textContent = '';
                        }
                    }
                    else if (this.streamingConversationId === (this.currentConversation?.id ?? null)) {
                        // Only draw the bubble when this stream belongs to the
                        // conversation on screen. If the user already switched
                        // away (server bound the stream to another id), draw
                        // nothing — chunks keep buffering and restoreStreamingBubble
                        // replays them when they return, mirroring the
                        // conversation_loaded path. Drawing here would paint the
                        // wrong room's answer into the open conversation.
                        this.appendStreamingMessage(data.mode || '');
                    }
                }
                this.setInputEnabled(false);
                break;
            case 'thinking_start':
                this.showThinkingIndicator();
                break;
            case 'thinking_chunk':
                this.appendThinkingChunk(typeof data.content === 'string' ? data.content : '');
                break;
            case 'thinking_end':
                this.finalizeThinking(typeof data.full_thinking === 'string' ? data.full_thinking : '');
                break;
            case 'chunk': {
                // Guard the cast: a missing `content` field (protocol drift /
                // failover) must not inject a literal "undefined" text node or
                // throw downstream in stripThinkTags.
                const chunkText = typeof data.content === 'string' ? data.content : '';
                if (this.isEditStreaming) {
                    this.appendEditStreamChunk(chunkText);
                }
                else {
                    this.appendChunk(chunkText);
                }
                break;
            }
            case 'stream_end':
                // Drop a stream_end for a conversation the user has navigated
                // away from (mid-stream switch) — otherwise full_response would
                // be appended into the now-current (wrong) conversation.
                if (this.streamingConversationId !== null &&
                    this.streamingConversationId !== (this.currentConversation?.id ?? null)) {
                    this.streamingConversationId = null;
                    this.isStreaming = false;
                    this.isEditStreaming = false;
                    this.editTargetMessageId = null;
                    this.editStreamContent = '';
                    this.clearStreamBuffers();
                    // Sweep up a streaming bubble that may have been drawn into
                    // the now-current (wrong) conversation before the switch.
                    const strayBubble = document.getElementById('streaming-message');
                    if (strayBubble)
                        strayBubble.remove();
                    this.setInputEnabled(true);
                    break;
                }
                this.streamingConversationId = null;
                this.isStreaming = false;
                this.userScrolledUp = false; // Reset scroll lock when stream ends
                if (this.isEditStreaming && data.is_edit) {
                    // AI edit complete: finalize the edited message
                    this.finalizeEditStreaming(typeof data.full_response === 'string' ? data.full_response : '', data.target_message_id);
                    this.isEditStreaming = false;
                    this.editTargetMessageId = null;
                    this.editStreamContent = '';
                    this.setInputEnabled(true);
                    showToast('AI edit complete', { type: 'success' });
                    break;
                }
                if (this.isEditStreaming) {
                    // Server sent stream_end without is_edit while we were in
                    // edit mode (protocol mismatch / failover). Don't fall
                    // through to finalizeStreamingMessage — that would push a
                    // phantom assistant bubble. Clear edit state, restore
                    // original content, and surface the failure.
                    this.isEditStreaming = false;
                    this.editTargetMessageId = null;
                    this.editStreamContent = '';
                    this.setInputEnabled(true);
                    this.renderMessages();
                    showToast('AI edit was interrupted', { type: 'error' });
                    break;
                }
                if (data.is_edit) {
                    // A late stream_end for an edit whose state was already torn
                    // down — e.g. the user switched conversations mid-edit, which
                    // clears isEditStreaming AND nulls streamingConversationId, so
                    // neither the mid-switch guard nor the isEditStreaming branches
                    // above caught it. Discard it; falling through would push the
                    // edited text as a phantom assistant bubble in the now-open
                    // conversation.
                    this.clearStreamBuffers();
                    this.setInputEnabled(true);
                    break;
                }
                if (this.streamErrored) {
                    // The turn was already torn down by an `error` frame for this
                    // same turn (the error handler nulled streamingConversationId,
                    // so the mid-switch guard above was skipped). A late, non-edit
                    // stream_end here would otherwise fall through and push a
                    // phantom assistant bubble. Discard it; the error handler
                    // already cleared buffers, removed #streaming-message, and
                    // re-enabled the input.
                    this.streamErrored = false;
                    this.clearStreamBuffers();
                    this.setInputEnabled(true);
                    break;
                }
                this.finalizeStreamingMessage(typeof data.full_response === 'string' ? data.full_response : '');
                this.clearStreamBuffers();
                // Backfill DB IDs so newly-sent messages become editable/deletable
                if (data.assistant_message_id) {
                    const lastMsg = this.messages[this.messages.length - 1];
                    if (lastMsg && lastMsg.role === 'assistant' && !lastMsg.id) {
                        lastMsg.id = data.assistant_message_id;
                    }
                }
                if (data.user_message_id) {
                    for (let i = this.messages.length - 1; i >= 0; i--) {
                        if (this.messages[i].role === 'user' && !this.messages[i].id) {
                            this.messages[i].id = data.user_message_id;
                            break;
                        }
                    }
                }
                if (data.user_message_id || data.assistant_message_id) {
                    this.renderMessages();
                }
                // Update context window usage indicator
                if (data.token_usage) {
                    this.updateContextWindowIndicator(data.token_usage);
                }
                this.setInputEnabled(true);
                this.listConversations(); // Refresh sidebar message count
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
                this.contextWindow.forget(data.id); // forget() saves internally
                this.renderConversationList();
                if (this.currentConversation?.id === data.id) {
                    this.currentConversation = null;
                    this.hideChatContainer();
                }
                showToast('Conversation deleted', { type: 'success' });
                break;
            case 'conversation_starred':
                {
                    const conv = this.conversations.find(c => c.id === data.id);
                    if (conv)
                        conv.is_starred = data.starred;
                    // Also update currentConversation if it's the same one
                    if (this.currentConversation && this.currentConversation.id === data.id) {
                        this.currentConversation.is_starred = data.starred;
                    }
                    this.renderConversationList();
                    this.updateStarButton();
                }
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
            case 'message_edited':
                {
                    const editedId = data.message_id;
                    const editedContent = data.content;
                    const shouldRegenerate = data.regenerate;
                    // Update local message
                    const editedMsg = this.messages.find(m => m.id === editedId);
                    if (editedMsg)
                        editedMsg.content = editedContent;
                    // Preserve scroll position so user stays where they are
                    const chatEl = document.getElementById('chat-messages');
                    const savedPos = chatEl?.scrollTop ?? 0;
                    if (shouldRegenerate && editedMsg) {
                        // Remove all messages after the edited one
                        const editedIdx = this.messages.indexOf(editedMsg);
                        this.messages = this.messages.slice(0, editedIdx + 1);
                        this.renderMessages();
                        if (chatEl)
                            chatEl.scrollTop = savedPos;
                        // Re-send the edited message to get a new AI response
                        this.regenerateAfterEdit(editedMsg);
                    }
                    else {
                        this.renderMessages();
                        if (chatEl)
                            chatEl.scrollTop = savedPos;
                        showToast('Message edited', { type: 'success' });
                    }
                }
                break;
            case 'message_deleted':
                {
                    const deletedId = data.message_id;
                    const deletedPairId = data.pair_message_id;
                    this.messages = this.messages.filter(m => m.id !== deletedId && m.id !== deletedPairId);
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
                    this.currentConversation.tags = data.tags;
                    this.renderConversationTags();
                }
                break;
            case 'all_tags':
                // Tag list arrives here; a future tag-picker UI can consume it.
                // Not stored yet (no reader) to keep state minimal.
                break;
            case 'status':
                // Transient backend status (e.g. "retrying…"): surface briefly
                // so the user sees progress instead of an apparent stall.
                if (typeof data.message === 'string' && data.message) {
                    showToast(data.message, { type: 'info', duration: 2500 });
                }
                break;
            case 'info':
                // Backend informational notice (e.g. endpoint unavailable).
                // Previously fell through to `default` and was dropped silently.
                if (typeof data.message === 'string' && data.message) {
                    showToast(data.message, { type: 'info' });
                }
                break;
            case 'error': {
                // History-scoped errors (backend tags them with `scope`) must
                // not cross-fire into chat streaming state: a rejected history
                // edit while a chat response streams in the background would
                // otherwise kill the stream UI, re-enable the input mid-stream
                // and null the guard that keeps stream_end out of the wrong
                // conversation. Surface the error + unstick the history editor
                // and leave every bit of chat state alone.
                // Guard a missing/non-string `message` the same way the
                // status/info cases do — without it an error frame that omits
                // `message` rendered the literal toast "undefined" and logged a
                // useless "undefined", masking the real failure.
                const errorMsg = typeof data.message === 'string' && data.message
                    ? data.message
                    : 'An error occurred';
                if (typeof data.scope === 'string' && HISTORY_ERROR_SCOPES.has(data.scope)) {
                    console.error('Server error (ai history):', errorMsg);
                    errorLogger.log('AI_SERVER_ERROR', errorMsg, JSON.stringify(data));
                    showToast(errorMsg, { type: 'error' });
                    // Forward the rejection code so HistoryManager can tell
                    // permanent rejections (ROW_CONFLICT…) — which drop the
                    // doomed undo entry — from transient ones (kept for retry).
                    this.historyManager?.onError(typeof data.code === 'string' ? data.code : undefined);
                    break;
                }
                console.error('Server error:', errorMsg);
                errorLogger.log('AI_SERVER_ERROR', errorMsg, JSON.stringify(data));
                showToast(errorMsg, { type: 'error' });
                this.isStreaming = false;
                // Mark the turn as torn down so a late stream_end for THIS turn
                // (server emits both error + stream_end) bails instead of
                // pushing a phantom assistant bubble. Cleared on next stream_start.
                this.streamErrored = true;
                // Clear the stream-conversation guard so a later stream_end for
                // a NEW turn isn't evaluated against this stale id.
                this.streamingConversationId = null;
                this.clearStreamBuffers();
                this.setInputEnabled(true);
                // Re-enable auto-scroll: only stream_start/stream_end reset
                // this, so a stream that ENDED with an error frame left the
                // view permanently stuck at the user's scroll position.
                this.userScrolledUp = false;
                // Clean up stuck streaming message on error
                const stuckErrorMsg = document.getElementById('streaming-message');
                if (stuckErrorMsg)
                    stuckErrorMsg.remove();
                // Reset edit streaming state on error
                if (this.isEditStreaming) {
                    this.isEditStreaming = false;
                    this.editTargetMessageId = null;
                    this.editStreamContent = '';
                    this.renderMessages(); // Restore original message content
                }
                // A rejected history edit (e.g. MSG_NOT_FOUND) arrives as a
                // plain error frame — unstick the history editor's Save
                // button, forwarding the code (same contract as the scoped
                // path above) so permanent rejections drop their undo entry.
                this.historyManager?.onError(typeof data.code === 'string' ? data.code : undefined);
                break;
            }
            case 'pong':
                this.wsClient.notePong();
                break;
            case 'provider_updated': {
                const conversationId = data.conversation_id;
                const aiProvider = data.ai_provider;
                if (conversationId &&
                    aiProvider &&
                    this.currentConversation?.id === conversationId) {
                    this.aiProvider = aiProvider;
                }
                window.dispatchEvent(new CustomEvent('ai-provider-updated', {
                    detail: { conversationId, aiProvider },
                }));
                break;
            }
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
            case 'document_saved':
                // Server confirmed a document's text was extracted + persisted
                // to the document memory store. Show a short toast summarising
                // what was saved so the user knows the upload will persist
                // across restarts (scoped to this conversation only).
                {
                    const docs = data.documents || [];
                    if (docs.length === 1) {
                        const d = docs[0];
                        const charCount = typeof d.char_count === 'number' ? d.char_count : 0;
                        showToast(`Saved "${d.filename}" to this conversation (${charCount.toLocaleString()} chars)`, { type: 'success', duration: 3500 });
                    }
                    else if (docs.length > 1) {
                        const totalChars = docs.reduce((s, d) => s + (typeof d.char_count === 'number' ? d.char_count : 0), 0);
                        showToast(`Saved ${docs.length} documents (${totalChars.toLocaleString()} chars) to this conversation`, { type: 'success', duration: 3500 });
                    }
                    // Refresh the files badge count — pulls the fresh list
                    // from the server rather than optimistically incrementing
                    // so the badge stays in sync even on reconnect races.
                    this.refreshChatFilesBadge();
                }
                break;
            case 'conversation_documents':
                // Populate the 📎 Files modal with the conversation-scoped
                // document list. Also updates the chat-header badge so the
                // count stays accurate.
                this.renderChatFilesModal(data.conversation_id, data.documents || []);
                break;
            case 'document_memory_deleted':
                // Server confirmed a delete. Drop the row locally without
                // a full refetch — faster than round-tripping list again.
                this.removeChatFileRow(data.id);
                this.refreshChatFilesBadge();
                showToast('Deleted', { type: 'info', duration: 1800 });
                break;
            case 'document_memory_content':
                // Full content arrived for the document currently being
                // edited — populate the editor form.
                this.hydrateChatFileEditor(data.document);
                break;
            case 'document_memory_updated':
                // Server ack for a save. Close editor, refetch the list
                // (so filename / char-count in the list row reflect the
                // new values), and nudge with a toast.
                this.closeChatFileEditor();
                if (!data.noop) {
                    showToast('Saved', { type: 'success', duration: 1800 });
                    // Refresh the list + badge to pick up new metadata.
                    if (this.currentConversation) {
                        this.send({
                            type: 'list_conversation_documents',
                            conversation_id: this.currentConversation.id,
                        });
                    }
                }
                break;
            // API Failover handlers
            case 'api_endpoints':
                window.dispatchEvent(new CustomEvent('api-failover-status', { detail: data }));
                break;
            case 'api_endpoint_switched':
                window.dispatchEvent(new CustomEvent('api-failover-status', { detail: data }));
                showToast(`API switched to ${(data.endpoint || '').toUpperCase()}${data.reason ? ` (${data.reason})` : ''}`, { type: 'info', duration: 4000 });
                break;
            case 'api_health_result':
                window.dispatchEvent(new CustomEvent('api-health-result', { detail: data }));
                break;
            // AI History page frames — owned by history-manager.ts (wired by
            // app.ts). Grouped labels share one forwarding body.
            case 'ai_channels_list':
            case 'ai_history_loaded':
            case 'ai_history_message_edited':
            case 'ai_history_message_deleted':
            case 'ai_history_message_restored':
                this.historyManager?.handleMessage(data);
                break;
            default:
                console.warn('Unknown WebSocket message type:', data.type);
                break;
        }
    }
    updateConnectionStatus(connected) {
        const statusEl = document.getElementById('chat-connection-status');
        if (statusEl) {
            statusEl.className = connected ? 'connected' : 'disconnected';
            if (connected) {
                statusEl.textContent = 'Connected';
            }
            else if (this.reconnectAttempts >= this.wsClient.maxReconnectAttempts) {
                statusEl.textContent = 'Disconnected';
            }
            else {
                statusEl.textContent = 'Connecting...';
            }
        }
        // Note: Overlay is now controlled by bot status in updateStatusBadge()
    }
    listConversations() {
        if (this.connected) {
            this.send({ type: 'list_conversations' });
            return;
        }
        void this.loadConversationsFallback();
    }
    createConversation() {
        const providerSelect = document.getElementById('modal-ai-provider');
        if (providerSelect) {
            // Validate against the allowlist before accepting, mirroring the
            // other provider write-sites (field initializer, ``connected``
            // handler, showNewChatModal). The <select> normally only holds
            // server-populated options, but a stale/tampered/injected <option>
            // could otherwise push an out-of-allowlist string to localStorage
            // and onto the wire. Ignore garbage and keep the current provider.
            const picked = providerSelect.value;
            if (this.availableProviders.includes(picked)) {
                this.aiProvider = picked;
                // Persist the explicit modal choice so the New Chat modal default
                // (showNewChatModal prefers the localStorage value) stays consistent
                // with the provider used for the most recent conversation.
                try {
                    localStorage.setItem('dashboard_ai_provider', this.aiProvider);
                }
                catch {
                    // localStorage write failures are non-fatal.
                }
            }
        }
        this.send({
            type: 'new_conversation',
            role_preset: this.selectedRole,
            thinking_enabled: this.thinkingEnabled,
            ai_provider: this.aiProvider,
        });
    }
    loadConversation(id) {
        // Flush any pending debounced draft write for the OLD conversation
        // BEFORE restoreDraft() replaces the textarea content. The timer
        // resolves ids/value at fire time, so switching within the 400ms
        // window wrote the NEW conversation's restored draft (or '') under
        // the OLD conversation's key, silently destroying that draft.
        if (this.draftSaveTimer !== null) {
            clearTimeout(this.draftSaveTimer);
            this.draftSaveTimer = null;
            if (this.currentConversation && this.currentConversation.id !== id) {
                const el = document.getElementById('chat-input');
                if (el)
                    this.saveDraft(this.currentConversation.id, el.value);
            }
        }
        // Track the most recently requested conversation ID so the
        // ``conversation_loaded`` handler can drop late-arriving frames
        // for a conversation the user already switched away from.
        this.pendingConversationLoadId = id;
        // Show loading spinner immediately for responsive feel
        this.showChatLoading();
        // Persist the last-opened conversation so it re-opens next launch.
        try {
            settings.lastConversationId = id;
            saveSettings();
        }
        catch {
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
    draftKey(id) {
        return `dashboard-draft-${id}`;
    }
    saveDraft(id, text) {
        try {
            if (text) {
                localStorage.setItem(this.draftKey(id), text);
            }
            else {
                localStorage.removeItem(this.draftKey(id));
            }
        }
        catch {
            // Quota exceeded etc — drafts are best-effort, swallow.
        }
    }
    restoreDraft(id) {
        try {
            const draft = localStorage.getItem(this.draftKey(id));
            const input = document.getElementById('chat-input');
            if (input && draft) {
                input.value = draft;
            }
            else if (input) {
                input.value = '';
            }
        }
        catch {
            // Swallow — drafts are best-effort.
        }
    }
    clearDraft(id) {
        try {
            localStorage.removeItem(this.draftKey(id));
        }
        catch {
            // Swallow.
        }
    }
    showChatLoading() {
        const container = document.getElementById('chat-messages');
        if (!container)
            return;
        this.showChatContainer();
        // Show message-shaped skeleton placeholders instead of a generic spinner.
        const skeleton = () => `
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
    // Rename + delete-confirm modals (#11) now live in ./chat/conversation-modals.ts.
    // ChatManager exposes the same method names as before so event bindings keep working.
    convModals = new ConversationModals({
        sendWsMessage: (payload) => this.send(payload),
        isStreaming: () => this.isStreaming,
        findConversation: (id) => this.conversations.find(c => c.id === id),
    });
    deleteConversation(id) { this.convModals.showDelete(id); }
    confirmDelete() { this.convModals.confirmDelete(); }
    closeDeleteModal() { this.convModals.closeDelete(); }
    renameConversation(id) { this.convModals.showRename(id); }
    confirmRename() { this.convModals.confirmRename(); }
    closeRenameModal() { this.convModals.closeRename(); }
    starConversation(id, starred) {
        this.send({ type: 'star_conversation', id, starred });
    }
    exportConversation(id, format = 'json') {
        this.send({ type: 'export_conversation', id, format });
    }
    // promptExportFormat now lives in ./chat/export-picker.ts. Thin
    // forwarder keeps the method name stable for the two call sites below.
    async promptExportFormat() {
        return promptExportFormat();
    }
    sendMessage() {
        const input = document.getElementById('chat-input');
        const rawContent = input?.value?.trim() ?? '';
        // A message is sendable if it has text OR attached images OR attached
        // docs. Sending attachments with no text is a legitimate pattern
        // ("here, look at this PDF") — the old check required text too, which
        // blocked that flow entirely.
        const hasAttachments = this.attachedImages.length > 0 || this.attachedDocs.length > 0;
        if (!rawContent && !hasAttachments) {
            return;
        }
        if (this.isStreaming) {
            // Surface a hint instead of returning silently — without it,
            // hitting Enter while a previous response is still streaming
            // looks like the keystroke was dropped, leaving the user to
            // wonder if Discord/Tauri ate their input.
            showToast('Wait for the current response to finish', { type: 'warning' });
            return;
        }
        if (!this.currentConversation) {
            showToast('Please start a conversation first', { type: 'warning' });
            return;
        }
        // Set the streaming gate immediately so a second send (e.g. Enter + Send-button
        // click in the same frame, or a fast double-tap) cannot slip through before
        // the backend's `stream_start` frame arrives and sets it. The disconnect
        // handler resets isStreaming on WS errors, so this won't strand the UI.
        this.isStreaming = true;
        // When only attachments are sent, substitute a short default prompt
        // so the backend (which treats empty content as an error) has
        // something to anchor the turn on. Claude reads the attached files
        // anyway, so "please take a look" works as a neutral nudge.
        const content = rawContent || '[attached file(s) for you to review]';
        // Detect /edit command: AI rewrites its last message based on user instruction
        if (content.startsWith('/edit ')) {
            const instruction = content.substring(6).trim();
            if (!instruction) {
                showToast('Usage: /edit <instruction>', { type: 'warning' });
                this.isStreaming = false; // release gate set above
                return;
            }
            // Find last assistant message with a DB ID
            let targetMsg = null;
            for (let i = this.messages.length - 1; i >= 0; i--) {
                if (this.messages[i].role === 'assistant' && this.messages[i].id) {
                    targetMsg = this.messages[i];
                    break;
                }
            }
            if (!targetMsg || !targetMsg.id) {
                showToast('No AI message to edit', { type: 'warning' });
                this.isStreaming = false; // release gate set above
                return;
            }
            if (input) {
                input.value = '';
                this.autoResizeInput();
            }
            const thinkingToggle = document.getElementById('thinking-toggle');
            const userName = settings.userName || 'User';
            const editSendOk = this.send({
                type: 'ai_edit_message',
                conversation_id: this.currentConversation.id,
                target_message_id: targetMsg.id,
                instruction,
                role_preset: this.currentConversation.role_preset,
                thinking_enabled: thinkingToggle?.checked || false,
                user_name: userName,
                ai_provider: this.aiProvider,
            });
            if (!editSendOk) {
                // Drop the streaming gate so the user can retry once the WS
                // reconnects — without this rollback, the input stays locked.
                this.isStreaming = false;
                // Restore the typed /edit instruction — it was cleared on the
                // optimistic path above and was previously lost entirely.
                if (input) {
                    input.value = rawContent;
                    this.autoResizeInput();
                    input.focus();
                }
            }
            else {
                // Edit sent successfully — consume any attachments so they don't
                // silently carry into the next normal message, matching the
                // normal-send path's clear() at the bottom of sendMessage().
                // (ai_edit_message itself carries no attachments by design.)
                this.imageAttach.clear();
                this.docAttach.clear();
                // Clearing the textarea via input.value='' above fires no 'input'
                // event, so the debounced draft writer never runs to remove the
                // draft. Cancel any pending save and drop the stored draft now —
                // otherwise a fired-then-sent '/edit ...' draft survives and is
                // replayed by restoreDraft() on the next loadConversation().
                if (this.draftSaveTimer !== null) {
                    clearTimeout(this.draftSaveTimer);
                    this.draftSaveTimer = null;
                }
                this.clearDraft(this.currentConversation.id);
            }
            return;
        }
        // Get history BEFORE adding new message (backend will add it)
        // Strip unnecessary fields (images/thinking/mode) to reduce payload size,
        // but keep `created_at` so the backend can prefix each message with its
        // send timestamp — without it the AI can't tell hours-long gaps from
        // back-to-back replies.
        const historyToSend = this.messages.slice(-20).map(m => ({
            role: m.role,
            content: m.content,
            created_at: m.created_at,
        }));
        // Add to local messages for display (include images + documents).
        // ``documents`` must be persisted on the message object so a later
        // regenerate-after-edit can resend the same attachments — previously
        // ``editedMsg.documents`` was always undefined and the regenerate
        // dropped attached PDFs/text files.
        this.messages.push({
            role: 'user',
            content,
            created_at: new Date().toISOString(),
            images: this.attachedImages.length > 0 ? [...this.attachedImages] : undefined,
            documents: this.attachedDocs.length > 0 ? [...this.attachedDocs] : undefined,
        });
        this.trimLocalMessages();
        this.renderMessages();
        if (input) {
            input.value = '';
            this.autoResizeInput();
            input.focus(); // Keep cursor in input
        }
        // Message sent — draft no longer needed for this conversation.
        if (this.currentConversation) {
            this.clearDraft(this.currentConversation.id);
        }
        const thinkingToggle = document.getElementById('thinking-toggle');
        const searchToggle = document.getElementById('chat-use-search');
        const unrestrictedToggle = document.getElementById('chat-unrestricted');
        const userName = settings.userName || 'User';
        // Snapshot both attachment types before the send so clear() can't
        // race with in-flight FileReaders still resolving their payload.
        // Also: ``images`` was previously sent by reference, so the clear()
        // below could empty the array between WS-client serialization and
        // the network write. Take a defensive shallow copy here too.
        const docs = this.attachedDocs;
        const images = [...this.attachedImages];
        const sendOk = this.send({
            type: 'message',
            conversation_id: this.currentConversation.id,
            content,
            role_preset: this.currentConversation.role_preset,
            thinking_enabled: thinkingToggle?.checked || false,
            history: historyToSend,
            // New features
            use_search: searchToggle?.checked ?? true,
            unrestricted_mode: unrestrictedToggle?.checked || false,
            images,
            documents: docs.length > 0 ? docs : undefined,
            user_name: userName,
            ai_provider: this.aiProvider,
        });
        if (!sendOk) {
            // Roll back the streaming gate so the user isn't locked out
            // of sending further messages until the WS reconnects, and
            // drop the user-message that was already pushed locally so
            // it doesn't linger in the rendered list as a phantom turn.
            this.isStreaming = false;
            this.messages.pop();
            this.renderMessages();
            // Restore the typed text + draft — both were cleared above on
            // the optimistic path, so a failed send used to destroy the
            // user's message entirely (only a toast remained).
            if (input) {
                input.value = content;
                this.autoResizeInput();
                input.focus();
            }
            if (this.currentConversation) {
                this.saveDraft(this.currentConversation.id, content);
            }
            return;
        }
        // Clear attached images + documents after sending
        this.imageAttach.clear();
        this.docAttach.clear();
    }
    appendStreamingMessage(mode = '') {
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
            : escapeHtml(this.currentConversation?.role_emoji || '\uD83E\uDD16');
        msgDiv.innerHTML = `
            <div class="message-avatar">${avatarHtml}</div>
            <div class="message-wrapper">
                <div class="message-header">
                    <span class="message-name">${escapeHtml(aiName)}</span>
                    <span class="message-time">${timeStr}</span>
                    ${modeHtml}
                </div>

                <div class="thinking-container">
                    <div class="thinking-header">${icon('chat')} Thinking...</div>
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
    showThinkingIndicator() {
        this.streamThinkingActive = true;
        const thinkingContainer = document.querySelector('#streaming-message .thinking-container');
        if (thinkingContainer) {
            thinkingContainer.style.display = 'block';
        }
    }
    // Reset the cross-switch partial buffers. Does NOT touch currentThinking,
    // which finalizeStreamingMessage consumes on stream_end (stream_start clears
    // it separately).
    clearStreamBuffers() {
        this.streamPartialChunks = [];
        this.streamPartialThinkingChunks = [];
        this.streamThinkingActive = false;
    }
    // Re-create the in-progress #streaming-message from the buffered partial.
    // Called from conversation_loaded when the user navigates back to a chat
    // whose RESPONSE stream is still running, so the live answer reappears
    // instead of an empty/stale view (the partial isn't in the DB yet).
    restoreStreamingBubble() {
        if (document.getElementById('streaming-message'))
            return; // already present
        this.appendStreamingMessage(this.currentMode || '');
        // Restore the response text (DOM-only — don't re-push into the buffer).
        const partial = this.streamPartialChunks.join('');
        if (partial) {
            const streamingText = document.querySelector('#streaming-message .streaming-text');
            if (streamingText)
                streamingText.appendChild(document.createTextNode(partial));
        }
        // Restore thinking: finalized (collapsed) if thinking_end already arrived,
        // otherwise the live partial.
        if (this.currentThinking) {
            this.showThinkingIndicator();
            this.finalizeThinking(this.currentThinking);
        }
        else if (this.streamThinkingActive) {
            this.showThinkingIndicator();
            const liveThinking = this.streamPartialThinkingChunks.join('');
            if (liveThinking) {
                const thinkingContent = document.querySelector('#streaming-message .thinking-content');
                if (thinkingContent)
                    thinkingContent.appendChild(document.createTextNode(liveThinking));
            }
        }
        this.scrollToBottom();
    }
    // Append-via-text-node avoids the O(n²) string growth of
    // ``textContent += chunk`` (each += copies the entire prior string).
    // ``createTextNode`` + ``appendChild`` is O(1) per chunk while still
    // letting consumers read aggregated ``textContent`` synchronously.
    appendThinkingChunk(text) {
        // Buffer so the live thinking survives a conversation switch (replayed by
        // restoreStreamingBubble when the user returns mid-stream).
        this.streamPartialThinkingChunks.push(text);
        const thinkingContent = document.querySelector('#streaming-message .thinking-content');
        if (thinkingContent) {
            thinkingContent.appendChild(document.createTextNode(text));
            this.followStream();
        }
    }
    currentThinking = ''; // Store current thinking for the streaming message
    finalizeThinking(fullThinking) {
        // Store for later use in finalizeStreamingMessage
        this.currentThinking = fullThinking;
        const thinkingHeader = document.querySelector('#streaming-message .thinking-header');
        const thinkingContent = document.querySelector('#streaming-message .thinking-content');
        if (thinkingHeader) {
            thinkingHeader.textContent = 'Thought Process';
            thinkingHeader.classList.add('collapsible', 'collapsed'); // Start collapsed
            // ``addEventListener`` over ``.onclick =``: assignment to
            // ``onclick`` overwrites any prior handler, so re-rendering
            // a streaming message would clobber a handler attached by
            // an earlier finalize pass and confuse multi-render flows.
            // ``addEventListener`` plays nicely with multi-attach
            // patterns and is the convention used everywhere else in
            // this file. Guard against double-binding via a data flag.
            if (!thinkingHeader.dataset.collapseBound) {
                thinkingHeader.dataset.collapseBound = '1';
                thinkingHeader.addEventListener('click', () => {
                    thinkingContent?.classList.toggle('collapsed');
                    thinkingHeader.classList.toggle('collapsed');
                });
            }
        }
        if (thinkingContent) {
            // Render Markdown formatting (bold, italic, code, etc.)
            thinkingContent.innerHTML = this.formatMessage(fullThinking);
            // Syntax-highlight any fenced code blocks in the thinking text too —
            // formatMessage only escapes/wraps them; Prism runs as a separate
            // pass. Without this, code in the thought process stayed plain until
            // the next full renderMessages() (and never, if it stayed collapsed).
            // Fire-and-forget to keep finalizeThinking synchronous for callers.
            void this.highlightCodeBlocks(thinkingContent);
            thinkingContent.classList.add('collapsed'); // Start collapsed
        }
    }
    appendChunk(text) {
        // Buffer first so the partial survives a conversation switch even when
        // the #streaming-message DOM isn't currently mounted (user viewing
        // another chat). restoreStreamingBubble replays this on return.
        this.streamPartialChunks.push(text);
        const streamingText = document.querySelector('#streaming-message .streaming-text');
        if (streamingText) {
            // Same O(n²) avoidance as ``appendThinkingChunk`` above —
            // append a text node instead of concatenating onto
            // ``textContent`` so chunk N doesn't re-copy chunks 1..N-1.
            streamingText.appendChild(document.createTextNode(text));
            this.followStream();
        }
    }
    finalizeStreamingMessage(fullResponse) {
        // Push first so msgIdx is the actual post-trim index. The previous
        // version captured `this.messages.length` BEFORE push, which was
        // correct for indices < MAX_LOCAL_MESSAGES but went one past the end
        // once trimLocalMessages started shifting the window.
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
        this.trimLocalMessages();
        const streamingMsg = document.getElementById('streaming-message');
        if (streamingMsg) {
            streamingMsg.classList.remove('streaming');
            streamingMsg.removeAttribute('id');
            const content = streamingMsg.querySelector('.message-content');
            if (content) {
                content.innerHTML = this.formatMessage(this.stripThinkTags(fullResponse));
                void this.highlightCodeBlocks(content);
            }
            // Add action buttons (copy, edit, delete) at the bottom. Resolve
            // the index at click time via indexOf(newMessage) so subsequent
            // trims/edits/deletes that shift the array don't desync the
            // closures.
            const wrapper = streamingMsg.querySelector('.message-wrapper');
            if (wrapper && !wrapper.querySelector('.message-actions')) {
                const actionsDiv = document.createElement('div');
                actionsDiv.className = 'message-actions';
                const currentIdx = this.messages.indexOf(newMessage);
                actionsDiv.innerHTML = `
                    <button class="copy-message-btn" data-content="${escapeHtml(fullResponse)}" title="Copy">${icon('copy')} Copy</button>
                    <button class="edit-message-btn" data-msg-idx="${currentIdx}" title="Edit">${icon('pencil')} Edit</button>
                    <button class="delete-message-btn" data-msg-idx="${currentIdx}" data-role="assistant" title="Delete">${icon('trash')} Delete</button>
                `;
                wrapper.appendChild(actionsDiv);
                actionsDiv.querySelector('.copy-message-btn')?.addEventListener('click', async (e) => {
                    const btn = e.target;
                    // ``getAttribute`` returns the attribute value already
                    // entity-decoded by the HTML parser. Previously this
                    // path piped the value through ``textarea.innerHTML =
                    // contentAttr`` to "decode" it \u2014 a NO-OP for entity
                    // handling but a YES-OP for HTML parsing: a payload
                    // like ``</textarea><img src=x onerror=...>`` would
                    // escape the textarea (RCDATA terminates on its own
                    // closing tag) and the parser would create a real
                    // ``<img>`` element with the onerror handler firing.
                    // Writing the plain string straight to the clipboard
                    // skips the parse step entirely.
                    const contentAttr = btn.getAttribute('data-content') || '';
                    try {
                        await navigator.clipboard.writeText(contentAttr);
                        btn.textContent = 'Copied';
                        setTimeout(() => { btn.textContent = 'Copy'; }, 1500);
                    }
                    catch (err) {
                        console.error('Failed to copy:', err);
                    }
                });
                actionsDiv.querySelector('.edit-message-btn')?.addEventListener('click', () => {
                    const idx = this.messages.indexOf(newMessage);
                    if (idx >= 0)
                        this.startEditMessage(idx);
                });
                actionsDiv.querySelector('.delete-message-btn')?.addEventListener('click', async () => {
                    const confirmed = await showConfirmDialog('Delete this message?');
                    if (!confirmed)
                        return;
                    const idx = this.messages.indexOf(newMessage);
                    if (idx >= 0)
                        this.deleteMessage(idx);
                });
            }
        }
        this.scrollToBottom();
    }
    trimLocalMessages() {
        if (this.messages.length > ChatManager.MAX_LOCAL_MESSAGES) {
            this.messages = this.messages.slice(-ChatManager.MAX_LOCAL_MESSAGES);
        }
    }
    // ========================================================================
    // AI Edit Streaming — /edit command support
    // ========================================================================
    startEditStreamingUI(targetMessageId) {
        // Find the target message element in DOM and put it into "editing" streaming state
        const msgIdx = this.messages.findIndex(m => m.id === targetMessageId);
        if (msgIdx < 0)
            return;
        const container = document.getElementById('chat-messages');
        if (!container)
            return;
        let msgElements = container.querySelectorAll('.chat-message');
        // With virtualization the DOM only contains messages.slice(visibleStartIdx);
        // translate the absolute index into the local DOM index.
        let msgEl = msgElements[msgIdx - this.visibleStartIdx];
        if (!msgEl) {
            // Target is virtualized OUT of the rendered window (editing an
            // older message). Grow the window so it renders, re-resolve, and
            // scroll it into view — otherwise the live edit stream is silently
            // dropped (.edit-streaming-text never exists) until stream_end
            // re-renders. windowSize = total - msgIdx ⇒ startIdx = msgIdx, so
            // the target lands at local DOM index 0.
            this.visibleMessageCount = Math.max(this.visibleMessageCount, this.messages.length - msgIdx);
            this.renderMessages();
            msgElements = container.querySelectorAll('.chat-message');
            msgEl = msgElements[msgIdx - this.visibleStartIdx];
            if (msgEl)
                msgEl.scrollIntoView({ block: 'center' });
        }
        if (!msgEl)
            return;
        const contentEl = msgEl.querySelector('.message-content');
        if (!contentEl)
            return;
        // Replace content with streaming placeholder
        contentEl.innerHTML = `
            <span class="streaming-text edit-streaming-text"></span>
            <span class="typing-indicator-dots" aria-label="AI is typing"><span></span><span></span><span></span></span>
        `;
        msgEl.classList.add('streaming');
        // Show mode badge if present
        const headerEl = msgEl.querySelector('.message-header');
        if (headerEl && this.currentMode) {
            let modeSpan = headerEl.querySelector('.message-mode');
            if (modeSpan) {
                modeSpan.textContent = this.currentMode;
            }
            else {
                modeSpan = document.createElement('span');
                modeSpan.className = 'message-mode';
                modeSpan.textContent = this.currentMode;
                headerEl.appendChild(modeSpan);
            }
        }
        // Hide action buttons during editing
        const actionsEl = msgEl.querySelector('.message-actions');
        if (actionsEl)
            actionsEl.style.display = 'none';
    }
    appendEditStreamChunk(text) {
        // Buffer into the running content string but defer the DOM write to
        // the next animation frame. Without batching, a fast stream issuing
        // many small chunks triggered N textContent writes per frame —
        // each one re-renders the full string, giving O(n²) total work as
        // the response grew. With rAF batching it's exactly one write per
        // frame regardless of chunk count.
        this.editStreamContent += text;
        if (this.editStreamRafId !== null)
            return;
        this.editStreamRafId = requestAnimationFrame(() => {
            this.editStreamRafId = null;
            const streamingText = document.querySelector('.edit-streaming-text');
            if (streamingText) {
                streamingText.textContent = this.editStreamContent;
            }
        });
    }
    finalizeEditStreaming(fullResponse, targetMessageId) {
        // Cancel any pending rAF flush — we're about to re-render the message
        // entirely from ``fullResponse``, so a deferred chunk write would
        // race against (and lose to) the renderMessages() below.
        if (this.editStreamRafId !== null) {
            cancelAnimationFrame(this.editStreamRafId);
            this.editStreamRafId = null;
        }
        // Update the local message content. Fall back to the id captured at
        // stream_start (still set here — nulled only after this returns) in case
        // the backend omits target_message_id on the stream_end frame, so an
        // undefined cast can't make findIndex match a non-persisted message.
        const resolvedTargetId = targetMessageId ?? this.editTargetMessageId;
        const msgIdx = this.messages.findIndex(m => m.id === resolvedTargetId);
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
        if (chatContainer)
            chatContainer.scrollTop = savedScroll;
    }
    // Conversation list sidebar (#15 / #22) now lives in ./chat/conversation-list.ts.
    // ChatManager holds one ConversationList instance; callbacks route back here.
    convList = new ConversationList({
        onLoadConversation: (id) => this.loadConversation(id),
        sendWsMessage: (payload) => this.send(payload),
        onFilterChanged: () => {
            const container = document.getElementById('conversation-list');
            const savedScroll = container?.scrollTop ?? 0;
            this.renderConversationList();
            if (container)
                container.scrollTop = savedScroll;
        },
    });
    renderConversationList() {
        this.convList.render({
            conversations: this.conversations,
            currentConversation: this.currentConversation,
            presets: this.presets,
        });
    }
    renderMessages() {
        const container = document.getElementById('chat-messages');
        if (!container)
            return;
        // Capture whether the user was reading near the bottom BEFORE we replace
        // innerHTML below. Outside of streaming, userScrolledUp is always false
        // (it is only ever set inside `if (this.isStreaming)`), so an
        // unconditional scrollToBottom() yanked a user reading older history to
        // the bottom whenever they pinned/liked a message or an ack re-rendered.
        // Only auto-scroll when the user was already near the bottom (or when a
        // stream is feeding new chunks).
        const AUTO_SCROLL_THRESHOLD = 150; // px from bottom — mirrors setupScrollListener
        const distanceFromBottom = container.scrollHeight - container.scrollTop - container.clientHeight;
        const wasNearBottom = this.isStreaming || distanceFromBottom <= AUTO_SCROLL_THRESHOLD;
        // Template + virtualization-windowing math now lives in
        // ./chat/message-template.ts. We pass in the formatter/stripThinkTags/
        // formatTime methods as deps; the template never reaches into `this`.
        const result = renderMessagesHtml({
            messages: this.messages,
            currentConversation: this.currentConversation,
            visibleMessageCount: this.visibleMessageCount,
            deps: {
                formatTime: (s) => this.formatTime(s),
                formatMessage: (c) => this.formatMessage(c),
                stripThinkTags: (c) => this.stripThinkTags(c),
            },
        });
        // Propagate the clamped window size back to ChatManager so subsequent
        // "show earlier" clicks grow from the correct baseline.
        this.visibleMessageCount = result.visibleMessageCount;
        this.visibleStartIdx = result.startIdx;
        container.innerHTML = result.html;
        if (this.messages.length === 0)
            return; // no events to bind on the welcome card
        if (wasNearBottom)
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
                this.visibleMessageCount += VIRT_WINDOW_SIZE;
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
                const src = img.src;
                if (src) {
                    // Open image in new window safely (no document.write XSS).
                    // NOTE: 'noopener' must NOT be in the features string —
                    // per the HTML spec window.open() returns null when
                    // noopener is present, so the whole `if (newWindow)` body
                    // (the actual image render) became dead code and clicking
                    // an image did nothing. We still sever the back-reference
                    // by setting opener=null on the returned window below.
                    const newWindow = window.open('', '_blank');
                    if (newWindow) {
                        try {
                            newWindow.opener = null;
                        }
                        catch { /* cross-origin guard */ }
                        const doc = newWindow.document;
                        doc.title = 'Image Preview';
                        // Style via CSSOM property setters (not a <style> element
                        // or inline style= attribute): the popup is about:blank and
                        // inherits this page's CSP, where style-src is 'self' with
                        // no 'unsafe-inline'. CSSOM mutations are exempt from CSP.
                        const b = doc.body;
                        b.style.margin = '0';
                        b.style.display = 'flex';
                        b.style.justifyContent = 'center';
                        b.style.alignItems = 'center';
                        b.style.minHeight = '100vh';
                        b.style.background = '#1a1a1a';
                        const imgEl = doc.createElement('img');
                        imgEl.src = src;
                        imgEl.alt = 'preview';
                        imgEl.style.maxWidth = '100%';
                        imgEl.style.maxHeight = '100vh';
                        imgEl.style.objectFit = 'contain';
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
        // Setup copy button clicks (whole message)
        container.querySelectorAll('.copy-message-btn').forEach(btn => {
            btn.addEventListener('click', async () => {
                // ``getAttribute`` returns the value already entity-decoded
                // by the HTML parser. The previous textarea-based "decode"
                // dance was a no-op for entities and a XSS sink for HTML:
                // a payload like ``</textarea><img onerror=...>`` would
                // escape the textarea's RCDATA and create a live ``<img>``
                // with a firing handler. Write the string straight to the
                // clipboard instead.
                const content = btn.getAttribute('data-content') || '';
                try {
                    await navigator.clipboard.writeText(content);
                    const originalText = btn.textContent;
                    btn.textContent = 'Copied';
                    setTimeout(() => { btn.textContent = originalText; }, 1500);
                }
                catch (err) {
                    console.error('Failed to copy:', err);
                    showToast('Failed to copy message', { type: 'error' });
                }
            });
        });
        // Setup code-block copy button clicks (per-block inside a message)
        container.querySelectorAll('.code-copy-btn').forEach(btn => {
            btn.addEventListener('click', async () => {
                // Same fix as the message-copy path above: getAttribute
                // already returns decoded text; the textarea round-trip
                // re-parses HTML and would execute injected handlers.
                let content = btn.getAttribute('data-code-copy') || '';
                // Resilience: if data-code-copy ever comes back empty (e.g. a
                // sanitiser dropped the attribute), read the code straight from
                // the rendered block. formatter.ts emits
                // .code-block-wrapper > pre > code, so the <pre><code> text is
                // the same escaped-then-decoded source the attribute held.
                if (!content) {
                    content = btn
                        .closest('.code-block-wrapper')
                        ?.querySelector('pre code')?.textContent ?? '';
                }
                // Still nothing to copy — don't fake a 'Copied' confirmation.
                if (!content) {
                    showToast('Nothing to copy', { type: 'error' });
                    return;
                }
                try {
                    await navigator.clipboard.writeText(content);
                    const originalText = btn.textContent;
                    btn.textContent = 'Copied';
                    setTimeout(() => { btn.textContent = originalText; }, 1200);
                }
                catch (err) {
                    console.error('Failed to copy code:', err);
                    showToast('Failed to copy code', { type: 'error' });
                }
            });
        });
        // Setup edit button clicks. Always pass radix 10 to ``parseInt``
        // — without it, JS engines may interpret leading-zero strings as
        // octal in non-strict mode, silently corrupting message IDs.
        container.querySelectorAll('.edit-message-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const idx = parseInt(btn.dataset.msgIdx || '-1', 10);
                if (idx >= 0)
                    this.startEditMessage(idx);
            });
        });
        // Setup AI edit button clicks
        container.querySelectorAll('.ai-edit-message-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const idx = parseInt(btn.dataset.msgIdx || '-1', 10);
                if (idx >= 0)
                    this.startAiEditMessage(idx);
            });
        });
        // Setup delete button clicks
        container.querySelectorAll('.delete-message-btn').forEach(btn => {
            btn.addEventListener('click', async () => {
                const idx = parseInt(btn.dataset.msgIdx || '-1', 10);
                if (idx >= 0) {
                    const confirmed = await showConfirmDialog('Delete this message?');
                    if (confirmed)
                        this.deleteMessage(idx);
                }
            });
        });
        // Setup pin/unpin button clicks
        container.querySelectorAll('.pin-message-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const el = btn;
                const msgId = el.dataset.msgId;
                if (!msgId)
                    return;
                const messageId = parseInt(msgId, 10);
                if (!Number.isFinite(messageId) || messageId <= 0)
                    return;
                const nextPinned = el.dataset.pinned !== '1';
                // Send first; only flip locally if the WS is open. send()
                // shows a toast on disconnected — without this guard the
                // local state would drift from the server's view.
                if (!this.connected) {
                    this.send({ type: 'pin_message', message_id: messageId, pinned: nextPinned });
                    return;
                }
                // Only flip locally if the frame actually went out — send() can
                // still return false if the socket closes between the connected
                // check above and ws.send() (InvalidStateError), which would
                // otherwise drift the UI from the server until the next refresh.
                const ok = this.send({ type: 'pin_message', message_id: messageId, pinned: nextPinned });
                if (!ok)
                    return;
                // Optimistic local update — server confirmation will re-render.
                const targetMsg = this.messages.find(m => String(m.id) === msgId);
                if (targetMsg)
                    targetMsg.is_pinned = nextPinned;
                this.renderMessages();
            });
        });
        // Setup like/unlike button clicks (#20b)
        container.querySelectorAll('.like-message-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const el = btn;
                const msgId = el.dataset.msgId;
                if (!msgId)
                    return;
                const messageId = parseInt(msgId, 10);
                if (!Number.isFinite(messageId) || messageId <= 0)
                    return;
                const nextLiked = el.dataset.liked !== '1';
                if (!this.connected) {
                    this.send({ type: 'like_message', message_id: messageId, liked: nextLiked });
                    return;
                }
                // Only flip locally if the frame actually went out (see pin
                // handler above) — a send() that returned false would drift the
                // UI from the server's view until the next list refresh.
                const ok = this.send({ type: 'like_message', message_id: messageId, liked: nextLiked });
                if (!ok)
                    return;
                const targetMsg = this.messages.find(m => String(m.id) === msgId);
                if (targetMsg)
                    targetMsg.liked = nextLiked;
                this.renderMessages();
            });
        });
    }
    // stripThinkTags + formatMessage now live in ./chat/formatter.ts.
    // These thin forwarders keep the ChatManager method surface stable so
    // inline templates (`${this.formatMessage(...)}`) don't all have to be updated.
    stripThinkTags(content) {
        return stripThinkTags(content);
    }
    formatMessage(content) {
        return formatMessage(content);
    }
    async highlightCodeBlocks(root) {
        return highlightCodeBlocks(root);
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
        if (avatarEl) {
            // Validate before assigning to .src — same defense-in-depth as renderMessages().
            // localStorage can be tampered with, so never trust avatar URLs blindly.
            // Use isSafeAvatarUrl + raw value (NOT safeAvatarUrl, which HTML-escapes for innerHTML).
            if (isSafeAvatarUrl(settings.aiAvatar)) {
                avatarEl.src = settings.aiAvatar;
                avatarEl.style.display = '';
            }
            else {
                avatarEl.removeAttribute('src');
                avatarEl.style.display = 'none';
            }
        }
        if (nameEl)
            nameEl.textContent = this.currentConversation.role_name || 'AI';
        if (thinkingToggle)
            thinkingToggle.checked = this.currentConversation.thinking_enabled || false;
        // Restore AI provider dropdown to match this conversation
        const providerSelect = document.getElementById('chat-ai-provider');
        if (providerSelect) {
            providerSelect.value = this.aiProvider;
        }
        // Restore Unrestricted toggle from saved preference
        const unrestrictedToggle = document.getElementById('chat-unrestricted');
        if (unrestrictedToggle) {
            unrestrictedToggle.checked = localStorage.getItem('dashboard_unrestricted') === 'true';
        }
        // Render conversation tags below the header.
        this.renderConversationTags();
        this.updateStarButton();
    }
    /** Render the tag chips + "add tag" input strip under the chat header. */
    renderConversationTags() {
        this.convList.renderTags(this.currentConversation);
    }
    updateStarButton() {
        const btn = document.getElementById('btn-star-chat');
        if (btn && this.currentConversation) {
            btn.textContent = this.currentConversation.is_starred ? 'Starred' : 'Star';
        }
    }
    // Context-window indicator (#21 header bar) now lives in ./chat/context-window.ts.
    // Thin forwarders preserve the public method names used by handleMessage +
    // conversation_loaded / streaming paths.
    contextWindow = new ContextWindowIndicator();
    updateContextWindowIndicator(usage) {
        this.contextWindow.update(this.currentConversation?.id ?? null, usage);
    }
    resetContextWindowIndicator() { this.contextWindow.reset(); }
    restoreContextWindowIndicator(conversationId) {
        this.contextWindow.restore(conversationId);
    }
    loadTokenUsageCache() { this.contextWindow.load(); }
    showChatContainer() {
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
    hideChatContainer() {
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
    setInputEnabled(enabled) {
        const input = document.getElementById('chat-input');
        const btn = document.getElementById('btn-send');
        // Also gate the 📎 attach button so files can't be staged mid-stream and
        // then silently ride into the NEXT turn. The drop/paste paths (in
        // image-attach.ts) are gated separately via the isStreaming callback
        // passed to setup(); this just covers the click-to-pick affordance and
        // dims it so the disabled state is visible.
        const attachBtn = document.getElementById('btn-attach');
        if (input)
            input.disabled = !enabled;
        if (btn)
            btn.disabled = !enabled;
        if (attachBtn) {
            attachBtn.disabled = !enabled;
            // `#btn-attach` may be a plain <button> or a styled element; toggle a
            // class for the dim so CSS owns the exact look (no inline style here,
            // matching the CSP-friendly no-inline-style posture in this file).
            attachBtn.classList.toggle('disabled', !enabled);
        }
    }
    scrollToBottom(force = false) {
        if (!force && this.userScrolledUp) {
            // User is scrolled up — increment the badge so they can see how
            // many new messages arrived while they were reading older ones.
            // Without this the FAB badge stayed permanently at 0 (dead UI).
            this.newMessagesWhileScrolledUp += 1;
            this.updateScrollFab(true);
            return;
        }
        const container = document.getElementById('chat-messages');
        if (container) {
            container.scrollTop = container.scrollHeight;
        }
        // Any explicit scroll-to-bottom resets the "new message" counter.
        this.newMessagesWhileScrolledUp = 0;
        this.updateScrollFab(false);
    }
    /**
     * Per-chunk auto-follow during streaming. Unlike scrollToBottom(), this
     * does NOT touch newMessagesWhileScrolledUp — a single response emits
     * hundreds of chunks, so counting them would climb the FAB badge into the
     * hundreds for one message. The badge is only bumped on message-boundary
     * events (scrollToBottom from appendStreamingMessage / finalizeStreamingMessage).
     * When the user has scrolled up we leave the viewport alone and just keep
     * the FAB visible; otherwise we keep the latest text in view.
     */
    followStream() {
        if (this.userScrolledUp) {
            this.updateScrollFab(true);
            return;
        }
        const container = document.getElementById('chat-messages');
        if (container) {
            container.scrollTop = container.scrollHeight;
        }
    }
    /** Count of messages that arrived while the user was scrolled up. */
    newMessagesWhileScrolledUp = 0;
    /** Toggle the floating scroll-to-bottom button + optional new-count badge. */
    updateScrollFab(show) {
        const fab = document.getElementById('scroll-to-bottom-fab');
        const badge = document.getElementById('scroll-new-count');
        if (!fab)
            return;
        fab.classList.toggle('hidden', !show);
        if (badge) {
            if (this.newMessagesWhileScrolledUp > 0) {
                badge.textContent = String(this.newMessagesWhileScrolledUp);
                badge.classList.remove('hidden');
            }
            else {
                badge.classList.add('hidden');
            }
        }
    }
    // In-conversation search (#14) now lives in ./chat/search.ts.
    // ChatManager holds a ChatSearch instance + forwarders so keybinding
    // shortcuts from app.ts (Ctrl+F) still hit the same public methods.
    chatSearch = new ChatSearch(() => document.getElementById('chat-messages'));
    openChatSearch() { this.chatSearch.open(); }
    closeChatSearch() { this.chatSearch.close(); }
    performChatSearch(query) { this.chatSearch.perform(query); }
    stepChatSearch(direction) { this.chatSearch.step(direction); }
    setupChatSearchHandlers() { this.chatSearch.setup(); }
    setupScrollListener() {
        const container = document.getElementById('chat-messages');
        if (!container)
            return;
        // Guard: setupScrollListener() is called from both init() and renderMessages().
        // Without this flag the scroll listener stacks N times after N renders, turning
        // each scroll into N callbacks and causing FAB flicker / UI jank on long chats.
        if (container.dataset.scrollBound === '1')
            return;
        container.dataset.scrollBound = '1';
        // setupChatSearchHandlers() also lives here so it binds once on the same gate.
        this.setupChatSearchHandlers();
        const FAB_THRESHOLD = 200; // px from bottom to show FAB
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
        // Click FAB → smooth scroll to bottom. Mark flag BEFORE addEventListener
        // so a re-entrant call cannot slip through between check and bind.
        const fab = document.getElementById('scroll-to-bottom-fab');
        if (fab && !fab.dataset.fabBound) {
            fab.dataset.fabBound = '1';
            fab.addEventListener('click', () => {
                container.scrollTo({ top: container.scrollHeight, behavior: 'smooth' });
                this.newMessagesWhileScrolledUp = 0;
                // Clicking "jump to bottom" means: follow the stream again.
                this.userScrolledUp = false;
                this.updateScrollFab(false);
            });
        }
    }
    formatTime(dateStr) {
        try {
            // SQLite's CURRENT_TIMESTAMP stores UTC as a naive string
            // (e.g. "2026-04-26 11:16:08"). JS's Date constructor would parse
            // that as local time, which is wrong — a message sent at 18:16
            // Bangkok would render as 11:16. Append "Z" for naive strings so
            // they're parsed as UTC, then toLocaleTimeString below converts
            // to the user's local timezone.
            const date = new Date(normalizeSqliteUtc(dateStr));
            // A malformed/empty timestamp yields an Invalid Date (which doesn't
            // throw — toLocaleTimeString would render the literal "Invalid Date").
            // Return the raw input instead, matching formatChatFileDate /
            // formatTimestamp / formatLastActive.
            if (Number.isNaN(date.getTime()))
                return dateStr;
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
    // Virtualization state — thresholds themselves live in ./chat/message-template.ts.
    visibleMessageCount = 0;
    // Absolute index in `messages` of the first DOM element rendered. With
    // virtualization (>150 messages) only the tail window is in the DOM, so
    // querySelectorAll('.chat-message')[absoluteIdx] is wrong — callers must
    // subtract this offset. Updated on every renderMessages().
    visibleStartIdx = 0;
    // Image attach manager — file picker, drag-drop, paste. Thin forwarders
    // keep the public method surface stable for callers (renderMessages uses
    // `this.attachedImages` inside template strings; sendMessage snapshots it).
    imageAttach = new ImageAttachManager();
    docAttach = new DocumentAttachManager();
    get attachedImages() { return this.imageAttach.get(); }
    get attachedDocs() { return this.docAttach.get(); }
    attachImage(file) { this.imageAttach.attach(file); }
    removeImage(index) { this.imageAttach.remove(index); }
    renderAttachedImages() { this.imageAttach.renderPreview(); }
    /** Bind the shared file picker + drop zone. Document manager is passed
     * to the image manager so non-image files (PDF, text, code) are routed
     * to it automatically rather than rejected. */
    setupImageUpload() { this.imageAttach.setup(this.docAttach, () => this.isStreaming); }
    // ========================================================================
    // Chat Files Modal — per-conversation document list (📎 button)
    // ========================================================================
    /** Open the "Attached Files" modal for the active conversation and
     * request a fresh list from the server. */
    openChatFilesModal() {
        if (!this.currentConversation) {
            showToast('Open a conversation first', { type: 'warning' });
            return;
        }
        const modal = document.getElementById('chat-files-modal');
        const subtitle = document.getElementById('chat-files-subtitle');
        const list = document.getElementById('chat-files-list');
        const empty = document.getElementById('chat-files-empty');
        if (!modal)
            return;
        if (subtitle)
            subtitle.textContent = 'Loading…';
        if (list)
            list.innerHTML = '';
        if (empty)
            empty.classList.add('hidden');
        modal.classList.add('active');
        this.send({
            type: 'list_conversation_documents',
            conversation_id: this.currentConversation.id,
        });
    }
    closeChatFilesModal() {
        const modal = document.getElementById('chat-files-modal');
        modal?.classList.remove('active');
    }
    /** Handler for the `conversation_documents` WS frame. Renders the list
     * or shows the empty state. */
    renderChatFilesModal(conversationId, docs) {
        // Drop the frame if the user already switched to a different
        // conversation (request race) — we don't want to show stale data.
        if (!this.currentConversation || conversationId !== this.currentConversation.id)
            return;
        const subtitle = document.getElementById('chat-files-subtitle');
        const list = document.getElementById('chat-files-list');
        const empty = document.getElementById('chat-files-empty');
        // Update the badge on the header button regardless of modal state.
        this.updateChatFilesBadge(docs.length);
        if (!list)
            return;
        if (docs.length === 0) {
            if (subtitle)
                subtitle.textContent = '';
            list.innerHTML = '';
            empty?.classList.remove('hidden');
            return;
        }
        empty?.classList.add('hidden');
        if (subtitle) {
            // Coerce char_count via a numeric-finite guard before arithmetic /
            // .toLocaleString(): `docs` is an untrusted WS frame (no runtime
            // validation), so a non-numeric char_count (string/object) would make
            // `(x || 0)` return the raw value and a later .toLocaleString() throw
            // a TypeError that blanks the whole Files modal — same bug class as the
            // file_kind/filename coercion below. We can't use Number(x) || 0 either:
            // Number(Object.create(null)) itself throws ("Cannot convert object to
            // primitive value"). The typeof+isFinite guard never throws and matches
            // the safe pattern the other documents-frame handler already uses.
            const totalChars = docs.reduce((s, d) => s + chatFileCount(d.char_count), 0);
            subtitle.textContent = `${docs.length} file(s), ${totalChars.toLocaleString()} chars in persistent memory.`;
        }
        list.innerHTML = docs.map(d => {
            // Coerce file_kind/filename before calling string methods: `docs`
            // is a TYPE CAST of an untrusted WS frame (no runtime validation),
            // so a compromised/buggy backend could send null/number/object and
            // a raw .toUpperCase()/.slice() would throw a TypeError that aborts
            // the whole docs.map — blanking the Files modal. Mirrors the String()
            // coercion the failover/health-check renderers already do.
            const kind = String(d.file_kind ?? '');
            const name = String(d.filename ?? '');
            const fileIcon = chatFileIconFor(kind, name);
            // Coerce char_count/page_count via the same numeric-finite guard for
            // the same reason as kind/name above: a malformed numeric field
            // (string/object) reaching .toLocaleString() / template interpolation
            // would throw inside this map and abort it, blanking the modal. The
            // guard normalises non-numeric/NaN to 0 (and never throws on a
            // null-prototype object, which Number() would); pageCount stays falsy
            // (0) so the page(s) chip is omitted when there's no usable page count.
            const charCount = chatFileCount(d.char_count);
            const pageCount = chatFileCount(d.page_count);
            const meta = [
                `${charCount.toLocaleString()} chars`,
                pageCount ? `${pageCount} page(s)` : null,
                kind.toUpperCase(),
                formatChatFileDate(d.created_at),
            ].filter(Boolean).join(' · ');
            // Escape the id even though it's typed `number` — values arrive
            // from a WS frame parsed by JSON.parse, so a compromised server
            // could send a non-numeric string with embedded quotes that
            // would break out of the attribute.
            const safeId = escapeHtml(String(d.id));
            return `
                <div class="chat-file-row" data-id="${safeId}">
                    <span class="file-icon" aria-hidden="true">${fileIcon}</span>
                    <div class="file-body">
                        <div class="file-name">${escapeHtml(name)}</div>
                        <div class="file-meta">${escapeHtml(meta)}</div>
                    </div>
                    <button class="file-edit" data-id="${safeId}" title="Edit contents">Edit</button>
                    <button class="file-delete" data-id="${safeId}" title="Remove from memory">Delete</button>
                </div>
            `;
        }).join('');
        list.querySelectorAll('.file-edit').forEach(btn => {
            btn.addEventListener('click', (e) => {
                // ``parseInt`` without an explicit radix is implementation-
                // specific (older JS engines parse ``08`` as octal); always
                // pass radix 10 to keep the parse deterministic.
                const id = parseInt(e.currentTarget.dataset.id || '0', 10);
                if (!id || !this.currentConversation)
                    return;
                this.openChatFileEditor(id);
            });
        });
        list.querySelectorAll('.file-delete').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const id = parseInt(e.currentTarget.dataset.id || '0', 10);
                if (!id || !this.currentConversation)
                    return;
                this.send({
                    type: 'delete_document_memory',
                    id,
                    conversation_id: this.currentConversation.id,
                });
            });
        });
    }
    // ========================================================================
    // Chat File Editor — filename + extracted_text edit view
    // ========================================================================
    /** Currently-editing document id. Stored on the instance so the
     * `document_memory_content` WS frame knows which row to hydrate. */
    editingDocId = null;
    /** Switch the files modal into editor view and request the full content
     * for the given id. The textarea fills in once `document_memory_content`
     * arrives — avoids shipping the full text in the list frame. Also
     * flips the `.editing` class on the modal-content so CSS can widen the
     * box from the compact list size to a roomy editing surface. */
    openChatFileEditor(docId) {
        if (!this.currentConversation)
            return;
        this.editingDocId = docId;
        const modalContent = document.querySelector('.chat-files-modal-content');
        const listView = document.getElementById('chat-files-list-view');
        const editView = document.getElementById('chat-files-edit-view');
        const nameInput = document.getElementById('chat-files-edit-name');
        const textInput = document.getElementById('chat-files-edit-text');
        const counter = document.getElementById('chat-files-edit-counter');
        if (nameInput)
            nameInput.value = '';
        if (textInput) {
            textInput.value = '';
            textInput.placeholder = 'Loading…';
        }
        if (counter)
            counter.textContent = '0 chars';
        listView?.classList.add('hidden');
        editView?.classList.remove('hidden');
        modalContent?.classList.add('editing');
        this.send({
            type: 'get_document_memory_content',
            id: docId,
            conversation_id: this.currentConversation.id,
        });
    }
    /** Populate the edit form from a `document_memory_content` WS frame. */
    hydrateChatFileEditor(doc) {
        if (this.editingDocId !== doc.id)
            return; // stale frame
        const nameInput = document.getElementById('chat-files-edit-name');
        const textInput = document.getElementById('chat-files-edit-text');
        if (nameInput)
            nameInput.value = doc.filename || '';
        if (textInput) {
            textInput.placeholder = '';
            textInput.value = doc.extracted_text || '';
            textInput.focus();
        }
        this.updateChatFileEditorCounter();
    }
    closeChatFileEditor() {
        this.editingDocId = null;
        document.getElementById('chat-files-edit-view')?.classList.add('hidden');
        document.getElementById('chat-files-list-view')?.classList.remove('hidden');
        // Shrink the modal back to the compact list size — the CSS
        // transition makes this feel smooth rather than popping.
        document.querySelector('.chat-files-modal-content')?.classList.remove('editing');
    }
    /** Refresh the char counter under the textarea. */
    updateChatFileEditorCounter() {
        const textInput = document.getElementById('chat-files-edit-text');
        const counter = document.getElementById('chat-files-edit-counter');
        if (!textInput || !counter)
            return;
        counter.textContent = `${textInput.value.length.toLocaleString()} / 500,000 chars`;
    }
    /** Reflow broken per-glyph newlines in the current editor textarea.
     *
     * Old PDFs uploaded before the extraction fix have `\n` between every
     * few characters — renders as vertically-stacked text in the editor.
     * This button re-applies the same join algorithm the backend now uses
     * on fresh uploads: single newlines become spaces, double newlines
     * stay as paragraph breaks, runs of spaces collapse.
     *
     * Kept as an explicit button rather than running automatically so the
     * user can choose whether to keep intentional line breaks (e.g. in a
     * text file with bulleted lists) or reflow a genuinely broken extract.
     */
    reflowChatFileEditor() {
        const textInput = document.getElementById('chat-files-edit-text');
        if (!textInput)
            return;
        const original = textInput.value;
        if (!original)
            return;
        const joined = reflowPdfText(original);
        if (joined === original) {
            showToast('Nothing to reflow — already looks clean', { type: 'info', duration: 2000 });
            return;
        }
        textInput.value = joined;
        this.updateChatFileEditorCounter();
        textInput.focus();
        showToast(`Reflowed (${original.length.toLocaleString()} → ${joined.length.toLocaleString()} chars). Click Save to persist.`, { type: 'success', duration: 3000 });
    }
    /** Submit edit — server patches both fields in one UPDATE, then we pop
     * back to the list view and request a fresh list so the row shows the
     * new char count / filename. */
    saveChatFileEditor() {
        // Explicit null check (not `!this.editingDocId`) so a document id of 0
        // isn't treated as "not editing" — consistent with the `msg.id == null`
        // idiom used elsewhere in this file.
        if (this.editingDocId == null || !this.currentConversation)
            return;
        const nameInput = document.getElementById('chat-files-edit-name');
        const textInput = document.getElementById('chat-files-edit-text');
        const filename = nameInput?.value.trim() || '';
        const extractedText = textInput?.value ?? '';
        if (!filename) {
            showToast('Filename cannot be empty', { type: 'warning' });
            nameInput?.focus();
            return;
        }
        this.send({
            type: 'update_document_memory',
            id: this.editingDocId,
            conversation_id: this.currentConversation.id,
            filename,
            extracted_text: extractedText,
        });
    }
    /** Remove a single row from the modal (called after delete ack). */
    removeChatFileRow(id) {
        // Coerce to a plain integer before interpolating into the selector: the
        // WS frame supplies `id` via an unchecked `as number` cast, so a
        // non-numeric value could otherwise break out of the attribute selector.
        const safeId = Math.trunc(Number(id));
        if (!Number.isFinite(safeId))
            return;
        const row = document.querySelector(`.chat-file-row[data-id="${safeId}"]`);
        row?.remove();
        // If that was the last row, flip to empty state.
        const list = document.getElementById('chat-files-list');
        if (list && list.children.length === 0) {
            document.getElementById('chat-files-empty')?.classList.remove('hidden');
            const subtitle = document.getElementById('chat-files-subtitle');
            if (subtitle)
                subtitle.textContent = '';
        }
    }
    /** Fire-and-forget badge refresh: asks the server for the current count
     * without opening the modal. Called after upload + delete. */
    refreshChatFilesBadge() {
        if (!this.currentConversation || !this.connected)
            return;
        this.send({
            type: 'list_conversation_documents',
            conversation_id: this.currentConversation.id,
        });
    }
    /** Set the 📎 badge count on the chat-header button. Hidden when 0. */
    updateChatFilesBadge(count) {
        const badge = document.getElementById('chat-files-badge');
        if (!badge)
            return;
        badge.textContent = String(count);
        badge.classList.toggle('hidden', count <= 0);
    }
    // ========================================================================
    // Message Edit / Delete
    // ========================================================================
    startAiEditMessage(msgIdx) {
        if (this.isStreaming)
            return;
        const msg = this.messages[msgIdx];
        if (!msg || msg.role !== 'assistant' || !msg.id)
            return;
        const container = document.getElementById('chat-messages');
        if (!container)
            return;
        const msgElements = container.querySelectorAll('.chat-message');
        // With virtualization the DOM only contains messages.slice(visibleStartIdx);
        // translate the absolute index into the local DOM index.
        const msgEl = msgElements[msgIdx - this.visibleStartIdx];
        if (!msgEl)
            return;
        const contentEl = msgEl.querySelector('.message-content');
        const actionsEl = msgEl.querySelector('.message-actions');
        if (!contentEl)
            return;
        // Insert AI edit instruction input below the message content
        const editBar = document.createElement('div');
        editBar.className = 'ai-edit-bar';
        editBar.innerHTML = `
            <div class="ai-edit-label">${icon('sparkle')} Tell AI how to edit this message:</div>
            <div class="ai-edit-input-row">
                <textarea class="ai-edit-input" rows="1" placeholder="e.g. Make it shorter, Add examples, Translate to English..."></textarea>
                <button class="ai-edit-submit-btn">Send</button>
                <button class="ai-edit-cancel-btn">Cancel</button>
            </div>
        `;
        // Hide action buttons and append bar after content
        if (actionsEl)
            actionsEl.style.display = 'none';
        contentEl.after(editBar);
        const inputEl = editBar.querySelector('.ai-edit-input');
        inputEl?.focus();
        const submitEdit = () => {
            // The edit bar can stay open while a normal message starts a
            // stream; two concurrent streams on one socket garble both
            // (the backend allows up to 4 concurrent tasks per client).
            if (this.isStreaming) {
                showToast('Wait for the current response to finish', { type: 'warning' });
                return;
            }
            const instruction = inputEl?.value?.trim();
            if (!instruction) {
                showToast('Please enter an instruction', { type: 'warning' });
                return;
            }
            editBar.remove();
            if (actionsEl)
                actionsEl.style.display = '';
            const thinkingToggle = document.getElementById('thinking-toggle');
            const userName = settings.userName || 'User';
            const sent = this.send({
                type: 'ai_edit_message',
                conversation_id: this.currentConversation?.id,
                target_message_id: msg.id,
                instruction,
                role_preset: this.currentConversation?.role_preset || 'general',
                thinking_enabled: thinkingToggle?.checked || false,
                user_name: userName,
                ai_provider: this.aiProvider,
            });
            // Close the streaming gate so a normal message can't be sent
            // concurrently before the backend's stream_start arrives.
            if (sent) {
                this.isStreaming = true;
                this.setInputEnabled(false);
            }
        };
        editBar.querySelector('.ai-edit-submit-btn')?.addEventListener('click', submitEdit);
        editBar.querySelector('.ai-edit-cancel-btn')?.addEventListener('click', () => {
            editBar.remove();
            if (actionsEl)
                actionsEl.style.display = '';
        });
        inputEl?.addEventListener('keydown', (e) => {
            // IME guard: Enter that commits a Korean/Japanese/Chinese
            // composition must not submit (keydown fires with isComposing).
            if (e.isComposing || e.keyCode === 229)
                return;
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                submitEdit();
            }
            if (e.key === 'Escape') {
                editBar.remove();
                if (actionsEl)
                    actionsEl.style.display = '';
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
    startEditMessage(msgIdx) {
        if (this.isStreaming)
            return;
        const msg = this.messages[msgIdx];
        if (!msg)
            return;
        // Find the message element in DOM
        const container = document.getElementById('chat-messages');
        if (!container)
            return;
        const msgElements = container.querySelectorAll('.chat-message');
        // With virtualization the DOM only contains messages.slice(visibleStartIdx);
        // translate the absolute index into the local DOM index.
        const msgEl = msgElements[msgIdx - this.visibleStartIdx];
        if (!msgEl)
            return;
        const contentEl = msgEl.querySelector('.message-content');
        const actionsEl = msgEl.querySelector('.message-actions');
        if (!contentEl)
            return;
        // Replace content with textarea
        const originalContent = msg.content;
        contentEl.innerHTML = `
            <textarea class="edit-textarea">${escapeHtml(originalContent)}</textarea>
            <div class="edit-actions">
                <button class="edit-save-btn">Save</button>
                <button class="edit-save-regen-btn${msg.role === 'user' ? '' : ' hidden'}">Save &amp; Regenerate</button>
                <button class="edit-cancel-btn">Cancel</button>
            </div>
        `;
        if (actionsEl)
            actionsEl.style.display = 'none';
        const textarea = contentEl.querySelector('.edit-textarea');
        if (textarea) {
            textarea.focus();
            textarea.setSelectionRange(textarea.value.length, textarea.value.length);
            // Auto-resize
            textarea.style.height = Math.min(textarea.scrollHeight, 300) + 'px';
        }
        // Save button (edit only, no regenerate)
        contentEl.querySelector('.edit-save-btn')?.addEventListener('click', () => {
            const newContent = contentEl.querySelector('.edit-textarea')?.value?.trim();
            if (newContent && newContent !== originalContent) {
                this.saveEdit(msgIdx, newContent, false);
            }
            else {
                this.cancelEdit(msgIdx, originalContent);
            }
        });
        // Save & Regenerate button (edit + regenerate AI response)
        contentEl.querySelector('.edit-save-regen-btn')?.addEventListener('click', () => {
            const newContent = contentEl.querySelector('.edit-textarea')?.value?.trim();
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
    saveEdit(msgIdx, newContent, regenerate) {
        const msg = this.messages[msgIdx];
        if (!msg)
            return;
        if (msg.id == null) {
            // No DB id yet (stream_end id-backfill missing / protocol drift):
            // the server would silently drop an edit_message with message_id
            // undefined, leaving the bubble stuck in the textarea. Surface it
            // and restore the bubble instead.
            showToast('Message not yet saved — try again in a moment', { type: 'warning' });
            this.cancelEdit(msgIdx, msg.content);
            return;
        }
        this.send({
            type: 'edit_message',
            message_id: msg.id,
            content: newContent,
            conversation_id: this.currentConversation?.id,
            regenerate,
        });
    }
    cancelEdit(msgIdx, originalContent) {
        // Re-render the single message back to normal
        const container = document.getElementById('chat-messages');
        if (!container)
            return;
        const msgElements = container.querySelectorAll('.chat-message');
        // With virtualization the DOM only contains messages.slice(visibleStartIdx);
        // translate the absolute index into the local DOM index.
        const msgEl = msgElements[msgIdx - this.visibleStartIdx];
        if (!msgEl)
            return;
        const contentEl = msgEl.querySelector('.message-content');
        const actionsEl = msgEl.querySelector('.message-actions');
        if (contentEl) {
            contentEl.innerHTML = this.formatMessage(this.stripThinkTags(originalContent));
            // formatMessage doesn't syntax-highlight (separate async pass) — re-
            // highlight so a cancelled edit of a code block isn't left as plain
            // text until the next full render (mirrors finalizeStreamingMessage).
            void this.highlightCodeBlocks(contentEl);
        }
        if (actionsEl)
            actionsEl.style.display = '';
    }
    deleteMessage(msgIdx) {
        if (this.isStreaming)
            return;
        const msg = this.messages[msgIdx];
        if (!msg || msg.id == null)
            return;
        const isUser = msg.role === 'user';
        // For user messages, also delete the paired AI response (next message)
        let pairId;
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
            // Scope the delete to the currently open conversation. The
            // backend validates the message belongs to this conversation
            // and refuses cross-conversation deletes (defence-in-depth
            // against a stale client UI deleting the wrong message).
            conversation_id: this.currentConversation?.id ?? null,
        });
    }
    regenerateAfterEdit(editedMsg) {
        if (!this.currentConversation)
            return;
        // Build history from messages before the edited message
        // Strip unnecessary fields (images/thinking/mode) to reduce payload size,
        // but keep `created_at` so the backend retains per-message timing.
        const editedIdx = this.messages.indexOf(editedMsg);
        const historyToSend = this.messages.slice(0, editedIdx).map(m => ({
            role: m.role,
            content: m.content,
            created_at: m.created_at,
        }));
        const thinkingToggle = document.getElementById('thinking-toggle');
        const searchToggle = document.getElementById('chat-use-search');
        const unrestrictedToggle = document.getElementById('chat-unrestricted');
        const userName = settings.userName || 'User';
        // Carry over the original message's images/documents so the
        // regenerated reply still has the attachments to reason over.
        // Without this, a regenerate on a turn that originally had a PDF
        // attached would produce a reply written with no doc context.
        const originalImages = (editedMsg.images && editedMsg.images.length > 0) ? editedMsg.images : [];
        // Extract once into a local instead of casting the same expression
        // three times — the repeated cast was noisy and made it easy to
        // miss if one of the three branches drifted.
        const editedDocs = editedMsg.documents;
        const originalDocs = (editedDocs && editedDocs.length > 0) ? editedDocs : undefined;
        const sent = this.send({
            type: 'message',
            conversation_id: this.currentConversation.id,
            content: editedMsg.content,
            role_preset: this.currentConversation.role_preset,
            thinking_enabled: thinkingToggle?.checked || false,
            history: historyToSend,
            use_search: searchToggle?.checked ?? true,
            unrestricted_mode: unrestrictedToggle?.checked || false,
            images: originalImages,
            documents: originalDocs,
            user_name: userName,
            ai_provider: this.aiProvider,
            is_regeneration: true, // Skip duplicate user message save in backend
        });
        // Close the streaming gate immediately (mirrors sendMessage) so a
        // second send can't slip through before the backend's stream_start
        // frame arrives. Only lock if the frame actually went out.
        if (sent) {
            this.isStreaming = true;
            this.setInputEnabled(false);
        }
    }
    showNewChatModal() {
        const modal = document.getElementById('new-chat-modal');
        if (modal) {
            modal.classList.add('active');
            this.selectedRole = 'general';
            // Restore saved preferences for new chat
            const savedThinking = localStorage.getItem('dashboard_thinking') === 'true';
            this.thinkingEnabled = savedThinking;
            const modalThinking = document.getElementById('modal-thinking');
            if (modalThinking)
                modalThinking.checked = savedThinking;
            // Restore saved provider preference from localStorage
            // (this.aiProvider may have been overridden by loading a different conversation)
            const savedProvider = localStorage.getItem('dashboard_ai_provider');
            const modalProvider = document.getElementById('modal-ai-provider');
            if (modalProvider) {
                modalProvider.value = (savedProvider && this.availableProviders.includes(savedProvider))
                    ? savedProvider
                    : this.aiProvider;
            }
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
            const isSelected = card.dataset.role === this.selectedRole;
            card.classList.toggle('selected', isSelected);
            // Reflect selection to assistive tech: the cards form a
            // role="radiogroup" of role="radio" items, so aria-checked (not
            // aria-pressed) is the correct state. Roving tabindex keeps a
            // single tab stop for the group — only the checked radio is
            // tabbable; arrow keys move focus within (see the keydown handler).
            card.setAttribute('aria-checked', String(isSelected));
            card.tabIndex = isSelected ? 0 : -1;
        });
    }
    updateProviderSelects() {
        // Update both the modal and inline header select elements
        const selects = [
            document.getElementById('modal-ai-provider'),
            document.getElementById('chat-ai-provider'),
        ];
        for (const select of selects) {
            if (!select)
                continue;
            select.innerHTML = '';
            for (const provider of this.availableProviders) {
                const option = document.createElement('option');
                option.value = provider;
                // Label via a map with a capitalize fallback. The old ternary
                // labelled EVERY non-gemini provider "Claude" — so a third
                // provider (e.g. "openai") would be mislabelled. The fallback
                // capitalizes the raw id so an unknown provider at least shows a
                // sensible name instead of the wrong one.
                option.textContent = providerLabel(provider);
                select.appendChild(option);
            }
            select.value = this.aiProvider;
        }
    }
    downloadExport(data) {
        const id = typeof data.id === 'string' ? data.id : '';
        const format = typeof data.format === 'string' ? data.format : 'txt';
        const content = typeof data.data === 'string' ? data.data : '';
        if (!content) {
            showToast('Export failed: no content received', { type: 'error' });
            return;
        }
        const filename = `chat_${id.slice(0, 8)}_${Date.now()}.${format}`;
        const mime = { json: 'application/json', markdown: 'text/markdown', html: 'text/html', txt: 'text/plain' }[format] ?? 'text/plain';
        const blob = new Blob([content], { type: mime });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        a.click();
        // Defer revoke. Calling revokeObjectURL synchronously after .click()
        // can cancel an in-flight download in Firefox / older Edge because
        // the actual fetch of the blob: URL is async. 1s is a comfortable
        // upper bound on the time the browser needs to start streaming.
        setTimeout(() => URL.revokeObjectURL(url), 1000);
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
        const roleCards = Array.from(document.querySelectorAll('.role-card'));
        roleCards.forEach((card, idx) => {
            const select = () => this.selectRole(card.dataset.role || 'general');
            card.addEventListener('click', select);
            // role-cards form a role="radiogroup"; Enter/Space activate the
            // focused radio and Arrow keys move selection + focus within the
            // group (roving tabindex managed by updateRoleSelection()).
            card.addEventListener('keydown', (e) => {
                const ke = e;
                if (ke.key === 'Enter' || ke.key === ' ') {
                    ke.preventDefault();
                    select();
                    return;
                }
                let delta = 0;
                if (ke.key === 'ArrowDown' || ke.key === 'ArrowRight')
                    delta = 1;
                else if (ke.key === 'ArrowUp' || ke.key === 'ArrowLeft')
                    delta = -1;
                if (delta === 0)
                    return;
                ke.preventDefault();
                const next = roleCards[(idx + delta + roleCards.length) % roleCards.length];
                if (!next)
                    return;
                this.selectRole(next.dataset.role || 'general');
                next.focus();
            });
        });
        document.getElementById('modal-thinking')?.addEventListener('change', (e) => {
            this.thinkingEnabled = e.target.checked;
            localStorage.setItem('dashboard_thinking', String(this.thinkingEnabled));
        });
        // AI provider selector in chat header
        document.getElementById('chat-ai-provider')?.addEventListener('change', (e) => {
            this.aiProvider = e.target.value;
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
            localStorage.setItem('dashboard_unrestricted', String(e.target.checked));
        });
        document.getElementById('btn-send')?.addEventListener('click', () => this.sendMessage());
        document.getElementById('thinking-toggle')?.addEventListener('change', (e) => {
            if (this.currentConversation) {
                this.currentConversation.thinking_enabled = e.target.checked;
                localStorage.setItem('dashboard_thinking', String(e.target.checked));
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
            if (!this.currentConversation)
                return;
            const format = await this.promptExportFormat();
            if (format)
                this.exportConversation(this.currentConversation.id, format);
        });
        document.getElementById('btn-export-all')?.addEventListener('click', async () => {
            if (this.conversations.length === 0) {
                showToast('No conversations to export', { type: 'warning' });
                return;
            }
            const format = await this.promptExportFormat();
            if (!format)
                return;
            // Serialize: parallel forEach fires N export WS messages and N
            // synthetic <a>.click() downloads in the same event tick. Browsers
            // consolidate/block all but the first. Space them out so each
            // download sees a fresh tick.
            for (const conv of this.conversations) {
                this.exportConversation(conv.id, format);
                await new Promise(resolve => setTimeout(resolve, 250));
            }
        });
        document.getElementById('btn-delete-chat')?.addEventListener('click', () => {
            if (this.currentConversation) {
                this.deleteConversation(this.currentConversation.id);
            }
        });
        // Attached files modal — opens per-conversation document list
        document.getElementById('btn-chat-files')?.addEventListener('click', () => {
            this.openChatFilesModal();
        });
        document.querySelectorAll('[data-close-files]').forEach(el => {
            el.addEventListener('click', () => {
                // Closing from editor view should bail editing too, not
                // just re-hide the modal with the editor still "open".
                this.closeChatFileEditor();
                this.closeChatFilesModal();
            });
        });
        // Chat-file editor controls
        document.getElementById('chat-files-edit-back')?.addEventListener('click', () => {
            this.closeChatFileEditor();
        });
        document.getElementById('chat-files-edit-cancel')?.addEventListener('click', () => {
            this.closeChatFileEditor();
        });
        document.getElementById('chat-files-edit-save')?.addEventListener('click', () => {
            this.saveChatFileEditor();
        });
        document.getElementById('chat-files-edit-reflow')?.addEventListener('click', () => {
            this.reflowChatFileEditor();
        });
        document.getElementById('chat-files-edit-text')?.addEventListener('input', () => {
            this.updateChatFileEditorCounter();
        });
        // Ctrl/Cmd+S inside the editor textarea = save, same as RP Notes.
        document.getElementById('chat-files-edit-text')?.addEventListener('keydown', (e) => {
            const ev = e;
            if ((ev.ctrlKey || ev.metaKey) && ev.key === 's') {
                ev.preventDefault();
                this.saveChatFileEditor();
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
            // IME guard — Enter committing a composition must not confirm.
            if (e.isComposing || e.keyCode === 229)
                return;
            if (e.key === 'Enter') {
                e.preventDefault();
                this.confirmRename();
            }
            else if (e.key === 'Escape') {
                this.closeRenameModal();
            }
        });
        const input = document.getElementById('chat-input');
        input?.addEventListener('input', () => {
            this.autoResizeInput();
            // Debounce draft save per conversation
            if (this.currentConversation) {
                if (this.draftSaveTimer !== null)
                    clearTimeout(this.draftSaveTimer);
                this.draftSaveTimer = window.setTimeout(() => {
                    const el = document.getElementById('chat-input');
                    if (this.currentConversation && el) {
                        this.saveDraft(this.currentConversation.id, el.value);
                    }
                    this.draftSaveTimer = null;
                }, 400);
            }
        });
        input?.addEventListener('keydown', (e) => {
            // IME guard: in Chromium/WebView2 the Enter that COMMITS a
            // Korean/Japanese/Chinese composition fires keydown with
            // isComposing=true (keyCode 229) — sending here would submit a
            // half-composed message for this dashboard's Korean UI users.
            if (e.isComposing || e.keyCode === 229)
                return;
            if (e.key === 'Enter' && !e.shiftKey) {
                // Enter = send, Shift+Enter = new line
                e.preventDefault();
                this.sendMessage();
            }
        });
        // Ping/pong keepalive is now owned by WebSocketClient — it starts the
        // loop on every `onopen` and stops on `onclose`. Nothing to do here.
    }
}
// ============================================================================
// Module-level instances
// ============================================================================
export let chatManager = null;
export function initChatManager() {
    chatManager = new ChatManager();
    chatManager.init();
    window.chatManager = chatManager;
}
//# sourceMappingURL=chat-manager.js.map