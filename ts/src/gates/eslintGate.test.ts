import { describe, it, expect } from 'vitest';
import { writeFileSync, unlinkSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';
import { eslintGate, diffCounts, resolveFiles } from './eslintGate.js';

/**
 * Resolve fixture paths from this test file's location.
 *
 * import.meta.url = file:///…/ts/src/gates/eslintGate.test.ts
 * new URL('./__rods__', import.meta.url).pathname → /…/ts/src/gates/__rods__
 *
 * The config now has `**\/__rods__\/**` in global ignores (CLI safety), but the
 * gate constructs ESLint with `ignore: false`, so explicit rod paths are still
 * linted verbatim in tests below.  resolveFiles() separately excludes __rods__
 * during directory walks.
 */
const ROD_DIR = new URL('./__rods__', import.meta.url).pathname;
const ROD_FILE = join(ROD_DIR, 'tooComplex.fixture.ts');
const CLEAN_FILE = join(ROD_DIR, 'clean.fixture.ts');

// ---------------------------------------------------------------------------
// 1. diffCounts — unit
// ---------------------------------------------------------------------------
describe('diffCounts', () => {
  it('flags when current count exceeds baseline', () => {
    const problems = diffCounts(
      { 'a::complexity': 2 },
      { 'a::complexity': 1 },
    );
    expect(problems).toHaveLength(1);
    expect(problems[0]).toContain('a::complexity');
    expect(problems[0]).toContain('2 > 1');
  });

  it('passes when current count equals baseline', () => {
    const problems = diffCounts(
      { 'a::complexity': 2 },
      { 'a::complexity': 2 },
    );
    expect(problems).toHaveLength(0);
  });

  it('flags when no baseline entry exists (defaults to 0)', () => {
    const problems = diffCounts({ 'a::complexity': 2 }, {});
    expect(problems).toHaveLength(1);
    expect(problems[0]).toContain('2 > 0');
  });
});

// ---------------------------------------------------------------------------
// 2. eslintGate — tooComplex rod (no baseline) → fail
// ---------------------------------------------------------------------------
describe('eslintGate — tooComplex rod, no baseline', () => {
  it('returns ok=false and a problem containing "complexity"', async () => {
    const result = await eslintGate({ roots: [ROD_FILE] }).run();

    expect(result.gate).toBe('eslint');
    expect(result.ok).toBe(false);
    const hasComplexityProblem = result.problems.some(p =>
      p.includes('complexity'),
    );
    expect(hasComplexityProblem).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// 3. eslintGate — tooComplex rod with frozen baseline → pass (ratchet honored)
// ---------------------------------------------------------------------------
describe('eslintGate — tooComplex rod, frozen baseline', () => {
  it('returns ok=true when the complexity count is frozen in the baseline', async () => {
    // Build the expected signature key: relpath relative to cwd.
    const rodRelPath = relative(process.cwd(), ROD_FILE);
    const complexSig = `${rodRelPath}::complexity`;

    // The rod has CC=13 (1 function exceeding the threshold) → 1 error.
    const baselineObj: Record<string, number> = { [complexSig]: 1 };
    const tmpFile = join(tmpdir(), `kt3-baseline-${Date.now()}.json`);
    writeFileSync(tmpFile, JSON.stringify(baselineObj), 'utf8');

    try {
      const result = await eslintGate({
        roots: [ROD_FILE],
        baseline: tmpFile,
      }).run();

      expect(result.gate).toBe('eslint');
      expect(result.ok).toBe(true);
      expect(result.problems).toHaveLength(0);
    } finally {
      unlinkSync(tmpFile);
    }
  });
});

// ---------------------------------------------------------------------------
// 4. eslintGate — clean fixture → pass
// ---------------------------------------------------------------------------
describe('eslintGate — clean fixture', () => {
  it('returns ok=true for a file with no complexity violations', async () => {
    const result = await eslintGate({ roots: [CLEAN_FILE] }).run();

    expect(result.gate).toBe('eslint');
    expect(result.ok).toBe(true);
    expect(result.problems).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// 5. resolveFiles — self-run safety (directory walk excludes __rods__)
// ---------------------------------------------------------------------------
describe('resolveFiles', () => {
  it('excludes __rods__ paths when walking a directory root', () => {
    // Use an absolute path derived from import.meta.url so the walk succeeds
    // regardless of the process cwd (guards against vacuous-pass when cwd≠ts/).
    // import.meta.url = file:///…/ts/src/gates/eslintGate.test.ts
    // new URL('..', import.meta.url) → file:///…/ts/src/gates/../  = ts/src/
    const srcDir = fileURLToPath(new URL('..', import.meta.url));
    const files = resolveFiles([srcDir]);
    // Sentinel: the walk must find at least one file — an empty result would
    // make the __rods__ assertion below trivially true (vacuous pass).
    expect(files.length).toBeGreaterThan(0);
    const hasRod = files.some(f => f.includes('__rods__'));
    expect(hasRod).toBe(false);
  });
});
