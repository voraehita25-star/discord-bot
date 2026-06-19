/**
 * Audit-2 regression test for chat/message-template.ts.
 *
 * dash-ts-chat-2: isAllowedExternalImage's host allowlist was WIDER than the
 * packaged CSP (`img-src 'self' data: blob:` — no https host), so an https CDN
 * image passed the JS filter, was emitted as <img>, then silently blocked by
 * CSP at load ("valid but invisible"). The fix narrows the allowlist to match
 * the CSP: NO https host is emitted. The strict scheme rejections (svg / http /
 * javascript) are the security control and MUST stay intact, and data:image/png
 * (non-SVG) must still render.
 *
 * Renders via renderMessagesHtml with fake deps (no DOMPurify needed — these
 * <img> tags are built by the template, not the formatter).
 */

import { describe, it, expect } from 'vitest';
import { renderMessagesHtml, type MessageTemplateDeps } from './message-template.js';
import type { ChatConversation, ChatMessage } from './types.js';

const fakeDeps: MessageTemplateDeps = {
    formatTime: () => 'NOW',
    formatMessage: (c: string) => `[formatted]${c}[/formatted]`,
    stripThinkTags: (c: string) => c,
};

function mkConv(): ChatConversation {
    return {
        id: 'c1',
        title: 'test',
        role_preset: 'general',
        thinking_enabled: false,
        is_starred: false,
        created_at: '2026-04-01T00:00:00Z',
    };
}

function mkMsg(images: string[]): ChatMessage {
    return {
        id: 0,
        role: 'user',
        content: 'msg',
        created_at: '2026-04-01T00:00:00Z',
        images,
    };
}

function renderImages(images: string[]): string {
    return renderMessagesHtml({
        messages: [mkMsg(images)],
        currentConversation: mkConv(),
        visibleMessageCount: 0,
        deps: fakeDeps,
    }).html;
}

describe('message-template — dash-ts-chat-2 (img allowlist matches CSP)', () => {
    it('does NOT emit any https CDN image (allowlist narrowed to CSP img-src)', () => {
        // These four hosts were the OLD allowlist; CSP has no https host so they
        // must no longer be emitted (they would render broken under CSP anyway).
        const html = renderImages([
            'https://cdn.discordapp.com/ok.png',
            'https://media.discordapp.net/ok.png',
            'https://i.imgur.com/ok.png',
            'https://images.unsplash.com/ok.png',
        ]);
        expect(html).not.toContain('cdn.discordapp.com');
        expect(html).not.toContain('media.discordapp.net');
        expect(html).not.toContain('i.imgur.com');
        expect(html).not.toContain('images.unsplash.com');
        // No surviving images at all -> no <img class="message-image">.
        expect(html).not.toContain('class="message-image"');
    });

    it('still emits a data:image/png (non-SVG) image', () => {
        const html = renderImages(['data:image/png;base64,AAA']);
        expect(html).toContain('src="data:image/png;base64,AAA"');
        expect(html).toContain('class="message-image"');
    });

    it('still REJECTS svg, http, javascript, and arbitrary https (security control intact)', () => {
        const html = renderImages([
            'data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=', // scriptable SVG -> REJECT
            'http://evil.example/x.png',                   // plaintext http -> REJECT
            'javascript:alert(1)',                         // scheme abuse  -> REJECT
            'https://attacker.example/pixel.png',          // arbitrary https -> REJECT
        ]);
        expect(html).not.toMatch(/data:image\/svg/i);
        expect(html).not.toMatch(/src="http:/i);
        expect(html).not.toMatch(/javascript:/i);
        expect(html).not.toContain('evil.example');
        expect(html).not.toContain('attacker.example');
        expect(html).not.toContain('class="message-image"');
    });

    it('keeps only the data:image/png when mixed with now-rejected https CDN + dangerous schemes', () => {
        const html = renderImages([
            'data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=',
            'http://evil.example/x.png',
            'data:image/png;base64,AAA',                   // only survivor
            'https://cdn.discordapp.com/ok.png',           // now rejected
        ]);
        expect(html).toContain('src="data:image/png;base64,AAA"');
        // Exactly one surviving image, re-based to index 0.
        expect((html.match(/class="message-image"/g) ?? []).length).toBe(1);
        expect(html).toContain('data-img-idx="0"');
        expect(html).not.toContain('data-img-idx="1"');
    });
});
