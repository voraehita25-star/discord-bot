/**
 * Tests for chat/context-window.ts — token-usage bar + LRU localStorage cache.
 *
 * jsdom gives us localStorage + DOM so we exercise the indicator end-to-end:
 * update → DOM paint → restore from cache → forget → persisted.
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { ContextWindowIndicator, type TokenUsage } from './context-window.js';

// Minimal DOM the indicator needs.
const INDICATOR_HTML = `
    <div id="context-window-indicator" style="display:none">
        <div class="context-bar-container">
            <div id="context-bar-fill"></div>
        </div>
        <span id="context-bar-label"></span>
    </div>
`;

function mountDom(): void {
    document.body.innerHTML = INDICATOR_HTML;
}

function mkUsage(total: number, ctx: number = 100_000): TokenUsage {
    return {
        input_tokens: Math.floor(total * 0.7),
        output_tokens: total - Math.floor(total * 0.7),
        total_tokens: total,
        context_window: ctx,
    };
}

beforeEach(() => {
    localStorage.clear();
    mountDom();
});

describe('ContextWindowIndicator.update', () => {
    it('displays the indicator and sets width as percentage of context_window', () => {
        const cw = new ContextWindowIndicator();
        cw.update('c1', mkUsage(25_000, 100_000));  // 25% of context

        const indicator = document.getElementById('context-window-indicator')!;
        const fill = document.getElementById('context-bar-fill')!;
        const label = document.getElementById('context-bar-label')!;

        expect(indicator.style.display).toBe('flex');
        expect(fill.style.width).toBe('25%');
        expect(label.textContent).toMatch(/25\.0%/);
    });

    it('adds usage-moderate class at ≥50% and usage-high at ≥80%', () => {
        const cw = new ContextWindowIndicator();
        const fill = document.getElementById('context-bar-fill')!;

        cw.update('c1', mkUsage(60_000));  // 60% → moderate
        expect(fill.classList.contains('usage-moderate')).toBe(true);
        expect(fill.classList.contains('usage-high')).toBe(false);

        cw.update('c1', mkUsage(85_000));  // 85% → high
        expect(fill.classList.contains('usage-high')).toBe(true);
        expect(fill.classList.contains('usage-moderate')).toBe(false);

        cw.update('c1', mkUsage(10_000));  // 10% → neither
        expect(fill.classList.contains('usage-high')).toBe(false);
        expect(fill.classList.contains('usage-moderate')).toBe(false);
    });

    it('caps width at 100% when usage exceeds context window', () => {
        const cw = new ContextWindowIndicator();
        cw.update('c1', mkUsage(200_000, 100_000));  // 200% of context
        const fill = document.getElementById('context-bar-fill')!;
        expect(fill.style.width).toBe('100%');
    });

    it('formats large numbers with K suffix', () => {
        const cw = new ContextWindowIndicator();
        cw.update('c1', mkUsage(45_000, 100_000));
        const label = document.getElementById('context-bar-label')!;
        expect(label.textContent).toMatch(/45\.0K.*100\.0K/);
    });

    it('ignores updates with context_window=0 (avoid div-by-zero)', () => {
        const cw = new ContextWindowIndicator();
        const zeroUsage: TokenUsage = { input_tokens: 100, output_tokens: 0, total_tokens: 100, context_window: 0 };
        cw.update('c1', zeroUsage);
        const indicator = document.getElementById('context-window-indicator')!;
        // Display stays at its initial value (display:none from inline style).
        expect(indicator.style.display).toBe('none');
    });

    it('accepts null conversationId (render without caching)', () => {
        const cw = new ContextWindowIndicator();
        cw.update(null, mkUsage(10_000));
        const indicator = document.getElementById('context-window-indicator')!;
        expect(indicator.style.display).toBe('flex');
        // Nothing should land in localStorage without a conversation id.
        expect(localStorage.getItem('dashboard_token_usage')).toBeNull();
    });
});

describe('ContextWindowIndicator.reset', () => {
    it('hides the indicator', () => {
        const cw = new ContextWindowIndicator();
        cw.update('c1', mkUsage(10_000));
        cw.reset();
        const indicator = document.getElementById('context-window-indicator')!;
        expect(indicator.style.display).toBe('none');
    });

    it('is a no-op when DOM is missing (defensive against hot reload)', () => {
        document.body.innerHTML = '';
        const cw = new ContextWindowIndicator();
        expect(() => cw.reset()).not.toThrow();
    });
});

describe('ContextWindowIndicator.restore', () => {
    it('paints the bar from cached usage', () => {
        const cw = new ContextWindowIndicator();
        cw.update('c1', mkUsage(40_000));
        cw.reset();  // hide it again

        cw.restore('c1');
        const indicator = document.getElementById('context-window-indicator')!;
        expect(indicator.style.display).toBe('flex');
    });

    it('hides the indicator for unknown conversation ids', () => {
        const cw = new ContextWindowIndicator();
        cw.update('c1', mkUsage(40_000));  // cache another conv
        cw.restore('c-never-seen');
        const indicator = document.getElementById('context-window-indicator')!;
        expect(indicator.style.display).toBe('none');
    });
});

describe('ContextWindowIndicator.forget', () => {
    it('drops a cached reading and persists the new cache state', () => {
        const cw = new ContextWindowIndicator();
        cw.update('c1', mkUsage(40_000));
        cw.update('c2', mkUsage(50_000));
        cw.forget('c1');

        const raw = localStorage.getItem('dashboard_token_usage');
        expect(raw).toBeTruthy();
        const parsed = JSON.parse(raw!);
        expect(parsed.c1).toBeUndefined();
        expect(parsed.c2).toBeDefined();
    });

    it('is a no-op for unknown conversation ids', () => {
        const cw = new ContextWindowIndicator();
        cw.update('c1', mkUsage(40_000));
        expect(() => cw.forget('c-never-seen')).not.toThrow();
    });
});

describe('ContextWindowIndicator — localStorage persistence', () => {
    it('writes to localStorage on every update', () => {
        const cw = new ContextWindowIndicator();
        cw.update('c1', mkUsage(40_000));
        const raw = localStorage.getItem('dashboard_token_usage');
        expect(raw).toBeTruthy();
        expect(JSON.parse(raw!).c1.total_tokens).toBe(40_000);
    });

    it('load() restores cache from prior session', () => {
        localStorage.setItem('dashboard_token_usage', JSON.stringify({
            c1: mkUsage(10_000),
            c2: mkUsage(20_000),
        }));
        const cw = new ContextWindowIndicator();
        cw.load();
        // Check by restoring each — should set bar to visible.
        cw.restore('c1');
        expect(document.getElementById('context-window-indicator')!.style.display).toBe('flex');
        cw.restore('c-missing');
        expect(document.getElementById('context-window-indicator')!.style.display).toBe('none');
    });

    it('load() survives corrupt localStorage without throwing', () => {
        localStorage.setItem('dashboard_token_usage', '{ this is not json');
        const cw = new ContextWindowIndicator();
        expect(() => cw.load()).not.toThrow();
    });

    it('LRU-caps persisted entries at 200', () => {
        const cw = new ContextWindowIndicator();
        // Insert 220 conversations — only the last 200 should survive.
        for (let i = 0; i < 220; i++) {
            cw.update(`c${i}`, mkUsage(10_000 + i));
        }
        const raw = localStorage.getItem('dashboard_token_usage');
        const parsed = JSON.parse(raw!);
        const keys = Object.keys(parsed);
        expect(keys.length).toBe(200);
        // The earliest 20 were evicted.
        expect(parsed.c0).toBeUndefined();
        expect(parsed.c19).toBeUndefined();
        expect(parsed.c20).toBeDefined();
        expect(parsed.c219).toBeDefined();
    });
});
