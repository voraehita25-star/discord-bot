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
import { DocumentAttachManager, isDocumentFile } from './document-attach.js';

const MAX_IMAGE_SIZE = 20 * 1024 * 1024; // 20 MB
const MAX_ATTACHED_IMAGES = 5;

export class ImageAttachManager {
    private images: string[] = [];

    /** Current snapshot of attached base64 data URLs (read before sendMessage).
     *
     * Empty strings represent slots reserved for a FileReader that hasn't
     * resolved yet — omit them so we never send a half-encoded image if the
     * user hits send before decoding finishes.
     */
    get(): string[] {
        return this.images.filter(img => img !== '');
    }

    /** Drop every attached image. Called by ChatManager after a successful send. */
    clear(): void {
        this.images = [];
        this.renderPreview();
    }

    /** Add one file — size + count limits enforced. Base64 encoded via FileReader.
     *
     * Reserves the preview slot BEFORE the FileReader resolves so that if the
     * user picks multiple files at once, the visible order matches the pick
     * order even when readers finish out-of-order (small image loaded before
     * a large one).
     */
    attach(file: File): void {
        if (file.size > MAX_IMAGE_SIZE) {
            showToast(`Image too large (${(file.size / 1024 / 1024).toFixed(1)}MB). Maximum is 20MB.`, { type: 'warning' });
            return;
        }
        if (this.images.length >= MAX_ATTACHED_IMAGES) {
            showToast(`Maximum ${MAX_ATTACHED_IMAGES} images allowed.`, { type: 'warning' });
            return;
        }
        const slot = this.images.length;
        this.images.push('');  // reserve this slot so later attaches don't shift under us
        const reader = new FileReader();
        reader.onload = (e) => {
            const base64 = e.target?.result as string;
            if (base64) {
                this.images[slot] = base64;
                this.renderPreview();
            } else {
                this.images.splice(slot, 1);
            }
        };
        reader.onerror = () => {
            this.images.splice(slot, 1);
            this.renderPreview();
        };
        reader.readAsDataURL(file);
    }

    remove(index: number): void {
        this.images.splice(index, 1);
        this.renderPreview();
    }

    /** Re-render the preview strip below the chat input. */
    renderPreview(): void {
        const container = document.getElementById('attached-images');
        if (!container) return;

        // Skip reserved-but-still-loading slots so the UI never shows a
        // broken-image icon for a FileReader that hasn't resolved yet.
        const visible = this.images
            .map((img, idx) => ({ img, idx }))
            .filter(({ img }) => img !== '');

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
                const idx = parseInt((e.target as HTMLElement).dataset.idx || '0');
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
    setup(documents?: DocumentAttachManager): void {
        const attachBtn = document.getElementById('btn-attach');
        const fileInput = document.getElementById('image-input') as HTMLInputElement | null;

        // Widen the accept filter when documents manager is active so the
        // OS file picker shows PDFs / text files / code, not just images.
        if (fileInput && documents) {
            fileInput.setAttribute(
                'accept',
                'image/*,application/pdf,text/*,' +
                '.pdf,.docx,.txt,.md,.markdown,.json,.jsonc,.yaml,.yml,.toml,' +
                '.ini,.conf,.cfg,.env,.csv,.tsv,.xml,.log,' +
                '.py,.pyi,.js,.mjs,.cjs,.ts,.tsx,.jsx,.rs,.go,.java,.kt,' +
                '.c,.cc,.cpp,.h,.hpp,.cs,.rb,.php,.pl,.r,.lua,' +
                '.sh,.bash,.zsh,.ps1,.bat,.cmd,' +
                '.html,.htm,.css,.scss,.sass,.less,.vue,.svelte,' +
                '.sql,.graphql,.gql',
            );
        }

        attachBtn?.addEventListener('click', () => fileInput?.click());

        fileInput?.addEventListener('change', () => {
            const files = fileInput.files;
            if (files) {
                Array.from(files).forEach(file => {
                    if (file.type.startsWith('image/')) {
                        this.attach(file);
                    } else if (documents && isDocumentFile(file)) {
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
        ].filter((el): el is HTMLElement => el instanceof HTMLElement);

        const showDropState = (active: boolean): void => {
            dropZones.forEach(z => z.classList.toggle('drop-active', active));
        };

        dropZones.forEach(zone => {
            zone.addEventListener('dragenter', (e) => {
                if (!e.dataTransfer) return;
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
                // Only clear state when leaving the zone entirely (not its children).
                if (e.target === zone) showDropState(false);
            });
            zone.addEventListener('drop', (e) => {
                if (!e.dataTransfer) return;
                e.preventDefault();
                showDropState(false);
                const dropped = Array.from(e.dataTransfer.files);
                let accepted = 0;
                for (const f of dropped) {
                    if (f.type.startsWith('image/')) {
                        this.attach(f);
                        accepted++;
                    } else if (documents && isDocumentFile(f)) {
                        documents.attach(f);
                        accepted++;
                    }
                }
                if (accepted === 0) {
                    showToast(
                        documents
                            ? 'Unsupported file type (images, PDFs, and text files only)'
                            : 'Only image files can be attached',
                        { type: 'warning' },
                    );
                }
            });
        });

        // Paste — Ctrl+V an image from clipboard into the chat input.
        document.getElementById('chat-input')?.addEventListener('paste', (e) => {
            const items = (e as ClipboardEvent).clipboardData?.items;
            if (!items) return;
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
