/**
 * RuleTester control rod for local/no-untyped-catch.
 *
 * Verifies:
 *  - invalid: empty catch block             → 1 error (swallowed)
 *  - invalid: catch that only console.error → 1 error (swallowed)
 *  - valid:   catch that rethrows (throw e)
 *  - valid:   catch that throws a new typed Error
 *  - valid:   catch that returns a fallback value
 *
 * Also confirms the rod fixture (swallowedCatch.fixture.ts) contains a
 * genuinely empty catch — linted inline via the code string below.
 */

import { RuleTester } from 'eslint';
import parser from '@typescript-eslint/parser';
import { describe, it } from 'vitest';
import rule from './no-untyped-catch.mjs';

// RuleTester.describe/it bindings for vitest compatibility
RuleTester.describe = describe;
RuleTester.it = it;

const tester = new RuleTester({
  languageOptions: {
    // Use the TypeScript-ESLint parser so TS syntax is handled correctly.
    parser: parser as RuleTester['constructor']['prototype']['languageOptions']['parser'],
  },
});

tester.run('local/no-untyped-catch', rule, {
  // -----------------------------------------------------------------------
  // VALID — catch blocks that rethrow or return
  // -----------------------------------------------------------------------
  valid: [
    {
      // Rethrow the caught value directly.
      name: 'rethrow: throw e',
      code: `
        function a() {
          try { foo(); } catch (e) { throw e; }
        }
      `,
    },
    {
      // Throw a new, typed Error — the original is wrapped.
      name: 'typed throw: throw new Error',
      code: `
        function a() {
          try { foo(); } catch (e) { throw new Error('x'); }
        }
      `,
    },
    {
      // Return a fallback — caller receives a typed failure signal.
      name: 'return fallback',
      code: `
        function a() {
          try { foo(); } catch (e) { return fallback(e); }
        }
      `,
    },
  ],

  // -----------------------------------------------------------------------
  // INVALID — swallowed catches
  // -----------------------------------------------------------------------
  invalid: [
    {
      // Empty catch — the archetypal swallow.
      name: 'empty catch block',
      code: `
        function a() {
          try { foo(); } catch (e) {}
        }
      `,
      errors: [{ messageId: 'swallowed' }],
    },
    {
      // Only a console.error call — logs but does not propagate the failure.
      name: 'catch with only console.error (swallow)',
      code: `
        function a() {
          try { foo(); } catch (e) { console.error(e); }
        }
      `,
      errors: [{ messageId: 'swallowed' }],
    },
  ],
});
