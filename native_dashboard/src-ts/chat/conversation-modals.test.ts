/**
 * Tests for chat/conversation-modals.ts — rename + delete-confirm state machines.
 *
 * Both modals share the same invariants:
 *   - show() is a no-op while streaming (prevents mutation mid-response)
 *   - confirm() emits the right WS frame + closes the modal
 *   - close() clears the pending id so a stale confirm() doesn't re-fire
 *   - show() toggles the `.active` class on the modal element
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { ConversationModals, type ConversationModalsCallbacks } from './conversation-modals.js';
import type { ChatConversation } from './types.js';

const MODALS_HTML = `
    <div id="delete-confirm-modal" class="modal"></div>
    <div id="rename-modal" class="modal">
        <input id="rename-input" type="text">
    </div>
`;

function mountDom(): void {
    document.body.innerHTML = MODALS_HTML;
}

function mkConv(id: string, overrides: Partial<ChatConversation> = {}): ChatConversation {
    return {
        id,
        title: `Conv ${id}`,
        role_preset: 'general',
        thinking_enabled: false,
        is_starred: false,
        created_at: '2026-04-01T00:00:00Z',
        ...overrides,
    };
}

function mkModals(overrides: Partial<ConversationModalsCallbacks> = {}): {
    modals: ConversationModals;
    cb: {
        sendWsMessage: ReturnType<typeof vi.fn>;
        isStreaming: ReturnType<typeof vi.fn>;
        findConversation: ReturnType<typeof vi.fn>;
    };
} {
    const cb = {
        sendWsMessage: vi.fn(),
        isStreaming: vi.fn(() => false),
        findConversation: vi.fn((id: string) => mkConv(id, { title: 'original title' })),
        ...overrides,
    };
    return { modals: new ConversationModals(cb as ConversationModalsCallbacks), cb };
}

beforeEach(() => {
    mountDom();
});

// ============================================================================
// Delete modal
// ============================================================================

describe('ConversationModals.showDelete', () => {
    it('opens the delete-confirm modal', () => {
        const { modals } = mkModals();
        modals.showDelete('c1');
        expect(document.getElementById('delete-confirm-modal')!.classList.contains('active')).toBe(true);
    });

    it('is a no-op while streaming (guards against mid-response mutation)', () => {
        const { modals } = mkModals({ isStreaming: () => true });
        modals.showDelete('c1');
        expect(document.getElementById('delete-confirm-modal')!.classList.contains('active')).toBe(false);
    });

    it('does not throw when modal node is missing (hot-reload safety)', () => {
        document.body.innerHTML = '';
        const { modals } = mkModals();
        expect(() => modals.showDelete('c1')).not.toThrow();
    });
});

describe('ConversationModals.confirmDelete', () => {
    it('emits delete_conversation WS frame and closes the modal', () => {
        const { modals, cb } = mkModals();
        modals.showDelete('c1');
        modals.confirmDelete();

        expect(cb.sendWsMessage).toHaveBeenCalledExactlyOnceWith({
            type: 'delete_conversation',
            id: 'c1',
        });
        expect(document.getElementById('delete-confirm-modal')!.classList.contains('active')).toBe(false);
    });

    it('does nothing if show() was never called (no stale pending id)', () => {
        const { modals, cb } = mkModals();
        modals.confirmDelete();
        expect(cb.sendWsMessage).not.toHaveBeenCalled();
    });

    it('subsequent confirmDelete() with no re-open does not re-send', () => {
        const { modals, cb } = mkModals();
        modals.showDelete('c1');
        modals.confirmDelete();
        modals.confirmDelete();
        modals.confirmDelete();
        // Only one send — pending id is cleared after the first confirm.
        expect(cb.sendWsMessage).toHaveBeenCalledOnce();
    });
});

describe('ConversationModals.closeDelete', () => {
    it('hides the modal and clears the pending id', () => {
        const { modals, cb } = mkModals();
        modals.showDelete('c1');
        modals.closeDelete();
        modals.confirmDelete();

        expect(document.getElementById('delete-confirm-modal')!.classList.contains('active')).toBe(false);
        // No send because pending id was cleared.
        expect(cb.sendWsMessage).not.toHaveBeenCalled();
    });
});

// ============================================================================
// Rename modal
// ============================================================================

describe('ConversationModals.showRename', () => {
    it('opens the rename modal and pre-fills the input with current title', () => {
        const findSpy = vi.fn(() => mkConv('c1', { title: 'Old Title' }));
        const { modals } = mkModals({ findConversation: findSpy });
        modals.showRename('c1');

        expect(document.getElementById('rename-modal')!.classList.contains('active')).toBe(true);
        const input = document.getElementById('rename-input') as HTMLInputElement;
        expect(input.value).toBe('Old Title');
        expect(findSpy).toHaveBeenCalledWith('c1');
    });

    it('pre-fills with empty string when conversation is not found', () => {
        const { modals } = mkModals({ findConversation: () => undefined });
        modals.showRename('missing');

        const input = document.getElementById('rename-input') as HTMLInputElement;
        expect(input.value).toBe('');
    });

    it('focuses + selects the input so the user can retype', () => {
        const { modals } = mkModals();
        modals.showRename('c1');
        const input = document.getElementById('rename-input') as HTMLInputElement;
        expect(document.activeElement).toBe(input);
    });

    it('is a no-op while streaming', () => {
        const { modals } = mkModals({ isStreaming: () => true });
        modals.showRename('c1');
        expect(document.getElementById('rename-modal')!.classList.contains('active')).toBe(false);
    });
});

describe('ConversationModals.confirmRename', () => {
    it('emits rename_conversation with the trimmed input value', () => {
        const { modals, cb } = mkModals();
        modals.showRename('c1');
        const input = document.getElementById('rename-input') as HTMLInputElement;
        input.value = '  New Title  ';
        modals.confirmRename();

        expect(cb.sendWsMessage).toHaveBeenCalledExactlyOnceWith({
            type: 'rename_conversation',
            id: 'c1',
            title: 'New Title',
        });
    });

    it('skips the send when the input is empty (still closes the modal)', () => {
        const { modals, cb } = mkModals();
        modals.showRename('c1');
        const input = document.getElementById('rename-input') as HTMLInputElement;
        input.value = '';
        modals.confirmRename();

        expect(cb.sendWsMessage).not.toHaveBeenCalled();
        expect(document.getElementById('rename-modal')!.classList.contains('active')).toBe(false);
    });

    it('skips the send when the input is whitespace-only', () => {
        const { modals, cb } = mkModals();
        modals.showRename('c1');
        const input = document.getElementById('rename-input') as HTMLInputElement;
        input.value = '     ';
        modals.confirmRename();
        expect(cb.sendWsMessage).not.toHaveBeenCalled();
    });

    it('does nothing when showRename() was never called', () => {
        const { modals, cb } = mkModals();
        const input = document.getElementById('rename-input') as HTMLInputElement;
        input.value = 'stray input';
        modals.confirmRename();
        expect(cb.sendWsMessage).not.toHaveBeenCalled();
    });
});

describe('ConversationModals.closeRename', () => {
    it('hides the modal and clears the pending id', () => {
        const { modals, cb } = mkModals();
        modals.showRename('c1');
        modals.closeRename();

        const input = document.getElementById('rename-input') as HTMLInputElement;
        input.value = 'Should be ignored';
        modals.confirmRename();

        expect(cb.sendWsMessage).not.toHaveBeenCalled();
        expect(document.getElementById('rename-modal')!.classList.contains('active')).toBe(false);
    });
});
