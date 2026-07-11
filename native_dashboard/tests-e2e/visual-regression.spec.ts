import { test, expect } from '@playwright/test';
import type { Page } from '@playwright/test';
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

// The chart canvases draw a temporal axis anchored to the wall clock, so
// their pixels are nondeterministic the moment ≥2 samples land (which is a
// race against the 2s status tick — baselines happened to capture the
// "Collecting data..." placeholder). Mask them out of every snapshot; on
// pages without charts the locator resolves to hidden elements and the mask
// is a no-op.
const snapOpts = (page: Page) => ({
    ...SNAP_OPTS,
    mask: [page.locator('.chart-card canvas')],
});

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

// Mirror VALID_PAGES in src-ts/app.ts (the real nav set). 'config' was a stale
// alias for 'settings' and there is no page-config section anymore.
const BASELINE_PAGES = ['status', 'chat', 'logs', 'database', 'settings', 'history'] as const;

for (const pageName of BASELINE_PAGES) {
    test(`visual: ${pageName} page baseline`, async ({ page }) => {
        await page.evaluate((p) => {
            const fn = (window as unknown as { showPage?: (s: string) => void }).showPage;
            fn?.(p);
        }, pageName);
        await page.waitForTimeout(200);
        await expect(page).toHaveScreenshot(`page-${pageName}.png`, snapOpts(page));
    });
}

test('visual: dark vs light theme — status page', async ({ page }) => {
    await page.evaluate(() => {
        const fn = (window as unknown as { showPage?: (s: string) => void }).showPage;
        fn?.('status');
    });
    await page.waitForTimeout(150);
    await expect(page).toHaveScreenshot('theme-dark-status.png', snapOpts(page));

    await page.evaluate(() => {
        document.documentElement.setAttribute('data-theme', 'light');
    });
    await page.waitForTimeout(150);
    await expect(page).toHaveScreenshot('theme-light-status.png', snapOpts(page));
});

test('visual: avatar crop modal', async ({ page }) => {
    await page.evaluate(() => {
        document.getElementById('avatar-crop-modal')?.classList.add('active');
    });
    await page.waitForTimeout(150);
    await expect(page).toHaveScreenshot('modal-avatar-crop.png', snapOpts(page));
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
    await expect(page).toHaveScreenshot('modal-rename.png', snapOpts(page));
});
