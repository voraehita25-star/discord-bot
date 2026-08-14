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

/**
 * Settings sections in the palette.
 *
 * The Settings page is 3,023px — 3.8 screens at the 800px design height — and
 * has no sub-navigation by design, so until these commands existed every
 * section but the first was reachable only by scrolling until you recognised
 * its heading. The palette's own docstring had already named the gap ("Settings
 * alone is eight stacked cards deep") without closing it.
 */
test('every Settings section is in the palette, and the set is read off the page', async ({
    page,
}) => {
    const onPage = await page.evaluate(() =>
        Array.from(document.querySelectorAll('#page-settings .settings-card h2')).map((h) =>
            (h.textContent || '').replace(/\s+/g, ' ').trim(),
        ),
    );
    expect(onPage.length, 'the settings page grew or lost cards').toBeGreaterThan(4);

    await open(page);
    const inPalette = (await page.locator(rows).allTextContents())
        .map((t) => t.replace(/\s+/g, ' ').trim())
        .filter((t) => t.startsWith('Settings:'))
        .map((t) => t.replace(/^Settings:\s*/, ''));

    // Not "contains" — EQUAL. The commands are derived from the DOM precisely
    // so the two can never drift; asserting the weaker relation would let a
    // hardcoded list creep back in and still pass.
    expect(inPalette, 'the palette and the page disagree about the sections').toEqual(onPage);
});

test('a Settings section is findable by the name of a setting inside it', async ({ page }) => {
    // Keywords are the card's own control captions, so you can search for the
    // thing you want to change rather than the section someone filed it under.
    await open(page);
    await page.keyboard.type('display name');
    await expect(
        page.locator(rows).first(),
        '"Display Name" is a caption in the Profile card',
    ).toContainText('Settings: Profile');
});

/** Where a section sits relative to the reading column, and whether it all fits. */
const sectionBox = (page: Page, heading: string): Promise<{ top: number; inView: boolean } | null> =>
    page.evaluate((h) => {
        const card = Array.from(
            document.querySelectorAll<HTMLElement>('#page-settings .settings-card'),
        ).find((c) => (c.querySelector('h2')?.textContent || '').trim() === h);
        const content = document.querySelector('.content');
        if (!card || !content) return null;
        const c = card.getBoundingClientRect();
        const v = content.getBoundingClientRect();
        return {
            top: Math.round(c.top - v.top),
            inView: c.top >= v.top - 1 && c.bottom <= v.bottom + 1,
        };
    }, heading);

const runCommand = async (page: Page, query: string, label: string): Promise<void> => {
    await open(page);
    await page.keyboard.type(query);
    await expect(page.locator(rows).first()).toContainText(label);
    await page.keyboard.press('Enter');
    await expect(page.locator('#page-settings')).toHaveClass(/active/);
};

const focusedSection = (page: Page): Promise<string | null> =>
    page.evaluate(() => {
        const el = document.activeElement as HTMLElement | null;
        if (!el?.classList.contains('settings-card')) return null;
        return (el.querySelector('h2')?.textContent || '').trim();
    });

test('running one scrolls to its section and hands it the cursor', async ({ page }) => {
    // Instant scroll, so the assertion is not racing an animation.
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await runCommand(page, 'display name', 'Settings: Profile');

    // Near the top of the reading column, and NOT flush against it — the card
    // carries scroll-margin-top so an arrival is framed. `block: 'start'` would
    // otherwise put the heading hard on the scrollport edge.
    await expect
        .poll(async () => (await sectionBox(page, 'Profile'))?.top ?? -1, {
            message: 'the Profile card never reached the top of the reading column',
        })
        .toBeLessThan(80);
    expect((await sectionBox(page, 'Profile'))!.top, 'flush against the edge').toBeGreaterThan(4);

    // A jump that moves only pixels leaves the keyboard and screen-reader
    // cursor behind — the standard skip-link defect. Focus follows the scroll.
    expect(await focusedSection(page), 'focus was not moved to the section').toBe('Profile');
});

test('the LAST section still arrives fully in view, where no scroll can top-align it', async ({
    page,
}) => {
    // The bottom card cannot reach the scrollport top — there is not a
    // viewport's worth of page beneath it, so the browser stops at max scroll
    // and it lands mid-screen. That is unavoidable and is exactly why the
    // focus move matters: it, not the scroll position, is what marks the
    // arrival. Assert the contract that DOES hold everywhere — the whole
    // section is on screen, and the cursor is on it.
    await page.emulateMedia({ reducedMotion: 'reduce' });
    const last = await page.evaluate(() => {
        const cards = document.querySelectorAll('#page-settings .settings-card h2');
        return (cards[cards.length - 1]?.textContent || '').replace(/\s+/g, ' ').trim();
    });
    await runCommand(page, last.toLowerCase(), `Settings: ${last}`);

    await expect
        .poll(async () => (await sectionBox(page, last))?.inView ?? false, {
            message: `the ${last} card did not come fully into view`,
        })
        .toBe(true);
    expect(await focusedSection(page)).toBe(last);
});

test('the eight section rows put nothing destructive in reach', async ({ page }) => {
    // The section labels are derived from page headings, so a future card named
    // e.g. "Reset Everything" would silently arm Enter-on-top-hit. Same guard as
    // the authored commands, applied to the derived ones.
    await open(page);
    const derived = (await page.locator(rows).allTextContents()).filter((t) =>
        t.includes('Settings:'),
    );
    expect(derived.length).toBeGreaterThan(4);
    for (const word of ['clear', 'delete', 'wipe', 'reset', 'remove']) {
        expect(derived.join(' ').toLowerCase()).not.toContain(word);
    }
});
