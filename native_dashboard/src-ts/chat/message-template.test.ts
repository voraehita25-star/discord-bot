/**
 * Tests for chat/message-template.ts — virtualization math + message HTML output.
 *
 * computeWindow() is pure math — hammered with table-driven cases.
 * renderMessagesHtml() is exercised with fake `deps` so we don't need KaTeX /
 * DOMPurify / real message formatting; we just care the HTML structure lines
 * up with what the post-render event delegation in ChatManager expects.
 */

import { describe, it, expect } from 'vitest';
import {
    computeWindow,
    renderMessagesHtml,
    renderWelcomeCard,
    VIRT_THRESHOLD,
    VIRT_WINDOW_SIZE,
    type MessageTemplateDeps,
} from './message-template.js';
import type { ChatConversation, ChatMessage } from './types.js';

/** Deterministic fake deps so HTML output is predictable across test runs. */
const fakeDeps: MessageTemplateDeps = {
    formatTime: () => 'NOW',
    formatMessage: (c: string) => `[formatted]${c}[/formatted]`,
    stripThinkTags: (c: string) => c,
};

function mkConv(id: string = 'c1', overrides: Partial<ChatConversation> = {}): ChatConversation {
    return {
        id,
        title: 'test',
        role_preset: 'general',
        thinking_enabled: false,
        is_starred: false,
        created_at: '2026-04-01T00:00:00Z',
        ...overrides,
    };
}

function mkMsg(i: number, overrides: Partial<ChatMessage> = {}): ChatMessage {
    return {
        id: i,
        role: i % 2 === 0 ? 'user' : 'assistant',
        content: `msg ${i}`,
        created_at: '2026-04-01T00:00:00Z',
        ...overrides,
    };
}

// ============================================================================
// computeWindow — the windowing-by-tail math
// ============================================================================

describe('computeWindow', () => {
    it('renders everything below VIRT_THRESHOLD', () => {
        const w = computeWindow(50, 0);
        expect(w.startIdx).toBe(0);
        expect(w.windowSize).toBe(50);
        expect(w.hiddenBefore).toBe(0);
    });

    it('at exactly the threshold, still renders all', () => {
        const w = computeWindow(VIRT_THRESHOLD, 0);
        expect(w.hiddenBefore).toBe(0);
        expect(w.windowSize).toBe(VIRT_THRESHOLD);
    });

    it('just above the threshold, virtualizes to default window size', () => {
        const total = VIRT_THRESHOLD + 1;
        const w = computeWindow(total, 0);
        expect(w.windowSize).toBe(VIRT_WINDOW_SIZE);
        expect(w.startIdx).toBe(total - VIRT_WINDOW_SIZE);
        expect(w.hiddenBefore).toBe(total - VIRT_WINDOW_SIZE);
    });

    it('clamps a requested count larger than total to total', () => {
        const w = computeWindow(200, 999);
        expect(w.windowSize).toBe(200);
        expect(w.startIdx).toBe(0);
    });

    it('grows the window when the requested count is > default (show-earlier)', () => {
        const w = computeWindow(500, 300);
        expect(w.windowSize).toBe(300);
        expect(w.startIdx).toBe(200);
        expect(w.hiddenBefore).toBe(200);
    });

    it('always keeps the window anchored to the tail', () => {
        // Regardless of request, start + windowSize must equal total.
        const total = 1000;
        const w = computeWindow(total, 100);
        expect(w.startIdx + w.windowSize).toBe(total);
    });
});

// ============================================================================
// renderWelcomeCard
// ============================================================================

describe('renderWelcomeCard', () => {
    it('includes the AI role name when provided', () => {
        const html = renderWelcomeCard(mkConv('c', { role_name: 'Faust' }));
        expect(html).toContain('Chat with Faust');
    });

    it('falls back to "AI" when no role_name', () => {
        const html = renderWelcomeCard(mkConv());
        expect(html).toContain('Chat with AI');
    });

    it('handles null conversation (initial state)', () => {
        const html = renderWelcomeCard(null);
        expect(html).toContain('chat-welcome');
    });

    it('escapes role name to prevent XSS via conversation title', () => {
        const html = renderWelcomeCard(mkConv('c', { role_name: '<script>evil</script>' }));
        expect(html).not.toMatch(/<script>evil<\/script>/);
        expect(html).toContain('&lt;script&gt;');
    });
});

// ============================================================================
// renderMessagesHtml — top-level shape
// ============================================================================

describe('renderMessagesHtml', () => {
    it('returns welcome card when messages is empty', () => {
        const result = renderMessagesHtml({
            messages: [],
            currentConversation: mkConv(),
            visibleMessageCount: 0,
            deps: fakeDeps,
        });
        expect(result.html).toContain('chat-welcome');
        expect(result.startIdx).toBe(0);
        expect(result.hiddenBefore).toBe(0);
    });

    it('renders every message for small conversations', () => {
        const messages = [mkMsg(0), mkMsg(1), mkMsg(2)];
        const result = renderMessagesHtml({
            messages,
            currentConversation: mkConv(),
            visibleMessageCount: 0,
            deps: fakeDeps,
        });
        // Three message blocks + no show-earlier button.
        expect(result.html).not.toContain('show-earlier-btn');
        expect(result.html.match(/class="chat-message /g)?.length).toBe(3);
        expect(result.hiddenBefore).toBe(0);
    });

    it('adds show-earlier button when virtualizing', () => {
        const messages = Array.from({ length: VIRT_THRESHOLD + 20 }, (_, i) => mkMsg(i));
        const result = renderMessagesHtml({
            messages,
            currentConversation: mkConv(),
            visibleMessageCount: VIRT_WINDOW_SIZE,
            deps: fakeDeps,
        });
        expect(result.html).toContain('show-earlier-btn');
        expect(result.html).toContain('id="chat-show-earlier"');
        expect(result.hiddenBefore).toBeGreaterThan(0);
    });

    it('uses the absolute message index for data-msg-idx', () => {
        // 200 msgs → window of 100 → first rendered msg has absolute index 100.
        const messages = Array.from({ length: 200 }, (_, i) => mkMsg(i));
        const result = renderMessagesHtml({
            messages,
            currentConversation: mkConv(),
            visibleMessageCount: VIRT_WINDOW_SIZE,
            deps: fakeDeps,
        });
        // First rendered msg in the window should have data-msg-idx="100".
        expect(result.html).toContain('data-msg-idx="100"');
        // And the last should be the final absolute index.
        expect(result.html).toContain('data-msg-idx="199"');
    });

    it('wires formatMessage for both content and thinking blocks', () => {
        const messages = [mkMsg(0, {
            role: 'assistant',
            content: 'hello',
            thinking: 'my reasoning',
        })];
        const result = renderMessagesHtml({
            messages,
            currentConversation: mkConv(),
            visibleMessageCount: 0,
            deps: fakeDeps,
        });
        // [formatted]hello[/formatted] proves content went through the formatter dep.
        expect(result.html).toContain('[formatted]hello[/formatted]');
        // ...and so did thinking.
        expect(result.html).toContain('[formatted]my reasoning[/formatted]');
    });

    it('marks pinned messages in the pin button dataset', () => {
        // Use id=42 for a clearly persisted message. (id=0 also renders
        // correctly — msgId becomes the truthy string "0" via the
        // String(Math.trunc(...)) coercion; only a missing/negative/non-finite
        // id yields "" and skips the buttons.)
        const result = renderMessagesHtml({
            messages: [mkMsg(42, { is_pinned: true })],
            currentConversation: mkConv(),
            visibleMessageCount: 0,
            deps: fakeDeps,
        });
        expect(result.html).toMatch(/pin-message-btn pinned/);
        expect(result.html).toMatch(/data-pinned="1"/);
    });

    it('marks liked messages in the like button dataset', () => {
        const result = renderMessagesHtml({
            messages: [mkMsg(42, { liked: true })],
            currentConversation: mkConv(),
            visibleMessageCount: 0,
            deps: fakeDeps,
        });
        expect(result.html).toMatch(/like-message-btn liked/);
        expect(result.html).toMatch(/data-liked="1"/);
    });

    it('skips pin/like buttons for messages without an id (in-flight local sends)', () => {
        const msg: ChatMessage = {
            role: 'user',
            content: 'not yet persisted',
            created_at: '2026-04-01T00:00:00Z',
        };
        const result = renderMessagesHtml({
            messages: [msg],
            currentConversation: mkConv(),
            visibleMessageCount: 0,
            deps: fakeDeps,
        });
        expect(result.html).not.toContain('pin-message-btn');
        expect(result.html).not.toContain('like-message-btn');
        // Copy + edit + delete still render (they don't require a persisted ID).
        expect(result.html).toContain('copy-message-btn');
    });

    it('renders attached images with data-img-idx', () => {
        const result = renderMessagesHtml({
            messages: [mkMsg(0, { images: ['data:image/png;base64,AAA', 'data:image/png;base64,BBB'] })],
            currentConversation: mkConv(),
            visibleMessageCount: 0,
            deps: fakeDeps,
        });
        expect(result.html).toContain('data-img-idx="0"');
        expect(result.html).toContain('data-img-idx="1"');
        expect(result.html).toContain('message-images');
    });

    // ------------------------------------------------------------------------
    // SECURITY: <img src> allowlist filter. This is the sole in-JS XSS/privacy
    // defense for server-controlled image URLs (a compromised WS server could
    // otherwise smuggle javascript:, http:// tracking pixels, or an
    // SVG-with-onload). The filter lets through ONLY data:image/* (non-svg).
    //
    // NOTE: the https-CDN allowlist (ALLOWED_IMG_HOSTS) was narrowed to EMPTY
    // (dash-ts-chat-2) to match the packaged CSP `img-src 'self' data: blob:`
    // (no https host) — CSP is the authoritative, stricter gate, so emitting an
    // https <img> the runtime can't render would be a "valid but invisible"
    // broken image. These tests therefore assert NO remote https image survives,
    // only the png data: URL.
    // ------------------------------------------------------------------------
    it('filters out svg, http, javascript, and remote-https image srcs, keeping only png-data', () => {
        const result = renderMessagesHtml({
            messages: [mkMsg(0, {
                images: [
                    'data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=',  // SVG → scriptable, REJECT
                    'http://evil.example/x.png',                    // plaintext http → REJECT
                    'javascript:alert(1)',                          // scheme abuse → REJECT
                    'data:image/png;base64,AAA',                    // raster data URL → ALLOW
                    'https://cdn.discordapp.com/ok.png',            // remote https → REJECT (no CDN in CSP)
                ],
            })],
            currentConversation: mkConv(),
            visibleMessageCount: 0,
            deps: fakeDeps,
        });

        // Only the png data: URL survives — as a src="..." attribute.
        expect(result.html).toContain('src="data:image/png;base64,AAA"');

        // None of the rejected URLs appear as an <img src> (escaped or not).
        // NOTE: match `http://` (not bare `http:`) so a future re-allowed
        // `https://` host couldn't accidentally satisfy this assertion.
        expect(result.html).not.toMatch(/data:image\/svg/i);
        expect(result.html).not.toMatch(/src="http:\/\//i);
        expect(result.html).not.toMatch(/javascript:/i);
        expect(result.html).not.toContain('evil.example');
        // The previously-allowlisted CDN host is now rejected too (CSP-aligned).
        expect(result.html).not.toContain('cdn.discordapp.com');

        // Exactly one surviving image, re-based to index 0 — the filter runs
        // before the map, so we never emit a gap.
        expect((result.html.match(/class="message-image"/g) ?? []).length).toBe(1);
        expect(result.html).toContain('data-img-idx="0"');
        expect(result.html).not.toContain('data-img-idx="1"');
    });

    it('rejects an arbitrary https host (no remote image is emitted)', () => {
        const result = renderMessagesHtml({
            messages: [mkMsg(0, { images: ['https://attacker.example/pixel.png'] })],
            currentConversation: mkConv(),
            visibleMessageCount: 0,
            deps: fakeDeps,
        });
        expect(result.html).not.toContain('attacker.example');
        // No surviving images → no <img class="message-image"> at all.
        expect(result.html).not.toContain('class="message-image"');
    });

    // ------------------------------------------------------------------------
    // SECURITY: escapeHtml must run on every user/server-controlled value that
    // lands in an HTML attribute or text node, INDEPENDENT of formatMessage
    // (which the real ChatManager sanitizes separately). The fake formatMessage
    // here is a pass-through, so this test proves the escapeHtml call sites in
    // renderSingleMessage are present rather than relying on the formatter.
    // ------------------------------------------------------------------------
    it('escapes attacker-controlled attribute/text fields (content, mode, role, doc name, displayName)', () => {
        const XSS = '"><svg onload=alert(1)>';
        const result = renderMessagesHtml({
            messages: [mkMsg(0, {
                role: `assistant${XSS}` as ChatMessage['role'],
                content: XSS,
                mode: XSS,
                // Only `.name` is read by the template; cast keeps the test
                // independent of DocumentPayload's full shape.
                documents: [{ name: XSS }] as unknown as ChatMessage['documents'],
            })],
            // displayName for an assistant comes from role_name on the conversation.
            currentConversation: mkConv('c1', { role_name: `Faust${XSS}` }),
            visibleMessageCount: 0,
            deps: fakeDeps,
        });

        // The `.message-content` body is deliberately the formatter's job
        // (real ChatManager pipes msg.content through DOMPurify; the fake
        // formatMessage here is a pass-through). This test is about the
        // OTHER fields, so strip the body before the global breakout checks.
        const outsideBody = result.html.replace(
            /<div class="message-content">[\s\S]*?<\/div>/,
            '<div class="message-content">[BODY]</div>',
        );

        // The attacker's scriptable element must never survive as live markup
        // outside the formatter-owned body. (Legit icon() output is inline
        // `<svg class="ic" ...>` followed/preceded by buttons, so a bare `<svg`
        // or `"><svg` check would false-positive; we target the attacker's
        // specific `<svg ... onload=` injection, which escapeHtml neutralizes.)
        expect(outsideBody).not.toMatch(/<svg[^>]*onload/i);

        // Each field's dangerous payload is present only in escaped form.
        // escapeHtml turns < > " into &lt; &gt; &quot;.
        expect(result.html).toContain('&lt;svg onload=alert(1)&gt;');
        // data-content (copy button), the role class, the mode badge, the doc
        // chip name, and the display name all carry the escaped payload.
        expect(result.html).toMatch(/data-content="[^"]*&lt;svg/i);
        expect(result.html).toMatch(/class="chat-message assistant&quot;&gt;&lt;svg/i);
        expect(result.html).toMatch(/class="message-mode">[^<]*&lt;svg/i);
        expect(result.html).toMatch(/class="message-doc-chip"[^>]*&lt;svg/i);
        expect(result.html).toMatch(/class="message-name">Faust&quot;&gt;&lt;svg/i);
    });
});
