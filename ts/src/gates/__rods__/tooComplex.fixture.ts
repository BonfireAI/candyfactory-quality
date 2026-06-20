/**
 * Control rod for the eslint KISS gate (KT3).
 *
 * Intentionally violates ADR 0030 / BubbleGum Law:
 *   - Cyclomatic complexity = 13  (threshold: 10)
 *
 * Branch count: 12 decision points (if + 11 else-if), giving CC = 1 + 12 = 13.
 * max-statements = 14 (well under the 50 threshold — only complexity fires).
 *
 * DO NOT fix this function.  It exists to prove that the eslint gate catches
 * complexity violations.  See eslintGate.test.ts test #1.
 */
export function tooComplex(x: number): string {
  if (x === 1) {
    return 'one';
  } else if (x === 2) {
    return 'two';
  } else if (x === 3) {
    return 'three';
  } else if (x === 4) {
    return 'four';
  } else if (x === 5) {
    return 'five';
  } else if (x === 6) {
    return 'six';
  } else if (x === 7) {
    return 'seven';
  } else if (x === 8) {
    return 'eight';
  } else if (x === 9) {
    return 'nine';
  } else if (x === 10) {
    return 'ten';
  } else if (x === 11) {
    return 'eleven';
  } else if (x === 12) {
    return 'twelve';
  } else {
    return 'other';
  }
}
