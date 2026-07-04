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
    cache = new Map();
    /** Estimated tokens (~4 chars each) of documents attached AFTER the last
     *  real usage reading, per conversation. Session-scoped, not persisted:
     *  the next real token_usage frame already includes the injected document
     *  text, so it supersedes + clears the estimate — no double counting. */
    pendingDocTokens = new Map();
    /** Load persisted cache. Call once at startup (ChatManager.connect() does this). */
    load() {
        try {
            const raw = localStorage.getItem(LS_KEY);
            if (!raw)
                return;
            const parsed = JSON.parse(raw);
            // Shape check — localStorage is user-writable, so a tampered or
            // partially-corrupted value could be a string/array/null and
            // crash ``Object.entries`` later. Refuse anything that isn't a
            // plain non-null object.
            if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
                return;
            }
            const out = new Map();
            for (const [k, v] of Object.entries(parsed)) {
                if (typeof v !== 'object' || v === null)
                    continue;
                const u = v;
                // Reject NaN/non-finite numbers — they would propagate into
                // ``pct`` math and render "NaN%" in the UI forever until
                // localStorage is cleared.
                if (typeof u.input_tokens !== 'number' || !Number.isFinite(u.input_tokens))
                    continue;
                if (typeof u.output_tokens !== 'number' || !Number.isFinite(u.output_tokens))
                    continue;
                if (typeof u.context_window !== 'number' || !Number.isFinite(u.context_window))
                    continue;
                // Mirror update()'s domain guards so a tampered/stale entry with
                // a non-positive context_window or negative token counts is
                // rejected on restore the same way it would be refused on write.
                if (u.context_window <= 0)
                    continue;
                if (u.input_tokens < 0 || u.output_tokens < 0)
                    continue;
                const total = typeof u.total_tokens === 'number' && Number.isFinite(u.total_tokens)
                    ? u.total_tokens
                    : u.input_tokens + u.output_tokens;
                out.set(k, {
                    input_tokens: u.input_tokens,
                    output_tokens: u.output_tokens,
                    total_tokens: total,
                    context_window: u.context_window,
                });
            }
            this.cache = out;
        }
        catch {
            // Ignore corrupt cache — starting fresh is harmless.
        }
    }
    /** Paint the bar from a fresh usage reading + cache it for the given conversation. */
    update(conversationId, usage) {
        const { input_tokens, output_tokens, context_window } = usage;
        // Validate on WRITE, mirroring load(): a single WS frame with a
        // NaN/negative token count would otherwise be cached + persisted and
        // render "NaN%" forever on every later restore().
        if (!Number.isFinite(input_tokens) ||
            !Number.isFinite(output_tokens) ||
            !Number.isFinite(context_window) ||
            context_window <= 0 ||
            input_tokens < 0 ||
            output_tokens < 0) {
            return;
        }
        if (conversationId) {
            // A real reading supersedes any attached-file estimate (the
            // injected documents are part of this turn's actual input).
            this.pendingDocTokens.delete(conversationId);
            // Move-to-end LRU: ``cache.set`` only refreshes insertion order
            // when the key is new. For an existing key it keeps the
            // original position, defeating the LRU trim in ``save()``
            // which slices off the FRONT of the iteration order. Delete
            // first so a re-update always lands at the end of the order.
            this.cache.delete(conversationId);
            // Store a NORMALIZED object so the cached/persisted total_tokens is
            // always finite and == input+output (the raw frame's total_tokens is
            // never validated above, and paint()/load() assume that invariant).
            this.cache.set(conversationId, {
                input_tokens,
                output_tokens,
                context_window,
                total_tokens: input_tokens + output_tokens,
            });
            // Bound the in-memory Map to the same cap save() enforces on the
            // persisted payload (oldest = front of insertion order).
            while (this.cache.size > MAX_CACHE_SIZE) {
                const oldest = this.cache.keys().next().value;
                if (oldest === undefined)
                    break;
                this.cache.delete(oldest);
            }
            this.save();
        }
        this.paint(usage);
    }
    /**
     * Render the bar from a usage reading. Pure DOM paint — NO cache or
     * localStorage writes — so restore() can repaint on a conversation switch
     * without forcing a wasted save() each time.
     */
    paint(usage) {
        const indicator = document.getElementById('context-window-indicator');
        const fill = document.getElementById('context-bar-fill');
        const label = document.getElementById('context-bar-label');
        if (!indicator || !fill || !label)
            return;
        const { input_tokens, output_tokens, context_window } = usage;
        if (!Number.isFinite(input_tokens) ||
            !Number.isFinite(output_tokens) ||
            !Number.isFinite(context_window) ||
            context_window <= 0) {
            return;
        }
        const total = input_tokens + output_tokens;
        const pct = Math.max(0, Math.min((total / context_window) * 100, 100));
        // The element ships with the `hidden` class (`display:none !important`
        // in styles.css), which an inline style CANNOT override — so toggling
        // only `style.display` left the bar invisible forever. Remove the
        // class to actually reveal it; reset() re-adds it.
        indicator.classList.remove('hidden');
        indicator.style.display = 'flex';
        // Keep the progressbar semantics in sync (index.html carries
        // role="progressbar" + aria-valuemin/max on the indicator).
        indicator.setAttribute('aria-valuenow', pct.toFixed(0));
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
        if (indicator) {
            indicator.classList.add('hidden');
            indicator.style.display = 'none';
            indicator.setAttribute('aria-valuenow', '0');
        }
    }
    /** Paint the bar from the cached reading for a conversation (or hide if none). */
    restore(conversationId) {
        const cached = this.cache.get(conversationId);
        if (cached) {
            // In-memory LRU touch so a frequently-read conversation isn't
            // evicted before never-read ones (Map ordering is otherwise by
            // insertion only — see comment in ``update``). No save() here:
            // restore is a read/repaint, not a data change, and persisting on
            // every conversation switch was a wasted localStorage write. The
            // promotion is persisted on the next real update().
            this.cache.delete(conversationId);
            this.cache.set(conversationId, cached);
            this.paint(this.withPending(conversationId, cached));
        }
        else {
            this.reset();
        }
    }
    /**
     * Fold freshly-attached document text into the bar as an ESTIMATE
     * (~4 chars/token), so the meter reacts the moment a file is saved to the
     * conversation instead of waiting for the next turn's real usage frame
     * (which then replaces the estimate with actual numbers).
     */
    addPendingDocumentChars(conversationId, chars) {
        if (!conversationId || !Number.isFinite(chars) || chars <= 0)
            return;
        const tokens = Math.ceil(chars / 4);
        this.pendingDocTokens.set(conversationId, (this.pendingDocTokens.get(conversationId) ?? 0) + tokens);
        const cached = this.cache.get(conversationId);
        if (cached)
            this.paint(this.withPending(conversationId, cached));
    }
    /** Overlay a conversation's pending-document estimate onto a usage reading. */
    withPending(conversationId, usage) {
        const pending = this.pendingDocTokens.get(conversationId) ?? 0;
        if (pending <= 0)
            return usage;
        return {
            ...usage,
            input_tokens: usage.input_tokens + pending,
            total_tokens: usage.total_tokens + pending,
        };
    }
    /** Drop one conversation's cached usage (called on conversation delete). */
    forget(conversationId) {
        this.pendingDocTokens.delete(conversationId);
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