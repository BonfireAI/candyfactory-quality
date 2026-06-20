import parser from '@typescript-eslint/parser';

/** @type {import('eslint').Linter.Config[]} */
export default [
  /**
   * Global ignores: build output and vendored dependencies only.
   * __rods__ exclusion is NOT here — the gate's resolveFiles() handles it so
   * that tests can still target a rod explicitly via an absolute file path.
   */
  { ignores: ['node_modules/**', 'dist/**'] },
  {
    /**
     * Broad glob — matches ANY TypeScript file that ESLint is asked to lint,
     * including explicitly-targeted rod fixtures.  The old `src/**` prefix
     * caused espree fallback for explicitly-passed absolute paths outside cwd,
     * producing SyntaxError on TS syntax.
     */
    files: ['**/*.ts', '**/*.tsx'],
    languageOptions: { parser },
    rules: {
      /**
       * KISS gate rules (ADR 0030 / BubbleGum Law):
       *   complexity     — cyclomatic complexity ≤ 10 per function
       *   max-statements — statement count       ≤ 50 per function
       */
      complexity: ['error', 10],
      'max-statements': ['error', 50],
    },
  },
];
