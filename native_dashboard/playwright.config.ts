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
    // NOTE: `fullyParallel: false` serializes cases WITHIN a file; spec files
    // still run concurrently across workers. Every spec used to wait a FIXED
    // ~250ms after goto() for the deferred ES-module bootstrap, and under that
    // cross-file CPU load the wait was regularly too short — a click landed
    // before initNavigation() had bound its handler, or axe scored a
    // half-rendered DOM. Cases that passed in isolation failed in the suite.
    //
    // The specs now await `window.__dashboardReady` (see waitForDashboardReady()
    // in _fixtures/mock-tauri.ts), which app.ts sets synchronously as the last
    // statement of its DOMContentLoaded handler. That removed the whole class of
    // load-induced failures. The retry budget is kept as a backstop for genuine
    // environment noise; a real regression still fails every attempt.
    retries: process.env.CI ? 2 : 1,
    reporter: process.env.CI ? 'list' : [['list'], ['html', { open: 'never' }]],

    use: {
        baseURL: 'http://127.0.0.1:5173',
        screenshot: 'only-on-failure',
        trace: 'retain-on-failure',
        video: 'off',
        // Pin the OS color-scheme to dark for the whole suite. The app now
        // honors prefers-color-scheme on first run (A11Y-05), so without this
        // pin the suite would inherit Playwright's default 'light' and render
        // every "dark" baseline as light. Dark is this Midnight app's canonical
        // surface; the OS-light first-run branch is covered by app.test.ts.
        colorScheme: 'dark',
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
        //
        // scripts/serve-ui.py, NOT a bare `-m http.server`: the stdlib CLI form
        // listens with a backlog of 5, which 8 Playwright workers each requesting
        // ~30 assets on page boot overflow instantly — the OS then REFUSES
        // connections and a page silently comes up missing a vendor script
        // (net::ERR_CONNECTION_REFUSED), never finishing bootstrap. That was the
        // true source of this suite's flakiness. The script is still stdlib-only;
        // it just raises the backlog and quiets the per-request logging.
        command: `${process.env.PYTHON ?? 'python'} -u scripts/serve-ui.py 5173 ui`,
        url: 'http://127.0.0.1:5173/index.html',
        // Never reuse an already-running server by default: 5173 is the Vite
        // default, so a stale http.server / another project's Vite could be
        // reused and serve stale ui/ assets (which the test:e2e `npm run build`
        // step just regenerated). Opt in to reuse for speed during local dev
        // by setting PW_REUSE=1 (and not on CI, which always wants a fresh
        // server). PLAYWRIGHT_NO_REUSE_SERVER is still honored as a kill switch.
        reuseExistingServer:
            !process.env.CI &&
            !!process.env.PW_REUSE &&
            !process.env.PLAYWRIGHT_NO_REUSE_SERVER,
        timeout: 15_000,
        stdout: 'pipe',
        stderr: 'pipe',
    },
});
