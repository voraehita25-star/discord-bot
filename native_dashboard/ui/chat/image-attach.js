/**
 * Image attachment manager — picker + drag-drop + paste + base64 preview strip.
 *
 * Self-contained state (just an array of base64 data URLs). Exposes:
 *   - attach(file)         — read as base64, push onto list, re-render preview
 *   - remove(idx)          — drop one preview + re-render
 *   - get()                — current snapshot for sendMessage() payloads
 *   - clear()              — reset after send
 *   - setup()              — bind picker / drag-drop / paste listeners once
 *
 * Separated from ChatManager because the upload + drop handling is ~120
 * lines of DOM event wiring with only one outward dependency (sendMessage
 * reads the current images via `get()` before clearing). The dropZones
 * list is intentionally narrow (chat-messages + chat-input-area) so
 * dragging links to the address bar still works.
 */
import { escapeHtml, showToast } from '../shared.js';
import { isDocumentFile } from './document-attach.js';
const MAX_IMAGE_SIZE = 20 * 1024 * 1024; // 20 MB
const MAX_ATTACHED_IMAGES = 5;
export class ImageAttachManager {
    constructor() {
        this.images = [];
        this.pendingCount = 0;
    }
    /** Current snapshot of attached base64 data URLs (read before sendMessage). */
    get() {
        return this.images.slice();
    }
    /** Drop every attached image. Called by ChatManager after a successful send. */
    clear() {
        this.images = [];
        this.renderPreview();
    }
    /** Add one file — size + count limits enforced. Base64 encoded via FileReader.
     *
     * Pushes onto `images` only after the FileReader successfully resolves
     * with a `data:image/` URL. Errors decrement `pendingCount` without
     * pushing, so a failed read can never leak a placeholder slot.
     */
    attach(file) {
        if (file.size > MAX_IMAGE_SIZE) {
            showToast(`Image too large (${(file.size / 1024 / 1024).toFixed(1)}MB). Maximum is 20MB.`, { type: 'warning' });
            return;
        }
        // Count both committed images and in-flight readers against the cap so
        // a user can't queue 100 large reads while the first ones are still
        // decoding.
        if (this.images.length + this.pendingCount >= MAX_ATTACHED_IMAGES) {
            showToast(`Maximum ${MAX_ATTACHED_IMAGES} images allowed.`, { type: 'warning' });
            return;
        }
        this.pendingCount++;
        const reader = new FileReader();
        reader.onload = (e) => {
            this.pendingCount--;
            const base64 = e.target?.result;
            if (typeof base64 === 'string' && base64.startsWith('data:image/')) {
                this.images.push(base64);
                this.renderPreview();
            }
        };
        reader.onerror = () => {
            this.pendingCount--;
        };
        reader.readAsDataURL(file);
    }
    remove(index) {
        this.images.splice(index, 1);
        this.renderPreview();
    }
    /** Re-render the preview strip below the chat input. */
    renderPreview() {
        const container = document.getElementById('attached-images');
        if (!container)
            return;
        // Defence in depth: drop anything that isn't a data:image/ URL even
        // though attach() already validates this before pushing.
        const visible = this.images
            .map((img, idx) => ({ img, idx }))
            .filter(({ img }) => typeof img === 'string' && img.startsWith('data:image/'));
        if (visible.length === 0) {
            container.innerHTML = '';
            return;
        }
        container.innerHTML = visible.map(({ img, idx }, displayIdx) => `
            <div class="attached-image-preview">
                <img src="${escapeHtml(img)}" alt="Attached ${displayIdx + 1}">
                <button class="remove-image" data-idx="${idx}">&times;</button>
            </div>
        `).join('');
        container.querySelectorAll('.remove-image').forEach(btn => {
            btn.addEventListener('click', (e) => {
                // currentTarget (the button the listener is bound to) not target:
                // future-proofs against an icon element being added inside the
                // button, and matches document-attach.ts. Radix 10 keeps parseInt
                // deterministic (no accidental octal on a leading-zero idx).
                const idx = parseInt(e.currentTarget.dataset.idx || '0', 10);
                this.remove(idx);
            });
        });
    }
    /** Bind file picker, drag-drop, and paste handlers once on page init.
     *
     * When a `documents` manager is supplied, non-image files (PDF, text,
     * code, etc.) picked from the file dialog or dropped onto the chat area
     * are routed there instead of being rejected. Images continue to land
     * here. Paste is still images-only — pasting a PDF via Ctrl+V is an
     * unusual flow and adding it now would complicate the event path.
     */
    setup(documents) {
        const attachBtn = document.getElementById('btn-attach');
        const fileInput = document.getElementById('image-input');
        // Widen the accept filter when documents manager is active so the
        // OS file picker shows PDFs / text files / code, not just images.
        if (fileInput && documents) {
            fileInput.setAttribute('accept', 'image/*,application/pdf,text/*,' +
                '.pdf,.docx,.txt,.md,.markdown,.json,.jsonc,.yaml,.yml,.toml,' +
                '.ini,.conf,.cfg,.env,.csv,.tsv,.xml,.log,' +
                '.py,.pyi,.js,.mjs,.cjs,.ts,.tsx,.jsx,.rs,.go,.java,.kt,' +
                '.c,.cc,.cpp,.h,.hpp,.cs,.rb,.php,.pl,.r,.lua,' +
                '.sh,.bash,.zsh,.ps1,.bat,.cmd,' +
                '.html,.htm,.css,.scss,.sass,.less,.vue,.svelte,' +
                '.sql,.graphql,.gql');
        }
        attachBtn?.addEventListener('click', () => fileInput?.click());
        fileInput?.addEventListener('change', () => {
            const files = fileInput.files;
            if (files) {
                Array.from(files).forEach(file => {
                    if (file.type.startsWith('image/')) {
                        this.attach(file);
                    }
                    else if (documents && isDocumentFile(file)) {
                        documents.attach(file);
                    }
                });
            }
            // Reset input so the same file can be selected again.
            fileInput.value = '';
        });
        // Drag-and-drop: bind the drop listener to `.chat-main` — the
        // outermost chat container that's visible on the chat page
        // regardless of whether a conversation is active. Events from
        // inner children (chat-messages, chat-input-area, chat-empty)
        // bubble up to this one listener, so we get universal coverage
        // without double-attaching on nested zones. We intentionally do
        // NOT bind to the whole window so links being dragged to the
        // address bar still work.
        const dropZones = [
            document.querySelector('.chat-main'),
        ].filter((el) => el instanceof HTMLElement);
        const showDropState = (active) => {
            dropZones.forEach(z => z.classList.toggle('drop-active', active));
        };
        dropZones.forEach(zone => {
            zone.addEventListener('dragenter', (e) => {
                if (!e.dataTransfer)
                    return;
                if (Array.from(e.dataTransfer.items).some(i => i.kind === 'file')) {
                    e.preventDefault();
                    showDropState(true);
                }
            });
            zone.addEventListener('dragover', (e) => {
                if (e.dataTransfer && Array.from(e.dataTransfer.items).some(i => i.kind === 'file')) {
                    e.preventDefault();
                    e.dataTransfer.dropEffect = 'copy';
                }
            });
            zone.addEventListener('dragleave', (e) => {
                // dragleave fires for every child boundary crossed inside the
                // zone, not just when the cursor truly exits. e.target there is
                // the child being left, never the zone itself, so the previous
                // `e.target === zone` guard never cleared state — the overlay
                // got stuck on after first dragenter. Use relatedTarget (the
                // element being entered) and only clear when it's outside.
                const next = e.relatedTarget;
                if (!next || !zone.contains(next))
                    showDropState(false);
            });
            zone.addEventListener('drop', (e) => {
                if (!e.dataTransfer)
                    return;
                e.preventDefault();
                showDropState(false);
                const dropped = Array.from(e.dataTransfer.files);
                let accepted = 0;
                for (const f of dropped) {
                    if (f.type.startsWith('image/')) {
                        this.attach(f);
                        accepted++;
                    }
                    else if (documents && isDocumentFile(f)) {
                        documents.attach(f);
                        accepted++;
                    }
                }
                if (accepted === 0) {
                    showToast(documents
                        ? 'Unsupported file type (images, PDFs, and text files only)'
                        : 'Only image files can be attached', { type: 'warning' });
                }
            });
        });
        // Paste — Ctrl+V an image from clipboard into the chat input.
        document.getElementById('chat-input')?.addEventListener('paste', (e) => {
            const items = e.clipboardData?.items;
            if (!items)
                return;
            for (const item of Array.from(items)) {
                if (item.kind === 'file' && item.type.startsWith('image/')) {
                    const file = item.getAsFile();
                    if (file) {
                        e.preventDefault();
                        this.attach(file);
                    }
                }
            }
        });
    }
}
//# sourceMappingURL=image-attach.js.map