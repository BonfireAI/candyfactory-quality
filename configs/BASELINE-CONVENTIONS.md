# Baseline conventions — mounting the ratchet on a consumer repo

How a repo boots green-by-construction on day one and then only ever shrinks.
Every workflow below is the **observed** behavior of the pinned tools
(complexipy 5.5.0 · mypy-baseline 0.7.4), measured in `docs/tool-spikes.md` —
not read off a README. Every baseline carries a dated ratchet ticket so
green-by-baseline cannot become green-forever (the Law-1 refuter's expiry fix).

## The shared configs in this directory

| File | Role |
|---|---|
| `ruff-base.toml` | The ruff gauge (ruff.toml format). **Vendored** into each consumer repo; drift caught by a `ruff-sync check` CI step. The only locally-extendable section — and the only dotted path allowed in `[tool.ruff-sync].exclude` — is `lint.per-file-ignores` (anything wider is the refuter's unbounded escape hatch). |
| `mypy-base.toml` | The mypy gauge (strict-leaning). Grace is per-module via `[[tool.mypy.overrides]]` with a reason comment, never a global loosening. |
| `jscpd.src.json` / `jscpd.tests.json` | The clone-tripwire two-profile carve-out: src at `minTokens` 35, tests at 70. **Two files by necessity** — one `.jscpd.json` cannot carry two `minTokens` values (refuter-confirmed, Law 4 fix #4), so CI runs jscpd twice, once per profile. |

## 1. complexipy — the cognitive-complexity watermark (snapshot ratchet)

complexipy measures **cognitive** complexity (a second metric beside ruff's
C901 cyclomatic — the two cover each other's blind spots).

**Boot (day one, run from the repo root):**

```bash
cd <repo-root>            # the snapshot lands in CWD, NOT the analyzed path
complexipy src --snapshot-create
git add complexipy-snapshot.json   # commit the watermark + open a dated shrink ticket
```

Exit 0 even when offenders exist — baseline boot is green by construction.
The snapshot records only functions over the threshold; an all-clean tree
writes a literal `[]`.

**Gate (every CI run, from the repo root):**

```bash
complexipy src            # plain run auto-compares when the snapshot exists
```

Fails (exit 1) on any NEW offender, or any baselined offender rising above its
watermark. A function at-or-below its watermark passes.

**Observed gotchas the mount must respect:**

- The snapshot **does NOT auto-shrink**. After an improvement the plain run
  passes but the file still holds the old watermark — a later regression back
  up to the stale watermark would pass. The kit owns the re-baseline step:
  re-run `--snapshot-create` on merge (or in the shrink ticket) to lock
  improvements in.
- Run from the **repo root** so the committed snapshot is the one compared
  (snapshot path is CWD-relative).
- Never pipe the gate command (`complexipy … | tail` masks the exit code);
  gate on the command's own status, or set `pipefail`.

## 2. mypy-baseline — the 0-new-type-errors gate (multiset set-difference)

**Boot (day one) — MANDATORY for any repo containing Python.** The gate
REFUSES a Python repo with no `mypy-baseline.txt` (the 2026-06-10 refuter
showed the old presence-conditioned skip made "0 new type errors" opt-in);
a zero-error repo boots an empty baseline the same way.

```bash
mypy src --config-file mypy-base.toml | python -m cf_quality.mypy_normalize | mypy-baseline sync
git add mypy-baseline.txt          # commit the frozen debt + a dated shrink ticket
```

The baseline normalizes line numbers to `:0`, so unrelated line drift cannot
resurrect or duplicate findings.

**Gate (every CI run):**

```bash
mypy src --config-file mypy-base.toml | python -m cf_quality.mypy_normalize | mypy-baseline filter
```

### `cf_quality.mypy_normalize` — the env-independence filter (the deterministic-verdict fix)

Without it the baseline encodes the **environment**, not the code, and produces
phantom new/fixed deltas (the bug that cost a sister repo four blind CI rounds).
`cf-gate` applies the SAME transform in-process between mypy and mypy-baseline;
the manual boot/gate commands above pipe through `python -m
cf_quality.mypy_normalize` so a hand-synced baseline matches what the gate
filters against. It is a pure stdin→stdout text pass that:

- **canonicalizes missing third-party imports.** A missing import reads as
  `Library stubs not installed for "M"` / `Skipping analyzing "M": …`
  (`[import-untyped]`) when the package is installed-without-stubs, but
  `Cannot find implementation or library stub for module named "M"`
  (`[import-not-found]`) when it is absent — same code, different baseline line
  per machine. All three collapse onto ONE canonical `import-untyped` line keyed
  by `M`, so the baseline multiset is identical either way.
- **strips the once-per-run global stub notes.** mypy emits the
  `(or run "mypy --install-types" …)` note, the `…#missing-imports` See note, and
  the per-package `Hint: "… pip install …-stubs"` note ONCE per run, anchored to
  the first missing-import site — so they relocate between files as the import
  landscape shifts. Dropping them keeps them out of the baseline entirely.
- **leaves everything else byte-identical.** Real type errors and all other
  diagnostics pass through verbatim; the filter never drops an error line, so no
  real finding is masked.

Observed semantics (the reason no bespoke wrapper is needed):

- **Multiset matching, never counts.** A fix-one-add-one swap (count
  laundering) is caught; even a byte-identical duplicate of a baselined error
  in the same file is flagged as new.
- **The baseline cannot rot silently.** Fixed-only also exits nonzero with an
  instruction to re-`sync` — every shrink is committed, so the ratchet
  direction is enforced by the tool itself (unlike complexipy, which needs the
  kit's re-snapshot step above).
- Exit codes observed: `0` clean · `1` when only one of {new, fixed} present ·
  `2` when both. **Gate on nonzero**, never on a specific value.

## 3. file budget — `cf-file-budget`

```bash
cf-file-budget init       # freeze existing >500-line files at measured size
```

New files ≤ 500 lines; baselined offenders are frozen shrink-only in
`file-budget.json` (see the kit README for the full gate battery).
