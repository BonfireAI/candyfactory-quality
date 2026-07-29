# Baseline conventions — mounting the ratchet on a consumer repo

How a repo boots green-by-construction on day one and then only ever shrinks.
Every workflow below is the **observed** behavior of the pinned tools, measured
in `docs/tool-spikes.md` — not read off a README. Version provenance, stated
because a stale label is exactly how a false claim survives here: the spike was
run on **complexipy 5.5.0 · mypy-baseline 0.7.4**; mypy-baseline is still pinned
at 0.7.4, but complexipy is now pinned at **5.6.0** and only its
snapshot-**write** semantics have been re-measured there (2026-07-28 — the first
complexipy gotcha below). Every baseline carries a dated ratchet ticket so
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

**Gate (every CI run, from the repo root) — `cf-gate`, never the tool's own
compare:**

```bash
cf-gate                   # the complexipy stage measures write-free, grades in-kit
```

Fails (exit 1) on any NEW offender, or any baselined offender rising above its
watermark — complexipy's own rule, applied by `cf_quality.complexipy_ratchet`
over a floor the tool is never allowed to touch. A function at-or-below its
watermark passes. Do **not** mount a bare `complexipy src` as the gate; the first
gotcha is why.

**Observed gotchas the mount must respect:**

- **A passing plain-run compare REWRITES the snapshot** — measured on the pinned
  **complexipy 5.6.0** (2026-07-28), correcting the 5.5.0 entry that used to
  stand here and claim the file never shrinks itself. The destructive call site is
  `complexipy/utils/snapshot.py::handle_snapshot_watermark`, which calls
  `create_snapshot_file(...)` on its **no-violation** branch — the tool's green
  path is its write path. Reproduced twice at exit 0, a populated snapshot
  rewritten to `[]`: once by grading a path narrower than the floor describes,
  once by raising the threshold above every function. Committed, either one
  deletes the watermark forever behind a green run. `cf-gate` therefore measures
  write-free with `--plain --color no --snapshot-ignore` (verified on 5.6.0 to
  leave the file byte-unchanged) and grades the ratchet itself.
- **Your own `complexipy` config can defeat the gate, so the gate REFUSES instead
  of measuring through it.** `--snapshot-ignore` disarms the compare's rewrite, but
  `snapshot-create` is a **separate branch** (`main.py:323`) resolved CLI-first,
  TOML-second (`utils/toml.py:235-240`) — and `--snapshot-create` has no negating
  flag, so `cf-gate` cannot override it from the command line. So a
  `complexipy.toml` / `.complexipy.toml` / `[tool.complexipy]` carrying any of
  `snapshot-create`, `quiet`, `ratchet`, `failed`, `details = "low"`,
  `ignore-complexity`, `report-ignored`, `output`, `output-format`, or the legacy
  `output-csv|json|gitlab|sarif` fails the stage typed, naming the key and the file
  (`GATE_COMPLEXIPY_CONFIG_DEFEATS_MEASUREMENT`, exit 2). **Remove the key** — there
  is no workaround to reach for, because the two you actually want are already
  honoured: `max-complexity-allowed` (your threshold — the kit declares none of its
  own) and `exclude` (your surface). `no-ignore`, `check-script` and `sort` are
  honoured too. An unparseable config is also a refusal
  (`GATE_COMPLEXIPY_CONFIG_UNREADABLE`) — unreadable is not absent.
- **Raising `max-complexity-allowed` above a committed watermark fails the gate**
  (`GATE_COMPLEXIPY_THRESHOLD_RAISED`, exit 2) rather than quietly grading an empty
  offender set. If you mean to raise the bar, raise it and **re-boot the floor at
  the new threshold** in the same commit, so the floor and the bar agree.
- **The re-snapshot duty is still yours, in a narrower shape.** With the write
  disarmed the floor holds still, which means a shrink is not locked in merely by
  passing: the watermark rule is a `>` bound, so a function that got simpler and
  later climbs back to its stale watermark passes. Re-run
  `complexipy <source-root> --snapshot-create` from the repo root, deliberately,
  and commit it — that is the shrink ticket's job. What is MECHANICAL now, stated
  exactly (an earlier draft of this file claimed a floor file emptied of functions
  fails — it does **not**: `--plain` lists every measured function regardless of
  threshold, so a file whose functions all dropped below the bar is still measured
  and still green):
  - a floor file that exists but was not **measured** at all — excluded,
    ignore-commented, outside the surface, or now functionless — fails
    (`COMPLEXIPY_SNAPSHOT_FILE_UNMEASURED`);
  - a floor file outside the graded source root fails
    (`COMPLEXIPY_SURFACE_NARROWED`);
  - a floor **function** missing from a file that WAS measured fails
    (`COMPLEXIPY_SNAPSHOT_FUNCTION_UNMEASURED`) — that is the shape a
    `# complexipy: ignore` comment takes, and it is an unregistered exemption from
    this gate, so it is refused rather than absorbed;
  - a run that measured **zero functions** can no longer report clean while the
    floor names functions or the repo contains Python at all
    (`GATE_COMPLEXIPY_MEASURED_NOTHING`).

  Every one of those messages names the re-boot command as its remedy. Still on you,
  not on the gate: a wholly deleted floor file is a legitimate improvement and stays
  green, so the snapshot keeps dead entries until a re-boot clears them — and a floor
  someone zeroes by hand and commits is green too, visible only as a
  `complexipy-snapshot.json` diff in review.
- Run the **boot** from the **repo root** so the snapshot lands beside the code it
  describes (its path is CWD-relative, and the gate reads it from the repo root).
- Never pipe a hand-run complexipy command (`complexipy … | tail` masks the exit
  code). `cf-gate` runs it with a fixed argv and no shell, and does not *grade* on
  its exit code — but it does **cross-check** it: 0 and 1 are the tool's only
  verdicts, 1 being the ordinary "some function is over threshold", so exit 1 with an
  empty census, or any other non-zero code, is the instrument failing and refuses
  distinctly (`GATE_COMPLEXIPY_INSTRUMENT_FAILED`, carrying the exit code and a
  stderr excerpt) instead of being charged to your code. A file complexipy cannot
  parse likewise refuses (`GATE_COMPLEXIPY_PATHS_UNMEASURABLE`, exit 2, not exit 1):
  a narrower surface than the tree makes every other clean reading unsupported.

## 2. mypy-baseline — the 0-new-type-errors gate (multiset set-difference)

**Boot (day one) — MANDATORY for any repo containing Python.** The gate
REFUSES a Python repo with no `mypy-baseline.txt` (the 2026-06-10 refuter
showed the old presence-conditioned skip made "0 new type errors" opt-in);
a zero-error repo boots an empty baseline the same way. This boot is the ONLY
manual mypy command a consumer runs — once the baseline exists, `cf-gate` is the
day-to-day command (it applies the identical mypy → normalize transform
in-process; see below).

```bash
mypy <source-root> --config-file mypy-base.toml | python -m cf_quality.mypy_normalize | mypy-baseline sync
git add mypy-baseline.txt          # commit the frozen debt + a dated shrink ticket
```

`<source-root>` is the tree the gate measures — the kit's resolved source root
(`src/` when present, else the declared `[tool.cf-quality] source_root`; see
`cf-repo-config source-root`). `mypy-base.toml` is the kit's pinned mypy gauge —
the same config `cf-gate` loads from the installed kit, so the hand-synced
baseline is gauged exactly as the gate will gauge it. The baseline normalizes
line numbers to `:0`, so unrelated line drift cannot resurrect or duplicate
findings.

**Gate (every CI run, via `cf-gate`):** `cf-gate`'s mypy stage runs the SAME
`mypy <source-root> --config-file <kit cfg>` invocation, applies
`cf_quality.mypy_normalize` in-process, and gates on `mypy-baseline filter`'s
exit. The equivalent manual pipe — only the terminal verb changes, `sync` →
`filter`:

```bash
mypy <source-root> --config-file mypy-base.toml | python -m cf_quality.mypy_normalize | mypy-baseline filter
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
