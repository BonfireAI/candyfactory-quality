# DESIGN — the gauge kit (candyfactory-quality)

The shared quality gate every CandyFactory repo mounts: the executable half of
**the BubbleGum Law** (canon ADR 0029 — *code keeps a measured shape, and the
law that keeps it travels sticky*). This design record is organized around the
one fact that shaped it: the adversarial refuter pass returned **0/7 law
drafts ungameable as written**. Every gaming vector from that pass gets its
own section below, answering how the shipped v0 closes it — or stating an
honest OPEN. A vector with no answer is an OPEN, never a silent skip.

Everything here describes code that exists in this repo as of v0
(`src/cf_quality/`, `.github/workflows/`, `configs/`, `templates/`, `data/`),
verified against the source — not the plan. Where the plan demanded something
v0 does not ship, that gap is named here and again in **Open issues**.

---

## 1. Two-surface architecture

The law has two surfaces by ratified design (ADR 0029: *"prose teaches, gates
gate"*), and the kit ships both:

1. **The sticky intro (cognitive surface).** `src/cf_quality/data/sticky-intro.md` is the
   canonical short introduction to the law — a **declared mirror** of canon
   ADR 0029's fenced block, provenance + content hash recorded in
   `src/cf_quality/data/sticky-intro.SOURCE.md`. `cf-sticky-check mount` appends it to a
   consumer repo's `CLAUDE.md` under a one-line declared-mirror header
   (idempotent; refuses to mount over a tampered block). Any model scanning
   the repo ingests the law as it reads; outside an enforcement perimeter it
   acts as the strongest suggestion in the file — that is its job.
2. **The gate (mechanical surface).** Inside CI the law is executable and
   refusing:
   - `.github/workflows/quality-gate.yml` — the reusable (`workflow_call`)
     gate consumers pin by full commit SHA via the generated caller stub
     (`templates/quality.caller.yml`).
   - `.github/workflows/self-ci.yml` — the kit's own CI, deliberately NOT via
     `workflow_call`: the kit runs the same battery directly, so a broken
     reusable workflow can never grade itself green. The gauge submits to its
     own gate first (the Method's test, applied to the instrument).

The gate battery shipped in v0 — console scripts, all speaking the typed
failure vocabulary of `cf_quality/errors.py` (`GateError` = "the gate could
not run", stable code + context + retryability; `GateViolation` = the frozen
finding; exit codes 0 clean · 1 violations · 2 gate error, per the Elegance
Law — no swallowed exceptions, no `None`/`-1` returns):

| Command | Module | Gates |
|---|---|---|
| `cf-file-budget` | `file_budget.py` | new files ≤ 500 lines; frozen files shrink-only; per-package LOC draw |
| `cf-sticky-check` | `sticky_check.py` | sticky intro mounted byte-faithful; chewed gum fails with a diff |
| `cf-mirror-check` | `mirror_check.py` | cross-repo copies declared in `MIRRORS.md`; hash + pin-age checks |
| `cf-recursion-check` | `recursion_check.py` | self-recursion declared with a stated bound, or it fails |
| `cf-exemptions` | `exemptions.py` | every gated suppression traces to a reasoned, approved registry entry |

Shared configs: `configs/ruff-base.toml` (C901 ≤ 10, PLR0915 ≤ 50, S battery,
BLE ban — the ratified budgets), `configs/mypy-base.toml` (strict-leaning
profile, see §10), `configs/jscpd.src.json` / `configs/jscpd.tests.json` (the
two-profile clone carve-out, see §7). Tool-behavior ground truth lives in
`docs/tool-spikes.md` — complexipy 5.5.0 and mypy-baseline 0.7.4 semantics
were observed on fixtures, not read off READMEs.

---

## 2. SHA-pin doctrine

Full text in `docs/sha-pin-doctrine.md`; load-bearing points:

- Every cross-repo workflow/action ref is pinned to a **full 40-hex commit
  SHA** — never `@main`, never a tag (tags move; SHAs do not). The kit's own
  action pins follow the same rule with the human-readable tag in a trailing
  comment (see both workflow files).
- The gate checks the kit itself out at **`github.job_workflow_sha`** — the
  exact commit the caller pinned the reusable workflow to — so the gate
  scripts and the workflow file are always the SAME commit. No gauge/workflow
  skew, and a consumer cannot be gated by scripts newer or older than the
  workflow that invokes them.
- Dependabot (`github-actions` ecosystem) owns pin freshness via bump PRs;
  the bump itself runs through the gate it bumps. Org Actions policy enforces
  full-SHA pinning; the Constable's weekly sweep audits unpinned refs
  estate-wide. Emergency rollback = a one-line re-pin PR — history sacred.

---

## 3. Baseline-generation runbook (mounting a consumer repo)

The observed-behavior version lives in `configs/BASELINE-CONVENTIONS.md`;
summary of the day-one mount (green by construction, then shrink-only — and
every baseline carries a **dated ratchet ticket** so green-by-baseline cannot
become green-forever):

1. **Caller stub:** copy `templates/quality.caller.yml` to
   `.github/workflows/quality.yml`, replace the placeholder with a real full
   commit SHA of this kit. Mount it as a **required status check** in the
   repo's branch protection/ruleset (see §11 for why this step is
   load-bearing and not yet mechanical).
2. **Sticky intro:** `cf-sticky-check mount <repo>` — appends the canonical
   block to `CLAUDE.md` under the declared-mirror header.
3. **ruff gauge:** vendor `configs/ruff-base.toml` as `<repo>/ruff.toml`. The
   only locally-extendable section is `lint.per-file-ignores` (anything wider
   is the refuter's escape hatch — §12). Recommended: declare the vendored
   copy in `MIRRORS.md` so `cf-mirror-check` hash-gates its drift.
4. **File budget:** `cf-file-budget init` — freezes every existing >500-line
   file at its measured size and writes the per-package LOC totals into
   `file-budget.json`.
5. **Type ratchet:** `mypy src --config-file mypy-base.toml | mypy-baseline
   sync` → commit `mypy-baseline.txt`. The baseline normalizes line numbers
   to `:0`, so unrelated drift cannot resurrect findings.
6. **Cognitive-complexity watermark:** `complexipy src --snapshot-create`
   **from the repo root** (the snapshot lands in CWD, not the analyzed path)
   → commit `complexipy-snapshot.json`. Observed gotchas: the snapshot does
   NOT auto-shrink (the kit owns the re-snapshot on merge, or improvements
   are not locked in); piping the gate command masks its exit code.
7. **Exemptions:** if the repo carries any gated suppression, register each
   in `exemptions.json` (five fields: file, symbol_or_line, rule, reason,
   approver) and set `frozen_count`.
8. **Mirrors:** `cf-mirror-check init` writes a template `MIRRORS.md`;
   declare every cross-repo copy with content sha256 + pinned parent SHA +
   pinned date.

---

## 4. The gaming vectors — one section each

Each section names the refuter vector, what v0 ships against it (verified
in code), and a verdict: **CLOSED** (mechanically refused) · **PARTIAL**
(refused in part; named residue) · **OPEN** (honest: v0 does not close it).
Every PARTIAL/OPEN residue reappears in **Open issues** (§5).

### 4.1 Sibling-file accretion

*The vector:* instead of growing a frozen `handle.py` past its watermark, the
agent creates `handle_extra.py` at 499 lines next to it — the accretion
engine intact, just relocated; per-file budgets never fire.

*What v0 ships:* `cf-file-budget`'s third rule. `file-budget.json` carries
`packages` — frozen recursive LOC totals for every directory holding a frozen
file (written by `init`). Every undeclared `.py` file under a baselined
package draws against the frozen total; `_check_packages` fails with
`PACKAGE_BUDGET_EXCEEDED`, listing the new files. A 499-line sibling next to
a frozen file therefore FAILS. The declared escape is declared-not-banned: a
new file may carry `{"purpose": "one-line"}` in `files`, exempting it from
the package draw while it still obeys the 500-line new-file cap — so a split
is a visible, reviewed declaration, never silence.

*Hardened 2026-06-10 (second refuter pass):* the unit of measure was
physical lines — trivially compressible. The refuter re-flowed 900 real
statements onto 300 `;`-joined lines against a 700-line freeze and the gate
reported a SHRINK while a new 380-line sibling spent the freed headroom
(+83% real content reported as shrink). Every draw is now anchored to
`measure_file` = **max(physical lines, logical statements)** — re-flowing
cannot manufacture headroom, and an unparseable `.py` is a typed gate error,
never a silent line-count fallback.

*Residue:* the `purpose` declaration is written by the same PR it excuses —
review-visible (a `file-budget.json` diff) but not approver-gated like
`exemptions.json` entries. The sticky intro carries the human-side doctrine:
*"splitting a file is design, not evasion — the gate measures, review
judges."* And the package draw is RELOCATION-ONLY: `init` seeds a package
total only for directories already holding a >500 offender, so a greenfield
burn authoring many sub-500 siblings in a fresh package never draws against
a package ceiling (refuter attack 2) — disclosed in the module docstring and
filed in §5.

**Verdict:** CLOSED mechanically for relocation and compression; the
greenfield-package boundary and the purpose-declaration residue are on the
open record.

### 4.2 CC laundering

*The vector:* split a CC-23 function into `_run_a`/`_run_b` called in
sequence, or a dict-dispatch table — each piece ≤ 10, total complexity
unchanged, every per-function counter resets, ruff and complexipy both green.

*What v0 ships:* nothing that mechanically refuses it. ruff C901 and
PLR0915 gate each function; complexipy's watermark is also per-function.
The refuter's own fix conceded the catch is cross-wired (the clone gate as
the cross-check) and review-judged; the clone gate is not yet wired (§4.4).
The sticky intro states the doctrine so every scanning model carries it, but
prose is not a gate — by this kit's own ratified text.

**Verdict:** OPEN. Per-function counters reset on split by construction;
v0 has no totality metric. Mitigations on the roadmap: the jscpd wiring
(§4.4) catches the copy-shaped variant, and a per-module cognitive-complexity
sum is a candidate second wire — neither is built.

### 4.3 Self-issued noqa

*The vector:* "Wizard-gated `# noqa: C901`" with no tool verifying the
Wizard — the agent writes `# noqa: C901  # reason: inherently complex`
itself; ruff sees a noqa and passes.

*What v0 ships:* `cf-exemptions` makes the gating mechanical. Comments are
read via `tokenize` (COMMENT tokens only — suppression text in string
literals never trips or hides). Every `# noqa: C901` / `# noqa: PLR0915`
must match an `exemptions.json` entry carrying all five fields (file,
symbol_or_line, rule, reason, approver — empty fields fail validation); an
unregistered suppression fails with `UNREGISTERED_SUPPRESSION` ("a
self-issued suppression is not an exemption"); gated suppressions with NO
`exemptions.json` at all raise `GATE_CONFIG_MISSING`. The registry itself is
ratcheted: `frozen_count` must cover the entry count; additions require
bumping it — printed loudly on every run, a visible decision, never silent.

*Hardened 2026-06-10 (second refuter pass):* (a) a bare CODELESS `# noqa`
was strictly more powerful than any coded one (ruff honors it as a blanket
suppression) and was invisible to both the registry and the gauge — it now
fails `BARE_NOQA` in cf-exemptions AND PGH004/RUF100 in the ruff gauge.
(b) the registry-gated set was only C901/PLR0915 while the gauge's security
(S) and Elegance (BLE) batteries were suppressible with no entry and no
reason — the whole S and BLE families are now registry-gated, and the kit
registers its own S603 in its own `exemptions.json` (self-policing).
(c) symbols are matched by QUALIFIED name (`ClassA.run`) and an entry
covering more than one live suppression fails `EXEMPTION_ENTRY_OVERLOADED`
— N same-named suppressions can no longer collapse onto one frozen entry.
(d) the measured surface is discovered (src/ when present, else top-level
packages and modules), so a flat/app layout is measured, never a no-op.

*Residue:* the `approver` field is a string; its authenticity is carried by
PR review of the `exemptions.json` diff, not by signature. Style/import noqa
codes (E/F/I/UP/B) remain ungated by the registry — ruff + review carry them.

**Verdict:** CLOSED for the form, security, and Elegance batteries; the
approver-authenticity residue is review-carried.

### 4.4 jscpd untouched-file blind spot

*The vector:* `git diff --name-only` scoping puts only changed files in
jscpd's scan set, and jscpd only finds clones AMONG scanned files — pasting
from any file the PR does not touch reports 0% by construction. The
canonical LLM copy event escapes the gate that exists to catch it.

*The design answer (agreed, from the refuter fix):* scan the FULL tree every
PR, emit the JSON report, and gate via a thin attribution wrapper that fails
only when a clone instance intersects the PR's ADDED line ranges
(`git diff -U0 origin/<base>...HEAD`) — restoring real new-code semantics.
Split modes: **diff-attribution mode on PR** (fast verdict on the change) +
**full-scan nightly** (census sweep for clones that predate the wiring,
feeding shrink tickets), plus an absolute backstop (any single new clone
block ≥ 30 lines fails regardless of ratio) to kill denominator padding.

*What v0 ships vs OPEN:* v0 ships the two profile configs only —
`configs/jscpd.src.json` (minTokens 35, tests ignored) and
`configs/jscpd.tests.json` (minTokens 70) — two files by necessity, since one
`.jscpd.json` cannot carry two minTokens values. **The attribution wrapper,
the PR diff mode, the nightly full scan, the clone-fingerprint baseline, and
the jscpd step in `quality-gate.yml` are all unbuilt.** There is no jscpd
step in either workflow today.

**Verdict:** OPEN. v0 ships configs; the wiring that makes the semantics
true is the kit's single largest unbuilt piece.

### 4.5 Fixture indirection

*The vector:* a conformance battery whose BINDING is agent-supplied — a
conftest fixture hands the battery a conforming `to_wire()` shim while the
production path keeps serializing the old dialect. Battery green, wire bytes
unchanged.

*What v0 ships:* the conformance batteries themselves (ErrorDetail wire
shape, slug contract) are not in v0, so the vector's primary target does not
exist yet. The *principle* is, however, already applied where v0 binds a
gauge to a source of truth: `cf-sticky-check` loads the canonical sticky
text **from the kit's own packaged data file, never from the consumer repo**
(`canonical_text()` resolves only inside the installed kit) — a consumer
cannot re-declare its own edited copy as canonical. The agreed battery
design: assert bytes from the repo's REAL egress (boot the app, trigger an
error, assert serialized JSON), the producer named by import-path in a
committed `conformance.toml` proven by an import-linter contract to be the
symbol the routes import.

**Verdict:** OPEN (the batteries are unbuilt); the kit-side binding pattern
that answers the vector is established in shipped code.

### 4.6 Bare # nosec

*The vector:* the law regulated ruff-S noqa but never bandit's own inline
suppression — a bare `# nosec` silences any finding before it reaches a
report or baseline; gate green, vuln shipped.

*What v0 ships:* `cf-exemptions` check (a): a bare `# nosec` — no rule id
AND no reason — anywhere under `src/` fails with `BARE_NOSEC`. A `# nosec
B###` (specific rule) is a gated suppression and must match a reasoned,
approved `exemptions.json` entry like any noqa (§4.3). The ruff gauge also
runs the S category (the ported bandit battery) on every gated repo, where
suppression is `# noqa: S###` — visible to review and the diff.

*Residue:* full bandit itself (for rules ruff has not ported) and pip-audit
are not workflow steps in v0; the `# nosec` gate polices the suppression
idiom ahead of the engine it suppresses (§5).

**Verdict:** CLOSED for the suppression idiom; the engine rollout it
anticipates is OPEN.

### 4.7 Test-target unbinding

*The vector (the money seam):* the kit ships forged payloads but the repo
authors the TEST — the agent aims the manifest-named test at a strict shadow
verifier while the production route keeps the lax one. Green gate, forgeable
webhook.

*What v0 ships:* nothing. The money-seam kit (`test_money_seam.py`,
`money-paths.toml`, the parametrized kit-owned test that builds the app from
a manifest-named factory and POSTs golden forged payloads at the production
route, asserting typed-error rejection plus no side-effect) is entirely
unbuilt. The agreed design is recorded in the audit corpus (Law 7 refuter
fix), acceptance-gated by a pre-registered RED on the two known in-memory
money stores before it is trusted.

**Verdict:** OPEN. Named so the absence is a decision on record, not silence.

### 4.8 Caller-stub neutering / non-required checks

*The vector:* a 10-line stub that "calls the shared workflow" while never
gating — `continue-on-error: true`, a `paths:` filter, a non-default-branch
or non-push/PR trigger, a skip-mode input; or a gate that runs red while
nothing makes it a required status check, so merges land anyway.

*What v0 ships:*

- **No inputs, by design.** `quality-gate.yml` declares `workflow_call: {}`
  with an empty-forever inputs block; GitHub itself rejects any caller that
  passes `with:` against an undeclared input — a skip knob cannot even be
  smuggled in. Behavior differences live in committed consumer state
  (baselines, `MIRRORS.md`), never in caller knobs.
- **Trigger self-assertion.** The first step (before any checkout) reads
  `github.event_name` and refuses anything but `push`/`pull_request` — a
  `workflow_dispatch`- or `schedule`-only stub is refused loudly.
- **Hollow-gauge refusal.** The workflow fails if no vendored ruff config
  exists (defaults are far weaker than the gauge), and plain `pytest` fails
  on exit 5 — a repo with zero collected tests fails the floor on purpose.
- **The stub is a generated surface.** `templates/quality.caller.yml`
  documents every banned neutering vector inline; stubs are copied from the
  template, never hand-written.

*What v0 cannot see from inside:* a `paths:` filter means the run never
happens — undetectable by the called workflow; `continue-on-error` on the
CALLER's job neutralizes a red verdict at a layer the gate cannot reach; and
**required-status-check rulesets are repo settings**, outside any workflow's
power to assert. Those live in the mount runbook (step 1), the Constable's
weekly ruleset sweep, and the pre-registered mount canary (deliberately
failing commit → assert red AND unmergeable → record the run URL) — all
procedure in v0, not mechanism.

**Verdict:** PARTIAL. Event-type neutering and skip inputs are mechanically
refused; paths filters, caller-side `continue-on-error`, and
required-check enforcement remain procedural (Constable + mount canary).

### 4.9 ruff-sync exclude escape

*The vector:* `[tool.ruff-sync].exclude` is an unbounded dotted-path escape
hatch — exclude `lint.ignore`, stuff the local ignore list, and the sync
check exits 0 forever; or simply vendor a hollowed copy of the gauge.

*What v0 ships:* the doctrine, plus one real mechanical path — not the named
tool. `configs/ruff-base.toml`'s header declares the allowlist: the ONLY
locally-extendable section, and the only dotted path permitted in a
ruff-sync exclude, is `lint.per-file-ignores` — and every added ignore must
trace to a reasoned `exemptions.json` entry. The workflow asserts a vendored
ruff config EXISTS (refusing the no-config hollow-lint case). The mechanical
drift closure available today is `cf-mirror-check`: the mount runbook (§3
step 3) recommends declaring the vendored `ruff.toml` in `MIRRORS.md`, after
which any byte of drift from the declared hash fails the build.

*Hardened 2026-06-10 (second refuter pass):* the workflow's presence-only
assert accepted a hollowed `ruff.toml` (`select=["F"]`) and graded the
consumer against its own weak gauge. The gated `ruff check` / `ruff format`
now run with `--config "$GITHUB_WORKSPACE/.cf-quality/configs/ruff-base.toml"`
— the kit checkout at the pinned SHA, the same doctrine as the mypy step —
so the consumer's vendored copy serves local dev only and cannot weaken the
graded verdict.

*What v0 still does not ship:* a `ruff-sync check` step or an allowlist
auditor for exclude paths; the vendored copy's drift is now cosmetic in CI
but still misleads local runs unless mirror-declared.

**Verdict:** CLOSED at CI altitude (the verdict rides the kit's pinned
gauge); local-dev fidelity of the vendored copy stays mirror-declared,
not forced.

### 4.10 De-annotation invisibility

*The vector:* default mypy skips bodies of unannotated functions — ship new
code with NO annotations (0 new errors forever), or shrink the baseline by
deleting the annotation that triggered an error; CI reads stripping types as
burndown progress.

*What v0 ships:* the pinned profile the refuter demanded, owned by the kit.
`configs/mypy-base.toml` sets `check_untyped_defs` + `disallow_untyped_defs`
(unannotated new code is itself an error — de-annotation creates errors
instead of hiding them) + `warn_unused_ignores` + `warn_redundant_casts`.
Decisively: the workflow runs mypy with `--config-file` pointing at the
**kit checkout at the pinned SHA, not the consumer repo**, so a consumer
cannot weaken the profile it is graded by. Per-module grace exists only as a
narrow `[[tool.mypy.overrides]]` pattern with a reason comment (documented
in the config), never a global loosening.

*Residue:* (a) the sibling ratchet on per-repo `# type: ignore` counts is
not built (`warn_unused_ignores` polices stale ignores, not new ones);
(b) because the CI path uses the kit's config file directly, consumer
per-module overrides have no vehicle in the gated run yet (§5).

**Verdict:** CLOSED for the de-annotation mechanics; the `type: ignore`
volume ratchet is OPEN.

### 4.11 Count-vs-set baseline laundering

*The vector:* "baseline only shrinks" enforced as a COUNT lets fix-one +
add-one + resync keep the count equal and grandfather a NEW finding in an
ordinary PR.

*What v0 ships, per baseline:*

- **mypy — CLOSED, by observed tool semantics** (`docs/tool-spikes.md`):
  `mypy-baseline filter` matches individual error lines, never counts. The
  1-for-1 swap was run on a fixture and CAUGHT (exit 2, the added error
  printed with real file:line). It is better than a set — a MULTISET: even a
  byte-identical duplicate of a baselined error in the same file is flagged
  new. Fixed-only also exits nonzero ("re-sync"), so every shrink is
  committed — the ratchet direction is enforced by the tool itself.
- **complexipy — set-like per function** (new offender fails; baselined
  offender worsening fails), but the snapshot does NOT auto-shrink: the
  re-snapshot-on-merge step is runbook procedure (§3 step 6), not yet CI
  mechanism, and the complexipy step is not yet in `quality-gate.yml`.
- **cf-exemptions — count-based by design**, and honestly so: `frozen_count`
  refuses silent growth, but a 1-for-1 entry swap at equal count is
  machine-visible only as an `exemptions.json` diff in review, not
  machine-refused.
- **bandit findings-set** — unbuilt (no bandit step exists to launder).

**Verdict:** PARTIAL. The type ratchet — the baseline carrying ~132 real
grandfathered errors estate-wide — is closed at the tool level with observed
proof; the exemption registry and the unwired engines retain count-shaped or
absent residue.

### 4.12 Declare-don't-fix mirror legalization

*The vector:* `cf-mirrors` fails only UNDECLARED drift — so declare every
divergence with a stale pinned SHA, drift is legalized forever, and the
dialect count is self-reported.

*What v0 ships:* `cf-mirror-check` with three refusals: (a) a declared local
file whose sha256 diverges from the declared content hash fails
(`MIRROR_DIVERGED`, both hashes in the finding) — declaring a mirror means
pinning its BYTES, so post-declaration drift is caught even though declared;
(b) a row missing any required field fails (`MIRROR_ROW_INCOMPLETE` — a
half-declaration is no declaration); (c) a `pinned date` older than
`--max-pin-age-days` (default 90) fails (`MIRROR_PIN_STALE` — *"legalized
drift expires and must be re-affirmed or healed"*). `init` refuses to
overwrite a live declaration.

*Hardened 2026-06-10 (second refuter pass):* expiry was OPT-OUT twice over —
omitting the `pinned date` column disabled staleness entirely (even at
`--max-pin-age-days 0`), and a FUTURE date (2099-01-01) gave negative age so
staleness could never fire. `pinned date` is now a REQUIRED column (missing
column fails the header check; a blank cell fails the row as incomplete) and
a forward-dated pin fails `MIRROR_PIN_FUTURE`. Expiry is unavoidable: with
no parent fetch in v0, the pin clock is the backstop that keeps self-declared
hashes from becoming permanently-legal drift.

*Honest OPENs (stated in the module docstring):* cross-repo parent fetch is
out of scope in v0 — the gate verifies the LOCAL side only; whether the
pinned parent SHA still names real content, or the parent moved on, is
unchecked (auth design unbuilt; Constable cadence). And the gate checks only
DECLARED rows — an undeclared mirror is invisible (§5).

**Verdict:** PARTIAL. Legalization now costs bytes-pinning and ALWAYS
expires; the parent-side diff and undeclared-copy detection are OPEN.

### 4.13 Enrollment escape

*The vector:* nothing forces a NEW producer to enroll in a conformance
battery at all — producer #5 never registers and the battery stays green
over 4; the gate's universe is enumerated by the agents it polices.

*What v0 ships:* nothing mechanical against it — the batteries the vector
targets are unbuilt (§4.5), and the agreed closed-world tripwires (fail CI
on unenrolled files matching slug-shaped signals; AST-walk app modules for
webhook-shaped routes absent from the manifest; only-grows ratchets on
manifest lists) are unbuilt with them. The same shape exists one level up —
a repo that never mounts the caller stub is outside every gate — handled
procedurally: the rollout mounts all managed repos; the Constable's weekly
sweep audits floor presence. For the sticky intro specifically, enrollment
IS gated once mounted: `cf-sticky-check` fails a mounted repo whose
`CLAUDE.md` lost or chewed the block.

**Verdict:** OPEN at the battery level (with the carrier-level mitigation
procedural), closed only for the sticky-intro artifact on mounted repos.

---

## 5. Open issues — what v0 honestly does not close

Everything below is a known gap, on the record. Ordered by blood.

1. **The jscpd wiring (§4.4)** — the attribution wrapper (full-tree scan ∩
   PR-added line ranges), PR diff mode + nightly full scan, the ≥30-line
   absolute backstop, the clone-fingerprint baseline, and the workflow step.
   v0 ships only the two profile configs. The clone gate is currently prose.
2. **CC laundering (§4.2)** — no totality metric; per-function counters
   reset on split. Candidate wires: per-module cognitive sum; the clone gate
   as cross-check once wired.
3. **The conformance batteries (§4.5, §4.13)** — ErrorDetail wire-shape and
   slug-contract kits, production-path binding (`conformance.toml` +
   import-linter), machine-derived dialect fingerprints, and the enrollment
   tripwires. The 7-copies/~5-dialects drift stands unguarded.
4. **The money-seam kit (§4.7)** — entirely unbuilt; both known in-memory
   money stores are ungated. Acceptance is pre-registered RED on them.
5. **Security engines (§4.6)** — full bandit (unported rules), pip-audit
   with the expiry-capped ignore wrapper (≤90-day horizons), and the
   findings-set ratchet are not workflow steps. ruff-S is the only security
   wire live today.
6. **Release tag guard** — the plan's floor carries "release refuses
   tag != pyproject.version"; no such step exists in either workflow yet.
7. **complexipy in CI (§4.11)** — the watermark is runbook-only; no workflow
   step, and re-snapshot-on-merge is manual. Improvements are not locked in
   mechanically.
8. **ruff-sync check (§4.9)** — not installed, not a step; vendored-gauge
   content fidelity is unforced unless the consumer mirror-declares it.
9. **Required-status-check mounting + canary (§4.8)** — rulesets and the
   failing mount canary are procedure (runbook + Constable), not mechanism;
   caller-side `paths:` filters and `continue-on-error` stay invisible.
10. **Undeclared mirrors (§4.12)** — the gate verifies only DECLARED rows;
    a repo holding real cross-repo copies that simply never lists them is
    green (refuter d8: an empty/template `MIRRORS.md` passes). The gate
    trusts the repo's self-enumeration. Candidate closure: a fingerprint
    scanner (filename/content match against known parent artifacts) flagging
    likely-undeclared mirrors, on Constable cadence.
    (The 2026-06-10 refuter's sibling holes — OPTIONAL pinned date and
    FUTURE-dated pins — are CLOSED: the date column is required and a
    forward-dated pin fails `MIRROR_PIN_FUTURE`.)
11. **Cross-repo parent fetch (§4.12)** — stale-parent detection and the
    auth design for private parent repos: unbuilt; Constable cadence.
12. **`type: ignore` volume ratchet (§4.10)** — not built; consumer
    per-module mypy overrides have no vehicle while CI uses the kit's config.
13. **Greenfield package growth (§4.1)** — the package draw is
    relocation-only: it engages only for directories holding a >500 offender
    at `init` time, so a greenfield burn authoring N sub-500 sibling files
    in a fresh package is never package-budgeted (refuter attack 2: five
    499-line `engine_*.py` siblings, 2495 lines, green). Bounded today by
    the per-function gates + review; an aggregate per-directory ceiling
    needs a measured anchor before it can be a budget (budgets are measured,
    never invented). Disclosed in the module docstring, pinned by test.
14. **Exemption entry swap (§4.11)** — `frozen_count` is a count; a 1-for-1
    registry swap is review-visible, not machine-refused. (The collision
    UNDERCOUNT is closed: qualified symbols + `EXEMPTION_ENTRY_OVERLOADED`
    force a 1:1 entry-to-suppression map.)
15. **Mutual recursion (`a -> b -> a`)** — `cf-recursion-check` detects
    genuine SELF-recursion only; call-graph cycles are a v2 feature, pinned
    by tests as a declared limitation. Same family, same verdict for the
    refuter's module-qualified self-call (`_self_mod.descend(n-1)` via
    `sys.modules[__name__]`): genuine recursion needing dataflow analysis
    this AST gate does not do — disclosed in the HONEST OPEN, pinned by
    test. (The dynamic-class receivers `type(self).f` / `self.__class__.f`
    ARE detected as of 2026-06-10.)
16. **`file-budget` purpose self-service (§4.1)** — the declared-new-file
    escape is reviewed, not approver-gated; aligning it with the five-field
    `exemptions.json` shape is a candidate hardening.
17. **Sticky-intro salience heuristic (§4.13, sticky-check)** — the
    2026-06-10 hardening detects chewed headings, buried (HTML-comment /
    fenced) copies, duplicates, and a keyword set of neutralizing wrappers
    ("deprecated", "does not apply", "ignore", ...). Keyword salience is a
    heuristic, not prose understanding: a paraphrased neutralizer passes the
    gate. Full salience is a reading task — review and the scanning models
    carry it; disclosed in the module docstring.

## 6. Declared source roots (monorepo layouts)

The 9-repo mount wave measured the gap: the gate assumed the package sits at
the repo root (`src/` discovery), so a monorepo with the package in a subdir
(`server/`) drew a **vacuous mypy gate** and an **un-importable pytest** —
green by emptiness, the exact lie the kit exists to refuse.

**The mechanism.** Layout is declared in COMMITTED repo state — a
`[tool.cf-quality]` table in `pyproject.toml` or in a dedicated
`.cf-quality.toml` at the repo root (one home only; both at once fails
`GATE_CONFIG_INVALID`). Two keys: `source_root` (the tree the type gate
measures; also the no-args default of `cf-recursion-check`) and `package_dir`
(where the installable package + its pytest config live; the gate installs
and runs pytest from there). `cf-repo-config source-root|package-dir`
resolves it for the workflow. The **zero-workflow-inputs doctrine is intact**:
this is committed, reviewed consumer state riding the same PR as the code it
describes — never a caller knob, so it cannot neuter the gate from a stub.

**Anti-gaming — the empty-room rule.** A *declared* `source_root` that does
not exist, escapes the repo, or holds **zero `.py` files** fails typed
(`GATE_CONFIG_INVALID`) before anything is graded: pointing the gauge at an
empty room is a violation, not a pass. A declared `package_dir` must carry a
`pyproject.toml` (an uninstallable package dir is the same empty room), and
unknown keys fail typed (a typo'd key silently ignored would be drift).
Absent declaration keeps the historical discovery exactly — `src/` when
present, else the repo root — and `mypy-baseline.txt` stays root-anchored.

Honest residue: a declared root holding one trivial `.py` while the real
code lives elsewhere passes the resolver — the floor is non-emptiness, not
completeness; review and the repo-root-wide gates (ruff, file-budget,
exemptions, recursion at `.`) still measure the whole tree.

---

*The kit obeys the law it enforces: every function CC ≤ 10 and ≤ 50
statements, every file ≤ 500 lines, 0 mypy errors at baseline zero, typed
errors throughout; `self-ci.yml` runs the battery on this repo first.
Budgets are anchored to measurement (canon ADR 0029), tunable without
reopening it. Completion is not declared here — the Stone Law holds.*
