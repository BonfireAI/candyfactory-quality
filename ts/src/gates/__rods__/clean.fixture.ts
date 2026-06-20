/**
 * Clean fixture for the eslint KISS gate (KT3).
 *
 * A trivial function with no complexity violations:
 *   - Cyclomatic complexity = 1  (threshold: 10)
 *   - Statement count       = 1  (threshold: 50)
 *
 * Used in test #4 to confirm the gate returns ok=true for well-formed code.
 */
export function add(a: number, b: number): number {
  return a + b;
}
