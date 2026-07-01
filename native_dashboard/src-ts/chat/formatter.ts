/**
 * Message formatter — turns raw Markdown + LaTeX + fenced code into sanitized
 * HTML for chat rendering.
 *
 * Order of operations (the order matters — many passes produce placeholders
 * that later passes must NOT re-escape):
 *
 *   0. Extract ```lang\n...``` fenced blocks into \x01 placeholders FIRST and
 *      render them as code-block cards (code escaped here). Doing this before
 *      the LaTeX passes stops `$` math syntax inside code from being eaten.
 *   1. Extract $$...$$ and $...$ into NUL-delimited placeholders, run KaTeX
 *      on each. We do this BEFORE escapeHtml so the math syntax survives.
 *   2. escapeHtml() on the remaining text — this is what guarantees safety.
 *   3. Re-insert KaTeX output (trusted) at the placeholders.
 *   5. Apply inline markdown: `code`, **bold**, *em*, # headings, ---, > quote.
 *   6. Extract | pipe | tables into \x02 placeholders.
 *   7. Extract - / 1. lists into \x03 placeholders.
 *   8. Collapse newlines to <br> on the remaining plain text.
 *   9. Restore list/table/code placeholders.
 *  10. DOMPurify whitelist-sanitize the whole thing.
 *
 * Returns '' if DOMPurify is missing — render nothing rather than risk XSS.
 */

import { escapeHtml, errorLogger } from '../shared.js';

interface KatexGlobal {
    renderToString: (tex: string, options: object) => string;
}

interface DOMPurifyGlobal {
    sanitize: (html: string, config: object) => string;
    addHook?: (
        entryPoint: string,
        hookFunction: (node: Element) => void,
    ) => void;
}

function getKatex(): KatexGlobal | undefined {
    return (window as unknown as { katex?: KatexGlobal }).katex;
}

function getPurify(): DOMPurifyGlobal | undefined {
    return (window as unknown as { DOMPurify?: DOMPurifyGlobal }).DOMPurify;
}

/** Strip `<think>...</think>` blocks used by extended-thinking model output. */
export function stripThinkTags(content: string): string {
    return content.replace(/<think>[\s\S]*?<\/think>/g, '').trim();
}

// Markdown-link + bare-autolink pass. Operates on ALREADY-escaped HTML (so the
// captured URL/text are entity-safe) and emits raw <a> tags whose href is the
// (escaped) URL. The emitted markup is still run through DOMPurify, which is the
// authoritative gate: ALLOWED_URI_REGEXP=/^https:/i drops any non-https href,
// and the afterSanitizeAttributes hook forces target/rel. Only https:// URLs
// are recognised here — markdown like `[x](javascript:alert(1))` simply doesn't
// match and stays as literal text.
//
// The `href` is restricted to https://. We deliberately do NOT linkify http://
// (DOMPurify would strip the href anyway, leaving a dead <a>) — mirroring the
// image host-allowlist / https-only posture used elsewhere in this file.
const HTTPS_URL = 'https:\\/\\/[^\\s<>"\']+';
// [text](https://url) — text may not contain ] or a newline; URL is https-only.
const MD_LINK_RE = new RegExp('\\[([^\\]\\n]+)\\]\\((' + HTTPS_URL + ')\\)', 'g');
// Bare https:// autolink. Run on text OUTSIDE existing anchors only (see the
// split in applyLinks), so it never re-wraps a URL we already turned into a
// link. A URL must start at the string start or after whitespace/`(` so a URL
// glued to `="` (an attribute value) is left alone. Trailing sentence
// punctuation is excluded from the match by splitTrailingPunctuation.
const BARE_URL_RE = new RegExp('(^|[\\s(])(' + HTTPS_URL + ')', 'g');
// Carves the string into protected vs. linkable segments so applyLinks only
// autolinks plain text. Protected = anchors we just emitted (so we don't
// double-wrap) AND any <code>…</code> span (the inline-code fallback at line
// ~297 restores single-line `code` content here, BEFORE the autolink pass; the
// primary \x04ICODE_ path is still a placeholder, but this also covers that
// fallback so a URL inside inline code is never linkified).
// The anchor body is matched lazily ([\s\S]*? up to the first </a>), not with
// [^<]*, because the earlier bold/em/`code` passes may have emitted inline tags
// (<strong>/<em>/<code>) INSIDE a markdown link's visible label — [^<]* would
// stop at that first nested '<', never reach </a>, and leave the anchor
// unprotected, so a bare URL in the label would get double-wrapped. Anchors are
// never nested at split time, so the lazy match still stops at the FIRST </a>
// and can't swallow a following separate anchor. (<code> body stays [^<]*.)
const PROTECTED_SPLIT_RE = /(<a href="[^"]*">[\s\S]*?<\/a>|<code>[^<]*<\/code>)/g;

/** Strip a trailing run of sentence punctuation from an autolinked URL so
 *  "see https://x.com." doesn't linkify the dot. Returns [url, trailing]. */
function splitTrailingPunctuation(url: string): [string, string] {
    const m = url.match(/[).,!?;:]+$/);
    if (!m) return [url, ''];
    // A trailing ')' that closes a '(' earlier in the URL is PART of the URL
    // (e.g. https://en.wikipedia.org/wiki/Foo_(bar) ) — keep balanced ')',
    // and strip only unmatched parens + the non-paren sentence punctuation, so
    // a legitimate closing paren isn't lopped off into a broken 404 link.
    //
    // Walk the ENTIRE trailing punctuation run (not just a leading ')' sub-run)
    // with RUNNING paren counters instead of re-`match()`-ing the growing prefix
    // each iteration. The old per-step .match(/\(/g)/.match(/\)/g) was O(n)
    // inside an O(n) loop -> O(n^2), so a bare URL ending in a long balanced-
    // paren run (BARE_URL_RE captures '(' and ')' as URL chars) froze the render
    // thread for seconds. Counting once up to the run start, then advancing a
    // keep-cursor as we scan, is a single O(n) pass. Scanning the whole run (not
    // stopping at the first non-')') keeps a ')' that balances an earlier '('
    // PLUS any '.'/',' it encloses (e.g. .../page(v1.) ), while a bare
    // "see https://x.com." still strips the trailing dot.
    const runStart = url.length - m[0].length;
    // Count parens in the prefix BEFORE the trailing punctuation run, once.
    let opens = 0;
    let closes = 0;
    for (let i = 0; i < runStart; i++) {
        if (url[i] === '(') opens++;
        else if (url[i] === ')') closes++;
    }
    let keep = runStart;
    for (let i = runStart; i < url.length; i++) {
        if (url[i] === ')') {
            closes++;
            if (opens < closes) break; // unmatched ')' — strip from here on
            keep = i + 1; // balanced ')' — keep it (and any '.'/',' it encloses)
        }
    }
    return [url.slice(0, keep), url.slice(keep)];
}

function applyLinks(html: string): string {
    // First: explicit [text](url) markdown links.
    const withMdLinks = html.replace(MD_LINK_RE, (_match, text: string, url: string) => {
        const [cleanUrl, trail] = splitTrailingPunctuation(url);
        // href is already escapeHtml'd (so `"`/`<`/`>` are entities); text is too.
        return `<a href="${cleanUrl}">${text}</a>${trail}`;
    });
    // Second: bare https:// URLs in the segments BETWEEN the protected spans
    // (anchors we emitted above + inline <code>). Splitting on the capturing
    // group keeps those spans in the array; we autolink only the odd (= text)
    // segments so an already-linked URL — both its href and its visible text —
    // and any URL inside inline code are never (re-)wrapped.
    const segments = withMdLinks.split(PROTECTED_SPLIT_RE);
    for (let i = 0; i < segments.length; i++) {
        // Even indices are plain text; odd indices are the protected spans.
        if (i % 2 === 1) continue;
        segments[i] = segments[i].replace(BARE_URL_RE, (_m, pre: string, url: string) => {
            const [cleanUrl, trail] = splitTrailingPunctuation(url);
            return `${pre}<a href="${cleanUrl}">${cleanUrl}</a>${trail}`;
        });
    }
    return segments.join('');
}

// Register the target/rel-forcing hook exactly once. formatMessage runs the
// sanitizer on every call (and may be called hundreds of times per render), so
// re-adding the hook each time would stack identical callbacks. The flag is
// keyed to the DOMPurify instance the formatter is currently using.
let linkHookInstalled: DOMPurifyGlobal | null = null;
function ensureLinkHook(purify: DOMPurifyGlobal): void {
    if (linkHookInstalled === purify) return;
    if (typeof purify.addHook !== 'function') {
        // Older/stub DOMPurify without addHook: links still get sanitized
        // (https-only) but won't carry forced target/rel. Don't retry every call.
        linkHookInstalled = purify;
        return;
    }
    purify.addHook('afterSanitizeAttributes', (node: Element) => {
        if (node.tagName === 'A' && node.hasAttribute('href')) {
            // Open external links in a new context and sever the back-reference
            // so window.opener can't be abused (reverse tabnabbing).
            node.setAttribute('target', '_blank');
            node.setAttribute('rel', 'noopener noreferrer');
        }
    });
    linkHookInstalled = purify;
}

// Bounded content-keyed LRU memo for formatMessage. The function is a pure
// function of `content` (its only argument) and its output is already
// DOMPurify-sanitized, so caching by the exact input string is safe. The chat
// re-renders the whole window (up to ~100 messages) on every pin/like/edit,
// and each formatMessage call runs ~20 regex passes + per-block KaTeX +
// DOMPurify.sanitize — so memoizing avoids redoing that work for unchanged
// messages. Map preserves insertion order, so the oldest key is the first one
// iterated; we evict it on overflow (max ~300 entries).
const FORMAT_CACHE_MAX = 300;
const formatCache = new Map<string, string>();

export function formatMessage(content: string): string {
    const cached = formatCache.get(content);
    if (cached !== undefined) {
        // Refresh recency: re-insert so this key moves to the newest position.
        formatCache.delete(content);
        formatCache.set(content, cached);
        return cached;
    }
    const result = formatMessageUncached(content);
    // Only memoize the fully-sanitized (happy) output. If DOMPurify was
    // momentarily unavailable, formatMessageUncached returns degraded output
    // (escaped plain text or '') — caching that would keep serving the degraded
    // render for this exact content even after DOMPurify recovers, because the
    // cache key is the raw string and doesn't incorporate global availability.
    // Skipping the write on the fail-closed path lets the next call re-render.
    if (getPurify()) {
        formatCache.set(content, result);
        if (formatCache.size > FORMAT_CACHE_MAX) {
            // Evict the oldest entry (first key in insertion order).
            const oldest = formatCache.keys().next().value;
            if (oldest !== undefined) {
                formatCache.delete(oldest);
            }
        }
    }
    return result;
}

function formatMessageUncached(content: string): string {
    // Strip the control bytes (\x00-\x04) used as internal block placeholders
    // from the incoming content FIRST, so user-supplied text can't forge a
    // placeholder token (e.g. "\x01CODE_BLOCK_0\x01") and get spliced with a
    // real extracted code/LaTeX block during the restore passes below. These
    // bytes never carry meaning in chat text. Output-integrity hardening (not
    // XSS — DOMPurify still runs); prevents garbled/relocated rendering.
    content = content.replace(/[\x00-\x04]/g, '');

    // Normalize CRLF/CR to LF once, up front. Every block-level pass below
    // (tables line ~382, unordered/ordered lists ~422/430) matches LF only and
    // `.` excludes \r, so a `\r\n`-terminated line would fail to match — tables
    // emit raw `|` pipes and the first list item is dropped. Mirrors how
    // CommonMark treats \r\n and \r as line breaks; fixes all three at once.
    content = content.replace(/\r\n?/g, '\n');

    // Fail-closed if DOMPurify isn't available — return escaped plain text
    // rather than risk emitting any of the markdown HTML pipeline output
    // unsanitised. The same check runs again at the bottom as defence-in-
    // depth in case the global is yanked mid-pass.
    if (!getPurify()) {
        return escapeHtml(content);
    }

    // Extract LaTeX blocks BEFORE HTML escaping so KaTeX gets raw math notation.
    const latexBlocks: string[] = [];
    const blockPlaceholder = '\x00BLOCK_LATEX_';
    const inlinePlaceholder = '\x00INLINE_LATEX_';
    const katex = getKatex();

    // Streaming guard: if the buffer ends with an unclosed code fence (odd count
    // of ``` markers), the code-block regex won't match and the user sees three
    // literal backticks until the closing fence arrives. Adding a virtual close
    // lets us render the partial block as code mid-stream. The closing fence is
    // local to this format pass — the next pass with more content will re-parse
    // from the (possibly now-closed) original.
    const fenceCount = (content.match(/```/g) || []).length;
    if (fenceCount % 2 === 1) {
        content = content + '\n```';
    }

    // Extract fenced code blocks FIRST — BEFORE the LaTeX passes — so `$` math
    // syntax inside code (shell `echo $HOME`, jQuery `$(...)`, PHP `$var`,
    // even `$$...$$`-looking pairs) is treated as literal code instead of being
    // consumed by the LaTeX extraction below and rendered as a math span. The
    // captured `code` is RAW here (the old pipeline extracted code AFTER
    // escapeHtml and reused that escaping); we escape it explicitly when
    // building the card, so the emitted HTML is byte-identical to before — only
    // the extraction order changed. The lang label stays restricted to
    // [a-zA-Z0-9_-] so it can't break out of the class= / <span> attribute.
    const codeBlocks: string[] = [];
    const codePlaceholder = '\x01CODE_BLOCK_';
    content = content.replace(/```(\w*)\n([\s\S]*?)```/g, (_match, lang, code) => {
        const idx = codeBlocks.length;
        const safeLang = String(lang || '').replace(/[^a-zA-Z0-9_-]/g, '');
        const langLabel = safeLang || 'code';
        // Escape now (code is raw at this stage). escapeHtml handles <, >, &,
        // ", ' and backtick — the same escaping the old post-escape path
        // produced — so HTML entities still decode correctly inside <pre>/<code>
        // and the data-code-copy attribute.
        const escapedCode = escapeHtml(code);
        codeBlocks.push(
            `<div class="code-block-wrapper">` +
            `<div class="code-block-header">` +
            `<span class="code-lang">${langLabel}</span>` +
            `<button class="code-copy-btn" data-code-copy="${escapedCode}" title="Copy code" aria-label="Copy code"></button>` +
            `</div>` +
            `<pre><code class="language-${langLabel}">${escapedCode}</code></pre>` +
            `</div>`
        );
        return `${codePlaceholder}${idx}\x01`;
    });

    // Extract INLINE `code` spans before the LaTeX passes — otherwise the
    // inline-math regex below eats '$' inside code (`$HOME`, `$PATH`) and
    // currency in prose ("$5 ... $10"). Restored near the end alongside the
    // bold/em passes (the existing `code` restore at the inline-code step).
    const inlineCodeBlocks: string[] = [];
    const inlineCodePlaceholder = '\x04ICODE_';
    content = content.replace(/`([^`\n]+)`/g, (_match, code) => {
        const idx = inlineCodeBlocks.length;
        inlineCodeBlocks.push(`<code>${escapeHtml(code)}</code>`);
        return `${inlineCodePlaceholder}${idx}\x04`;
    });

    // Extract block LaTeX ($$...$$). The pattern allows `\$` (escaped dollar)
    // inside the formula so equations like `$$\frac{1}{\$x}$$` survive
    // extraction instead of slipping past as plain text. The alternation is
    // written `[^$\\] | \\.` (not `[^$] | \\\$`) so a backslash always starts
    // the escape branch — removing the ambiguity that let the old pattern
    // backtrack super-linearly (ReDoS) on adversarial `$$\$\$\$…` input.
    let processed = content.replace(/\$\$((?:[^$\\]|\\.)+)\$\$/g, (_match, tex) => {
        const idx = latexBlocks.length;
        try {
            if (katex) {
                // output:'mathml' — emit pure MathML (no inline-style HTML
                // spans), so the chat body needs no `style-src 'unsafe-inline'`
                // CSP grant. DOMPurify's ALLOWED_TAGS below already whitelists
                // exactly these MathML elements; the HTML renderer's styled
                // spans would have their style= stripped by DOMPurify anyway.
                latexBlocks.push(`<div class="math-block">${katex.renderToString(tex.trim(), { displayMode: true, throwOnError: false, output: 'mathml' })}</div>`);
            } else {
                latexBlocks.push(`<div class="math-block">$$${escapeHtml(tex)}$$</div>`);
            }
        } catch {
            latexBlocks.push(`<div class="math-block">$$${escapeHtml(tex)}$$</div>`);
        }
        return `${blockPlaceholder}${idx}\x00`;
    });

    // Extract inline LaTeX ($...$). Single-line only ([^$\n]) so unmatched
    // currency dollars in prose can't span paragraphs into a math span.
    processed = processed.replace(/(?<!\$)\$(?!\$)([^$\n]+)\$(?!\$)/g, (_match, tex) => {
        const idx = latexBlocks.length;
        try {
            if (katex) {
                latexBlocks.push(`<span class="math-inline">${katex.renderToString(tex.trim(), { displayMode: false, throwOnError: false, output: 'mathml' })}</span>`);
            } else {
                latexBlocks.push(`<span class="math-inline">$${escapeHtml(tex)}$</span>`);
            }
        } catch {
            latexBlocks.push(`<span class="math-inline">$${escapeHtml(tex)}$</span>`);
        }
        return `${inlinePlaceholder}${idx}\x00`;
    });

    // Now HTML-escape the rest (placeholders will be escaped but we restore them below).
    let html = escapeHtml(processed);

    // Restore backticks. escapeHtml() in shared.ts also escapes `\`` → `&#96;`
    // defensively for attribute contexts, but our markdown pipeline matches on
    // literal backticks and would otherwise miss every `\`code\`` and fenced
    // ``` block. Content captured by those regexes is already escaped for <, >,
    // ", ' so this doesn't reintroduce an XSS vector. (Bug surfaced by
    // chat/formatter.test.ts — code blocks never rendered before this line.)
    html = html.replace(/&#96;/g, '`');

    // (Fenced code blocks were already extracted into \x01 placeholders at the
    // very top, before the LaTeX/escape passes, so $ inside code is preserved.
    // The placeholders survive escapeHtml and the markdown passes and are
    // restored near the end alongside tables/lists.)
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
    html = html.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
    // Single-line only, and never match a bullet ("* item"): the old
    // [^*]+ spanned newlines, so the * at the start of one list line paired
    // with the * starting the NEXT line and italicized the whole list before
    // the list extraction below ever saw it (Gemini emits * bullets).
    html = html.replace(/\*(?!\s)([^*\n]+?)(?<!\s)\*/g, '<em>$1</em>');

    // Markdown links [text](url) + bare https:// autolinks. Run here, while the
    // fenced/inline code (\x01/\x04) and LaTeX (\x00) blocks are still opaque
    // placeholders, so URLs INSIDE code are never turned into anchors. Only
    // https URLs are linkified — the scheme is also re-validated by DOMPurify's
    // ALLOWED_URI_REGEXP below, and target/rel are forced by the
    // afterSanitizeAttributes hook, so a `javascript:`/`http:` URL never
    // becomes a live <a href>. The href value here is post-escapeHtml, so any
    // `"`/`<`/`>` in the URL is already an entity and can't break the attribute.
    html = applyLinks(html);

    // Headings (# to ######) — must be at start of line.
    html = html.replace(/^#{6}\s+(.+)$/gm, '<h6 class="md-heading">$1</h6>');
    html = html.replace(/^#{5}\s+(.+)$/gm, '<h5 class="md-heading">$1</h5>');
    html = html.replace(/^#{4}\s+(.+)$/gm, '<h4 class="md-heading">$1</h4>');
    html = html.replace(/^#{3}\s+(.+)$/gm, '<h3 class="md-heading">$1</h3>');
    html = html.replace(/^#{2}\s+(.+)$/gm, '<h2 class="md-heading">$1</h2>');
    html = html.replace(/^#{1}\s+(.+)$/gm, '<h1 class="md-heading">$1</h1>');
    // Horizontal rule (--- or ___ or *** on its own line).
    html = html.replace(/^(?:---+|___+|\*\*\*+)\s*$/gm, '<hr class="md-hr">');
    // Blockquotes (> at start of line — already &gt; after escapeHtml).
    html = html.replace(/^&gt; (.+)$/gm, '<blockquote>$1</blockquote>');
    // Merge consecutive blockquotes.
    html = html.replace(/<\/blockquote>\n?<blockquote>/g, '<br>');

    // Markdown tables — extract into placeholders before \n → <br>.
    const tableBlocks: string[] = [];
    const tablePlaceholder = '\x02TABLE_BLOCK_';
    // A separator row is `|---|`, `|:-:|`, etc. — only pipes, dashes, colons,
    // spaces. Used both to validate a table head and to detect where a second
    // table begins (a data-looking row immediately followed by a separator row
    // is really the header of a NEW table, not a body row of the current one).
    const isSeparatorRow = (row: string): boolean => /^\s*\|[\s:|-]+\|\s*$/.test(row);
    const renderTableRows = (rows: string[]): string => {
        // rows[1] is the separator — parse alignment markers.
        const headerCells = rows[0].replace(/^\s*\|/, '').replace(/\|\s*$/, '').split('|').map(c => c.trim());
        const alignCells = rows[1].replace(/^\s*\|/, '').replace(/\|\s*$/, '').split('|').map(c => c.trim());
        const aligns = alignCells.map(c => {
            const t = c.trim();
            if (t.startsWith(':') && t.endsWith(':')) return 'center';
            if (t.endsWith(':')) return 'right';
            return 'left';
        });
        let tbl = '<div class="md-table-wrap"><table class="md-table"><thead><tr>';
        headerCells.forEach((cell, i) => {
            const align = aligns[i] || 'left';
            tbl += `<th class="md-ta-${align}">${cell.trim()}</th>`;
        });
        tbl += '</tr></thead><tbody>';
        for (let r = 2; r < rows.length; r++) {
            const cells = rows[r].replace(/^\s*\|/, '').replace(/\|\s*$/, '').split('|').map(c => c.trim());
            tbl += '<tr>';
            cells.forEach((cell, i) => {
                const align = aligns[i] || 'left';
                tbl += `<td class="md-ta-${align}">${cell.trim()}</td>`;
            });
            tbl += '</tr>';
        }
        tbl += '</tbody></table></div>';
        return tbl;
    };
    html = html.replace(
        /(?:^|\n)(\|.+\|\n\|[\s:|-]+\|\n(?:\|.+\|(?:\n|$))+)/g,
        (_match, table: string) => {
            const rows = table.trim().split('\n');
            if (rows.length < 2) return _match;
            // The body-row quantifier above greedily swallows a directly-adjacent
            // second table (only a single newline between them). Split the matched
            // block back into individual tables wherever a row is followed by a
            // separator row — that pair marks the head of a new table.
            const placeholders: string[] = [];
            let i = 0;
            while (i < rows.length) {
                if (i + 1 < rows.length && isSeparatorRow(rows[i + 1]) && !isSeparatorRow(rows[i])) {
                    const seg = [rows[i], rows[i + 1]];
                    let j = i + 2;
                    while (j < rows.length) {
                        // A new header+separator pair, or a stray separator row, ends this body.
                        if (isSeparatorRow(rows[j])) break;
                        if (j + 1 < rows.length && isSeparatorRow(rows[j + 1])) break;
                        seg.push(rows[j]);
                        j++;
                    }
                    const idx = tableBlocks.length;
                    tableBlocks.push(renderTableRows(seg));
                    placeholders.push(`${tablePlaceholder}${idx}\x02`);
                    i = j;
                } else {
                    // Not a valid table head — preserve the line as-is.
                    placeholders.push(rows[i]);
                    i++;
                }
            }
            // Emit surrounding newlines (like the list branches) so the later
            // \n → <br> pass keeps a boundary between the table and adjacent text.
            return `\n${placeholders.join('\n')}\n`;
        },
    );

    // Unordered lists: consecutive lines starting with - or *.
    const listBlocks: string[] = [];
    const listPlaceholder = '\x03LIST_BLOCK_';
    html = html.replace(/((?:^|\n)(?:[-*]\s+.+(?:\n|$))+)/g, (match) => {
        const items = match.trim().split('\n').map(line => line.replace(/^[-*]\s+/, '').trim());
        const i = listBlocks.length;
        listBlocks.push('<ul>' + items.map(item => `<li>${item}</li>`).join('') + '</ul>');
        return `\n${listPlaceholder}${i}\x03\n`;
    });

    // Ordered lists: consecutive lines starting with 1. 2. etc.
    html = html.replace(/((?:^|\n)(?:\d+\.\s+.+(?:\n|$))+)/g, (match) => {
        const items = match.trim().split('\n').map(line => line.replace(/^\d+\.\s+/, '').trim());
        const i = listBlocks.length;
        listBlocks.push('<ol>' + items.map(item => `<li>${item}</li>`).join('') + '</ol>');
        return `\n${listPlaceholder}${i}\x03\n`;
    });

    // Paragraph breaks: double+ newlines become a spaced paragraph break.
    html = html.replace(/\n{2,}/g, '<br><div class="paragraph-break"></div>');
    html = html.replace(/\n/g, '<br>');

    // Restore list/table/code placeholders.
    html = html.replace(/\x03LIST_BLOCK_(\d+)\x03/g, (_match, idx) => listBlocks[parseInt(idx)] || '');
    html = html.replace(/\x02TABLE_BLOCK_(\d+)\x02/g, (_match, idx) => tableBlocks[parseInt(idx)] || '');
    html = html.replace(/\x01CODE_BLOCK_(\d+)\x01/g, (_match, idx) => codeBlocks[parseInt(idx)] || '');
    // Restore LaTeX blocks/spans LAST (after bold/em/heading/list/table passes)
    // so TeX containing `*` (e.g. $a*b*c$) is not corrupted into <em>/<strong>.
    html = html.replace(/\x00(?:BLOCK_LATEX_|INLINE_LATEX_)(\d+)\x00/g, (_match, idx) => latexBlocks[parseInt(idx)] || '');
    html = html.replace(
        /\x04ICODE_(\d+)\x04/g,
        (_match, idx) => inlineCodeBlocks[parseInt(idx)] || '',
    );

    // Sanitize final HTML output with DOMPurify (whitelist approach). DOMPurify
    // is bundled locally in vendor/; if it fails to load we return '' rather
    // than risk rendering un-sanitized HTML.
    const purify = getPurify();
    if (!purify) {
        errorLogger.log('DOMPURIFY_MISSING', 'DOMPurify failed to load — rendering aborted to prevent XSS');
        return '';
    }
    // Install the target/rel-forcing hook before sanitizing the (possibly)
    // linkified HTML. Idempotent — only registers once per DOMPurify instance.
    ensureLinkHook(purify);
    return purify.sanitize(html, {
        ALLOWED_TAGS: [
            'br', 'hr', 'p', 'div', 'span',
            'strong', 'b', 'em', 'i', 'u', 's', 'del',
            'code', 'pre', 'blockquote',
            // <a> for markdown links + bare autolinks. href is gated https-only
            // by ALLOWED_URI_REGEXP below; target/rel are forced by the
            // afterSanitizeAttributes hook (ensureLinkHook).
            'a',
            'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
            'ul', 'ol', 'li',
            'table', 'thead', 'tbody', 'tr', 'th', 'td',
            // <button> kept for the in-formatter copy button. We never allow
            // on* handlers (DOMPurify strips them), so this is just an inert
            // button that JS wires up via addEventListener.
            'button',
            // <img> dropped — formatter does not generate <img>, and an
            // attacker injecting <img src=remote-tracking-pixel> via raw
            // HTML in markdown was previously rendered. Inline message
            // images are inserted by message-template before this runs.
            // KaTeX MathML output (output:'mathml'). Full presentation-MathML
            // tag set KaTeX can emit, so complex formulae (tables, roots,
            // sub/superscripts, spacing) survive sanitisation intact.
            'math', 'semantics', 'annotation', 'mrow', 'mi', 'mo', 'mn',
            'ms', 'mtext', 'mspace', 'msup', 'msub', 'msubsup', 'mfrac',
            'mroot', 'msqrt', 'mover', 'munder', 'munderover', 'mtable',
            'mtr', 'mtd', 'mstyle', 'mpadded', 'mphantom', 'menclose',
            'merror',
        ],
        ALLOWED_ATTR: [
            // Table alignment now uses CSS classes (md-ta-*), and KaTeX output is
            // re-inserted post-sanitisation (trusted, never seen by DOMPurify), so
            // 'style' is no longer needed here. Dropping it removes an inline-CSS
            // injection surface from raw AI markdown (e.g. style="background:url(...)").
            'class', 'alt',
            'title', 'colspan', 'rowspan',
            // <a> link attributes. href is constrained to https by
            // ALLOWED_URI_REGEXP; target/rel are (re)written by the hook so even
            // an AI-supplied target/rel is normalised to _blank/noopener.
            'href', 'target', 'rel',
            // KaTeX attributes
            'mathvariant', 'encoding', 'xmlns', 'display',
            'aria-hidden', 'focusable', 'role',
            'width', 'height', 'viewBox', 'fill', 'stroke',
            'stroke-width', 'stroke-linecap', 'stroke-linejoin', 'd',
        ],
        ADD_ATTR: ['data-img-idx', 'data-code-copy'],
        // Must stay true: it is the ONLY setting that lets our own data-*
        // attributes survive DOMPurify. ADD_ATTR / ALLOWED_ATTR alone do NOT
        // whitelist data-* (proven), so without this the per-block copy button
        // loses data-code-copy and the copy-code handler reads ''. The other
        // guards still apply — on* handlers are stripped, hrefs are pinned to
        // ALLOWED_URI_REGEXP (/^https:/i), and only ALLOWED_TAGS/ALLOWED_ATTR
        // survive — and data-* are inert (can't run script), so this widens the
        // surface negligibly while keeping the code-copy / image-index hooks.
        ALLOW_DATA_ATTR: true,
        // Only HTTPS — downgrade to http: would let injected markdown phone
        // home over plaintext or hit private hosts.
        ALLOWED_URI_REGEXP: /^https:/i,
    });
}
