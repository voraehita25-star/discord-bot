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

// ---------------------------------------------------------------------------
// …and the same rail with ROWS in it, which is the state it is actually for.
// The test above only ever measures the zero-data block, so it kept passing
// while the populated rail was unusable: every number in .conversation-item is
// tuned for a full-height desktop rail (12px padding + a 32px avatar + an 8px
// gutter = a 68px row), and against a ~110px list that rendered ONE
// conversation plus a second sliced through its title by the Export All footer
// — which reads as a rendering fault, not as a list that scrolls.
// ---------------------------------------------------------------------------
test('chat: the populated conversation rail shows whole rows at 800x600', async ({ page }) => {
    await boot(page, MIN_WIN);
    await show(page, 'chat');
    await page.evaluate(() => {
        const list = document.getElementById('conversation-list')!;
        list.replaceChildren();
        for (let i = 0; i < 12; i++) {
            const item = document.createElement('div');
            item.className = 'conversation-item';
            const avatar = document.createElement('img');
            avatar.className = 'conv-avatar';
            const info = document.createElement('div');
            info.className = 'conv-info';
            const title = document.createElement('span');
            title.className = 'conv-title';
            title.textContent = `Conversation ${i}`;
            const meta = document.createElement('span');
            meta.className = 'conv-meta';
            meta.textContent = '41 messages';
            info.append(title, meta);
            item.append(avatar, info);
            list.appendChild(item);
        }
    });
    await page.waitForTimeout(250);

    const r = await page.evaluate(() => {
        const list = document.getElementById('conversation-list')!;
        const row = list.querySelector<HTMLElement>('.conversation-item')!;
        const footer = document.querySelector<HTMLElement>('#page-chat .chat-sidebar-footer')!;
        const rail = document.querySelector<HTMLElement>('#page-chat .chat-sidebar')!;
        const main = document.querySelector<HTMLElement>('#page-chat .chat-main')!;
        return {
            rowH: row.getBoundingClientRect().height,
            listClientH: list.clientHeight,
            scrolls: list.scrollHeight > list.clientHeight,
            footerSpill: Math.round(
                footer.getBoundingClientRect().bottom - rail.getBoundingClientRect().bottom),
            mainH: Math.round(main.getBoundingClientRect().height),
            docOverflowY: document.documentElement.scrollHeight - document.documentElement.clientHeight,
        };
    });

    expect(r.rowH, 'no rows rendered — fixture drifted').toBeGreaterThan(0);
    // TWO whole rows. Not a round number for its own sake: one row is what the
    // rail showed before, and a list that can only ever display a single item
    // is a dropdown, not a browsable rail.
    expect(
        r.listClientH / r.rowH,
        `only ${(r.listClientH / r.rowH).toFixed(2)} rows fit (${r.rowH}px rows in a ${r.listClientH}px list)`,
    ).toBeGreaterThanOrEqual(2);
    // The rest of the rail's contract still has to hold with rows present.
    expect(r.scrolls, 'the list must own its overflow').toBe(true);
    expect(r.footerSpill, 'the rail spilled its footer past its own box').toBeLessThanOrEqual(1);
    expect(r.mainH, 'chat-main squeezed by the rail').toBeGreaterThanOrEqual(260);
    expect(r.docOverflowY, 'the page itself must not scroll').toBeLessThanOrEqual(1);
});

// ---------------------------------------------------------------------------
// A user row is row-reverse — the avatar sits on the RIGHT, and the bubble
// squares its top-right corner to point at it — but .message-header kept the
// base sheet's left alignment inside a flex:1 wrapper. So the name and time were
// pinned to the far left of a full-width row while the face they belong to was
// hundreds of px away at the other end, with the action row (already flex-end)
// right-aligned underneath. Nothing saw it: the visual baselines only render the
// empty chat page, and a misaligned caption is neither an axe violation nor an
// overflow.
// ---------------------------------------------------------------------------
test('chat: a user message caption sits with its own avatar, not across the row', async ({ page }) => {
    await boot(page, NORMAL);
    await show(page, 'chat');
    await page.evaluate(() => {
        document.getElementById('chat-not-running-overlay')?.classList.remove('visible');
        document.getElementById('chat-empty')?.classList.add('hidden');
        const c = document.getElementById('chat-container');
        if (c) { c.classList.remove('hidden'); (c as HTMLElement).style.display = 'flex'; }
        const host = document.getElementById('chat-messages')!;
        host.replaceChildren();
        for (const role of ['user', 'assistant'] as const) {
            const msg = document.createElement('div');
            msg.className = `chat-message ${role}`;
            const avatar = document.createElement('div');
            avatar.className = 'message-avatar';
            const wrapper = document.createElement('div');
            wrapper.className = 'message-wrapper';
            const header = document.createElement('div');
            header.className = 'message-header';
            const name = document.createElement('span');
            name.className = 'message-name';
            name.textContent = role === 'user' ? 'TestUser' : 'General Assistant';
            const time = document.createElement('span');
            time.className = 'message-time';
            time.textContent = '12:34';
            header.append(name, time);
            const body = document.createElement('div');
            body.className = 'message-content';
            body.textContent = 'A message long enough that its wrapper is much wider than its caption.';
            wrapper.append(header, body);
            msg.append(avatar, wrapper);
            host.appendChild(msg);
        }
    });
    await page.waitForTimeout(250);

    const r = await page.evaluate(() => {
        // .message-header spans the whole flex:1 wrapper in both roles, so the
        // question is where its CONTENT sits inside it — flush to the avatar's
        // end, or stranded at the far one.
        const read = (role: string) => {
            const msg = document.querySelector<HTMLElement>(`.chat-message.${role}`)!;
            const header = msg.querySelector<HTMLElement>('.message-header')!;
            const kids = Array.from(header.children).map((k) => k.getBoundingClientRect());
            const hb = header.getBoundingClientRect();
            return {
                headerW: hb.width,
                // Slack between the caption block and each end of its header.
                slackLeft: Math.min(...kids.map((k) => k.left)) - hb.left,
                slackRight: hb.right - Math.max(...kids.map((k) => k.right)),
            };
        };
        return { user: read('user'), assistant: read('assistant') };
    });

    // Sanity: the header really is much wider than its caption, so "which end
    // is it on" is a meaningful question at all.
    expect(r.user.headerW, 'header too narrow to distinguish the ends').toBeGreaterThan(300);

    // The user's caption belongs at the avatar's end (right). Before the fix its
    // slackRight was the near-full width of the row.
    expect(
        r.user.slackRight,
        `user caption is ${Math.round(r.user.slackRight)}px from the right edge it shares `
        + `with its avatar (header is ${Math.round(r.user.headerW)}px wide)`,
    ).toBeLessThanOrEqual(12);
    // …and the assistant's stays at its own avatar's end (left), unchanged.
    expect(
        r.assistant.slackLeft,
        `assistant caption drifted ${Math.round(r.assistant.slackLeft)}px off its left edge`,
    ).toBeLessThanOrEqual(12);
});

// ---------------------------------------------------------------------------
// Bubbles size to what is in them. .message-content is a plain block in a flex:1
// wrapper, so every bubble used to be drawn at the full width of the row — "ok"
// got the same slab as a 40-line answer. fit-content fixes it, but only if all
// four of these hold at once, and each one is a different failure:
//   * a short bubble that did not shrink  -> the bug is back
//   * a long bubble that did not fill     -> answers wrap in a narrow column
//   * a bubble that overflows itself      -> fit-content beat max-width
//   * an action row that lost its bubble  -> a toolbar floating in dead space
// Plus the streaming exemption: chunks land many times a second and a
// fit-content box would step wider on every one of them.
// ---------------------------------------------------------------------------
test('chat: message bubbles size to their content, and keep their action row', async ({ page }) => {
    await boot(page, NORMAL);
    await show(page, 'chat');
    const LONG = 'A genuinely long assistant answer whose max-content width runs '
        + 'far past anything the row can give it, so it must still fill and wrap. ';
    await page.evaluate(({ long }) => {
        document.getElementById('chat-not-running-overlay')?.classList.remove('visible');
        document.getElementById('chat-empty')?.classList.add('hidden');
        const c = document.getElementById('chat-container');
        if (c) { c.classList.remove('hidden'); (c as HTMLElement).style.display = 'flex'; }
        const host = document.getElementById('chat-messages')!;
        host.replaceChildren();
        const rows: Array<[string, string, string]> = [
            ['user', 'short', 'ok'],
            ['assistant', 'short', 'Yes.'],
            ['user', 'long', long.repeat(3)],
            ['assistant', 'long', long.repeat(3)],
            ['assistant streaming', 'streaming', 'Short answer.'],
        ];
        for (const [cls, kind, text] of rows) {
            const msg = document.createElement('div');
            msg.className = `chat-message ${cls}`;
            msg.dataset.kind = `${cls.split(' ')[0]}-${kind}`;
            const avatar = document.createElement('div');
            avatar.className = 'message-avatar';
            const wrapper = document.createElement('div');
            wrapper.className = 'message-wrapper';
            const body = document.createElement('div');
            body.className = 'message-content';
            body.textContent = text;
            const actions = document.createElement('div');
            actions.className = 'message-actions';
            for (const label of ['Copy', 'Pin', 'Edit', 'Delete']) {
                const b = document.createElement('button');
                b.className = 'copy-message-btn';
                b.textContent = label;
                actions.appendChild(b);
            }
            wrapper.append(body, actions);
            msg.append(avatar, wrapper);
            host.appendChild(msg);
        }
    }, { long: LONG });
    await page.waitForTimeout(300);

    const rows = await page.evaluate(() =>
        Array.from(document.querySelectorAll<HTMLElement>('#chat-messages .chat-message')).map((m) => {
            const wrapper = m.querySelector<HTMLElement>('.message-wrapper')!;
            const body = m.querySelector<HTMLElement>('.message-content')!;
            const actions = m.querySelector<HTMLElement>('.message-actions')!;
            const wb = wrapper.getBoundingClientRect();
            const bb = body.getBoundingClientRect();
            const ab = actions.getBoundingClientRect();
            const isUser = m.classList.contains('user');
            return {
                kind: m.dataset.kind!,
                wrapperW: Math.round(wb.width),
                bubbleW: Math.round(bb.width),
                // Distance between the action row and the bubble on the side the
                // avatar is on — the edge they are both anchored to.
                actionsOffset: Math.round(isUser
                    ? Math.abs(ab.right - bb.right)
                    : Math.abs(ab.left - bb.left)),
                selfOverflow: body.scrollWidth - body.clientWidth,
            };
        }));
    const by = (k: string) => rows.find((r) => r.kind === k)!;

    for (const k of ['user-short', 'assistant-short']) {
        const r = by(k);
        expect(r.wrapperW, `${k}: wrapper too narrow to judge`).toBeGreaterThan(120);
        expect(
            r.bubbleW,
            `${k} bubble is ${r.bubbleW}px in a ${r.wrapperW}px wrapper — it did not shrink`,
        ).toBeLessThan(r.wrapperW * 0.6);
    }
    for (const k of ['user-long', 'assistant-long']) {
        const r = by(k);
        expect(
            r.bubbleW,
            `${k} bubble is ${r.bubbleW}px in a ${r.wrapperW}px wrapper — it stopped filling`,
        ).toBeGreaterThanOrEqual(r.wrapperW - 2);
    }
    // A live response holds full width for the whole stream.
    const s = by('assistant-streaming');
    expect(
        s.bubbleW,
        `a streaming bubble must not resize per chunk (${s.bubbleW}px of ${s.wrapperW}px)`,
    ).toBeGreaterThanOrEqual(s.wrapperW - 2);

    for (const r of rows) {
        expect(r.selfOverflow, `${r.kind} bubble overflows itself by ${r.selfOverflow}px`)
            .toBeLessThanOrEqual(2);
        expect(r.actionsOffset, `${r.kind} action row sits ${r.actionsOffset}px off its bubble`)
            .toBeLessThanOrEqual(2);
    }
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
