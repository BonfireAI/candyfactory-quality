import type { Gate, GateResult } from './types.js';

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
  // KT7 wires the real gate set here; for now the runner is empty-but-green.
  const gates: Gate[] = [];
  const results = await runCfGateTs(gates);
  console.log(digest(results)); // eslint-disable-line no-console -- the runner's job is to report to the operator
  if (results.some((r) => !r.ok)) process.exit(1);
}

// Run only as entrypoint, never on import by tests or other modules.
if (import.meta.url === `file://${process.argv[1]}`) {
  void main();
}
