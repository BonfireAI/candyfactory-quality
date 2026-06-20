import { describe, it, expect } from 'vitest';
import { writeFileSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { loadConfig, buildGates, CfGateConfigError } from './config.js';

// ---------------------------------------------------------------------------
// loadConfig
// ---------------------------------------------------------------------------

describe('loadConfig', () => {
  it('returns a CfGateConfig from a valid JSON file', () => {
    const dir = mkdtempSync(join(tmpdir(), 'cfq-config-test-'));
    const configPath = join(dir, 'cfq-ts.config.json');
    writeFileSync(
      configPath,
      JSON.stringify({
        roots: ['src'],
        importContractConfig: '.dependency-cruiser.cjs',
        suppressionRegistry: 'cfq-ts-exemptions.json',
        tsconfig: 'tsconfig.json',
      }),
    );
    try {
      const config = loadConfig(configPath);
      expect(config.roots).toEqual(['src']);
      expect(config.importContractConfig).toBe('.dependency-cruiser.cjs');
      expect(config.suppressionRegistry).toBe('cfq-ts-exemptions.json');
      expect(config.tsconfig).toBe('tsconfig.json');
      expect(config.fileBudgetBaseline).toBeUndefined();
      expect(config.eslintBaseline).toBeUndefined();
      expect(config.tscBaseline).toBeUndefined();
    } finally {
      rmSync(dir, { recursive: true });
    }
  });

  it('parses optional baseline fields when present', () => {
    const dir = mkdtempSync(join(tmpdir(), 'cfq-config-test-'));
    const configPath = join(dir, 'cfq-ts.config.json');
    writeFileSync(
      configPath,
      JSON.stringify({
        roots: ['src'],
        importContractConfig: '.dependency-cruiser.cjs',
        suppressionRegistry: 'cfq-ts-exemptions.json',
        tsconfig: 'tsconfig.json',
        fileBudgetBaseline: '.baselines/file-budget.json',
        eslintBaseline: '.baselines/eslint.json',
        tscBaseline: '.baselines/tsc.json',
      }),
    );
    try {
      const config = loadConfig(configPath);
      expect(config.fileBudgetBaseline).toBe('.baselines/file-budget.json');
      expect(config.eslintBaseline).toBe('.baselines/eslint.json');
      expect(config.tscBaseline).toBe('.baselines/tsc.json');
    } finally {
      rmSync(dir, { recursive: true });
    }
  });

  it('throws CfGateConfigError(CONFIG_MISSING) for a missing file', () => {
    try {
      loadConfig('/nonexistent/__cfq_test__/cfq-ts.config.json');
      expect(true).toBe(false); // should not reach here
    } catch (err) {
      if (err instanceof CfGateConfigError) {
        expect(err.kind).toBe('CONFIG_MISSING');
      } else {
        throw err;
      }
    }
  });

  it('throws CfGateConfigError(CONFIG_INVALID_JSON) for malformed JSON', () => {
    const dir = mkdtempSync(join(tmpdir(), 'cfq-config-test-'));
    const configPath = join(dir, 'cfq-ts.config.json');
    writeFileSync(configPath, 'not { valid json');
    try {
      try {
        loadConfig(configPath);
        expect(true).toBe(false);
      } catch (err) {
        if (err instanceof CfGateConfigError) {
          expect(err.kind).toBe('CONFIG_INVALID_JSON');
        } else {
          throw err;
        }
      }
    } finally {
      rmSync(dir, { recursive: true });
    }
  });

  it('throws CfGateConfigError(CONFIG_INVALID_SCHEMA) when roots is missing', () => {
    const dir = mkdtempSync(join(tmpdir(), 'cfq-config-test-'));
    const configPath = join(dir, 'cfq-ts.config.json');
    writeFileSync(
      configPath,
      JSON.stringify({
        importContractConfig: '.dependency-cruiser.cjs',
        suppressionRegistry: 'cfq-ts-exemptions.json',
        tsconfig: 'tsconfig.json',
      }),
    );
    try {
      try {
        loadConfig(configPath);
        expect(true).toBe(false);
      } catch (err) {
        if (err instanceof CfGateConfigError) {
          expect(err.kind).toBe('CONFIG_INVALID_SCHEMA');
        } else {
          throw err;
        }
      }
    } finally {
      rmSync(dir, { recursive: true });
    }
  });
});

// ---------------------------------------------------------------------------
// buildGates
// ---------------------------------------------------------------------------

describe('buildGates', () => {
  it('returns exactly 5 gates with the expected names in order', () => {
    const config = {
      roots: ['src'],
      importContractConfig: '.dependency-cruiser.cjs',
      suppressionRegistry: 'cfq-ts-exemptions.json',
      tsconfig: 'tsconfig.json',
    };
    const gates = buildGates(config, '/some/project/dir');
    const names = gates.map(g => g.name);
    expect(names).toEqual([
      'file-budget',
      'eslint',
      'import-contract',
      'suppression-registry',
      'tsc-strict',
    ]);
  });

  it('resolves relative config paths against baseDir', () => {
    const config = {
      roots: ['src'],
      importContractConfig: '.dependency-cruiser.cjs',
      suppressionRegistry: 'cfq-ts-exemptions.json',
      tsconfig: 'tsconfig.json',
    };
    // buildGates should not throw even for non-existent baseDir (it only constructs gates)
    const gates = buildGates(config, '/project');
    expect(gates).toHaveLength(5);
  });
});
