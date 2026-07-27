/**
 * Conversation-sidebar renderer (#22 / #15).
 *
 * Owns everything that happens inside #conversation-list + #conversation-filter-input
 * + #chat-tags (the per-conversation tag chip row). Extracted from ChatManager
 * because the HTML generation, 200-item render cap, filter debounce, and event
 * delegation together make up ~150 tightly-related lines that don't touch the
 * WS / messages / streaming state.
 *
 * The renderer talks to the outside world through a narrow callback bag:
 *   - `onLoadConversation(id)`    — user clicked a conversation in the list
 *   - `sendWsMessage(payload)`    — emit an add_tag/remove_tag WS frame
 *
 * State it owns:
 *   - `filter` text typed into the filter input
 *   - debounce timer for filter keystrokes
 *
 * State it READS from the caller each render:
 *   - `conversations[]`, `currentConversation`, `presets` — passed into render()
 *
 * That read model is a snapshot so we don't couple to the caller's object identity.
 */

import { countLabel, escapeHtml, icon, safeAvatarUrl, settings } from '../shared.js';
import type { ChatConversation, RolePreset } from './types.js';

/** Conversations beyond this count are not rendered until the user narrows the filter. */
const RENDER_CAP = 200;

export interface ConversationListCallbacks {
    /** User clicked a conversation row. */
    onLoadConversation: (id: string) => void;
    /** Emit a WebSocket frame (used by tag add/remove). */
    sendWsMessage: (payload: { type: string; [k: string]: unknown }) => void;
    /** Filter text changed (debounced). The caller should re-render with fresh ctx. */
    onFilterChanged: () => void;
}

export interface ConversationListContext {
    conversations: ChatConversation[];
    currentConversation: ChatConversation | null;
    presets: Record<string, RolePreset>;
}

export class ConversationList {
    private filter: string = '';
    private filterDebounce: number | null = null;

    constructor(private readonly callbacks: ConversationListCallbacks) {}

    /** Paint the conversation list sidebar. Idempotent — safe to call as often as you like. */
    render(ctx: ConversationListContext): void {
        const container = document.getElementById('conversation-list');
        if (!container) return;

        // Wire the filter input once per DOM lifetime. Safe across innerHTML
        // replacements of `#conversation-list` because the input lives in a
        // sibling node above it (see index.html).
        this.setupFilterInput();

        // a11y: the rail is a single-select listbox and the rows are its
        // options — the same contract #ai-channel-list already publishes in
        // history-manager.ts. index.html declares role="group" for the pre-boot
        // static markup; once we own the children we can be specific, so ATs
        // announce position-in-set and which conversation is open.
        //
        // The role is set PER BRANCH, not once up front. The two empty states
        // below fill the container with a <div class="no-conversations"> and
        // nothing else, and a listbox whose children are not options is an
        // aria-required-children violation — worse, AT announces "listbox, 0
        // items" and the user filtering to zero matches never hears the
        // message explaining why. role="group" still supports an accessible
        // name, so the label stays outside the switch and every state keeps it.
        container.setAttribute('aria-label', 'Conversations');

        // A rebuild below destroys whichever option node holds focus — capture
        // first, restore after. render() is not only called on user action: a
        // WS frame (a new message bumping a row's count, a title update, a star
        // ack) re-renders the whole rail, so a keyboard user parked on a row
        // would silently lose focus to <body> mid-conversation. The container
        // itself is EXCLUDED because it carries tabindex=0 as a focusable
        // scroll region: someone who tabbed in only to scroll must not be
        // dragged onto an option. Mirrors renderChannelList() in
        // history-manager.ts, which gained the same guard.
        const hadFocus = document.activeElement !== container
            && container.contains(document.activeElement);

        if (ctx.conversations.length === 0) {
            container.setAttribute('role', 'group');
            container.removeAttribute('aria-activedescendant');
            container.innerHTML = `
                <div class="no-conversations">
                    <p>No conversations yet</p>
                    <p>Start a new chat!</p>
                </div>
            `;
            this.detachRowHandlers(container);
            // No options left to land on; keep focus in the rail rather than
            // dropping it to <body> (the container is the focusable region).
            if (hadFocus) container.focus();
            return;
        }

        const filter = this.filter.trim().toLowerCase();
        const matches = filter
            ? ctx.conversations.filter(c => (c.title || '').toLowerCase().includes(filter))
            : ctx.conversations;

        if (matches.length === 0) {
            container.setAttribute('role', 'group');
            container.removeAttribute('aria-activedescendant');
            container.innerHTML = `
                <div class="no-conversations">
                    <p>No matches for "${escapeHtml(this.filter)}"</p>
                </div>
            `;
            this.detachRowHandlers(container);
            if (hadFocus) container.focus();
            return;
        }

        const visible = matches.slice(0, RENDER_CAP);
        const overflow = matches.length - visible.length;
        const safeAi = safeAvatarUrl(settings.aiAvatar);
        // The roving-tabindex anchor: the open conversation if it survived the
        // filter, else the first row. Exactly one option is tabbable at a time,
        // so the rail costs the keyboard user ONE Tab stop, not one per chat.
        const activeId = ctx.currentConversation?.id ?? null;
        const hasActiveVisible = visible.some(c => c.id === activeId);
        const focusId = hasActiveVisible ? activeId : visible[0].id;

        // Only now are the children genuinely options.
        container.setAttribute('role', 'listbox');

        container.innerHTML = visible.map(conv => {
            const preset = ctx.presets[conv.role_preset] || ({} as RolePreset);
            const isActive = ctx.currentConversation?.id === conv.id;
            const starClass = conv.is_starred ? 'starred' : '';
            const avatarHtml = safeAi
                ? `<img class="conv-avatar" src="${safeAi}" alt="AI">`
                : `<span class="conv-emoji">${preset.emoji ? escapeHtml(preset.emoji) : icon('chat')}</span>`;

            return `
                <div class="conversation-item ${isActive ? 'active' : ''} ${starClass}"
                     id="conversation-opt-${escapeHtml(conv.id)}"
                     role="option"
                     aria-selected="${isActive ? 'true' : 'false'}"
                     tabindex="${conv.id === focusId ? '0' : '-1'}"
                     data-id="${escapeHtml(conv.id)}">
                    ${avatarHtml}
                    <div class="conv-info">
                        <span class="conv-title">${escapeHtml(conv.title || 'New Chat')}</span>
                        <span class="conv-meta">${countLabel(Number(conv.message_count) || 0, 'message')}</span>
                    </div>
                    ${conv.is_starred ? `<span class="conv-star">${icon('star')}</span>` : ''}
                </div>
            `;
        }).join('') + (overflow > 0
            ? `<div class="conversation-overflow-note" role="status">${overflow} more hidden — narrow your filter</div>`
            : '');

        // Point aria-activedescendant at the open conversation when it is shown.
        if (hasActiveVisible && activeId) {
            container.setAttribute('aria-activedescendant', `conversation-opt-${activeId}`);
        } else {
            container.removeAttribute('aria-activedescendant');
        }

        // Restore the focus the innerHTML swap destroyed. The roving anchor has
        // already been placed on the open conversation (or the first row), so
        // focus simply follows it.
        if (hadFocus) {
            (container.querySelector('.conversation-item[tabindex="0"]') as HTMLElement | null)
                ?.focus();
        }

        // Re-bind click delegation. One handler per container; we replace it
        // rather than stack because innerHTML wipes descendants but leaves
        // listeners on the container itself.
        const slot = container as unknown as Record<string, EventListener | undefined>;
        if (slot._convClickHandler) {
            container.removeEventListener('click', slot._convClickHandler);
        }
        const handler: EventListener = (e) => {
            const target = (e.target as HTMLElement).closest('.conversation-item[data-id]') as HTMLElement | null;
            if (!target) return;
            const id = target.dataset.id;
            if (id) this.callbacks.onLoadConversation(id);
        };
        slot._convClickHandler = handler;
        container.addEventListener('click', handler);

        // One delegated KEYDOWN handler: Enter/Space open the focused row, ↑/↓
        // (and Home/End) rove focus within the rail. Without this the rows were
        // click-ONLY — plain <div>s carrying nothing but data-id — so a
        // keyboard-only user could reach the filter box and the scroll
        // container but could never actually open a conversation. The identical
        // rail on the History page has been operable this whole time; this is
        // that same contract, and roveConversationFocus mirrors
        // HistoryManager.roveChannelFocus deliberately.
        if (slot._convKeyHandler) {
            container.removeEventListener('keydown', slot._convKeyHandler);
        }
        const keyHandler: EventListener = (e) => {
            const ev = e as KeyboardEvent;
            const row = (ev.target as HTMLElement).closest('.conversation-item[data-id]') as HTMLElement | null;
            if (!row) return;
            if (ev.key === 'Enter' || ev.key === ' ' || ev.key === 'Spacebar') {
                ev.preventDefault();
                const id = row.dataset.id;
                if (id) this.callbacks.onLoadConversation(id);
                return;
            }
            if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp'
                || ev.key === 'Home' || ev.key === 'End') {
                ev.preventDefault();
                this.roveConversationFocus(container, row, ev.key);
            }
        };
        slot._convKeyHandler = keyHandler;
        container.addEventListener('keydown', keyHandler);
    }

    /**
     * Move keyboard focus (and the tabindex=0 roving anchor) between rows.
     * Arrowing does NOT open a conversation — only Enter/Space commits — so a
     * keyboard user can survey the rail without firing a load for every row
     * they pass over. Same "selection follows focus only on commit" rule the
     * History channel rail uses.
     */
    private roveConversationFocus(container: HTMLElement, current: HTMLElement, key: string): void {
        const rows = Array.from(
            container.querySelectorAll<HTMLElement>('.conversation-item[data-id]'),
        );
        if (rows.length === 0) return;
        const i = rows.indexOf(current);
        let next: number;
        if (key === 'Home') next = 0;
        else if (key === 'End') next = rows.length - 1;
        else if (key === 'ArrowDown') next = i < 0 ? 0 : Math.min(rows.length - 1, i + 1);
        else next = i < 0 ? rows.length - 1 : Math.max(0, i - 1);
        const target = rows[next];
        rows.forEach(r => r.setAttribute('tabindex', '-1'));
        target.setAttribute('tabindex', '0');
        target.focus();
    }

    /** Drop the delegated row handlers bound by render() (used by the empty/no-match early returns). */
    private detachRowHandlers(container: HTMLElement): void {
        const slot = container as unknown as Record<string, EventListener | undefined>;
        if (slot._convClickHandler) {
            container.removeEventListener('click', slot._convClickHandler);
            slot._convClickHandler = undefined;
        }
        if (slot._convKeyHandler) {
            container.removeEventListener('keydown', slot._convKeyHandler);
            slot._convKeyHandler = undefined;
        }
    }

    /** Render the tag chips + "add tag" input strip under the chat header. */
    renderTags(conversation: ChatConversation | null): void {
        const host = document.getElementById('chat-tags');
        if (!host || !conversation) return;

        // Preserve any in-progress "add tag" entry across re-renders: the
        // innerHTML swap below destroys the old #chat-tag-add element, which
        // would otherwise drop a partially typed tag (and keyboard focus) if a
        // re-render fires while the user is mid-typing.
        const prevInput = document.getElementById('chat-tag-add') as HTMLInputElement | null;
        const prevValue = prevInput?.value ?? '';
        const prevHadFocus = prevInput !== null && document.activeElement === prevInput;
        const prevSelStart = prevInput?.selectionStart ?? null;
        const prevSelEnd = prevInput?.selectionEnd ?? null;

        const tags = conversation.tags ?? [];
        const chips = tags.map(t =>
            `<span class="tag-chip" data-tag="${escapeHtml(t)}">#${escapeHtml(t)}<button class="tag-remove" data-tag="${escapeHtml(t)}" aria-label="Remove tag ${escapeHtml(t)}">&times;</button></span>`,
        ).join('');
        host.innerHTML = chips +
            `<input type="text" class="tag-add-input" id="chat-tag-add" placeholder="+ tag" aria-label="Add tag" maxlength="64">`;

        // Remove buttons.
        host.querySelectorAll<HTMLElement>('.tag-remove').forEach(btn => {
            btn.addEventListener('click', () => {
                const tag = btn.dataset.tag;
                if (tag) {
                    this.callbacks.sendWsMessage({
                        type: 'remove_tag',
                        conversation_id: conversation.id,
                        tag,
                    });
                }
            });
        });

        // Add input — Enter commits, Esc cancels.
        const input = document.getElementById('chat-tag-add') as HTMLInputElement | null;
        if (input) {
            // Restore the partially typed tag (and focus/caret) that the
            // innerHTML swap above destroyed, so a re-render mid-typing is
            // non-destructive.
            if (prevValue) input.value = prevValue;
            if (prevHadFocus) {
                input.focus();
                if (prevSelStart !== null && prevSelEnd !== null) {
                    input.setSelectionRange(prevSelStart, prevSelEnd);
                }
            }
            input.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    const tag = input.value.trim().toLowerCase();
                    if (tag) {
                        this.callbacks.sendWsMessage({
                            type: 'add_tag',
                            conversation_id: conversation.id,
                            tag,
                        });
                        input.value = '';
                    }
                } else if (e.key === 'Escape') {
                    input.value = '';
                    input.blur();
                }
            });
        }
    }

    private setupFilterInput(): void {
        const input = document.getElementById('conversation-filter-input') as HTMLInputElement | null;
        if (!input || input.dataset.filterBound) return;
        input.addEventListener('input', () => {
            // Debounce — filtering 1000+ conversations on every keystroke is
            // an O(n) innerHTML replacement that drops frames during typing.
            if (this.filterDebounce !== null) clearTimeout(this.filterDebounce);
            this.filterDebounce = window.setTimeout(() => {
                this.filter = input.value;
                this.filterDebounce = null;
                this.callbacks.onFilterChanged();
            }, 120);
        });
        input.dataset.filterBound = '1';
    }

}
