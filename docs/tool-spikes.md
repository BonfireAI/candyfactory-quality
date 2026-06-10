# Tool spikes — observed semantics (2026-06-10)

Real behavior of the two pinned ratchet engines, measured on throwaway fixtures
in `/tmp` against the kit's venv. Every claim below was observed, not read off a
README. Versions: **complexipy 5.5.0** · **mypy-baseline 0.7.4** (mypy 1.x).

---

## 1. complexipy 5.5.0 — snapshot / watermark ratchet

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

- **The snapshot does NOT auto-shrink.** After an improvement the plain run
  passes but `complexipy-snapshot.json` still holds the old watermark; only
  `--snapshot-create` rewrites it. The kit's ratchet step must re-create the
  snapshot on merge (or a shrink ticket does) or improvements are not locked in
  — a later regression back up to the stale watermark would pass.
- **Snapshot lands in CWD** — the CI step must run from the repo root so the
  committed snapshot is the one compared.
- **Exit-code caution:** piping output (`complexipy … | tail`) masks the exit
  code; gate on the command's own status (or `pipefail`).
- A function exactly **at** its watermark passes — the watermark is a ≤ bound,
  shrink-only happens via re-snapshot, not via the compare itself.

**Verdict:** `--snapshot-create` + plain-run compare gives exactly the
freeze/shrink-only ratchet the plan wanted (plan Q2 answered). The kit must own
the re-baseline step to make shrink sticky.

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
