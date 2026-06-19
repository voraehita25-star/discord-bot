import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'jsdom',
    globals: true,
    include: ['src-ts/**/*.test.ts'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'html'],
      include: ['src-ts/**/*.ts'],
      exclude: ['src-ts/**/*.test.ts'],
      // Coverage floors set just below the suite's current measured numbers, so
      // `npm run test:coverage` PASSES today but FAILS (exit 1) if coverage
      // regresses meaningfully. Raise these as the suite grows — they are a
      // regression guard, not an aspiration.
      thresholds: {
        lines: 37,
        functions: 35,
        statements: 37,
        branches: 33
      }
    }
  }
});
