/**
 * Shared type definitions for the dashboard application.
 */

export interface BotStatus {
    is_running: boolean;
    uptime: string;
    mode: string;
    memory_mb: number;
}

export interface DbStats {
    total_messages: number;
    active_channels: number;
    total_entities: number;
    rag_memories: number;
}

export interface ChannelInfo {
    channel_id: string;
    message_count: number;
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
}
