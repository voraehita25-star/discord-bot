/**
 * Document attachment manager — PDF + text-like files.
 *
 * Complements ImageAttachManager: images stay there, everything else lands
 * here. Two file classes are distinguished at attach time by MIME + extension:
 *
 *   - `binary`  — PDF / DOCX / anything non-text. Stored as a base64 data URL
 *                 so the backend can round-trip the bytes unchanged.
 *   - `text`    — Plain text / code / markdown / json / yaml / etc. Stored as
 *                 decoded UTF-8 string so the backend can inline it directly
 *                 into the prompt without wasting tokens on base64 overhead.
 *
 * Outward shape (what `get()` returns) is a `DocumentPayload[]` so the send
 * handler in chat-manager doesn't have to re-inspect MIME.
 *
 * Hard caps:
 *   - 32 MB per file (matches Claude API `document` block limit)
 *   - 5 files per message (matches image attach behaviour)
 *   - 20,000-char truncation on preview filename (prevents giant names
 *     blowing out the UI — doesn't touch the actual file content)
 */
import { escapeHtml, showToast } from '../shared.js';
// Mirrors backend constants — keep in sync with dashboard_chat_claude_cli.py
// / dashboard_chat_claude.py. Claude's API caps at 32 MB per document block.
const MAX_DOC_SIZE = 32 * 1024 * 1024; // 32 MB
const MAX_ATTACHED_DOCS = 5;
// Extensions recognised as "text-like" regardless of browser-provided MIME
// (browsers often report empty or generic mime for niche extensions). The
// corresponding content is read as UTF-8 and inlined into the prompt on the
// backend, so binary file types MUST NOT be here.
const TEXT_EXTENSIONS = new Set([
    'txt', 'md', 'markdown', 'rst',
    'json', 'jsonc', 'yaml', 'yml', 'toml', 'ini', 'conf', 'cfg', 'env',
    'csv', 'tsv', 'xml', 'log',
    'py', 'pyi', 'js', 'mjs', 'cjs', 'ts', 'tsx', 'jsx',
    'rs', 'go', 'java', 'kt', 'scala', 'swift',
    'c', 'cc', 'cpp', 'cxx', 'h', 'hpp', 'hxx',
    'cs', 'rb', 'php', 'pl', 'r', 'lua',
    'sh', 'bash', 'zsh', 'fish', 'ps1', 'bat', 'cmd',
    'html', 'htm', 'css', 'scss', 'sass', 'less', 'vue', 'svelte',
    'sql', 'graphql', 'gql',
]);
// Binary formats we accept and forward to Claude as `document` blocks.
const BINARY_MIMES = new Set([
    'application/pdf',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document', // .docx
]);
const BINARY_EXTENSIONS = new Set([
    'pdf', 'docx',
]);
/** File extension in lowercase without the leading dot, or empty string. */
function extensionOf(filename) {
    const idx = filename.lastIndexOf('.');
    if (idx < 0 || idx === filename.length - 1)
        return '';
    return filename.slice(idx + 1).toLowerCase();
}
/** Returns true if the File should be routed to this manager (not to image). */
export function isDocumentFile(file) {
    if (file.type.startsWith('image/'))
        return false; // images go elsewhere
    const ext = extensionOf(file.name);
    if (BINARY_MIMES.has(file.type) || BINARY_EXTENSIONS.has(ext))
        return true;
    if (file.type.startsWith('text/'))
        return true;
    if (TEXT_EXTENSIONS.has(ext))
        return true;
    return false;
}
/** Classify a file as binary (base64) vs text (UTF-8 string). */
function classify(file) {
    const ext = extensionOf(file.name);
    if (BINARY_MIMES.has(file.type) || BINARY_EXTENSIONS.has(ext))
        return 'binary';
    return 'text';
}
function formatBytes(n) {
    if (n < 1024)
        return `${n} B`;
    if (n < 1024 * 1024)
        return `${(n / 1024).toFixed(1)} KB`;
    return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}
function iconFor(kind, name) {
    const ext = extensionOf(name);
    if (ext === 'pdf')
        return '📕';
    if (ext === 'docx')
        return '📘';
    if (ext === 'json' || ext === 'yaml' || ext === 'yml' || ext === 'toml')
        return '🧩';
    if (ext === 'md' || ext === 'markdown')
        return '📝';
    if (ext === 'csv' || ext === 'tsv' || ext === 'xml')
        return '📊';
    if (TEXT_EXTENSIONS.has(ext))
        return '📄';
    return kind === 'binary' ? '📎' : '📄';
}
export class DocumentAttachManager {
    constructor() {
        this.docs = [];
        this.pendingCount = 0;
    }
    /** Snapshot for the send payload. */
    get() {
        return this.docs.slice();
    }
    clear() {
        this.docs = [];
        this.renderPreview();
    }
    /** Try to attach a single file. Validates type + size; toasts on reject. */
    attach(file) {
        if (file.size > MAX_DOC_SIZE) {
            showToast(`File too large (${formatBytes(file.size)}). Maximum is ${formatBytes(MAX_DOC_SIZE)}.`, { type: 'warning' });
            return;
        }
        if (!isDocumentFile(file)) {
            showToast(`Unsupported file type: ${file.name}`, { type: 'warning' });
            return;
        }
        // Count both committed docs and in-flight readers against the cap.
        if (this.docs.length + this.pendingCount >= MAX_ATTACHED_DOCS) {
            showToast(`Maximum ${MAX_ATTACHED_DOCS} documents allowed.`, { type: 'warning' });
            return;
        }
        const kind = classify(file);
        this.pendingCount++;
        const reader = new FileReader();
        reader.onload = (e) => {
            this.pendingCount--;
            const result = e.target?.result;
            if (typeof result !== 'string' || result === '')
                return;
            this.docs.push({
                name: file.name,
                mime: file.type || (kind === 'binary' ? 'application/octet-stream' : 'text/plain'),
                kind,
                data: result,
                size_bytes: file.size,
            });
            this.renderPreview();
        };
        reader.onerror = () => {
            this.pendingCount--;
            showToast(`Failed to read ${file.name}`, { type: 'error' });
        };
        if (kind === 'binary') {
            reader.readAsDataURL(file);
        }
        else {
            reader.readAsText(file, 'utf-8');
        }
    }
    remove(index) {
        this.docs.splice(index, 1);
        this.renderPreview();
    }
    /** Re-render the preview strip below the chat input. */
    renderPreview() {
        const container = document.getElementById('attached-docs');
        if (!container)
            return;
        const visible = this.docs
            .map((doc, idx) => ({ doc, idx }))
            .filter(({ doc }) => doc.data !== '');
        if (visible.length === 0) {
            container.innerHTML = '';
            return;
        }
        container.innerHTML = visible.map(({ doc, idx }) => `
            <div class="attached-doc-preview" title="${escapeHtml(doc.name)}">
                <span class="doc-icon" aria-hidden="true">${iconFor(doc.kind, doc.name)}</span>
                <div class="doc-info">
                    <div class="doc-name">${escapeHtml(doc.name)}</div>
                    <div class="doc-meta">${escapeHtml(formatBytes(doc.size_bytes))} · ${escapeHtml(doc.kind)}</div>
                </div>
                <button class="remove-doc" data-idx="${idx}" aria-label="Remove ${escapeHtml(doc.name)}">&times;</button>
            </div>
        `).join('');
        container.querySelectorAll('.remove-doc').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const idx = parseInt(e.currentTarget.dataset.idx || '0');
                this.remove(idx);
            });
        });
    }
}
//# sourceMappingURL=document-attach.js.map