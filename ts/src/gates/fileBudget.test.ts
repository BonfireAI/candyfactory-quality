import { describe, it, expect } from 'vitest';
import { writeFileSync, unlinkSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, relative } from 'node:path';
import { measureFile, fileBudgetGate } from './fileBudget.js';
import { isShrinkOnly } from '../baseline/baseline.js';
import type { Baseline } from '../baseline/baseline.js';

/**
 * Resolve the __rods__ directory relative to this test file.
 *
 * import.meta.url = file:///…/ts/src/gates/fileBudget.test.ts
 * new URL('./__rods__', import.meta.url).pathname
 *   → /…/ts/src/gates/__rods__
 *
 * The gate normally skips subdirectories named `__rods__`; when tests pass
 * this directory as an explicit *root*, the exclusion guard never fires
 * (it only fires when descending *into* a child dir of that name).
 */
const ROD_DIR = new URL('./__rods__', import.meta.url).pathname;
const ROD_FILE = join(ROD_DIR, 'oversized.fixture.ts');

// ---------------------------------------------------------------------------
// 1. measureFile — control rod returns > 500
// ---------------------------------------------------------------------------
describe('measureFile', () => {
  it('returns > 500 for the oversized fixture (physical-line path)', () => {
    const count = measureFile(ROD_FILE);
    expect(count).toBeGreaterThan(500);
  });
});

// ---------------------------------------------------------------------------
// 2. fileBudgetGate — new file over the limit (no baseline) → fail
// ---------------------------------------------------------------------------
describe('fileBudgetGate', () => {
  it('fails when a new file exceeds max with no baseline', async () => {
    // Point the gate root directly at the __rods__ directory so the fixture
    // is collected without being excluded by the EXCLUDED_DIRS guard.
    const result = await fileBudgetGate({ roots: [ROD_DIR] }).run();

    expect(result.gate).toBe('file-budget');
    expect(result.ok).toBe(false);
    expect(result.problems).toHaveLength(1);
    // The problem string must name the offending file.
    expect(result.problems[0]).toContain('oversized.fixture.ts');
  });
});

// ---------------------------------------------------------------------------
// 3. isShrinkOnly — baselined file at its current count → ok
// ---------------------------------------------------------------------------
describe('isShrinkOnly — shrink-only honored', () => {
  it('passes a file that is in the baseline at its exact current count', () => {
    const count = measureFile(ROD_FILE); // e.g. 526
    const filePath = 'src/gates/__rods__/oversized.fixture.ts';
    const current: Record<string, number> = { [filePath]: count };
    const baseline: Baseline = { [filePath]: count };

    const problems = isShrinkOnly(current, baseline, 500);

    expect(problems).toHaveLength(0);
  });

  it('also passes a baselined file that shrank', () => {
    const current: Record<string, number> = { 'src/big.ts': 480 };
    const baseline: Baseline = { 'src/big.ts': 490 };

    const problems = isShrinkOnly(current, baseline, 500);

    expect(problems).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// 4. isShrinkOnly — baselined file that grew → flagged
// ---------------------------------------------------------------------------
describe('isShrinkOnly — growth detection', () => {
  it('flags a baselined file whose count exceeds the frozen baseline', () => {
    const current: Record<string, number> = { 'src/big.ts': 510 };
    const baseline: Baseline = { 'src/big.ts': 490 };

    const problems = isShrinkOnly(current, baseline, 500);

    expect(problems).toHaveLength(1);
    expect(problems[0]).toContain('src/big.ts');
  });

  it('does not flag a new file that is within the limit', () => {
    const current: Record<string, number> = { 'src/small.ts': 100 };
    const problems = isShrinkOnly(current, {}, 500);
    expect(problems).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// 5. fileBudgetGate — integration: baseline loaded from disk (shrink-only)
// ---------------------------------------------------------------------------
describe('fileBudgetGate — baseline loaded from disk', () => {
  it('passes a frozen file when its baseline count is read from disk', async () => {
    // The gate computes relative-path keys as relative(process.cwd(), absolutePath),
    // so we must use the same computation to match the baseline key at run time.
    const count = measureFile(ROD_FILE);
    const rodKey = relative(process.cwd(), ROD_FILE);
    const baselineObj = { [rodKey]: count };

    const tmpFile = join(tmpdir(), `kt2-baseline-${Date.now()}.json`);
    writeFileSync(tmpFile, JSON.stringify(baselineObj), 'utf8');

    try {
      const result = await fileBudgetGate({ roots: [ROD_DIR], baseline: tmpFile }).run();
      expect(result.ok).toBe(true);
      expect(result.problems).toHaveLength(0);
    } finally {
      unlinkSync(tmpFile);
    }
  });

  it('fails the same root with no baseline', async () => {
    const result = await fileBudgetGate({ roots: [ROD_DIR] }).run();
    expect(result.ok).toBe(false);
  });
});
