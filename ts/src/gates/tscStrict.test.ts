import { describe, it, expect } from 'vitest';
import { writeFileSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { tscStrictGate } from './tscStrict.js';

// ---------------------------------------------------------------------------
// Fixture paths (__rods__/tscError/ excluded from gate runs by EXCLUDED_DIRS)
// ---------------------------------------------------------------------------

const __dirnameEsm = dirname(fileURLToPath(import.meta.url));
const RODS_DIR = join(__dirnameEsm, '__rods__', 'tscError');

// ---------------------------------------------------------------------------
// Gate name
// ---------------------------------------------------------------------------

describe('tscStrictGate — name', () => {
  it('has gate name "tsc-strict"', () => {
    const gate = tscStrictGate({ project: 'tsconfig.json' });
    expect(gate.name).toBe('tsc-strict');
  });
});

// ---------------------------------------------------------------------------
// Broken fixture → ok:false naming the TS error code
// ---------------------------------------------------------------------------

describe('tscStrictGate — broken fixture', () => {
  it('reports ok:false with at least one TS error signature', async () => {
    const gate = tscStrictGate({
      project: join(RODS_DIR, 'broken', 'tsconfig.json'),
    });
    const result = await gate.run();

    expect(result.gate).toBe('tsc-strict');
    expect(result.ok).toBe(false);
    expect(result.problems.length).toBeGreaterThan(0);
    // Problem strings must reference a TS error code.
    const hasCode = result.problems.some(p => /TS\d+/.test(p));
    expect(hasCode).toBe(true);
  });

  it('passes (ok:true) when baseline covers all current errors', async () => {
    // Discover the current error signatures.
    const discover = tscStrictGate({
      project: join(RODS_DIR, 'broken', 'tsconfig.json'),
    });
    const discovery = await discover.run();
    expect(discovery.ok).toBe(false);
    expect(discovery.problems.length).toBeGreaterThan(0);

    // Write them to a temp baseline file.
    const tmpDir = mkdtempSync(join(tmpdir(), 'cfq-tsc-test-'));
    const baselinePath = join(tmpDir, 'tsc-baseline.json');
    writeFileSync(baselinePath, JSON.stringify(discovery.problems));
    try {
      const gateWithBaseline = tscStrictGate({
        project: join(RODS_DIR, 'broken', 'tsconfig.json'),
        baseline: baselinePath,
      });
      const result = await gateWithBaseline.run();
      // All errors are baselined → gate must pass.
      expect(result.ok).toBe(true);
      expect(result.problems).toHaveLength(0);
    } finally {
      rmSync(tmpDir, { recursive: true });
    }
  });
});

// ---------------------------------------------------------------------------
// Clean fixture → ok:true
// ---------------------------------------------------------------------------

describe('tscStrictGate — clean fixture', () => {
  it('reports ok:true with zero problems', async () => {
    const gate = tscStrictGate({
      project: join(RODS_DIR, 'clean', 'tsconfig.json'),
    });
    const result = await gate.run();

    expect(result.gate).toBe('tsc-strict');
    expect(result.ok).toBe(true);
    expect(result.problems).toHaveLength(0);
  });
});
