// NOTE: @candyfactory/cf-gate-ts must be installed as a devDependency for
// the import below to resolve at lint time.
import noUntypedCatch from '@candyfactory/cf-gate-ts/src/gates/eslint-rules/no-untyped-catch.mjs';
import parser from '@typescript-eslint/parser';

/** @type {import('eslint').Linter.Config[]} */
export default [
  { ignores: ['node_modules/**', 'dist/**', '**/__rods__/**'] },
  {
    files: ['**/*.ts', '**/*.tsx'],
    languageOptions: { parser },
    plugins: {
      local: {
        rules: {
          'no-untyped-catch': noUntypedCatch,
        },
      },
    },
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
       *   no-empty           — no silent empty catch {}
       *   local/no-untyped-catch — catch must rethrow or narrow the error type
       */
      'no-empty': ['error', { allowEmptyCatch: false }],
      'local/no-untyped-catch': 'error',
    },
  },
];
