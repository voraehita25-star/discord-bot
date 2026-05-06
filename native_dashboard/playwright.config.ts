import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright config for dashboard UI smoke + regression tests.
 *
 * The Tauri app uses WebView2 in production, but Playwright Chromium is close
 * enough for layout / focus / event-flow checks. The Tauri IPC bridge and the
 * Python WebSocket backend are both mocked at page-init time (see
 * tests-e2e/_fixtures/mock-tauri.ts) so the UI runs end-to-end without any
 * native side present.
 *
 * Static UI is served by python's stdlib http.server so we don't introduce a
 * second toolchain dep — every dev machine that has python (which the bot
 * already requires) can run these tests.
 */
export default defineConfig({
    testDir: './tests-e2e',
    timeout: 30_000,
    fullyParallel: false, // serialize so toast/modal screenshots don't race
    forbidOnly: !!process.env.CI,
    retries: 0,
    reporter: process.env.CI ? 'list' : [['list'], ['html', { open: 'never' }]],

    use: {
        baseURL: 'http://127.0.0.1:5173',
        screenshot: 'only-on-failure',
        trace: 'retain-on-failure',
        video: 'off',
    },

    projects: [
        {
            name: 'chromium',
            use: {
                ...devices['Desktop Chrome'],
                viewport: { width: 1280, height: 800 },
            },
        },
    ],

    webServer: {
        // -u flag = unbuffered stdout so Playwright sees ready output instantly.
        command: 'python -u -m http.server 5173 --directory ui --bind 127.0.0.1',
        url: 'http://127.0.0.1:5173/index.html',
        reuseExistingServer: !process.env.CI,
        timeout: 15_000,
        stdout: 'pipe',
        stderr: 'pipe',
    },
});
