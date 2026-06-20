/**
 * Control rod — swallowedCatch.fixture.ts
 *
 * This file intentionally contains an empty catch block (a swallowed error).
 * It MUST be flagged by the `local/no-untyped-catch` ESLint rule.
 *
 * The rod is excluded from directory-walk linting (the global ignore
 * `**\/__rods__\/**` in eslint.config.mjs) but can be targeted explicitly
 * by the gate test to verify the rule fires.
 */

export function doSomethingDangerous(): void {
  try {
    JSON.parse('}{');
  } catch (e) {
    // empty — swallows the error silently (Elegance Law violation)
  }
}
