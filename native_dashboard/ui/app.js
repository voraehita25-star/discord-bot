// Tauri API (v2)
const { invoke } = window.__TAURI__.core;

// State
let currentPage = 'status';
let refreshInterval = null;

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    initNavigation();
    startRefreshLoop();
    loadAllData();
    initSakuraAnimation();
});

// Sakura Petals Animation
function initSakuraAnimation() {
    const container = document.getElementById('sakura-container');
    if (!container) return;

    // Petal SVG shapes - variety of sakura petal designs
    const petalShapes = [
        // Classic sakura petal
        `<svg viewBox="0 0 40 40"><path d="M20 0 C25 10, 35 15, 40 20 C35 25, 25 30, 20 40 C15 30, 5 25, 0 20 C5 15, 15 10, 20 0" fill="currentColor"/></svg>`,
        // Round petal
        `<svg viewBox="0 0 40 40"><ellipse cx="20" cy="20" rx="18" ry="12" fill="currentColor"/></svg>`,
        // Heart-shaped petal
        `<svg viewBox="0 0 40 40"><path d="M20 35 C10 25, 0 15, 10 5 C15 0, 20 5, 20 10 C20 5, 25 0, 30 5 C40 15, 30 25, 20 35" fill="currentColor"/></svg>`,
        // Simple oval
        `<svg viewBox="0 0 40 40"><ellipse cx="20" cy="20" rx="10" ry="18" fill="currentColor"/></svg>`,
        // Pointed petal
        `<svg viewBox="0 0 40 40"><path d="M20 0 C30 15, 30 25, 20 40 C10 25, 10 15, 20 0" fill="currentColor"/></svg>`,
        // Wide petal
        `<svg viewBox="0 0 40 40"><path d="M20 5 C35 10, 40 20, 35 30 C25 40, 15 40, 5 30 C0 20, 5 10, 20 5" fill="currentColor"/></svg>`,
        // Double curve
        `<svg viewBox="0 0 40 40"><path d="M20 0 C35 5, 40 20, 35 35 C20 40, 5 35, 0 20 C5 5, 15 0, 20 0" fill="currentColor"/></svg>`,
        // Star-like
        `<svg viewBox="0 0 40 40"><path d="M20 0 L25 15 L40 20 L25 25 L20 40 L15 25 L0 20 L15 15 Z" fill="currentColor"/></svg>`
    ];

    // Color palette - various sakura pink shades
    const colors = [
        'rgba(255, 183, 197, 0.9)',  // Light pink
        'rgba(255, 145, 175, 0.85)', // Medium pink
        'rgba(255, 107, 157, 0.8)',  // Hot pink
        'rgba(255, 192, 203, 0.9)',  // Pink
        'rgba(255, 174, 201, 0.85)', // Soft pink
        'rgba(255, 209, 220, 0.9)',  // Pale pink
        'rgba(255, 130, 171, 0.8)',  // Rose pink
        'rgba(248, 200, 220, 0.9)',  // Blush
        'rgba(255, 160, 190, 0.85)', // Coral pink
        'rgba(255, 220, 230, 0.9)'   // Very light pink
    ];

    function createPetal() {
        const petal = document.createElement('div');
        petal.className = 'sakura-petal';

        // Random properties
        const size = Math.random() * 20 + 10; // 10-30px
        const startX = Math.random() * window.innerWidth;
        const duration = Math.random() * 8 + 8; // 8-16s
        const delay = Math.random() * 2;
        const rotateStart = Math.random() * 360;
        const rotateEnd = rotateStart + (Math.random() * 720 - 360);
        const swayAmount = Math.random() * 100 + 50;
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
            filter: blur(${Math.random() < 0.3 ? '1px' : '0px'}) drop-shadow(0 0 ${Math.random() * 5 + 2}px ${color});
            animation: sakuraFall${Math.floor(Math.random() * 3)} ${duration}s linear ${delay}s infinite;
            --sway: ${swayAmount}px;
            --rotate-start: ${rotateStart}deg;
            --rotate-end: ${rotateEnd}deg;
        `;

        container.appendChild(petal);
        return petal;
    }

    // Create initial petals
    for (let i = 0; i < 35; i++) {
        setTimeout(() => createPetal(), i * 200);
    }

    // Continuously create new petals
    setInterval(() => {
        if (container.children.length < 50) {
            createPetal();
        }
    }, 800);
}

// Navigation
function initNavigation() {
    document.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', () => {
            const page = item.dataset.page;
            switchPage(page);
        });
    });

    // Button handlers
    document.getElementById('btn-start').addEventListener('click', startBot);
    document.getElementById('btn-dev').addEventListener('click', startDevBot);
    document.getElementById('btn-stop').addEventListener('click', stopBot);
    document.getElementById('btn-restart').addEventListener('click', restartBot);
}

function switchPage(page) {
    currentPage = page;

    // Update nav
    document.querySelectorAll('.nav-item').forEach(item => {
        item.classList.toggle('active', item.dataset.page === page);
    });

    // Update pages
    document.querySelectorAll('.page').forEach(p => {
        p.classList.toggle('active', p.id === `page-${page}`);
    });

    // Handle logs page real-time refresh
    if (page === 'logs') {
        loadLogs();
        startLogsRefresh();  // Start real-time updates
    } else {
        stopLogsRefresh();   // Stop when leaving logs page
    }

    if (page === 'database') loadDbStats();
}

// Refresh Loop
function startRefreshLoop() {
    refreshInterval = setInterval(updateStatus, 2000);
    updateStatus();
}

async function updateStatus() {
    try {
        const status = await invoke('get_status');

        // Update status badge
        const badge = document.getElementById('status-badge');
        const statusText = badge.querySelector('.status-text');

        if (status.is_running) {
            badge.classList.add('online');
            statusText.textContent = 'Online';
        } else {
            badge.classList.remove('online');
            statusText.textContent = 'Offline';
        }

        // Update status text
        document.getElementById('bot-status-text').textContent =
            status.is_running ? 'Status: Online' : 'Status: Offline';

        // Update buttons
        document.getElementById('btn-start').disabled = status.is_running;
        document.getElementById('btn-dev').disabled = status.is_running;
        document.getElementById('btn-stop').disabled = !status.is_running;
        document.getElementById('btn-restart').disabled = !status.is_running;

        // Update stats
        document.getElementById('stat-uptime').textContent = status.uptime;
        document.getElementById('stat-mode').textContent = status.mode;
        document.getElementById('stat-memory').textContent = `${status.memory_mb.toFixed(1)} MB`;

        // Get DB stats
        const dbStats = await invoke('get_db_stats');
        document.getElementById('stat-messages').textContent = dbStats.total_messages.toLocaleString();
        document.getElementById('stat-channels').textContent = dbStats.active_channels;

    } catch (error) {
        console.error('Failed to update status:', error);
    }
}

// Bot Control
async function startBot() {
    try {
        const result = await invoke('start_bot');
        showMessage(result);
        updateStatus();
    } catch (error) {
        showMessage(error, true);
    }
}

async function stopBot() {
    try {
        const result = await invoke('stop_bot');
        showMessage(result);
        updateStatus();
    } catch (error) {
        showMessage(error, true);
    }
}

async function restartBot() {
    try {
        const result = await invoke('restart_bot');
        showMessage(result);
        updateStatus();
    } catch (error) {
        showMessage(error, true);
    }
}

async function startDevBot() {
    try {
        const result = await invoke('start_dev_bot');
        showMessage(result);
        updateStatus();
    } catch (error) {
        showMessage(error, true);
    }
}

// Logs - Real-time Streaming
let logsRefreshInterval = null;
let logsAutoScrollEnabled = true;
let lastLogCount = 0;

async function loadLogs() {
    try {
        const logs = await invoke('get_logs', { count: 200 });
        const container = document.getElementById('log-content');
        const filter = document.getElementById('log-filter').value;

        // Check if new logs arrived
        const hasNewLogs = logs.length !== lastLogCount;
        lastLogCount = logs.length;

        let html = '';
        logs.forEach(line => {
            let level = 'info';
            if (line.includes('ERROR')) level = 'error';
            else if (line.includes('WARNING')) level = 'warning';
            else if (line.includes('DEBUG')) level = 'debug';

            if (filter === 'all' || line.includes(filter)) {
                html += `<div class="log-line ${level}">${escapeHtml(line)}</div>`;
            }
        });

        container.innerHTML = html || 'No logs found.';

        // Auto-scroll only if enabled and new logs arrived
        if (logsAutoScrollEnabled && hasNewLogs) {
            container.scrollTop = container.scrollHeight;
        }
    } catch (error) {
        console.error('Failed to load logs:', error);
    }
}

function startLogsRefresh() {
    // Clear existing interval if any
    if (logsRefreshInterval) {
        clearInterval(logsRefreshInterval);
    }
    // Refresh logs every 1 second for real-time feel
    logsRefreshInterval = setInterval(loadLogs, 1000);
}

function stopLogsRefresh() {
    if (logsRefreshInterval) {
        clearInterval(logsRefreshInterval);
        logsRefreshInterval = null;
    }
}

function toggleAutoScroll() {
    logsAutoScrollEnabled = !logsAutoScrollEnabled;
    const btn = document.getElementById('btn-auto-scroll');
    if (btn) {
        btn.textContent = logsAutoScrollEnabled ? '⏸ Pause' : '▶️ Resume';
        btn.classList.toggle('paused', !logsAutoScrollEnabled);
    }
}

function clearLogs() {
    document.getElementById('log-content').innerHTML = '';
    lastLogCount = 0;
}

// Database
async function loadDbStats() {
    try {
        const stats = await invoke('get_db_stats');
        document.getElementById('db-messages').textContent = stats.total_messages.toLocaleString();
        document.getElementById('db-channels').textContent = stats.active_channels;
        document.getElementById('db-entities').textContent = stats.total_entities;
        document.getElementById('db-rag').textContent = stats.rag_memories;

        // Load channels
        const channels = await invoke('get_recent_channels', { limit: 10 });
        const channelsList = document.getElementById('channels-list');
        channelsList.innerHTML = channels.map(ch => `
            <div class="data-item">
                <span class="data-item-id">${ch.channel_id}</span>
                <span class="data-item-value">${ch.message_count} messages</span>
            </div>
        `).join('') || '<p>No channels found.</p>';

        // Load users
        const users = await invoke('get_top_users', { limit: 10 });
        const usersList = document.getElementById('users-list');
        usersList.innerHTML = users.map(u => `
            <div class="data-item">
                <span class="data-item-id">${u.user_id}</span>
                <span class="data-item-value">${u.message_count} messages</span>
            </div>
        `).join('') || '<p>No users found.</p>';

    } catch (error) {
        console.error('Failed to load DB stats:', error);
    }
}

async function clearHistory() {
    if (!confirm('⚠️ This will permanently delete ALL chat history. Continue?')) {
        return;
    }

    try {
        const count = await invoke('clear_history');
        showMessage(`Deleted ${count} messages.`);
        loadDbStats();
    } catch (error) {
        showMessage(error, true);
    }
}

// Helpers
async function openFolder(type) {
    const path = type === 'logs'
        ? 'C:\\Users\\ME\\BOT\\logs'
        : 'C:\\Users\\ME\\BOT\\data';

    await invoke('open_folder', { path });
}

function loadAllData() {
    updateStatus();
    loadLogs();
    loadDbStats();
}

function showMessage(msg, isError = false) {
    alert(isError ? `Error: ${msg}` : msg);
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
