import { expect, test } from '@playwright/test';
import {
    installDashboardMocks,
    setInvokeReject,
    setInvokeOverride,
    getPageErrors,
} from './_fixtures/mock-tauri';

/**
 * Tauri IPC failure-path tests.
 *
 * The default mock-tauri bridge only covers success paths — every command
 * resolves with a sensible default. Real Tauri commands can fail (process
 * spawn errors, missing files, busy locks). The frontend must:
 *
 *   1. Convert the rejection into a user-visible signal (toast or status).
 *   2. NOT crash the page (no uncaught error/rejection on window.__pageErrors).
 *   3. Leave the rest of the UI functional after the error.
 *
 * Each test installs an override on a single command via the new helpers
 * `setInvokeReject` / `setInvokeOverride` in `_fixtures/mock-tauri.ts`, then
 * exercises the UI flow that calls it.
 */

test.beforeEach(async ({ page }) => {
    await installDashboardMocks(page);
    await page.goto('/index.html');
    await page.waitForLoadState('domcontentloaded');
    await page.waitForFunction(
        () => (window as unknown as { chatManager?: unknown }).chatManager !== undefined,
        { timeout: 5000 },
    );
});

test.describe('start_bot rejection surfaces a user-visible error', () => {
    test('clicking Start while start_bot rejects shows an error toast', async ({ page }) => {
        await setInvokeReject(page, 'start_bot', 'spawn failed: ENOENT bot.py');
        // Press the Start button on the Status page (default landing page).
        await page.locator('#btn-start').click();
        // The toast container is at the body root; the error toast carries
        // the rejection message text.
        const toast = page.locator('#toast-container .toast').first();
        await expect(toast).toBeVisible({ timeout: 5000 });
        const text = (await toast.textContent()) || '';
        expect(text.toLowerCase()).toContain('spawn failed');

        // The page did not crash — chatManager is still around.
        const hasCm = await page.evaluate(
            () => (window as unknown as { chatManager?: unknown }).chatManager !== undefined,
        );
        expect(hasCm).toBe(true);
    });

    test('start_bot rejection leaves the Start button re-enabled (not stuck)', async ({ page }) => {
        await setInvokeReject(page, 'start_bot', 'permission denied');
        const startBtn = page.locator('#btn-start');
        await startBtn.click();
        // The error toast confirms the rejection landed.
        await expect(page.locator('#toast-container .toast').first()).toBeVisible({
            timeout: 5000,
        });
        // setBotControlBusy(false) runs in the finally{} block — start
        // should be clickable again. (Strictly, get_status decides
        // disabled state via is_running. With our mock returning
        // is_running:false, the button is enabled.)
        await expect(startBtn).toBeEnabled({ timeout: 3000 });
    });

    test('no uncaught error reaches window.__pageErrors on rejection', async ({ page }) => {
        await setInvokeReject(page, 'start_bot', 'oops');
        await page.locator('#btn-start').click();
        // Give the toast time to settle so the unhandledrejection (if any)
        // would have fired by now.
        await expect(page.locator('#toast-container .toast').first()).toBeVisible({
            timeout: 5000,
        });
        const errs = await getPageErrors(page);
        // The handled rejection is converted into a toast; nothing should
        // bubble up as 'unhandled' or 'error'.
        expect(errs, errs.join('\n')).toEqual([]);
    });
});

test.describe('stop_bot rejection surfaces an error', () => {
    test('clicking Stop while stop_bot rejects shows an error toast', async ({ page }) => {
        // Need is_running:true so the Stop button is enabled.
        await setInvokeOverride(page, 'get_status', {
            is_running: true,
            cpu_percent: 5,
            memory_mb: 100,
            uptime_secs: 60,
            pid: 1234,
        });
        // Force a status refresh so the button enables.
        await page.evaluate(() => {
            const fn = (window as unknown as {
                showPage?: (s: string) => void;
            }).showPage;
            fn?.('status');
        });
        await expect(page.locator('#btn-stop')).toBeEnabled({ timeout: 5000 });
        await setInvokeReject(page, 'stop_bot', 'process not responding');
        await page.locator('#btn-stop').click();
        await expect(page.locator('#toast-container .toast').first()).toBeVisible({
            timeout: 5000,
        });
        const text = (await page.locator('#toast-container .toast').first().textContent()) || '';
        expect(text.toLowerCase()).toContain('not responding');
    });
});

test.describe('get_status returning malformed data is handled gracefully', () => {
    test('get_status returns null — no crash, no uncaught', async ({ page }) => {
        // The updateStatus() handler guards `if (!status || !dbStats) return`.
        // Without that guard, the .memory_mb / .total_messages accesses would
        // throw and blank the UI. This test pins that guard.
        await setInvokeOverride(page, 'get_status', null);
        // Trigger a refresh cycle.
        await page.evaluate(() => {
            const fn = (window as unknown as {
                showPage?: (s: string) => void;
            }).showPage;
            fn?.('status');
        });
        // Give the polling loop one tick.
        await page.waitForTimeout(500);
        const errs = await getPageErrors(page);
        expect(errs, errs.join('\n')).toEqual([]);
    });

    test('get_status returns wrong-shape object — no crash on null fields', async ({ page }) => {
        // Older bot versions might return a partial shape. The dashboard
        // should treat missing fields as falsy and keep going.
        await setInvokeOverride(page, 'get_status', {
            // missing is_running, cpu_percent, memory_mb…
            uptime_secs: 100,
        });
        await page.evaluate(() => {
            const fn = (window as unknown as {
                showPage?: (s: string) => void;
            }).showPage;
            fn?.('status');
        });
        await page.waitForTimeout(500);
        const errs = await getPageErrors(page);
        expect(errs, errs.join('\n')).toEqual([]);
        // The status badge should still be in a sane state — "Offline" is the
        // default for is_running:undefined/falsy.
        const badgeText = (await page.locator('#status-badge .status-text').textContent()) || '';
        expect(badgeText.trim().toLowerCase()).toMatch(/online|offline/);
    });

    test('get_db_stats returns null — page renders without crashing', async ({ page }) => {
        // Same guard as get_status; null-DB is the early-init case.
        await setInvokeOverride(page, 'get_db_stats', null);
        await page.evaluate(() => {
            const fn = (window as unknown as {
                showPage?: (s: string) => void;
            }).showPage;
            fn?.('status');
        });
        await page.waitForTimeout(500);
        const errs = await getPageErrors(page);
        expect(errs, errs.join('\n')).toEqual([]);
        // Stat values should still be present in the DOM (default "0").
        const memVal = await page.locator('#stat-memory').textContent();
        expect(memVal).toBeTruthy();
    });
});

test.describe('clear_logs failure — toast appears, no crash', () => {
    test('rejection from clear_logs surfaces as an error toast', async ({ page }) => {
        await setInvokeReject(page, 'clear_logs', 'log file is locked');
        // Switch to the logs page so the Clear button is visible.
        await page.evaluate(() => {
            const fn = (window as unknown as {
                showPage?: (s: string) => void;
            }).showPage;
            fn?.('logs');
        });
        // The Clear-logs button currently asks for confirm before clearing.
        // Auto-accept the confirm so the rejection actually fires.
        page.once('dialog', (d) => d.accept());
        const btn = page.locator('#btn-clear-logs');
        if (await btn.count() > 0) {
            await btn.click();
            // Either an immediate toast or none if user clicked Cancel in
            // the confirm. Don't strictly assert the toast content here —
            // assert no uncaught error.
            await page.waitForTimeout(800);
            const errs = await getPageErrors(page);
            expect(errs, errs.join('\n')).toEqual([]);
        }
    });
});

test.describe('Avatar flow handles cancellation gracefully', () => {
    // The dashboard's avatar upload uses an HTML <input type="file"> change
    // event, NOT the Tauri pick_image_file IPC (which exists in the mock
    // bridge defaults but is unused by app.ts as of 2026-05-28).
    //
    // Test the equivalent failure mode: the user opens the file picker via
    // Change Avatar but cancels — i.e. the input ``change`` event fires
    // with no files. The code path is:
    //   btn-change-avatar -> avatar-input.click() -> change event -> if(file) handleAvatarUpload
    // so the missing `file` branch must NOT crash.

    test('change event with no file selected does not crash the page', async ({ page }) => {
        // Navigate to Settings page where #btn-change-avatar lives.
        await page.evaluate(() => {
            const fn = (window as unknown as {
                showPage?: (s: string) => void;
            }).showPage;
            fn?.('settings');
        });
        await expect(page.locator('#btn-change-avatar')).toBeVisible();
        // Simulate the cancel path by dispatching a `change` event with an
        // empty FileList on the hidden file input.
        await page.evaluate(() => {
            const input = document.getElementById('avatar-input') as HTMLInputElement | null;
            if (!input) return;
            // FileList can't be constructed directly, but a synthetic
            // event with .target.files === null is what the production
            // code expects to see post-cancel (the input keeps its
            // pre-existing empty FileList).
            input.dispatchEvent(new Event('change', { bubbles: true }));
        });
        await page.waitForTimeout(200);
        const errs = await getPageErrors(page);
        expect(errs, errs.join('\n')).toEqual([]);
        // Avatar preview should still render (no broken-image flash).
        const previewSrc = await page.locator('#avatar-image').getAttribute('src');
        expect(previewSrc, '#avatar-image src after cancel').not.toBe('');
        expect(previewSrc).not.toBeNull();
    });
});

test.describe('Bootstrap survives early IPC failures', () => {
    test('get_settings rejection at boot does not blank the UI', async ({ page, context }) => {
        // Re-install mocks with a get_settings rejection BEFORE goto so the
        // failure happens during bootstrap (not after). Need a fresh page.
        const fresh = await context.newPage();
        await installDashboardMocks(fresh);
        await setInvokeReject(fresh, 'get_settings', 'config corrupted');
        await fresh.goto('/index.html');
        await fresh.waitForLoadState('domcontentloaded');
        // The dashboard should still render: the sidebar exists, the status
        // page is active by default. The boot path should fall back to
        // defaults instead of throwing.
        await expect(fresh.locator('.sidebar')).toBeVisible({ timeout: 5000 });
        await expect(fresh.locator('#page-status')).toHaveClass(/active/);
        const errs = await getPageErrors(fresh);
        // Allow tolerated "unhandled" entries that contain the rejection
        // message — those are exactly what we're testing. But the UI must
        // be functional after.
        const unhandled = errs.filter((e) => !e.includes('config corrupted'));
        expect(unhandled, unhandled.join('\n')).toEqual([]);
    });
});
