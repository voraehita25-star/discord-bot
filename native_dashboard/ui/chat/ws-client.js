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
const DEFAULT_WS_ENDPOINT = 'ws://127.0.0.1:8765/ws';
const LOCALHOST_WS_ENDPOINT = 'ws://localhost:8765/ws';
const PING_INTERVAL_MS = 30000;
const MISSED_PONG_LIMIT = 2;
const MAX_MESSAGE_BYTES = 50 * 1024 * 1024; // 50 MB — conversation_loaded may include base64 images
export class WebSocketClient {
    constructor(callbacks) {
        this.callbacks = callbacks;
        this.ws = null;
        this.connected = false;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 5;
        this.wsToken = null;
        this.isConnecting = false;
        this.reconnectTimeout = null;
        this.pingInterval = null;
        this.pongPending = false;
        this.missedPongs = 0;
    }
    /** Current token (for consumers that need to re-auth inline, e.g. cross-origin iframes). */
    get token() { return this.wsToken; }
    /** Send a JSON frame. Shows a toast + drops the message if not open. */
    send(data) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify(data));
        }
        else {
            showToast('Not connected to AI server', { type: 'error' });
        }
    }
    /** Clear the pong-pending flag. Call this when an incoming `{type:'pong'}` arrives. */
    notePong() {
        this.pongPending = false;
        this.missedPongs = 0;
    }
    /** Cleanly close any active socket, stop ping/reconnect timers. */
    disconnect() {
        if (this.pingInterval) {
            clearInterval(this.pingInterval);
            this.pingInterval = null;
        }
        if (this.reconnectTimeout) {
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
    connect() {
        if (this.isConnecting
            || (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING))) {
            return;
        }
        if (this.reconnectTimeout) {
            clearTimeout(this.reconnectTimeout);
            this.reconnectTimeout = null;
        }
        this.isConnecting = true;
        try {
            Promise.all([
                invoke('get_ws_token').catch(() => ''),
                invoke('get_ws_endpoint').catch(() => DEFAULT_WS_ENDPOINT),
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
        }
        catch (e) {
            this.isConnecting = false;
            console.error('Failed to create WebSocket:', e);
            errorLogger.log('WEBSOCKET_CREATE_ERROR', 'Failed to create WebSocket', String(e));
            this.scheduleReconnect();
        }
    }
    /** Produce a dedup'd list of endpoints to try (primary + 127.0.0.1 / localhost variants). */
    buildEndpointCandidates(primaryEndpoint) {
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
    connectWithUrl(wsUrl, fallbackUrls = []) {
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
                    }
                    catch (e) {
                        console.error('Failed to authenticate WebSocket:', e);
                        errorLogger.log('WEBSOCKET_AUTH_ERROR', 'Failed to send dashboard auth token', String(e));
                        socket.close();
                        return;
                    }
                }
                this.connected = true;
                this.reconnectAttempts = 0;
                this.pongPending = false;
                this.missedPongs = 0;
                this.callbacks.onConnectStateChange?.(true);
                this.startPingLoop();
            };
            socket.onclose = (event) => {
                if (this.ws !== socket)
                    return;
                this.ws = null;
                this.connected = false;
                this.stopPingLoop();
                if (!opened && fallbackUrls.length > 0) {
                    const [nextUrl, ...remaining] = fallbackUrls;
                    errorLogger.log('WEBSOCKET_FALLBACK', `WebSocket connection to ${wsUrl} closed before opening; retrying ${nextUrl}`, JSON.stringify({ code: event.code, reason: event.reason || '' }));
                    this.connectWithUrl(nextUrl, remaining);
                    return;
                }
                // Fire disconnect callback ONLY for connections that actually opened,
                // so ChatManager can distinguish "bot is down" from "lost mid-session".
                if (opened)
                    this.callbacks.onDisconnect?.();
                this.callbacks.onConnectStateChange?.(false);
                this.scheduleReconnect();
            };
            socket.onerror = (error) => {
                if (this.ws !== socket)
                    return;
                // Only log first error, not repeated connection failures during reconnect storms.
                if (this.reconnectAttempts === 0) {
                    console.warn('🔌 WebSocket connection failed (bot may not be running)');
                }
                errorLogger.log('WEBSOCKET_ERROR', `WebSocket connection error (${wsUrl})`, String(error));
                this.connected = false;
                this.callbacks.onConnectStateChange?.(false);
            };
            socket.onmessage = (event) => {
                if (this.ws !== socket)
                    return;
                // Reject oversized frames to prevent memory exhaustion.
                if (typeof event.data === 'string' && event.data.length > MAX_MESSAGE_BYTES) {
                    console.warn('Dropped oversized WebSocket message:', event.data.length, 'bytes');
                    return;
                }
                try {
                    const data = JSON.parse(event.data);
                    this.callbacks.onMessage(data);
                }
                catch (e) {
                    console.error('Failed to parse WebSocket message:', e);
                    errorLogger.log('WEBSOCKET_PARSE_ERROR', 'Failed to parse message', String(e));
                }
            };
        }
        catch (e) {
            console.error('Failed to create WebSocket:', e);
            errorLogger.log('WEBSOCKET_CREATE_ERROR', 'Failed to create WebSocket', String(e));
            this.scheduleReconnect();
        }
    }
    scheduleReconnect() {
        if (this.reconnectTimeout) {
            clearTimeout(this.reconnectTimeout);
            this.reconnectTimeout = null;
        }
        if (this.reconnectAttempts >= this.maxReconnectAttempts) {
            console.warn('Max reconnect attempts reached');
            this.callbacks.onConnectStateChange?.(false);
            showToast('Connection to AI server lost. Please restart the bot and reload the dashboard.', { type: 'error', duration: 10000 });
            return;
        }
        this.reconnectAttempts++;
        const baseDelay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 30000);
        const jitter = Math.random() * baseDelay * 0.3;
        const delay = Math.floor(baseDelay + jitter);
        console.debug(`Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts})`);
        this.reconnectTimeout = window.setTimeout(() => {
            this.reconnectTimeout = null;
            this.connect();
        }, delay);
    }
    startPingLoop() {
        this.stopPingLoop();
        this.pingInterval = window.setInterval(() => {
            if (!this.connected)
                return;
            if (this.pongPending) {
                this.missedPongs++;
                if (this.missedPongs >= MISSED_PONG_LIMIT) {
                    console.warn('🔌 Server unresponsive (missed pongs), forcing reconnect');
                    errorLogger.log('WEBSOCKET_STALE', `Server missed ${this.missedPongs} pongs, forcing reconnect`);
                    this.missedPongs = 0;
                    this.pongPending = false;
                    if (this.ws)
                        this.ws.close(); // onclose handler will reconnect
                    return;
                }
            }
            this.pongPending = true;
            this.send({ type: 'ping' });
        }, PING_INTERVAL_MS);
    }
    stopPingLoop() {
        if (this.pingInterval !== null) {
            clearInterval(this.pingInterval);
            this.pingInterval = null;
        }
    }
}
//# sourceMappingURL=ws-client.js.map