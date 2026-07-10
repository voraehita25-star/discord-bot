/**
 * Tests for chat/ws-client.ts — the dashboard WebSocket lifecycle wrapper.
 *
 * Two surfaces are exercised without ever touching a real network socket:
 *
 *   1. onmessage hardening — the frame guard that protects JSON.parse():
 *        - non-string frames (Blob / ArrayBuffer) are dropped
 *        - oversized strings (> MAX_MESSAGE_LENGTH code units) are dropped
 *        - __proto__/constructor/prototype keys can't pollute Object.prototype
 *        - null / array / string JSON values are dropped (frontend needs an object)
 *   2. reconnect backoff — the exponential-backoff scheduler caps at
 *      maxReconnectAttempts fast retries then settles on the 30s interval.
 *   3. disconnect() vs. an in-flight connect() — tearing down while the async
 *      config fetch is pending must NOT resurrect a socket afterwards.
 *
 * The global WebSocket is replaced with a controllable fake that records
 * instances and lets each test fire onopen/onmessage/onclose by hand. shared.ts
 * (invoke/showToast/errorLogger) is mocked so no Tauri IPC is needed.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

// invoke resolves the WS token + endpoint; default to empty so connect() falls
// straight through to the default localhost endpoint. Individual tests can
// override mockInvoke per case. (Names start with `mock` so vitest permits
// referencing them inside the hoisted vi.mock factory below.)
const mockInvoke = vi.fn<(cmd: string) => Promise<string>>().mockResolvedValue('');
const mockShowToast = vi.fn();
const mockErrorLog = vi.fn();

vi.mock('../shared.js', () => ({
    invoke: (cmd: string) => mockInvoke(cmd),
    showToast: (...args: unknown[]) => mockShowToast(...args),
    errorLogger: { log: (...args: unknown[]) => mockErrorLog(...args) },
}));

// Late import — AFTER the mock is registered.
let WebSocketClient: typeof import('./ws-client.js').WebSocketClient;
type WsClientCallbacks = import('./ws-client.js').WsClientCallbacks;

/** Minimal stand-in for the browser WebSocket. Records every constructed
 *  instance so tests can drive lifecycle events manually. */
class FakeWebSocket {
    static readonly CONNECTING = 0;
    static readonly OPEN = 1;
    static readonly CLOSING = 2;
    static readonly CLOSED = 3;

    static instances: FakeWebSocket[] = [];

    readyState: number = FakeWebSocket.CONNECTING;
    sent: string[] = [];
    closed = false;

    onopen: ((ev: unknown) => void) | null = null;
    onclose: ((ev: { code: number; reason: string }) => void) | null = null;
    onerror: ((ev: unknown) => void) | null = null;
    onmessage: ((ev: { data: unknown }) => void) | null = null;

    constructor(public readonly url: string) {
        FakeWebSocket.instances.push(this);
    }

    send(data: string): void {
        this.sent.push(data);
    }

    close(): void {
        this.closed = true;
        this.readyState = FakeWebSocket.CLOSED;
    }

    // --- test driver helpers ---
    fireOpen(): void {
        this.readyState = FakeWebSocket.OPEN;
        this.onopen?.({});
    }
    fireMessage(data: unknown): void {
        this.onmessage?.({ data });
    }
    fireClose(code = 1006, reason = ''): void {
        this.readyState = FakeWebSocket.CLOSED;
        this.onclose?.({ code, reason });
    }
}

function makeCallbacks(): {
    callbacks: WsClientCallbacks;
    onMessage: ReturnType<typeof vi.fn>;
    onConnectStateChange: ReturnType<typeof vi.fn>;
    onDisconnect: ReturnType<typeof vi.fn>;
} {
    const onMessage = vi.fn();
    const onConnectStateChange = vi.fn();
    const onDisconnect = vi.fn();
    return {
        callbacks: { onMessage, onConnectStateChange, onDisconnect },
        onMessage,
        onConnectStateChange,
        onDisconnect,
    };
}

/** Run connect() to completion (config fetch resolves) and return the socket
 *  the client created. A single real-timer macrotask hop drains the
 *  Promise.all([...]).then() chain that creates the socket (only valid under
 *  real timers — the fake-timer tests advance the clock manually instead). */
async function connectAndGetSocket(client: InstanceType<typeof WebSocketClient>): Promise<FakeWebSocket> {
    client.connect();
    await new Promise((r) => setTimeout(r, 0));
    const socket = FakeWebSocket.instances.at(-1);
    if (!socket) throw new Error('connect() did not create a socket');
    return socket;
}

beforeEach(async () => {
    if (!WebSocketClient) {
        ({ WebSocketClient } = await import('./ws-client.js'));
    }
    FakeWebSocket.instances = [];
    mockInvoke.mockReset();
    mockInvoke.mockResolvedValue('');
    mockShowToast.mockReset();
    mockErrorLog.mockReset();
    // Install the fake constructor + static OPEN/CONNECTING the client reads.
    (globalThis as unknown as { WebSocket: unknown }).WebSocket = FakeWebSocket;
});

afterEach(() => {
    vi.useRealTimers();
});

describe('WebSocketClient — exports', () => {
    it('constructs with a callbacks object and exposes the expected fields', () => {
        const { callbacks } = makeCallbacks();
        const client = new WebSocketClient(callbacks);
        expect(client.connected).toBe(false);
        expect(client.reconnectAttempts).toBe(0);
        expect(client.maxReconnectAttempts).toBe(5);
        expect(client.token).toBe(null);
    });
});

describe('WebSocketClient — synchronous constructor throw', () => {
    it('falls back to the next candidate when new WebSocket() throws on a malformed configured URL', async () => {
        const { callbacks } = makeCallbacks();
        // get_ws_endpoint returns a malformed URL (space in host — e.g. a .env
        // typo passed through verbatim). The real browser WebSocket constructor
        // throws SyntaxError SYNCHRONOUSLY for this, which used to discard the
        // fallback candidates and reconnect-loop on the same bad URL forever.
        mockInvoke.mockImplementation((cmd: string) =>
            Promise.resolve(cmd === 'get_ws_endpoint' ? 'ws://my host:8765/ws' : ''));
        const ThrowingWebSocket = class extends FakeWebSocket {
            constructor(url: string) {
                if (url.includes(' ')) throw new SyntaxError('invalid WebSocket URL');
                super(url);
            }
        };
        (globalThis as unknown as { WebSocket: unknown }).WebSocket = ThrowingWebSocket;

        const client = new WebSocketClient(callbacks);
        client.connect();
        await new Promise((r) => setTimeout(r, 0));

        // The throw on the malformed primary must NOT discard the fallbacks:
        // a socket for the default loopback endpoint gets created.
        const socket = FakeWebSocket.instances.at(-1);
        expect(socket).toBeDefined();
        expect(socket!.url).toBe('ws://127.0.0.1:8765/ws');
    });
});

describe('WebSocketClient.onmessage — frame hardening', () => {
    it('drops a Blob frame without calling onMessage', async () => {
        const { callbacks, onMessage } = makeCallbacks();
        const client = new WebSocketClient(callbacks);
        // NB: we deliberately do NOT fireOpen() in this block. onmessage only
        // gates on `this.ws === socket` (set the moment the socket is created,
        // before open), so messages dispatch without an open handshake — and
        // skipping open avoids leaking the 30s ping-loop interval into the test.
        const socket = await connectAndGetSocket(client);

        // Blob isn't a string → rejected before JSON.parse.
        const blob = typeof Blob !== 'undefined' ? new Blob(['{"type":"x"}']) : { size: 1 };
        socket.fireMessage(blob);
        expect(onMessage).not.toHaveBeenCalled();
    });

    it('drops an ArrayBuffer frame without calling onMessage', async () => {
        const { callbacks, onMessage } = makeCallbacks();
        const client = new WebSocketClient(callbacks);
        const socket = await connectAndGetSocket(client);

        socket.fireMessage(new ArrayBuffer(8));
        expect(onMessage).not.toHaveBeenCalled();
    });

    it('drops a string longer than the 50 MB code-unit cap', async () => {
        const { callbacks, onMessage } = makeCallbacks();
        const client = new WebSocketClient(callbacks);
        const socket = await connectAndGetSocket(client);
        socket.fireOpen();

        // The cap is 50 * 1024 * 1024 UTF-16 code units. We must exceed `.length`,
        // and there's no way to fake String.length, so allocate one oversized
        // string for this single case and release it right after.
        const MAX = 50 * 1024 * 1024;
        let huge: string | null = 'a'.repeat(MAX + 1);
        socket.fireMessage(huge);
        huge = null;  // let GC reclaim the ~100 MB buffer promptly
        expect(onMessage).not.toHaveBeenCalled();
    });

    it('delivers a string exactly at the cap (boundary is inclusive)', async () => {
        const { callbacks, onMessage } = makeCallbacks();
        const client = new WebSocketClient(callbacks);
        const socket = await connectAndGetSocket(client);
        socket.fireOpen();

        // A valid JSON object padded with spaces to land exactly on the cap.
        // length === MAX_MESSAGE_LENGTH passes (`> cap` is the reject test).
        const MAX = 50 * 1024 * 1024;
        const head = '{"type":"x"}';
        let atCap: string | null = head + ' '.repeat(MAX - head.length);
        expect(atCap.length).toBe(MAX);
        socket.fireMessage(atCap);
        atCap = null;
        expect(onMessage).toHaveBeenCalledTimes(1);
        expect(onMessage).toHaveBeenCalledWith({ type: 'x' });
    });

    it('strips __proto__ so a malicious frame cannot pollute Object.prototype', async () => {
        const { callbacks, onMessage } = makeCallbacks();
        const client = new WebSocketClient(callbacks);
        const socket = await connectAndGetSocket(client);

        socket.fireMessage('{"__proto__":{"polluted":true},"type":"ok"}');
        // The reviver drops the dangerous key; the surviving object is still a
        // valid frame, so onMessage IS invoked — but with NO prototype pollution.
        expect(onMessage).toHaveBeenCalledTimes(1);
        const delivered = onMessage.mock.calls[0][0] as Record<string, unknown>;
        expect(delivered.type).toBe('ok');
        expect('polluted' in delivered).toBe(false);
        expect(({} as Record<string, unknown>).polluted).toBeUndefined();
        expect((Object.prototype as Record<string, unknown>).polluted).toBeUndefined();
    });

    it('strips constructor / prototype keys too', async () => {
        const { callbacks, onMessage } = makeCallbacks();
        const client = new WebSocketClient(callbacks);
        const socket = await connectAndGetSocket(client);

        socket.fireMessage('{"constructor":{"bad":1},"prototype":{"bad":2},"type":"ok"}');
        expect(onMessage).toHaveBeenCalledTimes(1);
        const delivered = onMessage.mock.calls[0][0] as Record<string, unknown>;
        // Assert on OWN keys: `in` walks the prototype chain, where `constructor`
        // is always inherited from Object.prototype, so `'constructor' in delivered`
        // is true for any plain object regardless of the reviver. The reviver drops
        // the dangerous OWN keys — that's what we verify here.
        expect(Object.prototype.hasOwnProperty.call(delivered, 'constructor')).toBe(false);
        expect(Object.prototype.hasOwnProperty.call(delivered, 'prototype')).toBe(false);
        expect(delivered.type).toBe('ok');
    });

    it('drops a JSON null frame', async () => {
        const { callbacks, onMessage } = makeCallbacks();
        const client = new WebSocketClient(callbacks);
        const socket = await connectAndGetSocket(client);

        socket.fireMessage('null');
        expect(onMessage).not.toHaveBeenCalled();
    });

    it('drops a JSON array frame', async () => {
        const { callbacks, onMessage } = makeCallbacks();
        const client = new WebSocketClient(callbacks);
        const socket = await connectAndGetSocket(client);

        socket.fireMessage('[1,2,3]');
        expect(onMessage).not.toHaveBeenCalled();
    });

    it('drops a bare JSON string frame', async () => {
        const { callbacks, onMessage } = makeCallbacks();
        const client = new WebSocketClient(callbacks);
        const socket = await connectAndGetSocket(client);

        socket.fireMessage('"just a string"');
        expect(onMessage).not.toHaveBeenCalled();
    });

    it('drops a malformed (unparseable) JSON frame', async () => {
        const { callbacks, onMessage } = makeCallbacks();
        const client = new WebSocketClient(callbacks);
        const socket = await connectAndGetSocket(client);

        socket.fireMessage('{not json');
        expect(onMessage).not.toHaveBeenCalled();
    });

    it('delivers a normal object frame', async () => {
        const { callbacks, onMessage } = makeCallbacks();
        const client = new WebSocketClient(callbacks);
        const socket = await connectAndGetSocket(client);

        socket.fireMessage('{"type":"chunk","content":"hi"}');
        expect(onMessage).toHaveBeenCalledTimes(1);
        expect(onMessage).toHaveBeenCalledWith({ type: 'chunk', content: 'hi' });
    });
});

describe('WebSocketClient — reconnect backoff', () => {
    it('caps fast retries at maxReconnectAttempts, then settles at the 30s interval', async () => {
        vi.useFakeTimers();
        const { callbacks } = makeCallbacks();
        const client = new WebSocketClient(callbacks);
        const randomSpy = vi.spyOn(Math, 'random').mockReturnValue(0);  // no jitter

        // First socket: open then close to enter the reconnect cycle.
        client.connect();
        await vi.advanceTimersByTimeAsync(0);  // flush config-fetch microtasks
        let socket = FakeWebSocket.instances.at(-1)!;
        socket.fireOpen();
        socket.fireClose();  // schedules attempt #1

        // Walk the 5 fast retries. Delays double: 1s,2s,4s,8s,16s (capped 30s).
        // Each scheduled connect() opens a PRIMARY socket; because the default
        // endpoint expands to two candidates (127.0.0.1 + localhost), a primary
        // that closes WITHOUT opening makes onclose chain to the FALLBACK url
        // (a second socket) before giving up. Only once that fallback also
        // closes unopened does scheduleReconnect() bump the attempt counter — so
        // each cycle closes both sockets to reach the next attempt.
        const expectedDelays = [1000, 2000, 4000, 8000, 16000];
        for (let i = 0; i < expectedDelays.length; i++) {
            expect(client.reconnectAttempts).toBe(i + 1);
            await vi.advanceTimersByTimeAsync(expectedDelays[i]);  // fire reconnect timer
            await vi.advanceTimersByTimeAsync(0);                  // flush config fetch
            const primary = FakeWebSocket.instances.at(-1)!;
            primary.fireClose();  // unopened → onclose tries the fallback candidate
            const fallback = FakeWebSocket.instances.at(-1)!;
            fallback.fireClose();  // unopened, candidates exhausted → scheduleReconnect
        }

        // Budget spent: now pinned at the cap and the one-time toast fired.
        expect(client.reconnectAttempts).toBe(5);
        expect(mockShowToast).toHaveBeenCalledTimes(1);
        // This socket OPENED before dropping → the "connection lost / restart"
        // WARNING (not the gentle never-connected message).
        {
            const [msg, opts] = mockShowToast.mock.calls[0] as [string, { type: string }];
            expect(msg).toMatch(/lost/i);
            expect(opts.type).toBe('warning');
        }

        // The capped path retries on a flat 30s timer (no further attempt-count bump).
        const before = FakeWebSocket.instances.length;
        await vi.advanceTimersByTimeAsync(30000);
        await vi.advanceTimersByTimeAsync(0);
        expect(FakeWebSocket.instances.length).toBe(before + 1);
        expect(client.reconnectAttempts).toBe(5);

        randomSpy.mockRestore();
    });

    it('never-opened (bot offline): caps retries then shows a GENTLE info message, not "lost / restart"', async () => {
        vi.useFakeTimers();
        const { callbacks } = makeCallbacks();
        const client = new WebSocketClient(callbacks);
        const randomSpy = vi.spyOn(Math, 'random').mockReturnValue(0);  // no jitter

        // First connect: socket NEVER opens (bot not running). Close the primary
        // then the fallback candidate (both unopened) to schedule attempt #1.
        client.connect();
        await vi.advanceTimersByTimeAsync(0);  // flush config-fetch microtasks
        FakeWebSocket.instances.at(-1)!.fireClose();  // primary, unopened → fallback
        FakeWebSocket.instances.at(-1)!.fireClose();  // fallback, unopened → schedule

        const expectedDelays = [1000, 2000, 4000, 8000, 16000];
        for (let i = 0; i < expectedDelays.length; i++) {
            expect(client.reconnectAttempts).toBe(i + 1);
            await vi.advanceTimersByTimeAsync(expectedDelays[i]);
            await vi.advanceTimersByTimeAsync(0);
            FakeWebSocket.instances.at(-1)!.fireClose();  // primary
            FakeWebSocket.instances.at(-1)!.fireClose();  // fallback
        }

        // Budget spent, but the socket never opened → the gentle "server offline,
        // press Start" INFO message, NOT the misleading "lost / restart" warning.
        expect(client.reconnectAttempts).toBe(5);
        expect(mockShowToast).toHaveBeenCalledTimes(1);
        const [msg, opts] = mockShowToast.mock.calls[0] as [string, { type: string }];
        expect(msg, 'never-connected message must not say lost/restart').not.toMatch(/lost|restart/i);
        expect(opts.type).toBe('info');

        randomSpy.mockRestore();
    });

    it('a STABLE open (survives the stability window) resets reconnectAttempts to 0', async () => {
        vi.useFakeTimers();
        const { callbacks } = makeCallbacks();
        const client = new WebSocketClient(callbacks);
        vi.spyOn(Math, 'random').mockReturnValue(0);

        client.connect();
        await vi.advanceTimersByTimeAsync(0);
        let socket = FakeWebSocket.instances.at(-1)!;
        socket.fireOpen();
        socket.fireClose();           // attempt #1 scheduled
        expect(client.reconnectAttempts).toBe(1);

        await vi.advanceTimersByTimeAsync(1000);
        await vi.advanceTimersByTimeAsync(0);
        socket = FakeWebSocket.instances.at(-1)!;
        socket.fireOpen();            // reconnect opens…
        // …but the backoff is NOT cleared until the connection proves stable.
        expect(client.reconnectAttempts).toBe(1);
        await vi.advanceTimersByTimeAsync(3000);  // survive CONNECTION_STABLE_MS
        expect(client.reconnectAttempts).toBe(0);
    });

    it('an open immediately followed by a close (bad token) does NOT reset backoff', async () => {
        // Regression: the server accepts the WS upgrade for a message-auth client
        // then closes ~immediately on a wrong/stale token. Resetting backoff on
        // raw open let that reconnect-storm at the base delay forever. The reset
        // is now gated on surviving the stability window, which a rejected socket
        // never does — so the backoff must keep escalating across attempts.
        vi.useFakeTimers();
        const { callbacks } = makeCallbacks();
        const client = new WebSocketClient(callbacks);
        vi.spyOn(Math, 'random').mockReturnValue(0);

        client.connect();
        await vi.advanceTimersByTimeAsync(0);
        for (let i = 1; i <= 3; i++) {
            const socket = FakeWebSocket.instances.at(-1)!;
            socket.fireOpen();
            // Server rejects the token well within the stability window.
            await vi.advanceTimersByTimeAsync(100);
            socket.fireClose(4001);
            // Backoff must escalate every round, not reset to 0 on the open.
            expect(client.reconnectAttempts).toBe(i);
            // Advance past the scheduled reconnect to spawn the next socket.
            await vi.advanceTimersByTimeAsync(60000);
            await vi.advanceTimersByTimeAsync(0);
        }
    });
});

describe('WebSocketClient.disconnect — no resurrection of in-flight connect', () => {
    it('does not open a socket when disconnect() runs before the config fetch resolves', async () => {
        const { callbacks } = makeCallbacks();
        const client = new WebSocketClient(callbacks);

        // Hold the config fetch open so we can disconnect() mid-flight.
        let resolveToken!: (v: string) => void;
        mockInvoke.mockImplementation((cmd: string) => {
            if (cmd === 'get_ws_token') {
                return new Promise<string>((res) => { resolveToken = res; });
            }
            return Promise.resolve('ws://127.0.0.1:8765/ws');
        });

        client.connect();
        await new Promise((r) => setTimeout(r, 0));
        // No socket yet — still awaiting the token.
        expect(FakeWebSocket.instances.length).toBe(0);

        client.disconnect();           // user tears down mid-connect

        resolveToken('tok');           // the pending fetch now resolves...
        await new Promise((r) => setTimeout(r, 0));

        // ...but the generation guard must stop it from opening a socket.
        expect(FakeWebSocket.instances.length).toBe(0);
        expect(client.connected).toBe(false);
    });

    it('a fresh connect() after disconnect() still works (isConnecting was cleared)', async () => {
        const { callbacks } = makeCallbacks();
        const client = new WebSocketClient(callbacks);

        let resolveToken!: (v: string) => void;
        mockInvoke.mockImplementationOnce(() => new Promise<string>((res) => { resolveToken = res; }))
            .mockResolvedValue('');

        client.connect();              // first attempt — hangs on token
        await new Promise((r) => setTimeout(r, 0));
        client.disconnect();           // clears isConnecting + bumps generation
        resolveToken('tok');           // stale fetch resolves into a no-op
        await new Promise((r) => setTimeout(r, 0));
        expect(FakeWebSocket.instances.length).toBe(0);

        // A brand-new connect() must not be blocked by a stale isConnecting flag.
        const socket = await connectAndGetSocket(client);
        expect(socket).toBeDefined();
        socket.fireOpen();
        expect(client.connected).toBe(true);
    });

    it('disconnect() closes an already-open socket and clears connected', async () => {
        const { callbacks } = makeCallbacks();
        const client = new WebSocketClient(callbacks);
        const socket = await connectAndGetSocket(client);
        socket.fireOpen();
        expect(client.connected).toBe(true);

        client.disconnect();
        expect(socket.closed).toBe(true);
        expect(client.connected).toBe(false);
    });
});
