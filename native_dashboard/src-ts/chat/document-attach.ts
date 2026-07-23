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
 * Long file names are ellipsised by CSS in the preview strip; the full name
 * is preserved in the payload and the `title` tooltip (no content truncation).
 */

import { escapeHtml, icon, showToast } from '../shared.js';

/** Outward shape of a single document attachment. */
export interface DocumentPayload {
    name: string;
    mime: string;
    /** `'binary'` → `data` is a `data:` URL; `'text'` → decoded UTF-8 string. */
    kind: 'binary' | 'text';
    data: string;
    size_bytes: number;
}

// Mirrors backend constants — keep in sync with dashboard_chat_claude_cli.py
// / dashboard_chat_claude.py. Claude's API caps at 32 MB per document block.
const MAX_DOC_SIZE = 32 * 1024 * 1024; // 32 MB
const MAX_ATTACHED_DOCS = 5;
// Approximates the backend's MAX_EXTRACTED_CHARS — document_extractor caps a
// single text document's extracted/inlined content at 500,000 chars (see
// dashboard_chat_claude_cli.py / dashboard_chat_claude.py — same limit the
// editor's char counter shows: "… / 500,000 chars"). The backend counts Python
// str length (Unicode code POINTS); we count JS str.length (UTF-16 code UNITS),
// so the two diverge slightly on astral chars (one code point = two units), and
// this client-side clamp is an approximation, not an exact mirror. The 32 MB
// byte cap above is a separate, coarser layer (raw bytes, pre-read). We still
// re-check the DECODED length here so a multi-byte (UTF-8) file that slips under
// 32 MB of bytes yet decodes past ~500k chars is truncated client-side instead
// of being silently dropped by the backend.
const MAX_TEXT_CHARS = 500_000;

// Extensions recognised as "text-like" regardless of browser-provided MIME
// (browsers often report empty or generic mime for niche extensions). The
// corresponding content is read as UTF-8 and inlined into the prompt on the
// backend, so binary file types MUST NOT be here.
const TEXT_EXTENSIONS = new Set<string>([
    'txt', 'md', 'markdown', 'rst',
    // NOTE: 'env' deliberately OMITTED — the backend allowlist
    // (_SUPPORTED_DOC_TEXT_EXT) excludes .env so a malicious frontend can't
    // exfiltrate secrets; accepting it here only produced a silent server-
    // side drop with no user feedback.
    'json', 'jsonc', 'yaml', 'yml', 'toml', 'ini', 'conf', 'cfg',
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
const BINARY_MIMES = new Set<string>([
    'application/pdf',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document', // .docx
]);

const BINARY_EXTENSIONS = new Set<string>([
    'pdf', 'docx',
]);

/** Result of the post-decode text-size check. `data` is the (possibly
 *  truncated) content; `truncated` is true when it was clipped to the cap. */
export interface TextSizeCheck {
    data: string;
    truncated: boolean;
    originalLength: number;
}

/** Clamp decoded text to the backend's MAX_TEXT_CHARS cap. Pure + exported so
 *  it can be unit-tested without a FileReader. When over the cap, the content is
 *  hard-truncated to MAX_TEXT_CHARS chars (the backend would otherwise drop the
 *  overflow silently — truncating client-side keeps what we send in sync with
 *  what the user is told). */
export function clampTextToCap(text: string): TextSizeCheck {
    const originalLength = text.length;
    if (originalLength <= MAX_TEXT_CHARS) {
        return { data: text, truncated: false, originalLength };
    }
    let cap = MAX_TEXT_CHARS;
    // If the cut lands between the two halves of a surrogate pair, the kept
    // slice would end in a lone high surrogate (0xD800–0xDBFF) — an unpaired
    // code unit that serialises to U+FFFD and corrupts the trailing emoji /
    // astral char. Drop that dangling half so we never send a broken pair.
    const last = text.charCodeAt(cap - 1);
    if (last >= 0xd800 && last <= 0xdbff) cap -= 1;
    return { data: text.slice(0, cap), truncated: true, originalLength };
}

/** File extension in lowercase without the leading dot, or empty string. */
function extensionOf(filename: string): string {
    const idx = filename.lastIndexOf('.');
    if (idx < 0 || idx === filename.length - 1) return '';
    return filename.slice(idx + 1).toLowerCase();
}

/** Returns true if the File should be routed to this manager (not to image). */
export function isDocumentFile(file: File): boolean {
    if (file.type.startsWith('image/')) return false;  // images go elsewhere
    const ext = extensionOf(file.name);
    if (BINARY_MIMES.has(file.type) || BINARY_EXTENSIONS.has(ext)) return true;
    if (file.type.startsWith('text/')) return true;
    if (TEXT_EXTENSIONS.has(ext)) return true;
    return false;
}

/** Classify a file as binary (base64) vs text (UTF-8 string). */
function classify(file: File): 'binary' | 'text' {
    const ext = extensionOf(file.name);
    if (BINARY_MIMES.has(file.type) || BINARY_EXTENSIONS.has(ext)) return 'binary';
    return 'text';
}

function formatBytes(n: number): string {
    if (n < 1024) return `${n} B`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
    return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function iconFor(kind: 'binary' | 'text', name: string): string {
    const ext = extensionOf(name);
    if (ext === 'pdf') return icon('file');
    if (ext === 'docx') return icon('file');
    if (ext === 'json' || ext === 'yaml' || ext === 'yml' || ext === 'toml') return icon('chip');
    if (ext === 'md' || ext === 'markdown') return icon('pencil');
    if (ext === 'csv' || ext === 'tsv' || ext === 'xml') return icon('gauge');
    if (TEXT_EXTENSIONS.has(ext)) return icon('file');
    return kind === 'binary' ? icon('paperclip') : icon('file');
}

export class DocumentAttachManager {
    private docs: DocumentPayload[] = [];
    private pendingCount = 0;

    /** Snapshot for the send payload. */
    get(): DocumentPayload[] {
        return this.docs.slice();
    }

    clear(): void {
        this.docs = [];
        this.renderPreview();
    }

    /** Re-stage a previously captured snapshot (see get()). Used by
     *  retryFailedSend to restore attachments a text-only retry cleared. */
    restore(docs: DocumentPayload[]): void {
        this.docs = docs.slice();
        this.renderPreview();
    }

    /** Try to attach a single file. Validates type + size; toasts on reject. */
    attach(file: File): void {
        if (file.size > MAX_DOC_SIZE) {
            showToast(
                `File too large (${formatBytes(file.size)}). Maximum is ${formatBytes(MAX_DOC_SIZE)}.`,
                { type: 'warning' },
            );
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
            if (typeof result !== 'string' || result === '') {
                // Empty/non-string result (e.g. a zero-byte .txt/.md) — tell the
                // user instead of silently dropping the attachment with no chip
                // and no explanation.
                showToast(`Skipped empty file: ${file.name}`, { type: 'warning' });
                return;
            }
            // Post-decode size cap for TEXT files only. The byte-size check at the
            // top of attach() can pass for a multi-byte file that still decodes to
            // more than the backend's ~500k-char extractor limit; clamp it here
            // (an approximate UTF-16-units mirror of the Python code-point cap —
            // see MAX_TEXT_CHARS) and tell the user, so what we send roughly
            // matches what they're told instead of being silently dropped.
            // Binary (data-URL) docs aren't subject to the char cap.
            let data = result;
            if (kind === 'text') {
                const checked = clampTextToCap(result);
                if (checked.truncated) {
                    showToast(
                        `"${file.name}" is ${checked.originalLength.toLocaleString()} chars — `
                        + `truncated to the ${MAX_TEXT_CHARS.toLocaleString()}-char limit.`,
                        { type: 'warning', duration: 4000 },
                    );
                }
                data = checked.data;
            }
            this.docs.push({
                name: file.name,
                mime: file.type || (kind === 'binary' ? 'application/octet-stream' : 'text/plain'),
                kind,
                data,
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
        } else {
            reader.readAsText(file, 'utf-8');
        }
    }

    remove(index: number): void {
        this.docs.splice(index, 1);
        this.renderPreview();
    }

    /** Re-render the preview strip below the chat input. */
    renderPreview(): void {
        const container = document.getElementById('attached-docs');
        if (!container) return;

        const visible = this.docs
            .map((doc, idx) => ({ doc, idx }))
            // Defence in depth: drop empty-data entries even though attach()
            // already rejects them before pushing (so this never removes any).
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
                const idx = parseInt((e.currentTarget as HTMLElement).dataset.idx || '0', 10);
                this.remove(idx);
            });
        });
    }
}
