import { expect, test, type Page } from '@playwright/test';
import { installDashboardMocks } from './_fixtures/mock-tauri';

/**
 * Modal lifecycle tests — open / close paths + ARIA invariants for every modal
 * that ships in the dashboard.
 *
 * The goal is LIFECYCLE coverage (open → close via every supported path →
 * post-close state), NOT feature coverage inside each modal. The feature
 * paths (e.g. confirming a rename, picking a role) already live in
 * src-ts/chat/conversation-modals.test.ts and friends.
 *
 * Many modals are nested inside a per-page `<section class="page">` that is
 * `display: none` while inactive — so EVERY test first calls `showPage`
 * to ensure the modal's host page is rendered, otherwise the modal itself
 * would be visually present but not clickable through Playwright's
 * visibility check.
 *
 * Some ARIA assertions are intentionally `expect.soft` — they encode known
 * a11y issues (e.g. aria-hidden not flipped on show, focus not moved into
 * the dialog). We want every modal's findings surfaced in one run instead
 * of bailing on the first regression.
 */

interface ModalSpec {
    /** ID of the modal element. */
    id: string;
    /** Page slug (matches `data-page` and `#page-<slug>`). The test
     *  navigates here first so the modal's container is `display:block`. */
    hostPage: string | null;
    /** Open the modal in a way that runs the production code path. */
    open: (page: Page) => Promise<void>;
    /** Whether this modal closes on Escape. */
    closesOnEscape: boolean;
    /** Whether this modal closes on backdrop (.modal-overlay) click. */
    closesOnBackdrop: boolean;
    /** Selector for the `×` close button inside the modal. ``null`` if the
     *  modal has no `×` button (e.g. delete-confirm only has Cancel/Confirm). */
    closeButtonSelector: string | null;
    /** ID of the labelledby element. */
    labelledById: string;
    /** Known a11y regressions for this modal. When the underlying fix lands,
     *  flip the matching flag and the test will assert (instead of being
     *  skipped with the "fixme" reason). See
     *  tests-e2e/modal-lifecycle.spec.ts comments for the bug each one tracks. */
    knownIssues?: {
        /** Show path doesn't focus a control inside the dialog. WCAG 2.1 SC
         *  2.4.3 (Focus Order): when a modal opens, focus should move into
         *  it so keyboard users land in the dialog. Today only new-chat
         *  + rename modals do this. */
        focusNotMovedOnOpen?: boolean;
        /** Close path doesn't reset aria-hidden="true" on the modal element.
         *  When a modal is closed, its body content becomes inert; if
         *  aria-hidden isn't restored, screen readers may announce stale
         *  content. Today only `new-chat-modal.closeModal()` resets it. */
        ariaHiddenNotResetOnClose?: boolean;
    };
}

const MODALS: ModalSpec[] = [
    {
        id: 'new-chat-modal',
        hostPage: 'chat',
        labelledById: 'new-chat-modal-title',
        open: async (page) => {
            await page.evaluate(() => {
                const cm = (window as unknown as {
                    chatManager?: { showNewChatModal: () => void };
                }).chatManager;
                cm?.showNewChatModal();
            });
        },
        closesOnEscape: false, // No Escape handler bound for this modal.
        closesOnBackdrop: true,
        closeButtonSelector: '#modal-close',
        // No known issues — both focus + aria-hidden-on-close work today.
    },
    {
        id: 'delete-confirm-modal',
        hostPage: 'chat',
        labelledById: 'delete-confirm-modal-title',
        open: async (page) => {
            await page.evaluate(() => {
                const cm = (window as unknown as {
                    chatManager?: {
                        convModals?: { showDelete: (id: string) => void };
                        isStreaming?: boolean;
                        conversations?: Array<{ id: string; title: string }>;
                    };
                }).chatManager;
                if (!cm?.convModals) return;
                cm.isStreaming = false;
                cm.conversations = [{ id: 'lc-test', title: 'Test' }];
                cm.convModals.showDelete('lc-test');
            });
        },
        closesOnEscape: true,
        closesOnBackdrop: true,
        closeButtonSelector: null,
        knownIssues: {
            // ConversationModals.showDelete only adds .active; no focus
            // move. Should focus the Cancel button (safer default for an
            // alertdialog). Tracked as a11y finding 2026-05-28.
            focusNotMovedOnOpen: true,
            // closeDelete() doesn't set aria-hidden back to "true".
            ariaHiddenNotResetOnClose: true,
        },
    },
    {
        id: 'rename-modal',
        hostPage: 'chat',
        labelledById: 'rename-modal-title',
        open: async (page) => {
            await page.evaluate(() => {
                const cm = (window as unknown as {
                    chatManager?: {
                        convModals?: { showRename: (id: string) => void };
                        isStreaming?: boolean;
                        conversations?: Array<{ id: string; title: string }>;
                    };
                }).chatManager;
                if (!cm?.convModals) return;
                cm.isStreaming = false;
                cm.conversations = [{ id: 'lc-test', title: 'Rename me' }];
                cm.convModals.showRename('lc-test');
            });
        },
        closesOnEscape: true,
        closesOnBackdrop: true,
        closeButtonSelector: null,
        knownIssues: {
            // showRename DOES focus the input — focus check passes.
            // closeRename() doesn't reset aria-hidden.
            ariaHiddenNotResetOnClose: true,
        },
    },
    {
        id: 'chat-files-modal',
        hostPage: 'chat',
        labelledById: 'chat-files-modal-title',
        open: async (page) => {
            await page.evaluate(() => {
                const cm = (window as unknown as {
                    chatManager?: {
                        currentConversation: { id: string; title: string } | null;
                        openChatFilesModal: () => void;
                    };
                }).chatManager;
                if (!cm) return;
                cm.currentConversation = { id: 'lc-test', title: 'Test' };
                cm.openChatFilesModal();
            });
        },
        closesOnEscape: false,
        closesOnBackdrop: true,
        closeButtonSelector: '#chat-files-close',
        knownIssues: {
            focusNotMovedOnOpen: true,
            ariaHiddenNotResetOnClose: true,
        },
    },
    {
        id: 'add-memory-modal',
        hostPage: 'memories',
        labelledById: 'add-memory-modal-title',
        open: async (page) => {
            await page.locator('#btn-add-memory').click();
        },
        closesOnEscape: false,
        closesOnBackdrop: true,
        closeButtonSelector: '#memory-modal-close',
        knownIssues: {
            // memoryManager.showModal() clears the textarea but doesn't
            // focus it. Should focus #memory-content for keyboard users.
            focusNotMovedOnOpen: true,
            ariaHiddenNotResetOnClose: true,
        },
    },
    {
        // The shortcuts modal lives at <body> root, no host page needed.
        id: 'shortcuts-modal',
        hostPage: null,
        labelledById: 'shortcuts-modal-title',
        open: async (page) => {
            // Press '?' OUTSIDE any text input so the global handler fires.
            await page.locator('body').click({ position: { x: 1, y: 1 } });
            await page.keyboard.press('?');
        },
        closesOnEscape: true,
        closesOnBackdrop: true,
        closeButtonSelector: '[data-close-shortcuts].modal-close',
        knownIssues: {
            // The "?" handler in app.ts just adds .active — no focus move,
            // no aria-hidden flip.
            focusNotMovedOnOpen: true,
            ariaHiddenNotResetOnClose: true,
        },
    },
    {
        // The avatar-crop modal lives at <body> root too.
        id: 'avatar-crop-modal',
        hostPage: null,
        labelledById: 'avatar-crop-modal-title',
        open: async (page) => {
            // The cropper expects a real image URL; force-open by toggling
            // .active directly — the lifecycle assertions don't care about
            // image bytes, and forcing through the production path requires
            // ipc-mocking pick_image_file + read_image_as_base64 + waiting
            // on the cropImage.onload callback.
            await page.evaluate(() => {
                document.getElementById('avatar-crop-modal')?.classList.add('active');
            });
        },
        closesOnEscape: true,
        closesOnBackdrop: true,
        closeButtonSelector: '#avatar-crop-close',
        knownIssues: {
            // Direct .active toggle test path skips startCropModal() entirely,
            // so we cannot validate focus on that path. The production
            // path also doesn't focus inside the modal once opened.
            focusNotMovedOnOpen: true,
            // closeCropModal doesn't reset aria-hidden.
            ariaHiddenNotResetOnClose: true,
        },
    },
];

test.beforeEach(async ({ page }) => {
    await installDashboardMocks(page);
    await page.goto('/index.html');
    await page.waitForLoadState('domcontentloaded');
    // Bootstrap completes within ~250ms (settings load, chatManager init,
    // event listener binding). Wait for the marker that init finished.
    await page.waitForFunction(
        () => (window as unknown as { chatManager?: unknown }).chatManager !== undefined,
        { timeout: 5000 },
    );
});

/** Navigate to the modal's host page so its container becomes display:block. */
async function gotoHostPage(page: Page, spec: ModalSpec): Promise<void> {
    if (!spec.hostPage) return;
    await page.evaluate((p) => {
        const fn = (window as unknown as { showPage?: (s: string) => void }).showPage;
        fn?.(p);
    }, spec.hostPage);
    await expect(page.locator(`#page-${spec.hostPage}`)).toHaveClass(/active/);
}

for (const spec of MODALS) {
    test.describe(`${spec.id}`, () => {
        test('opens with role + aria-modal=true + aria-labelledby resolves', async ({ page }) => {
            await gotoHostPage(page, spec);
            await spec.open(page);
            const modal = page.locator(`#${spec.id}`);
            await expect(modal).toHaveClass(/active/);

            // role must be present and either "dialog" or "alertdialog".
            const role = await modal.getAttribute('role');
            expect(role, `${spec.id} role`).toMatch(/^(dialog|alertdialog)$/);

            // aria-modal must be the literal string "true" (axe + ARIA spec).
            await expect(modal).toHaveAttribute('aria-modal', 'true');

            // aria-labelledby must point at a real, non-empty element so
            // assistive tech can name the dialog.
            const labelledBy = await modal.getAttribute('aria-labelledby');
            expect(labelledBy, `${spec.id} aria-labelledby`).toBe(spec.labelledById);
            const labelText = await page.locator(`#${spec.labelledById}`).textContent();
            expect(
                (labelText ?? '').trim(),
                `${spec.id} labelledby target has no text`,
            ).not.toBe('');
        });

        if (spec.closesOnEscape) {
            test('closes on Escape', async ({ page }) => {
                await gotoHostPage(page, spec);
                await spec.open(page);
                const modal = page.locator(`#${spec.id}`);
                await expect(modal).toHaveClass(/active/);
                await page.keyboard.press('Escape');
                await expect(modal).not.toHaveClass(/active/);
            });
        }

        if (spec.closeButtonSelector) {
            test('closes on × button click', async ({ page }) => {
                await gotoHostPage(page, spec);
                await spec.open(page);
                const modal = page.locator(`#${spec.id}`);
                await expect(modal).toHaveClass(/active/);
                await page.locator(spec.closeButtonSelector!).first().click();
                await expect(modal).not.toHaveClass(/active/);
            });
        }

        if (spec.closesOnBackdrop) {
            test('closes on backdrop click', async ({ page }) => {
                await gotoHostPage(page, spec);
                await spec.open(page);
                const modal = page.locator(`#${spec.id}`);
                await expect(modal).toHaveClass(/active/);
                // Click at the top-left corner of the .modal-overlay so we
                // hit the backdrop, not the centered modal-content. The
                // overlay covers 100% of the viewport above the content.
                await modal.locator('.modal-overlay').first().click({
                    position: { x: 5, y: 5 },
                });
                await expect(modal).not.toHaveClass(/active/);
            });
        }

        test('starts hidden with aria-hidden="true" in the base markup', async ({ page }) => {
            // Sanity: every modal in index.html ships aria-hidden=true so SRs
            // don't announce body content before it opens. Soft so a single
            // missing attribute doesn't mask other modal findings.
            const modal = page.locator(`#${spec.id}`);
            const hidden = await modal.getAttribute('aria-hidden');
            expect.soft(hidden, `${spec.id} initial aria-hidden`).toBe('true');
        });

        const focusTest = spec.knownIssues?.focusNotMovedOnOpen ? test.fixme : test;
        focusTest('focus moves inside the modal on open', async ({ page }) => {
            // WCAG 2.1 SC 2.4.3: opening a modal should move focus into it
            // so keyboard/SR users actually arrive in the dialog. Modals
            // listed in `knownIssues.focusNotMovedOnOpen` are flagged
            // ``test.fixme`` until the show path adds a focus() call.
            await gotoHostPage(page, spec);
            await spec.open(page);
            await expect(page.locator(`#${spec.id}`)).toHaveClass(/active/);
            const focusInsideModal = await page.evaluate((id) => {
                const modal = document.getElementById(id);
                if (!modal) return false;
                const active = document.activeElement;
                if (!active || active === document.body) return false;
                return modal.contains(active);
            }, spec.id);
            expect(
                focusInsideModal,
                `${spec.id}: focus did not enter modal on open (a11y: keyboard/SR users still on previous element)`,
            ).toBe(true);
        });

        const closedHiddenTest = spec.knownIssues?.ariaHiddenNotResetOnClose
            ? test.fixme
            : test;
        closedHiddenTest('aria-hidden is reset to "true" after close', async ({ page }) => {
            // ARIA modal pattern: when closed, the .modal block becomes
            // inert again; aria-hidden should match. Only `new-chat-modal`
            // restores this today — every other modal's close path is
            // listed in `knownIssues.ariaHiddenNotResetOnClose`.
            await gotoHostPage(page, spec);
            await spec.open(page);
            const modal = page.locator(`#${spec.id}`);
            await expect(modal).toHaveClass(/active/);
            // Close via whichever path is supported, in order of preference.
            if (spec.closesOnEscape) {
                await page.keyboard.press('Escape');
            } else if (spec.closeButtonSelector) {
                await page.locator(spec.closeButtonSelector).first().click();
            } else if (spec.closesOnBackdrop) {
                await modal.locator('.modal-overlay').first().click({
                    position: { x: 5, y: 5 },
                });
            }
            await expect(modal).not.toHaveClass(/active/);

            const ariaHidden = await modal.getAttribute('aria-hidden');
            expect(
                ariaHidden,
                `${spec.id} aria-hidden after close (expected "true" so SRs ignore closed-modal content)`,
            ).toBe('true');
        });
    });
}

test.describe('Modal cross-cutting concerns', () => {
    test('Escape on an empty page (no modal open) does not throw', async ({ page }) => {
        // Capture page errors during this stretch.
        const errs: string[] = [];
        page.on('pageerror', (e) => errs.push(e.message));
        await page.keyboard.press('Escape');
        await page.keyboard.press('Escape');
        // We expect no errors and the URL stayed put.
        expect(errs, errs.join('\n')).toEqual([]);
        expect(page.url()).toContain('/index.html');
    });

    test('every modal has a unique id (no duplicates in markup)', async ({ page }) => {
        // Duplicate ids would make modal toggles silently target only the
        // first occurrence — a quiet correctness bug if someone copy-pastes
        // a modal block.
        const ids = await page.evaluate(() => {
            const modals = Array.from(document.querySelectorAll('.modal'));
            return modals.map((m) => m.id).filter((id) => id !== '');
        });
        const unique = new Set(ids);
        expect(
            unique.size,
            `duplicate modal ids: ${JSON.stringify(ids)}`,
        ).toBe(ids.length);
        // And: every modal in our spec list exists in the page.
        for (const m of MODALS) {
            expect(ids, `spec lists ${m.id} but it's missing from index.html`).toContain(m.id);
        }
    });

    test('every modal has role + aria-modal in markup (static check)', async ({ page }) => {
        // Static markup invariant — every .modal element should ship the
        // dialog/alertdialog role + aria-modal=true so screen readers treat
        // it as a modal context. Failing this means a future modal was
        // added without ARIA wiring.
        const flaws = await page.evaluate(() => {
            const modals = Array.from(document.querySelectorAll('.modal'));
            return modals.map((m) => ({
                id: m.id || '(no-id)',
                role: m.getAttribute('role'),
                ariaModal: m.getAttribute('aria-modal'),
            })).filter(
                (m) =>
                    !(m.role === 'dialog' || m.role === 'alertdialog') ||
                    m.ariaModal !== 'true',
            );
        });
        expect(
            flaws,
            `Modals with bad ARIA wiring: ${JSON.stringify(flaws, null, 2)}`,
        ).toEqual([]);
    });
});
