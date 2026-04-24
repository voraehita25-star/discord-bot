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

const MAX_IMAGE_SIZE = 20 * 1024 * 1024; // 20 MB
const MAX_ATTACHED_IMAGES = 5;

export class ImageAttachManager {
    private images: string[] = [];

    /** Current snapshot of attached base64 data URLs (read before sendMessage). */
    get(): string[] {
        return [...this.images];
    }

    /** Drop every attached image. Called by ChatManager after a successful send. */
    clear(): void {
        this.images = [];
        this.renderPreview();
    }

    /** Add one file — size + count limits enforced. Base64 encoded via FileReader. */
    attach(file: File): void {
        if (file.size > MAX_IMAGE_SIZE) {
            showToast(`Image too large (${(file.size / 1024 / 1024).toFixed(1)}MB). Maximum is 20MB.`, { type: 'warning' });
            return;
        }
        if (this.images.length >= MAX_ATTACHED_IMAGES) {
            showToast(`Maximum ${MAX_ATTACHED_IMAGES} images allowed.`, { type: 'warning' });
            return;
        }
        const reader = new FileReader();
        reader.onload = (e) => {
            const base64 = e.target?.result as string;
            if (base64) {
                this.images.push(base64);
                this.renderPreview();
            }
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

        if (this.images.length === 0) {
            container.innerHTML = '';
            return;
        }

        container.innerHTML = this.images.map((img, idx) => `
            <div class="attached-image-preview">
                <img src="${escapeHtml(img)}" alt="Attached ${idx + 1}">
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

    /** Bind file picker, drag-drop, and paste handlers once on page init. */
    setup(): void {
        const attachBtn = document.getElementById('btn-attach');
        const fileInput = document.getElementById('image-input') as HTMLInputElement | null;

        attachBtn?.addEventListener('click', () => fileInput?.click());

        fileInput?.addEventListener('change', () => {
            const files = fileInput.files;
            if (files) {
                Array.from(files).forEach(file => {
                    if (file.type.startsWith('image/')) this.attach(file);
                });
            }
            // Reset input so the same file can be selected again.
            fileInput.value = '';
        });

        // Drag-and-drop: accept image files over the chat input area or the
        // messages area. We intentionally do NOT accept drops on the whole
        // window so links being dragged to the address bar still work.
        const dropZones = [
            document.getElementById('chat-messages'),
            document.querySelector('.chat-input-area'),
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
                const files = Array.from(e.dataTransfer.files).filter(f => f.type.startsWith('image/'));
                if (files.length === 0) {
                    showToast('Only image files can be attached', { type: 'warning' });
                    return;
                }
                files.forEach(f => this.attach(f));
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
