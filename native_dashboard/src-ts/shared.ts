/**
 * Shared utilities and state for the dashboard application.
 * Imported by both app.ts and chat-manager.ts — no circular dependencies.
 */

import type { Settings, ToastOptions } from './types.js';
import { DEFAULT_AI_AVATAR } from './faust_avatar.js';

// Re-export for convenience
export type { Settings, ToastOptions };

// ============================================================================
// Tauri API
// ============================================================================

interface TauriAPI {
    core: {
        invoke: <T>(cmd: string, args?: Record<string, unknown>) => Promise<T>;
    };
}

declare global {
    interface Window {
        __TAURI__?: TauriAPI;
        toggleAutoScroll: () => void;
        clearLogs: () => void;
        clearHistory: () => Promise<void>;
        openFolder: (folder: string) => Promise<void>;
        loadLogs: () => Promise<void>;
        toggleTheme: () => void;
        showToast: (message: string, options?: ToastOptions) => void;
        chatManager: unknown;
        showPage: (page: string) => void;
        startBot: () => Promise<void>;
    }
}

// Use global Tauri API (withGlobalTauri: true in tauri.conf.json)
export const invoke = <T>(cmd: string, args?: Record<string, unknown>): Promise<T> => {
    if (window.__TAURI__?.core?.invoke) {
        return window.__TAURI__.core.invoke<T>(cmd, args);
    }
    console.warn('Tauri not available, using mock');
    return Promise.reject(new Error('Tauri not available'));
};

// ============================================================================
// Error Logger - Logs frontend errors to file for debugging
// ============================================================================

export class ErrorLogger {
    private static instance: ErrorLogger;
    private errorQueue: Array<{type: string; message: string; stack?: string}> = [];
    private isProcessing = false;
    private maxQueueSize = 100; // Prevent unbounded growth

    static getInstance(): ErrorLogger {
        if (!ErrorLogger.instance) {
            ErrorLogger.instance = new ErrorLogger();
        }
        return ErrorLogger.instance;
    }

    // Private: must use getInstance() to avoid duplicate console.error wrappers
    // (each new instance would re-wrap and could cause infinite recursion).
    private constructor() {
        this.setupGlobalErrorHandlers();
    }

    private setupGlobalErrorHandlers(): void {
        // Catch unhandled errors
        window.onerror = (message, source, lineno, colno, error) => {
            this.log('UNCAUGHT_ERROR', String(message), error?.stack || `at ${source}:${lineno}:${colno}`);
            return false;
        };

        // Catch unhandled promise rejections
        window.onunhandledrejection = (event) => {
            const reason = event.reason;
            const message = reason?.message || String(reason);
            const stack = reason?.stack || 'No stack trace';
            this.log('UNHANDLED_REJECTION', message, stack);
        };

        // Override console.error to also log to file
        const originalConsoleError = console.error;
        console.error = (...args) => {
            try {
                originalConsoleError.apply(console, args);
                const message = args.map(arg => {
                    if (arg instanceof Error) return arg.message;
                    if (typeof arg === 'object') {
                        try {
                            return JSON.stringify(arg).substring(0, 500);
                        } catch {
                            return '[Object]';
                        }
                    }
                    return String(arg).substring(0, 500);
                }).join(' ');
                const stack = args.find(arg => arg instanceof Error)?.stack?.substring(0, 1000);
                this.log('CONSOLE_ERROR', message, stack);
            } catch {
                originalConsoleError.apply(console, ['ErrorLogger override failed']);
            }
        };
    }

    async log(errorType: string, message: string, stack?: string): Promise<void> {
        // Drop oldest errors if queue is full to prevent memory leak
        if (this.errorQueue.length >= this.maxQueueSize) {
            this.errorQueue.shift(); // Remove oldest
        }
        this.errorQueue.push({ type: errorType, message, stack });
        this.processQueue().catch(() => { /* prevent unhandled rejection */ });
    }

    private async processQueue(): Promise<void> {
        if (this.isProcessing || this.errorQueue.length === 0) return;
        
        this.isProcessing = true;
        
        while (this.errorQueue.length > 0) {
            const error = this.errorQueue.shift();
            if (error) {
                try {
                    await invoke('log_frontend_error', {
                        errorType: error.type,
                        message: error.message,
                        stack: error.stack || null
                    });
                } catch (e) {
                    // Silently fail if logging fails
                }
            }
        }
        
        this.isProcessing = false;
    }

    async getErrors(count: number = 20): Promise<string[]> {
        try {
            return await invoke<string[]>('get_dashboard_errors', { count });
        } catch {
            return ['Failed to fetch errors'];
        }
    }

    async clearErrors(): Promise<void> {
        try {
            await invoke('clear_dashboard_errors');
        } catch (e) {
            console.warn('Failed to clear error log:', e);
        }
    }
}

// Initialize error logger early
export const errorLogger = ErrorLogger.getInstance();

// ============================================================================
// HTML Escape Utility
// ============================================================================

export function escapeHtml(text: string): string {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML.replace(/"/g, '&quot;').replace(/'/g, '&#39;').replace(/`/g, '&#96;');
}

/**
 * Test whether a URL is safe to use as an <img src>. Allows data:image/,
 * http(s):, tauri/asset schemes, and relative paths. Rejects javascript:,
 * vbscript:, file: and other dangerous schemes.
 *
 * Defense-in-depth: avatars in this app come from canvas.toDataURL() locally,
 * but localStorage can be tampered with, so we validate before rendering.
 */
export function isSafeAvatarUrl(url: string | undefined | null): boolean {
    if (!url || typeof url !== 'string') return false;
    const lower = url.trim().toLowerCase();
    if (!lower) return false;
    return (
        lower.startsWith('data:image/') ||
        lower.startsWith('http://') ||
        lower.startsWith('https://') ||
        lower.startsWith('asset://') ||
        lower.startsWith('tauri://') ||
        lower.startsWith('/') ||
        lower.startsWith('./') ||
        lower.startsWith('../')
    );
}

/**
 * Returns the URL HTML-escaped for safe use inside an innerHTML template
 * attribute (e.g. `<img src="${safeAvatarUrl(x)}">`). Returns empty string
 * for unsafe schemes. Do NOT use this for `element.src = ...` (use
 * `isSafeAvatarUrl` + raw value for property assignment).
 */
export function safeAvatarUrl(url: string | undefined | null): string {
    if (!isSafeAvatarUrl(url)) return '';
    return escapeHtml((url as string).trim());
}

// ============================================================================
// Settings
// ============================================================================

export let settings: Settings = {
    theme: 'dark',
    refreshInterval: 2000,
    autoScroll: true,
    notifications: true,
    chartHistory: 60,
    userName: 'You',
    userAvatar: '',
    aiAvatar: DEFAULT_AI_AVATAR,
    isCreator: false,
    sakuraEnabled: true,
    lastConversationId: null,
};

export function loadSettings(): void {
    try {
        const saved = localStorage.getItem('dashboard-settings');
        if (saved) {
            const defaultAiAvatar = settings.aiAvatar; // Keep default Faust avatar
            settings = { ...settings, ...JSON.parse(saved) };
            // Migration: Only set default Faust avatar if saved aiAvatar is empty/undefined
            // Don't override custom avatars that users have set
            if (!settings.aiAvatar) {
                settings.aiAvatar = defaultAiAvatar;
                saveSettings(); // Save the migration
            }
        }
    } catch (e) {
        console.warn('Failed to load settings:', e);
    }
}

export function saveSettings(): void {
    try {
        localStorage.setItem('dashboard-settings', JSON.stringify(settings));
    } catch (e) {
        // Quota exceeded usually means avatar(s) blew the localStorage cap
        // (~5-10MB depending on engine). Drop them so the rest of the settings
        // still persist; user-set avatars can be re-uploaded.
        if (e instanceof DOMException && (e.name === 'QuotaExceededError' || e.code === 22)) {
            console.warn('Settings quota exceeded — clearing avatars and retrying');
            settings.userAvatar = '';
            settings.aiAvatar = '';
            try {
                localStorage.setItem('dashboard-settings', JSON.stringify(settings));
                showToast('Storage full — avatars were cleared to free space.', { type: 'warning' });
            } catch {
                console.warn('Failed to save settings even after dropping avatars');
            }
        } else {
            console.warn('Failed to save settings:', e);
        }
    }
}

// ============================================================================
// Toast Notification System
// ============================================================================

export function initToastContainer(): void {
    if (!document.getElementById('toast-container')) {
        const container = document.createElement('div');
        container.id = 'toast-container';
        document.body.appendChild(container);
    }
}

/**
 * Show a confirmation dialog that works reliably in Tauri v2 WebView2.
 * Falls back to Tauri's dialog plugin command, then to native confirm().
 */
export async function showConfirmDialog(message: string): Promise<boolean> {
    try {
        // Try Tauri dialog plugin first (most reliable in desktop apps)
        const result = await invoke<boolean>('show_confirm_dialog', { message });
        return result;
    } catch {
        // Fallback to browser confirm() if Tauri command not available
        return confirm(message);
    }
}

export function showToast(message: string, options: ToastOptions = { type: 'info' }): void {
    if (!settings.notifications) return;

    const container = document.getElementById('toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast toast-${options.type}`;
    
    const icons: Record<string, string> = {
        success: '\u2705',
        error: '\u274C',
        warning: '\u26A0\uFE0F',
        info: '\u2139\uFE0F'
    };

    toast.innerHTML = `
        <span class="toast-icon">${icons[options.type]}</span>
        <span class="toast-message">${escapeHtml(message)}</span>
        <button class="toast-close">\u00D7</button>
    `;

    // Use addEventListener instead of inline onclick (CSP blocks inline scripts)
    toast.querySelector('.toast-close')?.addEventListener('click', () => toast.remove());

    container.appendChild(toast);

    // Animate in
    requestAnimationFrame(() => {
        toast.classList.add('toast-visible');
    });

    // Auto remove
    const duration = options.duration ?? 4000;
    setTimeout(() => {
        toast.classList.remove('toast-visible');
        toast.classList.add('toast-hiding');
        setTimeout(() => toast.remove(), 300);
    }, duration);
}
