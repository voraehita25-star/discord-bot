/**
 * Dashboard WebSocket client — connection lifecycle, auth, reconnect, ping/pong.
 *
 * Extracted from ChatManager so the message-processing logic (~2700 LOC) can
 * be tested / reasoned-about without also worrying about socket state. The
 * client exposes a narrow callback API:
 *
 *   onMessage(data)         — every successfully-parsed JSON frame
 *   onConnectStateChange(c) — fires on socket open/close; c=true means open
 *   onDisconnect()          — fires once on close ONLY after the socket had opened
 *                             (distinguish "disconnected mid-session" from
 *                             "never connected"; used by ChatManager to reset
 *                             streaming state)
 *
 * Reconnect uses exponential backoff (1s → 30s cap) with 0-30% jitter to
 * prevent a thundering herd when the bot restarts. The client also runs a
 * 30-second ping/pong loop so half-open connections (silent WiFi drops, NAT
 * timeouts) surface within ~60 seconds instead of hanging forever.
 *
 * Call `notePong()` from your onMessage handler when you see a `{type:'pong'}`
 * frame so the client can clear its missed-pong counter.
 */

import { errorLogger, invoke, showToast } from '../shared.js';

export interface WsClientCallbacks {
    /** Fires for every successfully-parsed incoming frame. */
    onMessage: (data: Record<string, unknown>) => void;
    /** Fires when the socket opens (true) or closes (false). */
    onConnectStateChange?: (connected: boolean) => void;
    /** Fires once per close AFTER the socket had opened — use to reset UI state. */
    onDisconnect?: () => void;
}

const DEFAULT_WS_ENDPOINT = 'ws://127.0.0.1:8765/ws';
const LOCALHOST_WS_ENDPOINT = 'ws://localhost:8765/ws';
const PING_INTERVAL_MS = 30_000;
const MISSED_PONG_LIMIT = 2;
// 50 MB cap — note that we measure JS string `.length` (UTF-16 code units),
// not raw bytes. We treat it as a safety net rather than an exact byte cap;
// for ASCII payloads the two match closely and that's the worst case.
const MAX_MESSAGE_LENGTH = 50 * 1024 * 1024;

export class WebSocketClient {
    ws: WebSocket | null = null;
    connected: boolean = false;
    reconnectAttempts: number = 0;
    readonly maxReconnectAttempts: number = 5;

    private wsToken: string | null = null;
    private isConnecting: boolean = false;
    private reconnectTimeout: number | null = null;
    private pingInterval: number | null = null;
    private pongPending: boolean = false;
    private missedPongs: number = 0;
    // Once the fast-retry budget is spent we keep retrying at the capped
    // interval but warn the user only once (avoid toast spam).
    private maxAttemptsNotified: boolean = false;

    constructor(private readonly callbacks: WsClientCallbacks) {}

    /** Current token (for consumers that need to re-auth inline, e.g. cross-origin iframes). */
    get token(): string | null { return this.wsToken; }

    /** Send a JSON frame. Returns true on success, false if the socket
     *  isn't open (caller can roll back streaming-state flags). Always
     *  shows a toast on drop. */
    send(data: unknown): boolean {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            try {
                this.ws.send(JSON.stringify(data));
                return true;
            } catch (e) {
                // Most often "InvalidStateError" if the socket closed
                // between readyState check and send. Treat as drop.
                showToast('Failed to send: connection lost', { type: 'error' });
                console.warn('WebSocket send failed:', e);
                return false;
            }
        }
        showToast('Not connected to AI server', { type: 'error' });
        return false;
    }

    /** Clear the pong-pending flag. Call this when an incoming `{type:'pong'}` arrives. */
    notePong(): void {
        this.pongPending = false;
        this.missedPongs = 0;
    }

    /** Cleanly close any active socket, stop ping/reconnect timers. */
    disconnect(): void {
        // Explicit `!== null` (not truthiness) — a timer id of 0 is valid per
        // spec and would be skipped by a truthy check, leaking the timer.
        if (this.pingInterval !== null) {
            clearInterval(this.pingInterval);
            this.pingInterval = null;
        }
        if (this.reconnectTimeout !== null) {
            clearTimeout(this.reconnectTimeout);
            this.reconnectTimeout = null;
        }
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }
        this.connected = false;
    }

    /** Open a connection. No-op if already connecting / open. */
    connect(): void {
        if (
            this.isConnecting
            || (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING))
        ) {
            return;
        }

        if (this.reconnectTimeout) {
            clearTimeout(this.reconnectTimeout);
            this.reconnectTimeout = null;
        }

        try {
            this.isConnecting = true;
            // Guard against a hung Tauri `invoke` (backend deadlock): if it
            // never resolves, the `.finally` below never runs, `isConnecting`
            // stays true forever, and every future connect() is a silent
            // no-op → permanent disconnect with no reconnect. Race each call
            // against a timeout that falls back to the default so we always
            // proceed (or fall through to scheduleReconnect()).
            const withTimeout = <T>(p: Promise<T>, fallback: T): Promise<T> => {
                let timer: number | undefined;
                const timeout = new Promise<T>((resolve) => {
                    timer = window.setTimeout(() => resolve(fallback), 8000);
                });
                // Clear the timer once the underlying promise settles so it
                // doesn't outlive a fast invoke() (avoids accumulating pending
                // no-op timers under connect/reconnect churn).
                return Promise.race([p.finally(() => clearTimeout(timer)), timeout]);
            };
            Promise.all([
                withTimeout(invoke<string>('get_ws_token').catch(() => ''), ''),
                withTimeout(invoke<string>('get_ws_endpoint').catch(() => DEFAULT_WS_ENDPOINT), DEFAULT_WS_ENDPOINT),
            ]).then(([token, endpoint]) => {
                this.wsToken = token || null;
                const candidates = this.buildEndpointCandidates(endpoint || DEFAULT_WS_ENDPOINT);
                this.connectWithUrl(candidates[0], candidates.slice(1));
            }).catch(() => {
                console.warn('WS config unavailable — falling back to default localhost endpoint');
                this.wsToken = null;
                const candidates = this.buildEndpointCandidates(DEFAULT_WS_ENDPOINT);
                this.connectWithUrl(candidates[0], candidates.slice(1));
            }).finally(() => {
                this.isConnecting = false;
            });
        } catch (e) {
            this.isConnecting = false;
            console.error('Failed to create WebSocket:', e);
            errorLogger.log('WEBSOCKET_CREATE_ERROR', 'Failed to create WebSocket', String(e));
            this.scheduleReconnect();
        }
    }

    /** Produce a dedup'd list of endpoints to try (primary + 127.0.0.1 / localhost variants). */
    private buildEndpointCandidates(primaryEndpoint: string): string[] {
        const normalizedPrimary = primaryEndpoint.trim() || DEFAULT_WS_ENDPOINT;
        const candidates = [normalizedPrimary, DEFAULT_WS_ENDPOINT, LOCALHOST_WS_ENDPOINT];

        if (normalizedPrimary.includes('127.0.0.1')) {
            candidates.push(normalizedPrimary.replace('127.0.0.1', 'localhost'));
        }
        if (normalizedPrimary.includes('localhost')) {
            candidates.push(normalizedPrimary.replace('localhost', '127.0.0.1'));
        }

        return [...new Set(candidates.map(url => url.trim()).filter(Boolean))];
    }

    private connectWithUrl(wsUrl: string, fallbackUrls: string[] = []): void {
        try {
            const socket = new WebSocket(wsUrl);
            this.ws = socket;
            let opened = false;

            socket.onopen = () => {
                if (this.ws !== socket) {
                    socket.close();
                    return;
                }
                opened = true;

                // Send token as first message for authentication (not in URL).
                if (this.wsToken) {
                    try {
                        socket.send(JSON.stringify({ type: 'auth', token: this.wsToken }));
                    } catch (e) {
                        console.error('Failed to authenticate WebSocket:', e);
                        errorLogger.log('WEBSOCKET_AUTH_ERROR', 'Failed to send dashboard auth token', String(e));
                        socket.close();
                        return;
                    }
                }
                this.connected = true;
                this.reconnectAttempts = 0;
                this.maxAttemptsNotified = false;
                this.pongPending = false;
                this.missedPongs = 0;
                this.callbacks.onConnectStateChange?.(true);
                this.startPingLoop();
            };

            socket.onclose = (event) => {
                if (this.ws !== socket) return;

                this.ws = null;
                this.connected = false;
                this.stopPingLoop();

                if (!opened && fallbackUrls.length > 0) {
                    const [nextUrl, ...remaining] = fallbackUrls;
                    errorLogger.log(
                        'WEBSOCKET_FALLBACK',
                        `WebSocket connection to ${wsUrl} closed before opening; retrying ${nextUrl}`,
                        JSON.stringify({ code: event.code, reason: (event.reason || '').slice(0, 512) }),
                    );
                    this.connectWithUrl(nextUrl, remaining);
                    return;
                }

                // Fire disconnect callback ONLY for connections that actually opened,
                // so ChatManager can distinguish "bot is down" from "lost mid-session".
                if (opened) this.callbacks.onDisconnect?.();
                this.callbacks.onConnectStateChange?.(false);
                this.scheduleReconnect();
            };

            socket.onerror = (error) => {
                if (this.ws !== socket) return;

                // Only log first error, not repeated connection failures during reconnect storms.
                if (this.reconnectAttempts === 0) {
                    console.warn('🔌 WebSocket connection failed (bot may not be running)');
                }
                errorLogger.log('WEBSOCKET_ERROR', `WebSocket connection error (${wsUrl})`, String(error));
                this.connected = false;
                // Don't emit onConnectStateChange(false) here: per the WS spec an
                // error is always followed by a close event, and onclose already
                // fires it — avoids a redundant double state-change per socket.
            };

            socket.onmessage = (event) => {
                if (this.ws !== socket) return;

                // Reject oversized frames to prevent memory exhaustion.
                // Length is measured in UTF-16 code units, not bytes.
                if (typeof event.data === 'string' && event.data.length > MAX_MESSAGE_LENGTH) {
                    console.warn('Dropped oversized WebSocket message:', event.data.length, 'code units');
                    return;
                }

                try {
                    const data = JSON.parse(event.data, (k, v) =>
                        k === '__proto__' || k === 'constructor' || k === 'prototype' ? undefined : v,
                    );
                    // Reject anything that isn't a non-null object — the
                    // frontend dispatches on `data.type`, which would crash
                    // (or silently no-op) on `null` / strings / arrays. This
                    // is also a small safety net against malformed server
                    // frames triggering odd behavior downstream.
                    if (data === null || typeof data !== 'object' || Array.isArray(data)) {
                        console.warn('Ignoring non-object WebSocket frame:', typeof data);
                        return;
                    }
                    this.callbacks.onMessage(data);
                } catch (e) {
                    console.error('Failed to parse WebSocket message:', e);
                    errorLogger.log('WEBSOCKET_PARSE_ERROR', 'Failed to parse message', String(e));
                }
            };
        } catch (e) {
            console.error('Failed to create WebSocket:', e);
            errorLogger.log('WEBSOCKET_CREATE_ERROR', 'Failed to create WebSocket', String(e));
            this.scheduleReconnect();
        }
    }

    private scheduleReconnect(): void {
        if (this.reconnectTimeout) {
            clearTimeout(this.reconnectTimeout);
            this.reconnectTimeout = null;
        }

        if (this.reconnectAttempts >= this.maxReconnectAttempts) {
            // Past the fast-retry budget: keep retrying at the capped 30s
            // interval so the dashboard self-heals when the bot comes back
            // (no manual page reload needed). Warn the user only once.
            if (!this.maxAttemptsNotified) {
                this.maxAttemptsNotified = true;
                // No onConnectStateChange?.(false) here — onclose (the only path
                // that reaches the cap via repeated socket failures) already
                // emitted false for this close, so the callback fires exactly
                // once per close (avoids a spurious duplicate transition).
                showToast(
                    'Connection to AI server lost — retrying in the background. Restart the bot if it stays offline.',
                    { type: 'warning', duration: 8000 },
                );
            }
            this.reconnectTimeout = window.setTimeout(() => {
                this.reconnectTimeout = null;
                this.connect();
            }, 30000);
            return;
        }

        this.reconnectAttempts++;
        const baseDelay = Math.min(1000 * Math.pow(2, this.reconnectAttempts - 1), 30000);
        const jitter = Math.random() * baseDelay * 0.3;
        const delay = Math.floor(baseDelay + jitter);
        console.debug(`Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts})`);
        this.reconnectTimeout = window.setTimeout(() => {
            this.reconnectTimeout = null;
            this.connect();
        }, delay);
    }

    private startPingLoop(): void {
        this.stopPingLoop();
        this.pingInterval = window.setInterval(() => {
            if (!this.connected) return;
            // Skip the keep-alive ping during the brief connected-but-CLOSING
            // window so a background ping never reaches send()'s error-toast path.
            if (this.ws?.readyState !== WebSocket.OPEN) return;
            if (this.pongPending) {
                this.missedPongs++;
                if (this.missedPongs >= MISSED_PONG_LIMIT) {
                    console.warn('🔌 Server unresponsive (missed pongs), forcing reconnect');
                    errorLogger.log('WEBSOCKET_STALE', `Server missed ${this.missedPongs} pongs, forcing reconnect`);
                    this.missedPongs = 0;
                    this.pongPending = false;
                    if (this.ws) this.ws.close();  // onclose handler will reconnect
                    return;
                }
            }
            this.pongPending = true;
            this.send({ type: 'ping' });
        }, PING_INTERVAL_MS);
    }

    private stopPingLoop(): void {
        if (this.pingInterval !== null) {
            clearInterval(this.pingInterval);
            this.pingInterval = null;
        }
    }
}
