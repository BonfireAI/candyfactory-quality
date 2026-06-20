import { spawnSync } from 'node:child_process';
import { readFileSync, existsSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import type { Gate, GateResult } from '../runner/types.js';

// ---------------------------------------------------------------------------
// Public interface
// ---------------------------------------------------------------------------

/** Options for the tsc-strict gate. */
export interface TscStrictOpts {
  /** Path to the tsconfig.json (or directory containing one). */
  project: string;
  /**
   * Path to a JSON baseline file (string[]).  Each element is an allowed error
   * signature of the form `<file>(<line>,<col>): <TScode>`.
   * Only signatures NOT present in the baseline are reported as problems
   * (shrink-only ratchet).  If omitted, every TS error is a problem.
   */
  baseline?: string;
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

const GATE_NAME = 'tsc-strict' as const;

/**
 * Matches a TypeScript diagnostic line.
 * Group 1: file path
 * Group 2: line number
 * Group 3: column number
 * Group 4: TS error code (e.g. "TS2322")
 */
const ERROR_LINE_RE = /^(.+)\((\d+),(\d+)\): error (TS\d+):/;

/**
 * Walk directories upward from `startDir` looking for `node_modules/.bin/tsc`.
 * Returns the absolute path to the local tsc binary if found, otherwise null.
 *
 * Loop terminates when `dirname(dir) === dir` (filesystem root reached).
 */
function findLocalTsc(startDir: string): string | null {
  let dir = startDir;
  while (true) {
    const candidate = join(dir, 'node_modules', '.bin', 'tsc');
    if (existsSync(candidate)) return candidate;
    const parent = dirname(dir);
    if (parent === dir) return null;
    dir = parent;
  }
}

/** Discriminated result of a tsc spawn. */
type SpawnOutcome = { kind: 'output'; text: string } | { kind: 'error'; message: string };

/**
 * Spawn tsc --noEmit -p <project> and return captured stdout+stderr.
 *
 * tsc exits non-zero when type errors exist — that is expected and NOT treated
 * as a spawn error.  Only a failure to exec the binary itself is an error.
 */
function runTsc(projectPath: string, tscBin: string): SpawnOutcome {
  const result = spawnSync(tscBin, ['--noEmit', '-p', projectPath], {
    encoding: 'utf8',
  });

  if (result.error !== undefined) {
    return {
      kind: 'error',
      message: `TSC_SPAWN_ERROR: failed to spawn "${tscBin}": ${result.error.message}`,
    };
  }

  const text = [result.stdout ?? '', result.stderr ?? ''].join('\n');
  return { kind: 'output', text };
}

/**
 * Parse tsc diagnostic output and return de-duplicated error signatures.
 * Signature format: `<file>(<line>,<col>): <TScode>`
 */
function parseErrors(output: string): string[] {
  const seen = new Set<string>();
  for (const line of output.split('\n')) {
    const match = ERROR_LINE_RE.exec(line);
    if (match !== null) {
      const file = match[1];
      const lineNum = match[2];
      const col = match[3];
      const tsCode = match[4];
      if (
        file !== undefined &&
        lineNum !== undefined &&
        col !== undefined &&
        tsCode !== undefined
      ) {
        seen.add(`${file}(${lineNum},${col}): ${tsCode}`);
      }
    }
  }
  return [...seen];
}

/**
 * Load a tsc baseline from a JSON file.
 *
 * The baseline is a `string[]` of allowed error signatures.  Returns an empty
 * array if the file is absent, unreadable, or malformed — the gate then treats
 * every current error as a new violation.
 */
function loadTscBaseline(baselinePath: string): string[] {
  let raw: string;
  try {
    raw = readFileSync(baselinePath, 'utf8');
  } catch {
    return [];
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return [];
  }

  if (!Array.isArray(parsed)) return [];
  return parsed.filter((e): e is string => typeof e === 'string');
}

// ---------------------------------------------------------------------------
// Public factory
// ---------------------------------------------------------------------------

/**
 * Build a Gate that enforces TypeScript strict-mode correctness via `tsc --noEmit`.
 *
 * Behaviour:
 * - Resolves `opts.project` to an absolute path.
 * - Locates the nearest local `node_modules/.bin/tsc` (walking up from the
 *   tsconfig's directory); falls back to the `tsc` on PATH.
 * - Spawns `tsc --noEmit -p <project>` and captures stdout+stderr.
 * - Parses error lines into `<file>(<line>,<col>): <TScode>` signatures.
 * - If a baseline is provided, reports only signatures absent from it
 *   (shrink-only: the set of allowed errors may only shrink over time).
 * - A spawn failure produces a `TSC_SPAWN_ERROR` problem (Elegance Law).
 *
 * @example
 * ```ts
 * const gate = tscStrictGate({ project: 'tsconfig.json' });
 * const result = await gate.run();
 * ```
 */
export function tscStrictGate(opts: TscStrictOpts): Gate {
  return {
    name: GATE_NAME,
    run: async (): Promise<GateResult> => {
      const projectPath = resolve(opts.project);
      const projectDir = dirname(projectPath);
      const tscBin = findLocalTsc(projectDir) ?? 'tsc';

      const outcome = runTsc(projectPath, tscBin);
      if (outcome.kind === 'error') {
        return {
          gate: GATE_NAME,
          ok: false,
          problems: [outcome.message],
        };
      }

      const current = parseErrors(outcome.text);

      let problems: string[];
      if (opts.baseline !== undefined) {
        const allowed = new Set(loadTscBaseline(opts.baseline));
        problems = current.filter(sig => !allowed.has(sig));
      } else {
        problems = current;
      }

      return {
        gate: GATE_NAME,
        ok: problems.length === 0,
        problems,
      };
    },
  };
}
