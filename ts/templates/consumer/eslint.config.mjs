import parser from '@typescript-eslint/parser';

/** @type {import('eslint').Linter.Config[]} */
export default [
  { ignores: ['node_modules/**', 'dist/**', '**/__rods__/**'] },
  {
    files: ['**/*.ts', '**/*.tsx'],
    languageOptions: { parser },
    rules: {
      /**
       * KISS gate rules (BubbleGum Law):
       *   complexity     — cyclomatic complexity ≤ 10 per function
       *   max-statements — statement count       ≤ 50 per function
       */
      complexity: ['error', 10],
      'max-statements': ['error', 50],
      /**
       * Elegance Law — fail-fast:
       *   no-empty — no silent empty catch {}
       */
      'no-empty': ['error', { allowEmptyCatch: false }],
    },
  },
];
