import parser from '@typescript-eslint/parser';

/** @type {import('eslint').Linter.Config[]} */
export default [
  /**
   * Global ignores: build output, vendored dependencies, and rod fixtures.
   * Adding **\/__rods__\/** here means `eslint src` from the CLI skips rods.
   * The gate itself constructs ESLint with `ignore: false` so that explicitly-
   * passed rod file paths are still linted (ESLint v9 global ignores otherwise
   * suppress explicitly-targeted files too).
   */
  { ignores: ['node_modules/**', 'dist/**', '**/__rods__/**'] },
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
