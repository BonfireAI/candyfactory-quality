import { readFileSync } from 'node:fs';

/**
 * A frozen snapshot of file line counts.
 *
 * Keys are project-relative file paths; values are the committed line counts.
 * Used by shrink-only gates (KT2, KT3, KT4, KT6) to let existing offenders stay
 * but never grow — the ratchet mechanism described in CLAUDE.md.
 */
export type Baseline = Record<string, number>;

/**
 * Load a baseline from a JSON file on disk.
 *
 * Returns an empty object if the file is absent, unreadable, or malformed.
 * All non-numeric values in the JSON are silently dropped.
 *
 * @param path  Absolute or cwd-relative path to the JSON baseline file.
 */
export function loadBaseline(path: string): Baseline {
  try {
    const content = readFileSync(path, 'utf8');
    const parsed: unknown = JSON.parse(content);
    if (
      typeof parsed !== 'object' ||
      parsed === null ||
      Array.isArray(parsed)
    ) {
      return {};
    }
    const result: Baseline = {};
    for (const [key, val] of Object.entries(parsed as Record<string, unknown>)) {
      if (typeof val === 'number') {
        result[key] = val;
      }
    }
    return result;
  } catch {
    return {};
  }
}

/**
 * Compare current file measurements against a shrink-only baseline.
 *
 * Returns one problem string per file that is either:
 *   - A NEW offender: `count > max` and the file is not in the baseline.
 *   - A BASELINED file that GREW: current count exceeds the frozen baseline count.
 *
 * Baselined files at or below their frozen count are OK (ratchet: allowed to
 * shrink, never to grow).  New files at or below `max` are also OK.
 *
 * @param current   Map of relative path → current measured count.
 * @param baseline  Frozen snapshot loaded by {@link loadBaseline}.
 * @param max       Ceiling for new (unbaselined) files.
 */
export function isShrinkOnly(
  current: Record<string, number>,
  baseline: Baseline,
  max: number,
): string[] {
  const problems: string[] = [];

  for (const [filePath, count] of Object.entries(current)) {
    if (filePath in baseline) {
      // Baselined file: only flag if it grew beyond its frozen count.
      const frozen = baseline[filePath];
      if (frozen !== undefined && count > frozen) {
        problems.push(
          `${filePath}: grew from ${frozen} to ${count} lines — baseline exceeded (shrink-only)`,
        );
      }
    } else if (count > max) {
      // New (unbaselined) file: flag if it exceeds the hard ceiling.
      problems.push(
        `${filePath}: ${count} lines exceeds max ${max} (add to baseline to acknowledge)`,
      );
    }
  }

  return problems;
}
