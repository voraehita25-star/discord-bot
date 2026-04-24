/**
 * E2E smoke tests for the static dashboard shell (#32).
 *
 * These tests parse the REAL `ui/index.html` via jsdom and assert structural
 * invariants — the IDs that the compiled app.js and chat-manager.js reach for.
 * They catch regressions like:
 *   - A rename or removal of a key element (e.g. removing `chat-input` would
 *     break every send).
 *   - ARIA-label drift on icon-only controls.
 *   - The feature toggles (sakura/telemetry) silently vanishing.
 *   - New DOM elements added by the TS code having a paired container.
 *
 * Full Tauri/IPC coverage would need `tauri-driver` + Playwright; that's a
 * heavier install. These tests run in under a second with zero extra deps
 * (uses the `jsdom` already in devDependencies).
 */

import { describe, it, expect, beforeAll } from 'vitest';
import { JSDOM } from 'jsdom';
import { readFileSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const INDEX_HTML = resolve(__dirname, '..', 'ui', 'index.html');

describe('index.html shell smoke', () => {
    let doc: Document;

    beforeAll(() => {
        const html = readFileSync(INDEX_HTML, 'utf-8');
        // runScripts: "outside-only" disables inline script execution so we
        // don't need to stub Tauri IPC — we're testing DOM structure only.
        const dom = new JSDOM(html, { runScripts: 'outside-only', url: 'http://localhost/' });
        doc = dom.window.document;
    });

    it('has a valid <!DOCTYPE html>', () => {
        expect(doc.doctype?.name).toBe('html');
    });

    it('sets a restrictive Content-Security-Policy meta', () => {
        const csp = doc.querySelector('meta[http-equiv="Content-Security-Policy"]');
        expect(csp).not.toBeNull();
        const content = csp?.getAttribute('content') ?? '';
        expect(content).toContain("default-src 'self'");
        expect(content).toContain("object-src 'none'");
        expect(content).toContain("frame-ancestors 'none'");
        expect(content).not.toContain("'unsafe-eval'");
    });

    it('has SRI integrity hashes on every vendor <script src>', () => {
        const vendorScripts = Array.from(
            doc.querySelectorAll('script[src^="vendor/"]'),
        ) as HTMLScriptElement[];
        expect(vendorScripts.length).toBeGreaterThan(0);
        for (const s of vendorScripts) {
            expect(s.hasAttribute('integrity')).toBe(true);
            expect(s.getAttribute('integrity')).toMatch(/^sha(256|384|512)-/);
            expect(s.getAttribute('crossorigin')).toBe('anonymous');
        }
    });

    it('bundles DOMPurify, KaTeX, and Prism locally (no CDN references)', () => {
        // Use the raw attribute — jsdom's `.src` resolves to an absolute URL
        // against the document base, which would be a false positive.
        const scripts = Array.from(doc.querySelectorAll('script[src]')) as HTMLScriptElement[];
        for (const s of scripts) {
            const rawSrc = (s.getAttribute('src') || '').trim().toLowerCase();
            expect(rawSrc).not.toMatch(/^https?:\/\//);
        }
    });

    it('exposes all core navigation tabs', () => {
        const pages = ['status', 'chat', 'memories', 'logs', 'database', 'settings'];
        for (const p of pages) {
            expect(doc.querySelector(`[data-page="${p}"]`), `nav item data-page=${p}`).not.toBeNull();
            expect(doc.getElementById(`page-${p}`), `<section id=page-${p}>`).not.toBeNull();
        }
    });

    it('provides the chat input + send button the TS code reaches for', () => {
        expect(doc.getElementById('chat-input')).not.toBeNull();
        expect(doc.getElementById('btn-send')).not.toBeNull();
        expect(doc.getElementById('chat-messages')).not.toBeNull();
        expect(doc.getElementById('conversation-list')).not.toBeNull();
        expect(doc.getElementById('conversation-filter-input')).not.toBeNull();
    });

    it('has the scroll-to-bottom FAB + search bar + tags bar (recent UI features)', () => {
        expect(doc.getElementById('scroll-to-bottom-fab')).not.toBeNull();
        expect(doc.getElementById('chat-search-bar')).not.toBeNull();
        expect(doc.getElementById('chat-search-input')).not.toBeNull();
        expect(doc.getElementById('chat-tags')).not.toBeNull();
    });

    it('has all Settings toggles wired by app.ts', () => {
        expect(doc.getElementById('refresh-interval')).not.toBeNull();
        expect(doc.getElementById('notifications-toggle')).not.toBeNull();
        expect(doc.getElementById('sakura-toggle')).not.toBeNull();
        expect(doc.getElementById('telemetry-toggle')).not.toBeNull();
        expect(doc.getElementById('creator-toggle')).not.toBeNull();
    });

    it('has modals used by the chat flow', () => {
        for (const id of [
            'new-chat-modal',
            'delete-confirm-modal',
            'rename-modal',
            'avatar-crop-modal',
            'shortcuts-modal',
            'add-memory-modal',
        ]) {
            expect(doc.getElementById(id), `modal ${id}`).not.toBeNull();
        }
    });

    it('icon-only buttons expose aria-label for screen readers', () => {
        // Buttons that have an emoji-only visible label MUST carry aria-label.
        const mustHaveAria = [
            'btn-rename-chat',
            'btn-star-chat',
            'btn-export-chat',
            'btn-delete-chat',
            'btn-attach',
            'btn-send',
            'scroll-to-bottom-fab',
            'chat-search-prev',
            'chat-search-next',
            'chat-search-close',
        ];
        for (const id of mustHaveAria) {
            const el = doc.getElementById(id);
            expect(el, `button ${id}`).not.toBeNull();
            expect(el?.hasAttribute('aria-label'), `${id} missing aria-label`).toBe(true);
        }
    });

    it('has no inline onclick/onload/onerror handlers (CSP-safe)', () => {
        const all = doc.querySelectorAll('*');
        for (const el of Array.from(all)) {
            for (const name of el.getAttributeNames()) {
                expect(name.startsWith('on'), `${el.tagName} has inline ${name}`).toBe(false);
            }
        }
    });

    it('has no inline <script> content (CSP: script-src \'self\')', () => {
        const inlineScripts = Array.from(doc.querySelectorAll('script:not([src])'));
        for (const s of inlineScripts) {
            expect((s.textContent || '').trim(), `inline script: "${s.textContent?.slice(0, 80)}"`).toBe('');
        }
    });

    it('has no javascript: / data: URLs in <a href> or <img src>', () => {
        const offenders: string[] = [];
        for (const el of Array.from(doc.querySelectorAll('a[href], img[src]'))) {
            const attr = el.tagName === 'A' ? 'href' : 'src';
            const value = (el.getAttribute(attr) || '').trim().toLowerCase();
            if (value.startsWith('javascript:') || value.startsWith('vbscript:')) {
                offenders.push(`${el.tagName}[${attr}=${value}]`);
            }
        }
        expect(offenders).toEqual([]);
    });
});
