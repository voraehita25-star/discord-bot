/**
 * 디스코드 봇 대시보드 - Enhanced TypeScript Frontend
 * Tauri v2 Desktop Application
 * 
 * Features:
 * - Toast Notifications
 * - Real-time Auto-refresh
 * - Performance Charts
 * - Dark/Light Theme
 * - Enhanced Settings Panel
 * - Optimized Performance with Caching
 */

// Extend Window interface for Tauri and global functions
interface TauriAPI {
    core: {
        invoke: <T>(cmd: string, args?: Record<string, unknown>) => Promise<T>;
    };
}

interface Window {
    __TAURI__?: TauriAPI;
    toggleAutoScroll: () => void;
    clearLogs: () => void;
    clearHistory: () => Promise<void>;
    openFolder: (folder: string) => Promise<void>;
    loadLogs: () => Promise<void>;
    toggleTheme: () => void;
    showToast: (message: string, options?: ToastOptions) => void;
}

// Use global Tauri API (withGlobalTauri: true in tauri.conf.json)
const invoke = <T>(cmd: string, args?: Record<string, unknown>): Promise<T> => {
    if (window.__TAURI__?.core?.invoke) {
        return window.__TAURI__.core.invoke<T>(cmd, args);
    }
    console.warn('Tauri not available, using mock');
    return Promise.reject(new Error('Tauri not available'));
};

// ============================================================================
// Types & Interfaces
// ============================================================================

interface BotStatus {
    is_running: boolean;
    uptime: string;
    mode: string;
    memory_mb: number;
}

interface DbStats {
    total_messages: number;
    active_channels: number;
    total_entities: number;
    rag_memories: number;
}

interface ChannelInfo {
    channel_id: string;
    message_count: number;
}

interface UserInfo {
    user_id: string;
    message_count: number;
}

interface ToastOptions {
    type: 'success' | 'error' | 'warning' | 'info';
    duration?: number;
}

interface ChartDataPoint {
    timestamp: number;
    value: number;
}

interface CacheEntry<T> {
    data: T;
    timestamp: number;
    ttl: number;
}

interface Settings {
    theme: 'dark' | 'light';
    refreshInterval: number;
    autoScroll: boolean;
    notifications: boolean;
    chartHistory: number;
}

// ============================================================================
// Performance Cache System
// ============================================================================

class DataCache {
    private cache: Map<string, CacheEntry<unknown>> = new Map();

    set<T>(key: string, data: T, ttlMs: number = 5000): void {
        this.cache.set(key, {
            data,
            timestamp: Date.now(),
            ttl: ttlMs
        });
    }

    get<T>(key: string): T | null {
        const entry = this.cache.get(key);
        if (!entry) return null;
        
        if (Date.now() - entry.timestamp > entry.ttl) {
            this.cache.delete(key);
            return null;
        }
        
        return entry.data as T;
    }

    invalidate(key: string): void {
        this.cache.delete(key);
    }

    clear(): void {
        this.cache.clear();
    }
}

const dataCache = new DataCache();

// ============================================================================
// State Management
// ============================================================================

let currentPage = 'status';
let refreshInterval: number | null = null;
let logsRefreshInterval: number | null = null;
let logsAutoScrollEnabled = true;
let lastLogCount = 0;

// Chart data history
const memoryHistory: ChartDataPoint[] = [];
const messagesHistory: ChartDataPoint[] = [];
const MAX_CHART_POINTS = 60;

// Settings with defaults
let settings: Settings = {
    theme: 'dark',
    refreshInterval: 2000,
    autoScroll: true,
    notifications: true,
    chartHistory: 60
};

// Debounce timers
const debounceTimers: Map<string, number> = new Map();

// ============================================================================
// Initialization
// ============================================================================

document.addEventListener('DOMContentLoaded', () => {
    loadSettings();
    initNavigation();
    initTheme();
    initToastContainer();
    initCharts();
    startRefreshLoop();
    loadAllData();
    initSakuraAnimation();
    initKeyboardShortcuts();
});

// ============================================================================
// Keyboard Shortcuts
// ============================================================================

function initKeyboardShortcuts(): void {
    document.addEventListener('keydown', (e) => {
        // Ctrl+1-4 for page navigation
        if (e.ctrlKey && e.key >= '1' && e.key <= '4') {
            const pages = ['status', 'logs', 'database', 'settings'];
            const index = parseInt(e.key) - 1;
            if (pages[index]) {
                e.preventDefault();
                switchPage(pages[index]);
            }
        }
        
        // Ctrl+R to refresh
        if (e.ctrlKey && e.key === 'r') {
            e.preventDefault();
            loadAllData();
            showToast('Refreshed!', { type: 'info', duration: 1500 });
        }
        
        // Ctrl+T to toggle theme
        if (e.ctrlKey && e.key === 't') {
            e.preventDefault();
            toggleTheme();
        }
    });
}

// ============================================================================
// Toast Notification System
// ============================================================================

function initToastContainer(): void {
    if (!document.getElementById('toast-container')) {
        const container = document.createElement('div');
        container.id = 'toast-container';
        document.body.appendChild(container);
    }
}

function showToast(message: string, options: ToastOptions = { type: 'info' }): void {
    if (!settings.notifications) return;

    const container = document.getElementById('toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast toast-${options.type}`;
    
    const icons: Record<string, string> = {
        success: '✅',
        error: '❌',
        warning: '⚠️',
        info: 'ℹ️'
    };

    toast.innerHTML = `
        <span class="toast-icon">${icons[options.type]}</span>
        <span class="toast-message">${escapeHtml(message)}</span>
        <button class="toast-close" onclick="this.parentElement.remove()">×</button>
    `;

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

// ============================================================================
// Theme System
// ============================================================================

function initTheme(): void {
    applyTheme(settings.theme);
    
    // Add theme toggle button listener
    const themeToggle = document.getElementById('theme-toggle');
    themeToggle?.addEventListener('click', toggleTheme);
}

function toggleTheme(): void {
    settings.theme = settings.theme === 'dark' ? 'light' : 'dark';
    applyTheme(settings.theme);
    saveSettings();
    showToast(`Theme: ${settings.theme === 'dark' ? '🌙 Dark' : '☀️ Light'}`, { type: 'info', duration: 1500 });
}

function applyTheme(theme: 'dark' | 'light'): void {
    document.documentElement.setAttribute('data-theme', theme);
    
    const themeIcon = document.getElementById('theme-icon');
    if (themeIcon) {
        themeIcon.textContent = theme === 'dark' ? '🌙' : '☀️';
    }
}

// ============================================================================
// Settings Management
// ============================================================================

function loadSettings(): void {
    try {
        const saved = localStorage.getItem('dashboard-settings');
        if (saved) {
            settings = { ...settings, ...JSON.parse(saved) };
        }
    } catch (e) {
        console.warn('Failed to load settings:', e);
    }
}

function saveSettings(): void {
    try {
        localStorage.setItem('dashboard-settings', JSON.stringify(settings));
    } catch (e) {
        console.warn('Failed to save settings:', e);
    }
}

function updateSetting<K extends keyof Settings>(key: K, value: Settings[K]): void {
    settings[key] = value;
    saveSettings();
    
    // Apply changes
    if (key === 'refreshInterval') {
        restartRefreshLoop();
    } else if (key === 'theme') {
        applyTheme(value as 'dark' | 'light');
    }
}

// ============================================================================
// Lightweight Charts (Canvas-based for performance)
// ============================================================================

function initCharts(): void {
    // Charts will be initialized when the status page loads
    window.addEventListener('resize', debounce(updateCharts, 'resize', 250));
}

function addChartDataPoint(history: ChartDataPoint[], value: number): void {
    history.push({
        timestamp: Date.now(),
        value
    });
    
    while (history.length > MAX_CHART_POINTS) {
        history.shift();
    }
}

function drawChart(canvasId: string, data: ChartDataPoint[], color: string, label: string): void {
    const canvas = document.getElementById(canvasId) as HTMLCanvasElement | null;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);

    const width = rect.width;
    const height = rect.height;
    const padding = 30;

    ctx.clearRect(0, 0, width, height);

    if (data.length < 2) {
        ctx.fillStyle = 'rgba(255,255,255,0.3)';
        ctx.font = '12px sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('Collecting data...', width / 2, height / 2);
        return;
    }

    const values = data.map(d => d.value);
    const minVal = Math.min(...values) * 0.9;
    const maxVal = Math.max(...values) * 1.1 || 1;

    // Draw grid
    ctx.strokeStyle = 'rgba(168, 85, 247, 0.15)';
    ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i++) {
        const y = padding + (height - padding * 2) * (i / 4);
        ctx.beginPath();
        ctx.moveTo(padding, y);
        ctx.lineTo(width - padding, y);
        ctx.stroke();
    }

    // Draw gradient fill
    const gradient = ctx.createLinearGradient(0, padding, 0, height - padding);
    gradient.addColorStop(0, color.replace('1)', '0.3)'));
    gradient.addColorStop(1, color.replace('1)', '0.05)'));

    ctx.beginPath();
    ctx.moveTo(padding, height - padding);

    data.forEach((point, i) => {
        const x = padding + (width - padding * 2) * (i / (data.length - 1));
        const y = height - padding - ((point.value - minVal) / (maxVal - minVal)) * (height - padding * 2);
        ctx.lineTo(x, y);
    });

    ctx.lineTo(width - padding, height - padding);
    ctx.closePath();
    ctx.fillStyle = gradient;
    ctx.fill();

    // Draw line
    ctx.beginPath();
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';

    data.forEach((point, i) => {
        const x = padding + (width - padding * 2) * (i / (data.length - 1));
        const y = height - padding - ((point.value - minVal) / (maxVal - minVal)) * (height - padding * 2);
        
        if (i === 0) {
            ctx.moveTo(x, y);
        } else {
            ctx.lineTo(x, y);
        }
    });
    ctx.stroke();

    // Draw current value
    const currentValue = data[data.length - 1]?.value ?? 0;
    ctx.fillStyle = color;
    ctx.font = 'bold 14px sans-serif';
    ctx.textAlign = 'right';
    ctx.fillText(`${label}: ${currentValue.toFixed(1)}`, width - padding, 20);

    // Draw min/max labels
    ctx.fillStyle = 'rgba(255,255,255,0.5)';
    ctx.font = '10px sans-serif';
    ctx.textAlign = 'left';
    ctx.fillText(maxVal.toFixed(1), 5, padding + 10);
    ctx.fillText(minVal.toFixed(1), 5, height - padding);
}

function updateCharts(): void {
    drawChart('memory-chart', memoryHistory, 'rgba(255, 107, 157, 1)', 'Memory MB');
    drawChart('messages-chart', messagesHistory, 'rgba(34, 211, 238, 1)', 'Messages');
}

// ============================================================================
// Sakura Petals Animation (Optimized with Object Pool)
// ============================================================================

function initSakuraAnimation(): void {
    const container = document.getElementById('sakura-container');
    if (!container) return;

    const petalShapes: string[] = [
        `<svg viewBox="0 0 40 40"><path d="M20 0 C25 10, 35 15, 40 20 C35 25, 25 30, 20 40 C15 30, 5 25, 0 20 C5 15, 15 10, 20 0" fill="currentColor"/></svg>`,
        `<svg viewBox="0 0 40 40"><ellipse cx="20" cy="20" rx="18" ry="12" fill="currentColor"/></svg>`,
        `<svg viewBox="0 0 40 40"><path d="M20 35 C10 25, 0 15, 10 5 C15 0, 20 5, 20 10 C20 5, 25 0, 30 5 C40 15, 30 25, 20 35" fill="currentColor"/></svg>`,
        `<svg viewBox="0 0 40 40"><ellipse cx="20" cy="20" rx="10" ry="18" fill="currentColor"/></svg>`,
        `<svg viewBox="0 0 40 40"><path d="M20 0 C30 15, 30 25, 20 40 C10 25, 10 15, 20 0" fill="currentColor"/></svg>`,
    ];

    const colors: string[] = [
        'rgba(255, 183, 197, 0.9)',
        'rgba(255, 145, 175, 0.85)',
        'rgba(255, 107, 157, 0.8)',
        'rgba(255, 192, 203, 0.9)',
        'rgba(255, 174, 201, 0.85)',
    ];

    const petalPool: HTMLDivElement[] = [];
    const activePetals: Set<HTMLDivElement> = new Set();
    const MAX_PETALS = 30;

    function getPetal(): HTMLDivElement {
        let petal = petalPool.pop();
        if (!petal) {
            petal = document.createElement('div');
            petal.className = 'sakura-petal';
        }
        return petal;
    }

    function returnPetal(petal: HTMLDivElement): void {
        activePetals.delete(petal);
        petal.remove();
        petalPool.push(petal);
    }

    function createPetal(): void {
        if (activePetals.size >= MAX_PETALS) return;

        const petal = getPetal();
        activePetals.add(petal);

        const size = Math.random() * 15 + 10;
        const startX = Math.random() * window.innerWidth;
        const duration = Math.random() * 6 + 6;
        const delay = Math.random() * 2;
        const rotateStart = Math.random() * 360;
        const rotateEnd = rotateStart + (Math.random() * 720 - 360);
        const swayAmount = Math.random() * 80 + 40;
        const color = colors[Math.floor(Math.random() * colors.length)];
        const shape = petalShapes[Math.floor(Math.random() * petalShapes.length)];

        petal.innerHTML = shape;
        petal.style.cssText = `
            position: fixed;
            width: ${size}px;
            height: ${size}px;
            left: ${startX}px;
            top: -40px;
            color: ${color};
            pointer-events: none;
            z-index: 1;
            opacity: 0;
            will-change: transform, opacity;
            animation: sakuraFall${Math.floor(Math.random() * 3)} ${duration}s linear ${delay}s;
            --sway: ${swayAmount}px;
            --rotate-start: ${rotateStart}deg;
            --rotate-end: ${rotateEnd}deg;
        `;

        container!.appendChild(petal);
        setTimeout(() => returnPetal(petal), (duration + delay) * 1000);
    }

    for (let i = 0; i < 15; i++) {
        setTimeout(createPetal, i * 300);
    }

    setInterval(createPetal, 1000);
}

// ============================================================================
// Navigation
// ============================================================================

function initNavigation(): void {
    document.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', () => {
            const page = (item as HTMLElement).dataset.page;
            if (page) switchPage(page);
        });
    });

    // Button handlers
    document.getElementById('btn-start')?.addEventListener('click', startBot);
    document.getElementById('btn-dev')?.addEventListener('click', startDevBot);
    document.getElementById('btn-stop')?.addEventListener('click', stopBot);
    document.getElementById('btn-restart')?.addEventListener('click', restartBot);
    
    // Settings handlers
    document.getElementById('refresh-interval')?.addEventListener('change', (e) => {
        const value = parseInt((e.target as HTMLSelectElement).value);
        updateSetting('refreshInterval', value);
        showToast(`Refresh interval: ${value / 1000}s`, { type: 'info' });
    });
    
    document.getElementById('notifications-toggle')?.addEventListener('change', (e) => {
        updateSetting('notifications', (e.target as HTMLInputElement).checked);
    });
}

function switchPage(page: string): void {
    currentPage = page;

    document.querySelectorAll('.nav-item').forEach(item => {
        const itemPage = (item as HTMLElement).dataset.page;
        item.classList.toggle('active', itemPage === page);
    });

    document.querySelectorAll('.page').forEach(p => {
        p.classList.toggle('active', p.id === `page-${page}`);
    });

    if (page === 'logs') {
        loadLogs();
        startLogsRefresh();
    } else {
        stopLogsRefresh();
    }

    if (page === 'database') loadDbStats();
    if (page === 'settings') loadSettingsUI();
}

// ============================================================================
// Optimized Refresh Loop
// ============================================================================

function startRefreshLoop(): void {
    if (refreshInterval) {
        clearInterval(refreshInterval);
    }
    refreshInterval = window.setInterval(updateStatus, settings.refreshInterval);
    updateStatus();
}

function restartRefreshLoop(): void {
    startRefreshLoop();
}

// Debounce helper for performance
function debounce(fn: () => void, key: string, delay: number): () => void {
    return () => {
        const existing = debounceTimers.get(key);
        if (existing) {
            clearTimeout(existing);
        }
        debounceTimers.set(key, window.setTimeout(() => {
            fn();
            debounceTimers.delete(key);
        }, delay));
    };
}

// Batch DOM updates for performance
function batchDOMUpdate(updates: (() => void)[]): void {
    requestAnimationFrame(() => {
        updates.forEach(update => update());
    });
}

async function updateStatus(): Promise<void> {
    // Check cache first
    const cachedStatus = dataCache.get<BotStatus>('status');
    const cachedDbStats = dataCache.get<DbStats>('dbStats');

    try {
        // Parallel fetch
        const [status, dbStats] = await Promise.all([
            cachedStatus ?? invoke<BotStatus>('get_status'),
            cachedDbStats ?? invoke<DbStats>('get_db_stats')
        ]);

        // Cache the results
        if (!cachedStatus) dataCache.set('status', status, 1500);
        if (!cachedDbStats) dataCache.set('dbStats', dbStats, 3000);

        // Add to chart history
        addChartDataPoint(memoryHistory, status.memory_mb);
        addChartDataPoint(messagesHistory, dbStats.total_messages);

        // Batch all DOM updates
        batchDOMUpdate([
            () => updateStatusBadge(status),
            () => updateStatusText(status),
            () => updateButtons(status),
            () => updateStats(status, dbStats),
            () => updateCharts()
        ]);

    } catch (error) {
        console.error('Failed to update status:', error);
    }
}

function updateStatusBadge(status: BotStatus): void {
    const badge = document.getElementById('status-badge');
    const statusText = badge?.querySelector('.status-text');

    if (badge && statusText) {
        badge.classList.toggle('online', status.is_running);
        statusText.textContent = status.is_running ? 'Online' : 'Offline';
    }
}

function updateStatusText(status: BotStatus): void {
    const botStatusText = document.getElementById('bot-status-text');
    if (botStatusText) {
        botStatusText.textContent = status.is_running ? 'Status: 🟢 Online' : 'Status: 🔴 Offline';
    }
}

function updateButtons(status: BotStatus): void {
    const btnStart = document.getElementById('btn-start') as HTMLButtonElement | null;
    const btnDev = document.getElementById('btn-dev') as HTMLButtonElement | null;
    const btnStop = document.getElementById('btn-stop') as HTMLButtonElement | null;
    const btnRestart = document.getElementById('btn-restart') as HTMLButtonElement | null;

    if (btnStart) btnStart.disabled = status.is_running;
    if (btnDev) btnDev.disabled = status.is_running;
    if (btnStop) btnStop.disabled = !status.is_running;
    if (btnRestart) btnRestart.disabled = !status.is_running;
}

function updateStats(status: BotStatus, dbStats: DbStats): void {
    const updates: [string, string][] = [
        ['stat-uptime', status.uptime],
        ['stat-mode', status.mode],
        ['stat-memory', `${status.memory_mb.toFixed(1)} MB`],
        ['stat-messages', dbStats.total_messages.toLocaleString()],
        ['stat-channels', dbStats.active_channels.toString()]
    ];

    updates.forEach(([id, value]) => {
        const el = document.getElementById(id);
        if (el && el.textContent !== value) {
            el.textContent = value;
        }
    });
}

// ============================================================================
// Bot Control
// ============================================================================

async function startBot(): Promise<void> {
    try {
        showToast('Starting bot...', { type: 'info', duration: 2000 });
        const result = await invoke<string>('start_bot');
        showToast(result, { type: 'success' });
        dataCache.invalidate('status');
        updateStatus();
    } catch (error) {
        showToast(String(error), { type: 'error' });
    }
}

async function stopBot(): Promise<void> {
    try {
        showToast('Stopping bot...', { type: 'info', duration: 2000 });
        const result = await invoke<string>('stop_bot');
        showToast(result, { type: 'success' });
        dataCache.invalidate('status');
        updateStatus();
    } catch (error) {
        showToast(String(error), { type: 'error' });
    }
}

async function restartBot(): Promise<void> {
    try {
        showToast('Restarting bot...', { type: 'info', duration: 2000 });
        const result = await invoke<string>('restart_bot');
        showToast(result, { type: 'success' });
        dataCache.invalidate('status');
        updateStatus();
    } catch (error) {
        showToast(String(error), { type: 'error' });
    }
}

async function startDevBot(): Promise<void> {
    try {
        showToast('Starting dev mode...', { type: 'info', duration: 2000 });
        const result = await invoke<string>('start_dev_bot');
        showToast(result, { type: 'success' });
        dataCache.invalidate('status');
        updateStatus();
    } catch (error) {
        showToast(String(error), { type: 'error' });
    }
}

// ============================================================================
// Logs - Optimized Real-time Streaming
// ============================================================================

async function loadLogs(): Promise<void> {
    try {
        const logs = await invoke<string[]>('get_logs', { count: 200 });
        const container = document.getElementById('log-content');
        const filterElement = document.getElementById('log-filter') as HTMLSelectElement | null;
        const filter = filterElement?.value || 'all';

        if (!container) return;

        const hasNewLogs = logs.length !== lastLogCount;
        lastLogCount = logs.length;

        // Use DocumentFragment for better performance
        const fragment = document.createDocumentFragment();
        
        logs.forEach((line: string) => {
            let level = 'info';
            if (line.includes('ERROR')) level = 'error';
            else if (line.includes('WARNING')) level = 'warning';
            else if (line.includes('DEBUG')) level = 'debug';

            if (filter === 'all' || line.includes(filter)) {
                const div = document.createElement('div');
                div.className = `log-line ${level}`;
                div.textContent = line;
                fragment.appendChild(div);
            }
        });

        container.innerHTML = '';
        container.appendChild(fragment);

        if (!container.firstChild) {
            container.textContent = 'No logs found.';
        }

        if (logsAutoScrollEnabled && hasNewLogs) {
            container.scrollTop = container.scrollHeight;
        }
    } catch (error) {
        console.error('Failed to load logs:', error);
        showToast('Failed to load logs', { type: 'error' });
    }
}

function startLogsRefresh(): void {
    if (logsRefreshInterval) {
        clearInterval(logsRefreshInterval);
    }
    logsRefreshInterval = window.setInterval(loadLogs, 1000);
}

function stopLogsRefresh(): void {
    if (logsRefreshInterval) {
        clearInterval(logsRefreshInterval);
        logsRefreshInterval = null;
    }
}

function toggleAutoScroll(): void {
    logsAutoScrollEnabled = !logsAutoScrollEnabled;
    const btn = document.getElementById('btn-auto-scroll');
    if (btn) {
        btn.textContent = logsAutoScrollEnabled ? '⏸ Pause' : '▶️ Resume';
        btn.classList.toggle('paused', !logsAutoScrollEnabled);
    }
    showToast(`Auto-scroll ${logsAutoScrollEnabled ? 'enabled' : 'disabled'}`, { type: 'info', duration: 1500 });
}

function clearLogs(): void {
    const container = document.getElementById('log-content');
    if (container) container.innerHTML = '';
    lastLogCount = 0;
    showToast('Logs cleared', { type: 'info', duration: 1500 });
}

// ============================================================================
// Database
// ============================================================================

async function loadDbStats(): Promise<void> {
    try {
        const stats = await invoke<DbStats>('get_db_stats');
        
        batchDOMUpdate([
            () => {
                const dbMessages = document.getElementById('db-messages');
                const dbChannels = document.getElementById('db-channels');
                const dbEntities = document.getElementById('db-entities');
                const dbRag = document.getElementById('db-rag');

                if (dbMessages) dbMessages.textContent = stats.total_messages.toLocaleString();
                if (dbChannels) dbChannels.textContent = stats.active_channels.toString();
                if (dbEntities) dbEntities.textContent = stats.total_entities.toString();
                if (dbRag) dbRag.textContent = stats.rag_memories.toString();
            }
        ]);

        // Load channels and users in parallel
        const [channels, users] = await Promise.all([
            invoke<ChannelInfo[]>('get_recent_channels', { limit: 10 }),
            invoke<UserInfo[]>('get_top_users', { limit: 10 })
        ]);

        const channelsList = document.getElementById('channels-list');
        if (channelsList) {
            channelsList.innerHTML = channels.map((ch: ChannelInfo) => `
                <div class="data-item">
                    <span class="data-item-id">${ch.channel_id}</span>
                    <span class="data-item-value">${ch.message_count.toLocaleString()} messages</span>
                </div>
            `).join('') || '<p class="no-data">No channels found.</p>';
        }

        const usersList = document.getElementById('users-list');
        if (usersList) {
            usersList.innerHTML = users.map((u: UserInfo) => `
                <div class="data-item">
                    <span class="data-item-id">${u.user_id}</span>
                    <span class="data-item-value">${u.message_count.toLocaleString()} messages</span>
                </div>
            `).join('') || '<p class="no-data">No users found.</p>';
        }

    } catch (error) {
        console.error('Failed to load DB stats:', error);
        showToast('Failed to load database stats', { type: 'error' });
    }
}

async function clearHistory(): Promise<void> {
    if (!confirm('⚠️ This will permanently delete ALL chat history. Continue?')) {
        return;
    }

    try {
        const count = await invoke<number>('clear_history');
        showToast(`Deleted ${count.toLocaleString()} messages`, { type: 'success' });
        dataCache.invalidate('dbStats');
        loadDbStats();
    } catch (error) {
        showToast(String(error), { type: 'error' });
    }
}

// ============================================================================
// Settings UI
// ============================================================================

function loadSettingsUI(): void {
    const refreshSelect = document.getElementById('refresh-interval') as HTMLSelectElement | null;
    if (refreshSelect) {
        refreshSelect.value = settings.refreshInterval.toString();
    }
    
    const notificationsToggle = document.getElementById('notifications-toggle') as HTMLInputElement | null;
    if (notificationsToggle) {
        notificationsToggle.checked = settings.notifications;
    }
}

// ============================================================================
// Helpers
// ============================================================================

async function openFolder(type: string): Promise<void> {
    let path: string;
    if (type === 'logs') {
        path = 'C:\\Users\\ME\\BOT\\logs';
    } else if (type === 'data') {
        path = 'C:\\Users\\ME\\BOT\\data';
    } else {
        path = type; // Allow direct path
    }

    try {
        await invoke('open_folder', { path });
    } catch (error) {
        showToast(`Failed to open folder: ${error}`, { type: 'error' });
    }
}

function loadAllData(): void {
    dataCache.clear();
    updateStatus();
    loadLogs();
    loadDbStats();
}

function escapeHtml(text: string): string {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ============================================================================
// Export for global access (Tauri needs these on window)
// ============================================================================

window.toggleAutoScroll = toggleAutoScroll;
window.clearLogs = clearLogs;
window.clearHistory = clearHistory;
window.openFolder = openFolder;
window.loadLogs = loadLogs;
window.toggleTheme = toggleTheme;
window.showToast = showToast;
