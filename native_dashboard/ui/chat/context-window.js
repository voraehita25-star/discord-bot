/**
 * Context-window usage indicator (token bar below the chat header).
 *
 * Displays input+output tokens vs the model's context window as a percentage
 * bar with color-coded fill (green → amber ≥50% → red ≥80%). Persists the
 * last reading per conversation in localStorage so switching between chats
 * doesn't lose the indicator until the next turn.
 *
 * Extracted from ChatManager because:
 *   - Self-contained UI (3 DOM nodes: #context-window-indicator + #context-bar-fill + #context-bar-label).
 *   - Self-contained state (a Map<convId, usage> + localStorage persistence).
 *   - No coupling to messages / streaming / WS.
 *
 * Public API is a single class method per action — ChatManager holds one
 * instance and forwards calls.
 */
const LS_KEY = 'dashboard_token_usage';
const MAX_CACHE_SIZE = 200; // LRU cap so localStorage doesn't grow unbounded
export class ContextWindowIndicator {
    constructor() {
        this.cache = new Map();
    }
    /** Load persisted cache. Call once at startup (ChatManager.connect() does this). */
    load() {
        try {
            const raw = localStorage.getItem(LS_KEY);
            if (raw) {
                const obj = JSON.parse(raw);
                this.cache = new Map(Object.entries(obj));
            }
        }
        catch {
            // Ignore corrupt cache — starting fresh is harmless.
        }
    }
    /** Paint the bar from a fresh usage reading + cache it for the given conversation. */
    update(conversationId, usage) {
        const indicator = document.getElementById('context-window-indicator');
        const fill = document.getElementById('context-bar-fill');
        const label = document.getElementById('context-bar-label');
        if (!indicator || !fill || !label)
            return;
        const { input_tokens, output_tokens, context_window } = usage;
        if (!context_window || context_window <= 0)
            return;
        if (conversationId) {
            this.cache.set(conversationId, usage);
            this.save();
        }
        const total = input_tokens + output_tokens;
        const pct = Math.min((total / context_window) * 100, 100);
        indicator.style.display = 'flex';
        fill.style.width = `${pct}%`;
        fill.classList.remove('usage-moderate', 'usage-high');
        if (pct >= 80)
            fill.classList.add('usage-high');
        else if (pct >= 50)
            fill.classList.add('usage-moderate');
        const fmt = (n) => n >= 1000 ? `${(n / 1000).toFixed(1)}K` : String(n);
        label.textContent = `${fmt(total)} / ${fmt(context_window)} (${pct.toFixed(1)}%)`;
        indicator.title = `Context Window: ${input_tokens.toLocaleString()} input + ${output_tokens.toLocaleString()} output = ${total.toLocaleString()} / ${context_window.toLocaleString()} tokens`;
    }
    /** Hide the bar (no conversation loaded / empty conversation). */
    reset() {
        const indicator = document.getElementById('context-window-indicator');
        if (indicator)
            indicator.style.display = 'none';
    }
    /** Paint the bar from the cached reading for a conversation (or hide if none). */
    restore(conversationId) {
        const cached = this.cache.get(conversationId);
        if (cached)
            this.update(conversationId, cached);
        else
            this.reset();
    }
    /** Drop one conversation's cached usage (called on conversation delete). */
    forget(conversationId) {
        if (this.cache.delete(conversationId))
            this.save();
    }
    save() {
        // LRU-trim so localStorage stays bounded — keep the most recent N entries.
        const entries = Array.from(this.cache.entries());
        const toSave = entries.length > MAX_CACHE_SIZE
            ? entries.slice(entries.length - MAX_CACHE_SIZE)
            : entries;
        const obj = {};
        for (const [k, v] of toSave)
            obj[k] = v;
        try {
            localStorage.setItem(LS_KEY, JSON.stringify(obj));
        }
        catch {
            // Quota exceeded or disabled — drop silently. Worst case the user
            // loses token-usage persistence across reloads.
        }
    }
}
//# sourceMappingURL=context-window.js.map