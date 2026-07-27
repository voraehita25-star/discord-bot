/**
 * Regression tests: Escape + focus handoff for the two chat-page dialogs.
 *
 * #new-chat-modal and #chat-files-modal used to open with a bare
 * `classList.add('active')` — no Escape binding, no focus move, no focus
 * restore. Both the Settings "Keyboard Shortcuts" card and #shortcuts-modal
 * advertise "Esc — Close modal / cancel", so these two were the dialogs
 * contradicting the app's own published reference, and a keyboard user who
 * opened either was left with focus on <body> BEHIND the overlay.
 *
 * Nothing caught it: app.ts's Escape branch only ever handled #shortcuts-modal,
 * ConversationModals covers rename/delete, export-picker covers its own, and no
 * e2e case pressed Escape on these two.
 *
 * Note these modals live INSIDE `.app` (both nested in <section id="page-chat">),
 * so they deliberately do NOT use app.ts's openModal/closeModal — that helper
 * inerts `.app`, which would inert the dialog with it. They follow the
 * ConversationModals shape instead, which is what these tests pin.
 */

import { describe, it, expect, beforeAll, beforeEach, vi } from 'vitest';

vi.mock('@tauri-apps/api/core', () => ({ invoke: vi.fn().mockResolvedValue('') }));

beforeAll(async () => {
    const DOMPurify = (await import('dompurify')).default;
    (window as unknown as { DOMPurify: unknown }).DOMPurify = DOMPurify(window);
    if (!Element.prototype.scrollIntoView) {
        Element.prototype.scrollIntoView = function () { /* no-op */ };
    }
    if (!Element.prototype.scrollTo) {
        Element.prototype.scrollTo = function () { /* no-op */ } as unknown as typeof Element.prototype.scrollTo;
    }
});

// Mirrors the shape of the two dialogs in ui/index.html, down to the trigger
// buttons — focus restoration is only meaningful if there is a real opener.
const DOM = `
    <div id="toast-container"></div>
    <button id="btn-new-chat">New</button>
    <button id="btn-chat-files">Files</button>
    <textarea id="chat-input"></textarea>
    <div class="modal" id="new-chat-modal">
        <div class="modal-overlay"></div>
        <div class="modal-content">
            <button class="modal-close" id="modal-close">x</button>
            <div class="role-cards">
                <div class="role-card selected" data-role="general" tabindex="0"></div>
                <div class="role-card" data-role="faust" tabindex="-1"></div>
            </div>
            <select id="modal-ai-provider"><option value="gemini">Gemini</option></select>
            <input type="checkbox" id="modal-thinking">
            <button id="modal-cancel">Cancel</button>
            <button id="modal-create">Start Chat</button>
        </div>
    </div>
    <div class="modal" id="chat-files-modal">
        <div class="modal-content chat-files-modal-content">
            <div class="chat-files-view" id="chat-files-list-view">
                <button class="modal-close" id="chat-files-close">x</button>
                <p id="chat-files-subtitle"></p>
                <div id="chat-files-list"></div>
                <div id="chat-files-empty" class="hidden"></div>
            </div>
            <div class="chat-files-view hidden" id="chat-files-edit-view">
                <input type="text" id="chat-files-edit-name">
                <span id="chat-files-edit-counter"></span>
                <textarea id="chat-files-edit-text"></textarea>
            </div>
        </div>
    </div>
    <span id="chat-files-badge" class="hidden"></span>
`;

let ChatManager: typeof import('./chat-manager.js').ChatManager;

beforeAll(async () => {
    ChatManager = (await import('./chat-manager.js')).ChatManager;
});

type AnyConv = import('./chat-manager.js').ChatManager['currentConversation'];

function mkCm() {
    document.body.innerHTML = DOM;
    const cm = new ChatManager();
    cm.wsClient.send = vi.fn();
    cm.currentConversation = { id: 'conv-1' } as unknown as NonNullable<AnyConv>;
    return cm;
}

function pressEscape(): void {
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
}

const isActive = (id: string): boolean =>
    document.getElementById(id)!.classList.contains('active');

beforeEach(() => {
    document.body.innerHTML = DOM;
});

describe('New Conversation modal — dismissal', () => {
    it('Escape closes it', () => {
        const cm = mkCm();
        cm.showNewChatModal();
        expect(isActive('new-chat-modal')).toBe(true);
        pressEscape();
        expect(isActive('new-chat-modal')).toBe(false);
    });

    it('moves focus onto the checked role card instead of leaving it on body', () => {
        const cm = mkCm();
        document.getElementById('btn-new-chat')!.focus();
        cm.showNewChatModal();
        expect(document.activeElement).toBe(
            document.querySelector('.role-card.selected'),
        );
    });

    it('restores focus to the trigger on close', () => {
        const cm = mkCm();
        const trigger = document.getElementById('btn-new-chat')!;
        trigger.focus();
        cm.showNewChatModal();
        pressEscape();
        expect(document.activeElement).toBe(trigger);
    });

    it('does not keep listening after it is closed', () => {
        // A handler left bound would fire Escape-close logic (and steal focus
        // back to the trigger) on every later keystroke anywhere in the app.
        const cm = mkCm();
        const trigger = document.getElementById('btn-new-chat')!;
        trigger.focus();
        cm.showNewChatModal();
        cm.closeModal();
        const other = document.getElementById('chat-input')!;
        other.focus();
        pressEscape();
        expect(document.activeElement).toBe(other);
    });
});

describe('Attached Files modal — dismissal', () => {
    it('Escape closes it from the list view', () => {
        const cm = mkCm();
        cm.openChatFilesModal();
        expect(isActive('chat-files-modal')).toBe(true);
        pressEscape();
        expect(isActive('chat-files-modal')).toBe(false);
    });

    it('moves focus into the dialog and restores it on close', () => {
        const cm = mkCm();
        const trigger = document.getElementById('btn-chat-files')!;
        trigger.focus();
        cm.openChatFilesModal();
        expect(document.activeElement).toBe(document.getElementById('chat-files-close'));
        pressEscape();
        expect(document.activeElement).toBe(trigger);
    });

    it('Escape in the editor unwinds to the list, not straight out of the dialog', () => {
        // Layered dismissal: the Back / Cancel buttons already discard editor
        // changes without prompting, so Escape matching them costs nothing and
        // keeps the user from losing their place in the file list.
        const cm = mkCm();
        cm.openChatFilesModal();
        cm.openChatFileEditor(7);
        expect(document.getElementById('chat-files-edit-view')!.classList.contains('hidden')).toBe(false);

        pressEscape();
        expect(document.getElementById('chat-files-edit-view')!.classList.contains('hidden')).toBe(true);
        expect(isActive('chat-files-modal')).toBe(true);

        // A second Escape now closes the dialog itself.
        pressEscape();
        expect(isActive('chat-files-modal')).toBe(false);
    });

    it('leaving the editor never drops focus to body behind the open dialog', () => {
        // Back, Cancel and Escape all hide the element holding focus — the
        // textarea, or the button just clicked. Focus has to land somewhere
        // inside the dialog that is still visible.
        const cm = mkCm();
        cm.openChatFilesModal();
        cm.openChatFileEditor(7);
        document.getElementById('chat-files-edit-text')!.focus();

        cm.closeChatFileEditor();
        expect(document.activeElement).not.toBe(document.body);
        expect(
            document.getElementById('chat-files-list-view')!.contains(document.activeElement),
        ).toBe(true);
    });

    it('leaves focus alone when the editor was not the thing holding it', () => {
        const cm = mkCm();
        cm.openChatFilesModal();
        cm.openChatFileEditor(7);
        const elsewhere = document.getElementById('chat-files-close')!;
        elsewhere.focus();
        cm.closeChatFileEditor();
        expect(document.activeElement).toBe(elsewhere);
    });
});
