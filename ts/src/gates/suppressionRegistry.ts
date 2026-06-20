import { readFileSync, readdirSync, statSync } from 'node:fs';
import { extname, join, relative } from 'node:path';
import type { Gate, GateResult } from '../runner/types.js';

// ---------------------------------------------------------------------------
// Public interfaces
// ---------------------------------------------------------------------------

export interface Suppression {
  file: string;
  line: number;
  directive: string;
}

export interface RegistryEntry extends Suppression {
  reason: string;
  blessedBy: string;
}

export interface SuppressionGateOpts {
  roots: string[];
  registry: string;
}

// ---------------------------------------------------------------------------
// Internal constants
// ---------------------------------------------------------------------------

const GATE_NAME = 'suppression-registry';

/**
 * Directory names excluded when descending during a recursive walk.
 * Note: if a root IS one of these directories (e.g. an explicit test path),
 * its files are still scanned verbatim — the guard fires only on child dirs.
 */
const EXCLUDED_DIR_NAMES = new Set(['node_modules', 'dist', '__rods__']);

interface DirectivePattern {
  directive: string;
  pattern: RegExp;
}

/**
 * Ordered directive patterns.  The eslint variants are ordered most-specific
 * first so that `eslint-disable-next-line` and `eslint-disable-line` are never
 * double-counted against the bare `eslint-disable` pattern.
 *
 * `eslint-disable-line` is NOT a substring of `eslint-disable-next-line`
 * (because `-next-` intervenes), so patterns 3 and 4 are naturally disjoint.
 * Pattern 5 uses a negative lookahead to exclude the more-specific variants.
 */
const DIRECTIVE_PATTERNS: DirectivePattern[] = [
  { directive: '@ts-ignore',               pattern: /@ts-ignore/ },
  { directive: '@ts-expect-error',         pattern: /@ts-expect-error/ },
  { directive: 'eslint-disable-next-line', pattern: /eslint-disable-next-line/ },
  { directive: 'eslint-disable-line',      pattern: /eslint-disable-line/ },
  { directive: 'eslint-disable',           pattern: /eslint-disable(?!-(?:next-)?line)/ },
];

// ---------------------------------------------------------------------------
// Comment extraction (anchors directive detection to comment context)
// ---------------------------------------------------------------------------

/**
 * Return only the comment text portions of a single source line.
 *
 * Handles:
 *   - `//` line comments — everything after `//` is comment text.
 *   - `/* ... *\/` block comments that open **and close** on the same line.
 *
 * Does not track multi-line block comment state: a `/*` with no matching `*\/`
 * on the same line contributes the text from `/*` to end-of-line (which is
 * safe — those lines are typically continuation lines with no directive).
 *
 * Directive words that appear only in code, strings, or regex literals are
 * therefore excluded from the returned text, avoiding self-poison when the
 * gate scans its own source (DIRECTIVE_PATTERNS contains the words as
 * string/regex literals, not in comments).
 */
function extractCommentText(line: string): string {
  const parts: string[] = [];
  let i = 0;
  while (i < line.length) {
    if (line[i] === '/' && line[i + 1] === '/') {
      parts.push(line.slice(i + 2));
      break;
    }
    if (line[i] === '/' && line[i + 1] === '*') {
      const end = line.indexOf('*/', i + 2);
      if (end === -1) {
        parts.push(line.slice(i + 2));
        break;
      }
      parts.push(line.slice(i + 2, end));
      i = end + 2;
    } else {
      i++;
    }
  }
  return parts.join(' ');
}

// ---------------------------------------------------------------------------
// File scanner (own small walk — lane-independent per ADR 0030 §4)
// ---------------------------------------------------------------------------

/**
 * Scan a single file for suppression directives and append findings to `out`.
 * `relPath` is the path used in the emitted Suppression objects.
 * Directives are detected only within comment text (see `extractCommentText`).
 */
function scanFile(absPath: string, relPath: string, out: Suppression[]): void {
  const content = readFileSync(absPath, 'utf8');
  const lines = content.split('\n');
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i] ?? '';
    const commentText = extractCommentText(line);
    for (const { directive, pattern } of DIRECTIVE_PATTERNS) {
      if (pattern.test(commentText)) {
        out.push({ file: relPath, line: i + 1, directive });
      }
    }
  }
}

/**
 * Recursively walk `dir` for `*.ts` / `*.tsx` files, skipping subdirectories
 * whose name appears in EXCLUDED_DIR_NAMES.  Results appended to `out`.
 */
function walkDir(dir: string, cwd: string, out: Suppression[]): void {
  const entries = readdirSync(dir);
  for (const entry of entries) {
    const full = join(dir, entry);
    const st = statSync(full);
    if (st.isDirectory()) {
      if (!EXCLUDED_DIR_NAMES.has(entry)) {
        walkDir(full, cwd, out);
      }
    } else {
      const ext = extname(entry);
      if (ext === '.ts' || ext === '.tsx') {
        scanFile(full, relative(cwd, full), out);
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Walk each root for `*.ts` / `*.tsx` files and return all suppression
 * directives found.  Directory roots are walked recursively (skipping
 * node_modules, dist, __rods__).  Explicit file roots are scanned verbatim.
 *
 * Exported for unit testing.
 */
export function findSuppressions(roots: string[]): Suppression[] {
  const cwd = process.cwd();
  const results: Suppression[] = [];
  for (const root of roots) {
    const st = statSync(root, { throwIfNoEntry: false });
    if (st === undefined) continue;
    if (st.isDirectory()) {
      walkDir(root, cwd, results);
    } else {
      const ext = extname(root);
      if (ext === '.ts' || ext === '.tsx') {
        scanFile(root, relative(cwd, root), results);
      }
    }
  }
  return results;
}

/**
 * Return true only when `entry` has the three fields required for a
 * registry match: a string `file`, a number `line`, and a string `directive`.
 * The optional `reason` and `blessedBy` fields are not validated here.
 */
function isValidRegistryEntry(entry: unknown): boolean {
  if (typeof entry !== 'object' || entry === null) return false;
  const e = entry as Record<string, unknown>;
  return (
    typeof e['file'] === 'string' &&
    typeof e['line'] === 'number' &&
    typeof e['directive'] === 'string'
  );
}

/**
 * Load the registry JSON from `registryPath`.
 *
 * - File absent / unreadable → returns `[]` (no suppressions blessed yet).
 * - File present but unparseable, not a JSON array, or containing an entry
 *   that lacks required fields (file/line/directive) → returns `{ error }`.
 */
function loadRegistry(registryPath: string): RegistryEntry[] | { error: string } {
  let raw: string;
  try {
    raw = readFileSync(registryPath, 'utf8');
  } catch {
    // File absent or unreadable — treat as empty (not an error).
    return [];
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return { error: `Registry at ${registryPath} contains invalid JSON` };
  }
  if (!Array.isArray(parsed)) {
    return { error: `Registry at ${registryPath} is not a JSON array` };
  }
  if (!parsed.every(isValidRegistryEntry)) {
    return {
      error: `Registry at ${registryPath} contains an entry missing required fields (file, line, directive)`,
    };
  }
  return parsed as RegistryEntry[];
}

/**
 * Build the suppression-registry gate.
 *
 * Each suppression found in source must have a matching entry in the registry
 * (matched on file + line + directive).  Unregistered suppressions are
 * flagged as problems.
 */
export function suppressionRegistryGate(opts: SuppressionGateOpts): Gate {
  return {
    name: GATE_NAME,
    run: async (): Promise<GateResult> => {
      // cwd read inside run() per spec — do NOT hoist to module scope.
      const cwd = process.cwd();

      const roots = opts.roots.map(r =>
        r.startsWith('/') ? r : join(cwd, r),
      );

      const current = findSuppressions(roots);

      const registryResult = loadRegistry(opts.registry);
      if ('error' in registryResult) {
        return {
          gate: GATE_NAME,
          ok: false,
          problems: [`REGISTRY_PARSE_ERROR: ${registryResult.error}`],
        };
      }

      const registry = registryResult;
      const problems: string[] = [];

      for (const s of current) {
        const registered = registry.some(
          e => e.file === s.file && e.line === s.line && e.directive === s.directive,
        );
        if (!registered) {
          problems.push(
            `UNREGISTERED_SUPPRESSION: ${s.file}:${s.line} ${s.directive}`,
          );
        }
      }

      return {
        gate: GATE_NAME,
        ok: problems.length === 0,
        problems,
      };
    },
  };
}
