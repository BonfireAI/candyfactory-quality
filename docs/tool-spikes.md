# Tool spikes — observed semantics (2026-06-10; §1 write semantics re-measured 2026-07-28)

Real behavior of the two pinned ratchet engines, measured on throwaway fixtures
in `/tmp` against the kit's venv. Every claim below was observed, not read off a
README. Versions **as measured in the original spike**: **complexipy 5.5.0** ·
**mypy-baseline 0.7.4** (mypy 1.x). The pin has since moved — read the skew note.

> **Version skew — read before trusting §1 (2026-07-28).** `pyproject.toml` pins
> **complexipy 5.6.0**; this spike was run against 5.5.0 and the label was never
> refreshed when the pin moved. Only the snapshot-**write** semantics have been
> re-measured on 5.6.0: the first entry under "Gotchas for the kit", the
> `handle_snapshot_watermark` call site, and the write-free measurement argv.
> The flag table, the snapshot file format and the ratchet exit-code table below
> still carry their original **5.5.0** observation and are unverified against the
> pin — treat each as a claim until re-run. §2's mypy-baseline 0.7.4 is still the
> pinned version. The reason this note exists: a stale version header let a
> flatly false claim about the snapshot survive in this file from 5.5.0 into a
> 5.6.0 world, and the kit's ratchet was designed against it.

> **Determinism note (2026-06-16).** The whole `[dev]` gauge battery is now pinned
> EXACTLY in `pyproject.toml` (`ruff==0.15.17`, `mypy==2.1.0`,
> `mypy-baseline==0.7.4`, `complexipy==5.6.0`, `pytest==9.1.0`, `pyyaml`,
> `types-PyYAML`, `import-linter==2.11`), and `requirements-lock.txt` freezes the
> full transitive set CI installs from. Rationale: ruff/mypy/complexipy output is
> version-sensitive, so a floating tool lets the grade drift under the code — the
> verdict must be a pure function of the code. `tests/test_pyproject_pins.py`
> guards the pins + lockfile. **The pins need a bump cadence** (a periodic
> Constable-driven refresh) or the battery rots; the lock has an owner ritual,
> not a freeze-and-forget.

---

## 1. complexipy — snapshot / watermark ratchet (5.5.0; writes re-measured on 5.6.0)

Fixture: a package with `simple` (CC 1), `branchy` (CC 4), later a deliberately
nested `monster` (cognitive complexity 33). Note complexipy measures **cognitive**
complexity (a second metric beside ruff's C901 cyclomatic), default threshold 15,
tunable with `--max-complexity-allowed/-mx`.

### Flags (verified against `--help` and runs)

- `--snapshot-create` / `-spc` — writes `complexipy-snapshot.json` into the
  **current working directory** (not the analyzed path). Exit 0 even when
  offenders exist (baseline boot is green by construction).
- A **plain run** (no flag) with a snapshot file present in CWD compares against
  it automatically — there is no separate `--diff`/`--ratchet` flag in 5.5.0;
  comparison is the default whenever the snapshot exists.
- `--snapshot-ignore` / `-spi` — skips the comparison.
- `-q` quiet · `-C no` disables color · `--output-format` for machine output.

### Snapshot file format

`complexipy-snapshot.json` records **only functions over the threshold** —
passing functions are not stored. All-clean tree → literal `[]` (2 bytes).
Shape:

```json
[
  {
    "path": "fixt/mod.py",
    "file_name": "mod.py",
    "functions": [ { "name": "monster", "complexity": 33 } ]
  }
]
```

### Observed ratchet semantics (the watermark)

| Scenario | Output | Exit |
|---|---|---|
| All functions ≤ threshold, snapshot `[]` | PASSED | 0 |
| **New** offender not in snapshot | `monster 33 (new, Δ = +33) FAILED` · "exceeds 15 but was not part of the snapshot" | **1** |
| Baselined offender **worsens** (33 → 38) | `monster 38 (last: 33, Δ = +5) FAILED` · "increased from 33 to 38" | **1** |
| Baselined offender at/below its watermark (back to 33) | PASSED | 0 |

### Gotchas for the kit

- **CORRECTED 2026-07-28 — a passing plain-run compare REWRITES the snapshot, so
  the tool shrinks its own floor, all the way to `[]` in the reproduced case.**
  The 5.5.0 entry that stood here asserted the opposite (that the file never
  shrinks itself, and that `--snapshot-create` is the only thing that rewrites
  it). Both halves are false on the pinned **complexipy 5.6.0**. The destructive
  call site is `complexipy/utils/snapshot.py::handle_snapshot_watermark`, which
  calls `create_snapshot_file(...)` on its **no-violation** branch: the tool's
  GREEN path *is* its write path. Reproduced twice at **exit 0** against a
  populated snapshot, each time leaving `[]` behind — (a) **narrowed surface**:
  compare over a path narrower than the floor describes, nothing in that subset
  violates, the floor is rewritten to the subset; (b) **raised threshold**:
  `-mx 100` puts every function under the bar, same rewrite. Committed, either
  one deletes the watermark forever behind a green gate. This is why the kit
  never lets the tool near the artifact: `cf-gate` measures with
  `--plain --color no --snapshot-ignore` (which makes
  `should_run_snapshot_watermark` False — the only other caller of
  `create_snapshot_file` is the never-passed `--snapshot-create`) and grades the
  ratchet in its own pure function, `cf_quality.complexipy_ratchet.grade`, over
  (committed floor, measured census). Also measured on 5.6.0: that argv over a
  142-file tree emitted 681 stdout lines, every one a
  `<path> <function> <complexity>` census row, **0 bytes on stderr**, and left
  `complexipy-snapshot.json` byte-unchanged.
- **`--snapshot-ignore` alone is NOT enough — the consumer's own config can put the
  write back, so the kit AUDITS that config and refuses.** Read in the source, not
  inferred: `snapshot_create` resolves CLI-first-then-TOML
  (`utils/toml.py:235-240`), the kit passes no CLI value for it, and
  `handle_snapshot_file_creation` (`main.py:323`) is an **entirely separate branch**
  from the watermark compare that `--snapshot-ignore` disarms. `--snapshot-create`
  is declared with no negating secondary name (`main.py:97-102`), so argv cannot
  force it off. A consumer's `complexipy.toml` / `.complexipy.toml` /
  `[tool.complexipy] snapshot-create = true` therefore made **both** measurement
  runs rewrite the floor while the gate graded the pre-write bytes it had already
  read — green, artifact silently mutated. Two more keys defeat the run the same
  way: `quiet = true` (rejected beside `--plain`, `main.py:748` → exit 2, empty
  census, which the gate used to report as `GATE_COMPLEXIPY_MEASURED_NOTHING` and
  blame on the repo) and `output-format` / the legacy `output-csv|json|gitlab|sarif`
  (a report file written into the consumer's tree, plus `Results saved at …`
  (`main.py:510`) and `Deprecated: …` (`main.py:521-536`) printed on **stdout,
  unguarded by `plain`, BEFORE the census**). `cf_quality.complexipy_measure`
  `audit_config` reads the same file the tool reads, in the tool's own order
  (`utils/toml.py:135-148`: `complexipy.toml`, then `.complexipy.toml`, then
  `pyproject.toml`, first hit wins — and for the first two an EMPTY document counts
  as a hit, so it shadows `pyproject.toml`), and REFUSES with the key and the file
  named (`GATE_COMPLEXIPY_CONFIG_DEFEATS_MEASUREMENT`). Neutralising it by moving
  the cwd was rejected for cause: `main.py:66-67` resolves the config,
  `main.py:321` the snapshot path and `main.py:308-310` every reported path from the
  **same `os.getcwd()`**, so a different cwd re-keys the whole census. Deliberately
  still honoured: `max-complexity-allowed`, `exclude`, `no-ignore`, `check-script`,
  `sort`.
- **A raised threshold empties the offender set, and the ratchet must refuse rather
  than grade nothing.** With `max-complexity-allowed` raised (by `-mx` or by
  config), the census still lists every function — so every floor file is present
  and the surface audit is silent — while `--failed` returns **nothing**, and a
  subset check over an empty subset passes trivially. The closure needs no second
  threshold authority: a floor entry is proof that function was ABOVE the bar when
  the floor was booted (`create_snapshot_file` stores only over-threshold
  functions), so a census value at-or-above its watermark that the offender run does
  NOT report means `threshold_now >= census >= watermark > threshold_at_boot`
  (`GATE_COMPLEXIPY_THRESHOLD_RAISED`). A hand-lowered watermark lands in the same
  refusal, correctly — the tool would never have written one at or below its own
  threshold.
- **Exit semantics, established from the source** (`main.py:756-767`
  `resolve_final_success` reduces to `has_success and valid_paths` with the compare
  disarmed; `has_success` is `not failing_functions`, `utils/output.py:44`, which is
  filled for every over-threshold function whether or not `--failed` was passed,
  `utils/output.py:234-241`). So **0 and 1 are the tool's only verdicts**, 1 being
  the legitimate "some function is over threshold" — the normal state of a repo
  carrying a floor. Exit 1 with an **empty** census is a contradiction (and is the
  offender run's second vacuity leg); any other code is `typer` declining to run
  (`BadParameter` → 2 at `main.py:748`, `validate_ratchet` → 2 at
  `main.py:726-729`). The kit refuses distinctly on both
  (`GATE_COMPLEXIPY_INSTRUMENT_FAILED`) and carries the exit code plus a stderr
  excerpt in the refusal context, because a tool-side failure re-attributed to the
  repo with its reason deleted is worse than no gate.
- **`--plain` prints EVERY measured function, over threshold or not**
  (`utils/output.py:234` drops a row only under `failed_only`; `:243` appends every
  other one). That is load-bearing twice over: it is why a function that merely got
  simpler is still in the census, and therefore why a floor function absent from a
  file that WAS measured means something else — renamed, deleted, or dropped by a
  `# complexipy: ignore` comment (`COMPLEXIPY_SNAPSHOT_FUNCTION_UNMEASURED`). The
  argv passes neither `--no-ignore` nor `--report-ignored`, so an ignore comment
  drops a function from both runs; that is caught structurally now rather than by
  flag. **Open for the operator:** adding `--no-ignore` to the gate argv would need
  the boot command in `configs/BASELINE-CONVENTIONS.md` to carry the same flag, or
  every currently-ignored function floods in as a new offender — a paired change,
  not a unilateral one.
- **A path complexipy cannot analyze is a REFUSAL, not a finding** — declared, since
  it is a taxonomy change: `print_invalid_paths` → `has_success=False` used to make
  it exit 1. `GATE_COMPLEXIPY_PATHS_UNMEASURABLE` exits 2 instead, because an
  unparseable file means the graded surface is narrower than the tree, so every
  OTHER function's clean reading is unsupported and a findings-level report would
  let the rest of the board read green beside a void. A consumer who lands a syntax
  error gets a setup-error board; ruff and mypy red independently, so nothing is
  hidden.
- **The re-snapshot duty survived the fix — it changed shape, it did not go
  away.** With the write disarmed the floor holds still in both directions, so a
  shrink is still not locked in merely by passing: the watermark rule is a `>`
  bound (`complexipy_ratchet._regressions` mirrors the tool exactly), so a
  function that got simpler and later climbs back to its stale watermark passes.
  Locking a shrink in is a deliberate, committed
  `complexipy <source-root> --snapshot-create` from the repo root — the shrink
  ticket's job. What changed is that forgetting is no longer silent where it used to
  be catastrophic. Precisely (corrected 2026-07-28 — an earlier pass on this branch
  claimed "an improvement that empties a floor file of functions … FAILS
  `COMPLEXIPY_SNAPSHOT_FILE_UNMEASURED`", which is **false**: `--plain` without
  `--failed` lists every measured function regardless of threshold, so a file whose
  functions all dropped below the bar stays in `census.files` and the gate is
  GREEN):
  - `COMPLEXIPY_SNAPSHOT_FILE_UNMEASURED` fires when the file was not **measured**
    at all — excluded, ignore-commented, outside the measurement surface, or now
    containing no function whatsoever — while still existing on disk.
  - `COMPLEXIPY_SURFACE_NARROWED` fires when a floor file exists but lies outside
    the graded source root.
  - `COMPLEXIPY_SNAPSHOT_FUNCTION_UNMEASURED` fires when the file WAS measured and
    a floor function inside it was not, which the two rules above cannot see.
  - A run that measured **zero functions** can no longer report clean while the
    floor still names functions or the repo contains Python at all
    (`GATE_COMPLEXIPY_MEASURED_NOTHING`); the second leg is the caller's repo-wide
    `py_present`, the same answer the absent-snapshot doctrine rides, so the two
    surfaces cannot disagree about whether there was anything to grade.
  - Every one of those messages names the re-boot as its remedy, spelled with the
    resolved graded root.

  Not caught, honestly: a wholly **deleted** floor file is a legitimate improvement
  and stays green, so the snapshot accumulates dead entries until someone re-boots
  it, and a floor a human zeroes by hand and commits is green as well — review of
  the `complexipy-snapshot.json` diff is the only instrument on that one.
- **Snapshot lands in CWD** — the boot command must run from the repo root, so the
  committed snapshot sits where the kit reads it from.
- **Exit-code caution:** piping output (`complexipy … | tail`) masks the exit code;
  never pipe a hand-run command. The kit does not *grade* on that exit code — the
  grade is `complexipy_ratchet.grade` over (floor, census) — but it does
  **cross-check** it, per the exit semantics above: a code that contradicts the
  census is the instrument failing, and the kit refuses instead of charging it to
  the code.
- A function exactly **at** its watermark passes the watermark rule — a `>` bound,
  mirrored exactly; shrink-only happens via re-snapshot, not via the compare itself.
  It must however still appear in the `--failed` run, or the bar has moved
  (`GATE_COMPLEXIPY_THRESHOLD_RAISED` above) — "at its watermark" and "no longer an
  offender at all" are different worlds.

**Verdict (revised 2026-07-28, measured on the pinned 5.6.0).**
`--snapshot-create` gives the freeze the plan wanted (plan Q2 answered), but the
plain-run **compare** is unusable as a gate: the run that passes is the run that
rewrites the floor it just graded. So the kit demotes complexipy to a measuring
instrument (`--plain … --snapshot-ignore`) and owns both halves of the ratchet —
the comparison, in `complexipy_ratchet.grade`, and the re-baseline step that
makes a shrink sticky.

---

## 2. mypy-baseline 0.7.4 — the set-difference question

Fixture: a package with 2 deliberate errors (`return-value`, `operator`).
Baseline: `mypy pkg | mypy-baseline sync` → writes `mypy-baseline.txt`, exit 0.

### Baseline file format

One line per error, **line numbers normalized to `:0`** (position-insensitive —
unrelated line drift cannot resurrect or duplicate findings; this kills the
bandit-style line-position fragility):

```
pkg/mod.py:0: error: Incompatible return value type (got "str", expected "int")  [return-value]
pkg/mod.py:0: error: Unsupported operand types for + ("int" and "str")  [operator]
```

### Observed filter semantics

`mypy … | mypy-baseline filter` — exit codes and verdicts:

| Scenario | fixed / new / unresolved | Exit |
|---|---|---|
| Unchanged code | 0 / 0 / 2 | 0 |
| **Fix 1 + ADD 1** (count stays 2 — the laundering attack) | 1 / 1 / 1 · "Your changes introduced new violations." · the added error printed with real file:line | **2** |
| Add a **byte-identical** duplicate of a baselined error (same file, same message) | 0 / 1 / 2 — still flagged new | **1** |
| Fix-only, baseline stale | 1 / 0 / 1 · "resolved existing violations… remove from the baseline" | **1** |

### Answers to the plan's questions

- **Set-difference: YES.** A 1-for-1 swap is caught — `filter` matches
  individual error lines, never counts, so the count-laundering hole in a
  naive `error-count ≤ baseline-count` assertion does not exist here.
- **Better than a set — it is a MULTISET.** Even an added error whose message is
  byte-identical to a baselined one in the same file is reported as new
  (occurrences are counted per message, not deduplicated). Same-shaped copies
  cannot hide behind an existing entry.
- **The baseline cannot rot silently:** fixed-only also exits nonzero and
  instructs a `sync`, so every shrink is committed — the ratchet direction is
  enforced by the tool itself (unlike complexipy, which needs the kit's help).
- Observed exit pattern: `0` clean · `1` when only one of {new, fixed} is
  present · `2` when both. Gate on **nonzero**, not on a specific value.

**Verdict:** `mypy-baseline filter` natively implements the deletions-only
set-difference assertion the Law-3 refuter demanded (plan Q3, mypy half) — no
bespoke wrapper needed for the type gate.
