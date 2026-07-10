import { test } from '@playwright/test';
import { installDashboardMocks } from './_fixtures/mock-tauri';

/**
 * Capture screenshots of every dashboard state we care about.
 *
 * These aren't asserted — they're for human review of layout/contrast/focus
 * after a UI change. Output goes to test-results/screenshots/.
 */

test.beforeEach(async ({ page }) => {
    await installDashboardMocks(page);
    await page.goto('/index.html');
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(300);
});

// Mirror VALID_PAGES in src-ts/app.ts (the real nav set). The old list had
// speculative pages (servers/connections/config/about) that never existed.
const PAGES = ['status', 'chat', 'logs', 'database', 'settings', 'history'];

for (const pageName of PAGES) {
    test(`screenshot: ${pageName} page`, async ({ page }) => {
        await page.evaluate((p) => {
            const fn = (window as unknown as { showPage?: (s: string) => void }).showPage;
            fn?.(p);
        }, pageName);
        await page.waitForTimeout(200);
        await page.screenshot({
            path: `test-results/screenshots/page-${pageName}.png`,
            fullPage: true,
        });
    });
}

test('screenshot: rename modal open', async ({ page }) => {
    // The rename modal is nested inside <section id="page-chat"> so it
    // inherits display:none when any other page is active. Switch first.
    await page.evaluate(() => {
        const fn = (window as unknown as { showPage?: (s: string) => void }).showPage;
        fn?.('chat');
        document.getElementById('rename-modal')?.classList.add('active');
        const input = document.getElementById('rename-input') as HTMLInputElement | null;
        if (input) input.value = 'My Conversation';
    });
    await page.waitForTimeout(200);
    await page.screenshot({
        path: 'test-results/screenshots/modal-rename.png',
    });
});

test('screenshot: delete confirm modal open', async ({ page }) => {
    await page.evaluate(() => {
        const fn = (window as unknown as { showPage?: (s: string) => void }).showPage;
        fn?.('chat');
        document.getElementById('delete-confirm-modal')?.classList.add('active');
    });
    await page.waitForTimeout(200);
    await page.screenshot({
        path: 'test-results/screenshots/modal-delete.png',
    });
});

test('screenshot: avatar crop modal open', async ({ page }) => {
    await page.evaluate(() => {
        document.getElementById('avatar-crop-modal')?.classList.add('active');
    });
    await page.waitForTimeout(150);
    await page.screenshot({
        path: 'test-results/screenshots/modal-avatar-crop.png',
    });
});

test('screenshot: light theme — every page', async ({ page }) => {
    // Toggle theme to light, then snapshot the most-used pages.
    await page.evaluate(() => {
        document.documentElement.setAttribute('data-theme', 'light');
    });
    for (const p of ['status', 'chat']) {
        await page.evaluate((n) => {
            const fn = (window as unknown as { showPage?: (s: string) => void }).showPage;
            fn?.(n);
        }, p);
        await page.waitForTimeout(150);
        await page.screenshot({
            path: `test-results/screenshots/light-${p}.png`,
            fullPage: true,
        });
    }
});

test('screenshot: chat with fake messages', async ({ page }) => {
    // Inject realistic-looking content into the chat container so we can see
    // how messages, avatars, and the FAB look when populated.
    await page.evaluate(() => {
        const fn = (window as unknown as { showPage?: (s: string) => void }).showPage;
        fn?.('chat');
        // Hide the bot-offline overlay so the chat is visible.
        const overlay = document.getElementById('chat-not-running-overlay');
        if (overlay) overlay.style.display = 'none';
        const empty = document.getElementById('chat-empty');
        const container = document.getElementById('chat-container');
        if (empty) empty.style.display = 'none';
        if (container) {
            container.classList.remove('hidden');
            container.style.display = 'flex';
            container.style.flexDirection = 'column';
            container.style.height = '100%';
        }
        const messages = document.getElementById('chat-messages');
        if (messages) {
            messages.innerHTML = `
                <div class="chat-message user">
                    <div class="message-avatar">👤</div>
                    <div class="message-wrapper">
                        <div class="message-header">
                            <span class="message-name">User</span>
                            <span class="message-time">12:34</span>
                        </div>
                        <div class="message-content">สวัสดี ช่วยทดสอบหน่อยได้ไหม</div>
                    </div>
                </div>
                <div class="chat-message assistant">
                    <div class="message-avatar">🤖</div>
                    <div class="message-wrapper">
                        <div class="message-header">
                            <span class="message-name">AI</span>
                            <span class="message-time">12:35</span>
                        </div>
                        <div class="message-content">
                            <p>ได้ครับ นี่คือ code block ตัวอย่าง:</p>
                            <pre><code class="language-python">def hello():\n    print("hi")</code></pre>
                            <p>และ markdown <strong>bold</strong> + <em>italic</em></p>
                        </div>
                    </div>
                </div>
            `;
        }
    });
    await page.waitForTimeout(200);
    await page.screenshot({
        path: 'test-results/screenshots/chat-with-messages.png',
        fullPage: true,
    });
});

// Populated performance charts — dark, hover tooltip, and light theme.
// Uses the seedChartHistories test seam (app.ts): the Tauri mock reports the
// bot as stopped with memory_mb 0, so real ticks would only chart a 0-line —
// and the seam stops the refresh loop so a live tick can't append a 0 sample
// onto the seeded series between seed and screenshot.
test('screenshot: performance charts seeded (dark + hover + light)', async ({ page }) => {
    const seed = async () => {
        await page.evaluate(async () => {
            // dynamic specifier via a variable so tsc (typecheck:e2e) doesn't
            // try to resolve the server-root path '/app.js' as a module
            const appModulePath = '/app.js';
            const mod = await import(appModulePath) as {
                seedChartHistories?: (m: number[], c: number[]) => void;
            };
            // memory: cold start → load spike → plateau with jitter (the real
            // shape from production); messages: the idle flat counter that
            // used to render a degenerate "214.0 … 214.0" axis.
            const memory: number[] = [];
            for (let i = 0; i < 40; i++) {
                if (i < 4) memory.push(3 + i * 2);
                else if (i < 10) memory.push(30 + (i - 4) * 33);
                else memory.push(228 + Math.sin(i * 1.7) * 4 + (i % 5));
            }
            const messages: number[] = new Array(40).fill(214);
            mod.seedChartHistories?.(memory, messages);
        });
        await page.waitForTimeout(250);
    };

    await seed();
    await page.locator('.charts-section').screenshot({
        path: 'test-results/screenshots/charts-seeded-dark.png',
    });

    await page.locator('#memory-chart').hover({ position: { x: 300, y: 90 } });
    await page.waitForTimeout(200);
    await page.locator('.charts-section').screenshot({
        path: 'test-results/screenshots/charts-hover-tooltip.png',
    });

    // Park the pointer off the canvas so pointerleave clears the crosshair —
    // otherwise the light screenshot inherits the dark run's hover tooltip.
    await page.mouse.move(5, 5);
    await page.waitForTimeout(150);

    await page.evaluate(() => document.documentElement.setAttribute('data-theme', 'light'));
    await seed();
    await page.locator('.charts-section').screenshot({
        path: 'test-results/screenshots/charts-seeded-light.png',
    });
});
