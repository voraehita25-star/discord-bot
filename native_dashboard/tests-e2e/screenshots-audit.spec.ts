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

async function setTheme(page: Page, theme: 'dark' | 'light'): Promise<void> {
    await page.evaluate((t) => document.documentElement.setAttribute('data-theme', t), theme);
    // Colour tokens transition over --dur-base (.22s); shoot the settled frame,
    // not a half-interpolated one that reads as a contrast bug that isn't there.
    await page.waitForTimeout(400);
}

/**
 * The AI-History page has no IPC command behind it — history-manager.ts drives
 * it off the WebSocket — so a populated capture means injecting the markup the
 * manager itself emits (src-ts/history-manager.ts:1738-1751).
 */
async function fillHistory(page: Page): Promise<void> {
    await page.evaluate(() => {
        const list = document.getElementById('ai-channel-list');
        if (list) {
            list.innerHTML = Array.from({ length: 6 }, (_, i) => `
                <button class="ai-channel-item${i === 1 ? ' active' : ''}" type="button">
                    <span class="ai-channel-name">#general-${i + 1}</span>
                    <span class="ai-channel-count">${[3, 128, 42, 7, 1904, 61][i]}</span>
                </button>`).join('');
        }
        const header = document.getElementById('ai-history-header');
        if (header) {
            header.innerHTML = '<h2>#general-2</h2><span class="history-header-meta">128 of 128 messages</span>';
        }
        const host = document.getElementById('ai-history-messages');
        if (host) {
            const row = (user: boolean, body: string, time: string): string => `
                <div class="history-msg ${user ? 'history-msg-user' : 'history-msg-model'}">
                    <div class="history-msg-meta">
                        <span class="history-role-badge ${user ? 'role-user' : 'role-model'}">${user ? 'User' : 'Model'}</span>
                        ${user ? '<span class="history-msg-user-id">987654321098765430</span>' : ''}
                        <span class="history-msg-time">${time}</span>
                    </div>
                    <div class="history-msg-content">${body}</div>
                </div>`;
            host.innerHTML = [
                row(true, 'What changed in the deploy last night?', '09:12'),
                row(false, 'Three things landed: the retry budget moved to the client, the log shipper switched to batched writes, and the health probe now fails closed instead of open.', '09:12'),
                row(true, 'Does the probe change affect the rolling restart?', '09:14'),
                row(false, 'Yes — a pod that cannot reach the database is now removed from the pool instead of serving errors, so a restart drains cleanly.', '09:14'),
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
