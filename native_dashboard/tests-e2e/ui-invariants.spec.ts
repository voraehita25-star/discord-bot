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
// The sakura simulation, which the rest of the suite cannot see.
//
// `SEED_SETTINGS.sakuraEnabled = false` in the fixture switches the effect off
// for every other spec — deliberately, because the animated transforms make
// scrollWidth flicker and produce false horizontal-overflow failures. The side
// effect is that the entire renderer (a per-frame physics loop that writes
// transform + opacity on ~30 nodes) shipped with no automated coverage at all.
//
// These two tests turn it ON and assert the properties that do not depend on
// where any individual petal happens to be, so nothing here can flicker.
// ---------------------------------------------------------------------------
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
    await page.waitForTimeout(2500);   // let the field seed and the loop run
}

test('sakura: the field renders, moves, and stays inside its container', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (e) => errors.push(`${e.name}: ${e.message}`));
    await bootWithSakura(page);

    const first = await page.evaluate(() => {
        const petals = Array.from(
            document.getElementById('sakura-container')?.querySelectorAll<HTMLElement>('.sakura-petal') ?? [],
        );
        return {
            count: petals.length,
            withShape: petals.filter((p) => p.querySelector('svg path')).length,
            visible: petals.filter((p) => parseFloat(p.style.opacity || '0') > 0.01).length,
            // Several inline <svg> roots share one id namespace and url(#id)
            // resolves to the FIRST match, so a duplicate gradient id would
            // repaint every petal in the first petal's colour.
            gradIds: petals.map((p) => p.querySelector('linearGradient')?.id ?? '').filter(Boolean),
            transforms: petals.map((p) => p.style.transform),
            docOverflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        };
    });

    expect(first.count, 'no petals spawned').toBeGreaterThan(0);
    expect(first.withShape, 'a petal rendered without its SVG shape').toBe(first.count);
    expect(first.visible, 'petals spawned but never faded in').toBe(first.count);
    expect(new Set(first.gradIds).size, 'duplicate petal gradient ids').toBe(first.gradIds.length);
    expect(first.docOverflowX, 'petals pushed the document sideways').toBeLessThanOrEqual(1);
    expect(errors, errors.join('\n')).toEqual([]);

    // The sim writes transform every frame; a stalled loop is the failure mode
    // a static snapshot cannot tell apart from a healthy one.
    await page.waitForTimeout(700);
    const moved = await page.evaluate((before: string[]) => {
        const now = Array.from(
            document.getElementById('sakura-container')?.querySelectorAll<HTMLElement>('.sakura-petal') ?? [],
        ).map((p) => p.style.transform);
        return now.some((t, i) => t !== before[i]);
    }, first.transforms);
    expect(moved, 'the simulation is not advancing').toBe(true);
});

test('sakura: toggling off then on does not leave a second loop running', async ({ page }) => {
    await bootWithSakura(page);
    const counts = await page.evaluate(async () => {
        // Variable specifier so tsc does not try to resolve the server path.
        const appModulePath = '/app.js';
        const mod = await import(appModulePath) as { setSakuraEnabled?: (b: boolean) => void };
        const n = () =>
            document.getElementById('sakura-container')?.querySelectorAll('.sakura-petal').length ?? -1;
        mod.setSakuraEnabled?.(false);
        await new Promise((r) => setTimeout(r, 300));
        const off = n();
        mod.setSakuraEnabled?.(true);
        await new Promise((r) => setTimeout(r, 2500));
        const on = n();
        mod.setSakuraEnabled?.(true);          // idempotent re-enable
        await new Promise((r) => setTimeout(r, 2500));
        return { off, on, onTwice: n() };
    });
    expect(counts.off, 'disabling must clear the field').toBe(0);
    expect(counts.on, 're-enabling must refill it').toBeGreaterThan(0);
    // A second simulation loop over the same container would push the node
    // count past the cap the first loop enforces.
    expect(counts.onTwice, 'a second loop started on re-enable').toBe(counts.on);
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
