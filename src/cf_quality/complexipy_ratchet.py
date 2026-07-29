"""The cognitive-complexity ratchet, graded HERE — because the tool eats its own floor.

**The measured defect.** ``complexipy-snapshot.json`` is the committed floor: the
per-function cognitive-complexity watermark no later run may exceed. In the
pinned ``complexipy==5.6.0`` the tool's OWN snapshot comparison ends, on success,
in a REWRITE of that file — ``complexipy/utils/snapshot.py``
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

1. **The gate never lets the tool near the artifact.** Both measurement
   invocations carry ``--snapshot-ignore``. In the pinned source the ONLY two
   callers of ``create_snapshot_file`` are ``--snapshot-create`` (never passed)
   and the watermark compare's success path (which ``--snapshot-ignore`` switches
   off by making ``should_run_snapshot_watermark`` False). The committed floor is
   therefore READ by this module and written by nobody.
2. **The ratchet is our pure function.** :func:`grade` maps (committed floor,
   measured census) to a :class:`~cf_quality.errors.GateVerdict` with no
   subprocess, no write and no tool exit code in the path — unit-testable, and
   nothing a green run can silently destroy.
3. **complexipy is demoted to a measuring instrument.** It answers two questions
   and grades nothing: ``--plain`` (every function measured, with its complexity)
   and ``--plain --failed`` (the subset ITS OWN threshold calls offenders). The
   second run is why the kit never re-declares a budget complexipy already
   resolves from its default / CLI / ``[tool.complexipy]`` config — a second
   threshold authority here would flag a consumer's baselined band as new.

**The taxonomy.** Findings (exit 1, the repo's to fix): ``COMPLEXIPY_NEW_OFFENDER``
and ``COMPLEXIPY_WATERMARK_REGRESSION`` (complexipy's own watermark rule over data
we own), ``COMPLEXIPY_SURFACE_NARROWED`` and ``COMPLEXIPY_SNAPSHOT_FILE_UNMEASURED``
(the floor names a file this run did not grade — the narrowed-surface trigger,
caught structurally, independent of any threshold). Refusals (exit 2, the gate
could not do its job): ``GATE_COMPLEXIPY_SNAPSHOT_UNREADABLE``,
``GATE_COMPLEXIPY_PATHS_UNMEASURABLE``, ``GATE_COMPLEXIPY_OUTPUT_UNREADABLE``,
``GATE_COMPLEXIPY_MEASUREMENT_SKEW``, ``GATE_COMPLEXIPY_MEASURED_NOTHING``. A
legitimate improvement — a function that got simpler, a deleted file — is GREEN;
only re-booting the floor locks it in, which stays the existing runbook duty.

The absent-watermark doctrine is unchanged and stays in the caller
(``gate_runner._complexipy``): no snapshot + Python present REFUSES
``GATE_COMPLEXIPY_SNAPSHOT_MISSING``; a Python-free repo skips, visibly.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from cf_quality.errors import GateError, GateVerdict, GateViolation

#: The stage name every verdict from this module carries.
GATE = "complexipy"

#: The committed floor's filename (CWD-relative for complexipy, repo root for us).
SNAPSHOT_FILENAME = "complexipy-snapshot.json"

#: ``(repo-relative file, function name)`` — the identity a watermark is keyed by.
#: complexipy keys on ``(path, file_name, name)``; ``path`` already carries the
#: file name in its own output, so the joined form is the same identity.
FunctionKey = tuple[str, str]

#: Environment pinned onto every measurement run. ``COLUMNS`` is load-bearing:
#: ``--plain`` prints through rich, which wraps at 80 columns when stdout is not
#: a terminal, and a wrapped census row is an unparseable census row.
#: ``PYTHONIOENCODING`` pins UTF-8 so the census does not decode by locale.
_MEASURE_ENV = {"COLUMNS": "10000", "PYTHONIOENCODING": "utf-8", "NO_COLOR": "1"}

#: complexipy's own words when it could not analyze a path it was handed
#: (``complexipy.utils.output.print_invalid_paths``) — a silently narrower surface.
_UNMEASURABLE_MARKER = "Failed to process"


class _Executor(Protocol):
    """The subprocess seam the caller injects (``gate_runner._exec``).

    Structural, not inherited: the runner stays the caller's — one place owns
    typed OSError translation and the no-shell fixed-argv discipline — while the
    tests keep patching that single seam.
    """

    def __call__(
        self,
        argv: list[str],
        cwd: Path,
        env: Mapping[str, str],
        *,
        stdin: str | None = None,
    ) -> subprocess.CompletedProcess[str]: ...


@dataclass(frozen=True)
class Census:
    """What ONE write-free complexipy run actually measured.

    The census is the gate's independent fact about its own measurement surface:
    it is read from the tool's output, never from the snapshot, so "the floor is
    empty" and "we graded nothing" can never be the same observation.
    """

    functions: dict[FunctionKey, int]

    @property
    def files(self) -> frozenset[str]:
        """The distinct files this run measured — the surface audit's evidence."""
        return frozenset(path for path, _ in self.functions)


def _gate_error(code: str, message: str, context: dict[str, object]) -> GateError:
    """A refusal in the kit's typed vocabulary — the gate could not do its job."""
    return GateError(code=code, message=message, context=context)


def _normalized_path(path: str, file_name: str) -> str:
    """Join a snapshot entry's two path fields the way complexipy's output does.

    Declared mirror of ``complexipy.utils.output.normalize_path`` (pinned 5.6.0):
    the snapshot stores ``path`` and ``file_name`` separately while ``--plain``
    prints the joined form. Join them differently and every committed watermark
    looks like a brand-new offender.
    """
    cleaned = path.rstrip("/")
    if cleaned.endswith(file_name):
        return cleaned
    return f"{cleaned}/{file_name}" if cleaned else file_name


def _refuse_snapshot(snapshot: Path, reason: str) -> GateError:
    return _gate_error(
        "GATE_COMPLEXIPY_SNAPSHOT_UNREADABLE",
        f"{SNAPSHOT_FILENAME} is not a readable complexipy snapshot: {reason} — "
        "re-boot it (complexipy <source-root> --snapshot-create); an unreadable "
        "floor is not an empty floor",
        {"snapshot": str(snapshot), "reason": reason},
    )


def _entry_watermarks(entry: object, snapshot: Path) -> dict[FunctionKey, int]:
    """One snapshot entry's watermarks; any other shape REFUSES rather than skips."""
    if not isinstance(entry, dict) or not isinstance(entry.get("functions"), list):
        raise _refuse_snapshot(snapshot, f"entry is not {{path, file_name, functions}}: {entry!r}")
    path = _normalized_path(str(entry.get("path", "")), str(entry.get("file_name", "")))
    watermarks: dict[FunctionKey, int] = {}
    for function in entry["functions"]:
        if not isinstance(function, dict) or not isinstance(function.get("complexity"), int):
            raise _refuse_snapshot(snapshot, f"function is not {{name, complexity}}: {function!r}")
        watermarks[(path, str(function.get("name", "")))] = int(function["complexity"])
    return watermarks


def read_snapshot(snapshot: Path) -> dict[FunctionKey, int]:
    """The committed floor as ``{(file, function): watermark}``.

    This is the ONLY code that touches the artifact, and it only reads. A
    malformed snapshot REFUSES: treating it as an empty floor would be
    green-by-unreadable-file, the same gaming vector as green-by-missing-file
    (which this gate already refuses).
    """
    try:
        raw = json.loads(snapshot.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise _refuse_snapshot(snapshot, str(exc)) from exc
    if not isinstance(raw, list):
        raise _refuse_snapshot(snapshot, f"top level is {type(raw).__name__}, not a list")
    floor: dict[FunctionKey, int] = {}
    for entry in raw:
        floor.update(_entry_watermarks(entry, snapshot))
    return floor


def _census_row(line: str) -> tuple[FunctionKey, int] | None:
    """``<path.py> <function> <complexity>`` -> the keyed measurement, else None.

    Split from the RIGHT: the complexity and the function name are single tokens
    while a path may contain spaces, so ``rsplit`` is the only safe direction.
    """
    parts = line.strip().rsplit(maxsplit=2)
    if len(parts) != 3 or not parts[0].endswith(".py"):
        return None
    try:
        complexity = int(parts[2])
    except ValueError:
        return None
    return (parts[0], parts[1]), complexity


def parse_census(stdout: str) -> Census:
    """complexipy ``--plain`` stdout -> the measured census.

    ``--plain`` is complexipy's documented scripting form: one
    ``<path> <function> <complexity>`` line per function it measured, over
    threshold or not. A non-blank line that is not a census row REFUSES instead
    of being dropped — an unreadable census and an empty one look identical from
    a count, and the empty one is the exact world this gate exists to catch.
    """
    functions: dict[FunctionKey, int] = {}
    unreadable: list[str] = []
    for line in stdout.splitlines():
        row = _census_row(line)
        if row is not None:
            functions[row[0]] = row[1]
        elif line.strip():
            unreadable.append(line.strip())
    if unreadable:
        raise _gate_error(
            "GATE_COMPLEXIPY_OUTPUT_UNREADABLE",
            f"complexipy --plain emitted {len(unreadable)} line(s) that are not "
            "'<path> <function> <complexity>' — the census cannot be trusted, so "
            "the floor cannot be graded",
            {"lines": unreadable[:10], "measured_functions": len(functions)},
        )
    return Census(functions=functions)


def measurement_argv(tool: Path, source_root: Path, *, offenders_only: bool) -> list[str]:
    """The write-free measurement command — the root of the fix, not a nicety.

    ``--snapshot-ignore`` makes ``should_run_snapshot_watermark`` False in the
    pinned tool, which is the only path (besides the never-passed
    ``--snapshot-create``) that reaches ``create_snapshot_file``. This argv
    therefore CANNOT write ``complexipy-snapshot.json``. ``--failed`` narrows the
    census to the functions complexipy's own resolved threshold calls offenders,
    so the kit never states a complexity budget of its own here.
    """
    argv = [str(tool), str(source_root), "--plain", "--color", "no", "--snapshot-ignore"]
    if offenders_only:
        argv.append("--failed")
    return argv


def _measure(
    root: Path,
    source_root: Path,
    env: Mapping[str, str],
    tool: Path,
    executor: _Executor,
    *,
    offenders_only: bool,
) -> Census:
    """Run one write-free measurement from the repo root and read its census.

    cwd is the repo root deliberately: complexipy resolves both its config and
    its reported paths against the invocation directory, so measuring from
    anywhere else would re-key every path and break the comparison. The exit
    code is NOT consulted — with the compare switched off it merely restates
    "some function is over threshold", which is the normal state of a repo
    carrying a baselined floor.
    """
    argv = measurement_argv(tool, source_root, offenders_only=offenders_only)
    proc = executor(argv, root, {**env, **_MEASURE_ENV})
    lines = [line.strip() for line in proc.stdout.splitlines()]
    unmeasurable = [line for line in lines if _UNMEASURABLE_MARKER in line]
    if unmeasurable:
        raise _gate_error(
            "GATE_COMPLEXIPY_PATHS_UNMEASURABLE",
            f"complexipy could not analyze {len(unmeasurable)} path(s) — the graded "
            "surface is narrower than the tree, so a clean verdict would be a void",
            {"paths": unmeasurable[:10], "exit_code": proc.returncode},
        )
    return parse_census(proc.stdout)


def _counts(
    floor: Mapping[FunctionKey, int], census: Census, offenders: Census
) -> dict[str, object]:
    """The measured tally every finding and refusal carries — never a bare verdict."""
    return {
        "measured_functions": len(census.functions),
        "measured_files": len(census.files),
        "measured_offenders": len(offenders.functions),
        "snapshot_functions": len(floor),
        "snapshot_files": len({path for path, _ in floor}),
    }


def _violation(
    code: str, message: str, path: str, counts: Mapping[str, object], **detail: object
) -> GateViolation:
    return GateViolation(code=code, message=message, path=path, context={**counts, **detail})


def _regressions(
    floor: Mapping[FunctionKey, int], offenders: Census, counts: Mapping[str, object]
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
            message = f"{name} exceeds complexipy's threshold at {value}, no committed watermark"
        elif value > watermark:
            code = "COMPLEXIPY_WATERMARK_REGRESSION"
            message = f"{name} rose above its committed watermark: {watermark} -> {value}"
        else:
            continue
        violations.append(_violation(code, message, path, counts, function=name, measured=value))
    return violations


def _surface_violations(
    root: Path,
    source_root: Path,
    floor: Mapping[FunctionKey, int],
    census: Census,
    counts: Mapping[str, object],
) -> list[GateViolation]:
    """Every floor file that still EXISTS must have been measured this run.

    The narrowed-surface trigger caught head-on, independent of any threshold: a
    snapshot entry is proof that file HELD an over-threshold function, so a run
    that produced no measurement for it graded a smaller world than the floor
    describes. A file that is GONE is a legitimate improvement and is passed over;
    a file whose functions all vanished reads the same way and asks for the same
    remedy — re-boot the floor, deliberately, so the improvement is locked in.
    """
    violations: list[GateViolation] = []
    graded = source_root.resolve()  # both sides resolved, or a symlinked tmp lies
    for path in sorted({path for path, _ in floor}):
        on_disk = root / path
        if not on_disk.is_file():
            continue
        if not on_disk.resolve().is_relative_to(graded):
            code = "COMPLEXIPY_SURFACE_NARROWED"
            message = f"the floor covers {path}, which lies OUTSIDE the graded source root"
        elif path not in census.files:
            code = "COMPLEXIPY_SNAPSHOT_FILE_UNMEASURED"
            message = f"{path} carries a committed watermark but no function in it was measured"
        else:
            continue
        violations.append(_violation(code, message, path, counts, source_root=str(source_root)))
    return violations


def _module_defines_functions(path: Path) -> bool:
    """True when a module contains any ``def``/``async def``, by AST not by regex.

    Source we cannot read or parse counts as YES: a void must never certify
    itself, and we cannot prove a file is functionless from bytes we never
    parsed (complexipy would report such a path as unmeasurable anyway).
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError):
        return True
    return any(isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) for node in ast.walk(tree))


def _defines_functions(source_root: Path) -> bool:
    """True when the graded tree defines at least one function.

    Consulted only when the census came back EMPTY, so the common path never
    parses anything. Dotted directories are skipped, mirroring the workflow's
    own ``find . -not -path '*/.*'`` measurement surface.
    """
    for path in sorted(source_root.rglob("*.py")):
        parts = path.relative_to(source_root).parts
        if any(part.startswith(".") for part in parts):
            continue
        if _module_defines_functions(path):
            return True
    return False


def _skew(census: Census, offenders: Census, counts: Mapping[str, object]) -> GateError | None:
    """The two write-free runs must describe ONE world.

    The offender set is a filter of the census, so every offender must appear in
    the census at the same complexity. A disagreement means the tree changed
    between the runs, or a flag moved the measurement surface — either way the
    comparison inputs are not a single observation and must not be graded.
    """
    disagreements = sorted(
        f"{path}:{name}"
        for (path, name), value in offenders.functions.items()
        if census.functions.get((path, name)) != value
    )
    if not disagreements:
        return None
    return _gate_error(
        "GATE_COMPLEXIPY_MEASUREMENT_SKEW",
        f"{len(disagreements)} function(s) reported by the offender run are absent from "
        "(or disagree with) the census run — the two measurements are not one world",
        {**counts, "functions": disagreements[:10]},
    )


def _vacuity(
    census: Census,
    floor: Mapping[FunctionKey, int],
    source_root: Path,
    counts: Mapping[str, object],
) -> GateError | None:
    """A run that measured nothing can never report clean.

    Two independent legs, so the refusal survives an ALREADY-emptied floor: a
    committed floor that still names functions, or a graded tree that
    demonstrably defines functions. When both are empty there is genuinely
    nothing to grade and clean is the honest answer, not a void.
    """
    if census.functions:
        return None
    if not floor and not _defines_functions(source_root):
        return None
    return _gate_error(
        "GATE_COMPLEXIPY_MEASURED_NOTHING",
        "complexipy measured zero functions while there was something to grade — a "
        "gate that measured nothing cannot report a clean floor (check the resolved "
        f"source root {source_root} and any complexipy exclude/ignore configuration)",
        {**counts, "source_root": str(source_root)},
    )


def grade(
    root: Path,
    source_root: Path,
    floor: Mapping[FunctionKey, int],
    census: Census,
    offenders: Census,
) -> GateVerdict:
    """The whole ratchet as a pure function of (committed floor, measured world).

    No subprocess, no write, no tool exit code — which is the property the
    tool's own comparison cannot have, because its green path IS the rewrite.
    Every finding and refusal carries the measured tally, so a verdict can never
    be read without the count behind it.
    """
    counts = _counts(floor, census, offenders)
    violations = _regressions(floor, offenders, counts)
    violations.extend(_surface_violations(root, source_root, floor, census, counts))
    error = _skew(census, offenders, counts) or _vacuity(census, floor, source_root, counts)
    return GateVerdict(gate=GATE, violations=violations, error=error)


def _report_measured(floor: Mapping[FunctionKey, int], census: Census) -> None:
    """State the measured count out loud, on every run including a clean one.

    :class:`~cf_quality.errors.GateVerdict` carries no notices channel, so a
    PASSING stage would otherwise report a floor it never proves it measured.
    stderr keeps the aggregated JSON wire form on stdout untouched.
    """
    print(
        f"{GATE}: measured {len(census.functions)} function(s) in {len(census.files)} "
        f"file(s) against a {len(floor)}-function committed floor",
        file=sys.stderr,
    )


def complexipy_verdict(
    root: Path,
    source_root: Path,
    env: Mapping[str, str],
    tool: Path,
    executor: _Executor,
) -> GateVerdict:
    """Measure the tree write-free, then grade the ratchet in our own code.

    The caller has already enforced the absent-watermark doctrine, so the floor
    exists here. Two write-free runs (the full census, then complexipy's own
    offender subset) feed :func:`grade`; a GateError from either measurement
    propagates as the stage's refusal, which the battery records and continues.
    """
    floor = read_snapshot(root / SNAPSHOT_FILENAME)
    census = _measure(root, source_root, env, tool, executor, offenders_only=False)
    offenders = _measure(root, source_root, env, tool, executor, offenders_only=True)
    _report_measured(floor, census)
    return grade(root, source_root, floor, census, offenders)
