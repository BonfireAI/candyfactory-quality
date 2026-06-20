import { resolve, dirname } from 'node:path';
import type { Gate, GateResult } from './types.js';
import { loadConfig, buildGates, CfGateConfigError } from './config.js';

/**
 * Runs each gate in sequence and returns all results.
 * Gates are run serially so output ordering is deterministic.
 */
export async function runCfGateTs(gates: Gate[]): Promise<GateResult[]> {
  const results: GateResult[] = [];
  for (const gate of gates) {
    results.push(await gate.run());
  }
  return results;
}

/**
 * Formats a list of gate results into a one-line-per-gate digest string.
 * PASS lines are plain; FAIL lines include the problem count.
 */
export function digest(results: GateResult[]): string {
  return results
    .map((r) => `${r.ok ? 'PASS' : 'FAIL'} ${r.gate}${r.ok ? '' : ` (${r.problems.length})`}`)
    .join('\n');
}

async function main(): Promise<void> {
  const configArg = process.argv[2] ?? 'cfq-ts.config.json';
  const configPath = resolve(configArg);

  let gates: Gate[];
  try {
    const config = loadConfig(configPath);
    gates = buildGates(config, dirname(configPath));
  } catch (err) {
    const msg = err instanceof CfGateConfigError
      ? `cf-gate-ts: ${err.kind}: ${err.message}`
      : `cf-gate-ts: unexpected error loading config: ${String(err)}`;
    console.error(msg);
    // process.exit returns never; the return satisfies no-untyped-catch.
    return process.exit(1);
  }

  const results = await runCfGateTs(gates);
  console.log(digest(results));
  if (results.some((r) => !r.ok)) process.exit(1);
}

// Run only as entrypoint, never on import by tests or other modules.
if (import.meta.url === `file://${process.argv[1]}`) {
  void main();
}
