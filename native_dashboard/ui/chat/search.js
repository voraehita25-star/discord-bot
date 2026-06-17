/**
 * In-conversation search (#14) — Ctrl+F overlay that highlights matches
 * inside the currently-rendered chat messages and steps through them with
 * ↑/↓. Extracted from ChatManager so the ~150 lines of DOM traversal +
 * match-wrapping don't clutter the main orchestrator.
 *
 * Public API:
 *   const search = new ChatSearch(() => document.getElementById('chat-messages'));
 *   search.open();            // show bar + focus input
 *   search.close();           // hide + clear highlights
 *   search.setup();           // bind input/keydown/buttons once per DOM lifetime
 *
 * The search is DOM-only: it walks live text nodes inside the chat messages
 * container and wraps matches in <mark class="chat-search-hit">. Because
 * renderMessages() replaces container.innerHTML, highlights are wiped
 * naturally on every re-render — callers don't need to call clear() first.
 */
export class ChatSearch {
    constructor(getContainer) {
        this.matches = [];
        this.currentIdx = -1;
        this.bound = false;
        this.previousFocus = null;
        this.getContainer = getContainer;
    }
    open() {
        const bar = document.getElementById('chat-search-bar');
        const input = document.getElementById('chat-search-input');
        if (!bar || !input)
            return;
        // Re-entrant open() (repeated Ctrl+F while the bar is already visible)
        // must NOT recapture previousFocus — document.activeElement would now be
        // the search input itself, overwriting the real pre-open target and
        // breaking focus restoration on Escape. Just re-focus and bail.
        if (!bar.classList.contains('hidden')) {
            input.focus();
            input.select();
            return;
        }
        // Remember what had focus so close() can restore it — otherwise
        // keyboard focus is left on the now-hidden search bar.
        this.previousFocus = document.activeElement;
        bar.classList.remove('hidden');
        input.focus();
        input.select();
    }
    close() {
        const bar = document.getElementById('chat-search-bar');
        if (!bar)
            return;
        bar.classList.add('hidden');
        this.clearHighlights();
        this.matches = [];
        this.currentIdx = -1;
        // Restore focus to the pre-open element (e.g. the chat input).
        if (this.previousFocus && document.contains(this.previousFocus)) {
            this.previousFocus.focus();
        }
        this.previousFocus = null;
    }
    /** Wire input/keydown/buttons once per DOM lifetime — idempotent. */
    setup() {
        const input = document.getElementById('chat-search-input');
        const bar = document.getElementById('chat-search-bar');
        if (!input || !bar || bar.dataset.searchBound || this.bound)
            return;
        let debounce = null;
        input.addEventListener('input', () => {
            if (debounce !== null)
                clearTimeout(debounce);
            debounce = window.setTimeout(() => {
                this.perform(input.value);
                debounce = null;
            }, 120);
        });
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                this.step(e.shiftKey ? -1 : 1);
            }
            else if (e.key === 'Escape') {
                e.preventDefault();
                this.close();
            }
        });
        document.getElementById('chat-search-next')?.addEventListener('click', () => this.step(1));
        document.getElementById('chat-search-prev')?.addEventListener('click', () => this.step(-1));
        document.getElementById('chat-search-close')?.addEventListener('click', () => this.close());
        bar.dataset.searchBound = '1';
        this.bound = true;
    }
    perform(query) {
        this.clearHighlights();
        this.matches = [];
        this.currentIdx = -1;
        const container = this.getContainer();
        const countEl = document.getElementById('chat-search-count');
        if (!container)
            return;
        if (query) {
            this.matches = wrapMatches(container, query);
            if (this.matches.length > 0) {
                this.focus(0);
            }
        }
        if (countEl) {
            countEl.textContent = `${this.matches.length ? this.currentIdx + 1 : 0} / ${this.matches.length}`;
        }
    }
    step(direction) {
        if (this.matches.length === 0)
            return;
        // The <mark> nodes in this.matches are detached when renderMessages()
        // replaces container.innerHTML — stepping onto a detached node would
        // scrollIntoView() a no-op and display a stale count. Re-run the search
        // against the current DOM before stepping if our matches are stale.
        if (this.matches.some(m => !m.isConnected)) {
            const input = document.getElementById('chat-search-input');
            this.perform(input?.value ?? '');
            return;
        }
        this.focus(this.currentIdx + direction);
    }
    focus(idx) {
        if (this.matches.length === 0)
            return;
        idx = ((idx % this.matches.length) + this.matches.length) % this.matches.length;
        this.matches.forEach(m => m.classList.remove('active'));
        const target = this.matches[idx];
        target.classList.add('active');
        target.scrollIntoView({ block: 'center', behavior: 'smooth' });
        this.currentIdx = idx;
        const countEl = document.getElementById('chat-search-count');
        if (countEl)
            countEl.textContent = `${idx + 1} / ${this.matches.length}`;
    }
    clearHighlights() {
        const container = this.getContainer();
        if (!container)
            return;
        container.querySelectorAll('mark.chat-search-hit').forEach(mark => {
            const parent = mark.parentNode;
            if (!parent)
                return;
            // Unwrap <mark> by replacing with its text content.
            parent.replaceChild(document.createTextNode(mark.textContent || ''), mark);
            parent.normalize();
        });
    }
}
/** Find all text nodes within a root that contain `query` (case-insensitive),
 *  wrap each hit in <mark class="chat-search-hit">, and return the marks. */
function wrapMatches(root, query) {
    if (!query)
        return [];
    // Cap the number of candidate TEXT NODES we collect (below) so a short query
    // against a giant history can't lock the main thread. The per-highlight cap
    // (total <mark>s) is enforced separately by the hits.length >= MAX_HITS check
    // further down; both happen to use this same bound.
    const MAX_HITS = 1000;
    const hits = [];
    const needle = query.toLowerCase();
    // TreeWalker over text nodes, skipping <script>/<style>/<mark> and hidden nodes.
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
        acceptNode: (node) => {
            const parent = node.parentElement;
            if (!parent)
                return NodeFilter.FILTER_REJECT;
            const tag = parent.tagName;
            if (tag === 'SCRIPT' || tag === 'STYLE' || tag === 'MARK')
                return NodeFilter.FILTER_REJECT;
            if (!node.nodeValue || !node.nodeValue.toLowerCase().includes(needle))
                return NodeFilter.FILTER_SKIP;
            return NodeFilter.FILTER_ACCEPT;
        },
    });
    // Collect first so we can mutate the DOM without breaking iteration.
    const candidates = [];
    let n = walker.nextNode();
    while (n) {
        candidates.push(n);
        if (candidates.length >= MAX_HITS)
            break;
        n = walker.nextNode();
    }
    outer: for (const textNode of candidates) {
        const text = textNode.nodeValue || '';
        const lower = text.toLowerCase();
        let idx = 0;
        let start = lower.indexOf(needle, idx);
        if (start < 0)
            continue;
        const fragment = document.createDocumentFragment();
        while (start >= 0) {
            if (start > idx) {
                fragment.appendChild(document.createTextNode(text.slice(idx, start)));
            }
            const mark = document.createElement('mark');
            mark.className = 'chat-search-hit';
            // `start` is an offset in `lower` (= text.toLowerCase()), so the
            // matched span has `needle.length` code units. Using query.length
            // would diverge whenever toLowerCase changes length (Turkish dotted
            // İ → i̇, etc.) and shift later highlights by one.
            mark.textContent = text.slice(start, start + needle.length);
            fragment.appendChild(mark);
            hits.push(mark);
            idx = start + needle.length;
            if (hits.length >= MAX_HITS) {
                if (idx < text.length) {
                    fragment.appendChild(document.createTextNode(text.slice(idx)));
                }
                textNode.replaceWith(fragment);
                break outer;
            }
            start = lower.indexOf(needle, idx);
        }
        if (idx < text.length) {
            fragment.appendChild(document.createTextNode(text.slice(idx)));
        }
        textNode.replaceWith(fragment);
    }
    return hits;
}
//# sourceMappingURL=search.js.map