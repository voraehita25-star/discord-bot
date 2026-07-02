/**
 * Conversation modals — rename + delete-confirm.
 *
 * Both follow the same shape: user clicks a trigger (rename or delete in the
 * chat header), we open a modal, the user confirms/cancels, and on confirm we
 * emit a WebSocket frame. Bundling them keeps the "open/confirm/close" state
 * machine in one place and out of ChatManager.
 *
 * The `new conversation` modal is NOT in here — it shares state with
 * selectedRole + thinkingEnabled + aiProvider which are still ChatManager
 * concerns (they feed into sendMessage payloads too). Extracting that one
 * cleanly requires a small state-bus first.
 *
 * Each modal is guarded against running while streaming so the user can't
 * mutate a conversation mid-response.
 */

import type { ChatConversation } from './types.js';

type SendWs = (payload: { type: string; [k: string]: unknown }) => void;

export interface ConversationModalsCallbacks {
    sendWsMessage: SendWs;
    /** True while an AI response is streaming — modals are blocked in that state. */
    isStreaming: () => boolean;
    /** Find a conversation by id, for pre-filling the rename input. */
    findConversation: (id: string) => ChatConversation | undefined;
}

export class ConversationModals {
    private pendingDeleteId: string | null = null;
    private pendingRenameId: string | null = null;
    private escapeHandler: ((e: KeyboardEvent) => void) | null = null;
    // Element focused before a modal opened, restored on close (WCAG 2.4.3) —
    // otherwise keyboard/AT users are stranded wherever the modal left them.
    private previousFocus: HTMLElement | null = null;

    constructor(private readonly cb: ConversationModalsCallbacks) {}

    /** Install an Escape-to-close handler on document, scoped to whichever modal
     * is open. We attach lazily on show and detach on close so the listener
     * doesn't run on every keystroke when no modal is visible. */
    private attachEscape(close: () => void): void {
        this.detachEscape();
        this.escapeHandler = (e: KeyboardEvent) => {
            if (e.key === 'Escape') close();
        };
        document.addEventListener('keydown', this.escapeHandler);
    }

    private detachEscape(): void {
        if (this.escapeHandler) {
            document.removeEventListener('keydown', this.escapeHandler);
            this.escapeHandler = null;
        }
    }

    // ---------- Delete ----------

    /** Called by the trash-can button in the chat header. */
    showDelete(id: string): void {
        if (this.cb.isStreaming()) return;
        this.pendingDeleteId = id;
        this.previousFocus = document.activeElement as HTMLElement | null;
        const modal = document.getElementById('delete-confirm-modal');
        modal?.classList.add('active');
        // Move focus into the dialog (WCAG 2.4.3): it's aria-modal, so leaving
        // focus on the now-inert trash-can trigger behind it strands keyboard/AT
        // users. Focus Cancel (not Delete) so a reflexive Enter dismisses rather
        // than performs the irreversible delete — mirrors showRename's focus move.
        (document.getElementById('delete-cancel') as HTMLElement | null)?.focus();
        this.attachEscape(() => this.closeDelete());
    }

    /** User clicked "Delete" in the confirm modal. Emits WS frame + hides modal. */
    confirmDelete(): void {
        if (this.pendingDeleteId) {
            this.cb.sendWsMessage({ type: 'delete_conversation', id: this.pendingDeleteId });
            this.pendingDeleteId = null;
        }
        this.closeDelete();
    }

    /** User clicked cancel / clicked outside the confirm modal. */
    closeDelete(): void {
        document.getElementById('delete-confirm-modal')?.classList.remove('active');
        this.pendingDeleteId = null;
        this.detachEscape();
        this.restoreFocus();
    }

    /** Return focus to whatever had it before the modal opened (if it's still
     * in the document — the conversation row may have been deleted/re-rendered). */
    private restoreFocus(): void {
        if (this.previousFocus && document.body.contains(this.previousFocus)) {
            this.previousFocus.focus();
        }
        this.previousFocus = null;
    }

    // ---------- Rename ----------

    /** Called by the pencil button in the chat header. */
    showRename(id: string): void {
        if (this.cb.isStreaming()) return;
        const conv = this.cb.findConversation(id);
        this.pendingRenameId = id;

        const modal = document.getElementById('rename-modal');
        const input = document.getElementById('rename-input') as HTMLInputElement | null;
        if (modal && input) {
            this.previousFocus = document.activeElement as HTMLElement | null;
            input.value = conv?.title || '';
            modal.classList.add('active');
            input.focus();
            input.select();
            this.attachEscape(() => this.closeRename());
        }
    }

    /** User hit Enter or clicked Save. */
    confirmRename(): void {
        const input = document.getElementById('rename-input') as HTMLInputElement | null;
        const newTitle = input?.value?.trim();

        if (this.pendingRenameId && newTitle) {
            this.cb.sendWsMessage({
                type: 'rename_conversation',
                id: this.pendingRenameId,
                title: newTitle,
            });
            this.pendingRenameId = null;
        }
        this.closeRename();
    }

    /** User cancelled. */
    closeRename(): void {
        document.getElementById('rename-modal')?.classList.remove('active');
        this.pendingRenameId = null;
        this.detachEscape();
        this.restoreFocus();
    }
}
