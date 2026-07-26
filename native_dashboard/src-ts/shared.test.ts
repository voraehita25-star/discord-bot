/**
 * Unit tests for the small pure helpers in shared.ts.
 */
import { describe, it, expect } from 'vitest';
import { countLabel, normalizeSqliteUtc } from './shared.js';

describe('countLabel', () => {
    // The bug it replaces: every count in the UI was `${n.toLocaleString()}
    // messages`, so a channel holding one message rendered "1 messages".
    it('uses the singular for exactly one', () => {
        expect(countLabel(1, 'message')).toBe('1 message');
        expect(countLabel(1, 'file')).toBe('1 file');
        expect(countLabel(1, 'channel')).toBe('1 channel');
    });

    it('uses the plural for everything else, zero included', () => {
        expect(countLabel(0, 'message')).toBe('0 messages');
        expect(countLabel(2, 'message')).toBe('2 messages');
        expect(countLabel(42, 'file')).toBe('42 files');
    });

    it('keeps the group separators toLocaleString applies', () => {
        expect(countLabel(1234567, 'message')).toBe('1,234,567 messages');
    });

    it('takes an explicit plural for irregular nouns', () => {
        expect(countLabel(1, 'entity', 'entities')).toBe('1 entity');
        expect(countLabel(3, 'entity', 'entities')).toBe('3 entities');
    });

    it('treats -1 as plural (it is not "one")', () => {
        expect(countLabel(-1, 'message')).toBe('-1 messages');
    });
});

describe('normalizeSqliteUtc', () => {
    it('appends Z and swaps the separator on a naive timestamp', () => {
        expect(normalizeSqliteUtc('2026-01-22 10:00:00')).toBe('2026-01-22T10:00:00Z');
    });

    it('leaves an already-zoned timestamp alone apart from the separator', () => {
        expect(normalizeSqliteUtc('2026-01-22 10:00:00Z')).toBe('2026-01-22T10:00:00Z');
        expect(normalizeSqliteUtc('2026-01-22T10:00:00+07:00')).toBe('2026-01-22T10:00:00+07:00');
    });
});
