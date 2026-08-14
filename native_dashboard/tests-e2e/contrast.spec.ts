/**
 * Pixel-sampled colour contrast (WCAG 1.4.3 AA).
 *
 * WHY THIS EXISTS — the suite already runs axe's `color-contrast` rule in both
 * themes and it reports zero VIOLATIONS. That result is close to meaningless
 * here: on this UI axe cannot resolve the backdrop for ~390 text nodes per
 * sweep and files them as `incomplete`, which is neither a pass nor a fail and
 * which no assertion looks at. Roughly every surface in the app carries a
 * ::before texture or a background gradient, and those are exactly the two
 * things that make axe give up:
 *
 *     366 x "background color could not be determined due to a pseudo element"
 *      23 x "...due to a background gradient"
 *       2 x "...because it is overlapped by another element"
 *
 * Four low-emphasis styles shipped under AA behind that blind spot
 * (.page-eyebrow, .nav-item .shortcut, .setting-hint-inline, .empty-state p),
 * the worst at 2.52:1.
 *
 * So this spec measures what the user actually sees: hide the text, screenshot
 * the box it occupied, average those pixels for the true composited backdrop,
 * then run the WCAG maths against the text colour — including any `opacity`
 * multiplier on the element or its ancestors, which is invisible to anything
 * that only reads `color` (that multiplier is what took .nav-item .shortcut
 * from a survivable 3.87 to 2.71).
 *
 * Slower than axe, so it is scoped to the styles that carry quiet text. Add a
 * selector here whenever you add another muted role.
 */
import { test, expect, type Page } from '@playwright/test';
import { installPopulatedMocks, waitForDashboardReady } from './_fixtures/mock-tauri';
import { PNG } from 'pngjs';

const PAGES = ['status', 'chat', 'logs', 'database', 'settings', 'history'] as const;

/**
 * Every style whose job is to be quiet — i.e. every candidate for going too
 * quiet — plus every ACCENT-ON-TINT chip. The accent group is here because the
 * light palette's tokens were each verified against white, and not one of them
 * is ever painted on white: they sit on a 9-10% tint of themselves, over a
 * tinted surface. `--accent-green` measured 5.0:1 on paper and 4.25:1 on the
 * sidebar badge it actually paints; the "LIVE" chip was worse still.
 */
const MUTED_TEXT = [
    '.status-badge .status-text',
    '#bot-status-text',
    '.live-indicator',
    '.page-eyebrow',
    '.nav-item .shortcut',
    '.setting-hint-inline',
    '.settings-hint',
    '.empty-state p',
    '.stat-label',
    '.chat-input-hint',
    '.chart-readout',
    '.chat-role-name',
    '.no-conversations p',
    '.history-header.is-placeholder h2',
    '.shortcut-item span',
    '.features-list li',
    '.conv-meta',
    '.data-item-id',
    // Command palette. Only reachable with the dialog OPEN, which is why the
    // sweep below opens it on the last page rather than trusting a resting
    // page to contain these — a selector that matches nothing is measured as a
    // pass, silently, forever.
    '.cmdk-group-label',
    '.cmdk-hint',
    '.cmdk-esc',
    '.cmdk-item',
];

const relLum = (r: number, g: number, b: number): number => {
    const f = [r, g, b].map((v) => {
        const s = v / 255;
        return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * f[0] + 0.7152 * f[1] + 0.0722 * f[2];
};
const contrast = (a: number, b: number): number =>
    (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);

interface Target {
    sel: string; idx: number;
    x: number; y: number; w: number; h: number;
    color: string; alpha: number; fontPx: number; bold: boolean; text: string;
}

async function collectTargets(page: Page, sels: string[]): Promise<Target[]> {
    return page.evaluate((selectors) => {
        const out: Target[] = [];
        for (const sel of selectors) {
            document.querySelectorAll<HTMLElement>(sel).forEach((el, idx) => {
                const b = el.getBoundingClientRect();
                // Must be fully on-screen: the clip below cannot sample pixels
                // that were never painted.
                if (b.width < 4 || b.height < 4) return;
                if (b.top < 0 || b.left < 0 || b.bottom > window.innerHeight || b.right > window.innerWidth) return;
                const cs = getComputedStyle(el);
                if (cs.visibility === 'hidden' || cs.display === 'none') return;
                const text = (el.textContent || '').replace(/\s+/g, ' ').trim();
                if (!text) return;
                // -webkit-text-fill-color wins over `color` when both are set
                // (.live-indicator sets it), so read the one that paints.
                const fill = cs.webkitTextFillColor;
                const inkColor =
                    fill && fill !== 'currentcolor' && /^rgba?\(/.test(fill) ? fill : cs.color;
                // The effective alpha is the element's own opacity times every
                // ancestor's — `color`'s alpha channel alone misses both.
                let alpha = 1;
                for (let n: HTMLElement | null = el; n; n = n.parentElement) {
                    const o = parseFloat(getComputedStyle(n).opacity);
                    if (!Number.isNaN(o)) alpha *= o;
                }
                if (alpha < 0.05) return; // effectively invisible; not a contrast question
                out.push({
                    sel, idx, x: b.x, y: b.y, w: b.width, h: b.height,
                    color: inkColor, alpha,
                    fontPx: parseFloat(cs.fontSize),
                    bold: parseInt(cs.fontWeight, 10) >= 700,
                    text: text.slice(0, 50),
                });
            });
        }
        return out;
    }, sels);
}

async function measure(page: Page, t: Target): Promise<{ ratio: number; need: number; bg: string } | null> {
    // Hide the GLYPHS, not the element. `visibility: hidden` also removes the
    // element's own background, so any chip that paints its own fill (the
    // status badge, #bot-status-text, the LIVE indicator) would be measured
    // against the surface BEHIND it rather than the tint it actually sits on —
    // which reads as a comfortable pass for text that is really under AA.
    const setInk = (v: string) =>
        page.evaluate(
            ({ sel, idx, v }) => {
                const el = document.querySelectorAll<HTMLElement>(sel)[idx];
                if (!el) return;
                if (v) {
                    el.style.setProperty('color', v, 'important');
                    el.style.setProperty('-webkit-text-fill-color', v, 'important');
                } else {
                    el.style.removeProperty('color');
                    el.style.removeProperty('-webkit-text-fill-color');
                }
            },
            { sel: t.sel, idx: t.idx, v },
        );

    await setInk('transparent');
    const buf = await page.screenshot({
        clip: {
            x: Math.floor(t.x), y: Math.floor(t.y),
            width: Math.max(2, Math.floor(t.w)), height: Math.max(2, Math.floor(t.h)),
        },
        // Freeze the LIVE badge's infinite pulse so its sampled backdrop is
        // the same on every run.
        animations: 'disabled',
    });
    await setInk('');

    const png = PNG.sync.read(buf);
    let r = 0, g = 0, b = 0, n = 0;
    for (let i = 0; i < png.data.length; i += 4) {
        r += png.data[i]; g += png.data[i + 1]; b += png.data[i + 2]; n++;
    }
    if (n === 0) return null;
    r /= n; g /= n; b /= n;

    const m = t.color.match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const cv = m[1].split(',').map((x) => parseFloat(x));
    // Fully transparent ink means the glyphs are painted by something else
    // (background-clip:text). Blending it would compute a fabricated 1.0 ratio
    // and report a pass; skip instead of lying.
    if (cv[3] === 0) return null;
    const a = t.alpha * (cv[3] === undefined ? 1 : cv[3]);
    const fr = cv[0] * a + r * (1 - a);
    const fg = cv[1] * a + g * (1 - a);
    const fb = cv[2] * a + b * (1 - a);

    const large = t.fontPx >= 24 || (t.fontPx >= 18.66 && t.bold);
    return {
        ratio: contrast(relLum(fr, fg, fb), relLum(r, g, b)),
        need: large ? 3 : 4.5,
        bg: `rgb(${Math.round(r)},${Math.round(g)},${Math.round(b)})`,
    };
}

for (const theme of ['dark', 'light'] as const) {
    test(`low-emphasis text clears WCAG AA — ${theme} theme, every page`, async ({ page }) => {
        test.slow(); // one screenshot per measured node
        await page.setViewportSize({ width: 1280, height: 800 });
        await installPopulatedMocks(page);
        await page.goto('/index.html');
        await waitForDashboardReady(page);
        await page.evaluate((t) => document.documentElement.setAttribute('data-theme', t), theme);

        const failures: string[] = [];
        let measured = 0;

        for (const p of PAGES) {
            await page.evaluate(
                (n) => (window as unknown as { showPage?: (s: string) => void }).showPage?.(n),
                p,
            );
            // Long enough for every FINITE entrance animation to settle. This
            // is load-bearing, not padding: #page-status.active .stat-card runs
            // orbital-rise (opacity 0 -> 1) with delays up to 0.20s on top of a
            // 0.5s duration, and .page.active adds a 0.3s fadeIn. collectTargets
            // reads the live opacity while page.screenshot({animations:'disabled'})
            // fast-forwards the render to completion — measure before they
            // settle and the text alpha comes from a half-faded card while the
            // backdrop comes from a fully painted one, which scored .stat-label
            // at a fictional 4.13:1.
            await page.waitForTimeout(900);

            for (const t of await collectTargets(page, MUTED_TEXT)) {
                const m = await measure(page, t);
                if (!m) continue;
                measured++;
                if (m.ratio < m.need) {
                    failures.push(
                        `${theme}/${p} ${t.sel} "${t.text}" — ${m.ratio.toFixed(2)}:1 ` +
                        `(needs ${m.need}, ${t.fontPx}px, fg ${t.color} @${t.alpha.toFixed(2)} on ${m.bg})`,
                    );
                }
            }
        }

        // The command palette, which is a surface no page sweep can reach: it
        // is a dialog, its rows are built at runtime, and its whole vocabulary
        // is quiet text (a mono group label, a mono chord chip, and rows set in
        // --text-secondary) sitting on the modal's own tinted plate rather than
        // on any page surface measured above.
        await page.keyboard.press('Control+k');
        await page.waitForTimeout(400);
        const paletteTargets = await collectTargets(page, MUTED_TEXT);
        expect(
            paletteTargets.some((t) => t.sel.startsWith('.cmdk-')),
            'the palette did not open, so its text was never measured',
        ).toBe(true);
        for (const t of paletteTargets) {
            if (!t.sel.startsWith('.cmdk-')) continue;
            const m = await measure(page, t);
            if (!m) continue;
            measured++;
            if (m.ratio < m.need) {
                failures.push(
                    `${theme}/palette ${t.sel} "${t.text}" — ${m.ratio.toFixed(2)}:1 ` +
                    `(needs ${m.need}, ${t.fontPx}px, fg ${t.color} @${t.alpha.toFixed(2)} on ${m.bg})`,
                );
            }
        }
        await page.keyboard.press('Escape');

        expect(measured, 'no nodes measured — the selector list or the boot flow broke').toBeGreaterThan(40);
        expect(failures, `${failures.length} of ${measured} nodes under AA:\n${failures.join('\n')}`).toEqual([]);
    });
}
