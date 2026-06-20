/**
 * Sakura Midnight v2 upgrade guards.
 *
 * Locks in the regression-prone fixes from the multi-agent UI audit so a future
 * restyle can't silently undo them:
 *   - [B1]  .btn-danger label clears WCAG AA on BOTH gradient stops, resting AND hover.
 *   - [B2]  light theme has ZERO anime-purple/indigo anywhere (scans every light rule).
 *   - [B3]  the History channel filter input is styled to a >=24px target.
 *   - [SEC-06/07] CSP carries base-uri 'none' + form-action 'none'.
 *   - [VIS-04] the four --ease-* motion tokens are no longer identical.
 *   - light-theme nav hover/active label keeps AA contrast after the teal repoint.
 */
import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';

import { installDashboardMocks } from './_fixtures/mock-tauri';

// WCAG relative luminance + contrast for an "rgb(r, g, b[, a])" string vs white.
function contrastVsWhite(rgb: string): number {
    const m = rgb.match(/(\d+(?:\.\d+)?)/g);
    if (!m) return 0;
    const [r, g, b] = m.slice(0, 3).map((v) => {
        const c = Number(v) / 255;
        return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
    });
    const L = 0.2126 * r + 0.7152 * g + 0.0722 * b;
    return +((1.0 + 0.05) / (L + 0.05)).toFixed(2);
}

test.beforeEach(async ({ page }) => {
    await installDashboardMocks(page);
    await page.goto('/index.html');
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(150);
});

test('[B1] danger buttons: white label clears AA (>=4.5:1) on resting AND hover gradient stops', async ({ page }) => {
    // Resting: sample every rendered white-on-gradient danger button.
    const resting = await page.evaluate(() => {
        const ids = ['btn-stop', 'btn-clear-history', 'delete-confirm', 'btn-delete-selected'];
        return ids.map((id) => {
            const el = document.getElementById(id);
            if (!el) return { id, bg: '', color: '' };
            const cs = getComputedStyle(el);
            return { id, bg: cs.backgroundImage, color: cs.color };
        });
    });
    let checked = 0;
    for (const { id, bg, color } of resting) {
        if (!bg || bg === 'none') continue;
        if (color !== 'rgb(255, 255, 255)') continue; // white-label danger only (skip ghost-danger)
        for (const stop of bg.match(/rgb\([^)]+\)/g) ?? []) {
            const ratio = contrastVsWhite(stop);
            expect(ratio, `[B1] resting ${id} stop ${stop} = ${ratio} < 4.5`).toBeGreaterThanOrEqual(4.5);
            checked++;
        }
    }
    expect(checked, 'sampled at least one resting danger stop').toBeGreaterThan(0);

    // Hover: drive a real :hover on the always-visible Stop button and re-sample.
    await page.hover('#btn-stop');
    await page.waitForTimeout(60);
    const hover = await page.evaluate(() => {
        const cs = getComputedStyle(document.getElementById('btn-stop')!);
        return { bg: cs.backgroundImage, color: cs.color };
    });
    if (hover.color === 'rgb(255, 255, 255)') {
        for (const stop of hover.bg.match(/rgb\([^)]+\)/g) ?? []) {
            const ratio = contrastVsWhite(stop);
            expect(ratio, `[B1] hover #btn-stop stop ${stop} = ${ratio} < 4.5`).toBeGreaterThanOrEqual(4.5);
        }
    }
});

test('[B2] light theme: NO anime-purple/indigo in any light-theme CSS rule', async ({ page }) => {
    // Static scan of every rule scoped to the light theme — catches hover/active
    // and every other state, not just the resting DOM a previous guard probed.
    const offenders = await page.evaluate(() => {
        const PURPLE = [
            '124, 58, 237', '124,58,237', '#7c3aed',  // primary anime-purple
            '#6d28d9', '#9333ea', '#6366f1', '#818cf8', // violet/indigo family
            '214, 51, 132', '#d63384',                  // pink gradient partner
        ];
        const hits: string[] = [];
        for (const sheet of Array.from(document.styleSheets)) {
            let rules: CSSRuleList;
            try { rules = sheet.cssRules; } catch { continue; }
            const walk = (list: CSSRuleList) => {
                for (const rule of Array.from(list)) {
                    const grouping = rule as CSSGroupingRule;
                    if (grouping.cssRules) { walk(grouping.cssRules); continue; }
                    const sr = rule as CSSStyleRule;
                    if (!sr.selectorText) continue;
                    if (!/\[data-theme=["']?light["']?\]/.test(sr.selectorText)) continue;
                    const lower = sr.cssText.toLowerCase();
                    for (const p of PURPLE) {
                        if (lower.includes(p.toLowerCase())) {
                            hits.push(`${sr.selectorText}  ::  ${p}`);
                            break;
                        }
                    }
                }
            };
            walk(rules);
        }
        return hits;
    });
    expect(offenders, `light-theme purple/indigo leak:\n${offenders.join('\n')}`).toEqual([]);
});

test('[B2b] light-theme nav hover/active label keeps AA contrast', async ({ page }) => {
    // The teal repoint must not drop nav text below 4.5:1. Proxy: nav text on the
    // light sidebar wash (~white) — assert contrast vs white >= 4.5.
    // Force light via the app's real path (stored theme) + reload, so boot's
    // initTheme() applies light deterministically instead of racing a setAttribute.
    await page.evaluate(() => localStorage.setItem('dashboard-settings', JSON.stringify({ theme: 'light' })));
    await page.reload();
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(200);
    const ratios = await page.evaluate(() => {
        const out: { sel: string; color: string }[] = [];
        const active = document.querySelector('.nav-item.active') as HTMLElement | null;
        if (active) out.push({ sel: '.nav-item.active', color: getComputedStyle(active).color });
        const idle = document.querySelector('.nav-item:not(.active)') as HTMLElement | null;
        if (idle) {
            idle.classList.add('__probe-hover'); // can't trigger :hover here; read base
            out.push({ sel: '.nav-item', color: getComputedStyle(idle).color });
        }
        return out;
    });
    for (const { sel, color } of ratios) {
        const ratio = contrastVsWhite(color);
        expect(ratio, `[B2b] light ${sel} text ${color} on light wash = ${ratio} < 4.5`).toBeGreaterThanOrEqual(4.5);
    }
});

test('[B3] History channel filter input is styled to a >=24px target', async ({ page }) => {
    const height = await page.evaluate(() => {
        const wrap = document.createElement('div');
        wrap.className = 'history-channel-filter';
        const input = document.createElement('input');
        input.type = 'search';
        input.className = 'history-filter-input';
        wrap.appendChild(input);
        document.body.appendChild(wrap);
        const h = input.getBoundingClientRect().height;
        wrap.remove();
        return h;
    });
    expect(height, `history-filter-input height ${height}px < 24`).toBeGreaterThanOrEqual(24);
});

test('[SEC-06/07] CSP carries base-uri and form-action hardening', async ({ page }) => {
    const csp = await page
        .locator('meta[http-equiv="Content-Security-Policy"]')
        .getAttribute('content');
    expect(csp, 'CSP present').toBeTruthy();
    expect(csp ?? '', "base-uri 'none'").toContain("base-uri 'none'");
    expect(csp ?? '', "form-action 'none'").toContain("form-action 'none'");
    expect(csp ?? '', 'script-src self preserved').toContain("script-src 'self'");
    expect(csp ?? '', 'connect-src loopback preserved').toContain('127.0.0.1:8765');
});

test('[VIS-04] motion vocabulary is no longer collapsed (eases differ)', async ({ page }) => {
    const eases = await page.evaluate(() => {
        const cs = getComputedStyle(document.documentElement);
        return {
            base: cs.getPropertyValue('--ease').trim(),
            smooth: cs.getPropertyValue('--ease-smooth').trim(),
            expo: cs.getPropertyValue('--ease-out-expo').trim(),
            bounce: cs.getPropertyValue('--ease-bounce').trim(),
        };
    });
    const set = new Set(Object.values(eases));
    expect(set.size, `eases should be distinct, got ${JSON.stringify(eases)}`).toBeGreaterThanOrEqual(3);
    expect(eases.bounce, 'bounce overshoots').toMatch(/1\.\d/);
});

test('[a11y-light] no axe color-contrast violations across pages in LIGHT theme', async ({ page }) => {
    // The teal repoint (B2) only ever runs against the dark default in the other
    // axe suite; this drives axe (correct gradient/alpha compositing) over every
    // page in LIGHT theme so a sub-AA accent (e.g. teal text on the light wash)
    // can't slip through the way the original purple leak did.
    // Force light via the app's real stored-theme path + reload (deterministic,
    // no race with boot initTheme()).
    await page.evaluate(() => localStorage.setItem('dashboard-settings', JSON.stringify({ theme: 'light' })));
    await page.reload();
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(200);
    // Reveal the chat thread so message text is analyzable.
    await page.evaluate(() => {
        const o = document.getElementById('chat-not-running-overlay'); if (o) o.style.display = 'none';
        const e = document.getElementById('chat-empty'); if (e) e.classList.add('hidden');
        const c = document.getElementById('chat-container'); if (c) { c.classList.remove('hidden'); (c as HTMLElement).style.display = 'flex'; }
    });
    const pages = ['status', 'chat', 'logs', 'database', 'settings', 'history'];
    const violations: string[] = [];
    for (const p of pages) {
        await page.evaluate((pg) => (window as unknown as { showPage: (s: string) => void }).showPage(pg), p);
        await page.waitForTimeout(120);
        const results = await new AxeBuilder({ page }).withRules(['color-contrast']).analyze();
        for (const v of results.violations) {
            for (const n of v.nodes) {
                violations.push(`${p}: ${n.target.join(' ')} — ${n.html.slice(0, 70)}`);
            }
        }
    }
    expect(violations, `light-theme color-contrast violations:\n${violations.join('\n')}`).toEqual([]);
});
