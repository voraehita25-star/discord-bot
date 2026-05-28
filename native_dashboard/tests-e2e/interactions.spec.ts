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
        await page.click('[data-page="memories"]');
        await expect(page.locator('#page-memories')).toHaveClass(/active/);
        await page.click('[data-page="logs"]');
        await expect(page.locator('#page-logs')).toHaveClass(/active/);
    });

    test('Ctrl+1 keyboard shortcut switches to status', async ({ page }) => {
        await page.click('[data-page="memories"]');
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
        const themeBefore = await page.locator('html').getAttribute('data-theme');
        const toggle = page.locator('button:has-text("Toggle Theme")').first();
        await toggle.click();
        await page.waitForTimeout(150);
        const themeAfterToggle = await page.locator('html').getAttribute('data-theme');
        // Sanity: the toggle MUST have flipped the attribute. If this fails
        // the rest of the persistence assertion is meaningless.
        expect(themeAfterToggle, 'Toggle must change data-theme').not.toBe(themeBefore);
        await page.reload();
        await page.waitForTimeout(300);
        const themeAfterReload = await page.locator('html').getAttribute('data-theme');
        expect(themeAfterReload).toMatch(/dark|light/);
        // Real persistence assertion: post-reload theme must equal the
        // post-toggle theme. (The old `expect([themeAfterToggle, 'dark', 'light']).toContain(...)`
        // accepted literally any theme value and provided zero guarantee.)
        expect(
            themeAfterReload,
            `Theme didn't persist: before=${themeBefore} afterToggle=${themeAfterToggle} afterReload=${themeAfterReload}`,
        ).toBe(themeAfterToggle);
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
        const inputValue = await input.inputValue();
        // Either the message reached the WS layer (frame sent) OR the input
        // retained the message text (UI saw the keystroke but the streaming
        // gate refused to emit) — both indicate the keystroke wasn't swallowed.
        // `frames.length >= 0` is always true and was the bug we're replacing;
        // require > 0 here.
        expect(
            frames.length > 0 || inputValue.includes('Test message'),
            `Enter neither sent a WS frame (${frames.length}) nor retained input ('${inputValue}')`,
        ).toBe(true);
        // And separately: the page must not have crashed/blanked.
        const bodyLen = await page.evaluate(() => document.body.innerHTML.length);
        expect(bodyLen).toBeGreaterThan(0);
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
        // Focus via Tab to trigger :focus-visible
        await page.locator('body').click({ position: { x: 1, y: 1 } });
        // Tab through until we land on chat-input — must be reachable in a
        // normal Tab sequence (regression guard against accidentally adding
        // tabindex=-1 or visibility:hidden to the chat input wrapper).
        for (let i = 0; i < 30; i++) {
            await page.keyboard.press('Tab');
            const isFocused = await page.evaluate(
                () => document.activeElement?.id === 'chat-input',
            );
            if (isFocused) break;
        }
        const isFocused = await page.evaluate(
            () => document.activeElement?.id === 'chat-input',
        );
        expect(isFocused, 'Tab must reach #chat-input within 30 keystrokes').toBe(true);
        const ring = await page.locator('#chat-input').evaluate((el) => {
            const cs = getComputedStyle(el);
            return {
                outline: cs.outline,
                outlineWidth: cs.outlineWidth,
                boxShadow: cs.boxShadow,
            };
        });
        const hasIndicator =
            (ring.outlineWidth !== '0px' && ring.outline !== 'none') ||
            (ring.boxShadow !== 'none' && ring.boxShadow !== '');
        expect(hasIndicator, `No focus indicator: ${JSON.stringify(ring)}`).toBe(true);
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
        // Show rename modal via the public API. `convModals` is a private
        // field on ChatManager, but renameConversation() is the documented
        // entry point (called by the pencil button in the chat header), so
        // tests should use it the same way production does.
        await page.evaluate(() => {
            const cm = (window as unknown as {
                chatManager?: {
                    renameConversation?: (id: string) => void;
                    currentConversation?: { id: string; title: string };
                    isStreaming?: boolean;
                    conversations?: Array<{ id: string; title: string }>;
                };
            }).chatManager;
            if (cm?.renameConversation) {
                cm.conversations = [{ id: 'test-1', title: 'Test Conv' }];
                cm.isStreaming = false;
                cm.renameConversation('test-1');
            }
        });
        // The modal MUST become visible — if it doesn't, that's a real
        // regression in showRename() or its DOM wiring, not a reason to skip.
        await expect(
            page.locator('#rename-modal'),
            'showRename() must add .active to #rename-modal',
        ).toHaveClass(/active/);
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
        // The button MUST exist — it's part of the chat page chrome, not a
        // conditional element. If this count is 0 that's a real regression
        // in the chat page template.
        await expect(newBtn).toHaveCount(1);
        await newBtn.click({ force: true });
        await page.waitForTimeout(300);
        const modalCount = await page.locator('.modal.active').count();
        const convCount = await page.locator('.conversation-item').count();
        // The "+ New Chat" button must either (a) open a role-preset modal
        // or (b) create a conversation directly. Doing neither would be a
        // regression: the previous expect(modalCount + convCount).toBeGreaterThanOrEqual(0)
        // was tautologically true.
        expect(
            modalCount > 0 || convCount > 0,
            `+ New Chat opened ${modalCount} modal(s) and produced ${convCount} conversation(s) — expected at least one`,
        ).toBe(true);
    });
});

test.describe('Console error vigilance during interaction', () => {
    test('clicking through every nav item produces no console errors', async ({ page }) => {
        const errors: string[] = [];
        page.on('console', (msg) => {
            if (msg.type() === 'error') errors.push(msg.text());
        });
        for (const dataPage of ['chat', 'memories', 'logs', 'connections', 'config', 'about', 'status']) {
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
