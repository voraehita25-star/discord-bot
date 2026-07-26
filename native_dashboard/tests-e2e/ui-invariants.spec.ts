/**
 * UI invariants found by the July-2026 dashboard audit.
 *
 * Each test here pins one defect that shipped green: the existing suite proved
 * the app boots, navigates, and passes axe, but nothing measured whether a
 * control was big enough to hit, whether two copies of the same reference
 * agreed, whether a block the code renders can ever be seen, or whether a
 * column of form fields shared an edge. Colour contrast has its own file
 * (contrast.spec.ts) because it needs pixel sampling.
 */
import { test, expect, type Page } from '@playwright/test';
import { installPopulatedMocks, waitForDashboardReady } from './_fixtures/mock-tauri';

const PAGES = ['status', 'chat', 'logs', 'database', 'settings', 'history'] as const;

async function boot(page: Page, w = 1280, h = 900): Promise<void> {
    await page.setViewportSize({ width: w, height: h });
    await installPopulatedMocks(page);
    await page.goto('/index.html');
    await waitForDashboardReady(page);
}

async function show(page: Page, name: string): Promise<void> {
    await page.evaluate(
        (p) => (window as unknown as { showPage?: (s: string) => void }).showPage?.(p),
        name,
    );
    await page.waitForTimeout(250);
}

/**
 * Freeze CSS animation + transition so a geometry assertion measures LAYOUT.
 *
 * The panels animate in with a per-card stagger, so a rect read shortly after a
 * page switch samples a frame of that entrance: the metric strip's five captions
 * came back at 281.0 / 281.2 / 281.5 / 282.1 / 283.1 — a 2.1px monotonic drift
 * left-to-right that is the stagger, not a misalignment. Colour transitions do
 * the same to a computed-colour read (a just-disabled button samples mid-fade).
 *
 * Injected as a constructed stylesheet rather than page.addStyleTag(): the
 * production CSP has no 'unsafe-inline' for style-src, so a <style> element is
 * blocked, while CSSOM mutation is exempt. Same technique as
 * visual-regression.spec.ts.
 */
async function freezeMotion(page: Page): Promise<void> {
    await page.evaluate(() => {
        const sheet = new CSSStyleSheet();
        sheet.replaceSync(
            '*, *::before, *::after { animation: none !important; transition: none !important; }',
        );
        document.adoptedStyleSheets = [...document.adoptedStyleSheets, sheet];
    });
}

// ---------------------------------------------------------------------------
// The three keyboard-shortcut surfaces are one reference in three places.
// The Settings card used to list 10 of the 12 the modal listed — and the two it
// dropped were `?` and `Esc`, `?` being the only way to reach that modal.
// ---------------------------------------------------------------------------
test('keyboard shortcuts: Settings card and the ? modal list the same thing', async ({ page }) => {
    await boot(page);
    const { settings, modal, rail } = await page.evaluate(() => {
        const read = (root: Element | null) =>
            root
                ? Array.from(root.querySelectorAll('.shortcut-item')).map((i) => ({
                      keys: (i.querySelector('kbd')?.textContent || '').trim(),
                      what: (i.querySelector('span')?.textContent || '').trim(),
                  }))
                : [];
        return {
            settings: read(document.querySelector('#page-settings .shortcuts-list')),
            modal: read(document.querySelector('#shortcuts-modal .shortcuts-list')),
            rail: Array.from(document.querySelectorAll('.nav-item .shortcut')).map(
                (k) => (k.textContent || '').trim(),
            ),
        };
    });

    expect(settings.length, 'Settings card lists no shortcuts').toBeGreaterThan(0);
    expect(settings).toEqual(modal);
    for (const k of ['?', 'Esc']) {
        expect(settings.map((s) => s.keys), `Settings card must document ${k}`).toContain(k);
    }
    // One chip format everywhere: the rail renders "Ctrl+1" (uppercased by CSS),
    // so the reference lists must not drift to a spaced "Ctrl + 1".
    for (const r of rail) expect(r).toMatch(/^Ctrl\+\w+$/);
    for (const s of settings) expect(s.keys).not.toMatch(/\s/);
});

// ---------------------------------------------------------------------------
// WCAG 2.5.8 (AA) — 24x24 minimum. axe does not implement this rule, so the
// 18x18 checkbox that arms "Delete Selected" went unnoticed.
// ---------------------------------------------------------------------------
test('pointer targets are at least 24x24 (WCAG 2.5.8)', async ({ page }) => {
    await boot(page);
    const small: string[] = [];
    for (const p of PAGES) {
        await show(page, p);
        small.push(
            ...(await page.evaluate((pg) => {
                const out: string[] = [];
                const sel = 'button, a[href], select, [role="radio"], input[type="checkbox"], input[type="range"]';
                for (const el of Array.from(document.querySelectorAll<HTMLElement>(sel))) {
                    const b = el.getBoundingClientRect();
                    if (b.width === 0 || b.height === 0) continue;
                    if (getComputedStyle(el).opacity === '0') continue;
                    if (b.width < 24 || b.height < 24) {
                        const name = (el.getAttribute('aria-label') || el.textContent || '').trim().slice(0, 40);
                        out.push(`${pg}: ${el.tagName}#${el.id || '?'}.${el.className.toString().slice(0, 30)} ` +
                                 `${Math.round(b.width)}x${Math.round(b.height)} — "${name}"`);
                    }
                }
                return out;
            }, p)),
        );
    }
    expect([...new Set(small)], small.join('\n')).toEqual([]);
});

// ---------------------------------------------------------------------------
// A row is `justify-content: space-between`, which guarantees nothing once the
// left side has grown to fill the row. With a long unbroken channel id the
// ellipsis butted straight into the count: "…12345678…1 messages".
// ---------------------------------------------------------------------------
test('database rows keep the id and the count apart, however long the id', async ({ page }) => {
    await boot(page);
    await show(page, 'database');

    const rows = await page.evaluate(() =>
        Array.from(document.querySelectorAll<HTMLElement>('.data-item')).map((row) => {
            const id = row.querySelector<HTMLElement>('.data-item-id');
            const val = row.querySelector<HTMLElement>('.data-item-value');
            if (!id || !val) return null;
            return {
                ellipsized: id.scrollWidth > id.clientWidth,
                gap: val.getBoundingClientRect().left - id.getBoundingClientRect().right,
                text: (id.textContent || '').slice(0, 20),
            };
        }).filter(Boolean),
    );

    expect(rows.length, 'populated mock rendered no data rows').toBeGreaterThan(0);
    expect(
        rows.some((r) => r!.ellipsized),
        'no row was long enough to ellipsize — this test would prove nothing',
    ).toBe(true);
    for (const r of rows) {
        expect(r!.gap, `row "${r!.text}" leaves only ${Math.round(r!.gap)}px before the count`)
            .toBeGreaterThanOrEqual(12);
    }
});

// ---------------------------------------------------------------------------
// Settings is a two-column grid, but a control dropped straight into it (the
// auto-refresh <select>) had no width cap and stretched the full 1fr — 614px
// for a menu of "1 second".."10 seconds", beside a 200px text input. Seven
// different right edges down one page.
// ---------------------------------------------------------------------------
test('settings fields share one column edge', async ({ page }) => {
    await boot(page, 1280, 900);
    await show(page, 'settings');

    const fields = await page.evaluate(() =>
        Array.from(
            document.querySelectorAll<HTMLElement>(
                '#page-settings .setting-input, #page-settings .setting-textarea, #page-settings .setting-select',
            ),
        ).map((el) => {
            const b = el.getBoundingClientRect();
            const row = el.closest('.setting-row');
            return {
                id: el.id,
                left: Math.round(b.left),
                right: Math.round(b.right),
                label: (row?.querySelector('label, .setting-label')?.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 30),
            };
        }),
    );

    expect(fields.length, 'no settings fields found').toBeGreaterThan(3);
    const lefts = [...new Set(fields.map((f) => f.left))];
    const rights = [...new Set(fields.map((f) => f.right))];
    expect(lefts, `fields start at ${lefts.length} different x:\n${JSON.stringify(fields, null, 1)}`).toHaveLength(1);
    expect(rights, `fields end at ${rights.length} different x:\n${JSON.stringify(fields, null, 1)}`).toHaveLength(1);
});

// ---------------------------------------------------------------------------
// buildMessageHtml() emits a .thinking-container only when the message carries
// saved reasoning — but the container defaulted to display:none and the only
// code that ever revealed it targets `#streaming-message`. Live streams looked
// right; every re-render from this.messages (switch conversation, reload, load
// history) silently dropped the block, with its toggle bound to something
// unclickable.
// ---------------------------------------------------------------------------
test('a stored message shows its saved Thought Process', async ({ page }) => {
    await boot(page);
    await show(page, 'chat');

    const r = await page.evaluate(() => {
        document.getElementById('chat-not-running-overlay')?.classList.remove('visible');
        document.getElementById('chat-empty')?.classList.add('hidden');
        const c = document.getElementById('chat-container');
        if (c) { c.classList.remove('hidden'); (c as HTMLElement).style.display = 'flex'; }
        const msgs = document.getElementById('chat-messages');
        if (!msgs) return null;
        // Shape copied from buildMessageHtml() (src-ts/chat/message-template.ts).
        msgs.innerHTML =
            '<div class="chat-message assistant"><div class="message-avatar">A</div>' +
            '<div class="message-wrapper">' +
            '<div class="message-header"><span class="message-name">AI</span></div>' +
            '<div class="thinking-container">' +
            '<div class="thinking-header collapsible collapsed">Thought Process</div>' +
            '<div class="thinking-content collapsed">saved reasoning</div>' +
            '</div>' +
            '<div class="message-content"><p>The answer.</p></div>' +
            '</div></div>';
        const head = msgs.querySelector<HTMLElement>('.thinking-header');
        return {
            containerDisplay: getComputedStyle(msgs.querySelector('.thinking-container')!).display,
            headerHeight: head ? head.getBoundingClientRect().height : 0,
            // collapsed by default — the header is the affordance, not the body
            contentHeight: msgs.querySelector('.thinking-content')!.getBoundingClientRect().height,
        };
    });

    expect(r).not.toBeNull();
    expect(r!.containerDisplay, 'stored thinking block is hidden').not.toBe('none');
    expect(r!.headerHeight, '"Thought Process" header has no height').toBeGreaterThan(10);
    expect(r!.contentHeight, 'body should start collapsed').toBeLessThan(2);
});

// The streaming skeleton keeps the opposite default: it ships empty and is
// revealed by showThinkingIndicator() when the first reasoning token lands.
test('the streaming skeleton still starts hidden', async ({ page }) => {
    await boot(page);
    await show(page, 'chat');
    const display = await page.evaluate(() => {
        const msgs = document.getElementById('chat-messages');
        if (!msgs) return null;
        msgs.innerHTML =
            '<div class="chat-message assistant" id="streaming-message"><div class="message-wrapper">' +
            '<div class="thinking-container"><div class="thinking-header">Thinking...</div>' +
            '<div class="thinking-content"></div></div>' +
            '<div class="message-content"><span class="streaming-text"></span></div>' +
            '</div></div>';
        return getComputedStyle(msgs.querySelector('.thinking-container')!).display;
    });
    expect(display).toBe('none');
});

// ---------------------------------------------------------------------------
// Counts agree with their noun. Every count in the UI used to be a hardcoded
// plural, so a channel with one message read "1 messages".
// ---------------------------------------------------------------------------
test('counts are not hardcoded plurals', async ({ page }) => {
    await boot(page);
    await show(page, 'database');
    const bad = await page.evaluate(() =>
        Array.from(document.querySelectorAll('.data-item-value, .conv-meta'))
            .map((e) => (e.textContent || '').trim())
            .filter((t) => /^1\s+\w+s\b/.test(t)),
    );
    expect([...new Set(bad)], 'singular count rendered with a plural noun').toEqual([]);
});

// ---------------------------------------------------------------------------
// Panels are named after what they hold. The history rail listed channels but
// was titled "AI History", which the page already said as an eyebrow and an h1
// — the name appeared four times and the rail's contents were never named.
// ---------------------------------------------------------------------------
test('the history rail is named for its contents, not the page', async ({ page }) => {
    await boot(page);
    await show(page, 'history');
    const t = await page.evaluate(() => ({
        railTitle: (document.querySelector('.history-sidebar-header h2')?.textContent || '').replace(/\s+/g, ' ').trim(),
        pageName: (document.querySelector('#page-history h1')?.textContent || '').trim(),
        placeholder: (document.querySelector('#ai-history-header')?.textContent || '').replace(/\s+/g, ' ').trim(),
    }));
    expect(t.railTitle).toBe('Channels');
    expect(t.railTitle).not.toBe(t.pageName);
    expect(t.placeholder).not.toBe(t.pageName);
});

// ---------------------------------------------------------------------------
// The chat placeholder said "(Enter to send)" with "Press Enter to send"
// restated in the hint 20px below it.
// ---------------------------------------------------------------------------
test('the chat input does not restate its own hint', async ({ page }) => {
    await boot(page);
    await show(page, 'chat');
    const { placeholder, hint } = await page.evaluate(() => ({
        placeholder: document.querySelector<HTMLTextAreaElement>('#chat-input')?.placeholder ?? '',
        hint: (document.querySelector('.chat-input-hint')?.textContent || '').replace(/\s+/g, ' ').trim(),
    }));
    expect(placeholder).not.toMatch(/enter/i);
    expect(hint).toMatch(/Enter/); // the hint still owns the how
});

// ---------------------------------------------------------------------------
// Density is app-wide spacing, so it belongs with Theme under "Appearance" —
// not under "AI Appearance", which is about the assistant's avatar.
// ---------------------------------------------------------------------------
test('every settings row sits in a card that explains it', async ({ page }) => {
    await boot(page);
    await show(page, 'settings');
    const cardOf = await page.evaluate(() => {
        const row = document.getElementById('setting-density')?.closest('.setting-row');
        return (row?.closest('.settings-card')?.querySelector('h2')?.textContent || '').replace(/\s+/g, ' ').trim();
    });
    expect(cardOf).toBe('Appearance');

    // ...and rows within one card are labelled consistently: all with a leading
    // icon or none. "Refresh Settings" shipped 4-of-6 with one.
    const mixed = await page.evaluate(() =>
        Array.from(document.querySelectorAll<HTMLElement>('#page-settings .settings-card'))
            .map((card) => {
                const rows = Array.from(card.querySelectorAll<HTMLElement>('.setting-row'))
                    .map((r) => r.querySelector('label, .setting-label'))
                    .filter((l): l is Element => !!l && !!(l.textContent || '').trim());
                if (rows.length < 2) return null;
                const withIcon = rows.filter((l) => l.querySelector('svg.ic')).length;
                if (withIcon === 0 || withIcon === rows.length) return null;
                return `${(card.querySelector('h2')?.textContent || '').trim()}: ${withIcon}/${rows.length} labels have an icon`;
            })
            .filter(Boolean),
    );
    expect(mixed, mixed.join('\n')).toEqual([]);
});

// ---------------------------------------------------------------------------
// The sakura field, which the rest of the suite cannot see.
//
// `SEED_SETTINGS.sakuraEnabled = false` in the fixture switches the effect off
// for every other spec — deliberately, because the motion makes scrollWidth
// flicker and produces false horizontal-overflow failures. The side effect is
// that the whole thing shipped with no automated coverage at all.
//
// It is now a 3D model drawn through WebGL (sakura-model.ts), so there are no
// per-petal DOM nodes left to inspect: these assert through the two canvases
// and the `sakuraDebugState()` seam instead, and only on properties that do not
// depend on where any individual petal happens to be.
// ---------------------------------------------------------------------------
interface SakuraState { running: boolean; count: number; frames: number }

async function bootWithSakura(page: Page): Promise<void> {
    await page.setViewportSize({ width: 1280, height: 800 });
    await installPopulatedMocks(page);
    // Runs after the fixture's own init script, so it wins.
    await page.addInitScript(() => {
        try {
            const raw = localStorage.getItem('dashboard-settings');
            const s = raw ? JSON.parse(raw) : {};
            s.sakuraEnabled = true;
            localStorage.setItem('dashboard-settings', JSON.stringify(s));
        } catch { /* storage blocked — the test below will report it */ }
    });
    await page.goto('/index.html');
    await waitForDashboardReady(page);
    await page.waitForTimeout(2200);   // let the field seed and the loop run
}

/** The app module's live view of the field. */
async function sakuraState(page: Page): Promise<SakuraState> {
    return page.evaluate(async () => {
        // Variable specifier so tsc does not try to resolve the server path.
        const appModulePath = '/app.js';
        const mod = await import(appModulePath) as { sakuraDebugState?: () => SakuraState };
        return mod.sakuraDebugState?.() ?? { running: false, count: -1, frames: -1 };
    });
}

test('sakura: the field renders through both depth layers and advances', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (e) => errors.push(`${e.name}: ${e.message}`));
    await bootWithSakura(page);

    const layers = await page.evaluate(() => {
        const c = document.getElementById('sakura-container');
        const canvases = Array.from(c?.querySelectorAll<HTMLCanvasElement>('canvas.sakura-gl') ?? []);
        return {
            count: canvases.length,
            // One behind `.app` (which is z-index 1) and one in front. That
            // split is the parallax: the far half is occluded by the panels.
            zIndexes: canvases.map((n) => n.style.zIndex).sort(),
            // A zero-sized backing store means resize() never ran and the field
            // is drawing into nothing.
            sized: canvases.every((n) => n.width > 0 && n.height > 0),
            // Decoration must never eat a click.
            clickThrough: canvases.every((n) => getComputedStyle(n).pointerEvents === 'none'),
        };
    });
    expect(layers.count, 'expected a far and a near canvas').toBe(2);
    expect(layers.zIndexes).toEqual(['0', '2']);
    expect(layers.sized, 'a petal canvas has no backing store').toBe(true);
    expect(layers.clickThrough, 'the petal canvases are not click-through').toBe(true);

    const first = await sakuraState(page);
    expect(first.running, 'the field reports itself stopped').toBe(true);
    expect(first.count, 'no petals in the field').toBeGreaterThan(0);

    // A stalled loop is the failure mode a single snapshot cannot tell apart
    // from a healthy one.
    await page.waitForTimeout(600);
    const second = await sakuraState(page);
    expect(second.frames, 'the simulation is not advancing').toBeGreaterThan(first.frames);
    expect(errors, errors.join('\n')).toEqual([]);
});

test('sakura: toggling off then on does not leave a second loop running', async ({ page }) => {
    await bootWithSakura(page);

    const setEnabled = (on: boolean) =>
        page.evaluate(async (v) => {
            const appModulePath = '/app.js';
            const mod = await import(appModulePath) as { setSakuraEnabled?: (b: boolean) => void };
            mod.setSakuraEnabled?.(v);
        }, on);
    const canvasCount = () =>
        page.evaluate(() =>
            document.getElementById('sakura-container')?.querySelectorAll('canvas.sakura-gl').length ?? -1);

    await setEnabled(false);
    await page.waitForTimeout(250);
    expect((await sakuraState(page)).count, 'disabling must clear the field').toBe(0);
    expect(await canvasCount(), 'disabling must tear the canvases down').toBe(0);

    await setEnabled(true);
    await page.waitForTimeout(1500);
    const on = await sakuraState(page);
    expect(on.count, 're-enabling must refill the field').toBeGreaterThan(0);
    expect(await canvasCount()).toBe(2);

    // Idempotent re-enable. A second init would build a second renderer (two
    // more canvases) and a second rAF loop — which would also double the rate
    // the frame counter climbs at, so both are checked.
    await setEnabled(true);
    const before = await sakuraState(page);
    await page.waitForTimeout(700);
    const after = await sakuraState(page);
    expect(await canvasCount(), 'a second renderer was built on re-enable').toBe(2);
    // ~60fps over 700ms is ~42 frames; a doubled loop would be ~84. 70 is clear
    // of the noise in either direction.
    expect(after.frames - before.frames, 'a second simulation loop is running').toBeLessThan(70);
    expect(after.frames).toBeGreaterThan(before.frames);
});

// ---------------------------------------------------------------------------
// The LIVE badge pulses its GLOW, not its legibility.
//
// `livePulse` used to cycle opacity 1 -> 0.7 twice a second, which took the
// label from 4.9:1 to 3.4:1 in dark and from 4.2:1 to 3.0:1 in light — under
// WCAG AA for part of every cycle, and in light theme for all of it. Nothing
// caught it: an opacity multiplier is invisible to anything reading `color`
// (axe), and contrast.spec.ts freezes infinite animations to their FIRST frame,
// where opacity is still 1. So the trough needs its own assertion, made against
// the keyframes themselves rather than a sampled pixel.
// ---------------------------------------------------------------------------
test('the LIVE badge does not animate its own opacity', async ({ page }) => {
    await boot(page);
    await show(page, 'logs');

    const found = await page.evaluate(() => {
        const el = document.getElementById('live-indicator')!;
        const name = getComputedStyle(el).animationName;
        const offenders: string[] = [];
        let matched = false;
        for (const sheet of Array.from(document.styleSheets)) {
            let rules: CSSRuleList;
            try { rules = sheet.cssRules; } catch { continue; }
            for (const rule of Array.from(rules)) {
                if (!(rule instanceof CSSKeyframesRule) || rule.name !== name) continue;
                matched = true;
                for (const kf of Array.from(rule.cssRules) as CSSKeyframeRule[]) {
                    const op = kf.style.getPropertyValue('opacity');
                    if (op && parseFloat(op) < 1) offenders.push(`${kf.keyText} { opacity: ${op} }`);
                }
            }
        }
        return {
            name,
            matched,
            offenders,
            liveOpacity: parseFloat(getComputedStyle(el).opacity),
        };
    });

    expect(found.name, 'the LIVE badge lost its animation entirely').not.toBe('none');
    expect(found.matched, `no @keyframes named "${found.name}" found`).toBe(true);
    expect(
        found.offenders,
        `livePulse dims the badge below full opacity: ${found.offenders.join(', ')}`,
    ).toEqual([]);
    expect(found.liveOpacity, 'the badge is dimmed by a static rule instead').toBe(1);
});

// ---------------------------------------------------------------------------
// v7 audit — one guard per finding from the July-2026 geometry + screenshot
// pass. Each of these shipped green: the suite proved the app boots, navigates,
// passes axe and matches its baselines, and none of it measured whether a
// numeral's descender fitted its own line box, whether two disabled buttons in
// one row looked disabled the same way, or whether the OS was drawing a control.
// ---------------------------------------------------------------------------

// `.stat-card .stat-value` clips its overflow to drive the ellipsis, and carried
// `line-height: 1.08` — under JetBrains Mono's ~1.16-1.20em glyph box. The line
// box was 1-2px shorter than the ink, so `overflow: hidden` sliced the bottom off
// every comma: "1,234,567" rendered with both commas cut flat. Visible on the
// hero tile at 1280 and on all five tiles at the 800px window floor.
test('stat numerals are not clipped by their own line box', async ({ page }) => {
    for (const [w, h] of [[1280, 900], [800, 600], [1920, 1080]] as const) {
        await boot(page, w, h);
        await freezeMotion(page);
        for (const p of ['status', 'database']) {
            await show(page, p);
            const clipped = await page.evaluate(
                (pg) =>
                    Array.from(document.querySelectorAll<HTMLElement>(`#page-${pg} .stat-value`))
                        .filter((el) => el.scrollHeight > el.clientHeight)
                        .map((el) => `${el.id}: ${el.scrollHeight - el.clientHeight}px of "${el.textContent}"`),
                p,
            );
            expect(clipped, `${w}x${h} ${p}: ${clipped.join(', ')}`).toEqual([]);
        }
    }
});

// The metric strip is one row of sibling tiles, so its captions are one line of
// type. The hero tile declared a bigger numeral, which made its value row taller;
// inside `align-content: center` that lifted the hero's whole block and MESSAGES
// sat 1.7px above the four labels beside it.
test('the metric strip shares one caption baseline', async ({ page }) => {
    // 1280 and up only: below ~1150 the grid wraps to two rows, where different
    // caption tops are correct rather than a defect.
    for (const [w, h] of [[1280, 900], [1920, 1080]] as const) {
        await boot(page, w, h);
        await freezeMotion(page);
        for (const p of ['status', 'database']) {
            await show(page, p);
            const tops = await page.evaluate(
                (pg) =>
                    Array.from(
                        document.querySelectorAll<HTMLElement>(`#page-${pg} .stat-card .stat-label`),
                    ).map((el) => +el.getBoundingClientRect().top.toFixed(1)),
                p,
            );
            expect(tops.length, `${p} rendered no stat captions`).toBeGreaterThan(3);
            const spread = Math.max(...tops) - Math.min(...tops);
            expect(spread, `${w}x${h} ${p}: caption tops ${tops.join(', ')}`).toBeLessThanOrEqual(1);
        }
    }
});

// `accent-color` tints a checkbox only once it is CHECKED, so the empty box kept
// UA chrome — which `color-scheme: dark` draws as a flat olive-grey square.
// Twelve of them down the Database list, plus one in the New Conversation modal
// and the crop dialog's zoom slider, were the only places the OS showed through
// a hand-built UI.
test('no form control is left drawing OS chrome', async ({ page }) => {
    await boot(page);
    const native: string[] = [];
    for (const p of PAGES) {
        await show(page, p);
        native.push(...(await page.evaluate((pg) => {
            const out: string[] = [];
            const sel = 'input[type="checkbox"], input[type="radio"], input[type="range"], select';
            for (const el of Array.from(document.querySelectorAll<HTMLElement>(sel))) {
                const cs = getComputedStyle(el);
                const b = el.getBoundingClientRect();
                // A control hidden behind a custom one (the settings switches clip
                // their input to 1px at opacity 0) is not showing OS chrome.
                if (b.width < 8 || b.height < 8) continue;
                if (cs.opacity === '0' || cs.visibility === 'hidden') continue;
                if (cs.appearance !== 'none') {
                    out.push(`${pg}: ${el.tagName}#${el.id || '?'}.${el.className.toString().slice(0, 28)} appearance:${cs.appearance}`);
                }
            }
            return out;
        }, p)));
    }
    // The modals are where the last two hid.
    for (const id of ['new-chat-modal', 'avatar-crop-modal']) {
        await page.evaluate((m) => {
            (window as unknown as { showPage?: (s: string) => void }).showPage?.('chat');
            document.getElementById(m)?.classList.add('active');
        }, id);
        await page.waitForTimeout(150);
        native.push(...(await page.evaluate((m) => {
            const out: string[] = [];
            const root = document.getElementById(m);
            if (!root) return out;
            for (const el of Array.from(root.querySelectorAll<HTMLElement>('input[type="checkbox"], input[type="range"], select'))) {
                const cs = getComputedStyle(el);
                const b = el.getBoundingClientRect();
                if (b.width < 8 || b.height < 8) continue;
                if (cs.opacity === '0' || cs.visibility === 'hidden') continue;
                if (cs.appearance !== 'none') out.push(`${m}: ${el.tagName}#${el.id || '?'} appearance:${cs.appearance}`);
            }
            return out;
        }, id)));
        await page.evaluate((m) => document.getElementById(m)?.classList.remove('active'), id);
    }
    expect([...new Set(native)], native.join('\n')).toEqual([]);
});

// `opacity + saturate` dims each variant's OWN treatment, which is not the same
// as giving them a shared one. In the offline control row a disabled primary
// stayed a filled slab (the most solid object in the row) while the disabled
// warning beside it faded to a near-invisible outline — and in light theme a
// disabled STOP kept full-strength red, because `html[data-theme="light"]
// .btn-danger` (0,2,1) outranked a bare `.btn:disabled` (0,2,0).
test('disabled buttons look disabled the same way, whatever variant they are', async ({ page }) => {
    for (const theme of ['dark', 'light'] as const) {
        await boot(page);
        await page.evaluate((t) => document.documentElement.setAttribute('data-theme', t), theme);
        await show(page, 'status');
        // Without this the read lands mid-fade: a just-disabled STOP sampled
        // rgba(0,0,0,0) because --danger-grad's background-COLOR was already
        // transparent and the new surface colour had not finished animating in.
        await freezeMotion(page);
        const seen = await page.evaluate(() => {
            const out: Array<{ id: string; bg: string; img: string }> = [];
            for (const id of ['btn-start', 'btn-dev', 'btn-stop', 'btn-restart']) {
                const el = document.getElementById(id) as HTMLButtonElement | null;
                if (!el) continue;
                el.disabled = true;
                const cs = getComputedStyle(el);
                out.push({ id, bg: cs.backgroundColor, img: cs.backgroundImage });
            }
            return out;
        });
        expect(seen.length, 'no control buttons found').toBe(4);
        const fills = [...new Set(seen.map((s) => `${s.bg} | ${s.img}`))];
        expect(
            fills,
            `[${theme}] four disabled buttons render ${fills.length} different fills:\n` +
                seen.map((s) => `  ${s.id}: ${s.bg} / ${s.img}`).join('\n'),
        ).toHaveLength(1);
        // ...and the shared fill is a real surface, not a gradient left showing.
        expect(seen[0].img, `[${theme}] disabled button still paints a gradient`).toBe('none');
    }
});

// Four panels put their empty state at the TOP of a 540-660px scroller and left
// the rest blank: the Log viewer's was 293px above the centre of its own frame,
// the chat rail's 229px, both History panes 155-169px.
test('a panel standing empty centres its placeholder', async ({ page }) => {
    await boot(page, 1280, 900);
    await freezeMotion(page);
    const cases: Array<[string, string, string]> = [
        ['logs', '#log-container', '.empty-state'],
        ['chat', '#conversation-list', '.no-conversations'],
        ['history', '#ai-channel-list', '.empty-state, .no-data'],
        ['history', '#ai-history-messages', '.empty-state'],
    ];
    const offenders: string[] = [];
    for (const [pageName, host, placeholder] of cases) {
        await show(page, pageName);
        const off = await page.evaluate(([h, ph]) => {
            const host = document.querySelector<HTMLElement>(h);
            const el = host?.querySelector<HTMLElement>(ph);
            if (!host || !el) return null;
            const hr = host.getBoundingClientRect();
            const er = el.getBoundingClientRect();
            if (hr.height < 260) return null;   // too short to have a centre worth hitting
            return {
                off: Math.round(er.top + er.height / 2 - (hr.top + hr.height / 2)),
                hostH: Math.round(hr.height),
            };
        }, [host, placeholder] as const);
        if (off === null) continue;
        if (Math.abs(off.off) > 40) {
            offenders.push(`${pageName} ${host}: placeholder is ${off.off}px off the centre of a ${off.hostH}px panel`);
        }
    }
    expect(offenders, offenders.join('\n')).toEqual([]);
});

// The kbd chips were content-width past their 80px min, so "Ctrl+Enter" pushed
// its description 14px right of the other eleven — in the ? modal AND in the
// Settings card, which render the same reference. The modal also needs to fit the
// 800x600 window floor without hiding the `?` row that documents how to open it.
test('the shortcut reference lines up and fits the smallest window', async ({ page }) => {
    await boot(page, 800, 600);
    await page.evaluate(() => document.getElementById('shortcuts-modal')?.classList.add('active'));
    await page.waitForTimeout(200);

    const r = await page.evaluate(() => {
        const rows = Array.from(document.querySelectorAll<HTMLElement>('#shortcuts-modal .shortcut-item'));
        const box = document.querySelector<HTMLElement>('#shortcuts-modal .modal-content')!;
        return {
            // Descriptions in the same COLUMN must share a left edge. Two columns
            // means two allowed values, so group by column index instead of
            // demanding one x for all twelve.
            lefts: rows.map((r) => {
                const s = r.querySelector('span')!.getBoundingClientRect();
                return Math.round(s.left);
            }),
            // Nothing may paint outside the panel.
            overflowing: rows
                .filter((r) => {
                    const s = r.querySelector('span')!;
                    return s.scrollWidth > s.clientWidth + 1;
                })
                .map((r) => r.querySelector('span')!.textContent),
            fits: box.scrollHeight <= box.clientHeight + 1,
            rows: rows.length,
        };
    });

    expect(r.rows, 'the shortcuts modal lists nothing').toBeGreaterThan(6);
    expect(new Set(r.lefts).size, `descriptions start at ${new Set(r.lefts).size} different x: ${r.lefts.join(', ')}`)
        .toBeLessThanOrEqual(2);
    expect(r.overflowing, `a shortcut label paints past its column: ${r.overflowing.join(', ')}`).toEqual([]);
    expect(r.fits, 'the shortcut reference does not fit the 800x600 window without scrolling').toBe(true);
});

// showToast() rendered four full-colour emoji into an app whose entire icon
// language is one monoline sprite. Emoji also inherit no colour, so a toast's
// glyph could never agree with the severity rail down its own left edge.
test('toasts use the icon sprite, not emoji', async ({ page }) => {
    await boot(page);
    const r = await page.evaluate(async () => {
        // Variable specifier so tsc does not try to resolve the server-root path
        // as a module (same trick the sakura + chart specs use for '/app.js').
        const sharedModulePath = '/shared.js';
        const mod = await import(sharedModulePath) as {
            showToast?: (m: string, o: { type: string; duration?: number }) => void;
        };
        for (const type of ['success', 'error', 'warning', 'info']) {
            mod.showToast?.(`a ${type} toast`, { type, duration: 30_000 });
        }
        await new Promise((r) => setTimeout(r, 200));
        const toasts = Array.from(document.querySelectorAll('#toast-container .toast'));
        return toasts.map((t) => ({
            cls: t.className,
            icon: (t.querySelector('.toast-icon')?.textContent || '').trim(),
            sprite: t.querySelector('.toast-icon use')?.getAttribute('href') ?? null,
            closeSprite: t.querySelector('.toast-close use')?.getAttribute('href') ?? null,
        }));
    });
    expect(r.length, 'no toasts rendered').toBe(4);
    for (const t of r) {
        expect(t.sprite, `${t.cls} has no sprite icon`).toMatch(/^#i-/);
        expect(t.closeSprite, `${t.cls} dismiss control has no sprite icon`).toMatch(/^#i-/);
        // Any leftover emoji would show up as text content beside the <svg>.
        expect(t.icon, `${t.cls} still renders a text/emoji glyph: "${t.icon}"`).toBe('');
    }
});
