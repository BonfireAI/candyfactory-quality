import { readdirSync, readFileSync, statSync } from 'node:fs';
import { extname, join, relative } from 'node:path';
import type { Gate, GateResult } from '../runner/types.js';
import { isShrinkOnly, loadBaseline } from '../baseline/baseline.js';

/** Options for the file-budget gate. */
export interface FileBudgetOpts {
  /** Directories to walk recursively for *.ts / *.tsx source files. */
  roots: string[];
  /**
   * Maximum allowed effective line count for new (unbaselined) files.
   * Default: 500 (the SOLID/SRP budget in CLAUDE.md).
   */
  max?: number;
  /**
   * Path to a JSON baseline file mapping relative paths to frozen line counts.
   * If omitted, every file must be at or below `max`.
   */
  baseline?: string;
}

/** Gate name — must equal the `gate` field returned in every GateResult. */
const GATE_NAME = 'file-budget';
const DEFAULT_MAX = 500;

/**
 * Subdirectory names excluded from the recursive walk.
 *
 * NOTE: this excludes *subdirectories* named these values.  If a root IS one of
 * these directories (e.g. in tests that point directly at `__rods__`), files
 * inside it are still processed — the guard fires only when descending into a
 * child directory.
 */
const EXCLUDED_DIRS = new Set(['node_modules', '__rods__', 'dist']);

/**
 * Measure the effective size of a TypeScript / TSX source file.
 *
 * physical = total line count (the trailing blank element from a final `\n` is
 *            not counted, so the result matches the editor line-number display).
 * logical  = count of non-blank, non-comment lines.  This is an approximation of
 *            ADR 0030's "logical statements": rather than AST-level statement
 *            counting, we filter blank lines, `//` lines, `/* … *‌/` block-comment
 *            lines, and JSDoc continuation lines (`* …`).  Because every logical
 *            line is also a physical line, logical ≤ physical always, so
 *            Math.max(physical, logical) === physical under this approximation.
 *            See kt2-report.md for the full caveat.
 *
 * @returns Math.max(physical, logical)
 */
export function measureFile(filePath: string): number {
  const content = readFileSync(filePath, 'utf8');
  const lines = content.split('\n');

  // A file ending with \n produces an empty trailing element — exclude it from
  // the physical count so the number matches the editor's line count.
  const lastLine = lines.at(-1);
  const physical = lastLine === '' ? lines.length - 1 : lines.length;

  let logical = 0;
  let inBlock = false;

  for (const line of lines) {
    const t = line.trim();

    if (inBlock) {
      // Inside a block comment: look for the closing marker.
      if (t.includes('*/')) {
        inBlock = false;
      }
      continue;
    }

    if (t === '') continue;
    if (t.startsWith('//')) continue;

    if (t.startsWith('/*')) {
      // Self-closing `/* … */` stays out of block-comment state;
      // an unclosed `/*` opens block-comment state.
      if (!t.includes('*/')) {
        inBlock = true;
      }
      // Either way, the line itself is a pure comment — skip it.
      continue;
    }

    // Continuation lines inside a JSDoc / block comment (`* @param …` etc.)
    if (t.startsWith('*')) continue;

    logical++;
  }

  return Math.max(physical, logical);
}

/**
 * Recursively collect *.ts / *.tsx non-test source files under `dir`.
 *
 * Results are stored in `out` keyed by path relative to `cwd`.
 * Subdirectories in EXCLUDED_DIRS are skipped entirely.
 */
function collectFiles(
  dir: string,
  cwd: string,
  out: Map<string, number>,
): void {
  const entries = readdirSync(dir);
  for (const entry of entries) {
    const full = join(dir, entry);
    const st = statSync(full);
    if (st.isDirectory()) {
      if (!EXCLUDED_DIRS.has(entry)) {
        collectFiles(full, cwd, out);
      }
    } else {
      const ext = extname(entry);
      if (
        (ext === '.ts' || ext === '.tsx') &&
        !entry.endsWith('.test.ts') &&
        !entry.endsWith('.test.tsx')
      ) {
        out.set(relative(cwd, full), measureFile(full));
      }
    }
  }
}

/**
 * Build a Gate that enforces the file-budget rule across the given roots.
 *
 * The gate walks `opts.roots` recursively, skipping node_modules, `__rods__`,
 * dist, and `*.test.ts` / `*.test.tsx` files.  For each collected file it calls
 * {@link measureFile} and then delegates to {@link isShrinkOnly} for the
 * pass/fail decision.
 *
 * @example
 * ```ts
 * const gate = fileBudgetGate({ roots: ['src'], baseline: '.baselines/file-budget.json' });
 * const result = await gate.run();
 * ```
 */
export function fileBudgetGate(opts: FileBudgetOpts): Gate {
  const max = opts.max ?? DEFAULT_MAX;
  const cwd = process.cwd();

  return {
    name: GATE_NAME,
    run: async (): Promise<GateResult> => {
      const collected = new Map<string, number>();
      for (const root of opts.roots) {
        collectFiles(root, cwd, collected);
      }

      const current: Record<string, number> = Object.fromEntries(collected);
      const baseline =
        opts.baseline !== undefined ? loadBaseline(opts.baseline) : {};

      const problems = isShrinkOnly(current, baseline, max);
      return {
        gate: GATE_NAME,
        ok: problems.length === 0,
        problems,
      };
    },
  };
}
