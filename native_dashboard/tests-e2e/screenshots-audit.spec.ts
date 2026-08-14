import { test, type Page } from '@playwright/test';
import { installPopulatedMocks, waitForDashboardReady } from './_fixtures/mock-tauri';

/**
 * Audit capture pass — the states screenshots.spec.ts does not reach.
 *
 * screenshots.spec.ts boots with installDashboardMocks (bot offline, no data),
 * so every page it captures is an empty state. A design review needs the
 * opposite: real content, the responsive collapse, the compact density, and the
 * modals nobody has a baseline for. Nothing here is asserted — output is for
 * human review in test-results/screenshots/ (gitignored).
 *
 * Separate file rather than an extension of screenshots.spec.ts because the
 * populated mock has to be installed BEFORE the first goto(), and that file's
 * top-level beforeEach has already navigated by the time a test body runs.
 */

const SHOT_DIR = 'test-results/screenshots';

async function boot(page: Page, w = 1280, h = 800): Promise<void> {
    await page.setViewportSize({ width: w, height: h });
    await installPopulatedMocks(page);
    await page.goto('/index.html');
    await page.waitForLoadState('domcontentloaded');
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
 * Flip the theme through the app's OWN toggle, not by writing data-theme.
 *
 * The attribute alone re-colours everything the cascade owns and nothing else —
 * and the two performance charts are `<canvas>`, painted once from the tokens
 * that were live at draw time. Setting the attribute left both canvases holding
 * their dark-theme paint, so every "light" chart shot in this audit showed a
 * white end-label ("512.8 MB") on white paper and read as a contrast bug that
 * does not exist in the app. applyTheme() calls updateCharts() precisely so the
 * real toggle does not have that hole; going through the button exercises it.
 */
async function setTheme(page: Page, theme: 'dark' | 'light'): Promise<void> {
    const current = await page.evaluate(() => document.documentElement.getAttribute('data-theme'));
    if (current !== theme) await page.locator('#theme-toggle').click();
    // Colour tokens transition over --dur-base (.22s); shoot the settled frame,
    // not a half-interpolated one that reads as a contrast bug that isn't there.
    await page.waitForTimeout(400);
}

/**
 * The AI-History page has no IPC command behind it — history-manager.ts drives
 * it off the WebSocket — so a populated capture means injecting the markup the
 * manager itself emits.
 *
 * ⚠️ This markup MUST track the real emitters, or the capture is a picture of a
 * component that does not exist. It shipped once with a `.ai-channel-item`
 * channel row — a class name no renderer writes and no stylesheet styles — so
 * the rail rendered as a run of unstyled inline chips in every audit shot ever
 * taken, and two design passes read that as the shipped design. The sources of
 * truth are `renderChannels()` (history-manager.ts, `.history-channel-item`),
 * `updateHeader()`, and `messageRowHtml()`. `zz` ⇒ if you add a class here,
 * grep it in src-ts/ first.
 */
async function fillHistory(page: Page): Promise<void> {
    await page.evaluate(() => {
        const list = document.getElementById('ai-channel-list');
        if (list) {
            // Mirrors renderChannels(): a listbox of role=option rows, each a
            // name over a meta line of count badge + relative last-active.
            list.setAttribute('role', 'listbox');
            const meta = [
                { n: 3, t: '2m ago' }, { n: 128, t: '18m ago' }, { n: 42, t: '1h ago' },
                { n: 7, t: '3h ago' }, { n: 1904, t: 'yesterday' }, { n: 61, t: '4d ago' },
            ];
            list.innerHTML = meta.map((m, i) => `
                <div class="history-channel-item${i === 1 ? ' active' : ''}"
                     id="ai-channel-opt-${i}" role="option"
                     aria-selected="${i === 1 ? 'true' : 'false'}"
                     tabindex="${i === 1 ? '0' : '-1'}"
                     data-channel-id="${i}">
                    <div class="history-channel-name">#general-${i + 1}</div>
                    <div class="history-channel-meta">
                        <span class="history-count-badge">${m.n}</span>
                        <span class="history-last-active">${m.t}</span>
                    </div>
                </div>`).join('');
        }
        const header = document.getElementById('ai-history-header');
        if (header) {
            header.classList.remove('is-placeholder');
            header.innerHTML = '<h2>#general-2</h2><span class="history-header-meta">4 of 128 messages</span>';
        }
        const host = document.getElementById('ai-history-messages');
        if (host) {
            // Mirrors messageRowHtml(), row actions included — they are
            // opacity:0 until :focus-within, so leaving them out changes the
            // row's height and the shot lies about the layout.
            const row = (user: boolean, body: string, time: string, idx: number): string => `
                <div class="history-msg ${user ? 'history-msg-user' : 'history-msg-model'}" data-idx="${idx}">
                    <div class="history-msg-meta">
                        <span class="history-role-badge ${user ? 'role-user' : 'role-model'}">${user ? 'User' : 'Model'}</span>
                        ${user ? '<span class="history-msg-user-id">987654321098765430</span>' : ''}
                        <span class="history-msg-time">${time}</span>
                        <span class="history-msg-actions">
                            <button class="history-edit-btn" data-idx="${idx}">Edit</button>
                            <button class="history-delete-btn" data-idx="${idx}">Delete</button>
                        </span>
                    </div>
                    <div class="history-msg-content">${body}</div>
                </div>`;
            host.innerHTML = [
                row(true, 'What changed in the deploy last night?', '09:12', 0),
                row(false, 'Three things landed: the retry budget moved to the client, the log shipper switched to batched writes, and the health probe now fails closed instead of open.', '09:12', 1),
                row(true, 'Does the probe change affect the rolling restart?', '09:14', 2),
                row(false, 'Yes — a pod that cannot reach the database is now removed from the pool instead of serving errors, so a restart drains cleanly.', '09:14', 3),
            ].join('');
        }
    });
    await page.waitForTimeout(200);
}

const PAGES = ['status', 'chat', 'logs', 'database', 'settings', 'history'] as const;

for (const theme of ['dark', 'light'] as const) {
    test(`populated: every page — ${theme}`, async ({ page }) => {
        await boot(page);
        await setTheme(page, theme);
        for (const name of PAGES) {
            await show(page, name);
            if (name === 'history') await fillHistory(page);
            await page.screenshot({
                path: `${SHOT_DIR}/populated-${theme}-${name}.png`,
                fullPage: true,
            });
        }
    });
}

test('modals: the three with no baseline', async ({ page }) => {
    await boot(page);
    // #new-chat-modal and #chat-files-modal are nested inside <section
    // id="page-chat">, so they inherit display:none unless chat is the active
    // page. #shortcuts-modal is a sibling of the pages and needs no switch.
    await show(page, 'chat');
    for (const id of ['new-chat-modal', 'chat-files-modal']) {
        await page.evaluate((m) => document.getElementById(m)?.classList.add('active'), id);
        await page.waitForTimeout(250);
        await page.screenshot({ path: `${SHOT_DIR}/modal-${id}.png` });
        await page.evaluate((m) => document.getElementById(m)?.classList.remove('active'), id);
    }
    await page.evaluate(() => document.getElementById('shortcuts-modal')?.classList.add('active'));
    await page.waitForTimeout(250);
    await page.screenshot({ path: `${SHOT_DIR}/modal-shortcuts-modal.png` });
});

test('responsive: the 1100px icon-rail collapse', async ({ page }) => {
    await boot(page, 1040, 800);
    for (const name of ['status', 'chat', 'database'] as const) {
        await show(page, name);
        await page.screenshot({ path: `${SHOT_DIR}/rail-collapsed-${name}.png`, fullPage: true });
    }
});

test('responsive: the 800x600 window minimum', async ({ page }) => {
    await boot(page, 800, 600);
    for (const name of PAGES) {
        await show(page, name);
        if (name === 'history') await fillHistory(page);
        await page.screenshot({ path: `${SHOT_DIR}/min-window-${name}.png`, fullPage: true });
    }
});

test('density: compact', async ({ page }) => {
    await boot(page);
    await page.evaluate(() => document.documentElement.setAttribute('data-density', 'compact'));
    await page.waitForTimeout(300);
    for (const name of ['status', 'database', 'settings'] as const) {
        await show(page, name);
        await page.screenshot({ path: `${SHOT_DIR}/density-compact-${name}.png`, fullPage: true });
    }
});

test('states: focus ring and hover on the control row', async ({ page }) => {
    await boot(page);
    await show(page, 'status');
    // Keyboard focus, not mouse — :focus-visible is what the ring hangs off.
    await page.locator('#btn-start').focus();
    await page.waitForTimeout(150);
    await page.locator('.control-card').screenshot({ path: `${SHOT_DIR}/state-focus-start.png` });
    await page.locator('#btn-restart').hover();
    await page.waitForTimeout(200);
    await page.locator('.control-card').screenshot({ path: `${SHOT_DIR}/state-hover-restart.png` });
});
