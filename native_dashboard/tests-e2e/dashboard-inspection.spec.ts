/**
 * Dashboard UI deep inspection — permanent regression suite.
 *
 * Walks every nav page, exercises common flows, and asserts:
 *   - no console errors / runtime exceptions / network failures
 *   - no broken-image flashes (empty img.src)
 *   - no layout overflow past viewport at supported widths (>= 800px,
 *     enforced by Tauri minWidth)
 *   - avatar-crop modal opens, ESC closes, no listener leak
 *   - keyboard focus is visible; nav buttons have accessible names
 *   - toast container z-index sits above modals
 *
 * Findings also written to test-results/inspection-findings.json for
 * historical tracking. Sakura-blossom decorative animation is filtered
 * out of layout overflow checks (intentional off-viewport drift).
 */
import { test, expect, type Page, type ConsoleMessage } from '@playwright/test';
import { installDashboardMocks } from './_fixtures/mock-tauri';
import * as fs from 'node:fs';
import * as path from 'node:path';

interface InspectionFinding {
    page: string;
    kind: 'console-error' | 'console-warning' | 'network-failure' | 'broken-image' | 'a11y' | 'layout' | 'js-runtime';
    detail: string;
    location?: string;
}

const findings: InspectionFinding[] = [];

// Real nav items rendered in ui/index.html (not the speculative list I had).
const PAGES = ['status', 'chat', 'logs', 'database', 'settings', 'history'];

function attachLogging(page: Page, pageName: string): void {
    page.on('console', (msg: ConsoleMessage) => {
        const t = msg.type();
        if (t === 'error') {
            findings.push({
                page: pageName,
                kind: 'console-error',
                detail: msg.text(),
                location: msg.location() ? `${msg.location().url}:${msg.location().lineNumber}` : undefined,
            });
        } else if (t === 'warning') {
            // Filter out vendor/CDN-style warnings that are noise
            const text = msg.text();
            const noise = [
                'Tauri not available',  // expected: tests run without Tauri
                'WebSocket connection failed', // expected with mock backend
                'Failed to load resource',  // sometimes occurs during teardown
            ];
            if (!noise.some(n => text.includes(n))) {
                findings.push({
                    page: pageName,
                    kind: 'console-warning',
                    detail: text,
                });
            }
        }
    });

    page.on('pageerror', (err) => {
        findings.push({
            page: pageName,
            kind: 'js-runtime',
            detail: `${err.name}: ${err.message}`,
            location: err.stack?.split('\n')[1]?.trim(),
        });
    });

    page.on('requestfailed', (req) => {
        // Ignore known mock-WS failures
        const url = req.url();
        if (url.startsWith('ws://') || url.startsWith('wss://')) return;
        findings.push({
            page: pageName,
            kind: 'network-failure',
            detail: `${req.method()} ${url} — ${req.failure()?.errorText ?? 'unknown'}`,
        });
    });
}

test.describe('Dashboard UI deep inspection', () => {
    test.beforeEach(async ({ page }) => {
        await installDashboardMocks(page);
    });

    test('every nav page loads without console errors', async ({ page }) => {
        // Snapshot the count so we only assert on console/runtime entries this
        // test produced (findings[] is shared across the whole suite).
        const baseFindingCount = findings.length;
        attachLogging(page, '<bootstrap>');
        await page.goto('/index.html');
        await page.waitForLoadState('networkidle');

        for (const navPage of PAGES) {
            await page.click(`[data-page="${navPage}"]`);
            await page.waitForTimeout(300);  // settle
            // Page sections in this app use id="page-<name>" + class="page active"
            // (NOT "<name>-page" + .hidden as I first assumed).
            const visible = await page.evaluate((id) => {
                const el = document.getElementById(`page-${id}`);
                return el ? el.classList.contains('active') : false;
            }, navPage);
            expect(visible, `${navPage} page should be active after click`).toBe(true);
        }

        // Enforce the "without console errors" half of the test name: any console
        // error / runtime exception / network failure raised during navigation
        // must fail CI, not just land in the JSON report. Filter the same
        // mock-environment noise the other suites tolerate.
        const consoleNoise = ['Failed to load resource', 'WebSocket', "'frame-ancestors' is ignored"];
        const newErrors = findings
            .slice(baseFindingCount)
            .filter((f) => f.kind === 'console-error' || f.kind === 'js-runtime' || f.kind === 'network-failure')
            .filter((f) => !consoleNoise.some((n) => f.detail.includes(n)))
            .map((f) => `[${f.kind}] ${f.page}: ${f.detail}`);
        expect(newErrors, newErrors.join('\n')).toEqual([]);
    });

    test('chat page: input, send, conversation list', async ({ page }) => {
        attachLogging(page, 'chat');
        await page.goto('/index.html');
        await page.waitForLoadState('networkidle');
        await page.click('[data-page="chat"]');
        await page.waitForTimeout(500);  // wait for page transition + render

        // Wait for chat page to actually become active first
        await page.waitForFunction(() => {
            const p = document.getElementById('page-chat');
            return p?.classList.contains('active');
        });

        // The chat input is gated behind two layers:
        //   1. "Bot Not Running" overlay (chat-not-running-overlay)
        //   2. The chat-container is .hidden until a conversation is opened
        // For UI-surface verification we drop both — we're not testing the
        // gating logic here, we're testing the input itself.
        // Force chat-container visible. Setting style.display directly wins
        // over any class-based rule short of !important — the .hidden class
        // is the only !important rule and we've already removed that.
        await page.evaluate(() => {
            const overlay = document.getElementById('chat-not-running-overlay');
            if (overlay) overlay.style.display = 'none';
            const empty = document.getElementById('chat-empty');
            if (empty) empty.classList.add('hidden');
            const container = document.getElementById('chat-container');
            if (container) {
                container.classList.remove('hidden');
                container.style.display = 'flex';
            }
        });

        const input = page.locator('#chat-input');
        await expect(input).toBeVisible();
        await input.fill('test message');
        await expect(input).toHaveValue('test message');

        // Verify the isStreaming contract is exposed and idle. chatManager must
        // EXIST (fixture contract) and the flag must be literally false —
        // toBeFalsy() also passed on undefined, i.e. with no chatManager at all.
        // (The actual double-send race is exercised by C3 in dashboard-smoke.)
        const before = await page.evaluate(() => (window as unknown as { chatManager?: { isStreaming: boolean } }).chatManager?.isStreaming);
        expect(before).toBe(false);

        // Conversation list should at least render its container
        const convList = page.locator('#conversation-list');
        await expect(convList).toBeVisible();

        // Provider select has aria-label (real id is #chat-ai-provider)
        const aiProviderSelect = page.locator('#chat-ai-provider');
        if (await aiProviderSelect.count() > 0) {
            const label = await aiProviderSelect.getAttribute('aria-label');
            expect(label, 'AI provider select must have aria-label').toBeTruthy();
        }
    });

    test('avatar crop modal: open, ESC closes, no listener leak', async ({ page }) => {
        attachLogging(page, 'avatar-crop');
        // Count document-level 'keydown' listener registrations so the
        // "no listener leak" claim below is actually falsifiable — the old
        // version only asserted the modal ends hidden, which passes identically
        // WITH a leak (5 stacked handlers each remove the same .active class).
        await page.addInitScript(() => {
            let keydownCount = 0;
            (window as unknown as { __docKeydownCount: () => number }).__docKeydownCount =
                () => keydownCount;
            const origAdd = document.addEventListener.bind(document);
            const origRemove = document.removeEventListener.bind(document);
            document.addEventListener = ((type: string, ...rest: unknown[]) => {
                if (type === 'keydown') keydownCount++;
                return (origAdd as (...a: unknown[]) => unknown)(type, ...rest);
            }) as typeof document.addEventListener;
            document.removeEventListener = ((type: string, ...rest: unknown[]) => {
                if (type === 'keydown') keydownCount--;
                return (origRemove as (...a: unknown[]) => unknown)(type, ...rest);
            }) as typeof document.removeEventListener;
        });
        await page.goto('/index.html');
        await page.waitForLoadState('networkidle');

        // Modals in this app are opened by adding `.active` (CSS rule
        // `.modal.active { display: flex }`). The previous attempt removed
        // a `.hidden` class that doesn't exist on these elements.
        const openModal = async () => {
            await page.evaluate(() => {
                const modal = document.getElementById('avatar-crop-modal');
                if (modal) modal.classList.add('active');
            });
        };

        await openModal();
        const modal = page.locator('#avatar-crop-modal');
        await expect(modal).toBeVisible();

        // ESC should close
        await page.keyboard.press('Escape');
        await page.waitForTimeout(200);
        await expect(modal).toBeHidden();

        // Re-open + close 5 times and assert the NET document keydown listener
        // count doesn't grow — a per-open addEventListener without the matching
        // removeEventListener would add +1 per cycle here (the instrumentation
        // is installed by the addInitScript above, before any page script ran).
        const baseline = await page.evaluate(() =>
            (window as unknown as { __docKeydownCount: () => number }).__docKeydownCount());
        for (let i = 0; i < 5; i++) {
            await openModal();
            await page.keyboard.press('Escape');
            await page.waitForTimeout(50);
        }
        await expect(modal).toBeHidden();
        const after = await page.evaluate(() =>
            (window as unknown as { __docKeydownCount: () => number }).__docKeydownCount());
        expect(after, 'document keydown listeners leaked across modal open/close cycles').toBe(baseline);
    });

    test('responsive: no horizontal scroll at 1280, 1024, 800', async ({ page }) => {
        // 800 is the floor — Tauri config enforces minWidth=800 so we
        // never need to validate below it. (Below 800 the .control-buttons
        // and .log-controls flex rows wrap to the next line, which is the
        // expected break-point; nobody designed for sub-800.)
        attachLogging(page, 'responsive');
        await page.goto('/index.html');
        await page.waitForLoadState('networkidle');

        const layoutFindings: string[] = [];
        for (const w of [1280, 1024, 800]) {
            await page.setViewportSize({ width: w, height: 800 });
            await page.waitForTimeout(150);
            for (const navPage of ['status', 'chat', 'logs']) {
                await page.click(`[data-page="${navPage}"]`);
                await page.waitForTimeout(100);
                const result = await page.evaluate(() => {
                    const overflow = document.documentElement.scrollWidth - document.documentElement.clientWidth;
                    if (overflow <= 1) return { overflow, culprit: null };

                    // Identify the worst element that extends past viewport,
                    // filtering out the decorative sakura-blossom animation
                    // (its petals fall across the screen by design and the
                    // body has overflow:hidden so the user never sees scroll).
                    const vw = window.innerWidth;
                    const all = Array.from(document.querySelectorAll('*'));
                    let worst = { tag: '', id: '', cls: '', right: 0, width: 0 };
                    for (const el of all) {
                        const r = el.getBoundingClientRect();
                        if (r.width === 0 || r.height === 0) continue;
                        const cls = (el.className?.toString?.() || '').toString();
                        const id = (el as HTMLElement).id || '';
                        // Skip the decorative falling-petals layer entirely.
                        // The petals are SVGs (with <ellipse> children) that
                        // animate across the viewport by design — body has
                        // overflow:hidden so the user never sees a scrollbar
                        // from them. Any descendant of the sakura container
                        // is treated as decorative.
                        if (id === 'sakura-container' || cls.includes('sakura-petal')) continue;
                        if (el.closest('#sakura-container, .sakura-petal')) continue;
                        if (r.right > worst.right) {
                            worst = {
                                tag: el.tagName,
                                id,
                                cls: cls.slice(0, 80),
                                right: r.right,
                                width: r.width,
                            };
                        }
                    }
                    // After filtering decorative layers, anything still past
                    // the viewport is a real layout issue.
                    if (worst.right <= vw + 1) return { overflow: 0, culprit: null };
                    return { overflow: worst.right - vw, culprit: { ...worst, viewport: vw } };
                });
                if (result.overflow > 1) {
                    const detail = `${navPage}@${w}px overflow ${result.overflow}px — culprit: ${JSON.stringify(result.culprit)}`;
                    layoutFindings.push(detail);
                    findings.push({
                        page: `${navPage}@${w}px`,
                        kind: 'layout',
                        detail: `overflow ${result.overflow}px — culprit: ${JSON.stringify(result.culprit)}`,
                    });
                }
            }
        }
        // Gate CI on the real invariant: no element extends past the viewport at
        // any supported width. Previously this only recorded findings and always
        // passed, so a layout-overflow regression slipped through.
        expect(layoutFindings, layoutFindings.join('\n')).toEqual([]);
    });

    test('image elements never have empty src that flashes broken-image', async ({ page }) => {
        attachLogging(page, 'broken-images');
        await page.goto('/index.html');
        await page.waitForLoadState('networkidle');

        const brokenImages: string[] = [];
        for (const navPage of PAGES) {
            await page.click(`[data-page="${navPage}"]`);
            await page.waitForTimeout(150);
            const broken = await page.$$eval('img', (imgs) =>
                imgs
                    .filter((img) => {
                        const src = img.getAttribute('src');
                        return src === '' || src === null;
                    })
                    .map((img) => img.outerHTML.slice(0, 200)),
            );
            for (const b of broken) {
                brokenImages.push(`${navPage}: ${b}`);
                findings.push({
                    page: navPage,
                    kind: 'broken-image',
                    detail: `<img> with empty src: ${b}`,
                });
            }
        }
        // Assert the invariant the test name promises (mirrors dashboard-smoke):
        // an <img src=""> is the broken-image flash this guards against.
        expect(brokenImages, brokenImages.join('\n')).toEqual([]);
    });

    test('focus-visible ring is rendered on keyboard-focused interactive elements', async ({ page }) => {
        attachLogging(page, 'focus-visible');
        await page.goto('/index.html');
        await page.waitForLoadState('networkidle');

        // Tab a few times and check :focus-visible has an outline
        for (let i = 0; i < 3; i++) {
            await page.keyboard.press('Tab');
        }
        const ringDetected = await page.evaluate(() => {
            const el = document.activeElement as HTMLElement | null;
            if (!el) return false;
            const cs = getComputedStyle(el);
            // Either outline must be set, or box-shadow used as ring
            const hasOutline = cs.outlineStyle !== 'none' && cs.outlineWidth !== '0px';
            const hasShadow = cs.boxShadow !== 'none';
            return hasOutline || hasShadow;
        });
        if (!ringDetected) {
            findings.push({
                page: '<keyboard-focus>',
                kind: 'a11y',
                detail: 'No outline / box-shadow on keyboard-focused element after Tab',
            });
        }
        // A removed focus ring is a real a11y regression — gate CI on it
        // instead of only recording a finding.
        expect(ringDetected, 'no focus ring after Tab').toBe(true);
    });

    test('every nav button has accessible name', async ({ page }) => {
        attachLogging(page, 'nav-aria');
        await page.goto('/index.html');
        await page.waitForLoadState('networkidle');

        const navIssues = await page.$$eval('[data-page]', (btns) =>
            btns
                .filter((b) => {
                    const text = (b.textContent || '').trim();
                    const aria = b.getAttribute('aria-label');
                    const title = b.getAttribute('title');
                    return !text && !aria && !title;
                })
                .map((b) => (b as HTMLElement).outerHTML.slice(0, 150)),
        );
        for (const n of navIssues) {
            findings.push({
                page: 'sidebar',
                kind: 'a11y',
                detail: `nav button without accessible name: ${n}`,
            });
        }
        // A nav button without an accessible name is an a11y regression — assert,
        // don't just record (mirrors the icon-button check in e2e_smoke.test.ts).
        expect(navIssues, navIssues.join('\n')).toEqual([]);
    });

    test('toast container z-index is above all modals', async ({ page }) => {
        attachLogging(page, 'z-index');
        await page.goto('/index.html');
        await page.waitForLoadState('networkidle');

        const ok = await page.evaluate(() => {
            const toast = document.getElementById('toast-container');
            if (!toast) return true;  // no toast container → no issue
            const toastZ = parseInt(getComputedStyle(toast).zIndex, 10) || 0;
            const modals = Array.from(document.querySelectorAll('.modal, [class*="modal-overlay"]'));
            const maxModalZ = modals.length === 0 ? 0 : Math.max(
                ...modals.map((m) => parseInt(getComputedStyle(m).zIndex, 10) || 0),
            );
            return toastZ > maxModalZ;
        });
        if (!ok) {
            findings.push({
                page: 'toast',
                kind: 'layout',
                detail: 'toast-container z-index is not above modals — toast gets hidden behind dialogs',
            });
        }
        // Gate CI on the named invariant (mirrors dashboard-smoke): a toast that
        // drops below modal z-index would otherwise be silently recorded.
        expect(ok, 'toast z-index not above modals').toBe(true);
    });

    test.afterAll(async () => {
        // Write findings to disk so the agent can inspect afterward.
        const out = path.join(process.cwd(), 'test-results', 'inspection-findings.json');
        fs.mkdirSync(path.dirname(out), { recursive: true });
        fs.writeFileSync(out, JSON.stringify(findings, null, 2), 'utf-8');
        console.log(`\n[inspection] wrote ${findings.length} findings to ${out}`);
        for (const f of findings.slice(0, 30)) {
            console.log(`  [${f.kind}] ${f.page}: ${f.detail}`);
        }
    });
});
