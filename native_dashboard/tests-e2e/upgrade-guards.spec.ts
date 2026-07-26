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

import { installDashboardMocks, waitForDashboardReady } from './_fixtures/mock-tauri';

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
    // Await the real bootstrap-complete signal rather than a fixed timeout:
    // spec FILES run concurrently, so under load the deferred ES-module
    // bootstrap regularly outran the old wait and a click landed before
    // initNavigation() had bound its handler.
    await waitForDashboardReady(page);
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
    //
    // ⚠️ This test spent its whole life passing vacuously — see the note on the
    // walk below. It inspected zero declarations. Its sibling [B2c] covers the
    // colours that leaked past it while it was asleep.
    const offenders = await page.evaluate(() => {
        const RETIRED = [
            '124, 58, 237', '124,58,237', '#7c3aed',  // primary anime-purple
            '#6d28d9', '#9333ea', '#6366f1', '#818cf8', // violet/indigo family
            '214, 51, 132', '#d63384',                  // pink gradient partner
        ];
        const hits: string[] = [];
        for (const sheet of Array.from(document.styleSheets)) {
            let rules: CSSRuleList;
            try { rules = sheet.cssRules; } catch { continue; }
            // CAREFUL — this walk used to read:
            //     if (grouping.cssRules) { walk(grouping.cssRules); continue; }
            //     if (!sr.selectorText) continue;
            //     ...check...
            // Since Chromium shipped CSS nesting, `CSSStyleRule` ALSO exposes a
            // (usually empty) `cssRules`, so that first branch matched every
            // style rule in the sheet, recursed into nothing, and `continue`d
            // past the check. The guard inspected zero declarations and passed
            // unconditionally — which is how a retired teal survived two skins
            // under a test written to forbid exactly that. Check the rule FIRST,
            // then descend into whatever it nests.
            const walk = (list: CSSRuleList) => {
                for (const rule of Array.from(list)) {
                    const sr = rule as CSSStyleRule;
                    if (sr.selectorText && sr.style &&
                        /\[data-theme=["']?light["']?\]/.test(sr.selectorText)) {
                        // .style.cssText is this rule's own declarations. Using
                        // .cssText instead would pull in nested rules' text and
                        // report the same literal against several selectors.
                        const lower = sr.style.cssText.toLowerCase();
                        for (const p of RETIRED) {
                            if (lower.includes(p.toLowerCase())) {
                                hits.push(`${sr.selectorText}  ::  ${p}`);
                                break;
                            }
                        }
                    }
                    const nested = (rule as CSSGroupingRule).cssRules;
                    if (nested && nested.length) walk(nested);
                }
            };
            walk(rules);
        }
        return hits;
    });
    expect(offenders, `light-theme purple/indigo leak:\n${offenders.join('\n')}`).toEqual([]);
});

/**
 * [B2c] No retired palette reaches the SCREEN, in either theme.
 *
 * [B2] above is a static scan, and a static scan of a layered stylesheet cannot
 * tell a live rule from a dead one: styles.css still holds ~40 declarations in
 * the retired Blueprint teal / slate / Tailwind-400 ramp, and orbital.css
 * overrides most of them. Demanding the source be literal-free would be a
 * separate cleanup; what matters to a user is which of them still PAINT.
 *
 * Four did, and none of them were visible to any existing test:
 *   · `.data-item.selected`   — a teal fill + glow on a checked Database row,
 *                               a state no screenshot covered.
 *   · `.toast-info`           — a cold blue card every time the app said
 *                               something neutral; toasts only exist while one
 *                               is on screen, so the resting DOM never had it.
 *   · the light card border / log-container / input rules — a slate-violet
 *                               hairline and a 25%-alpha teal outline on dawn
 *                               paper, which axe has no opinion about.
 *
 * So this samples COMPUTED colour across every page, both themes, and the
 * transient surfaces (toasts, each modal, a selected row) that a resting sweep
 * misses — then flags any hue in the 165-250deg band. The Sakura Midnight palette
 * is gold (~36deg), jade (~155deg), wisteria (~257deg) and sakura/rose
 * (~337-351deg); nothing legitimate lands between jade and wisteria.
 */
test('[B2c] no retired-palette colour is painted on screen, in either theme', async ({ page }) => {
    const PROPS = [
        'color', 'backgroundColor', 'borderTopColor', 'borderLeftColor',
        'outlineColor', 'boxShadow', 'backgroundImage', 'fill', 'stroke',
    ] as const;

    const scan = (label: string) =>
        page.evaluate(({ label, PROPS }) => {
            const hueOf = (r: number, g: number, b: number) => {
                const mx = Math.max(r, g, b), mn = Math.min(r, g, b), d = mx - mn;
                if (!d) return { h: 0, s: 0, l: mx / 255 };
                let h: number;
                if (mx === r) h = 60 * (((g - b) / d) % 6);
                else if (mx === g) h = 60 * ((b - r) / d + 2);
                else h = 60 * ((r - g) / d + 4);
                return { h: h < 0 ? h + 360 : h, s: d / mx, l: mx / 255 };
            };
            const out: string[] = [];
            for (const el of Array.from(document.querySelectorAll<HTMLElement>('*'))) {
                const cs = getComputedStyle(el);
                if (cs.display === 'none' || cs.visibility === 'hidden') continue;
                const b = el.getBoundingClientRect();
                if (b.width === 0 || b.height === 0) continue;
                for (const prop of PROPS) {
                    const raw = (cs as unknown as Record<string, string>)[prop];
                    if (!raw || raw === 'none') continue;
                    for (const m of raw.matchAll(/rgba?\(([^)]*)\)/g)) {
                        const parts = m[1].split(/[,/\s]+/).filter(Boolean).map(Number);
                        const [r, g, bl] = parts;
                        const a = parts.length > 3 ? parts[3] : 1;
                        if (!Number.isFinite(r) || a < 0.06) continue;
                        const { h, s, l } = hueOf(r, g, bl);
                        if (s < 0.18 || l < 0.10) continue;
                        if (h < 165 || h > 250) continue;
                        out.push(
                            `[${label}] hue ${Math.round(h)} rgb(${r},${g},${bl}) via ${prop} on ` +
                            el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') +
                            (typeof el.className === 'string' && el.className
                                ? '.' + el.className.trim().split(/\s+/).slice(0, 3).join('.') : ''),
                        );
                    }
                }
            }
            return out;
        }, { label, PROPS: PROPS as unknown as string[] });

    const hits: string[] = [];
    for (const theme of ['dark', 'light'] as const) {
        await page.evaluate((t) => document.documentElement.setAttribute('data-theme', t), theme);
        await page.waitForTimeout(300);

        for (const p of ['status', 'chat', 'logs', 'database', 'settings', 'history']) {
            await page.evaluate(
                (n) => (window as unknown as { showPage?: (s: string) => void }).showPage?.(n),
                p,
            );
            await page.waitForTimeout(250);
            hits.push(...(await scan(`${theme}/${p}`)));
        }

        // A selected Database row — where the teal actually hid.
        await page.evaluate(() => {
            (window as unknown as { showPage?: (s: string) => void }).showPage?.('database');
            document.querySelectorAll<HTMLInputElement>('.data-item-checkbox')[0]?.click();
        });
        await page.waitForTimeout(250);
        hits.push(...(await scan(`${theme}/database:row-selected`)));

        // All four toast severities.
        await page.evaluate(async () => {
            const sharedModulePath = '/shared.js';
            const mod = await import(sharedModulePath) as {
                showToast?: (m: string, o: { type: string; duration?: number }) => void;
            };
            for (const type of ['success', 'error', 'warning', 'info']) {
                mod.showToast?.(`a ${type} toast`, { type, duration: 30_000 });
            }
        });
        await page.waitForTimeout(400);
        hits.push(...(await scan(`${theme}/toasts`)));
        await page.evaluate(() => {
            document.getElementById('toast-container')?.replaceChildren();
        });

        // Every modal, each of which owns surfaces nothing else renders.
        for (const id of [
            'new-chat-modal', 'rename-modal', 'delete-confirm-modal',
            'chat-files-modal', 'avatar-crop-modal', 'shortcuts-modal',
        ]) {
            await page.evaluate((m) => {
                for (const el of Array.from(document.querySelectorAll('.modal.active'))) {
                    el.classList.remove('active');
                }
                document.getElementById(m)?.classList.add('active');
            }, id);
            await page.waitForTimeout(200);
            hits.push(...(await scan(`${theme}/${id}`)));
        }
        await page.evaluate(() => {
            for (const el of Array.from(document.querySelectorAll('.modal.active'))) {
                el.classList.remove('active');
            }
        });
    }

    expect([...new Set(hits)], `retired palette still painting:\n${[...new Set(hits)].join('\n')}`)
        .toEqual([]);
});

/**
 * Settle CSS colour transitions before sampling computed colour.
 *
 * The theme flip below happens AFTER first paint (initTheme() sets data-theme
 * during bootstrap), so every colour token animates over --dur-base (220ms).
 * A contrast assertion that reads getComputedStyle() mid-animation samples an
 * interpolated colour: this test was failing intermittently on
 * `rgb(245,237,244)` (the DARK theme's --text-primary) and on in-between values
 * like `rgb(167,156,166)`. It only ever "passed" because the old fixed
 * waitForTimeout(200) usually outlasted the transition.
 *
 * Kill transitions via a constructed CSSStyleSheet rather than addStyleTag() —
 * the production CSP is style-src 'self' with no 'unsafe-inline', so an injected
 * <style> element is blocked, while CSSOM mutation is exempt (same technique as
 * visual-regression.spec.ts). Scoped to the two tests that flip the theme and
 * then read colour, so VIS-04's motion-vocabulary assertions are untouched.
 */
async function freezeColorTransitions(page: import('@playwright/test').Page): Promise<void> {
    await page.evaluate(() => {
        const sheet = new CSSStyleSheet();
        sheet.replaceSync('*, *::before, *::after { transition: none !important; animation: none !important; }');
        document.adoptedStyleSheets = [...document.adoptedStyleSheets, sheet];
    });
}

test('[B2b] light-theme nav hover/active label keeps AA contrast', async ({ page }) => {
    // The teal repoint must not drop nav text below 4.5:1. Proxy: nav text on the
    // light sidebar wash (~white) — assert contrast vs white >= 4.5.
    // Force light via the app's real path (stored theme) + reload, so boot's
    // initTheme() applies light deterministically instead of racing a setAttribute.
    await page.evaluate(() => localStorage.setItem('dashboard-settings', JSON.stringify({ theme: 'light' })));
    await page.reload();
    await page.waitForLoadState('domcontentloaded');
    // The reload re-runs boot, so await the fresh bootstrap signal — the old
    // fixed wait could sample the DOM before initTheme() had applied light.
    await waitForDashboardReady(page);
    await freezeColorTransitions(page);
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
    // The reload re-runs boot, so await the fresh bootstrap signal — the old
    // fixed wait could sample the DOM before initTheme() had applied light.
    await waitForDashboardReady(page);
    // axe composites real computed colours, so the theme transition must be
    // settled here too or a mid-animation colour gets scored.
    await freezeColorTransitions(page);
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

test('[a11y-dark] no axe color-contrast violations across pages in DARK theme (the default)', async ({ page }) => {
    // Dark is this app's canonical surface (playwright.config pins
    // colorScheme:'dark'), yet only LIGHT theme had a color-contrast axe run —
    // a dark-theme contrast regression could ship with every gate green. Same
    // loop as [a11y-light] above, no theme forcing: the default IS dark.
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
    expect(violations, `dark-theme color-contrast violations:\n${violations.join('\n')}`).toEqual([]);
});
