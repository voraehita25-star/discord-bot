/**
 * Export format picker modal (#21).
 *
 * Pure, Promise-based: shows a modal with JSON / Markdown / HTML / Plain-Text
 * options and resolves with the chosen format (or null if the user dismissed).
 *
 * Extracted from ChatManager so it's reusable from anywhere (future
 * "Export All" with format options can import it directly without routing
 * through ChatManager).
 */
const MODAL_ID = 'export-format-modal';
/** Build the modal once, return the element. Idempotent — reuses existing node. */
function ensureModal() {
    const existing = document.getElementById(MODAL_ID);
    if (existing)
        return existing;
    const modal = document.createElement('div');
    modal.id = MODAL_ID;
    modal.className = 'modal';
    modal.innerHTML = `
        <div class="modal-overlay" data-close-export></div>
        <div class="modal-content modal-small">
            <div class="modal-header">
                <h2>📥 Export Format</h2>
                <button class="modal-close" data-close-export aria-label="Close">&times;</button>
            </div>
            <div class="modal-body">
                <p>Choose an export format:</p>
                <div class="export-format-grid">
                    <button class="btn export-format-btn" data-format="json">
                        <span class="format-icon">📋</span>
                        <span class="format-name">JSON</span>
                        <span class="format-desc">Structured data, re-importable</span>
                    </button>
                    <button class="btn export-format-btn" data-format="markdown">
                        <span class="format-icon">📝</span>
                        <span class="format-name">Markdown</span>
                        <span class="format-desc">Human-readable, great for sharing</span>
                    </button>
                    <button class="btn export-format-btn" data-format="html">
                        <span class="format-icon">🌐</span>
                        <span class="format-name">HTML</span>
                        <span class="format-desc">Standalone web page</span>
                    </button>
                    <button class="btn export-format-btn" data-format="txt">
                        <span class="format-icon">📄</span>
                        <span class="format-name">Plain Text</span>
                        <span class="format-desc">Minimal, just the messages</span>
                    </button>
                </div>
            </div>
        </div>
    `;
    document.body.appendChild(modal);
    return modal;
}
/** Show the picker and wait for a choice. Resolves to null if cancelled. */
export function promptExportFormat() {
    return new Promise(resolve => {
        const modal = ensureModal();
        modal.classList.add('active');
        // AbortController is the right tool here: `{once: true}` only removes the
        // handler that fires, so listeners on un-clicked buttons accumulate every
        // time the modal is opened-and-closed. With a controller we drop ALL
        // bound listeners on cleanup, regardless of which one resolved.
        const ac = new AbortController();
        const opts = { signal: ac.signal };
        const cleanup = (result) => {
            // ac.abort() tears down ALL listeners (incl. escHandler, bound with
            // the same signal below) — single source of truth for teardown.
            ac.abort();
            modal.classList.remove('active');
            resolve(result);
        };
        modal.querySelectorAll('[data-close-export]').forEach(el => {
            el.addEventListener('click', () => cleanup(null), opts);
        });
        modal.querySelectorAll('.export-format-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const format = (btn.dataset.format || 'json');
                cleanup(format);
            }, opts);
        });
        // Escape closes (matches the affordance other modals provide). Bound
        // with the same AbortController signal so ac.abort() removes it too.
        const escHandler = (e) => {
            if (e.key === 'Escape')
                cleanup(null);
        };
        document.addEventListener('keydown', escHandler, opts);
    });
}
//# sourceMappingURL=export-picker.js.map