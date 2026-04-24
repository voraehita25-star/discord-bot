/**
 * Tests for chat/prism.ts — language alias normalization + highlightCodeBlocks.
 *
 * The language-loader half (`loadPrismLanguage`) does a <script> injection;
 * jsdom executes that, which would 404 against vendor/prism/prism-*.min.js
 * because we don't serve files here. So we stub `window.Prism` and watch
 * what `highlightCodeBlocks` does: which elements it tries to highlight,
 * whether it skips already-highlighted blocks, whether it skips our "code"
 * fallback language marker.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { canonicalPrismLang, highlightCodeBlocks } from './prism.js';

interface PrismLike {
    highlightElement: (el: Element) => void;
    languages: Record<string, unknown>;
}

function installPrismStub(languages: string[] = ['javascript', 'python']): {
    prism: PrismLike;
    highlighted: Element[];
} {
    const highlighted: Element[] = [];
    const langMap: Record<string, unknown> = {};
    for (const l of languages) langMap[l] = {};
    const prism: PrismLike = {
        highlightElement: (el: Element) => { highlighted.push(el); },
        languages: langMap,
    };
    (window as unknown as { Prism: PrismLike }).Prism = prism;
    return { prism, highlighted };
}

function removePrism(): void {
    delete (window as unknown as { Prism?: unknown }).Prism;
}

beforeEach(() => {
    document.body.innerHTML = '';
    removePrism();
});

describe('canonicalPrismLang', () => {
    it('maps known aliases to canonical ids', () => {
        expect(canonicalPrismLang('js')).toBe('javascript');
        expect(canonicalPrismLang('ts')).toBe('typescript');
        expect(canonicalPrismLang('py')).toBe('python');
        expect(canonicalPrismLang('rb')).toBe('ruby');
        expect(canonicalPrismLang('rs')).toBe('rust');
        expect(canonicalPrismLang('cs')).toBe('csharp');
        expect(canonicalPrismLang('c++')).toBe('cpp');
        expect(canonicalPrismLang('sh')).toBe('bash');
        expect(canonicalPrismLang('shell')).toBe('bash');
        expect(canonicalPrismLang('md')).toBe('markdown');
        expect(canonicalPrismLang('ps1')).toBe('powershell');
        expect(canonicalPrismLang('yml')).toBe('yaml');
    });

    it('returns the input unchanged for canonical ids', () => {
        expect(canonicalPrismLang('javascript')).toBe('javascript');
        expect(canonicalPrismLang('python')).toBe('python');
        expect(canonicalPrismLang('bash')).toBe('bash');
    });

    it('returns unknown languages unchanged (caller decides what to do)', () => {
        expect(canonicalPrismLang('not-a-real-lang')).toBe('not-a-real-lang');
    });
});

describe('highlightCodeBlocks — Prism not loaded', () => {
    it('is a no-op when window.Prism is missing', async () => {
        document.body.innerHTML = '<pre><code class="language-javascript">x=1</code></pre>';
        await expect(highlightCodeBlocks(document.body)).resolves.toBeUndefined();
        // No mutation.
        expect(document.querySelector('code[class*="language-"]')?.className).toBe('language-javascript');
    });
});

describe('highlightCodeBlocks — with stub', () => {
    it('highlights each code block with a known language', async () => {
        const { highlighted } = installPrismStub(['javascript', 'python']);
        document.body.innerHTML = `
            <pre><code class="language-javascript">a</code></pre>
            <pre><code class="language-python">b</code></pre>
        `;
        await highlightCodeBlocks(document.body);
        expect(highlighted.length).toBe(2);
    });

    it('skips blocks marked with data-prism-done=1 (incremental re-render)', async () => {
        const { highlighted } = installPrismStub(['javascript']);
        document.body.innerHTML = `<pre><code class="language-javascript" data-prism-done="1">x</code></pre>`;
        await highlightCodeBlocks(document.body);
        expect(highlighted.length).toBe(0);
    });

    it('skips blocks with language-code (formatter fallback marker)', async () => {
        const { highlighted } = installPrismStub(['code']);  // even if Prism had a "code" lang
        document.body.innerHTML = `<pre><code class="language-code">plain</code></pre>`;
        await highlightCodeBlocks(document.body);
        expect(highlighted.length).toBe(0);
    });

    it('tags blocks with data-prism-done=1 after highlighting', async () => {
        installPrismStub(['python']);
        document.body.innerHTML = `<pre><code class="language-python">x</code></pre>`;
        await highlightCodeBlocks(document.body);
        const code = document.querySelector('code[class*="language-"]') as HTMLElement;
        expect(code.dataset.prismDone).toBe('1');
    });

    it('resolves language aliases to canonical before checking Prism support', async () => {
        // Prism is configured with 'javascript' but the code block says 'js'.
        const { highlighted } = installPrismStub(['javascript']);
        document.body.innerHTML = `<pre><code class="language-js">x</code></pre>`;
        await highlightCodeBlocks(document.body);
        expect(highlighted.length).toBe(1);
    });

    it('does not crash if Prism.highlightElement throws', async () => {
        installPrismStub(['javascript']);
        // Replace with one that throws.
        (window as unknown as { Prism: PrismLike }).Prism.highlightElement = () => {
            throw new Error('boom');
        };
        document.body.innerHTML = `<pre><code class="language-javascript">x</code></pre>`;
        await expect(highlightCodeBlocks(document.body)).resolves.toBeUndefined();
        // Still marked as done so we don't re-try on every render.
        const code = document.querySelector('code[class*="language-"]') as HTMLElement;
        expect(code.dataset.prismDone).toBe('1');
    });

    it('skips unknown languages silently (no highlight, no throw)', async () => {
        const { highlighted } = installPrismStub(['javascript']);
        document.body.innerHTML = `<pre><code class="language-cobol">x</code></pre>`;
        await highlightCodeBlocks(document.body);
        expect(highlighted.length).toBe(0);
    });

    it('ignores <pre><code> blocks without any language-* class', async () => {
        const { highlighted } = installPrismStub(['javascript']);
        document.body.innerHTML = `<pre><code>no lang at all</code></pre>`;
        await highlightCodeBlocks(document.body);
        expect(highlighted.length).toBe(0);
    });

    it('processes multiple blocks in order', async () => {
        const { highlighted } = installPrismStub(['javascript', 'python']);
        document.body.innerHTML = `
            <pre><code class="language-javascript">a</code></pre>
            <pre><code class="language-python">b</code></pre>
        `;
        await highlightCodeBlocks(document.body);
        expect(highlighted.length).toBe(2);
        expect(highlighted[0].textContent).toBe('a');
        expect(highlighted[1].textContent).toBe('b');
    });
});
