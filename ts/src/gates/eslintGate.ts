import { relative, join } from 'node:path';
import { statSync, readdirSync } from 'node:fs';
import { ESLint } from 'eslint';
import type { Gate, GateResult } from '../runner/types.js';
import { loadBaseline } from '../baseline/baseline.js';

/** Options for the eslint KISS gate. */
export interface EslintGateOpts {
  /**
   * File paths or directory paths to lint.  For directory roots,
   * `resolveFiles` walks recursively, excluding node_modules / dist /
   * __rods__ directories and *.test.ts / *.test.tsx files.  An explicit
   * file path is always included verbatim (so tests can target a rod).
   */
  roots: string[];
  /**
   * Path to a JSON baseline file mapping `${relpath}::${ruleId}` signatures
   * to frozen error counts.  Absent keys default to 0 (new violations are
   * always flagged).  Provides the shrink-only ratchet: existing offenders
   * may only stay or shrink, never grow.
   */
  baseline?: string;
}

const GATE_NAME = 'eslint';

/** Directory names skipped during recursive walks. */
const EXCLUDED_DIRS = new Set(['node_modules', 'dist', '__rods__']);

/** TypeScript file extensions to collect. */
const TS_EXTS = ['.ts', '.tsx'] as const;

/** Suffixes that identify test files — excluded from directory walks. */
const TEST_SUFFIXES = ['.test.ts', '.test.tsx'] as const;

function isTsFile(name: string): boolean {
  return TS_EXTS.some(ext => name.endsWith(ext));
}

function isTestFile(name: string): boolean {
  return TEST_SUFFIXES.some(s => name.endsWith(s));
}

/**
 * Recursively collect TS source files under a directory.
 *
 * Skips any subdirectory whose name is in EXCLUDED_DIRS (node_modules, dist,
 * __rods__) and any file whose name ends with a TEST_SUFFIX.
 */
function collectTsFiles(dir: string, out: string[]): void {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    if (entry.isDirectory()) {
      if (!EXCLUDED_DIRS.has(entry.name)) {
        collectTsFiles(join(dir, entry.name), out);
      }
    } else if (isTsFile(entry.name) && !isTestFile(entry.name)) {
      out.push(join(dir, entry.name));
    }
  }
}

/**
 * Resolve a list of roots (files or directories) to individual TS file paths.
 *
 * - Directory root: walked recursively; skips `node_modules`, `dist`,
 *   `__rods__` path segments and files ending `.test.ts`/`.test.tsx`.
 * - File root: included verbatim, so a test may target a rod explicitly.
 * - Non-existent roots are silently skipped.
 */
export function resolveFiles(roots: string[]): string[] {
  const out: string[] = [];
  for (const root of roots) {
    const stat = statSync(root, { throwIfNoEntry: false });
    if (stat === undefined) continue;
    if (stat.isDirectory()) {
      collectTsFiles(root, out);
    } else {
      out.push(root);
    }
  }
  return out;
}

/**
 * Compare current per-file rule error counts against a shrink-only baseline.
 *
 * Each key in `current` is `${relpath}::${ruleId}`.  A key whose current
 * count exceeds the baseline count (default 0) is reported as a problem
 * string of the form `${sig}: ${count} > ${base}`.
 *
 * @param current   Current error counts keyed by `${relpath}::${ruleId}`.
 * @param baseline  Frozen snapshot.  Missing keys default to 0.
 */
export function diffCounts(
  current: Record<string, number>,
  baseline: Record<string, number>,
): string[] {
  const problems: string[] = [];
  for (const [sig, count] of Object.entries(current)) {
    const base = baseline[sig] ?? 0;
    if (count > base) {
      problems.push(`${sig}: ${count} > ${base}`);
    }
  }
  return problems;
}

/**
 * Build a Gate that enforces KISS via the project's eslint flat config.
 *
 * Behaviour:
 * - Calls `resolveFiles(opts.roots)` to expand directories into individual TS
 *   files, excluding rods/tests/build dirs.  Explicit file paths are linted
 *   verbatim (needed for rod-targeting tests).
 * - Returns `ok: true` immediately when no files resolve (nothing to check).
 * - Constructs `new ESLint({ cwd })` with the flat config auto-discovered
 *   from `ts/eslint.config.mjs` (complexity ≤ 10, max-statements ≤ 50).
 * - Collects all error-severity (`severity === 2`) messages that have a
 *   `ruleId`, building `current: Record<\`${relpath}::${ruleId}\`, count>`.
 * - Loads the baseline JSON (empty object if absent or unreadable).
 * - Delegates pass/fail to `diffCounts` (shrink-only ratchet).
 *
 * The `cwd` is read inside `run()` so the gate captures the working directory
 * at call time, not construction time (mirrors KT2 lesson).
 *
 * @example
 * ```ts
 * const gate = eslintGate({ roots: ['src'], baseline: '.baselines/eslint.json' });
 * const result = await gate.run();
 * ```
 */
export function eslintGate(opts: EslintGateOpts): Gate {
  return {
    name: GATE_NAME,
    run: async (): Promise<GateResult> => {
      const cwd = process.cwd();
      const files = resolveFiles(opts.roots);

      if (files.length === 0) {
        return { gate: GATE_NAME, ok: true, problems: [] };
      }

      // ignore: false — resolveFiles() already excludes __rods__/node_modules/
      // dist from directory walks, so skipping global ignores is safe here AND
      // ensures an explicitly-passed rod file path is still linted (ESLint v9
      // global ignores would otherwise suppress explicitly-targeted files too).
      const eslint = new ESLint({ cwd, ignore: false });
      const results = await eslint.lintFiles(files);

      // Accumulate error counts keyed by `${relpath}::${ruleId}`.
      const current: Record<string, number> = {};
      for (const result of results) {
        const relpath = relative(cwd, result.filePath);
        for (const msg of result.messages) {
          if (msg.severity === 2 && msg.ruleId != null) {
            const sig = `${relpath}::${msg.ruleId}`;
            current[sig] = (current[sig] ?? 0) + 1;
          }
        }
      }

      const baseline =
        opts.baseline !== undefined ? loadBaseline(opts.baseline) : {};
      const problems = diffCounts(current, baseline);

      return {
        gate: GATE_NAME,
        ok: problems.length === 0,
        problems,
      };
    },
  };
}
