import { expect, test } from '@playwright/test';
import { installDashboardMocks } from './_fixtures/mock-tauri';

/**
 * Real user-flow tests — type, click, keyboard, focus.
 * These exercise the bits jsdom can't reliably simulate (focus order,
 * synthetic event timing, animations, computed layout under interaction).
 */

test.beforeEach(async ({ page }) => {
    await installDashboardMocks(page);
    await page.goto('/index.html');
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(250);
});

test.describe('Navigation interactions', () => {
    test('clicking sidebar nav switches page', async ({ page }) => {
        // 'config' was renamed to 'settings' in the sidebar; 'history' is the
        // AI History page added alongside the rename fix.
        await page.click('[data-page="settings"]');
        await expect(page.locator('#page-settings')).toHaveClass(/active/);
        await page.click('[data-page="history"]');
        await expect(page.locator('#page-history')).toHaveClass(/active/);
        await page.click('[data-page="logs"]');
        await expect(page.locator('#page-logs')).toHaveClass(/active/);
    });

    test('Ctrl+1 keyboard shortcut switches to status', async ({ page }) => {
        await page.click('[data-page="logs"]');
        await page.keyboard.press('Control+1');
        await expect(page.locator('#page-status')).toHaveClass(/active/);
    });

    test('Ctrl+2 switches to chat', async ({ page }) => {
        await page.keyboard.press('Control+2');
        await expect(page.locator('#page-chat')).toHaveClass(/active/);
    });
});

test.describe('Theme toggle', () => {
    test('clicking Toggle Theme switches data-theme attribute', async ({ page }) => {
        const before = await page.locator('html').getAttribute('data-theme');
        // Toggle button has the .toggle-theme-btn class or sits in sidebar-footer.
        const toggle = page.locator('button:has-text("Toggle Theme")').first();
        await toggle.click();
        await page.waitForTimeout(150);
        const after = await page.locator('html').getAttribute('data-theme');
        expect(after).not.toBe(before);
    });

    test('theme persists across reload (via settings)', async ({ page }) => {
        // Persistence is real and testable: toggleTheme() -> saveSettings()
        // writes the localStorage key 'dashboard-settings', and on reload
        // loadSettings() reads it back BEFORE initTheme() applies it (app.ts
        // 217 -> 224). localStorage survives page.reload() in the same context,
        // so a regression that stops persisting the theme WILL fail here.
        const before = await page.locator('html').getAttribute('data-theme');
        const toggle = page.locator('button:has-text("Toggle Theme")').first();
        await toggle.click();
        await page.waitForTimeout(150);
        const themeAfterToggle = await page.locator('html').getAttribute('data-theme');
        // The toggle must actually flip the theme, otherwise the persistence
        // assertion below would be vacuously satisfied.
        expect(themeAfterToggle).not.toBe(before);
        await page.reload();
        await page.waitForTimeout(300);
        const themeAfterReload = await page.locator('html').getAttribute('data-theme');
        // The persisted (toggled) value must survive the reload exactly.
        expect(themeAfterReload).toBe(themeAfterToggle);
    });
});

test.describe('Chat input behaviors', () => {
    // Helper: nav to chat + un-hide the conversation container so #chat-input
    // is actually interactable (it's nested inside chat-container which stays
    // .hidden until a real conversation loads — the empty state covers it).
    async function openChatWithVisibleInput(page: import('@playwright/test').Page): Promise<void> {
        await page.click('[data-page="chat"]');
        await page.evaluate(() => {
            document.getElementById('chat-not-running-overlay')?.classList.remove('visible');
            document.getElementById('chat-empty')?.style.setProperty('display', 'none');
            const c = document.getElementById('chat-container');
            if (c) {
                c.classList.remove('hidden');
                c.style.display = 'flex';
                c.style.flexDirection = 'column';
                c.style.height = '100%';
            }
        });
        await page.locator('#chat-input').waitFor({ state: 'visible', timeout: 3000 });
    }

    test('typing in chat input updates value', async ({ page }) => {
        await openChatWithVisibleInput(page);
        await page.locator('#chat-input').fill('Hello world');
        await expect(page.locator('#chat-input')).toHaveValue('Hello world');
    });

    test('Enter triggers submit (sends a frame to the mock WS)', async ({ page }) => {
        await openChatWithVisibleInput(page);
        // Need an active conversation for sendMessage to actually emit.
        await page.evaluate(() => {
            const cm = (window as unknown as {
                chatManager?: {
                    currentConversation?: unknown;
                    isStreaming?: boolean;
                };
            }).chatManager;
            if (cm) {
                cm.currentConversation = {
                    id: 'test-conv-1',
                    title: 'Test',
                    role_preset: 'general',
                };
                cm.isStreaming = false;
            }
        });
        const input = page.locator('#chat-input');
        await input.click();
        await input.type('Test message');
        await input.press('Enter');
        await page.waitForTimeout(200);
        // Verify a frame was sent (the mock captures every send())
        const frames = await page.evaluate(
            () => (window as unknown as { __mockWsLastSent?: { frames: string[] } })
                .__mockWsLastSent?.frames ?? [],
        );
        // With currentConversation set + isStreaming=false, sendMessage's guards
        // pass and it must emit a 'message' frame the mock WS captured. Assert
        // that deterministically (the old `frames.length >= 0` was a tautology).
        const messageFrames = frames.filter((f) => {
            try {
                return (JSON.parse(f) as { type?: string }).type === 'message';
            } catch {
                return false;
            }
        });
        expect(messageFrames.length, `no 'message' frame sent; frames=${JSON.stringify(frames)}`)
            .toBeGreaterThan(0);
        // And the input is cleared on a successful send.
        await expect(input).toHaveValue('');
    });

    test('Shift+Enter adds newline instead of sending', async ({ page }) => {
        await openChatWithVisibleInput(page);
        const input = page.locator('#chat-input');
        await input.click();
        await input.type('Line1');
        await input.press('Shift+Enter');
        await input.type('Line2');
        const value = await input.inputValue();
        expect(value).toContain('\n');
    });

    test('chat-input has focus ring when keyboard-focused', async ({ page }) => {
        await openChatWithVisibleInput(page);
        await page.locator('body').click({ position: { x: 1, y: 1 } });

        // Capture the resting (unfocused) ring properties first. The element may
        // carry a static box-shadow at rest, so "boxShadow !== 'none'" alone is
        // NOT proof of a focus ring (dash-tests-missed-4) — we compare before vs
        // after keyboard focus instead.
        const restRing = await page.locator('#chat-input').evaluate((el) => {
            const cs = getComputedStyle(el);
            return { outline: cs.outline, outlineWidth: cs.outlineWidth, boxShadow: cs.boxShadow };
        });

        // Tab through until we land on chat-input (it sits after the sidebar +
        // chat controls in tab order).
        let reached = false;
        for (let i = 0; i < 40; i++) {
            await page.keyboard.press('Tab');
            reached = await page.evaluate(() => document.activeElement?.id === 'chat-input');
            if (reached) break;
        }
        // Fail (don't no-op) when Tab can't reach the input — an unreachable
        // chat input is itself a keyboard-accessibility regression.
        expect(reached, 'Tab never reached #chat-input').toBe(true);

        const focusRing = await page.locator('#chat-input').evaluate((el) => {
            const cs = getComputedStyle(el);
            return { outline: cs.outline, outlineWidth: cs.outlineWidth, boxShadow: cs.boxShadow };
        });
        // A real :focus-visible ring must change the computed outline/box-shadow
        // relative to the resting state — a removed ring would leave them equal.
        const ringChanged =
            focusRing.outline !== restRing.outline ||
            focusRing.outlineWidth !== restRing.outlineWidth ||
            focusRing.boxShadow !== restRing.boxShadow;
        expect(
            ringChanged,
            `focus ring did not change computed style on keyboard focus: rest=${JSON.stringify(restRing)} focus=${JSON.stringify(focusRing)}`,
        ).toBe(true);
    });
});

test.describe('Modal interactions', () => {
    test('avatar crop modal: Escape really closes', async ({ page }) => {
        await page.evaluate(() => {
            document.getElementById('avatar-crop-modal')?.classList.add('active');
        });
        await expect(page.locator('#avatar-crop-modal')).toHaveClass(/active/);
        await page.keyboard.press('Escape');
        await expect(page.locator('#avatar-crop-modal')).not.toHaveClass(/active/);
    });

    test('avatar crop modal: clicking overlay closes', async ({ page }) => {
        await page.evaluate(() => {
            document.getElementById('avatar-crop-modal')?.classList.add('active');
        });
        // Default click goes to element center, where modal-content sits.
        // Click a corner of the overlay (which is full-size) to actually
        // hit the backdrop, the same way a user clicking outside the dialog would.
        await page.locator('#avatar-crop-modal .modal-overlay').click({
            force: true,
            position: { x: 5, y: 5 },
        });
        await expect(page.locator('#avatar-crop-modal')).not.toHaveClass(/active/);
    });

    test('avatar crop modal: clicking close (×) button closes', async ({ page }) => {
        await page.evaluate(() => {
            document.getElementById('avatar-crop-modal')?.classList.add('active');
        });
        await page.locator('#avatar-crop-close').click();
        await expect(page.locator('#avatar-crop-modal')).not.toHaveClass(/active/);
    });

    test('rename modal in chat page: Escape closes (when shown via chatManager flow)', async ({ page }) => {
        await page.click('[data-page="chat"]');
        // Show rename modal via the proper API so the Escape handler binds.
        await page.evaluate(() => {
            const cm = (window as unknown as {
                chatManager?: {
                    convModals?: { showRename: (id: string) => void };
                    currentConversation?: { id: string; title: string };
                    isStreaming?: boolean;
                    conversations?: Array<{ id: string; title: string }>;
                };
            }).chatManager;
            if (cm?.convModals) {
                cm.conversations = [{ id: 'test-1', title: 'Test Conv' }];
                cm.isStreaming = false;
                cm.convModals.showRename('test-1');
            }
        });
        // First assert the modal actually opened — a showRename() that fails to
        // add .active is exactly the regression this test should catch, so don't
        // silently skip when it didn't open (dash-tests-missed-2).
        await expect(page.locator('#rename-modal')).toHaveClass(/active/);
        // Then Escape must close it.
        await page.keyboard.press('Escape');
        await expect(page.locator('#rename-modal')).not.toHaveClass(/active/);
    });
});

test.describe('Conversation list interactions', () => {
    test('clicking + New Chat button opens new conversation flow', async ({ page }) => {
        await page.click('[data-page="chat"]');
        // Hide the bot-not-running overlay that intercepts pointer events
        // when the bot isn't online (mock returns is_running: false).
        await page.evaluate(() => {
            const ov = document.getElementById('chat-not-running-overlay');
            if (ov) ov.style.display = 'none';
        });
        const newBtn = page.locator('#btn-new-chat-main');
        // Fail (don't silently skip) if the button is missing — its absence is
        // itself a regression this test should catch.
        await expect(newBtn).toHaveCount(1);
        await newBtn.click({ force: true });
        // The + New Chat flow opens the new-chat modal (showNewChatModal adds
        // .active to #new-chat-modal). Assert that concrete outcome rather than
        // the old `modalCount + convCount >= 0` tautology.
        await expect(page.locator('#new-chat-modal')).toHaveClass(/active/);
    });
});

test.describe('Console error vigilance during interaction', () => {
    test('clicking through every nav item produces no console errors', async ({ page }) => {
        const errors: string[] = [];
        page.on('console', (msg) => {
            if (msg.type() === 'error') errors.push(msg.text());
        });
        for (const dataPage of ['chat', 'logs', 'connections', 'config', 'about', 'history', 'status']) {
            const item = page.locator(`[data-page="${dataPage}"]`);
            if ((await item.count()) > 0) {
                await item.click();
                await page.waitForTimeout(200);
            }
        }
        const real = errors.filter(
            (e) =>
                !e.includes('Failed to load resource') &&
                !e.includes('Refused to apply inline style') &&
                !e.includes("'frame-ancestors' is ignored") &&
                !e.includes('WebSocket'),
        );
        expect(real, real.join('\n---\n')).toEqual([]);
    });
});

test.describe('Forced-colors keyboard focus (WCAG 2.4.7)', () => {
    // Regression for the orbital.css "authoritative" focus block losing on
    // specificity to styles.css L5030 `outline:none`. Under forced-colors
    // (Windows High Contrast) the OS strips box-shadow, so a *visible outline*
    // is the only possible focus indicator — it must NOT be `none`. The orbital
    // block must therefore match (0,2,0) so source-order-LAST actually wins.
    test.use({ forcedColors: 'active' });

    // #theme-toggle carries the .theme-toggle class the finding flagged as
    // missing from the forced-colors rescue; #btn-start is a .btn primary
    // control; the sidebar status link is a .nav-item.
    const targets: Array<[string, string]> = [
        ['#btn-start', '.btn primary control'],
        ['.nav-item[data-page="status"]', '.nav-item sidebar link'],
        ['#theme-toggle', '.theme-toggle'],
    ];

    for (const [selector, name] of targets) {
        test(`${name} shows a non-none outline on keyboard focus`, async ({ page }) => {
            const el = page.locator(selector).first();
            await expect(el).toHaveCount(1);
            // Land REAL keyboard focus on the target (Tab modality) so
            // :focus-visible deterministically matches in Chromium — a bare
            // .focus() does not flag :focus-visible on a <button>. Bound the
            // walk; the controls are all reachable from the top of the page.
            await page.locator('body').click({ position: { x: 1, y: 1 } });
            let reached = false;
            for (let i = 0; i < 60; i++) {
                await page.keyboard.press('Tab');
                reached = await el.evaluate((node) => node === document.activeElement);
                if (reached) break;
            }
            expect(reached, `${name}: never received keyboard focus via Tab`).toBe(true);
            const ring = await el.evaluate((node) => {
                const cs = getComputedStyle(node, null);
                return { outline: cs.outline, outlineStyle: cs.outlineStyle, outlineWidth: cs.outlineWidth };
            });
            // In forced-colors mode box-shadow is dropped by the UA, so the only
            // valid indicator is a real outline (style !== none, width > 0).
            expect(
                ring.outlineStyle,
                `${name}: outline-style is "${ring.outlineStyle}" (full: ${JSON.stringify(ring)}) — `
                + 'forced-colors keyboard focus is invisible (orbital focus block lost on specificity).',
            ).not.toBe('none');
            expect(
                ring.outlineWidth,
                `${name}: outline-width is 0 (${JSON.stringify(ring)})`,
            ).not.toBe('0px');
        });
    }

    test('#chat-input shows a non-none outline on keyboard focus', async ({ page }) => {
        // The chat textarea is the highest-traffic control. styles.css sets
        // `#chat-input:focus{outline:none}` at ID specificity (1,1,0), which the
        // (0,2,0) authoritative block cannot beat — only orbital's matching
        // `#chat-input:focus-visible` (1,1,0, source-order-last) overrides it, so
        // forced-colors keyboard focus stays visible on the message box.
        await page.click('[data-page="chat"]');
        await page.evaluate(() => {
            document.getElementById('chat-not-running-overlay')?.classList.remove('visible');
            document.getElementById('chat-empty')?.style.setProperty('display', 'none');
            const c = document.getElementById('chat-container');
            if (c) {
                c.classList.remove('hidden');
                c.style.display = 'flex';
            }
        });
        const input = page.locator('#chat-input');
        await input.waitFor({ state: 'visible', timeout: 3000 });
        await page.locator('body').click({ position: { x: 1, y: 1 } });
        let reached = false;
        for (let i = 0; i < 60; i++) {
            await page.keyboard.press('Tab');
            reached = await page.evaluate(() => document.activeElement?.id === 'chat-input');
            if (reached) break;
        }
        expect(reached, '#chat-input never received keyboard focus via Tab').toBe(true);
        const ring = await input.evaluate((node) => {
            const cs = getComputedStyle(node, null);
            return { outlineStyle: cs.outlineStyle, outlineWidth: cs.outlineWidth };
        });
        expect(
            ring.outlineStyle,
            `#chat-input: outline-style is "${ring.outlineStyle}" (${JSON.stringify(ring)}) — `
            + 'forced-colors keyboard focus invisible (styles.css #chat-input:focus{outline:none} won on ID specificity).',
        ).not.toBe('none');
        expect(
            ring.outlineWidth,
            `#chat-input: outline-width is 0 (${JSON.stringify(ring)})`,
        ).not.toBe('0px');
    });
});

test.describe('Responsive layout', () => {
    test('no horizontal scrollbar appears at common widths', async ({ page }) => {
        // Body has overflow:hidden so no scrollbar can appear regardless;
        // the user-facing question is "does any visible interactive element
        // get clipped or pushed off-screen?". Assert against
        // `getBoundingClientRect().right` of every interactive element.
        for (const w of [1280, 1024, 800]) {
            await page.setViewportSize({ width: w, height: 720 });
            await page.waitForTimeout(150);
            const diag = await page.evaluate(() => {
                const interactive = Array.from(document.querySelectorAll(
                    'button, a, input, textarea, select, [role="button"]',
                ));
                let worst = { tag: '', id: '', right: 0 };
                for (const el of interactive) {
                    const r = el.getBoundingClientRect();
                    // Skip hidden elements (rect.width=0 means display:none).
                    if (r.width === 0) continue;
                    if (r.right > worst.right) {
                        worst = {
                            tag: el.tagName,
                            id: (el as HTMLElement).id,
                            right: r.right,
                        };
                    }
                }
                return { worst, viewportWidth: window.innerWidth };
            });
            expect(
                diag.worst.right,
                `width=${w}: interactive element extends past viewport: ${JSON.stringify(diag.worst)}`,
            ).toBeLessThanOrEqual(diag.viewportWidth + 5);
        }
    });
});
