/**
 * Regression net for the dashboard UI audit.
 *
 * WHY THIS FILE EXISTS — the rest of the suite had two structural blind spots,
 * and every defect this file guards lived in one of them:
 *
 *   1. `installDashboardMocks` answers every Tauri command with zero/[], so the
 *      suite only ever rendered EMPTY states. Unnamed checkboxes on populated
 *      rows, scroll containers that only overflow once they have content, and
 *      rows whose long ids shove the message count off-window are all invisible
 *      that way. This file uses `installPopulatedMocks`.
 *   2. Everything else renders at 1280x800 only — but `tauri.conf.json` sets
 *      `minWidth: 800` and the sidebar collapses to an icon rail at <=1100px.
 *      The collapsed rail shipped with SIX anonymous nav buttons. This file
 *      asserts at 800x600 too.
 *
 * Keep both dimensions when extending it.
 */
import { test, expect } from '@playwright/test';
import type { Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { installDashboardMocks, installPopulatedMocks, waitForDashboardReady } from './_fixtures/mock-tauri';

// Mirror VALID_PAGES in src-ts/app.ts (the real nav set).
const PAGES = ['status', 'chat', 'logs', 'database', 'settings', 'history'] as const;

const NORMAL = { width: 1280, height: 800 };
/** The Tauri window minimum (tauri.conf.json minWidth/minHeight). */
const MIN_WIN = { width: 800, height: 600 };

async function show(page: Page, name: string): Promise<void> {
    // cast: tsconfig.e2e.json includes only src-ts/types.ts, so shared.ts's
    // Window augmentation is not in this program.
    await page.evaluate(
        (p) => (window as unknown as { showPage?: (s: string) => void }).showPage?.(p),
        name,
    );
    // Not a bootstrap race — just the .page class swap + any load* the switch
    // kicks off. Short and bounded.
    await page.waitForTimeout(250);
}

async function boot(page: Page, viewport: { width: number; height: number }): Promise<void> {
    await page.setViewportSize(viewport);
    await installPopulatedMocks(page);
    await page.goto('/index.html');
    await waitForDashboardReady(page);
}

// ---------------------------------------------------------------------------
// axe at EVERY impact level (the other a11y specs filter to critical/serious,
// or to the color-contrast rule alone) — populated, both sizes, both themes.
// ---------------------------------------------------------------------------
for (const [label, viewport] of [['1280x800', NORMAL], ['800x600', MIN_WIN]] as const) {
    for (const theme of ['dark', 'light'] as const) {
        test(`a11y: zero violations at any impact — populated, ${label}, ${theme}`, async ({ page }) => {
            await boot(page, viewport);
            await page.evaluate((t) => document.documentElement.setAttribute('data-theme', t), theme);
            const violations: string[] = [];
            for (const p of PAGES) {
                await show(page, p);
                const result = await new AxeBuilder({ page })
                    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'best-practice'])
                    .analyze();
                for (const v of result.violations) {
                    violations.push(
                        `[${label}/${theme}/${p}] ${v.impact} ${v.id}: ${v.help}\n` +
                        v.nodes.slice(0, 4).map((n) => `      -> ${n.target.join(' ')}`).join('\n'),
                    );
                }
            }
            expect(violations, violations.join('\n')).toEqual([]);
        });
    }
}

// ---------------------------------------------------------------------------
// The collapsed icon rail (<=1100px) must not strip the nav's accessible name.
// ---------------------------------------------------------------------------
test('nav: every button keeps an accessible name + tooltip across the collapse breakpoint', async ({ page }) => {
    await installDashboardMocks(page);
    await page.goto('/index.html');
    await waitForDashboardReady(page);

    // 1280 = expanded rail; 1100 and below = collapsed (label span display:none).
    for (const width of [1280, 1101, 1100, 1000, 900, 800]) {
        await page.setViewportSize({ width, height: 700 });
        const buttons = page.locator('.nav-item');
        await expect(buttons).toHaveCount(6);

        for (const button of await buttons.all()) {
            const dataPage = await button.getAttribute('data-page');
            // aria-label, not innerText: the visible label is hidden in the rail.
            const name = await button.getAttribute('aria-label');
            expect(name, `nav [${dataPage}] has no aria-label at ${width}px`).toBeTruthy();
            // title supplies the hover tooltip a mouse user needs on an icon.
            const tooltip = await button.getAttribute('title');
            expect(tooltip, `nav [${dataPage}] has no title at ${width}px`).toBeTruthy();
        }
    }
});

test('sidebar footer: status text stays in the a11y tree when the rail collapses', async ({ page }) => {
    await installDashboardMocks(page);
    await page.goto('/index.html');
    await waitForDashboardReady(page);
    await page.setViewportSize({ width: 800, height: 600 });

    // #status-badge is an aria-live region; display:none on its text would pull
    // it out of the a11y tree and silence the Online/Offline announcement.
    const badge = page.locator('#status-badge');
    await expect(badge).toHaveAttribute('aria-live', 'polite');
    await expect(badge).toHaveAttribute('role', 'status');
    const display = await page.locator('#status-badge .status-text')
        .evaluate((el) => getComputedStyle(el).display);
    expect(display, '.status-text must be visually hidden, NOT display:none').not.toBe('none');
});

// ---------------------------------------------------------------------------
// aria-current on the FIRST paint — switchPage() maintains it, but never runs
// at boot, so the hardcoded .active item used to ship without it.
// ---------------------------------------------------------------------------
test('nav: aria-current is present before any navigation and tracks it afterwards', async ({ page }) => {
    await installDashboardMocks(page);
    await page.goto('/index.html');
    await waitForDashboardReady(page);

    const current = page.locator('.nav-item[aria-current="page"]');
    await expect(current).toHaveCount(1);
    await expect(current).toHaveAttribute('data-page', 'status');

    await show(page, 'logs');
    await expect(current).toHaveCount(1);
    await expect(current).toHaveAttribute('data-page', 'logs');
});

// ---------------------------------------------------------------------------
// Sidebar order must match the Ctrl+N numbering it advertises (it read 1,2,3,4,6,5).
// ---------------------------------------------------------------------------
test('nav: DOM order matches the advertised shortcuts, and each one navigates', async ({ page }) => {
    await installDashboardMocks(page);
    await page.goto('/index.html');
    await waitForDashboardReady(page);

    const rows = await page.locator('.nav-item').evaluateAll((els) =>
        els.map((el) => ({
            page: (el as HTMLElement).dataset.page,
            kbd: el.querySelector('kbd')?.textContent?.trim(),
        })),
    );
    expect(rows.map((r) => r.kbd)).toEqual(
        ['Ctrl+1', 'Ctrl+2', 'Ctrl+3', 'Ctrl+4', 'Ctrl+5', 'Ctrl+6'],
    );

    // The label is only true if the chord actually goes there.
    for (const [i, row] of rows.entries()) {
        await page.keyboard.press(`Control+${i + 1}`);
        await expect(
            page.locator(`#page-${row.page}`),
            `Ctrl+${i + 1} should open ${row.page}`,
        ).toHaveClass(/active/);
    }
});

// ---------------------------------------------------------------------------
// Populated rows must not push content off the window.
// ---------------------------------------------------------------------------
for (const [label, viewport] of [['1280x800', NORMAL], ['800x600', MIN_WIN]] as const) {
    test(`database: long ids never push a row's count off-window (${label})`, async ({ page }) => {
        await boot(page, viewport);
        await show(page, 'database');

        const problems = await page.evaluate(() => {
            const out: string[] = [];
            const rows = document.querySelectorAll<HTMLElement>('#channels-list *, #users-list *');
            for (const el of Array.from(rows)) {
                const r = el.getBoundingClientRect();
                if (r.width > 0 && r.right > window.innerWidth + 2) {
                    out.push(`${el.className || el.tagName} extends to ${Math.round(r.right)} (viewport ${window.innerWidth})`);
                }
            }
            // and the count must still sit inside its own row
            for (const row of Array.from(document.querySelectorAll<HTMLElement>('#channels-list .data-item'))) {
                const value = row.querySelector<HTMLElement>('.data-item-value');
                if (!value) continue;
                const vr = value.getBoundingClientRect();
                const rr = row.getBoundingClientRect();
                if (vr.width === 0) out.push('.data-item-value collapsed to zero width');
                else if (vr.right > rr.right + 2) out.push(`.data-item-value overflows its row by ${Math.round(vr.right - rr.right)}px`);
            }
            return Array.from(new Set(out));
        });
        expect(problems, problems.join('\n')).toEqual([]);
    });
}

// ---------------------------------------------------------------------------
// AI History at the window minimum: content must be reachable, not clipped away.
// ---------------------------------------------------------------------------
test('history: content is fully reachable at the 800x600 window minimum', async ({ page }) => {
    await boot(page, MIN_WIN);
    await show(page, 'history');

    const result = await page.evaluate(() => {
        const content = document.querySelector<HTMLElement>('.content')!;
        const before = { scrollH: content.scrollHeight, clientH: content.clientHeight };
        content.scrollTop = content.scrollHeight;
        const undo = document.getElementById('ai-history-undo')!.getBoundingClientRect();
        // every empty state must be fully rendered, not sliced through
        const clipped: string[] = [];
        for (const es of Array.from(document.querySelectorAll<HTMLElement>('#page-history .empty-state'))) {
            const pane = es.parentElement!;
            if (es.scrollHeight > pane.clientHeight + 2 && getComputedStyle(pane).overflowY === 'hidden') {
                clipped.push(`${pane.id || pane.className}: needs ${es.scrollHeight}px, has ${pane.clientHeight}px, overflow hidden`);
            }
        }
        return {
            ...before,
            scrolledTo: content.scrollTop,
            undoReachable: undo.top >= 0 && undo.bottom <= window.innerHeight + 1,
            clipped,
        };
    });

    // The page is taller than the viewport at this size — that is the fix (it
    // used to be pinned to height:100% and crush both panes instead).
    expect(result.scrollH).toBeGreaterThan(result.clientH);
    expect(result.scrolledTo, 'overflow must be scrollable').toBeGreaterThan(0);
    expect(result.undoReachable, 'Undo must be reachable by scrolling').toBe(true);
    expect(result.clipped, result.clipped.join('\n')).toEqual([]);
});

// ---------------------------------------------------------------------------
// AI Chat at the window minimum. The stacked-and-short fix was scoped to
// #page-history on the reading that chat "already lays out correctly at this
// size" — it did not. `.chat-sidebar` capped at 38vh is 228px here, the rail's
// own chrome took ~186px of it, and #conversation-list was left 42px to show a
// 111px zero-data block: both its heading and its hint sat below the fold.
// Nothing in the suite saw it, because a vertically crushed panel still has no
// horizontal overflow and still passes axe.
// ---------------------------------------------------------------------------
test('chat: the conversation rail is usable at the 800x600 window minimum', async ({ page }) => {
    await boot(page, MIN_WIN);
    await show(page, 'chat');

    const r = await page.evaluate(() => {
        const q = (sel: string) => document.querySelector<HTMLElement>(sel);
        const list = q('#conversation-list')!;
        const rail = q('#page-chat .chat-sidebar')!;
        const main = q('#page-chat .chat-main')!;
        const zero = q('#conversation-list .no-conversations');
        return {
            listClientH: list.clientHeight,
            zeroH: zero ? zero.getBoundingClientRect().height : 0,
            railSelfOverflow: rail.scrollHeight - rail.clientHeight,
            mainH: Math.round(main.getBoundingClientRect().height),
        };
    });

    // The zero-data block must FIT the list, not be sliced by it.
    expect(r.zeroH, 'no zero-data block to measure — fixture changed').toBeGreaterThan(0);
    expect(
        r.zeroH,
        `zero-data block is ${r.zeroH}px inside a ${r.listClientH}px list`,
    ).toBeLessThanOrEqual(r.listClientH);
    // The rail must not overflow its own cap either.
    expect(r.railSelfOverflow, 'chat rail overflows its own max-height').toBeLessThanOrEqual(2);
    // …and it must not win the split at .chat-main's expense.
    expect(r.mainH, 'chat-main squeezed by the rail').toBeGreaterThanOrEqual(260);
});

test('chat: the composer stays pinned at 800x600 with a conversation open', async ({ page }) => {
    await boot(page, MIN_WIN);
    await show(page, 'chat');
    // Reveal the live conversation surface (the overlay + .hidden gating is not
    // what this test is about) and fill it past the message viewport.
    await page.evaluate(() => {
        document.getElementById('chat-not-running-overlay')?.classList.remove('visible');
        document.getElementById('chat-empty')?.classList.add('hidden');
        const c = document.getElementById('chat-container');
        if (c) { c.classList.remove('hidden'); c.style.display = 'flex'; }
        const m = document.getElementById('chat-messages');
        if (m) {
            for (let i = 0; i < 30; i++) {
                const d = document.createElement('div');
                d.className = 'chat-message user';
                d.textContent = `message ${i}`;
                m.appendChild(d);
            }
        }
    });
    await page.waitForTimeout(300);

    const r = await page.evaluate(() => {
        const input = document.getElementById('chat-input')!.getBoundingClientRect();
        const messages = document.getElementById('chat-messages')!;
        const rail = document.querySelector<HTMLElement>('#page-chat .chat-sidebar')!;
        const footer = document.querySelector<HTMLElement>('#page-chat .chat-sidebar-footer')!;
        return {
            inputInView: input.top >= 0 && input.bottom <= window.innerHeight + 1,
            inputH: Math.round(input.height),
            messagesScrolls: messages.scrollHeight > messages.clientHeight,
            messagesClientH: messages.clientHeight,
            docOverflowY: document.documentElement.scrollHeight - document.documentElement.clientHeight,
            // The rail shrinks once a conversation is open; .chat-sidebar does
            // not clip, so anything it cannot fit spills over the conversation
            // header below it rather than scrolling.
            footerSpill: Math.round(
                footer.getBoundingClientRect().bottom - rail.getBoundingClientRect().bottom),
        };
    });

    // The height model that the #page-history fix deliberately did NOT apply
    // here: the composer stays put and only .chat-messages scrolls.
    expect(r.inputInView, 'composer scrolled out of the window').toBe(true);
    expect(r.messagesScrolls, 'the message list must own the overflow').toBe(true);
    expect(r.docOverflowY, 'the page itself must not scroll').toBeLessThanOrEqual(1);
    // 96px ≈ two messages. The floor is set from the two states this pins:
    // the header (130px) + composer (178px) chrome used to leave 62px here,
    // and compacting both — plus letting the rail shrink once a conversation
    // is open — takes it to ~130px. A regression in either direction lands
    // back near 62 and fails; ordinary font/spacing drift does not.
    expect(r.messagesClientH, 'message viewport crushed').toBeGreaterThanOrEqual(96);
    expect(r.footerSpill, 'the rail spilled its footer over the conversation header')
        .toBeLessThanOrEqual(1);
});

test('history: both scroll containers are keyboard-focusable', async ({ page }) => {
    await boot(page, MIN_WIN);
    await show(page, 'history');
    // A scrollable region that cannot take focus cannot be scrolled by keyboard.
    for (const id of ['ai-channel-list', 'ai-history-messages']) {
        await expect(page.locator(`#${id}`)).toHaveAttribute('tabindex', '0');
    }
});

// ---------------------------------------------------------------------------
// The LIVE badge must not claim "live" after Pause stops the poll.
// ---------------------------------------------------------------------------
test('logs: LIVE badge reflects the real poll state', async ({ page }) => {
    await boot(page, NORMAL);
    await show(page, 'logs');

    const readBadge = () => page.locator('#live-indicator').evaluate((el) => ({
        text: (el as HTMLElement).innerText.trim(),
        paused: el.classList.contains('paused'),
        animation: getComputedStyle(el).animationName,
    }));

    const live = await readBadge();
    expect(live.text).toContain('LIVE');
    expect(live.paused).toBe(false);

    // Pause genuinely stops the poll (not just the scroll), so the badge must follow.
    await page.locator('#btn-auto-scroll').click();
    await expect.poll(async () => (await readBadge()).text).toContain('PAUSED');
    const paused = await readBadge();
    expect(paused.paused).toBe(true);
    expect(paused.animation, 'the pulse must stop when paused').toBe('none');

    // ...and back
    await page.locator('#btn-auto-scroll').click();
    await expect.poll(async () => (await readBadge()).text).toContain('LIVE');
});

// ---------------------------------------------------------------------------
// The chat page deliberately hides its title bar — but must keep its <h1>.
// ---------------------------------------------------------------------------
test('chat: page title bar is visually hidden yet still exposes an h1', async ({ page }) => {
    await boot(page, NORMAL);
    await show(page, 'chat');

    const bar = page.locator('#page-chat .page-title-bar');
    // display:none would strip the h1 from the a11y tree (page-has-heading-one).
    expect(await bar.evaluate((el) => getComputedStyle(el).display)).not.toBe('none');
    // ...while taking no meaningful layout space, so the flex column keeps it all.
    const box = await bar.boundingBox();
    expect(box === null || box.height <= 2).toBe(true);
    // The heading is present in the accessibility tree.
    await expect(page.locator('#page-chat .page-title-bar h1')).toHaveCount(1);
});

// ---------------------------------------------------------------------------
// Language: the document must declare the language it is actually written in.
// ---------------------------------------------------------------------------
test('document language matches its content, with Korean strings marked', async ({ page }) => {
    await installDashboardMocks(page);
    await page.goto('/index.html');
    await waitForDashboardReady(page);

    // The visible UI is English; a lang="ko" root made a Korean TTS voice
    // mispronounce all of it.
    expect(await page.evaluate(() => document.documentElement.lang)).toBe('en');
    // Every Korean string still carries its own lang so the voice switches.
    const unmarked = await page.evaluate(() => {
        const HANGUL = /[가-힣]/;
        const bad: string[] = [];
        const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
        for (let n = walk.nextNode(); n; n = walk.nextNode()) {
            const text = (n.textContent ?? '').trim();
            if (!text || !HANGUL.test(text)) continue;
            const el = n.parentElement;
            if (!el || !el.closest('[lang="ko"]')) bad.push(text.slice(0, 40));
        }
        return bad;
    });
    expect(unmarked, `Korean text with no lang="ko" ancestor: ${unmarked.join(' | ')}`).toEqual([]);

    // The walk above only sees TEXT nodes, so it stepped straight past the
    // sidebar's aria-label="주 메뉴" — a Korean accessible name in a lang="en"
    // document, and the FIRST thing announced on entering the landmark. Unlike
    // the skip link and the logo, an attribute value cannot carry lang="ko", so
    // there is no way to mark it: the accessible name has to be English.
    // (Korean visible branding is unaffected — that is what the walk covers.)
    const koreanNames = await page.evaluate(() => {
        const HANGUL = /[가-힣]/;
        const ATTRS = ['aria-label', 'title', 'placeholder', 'alt', 'aria-description'];
        const bad: string[] = [];
        for (const el of Array.from(document.querySelectorAll('*'))) {
            for (const a of ATTRS) {
                const v = el.getAttribute(a);
                if (v && HANGUL.test(v)) bad.push(`${el.tagName.toLowerCase()}[${a}="${v}"]`);
            }
        }
        return bad;
    });
    expect(koreanNames, `Korean in an accessible name, which cannot be lang-marked: ${koreanNames.join(' | ')}`)
        .toEqual([]);
});
