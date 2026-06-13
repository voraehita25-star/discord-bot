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

export function formatMessage(content: string): string {
    // Strip the control bytes (\x00-\x04) used as internal block placeholders
    // from the incoming content FIRST, so user-supplied text can't forge a
    // placeholder token (e.g. "\x01CODE_BLOCK_0\x01") and get spliced with a
    // real extracted code/LaTeX block during the restore passes below. These
    // bytes never carry meaning in chat text. Output-integrity hardening (not
    // XSS — DOMPurify still runs); prevents garbled/relocated rendering.
    content = content.replace(/[\x00-\x04]/g, '');

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
            `<button class="code-copy-btn" data-code-copy="${escapedCode}" title="Copy code">📋</button>` +
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

    // Restore LaTeX blocks from placeholders.
    html = html.replace(/\x00(?:BLOCK_LATEX_|INLINE_LATEX_)(\d+)\x00/g, (_match, idx) => {
        return latexBlocks[parseInt(idx)] || '';
    });

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
    html = html.replace(
        /(?:^|\n)(\|.+\|\n\|[\s:|-]+\|\n(?:\|.+\|(?:\n|$))+)/g,
        (_match, table: string) => {
            const rows = table.trim().split('\n');
            if (rows.length < 2) return _match;
            const headerCells = rows[0].replace(/^\s*\|/, '').replace(/\|\s*$/, '').split('|').map(c => c.trim());
            // rows[1] is the separator — parse alignment markers.
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
            const idx = tableBlocks.length;
            tableBlocks.push(tbl);
            return `${tablePlaceholder}${idx}\x02`;
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
    return purify.sanitize(html, {
        ALLOWED_TAGS: [
            'br', 'hr', 'p', 'div', 'span',
            'strong', 'b', 'em', 'i', 'u', 's', 'del',
            'code', 'pre', 'blockquote',
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
            // KaTeX attributes
            'mathvariant', 'encoding', 'xmlns', 'display',
            'aria-hidden', 'focusable', 'role',
            'width', 'height', 'viewBox', 'fill', 'stroke',
            'stroke-width', 'stroke-linecap', 'stroke-linejoin', 'd',
        ],
        ADD_ATTR: ['data-img-idx', 'data-code-copy'],
        ALLOW_DATA_ATTR: false,
        // Only HTTPS — downgrade to http: would let injected markdown phone
        // home over plaintext or hit private hosts.
        ALLOWED_URI_REGEXP: /^https:/i,
    });
}
