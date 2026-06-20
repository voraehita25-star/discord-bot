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
/**
 * Grammars that extend another component and therefore need it loaded FIRST.
 * Most shipped Prism components call ``Prism.languages.extend(<base>, …)`` at
 * script-eval time; if ``<base>`` isn't present that throws a TypeError during
 * the injected script's evaluation (uncatchable here) and the target grammar is
 * never created — so the first code block of these languages silently falls back
 * to plain text for the whole session. Resolved transitively (cpp → c → clike,
 * typescript → javascript → clike).
 */
const PRISM_DEPS = {
    c: ['clike'],
    cpp: ['c'],
    javascript: ['clike'],
    typescript: ['javascript'],
    go: ['clike'],
    csharp: ['clike'],
    java: ['clike'],
    kotlin: ['clike'],
    ruby: ['clike'],
    markdown: ['markup'],
    css: ['markup'],
};
/**
 * Subresource-Integrity (sha384) hashes for each lazily-injected Prism language
 * bundle, keyed by canonical lang id. Computed from the actual bytes in
 * native_dashboard/ui/vendor/prism/prism-<id>.min.js (openssl dgst -sha384).
 * prism-core / prism-tomorrow are loaded eagerly from index.html and not here.
 * If a regenerated bundle isn't in this map the script is skipped (we never
 * inject an unverified <script>); regenerate hashes if you re-vendor Prism.
 */
const PRISM_SRI = {
    bash: 'sha384-9WmlN8ABpoFSSHvBGGjhvB3E/D8UkNB9HpLJjBQFC2VSQsM1odiQDv4NbEo+7l15',
    c: 'sha384-gaD4ncierlmWk42Z3BmTp37/z+Dqt8V4Wf74UjTvFeo+M+SgnEI6Ysd98pWhksQv',
    clike: 'sha384-7LHwxHIDSHTBleLmgDWZbC/IMJsfYfFVOihKhvsrxYW4j47YQcRwZja4ToFE3bA8',
    cpp: 'sha384-NiOrAquf32LSG3Vuig99LKS03EZPUuM8a51NOp+XXsqx08hUVo3wbNWALY7K/2J8',
    csharp: 'sha384-nMKYzg6yfy0qgpaRpVhHvZp0gT5sgvmZYlFC0XAKZSp+zFUB9rE6zsdmIEiou4bV',
    css: 'sha384-0mV13Neu0xhJFylI+HV43C+XiR13bGSeL7D0/7e6hK7sJgvyvK6HVjeQwmvXTstY',
    diff: 'sha384-5MjMyjeLq48jKCQkz3wbIdVG8+jWbG3Dlh9oy9LkluQL7zDQghWEa+UYZiYi5qRJ',
    go: 'sha384-YxCco6ByOY5rJ3jD18514fa8w5so07zigIyV6tZa3CWSE5vYrbDSuFkZ5zOknnZ6',
    ini: 'sha384-IzgZExoq7muPnVEjP/MVubbALJ4d+D++YULBQxvKKWLSoXut91gFAg36n+5WAFf6',
    java: 'sha384-DioAMZB4yk91W6LuFit5wJDh8c5Ov09f/MBvja94y0PodMqTpTZeBeejqpRUru7D',
    javascript: 'sha384-D44bgYYKvaiDh4cOGlj1dbSDpSctn2FSUj118HZGmZEShZcO2v//Q5vvhNy206pp',
    json: 'sha384-RhrmFFMb0ZCHImjFMpR/UE3VEtIVTCtNrtKQqXCzqXZNJala02N3UbVhi+qzw3CY',
    kotlin: 'sha384-zz49ukKZF8e3sr9aiW45Ju61sb9hptYyPOufuu9eutOrjwnOK3D1CGRU+eb12fGy',
    lua: 'sha384-qnsmaXmSxuN1DguKvNsGsQFG1LyCwf1UaKmFgeac2/ssP3m7kDxtKmWTmOIkuOtE',
    markdown: 'sha384-s888ApkYHxfPsp8n81g77Unl/0XYnYltLvWbwqKHcheRE8/dZPlT4IjW3mRGv/Hd',
    markup: 'sha384-HkMr0bZB9kBW4iVtXn6nd35kO/L/dQtkkUBkL9swzTEDMdIe5ExJChVDSnC79aNA',
    powershell: 'sha384-xbI9krqyYp4npK9Cn94XyNoSR+TYZKddrk0NUVZ44zZ+OVpKz/LL0U1PB0MjR7Vx',
    python: 'sha384-WJdEkJKrbsqw0evQ4GB6mlsKe5cGTxBOw4KAEIa52ZLB7DDpliGkwdme/HMa5n1m',
    ruby: 'sha384-xVcnao4LK2LGPWtbEMXzbqrmtM8Ycfrz6nH7gthLCLwCrQGhNFScUV7UGjDotjVu',
    rust: 'sha384-JyDgFjMbyrE/TGiEUSXW3CLjQOySrsoiUNAlXTFdIsr/XUfaB7E+eYlR+tGQ9bCO',
    sql: 'sha384-/MKWdycCDliku23mP5sYXbZNuXrzgmQO/jsVxwPFn99dVOaXRyKsqDjarqpueGAp',
    swift: 'sha384-4RYbFVFN0J24/jfNL9Olk5/pS71bzqjKebX+ZvzzMQ+uDl2T4k/DOuGY6Znxqj8N',
    toml: 'sha384-Uh6n44GRSQeQSMIIfAjlbqojWR7F5KALTHNsspuLDrNCsXpDPRdZbJ5A42AP/cA4',
    typescript: 'sha384-PeOqKNW/piETaCg8rqKFy+Pm6KEk7e36/5YZE5XO/OaFdO+/Aw3O8qZ9qDPKVUgx',
    yaml: 'sha384-AKAiycghK0jDCjD+aavMHzDkLzRR7Yzcwh3+xL/295cvyVMe+cxQfyQC8xxGGcI8',
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
    const p = (async () => {
        // Load prerequisite grammars first so the component's eval-time
        // extend(<base>, …) finds its base (see PRISM_DEPS). Recurses to pull
        // transitive deps (cpp → c → clike, typescript → javascript → clike).
        for (const dep of PRISM_DEPS[canon] || []) {
            if (!prism.languages[dep]) {
                await loadPrismLanguage(dep);
            }
        }
        const integrity = PRISM_SRI[canon];
        if (!integrity) {
            // No pinned SRI hash for this bundle — never inject an unverified
            // <script>. (Should only happen if a lang was added to PRISM_LANGS
            // without regenerating PRISM_SRI.) Fall back to plain-text code.
            errorLogger.log('PRISM_LANG_NO_SRI', `No SRI hash for Prism language: ${canon}`);
            loadPromises.delete(canon);
            return;
        }
        await new Promise((resolve) => {
            const script = document.createElement('script');
            script.src = `vendor/prism/prism-${canon}.min.js`;
            // SRI: verify the lazily-loaded bundle against its pinned sha384 so a
            // tampered vendor file is rejected by the browser before eval.
            script.integrity = integrity;
            script.crossOrigin = 'anonymous';
            // Preserve load order — e.g. `markup` depends on `clike` being loaded first.
            script.async = false;
            script.onload = () => {
                // onload fires even when the component threw during eval (a
                // missing base grammar). Verify the grammar actually registered;
                // if not, evict the cached promise so a later render can retry
                // instead of caching a falsely-resolved promise for the session.
                if (!prism.languages[canon]) {
                    loadPromises.delete(canon);
                }
                resolve();
            };
            script.onerror = () => {
                errorLogger.log('PRISM_LANG_LOAD_FAIL', `Failed to load Prism language: ${canon}`);
                // Evict the cached promise so a transient load failure (CSP hiccup,
                // AV scan, momentary file-lock on Windows) can be retried on a later
                // render instead of permanently falling back to plain text this
                // session.
                loadPromises.delete(canon);
                // Don't reject — fall back to plain-text code for this attempt.
                resolve();
            };
            document.head.appendChild(script);
        });
    })();
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
        const canon = canonicalPrismLang(lang);
        const supported = PRISM_LANGS.has(canon);
        if (supported)
            await loadPrismLanguage(lang);
        if (prism.languages[canon]) {
            try {
                prism.highlightElement(code);
            }
            catch (e) {
                console.debug('Prism highlight failed:', e);
            }
            // Highlighted (or attempted on a loaded grammar) — don't re-walk.
            code.dataset.prismDone = '1';
        }
        else if (!supported) {
            // Unsupported language: nothing to load, mark done so we don't
            // re-walk this block on every render.
            code.dataset.prismDone = '1';
        }
        // Supported but the grammar failed to load (transient): leave prismDone
        // unset so a later render retries — loadPrismLanguage evicted its cache.
    }
}
//# sourceMappingURL=prism.js.map