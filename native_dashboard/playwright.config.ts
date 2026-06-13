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
        // PYTHON env override lets machines whose interpreter is 'py' or a venv
        // path (e.g. when the User PATH is not inherited) run the e2e suite.
        command: `${process.env.PYTHON ?? 'python'} -u -m http.server 5173 --directory ui --bind 127.0.0.1`,
        url: 'http://127.0.0.1:5173/index.html',
        // Reuse a running dev server outside CI for speed. 5173 is the Vite
        // default, so a stale http.server / another project's Vite could be
        // reused and serve stale ui/ assets; set PLAYWRIGHT_NO_REUSE_SERVER=1
        // to force Playwright to launch its own server.
        reuseExistingServer: !process.env.CI && !process.env.PLAYWRIGHT_NO_REUSE_SERVER,
        timeout: 15_000,
        stdout: 'pipe',
        stderr: 'pipe',
    },
});
