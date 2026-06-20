import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import type { Gate } from './types.js';
import { fileBudgetGate } from '../gates/fileBudget.js';
import { eslintGate } from '../gates/eslintGate.js';
import { importContractGate } from '../gates/importContract.js';
import { suppressionRegistryGate } from '../gates/suppressionRegistry.js';
import { tscStrictGate } from '../gates/tscStrict.js';

// ---------------------------------------------------------------------------
// Public schema
// ---------------------------------------------------------------------------

/**
 * Validated configuration for a cf-gate-ts run.
 *
 * All path fields are config-file-relative strings.  `buildGates` resolves
 * them against `baseDir` (the directory containing the config file) before
 * passing them to individual gate factories.
 */
export interface CfGateConfig {
  /** Source directories to walk (recursive, skipping node_modules / dist / __rods__). */
  roots: string[];
  /** Path to the .dependency-cruiser.cjs import-contract config. */
  importContractConfig: string;
  /** Path to the cfq-ts-exemptions.json suppression registry. */
  suppressionRegistry: string;
  /** Path to the tsconfig.json used for tsc --noEmit. */
  tsconfig: string;
  /** Optional baseline for the file-budget gate (Record<string, number> JSON). */
  fileBudgetBaseline?: string;
  /** Optional baseline for the eslint gate (Record<string, number> JSON). */
  eslintBaseline?: string;
  /** Optional baseline for the tsc-strict gate (string[] JSON). */
  tscBaseline?: string;
}

// ---------------------------------------------------------------------------
// Typed config error
// ---------------------------------------------------------------------------

/** Discriminated tag for CfGateConfigError failures. */
export type ConfigErrorKind =
  | 'CONFIG_MISSING'
  | 'CONFIG_INVALID_JSON'
  | 'CONFIG_INVALID_SCHEMA';

/**
 * Thrown by `loadConfig` when the config file is missing, unparseable, or
 * does not match the CfGateConfig schema.  Carries a machine-readable `kind`
 * for callers that need to distinguish between failure modes.
 */
export class CfGateConfigError extends Error {
  constructor(
    public readonly kind: ConfigErrorKind,
    message: string,
  ) {
    super(message);
    this.name = 'CfGateConfigError';
  }
}

// ---------------------------------------------------------------------------
// Validation helpers (keep loadConfig under CC 10 / 50 stmts)
// ---------------------------------------------------------------------------

function isStringArray(v: unknown): v is string[] {
  return Array.isArray(v) && v.every((r): r is string => typeof r === 'string');
}

function requireStringArray(
  obj: Record<string, unknown>,
  key: string,
  source: string,
): string[] {
  const val = obj[key];
  if (!isStringArray(val)) {
    throw new CfGateConfigError(
      'CONFIG_INVALID_SCHEMA',
      `Config.${key} must be a string[]: ${source}`,
    );
  }
  return val;
}

function requireString(
  obj: Record<string, unknown>,
  key: string,
  source: string,
): string {
  const val = obj[key];
  if (typeof val !== 'string') {
    throw new CfGateConfigError(
      'CONFIG_INVALID_SCHEMA',
      `Config.${key} must be a string: ${source}`,
    );
  }
  return val;
}

function optionalString(
  obj: Record<string, unknown>,
  key: string,
  source: string,
): string | undefined {
  const val = obj[key];
  if (val === undefined) return undefined;
  if (typeof val !== 'string') {
    throw new CfGateConfigError(
      'CONFIG_INVALID_SCHEMA',
      `Config.${key} must be a string: ${source}`,
    );
  }
  return val;
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Load and validate a CfGateConfig from a JSON file on disk.
 *
 * @throws {CfGateConfigError} with kind:
 *   - `CONFIG_MISSING`        — file not found or unreadable
 *   - `CONFIG_INVALID_JSON`   — file is not valid JSON
 *   - `CONFIG_INVALID_SCHEMA` — JSON does not match CfGateConfig schema
 */
export function loadConfig(path: string): CfGateConfig {
  let raw: string;
  try {
    raw = readFileSync(path, 'utf8');
  } catch {
    throw new CfGateConfigError('CONFIG_MISSING', `Config file not found: ${path}`);
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw new CfGateConfigError('CONFIG_INVALID_JSON', `Config file is not valid JSON: ${path}`);
  }

  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    throw new CfGateConfigError(
      'CONFIG_INVALID_SCHEMA',
      `Config must be a JSON object: ${path}`,
    );
  }

  const obj = parsed as Record<string, unknown>;

  return {
    roots: requireStringArray(obj, 'roots', path),
    importContractConfig: requireString(obj, 'importContractConfig', path),
    suppressionRegistry: requireString(obj, 'suppressionRegistry', path),
    tsconfig: requireString(obj, 'tsconfig', path),
    fileBudgetBaseline: optionalString(obj, 'fileBudgetBaseline', path),
    eslintBaseline: optionalString(obj, 'eslintBaseline', path),
    tscBaseline: optionalString(obj, 'tscBaseline', path),
  };
}

/**
 * Resolve a config-relative path against `baseDir`.
 * Absolute paths are returned unchanged.
 */
function resolveRel(p: string, baseDir: string): string {
  return resolve(baseDir, p);
}

/**
 * Construct the five gate instances from a validated config.
 *
 * All relative paths in `config` are resolved against `baseDir` (the directory
 * that contained the config file).  Gate order is deterministic:
 * `file-budget` → `eslint` → `import-contract` → `suppression-registry` → `tsc-strict`.
 */
export function buildGates(config: CfGateConfig, baseDir: string): Gate[] {
  const roots = config.roots.map(r => resolveRel(r, baseDir));

  return [
    fileBudgetGate({
      roots,
      baseline: config.fileBudgetBaseline !== undefined
        ? resolveRel(config.fileBudgetBaseline, baseDir)
        : undefined,
    }),
    eslintGate({
      roots,
      baseline: config.eslintBaseline !== undefined
        ? resolveRel(config.eslintBaseline, baseDir)
        : undefined,
    }),
    importContractGate({
      config: resolveRel(config.importContractConfig, baseDir),
      roots,
    }),
    suppressionRegistryGate({
      roots,
      registry: resolveRel(config.suppressionRegistry, baseDir),
    }),
    tscStrictGate({
      project: resolveRel(config.tsconfig, baseDir),
      baseline: config.tscBaseline !== undefined
        ? resolveRel(config.tscBaseline, baseDir)
        : undefined,
    }),
  ];
}
