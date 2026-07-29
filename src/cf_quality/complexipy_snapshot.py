"""The complexipy ratchet's floor guard — a gate may not eat the oracle it grades.

MEASURED DEFECT (complexipy 5.6.0, reproduced with real hands 2026-07-28): the
plain compare REWRITES ``complexipy-snapshot.json`` from the CURRENT run on the
PASSING path — not as a flag's side effect but as the success branch itself
(``complexipy/utils/snapshot.py::handle_snapshot_watermark`` calls
``create_snapshot_file(...)`` the moment it finds no violation). Two ways a run
that exits 0 empties a populated snapshot, both observed at 1 entry -> 0:

- **narrowed surface** — ``complexipy src/low_complexity_file.py``, a subset
  holding nothing above the threshold. This kit fixes the argv, so the
  consumer-side routes are a narrowed ``source_root`` (cf-repo-config) or a
  committed ``exclude``;
- **raised threshold** — ``complexipy src -mx 100``. The consumer-side route is
  committed config: complexipy reads ``complexipy.toml`` / ``.complexipy.toml``
  / ``[tool.complexipy]`` from its invocation directory, where
  ``max-complexity-allowed`` (default 15) lives.

So the ratchet loses its floor and every later run compares against nothing
while the board reads PASS. A real consumer carrying 12 entries (12 files / 13
functions, complexity 16..27) loses all of it in one green run, and whoever
commits the rewritten file has deleted the ratchet with a green gate on screen —
the gate-that-selects-by-the-value-it-guards-goes-vacuous scar in its purest
form: the verdict is derived from the artifact the gate destroys.

What this module adds around the same single unpiped run:

1. the snapshot is read BEFORE the run (raw bytes + the floor they declare) and
   RESTORED afterwards — the compare grades the artifact, never authors it.
   Re-baselining stays the deliberate act the runbook owns
   (``--snapshot-create``), so restoring holds the floor higher, never lower;
2. the graded surface is counted INDEPENDENTLY of the snapshot, so a run that
   graded nothing can never read clean (``checked > 0``). Two worlds, two
   verdicts: NO parseable Python under the surface means no count can be
   established (the wrong room — a setup failure, exit 2, the doctrine
   cf-repo-config's empty-room rule already carries), while parseable Python
   holding ZERO functions means the gauge ran over nothing gradeable (a finding,
   exit 1, with both counts named);
3. an emptied floor is a violation (exit 1), not a notice;
4. every dropped entry is printed and classified, because a real refactor also
   shrinks the snapshot and must still pass.

Doctrine kept EXACTLY as before: the missing-snapshot refuse/skip decision stays
in cf-gate's stage (absent snapshot + Python present => GateError
``GATE_COMPLEXIPY_SNAPSHOT_MISSING``; absent snapshot + no Python => visible
skip), and this module is only reached once the artifact exists.
"""

from __future__ import annotations

import ast
import json
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from cf_quality.errors import GateError, GateVerdict, GateViolation

#: The stage name every verdict and violation here carries (cf-gate's board label).
GATE = "complexipy"

#: The ratchet artifact. complexipy resolves it against its INVOCATION directory,
#: which is why the stage must run with cwd == repo root (tool-spike gotcha).
SNAPSHOT_FILENAME = "complexipy-snapshot.json"

#: ``gate_runner._tool``'s shape: a gauge name -> its absolute path beside the
#: running Python. Threaded in, never imported, so the arrow points one way.
ToolResolver = Callable[[str], Path]


class ExternalRunner(Protocol):
    """``gate_runner._run_external``'s shape, threaded in rather than imported.

    cf-gate owns the subprocess seam (absolute argv, the registered S603
    blessing, text handling, the exit-code -> verdict mapping) and its own tests
    fake THAT seam. Passing the runner in keeps one implementation of it, keeps
    this module importing nothing but the typed failure vocabulary (no cycle back
    into gate_runner), and lets every existing fake drive the guard unchanged.
    """

    def __call__(
        self, gate: str, argv: list[str], *, cwd: Path, env: Mapping[str, str]
    ) -> GateVerdict: ...


@dataclass(frozen=True)
class Snapshot:
    """One reading of the snapshot file: its bytes, and the floor they declare.

    ``raw`` is kept because putting the artifact back byte-for-byte is part of
    the contract. ``readable`` is False when the bytes are not a complexipy
    snapshot LIST: that declares no floor and says so in the notices — the
    weakest possible claim, so it cannot be gamed into a pass, while complexipy's
    own loader refuses such a file and the run goes red on the tool's exit rather
    than on our reading of garbage.
    """

    raw: bytes
    files: tuple[str, ...]
    functions: int
    readable: bool

    @property
    def entries(self) -> int:
        """How many FILE entries the snapshot pins — the floor's width."""
        return len(self.files)


@dataclass(frozen=True)
class Surface:
    """The graded surface, counted without consulting the snapshot at all."""

    files: int
    functions: int
    unparsed: tuple[str, ...]


@dataclass(frozen=True)
class Drops:
    """Snapshot entries that disappeared in this run, classified by WHY.

    This classification IS the discrimination rule between a legitimate ratchet
    tightening and a lost floor:

    - **improved** — the file still sits inside the graded surface, so complexipy
      measured it and it no longer exceeds the threshold. Real work; passes;
      named in the notices anyway.
    - **deleted** — the file is gone from the repo, so the debt left with the
      code and the watermark is stale, not evaded. Passes; named.
    - **unmeasured** — the file still EXISTS but sits outside the graded surface,
      so nothing measured it: dropped by narrowing, not by work. Red.
    """

    improved: tuple[str, ...]
    deleted: tuple[str, ...]
    unmeasured: tuple[str, ...]

    @property
    def names(self) -> tuple[str, ...]:
        """Every dropped entry, in one tuple, for the notices."""
        return self.improved + self.deleted + self.unmeasured


# --- reading the artifact ----------------------------------------------------


def _decode_entries(raw: bytes) -> list[Any] | None:
    """The snapshot's file entries, or None when the bytes are not that shape."""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(data, list):
        return None
    return data


def _entry_path(entry: Any) -> str:
    """An entry's repo-relative path (complexipy writes ``path`` + ``file_name``)."""
    if isinstance(entry, Mapping):
        return str(entry.get("path") or entry.get("file_name") or "<unnamed>")
    return "<unnamed>"


def _entry_functions(entry: Any) -> int:
    """How many watermarked functions one entry pins (0 for a foreign shape)."""
    if isinstance(entry, Mapping):
        functions = entry.get("functions")
        if isinstance(functions, list):
            return len(functions)
    return 0


def read_snapshot(path: Path) -> Snapshot:
    """Read the ratchet artifact: the bytes first, then the floor they declare.

    An unreadable FILE is a gate-cannot-run condition (typed, exit 2): cf-gate
    only delegates here once the file exists, so an OSError means the world
    moved under the run — never a pass, never an untyped crash out of the stage.
    """
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise GateError(
            code="GATE_COMPLEXIPY_SNAPSHOT_UNREADABLE",
            message=f"cannot read {path.name}: {exc}",
            context={"path": str(path)},
        ) from exc
    entries = _decode_entries(raw)
    if entries is None:
        return Snapshot(raw=raw, files=(), functions=0, readable=False)
    return Snapshot(
        raw=raw,
        files=tuple(_entry_path(entry) for entry in entries),
        functions=sum(_entry_functions(entry) for entry in entries),
        readable=True,
    )


# --- measuring the surface, independently of the artifact --------------------


def _count_functions(path: Path) -> int | None:
    """Function/method definitions in one module, or None when it cannot be read."""
    try:
        tree = ast.parse(path.read_bytes())
    except (OSError, SyntaxError, ValueError):
        return None
    return sum(
        1 for node in ast.walk(tree) if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    )


def measure_surface(source_root: Path) -> Surface:
    """Count the functions the graded surface actually holds — the honest count.

    WHY not the post-run snapshot: an empty post-run snapshot is EXACTLY the
    failure mode, so deriving "did this run grade anything?" from it is the
    circularity the scar names — an empty result and a narrowed surface then look
    identical (don't report voids).

    WHY not complexipy's stdout: the count would ride the tool's display layer (a
    rich table, or the ``--plain`` writer — both version-shaped) and the argv
    would have to grow a flag, while the stage's exact argv is itself a contract
    pinned by the runner's tests.

    Honest scope: this counts the room complexipy is POINTED at (the same
    resolved source_root passed as its only argument), by the same
    skip-dotted-directories rule the runner's Python-present probe uses. It
    proves the room is not empty; it does not re-implement cognitive complexity
    and does not claim to know what the tool did inside the room.
    """
    files = 0
    functions = 0
    unparsed: list[str] = []
    for path in sorted(source_root.rglob("*.py")):
        if any(part.startswith(".") for part in path.relative_to(source_root).parts):
            continue
        counted = _count_functions(path)
        if counted is None:
            unparsed.append(str(path))
            continue
        files += 1
        functions += counted
    return Surface(files=files, functions=functions, unparsed=tuple(unparsed))


def _refuse_unmeasurable_surface(source_root: Path, surface: Surface) -> None:
    """No parseable Python under the surface — the measured count cannot be established.

    cf-gate already skips a Python-FREE repo visibly, so reaching here with zero
    parseable files means the resolved source_root is the wrong room (a narrowed
    or mistyped declaration), or every candidate file failed to parse. Either way
    no honest count exists, so the gate refuses (exit 2) rather than grading an
    empty room and calling it clean — the same doctrine cf-repo-config's
    empty-room rule carries for a declared source_root.
    """
    if surface.files > 0:
        return
    raise GateError(
        code="GATE_COMPLEXIPY_SURFACE_UNMEASURED",
        message=(
            f"no parseable Python under {source_root} "
            f"({len(surface.unparsed)} file(s) failed to parse) — the complexity ratchet "
            "cannot establish what it graded, and an ungraded room must never report "
            "clean; point source_root at the tree that holds the code (cf-repo-config)"
        ),
        context={
            "source_root": str(source_root),
            "files_measured": surface.files,
            "functions_measured": surface.functions,
            "unparsed": list(surface.unparsed),
        },
    )


def _surface_vacuous(source_root: Path, surface: Surface) -> GateViolation:
    """Parseable Python, zero functions: the gauge ran over nothing gradeable."""
    return GateViolation(
        code="COMPLEXIPY_SURFACE_VACUOUS",
        message=(
            f"the complexity ratchet graded 0 functions across {surface.files} file(s) under "
            f"{source_root} — a cognitive-complexity gate over a surface with no functions "
            "reports clean by construction, which is a void, not a pass; declare the "
            "source_root that holds the code (cf-repo-config)"
        ),
        path=SNAPSHOT_FILENAME,
        context={
            "source_root": str(source_root),
            "files_measured": surface.files,
            "functions_measured": surface.functions,
        },
    )


# --- the floor guard --------------------------------------------------------


def _restore(path: Path, before: Snapshot, after: Snapshot) -> None:
    """Put the artifact back byte-for-byte: this gate GRADES the snapshot, never authors it.

    Restoration (not the violation) is what actually saves the floor, including
    the partial cases: whatever complexipy wrote, the committed watermark is
    what stays on disk, so no developer can commit a gate-authored shrink.
    """
    if after.raw != before.raw:
        path.write_bytes(before.raw)


def _drop_kind(root: Path, source_root: Path, name: str) -> str:
    """Classify one dropped entry: improved (measured) · deleted · unmeasured."""
    path = (root / name).resolve()
    if not path.exists():
        return "deleted"
    if path.is_relative_to(source_root.resolve()):
        return "improved"
    return "unmeasured"


def _classify_drops(root: Path, source_root: Path, before: Snapshot, after: Snapshot) -> Drops:
    """Every entry present before and absent after, bucketed by :class:`Drops`."""
    buckets: dict[str, list[str]] = {"improved": [], "deleted": [], "unmeasured": []}
    for name in before.files:
        if name in after.files:
            continue
        buckets[_drop_kind(root, source_root, name)].append(name)
    return Drops(
        improved=tuple(buckets["improved"]),
        deleted=tuple(buckets["deleted"]),
        unmeasured=tuple(buckets["unmeasured"]),
    )


def _floor_lost(before: Snapshot, after: Snapshot, surface: Surface, drops: Drops) -> GateViolation:
    """The whole floor vanished in a run that graded a non-empty surface."""
    return GateViolation(
        code="COMPLEXIPY_SNAPSHOT_FLOOR_LOST",
        message=(
            f"the run emptied {SNAPSHOT_FILENAME}: {before.entries} entry/entries "
            f"({before.functions} function(s)) before, {after.entries} after, over a surface "
            f"holding {surface.functions} function(s) — the committed floor was RESTORED; "
            "re-run the ratchet over the declared source_root at the pinned threshold, and "
            "if every offender really was refactored away, re-baseline deliberately with "
            "`complexipy <source-root> --snapshot-create`"
        ),
        path=SNAPSHOT_FILENAME,
        context={
            "entries_before": before.entries,
            "entries_after": after.entries,
            "functions_before": before.functions,
            "functions_measured": surface.functions,
            "files_measured": surface.files,
            "dropped": list(drops.names),
            "dropped_unmeasured": list(drops.unmeasured),
        },
    )


def _floor_unmeasured(before: Snapshot, surface: Surface, drops: Drops) -> GateViolation:
    """Entries dropped for files that still exist but were never measured."""
    return GateViolation(
        code="COMPLEXIPY_SNAPSHOT_FLOOR_UNMEASURED",
        message=(
            f"{len(drops.unmeasured)} snapshot entry/entries were dropped for files that "
            f"still exist OUTSIDE the graded surface ({', '.join(drops.unmeasured)}) — their "
            "watermarks were not measured, so the shrink is narrowing, not work; the "
            f"committed floor ({before.entries} entry/entries) was RESTORED"
        ),
        path=SNAPSHOT_FILENAME,
        context={
            "entries_before": before.entries,
            "unmeasured": list(drops.unmeasured),
            "functions_measured": surface.functions,
            "files_measured": surface.files,
        },
    )


def _guard_violations(
    source_root: Path, before: Snapshot, after: Snapshot, surface: Surface, drops: Drops
) -> list[GateViolation]:
    """Every guard finding this run earned — collected, never fail-fast.

    A LEGITIMATE empty snapshot is discriminated from a lost floor by what the
    run itself did, never by the file alone:

    - ``before`` empty, ``after`` empty, surface DOES hold functions: nothing
      above the threshold, i.e. a genuinely clean repo — passes. Had offenders
      existed, complexipy's own compare would have flagged them as "not part of
      the snapshot" and exited 1, so an empty floor cannot hide real offenders AT
      THE PINNED THRESHOLD. (An already-empty floor graded at a RAISED threshold
      is config drift, not a floor question — named as residual, not pretended
      closed.)
    - ``before`` empty and the surface holds no functions: vacuous, not clean.
    - ``before`` populated, ``after`` empty: the floor is gone while the room was
      not — red, and restored.
    """
    violations: list[GateViolation] = []
    if surface.functions == 0:
        violations.append(_surface_vacuous(source_root, surface))
    if before.entries > 0 and after.entries == 0:
        violations.append(_floor_lost(before, after, surface, drops))
    elif drops.unmeasured:
        violations.append(_floor_unmeasured(before, surface, drops))
    return violations


# --- notices (the visible decision) -----------------------------------------


def _drop_notice(drops: Drops) -> str:
    """One line naming EVERY dropped entry and the bucket it fell in."""
    parts = [f"{GATE}: {len(drops.names)} snapshot entry/entries dropped by this run"]
    for label, names in (
        ("measured-and-improved", drops.improved),
        ("file-deleted", drops.deleted),
        ("NOT MEASURED", drops.unmeasured),
    ):
        if names:
            parts.append(f"{label}: {', '.join(names)}")
    parts.append(
        "the committed floor was restored — lock a real improvement in deliberately with "
        "`complexipy <source-root> --snapshot-create`"
    )
    return " · ".join(parts)


def _notices(surface: Surface, before: Snapshot, drops: Drops) -> list[str]:
    """The always-emitted audit line, plus one line per visible decision."""
    lines = [
        f"{GATE}: functions_measured={surface.functions} files_measured={surface.files} "
        f"entries_checked={before.entries} floor_functions={before.functions}"
    ]
    if not before.readable:
        lines.append(
            f"{GATE}: {SNAPSHOT_FILENAME} is not a complexipy snapshot list, so it declares "
            "NO floor — re-boot it with `complexipy <source-root> --snapshot-create`"
        )
    if surface.unparsed:
        lines.append(
            f"{GATE}: {len(surface.unparsed)} file(s) under the surface could not be parsed "
            f"and were NOT counted: {', '.join(surface.unparsed)}"
        )
    if drops.names:
        lines.append(_drop_notice(drops))
    return lines


def _emit(notices: list[str]) -> None:
    """Notices go to STDERR, always — visible decision, never silent.

    :class:`~cf_quality.errors.GateVerdict` carries no notices channel
    (:mod:`cf_quality.reporting` exposes one, but only for a gate owning its own
    stdout), and cf-gate's stdout under ``CF_QUALITY_JSON`` is a single parseable
    envelope an audit line would corrupt. stderr keeps the counts in every CI log
    without touching the wire form; they also ride the violation ``context``.
    """
    for notice in notices:
        print(notice, file=sys.stderr)


def complexipy_with_floor_guard(
    root: Path,
    source_root: Path,
    env: Mapping[str, str],
    tool: ToolResolver,
    run_external: ExternalRunner,
) -> GateVerdict:
    """Run the snapshot ratchet, then prove it graded something and kept its floor.

    Same single unpiped process, same argv shape, same cwd and env as the
    unguarded stage (piping would mask complexipy's exit code — the tool-spike
    gotcha); the guard is entirely in what happens either side of it.
    """
    snapshot_path = root / SNAPSHOT_FILENAME
    before = read_snapshot(snapshot_path)
    surface = measure_surface(source_root)
    _refuse_unmeasurable_surface(source_root, surface)
    argv = [str(tool("complexipy")), str(source_root)]
    verdict = run_external(GATE, argv, cwd=root, env=env)
    after = read_snapshot(snapshot_path)
    _restore(snapshot_path, before, after)
    drops = _classify_drops(root, source_root, before, after)
    _emit(_notices(surface, before, drops))
    guarded = _guard_violations(source_root, before, after, surface, drops)
    return GateVerdict(
        gate=verdict.gate,
        violations=[*verdict.violations, *guarded],
        error=verdict.error,
    )
