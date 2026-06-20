# BubbleGum-for-TS Quality Kit — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Port the ratified BubbleGum gating core (ADR 0029/0030) to TypeScript as a reusable `ts/` package inside `candyfactory-quality`, so every TS mine (SweetCRM first, CMS next) is lawful from commit 1 via one aggregating `cf-gate-ts` runner with `local == CI`.

**Architecture:** This is a **port of an already-ratified mechanism**, not a new design — ADR 0030 already decided which gates exist, their budgets, and the doctrine (ratchet not world-refactor; every gate ships a control rod; the kit ratchets first). We translate each gate to its faithful TS analog: dependency-cruiser for layering/cycles (DIP/SoC), eslint for form (SRP/KISS/fail-fast/suppression), `tsc --strict` for substitutability (LSP). A single `cf-gate-ts` runner aggregates them and reads a shrink-only baseline.

**Tech Stack:** TypeScript, eslint (flat config), dependency-cruiser, vitest. Node ≥ 20.

## Global Constraints

- **Port fidelity:** budgets copied verbatim from ADR 0030 §8 — new files ≤ 500 lines; CC ≤ 10; ≤ 50 statements/function; `tsc --strict` + `noImplicitOverride`; empty/swallowing catch = 0; every suppression registry-gated.
- **Every gate ships a control rod** — a committed fixture that MUST fail; a gate without one does not ship (ADR 0030 §10).
- **Ratchet, never world-refactor** — gates read a baseline of pre-existing offenders, shrink-only; new code complies fully.
- **The kit ratchets first** — KT8 runs the kit against its own source and baselines/fixes rather than exempting.
- **local == CI** — the same `cf-gate-ts` entrypoint runs locally and in CI; no divergent logic.
- **Reusable infra** — nothing in this package may import or assume SweetCRM; it is mounted by consumers.

---

### Task KT1: Scaffold the `ts/` package + the `cf-gate-ts` runner skeleton

**Files:**
- Create: `ts/package.json`, `ts/tsconfig.json`, `ts/eslint.config.mjs`, `ts/.dependency-cruiser.cjs`
- Create: `ts/src/runner/cfGateTs.ts` (the aggregator), `ts/src/runner/types.ts`
- Test: `ts/src/runner/cfGateTs.test.ts`

**Interfaces:**
- Produces: `interface GateResult { gate: string; ok: boolean; problems: string[] }`; `runCfGateTs(gates: Gate[]): GateResult[]`; `type Gate = { name: string; run: () => Promise<GateResult> }`.

- [ ] **Step 1:** Write `ts/package.json` with scripts `{ "cf-gate-ts": "tsx src/runner/cfGateTs.ts", "test": "vitest run" }` and devDeps: `typescript`, `tsx`, `eslint`, `@typescript-eslint/*`, `dependency-cruiser`, `vitest`. Run `npm install`.
- [ ] **Step 2:** Write `tsconfig.json` with `strict: true`, `noImplicitOverride: true`, `noUncheckedIndexedAccess: true` (this file is also the LSP-gate template consumers extend).
- [ ] **Step 3:** Write the failing test:
```ts
import { describe, it, expect } from 'vitest';
import { runCfGateTs } from './cfGateTs';
describe('cf-gate-ts runner', () => {
  it('aggregates gate results and fails if any gate fails', async () => {
    const res = await runCfGateTs([
      { name: 'a', run: async () => ({ gate: 'a', ok: true, problems: [] }) },
      { name: 'b', run: async () => ({ gate: 'b', ok: false, problems: ['x'] }) },
    ]);
    expect(res.find(r => r.gate === 'b')!.ok).toBe(false);
  });
});
```
- [ ] **Step 4:** Run `npx vitest run ts/src/runner/cfGateTs.test.ts` → FAIL (module missing).
- [ ] **Step 5:** Implement `types.ts` + `cfGateTs.ts` (`runCfGateTs` runs each gate, collects results; a `main()` exits non-zero if any `ok===false` and prints a digest). Run test → PASS.
- [ ] **Step 6:** Commit: `feat(ts-kit): scaffold cf-gate-ts package + aggregating runner`.

---

### Task KT2: SRP gate — file budget (≤ 500 lines) + baseline + rod

**Files:**
- Create: `ts/src/gates/fileBudget.ts`, `ts/src/baseline/baseline.ts` (shared shrink-only baseline reader/writer)
- Create: `ts/src/gates/__rods__/oversized.fixture.ts` (501+ lines — MUST fail)
- Test: `ts/src/gates/fileBudget.test.ts`

**Interfaces:**
- Consumes: `GateResult`.
- Produces: `fileBudgetGate(opts: { roots: string[]; max?: number; baseline?: string }): Gate`; `loadBaseline(path): Set<string>`; `isShrinkOnly(current, baseline): string[]`.

- [ ] **Step 1:** Write failing test: a file > 500 logical lines not in the baseline → one problem; the same file IN the baseline → no problem (shrink-only); a NEW file > 500 → always a problem.
- [ ] **Step 2:** Run test → FAIL.
- [ ] **Step 3:** Implement `fileBudgetGate` (count max of physical lines and logical statements per ADR 0030 §3.3) + `baseline.ts`. Add the `oversized.fixture.ts` rod.
- [ ] **Step 4:** Run test → PASS (incl. the rod proving a fresh oversized file fails).
- [ ] **Step 5:** Commit: `feat(ts-kit): cf-file-budget gate (SRP) + shrink-only baseline + rod`.

---

### Task KT3: KISS gate — complexity / statements / function-length (eslint)

**Files:**
- Modify: `ts/eslint.config.mjs` (add `complexity: ['error', 10]`, `max-statements: ['error', 50]`, `max-lines-per-function`, `max-lines: ['error', 500]`)
- Create: `ts/src/gates/eslintGate.ts` (runs eslint programmatically, parses results, applies baseline)
- Create: `ts/src/gates/__rods__/tooComplex.fixture.ts` (a CC-12 function — MUST fail)
- Test: `ts/src/gates/eslintGate.test.ts`

**Interfaces:**
- Produces: `eslintGate(opts: { roots: string[]; baseline?: string }): Gate` (wraps the eslint flat config; the SRP `max-lines` also surfaces here — single eslint pass).

- [ ] **Step 1:** Write failing test: the `tooComplex.fixture.ts` rod yields a `complexity` violation; a simple function yields none; a baselined offender is suppressed.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Configure eslint flat config + implement `eslintGate` using the eslint Node API (`ESLint.lintFiles`), map results → `GateResult`, intersect with baseline.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit: `feat(ts-kit): KISS gate via eslint complexity/statements + rod`.

---

### Task KT4: DIP/SoC gate — import contract + cycles (dependency-cruiser)

**Files:**
- Modify: `ts/.dependency-cruiser.cjs` (forbidden rules: `core` ↛ `adapters|packs|tenants`; `no-circular`; `no-orphans` off)
- Create: `ts/src/gates/importContract.ts` (runs depcruise, parses JSON output → `GateResult`)
- Create: `ts/src/gates/__rods__/upwardImport.fixture/` (a `core` file importing an `adapters` file — MUST fail)
- Test: `ts/src/gates/importContract.test.ts`

**Interfaces:**
- Produces: `importContractGate(opts: { config: string; roots: string[] }): Gate`; failure taxonomy `CONTRACT_MISSING | CONTRACT_BROKEN | CONTRACT_CONFIG_ERROR` (ADR 0030 §3.1 — the gate itself speaks typed failures).

- [ ] **Step 1:** Write failing test: the upward-import rod → `CONTRACT_BROKEN` naming the edge; a clean tree → ok; a tree with no contract → `CONTRACT_MISSING`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Author the depcruise config (layering + `no-circular`) + implement `importContractGate` parsing depcruise `--output-type json` (never exit-code-only). Add the rod fixture.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit: `feat(ts-kit): DIP import-contract + SoC cycle gate (dependency-cruiser) + rod`.

---

### Task KT5: Fail-fast / Elegance gate — no swallowed catches

**Files:**
- Create: `ts/src/gates/eslint-rules/no-untyped-catch.mjs` (custom eslint rule: a `catch` must rethrow or produce a typed error; empty/`console`-only catch fails)
- Modify: `ts/eslint.config.mjs` (enable `no-empty` for catch + the custom rule)
- Create: `ts/src/gates/__rods__/swallowedCatch.fixture.ts` (`try{}catch(e){}` — MUST fail)
- Test: `ts/src/gates/eslint-rules/no-untyped-catch.test.ts`

**Interfaces:**
- Produces: the `no-untyped-catch` rule registered in the flat config; surfaced through `eslintGate` (KT3) — no separate runner.

- [ ] **Step 1:** Write failing rule test (eslint `RuleTester`): empty catch → error; catch that `throw`s a typed error → ok.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement the rule + wire into the flat config; add the rod fixture.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit: `feat(ts-kit): fail-fast gate (no swallowed catch) + custom rule + rod`.

---

### Task KT6: Suppression registry gate (eslint-disable / @ts-ignore / @ts-expect-error)

**Files:**
- Create: `ts/src/gates/suppressionRegistry.ts` (scan for suppression directives; each must be in `cfq-ts-exemptions.json` with a reason + blessing)
- Create: `ts/cfq-ts-exemptions.json` (the registry, seeded empty)
- Create: `ts/src/gates/__rods__/unregisteredIgnore.fixture.ts` (a bare `@ts-ignore` — MUST fail)
- Test: `ts/src/gates/suppressionRegistry.test.ts`

**Interfaces:**
- Produces: `suppressionRegistryGate(opts: { roots: string[]; registry: string }): Gate`; `UNREGISTERED_SUPPRESSION` problem code (mirrors the Python noqa/nosec/`type:ignore` family, ADR 0030 §3.2).

- [ ] **Step 1:** Write failing test: an unregistered `@ts-ignore` → `UNREGISTERED_SUPPRESSION`; a registered one (with reason) → ok; multi-code `// eslint-disable-line a, b` both checked.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement the scan + registry schema (`{ file, line, directive, reason, blessedBy }`) + the rod.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit: `feat(ts-kit): suppression registry gate + rod`.

---

### Task KT7: Wire all gates into `cf-gate-ts` + the LSP/tsc gate + consumer template

**Files:**
- Modify: `ts/src/runner/cfGateTs.ts` (compose fileBudget + eslint + importContract + suppressionRegistry + tsc)
- Create: `ts/src/gates/tscStrict.ts` (run `tsc --noEmit` against the consumer tsconfig; new type error = fail)
- Create: `ts/templates/consumer/` (the `tsconfig`, `eslint.config.mjs`, `.dependency-cruiser.cjs`, and the BubbleGum sticky a mine mounts)
- Test: `ts/src/gates/tscStrict.test.ts`

**Interfaces:**
- Consumes: all gate factories.
- Produces: a `cf-gate-ts` CLI that takes a config naming roots + baselines + the contract file, runs every gate, prints the aggregated digest, exits non-zero on any failure; `tscStrictGate(opts): Gate`.

- [ ] **Step 1:** Write failing test for `tscStrictGate`: a file with an LSP/override violation → fail; clean → ok.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement `tscStrictGate` + compose all six gates in the runner; write the consumer template files (what SweetCRM mounts).
- [ ] **Step 4:** Run `npm run cf-gate-ts` on a tiny clean fixture project → all gates green; on a dirty one → aggregated failures.
- [ ] **Step 5:** Commit: `feat(ts-kit): compose cf-gate-ts (all gates) + LSP tsc gate + consumer template`.

---

### Task KT8: The kit ratchets first (self-run) + docs

**Files:**
- Create: `ts/cfq-ts-baseline.json` (the kit's own measured baseline — must be near-empty; fix rather than baseline where cheap)
- Create: `ts/README.md` (how a mine mounts the kit), `docs/superpowers/specs/` pointer
- Modify: repo `README.md` / `DESIGN.md` (note the TS twin of the kit)

- [ ] **Step 1:** Run `npm run cf-gate-ts` against `ts/src/**` itself.
- [ ] **Step 2:** For each finding: FIX it if cheap; only baseline genuine pre-existing debt (the kit submits before it preaches — ADR 0030 §10).
- [ ] **Step 3:** Re-run → green. Commit the (near-empty) baseline.
- [ ] **Step 4:** Write `ts/README.md`: the 4-step mount (copy templates → name roots/contract → run `cf-gate-ts` → freeze baseline) — this is exactly what SweetCRM Task 1 follows.
- [ ] **Step 5:** Commit: `feat(ts-kit): self-ratchet green + mount docs (kit ratchets first)`.

---

## Self-Review

**Spec coverage (vs ADR 0030 live gates):** SRP/file-budget → KT2 ✓ · KISS → KT3 ✓ · DIP import-contract + SoC cycles → KT4 ✓ · fail-fast/Elegance → KT5 ✓ · LSP/tsc + suppression registry → KT6/KT7 ✓ · aggregating runner (local==CI) → KT1/KT7 ✓ · control rods per gate → every KT ✓ · kit-ratchets-first → KT8 ✓. Census bench (DRY/jscpd, dispatch, Demeter, etc.) is **deliberately out of this plan** — non-gating per ADR 0030 §4, follows as a census slice (logged here so the cap is not silent).

**Placeholder scan:** none — each task names exact files, the tool, the rod fixture, and the commit.

**Type consistency:** `Gate`, `GateResult`, `runCfGateTs`, `loadBaseline`, the gate factories (`fileBudgetGate`/`eslintGate`/`importContractGate`/`suppressionRegistryGate`/`tscStrictGate`) are defined in KT1–KT7 and composed once in KT7.

**Scope note:** this is the **gating core** only. The census bench is a follow-slice. The kit is consumed by SweetCRM Task 1 (baseline the mined Atomic CRM) — that step lives in the SweetCRM epic, not here.
