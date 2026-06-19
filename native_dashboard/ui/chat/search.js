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
    matches = [];
    currentIdx = -1;
    bound = false;
    previousFocus = null;
    getContainer;
    constructor(getContainer) {
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
    /** True when the last perform() hit MAX_HITS (or the candidate-node cap) and
     *  stopped early — used to append a "+" to the count so the user knows more
     *  matches exist beyond the highlighted ones. */
    truncated = false;
    perform(query) {
        this.clearHighlights();
        this.matches = [];
        this.currentIdx = -1;
        this.truncated = false;
        const container = this.getContainer();
        const countEl = document.getElementById('chat-search-count');
        if (!container)
            return;
        if (query) {
            const result = wrapMatches(container, query);
            this.matches = result.marks;
            this.truncated = result.truncated;
            if (this.matches.length > 0) {
                this.focus(0);
            }
        }
        if (countEl) {
            countEl.textContent = this.formatCount(this.matches.length ? this.currentIdx + 1 : 0);
        }
    }
    /** Build the "current / total" label, appending a "+" + hint when the
     *  highlight pass was capped so the user knows there are more matches than
     *  the N shown. */
    formatCount(current) {
        const total = this.matches.length;
        if (this.truncated && total > 0) {
            return `${current} / ${total}+ (showing first ${total})`;
        }
        return `${current} / ${total}`;
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
            countEl.textContent = this.formatCount(idx + 1);
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
/** Escape a string so it can be embedded literally in a RegExp. */
function escapeRegExp(s) {
    return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}
/** Find all text nodes within a root that contain `query` (case-insensitive),
 *  wrap each hit in <mark class="chat-search-hit">, and return the marks +
 *  whether the pass was capped. */
function wrapMatches(root, query) {
    if (!query)
        return { marks: [], truncated: false };
    // Two independent caps, both protecting the main thread on a short query
    // against a giant history:
    //   - MAX_CANDIDATE_NODES bounds how many matching TEXT NODES we collect
    //     (the TreeWalker scan). A node may contain many hits, so this is a
    //     coarser bound than the hit cap.
    //   - MAX_HITS bounds the total number of <mark> elements we create (the
    //     DOM-mutation + scroll-target cost). This is the one the user-facing
    //     "showing first N" hint is keyed to.
    // Splitting them (was a single shared 1000) lets us scan more nodes than we
    // ultimately highlight, so a few hit-dense nodes don't starve the scan of
    // later sparse-but-present matches.
    const MAX_CANDIDATE_NODES = 5000;
    const MAX_HITS = 1000;
    const hits = [];
    let truncated = false;
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
            // Pre-filter to skip nodes that can't possibly hit, so the scan
            // doesn't compile a regex per text node on a huge history. NOTE:
            // this uses toLowerCase().includes() while the wrapping pass below
            // matches with /gi — case-folding parity between the two is
            // best-effort ASCII. A handful of code points fold differently
            // under the two paths (e.g. Turkish İ, Kelvin sign), so a node the
            // regex *would* hit could be skipped here, under-counting. That's a
            // rare cosmetic miss on exotic input, accepted to keep the scan
            // cheap; the offsets we DO produce stay correct (the regex owns them).
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
        if (candidates.length >= MAX_CANDIDATE_NODES) {
            // Stopped scanning early. Peek one node further: only flag truncation
            // if there's genuinely more to scan. At EXACTLY MAX_CANDIDATE_NODES
            // matching nodes with nothing after, the peek is null and we must
            // NOT show a false "+N" hint.
            if (walker.nextNode() !== null)
                truncated = true;
            break;
        }
        n = walker.nextNode();
    }
    outer: for (let ci = 0; ci < candidates.length; ci++) {
        const textNode = candidates[ci];
        const text = textNode.nodeValue || '';
        // Match against the ORIGINAL text with a case-insensitive regex so the
        // hit's offset AND length come from `text` directly. Deriving offsets
        // from a lowercased copy (text.toLowerCase().indexOf) breaks whenever
        // toLowerCase changes length (Turkish dotted İ → i̇, etc.): the offset
        // refers to the lowercased string but the slice indexes the original,
        // shifting later highlights.
        const re = new RegExp(escapeRegExp(query), 'gi');
        let idx = 0;
        let foundAny = false;
        const fragment = document.createDocumentFragment();
        for (const m of text.matchAll(re)) {
            const start = m.index;
            const matched = m[0];
            // Zero-length matches can't happen for a non-empty escaped literal,
            // but guard anyway so matchAll never spins.
            if (matched.length === 0)
                continue;
            foundAny = true;
            if (start > idx) {
                fragment.appendChild(document.createTextNode(text.slice(idx, start)));
            }
            const mark = document.createElement('mark');
            mark.className = 'chat-search-hit';
            mark.textContent = matched; // preserves original case
            fragment.appendChild(mark);
            hits.push(mark);
            idx = start + matched.length;
            if (hits.length >= MAX_HITS) {
                const tail = idx < text.length;
                if (tail) {
                    fragment.appendChild(document.createTextNode(text.slice(idx)));
                }
                textNode.replaceWith(fragment);
                // Hit the highlight cap. Only claim truncation when more matches
                // can PROVABLY exist: either this node still has unscanned text
                // after the last hit (`tail`), or there's at least one more
                // candidate node to come. At exactly MAX_HITS landing on the last
                // hit of the last candidate, neither holds → no false "+N".
                if (tail || ci < candidates.length - 1)
                    truncated = true;
                break outer;
            }
        }
        if (!foundAny)
            continue;
        if (idx < text.length) {
            fragment.appendChild(document.createTextNode(text.slice(idx)));
        }
        textNode.replaceWith(fragment);
    }
    return { marks: hits, truncated };
}
//# sourceMappingURL=search.js.map