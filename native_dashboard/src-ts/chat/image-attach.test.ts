/**
 * Tests for chat/image-attach.ts — the remove-image button's accessible name.
 *
 * The preview strip renders one icon-only "×" button per attached image. With no
 * aria-label, a screen reader announces every button identically ("button ×"),
 * so a user with five attachments can't tell which "Remove" they're activating.
 * renderPreview() now stamps a POSITIONAL label ("Remove image N", 1-based on the
 * visible slot, not the array index) so each button is independently identifiable
 * and the labels re-number after a removal.
 *
 * `images` is private and only fillable through attach(), which is driven by a
 * FileReader. We stub the global FileReader to resolve onload synchronously with a
 * tiny data:image/png URL, so attach() commits an image without real file I/O.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { ImageAttachManager } from './image-attach.js';

const PNG_DATA_URL = 'data:image/png;base64,iVBORw0KGgo=';

// Minimal FileReader stand-in: readAsDataURL fires onload immediately with a
// data:image/ URL so attach()'s `startsWith('data:image/')` guard passes and the
// image is pushed + rendered before the test's next line runs.
class FakeFileReader {
    onload: ((e: { target: { result: string } }) => void) | null = null;
    onerror: (() => void) | null = null;
    result: string | null = null;
    readAsDataURL(_f: Blob): void {
        this.result = PNG_DATA_URL;
        this.onload?.({ target: { result: this.result } });
    }
}

function mountDom(): void {
    // toast-container present so any showToast() (e.g. cap warnings) no-ops on a
    // real element instead of probing a missing id; not required by assertions.
    document.body.innerHTML = '<div id="attached-images"></div><div id="toast-container"></div>';
}

function mkFile(name = 'pic.png'): File {
    return new File(['x'], name, { type: 'image/png' });
}

function removeButtons(): HTMLButtonElement[] {
    return Array.from(
        document.querySelectorAll<HTMLButtonElement>('#attached-images .remove-image'),
    );
}

describe('ImageAttachManager remove-image accessible name', () => {
    beforeEach(() => {
        mountDom();
        vi.stubGlobal('FileReader', FakeFileReader);
    });

    afterEach(() => {
        vi.unstubAllGlobals();
    });

    it('gives a single remove button a non-empty label that is not just "×"', () => {
        const mgr = new ImageAttachManager();
        mgr.attach(mkFile());

        const buttons = removeButtons();
        expect(buttons).toHaveLength(1);

        const label = buttons[0].getAttribute('aria-label');
        expect(label).toBeTruthy();
        // Guard against the label being the bare times glyph (entity or char):
        // a screen reader would announce nothing useful.
        expect(label).not.toBe('×');
        expect(label).not.toBe('&times;');
        expect(label).toBe('Remove image 1');
    });

    it('gives three attachments three distinct positional labels', () => {
        const mgr = new ImageAttachManager();
        mgr.attach(mkFile('a.png'));
        mgr.attach(mkFile('b.png'));
        mgr.attach(mkFile('c.png'));

        const labels = removeButtons().map(b => b.getAttribute('aria-label'));
        expect(labels).toEqual(['Remove image 1', 'Remove image 2', 'Remove image 3']);
        // Independently identifiable: no two buttons share a label.
        expect(new Set(labels).size).toBe(3);
    });

    it('re-numbers the remaining labels positionally after a removal', () => {
        const mgr = new ImageAttachManager();
        mgr.attach(mkFile('a.png'));
        mgr.attach(mkFile('b.png'));
        mgr.attach(mkFile('c.png'));

        mgr.remove(0);

        const labels = removeButtons().map(b => b.getAttribute('aria-label'));
        // Two buttons left, re-numbered by visible position — not the original
        // index (which would leave a stale "Remove image 1" gap or skip to 2).
        expect(labels).toEqual(['Remove image 1', 'Remove image 2']);
    });
});
