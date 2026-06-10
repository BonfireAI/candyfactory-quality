# candyfactory-quality — the gauge kit

The single shared quality gate for every CandyFactory repository. This kit is the
executable half of **the BubbleGum Law** — *code keeps a measured shape, and the law
that keeps it travels sticky*. Convention comes from the factory's gauge, not from
whatever package the first agent downloaded.

## The two surfaces

1. **The sticky intro** (cognitive surface) — `data/sticky-intro.md` is the canonical
   short introduction to the law that the kit mounts into every consumer repo. Any
   model that scans a repo ingests the law as it reads. Outside an enforcement
   perimeter it acts as the strongest suggestion in the file; that is its job.
   The copy here is a **declared mirror** of canon ADR 0029
   (see `data/sticky-intro.SOURCE.md` for provenance and content hash).
2. **The gate** (mechanical surface) — inside CandyFactory CI and inside Bonfire
   burns, the law is executable and refusing. Prose teaches; it never substitutes
   for the gate.

## The gate battery (console scripts)

| Command | What it gates |
|---|---|
| `cf-file-budget` | New files ≤ 500 lines; baselined offenders frozen shrink-only in `file-budget.json`. |
| `cf-sticky-check` | The repo carries the canonical sticky intro, byte-faithful to this kit's mirror. |
| `cf-mirror-check` | Cross-repo copies are declared mirrors (`MIRRORS.md`); undeclared drift fails. |
| `cf-recursion-check` | Recursion is declared with a stated bound, or it fails. |
| `cf-exemptions` | Gated suppressions — `# noqa: C901`/`PLR0915` (form), `# noqa: S###`/`# nosec B###` (security), `# noqa: BLE###` (Elegance) — trace to a reasoned entry in `exemptions.json`; bare/blanket and self-issued suppressions fail. Style codes (E/F/I/UP/B) ride on ruff + review. |

Budgets are anchored to measurement, never invented: CC ≤ 10 per function,
≤ 50 statements per function, new files ≤ 500 lines, 0 new type errors. Existing
code is baselined and may only shrink (ratchet — never a world-refactor).

The kit wears its own budgets: its ruff/mypy config enforces on this repo exactly
what the gate enforces on consumers, and failures speak typed errors
(`cf_quality.errors.GateError` / `GateViolation`) per the Elegance Law.

## Consumer quickstart

```bash
pip install candyfactory-quality  # or: pip install -e ../candyfactory-quality
```

Mount the gate in CI with the ~10-line caller stub (generated, never hand-edited):

```yaml
# .github/workflows/quality.yml
name: quality-gate
on:
  push: {branches: [main]}
  pull_request: {branches: [main]}
jobs:
  gate:
    uses: BonfireAI/candyfactory-quality/.github/workflows/quality-gate.yml@<full-commit-SHA>
    secrets: inherit
```

Day-one baseline generation (first run lands green by construction; every baseline
carries a dated ratchet ticket so green-by-baseline cannot become green-forever):

```bash
cf-file-budget init        # freeze existing >500-line files at measured size
mypy src | mypy-baseline sync
complexipy src             # cognitive-complexity snapshot (second metric)
```

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
.venv/bin/ruff check .
.venv/bin/mypy src
```

Tool-behavior spikes (complexipy snapshot semantics, mypy-baseline set-difference)
are documented in `docs/tool-spikes.md`.
