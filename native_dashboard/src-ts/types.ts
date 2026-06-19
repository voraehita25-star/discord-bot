/**
 * Shared type definitions for the dashboard application.
 */

export interface BotStatus {
    is_running: boolean;
    pid: number | null;
    uptime: string;
    mode: string;
    memory_mb: number;
}

/**
 * Progress of a dashboard-initiated bot start, reported by the backend
 * ``get_start_progress`` command. Mirrors the Rust ``StartProgress`` enum
 * (serde internally-tagged on ``state``). Lets the UI distinguish a slow-but-
 * healthy cold start (``starting``) from a genuine startup failure
 * (``exited``) instead of collapsing both into a fixed-deadline timeout.
 *
 * - ``running``  — bot.pid written + cmdline verified; the bot is up.
 * - ``starting`` — the spawned process is still alive but hasn't reached the
 *                  running signal yet (normal during heavy cold-start imports).
 * - ``exited``   — the spawned process terminated before reaching running;
 *                  startup truly failed. ``code`` is its exit code if known.
 * - ``unknown``  — no tracked startup child (e.g. bot started outside the
 *                  dashboard, or the outcome was already consumed).
 */
export type StartProgress =
    | { state: 'running' }
    | { state: 'starting' }
    | { state: 'exited'; code: number | null }
    | { state: 'unknown' };

export interface DbStats {
    total_messages: number;
    active_channels: number;
    total_entities: number;
    rag_memories: number;
}

export interface ChannelInfo {
    channel_id: string;
    message_count: number;
    last_active: string;
}

export interface UserInfo {
    user_id: string;
    message_count: number;
}

export interface ToastOptions {
    type: 'success' | 'error' | 'warning' | 'info';
    duration?: number;
}

export interface ChartDataPoint {
    timestamp: number;
    value: number;
}

export interface CacheEntry<T> {
    data: T;
    timestamp: number;
    ttl: number;
}

export interface Settings {
    theme: 'dark' | 'light';
    refreshInterval: number;
    autoScroll: boolean;
    notifications: boolean;
    chartHistory: number;
    userName: string;
    userAvatar: string;
    aiAvatar: string;
    isCreator: boolean;
    sakuraEnabled?: boolean;
    // 3D polish toggles — both default OFF so we never surprise users with
    // sound/vibration on first launch. Settings UI lets them opt in.
    soundEnabled?: boolean;
    hapticEnabled?: boolean;
    lastConversationId?: string | null;
    // Compact density mode (CONTRACT): when true, <html data-density="compact">
    // is set so the CSS [data-density="compact"]{--density:.7} recipe tightens
    // card/section paddings. Defaults OFF (comfortable spacing).
    densityCompact?: boolean;
}

// ----------------------------------------------------------------------------
// CustomEvent detail shapes for the API-failover bridge (chat-manager.ts emits,
// app.ts listens). Typing the detail lets the listener shape-check before
// destructuring instead of trusting an untyped CustomEvent payload — a stray /
// malformed frame can't blow up the handler with a "cannot read property of
// undefined" the way `e.detail.results` on an `any` would.
// ----------------------------------------------------------------------------

/** ``api-failover-status`` — endpoint roster + availability snapshot. */
export interface ApiFailoverStatusDetail extends Record<string, unknown> {
    available?: boolean;
    endpoints?: Array<Record<string, unknown>>;
}

/** ``api-health-result`` — results of an on-demand endpoint health probe. */
export interface ApiHealthResultDetail {
    results?: Array<Record<string, unknown>>;
}
