import { createRequire } from 'node:module';
import { resolve, dirname } from 'node:path';
import { cruise } from 'dependency-cruiser';
import type {
  IConfiguration,
  IFlattenedRuleSet,
  ICruiseOptions,
} from 'dependency-cruiser';
import type { Gate, GateResult } from '../runner/types.js';

/** Typed outcome tag for each failure mode (Elegance Law). */
export type ContractFailure =
  | 'CONTRACT_MISSING'
  | 'CONTRACT_BROKEN'
  | 'CONTRACT_CONFIG_ERROR';

/** Options for the import-contract gate. */
export interface ImportContractOpts {
  /** Absolute or cwd-relative path to the .dependency-cruiser.cjs config. */
  config: string;
  /** Directories or files to cruise. */
  roots: string[];
}

const GATE_NAME = 'import-contract' as const;

/**
 * require() helper bound to this module's location.
 * Used to load CJS config files from absolute paths without introducing `any`.
 */
const _require = createRequire(import.meta.url);

/**
 * Build the ruleSet object from the fields present on a loaded IConfiguration.
 * Only populates keys that exist so the ruleSet stays minimal and type-clean.
 */
function buildRuleSet(config: IConfiguration): IFlattenedRuleSet {
  const ruleSet: IFlattenedRuleSet = {};
  if (config.forbidden !== undefined) ruleSet.forbidden = config.forbidden;
  if (config.allowed !== undefined) ruleSet.allowed = config.allowed;
  if (config.required !== undefined) ruleSet.required = config.required;
  if (config.allowedSeverity !== undefined) ruleSet.allowedSeverity = config.allowedSeverity;
  return ruleSet;
}

/**
 * Run dependency-cruiser with the given config and roots, returning problem
 * strings for each error-severity violation found.
 *
 * Throws on cruise failure (caught by the caller's try/catch so that all
 * failure paths produce a typed CONTRACT_CONFIG_ERROR problem string).
 * Throws also when cruise returns string output, which indicates a mis-use
 * of the programmatic API (an outputType was set unexpectedly).
 */
async function cruiseViolations(
  config: IConfiguration,
  configDir: string,
  roots: string[],
): Promise<string[]> {
  const ruleSet = buildRuleSet(config);
  const cruiseOptions: ICruiseOptions = {
    ...(config.options ?? {}),
    validate: true,
    ruleSet,
  };

  // Make tsConfig.fileName absolute relative to the config file's own
  // directory so cruise finds tsconfig.json regardless of process.cwd()
  // (which is not guaranteed to be `ts/` inside a vitest worker).
  if (cruiseOptions.tsConfig !== undefined) {
    const existingFileName = cruiseOptions.tsConfig.fileName ?? 'tsconfig.json';
    cruiseOptions.tsConfig = {
      ...cruiseOptions.tsConfig,
      fileName: resolve(configDir, existingFileName),
    };
  }

  const { output } = await cruise(roots, cruiseOptions);

  if (typeof output === 'string') {
    // Programmatic API should never return a string without an explicit
    // outputType; treat it as a config error rather than silently passing.
    throw new Error(
      'dependency-cruiser returned string output; ' +
        'pass no outputType when using the programmatic API',
    );
  }

  const violations = output.summary.violations.filter(
    (v) => v.rule.severity === 'error',
  );

  return violations.map(
    (v) => `CONTRACT_BROKEN: ${v.rule.name} ${v.from} -> ${v.to}`,
  );
}

/**
 * Gate that enforces the project's import contract: layering direction (core
 * never imports adapters/packs/tenants) and no import cycles.
 *
 * Three typed outcomes (ContractFailure):
 * - CONTRACT_CONFIG_ERROR — config file missing, unparseable, or cruise threw
 * - CONTRACT_MISSING      — config loaded but declares no forbidden rules
 * - CONTRACT_BROKEN       — cruise found error-severity violations
 *
 * No exceptions are swallowed: every catch produces a typed problem string.
 *
 * @example
 * ```ts
 * const gate = importContractGate({
 *   config: '.dependency-cruiser.cjs',
 *   roots: ['src'],
 * });
 * const result = await gate.run();
 * ```
 */
export function importContractGate(opts: ImportContractOpts): Gate {
  return {
    name: GATE_NAME,
    run: async (): Promise<GateResult> => {
      // ── 1. Load the ruleset config ──────────────────────────────────────
      // Resolve the config path up-front so configDir is available for
      // making tsConfig.fileName absolute in cruiseViolations. resolve()
      // never throws — only _require() throws if the file is absent or
      // unparseable.
      const absoluteConfig = resolve(opts.config);
      const configDir = dirname(absoluteConfig);

      let config: IConfiguration;
      try {
        config = _require(absoluteConfig) as IConfiguration;
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        return {
          gate: GATE_NAME,
          ok: false,
          problems: [`CONTRACT_CONFIG_ERROR: could not load config "${opts.config}": ${msg}`],
        };
      }

      // ── 2. Guard: a config with no forbidden rules is the empty-room lie ─
      if (!Array.isArray(config.forbidden) || config.forbidden.length === 0) {
        return {
          gate: GATE_NAME,
          ok: false,
          problems: [
            `CONTRACT_MISSING: config "${opts.config}" declares no forbidden rules`,
          ],
        };
      }

      // ── 3. Run dependency-cruiser and collect error-severity violations ──
      try {
        const problems = await cruiseViolations(config, configDir, opts.roots);
        return {
          gate: GATE_NAME,
          ok: problems.length === 0,
          problems,
        };
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        return {
          gate: GATE_NAME,
          ok: false,
          problems: [`CONTRACT_CONFIG_ERROR: cruise failed: ${msg}`],
        };
      }
    },
  };
}
