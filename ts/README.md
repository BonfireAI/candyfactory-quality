# cf-gate-ts — BubbleGum quality kit for TypeScript

`cf-gate-ts` is CandyFactory's TypeScript quality gate runner. It enforces the
BubbleGum Law (SOLID · DRY · KISS) across a TypeScript project by running five
gates in sequence and exiting non-zero if any gate fails:

| Gate                  | What it checks                                                  |
|-----------------------|-----------------------------------------------------------------|
| `file-budget`         | No source file exceeds 500 lines (SOLID SRP)                   |
| `eslint`              | CC ≤ 10 per function; ≤ 50 statements; no silent empty catch   |
| `import-contract`     | No import cycles; core never imports adapters/packs/tenants     |
| `suppression-registry`| Every `@ts-ignore` / `eslint-disable` is registered + reasoned |
| `tsc-strict`          | Zero TypeScript errors under `strict` + `noUncheckedIndexedAccess` |

Pre-existing offenders are frozen in a baseline (ratchet: shrink-only, never grow).

## 4-step consumer mount

These are exactly the steps SweetCRM Task 1 (BON-1701) follows when mounting
the kit into a new TypeScript repository.

### Step 1 — Copy the consumer templates

```sh
cp -r node_modules/@candyfactory/cf-gate-ts/templates/consumer/. .
# or, from a local checkout of candyfactory-quality:
cp -r path/to/candyfactory-quality/ts/templates/consumer/. .
```

This drops four files into the target repo root:

- `cfq-ts.config.json` — gate configuration (edit next)
- `.dependency-cruiser.cjs` — import-contract rules (add your layer rules)
- `eslint.config.mjs` — BubbleGum eslint rules (extend if needed)
- `tsconfig.json` — strict TypeScript base (merge with your existing config)
- `BUBBLEGUM-STICKY.md` — the BubbleGum Law (carry it; it sticks)

### Step 2 — Configure source roots and import contract

Edit `cfq-ts.config.json` to name your source roots and point at the supporting
files you just copied:

```json
{
  "roots": ["src"],
  "importContractConfig": ".dependency-cruiser.cjs",
  "suppressionRegistry": "cfq-ts-exemptions.json",
  "tsconfig": "tsconfig.json"
}
```

Then edit `.dependency-cruiser.cjs` to add your project's layer rules
(e.g. `core` must not import `adapters`).  The template ships with the
standard no-circular + core-not-to-adapters rules as a starting point.

### Step 3 — Freeze pre-existing debt with a baseline

Run the gate in baseline mode to freeze any pre-existing offenders as
shrink-only ratchets:

```sh
npx tsx node_modules/@candyfactory/cf-gate-ts/src/runner/cfGateTs.ts --baseline
```

Or, if you've wired the npm script (see Step 4):

```sh
npm run cf-gate-ts -- --baseline
```

This writes (or updates) the baseline files referenced in `cfq-ts.config.json`.
Offenders captured here can only shrink — any regression causes the gate to
fail immediately.

### Step 4 — Wire into CI and npm scripts

Add the gate to your `package.json` so local runs are identical to CI:

```json
{
  "scripts": {
    "test": "vitest run && npm run cf-gate-ts",
    "cf-gate-ts": "tsx node_modules/@candyfactory/cf-gate-ts/src/runner/cfGateTs.ts"
  }
}
```

In CI (GitHub Actions, Vercel build, etc.) run the same `npm test` — no
separate gate step needed. The gate exits non-zero on any failure, blocking
the build, and prints the full problem list to stderr so the operator sees
exactly what failed.

## Self-run (kit authors)

From inside `candyfactory-quality/ts/`:

```sh
npm run cf-gate-ts   # runs the kit against its own source
npm test             # runs vitest (unit tests for all gates)
npm run typecheck    # tsc --noEmit
```

The kit passes its own gates by design (ADR 0030 §10: ratchets first).
