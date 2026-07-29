"""The complexipy ratchet's floor guard — the measured defect and its control rods.

MEASURED DEFECT (complexipy 5.6.0, reproduced with real hands 2026-07-28): the
plain compare REWRITES ``complexipy-snapshot.json`` on the PASSING path, so a run
grading a narrowed surface (or grading at a raised threshold) empties a populated
snapshot and exits 0. Every later run then compares against nothing while the
board reads PASS — the gate-that-selects-by-the-value-it-guards-goes-vacuous
scar, where the verdict is derived from the artifact the gate destroys.

Every test here is the POST-FIX CONTRACT, so this file fails against the
unguarded stage, which reported CLEAN for exactly the runs asserted red below and
left the emptied file on disk. Two oracles, deliberately: the FAKE seam
(``gate_runner._tool`` / ``gate_runner._exec``, the seam
``test_gate_runner._install_fakes`` already drives) carries a stand-in mimicking
the measured behaviour, one decision per test; and the REAL pinned complexipy
runs end to end over a temp tree (the ``test_integration_consumer`` style),
because a fake-only proof of a TOOL-BEHAVIOUR defect only proves the fake. The
six control-rod cases are the emptied floor, a genuine regression, a vacuous run
(all red), and an unchanged floor, a legitimate non-empty shrink, a clean repo
with an empty snapshot (all green) — each named in its own test.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest
from test_gate_runner import _layout, _write

from cf_quality import gate_runner
from cf_quality.complexipy_snapshot import SNAPSHOT_FILENAME, measure_surface
from cf_quality.errors import GateError, GateVerdict

# --- the source shapes the ratchet grades ------------------------------------

#: Cognitive complexity well above complexipy's default threshold of 15 (nesting plus a
#: boolean operator put it in the mid-20s), so a booted snapshot pins something real.
HEAVY_SOURCE = """\
def monster(items: list[int], flag: bool) -> int:
    total = 0
    for item in items:
        if item > 0:
            for inner in range(item):
                if inner % 2 == 0 and flag:
                    countdown = inner
                    while countdown > 0:
                        if countdown == 3:
                            total += 1
                        countdown -= 1
                elif inner % 3 == 0:
                    total += 2
                else:
                    total -= 1
        else:
            total -= 2
    return total
"""

#: The same function worsened by one more nested branch — a genuine regression
#: above whatever watermark the booted snapshot recorded.
WORSE_SOURCE = HEAVY_SOURCE.replace(
    "                        if countdown == 3:\n                            total += 1\n",
    "                        if countdown == 3:\n"
    "                            if flag or item > 5:\n"
    "                                total += 1\n",
)

#: Nothing above the threshold — the low room a narrowed surface points at.
LIGHT_SOURCE = "def simple(value: int) -> int:\n    return value + 1\n"

#: Data but no functions at all — the vacuous surface.
CONSTANTS_SOURCE = "ANSWER: int = 42\n"

#: Unparseable — the surface that cannot be counted at all.
BROKEN_SOURCE = "def (: syntax error\n"


# --- helpers ----------------------------------------------------------------


def _entry(rel: str, name: str, complexity: int) -> dict[str, object]:
    """One snapshot entry in complexipy 5.6.0's observed on-disk shape."""
    return {
        "path": rel,
        "file_name": Path(rel).name,
        "functions": [{"name": name, "complexity": complexity}],
    }


def _write_snapshot(root: Path, entries: list[dict[str, object]] | str) -> bytes:
    """Commit a snapshot; returns its exact bytes for the restore assertions."""
    path = root / SNAPSHOT_FILENAME
    text = entries if isinstance(entries, str) else json.dumps(entries, indent=2)
    path.write_text(text, encoding="utf-8")
    return path.read_bytes()


def _snapshot_entries(root: Path) -> list[dict[str, object]]:
    data = json.loads((root / SNAPSHOT_FILENAME).read_text(encoding="utf-8"))
    assert isinstance(data, list), "the committed snapshot must stay a list"
    return data


def _mount(root: Path, sources: Mapping[str, str]) -> None:
    for rel, text in sources.items():
        _write(root, rel, text)


def _fake_complexipy(
    monkeypatch: pytest.MonkeyPatch,
    root: Path,
    *,
    rewrite_to: list[dict[str, object]] | None,
    returncode: int = 0,
    stdout: str = "",
) -> list[tuple[list[str], str | None]]:
    """Stand in for complexipy 5.6.0 at the runner's own subprocess seam.

    Mimics the MEASURED behaviour, not an idealized one: on the passing path it
    rewrites the snapshot from the current run and exits 0; when the watermark
    compare FAILS it exits 1 and leaves the file alone (the watermark helper
    returns before ``create_snapshot_file``). Every OTHER tool the battery may
    call answers exit 0, so a battery-level test grades this stage only.
    """
    monkeypatch.setattr(gate_runner, "_tool", lambda name: Path("/fake") / name)
    calls: list[tuple[list[str], str | None]] = []

    def fake_exec(
        argv: list[str],
        cwd: Path,
        env: Mapping[str, str],
        *,
        stdin: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        calls.append((list(argv), stdin))
        mine = Path(argv[0]).name == "complexipy"
        if mine and returncode == 0 and rewrite_to is not None:
            _write_snapshot(root, rewrite_to)
        return subprocess.CompletedProcess(argv, returncode if mine else 0, stdout, "")

    monkeypatch.setattr(gate_runner, "_exec", fake_exec)
    return calls


def _codes(verdict: GateVerdict | None) -> list[str]:
    assert verdict is not None, "the stage must not skip a Python repo carrying a snapshot"
    return [violation.code for violation in verdict.violations]


def _run_real(root: Path, source_root: Path) -> GateVerdict:
    """Drive the guarded stage with the REAL pinned complexipy over a temp tree."""
    layout = gate_runner.Layout(
        root=root, source_root=source_root, package_dir=root, first_party="[]", py_present=True
    )
    verdict = gate_runner._complexipy(layout, os.environ)
    assert verdict is not None
    return verdict


def _boot_real_snapshot(root: Path, source_root: Path) -> bytes:
    """Boot the floor with the real tool, as BASELINE-CONVENTIONS prescribes."""
    proc = subprocess.run(
        [str(gate_runner._tool("complexipy")), str(source_root), "--snapshot-create"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"snapshot boot failed:\n{proc.stdout}\n{proc.stderr}"
    assert _snapshot_entries(root), (
        "the booted snapshot is EMPTY — the fixture is not over the threshold, so every "
        f"floor rod below would pass vacuously:\n{proc.stdout}"
    )
    return (root / SNAPSHOT_FILENAME).read_bytes()


# --- RED: the reproduction (a passing run that empties the floor) -------------


def test_a_passing_run_that_empties_the_snapshot_is_red_and_restores_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE REPRODUCTION as the post-fix contract: against the UNGUARDED stage this
    exact run reported ``passed`` and left the emptied file on disk (measured: 1
    entry -> 0 at exit 0). The contract is a violation plus a byte-identical restore.
    """
    _mount(tmp_path, {"src/heavy.py": HEAVY_SOURCE, "src/low/simple.py": LIGHT_SOURCE})
    committed = _write_snapshot(tmp_path, [_entry("src/heavy.py", "monster", 25)])
    _fake_complexipy(monkeypatch, tmp_path, rewrite_to=[])

    verdict = gate_runner._complexipy(_layout(tmp_path), {})

    assert "COMPLEXIPY_SNAPSHOT_FLOOR_LOST" in _codes(verdict)
    assert verdict is not None and verdict.error is None, "a finding, not a setup failure"
    assert verdict.exit_code == 1
    assert (tmp_path / SNAPSHOT_FILENAME).read_bytes() == committed, (
        "the gate must never destroy the artifact it grades — restore it byte-for-byte"
    )
    floor = next(v for v in verdict.violations if v.code == "COMPLEXIPY_SNAPSHOT_FLOOR_LOST")
    assert floor.context["entries_before"] == 1
    assert floor.context["entries_after"] == 0
    assert floor.context["functions_measured"] == 2, "the counts ride the finding"


def test_entries_dropped_for_files_outside_the_graded_surface_are_red(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # PARTIAL narrowing: one watermark survives, one is dropped for a file that still
    # exists OUTSIDE the graded surface — neither improved nor deleted, so red + restored.
    _mount(tmp_path, {"src/heavy.py": HEAVY_SOURCE, "extra/outside.py": HEAVY_SOURCE})
    committed = _write_snapshot(
        tmp_path,
        [_entry("src/heavy.py", "monster", 25), _entry("extra/outside.py", "monster", 25)],
    )
    _fake_complexipy(monkeypatch, tmp_path, rewrite_to=[_entry("src/heavy.py", "monster", 25)])

    verdict = gate_runner._complexipy(_layout(tmp_path), {})

    assert "COMPLEXIPY_SNAPSHOT_FLOOR_UNMEASURED" in _codes(verdict)
    assert (tmp_path / SNAPSHOT_FILENAME).read_bytes() == committed


def test_a_tool_reported_regression_stays_red_and_never_touches_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The pre-existing contract survives delegation: complexipy's own non-zero exit
    # is ONE violation carrying its output, and the artifact is untouched.
    _mount(tmp_path, {"src/heavy.py": HEAVY_SOURCE})
    committed = _write_snapshot(tmp_path, [_entry("src/heavy.py", "monster", 20)])
    _fake_complexipy(
        monkeypatch,
        tmp_path,
        rewrite_to=None,
        returncode=1,
        stdout="Snapshot watermark: src/heavy.py:monster increased from 20 to 25.",
    )

    verdict = gate_runner._complexipy(_layout(tmp_path), {})

    assert _codes(verdict) == ["COMPLEXIPY_FAILED"]
    assert verdict is not None and verdict.exit_code == 1
    assert "increased from 20 to 25" in verdict.violations[0].context["output"]
    assert (tmp_path / SNAPSHOT_FILENAME).read_bytes() == committed


# --- RED: the vacuity guard (nothing graded must never read clean) -----------


def test_a_surface_with_no_functions_is_a_finding_never_a_clean_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # ``checked > 0``: the room parses but holds nothing to grade, so this gate reports
    # clean BY CONSTRUCTION. That void is a finding with both counts named, never a pass.
    _mount(tmp_path, {"src/constants.py": CONSTANTS_SOURCE})
    _write_snapshot(tmp_path, [])
    _fake_complexipy(monkeypatch, tmp_path, rewrite_to=[])

    verdict = gate_runner._complexipy(_layout(tmp_path), {})

    assert "COMPLEXIPY_SURFACE_VACUOUS" in _codes(verdict)
    assert verdict is not None and verdict.exit_code == 1
    assert verdict.violations[0].context["functions_measured"] == 0
    assert verdict.violations[0].context["files_measured"] == 1


def test_a_surface_with_no_parseable_python_refuses_with_exit_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Worse than vacuous: no count can be established at all — a setup failure (the
    # empty-room doctrine), refused BEFORE the gauge is spent. No path to green.
    _mount(tmp_path, {"src/broken.py": BROKEN_SOURCE, "elsewhere.py": LIGHT_SOURCE})
    _write_snapshot(tmp_path, [])
    calls = _fake_complexipy(monkeypatch, tmp_path, rewrite_to=[])

    with pytest.raises(GateError) as excinfo:
        gate_runner._complexipy(_layout(tmp_path), {})

    assert excinfo.value.code == "GATE_COMPLEXIPY_SURFACE_UNMEASURED"
    assert excinfo.value.context["files_measured"] == 0
    assert calls == [], "an unmeasurable surface is refused before the gauge is spent"


def test_the_battery_records_the_unmeasurable_surface_as_exit_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The refusal reaches the BOARD the way every other setup failure does:
    # recorded as this stage's error verdict, collect-and-continue, aggregate 2.
    _mount(tmp_path, {"src/broken.py": BROKEN_SOURCE})
    _write_snapshot(tmp_path, [])
    _write(tmp_path, "mypy-baseline.txt", "")
    _fake_complexipy(monkeypatch, tmp_path, rewrite_to=[])

    verdicts = gate_runner.run_battery(tmp_path, {})
    complexipy = next(verdict for verdict in verdicts if verdict.gate == "complexipy")

    assert complexipy.error is not None
    assert complexipy.error.code == "GATE_COMPLEXIPY_SURFACE_UNMEASURED"
    assert gate_runner.battery_exit_code(verdicts) == 2


# --- GREEN: the legitimate shapes -------------------------------------------


def test_unchanged_populated_snapshot_stays_green_and_reports_its_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # An intact floor at exit 0 is clean — and the audit line is unconditional, so a
    # reader can tell what was graded WITHOUT trusting the artifact the run rewrites.
    _mount(tmp_path, {"src/heavy.py": HEAVY_SOURCE, "src/light.py": LIGHT_SOURCE})
    entries = [_entry("src/heavy.py", "monster", 25)]
    committed = _write_snapshot(tmp_path, entries)
    _fake_complexipy(monkeypatch, tmp_path, rewrite_to=entries)

    verdict = gate_runner._complexipy(_layout(tmp_path), {})
    notices = capsys.readouterr().err

    assert verdict is not None and verdict.passed
    assert (tmp_path / SNAPSHOT_FILENAME).read_bytes() == committed
    assert "functions_measured=2" in notices and "files_measured=2" in notices
    assert "entries_checked=1" in notices and "floor_functions=1" in notices


def test_non_empty_shrink_passes_and_names_every_dropped_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Both legitimate drop shapes at once: one watermarked function refactored below the
    # threshold with its file still INSIDE the graded surface, and one watermarked file
    # gone from the repo (the debt left with the code). A valid tightening, so it PASSES —
    # but every dropped file is named with its bucket, and the floor is not rewritten.
    _mount(tmp_path, {"src/heavy.py": HEAVY_SOURCE, "src/improved.py": LIGHT_SOURCE})
    _write_snapshot(
        tmp_path,
        [
            _entry("src/heavy.py", "monster", 25),
            _entry("src/improved.py", "was_heavy", 19),
            _entry("src/gone.py", "deleted_with_its_file", 22),
        ],
    )
    _fake_complexipy(monkeypatch, tmp_path, rewrite_to=[_entry("src/heavy.py", "monster", 25)])

    verdict = gate_runner._complexipy(_layout(tmp_path), {})
    notices = capsys.readouterr().err

    assert verdict is not None and verdict.passed, "a non-empty shrink is a tightening"
    assert "measured-and-improved" in notices and "src/improved.py" in notices
    assert "file-deleted" in notices and "src/gone.py" in notices
    assert len(_snapshot_entries(tmp_path)) == 3, "the committed floor is still the floor"


def test_clean_repo_with_an_empty_snapshot_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # No false positive on the legitimate empty floor: nothing above the threshold
    # in a NON-vacuous room is exactly what a clean repo looks like.
    _mount(tmp_path, {"src/light.py": LIGHT_SOURCE})
    _write_snapshot(tmp_path, [])
    _fake_complexipy(monkeypatch, tmp_path, rewrite_to=[])

    verdict = gate_runner._complexipy(_layout(tmp_path), {})
    notices = capsys.readouterr().err

    assert verdict is not None and verdict.passed
    assert "functions_measured=1" in notices and "entries_checked=0" in notices


# --- the argv contract, the lenient read, and the preserved doctrine ----------


def test_the_guard_keeps_the_single_unpiped_argv_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The pinned stage contract survives delegation: ONE process, argv scoped to the
    # resolved source_root, no stdin handoff (a pipe would mask the exit code).
    _mount(tmp_path, {"src/light.py": LIGHT_SOURCE})
    _write_snapshot(tmp_path, [])
    calls = _fake_complexipy(monkeypatch, tmp_path, rewrite_to=[])

    gate_runner._complexipy(_layout(tmp_path), {})

    assert len(calls) == 1
    argv, stdin = calls[0]
    assert argv == [str(Path("/fake") / "complexipy"), str(tmp_path / "src")]
    assert stdin is None


def test_a_snapshot_that_is_not_a_list_declares_no_floor_and_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # A shape the guard cannot read makes the WEAKEST claim (no floor) and PRINTS it,
    # never a pass or a phantom finding — complexipy's own loader refuses such a file.
    _mount(tmp_path, {"src/light.py": LIGHT_SOURCE})
    _write_snapshot(tmp_path, "{}")
    _fake_complexipy(monkeypatch, tmp_path, rewrite_to=[])

    verdict = gate_runner._complexipy(_layout(tmp_path), {})
    notices = capsys.readouterr().err

    assert verdict is not None and verdict.passed
    assert "declares" in notices and "NO floor" in notices


def test_the_missing_snapshot_doctrine_is_unchanged(tmp_path: Path) -> None:
    # Preserved EXACTLY: Python present with no snapshot refuses (typed, exit 2); a
    # Python-free repo skips visibly (None). The guard reaches neither.
    _write(tmp_path, "pkg.py", "def f() -> int:\n    return 1\n")

    with pytest.raises(GateError) as excinfo:
        gate_runner._complexipy(_layout(tmp_path, py_present=True), {})

    assert excinfo.value.code == "GATE_COMPLEXIPY_SNAPSHOT_MISSING"
    assert gate_runner._complexipy(_layout(tmp_path, py_present=False), {}) is None


def test_measure_surface_counts_what_it_claims_and_flags_what_it_cannot(tmp_path: Path) -> None:
    # The independent count IS the vacuity guard, so pin what it counts: functions AND
    # methods, by the runner's skip-dotted-dirs rule (a .venv full of functions must never
    # make an empty room look measured), with unparseable files reported, not zeroed.
    _mount(
        tmp_path,
        {
            "src/mod.py": "class C:\n    def m(self) -> None:\n        pass\n",
            "src/.venv/lib/vendor.py": HEAVY_SOURCE,
            "src/broken.py": BROKEN_SOURCE,
        },
    )

    surface = measure_surface(tmp_path / "src")

    assert (surface.files, surface.functions) == (1, 1)
    assert [Path(name).name for name in surface.unparsed] == ["broken.py"]


# --- the REAL pinned complexipy, end to end ---------------------------------
#
# A defect in a TOOL's behaviour cannot be proven by a stand-in for that tool, so these
# rods run the pinned complexipy (5.6.0) for real. No skip guard — the suite already
# requires the real battery, and a silent skip is the void this file exists to refuse.


def test_real_full_surface_run_keeps_the_booted_floor_green(tmp_path: Path) -> None:
    _mount(tmp_path, {"src/heavy.py": HEAVY_SOURCE, "src/low/simple.py": LIGHT_SOURCE})
    booted = _boot_real_snapshot(tmp_path, tmp_path / "src")

    verdict = _run_real(tmp_path, tmp_path / "src")

    assert verdict.passed, f"a booted floor graded over its own surface is clean: {verdict}"
    assert (tmp_path / SNAPSHOT_FILENAME).read_bytes() == booted


def test_real_narrowed_source_root_empties_the_floor_and_the_guard_catches_it(
    tmp_path: Path,
) -> None:
    # THE DEFECT with real hands: boot the floor over the whole tree, then grade a narrowed
    # room holding nothing above the threshold. The real tool exits 0 and rewrites the
    # snapshot to []; the guard must make that a violation and put the committed bytes back.
    _mount(tmp_path, {"src/heavy.py": HEAVY_SOURCE, "src/low/simple.py": LIGHT_SOURCE})
    booted = _boot_real_snapshot(tmp_path, tmp_path / "src")

    verdict = _run_real(tmp_path, tmp_path / "src" / "low")

    assert "COMPLEXIPY_SNAPSHOT_FLOOR_LOST" in [v.code for v in verdict.violations], (
        f"the real tool emptied the floor at exit 0 and the guard let it pass: {verdict}"
    )
    assert verdict.exit_code == 1
    assert (tmp_path / SNAPSHOT_FILENAME).read_bytes() == booted, "restored byte-for-byte"


def test_real_regression_above_the_booted_watermark_is_red(tmp_path: Path) -> None:
    assert WORSE_SOURCE != HEAVY_SOURCE, "the worsening edit must actually apply"
    _mount(tmp_path, {"src/heavy.py": HEAVY_SOURCE})
    booted = _boot_real_snapshot(tmp_path, tmp_path / "src")
    _write(tmp_path, "src/heavy.py", WORSE_SOURCE)  # one more nested branch

    verdict = _run_real(tmp_path, tmp_path / "src")

    assert not verdict.passed, "a function worsened above its watermark must go red"
    assert verdict.error is None, "a finding, not a setup failure"
    output = " ".join(str(v.context.get("output", "")) for v in verdict.violations)
    assert "monster" in output, f"the tool's own verdict must reach the reader: {verdict}"
    assert (tmp_path / SNAPSHOT_FILENAME).read_bytes() == booted


def test_real_clean_repo_with_an_empty_snapshot_passes(tmp_path: Path) -> None:
    # The legitimate empty floor, for real: a non-vacuous room with nothing above the
    # threshold. No false positive, and the artifact stays as committed.
    _mount(tmp_path, {"src/light.py": LIGHT_SOURCE})
    committed = _write_snapshot(tmp_path, [])

    verdict = _run_real(tmp_path, tmp_path / "src")

    assert verdict.passed, f"an empty snapshot in a genuinely clean repo is clean: {verdict}"
    assert (tmp_path / SNAPSHOT_FILENAME).read_bytes() == committed
