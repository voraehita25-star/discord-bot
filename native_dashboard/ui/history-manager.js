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
import { escapeHtml, showConfirmDialog, showToast } from './shared.js';
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
        const hasTzInfo = /Z$|[+-]\d{2}:?\d{2}$/.test(iso);
        const normalized = (hasTzInfo ? iso : iso + 'Z').replace(' ', 'T');
        const d = new Date(normalized);
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
        const hasTzInfo = /Z$|[+-]\d{2}:?\d{2}$/.test(iso);
        const normalized = (hasTzInfo ? iso : iso + 'Z').replace(' ', 'T');
        const d = new Date(normalized);
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
    constructor(callbacks) {
        this.callbacks = callbacks;
        this.channels = [];
        this.currentChannelId = null;
        this.messages = [];
        this.totalCount = 0;
        this.hasMore = false;
        /**
         * True when the server clipped the last ai_history_loaded payload by its
         * content-size budget — a re-request cannot return more rows, so the
         * Load-all button must not promise otherwise.
         */
        this.truncated = false;
        /** Absolute index (into this.messages) of the row in edit mode, or null. */
        this.editingIdx = null;
        // Most-recent channel id passed to openChannel()/loadAll(). The
        // ai_history_loaded handler compares against this to drop stale frames
        // when the user switches channels rapidly (copies ChatManager's
        // pendingConversationLoadId pattern).
        this.pendingChannelLoadId = null;
        // Set when a list_ai_channels send failed (socket down) so the request
        // can be flushed once ChatManager's 'connected' frame arrives.
        this.pendingChannelsList = false;
        // Channel load (openChannel/loadAll) that could not be sent because the
        // socket was down — flushed by onConnected(), cleared when the matching
        // ai_history_loaded arrives and when the user switches channels.
        this.pendingChannelLoad = null;
        /**
         * True while an edit_ai_history_message OR delete_ai_history_message is
         * awaiting the server ack — one mutation in flight at a time, so edit and
         * delete can never overlap (the name predates the delete op).
         */
        this.editInFlight = false;
        // Limit of the most recent channel load (200 default / 2000 after
        // "Load all") so a Refresh re-requests the same window instead of
        // collapsing a fully-loaded view back to the newest 200.
        this.lastLoadLimit = DEFAULT_LOAD_LIMIT;
        // Set by refresh() so the next ai_channels_list arrival confirms with a
        // "Refreshed" toast — page-enter/reconnect listings stay silent.
        this.refreshFeedbackPending = false;
        /**
         * Ack-confirmed undo history (newest last), capped at UNDO_STACK_MAX.
         * Entries are pushed ONLY when the matching edited/deleted ack arrives —
         * a rejected or unsendable mutation never lands here.
         */
        this.undoStack = [];
        /**
         * Mutation sent but not yet ack-confirmed — promoted onto undoStack by
         * the matching edited/deleted ack. Keyed by channel+id (NOT by the
         * current view): the acks clear editInFlight before the foreign-channel
         * guard, and the DB mutation happened regardless of which channel is
         * open when the ack lands, so foreign-channel acks must still push.
         */
        this.pendingUndoCandidate = null;
        /**
         * The stack entry whose undo is currently awaiting its success ack
         * (edited ack for an 'edit' entry, restored ack for a 'delete' entry).
         * Popped on that ack; a codeless/transient onError or a reconnect
         * (onConnected) clears this marker but KEEPS the entry so the user can
         * retry the undo, while an onError carrying a PERMANENT rejection code
         * (PERMANENT_HISTORY_ERROR_CODES) drops the entry too — retrying could
         * only fail identically and would shadow older undos in the channel.
         */
        this.pendingUndo = null;
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
                this.messages = Array.isArray(data.messages)
                    ? data.messages
                    : [];
                this.totalCount = Number(data.total_count) || this.messages.length;
                this.hasMore = data.has_more === true;
                // Optional flag: the server clipped the payload by content
                // budget — re-requesting cannot return more rows.
                this.truncated = data.truncated === true;
                this.editingIdx = null;
                this.editInFlight = false;
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
                // Preserve scroll position so the user stays where they are
                // (same approach as ChatManager's message_edited case).
                const container = document.getElementById('ai-history-messages');
                const savedPos = container?.scrollTop ?? 0;
                this.renderMessages();
                if (container)
                    container.scrollTop = savedPos;
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
                const container = document.getElementById('ai-history-messages');
                const savedPos = container?.scrollTop ?? 0;
                this.renderMessages();
                if (container)
                    container.scrollTop = savedPos;
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
                if (restoredMsg && !this.messages.some(m => m.id === restoredMsg.id)) {
                    let insertAt = this.messages.findIndex(m => m.id > restoredMsg.id);
                    if (insertAt === -1)
                        insertAt = this.messages.length;
                    this.messages.splice(insertAt, 0, restoredMsg);
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
                const savedPos = container?.scrollTop ?? 0;
                this.renderMessages();
                if (container)
                    container.scrollTop = savedPos;
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
        // Loading state + re-render the list so the active row highlights.
        const container = document.getElementById('ai-history-messages');
        if (container) {
            container.innerHTML = '<p class="no-data">Loading messages…</p>';
        }
        this.renderChannelList();
        this.updateHeader();
        this.renderLoadAll();
        this.renderUndo();
        // Per the callbacks contract: roll back the optimistic loading state
        // when the frame cannot be sent, and queue it for onConnected() —
        // otherwise the pane sits on "Loading messages…" forever.
        const sent = this.callbacks.isConnected() && this.callbacks.send({
            type: 'load_ai_history',
            channel_id: channelId,
            limit,
        });
        if (!sent) {
            this.pendingChannelLoad = { channelId, limit };
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
        if (this.channels.length === 0) {
            container.innerHTML = '<p class="no-data">No channels with AI history yet.</p>';
            return;
        }
        const visible = this.channels.slice(0, CHANNEL_RENDER_CAP);
        const overflow = this.channels.length - visible.length;
        container.innerHTML = visible.map(ch => {
            const isActive = this.currentChannelId === ch.channel_id;
            return `
                <div class="history-channel-item ${isActive ? 'active' : ''}"
                     data-channel-id="${escapeHtml(ch.channel_id)}">
                    <div class="history-channel-name">${escapeHtml(ch.name || `Channel ${ch.channel_id}`)}</div>
                    <div class="history-channel-meta">
                        <span class="history-count-badge">${Number(ch.message_count) || 0}</span>
                        <span class="history-last-active">${escapeHtml(formatLastActive(ch.last_active))}</span>
                    </div>
                </div>
            `;
        }).join('') + (overflow > 0
            ? `<div class="history-overflow-note">${overflow} more channels hidden</div>`
            : '');
        // One delegated handler per container; replace rather than stack
        // (innerHTML wipes descendants but leaves container listeners).
        const slot = container;
        if (slot._histChannelClickHandler) {
            container.removeEventListener('click', slot._histChannelClickHandler);
        }
        const handler = (e) => {
            const target = e.target.closest('.history-channel-item[data-channel-id]');
            if (!target)
                return;
            const id = target.dataset.channelId;
            if (id)
                this.openChannel(id);
        };
        slot._histChannelClickHandler = handler;
        container.addEventListener('click', handler);
    }
    renderMessages() {
        const container = document.getElementById('ai-history-messages');
        if (!container)
            return;
        if (this.currentChannelId === null) {
            container.innerHTML = '<p class="no-data">Pick a channel on the left to view its AI chat history.</p>';
            return;
        }
        if (this.messages.length === 0) {
            container.innerHTML = '<p class="no-data">No messages in this channel.</p>';
            return;
        }
        // Cap the render at the newest rows; messages arrive ascending by id
        // so the slice keeps the most recent ones.
        const start = Math.max(0, this.messages.length - MESSAGE_RENDER_CAP);
        const note = start > 0
            ? `<div class="history-overflow-note">Showing the newest ${MESSAGE_RENDER_CAP} of ${this.messages.length} loaded messages</div>`
            : '';
        container.innerHTML = note + this.messages.slice(start).map((m, i) => {
            const idx = start + i;
            const isUser = m.role === 'user';
            return `
                <div class="history-msg ${isUser ? 'history-msg-user' : 'history-msg-model'}" data-idx="${idx}">
                    <div class="history-msg-meta">
                        <span class="history-role-badge ${isUser ? 'role-user' : 'role-model'}">${isUser ? 'User' : 'Model'}</span>
                        ${m.user_id ? `<span class="history-msg-user-id">${escapeHtml(m.user_id)}</span>` : ''}
                        <span class="history-msg-time">${escapeHtml(formatTimestamp(m.timestamp))}</span>
                        <span class="history-msg-actions">
                            <button class="history-edit-btn" data-idx="${idx}" title="Edit message" aria-label="Edit message">✏️ Edit</button>
                            <button class="history-delete-btn" data-idx="${idx}" title="Delete message" aria-label="Delete message">🗑️ Delete</button>
                        </span>
                    </div>
                    <div class="history-msg-content">${escapeHtml(m.content)}</div>
                </div>
            `;
        }).join('');
        // Delegated edit/delete-button handler — same replace-not-stack pattern.
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
//# sourceMappingURL=history-manager.js.map