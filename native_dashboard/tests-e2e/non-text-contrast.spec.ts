/**
 * Non-text + high-emphasis contrast the other specs structurally cannot see.
 *
 * WHY THIS EXISTS — three separate blind spots let a whole class of unreadable
 * controls ship at once:
 *
 *   1. axe's `color-contrast` rule returns `incomplete` (not a pass, not a
 *      fail) for ~390 nodes here, because nearly every surface carries a
 *      ::before texture or a gradient. `contrast.spec.ts` was written to cover
 *      that, but it is deliberately scoped to LOW-EMPHASIS text — the styles
 *      whose job is to be quiet. Everything below is high-emphasis: a Save
 *      button, a submit button, a badge, a scroll FAB.
 *   2. Every one of these controls only exists in a TRANSIENT state — a history
 *      row switched to edit mode, a staged attachment, a scrolled-up transcript
 *      — so no full-page sweep or visual baseline ever renders them.
 *   3. WCAG 1.4.11 (non-text contrast) applies to the toggle switches and the
 *      icon-only send button, and nothing was checking it at all.
 *
 * What actually broke: styles.css fills these from --accent-purple /
 * --accent-red / --brand-grad and hardcodes `color: white` on top. That pairing
 * was written against a palette where those tokens were saturated mid-tones in
 * BOTH themes. Sakura inverts them — night's wisteria is #c7b1ff and its rose
 * #ff5d78, both pale — so the AI-History editor's Save button shipped as a
 * blank lavender pill at 1.88:1 and you could not read the word on it.
 *
 * The measurement is the same pixel-sampling method contrast.spec.ts uses (hide
 * the ink, screenshot the box it occupied, average for the true composited
 * backdrop) because gradients make computed-style arithmetic a lie here.
 */
import { test, expect, type Page } from '@playwright/test';
import { installPopulatedMocks, waitForDashboardReady } from './_fixtures/mock-tauri';
import { PNG } from 'pngjs';

const relLum = (r: number, g: number, b: number): number => {
    const f = [r, g, b].map((v) => {
        const s = v / 255;
        return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * f[0] + 0.7152 * f[1] + 0.0722 * f[2];
};
const contrast = (a: number, b: number): number =>
    (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);

/** Average the pixels of a screenshot buffer. */
function avg(buf: Buffer): { r: number; g: number; b: number } {
    const png = PNG.sync.read(buf);
    let r = 0, g = 0, b = 0, n = 0;
    for (let i = 0; i < png.data.length; i += 4) {
        r += png.data[i]; g += png.data[i + 1]; b += png.data[i + 2]; n++;
    }
    return { r: r / n, g: g / n, b: b / n };
}

/**
 * Ink-vs-plate ratio for one element, measured on the pixels the user sees.
 *
 * Blanking `color` blanks BOTH the text and any `stroke: currentColor` sprite
 * inside it (that is how `.ic` is drawn), so the same routine covers the
 * icon-only controls without a second code path.
 */
async function inkRatio(page: Page, sel: string): Promise<{ ratio: number; ink: string; plate: string }> {
    const box = await page.locator(sel).first().boundingBox();
    if (!box) throw new Error(`${sel} has no box`);
    const ink = await page.locator(sel).first().evaluate((el) => {
        // The glyph may be painted by a child (.ic inherits currentColor), so
        // read the colour off whichever node actually carries the mark.
        const marked = el.querySelector('svg') ?? el;
        return getComputedStyle(marked as Element).color;
    });
    await page.locator(sel).first().evaluate((el) => {
        (el as HTMLElement).style.setProperty('color', 'transparent', 'important');
        el.querySelectorAll<HTMLElement>('*').forEach((c) =>
            c.style.setProperty('color', 'transparent', 'important'));
    });
    // Inset by the border so the plate sample is the FILL, not the edge.
    const clip = {
        x: Math.floor(box.x) + 3, y: Math.floor(box.y) + 3,
        width: Math.max(2, Math.floor(box.width) - 6),
        height: Math.max(2, Math.floor(box.height) - 6),
    };
    const plate = avg(await page.screenshot({ clip, animations: 'disabled' }));
    await page.locator(sel).first().evaluate((el) => {
        (el as HTMLElement).style.removeProperty('color');
        el.querySelectorAll<HTMLElement>('*').forEach((c) => c.style.removeProperty('color'));
    });

    const m = ink.match(/rgba?\(([^)]+)\)/);
    if (!m) throw new Error(`unparseable ink ${ink} on ${sel}`);
    const v = m[1].split(',').map(parseFloat);
    const a = v[3] === undefined ? 1 : v[3];
    const fr = v[0] * a + plate.r * (1 - a);
    const fg = v[1] * a + plate.g * (1 - a);
    const fb = v[2] * a + plate.b * (1 - a);
    return {
        ratio: contrast(relLum(fr, fg, fb), relLum(plate.r, plate.g, plate.b)),
        ink,
        plate: `rgb(${Math.round(plate.r)},${Math.round(plate.g)},${Math.round(plate.b)})`,
    };
}

async function boot(page: Page, theme: 'dark' | 'light'): Promise<void> {
    await page.setViewportSize({ width: 1280, height: 800 });
    await installPopulatedMocks(page);
    await page.goto('/index.html');
    await waitForDashboardReady(page);
    await page.evaluate((t) => document.documentElement.setAttribute('data-theme', t), theme);
    await page.waitForTimeout(400);
}

/**
 * Show the chat composer. The mock reports the bot as running, but the
 * transcript only mounts once a conversation is open, so the overlay and the
 * empty state are dismissed directly.
 */
async function openComposer(page: Page): Promise<void> {
    await page.evaluate(() => {
        (window as unknown as { showPage?: (s: string) => void }).showPage?.('chat');
        document.getElementById('chat-not-running-overlay')?.classList.remove('visible');
        document.getElementById('chat-empty')?.classList.add('hidden');
        const c = document.getElementById('chat-container');
        if (c) { c.classList.remove('hidden'); (c as HTMLElement).style.display = 'flex'; }
    });
}

/**
 * Every control whose ink is hardcoded over an accent fill, with the AA floor
 * its content type owes: 4.5 for a word, 3.0 for a bare glyph (1.4.11).
 *
 * These are mounted on a board rather than driven through their real flows: two
 * of them need a live WebSocket turn (the AI-edit submit, the staged-attachment
 * chips) and one needs a scrolled transcript. The board instantiates the real
 * class names inside the real page, so the real cascade — tokens, theme
 * overrides, source order — is what gets measured; only the trigger is
 * synthetic. If a class here is ever renamed, the mount fails and the test
 * fails, which is the intended coupling.
 */
const INK_CASES: Array<{ id: string; html: string; need: number }> = [
    { id: 'edit-save-btn', need: 4.5, html: '<button class="edit-save-btn">Save</button>' },
    { id: 'ai-edit-submit-btn', need: 4.5, html: '<button class="ai-edit-submit-btn">Apply</button>' },
    // Both of these are styled by DESCENDANT selectors (`.scroll-to-bottom-fab
    // .fab-badge`), so the badge has to be mounted inside a real FAB or the case
    // measures an unstyled <span> and passes vacuously.
    {
        id: 'fab-badge', need: 4.5,
        html: '<button class="scroll-to-bottom-fab" style="position:relative;bottom:auto;right:auto">'
            + '<span class="fab-arrow"><svg class="ic"><use href="#i-chevron-down"/></svg></span>'
            + '<span class="fab-badge">7</span></button>',
    },
    {
        id: 'scroll-to-bottom-fab', need: 3.0,
        html: '<button class="scroll-to-bottom-fab" style="position:relative;bottom:auto;right:auto">'
            + '<span class="fab-arrow"><svg class="ic"><use href="#i-chevron-down"/></svg></span></button>',
    },
    {
        id: 'remove-image', need: 3.0,
        html: '<div class="attached-image-preview" style="position:relative;width:56px;height:56px">'
            + '<button class="remove-image" style="position:relative;top:0;right:0">&times;</button></div>',
    },
    {
        id: 'remove-doc', need: 3.0,
        html: '<div class="attached-doc-preview" style="position:relative;width:120px;height:44px">'
            + '<button class="remove-doc" style="position:relative;top:0;right:0">&times;</button></div>',
    },
    { id: 'btn-primary', need: 4.5, html: '<button class="btn btn-primary">Start Chat</button>' },
    { id: 'btn-danger', need: 4.5, html: '<button class="btn btn-danger">Delete</button>' },
];

for (const theme of ['dark', 'light'] as const) {
    test(`ink on every accent-filled control clears AA — ${theme}`, async ({ page }) => {
        await boot(page, theme);
        await page.evaluate((cases) => {
            const board = document.createElement('div');
            board.id = 'ntc-board';
            // Opaque card surface at a fixed spot so the sampled plate is the
            // control's own fill and not the animated page washes behind it.
            board.style.cssText =
                'position:fixed;left:40px;top:40px;z-index:99999;display:flex;'
                + 'flex-direction:column;gap:16px;padding:20px;background:var(--surface-1);';
            for (const c of cases) {
                const slot = document.createElement('div');
                slot.dataset.case = c.id;
                slot.innerHTML = c.html;
                board.appendChild(slot);
            }
            document.body.appendChild(board);
        }, INK_CASES);
        await page.waitForTimeout(250);

        const failures: string[] = [];
        for (const c of INK_CASES) {
            const sel = `#ntc-board [data-case="${c.id}"] .${c.id}`;
            const r = await inkRatio(page, sel);
            if (r.ratio < c.need) {
                failures.push(
                    `${theme} .${c.id} — ${r.ratio.toFixed(2)}:1 (needs ${c.need}), `
                    + `ink ${r.ink} on plate ${r.plate}`,
                );
            }
        }
        expect(failures, failures.join('\n')).toEqual([]);
    });

    // -----------------------------------------------------------------------
    // WCAG 1.4.11 — a switch has to be identifiable in the state it spends most
    // of its life in. Nothing about an OFF toggle cleared 3:1 against the card:
    // dawn's track measured 1.38:1 and its white knob the same (the control was
    // carried by a drop shadow), night's track 1.05:1 (carried by the knob's
    // brightness alone). The TRACK is what says "there is a switch here", so
    // its boundary is what gets measured.
    // -----------------------------------------------------------------------
    test(`the OFF toggle track is identifiable against its card — ${theme}`, async ({ page }) => {
        await boot(page, theme);
        await page.evaluate(() => (window as unknown as { showPage?: (s: string) => void }).showPage?.('settings'));
        await page.waitForTimeout(600);

        const target = page.locator('#setting-density + .toggle-slider');
        await expect(target, 'the density toggle moved — update the selector').toHaveCount(1);
        // The Appearance card sits below the fold at 1280x800; page.screenshot
        // clips against the VIEWPORT, so an off-screen box is not sampleable.
        await target.scrollIntoViewIfNeeded();
        await page.waitForTimeout(250);
        const box = (await target.boundingBox())!;
        const borderColor = await target.evaluate((el) => getComputedStyle(el).borderTopColor);

        // Sample the CARD immediately left of the switch, clear of its own edge.
        const card = avg(await page.screenshot({
            clip: { x: Math.floor(box.x) - 40, y: Math.floor(box.y), width: 24, height: Math.floor(box.height) },
            animations: 'disabled',
        }));
        const m = borderColor.match(/rgba?\(([^)]+)\)/)!;
        const v = m[1].split(',').map(parseFloat);
        const a = v[3] === undefined ? 1 : v[3];
        const edge = {
            r: v[0] * a + card.r * (1 - a),
            g: v[1] * a + card.g * (1 - a),
            b: v[2] * a + card.b * (1 - a),
        };
        const ratio = contrast(relLum(edge.r, edge.g, edge.b), relLum(card.r, card.g, card.b));
        expect(
            ratio,
            `${theme} toggle edge ${borderColor} on card rgb(${card.r | 0},${card.g | 0},${card.b | 0}) `
            + `= ${ratio.toFixed(2)}:1`,
        ).toBeGreaterThanOrEqual(3);
    });

    // -----------------------------------------------------------------------
    // The composer's send button. The base sheet drops the whole thing to
    // opacity .5 when disabled, which in dawn composites a deep-rose plate
    // halfway to white paper and then puts a #fff glyph on it — the page's
    // primary action disappearing entirely while it is merely unavailable.
    // -----------------------------------------------------------------------
    test(`the disabled send button still shows its glyph — ${theme}`, async ({ page }) => {
        await boot(page, theme);
        await openComposer(page);
        await page.evaluate(() => {
            (document.getElementById('btn-send') as HTMLButtonElement).disabled = true;
        });
        await page.waitForTimeout(400);
        const r = await inkRatio(page, '#btn-send');
        expect(r.ratio, `disabled send glyph ${r.ink} on ${r.plate} = ${r.ratio.toFixed(2)}:1`)
            .toBeGreaterThanOrEqual(3);
    });

    // -----------------------------------------------------------------------
    // …and the state it is in for the other 99% of its life. The case above
    // forces `disabled = true` before measuring, so the REST state — the one
    // the user actually looks at — was never sampled, and it was the broken
    // one: `.btn-send` sets the brand plate at (0,1,0), but styles.css's
    // `html[data-theme="light"] .btn` is (0,2,0), so on dawn the generic button
    // surface outranked the CTA and repainted it near-white --surface-2, while
    // `html[data-theme="light"] .btn-send .ic` (0,2,1) still painted the glyph
    // #fff. 1.05:1 — the app's primary action was a blank rounded square.
    // -----------------------------------------------------------------------
    test(`the enabled send button shows its glyph — ${theme}`, async ({ page }) => {
        await boot(page, theme);
        await openComposer(page);
        await page.evaluate(() => {
            (document.getElementById('btn-send') as HTMLButtonElement).disabled = false;
        });
        await page.waitForTimeout(400);
        const r = await inkRatio(page, '#btn-send');
        expect(r.ratio, `enabled send glyph ${r.ink} on ${r.plate} = ${r.ratio.toFixed(2)}:1`)
            .toBeGreaterThanOrEqual(3);
    });
}
