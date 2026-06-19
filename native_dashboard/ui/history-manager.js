/**
 * AI History page manager.
 *
 * Owns everything inside #page-history: the channel list (Discord channels
 * that have ai_history rows), the message viewer, and the click-to-edit /
 * click-to-delete flow for a message. Talks to the Python backend over the
 * SAME dashboard WebSocket that ChatManager owns — ChatManager forwards the
 * five `ai_*` frame types here (see chat-manager.ts handleMessage), and
 * outgoing frames go through the injected `send` callback (ChatManager.send),
 * which returns false + toasts when the socket is down.
 *
 * Wire contract (backend implements the mirror image):
 *   out: {type:'list_ai_channels'}
 *        {type:'load_ai_history', channel_id:'<digits>', limit:200|2000}
 *        {type:'edit_ai_history_message', channel_id:'<digits>', id:<row id>, content:'…'}
 *        {type:'delete_ai_history_message', channel_id:'<digits>', id:<row id>}
 *        {type:'restore_ai_history_message', channel_id:'<digits>', message:{…}}
 *          (message is byte-for-byte the object received in ai_history_loaded —
 *           snowflakes still strings; re-INSERTs the row under its original PK id)
 *   in:  {type:'ai_channels_list', channels:[{channel_id, name, message_count, last_active}]}
 *        {type:'ai_history_loaded', channel_id, messages:[…], total_count, has_more}
 *        {type:'ai_history_message_edited', channel_id, id, content, live_session, live_session_patched}
 *        {type:'ai_history_message_deleted', channel_id, id, live_session, live_session_patched, total_count}
 *        {type:'ai_history_message_restored', channel_id, id, live_session, live_session_patched, total_count}
 *
 * live_session ('patched' | 'not_loaded' | 'no_match' | 'unavailable' |
 * 'error') reports what happened to the bot's in-RAM session alongside the
 * DB write; older backends send only the boolean live_session_patched
 * (true ⟺ 'patched'). See notifyMutationOutcome for the toast mapping.
 *
 * Snowflakes (channel_id / message_id / user_id) are STRINGS in JSON — they
 * exceed Number.MAX_SAFE_INTEGER. Only the ai_history row `id` and `local_id`
 * are JS numbers.
 *
 * Rendering follows the conversation-list.ts house pattern: innerHTML with
 * escapeHtml on EVERY interpolation, a render cap with an overflow note, and
 * ONE delegated container-level click handler stored on the element and
 * replaced each render.
 */
import { escapeHtml, icon, normalizeSqliteUtc, showConfirmDialog, showToast } from './shared.js';
/** Channels beyond this count are not rendered (overflow note instead). */
const CHANNEL_RENDER_CAP = 200;
/** Message rows beyond this count are not rendered (newest kept). */
const MESSAGE_RENDER_CAP = 500;
/** Mirrors the backend's MAX_EDIT_CONTENT_LENGTH — pre-validate client-side. */
const MAX_EDIT_CONTENT_LENGTH = 200000;
/** Default page size for a channel open; "Load all" re-requests with the server max. */
const DEFAULT_LOAD_LIMIT = 200;
const FULL_LOAD_LIMIT = 2000;
/** Oldest undo entries are shifted out beyond this many. */
const UNDO_STACK_MAX = 20;
/**
 * Rejection codes for which re-sending the identical mutation can never
 * succeed — the backend deterministically rejects the payload. ROW_CONFLICT
 * covers both "the message was re-saved under a new row id" and "history was
 * rewritten since this undo was recorded" (a force-replace save staled the
 * entry). A failed undo carrying one of these is DROPPED from the stack
 * (otherwise it permanently shadows every older undo in its channel);
 * codeless/transient failures (rate limit, INTERNAL_ERROR, DB_UNAVAILABLE,
 * reconnects) keep the entry so the user can retry.
 */
const PERMANENT_HISTORY_ERROR_CODES = new Set([
    'ROW_CONFLICT',
    'MSG_NOT_FOUND',
    'INVALID_ID',
    'INVALID_PAYLOAD',
    'CONTENT_TOO_LONG',
]);
/** Short absolute timestamp for message rows, e.g. "Jun 11, 15:32". */
function formatTimestamp(iso) {
    if (!iso)
        return '';
    try {
        // SQLite naive timestamps are UTC — append Z so JS doesn't misread
        // them as local time (same normalization as formatChatFileDate).
        const d = new Date(normalizeSqliteUtc(iso));
        if (Number.isNaN(d.getTime()))
            return iso;
        return d.toLocaleString(undefined, {
            month: 'short', day: 'numeric',
            hour: '2-digit', minute: '2-digit',
        });
    }
    catch {
        return iso;
    }
}
/** Relative-ish "last active" display for the channel list. */
function formatLastActive(iso) {
    if (!iso)
        return 'no activity';
    try {
        const d = new Date(normalizeSqliteUtc(iso));
        if (Number.isNaN(d.getTime()))
            return iso;
        const diffMin = Math.floor((Date.now() - d.getTime()) / 60000);
        if (diffMin < 1)
            return 'just now';
        if (diffMin < 60)
            return `${diffMin}m ago`;
        const diffH = Math.floor(diffMin / 60);
        if (diffH < 24)
            return `${diffH}h ago`;
        const diffD = Math.floor(diffH / 24);
        if (diffD < 7)
            return `${diffD}d ago`;
        return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
    }
    catch {
        return iso;
    }
}
export class HistoryManager {
    callbacks;
    channels = [];
    currentChannelId = null;
    messages = [];
    totalCount = 0;
    hasMore = false;
    /**
     * True when the server clipped the last ai_history_loaded payload by its
     * content-size budget — a re-request cannot return more rows, so the
     * Load-all button must not promise otherwise.
     */
    truncated = false;
    /** Absolute index (into this.messages) of the row in edit mode, or null. */
    editingIdx = null;
    // Most-recent channel id passed to openChannel()/loadAll(). The
    // ai_history_loaded handler compares against this to drop stale frames
    // when the user switches channels rapidly (copies ChatManager's
    // pendingConversationLoadId pattern).
    pendingChannelLoadId = null;
    // Set when a list_ai_channels send failed (socket down) so the request
    // can be flushed once ChatManager's 'connected' frame arrives.
    pendingChannelsList = false;
    // Channel load (openChannel/loadAll) that could not be sent because the
    // socket was down — flushed by onConnected(), cleared when the matching
    // ai_history_loaded arrives and when the user switches channels.
    pendingChannelLoad = null;
    /**
     * True while an edit_ai_history_message OR delete_ai_history_message is
     * awaiting the server ack — one mutation in flight at a time, so edit and
     * delete can never overlap (the name predates the delete op).
     */
    editInFlight = false;
    // Limit of the most recent channel load (200 default / 2000 after
    // "Load all") so a Refresh re-requests the same window instead of
    // collapsing a fully-loaded view back to the newest 200.
    lastLoadLimit = DEFAULT_LOAD_LIMIT;
    // Set by refresh() so the next ai_channels_list arrival confirms with a
    // "Refreshed" toast — page-enter/reconnect listings stay silent.
    refreshFeedbackPending = false;
    /**
     * Ack-confirmed undo history (newest last), capped at UNDO_STACK_MAX.
     * Entries are pushed ONLY when the matching edited/deleted ack arrives —
     * a rejected or unsendable mutation never lands here.
     */
    undoStack = [];
    /**
     * Mutation sent but not yet ack-confirmed — promoted onto undoStack by
     * the matching edited/deleted ack. Keyed by channel+id (NOT by the
     * current view): the acks clear editInFlight before the foreign-channel
     * guard, and the DB mutation happened regardless of which channel is
     * open when the ack lands, so foreign-channel acks must still push.
     */
    pendingUndoCandidate = null;
    /**
     * The stack entry whose undo is currently awaiting its success ack
     * (edited ack for an 'edit' entry, restored ack for a 'delete' entry).
     * Popped on that ack; a codeless/transient onError or a reconnect
     * (onConnected) clears this marker but KEEPS the entry so the user can
     * retry the undo, while an onError carrying a PERMANENT rejection code
     * (PERMANENT_HISTORY_ERROR_CODES) drops the entry too — retrying could
     * only fail identically and would shadow older undos in the channel.
     */
    pendingUndo = null;
    notify;
    confirmDialog;
    /**
     * Channel-list filter text (lower-cased on apply). Debounced like
     * ConversationList's filter so typing across a capped 200-channel list
     * doesn't re-run the O(n) innerHTML build on every keystroke. The hidden
     * overflow ("N more channels hidden") is only reachable by narrowing here.
     */
    channelFilter = '';
    channelFilterDebounce = null;
    /**
     * In-transcript find state (Ctrl+F over the open channel's messages).
     * Mirrors the chat/search.ts idea — a TreeWalker over the rendered text
     * nodes wraps each hit in <mark class="chat-search-hit"> and ↑/↓ steps
     * through them — but uses its OWN #ai-history-search-* ids so it never
     * collides with the chat page's #chat-search-* nodes (duplicate ids would
     * break both). Self-contained here because chat/search.ts hardcodes the
     * chat ids and exports no reusable helper. Lets the user reach content the
     * 500-row render cap hides only by index, complementing the cap note.
     */
    findMatches = [];
    findIdx = -1;
    /** True from openChannel() until the matching ai_history_loaded lands —
     *  drives the spinner/skeleton loading pane. */
    loading = false;
    /** Guards the one-time DOM scaffold + listener wiring in init(). */
    chromeBuilt = false;
    constructor(callbacks) {
        this.callbacks = callbacks;
        this.notify = callbacks.notify ?? showToast;
        this.confirmDialog = callbacks.confirmDialog ?? showConfirmDialog;
    }
    /** Bind the static buttons (refresh / load-all / undo) once. Idempotent. */
    init() {
        const refreshBtn = document.getElementById('ai-history-refresh');
        if (refreshBtn && !refreshBtn.dataset.historyBound) {
            refreshBtn.dataset.historyBound = '1';
            refreshBtn.addEventListener('click', () => this.refresh());
        }
        const loadAllBtn = document.getElementById('ai-history-load-all');
        if (loadAllBtn && !loadAllBtn.dataset.historyBound) {
            loadAllBtn.dataset.historyBound = '1';
            loadAllBtn.addEventListener('click', () => this.loadAll());
        }
        const undoBtn = document.getElementById('ai-history-undo');
        if (undoBtn && !undoBtn.dataset.historyBound) {
            undoBtn.dataset.historyBound = '1';
            undoBtn.addEventListener('click', () => this.undo());
        }
        this.buildChrome();
    }
    // ------------------------------------------------------------------
    // Search / filter chrome — built dynamically (the static index.html has
    // no filter/find nodes for this page). Idempotent: the elements carry
    // their own ids and we guard with chromeBuilt + an in-DOM existence check
    // so a re-init (hot reload) or a fresh test DOM rebuilds cleanly.
    // ------------------------------------------------------------------
    /**
     * Inject the channel-filter input (above #ai-channel-list) and the
     * in-transcript find bar (above #ai-history-messages) once, then bind the
     * page-scoped Ctrl+F shortcut. No-op once built unless the nodes are gone
     * (a new DOM, e.g. a test rerun, rebuilds them).
     */
    buildChrome() {
        this.buildChannelFilter();
        this.buildFindBar();
        if (!this.chromeBuilt) {
            // Page-scoped Ctrl+F: only when the History page is the active one
            // (app.ts toggles `.active` on the .page sections). The chat page
            // owns its own Ctrl+F, so we gate on visibility to avoid stealing it.
            document.addEventListener('keydown', (e) => {
                if (e.ctrlKey && e.key.toLowerCase() === 'f') {
                    const page = document.getElementById('page-history');
                    if (page && page.classList.contains('active')) {
                        e.preventDefault();
                        this.openFind();
                    }
                }
            });
            this.chromeBuilt = true;
        }
    }
    /** Create #ai-history-channel-filter above the channel list, once. */
    buildChannelFilter() {
        if (document.getElementById('ai-history-channel-filter'))
            return;
        const list = document.getElementById('ai-channel-list');
        const parent = list?.parentElement;
        if (!list || !parent)
            return;
        const wrap = document.createElement('div');
        wrap.className = 'history-channel-filter';
        wrap.setAttribute('role', 'search');
        wrap.innerHTML =
            `<input type="search" id="ai-history-channel-filter" class="history-filter-input"`
                + ` placeholder="Filter channels…" aria-label="Filter AI history channels by name">`;
        parent.insertBefore(wrap, list);
        const input = wrap.querySelector('#ai-history-channel-filter');
        input.addEventListener('input', () => {
            // Debounce — re-filtering a 200-row capped list on every keystroke
            // is an O(n) innerHTML rebuild (same rationale as ConversationList).
            if (this.channelFilterDebounce !== null)
                clearTimeout(this.channelFilterDebounce);
            this.channelFilterDebounce = window.setTimeout(() => {
                this.channelFilter = input.value;
                this.channelFilterDebounce = null;
                this.renderChannelList();
            }, 120);
        });
    }
    /** Create the #ai-history-search-bar find strip above the message viewer, once. */
    buildFindBar() {
        if (document.getElementById('ai-history-search-bar'))
            return;
        const messages = document.getElementById('ai-history-messages');
        const parent = messages?.parentElement;
        if (!messages || !parent)
            return;
        const bar = document.createElement('div');
        bar.className = 'history-search-bar hidden';
        bar.id = 'ai-history-search-bar';
        bar.setAttribute('role', 'search');
        bar.innerHTML =
            `<input type="text" id="ai-history-search-input" placeholder="Find in transcript…" aria-label="Find in transcript">`
                + `<span class="history-search-count" id="ai-history-search-count" role="status" aria-live="polite">0 / 0</span>`
                + `<button class="btn btn-icon" id="ai-history-search-prev" type="button" title="Previous match" aria-label="Previous match">${icon('chevron-up')}</button>`
                + `<button class="btn btn-icon" id="ai-history-search-next" type="button" title="Next match" aria-label="Next match">${icon('chevron-down')}</button>`
                + `<button class="btn btn-icon" id="ai-history-search-close" type="button" title="Close (Esc)" aria-label="Close find">${icon('x')}</button>`;
        parent.insertBefore(bar, messages);
        const input = bar.querySelector('#ai-history-search-input');
        let debounce = null;
        input.addEventListener('input', () => {
            if (debounce !== null)
                clearTimeout(debounce);
            debounce = window.setTimeout(() => {
                this.performFind(input.value);
                debounce = null;
            }, 120);
        });
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                this.stepFind(e.shiftKey ? -1 : 1);
            }
            else if (e.key === 'Escape') {
                e.preventDefault();
                this.closeFind();
            }
        });
        bar.querySelector('#ai-history-search-next')?.addEventListener('click', () => this.stepFind(1));
        bar.querySelector('#ai-history-search-prev')?.addEventListener('click', () => this.stepFind(-1));
        bar.querySelector('#ai-history-search-close')?.addEventListener('click', () => this.closeFind());
    }
    /** Reveal the find bar and focus its input (Ctrl+F entry point). */
    openFind() {
        const bar = document.getElementById('ai-history-search-bar');
        const input = document.getElementById('ai-history-search-input');
        if (!bar || !input)
            return;
        bar.classList.remove('hidden');
        input.focus();
        input.select();
        // Re-run against the current DOM in case content changed since the last
        // open (so the count reflects what's actually rendered now).
        if (input.value)
            this.performFind(input.value);
    }
    /** Hide the find bar and strip its highlights. */
    closeFind() {
        const bar = document.getElementById('ai-history-search-bar');
        if (bar)
            bar.classList.add('hidden');
        this.clearFindHighlights();
        this.findMatches = [];
        this.findIdx = -1;
    }
    /** Wrap every hit in the rendered transcript and jump to the first. */
    performFind(query) {
        this.clearFindHighlights();
        this.findMatches = [];
        this.findIdx = -1;
        const container = document.getElementById('ai-history-messages');
        const countEl = document.getElementById('ai-history-search-count');
        if (container && query) {
            this.findMatches = wrapHistoryMatches(container, query);
            if (this.findMatches.length > 0)
                this.focusFind(0);
        }
        if (countEl) {
            countEl.textContent = `${this.findMatches.length ? this.findIdx + 1 : 0} / ${this.findMatches.length}`;
        }
    }
    /** Step ↑/↓ through the matches (re-runs if the DOM was re-rendered). */
    stepFind(direction) {
        if (this.findMatches.length === 0)
            return;
        // A re-render (renderMessages) detaches the old <mark> nodes — re-run
        // before stepping if any match is no longer connected.
        if (this.findMatches.some(m => !m.isConnected)) {
            const input = document.getElementById('ai-history-search-input');
            this.performFind(input?.value ?? '');
            return;
        }
        this.focusFind(this.findIdx + direction);
    }
    focusFind(idx) {
        if (this.findMatches.length === 0)
            return;
        idx = ((idx % this.findMatches.length) + this.findMatches.length) % this.findMatches.length;
        this.findMatches.forEach(m => m.classList.remove('active'));
        const target = this.findMatches[idx];
        target.classList.add('active');
        target.scrollIntoView({ block: 'center', behavior: 'smooth' });
        this.findIdx = idx;
        const countEl = document.getElementById('ai-history-search-count');
        if (countEl)
            countEl.textContent = `${idx + 1} / ${this.findMatches.length}`;
    }
    clearFindHighlights() {
        const container = document.getElementById('ai-history-messages');
        if (!container)
            return;
        container.querySelectorAll('mark.chat-search-hit').forEach(mark => {
            const parent = mark.parentNode;
            if (!parent)
                return;
            parent.replaceChild(document.createTextNode(mark.textContent || ''), mark);
            parent.normalize();
        });
    }
    /**
     * Page-enter hook (called from app.ts switchPage). Requests the channel
     * list; if the socket is still connecting, queues the request — it gets
     * flushed by onConnected() when ChatManager receives 'connected'.
     */
    onEnter() {
        // Check connectivity BEFORE send() — ws-client.send toasts a spurious
        // "Not connected" error while the socket is still connecting, even
        // though the request is correctly queued and flushed by onConnected().
        if (!this.callbacks.isConnected()) {
            this.pendingChannelsList = true;
            this.renderDisconnected();
            return;
        }
        if (!this.callbacks.send({ type: 'list_ai_channels' })) {
            this.pendingChannelsList = true;
            this.renderDisconnected();
        }
    }
    /** Forwarded by ChatManager from its 'connected' frame (incl. reconnects). */
    onConnected() {
        // An in-flight edit/delete ack can never arrive across a reconnect —
        // the backend replies only on the originating connection — so unstick
        // the pending mutation (re-enable Save / the delete button, keep any
        // typed text). Re-sending afterwards is idempotent. Deliberately
        // CODELESS: a reconnect is transient, so an orphaned undo keeps its
        // stack entry for a retry.
        this.onError();
        if (this.pendingChannelsList) {
            this.pendingChannelsList = false;
            this.callbacks.send({ type: 'list_ai_channels' });
        }
        // Flush a channel load that could not be sent while the socket was
        // down — but only if that channel is still the open one.
        if (this.pendingChannelLoad) {
            const { channelId, limit } = this.pendingChannelLoad;
            this.pendingChannelLoad = null;
            if (channelId === this.currentChannelId) {
                this.pendingChannelLoadId = channelId;
                this.callbacks.send({
                    type: 'load_ai_history',
                    channel_id: channelId,
                    limit,
                });
            }
        }
        // The flush above may have (re)started a channel load — re-render so
        // the undo button reflects the pending-load gate.
        this.renderUndo();
    }
    /**
     * Forwarded by ChatManager from its 'error' frame (with the envelope's
     * `code` when it carries one). A rejected mutation (e.g. MSG_NOT_FOUND,
     * CONTENT_TOO_LONG) is answered with a plain error envelope instead of
     * ai_history_message_edited/_deleted, which would otherwise leave the
     * Save button (or the row's delete button) disabled forever. The toast
     * itself is shown by ChatManager; here we only unstick the pending
     * mutation and keep the user's text.
     */
    onError(code) {
        if (!this.editInFlight)
            return;
        this.editInFlight = false;
        // The rejected mutation can no longer be ack-confirmed — drop its
        // unconfirmed undo candidate. A rejected/orphaned UNDO clears the
        // in-flight marker; whether its stack entry survives depends on the
        // rejection: codeless/transient failures (rate limit, reconnect,
        // INTERNAL_ERROR, DB_UNAVAILABLE…) KEEP the entry so the user can
        // retry, while PERMANENT codes (ROW_CONFLICT — incl. "history was
        // rewritten since this undo was recorded" — MSG_NOT_FOUND…) drop it:
        // retrying the byte-identical frame can only fail the same way, and
        // the doomed entry would shadow every older undo in its channel.
        this.pendingUndoCandidate = null;
        const failed = this.pendingUndo;
        this.pendingUndo = null;
        if (failed !== null && code !== undefined && PERMANENT_HISTORY_ERROR_CODES.has(code)) {
            const i = this.undoStack.indexOf(failed.entry);
            if (i !== -1)
                this.undoStack.splice(i, 1);
            if (failed.entry.channelId === this.currentChannelId) {
                // Re-sync the open view (same window as the last load) so
                // the user sees what actually occupies the slot now.
                this.openChannel(failed.entry.channelId, this.lastLoadLimit);
            }
        }
        const container = document.getElementById('ai-history-messages');
        const saveBtn = container?.querySelector('.edit-save-btn');
        if (saveBtn)
            saveBtn.disabled = false;
        // A pending delete disables its row button the same way Save is —
        // re-enable it so the delete can be retried.
        container?.querySelectorAll('.history-delete-btn[disabled]').forEach(btn => {
            btn.disabled = false;
        });
        this.renderUndo();
    }
    /**
     * Refresh button: re-list the channels AND reload the open channel's
     * messages (same limit window as last loaded). Always gives feedback —
     * a "Refreshed" toast on completion, or a reconnect attempt + notice
     * when the socket is down — so the button never looks dead when the
     * data happens to be unchanged.
     */
    refresh() {
        if (!this.callbacks.isConnected()) {
            // Queue the listing AND kick off a reconnect — the page-enter
            // hook reconnects, but a socket that dropped while sitting on
            // this page otherwise leaves the button doing nothing visible.
            this.pendingChannelsList = true;
            this.refreshFeedbackPending = true;
            this.renderDisconnected();
            this.callbacks.connect?.();
            this.notify('Reconnecting — will refresh shortly', { type: 'info' });
            return;
        }
        if (!this.callbacks.send({ type: 'list_ai_channels' })) {
            this.pendingChannelsList = true;
            return;
        }
        this.refreshFeedbackPending = true;
        // Reload the open channel too — skipped while an editor is open or a
        // mutation ack is in flight (the reload's re-render would destroy the
        // draft / in-flight state), and while a load is already pending.
        if (this.currentChannelId !== null
            && this.editingIdx === null
            && !this.editInFlight
            && this.pendingChannelLoadId === null) {
            this.openChannel(this.currentChannelId, this.lastLoadLimit);
        }
    }
    /** Incoming frames forwarded from ChatManager.handleMessage. */
    handleMessage(data) {
        switch (data.type) {
            case 'ai_channels_list':
                this.channels = Array.isArray(data.channels)
                    ? data.channels
                    : [];
                this.renderChannelList();
                this.updateHeader();
                if (this.refreshFeedbackPending) {
                    // Explicit Refresh click — confirm even when nothing
                    // visibly changed, or the button looks dead.
                    this.refreshFeedbackPending = false;
                    this.notify('Refreshed', { type: 'success' });
                }
                break;
            case 'ai_history_loaded': {
                // Drop a late-arriving load for a channel the user already
                // switched away from (mirrors ChatManager's
                // pendingConversationLoadId guard on conversation_loaded).
                const cid = String(data.channel_id ?? '');
                const requestedId = this.pendingChannelLoadId;
                if (this.currentChannelId === null
                    || cid !== this.currentChannelId
                    || (requestedId !== null && cid !== requestedId)) {
                    break;
                }
                this.pendingChannelLoadId = null;
                // The load arrived — drop any queued re-send for it.
                this.pendingChannelLoad = null;
                // The wire contract says `id`/`local_id` are JS numbers, but the
                // frame is untrusted — coerce both at the door so a string `id`
                // can't (a) break out of the data-id="…" attribute in
                // messageRowHtml, (b) blow up the .history-msg[data-id="…"]
                // selectors in patch/remove/insertRowInPlace, or (c) miss the
                // `m.id === <number>` lookups in the edit/delete/restore acks.
                // Drop any row whose id won't coerce to a finite number (a bad
                // row has no safe identity to edit/delete against anyway).
                this.messages = Array.isArray(data.messages)
                    ? data.messages
                        .map(m => ({
                        ...m,
                        id: Number(m.id),
                        // local_id is carried verbatim into the restore
                        // round-trip; coerce when present, leave a missing
                        // one absent rather than poisoning it with NaN.
                        ...(m.local_id !== undefined
                            ? { local_id: Number(m.local_id) }
                            : {}),
                    }))
                        .filter(m => Number.isFinite(m.id))
                    : [];
                this.totalCount = Number(data.total_count) || this.messages.length;
                this.hasMore = data.has_more === true;
                // Optional flag: the server clipped the payload by content
                // budget — re-requesting cannot return more rows.
                this.truncated = data.truncated === true;
                this.editingIdx = null;
                this.editInFlight = false;
                this.loading = false;
                this.renderMessages();
                this.updateHeader();
                this.renderLoadAll();
                this.renderUndo();
                // Fresh load — jump to the newest (bottom) messages.
                const container = document.getElementById('ai-history-messages');
                if (container)
                    container.scrollTop = container.scrollHeight;
                break;
            }
            case 'ai_history_message_edited': {
                const cid = String(data.channel_id ?? '');
                const editedId = Number(data.id);
                this.editInFlight = false;
                // A spurious onError() (unrelated error frame on the shared
                // socket) may have cleared a still-in-flight edit-undo's
                // marker — recover it so this late ack still pops the entry.
                this.recoverPendingUndo('edited', cid, editedId, typeof data.content === 'string' ? data.content : undefined);
                // Undo bookkeeping BEFORE the foreign-channel guard: the DB
                // write happened regardless of which channel is open now, so
                // an ack that lands after a channel switch must still push
                // its candidate (and pop a completed undo's entry).
                this.settleUndoOnAck('edited', cid, editedId);
                if (this.currentChannelId === null || cid !== this.currentChannelId) {
                    // Edited a channel that is no longer open — nothing to
                    // re-render locally; the DB write already happened.
                    break;
                }
                const editedContent = typeof data.content === 'string' ? data.content : '';
                const target = this.messages.find(m => m.id === editedId);
                if (target)
                    target.content = editedContent;
                this.editingIdx = null;
                // In-place patch the single edited row instead of rebuilding the
                // whole list; fall back to a full render (preserving scroll) only
                // when the row isn't in the rendered cap window. An edit is never
                // a structural change — the row count and order don't move.
                const container = document.getElementById('ai-history-messages');
                const patched = container !== null
                    && this.patchRowContent(container, editedId, editedContent);
                if (!patched) {
                    const savedPos = container?.scrollTop ?? 0;
                    this.renderMessages();
                    if (container)
                        container.scrollTop = savedPos;
                }
                this.notifyMutationOutcome(data, 'edit');
                break;
            }
            case 'ai_history_message_deleted': {
                const cid = String(data.channel_id ?? '');
                const deletedId = Number(data.id);
                this.editInFlight = false;
                // Same as the edited ack: push the delete's undo candidate
                // even when the ack belongs to a no-longer-open channel.
                this.settleUndoOnAck('deleted', cid, deletedId);
                if (this.currentChannelId === null || cid !== this.currentChannelId) {
                    // Deleted from a channel that is no longer open — nothing
                    // to re-render locally; the DB delete already happened.
                    break;
                }
                const before = this.messages.length;
                // Try the in-place row removal BEFORE mutating this.messages —
                // removeRowInPlace reads the pre-removal length to decide whether
                // the cap window would shift (in which case it bails to a full
                // render). Then drop the row from the model regardless.
                const container = document.getElementById('ai-history-messages');
                const removedInPlace = container !== null
                    && this.messages.some(m => m.id === deletedId)
                    && this.removeRowInPlace(container, deletedId);
                this.messages = this.messages.filter(m => m.id !== deletedId);
                const removed = before - this.messages.length;
                // The ack carries the post-delete per-channel count; fall back
                // to a local decrement if a (mis-built) frame omits it.
                const newTotal = Number(data.total_count);
                this.totalCount = Number.isFinite(newTotal) && newTotal >= 0
                    ? newTotal
                    : Math.max(0, this.totalCount - removed);
                // No editor can be open while a delete is in flight (the
                // in-flight guard + cancel-before-delete enforce it), but a
                // re-render would orphan one regardless — clear defensively.
                this.editingIdx = null;
                if (!removedInPlace) {
                    const savedPos = container?.scrollTop ?? 0;
                    this.renderMessages();
                    if (container)
                        container.scrollTop = savedPos;
                }
                this.updateHeader();
                this.renderLoadAll();
                this.notifyMutationOutcome(data, 'delete');
                break;
            }
            case 'ai_history_message_restored': {
                const cid = String(data.channel_id ?? '');
                const restoredId = Number(data.id);
                this.editInFlight = false;
                // A spurious onError() (unrelated error frame on the shared
                // socket, e.g. a failing chat stream) may have cleared
                // pendingUndo while this restore was still genuinely in
                // flight — recover the entry from the stack so the late ack
                // still re-inserts the row and pops the entry.
                this.recoverPendingUndo('restored', cid, restoredId);
                // The ack carries only the row id — the message object to
                // re-insert lives on the pending-undo entry. Grab it BEFORE
                // settleUndoOnAck pops the entry off the stack.
                const pending = this.pendingUndo;
                const restoredMsg = pending !== null
                    && pending.entry.kind === 'delete'
                    && pending.entry.channelId === cid
                    && pending.entry.message.id === restoredId
                    ? pending.entry.message
                    : null;
                this.settleUndoOnAck('restored', cid, restoredId);
                if (this.currentChannelId === null || cid !== this.currentChannelId) {
                    // Restored into a channel that is no longer open —
                    // nothing to re-render locally; the DB insert happened.
                    break;
                }
                // Re-insert at the id-sorted position: this.messages is
                // ascending by id and ai_history orders by PK id, so the row
                // returns to its original spot. Skip when the id is already
                // present (idempotent already-restored ack).
                let insertedAt = -1;
                if (restoredMsg && !this.messages.some(m => m.id === restoredMsg.id)) {
                    let insertAt = this.messages.findIndex(m => m.id > restoredMsg.id);
                    if (insertAt === -1)
                        insertAt = this.messages.length;
                    this.messages.splice(insertAt, 0, restoredMsg);
                    insertedAt = insertAt;
                }
                // The ack carries the post-restore per-channel count; fall
                // back to a local increment if a (mis-built) frame omits it.
                const newTotal = Number(data.total_count);
                this.totalCount = Number.isFinite(newTotal) && newTotal >= 0
                    ? newTotal
                    : this.totalCount + 1;
                // No editor can be open while an undo is in flight (the
                // in-flight guard enforces it), but a re-render would orphan
                // one regardless — clear defensively (same as the delete ack).
                this.editingIdx = null;
                const container = document.getElementById('ai-history-messages');
                // In-place insert the single restored row when it lands inside
                // the rendered cap window; otherwise (older head, or the model
                // didn't change) fall back to a full render preserving scroll.
                const insertedInPlace = container !== null
                    && restoredMsg !== null
                    && insertedAt !== -1
                    && this.insertRowInPlace(container, restoredMsg, insertedAt);
                if (!insertedInPlace) {
                    const savedPos = container?.scrollTop ?? 0;
                    this.renderMessages();
                    if (container)
                        container.scrollTop = savedPos;
                }
                this.updateHeader();
                this.renderLoadAll();
                this.notifyMutationOutcome(data, 'restore');
                break;
            }
            default:
                // Not ours — ChatManager only forwards the five ai_* types,
                // so this is unreachable in practice. Keep quiet regardless.
                break;
        }
    }
    /**
     * Toast for an edit/delete/restore ack, keyed on the ack's live_session
     * state. The crucial split: a session that simply isn't loaded in bot RAM
     * (not_loaded/unavailable) is benign — the DB is the source of truth and
     * the next session load reads the fresh rows — so it gets a SUCCESS
     * toast, while a loaded session whose matcher missed (no_match/error)
     * genuinely warns: stale RAM can clobber the DB change on the next save.
     * Older backends omit live_session — fall back to the legacy toast keyed
     * on the live_session_patched boolean.
     */
    notifyMutationOutcome(data, op) {
        const successMsg = op === 'edit' ? 'Message edited'
            : op === 'delete' ? 'Message deleted'
                : 'Message restored';
        const staleRamMsg = op === 'edit'
            ? 'Edited in DB, but the bot\'s live memory may still hold the old text until reload'
            : op === 'delete'
                ? 'Deleted from DB, but the bot\'s live memory may still hold it until reload'
                : 'Restored in DB, but the bot\'s live memory may not show it until reload';
        const state = typeof data.live_session === 'string' ? data.live_session : null;
        switch (state) {
            case 'patched':
                this.notify(successMsg, { type: 'success' });
                break;
            case 'not_loaded':
            case 'unavailable':
                this.notify(`${successMsg} (DB updated; channel not active in bot)`, { type: 'success' });
                break;
            case 'no_match':
            case 'error':
                this.notify(staleRamMsg, { type: 'warning', duration: 4000 });
                break;
            default:
                // Field missing (older backend) or an unknown state: today's
                // behavior, keyed on the legacy boolean.
                if (data.live_session_patched === false) {
                    this.notify(op === 'edit'
                        ? 'Edited in DB; live session not loaded'
                        : op === 'delete'
                            ? 'Deleted from DB; live session not loaded'
                            : 'Restored in DB; live session not loaded', { type: 'warning', duration: 4000 });
                }
                else {
                    this.notify(successMsg, { type: 'success' });
                }
                break;
        }
    }
    /** User clicked a channel row — request its newest messages. The limit
     *  override lets refresh() re-request the same window the user last
     *  loaded (e.g. 2000 after "Load all") instead of resetting to 200. */
    openChannel(channelId, limit = DEFAULT_LOAD_LIMIT) {
        if (!channelId)
            return;
        this.currentChannelId = channelId;
        this.pendingChannelLoadId = channelId;
        this.lastLoadLimit = limit;
        // Switching channels drops any load queued for the previous one.
        this.pendingChannelLoad = null;
        this.truncated = false;
        this.editingIdx = null;
        this.editInFlight = false;
        // A channel switch invalidates any open find (matches point at the
        // previous transcript's now-detached nodes).
        this.closeFind();
        // Loading state (spinner + skeleton) + re-render the list so the active
        // row highlights.
        this.loading = true;
        this.renderMessages();
        this.renderChannelList();
        this.updateHeader();
        this.renderLoadAll();
        this.renderUndo();
        // Per the callbacks contract: roll back the optimistic loading state
        // when the frame cannot be sent, and queue it for onConnected() —
        // otherwise the pane sits on the spinner forever.
        const sent = this.callbacks.isConnected() && this.callbacks.send({
            type: 'load_ai_history',
            channel_id: channelId,
            limit,
        });
        if (!sent) {
            this.loading = false;
            this.pendingChannelLoad = { channelId, limit };
            const container = document.getElementById('ai-history-messages');
            if (container) {
                container.innerHTML = '<p class="no-data">Not connected — messages will load when the connection is restored.</p>';
            }
        }
    }
    /** "Load all (N)" — re-request the open channel at the server max. */
    loadAll() {
        if (!this.currentChannelId)
            return;
        // A full reload would silently destroy an open editor's typed text
        // (the loaded frame re-renders every row) — make the user decide.
        if (this.editingIdx !== null) {
            this.notify('Finish or cancel the edit first', { type: 'warning' });
            return;
        }
        const channelId = this.currentChannelId;
        this.pendingChannelLoadId = channelId;
        this.lastLoadLimit = FULL_LOAD_LIMIT;
        this.renderUndo(); // the pending-load gate also disables Undo
        const sent = this.callbacks.isConnected() && this.callbacks.send({
            type: 'load_ai_history',
            channel_id: channelId,
            limit: FULL_LOAD_LIMIT,
        });
        if (!sent) {
            // Keep the already-loaded rows on screen; just queue the re-send.
            // The load stays pending (flushed by onConnected), so Undo stays
            // gated — render anyway in case a future rollback changes that.
            this.pendingChannelLoad = { channelId, limit: FULL_LOAD_LIMIT };
            this.renderUndo();
        }
    }
    // ------------------------------------------------------------------
    // Edit flow (copies ChatManager.startEditMessage's interaction pattern,
    // minus the regenerate button — history edits are DB-only).
    // ------------------------------------------------------------------
    startEdit(idx) {
        const msg = this.messages[idx];
        // No editing while a save ack OR a channel load is in flight — the
        // incoming ai_history_loaded re-render would silently discard the
        // editor (and the absolute idx may not survive the reload anyway).
        if (!msg || this.editInFlight || this.pendingChannelLoadId !== null)
            return;
        const container = document.getElementById('ai-history-messages');
        if (!container)
            return;
        // One editor at a time — re-render restores any other open editor.
        if (this.editingIdx !== null && this.editingIdx !== idx) {
            this.renderMessages();
        }
        this.editingIdx = idx;
        const row = container.querySelector(`.history-msg[data-idx="${idx}"]`);
        const contentEl = row?.querySelector('.history-msg-content');
        const actionsEl = row?.querySelector('.history-msg-actions');
        if (!contentEl)
            return;
        const originalContent = msg.content;
        contentEl.innerHTML = `
            <textarea class="edit-textarea">${escapeHtml(originalContent)}</textarea>
            <div class="edit-actions">
                <button class="edit-save-btn">Save</button>
                <button class="edit-cancel-btn">Cancel</button>
            </div>
        `;
        if (actionsEl)
            actionsEl.style.display = 'none';
        const textarea = contentEl.querySelector('.edit-textarea');
        if (textarea) {
            textarea.focus();
            textarea.setSelectionRange(textarea.value.length, textarea.value.length);
            textarea.style.height = Math.min(textarea.scrollHeight, 300) + 'px';
        }
        contentEl.querySelector('.edit-save-btn')?.addEventListener('click', () => {
            this.saveEdit(idx);
        });
        contentEl.querySelector('.edit-cancel-btn')?.addEventListener('click', () => {
            this.cancelEdit();
        });
        textarea?.addEventListener('keydown', (e) => {
            if (e.key === 'Escape')
                this.cancelEdit();
        });
    }
    saveEdit(idx) {
        const msg = this.messages[idx];
        if (!msg || this.editInFlight)
            return;
        const container = document.getElementById('ai-history-messages');
        const row = container?.querySelector(`.history-msg[data-idx="${idx}"]`);
        const textarea = row?.querySelector('.edit-textarea');
        const saveBtn = row?.querySelector('.edit-save-btn');
        if (!textarea)
            return;
        const newContent = textarea.value.trim();
        if (!newContent) {
            this.notify('Content cannot be empty', { type: 'warning' });
            return;
        }
        if (newContent.length > MAX_EDIT_CONTENT_LENGTH) {
            this.notify(`Content too long (max ${MAX_EDIT_CONTENT_LENGTH.toLocaleString()} chars)`, { type: 'error' });
            return;
        }
        if (newContent === msg.content) {
            this.cancelEdit();
            return;
        }
        // Disable Save while the ack is in flight; ChatManager.send already
        // toasts on a dead socket and returns false — keep the editor open
        // (with Save re-enabled) so the user's text isn't lost.
        this.editInFlight = true;
        this.renderUndo(); // the in-flight gate also disables Undo
        if (saveBtn)
            saveBtn.disabled = true;
        // Capture the pre-edit text as the undo candidate — promoted onto
        // the undo stack only when the matching edited ack arrives.
        if (this.currentChannelId !== null) {
            this.pendingUndoCandidate = {
                kind: 'edit',
                channelId: this.currentChannelId,
                id: msg.id,
                prevContent: msg.content,
            };
        }
        const sent = this.callbacks.send({
            type: 'edit_ai_history_message',
            channel_id: this.currentChannelId,
            id: msg.id,
            content: newContent,
        });
        if (!sent) {
            this.editInFlight = false;
            this.pendingUndoCandidate = null;
            if (saveBtn)
                saveBtn.disabled = false;
            this.renderUndo(); // rolled back — Undo is available again
        }
    }
    cancelEdit() {
        this.editingIdx = null;
        this.editInFlight = false;
        const container = document.getElementById('ai-history-messages');
        const savedPos = container?.scrollTop ?? 0;
        this.renderMessages();
        if (container)
            container.scrollTop = savedPos;
        // cancelEdit clears editInFlight and is reachable while a save ack
        // is in flight — re-render so the undo button reflects the gate.
        this.renderUndo();
    }
    // ------------------------------------------------------------------
    // Delete flow (confirm → delete_ai_history_message → ack removes the
    // row). Shares the single-mutation-in-flight flag with the edit flow.
    // ------------------------------------------------------------------
    async requestDelete(idx) {
        const msg = this.messages[idx];
        // Same gate as startEdit: one mutation at a time, and never during a
        // channel load (the incoming re-render would invalidate the idx).
        if (!msg || this.editInFlight || this.pendingChannelLoadId !== null)
            return;
        if (this.editingIdx !== null && this.editingIdx !== idx) {
            // An editor is open on ANOTHER row — deleting now would re-render
            // and silently discard its typed text. Make the user decide
            // (same rule as loadAll).
            this.notify('Finish or cancel the edit first', { type: 'warning' });
            return;
        }
        if (this.editingIdx === idx) {
            // Deleting the row currently being edited: close the editor first
            // so the confirm dialog refers to the row, not a half-typed draft.
            this.cancelEdit();
        }
        const confirmed = await this.confirmDialog('Delete this message?');
        if (!confirmed)
            return;
        // Re-check after the await — a load/mutation may have started (or the
        // channel switched, replacing this.messages) while the dialog was up.
        if (this.editInFlight || this.pendingChannelLoadId !== null)
            return;
        if (this.editingIdx !== null) {
            // An editor was opened while the (non-modal) confirm dialog was
            // up — deleting now would re-render and destroy its draft.
            this.notify('Finish or cancel the edit first', { type: 'warning' });
            return;
        }
        if (this.messages[idx] !== msg)
            return;
        const container = document.getElementById('ai-history-messages');
        const row = container?.querySelector(`.history-msg[data-idx="${idx}"]`);
        const deleteBtn = row?.querySelector('.history-delete-btn');
        // Disable the button while the ack is in flight; ChatManager.send
        // already toasts on a dead socket and returns false — roll back so
        // the delete can be retried.
        this.editInFlight = true;
        this.renderUndo(); // the in-flight gate also disables Undo
        if (deleteBtn)
            deleteBtn.disabled = true;
        // Stash the full message (shallow copy — verbatim field values, incl.
        // snowflakes as strings) as the undo candidate; promoted onto the
        // undo stack only when the matching deleted ack arrives. Undoing it
        // later re-INSERTs the row via restore_ai_history_message.
        if (this.currentChannelId !== null) {
            this.pendingUndoCandidate = {
                kind: 'delete',
                channelId: this.currentChannelId,
                id: msg.id,
                message: { ...msg },
            };
        }
        const sent = this.callbacks.send({
            type: 'delete_ai_history_message',
            channel_id: this.currentChannelId,
            id: msg.id,
        });
        if (!sent) {
            this.editInFlight = false;
            this.pendingUndoCandidate = null;
            if (deleteBtn)
                deleteBtn.disabled = false;
            this.renderUndo(); // rolled back — Undo is available again
        }
    }
    // ------------------------------------------------------------------
    // Undo flow (single-level undo/redo per channel). Entries are pushed
    // ack-confirmed, popped only on the undo's own success ack, and shared
    // with the edit/delete flows through the same editInFlight gate.
    // ------------------------------------------------------------------
    /**
     * Undo button: revert the MOST RECENT ack-confirmed mutation in the open
     * channel.
     *  - 'edit'  → re-send edit_ai_history_message with the pre-edit content
     *    (no new backend op). The edited ack will ALSO ack-push a NEW undo
     *    entry whose prevContent is the just-undone text, which makes a
     *    second Undo behave as redo — that is intended.
     *  - 'delete' → send restore_ai_history_message with the stored message
     *    verbatim; the restored ack re-inserts the row at its id-sorted spot.
     * The entry is popped ONLY on its success ack — an error envelope
     * (onError) or a reconnect (onConnected) keeps it so the user can retry.
     */
    undo() {
        const channelId = this.currentChannelId;
        if (channelId === null)
            return;
        // Same gates as the other mutations: one mutation in flight at a
        // time, and never while a channel load is pending (the incoming
        // re-render would invalidate the view this undo was judged against).
        if (this.editInFlight || this.pendingChannelLoadId !== null)
            return;
        if (this.editingIdx !== null) {
            this.notify('Finish or cancel the edit first', { type: 'warning' });
            return;
        }
        let found;
        for (let i = this.undoStack.length - 1; i >= 0; i--) {
            if (this.undoStack[i].channelId === channelId) {
                found = this.undoStack[i];
                break;
            }
        }
        if (!found)
            return;
        const entry = found;
        this.editInFlight = true;
        this.pendingUndo = { entry };
        this.renderUndo(); // disable the button while the ack is in flight
        let sent;
        if (entry.kind === 'edit') {
            // Capture the text being undone so the edited ack pushes the
            // redo entry (see the doc comment above). Skipped when the row
            // isn't in the loaded window — no current text to capture.
            const target = this.messages.find(m => m.id === entry.id);
            if (target) {
                this.pendingUndoCandidate = {
                    kind: 'edit',
                    channelId,
                    id: entry.id,
                    prevContent: target.content,
                };
            }
            sent = this.callbacks.send({
                type: 'edit_ai_history_message',
                channel_id: channelId,
                id: entry.id,
                content: entry.prevContent,
            });
        }
        else {
            // The stored message goes out VERBATIM — byte-for-byte what
            // ai_history_loaded delivered (snowflakes still strings), so the
            // backend re-inserts the row under its original PK id.
            sent = this.callbacks.send({
                type: 'restore_ai_history_message',
                channel_id: channelId,
                message: entry.message,
            });
        }
        if (!sent) {
            // Dead socket — ChatManager.send already toasted. Clear the
            // in-flight state but KEEP the entry so the undo can be retried.
            this.editInFlight = false;
            this.pendingUndo = null;
            this.pendingUndoCandidate = null;
            this.renderUndo();
        }
    }
    /** Push an ack-confirmed entry, shifting the oldest beyond the cap. */
    pushUndo(entry) {
        this.undoStack.push(entry);
        if (this.undoStack.length > UNDO_STACK_MAX)
            this.undoStack.shift();
        this.renderUndo();
    }
    /**
     * Recover a pendingUndo that a spurious onError() cleared. An unrelated
     * error frame on the shared socket (e.g. a failing chat stream) nulls
     * pendingUndo while the undo's mutation is still genuinely in flight;
     * when the real success ack then arrives, find the in-flight entry on
     * the undo stack by channel+id so the ack still settles it (re-insert +
     * pop) instead of toasting success while changing nothing. Restored acks
     * only ever answer a delete-undo, so a channel+id match is unambiguous;
     * edited acks also answer plain edits, so an 'edit' entry is recovered
     * only when the ack's content IS the entry's pre-edit text — i.e. the
     * ack confirms exactly that undo (any other match would make the entry's
     * own undo a content no-op anyway).
     */
    recoverPendingUndo(ackType, channelId, id, content) {
        if (this.pendingUndo !== null)
            return;
        for (let i = this.undoStack.length - 1; i >= 0; i--) {
            const e = this.undoStack[i];
            if (e.channelId !== channelId)
                continue;
            const matches = ackType === 'restored'
                ? e.kind === 'delete' && e.message.id === id
                : e.kind === 'edit' && e.id === id && e.prevContent === content;
            if (matches) {
                this.pendingUndo = { entry: e };
                return;
            }
        }
    }
    /**
     * Undo bookkeeping shared by the three mutation acks. Runs BEFORE the
     * acks' foreign-channel guards (matching is by channel+id, never by the
     * currently-open view):
     *  1. pop the entry whose undo this ack confirms (edited ack for an
     *     'edit' entry, restored ack for a 'delete' entry) — popping FIRST,
     *     so that at the UNDO_STACK_MAX cap the freed slot is reused by the
     *     redo push below instead of evicting the oldest entry, and
     *  2. promote a matching pendingUndoCandidate onto the undo stack
     *     (edited ack confirms an 'edit' candidate, deleted ack a 'delete'
     *     candidate; restored acks never push).
     */
    settleUndoOnAck(ackType, channelId, id) {
        const pending = this.pendingUndo;
        if (pending) {
            const e = pending.entry;
            const matches = e.channelId === channelId
                && ((ackType === 'edited' && e.kind === 'edit' && e.id === id)
                    || (ackType === 'restored' && e.kind === 'delete' && e.message.id === id));
            if (matches) {
                this.pendingUndo = null;
                const i = this.undoStack.indexOf(e);
                if (i !== -1)
                    this.undoStack.splice(i, 1);
            }
        }
        const cand = this.pendingUndoCandidate;
        if (cand
            && ((ackType === 'edited' && cand.kind === 'edit')
                || (ackType === 'deleted' && cand.kind === 'delete'))
            && cand.channelId === channelId
            && cand.id === id) {
            this.pendingUndoCandidate = null;
            this.pushUndo(cand.kind === 'edit'
                ? { kind: 'edit', channelId: cand.channelId, id: cand.id, prevContent: cand.prevContent }
                : { kind: 'delete', channelId: cand.channelId, message: cand.message });
        }
        this.renderUndo();
    }
    /**
     * Enable the static #ai-history-undo button only when the open channel
     * has at least one undoable entry, no mutation ack is in flight, and no
     * channel load is pending (undo() gates on both — a clickable button
     * that silently does nothing is a dead affordance).
     */
    renderUndo() {
        const btn = document.getElementById('ai-history-undo');
        if (!btn)
            return;
        const hasEntry = this.currentChannelId !== null
            && this.undoStack.some(e => e.channelId === this.currentChannelId);
        btn.disabled = !hasEntry
            || this.editInFlight
            || this.pendingChannelLoadId !== null;
    }
    // ------------------------------------------------------------------
    // Rendering
    // ------------------------------------------------------------------
    renderDisconnected() {
        const container = document.getElementById('ai-channel-list');
        if (container && this.channels.length === 0) {
            container.innerHTML = '<p class="no-data">Not connected — channels will load once the connection is up.</p>';
        }
    }
    renderChannelList() {
        const container = document.getElementById('ai-channel-list');
        if (!container)
            return;
        // a11y: the list is a single-select listbox; rows are options. ATs then
        // announce position-in-set and the active selection, and a roving
        // tabindex makes the whole list one Tab stop with arrow-key traversal.
        container.setAttribute('role', 'listbox');
        container.setAttribute('aria-label', 'AI history channels');
        if (this.channels.length === 0) {
            // Iconographic empty state (shared .empty-state recipe — classes
            // only, no inline style; #i-chat glyph). Heading keeps the literal
            // "No channels" that the smoke test asserts on.
            container.removeAttribute('aria-activedescendant');
            container.innerHTML = `
                <div class="empty-state">
                    ${icon('chat')}
                    <h3>No channels yet</h3>
                    <p>Channels with saved AI history will appear here.</p>
                </div>`;
            return;
        }
        // Apply the debounced channel filter (name match, case-insensitive).
        const filter = this.channelFilter.trim().toLowerCase();
        const matched = filter
            ? this.channels.filter(ch => (ch.name || `Channel ${ch.channel_id}`).toLowerCase().includes(filter))
            : this.channels;
        if (matched.length === 0) {
            // Non-empty source but the filter excluded everything — searchable
            // empty state (keeps the user's filter text visible).
            container.removeAttribute('aria-activedescendant');
            container.innerHTML = `
                <div class="empty-state">
                    ${icon('search')}
                    <h3>No matching channels</h3>
                    <p>No channels match "${escapeHtml(this.channelFilter)}".</p>
                </div>`;
            return;
        }
        const visible = matched.slice(0, CHANNEL_RENDER_CAP);
        const overflow = matched.length - visible.length;
        // The roving-tabindex anchor: the active row if it's visible, else the
        // first row. Exactly one option carries tabindex=0 at a time.
        const activeId = this.currentChannelId;
        const hasActiveVisible = visible.some(ch => ch.channel_id === activeId);
        const focusId = hasActiveVisible ? activeId : visible[0].channel_id;
        container.innerHTML = visible.map(ch => {
            const isActive = activeId === ch.channel_id;
            const isFocusable = ch.channel_id === focusId;
            const optId = `ai-channel-opt-${escapeHtml(ch.channel_id)}`;
            const label = ch.name || `Channel ${ch.channel_id}`;
            return `
                <div class="history-channel-item ${isActive ? 'active' : ''}"
                     id="${optId}"
                     role="option"
                     aria-selected="${isActive ? 'true' : 'false'}"
                     tabindex="${isFocusable ? '0' : '-1'}"
                     data-channel-id="${escapeHtml(ch.channel_id)}">
                    <div class="history-channel-name">${escapeHtml(label)}</div>
                    <div class="history-channel-meta">
                        <span class="history-count-badge">${Number(ch.message_count) || 0}</span>
                        <span class="history-last-active">${escapeHtml(formatLastActive(ch.last_active))}</span>
                    </div>
                </div>
            `;
        }).join('') + (overflow > 0
            ? `<div class="history-overflow-note" role="status">${overflow} more channels hidden — narrow the filter</div>`
            : '');
        // Point aria-activedescendant at the selected option when one is shown.
        if (hasActiveVisible && activeId) {
            container.setAttribute('aria-activedescendant', `ai-channel-opt-${activeId}`);
        }
        else {
            container.removeAttribute('aria-activedescendant');
        }
        // One delegated CLICK handler per container; replace rather than stack
        // (innerHTML wipes descendants but leaves container listeners).
        const slot = container;
        if (slot._histChannelClickHandler) {
            container.removeEventListener('click', slot._histChannelClickHandler);
        }
        const clickHandler = (e) => {
            const target = e.target.closest('.history-channel-item[data-channel-id]');
            if (!target)
                return;
            const id = target.dataset.channelId;
            if (id)
                this.openChannel(id);
        };
        slot._histChannelClickHandler = clickHandler;
        container.addEventListener('click', clickHandler);
        // One delegated KEYDOWN handler: Enter/Space activate the focused row,
        // ↑/↓ (and Home/End) rove focus between options without leaving the list.
        if (slot._histChannelKeyHandler) {
            container.removeEventListener('keydown', slot._histChannelKeyHandler);
        }
        const keyHandler = (e) => {
            const ev = e;
            const row = ev.target.closest('.history-channel-item[data-channel-id]');
            if (!row)
                return;
            if (ev.key === 'Enter' || ev.key === ' ' || ev.key === 'Spacebar') {
                ev.preventDefault();
                const id = row.dataset.channelId;
                if (id)
                    this.openChannel(id);
                return;
            }
            if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp'
                || ev.key === 'Home' || ev.key === 'End') {
                ev.preventDefault();
                this.roveChannelFocus(container, row, ev.key);
            }
        };
        slot._histChannelKeyHandler = keyHandler;
        container.addEventListener('keydown', keyHandler);
    }
    /**
     * Move keyboard focus (and the tabindex=0 roving anchor) between channel
     * options. Selection is NOT changed on arrow — only Enter/Space opens a
     * channel — matching the listbox "selection follows focus only on commit"
     * pattern used elsewhere in the app.
     */
    roveChannelFocus(container, current, key) {
        const rows = Array.from(container.querySelectorAll('.history-channel-item[data-channel-id]'));
        if (rows.length === 0)
            return;
        const i = rows.indexOf(current);
        let next;
        if (key === 'Home')
            next = 0;
        else if (key === 'End')
            next = rows.length - 1;
        else if (key === 'ArrowDown')
            next = i < 0 ? 0 : Math.min(rows.length - 1, i + 1);
        else
            next = i < 0 ? rows.length - 1 : Math.max(0, i - 1);
        const target = rows[next];
        rows.forEach(r => r.setAttribute('tabindex', '-1'));
        target.setAttribute('tabindex', '0');
        target.focus();
    }
    /** The viewer is the start index (into this.messages) of the rendered cap
     *  window — the newest MESSAGE_RENDER_CAP rows are kept. */
    renderStart() {
        return Math.max(0, this.messages.length - MESSAGE_RENDER_CAP);
    }
    /** One message row's markup. Shared by renderMessages() (full build) and
     *  the in-place insert helper so a re-inserted row is byte-identical. */
    messageRowHtml(m, idx) {
        const isUser = m.role === 'user';
        const roleLabel = isUser ? 'User' : 'Model';
        return `
                <div class="history-msg ${isUser ? 'history-msg-user' : 'history-msg-model'}"
                     role="listitem"
                     aria-label="${roleLabel} message"
                     data-idx="${idx}" data-id="${escapeHtml(String(m.id))}">
                    <div class="history-msg-meta">
                        <span class="history-role-badge ${isUser ? 'role-user' : 'role-model'}">${roleLabel}</span>
                        ${m.user_id ? `<span class="history-msg-user-id">${escapeHtml(m.user_id)}</span>` : ''}
                        <span class="history-msg-time">${escapeHtml(formatTimestamp(m.timestamp))}</span>
                        <span class="history-msg-actions">
                            <button class="history-edit-btn" data-idx="${idx}" title="Edit message" aria-label="Edit message">${icon('pencil')} Edit</button>
                            <button class="history-delete-btn" data-idx="${idx}" title="Delete message" aria-label="Delete message">${icon('trash')} Delete</button>
                        </span>
                    </div>
                    <div class="history-msg-content">${escapeHtml(m.content)}</div>
                </div>
            `;
    }
    renderMessages() {
        const container = document.getElementById('ai-history-messages');
        if (!container)
            return;
        // a11y: the viewer is a live log of list items; ATs announce new rows
        // and can navigate it as a list. (Set every render so a fresh test DOM
        // / hot reload still gets the roles.)
        container.setAttribute('role', 'log');
        container.setAttribute('aria-live', 'polite');
        container.setAttribute('aria-relevant', 'additions');
        if (this.currentChannelId === null) {
            // Iconographic "pick a channel" empty state.
            container.innerHTML = `
                <div class="empty-state">
                    ${icon('history')}
                    <h3>No channel selected</h3>
                    <p>Pick a channel on the left to view its AI chat history.</p>
                </div>`;
            return;
        }
        if (this.loading) {
            // Spinner + skeleton rows while the load is in flight.
            container.innerHTML = `
                <div class="history-loading" role="status" aria-live="polite">
                    <div class="loading-spinner" aria-hidden="true"></div>
                    <p class="no-data">Loading messages…</p>
                </div>
                <div class="history-msg is-loading skeleton-row" aria-hidden="true"></div>
                <div class="history-msg is-loading skeleton-row" aria-hidden="true"></div>
                <div class="history-msg is-loading skeleton-row" aria-hidden="true"></div>`;
            return;
        }
        if (this.messages.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    ${icon('inbox')}
                    <h3>No messages</h3>
                    <p>No messages in this channel yet.</p>
                </div>`;
            return;
        }
        // Cap the render at the newest rows; messages arrive ascending by id
        // so the slice keeps the most recent ones. The cap note is a status
        // region so ATs announce that older rows are hidden.
        const start = this.renderStart();
        const note = start > 0
            ? `<div class="history-overflow-note" role="status">Showing the newest ${MESSAGE_RENDER_CAP} of ${this.messages.length} loaded messages</div>`
            : '';
        container.innerHTML = note + this.messages.slice(start)
            .map((m, i) => this.messageRowHtml(m, start + i))
            .join('');
        this.bindMessageHandlers(container);
    }
    /** (Re)bind the delegated edit/delete click handler — replace-not-stack. */
    bindMessageHandlers(container) {
        const slot = container;
        if (slot._histMsgClickHandler) {
            container.removeEventListener('click', slot._histMsgClickHandler);
        }
        const handler = (e) => {
            const target = e.target;
            const editBtn = target.closest('.history-edit-btn');
            if (editBtn) {
                const idx = Number(editBtn.dataset.idx);
                if (Number.isInteger(idx))
                    this.startEdit(idx);
                return;
            }
            const deleteBtn = target.closest('.history-delete-btn');
            if (deleteBtn) {
                const idx = Number(deleteBtn.dataset.idx);
                if (Number.isInteger(idx))
                    void this.requestDelete(idx);
            }
        };
        slot._histMsgClickHandler = handler;
        container.addEventListener('click', handler);
    }
    // ------------------------------------------------------------------
    // In-place row mutation — patch/remove/insert ONE row node instead of
    // rebuilding the whole (up-to-500-row) list per ack. Each returns false
    // when it can't safely do the surgical update (the row isn't in the
    // rendered cap window, or the mutation crosses the cap boundary so the
    // overflow note / visible set changes), signalling the caller to fall
    // back to a full renderMessages().
    // ------------------------------------------------------------------
    /** Patch a single edited row's content text in place. Replaces the inline
     *  editor (if this row was the one being edited) with the plain content and
     *  restores the action buttons that startEdit() hid. */
    patchRowContent(container, id, content) {
        const row = container.querySelector(`.history-msg[data-id="${id}"]`);
        if (!row)
            return false;
        const contentEl = row.querySelector('.history-msg-content');
        if (!contentEl)
            return false;
        // textContent drops any open <textarea>/edit-actions and writes the new
        // text inert (no escaping needed).
        contentEl.textContent = content;
        // startEdit() hid the actions with inline display:none — clear it so the
        // edit/delete buttons return (the CSS hover/focus-within rule resumes).
        const actionsEl = row.querySelector('.history-msg-actions');
        if (actionsEl)
            actionsEl.style.removeProperty('display');
        return true;
    }
    /**
     * Remove a single deleted row in place and re-index the rows AFTER it
     * (their absolute data-idx shifts down by one). Falls back (returns false)
     * when removing it would change which rows are visible under the cap, i.e.
     * a previously-hidden older row must now appear.
     */
    removeRowInPlace(container, id) {
        const row = container.querySelector(`.history-msg[data-id="${id}"]`);
        if (!row)
            return false;
        // Bail to a full render when the removal would change the rendered
        // shell rather than just one row:
        //  - over the cap: removing a visible row pulls a previously-hidden
        //    older row into view (and the overflow note's denominator shifts);
        //  - last row: the empty-state pane must replace the (now empty) list.
        // (Pre-removal length is compared to the cap.)
        if (this.messages.length > MESSAGE_RENDER_CAP)
            return false;
        if (this.messages.length <= 1)
            return false;
        const removedIdx = Number(row.dataset.idx);
        row.remove();
        if (Number.isInteger(removedIdx))
            this.reindexFrom(container, removedIdx, -1);
        return true;
    }
    /**
     * Insert a restored row at its id-sorted DOM position and re-index the
     * rows AFTER it (+1). Falls back when the insert point falls outside the
     * rendered cap window (the row would belong to the hidden older head).
     */
    insertRowInPlace(container, msg, insertAt) {
        const start = this.renderStart(); // start uses the post-splice length
        // Over the cap, inserting a row slides the window — the oldest visible
        // row drops out and the "newest N of M" note appears/changes — so a
        // full render is simpler and correct. Also bail when the row lands in
        // the hidden (older) head, outside the rendered window.
        if (this.messages.length > MESSAGE_RENDER_CAP)
            return false;
        if (insertAt < start)
            return false;
        // First row back into a previously-empty channel: the container is
        // showing the empty-state pane (no message rows), so a full render must
        // replace it rather than appending a lone row beside the placeholder.
        if (this.messages.length <= 1)
            return false;
        // Shift the tail's data-idx up by one BEFORE inserting the new node.
        this.reindexFrom(container, insertAt, +1);
        const tmp = document.createElement('div');
        tmp.innerHTML = this.messageRowHtml(msg, insertAt);
        const newRow = tmp.firstElementChild;
        if (!newRow)
            return false;
        // Find the existing row currently at the insert position (now bearing
        // data-idx === insertAt+1 after the shift) to anchor the insert before.
        const anchor = container.querySelector(`.history-msg[data-idx="${insertAt + 1}"]`);
        if (anchor) {
            container.insertBefore(newRow, anchor);
        }
        else {
            container.appendChild(newRow);
        }
        return true;
    }
    /** Shift every rendered row's absolute data-idx (on the row AND its action
     *  buttons) by `delta`, for rows whose current idx is >= `fromIdx`. */
    reindexFrom(container, fromIdx, delta) {
        container.querySelectorAll('.history-msg[data-idx]').forEach(row => {
            const cur = Number(row.dataset.idx);
            if (!Number.isInteger(cur) || cur < fromIdx)
                return;
            const next = String(cur + delta);
            row.dataset.idx = next;
            row.querySelectorAll('[data-idx]').forEach(btn => {
                btn.dataset.idx = next;
            });
        });
    }
    updateHeader() {
        const header = document.getElementById('ai-history-header');
        if (!header)
            return;
        if (this.currentChannelId === null) {
            header.innerHTML = '<h2>Select a channel</h2>';
            return;
        }
        const ch = this.channels.find(c => c.channel_id === this.currentChannelId);
        const name = ch?.name || `Channel ${this.currentChannelId}`;
        const meta = this.messages.length > 0
            ? `${this.messages.length} of ${this.totalCount} messages`
            : '';
        header.innerHTML = `
            <h2>${escapeHtml(name)}</h2>
            <span class="history-header-meta">${escapeHtml(meta)}</span>
        `;
    }
    renderLoadAll() {
        const wrap = document.getElementById('ai-history-load-all-container');
        const btn = document.getElementById('ai-history-load-all');
        if (!wrap || !btn)
            return;
        // A further request can only help while we hold fewer rows than the
        // server cap AND the server didn't clip the last payload by content
        // budget — otherwise the button is a dead-end loop refetching the
        // identical window (the header already shows "N of M messages").
        const canLoadMore = this.hasMore
            && this.messages.length < FULL_LOAD_LIMIT
            && !this.truncated;
        wrap.classList.toggle('hidden', !canLoadMore);
        if (canLoadMore) {
            // Channels above the server cap can never be fetched in full —
            // promise only what the contract can deliver.
            btn.textContent = this.totalCount > FULL_LOAD_LIMIT
                ? `Load newest ${FULL_LOAD_LIMIT} of ${this.totalCount}`
                : `Load all (${this.totalCount})`;
        }
    }
}
/** Escape a string so it can be embedded literally in a RegExp. */
function escapeRegExp(s) {
    return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}
/**
 * Find all text nodes within `root` that contain `query` (case-insensitive),
 * wrap each hit in <mark class="chat-search-hit">, and return the marks. A
 * trimmed-down sibling of chat/search.ts's wrapMatches (same TreeWalker +
 * matchAll-against-original-text approach so offsets survive toLowerCase length
 * changes), kept local because that helper isn't exported. Caps both the
 * candidate text-node count and the total <mark>s so a short query against a
 * giant transcript can't lock the main thread.
 */
function wrapHistoryMatches(root, query) {
    if (!query)
        return [];
    const MAX_HITS = 1000;
    const hits = [];
    const needle = query.toLowerCase();
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
        acceptNode: (node) => {
            const parent = node.parentElement;
            if (!parent)
                return NodeFilter.FILTER_REJECT;
            const tag = parent.tagName;
            if (tag === 'SCRIPT' || tag === 'STYLE' || tag === 'MARK')
                return NodeFilter.FILTER_REJECT;
            // Skip the inline editor's textarea + the meta/badge chrome so a
            // find only highlights actual message content the user reads.
            if (!node.nodeValue || !node.nodeValue.toLowerCase().includes(needle))
                return NodeFilter.FILTER_SKIP;
            return NodeFilter.FILTER_ACCEPT;
        },
    });
    const candidates = [];
    let n = walker.nextNode();
    while (n) {
        candidates.push(n);
        if (candidates.length >= MAX_HITS)
            break;
        n = walker.nextNode();
    }
    outer: for (const textNode of candidates) {
        const text = textNode.nodeValue || '';
        const re = new RegExp(escapeRegExp(query), 'gi');
        let idx = 0;
        let foundAny = false;
        const fragment = document.createDocumentFragment();
        for (const m of text.matchAll(re)) {
            const start = m.index;
            const matched = m[0];
            if (matched.length === 0)
                continue;
            foundAny = true;
            if (start > idx) {
                fragment.appendChild(document.createTextNode(text.slice(idx, start)));
            }
            const mark = document.createElement('mark');
            mark.className = 'chat-search-hit';
            mark.textContent = matched; // preserves original case
            fragment.appendChild(mark);
            hits.push(mark);
            idx = start + matched.length;
            if (hits.length >= MAX_HITS) {
                if (idx < text.length) {
                    fragment.appendChild(document.createTextNode(text.slice(idx)));
                }
                textNode.replaceWith(fragment);
                break outer;
            }
        }
        if (!foundAny)
            continue;
        if (idx < text.length) {
            fragment.appendChild(document.createTextNode(text.slice(idx)));
        }
        textNode.replaceWith(fragment);
    }
    return hits;
}
//# sourceMappingURL=history-manager.js.map