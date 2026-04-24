/**
 * Prism.js integration (#11) — lazy language loader + code-block highlighter.
 *
 * Why extracted from chat-manager.ts:
 *   - Pure UI concern with its own caching state (one promise per language).
 *   - No dependency on ChatManager or its message state.
 *   - Keeps the shipped-language list + alias map in one place so adding a
 *     new vendor/prism/prism-*.min.js file only touches this module.
 *
 * Prism core + tomorrow theme are loaded eagerly from index.html. Individual
 * language components (python, rust, etc.) are fetched on demand the first
 * time a code block with that `language-*` class is rendered.
 */
import { errorLogger } from '../shared.js';
/** Languages we shipped bundles for (see native_dashboard/ui/vendor/prism/). */
const PRISM_LANGS = new Set([
    'markup', 'css', 'clike', 'javascript', 'js', 'bash', 'shell', 'c',
    'csharp', 'cs', 'cpp', 'diff', 'go', 'ini', 'java', 'json', 'kotlin',
    'lua', 'markdown', 'md', 'powershell', 'ps1', 'python', 'py', 'ruby',
    'rb', 'rust', 'rs', 'sql', 'swift', 'toml', 'typescript', 'ts', 'yaml', 'yml',
]);
const PRISM_ALIASES = {
    js: 'javascript',
    ts: 'typescript',
    py: 'python',
    rb: 'ruby',
    rs: 'rust',
    cs: 'csharp',
    'c++': 'cpp',
    sh: 'bash',
    shell: 'bash',
    md: 'markdown',
    ps1: 'powershell',
    yml: 'yaml',
};
/** Module-level cache — one promise per language so concurrent highlights de-dupe. */
const loadPromises = new Map();
function getPrism() {
    return window.Prism;
}
/** Normalize alias → canonical Prism id (js → javascript, py → python, …). */
export function canonicalPrismLang(lang) {
    return PRISM_ALIASES[lang] || lang;
}
/** Lazily load a Prism language component via <script> injection. */
export async function loadPrismLanguage(lang) {
    const canon = canonicalPrismLang(lang);
    if (!PRISM_LANGS.has(canon))
        return;
    const prism = getPrism();
    if (!prism)
        return; // Prism core not loaded (CSP block or load failure).
    if (prism.languages[canon])
        return;
    const existing = loadPromises.get(canon);
    if (existing)
        return existing;
    const p = new Promise((resolve) => {
        const script = document.createElement('script');
        script.src = `vendor/prism/prism-${canon}.min.js`;
        // Preserve load order — e.g. `markup` depends on `clike` being loaded first.
        script.async = false;
        script.onload = () => resolve();
        script.onerror = () => {
            errorLogger.log('PRISM_LANG_LOAD_FAIL', `Failed to load Prism language: ${canon}`);
            // Don't reject — fall back to plain-text code.
            resolve();
        };
        document.head.appendChild(script);
    });
    loadPromises.set(canon, p);
    return p;
}
/** Walk newly-rendered <pre><code class="language-X"> blocks and highlight them. */
export async function highlightCodeBlocks(root) {
    const prism = getPrism();
    if (!prism)
        return;
    const codes = root.querySelectorAll('pre code[class*="language-"]');
    for (const code of Array.from(codes)) {
        if (code.dataset.prismDone === '1')
            continue;
        const cls = code.className.match(/language-(\S+)/);
        if (!cls)
            continue;
        const lang = cls[1].toLowerCase();
        // "code" is our fallback marker from formatMessage when the author
        // omits the language after the opening backticks.
        if (lang === 'code')
            continue;
        await loadPrismLanguage(lang);
        if (prism.languages[canonicalPrismLang(lang)]) {
            try {
                prism.highlightElement(code);
            }
            catch (e) {
                console.debug('Prism highlight failed:', e);
            }
        }
        code.dataset.prismDone = '1';
    }
}
//# sourceMappingURL=prism.js.map