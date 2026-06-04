import type { Page } from '@playwright/test';

/**
 * Inject a mock `window.__TAURI__` IPC bridge + a fake WebSocket before
 * any page script runs. Without these the dashboard JS would either crash on
 * the missing bridge or sit forever waiting for a backend.
 *
 * The mocks are intentionally shallow — they return enough of the right shape
 * to let the UI render and accept user input. Tests that need richer
 * behavior can layer additional invoke handlers via page.evaluate().
 */
export async function installDashboardMocks(page: Page): Promise<void> {
    await page.addInitScript(() => {
        // ----- Tauri invoke mock -----
        // Returns sensible defaults for every command the app calls during
        // bootstrap (settings load, theme detection, etc). Unknown commands
        // resolve to null so the catch-all UI paths don't throw.
        const tauriInvoke = async <T>(cmd: string, _args?: Record<string, unknown>): Promise<T> => {
            const defaults: Record<string, unknown> = {
                get_settings: {
                    theme: 'dark',
                    aiAvatar: '',
                    userName: 'TestUser',
                    autoConnect: false,
                    enableAnimations: true,
                    // Disable the sakura petal animation in tests — the
                    // animated transforms move position:absolute petals
                    // around enough that scrollWidth flickers, creating
                    // false-positive horizontal-overflow assertions.
                    sakuraEnabled: false,
                    aiProvider: 'claude',
                },
                save_settings: null,
                get_config: {},
                save_config: null,
                load_avatar_file: '',
                save_avatar_file: '',
                pick_image_file: null,
                read_image_as_base64: '',
                // Stats endpoints — return shapes that match the TS types so
                // the dashboard's polling doesn't blow up at bootstrap.
                get_status: {
                    is_running: false,
                    cpu_percent: 0,
                    memory_mb: 0,
                    uptime_secs: 0,
                    pid: null,
                },
                get_db_stats: {
                    total_messages: 0,
                    active_channels: 0,
                    total_entities: 0,
                    total_facts: 0,
                    rag_index_size: 0,
                },
                get_servers: [],
                get_logs: [],
                start_bot: null,
                // waitForStart() polls this after a Start click. Resolve as
                // already-running so the poll loop exits immediately instead of
                // waiting out the cold-start hand-off ceiling.
                get_start_progress: { state: 'running' },
                stop_bot: null,
                restart_bot: null,
            };
            return (defaults[cmd] ?? null) as T;
        };
        (window as unknown as Record<string, unknown>).__TAURI__ = {
            core: { invoke: tauriInvoke },
        };
        (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__ = {
            invoke: tauriInvoke,
        };

        // ----- WebSocket mock -----
        // Captures send() calls in a global so tests can assert what the UI
        // emitted. The real bot's WS frames are never simulated unless a test
        // explicitly dispatches one via window.__mockWsRecv(frame).
        class MockWebSocket extends EventTarget {
            static CONNECTING = 0;
            static OPEN = 1;
            static CLOSING = 2;
            static CLOSED = 3;

            readyState = 0;
            url: string;
            onopen: ((ev: Event) => void) | null = null;
            onclose: ((ev: CloseEvent) => void) | null = null;
            onerror: ((ev: Event) => void) | null = null;
            onmessage: ((ev: MessageEvent) => void) | null = null;
            sentFrames: string[] = [];

            constructor(url: string) {
                super();
                this.url = url;
                // Fire 'open' on next tick so listeners attached after `new`
                // still hear it (matches real WebSocket timing).
                queueMicrotask(() => {
                    this.readyState = 1;
                    const ev = new Event('open');
                    this.onopen?.(ev);
                    this.dispatchEvent(ev);
                });
            }

            send(data: string): void {
                this.sentFrames.push(data);
                ((window as unknown as Record<string, unknown>).__mockWsLastSent as { frames: string[] }).frames.push(data);
            }

            close(): void {
                this.readyState = 3;
                const ev = new CloseEvent('close');
                this.onclose?.(ev);
                this.dispatchEvent(ev);
            }

            // Test helper: inject an inbound frame.
            recv(payload: unknown): void {
                const ev = new MessageEvent('message', {
                    data: typeof payload === 'string' ? payload : JSON.stringify(payload),
                });
                this.onmessage?.(ev);
                this.dispatchEvent(ev);
            }
        }
        (window as unknown as Record<string, unknown>).__mockWsLastSent = { frames: [] };
        (window as unknown as Record<string, unknown>).__MockWebSocket = MockWebSocket;
        (window as unknown as { WebSocket: typeof WebSocket }).WebSocket =
            MockWebSocket as unknown as typeof WebSocket;

        // ----- Stub localStorage helpers used during bootstrap -----
        // Some modules call localStorage before any user interaction. The
        // default jsdom-style storage works in chromium but we pre-seed a few
        // keys so the UI doesn't show first-launch onboarding banners.
        try {
            localStorage.setItem('dashboard_test_mode', '1');
        } catch { /* no-op if storage blocked */ }
    });

    // Collect runtime page errors instead of throwing immediately. Throwing
    // from inside the listener nukes whatever assertion is mid-flight with a
    // misleading stack trace. Each test that cares can read window.__pageErrors.
    await page.addInitScript(() => {
        const errors: string[] = [];
        (window as unknown as { __pageErrors: string[] }).__pageErrors = errors;
        window.addEventListener('error', (e) => errors.push(`error: ${e.message}`));
        window.addEventListener('unhandledrejection', (e) =>
            errors.push(`unhandled: ${String(e.reason)}`),
        );
    });
    page.on('pageerror', (err) => {
        // Forward to console so failure stacks show up in Playwright trace.
        // eslint-disable-next-line no-console
        console.error(`[pageerror] ${err.message}`);
    });
}

/** Read accumulated page errors. Empty array on a clean run. */
export async function getPageErrors(page: import('@playwright/test').Page): Promise<string[]> {
    return page.evaluate(
        () => (window as unknown as { __pageErrors?: string[] }).__pageErrors ?? [],
    );
}

/** Drive an inbound WebSocket frame from a test. */
export async function sendWsFrame(page: Page, frame: Record<string, unknown>): Promise<void> {
    await page.evaluate((f) => {
        // Find the most recent MockWebSocket instance via the WS client.
        // We recorded it at install time on window.__activeMockWs.
        const ws = (window as unknown as { __activeMockWs?: { recv: (p: unknown) => void } })
            .__activeMockWs;
        if (ws) ws.recv(f);
    }, frame);
}

/** Inspect frames the UI has sent to the (mocked) backend. */
export async function getSentFrames(page: Page): Promise<string[]> {
    return page.evaluate(() => {
        return ((window as unknown as { __mockWsLastSent?: { frames: string[] } })
            .__mockWsLastSent?.frames ?? []).slice();
    });
}
