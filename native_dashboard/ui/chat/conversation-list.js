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
import { escapeHtml, safeAvatarUrl, settings } from '../shared.js';
/** Conversations beyond this count are not rendered until the user narrows the filter. */
const RENDER_CAP = 200;
export class ConversationList {
    constructor(callbacks) {
        this.callbacks = callbacks;
        this.filter = '';
        this.filterDebounce = null;
    }
    /** Paint the conversation list sidebar. Idempotent — safe to call as often as you like. */
    render(ctx) {
        const container = document.getElementById('conversation-list');
        if (!container)
            return;
        // Wire the filter input once per DOM lifetime. Safe across innerHTML
        // replacements of `#conversation-list` because the input lives in a
        // sibling node above it (see index.html).
        this.setupFilterInput();
        if (ctx.conversations.length === 0) {
            container.innerHTML = `
                <div class="no-conversations">
                    <p>No conversations yet</p>
                    <p>Start a new chat!</p>
                </div>
            `;
            return;
        }
        const filter = this.filter.trim().toLowerCase();
        const matches = filter
            ? ctx.conversations.filter(c => (c.title || '').toLowerCase().includes(filter))
            : ctx.conversations;
        if (matches.length === 0) {
            container.innerHTML = `
                <div class="no-conversations">
                    <p>No matches for "${escapeHtml(this.filter)}"</p>
                </div>
            `;
            return;
        }
        const visible = matches.slice(0, RENDER_CAP);
        const overflow = matches.length - visible.length;
        const safeAi = safeAvatarUrl(settings.aiAvatar);
        container.innerHTML = visible.map(conv => {
            const preset = ctx.presets[conv.role_preset] || {};
            const isActive = ctx.currentConversation?.id === conv.id;
            const starClass = conv.is_starred ? 'starred' : '';
            const avatarHtml = safeAi
                ? `<img class="conv-avatar" src="${safeAi}" alt="AI">`
                : `<span class="conv-emoji">${escapeHtml(preset.emoji || '💬')}</span>`;
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
        }).join('') + (overflow > 0
            ? `<div class="conversation-overflow-note">${overflow} more hidden — narrow your filter</div>`
            : '');
        // Re-bind click delegation. One handler per container; we replace it
        // rather than stack because innerHTML wipes descendants but leaves
        // listeners on the container itself.
        const slot = container;
        if (slot._convClickHandler) {
            container.removeEventListener('click', slot._convClickHandler);
        }
        const handler = (e) => {
            const target = e.target.closest('.conversation-item[data-id]');
            if (!target)
                return;
            const id = target.dataset.id;
            if (id)
                this.callbacks.onLoadConversation(id);
        };
        slot._convClickHandler = handler;
        container.addEventListener('click', handler);
    }
    /** Render the tag chips + "add tag" input strip under the chat header. */
    renderTags(conversation) {
        const host = document.getElementById('chat-tags');
        if (!host || !conversation)
            return;
        const tags = conversation.tags ?? [];
        const chips = tags.map(t => `<span class="tag-chip" data-tag="${escapeHtml(t)}">#${escapeHtml(t)}<button class="tag-remove" data-tag="${escapeHtml(t)}" aria-label="Remove tag ${escapeHtml(t)}">&times;</button></span>`).join('');
        host.innerHTML = chips +
            `<input type="text" class="tag-add-input" id="chat-tag-add" placeholder="+ tag" aria-label="Add tag" maxlength="64">`;
        // Remove buttons.
        host.querySelectorAll('.tag-remove').forEach(btn => {
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
        const input = document.getElementById('chat-tag-add');
        if (input) {
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
                }
                else if (e.key === 'Escape') {
                    input.value = '';
                    input.blur();
                }
            });
        }
    }
    setupFilterInput() {
        const input = document.getElementById('conversation-filter-input');
        if (!input || input.dataset.filterBound)
            return;
        input.addEventListener('input', () => {
            // Debounce — filtering 1000+ conversations on every keystroke is
            // an O(n) innerHTML replacement that drops frames during typing.
            if (this.filterDebounce !== null)
                clearTimeout(this.filterDebounce);
            this.filterDebounce = window.setTimeout(() => {
                this.filter = input.value;
                this.filterDebounce = null;
                this.callbacks.onFilterChanged();
            }, 120);
        });
        input.dataset.filterBound = '1';
    }
}
//# sourceMappingURL=conversation-list.js.map