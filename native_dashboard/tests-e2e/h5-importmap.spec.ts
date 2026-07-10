/**
 * H5 validation: with ``withGlobalTauri: false`` the app has no
 * ``window.__TAURI__`` global, so the ``invoke`` wrapper (shared.ts) must fall
 * back to a dynamic ``import('@tauri-apps/api/core')`` that the browser resolves
 * via the inline import map in index.html → the locally vendored ESM build at
 * ``vendor/tauri/core.js``. The inline import map is SHA-256 hash-allowlisted in
 * the CSP, so this also catches a wrong/missing CSP hash (Chromium would block
 * the import map and the bare-specifier import would never resolve).
 *
 * Run against Playwright Chromium (close enough to the production WebView2 for
 * import-map + CSP behaviour). Deliberately does NOT install the Tauri mock, so
 * the real fallback path is exercised. The IPC call itself rejects (no native
 * backend in a plain browser) — we only assert the module resolved + loaded and
 * that the CSP did not block the import map.
 */
import { expect, test } from '@playwright/test';

test('H5: invoke dynamic-imports the import-map-resolved vendored Tauri core (no window.__TAURI__)', async ({
    page,
}) => {
    const cspViolations: string[] = [];
    page.on('console', (m) => {
        const t = m.text();
        if (/content security policy|refused to (load|execute)|violates the/i.test(t)) {
            cspViolations.push(t);
        }
    });
    const tauriCoreRequests: string[] = [];
    page.on('request', (r) => {
        if (r.url().includes('/vendor/tauri/core.js')) tauriCoreRequests.push(r.url());
    });

    await page.goto('/index.html');

    // withGlobalTauri:false ⇒ no global exposed to page scripts.
    const hasGlobalTauri = await page.evaluate(
        () => typeof (window as unknown as { __TAURI__?: unknown }).__TAURI__ !== 'undefined',
    );
    expect(hasGlobalTauri, 'window.__TAURI__ must NOT exist when withGlobalTauri is false').toBe(
        false,
    );

    // Drive the real invoke wrapper. With no global + no mock it takes the
    // dynamic-import branch, which the import map resolves to the vendored core.
    await page.evaluate(async () => {
        // Non-literal specifier: the browser resolves '/shared.js' at runtime
        // (via the import map), but a literal would make tsc try to resolve it
        // at compile time (TS2307 — no such module on disk from the spec's dir).
        const spec: string = '/shared.js';
        const mod = (await import(spec)) as { invoke: (c: string) => Promise<unknown> };
        try {
            await mod.invoke('h5_probe_noop');
        } catch {
            // Expected: no native IPC backend in a plain browser. We only care
            // that the import map resolved the module (asserted below).
        }
    });

    expect(
        tauriCoreRequests.length,
        'import map should have resolved @tauri-apps/api/core → /vendor/tauri/core.js',
    ).toBeGreaterThan(0);
    expect(cspViolations, `CSP blocked something:\n${cspViolations.join('\n')}`).toEqual([]);
});
