import { describe, it, expect } from 'vitest';
import { writeFileSync, unlinkSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { importContractGate } from './importContract.js';

/**
 * Resolve fixture paths from this test file's location.
 *
 * import.meta.url = file:///…/ts/src/gates/importContract.test.ts
 *
 * Absolute path derivation avoids cwd sensitivity: the tests pass regardless
 * of which directory vitest is invoked from.
 */
const GATES_DIR = fileURLToPath(new URL('.', import.meta.url));

/** Real config at ts/.dependency-cruiser.cjs  */
const REAL_CONFIG = fileURLToPath(
  new URL('../../.dependency-cruiser.cjs', import.meta.url),
);

/**
 * Rod-local contract: same forbidden rules as the real config but WITHOUT the
 * `exclude: { path: '__rods__' }` option so test #1 can cruise the rod dir and
 * prove CONTRACT_BROKEN.  The real config excludes __rods__ (Fix 2), which is
 * why test #1 must use this dedicated config instead of REAL_CONFIG.
 */
const ROD_CONFIG = fileURLToPath(
  new URL('./__rods__/upwardImport/contract.cjs', import.meta.url),
);

/** Rod directory: contains core/badImporter.ts → adapters/secret.ts */
const ROD_DIR = join(GATES_DIR, '__rods__', 'upwardImport');

/** Clean dir: a small module with no violations */
const CLEAN_DIR = fileURLToPath(new URL('../runner', import.meta.url));

// ─────────────────────────────────────────────────────────────────────────────
// 1. Rod (core→adapters) with real config → CONTRACT_BROKEN
// ─────────────────────────────────────────────────────────────────────────────
describe('importContractGate — upwardImport rod', () => {
  it('returns ok=false and a CONTRACT_BROKEN problem naming the core→adapters edge', async () => {
    // Use ROD_CONFIG (no __rods__ exclude) rather than REAL_CONFIG so the rod
    // dir is actually cruised.  The real config now excludes __rods__ so that
    // the kit's own self-run does not report the intentional DIP violation.
    const gate = importContractGate({ config: ROD_CONFIG, roots: [ROD_DIR] });
    const result = await gate.run();

    expect(result.gate).toBe('import-contract');
    expect(result.ok).toBe(false);
    const hasBroken = result.problems.some((p) => p.includes('CONTRACT_BROKEN'));
    expect(hasBroken).toBe(true);
    // The violated rule should name the core→adapters edge
    const hasRule = result.problems.some((p) =>
      p.includes('core-not-to-adapters') || p.includes('core') || p.includes('adapters'),
    );
    expect(hasRule).toBe(true);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// 2. Config with empty forbidden array → CONTRACT_MISSING
// ─────────────────────────────────────────────────────────────────────────────
describe('importContractGate — empty forbidden rules', () => {
  it('returns ok=false with a CONTRACT_MISSING problem', async () => {
    const content =
      '// KT4 empty-contract fixture\nmodule.exports = { forbidden: [] };\n';
    const tmpCjs = join(tmpdir(), `kt4-empty-contract-${Date.now()}.cjs`);
    writeFileSync(tmpCjs, content, 'utf8');

    try {
      const gate = importContractGate({ config: tmpCjs, roots: [CLEAN_DIR] });
      const result = await gate.run();

      expect(result.gate).toBe('import-contract');
      expect(result.ok).toBe(false);
      const hasMissing = result.problems.some((p) => p.includes('CONTRACT_MISSING'));
      expect(hasMissing).toBe(true);
    } finally {
      unlinkSync(tmpCjs);
    }
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// 3. Non-existent config path → CONTRACT_CONFIG_ERROR
// ─────────────────────────────────────────────────────────────────────────────
describe('importContractGate — non-existent config', () => {
  it('returns ok=false with a CONTRACT_CONFIG_ERROR problem', async () => {
    const gate = importContractGate({
      config: '/no/such/path/.dependency-cruiser.cjs',
      roots: [CLEAN_DIR],
    });
    const result = await gate.run();

    expect(result.gate).toBe('import-contract');
    expect(result.ok).toBe(false);
    const hasConfigError = result.problems.some((p) =>
      p.includes('CONTRACT_CONFIG_ERROR'),
    );
    expect(hasConfigError).toBe(true);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// 4. Clean dir (src/runner) with real config → ok=true
// ─────────────────────────────────────────────────────────────────────────────
describe('importContractGate — clean runner dir', () => {
  it('returns ok=true for the runner directory which has no violations', async () => {
    const gate = importContractGate({ config: REAL_CONFIG, roots: [CLEAN_DIR] });
    const result = await gate.run();

    expect(result.gate).toBe('import-contract');
    expect(result.ok).toBe(true);
    expect(result.problems).toHaveLength(0);
  });
});
