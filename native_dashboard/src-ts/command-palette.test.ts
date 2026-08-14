/**
 * Unit tests for the command palette's pure parts — the matcher, the ranker
 * and the highlight builder.
 *
 * These three decide what a keystroke selects, so they are the whole
 * correctness surface of the feature: everything else in the module is DOM
 * plumbing around whatever `filterCommands` returned. The e2e spec drives the
 * plumbing; this file pins the behaviour.
 */
import { describe, it, expect } from 'vitest';

import {
    buildLabel,
    filterCommands,
    scoreCommand,
    type Command,
} from './command-palette.js';

const cmd = (label: string, extra: Partial<Command> = {}): Command => ({
    id: label.toLowerCase().replace(/\s+/g, '-'),
    label,
    group: extra.group ?? 'Test',
    icon: 'bolt',
    run: () => {},
    ...extra,
});

describe('scoreCommand', () => {
    it('matches an empty query against everything, unranked', () => {
        const m = scoreCommand(cmd('Go to Status'), '');
        expect(m).not.toBeNull();
        expect(m?.score).toBe(0);
        expect(m?.positions).toEqual([]);
    });

    it('treats a whitespace-only query as empty', () => {
        expect(scoreCommand(cmd('Go to Status'), '   ')?.score).toBe(0);
    });

    it('matches a subsequence, not just a substring', () => {
        // The reason a palette beats a menu: initials find the command.
        const m = scoreCommand(cmd('Open Data Folder'), 'odf');
        expect(m).not.toBeNull();
        expect(m?.positions).toEqual([0, 5, 10]);
    });

    it('is case-insensitive in both directions', () => {
        expect(scoreCommand(cmd('Restart Bot'), 'RESTART')).not.toBeNull();
        expect(scoreCommand(cmd('RESTART BOT'), 'restart')).not.toBeNull();
    });

    it('returns null when the query is not a subsequence', () => {
        expect(scoreCommand(cmd('Start Bot'), 'xyz')).toBeNull();
        // Right letters, wrong order — a subsequence is ordered.
        expect(scoreCommand(cmd('Start Bot'), 'ts')).toBeNull();
    });

    it('falls back to keywords, with no highlight and a lower score', () => {
        const themed = cmd('Switch to Light Theme', { keywords: 'dark midnight' });
        const m = scoreCommand(themed, 'midnight');
        expect(m).not.toBeNull();
        expect(m?.positions).toEqual([]);
        // Must lose to any label hit — keywords exist to make a command
        // findable, not to let it jump the queue.
        const labelHit = scoreCommand(cmd('Midnight Mode'), 'midnight');
        expect(m!.score).toBeLessThan(labelHit!.score);
    });

    it('ranks a word-start hit above a mid-word one', () => {
        const start = scoreCommand(cmd('Data Folder'), 'da')!;
        const mid = scoreCommand(cmd('Update Archive'), 'da')!;
        expect(start.score).toBeGreaterThan(mid.score);
    });

    it('ranks contiguous hits above scattered ones', () => {
        const contiguous = scoreCommand(cmd('Restart Bot'), 'rest')!;
        const scattered = scoreCommand(cmd('Refresh Entity Statistics'), 'rest')!;
        expect(contiguous.score).toBeGreaterThan(scattered.score);
    });

    it('never scores below the keyword floor on a long late match', () => {
        // The early-hit bonus is clamped at 0, so a match starting past
        // position 10 cannot drag a real label hit under a keyword hit.
        const late = scoreCommand(cmd('Configure the advanced xylophone'), 'x')!;
        expect(late.score).toBeGreaterThan(1);
    });
});

describe('filterCommands', () => {
    const commands = [
        cmd('Go to Status', { group: 'Navigate' }),
        cmd('Go to Logs', { group: 'Navigate' }),
        cmd('Start Bot', { group: 'Bot' }),
        cmd('Open Data Folder', { group: 'Data' }),
    ];

    it('keeps the authored order for an empty query', () => {
        // The resting list is a grouped menu; re-sorting it would scramble the
        // groups it is grouped by.
        expect(filterCommands(commands, '').map((m) => m.command.label)).toEqual([
            'Go to Status', 'Go to Logs', 'Start Bot', 'Open Data Folder',
        ]);
    });

    it('drops non-matches', () => {
        expect(filterCommands(commands, 'zzz')).toEqual([]);
    });

    it('ranks by score once a query is typed', () => {
        // "go" matches only the two Navigate rows. Which of the two leads is
        // decided by coverage and is not worth pinning — both are equally good
        // answers to a two-letter prefix — so this asserts the SET.
        const labels = filterCommands(commands, 'go').map((m) => m.command.label);
        expect(labels).toHaveLength(2);
        expect(new Set(labels)).toEqual(new Set(['Go to Status', 'Go to Logs']));
    });

    it('prefers the command whose name is mostly the query', () => {
        // The defect coverage was added for: both labels match "logs" as a
        // whole word at a word start, so without it the longer one won on the
        // accident of having a shorter first word.
        const both = [cmd('Open Logs Folder'), cmd('Go to Logs')];
        expect(filterCommands(both, 'logs')[0].command.label).toBe('Go to Logs');
        // Authored order must not be what is doing the work here.
        expect(filterCommands(both.slice().reverse(), 'logs')[0].command.label).toBe('Go to Logs');
    });

    it('breaks score ties by authored order, so the ranking is stable', () => {
        const tied = [cmd('Alpha One'), cmd('Alpha Two'), cmd('Alpha Six')];
        expect(filterCommands(tied, 'alpha').map((m) => m.command.label)).toEqual([
            'Alpha One', 'Alpha Two', 'Alpha Six',
        ]);
    });

    it('does not mutate the array it was given', () => {
        const original = commands.map((c) => c.label);
        filterCommands(commands, 'o');
        expect(commands.map((c) => c.label)).toEqual(original);
    });
});

describe('buildLabel', () => {
    const html = (frag: DocumentFragment): string => {
        const host = document.createElement('div');
        host.appendChild(frag);
        return host.innerHTML;
    };

    it('returns plain text when nothing matched', () => {
        expect(html(buildLabel('Start Bot', []))).toBe('Start Bot');
    });

    it('wraps the matched characters', () => {
        expect(html(buildLabel('Logs', [0]))).toBe('<mark class="cmdk-hit">L</mark>ogs');
    });

    it('merges a contiguous run into ONE mark', () => {
        // Four separate <mark>s around "Rest" would put three seams through a
        // single highlighted word.
        expect(html(buildLabel('Restart', [0, 1, 2, 3])))
            .toBe('<mark class="cmdk-hit">Rest</mark>art');
    });

    it('splits non-adjacent hits into separate marks', () => {
        expect(html(buildLabel('Open Data', [0, 5])))
            .toBe('<mark class="cmdk-hit">O</mark>pen <mark class="cmdk-hit">D</mark>ata');
    });

    it('handles a hit on the last character', () => {
        expect(html(buildLabel('Bot', [2]))).toBe('Bo<mark class="cmdk-hit">t</mark>');
    });

    it('builds from text nodes, so a label can never inject markup', () => {
        // The query reaches the DOM here and nowhere else. Escaping is a thing
        // you can forget; createTextNode is not.
        const out = html(buildLabel('<img src=x onerror=alert(1)>', [0]));
        expect(out).not.toContain('<img');
        expect(out).toContain('&lt;');
    });
});
