"""The cognitive-complexity ratchet, graded HERE — because the tool eats its own floor.

**The measured defect.** ``complexipy-snapshot.json`` is the committed floor: the
per-function cognitive-complexity watermark no later run may exceed. In the
pinned ``complexipy==5.6.0`` the tool's OWN snapshot comparison ends, on success,
in a REWRITE of that file — ``complexipy/utils/snapshot.py:85``
``handle_snapshot_watermark`` returns ``True`` only after calling
``create_snapshot_file(...)`` with the functions IT measured this run. The tool's
green path *is* the destructive path, and two ordinary runs reproduce it at exit
0: a **narrowed surface** (``complexipy <one-low-complexity-file>`` measures a
subset, finds no violation, rewrites the floor to that subset — a populated
snapshot observed going ``1 entry -> []``) and a **raised threshold**
(``complexipy <tree> -mx 100`` puts everything under the bar, same rewrite).
Either one, committed, deletes the floor forever behind a green gate.

**Why this module rather than a before/after repair.** Detecting the rewrite and
restoring the file would still let it happen, and would only work *because* the
tool destroys the artifact: the moment the write does not occur — a crash between
compare and write, a release that stops rewriting, a run that never reached the
compare — a before/after diff of the file is identical and the narrowed surface
goes invisible again. So the fix sits upstream of the write:

1. **The gate never lets the tool near the artifact.** The write-free invocation
   and the audit that makes it genuinely write-free live in
   :mod:`cf_quality.complexipy_measure`; its docstring carries the two
   ``create_snapshot_file`` call sites and the config key that would re-open the
   second one. The floor itself has exactly one reader,
   :mod:`cf_quality.complexipy_floor`, which never writes.
2. **The ratchet is our pure function.** :func:`grade` maps (committed floor,
   measured census) to a :class:`~cf_quality.errors.GateVerdict` with no
   subprocess and no write in the path — unit-testable, and nothing a green run
   can silently destroy.
3. **complexipy is demoted to an instrument.** It answers two questions and
   grades nothing: ``--plain`` (every function measured, with its complexity)
   and ``--plain --failed`` (the subset ITS OWN threshold calls offenders). The
   second run is why the kit never re-declares a budget complexipy already
   resolves from its default / CLI / ``[tool.complexipy]`` config.

**Threshold-neutrality, and the vacuity that hid inside it.** Because the kit
declares no budget, a consumer who RAISES complexipy's threshold empties the
offender set — and the first cut of this fix then graded an empty dict against a
populated floor and reported clean. That is
``gate-that-selects-by-the-value-it-guards-goes-vacuous`` inside the fix for it.
:func:`_bar_moved` closes it without naming a threshold: a floor entry proves
that function was ABOVE the bar when the floor was booted, so if its census value
still sits at-or-above its watermark and yet the offender run does not report it,
then ``threshold_now >= census >= watermark > threshold_at_boot`` — the bar moved,
provable from the census and the floor alone. The offender run's exit code is the
second, independent leg (``complexipy_measure._refuse_instrument_failure``).

**The taxonomy.** Findings (exit 1, the repo's to fix): ``COMPLEXIPY_NEW_OFFENDER``
and ``COMPLEXIPY_WATERMARK_REGRESSION`` (complexipy's own watermark rule over data
we own); ``COMPLEXIPY_SURFACE_NARROWED``, ``COMPLEXIPY_SNAPSHOT_FILE_UNMEASURED``
and ``COMPLEXIPY_SNAPSHOT_FUNCTION_UNMEASURED`` (the floor names a file, or a
function inside a measured file, this run did not grade — the narrowed-surface
trigger, caught structurally, independent of any threshold). Refusals (exit 2,
the gate could not do its job): ``GATE_COMPLEXIPY_SNAPSHOT_UNREADABLE``,
``GATE_COMPLEXIPY_MEASUREMENT_SKEW``, ``GATE_COMPLEXIPY_THRESHOLD_RAISED``,
``GATE_COMPLEXIPY_MEASURED_NOTHING``, plus the instrument-side refusals
:mod:`cf_quality.complexipy_measure` raises. A legitimate improvement — a
function that got simpler, a deleted file — is GREEN; only re-booting the floor
locks it in, which stays the existing runbook duty.

The absent-watermark doctrine is unchanged and stays in the caller
(``gate_runner._complexipy``): no snapshot + Python present REFUSES
``GATE_COMPLEXIPY_SNAPSHOT_MISSING``; a Python-free repo skips, visibly.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

from cf_quality.complexipy_floor import SNAPSHOT_FILENAME, read_snapshot
from cf_quality.complexipy_measure import (
    Census,
    Executor,
    FunctionKey,
    audit_config,
    measure,
    refusal,
)
from cf_quality.errors import GateError, GateVerdict, GateViolation

#: The stage name every verdict from this module carries.
GATE = "complexipy"


class _Layout(Protocol):
    """The resolved consumer layout this stage reads (``gate_runner.Layout``).

    Structural, and read-only by declaration so a frozen dataclass satisfies it:
    importing ``gate_runner.Layout`` would close an import cycle, since
    ``gate_runner`` imports this module. ``py_present`` is threaded rather than
    re-derived on purpose — the caller already computes the repo-wide answer for
    the absent-snapshot doctrine, and a second local derivation is how the two
    surfaces came to disagree (a Python-free tree under a present-but-empty
    ``src/`` was reported PASS having measured nothing).
    """

    @property
    def root(self) -> Path: ...
    @property
    def source_root(self) -> Path: ...
    @property
    def py_present(self) -> bool: ...


def _reboot(graded: str) -> str:
    """The re-boot command, named as the remedy — a condition with no remedy is half a message."""
    return f"re-boot the floor from the repo root: complexipy {graded} --snapshot-create"


def _counts(
    floor: Mapping[FunctionKey, int], census: Census, offenders: Census
) -> dict[str, object]:
    """The measured tally every finding, refusal and PASS carries — never a bare verdict.

    ``measured_functions`` is the ROW count, not the key count: they differ
    wherever a ``(path, name)`` pair repeats, and reporting keys would under-state
    the very measurement this evidence exists to prove.
    """
    return {
        "measured_functions": census.rows,
        "measured_keys": len(census.functions),
        "measured_files": len(census.files),
        "measured_offenders": offenders.rows,
        "snapshot_functions": len(floor),
        "snapshot_files": len({path for path, _ in floor}),
    }


def _violation(
    code: str, message: str, path: str, counts: Mapping[str, object], **detail: object
) -> GateViolation:
    return GateViolation(code=code, message=message, path=path, context={**counts, **detail})


def _regressions(
    floor: Mapping[FunctionKey, int],
    offenders: Census,
    counts: Mapping[str, object],
    reboot: str,
) -> list[GateViolation]:
    """complexipy's own watermark rule, applied to data the tool cannot rewrite.

    Mirrors ``handle_snapshot_watermark`` exactly, including the ``>`` bound — a
    function sitting AT its watermark passes; only rising above it fails.
    """
    violations: list[GateViolation] = []
    for (path, name), value in sorted(offenders.functions.items()):
        watermark = floor.get((path, name))
        if watermark is None:
            code = "COMPLEXIPY_NEW_OFFENDER"
            message = (
                f"{name} exceeds complexipy's threshold at {value} with no committed "
                f"watermark — split it below the threshold, or baseline it deliberately: {reboot}"
            )
        elif value > watermark:
            code = "COMPLEXIPY_WATERMARK_REGRESSION"
            message = (
                f"{name} rose above its committed watermark: {watermark} -> {value} — bring "
                f"it back to {watermark} or below; raising the floor instead is a deliberate, "
                f"reviewed act: {reboot}"
            )
        else:
            continue
        violations.append(_violation(code, message, path, counts, function=name, measured=value))
    return violations


def _graded_prefix(root: Path, source_root: Path) -> str | None:
    """The graded root as a repo-relative POSIX prefix (``""`` == the whole repo).

    The ROOTS are resolved, never the file: resolving the file sent a symlinked
    module (``src/settings.py -> ../config/settings.py``) outside the graded root
    and made the gate accuse a file complexipy really did measure of lying outside
    the surface. The floor's own paths are already repo-relative, so containment
    is a lexical test on those. ``None`` means the graded root is not inside the
    repo at all, and the truthful reading of that is "every floor path is outside
    it" — not a crash, and not a pass.
    """
    try:
        relative = source_root.resolve().relative_to(root.resolve())
    except ValueError:
        return None
    text = relative.as_posix()
    return "" if text == "." else text


def _inside(path: str, prefix: str | None) -> bool:
    """Is this repo-relative path inside the graded prefix? Lexical, by design."""
    if prefix is None:
        return False
    return prefix == "" or path == prefix or path.startswith(f"{prefix}/")


def _unmeasured_functions(
    path: str,
    floor: Mapping[FunctionKey, int],
    census: Census,
    counts: Mapping[str, object],
    reboot: str,
) -> list[GateViolation]:
    """Floor functions missing from a file this run DID measure.

    The distinction that makes this honest: ``--plain`` without ``--failed`` lists
    every measured function regardless of threshold, so a function that merely got
    SIMPLER is still in the census. Absence from a measured file therefore means
    it was renamed, deleted, or dropped by a ``# complexipy: ignore`` comment —
    and that last one is an unregistered, unblessed exemption from the complexity
    gate, invisible to ``cf-exemptions`` (whose noqa pattern needs a coded id) and
    invisible to a per-FILE audit, because the file is still in ``census.files``.
    """
    return [
        _violation(
            "COMPLEXIPY_SNAPSHOT_FUNCTION_UNMEASURED",
            f"{name} carries a committed watermark of {watermark} but was not measured, "
            f"while {path} WAS — a function that merely got simpler would still be in the "
            f"census, so this was renamed, deleted, or dropped by a '# complexipy: ignore' "
            f"comment; remove the ignore comment, or {reboot}",
            path,
            counts,
            function=name,
            watermark=watermark,
        )
        for (entry_path, name), watermark in sorted(floor.items())
        if entry_path == path and (entry_path, name) not in census.functions
    ]


def _surface_violations(
    layout: _Layout,
    floor: Mapping[FunctionKey, int],
    census: Census,
    counts: Mapping[str, object],
    reboot: str,
) -> list[GateViolation]:
    """Every floor entry that still EXISTS must have been measured this run.

    The narrowed-surface trigger caught head-on, independent of any threshold: a
    snapshot entry is proof that function HELD an over-threshold complexity, so a
    run that produced no measurement for it graded a smaller world than the floor
    describes. A file that is GONE is a legitimate improvement and is passed over.
    Per-FILE where the whole file went unmeasured, then per-FUNCTION inside the
    files that were measured — the second half is what a ``# complexipy: ignore``
    comment used to slip through.
    """
    violations: list[GateViolation] = []
    prefix = _graded_prefix(layout.root, layout.source_root)
    for path in sorted({path for path, _ in floor}):
        if not (layout.root / path).is_file():
            continue
        if not _inside(path, prefix):
            violations.append(
                _violation(
                    "COMPLEXIPY_SURFACE_NARROWED",
                    f"the floor covers {path}, which lies OUTSIDE the graded source root "
                    f"({prefix or '.'}) — widen the declared source_root, or {reboot}",
                    path,
                    counts,
                    source_root=str(layout.source_root),
                )
            )
        elif path not in census.files:
            violations.append(
                _violation(
                    "COMPLEXIPY_SNAPSHOT_FILE_UNMEASURED",
                    f"{path} carries a committed watermark but NO function in it was "
                    f"measured — it is excluded, ignore-commented, or now functionless; "
                    f"restore it to the measured surface, or {reboot}",
                    path,
                    counts,
                    source_root=str(layout.source_root),
                )
            )
        else:
            violations.extend(_unmeasured_functions(path, floor, census, counts, reboot))
    return violations


def _skew(census: Census, offenders: Census, counts: Mapping[str, object]) -> GateError | None:
    """The two write-free runs must describe ONE world.

    The offender set is a filter of the census, so every offender must appear in
    the census at the same complexity. A disagreement means the tree changed
    between the runs, or a flag moved the measurement surface — either way the
    comparison inputs are not a single observation and must not be graded. Both
    sides aggregate ``max()`` per key, so a repeated ``(path, name)`` pair can no
    longer fake a skew by landing its high value in only one of the two maps.
    """
    disagreements = sorted(
        f"{path}:{name}"
        for (path, name), value in offenders.functions.items()
        if census.functions.get((path, name)) != value
    )
    if not disagreements:
        return None
    return refusal(
        "GATE_COMPLEXIPY_MEASUREMENT_SKEW",
        f"{len(disagreements)} function(s) reported by the offender run are absent from "
        "(or disagree with) the census run — the two measurements are not one world, so "
        "the gate refuses to compare them; re-run on a quiescent tree, and if it repeats, "
        "look for a complexipy.toml moving the surface between the two runs",
        {**counts, "functions": disagreements[:10]},
    )


def _bar_moved(
    floor: Mapping[FunctionKey, int],
    census: Census,
    offenders: Census,
    counts: Mapping[str, object],
    reboot: str,
) -> GateError | None:
    """The offender census's vacuity leg — threshold-free, from data already in hand.

    A floor entry is proof that function was ABOVE complexipy's threshold when the
    floor was booted (``create_snapshot_file`` stores only over-threshold
    functions). So if the census still measures it at-or-above its watermark and
    the offender run does NOT report it, then
    ``threshold_now >= census >= watermark > threshold_at_boot``: the bar moved
    since the floor was booted, and every regression rule downstream is grading a
    set the raised bar emptied. Refusing needs no second threshold authority — the
    kit still declares no budget of its own, which is the property that made this
    hole possible and is worth keeping.

    A hand-lowered watermark lands here too, correctly: complexipy would never
    have written a watermark at or below its own threshold, so such an entry is
    itself evidence the floor was not produced by the boot command.
    """
    stranded = sorted(
        f"{path}:{name} (measured {census.functions[(path, name)]} >= watermark {watermark})"
        for (path, name), watermark in floor.items()
        if (path, name) in census.functions
        and census.functions[(path, name)] >= watermark
        and (path, name) not in offenders.functions
    )
    if not stranded:
        return None
    return refusal(
        "GATE_COMPLEXIPY_THRESHOLD_RAISED",
        f"{len(stranded)} committed watermark(s) are at-or-below what complexipy now "
        "calls acceptable, so its offender set no longer covers the floor — the ratchet "
        "would grade nothing and report clean. complexipy's threshold has been raised "
        "since the floor was booted (or a watermark was hand-lowered): restore "
        f"max-complexity-allowed, or {reboot} at the threshold you intend",
        {**counts, "functions": stranded[:10]},
    )


def _vacuity(
    layout: _Layout,
    floor: Mapping[FunctionKey, int],
    census: Census,
    counts: Mapping[str, object],
    reboot: str,
) -> GateError | None:
    """A run that measured nothing can never report clean.

    Two independent legs, so the refusal survives an ALREADY-emptied floor: a
    committed floor that still names functions, or a repo that contains Python at
    all. The second leg is the CALLER's repo-wide answer (``layout.py_present``),
    the same one the absent-snapshot doctrine rides — not a local walk of
    ``source_root``, which was blind exactly when ``source_root`` was the wrong
    tree (code in ``app/`` beside an empty-but-present ``src/``, floor ``[]``:
    zero functions measured, PASS). Consulting one answer is what stops the two
    surfaces from diverging; it is also strictly stricter, since a repo whose only
    Python defines no functions now refuses instead of certifying a void.
    """
    if census.rows:
        return None
    if not floor and not layout.py_present:
        return None
    return refusal(
        "GATE_COMPLEXIPY_MEASURED_NOTHING",
        "complexipy measured zero functions while there was something to grade — a gate "
        "that measured nothing cannot report a clean floor. Check the resolved source "
        f"root ({layout.source_root}) actually holds the code, and any complexipy "
        f"exclude/ignore configuration; if the tree really did move, {reboot}",
        {**counts, "source_root": str(layout.source_root), "python_present": layout.py_present},
    )


def grade(
    layout: _Layout,
    floor: Mapping[FunctionKey, int],
    census: Census,
    offenders: Census,
    *,
    config: str | None = None,
) -> GateVerdict:
    """The whole ratchet as a pure function of (committed floor, measured world).

    No subprocess, no write — which is the property the tool's own comparison
    cannot have, because its green path IS the rewrite. Every finding and refusal
    carries the measured tally, and so does a PASS: the counts ride the verdict's
    ``evidence`` and one notice rides its ``notices``, so a machine reading the
    aggregated JSON can tell a clean grade from a vacuous one without re-running
    anything. Refusal order is deliberate — a skewed pair must not be reasoned
    over, and a raised bar must be named before the emptied offender set is
    mistaken for a quiet one.
    """
    counts = _counts(floor, census, offenders)
    reboot = _reboot(_graded_prefix(layout.root, layout.source_root) or ".")
    violations = _regressions(floor, offenders, counts, reboot)
    violations.extend(_surface_violations(layout, floor, census, counts, reboot))
    error = (
        _skew(census, offenders, counts)
        or _bar_moved(floor, census, offenders, counts, reboot)
        or _vacuity(layout, floor, census, counts, reboot)
    )
    return GateVerdict(
        gate=GATE,
        violations=violations,
        error=error,
        notices=[
            f"— measured {census.rows} function(s) in {len(census.files)} file(s) against a "
            f"{len(floor)}-function committed floor"
        ],
        evidence={**counts, "complexipy_config": config},
    )


def complexipy_verdict(
    layout: _Layout,
    env: Mapping[str, str],
    tool: Path,
    executor: Executor,
) -> GateVerdict:
    """Audit the consumer's config, measure the tree write-free, then grade in our code.

    Order is load-bearing. The config audit runs FIRST because it is what makes
    the two measurement runs write-free at all; grading the pre-write bytes of a
    floor a later run rewrote is precisely the green-with-the-artifact-mutated
    world the refuters found. The caller has already enforced the absent-watermark
    doctrine, so the floor exists here. A GateError from the audit or either
    measurement propagates as the stage's refusal, which the battery records and
    continues past.
    """
    config = audit_config(layout.root)
    floor = read_snapshot(layout.root / SNAPSHOT_FILENAME)
    census = measure(layout.root, layout.source_root, env, tool, executor, offenders_only=False)
    offenders = measure(layout.root, layout.source_root, env, tool, executor, offenders_only=True)
    return grade(layout, floor, census, offenders, config=config)
