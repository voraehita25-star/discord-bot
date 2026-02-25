/**
 * 디스코드 봇 대시보드 - Enhanced TypeScript Frontend
 * Tauri v2 Desktop Application
 * 
 * Main application module — UI, navigation, charts, bot control, settings.
 * Chat & memory management extracted to chat-manager.ts.
 * Shared utilities in shared.ts.
 */

import type { BotStatus, DbStats, ChannelInfo, UserInfo, ChartDataPoint, CacheEntry, Settings, ToastOptions } from './types.js';
import {
    invoke,
    errorLogger,
    escapeHtml,
    settings,
    loadSettings,
    saveSettings,
    initToastContainer,
    showToast,
    showConfirmDialog,
} from './shared.js';
import {
    ChatManager,
    chatManager,
    memoryManager,
    initChatManager,
    initMemoryManager,
} from './chat-manager.js';

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

const debounceTimers: Map<string, number> = new Map();

// ============================================================================
// Initialization
// ============================================================================

document.addEventListener("DOMContentLoaded", () => {
    loadSettings();
    initNavigation();
    initTheme();
    initToastContainer();
    initCharts();
    startRefreshLoop();
    loadAllData();
    initSakuraAnimation();
    initKeyboardShortcuts();
    initChatManager();
    initMemoryManager();
    // Update AI avatars after all init
    updateAiAvatars();
});

// ============================================================================
// Keyboard Shortcuts
// ============================================================================

function initKeyboardShortcuts(): void {
    document.addEventListener('keydown', (e) => {
        // Ctrl+1-6 for page navigation
        if (e.ctrlKey && e.key >= '1' && e.key <= '6') {
            const pages = ['status', 'chat', 'memories', 'logs', 'database', 'settings'];
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
        
        // Ctrl+Enter to send message (in chat)
        if (e.ctrlKey && e.key === 'Enter' && currentPage === 'chat') {
            e.preventDefault();
            chatManager?.sendMessage();
        }
    });
}

// ============================================================================
// Theme System
// ============================================================================

function initTheme(): void {
    applyTheme(settings.theme);
    
    // Add theme toggle button listeners (sidebar + settings page)
    document.getElementById('theme-toggle')?.addEventListener('click', toggleTheme);
    document.getElementById('theme-toggle-settings')?.addEventListener('click', toggleTheme);
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
    // Also update the settings page theme icon
    const themeIconSettings = document.getElementById('theme-icon-settings');
    if (themeIconSettings) {
        themeIconSettings.textContent = theme === 'dark' ? '🌙' : '☀️';
    }
}


// ============================================================================
// Settings Management
// ============================================================================

function updateAiAvatars(): void {
    // Update empty state avatar
    const emptyAvatar = document.getElementById('chat-empty-avatar') as HTMLImageElement | null;
    if (emptyAvatar && settings.aiAvatar) {
        emptyAvatar.src = settings.aiAvatar;
    }
    // Update chat header avatar
    const headerAvatar = document.getElementById('chat-role-avatar') as HTMLImageElement | null;
    if (headerAvatar && settings.aiAvatar) {
        headerAvatar.src = settings.aiAvatar;
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
    // Use reduce instead of spread to prevent stack overflow with large arrays
    const minVal = values.reduce((a, b) => Math.min(a, b), Infinity) * 0.9;
    const maxVal = values.reduce((a, b) => Math.max(a, b), -Infinity) * 1.1 || 1;

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

    // Quick action buttons (replaced inline onclick for CSP compliance)
    document.getElementById('btn-open-logs')?.addEventListener('click', () => openFolder('logs'));
    document.getElementById('btn-open-data')?.addEventListener('click', () => openFolder('data'));
    document.getElementById('btn-overlay-start')?.addEventListener('click', () => { switchPage('status'); startBot(); });
    document.getElementById('btn-auto-scroll')?.addEventListener('click', toggleAutoScroll);
    document.getElementById('btn-clear-logs')?.addEventListener('click', clearLogs);
    document.getElementById('btn-refresh-logs')?.addEventListener('click', loadLogs);
    document.getElementById('btn-clear-history')?.addEventListener('click', clearHistory);
    document.getElementById('btn-delete-selected')?.addEventListener('click', deleteSelectedChannels);
    
    // Settings handlers
    document.getElementById('refresh-interval')?.addEventListener('change', (e) => {
        const value = parseInt((e.target as HTMLSelectElement).value);
        updateSetting('refreshInterval', value);
        showToast(`Refresh interval: ${value / 1000}s`, { type: 'info' });
    });
    
    document.getElementById('notifications-toggle')?.addEventListener('change', (e) => {
        updateSetting('notifications', (e.target as HTMLInputElement).checked);
    });

    // User name input handler
    document.getElementById('user-name-input')?.addEventListener('input', (e) => {
        const value = (e.target as HTMLInputElement).value.trim();
        updateSetting('userName', value || 'You');
    });
    
    // Save profile to AI button
    document.getElementById('btn-save-profile')?.addEventListener('click', () => {
        saveProfileToAI();
    });
    
    // Avatar upload handlers
    document.getElementById('btn-change-avatar')?.addEventListener('click', () => {
        document.getElementById('avatar-input')?.click();
    });
    
    document.getElementById('avatar-input')?.addEventListener('change', (e) => {
        const file = (e.target as HTMLInputElement).files?.[0];
        if (file) handleAvatarUpload(file, 'user');
    });
    
    document.getElementById('btn-remove-avatar')?.addEventListener('click', () => {
        removeAvatar('user');
    });
    
    // AI Avatar upload handlers
    document.getElementById('btn-change-ai-avatar')?.addEventListener('click', () => {
        document.getElementById('ai-avatar-input')?.click();
    });
    
    document.getElementById('ai-avatar-input')?.addEventListener('change', (e) => {
        const file = (e.target as HTMLInputElement).files?.[0];
        if (file) handleAvatarUpload(file, 'ai');
    });
    
    document.getElementById('btn-remove-ai-avatar')?.addEventListener('click', () => {
        removeAvatar('ai');
    });
    
    // Creator toggle handler
    document.getElementById('creator-toggle')?.addEventListener('change', (e) => {
        settings.isCreator = (e.target as HTMLInputElement).checked;
        saveSettings();
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
    if (page === 'memories' && chatManager && chatManager.connected) {
        memoryManager.loadMemories();
    }
    if (page === 'chat' && chatManager) {
        // Reconnect if disconnected
        if (!chatManager.connected) {
            chatManager.connect();
        }
    }
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
    
    // Update AI Chat overlay based on bot running status
    const chatOverlay = document.getElementById('chat-not-running-overlay');
    if (chatOverlay) {
        chatOverlay.classList.toggle('visible', !status.is_running);
    }
}

function updateStatusText(status: BotStatus): void {
    const botStatusText = document.getElementById('bot-status-text');
    if (botStatusText) {
        botStatusText.textContent = status.is_running ? 'Status: 🟢 Online' : 'Status: 🔴 Offline';
    }
}

function updateButtons(status: BotStatus): void {
    // Don't override button states while a bot command is in progress
    if (botCommandInProgress) return;

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

let botCommandInProgress = false;

function setBotControlBusy(busy: boolean): void {
    botCommandInProgress = busy;
    const btnStart = document.getElementById('btn-start') as HTMLButtonElement | null;
    const btnDev = document.getElementById('btn-dev') as HTMLButtonElement | null;
    const btnStop = document.getElementById('btn-stop') as HTMLButtonElement | null;
    const btnRestart = document.getElementById('btn-restart') as HTMLButtonElement | null;

    if (busy) {
        if (btnStart) btnStart.disabled = true;
        if (btnDev) btnDev.disabled = true;
        if (btnStop) btnStop.disabled = true;
        if (btnRestart) btnRestart.disabled = true;
    }
}

async function startBot(): Promise<void> {
    if (botCommandInProgress) return;
    try {
        setBotControlBusy(true);
        showToast('Starting bot...', { type: 'info', duration: 10000 });
        const result = await invoke<string>('start_bot');
        showToast(result, { type: 'success' });
        dataCache.invalidate('status');
        updateStatus();
    } catch (error) {
        showToast(String(error), { type: 'error' });
    } finally {
        setBotControlBusy(false);
    }
}

async function stopBot(): Promise<void> {
    if (botCommandInProgress) return;
    try {
        setBotControlBusy(true);
        showToast('Stopping bot...', { type: 'info', duration: 5000 });
        const result = await invoke<string>('stop_bot');
        showToast(result, { type: 'success' });
        dataCache.invalidate('status');
        updateStatus();
    } catch (error) {
        showToast(String(error), { type: 'error' });
    } finally {
        setBotControlBusy(false);
    }
}

async function restartBot(): Promise<void> {
    if (botCommandInProgress) return;
    try {
        setBotControlBusy(true);
        showToast('Restarting bot...', { type: 'info', duration: 12000 });
        const result = await invoke<string>('restart_bot');
        showToast(result, { type: 'success' });
        dataCache.invalidate('status');
        updateStatus();
    } catch (error) {
        showToast(String(error), { type: 'error' });
    } finally {
        setBotControlBusy(false);
    }
}

async function startDevBot(): Promise<void> {
    if (botCommandInProgress) return;
    try {
        setBotControlBusy(true);
        showToast('Starting dev mode...', { type: 'info', duration: 8000 });
        const result = await invoke<string>('start_dev_bot');
        showToast(result, { type: 'success' });
        dataCache.invalidate('status');
        updateStatus();
    } catch (error) {
        showToast(String(error), { type: 'error' });
    } finally {
        setBotControlBusy(false);
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
    
    // Also clear the actual log file
    invoke('clear_logs').then(result => {
        showToast(String(result), { type: 'success', duration: 1500 });
    }).catch(err => {
        showToast('Failed to clear logs: ' + err, { type: 'error' });
    });
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
            if (channels.length === 0) {
                channelsList.innerHTML = '<p class="no-data">No channels found.</p>';
                updateChannelSelectionUI();
            } else {
                channelsList.innerHTML = '';
                channels.forEach((ch: ChannelInfo) => {
                    const item = document.createElement('div');
                    item.className = 'data-item';
                    item.dataset.channelId = String(ch.channel_id);

                    const leftDiv = document.createElement('div');
                    leftDiv.className = 'data-item-left';

                    const checkbox = document.createElement('input');
                    checkbox.type = 'checkbox';
                    checkbox.className = 'data-item-checkbox';
                    checkbox.dataset.channelId = String(ch.channel_id);
                    checkbox.addEventListener('change', () => {
                        item.classList.toggle('selected', checkbox.checked);
                        updateChannelSelectionUI();
                    });

                    const idSpan = document.createElement('span');
                    idSpan.className = 'data-item-id';
                    idSpan.textContent = String(ch.channel_id);

                    leftDiv.appendChild(checkbox);
                    leftDiv.appendChild(idSpan);

                    const valSpan = document.createElement('span');
                    valSpan.className = 'data-item-value';
                    valSpan.textContent = `${ch.message_count.toLocaleString()} messages`;

                    item.appendChild(leftDiv);
                    item.appendChild(valSpan);

                    // Click row to toggle checkbox
                    item.addEventListener('click', (e) => {
                        if ((e.target as HTMLElement).tagName !== 'INPUT') {
                            checkbox.checked = !checkbox.checked;
                            item.classList.toggle('selected', checkbox.checked);
                            updateChannelSelectionUI();
                        }
                    });

                    channelsList.appendChild(item);
                });
                updateChannelSelectionUI();
            }
        }

        const usersList = document.getElementById('users-list');
        if (usersList) {
            if (users.length === 0) {
                usersList.innerHTML = '<p class="no-data">No users found.</p>';
            } else {
                usersList.innerHTML = '';
                users.forEach((u: UserInfo) => {
                    const item = document.createElement('div');
                    item.className = 'data-item';
                    const idSpan = document.createElement('span');
                    idSpan.className = 'data-item-id';
                    idSpan.textContent = String(u.user_id);
                    const valSpan = document.createElement('span');
                    valSpan.className = 'data-item-value';
                    valSpan.textContent = `${u.message_count.toLocaleString()} messages`;
                    item.appendChild(idSpan);
                    item.appendChild(valSpan);
                    usersList.appendChild(item);
                });
            }
        }

    } catch (error) {
        console.error('Failed to load DB stats:', error);
        showToast('Failed to load database stats', { type: 'error' });
    }
}

async function clearHistory(): Promise<void> {
    const confirmed = await showConfirmDialog('⚠️ This will permanently delete ALL chat history. Continue?');
    if (!confirmed) {
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

function getSelectedChannelIds(): string[] {
    const checkboxes = document.querySelectorAll<HTMLInputElement>('.data-item-checkbox:checked');
    return Array.from(checkboxes).map(cb => cb.dataset.channelId!).filter(Boolean);
}

function updateChannelSelectionUI(): void {
    const selected = getSelectedChannelIds();
    const controls = document.getElementById('channel-selection-controls');
    const countEl = document.getElementById('channel-selection-count');
    if (controls) {
        controls.style.display = selected.length > 0 ? 'flex' : 'none';
    }
    if (countEl) {
        countEl.textContent = `${selected.length} selected`;
    }
}

async function deleteSelectedChannels(): Promise<void> {
    const channelIds = getSelectedChannelIds();
    if (channelIds.length === 0) {
        showToast('No channels selected', { type: 'warning' });
        return;
    }

    const confirmed = await showConfirmDialog(`⚠️ Delete history for ${channelIds.length} channel(s)? This cannot be undone.`);
    if (!confirmed) {
        return;
    }

    try {
        // Pass channel IDs as strings to avoid JavaScript Number precision loss for Discord Snowflake IDs
        const count = await invoke<number>('delete_channels_history', { channelIds: channelIds });
        showToast(`Deleted ${count.toLocaleString()} messages from ${channelIds.length} channel(s)`, { type: 'success' });
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

    const userNameInput = document.getElementById('user-name-input') as HTMLInputElement | null;
    if (userNameInput) {
        userNameInput.value = settings.userName === 'You' ? '' : settings.userName;
    }
    
    // Load AI avatar preview
    const aiAvatarImage = document.getElementById('ai-avatar-image') as HTMLImageElement | null;
    const aiAvatarPlaceholder = document.querySelector('#ai-avatar-preview .avatar-placeholder') as HTMLElement | null;
    const aiRemoveBtn = document.getElementById('btn-remove-ai-avatar') as HTMLElement | null;
    
    if (settings.aiAvatar) {
        if (aiAvatarImage) {
            aiAvatarImage.src = settings.aiAvatar;
            aiAvatarImage.classList.add('visible');
        }
        if (aiAvatarPlaceholder) aiAvatarPlaceholder.style.display = 'none';
        if (aiRemoveBtn) aiRemoveBtn.style.display = 'inline-block';
    } else {
        if (aiAvatarImage) {
            aiAvatarImage.src = '';
            aiAvatarImage.classList.remove('visible');
        }
        if (aiAvatarPlaceholder) aiAvatarPlaceholder.style.display = 'flex';
        if (aiRemoveBtn) aiRemoveBtn.style.display = 'none';
    }
    
    // Load user avatar preview
    const avatarImage = document.getElementById('avatar-image') as HTMLImageElement | null;
    const avatarPlaceholder = document.querySelector('#avatar-preview .avatar-placeholder') as HTMLElement | null;
    const removeBtn = document.getElementById('btn-remove-avatar') as HTMLElement | null;
    
    if (settings.userAvatar) {
        if (avatarImage) {
            avatarImage.src = settings.userAvatar;
            avatarImage.classList.add('visible');
        }
        if (avatarPlaceholder) avatarPlaceholder.style.display = 'none';
        if (removeBtn) removeBtn.style.display = 'inline-block';
    } else {
        if (avatarImage) {
            avatarImage.src = '';
            avatarImage.classList.remove('visible');
        }
        if (avatarPlaceholder) avatarPlaceholder.style.display = 'flex';
        if (removeBtn) removeBtn.style.display = 'none';
    }
    
    // Load creator checkbox
    const creatorCheckbox = document.getElementById('creator-toggle') as HTMLInputElement | null;
    if (creatorCheckbox) {
        creatorCheckbox.checked = settings.isCreator;
    }
    
    // Load profile from server
    if (chatManager?.connected) {
        chatManager.send({ type: 'get_profile' });
    }
}

// Track which avatar we're editing
let currentAvatarTarget: 'user' | 'ai' = 'user';

function handleAvatarUpload(file: File, target: 'user' | 'ai' = 'user'): void {
    if (!file.type.startsWith('image/')) {
        showToast('Please select an image file', { type: 'error' });
        return;
    }
    
    if (file.size > 5 * 1024 * 1024) { // 5MB limit for cropping
        showToast('Image must be less than 5MB', { type: 'error' });
        return;
    }
    
    currentAvatarTarget = target;
    
    const reader = new FileReader();
    reader.onload = (e) => {
        const dataUrl = e.target?.result as string;
        openAvatarCropModal(dataUrl);
    };
    reader.readAsDataURL(file);
}

// Avatar Cropper State
let cropState = {
    imageUrl: '',
    zoom: 100,
    offsetX: 0,
    offsetY: 0,
    isDragging: false,
    startX: 0,
    startY: 0,
    imgWidth: 0,
    imgHeight: 0
};

// Store bound functions for proper cleanup
let boundOnDrag: ((e: MouseEvent) => void) | null = null;
let boundOnDragTouch: ((e: TouchEvent) => void) | null = null;
let boundEndDrag: (() => void) | null = null;

function openAvatarCropModal(imageUrl: string): void {
    cropState = {
        imageUrl,
        zoom: 100,
        offsetX: 0,
        offsetY: 0,
        isDragging: false,
        startX: 0,
        startY: 0,
        imgWidth: 0,
        imgHeight: 0
    };
    
    const modal = document.getElementById('avatar-crop-modal');
    const cropImage = document.getElementById('crop-image') as HTMLImageElement;
    const zoomSlider = document.getElementById('crop-zoom') as HTMLInputElement;
    
    if (!modal || !cropImage || !zoomSlider) return;
    
    // Load image to get dimensions
    cropImage.onload = () => {
        const cropArea = document.getElementById('crop-area');
        if (!cropArea) return;
        
        const areaSize = 280;
        const scale = Math.max(areaSize / cropImage.naturalWidth, areaSize / cropImage.naturalHeight);
        cropState.imgWidth = cropImage.naturalWidth * scale;
        cropState.imgHeight = cropImage.naturalHeight * scale;
        
        // Center the image
        cropState.offsetX = (areaSize - cropState.imgWidth) / 2;
        cropState.offsetY = (areaSize - cropState.imgHeight) / 2;
        
        updateCropPreview();
    };
    
    cropImage.src = imageUrl;
    zoomSlider.value = '100';
    modal.style.display = 'flex';
    
    // Setup event listeners
    setupCropEventListeners();
}

function setupCropEventListeners(): void {
    const cropArea = document.getElementById('crop-area');
    const zoomSlider = document.getElementById('crop-zoom') as HTMLInputElement;
    const saveBtn = document.getElementById('btn-crop-save');
    const cancelBtn = document.getElementById('btn-crop-cancel');
    const closeBtn = document.getElementById('avatar-crop-close');
    const modal = document.getElementById('avatar-crop-modal');
    
    if (!cropArea || !zoomSlider || !saveBtn || !cancelBtn || !closeBtn || !modal) return;
    
    // Remove old listeners by cloning
    const newCropArea = cropArea.cloneNode(true) as HTMLElement;
    cropArea.parentNode?.replaceChild(newCropArea, cropArea);
    
    // Create bound functions for proper cleanup
    boundOnDrag = onDrag;
    boundOnDragTouch = onDragTouch;
    boundEndDrag = endDrag;
    
    // Mouse/touch drag
    newCropArea.addEventListener('mousedown', startDrag);
    newCropArea.addEventListener('touchstart', startDragTouch, { passive: false });
    document.addEventListener('mousemove', boundOnDrag);
    document.addEventListener('touchmove', boundOnDragTouch, { passive: false });
    document.addEventListener('mouseup', boundEndDrag);
    document.addEventListener('touchend', boundEndDrag);
    
    // Zoom
    zoomSlider.oninput = () => {
        cropState.zoom = parseInt(zoomSlider.value);
        updateCropPreview();
    };
    
    // Save
    saveBtn.onclick = () => {
        saveCroppedAvatar();
        closeCropModal();
    };
    
    // Cancel/Close
    cancelBtn.onclick = closeCropModal;
    closeBtn.onclick = closeCropModal;
    modal.onclick = (e) => {
        if (e.target === modal) closeCropModal();
    };
}

function startDrag(e: MouseEvent): void {
    cropState.isDragging = true;
    cropState.startX = e.clientX - cropState.offsetX;
    cropState.startY = e.clientY - cropState.offsetY;
}

function startDragTouch(e: TouchEvent): void {
    e.preventDefault();
    cropState.isDragging = true;
    const touch = e.touches[0];
    cropState.startX = touch.clientX - cropState.offsetX;
    cropState.startY = touch.clientY - cropState.offsetY;
}

function onDrag(e: MouseEvent): void {
    if (!cropState.isDragging) return;
    cropState.offsetX = e.clientX - cropState.startX;
    cropState.offsetY = e.clientY - cropState.startY;
    updateCropPreview();
}

function onDragTouch(e: TouchEvent): void {
    if (!cropState.isDragging) return;
    e.preventDefault();
    const touch = e.touches[0];
    cropState.offsetX = touch.clientX - cropState.startX;
    cropState.offsetY = touch.clientY - cropState.startY;
    updateCropPreview();
}

function endDrag(): void {
    cropState.isDragging = false;
}

function updateCropPreview(): void {
    const cropImage = document.getElementById('crop-image') as HTMLImageElement;
    if (!cropImage) return;
    
    const scale = cropState.zoom / 100;
    const width = cropState.imgWidth * scale;
    const height = cropState.imgHeight * scale;
    
    cropImage.style.width = `${width}px`;
    cropImage.style.height = `${height}px`;
    cropImage.style.left = `${cropState.offsetX}px`;
    cropImage.style.top = `${cropState.offsetY}px`;
}

function saveCroppedAvatar(): void {
    const cropImage = document.getElementById('crop-image') as HTMLImageElement;
    if (!cropImage) return;
    
    // Create canvas to crop the circular area
    const canvas = document.createElement('canvas');
    const size = 200; // Output size
    canvas.width = size;
    canvas.height = size;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    
    // Calculate crop area (center of crop-area is 140,140 and circle is 200x200)
    const areaCenter = 140;
    const circleRadius = 100;
    
    const scale = cropState.zoom / 100;
    const imgWidth = cropState.imgWidth * scale;
    const imgHeight = cropState.imgHeight * scale;
    
    // Calculate source position relative to image
    const srcX = (areaCenter - circleRadius - cropState.offsetX) / scale * (cropImage.naturalWidth / cropState.imgWidth);
    const srcY = (areaCenter - circleRadius - cropState.offsetY) / scale * (cropImage.naturalHeight / cropState.imgHeight);
    const srcSize = (circleRadius * 2) / scale * (cropImage.naturalWidth / cropState.imgWidth);
    
    // Draw circular clip
    ctx.beginPath();
    ctx.arc(size / 2, size / 2, size / 2, 0, Math.PI * 2);
    ctx.closePath();
    ctx.clip();
    
    // Draw image
    ctx.drawImage(cropImage, srcX, srcY, srcSize, srcSize, 0, 0, size, size);
    
    // Get data URL
    const croppedDataUrl = canvas.toDataURL('image/png');
    
    // Save to appropriate setting based on target
    if (currentAvatarTarget === 'ai') {
        settings.aiAvatar = croppedDataUrl;
        saveSettings();
        
        // Update AI avatar preview
        const avatarImage = document.getElementById('ai-avatar-image') as HTMLImageElement;
        const avatarPlaceholder = document.querySelector('#ai-avatar-preview .avatar-placeholder') as HTMLElement;
        const removeBtn = document.getElementById('btn-remove-ai-avatar') as HTMLElement;
        
        if (avatarImage) {
            avatarImage.src = croppedDataUrl;
            avatarImage.classList.add('visible');
        }
        if (avatarPlaceholder) avatarPlaceholder.style.display = 'none';
        if (removeBtn) removeBtn.style.display = 'inline-block';
        
        showToast('AI Avatar updated! 🤖', { type: 'success' });
    } else {
        settings.userAvatar = croppedDataUrl;
        saveSettings();
        
        // Update user avatar preview
        const avatarImage = document.getElementById('avatar-image') as HTMLImageElement;
        const avatarPlaceholder = document.querySelector('#avatar-preview .avatar-placeholder') as HTMLElement;
        const removeBtn = document.getElementById('btn-remove-avatar') as HTMLElement;
        
        if (avatarImage) {
            avatarImage.src = croppedDataUrl;
            avatarImage.classList.add('visible');
        }
        if (avatarPlaceholder) avatarPlaceholder.style.display = 'none';
        if (removeBtn) removeBtn.style.display = 'inline-block';
        
        showToast('Avatar updated! 🎉', { type: 'success' });
    }
    
    // Refresh chat to show new avatar
    if (chatManager) {
        chatManager.renderMessages();
    }
}

function closeCropModal(): void {
    const modal = document.getElementById('avatar-crop-modal');
    if (modal) modal.style.display = 'none';
    
    // Clean up listeners using stored bound functions
    if (boundOnDrag) {
        document.removeEventListener('mousemove', boundOnDrag);
        boundOnDrag = null;
    }
    if (boundEndDrag) {
        document.removeEventListener('mouseup', boundEndDrag);
        document.removeEventListener('touchend', boundEndDrag);
        boundEndDrag = null;
    }
    if (boundOnDragTouch) {
        document.removeEventListener('touchmove', boundOnDragTouch);
        boundOnDragTouch = null;
    }
}

function removeAvatar(target: 'user' | 'ai' = 'user'): void {
    if (target === 'ai') {
        settings.aiAvatar = '';
        saveSettings();
        
        const avatarImage = document.getElementById('ai-avatar-image') as HTMLImageElement;
        const avatarPlaceholder = document.querySelector('#ai-avatar-preview .avatar-placeholder') as HTMLElement;
        const removeBtn = document.getElementById('btn-remove-ai-avatar') as HTMLElement;
        
        if (avatarImage) {
            avatarImage.src = '';
            avatarImage.classList.remove('visible');
        }
        if (avatarPlaceholder) avatarPlaceholder.style.display = 'flex';
        if (removeBtn) removeBtn.style.display = 'none';
        
        showToast('AI Avatar removed', { type: 'info' });
    } else {
        settings.userAvatar = '';
        saveSettings();
        
        const avatarImage = document.getElementById('avatar-image') as HTMLImageElement;
        const avatarPlaceholder = document.querySelector('#avatar-preview .avatar-placeholder') as HTMLElement;
        const removeBtn = document.getElementById('btn-remove-avatar') as HTMLElement;
        
        if (avatarImage) {
            avatarImage.src = '';
            avatarImage.classList.remove('visible');
        }
        if (avatarPlaceholder) avatarPlaceholder.style.display = 'flex';
        if (removeBtn) removeBtn.style.display = 'none';
        
        showToast('Avatar removed', { type: 'info' });
    }
    
    // Refresh chat
    if (chatManager) {
        chatManager.renderMessages();
    }
}

function saveProfileToAI(): void {
    const displayName = (document.getElementById('user-name-input') as HTMLInputElement)?.value?.trim() || 'User';
    const bio = (document.getElementById('user-bio-input') as HTMLTextAreaElement)?.value?.trim() || '';
    const preferences = (document.getElementById('user-preferences-input') as HTMLTextAreaElement)?.value?.trim() || '';
    const isCreator = (document.getElementById('creator-toggle') as HTMLInputElement)?.checked || false;
    
    if (chatManager?.connected) {
        chatManager.send({ 
            type: 'save_profile', 
            profile: { display_name: displayName, bio, preferences, is_creator: isCreator }
        });
        
        // Also update local settings
        settings.userName = displayName;
        settings.isCreator = isCreator;
        saveSettings();
    } else {
        showToast('Not connected to AI server', { type: 'error' });
    }
}

// ============================================================================
// Helpers
// ============================================================================

async function openFolder(type: string): Promise<void> {
    let path: string;
    
    try {
        if (type === 'logs') {
            path = await invoke<string>('get_logs_path');
        } else if (type === 'data') {
            path = await invoke<string>('get_data_path');
        } else {
            showToast('Unknown folder type', { type: 'error' });
            return;
        }

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
window.chatManager = null; // Updated in initChatManager()
window.showPage = switchPage; // Alias for HTML onclick handlers
window.startBot = startBot;
