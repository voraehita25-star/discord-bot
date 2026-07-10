import type { Page } from '@playwright/test';
import type {
    BotStatus,
    ChannelInfo,
    DbStats,
    Settings,
    StartProgress,
    UserInfo,
} from '../../src-ts/types.js';

/**
 * Return type of every Tauri command the frontend actually invokes.
 *
 * This map is the e2e mirror of the `#[tauri::command]` set in `src/main.rs`.
 * Typing it against the REAL interfaces (rather than `Record<string, unknown>`)
 * is what stops the fixture from silently drifting away from the backend: the
 * old mock returned `{cpu_percent, uptime_secs}` for `get_status` while the
 * Rust side returns `{uptime: String, mode: String}`, so `updateStats()` wrote
 * `undefined` into `#stat-uptime` / `#stat-mode`. `textContent = undefined`
 * stringifies to `''` for a nullable IDL attribute, which silently collapsed
 * both stat cards to zero height — in every screenshot baseline, forever.
 *
 * `npm run typecheck:e2e` (tsconfig.e2e.json) type-checks this file, so adding
 * a command to main.rs without teaching the mock its shape now fails the build
 * instead of producing a plausible-looking-but-wrong baseline.
 */
interface MockResponses {
    // --- bot lifecycle (bot_manager.rs) ---
    get_status: BotStatus;
    start_bot: string;
    start_dev_bot: string;
    stop_bot: string;
    restart_bot: string;
    /**
     * `waitForStart()` polls this after a Start click. Resolve as
     * already-running so the poll loop exits immediately instead of waiting out
     * the cold-start hand-off ceiling.
     */
    get_start_progress: StartProgress;

    // --- logs + paths (main.rs) ---
    get_logs: string[];
    clear_logs: string;
    get_base_path: string;
    get_logs_path: string;
    get_data_path: string;
    open_folder: null;

    // --- database (database.rs) ---
    get_db_stats: DbStats;
    get_recent_channels: ChannelInfo[];
    get_top_users: UserInfo[];
    clear_history: number;
    delete_channels_history: number;

    // --- native AI-history bridge ---
    get_dashboard_conversations_native: unknown[];
    get_dashboard_conversation_detail_native: null;

    // --- frontend error sink (shared.ts ErrorLogger) ---
    log_frontend_error: null;
    get_dashboard_errors: string[];
    clear_dashboard_errors: string;

    // --- misc ---
    get_telemetry_enabled: boolean;
    set_telemetry_enabled: null;
    show_confirm_dialog: boolean;
    get_ws_token: string;
    get_ws_endpoint: string;
}

/**
 * Settings the dashboard reads from `localStorage['dashboard-settings']`.
 *
 * NOTE: there is no `get_settings` Tauri command — `loadSettings()` in
 * shared.ts reads this localStorage key directly. The previous fixture mocked a
 * phantom `get_settings` invoke (alongside `save_config`, `get_servers`,
 * `pick_image_file`, … — none of which exist in main.rs), so its
 * `sakuraEnabled: false` never took effect and the petal animation ran through
 * every e2e test. Seeding the real key is what actually turns it off.
 */
const SEED_SETTINGS: Partial<Settings> = {
    theme: 'dark',
    userName: 'TestUser',
    // The animated transforms move position:absolute petals around enough that
    // scrollWidth flickers, creating false-positive horizontal-overflow
    // assertions in the responsive-layout test.
    sakuraEnabled: false,
};

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
    await page.addInitScript((seedSettings) => {
        // ----- Tauri invoke mock -----
        // Returns a correctly-shaped default for every command the app invokes.
        // Unknown commands resolve to null so the catch-all UI paths don't throw.
        const tauriInvoke = async <T>(cmd: string, _args?: Record<string, unknown>): Promise<T> => {
            const defaults: MockResponses = {
                // Offline bot — matches exactly what bot_manager.rs::get_status()
                // returns when the process isn't running ("-" placeholders, not "").
                get_status: { is_running: false, pid: null, uptime: '-', mode: '-', memory_mb: 0 },
                start_bot: '',
                start_dev_bot: '',
                stop_bot: '',
                restart_bot: '',
                get_start_progress: { state: 'running' },

                get_logs: [],
                clear_logs: '',
                get_base_path: 'C:\\bot',
                get_logs_path: 'C:\\bot\\logs',
                get_data_path: 'C:\\bot\\data',
                open_folder: null,

                get_db_stats: {
                    total_messages: 0,
                    active_channels: 0,
                    total_entities: 0,
                    rag_memories: 0,
                },
                get_recent_channels: [],
                get_top_users: [],
                clear_history: 0,
                delete_channels_history: 0,

                get_dashboard_conversations_native: [],
                get_dashboard_conversation_detail_native: null,

                log_frontend_error: null,
                get_dashboard_errors: [],
                clear_dashboard_errors: '',

                get_telemetry_enabled: true,
                set_telemetry_enabled: null,
                // Answer "cancel" to every confirm prompt. Destructive flows
                // (Clear All History, Clear Logs) gate on this, so `true` would
                // let a stray click in an interaction test actually fire them.
                show_confirm_dialog: false,
                get_ws_token: '',
                get_ws_endpoint: 'ws://127.0.0.1:8765/ws',
            };
            return ((defaults as unknown as Record<string, unknown>)[cmd] ?? null) as T;
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
                // Expose the most-recently-constructed instance so the
                // sendWsFrame() helper can drive an inbound frame at it. The WS
                // client (ws-client.ts) does `new WebSocket(url)` exactly once
                // per connect attempt, so this always points at the live socket.
                (window as unknown as Record<string, unknown>).__activeMockWs = this;
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

        // ----- Seed the settings localStorage key -----
        // `loadSettings()` merges this over its defaults before `initTheme()`
        // runs, so this is the ONLY hook that can pin the theme and switch the
        // sakura animation off for the suite.
        //
        // Seed ONLY when the key is absent. addInitScript re-runs on every
        // navigation, including page.reload(); unconditionally re-seeding would
        // clobber a value the app itself just persisted (e.g. the theme-persists
        // -across-reload test toggles to light, reloads, and must read light
        // back — an unconditional re-seed would reset it to dark).
        try {
            if (localStorage.getItem('dashboard-settings') === null) {
                localStorage.setItem('dashboard-settings', JSON.stringify(seedSettings));
            }
        } catch { /* no-op if storage blocked */ }
    }, SEED_SETTINGS);

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
