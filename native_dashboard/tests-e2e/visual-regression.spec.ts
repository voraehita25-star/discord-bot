import { test, expect } from '@playwright/test';
import { installDashboardMocks } from './_fixtures/mock-tauri';

/**
 * Visual regression baselines.
 *
 * First run with `--update-snapshots` writes the baseline PNGs under
 * tests-e2e/__screenshots__/. Subsequent runs diff against those baselines
 * and fail on pixel changes (with a small threshold for font anti-aliasing).
 *
 * To update: npm run test:e2e -- --update-snapshots
 *
 * Threshold tuning: 'maxDiffPixelRatio' lets <0.5% of pixels differ,
 * forgiving the chromium subpixel rendering jitter without missing real
 * layout regressions.
 *
 * Snapshots are platform-specific (chromium-win32 vs chromium-linux), and
 * baselines are only committed for Windows since the dashboard targets
 * Windows + WebView2 exclusively. Skip these tests on non-Windows CI runners
 * so first-run-on-Linux doesn't fail the build with "snapshot doesn't exist".
 */
test.skip(process.platform !== 'win32' && !process.env.UPDATE_VISUAL_BASELINE,
    'visual baselines committed for Windows only');

const SNAP_OPTS = {
    maxDiffPixelRatio: 0.005,
    animations: 'disabled' as const,
};

test.beforeEach(async ({ page }) => {
    await installDashboardMocks(page);
    await page.goto('/index.html');
    await page.waitForLoadState('domcontentloaded');
    // Disable transitions globally so pixel diffs don't flake on partial
    // animation states (the modalIn/sakuraFall keyframes etc).
    // page.addStyleTag() injects a <style> element, which the production CSP
    // (style-src 'self', no 'unsafe-inline') now blocks. Inject via a
    // constructed CSSStyleSheet + adoptedStyleSheets instead — CSSOM mutations
    // are exempt from CSP, so the test exercises the real strict policy.
    await page.evaluate(() => {
        const sheet = new CSSStyleSheet();
        sheet.replaceSync('*, *::before, *::after { animation: none !important; transition: none !important; }');
        document.adoptedStyleSheets = [...document.adoptedStyleSheets, sheet];
    });
    await page.waitForTimeout(300);
});

const BASELINE_PAGES = ['status', 'chat', 'logs', 'config', 'history'] as const;

for (const pageName of BASELINE_PAGES) {
    test(`visual: ${pageName} page baseline`, async ({ page }) => {
        await page.evaluate((p) => {
            const fn = (window as unknown as { showPage?: (s: string) => void }).showPage;
            fn?.(p);
        }, pageName);
        await page.waitForTimeout(200);
        await expect(page).toHaveScreenshot(`page-${pageName}.png`, SNAP_OPTS);
    });
}

test('visual: dark vs light theme — status page', async ({ page }) => {
    await page.evaluate(() => {
        const fn = (window as unknown as { showPage?: (s: string) => void }).showPage;
        fn?.('status');
    });
    await page.waitForTimeout(150);
    await expect(page).toHaveScreenshot('theme-dark-status.png', SNAP_OPTS);

    await page.evaluate(() => {
        document.documentElement.setAttribute('data-theme', 'light');
    });
    await page.waitForTimeout(150);
    await expect(page).toHaveScreenshot('theme-light-status.png', SNAP_OPTS);
});

test('visual: avatar crop modal', async ({ page }) => {
    await page.evaluate(() => {
        document.getElementById('avatar-crop-modal')?.classList.add('active');
    });
    await page.waitForTimeout(150);
    await expect(page).toHaveScreenshot('modal-avatar-crop.png', SNAP_OPTS);
});

test('visual: rename modal (chat page)', async ({ page }) => {
    await page.evaluate(() => {
        const fn = (window as unknown as { showPage?: (s: string) => void }).showPage;
        fn?.('chat');
        document.getElementById('rename-modal')?.classList.add('active');
        const input = document.getElementById('rename-input') as HTMLInputElement | null;
        if (input) input.value = 'Sample Conversation';
    });
    await page.waitForTimeout(200);
    await expect(page).toHaveScreenshot('modal-rename.png', SNAP_OPTS);
});
