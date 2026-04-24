/**
 * Pure HTML string builder for the chat message list (#7).
 *
 * Takes a snapshot of the state needed to render + a small helpers bag
 * (formatMessage, stripThinkTags, formatTime are still methods on
 * ChatManager because they have their own internal caches/state). Returns
 * the HTML string that callers assign to `chat-messages.innerHTML`. Event
 * delegation (click handlers for copy/pin/edit/delete/like/etc.) stays in
 * ChatManager because those bindings call other ChatManager methods.
 *
 * Keeping this split lets the >100-line template string be edited without
 * touching the orchestrator, and makes the virtualization math (window start
 * index, show-earlier button) a testable pure function.
 */

import { escapeHtml, safeAvatarUrl, settings } from '../shared.js';
import type { ChatConversation, ChatMessage } from './types.js';

export const VIRT_THRESHOLD = 150;
export const VIRT_WINDOW_SIZE = 100;

export interface MessageTemplateDeps {
    /** Convert an ISO-ish timestamp to the "2h ago" / "Mar 12" string. */
    formatTime: (dateStr: string) => string;
    /** Markdown + LaTeX + fenced-code → sanitized HTML. */
    formatMessage: (content: string) => string;
    /** Strip `<think>…</think>` blocks. */
    stripThinkTags: (content: string) => string;
}

export interface RenderContext {
    messages: ChatMessage[];
    currentConversation: ChatConversation | null;
    /** The tail-window size requested by the caller. Clamped to [VIRT_WINDOW_SIZE, messages.length]. */
    visibleMessageCount: number;
    deps: MessageTemplateDeps;
}

export interface RenderResult {
    html: string;
    /** Absolute index into `messages` of the first rendered message (== hidden count). */
    startIdx: number;
    /** How many messages are hidden above the window. */
    hiddenBefore: number;
    /** Resolved `visibleMessageCount` (may differ from the requested one when clamped). */
    visibleMessageCount: number;
}

/** Render the "no messages yet" welcome card. */
export function renderWelcomeCard(conversation: ChatConversation | null): string {
    const emoji = conversation?.role_emoji || '🤖';
    const name = conversation?.role_name || 'AI';
    const safeAi = safeAvatarUrl(settings.aiAvatar);
    const welcomeAvatarHtml = safeAi
        ? `<img src="${safeAi}" alt="AI" class="welcome-avatar">`
        : `<div class="welcome-emoji">${emoji}</div>`;
    return `
        <div class="chat-welcome">
            ${welcomeAvatarHtml}
            <h3>Chat with ${escapeHtml(name)}</h3>
            <p>Type a message to start the conversation</p>
        </div>
    `;
}

/** Compute the windowing plan for virtualization — pure math. */
export function computeWindow(
    total: number,
    visibleMessageCount: number,
): { startIdx: number; windowSize: number; hiddenBefore: number; visibleMessageCount: number } {
    const shouldVirtualize = total > VIRT_THRESHOLD;
    let requested = visibleMessageCount;
    if (shouldVirtualize && requested <= 0) requested = VIRT_WINDOW_SIZE;
    const windowSize = shouldVirtualize ? Math.min(requested, total) : total;
    const startIdx = total - windowSize;
    return {
        startIdx,
        windowSize,
        hiddenBefore: startIdx,
        visibleMessageCount: requested,
    };
}

/** Build the full messages HTML including the "show earlier" button when virtualizing. */
export function renderMessagesHtml(ctx: RenderContext): RenderResult {
    const total = ctx.messages.length;

    if (total === 0) {
        return {
            html: renderWelcomeCard(ctx.currentConversation),
            startIdx: 0,
            hiddenBefore: 0,
            visibleMessageCount: ctx.visibleMessageCount,
        };
    }

    const win = computeWindow(total, ctx.visibleMessageCount);

    const aiEmoji = ctx.currentConversation?.role_emoji || '🤖';
    const aiName = ctx.currentConversation?.role_name || 'AI';
    const userName = settings.userName || 'You';
    const safeUserAvatar = safeAvatarUrl(settings.userAvatar);
    const safeAiAvatar = safeAvatarUrl(settings.aiAvatar);

    const showEarlierBtn = win.hiddenBefore > 0
        ? `<button class="show-earlier-btn" id="chat-show-earlier">↑ Show ${Math.min(win.hiddenBefore, VIRT_WINDOW_SIZE)} earlier (${win.hiddenBefore} hidden)</button>`
        : '';

    const html = showEarlierBtn + ctx.messages.slice(win.startIdx).map((msg, sliceIdx) => {
        const msgIdx = win.startIdx + sliceIdx;
        return renderSingleMessage(msg, msgIdx, {
            isUser: msg.role === 'user',
            aiEmoji,
            aiName,
            userName,
            safeUserAvatar,
            safeAiAvatar,
            deps: ctx.deps,
        });
    }).join('');

    return {
        html,
        startIdx: win.startIdx,
        hiddenBefore: win.hiddenBefore,
        visibleMessageCount: win.visibleMessageCount,
    };
}

interface PerMessageCtx {
    isUser: boolean;
    aiEmoji: string;
    aiName: string;
    userName: string;
    safeUserAvatar: string;
    safeAiAvatar: string;
    deps: MessageTemplateDeps;
}

function renderSingleMessage(msg: ChatMessage, msgIdx: number, mctx: PerMessageCtx): string {
    const { isUser, aiEmoji, aiName, userName, safeUserAvatar, safeAiAvatar, deps } = mctx;
    const displayName = isUser ? userName : aiName;
    const timeStr = deps.formatTime(msg.created_at);

    // Avatar — either a safe image URL or an emoji fallback.
    let avatarHtml: string;
    if (isUser) {
        avatarHtml = safeUserAvatar
            ? `<img src="${safeUserAvatar}" alt="avatar" class="user-avatar-img">`
            : '👤';
    } else {
        avatarHtml = safeAiAvatar
            ? `<img src="${safeAiAvatar}" alt="ai" class="user-avatar-img">`
            : aiEmoji;
    }

    // Attached images (user messages only, typically). `img` is a base64 data
    // URL — escapeHtml defuses quote/angle chars so it's safe inside src="".
    let imagesHtml = '';
    if (msg.images && msg.images.length > 0) {
        imagesHtml = `<div class="message-images">${msg.images.map((img, idx) =>
            `<img src="${escapeHtml(img)}" alt="attached" class="message-image" data-img-idx="${idx}">`,
        ).join('')}</div>`;
    }

    // Thinking container (collapsed by default; click-to-expand is wired in ChatManager).
    let thinkingHtml = '';
    if (!isUser && msg.thinking) {
        thinkingHtml = `
            <div class="thinking-container">
                <div class="thinking-header collapsible collapsed">
                    💭 Thought Process
                </div>
                <div class="thinking-content collapsed">${deps.formatMessage(msg.thinking)}</div>
            </div>
        `;
    }

    // Mode badge (assistant only).
    const modeHtml = (!isUser && msg.mode)
        ? `<span class="message-mode">${escapeHtml(msg.mode)}</span>`
        : '';

    // Action buttons. All carry data-msg-id / data-msg-idx so the click
    // delegation bound in ChatManager.renderMessages can dispatch correctly.
    const msgId = msg.id != null ? msg.id : '';
    const copyBtn = `<button class="copy-message-btn" data-content="${escapeHtml(msg.content)}" title="Copy">📋 Copy</button>`;
    const editBtn = `<button class="edit-message-btn" data-msg-id="${msgId}" data-msg-idx="${msgIdx}" title="Edit">✏️ Edit</button>`;
    const aiEditBtn = (!isUser && msgId)
        ? `<button class="ai-edit-message-btn" data-msg-id="${msgId}" data-msg-idx="${msgIdx}" title="AI Edit">✨ AI Edit</button>`
        : '';
    const deleteBtn = `<button class="delete-message-btn" data-msg-id="${msgId}" data-msg-idx="${msgIdx}" data-role="${msg.role}" title="Delete">🗑️ Delete</button>`;
    const pinLabel = msg.is_pinned ? 'Unpin' : 'Pin';
    const pinBtn = msgId
        ? `<button class="pin-message-btn${msg.is_pinned ? ' pinned' : ''}" data-msg-id="${msgId}" data-pinned="${msg.is_pinned ? '1' : '0'}" title="${pinLabel}" aria-label="${pinLabel} message">📌 ${pinLabel}</button>`
        : '';
    const likeBtn = msgId
        ? `<button class="like-message-btn${msg.liked ? ' liked' : ''}" data-msg-id="${msgId}" data-liked="${msg.liked ? '1' : '0'}" title="${msg.liked ? 'Unlike' : 'Like'}" aria-label="${msg.liked ? 'Unlike' : 'Like'} message">${msg.liked ? '❤️' : '🤍'}</button>`
        : '';
    const actionsHtml = `<div class="message-actions">${copyBtn}${likeBtn}${pinBtn}${editBtn}${aiEditBtn}${deleteBtn}</div>`;

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
                <div class="message-content">${deps.formatMessage(deps.stripThinkTags(msg.content))}</div>
                ${actionsHtml}
            </div>
        </div>
    `;
}
