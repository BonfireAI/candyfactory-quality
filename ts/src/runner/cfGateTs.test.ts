import { describe, it, expect } from 'vitest';
import { runCfGateTs } from './cfGateTs.js';

describe('cf-gate-ts runner', () => {
  it('aggregates gate results and surfaces a failing gate', async () => {
    const res = await runCfGateTs([
      { name: 'a', run: async () => ({ gate: 'a', ok: true, problems: [] }) },
      { name: 'b', run: async () => ({ gate: 'b', ok: false, problems: ['x'] }) },
    ]);
    expect(res).toHaveLength(2);
    expect(res.find((r) => r.gate === 'b')?.ok).toBe(false);
    expect(res.find((r) => r.gate === 'a')?.ok).toBe(true);
  });
});
