/**
 * H7-CSP regression guard.
 *
 * The dashboard ships with `style-src 'self'` (no `'unsafe-inline'`). The chat
 * renderer must therefore never emit inline `style=` attributes or `<style>`
 * elements into the live document:
 *   - the extended-thinking box reveals itself via CSSOM (el.style.display),
 *     which is exempt from CSP;
 *   - KaTeX is configured with output:'mathml', so math becomes a <math> tree
 *     (no inline-styled HTML spans) that DOMPurify whitelists.
 *
 * This test exercises both paths under the real strict policy and asserts that
 * the browser raised ZERO style-src violations. If someone reintroduces an
 * inline style (or drops the MathML output), the securitypolicyviolation event
 * fires and this fails — long before it reaches a user whose WebView enforces
 * the same CSP.
 */
import { expect, test } from '@playwright/test';

import { installDashboardMocks } from './_fixtures/mock-tauri';

interface DrivableChatManager {
    currentConversation: unknown;
    handleMessage: (msg: Record<string, unknown>) => void;
}

test('H7: strict style-src; chat thinking + KaTeX math render with no CSP style violation', async ({ page }) => {
    await installDashboardMocks(page);

    // Record every CSP violation from the very first byte of the document.
    await page.addInitScript(() => {
        const bucket: string[] = [];
        (window as unknown as { __cspViolations: string[] }).__cspViolations = bucket;
        document.addEventListener('securitypolicyviolation', (e) => {
            bucket.push(`${e.violatedDirective} :: ${e.blockedURI || e.sourceFile || '(inline)'}`);
        });
    });

    await page.goto('/index.html');
    await page.waitForLoadState('networkidle');

    // (a) The shipped CSP must keep style-src locked to 'self'.
    const csp = await page
        .locator('meta[http-equiv="Content-Security-Policy"]')
        .getAttribute('content');
    expect(csp, 'CSP meta present').toBeTruthy();
    const styleSrc = /style-src ([^;]*)/.exec(csp ?? '')?.[1] ?? '';
    expect(styleSrc, "style-src allows 'self'").toContain("'self'");
    expect(styleSrc, "style-src must NOT allow 'unsafe-inline'").not.toContain('unsafe-inline');

    // (b) Drive a streamed assistant reply with thinking + block LaTeX.
    await page.evaluate(() => {
        const fn = (window as unknown as { showPage?: (s: string) => void }).showPage;
        fn?.('chat');
        const cm = (window as unknown as { chatManager: DrivableChatManager }).chatManager;
        cm.currentConversation = {
            id: 'csp-guard', title: 't', role_preset: 'general',
            thinking_enabled: true, is_starred: false, created_at: '2026-05-25',
        };
        cm.handleMessage({ type: 'stream_start', mode: 'thinking' });
        cm.handleMessage({ type: 'thinking_start' });
        cm.handleMessage({ type: 'thinking_chunk', content: 'pondering the pythagorean identity' });
        const body = 'Result: $$a^2 + b^2 = c^2$$ shown above.';
        cm.handleMessage({ type: 'chunk', content: body });
        cm.handleMessage({ type: 'stream_end', full_response: body });
    });
    await page.waitForTimeout(250);

    // KaTeX rendered to MathML (proves the math path ran, not the text fallback).
    const mathCount = await page.locator('math').count();
    expect(mathCount, 'KaTeX emitted a <math> (MathML) element').toBeGreaterThan(0);

    // The thinking box became visible via CSSOM despite having no inline style=.
    const thinkingVisible = await page.evaluate(() => {
        const el = document.querySelector('.thinking-container') as HTMLElement | null;
        return el !== null && getComputedStyle(el).display !== 'none';
    });
    expect(thinkingVisible, 'thinking-container revealed via CSSOM').toBe(true);

    // The whole sequence raised no style-src violations.
    const violations: string[] = await page.evaluate(
        () => (window as unknown as { __cspViolations: string[] }).__cspViolations,
    );
    const styleViolations = violations.filter((v) => v.includes('style-src'));
    expect(
        styleViolations,
        `unexpected style-src CSP violations: ${JSON.stringify(styleViolations)}`,
    ).toHaveLength(0);
});
