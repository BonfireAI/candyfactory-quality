/** Result produced by a single gate run. */
export interface GateResult {
  gate: string;
  ok: boolean;
  problems: string[];
}

/** A named gate with an async run function that returns a GateResult. */
export type Gate = {
  name: string;
  run: () => Promise<GateResult>;
};
