import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';

import { installPopulatedMocks, waitForDashboardReady } from './_fixtures/mock-tauri';

/**
 * Command palette (Ctrl+K) — behaviour and the a11y contract it inherits.
 *
 * The palette reuses app.ts's openModal/closeModal, so it gets the same inert /
 * focus-trap / restore-focus treatment as every other dialog. That reuse is the
 * point and it is also the thing most likely to be broken by a later change, so
 * it is asserted here rather than assumed.
 */

test.beforeEach(async ({ page }) => {
    await installPopulatedMocks(page);
    await page.goto('/index.html');
    await page.waitForLoadState('domcontentloaded');
    await waitForDashboardReady(page);
});

const palette = '#command-palette';
const input = '#command-palette-input';
const rows = '#command-palette-list .cmdk-item';

async function open(page: Page): Promise<void> {
    await page.keyboard.press('Control+k');
    await expect(page.locator(palette)).toHaveClass(/active/);
}

test('Ctrl+K opens the palette and focuses the search field', async ({ page }) => {
    await open(page);
    await expect(page.locator(input)).toBeFocused();
    // Resting state lists every command, grouped.
    expect(await page.locator(rows).count()).toBeGreaterThan(10);
    expect(await page.locator('#command-palette-list .cmdk-group').count()).toBeGreaterThan(1);
});

test('Ctrl+K again closes it, and so does Escape', async ({ page }) => {
    await open(page);
    await page.keyboard.press('Control+k');
    await expect(page.locator(palette)).not.toHaveClass(/active/);

    await open(page);
    await page.keyboard.press('Escape');
    await expect(page.locator(palette)).not.toHaveClass(/active/);
});

test('the app is inert while the palette is open, and released after', async ({ page }) => {
    await open(page);
    expect(await page.locator('.app').getAttribute('inert')).not.toBeNull();
    await page.keyboard.press('Escape');
    expect(await page.locator('.app').getAttribute('inert')).toBeNull();
});

test('focus returns to whatever was focused before', async ({ page }) => {
    await page.locator('#theme-toggle').focus();
    await open(page);
    await expect(page.locator(input)).toBeFocused();
    await page.keyboard.press('Escape');
    await expect(page.locator('#theme-toggle')).toBeFocused();
});

test('typing filters, and Enter runs the top hit', async ({ page }) => {
    await open(page);
    await page.keyboard.type('logs');
    // Filtered well below the full set, and the best hit is first.
    const count = await page.locator(rows).count();
    expect(count).toBeGreaterThan(0);
    expect(count).toBeLessThan(8);
    await expect(page.locator(rows).first()).toContainText('Go to Logs');

    await page.keyboard.press('Enter');
    await expect(page.locator(palette)).not.toHaveClass(/active/);
    await expect(page.locator('#page-logs')).toHaveClass(/active/);
});

test('the arrows move the selection and the combobox reports it', async ({ page }) => {
    await open(page);
    const first = await page.locator(input).getAttribute('aria-activedescendant');
    expect(first).toBe('cmdk-option-0');
    await expect(page.locator(rows).first()).toHaveAttribute('aria-selected', 'true');

    await page.keyboard.press('ArrowDown');
    expect(await page.locator(input).getAttribute('aria-activedescendant')).toBe('cmdk-option-1');
    await expect(page.locator(rows).nth(1)).toHaveAttribute('aria-selected', 'true');
    await expect(page.locator(rows).first()).toHaveAttribute('aria-selected', 'false');

    // Wraps backwards off the top rather than sticking.
    await page.keyboard.press('ArrowUp');
    await page.keyboard.press('ArrowUp');
    const last = await page.locator(rows).count();
    expect(await page.locator(input).getAttribute('aria-activedescendant'))
        .toBe(`cmdk-option-${last - 1}`);
});

test('aria-activedescendant always names a row that exists', async ({ page }) => {
    // A stale id here is the classic combobox bug: the pointer is announced to
    // a screen reader as being on a row that the last keystroke filtered away.
    await open(page);
    await page.keyboard.type('bot');
    const id = await page.locator(input).getAttribute('aria-activedescendant');
    expect(id).toBeTruthy();
    await expect(page.locator(`#${id}`)).toHaveCount(1);
    await expect(page.locator(`#${id}`)).toHaveAttribute('aria-selected', 'true');
});

test('a query with no hits reports empty and clears the active row', async ({ page }) => {
    await open(page);
    await page.keyboard.type('qqqqqq');
    await expect(page.locator('#command-palette-empty')).toBeVisible();
    expect(await page.locator(rows).count()).toBe(0);
    expect(await page.locator(input).getAttribute('aria-activedescendant')).toBeNull();
    // Enter on nothing must be a no-op, not a crash or a stray navigation.
    await page.keyboard.press('Enter');
    await expect(page.locator(palette)).toHaveClass(/active/);
});

test('it refuses to stack on top of another dialog', async ({ page }) => {
    await page.keyboard.press('?');
    await expect(page.locator('#shortcuts-modal')).toHaveClass(/active/);
    await page.keyboard.press('Control+k');
    // Two openModal owners would both hold app inert, and closing one would
    // lift it while the other was still on screen.
    await expect(page.locator(palette)).not.toHaveClass(/active/);
    await expect(page.locator('#shortcuts-modal')).toHaveClass(/active/);
});

test('the toggle rows say which way they go, and follow the state', async ({ page }) => {
    await open(page);
    await expect(page.locator(rows).filter({ hasText: 'Switch to Light Theme' })).toHaveCount(1);
    await page.keyboard.press('Escape');

    await page.click('#theme-toggle');
    await open(page);
    // Rebuilt on open — a set captured at bootstrap would still offer "Light".
    await expect(page.locator(rows).filter({ hasText: 'Switch to Dark Theme' })).toHaveCount(1);
    await expect(page.locator(rows).filter({ hasText: 'Switch to Light Theme' })).toHaveCount(0);
});

test('it carries no destructive command', async ({ page }) => {
    await open(page);
    const labels = (await page.locator(rows).allTextContents()).join(' ').toLowerCase();
    // Enter fires the top hit, so a mistyped query must not be able to reach
    // anything that deletes data. These live on their own screens on purpose.
    for (const word of ['clear', 'delete', 'wipe', 'reset', 'remove']) {
        expect(labels, `"${word}" must not be reachable from the palette`).not.toContain(word);
    }
});

test('axe finds no violation in the open palette', async ({ page }) => {
    await open(page);
    await page.keyboard.type('go');
    const results = await new AxeBuilder({ page }).include('#command-palette').analyze();
    expect(results.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
});
