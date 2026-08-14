import { expect, test } from '@playwright/test';

import { installPopulatedMocks, waitForDashboardReady } from './_fixtures/mock-tauri';

/**
 * Dawn and midnight may differ in COLOUR. They may not differ in SHAPE.
 *
 * This guard exists because the same defect landed three times, and each time it
 * was invisible to everyone working in the default (dark) theme:
 *
 *   - `.stat-card` kept a card's hairline and drop shadow on dawn after the
 *     telemetry tiles gave that chrome up;
 *   - `.chart-card` kept a bordered, shadowed box per plot on dawn after v6
 *     ("CHARTS — one panel, two cells") retired the nested frames;
 *   - `.data-item` kept a filled, rounded, fully-bordered row on dawn after v8
 *     turned the data rows into one ruled list.
 *
 * All three share one mechanism. The base sheet writes its dawn overrides as
 * `html[data-theme="light"] .x`, which is specificity (0,2,0). Every later
 * design decision in `orbital.css` is written as a plain `.x`, which is (0,1,0).
 * Source order never gets consulted, so the newer decision loses and dawn goes
 * on rendering a design the app retired — a component with two designs, chosen
 * by whichever theme happens to be active. Nothing catches it: the visual
 * baselines, the axe run and the contrast sweeps are all per-theme, so a
 * component being a DIFFERENT SHAPE in the other theme is exactly the thing
 * none of them can see.
 *
 * So: snapshot the computed geometry of every visible element on every page in
 * both themes and diff them. Colour properties are deliberately absent from
 * SHAPE_PROPS — that is the axis the two themes are supposed to move on.
 */

const PAGES = ['status', 'chat', 'logs', 'database', 'settings', 'history'];

/**
 * Theme-invariant properties. Anything here changing across a theme flip is a
 * leaked override, not a palette choice.
 */
const SHAPE_PROPS = [
    'border-top-width',
    'border-right-width',
    'border-bottom-width',
    'border-left-width',
    'border-top-left-radius',
    'border-bottom-right-radius',
    'padding-top',
    'padding-left',
    'font-weight',
    'font-family',
    'text-transform',
    'letter-spacing',
    'display',
    'text-decoration-line',
] as const;

/**
 * The two places the themes are ALLOWED to be shaped differently, each settled
 * with a reason on the record. Anything else that wants on this list needs the
 * same: a rationale, not a shrug.
 *
 * Matched with `Element.matches()`, so these are ordinary selectors.
 */
const ACCEPTED_DIVERGENCE: ReadonlyArray<{ selector: string; why: string }> = [
    {
        // app-context.md names buttons as one of the three places the two themes
        // differ in design rather than merely in hue: midnight outlines the
        // primary button, dawn fills it with the brand gradient and drops the
        // border, because an outline on paper reads as secondary.
        selector: '.btn-primary',
        why: 'dawn fills the primary button with --brand-grad and drops the border (documented design divergence)',
    },
    {
        // `html[data-theme="light"] kbd` paints a solid accent pill with white
        // ink, measured at 7.05:1, and orbital.css's outlined-chip treatment is
        // written to sit UNDER it on purpose — see the `.chat-input-hint kbd`
        // comment, which states the light path is deliberately left alone.
        selector: 'kbd',
        why: 'dawn paints the key chip as a filled accent pill at a measured 7.05:1 (deliberate, see .chat-input-hint kbd)',
    },
];

interface ShapeRecord {
    /** Human-readable locator, only used to write a failure message. */
    label: string;
    /** SHAPE_PROPS values, joined. */
    shape: string;
    /** True when the element matched ACCEPTED_DIVERGENCE. */
    exempt: boolean;
}

/**
 * Walk the document in a stable order and record each visible element's shape.
 *
 * `#toast-container` is skipped wholesale: flipping the theme raises a "Theme:
 * Light" toast, so its subtree is the one part of the DOM that legitimately
 * differs between the two snapshots and would otherwise shift every index after
 * it.
 */
async function snapshotShapes(
    page: import('@playwright/test').Page,
): Promise<ShapeRecord[]> {
    return page.evaluate(
        ({ props, exemptSelectors }) => {
            const out: ShapeRecord[] = [];
            const walk = (el: Element): void => {
                if (el.id === 'toast-container') return;
                const he = el as HTMLElement;
                // offsetParent is null for display:none subtrees (and for
                // position:fixed elements, which is why <body> is exempted).
                const visible = he.offsetParent !== null || el.tagName === 'BODY';
                if (visible) {
                    const cs = getComputedStyle(he);
                    const cls =
                        typeof he.className === 'string' && he.className.trim()
                            ? '.' + he.className.trim().split(/\s+/).join('.')
                            : '';
                    out.push({
                        label: `${el.tagName.toLowerCase()}${he.id ? '#' + he.id : ''}${cls}`,
                        shape: props.map((p) => cs.getPropertyValue(p)).join(' | '),
                        exempt: exemptSelectors.some((s) => {
                            try {
                                return he.matches(s);
                            } catch {
                                return false;
                            }
                        }),
                    });
                }
                for (const child of Array.from(el.children)) walk(child);
            };
            walk(document.body);
            return out;
        },
        {
            props: SHAPE_PROPS as unknown as string[],
            exemptSelectors: ACCEPTED_DIVERGENCE.map((a) => a.selector),
        },
    );
}

test('theme parity: no element changes shape when the theme flips', async ({ page }) => {
    await installPopulatedMocks(page);
    await page.goto('/index.html');
    await page.waitForLoadState('domcontentloaded');
    await waitForDashboardReady(page);

    const failures: string[] = [];

    for (const name of PAGES) {
        await page.evaluate((p) => {
            (window as unknown as { showPage?: (s: string) => void }).showPage?.(p);
        }, name);
        await page.waitForTimeout(250);

        const dark = await snapshotShapes(page);

        // Flip through the REAL control, never by writing data-theme directly:
        // applyTheme() repaints the canvas charts and re-reads the CSS→JS token
        // contract, and a raw attribute write would skip both.
        await page.click('#theme-toggle');
        await page.waitForTimeout(350);
        const light = await snapshotShapes(page);

        expect(
            light.length,
            `[${name}] the theme flip changed the element count — the walk is no longer comparable`,
        ).toBe(dark.length);

        dark.forEach((d, i) => {
            const l = light[i];
            if (!l || l.shape === d.shape || d.exempt) return;
            const dp = d.shape.split(' | ');
            const lp = l.shape.split(' | ');
            const diffs = SHAPE_PROPS.map((p, k) =>
                dp[k] !== lp[k] ? `${p}: dark=${dp[k]} light=${lp[k]}` : null,
            ).filter(Boolean);
            failures.push(`[${name}] ${d.label}\n      ${diffs.join('\n      ')}`);
        });

        await page.click('#theme-toggle'); // restore midnight for the next page
        await page.waitForTimeout(350);
    }

    expect(
        failures,
        'These elements are a different SHAPE in dawn than in midnight. That is almost\n' +
            'always a `html[data-theme="light"] .x` rule in styles.css (0,2,0) outranking a\n' +
            'later plain `.x` decision in orbital.css (0,1,0). Fix the override rather than\n' +
            'restating the decision at higher specificity — and if the difference really is\n' +
            'intended, add it to ACCEPTED_DIVERGENCE with the reason.\n\n' +
            failures.join('\n'),
    ).toEqual([]);
});
