/**
 * Tests for chat/conversation-list.ts — sidebar render + filter + tag chips.
 *
 * Exercises:
 *   - Empty / non-empty / filtered / no-matches render states
 *   - 200-item render cap + overflow note
 *   - Click delegation routes to onLoadConversation
 *   - Filter input is debounced (~120ms) and then triggers onFilterChanged
 *   - Tag chip remove button sends a remove_tag WS frame
 *   - Add-tag input commits on Enter, clears on Escape
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { ConversationList, type ConversationListCallbacks } from './conversation-list.js';
import type { ChatConversation, RolePreset } from './types.js';

const SIDEBAR_HTML = `
    <input id="conversation-filter-input" type="text">
    <div id="conversation-list"></div>
    <div id="chat-tags"></div>
`;

function mountDom(): void {
    document.body.innerHTML = SIDEBAR_HTML;
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

function mkCallbacks(): ConversationListCallbacks & {
    onLoadConversation: ReturnType<typeof vi.fn>;
    sendWsMessage: ReturnType<typeof vi.fn>;
    onFilterChanged: ReturnType<typeof vi.fn>;
} {
    return {
        onLoadConversation: vi.fn(),
        sendWsMessage: vi.fn(),
        onFilterChanged: vi.fn(),
    };
}

beforeEach(() => {
    mountDom();
    vi.useRealTimers();
});

describe('ConversationList.render — empty state', () => {
    it('shows "No conversations yet" when list is empty', () => {
        const cb = mkCallbacks();
        const list = new ConversationList(cb);
        list.render({ conversations: [], currentConversation: null, presets: {} });

        const container = document.getElementById('conversation-list')!;
        expect(container.textContent).toContain('No conversations yet');
    });
});

describe('ConversationList.render — normal state', () => {
    it('renders one .conversation-item per conversation', () => {
        const cb = mkCallbacks();
        const list = new ConversationList(cb);
        const convs = [mkConv('a'), mkConv('b'), mkConv('c')];
        list.render({ conversations: convs, currentConversation: null, presets: {} });

        const items = document.querySelectorAll('.conversation-item');
        expect(items.length).toBe(3);
    });

    it('marks the current conversation with .active', () => {
        const cb = mkCallbacks();
        const list = new ConversationList(cb);
        const convs = [mkConv('a'), mkConv('b')];
        list.render({ conversations: convs, currentConversation: convs[1], presets: {} });

        const active = document.querySelectorAll('.conversation-item.active');
        expect(active.length).toBe(1);
        expect((active[0] as HTMLElement).dataset.id).toBe('b');
    });

    it('marks starred conversations with .starred and a star glyph', () => {
        const cb = mkCallbacks();
        const list = new ConversationList(cb);
        const convs = [mkConv('a', { is_starred: true }), mkConv('b')];
        list.render({ conversations: convs, currentConversation: null, presets: {} });

        const starred = document.querySelectorAll('.conversation-item.starred');
        expect(starred.length).toBe(1);
        expect(document.querySelector('.conv-star')).not.toBeNull();
    });

    it('uses the role preset emoji when AI avatar is not set', async () => {
        // settings.aiAvatar defaults to DEFAULT_AI_AVATAR (base64 image) —
        // emoji fallback only fires when the user has explicitly cleared it.
        const { settings } = await import('../shared.js');
        const originalAvatar = settings.aiAvatar;
        settings.aiAvatar = '';
        try {
            const cb = mkCallbacks();
            const list = new ConversationList(cb);
            const presets: Record<string, RolePreset> = {
                faust: { name: 'Faust', emoji: '👻', color: '#ffb1b4' },
            };
            const convs = [mkConv('a', { role_preset: 'faust' })];
            list.render({ conversations: convs, currentConversation: null, presets });

            const emoji = document.querySelector('.conv-emoji');
            expect(emoji?.textContent).toBe('👻');
        } finally {
            settings.aiAvatar = originalAvatar;
        }
    });

    it('escapes conversation titles to prevent XSS', () => {
        const cb = mkCallbacks();
        const list = new ConversationList(cb);
        const convs = [mkConv('x', { title: '<script>alert(1)</script>' })];
        list.render({ conversations: convs, currentConversation: null, presets: {} });

        const container = document.getElementById('conversation-list')!;
        expect(container.innerHTML).not.toMatch(/<script>alert\(1\)<\/script>/);
        expect(container.textContent).toContain('<script>alert(1)</script>');  // literal text, not markup
    });
});

describe('ConversationList.render — filter + overflow', () => {
    it('shows "No matches" when filter excludes everything', async () => {
        const cb = mkCallbacks();
        const list = new ConversationList(cb);
        const convs = [mkConv('a', { title: 'apple' }), mkConv('b', { title: 'banana' })];
        list.render({ conversations: convs, currentConversation: null, presets: {} });

        const input = document.getElementById('conversation-filter-input') as HTMLInputElement;
        input.value = 'zzz';
        input.dispatchEvent(new Event('input'));

        // Wait past debounce (120ms).
        await new Promise(r => setTimeout(r, 200));
        expect(cb.onFilterChanged).toHaveBeenCalledOnce();

        // Caller re-renders with the fresh filter — simulate that.
        list.render({ conversations: convs, currentConversation: null, presets: {} });
        const container = document.getElementById('conversation-list')!;
        expect(container.textContent).toContain('No matches for "zzz"');
    });

    it('caps rendered items at 200 and shows an overflow note', () => {
        const cb = mkCallbacks();
        const list = new ConversationList(cb);
        const convs = Array.from({ length: 300 }, (_, i) => mkConv(`c${i}`));
        list.render({ conversations: convs, currentConversation: null, presets: {} });

        const items = document.querySelectorAll('.conversation-item');
        expect(items.length).toBe(200);
        const overflow = document.querySelector('.conversation-overflow-note');
        expect(overflow).not.toBeNull();
        expect(overflow!.textContent).toContain('100 more hidden');
    });

    it('case-insensitive filter matches substring', async () => {
        const cb = mkCallbacks();
        const list = new ConversationList(cb);
        const convs = [
            mkConv('a', { title: 'Apple Pie' }),
            mkConv('b', { title: 'banana split' }),
            mkConv('c', { title: 'cherry' }),
        ];
        list.render({ conversations: convs, currentConversation: null, presets: {} });

        const input = document.getElementById('conversation-filter-input') as HTMLInputElement;
        input.value = 'APP';
        input.dispatchEvent(new Event('input'));
        await new Promise(r => setTimeout(r, 200));

        list.render({ conversations: convs, currentConversation: null, presets: {} });
        const items = document.querySelectorAll('.conversation-item');
        expect(items.length).toBe(1);
        expect((items[0] as HTMLElement).dataset.id).toBe('a');
    });
});

describe('ConversationList — click delegation', () => {
    it('click on a row invokes onLoadConversation with its id', () => {
        const cb = mkCallbacks();
        const list = new ConversationList(cb);
        const convs = [mkConv('a'), mkConv('b')];
        list.render({ conversations: convs, currentConversation: null, presets: {} });

        const bItem = document.querySelector('.conversation-item[data-id="b"]') as HTMLElement;
        bItem.click();

        expect(cb.onLoadConversation).toHaveBeenCalledExactlyOnceWith('b');
    });

    it('clicking a child node still routes to the row id', () => {
        const cb = mkCallbacks();
        const list = new ConversationList(cb);
        const convs = [mkConv('target')];
        list.render({ conversations: convs, currentConversation: null, presets: {} });

        const titleNode = document.querySelector('.conv-title') as HTMLElement;
        titleNode.click();
        expect(cb.onLoadConversation).toHaveBeenCalledExactlyOnceWith('target');
    });

    it('does not stack duplicate handlers across re-renders', () => {
        const cb = mkCallbacks();
        const list = new ConversationList(cb);
        const convs = [mkConv('a')];
        list.render({ conversations: convs, currentConversation: null, presets: {} });
        list.render({ conversations: convs, currentConversation: null, presets: {} });
        list.render({ conversations: convs, currentConversation: null, presets: {} });

        (document.querySelector('.conversation-item') as HTMLElement).click();
        // Should fire exactly once despite 3 renders.
        expect(cb.onLoadConversation).toHaveBeenCalledOnce();
    });
});

describe('ConversationList.renderTags', () => {
    it('renders one tag chip per tag + an input for adding', () => {
        const cb = mkCallbacks();
        const list = new ConversationList(cb);
        const conv = mkConv('x', { tags: ['important', 'work'] });
        list.renderTags(conv);

        const chips = document.querySelectorAll('.tag-chip');
        expect(chips.length).toBe(2);
        expect(document.getElementById('chat-tag-add')).not.toBeNull();
    });

    it('clicking remove sends a remove_tag WS frame', () => {
        const cb = mkCallbacks();
        const list = new ConversationList(cb);
        const conv = mkConv('c1', { tags: ['todelete', 'keep'] });
        list.renderTags(conv);

        const btn = document.querySelector('.tag-remove[data-tag="todelete"]') as HTMLButtonElement;
        btn.click();

        expect(cb.sendWsMessage).toHaveBeenCalledExactlyOnceWith({
            type: 'remove_tag',
            conversation_id: 'c1',
            tag: 'todelete',
        });
    });

    it('Enter in the add-tag input sends an add_tag frame (lowercased + trimmed)', () => {
        const cb = mkCallbacks();
        const list = new ConversationList(cb);
        list.renderTags(mkConv('c1'));

        const input = document.getElementById('chat-tag-add') as HTMLInputElement;
        input.value = '  FooBar  ';
        input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));

        expect(cb.sendWsMessage).toHaveBeenCalledExactlyOnceWith({
            type: 'add_tag',
            conversation_id: 'c1',
            tag: 'foobar',
        });
        expect(input.value).toBe('');
    });

    it('Escape clears the add-tag input without sending', () => {
        const cb = mkCallbacks();
        const list = new ConversationList(cb);
        list.renderTags(mkConv('c1'));

        const input = document.getElementById('chat-tag-add') as HTMLInputElement;
        input.value = 'wip';
        input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));

        expect(cb.sendWsMessage).not.toHaveBeenCalled();
        expect(input.value).toBe('');
    });

    it('does nothing when conversation is null (avoids stale-ref bugs)', () => {
        const cb = mkCallbacks();
        const list = new ConversationList(cb);
        expect(() => list.renderTags(null)).not.toThrow();
        expect(document.querySelectorAll('.tag-chip').length).toBe(0);
    });
});

describe('ConversationList.setupFilterInput', () => {
    it('fires onFilterChanged exactly once after a burst of keystrokes', async () => {
        const cb = mkCallbacks();
        const list = new ConversationList(cb);
        list.render({ conversations: [mkConv('a')], currentConversation: null, presets: {} });

        const input = document.getElementById('conversation-filter-input') as HTMLInputElement;
        input.value = 'a';
        input.dispatchEvent(new Event('input'));
        input.value = 'ap';
        input.dispatchEvent(new Event('input'));
        input.value = 'app';
        input.dispatchEvent(new Event('input'));

        // Before debounce fires — should still be zero.
        expect(cb.onFilterChanged).not.toHaveBeenCalled();

        await new Promise(r => setTimeout(r, 200));
        expect(cb.onFilterChanged).toHaveBeenCalledOnce();
    });
});
