"""The complexipy snapshot ratchet — the floor the tool used to eat.

**The reproduced defect.** ``complexipy-snapshot.json`` is the committed
cognitive-complexity floor. In the pinned ``complexipy==5.6.0`` the tool's own
snapshot compare REWRITES that file on its success path
(``complexipy/utils/snapshot.py`` ``handle_snapshot_watermark`` returns True only
after ``create_snapshot_file(...)`` with the functions IT measured), so two
ordinary green runs empty a populated floor at exit 0: measure a narrower surface
(``complexipy src/one_simple_file.py``), or raise the bar (``-mx 100``). Observed
on a real snapshot: ``1 entry -> 0 entries``, ``exit=0``, both ways. Committed,
that deletes the floor forever behind a green gate.

**What this file pins.** The stage no longer hands its own artifact to the tool:
:mod:`cf_quality.complexipy_ratchet` measures write-free (``--snapshot-ignore``,
never ``--snapshot-create`` — the only two paths to ``create_snapshot_file``) and
grades the ratchet in kit code, where it is a pure function of (committed floor,
measured census) and cannot be silently destroyed. The control rods:

- RED on the **emptying** world — the floor names a file the run did not measure,
  whether it fell outside the graded source root or was skipped inside it;
- RED on a real **complexity regression** — a new offender, and a rise above a
  committed watermark;
- RED on a **vacuous** run — a census of zero functions can never report clean,
  with a second leg (the tree demonstrably defines functions) so the refusal
  survives an already-emptied floor;
- GREEN on an **unchanged** floor, on a **legitimate non-empty shrink**, and on a
  genuinely clean repo whose floor is ``[]``;
- the **write-free** proof at the argv altitude, plus the measured COUNT riding
  every finding so no verdict can be read without the measurement behind it.

The external tool is faked at the established subprocess seam
(``gate_runner._exec`` / ``gate_runner._tool``, through ``test_gate_runner``'s
helpers) so the REAL grading logic runs against representative ``--plain``
output, and every stage runs through ``gate_runner._run_stage`` — the altitude the
battery reads, where a raised GateError is already the stage's exit-2 verdict.
:func:`cf_quality.complexipy_ratchet.grade` is additionally exercised with no
subprocess at all, which is the whole point of moving the comparison here.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest
from test_gate_runner import _clean_cf_responses, _install_fakes, _layout, _write

from cf_quality import complexipy_ratchet, gate_runner
from cf_quality.complexipy_ratchet import Census, grade, measurement_argv, read_snapshot
from cf_quality.errors import GateError, GateVerdict

#: Module text that merely EXISTS and defines a function. Every complexity in this
#: file comes from the faked ``--plain`` census, never from this source — the fake
#: is what lets a watermark of 33 be asserted without authoring a monster.
A_FUNCTION = "def a_function():\n    return 1\n"

Responses = Mapping[str, tuple[int, str, str]]


def _snapshot(root: Path, *entries: tuple[str, str, int]) -> None:
    """Write a committed floor in complexipy's own shape (path, function, watermark).

    Mirrors the observed on-disk form of a real consumer snapshot: ``path`` is
    repo-relative and already carries the file name, ``file_name`` is the
    basename, and only over-threshold functions are stored (clean tree -> ``[]``).
    """
    payload = [
        {
            "path": path,
            "file_name": Path(path).name,
            "functions": [{"name": name, "complexity": watermark}],
        }
        for path, name, watermark in entries
    ]
    _write(root, "complexipy-snapshot.json", json.dumps(payload))


def _census(*rows: tuple[str, str, int]) -> str:
    """complexipy ``--plain`` stdout: one ``<path> <function> <complexity>`` line."""
    return "".join(f"{path} {name} {complexity}\n" for path, name, complexity in rows)


def _measured(census: str, offenders: str) -> dict[str, tuple[int, str, str]]:
    """The clean board with complexipy's two write-free runs answered explicitly.

    The offender run's exit code is 1 whenever it reports anything, and it is
    deliberately irrelevant: with the compare switched off complexipy's status
    only restates "something is over threshold", the normal state of a repo
    carrying a baselined floor.
    """
    responses = _clean_cf_responses()
    responses["complexipy"] = (0, census, "")
    responses["complexipy-offenders"] = (1 if offenders else 0, offenders, "")
    return responses


def _stage_verdict(
    root: Path, monkeypatch: pytest.MonkeyPatch, responses: Responses
) -> GateVerdict:
    """Run the real complexipy stage the way the battery runs it.

    Through ``gate_runner._run_stage`` so a GateError raised by a measurement we
    cannot read arrives as the stage's exit-2 verdict, exactly as the board shows
    it — never as an exception the caller has to know about.
    """
    _install_fakes(monkeypatch, responses)
    stage = gate_runner.Stage("complexipy", gate_runner._complexipy)
    verdict = gate_runner._run_stage(stage, _layout(root), {})
    assert verdict is not None, "a Python repo carrying a snapshot never skips"
    return verdict


def _codes(verdict: GateVerdict) -> list[str]:
    return [violation.code for violation in verdict.violations]


def _light(root: Path, rel: str = "src/light.py") -> tuple[str, str, int]:
    """A measured, clean census row for a file that really is on disk."""
    _write(root, rel, A_FUNCTION)
    return (rel, "a_function", 1)


# --- RED: the emptying world (the reproduced defect) --------------------------


def test_floor_file_outside_the_graded_source_root_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The narrowed-surface trigger, structurally: the committed floor holds a
    # watermark for a file the gate no longer even looks at. Under the tool's own
    # compare this run is exit 0 AND rewrites the floor to the smaller world.
    _write(tmp_path, "legacy/heavy.py", A_FUNCTION)
    _snapshot(tmp_path, ("legacy/heavy.py", "heavy", 33))

    verdict = _stage_verdict(tmp_path, monkeypatch, _measured(_census(_light(tmp_path)), ""))

    assert _codes(verdict) == ["COMPLEXIPY_SURFACE_NARROWED"]
    assert verdict.exit_code == 1
    assert verdict.violations[0].context["snapshot_functions"] == 1


def test_floor_file_present_but_unmeasured_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Inside the graded tree and still on disk, yet this run produced NO
    # measurement for it (excluded, ignore-commented, or emptied). A before/after
    # diff of the artifact sees nothing here — there is no rewrite to observe.
    _write(tmp_path, "src/heavy.py", A_FUNCTION)
    _snapshot(tmp_path, ("src/heavy.py", "heavy", 33))

    verdict = _stage_verdict(tmp_path, monkeypatch, _measured(_census(_light(tmp_path)), ""))

    assert _codes(verdict) == ["COMPLEXIPY_SNAPSHOT_FILE_UNMEASURED"]
    assert verdict.exit_code == 1
    assert verdict.violations[0].path == "src/heavy.py"


def test_deleted_floor_file_is_a_legitimate_improvement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The other reading of an unmeasured entry: the file is GONE. That is a real
    # shrink, not a narrowed surface, and it must not be charged as a finding.
    _snapshot(tmp_path, ("src/removed.py", "heavy", 33))

    verdict = _stage_verdict(tmp_path, monkeypatch, _measured(_census(_light(tmp_path)), ""))

    assert verdict.passed, _codes(verdict)


# --- RED: real complexity regressions ----------------------------------------


def test_new_offender_without_a_watermark_is_a_violation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path, "src/heavy.py", A_FUNCTION)
    _snapshot(tmp_path)
    rows = _census(("src/heavy.py", "heavy", 40))

    verdict = _stage_verdict(tmp_path, monkeypatch, _measured(rows, rows))

    assert _codes(verdict) == ["COMPLEXIPY_NEW_OFFENDER"]
    assert verdict.exit_code == 1
    assert verdict.violations[0].context["measured"] == 40


def test_rise_above_a_committed_watermark_is_a_violation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path, "src/heavy.py", A_FUNCTION)
    _snapshot(tmp_path, ("src/heavy.py", "heavy", 20))
    rows = _census(("src/heavy.py", "heavy", 26))

    verdict = _stage_verdict(tmp_path, monkeypatch, _measured(rows, rows))

    assert _codes(verdict) == ["COMPLEXIPY_WATERMARK_REGRESSION"]
    assert verdict.violations[0].context["measured"] == 26


# --- RED: the vacuous run ----------------------------------------------------


def test_vacuous_run_can_never_report_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # THE void rod. The floor is ALREADY `[]` — so the per-file surface audit has
    # nothing to say — the tree demonstrably defines a function, and complexipy
    # measured NOTHING. An empty census and a clean tree are indistinguishable
    # from a count alone, so a run that graded nothing refuses at exit 2.
    _write(tmp_path, "src/heavy.py", A_FUNCTION)
    _snapshot(tmp_path)

    verdict = _stage_verdict(tmp_path, monkeypatch, _measured("", ""))

    assert verdict.error is not None
    assert verdict.error.code == "GATE_COMPLEXIPY_MEASURED_NOTHING"
    assert verdict.exit_code == 2
    assert verdict.error.context["measured_functions"] == 0


def test_vacuous_run_against_a_populated_floor_names_the_files_it_lost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The full emptying world: a populated floor plus a census of nothing. The
    # refusal AND the per-file findings both ride the verdict, so the board says
    # WHAT went unmeasured, not merely that something did.
    _write(tmp_path, "src/heavy.py", A_FUNCTION)
    _snapshot(tmp_path, ("src/heavy.py", "heavy", 33))

    verdict = _stage_verdict(tmp_path, monkeypatch, _measured("", ""))

    assert verdict.error is not None
    assert verdict.error.code == "GATE_COMPLEXIPY_MEASURED_NOTHING"
    assert _codes(verdict) == ["COMPLEXIPY_SNAPSHOT_FILE_UNMEASURED"]
    assert verdict.exit_code == 2


# --- RED: instruments we cannot read -----------------------------------------


def test_unreadable_floor_is_refused_not_read_as_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # green-by-unreadable-file is the same gaming vector as green-by-missing-file,
    # which this gate already refuses.
    _write(tmp_path, "complexipy-snapshot.json", "{}")

    verdict = _stage_verdict(tmp_path, monkeypatch, _measured(_census(_light(tmp_path)), ""))

    assert verdict.error is not None
    assert verdict.error.code == "GATE_COMPLEXIPY_SNAPSHOT_UNREADABLE"
    assert verdict.exit_code == 2


def test_unparseable_census_line_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A census we cannot parse must not degrade into a SMALLER census: dropping
    # the line would be reporting a void as a measurement.
    _snapshot(tmp_path)
    census = "Analyzing 1 file...\n" + _census(_light(tmp_path))

    verdict = _stage_verdict(tmp_path, monkeypatch, _measured(census, ""))

    assert verdict.error is not None
    assert verdict.error.code == "GATE_COMPLEXIPY_OUTPUT_UNREADABLE"
    assert verdict.exit_code == 2


def test_unmeasurable_path_report_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # complexipy telling us it could not analyze a file IS a narrowed surface,
    # in the tool's own words.
    _snapshot(tmp_path)
    census = _census(_light(tmp_path)) + (
        "error: Failed to process src/broken.py - Please check file/folder exists\n"
    )

    verdict = _stage_verdict(tmp_path, monkeypatch, _measured(census, ""))

    assert verdict.error is not None
    assert verdict.error.code == "GATE_COMPLEXIPY_PATHS_UNMEASURABLE"
    assert verdict.exit_code == 2


def test_offender_absent_from_the_census_is_measurement_skew(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The offender set is a FILTER of the census, so it cannot hold a function the
    # census never saw. If it does, the two runs are not one observation and the
    # comparison inputs must not be graded.
    _write(tmp_path, "src/heavy.py", A_FUNCTION)
    _snapshot(tmp_path, ("src/heavy.py", "heavy", 33))
    census = _census(("src/heavy.py", "heavy", 33))

    verdict = _stage_verdict(
        tmp_path, monkeypatch, _measured(census, _census(("src/ghost.py", "ghost", 40)))
    )

    assert verdict.error is not None
    assert verdict.error.code == "GATE_COMPLEXIPY_MEASUREMENT_SKEW"
    assert verdict.exit_code == 2


# --- GREEN: the worlds that must stay green ----------------------------------


def test_unchanged_floor_is_clean_at_the_watermark(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A function sitting AT its watermark passes — complexipy's own `>` bound,
    # preserved exactly (relaxing it to `>=` would be a softening).
    _write(tmp_path, "src/heavy.py", A_FUNCTION)
    _snapshot(tmp_path, ("src/heavy.py", "heavy", 33))
    rows = _census(("src/heavy.py", "heavy", 33))

    verdict = _stage_verdict(tmp_path, monkeypatch, _measured(rows, rows))

    assert verdict.passed, _codes(verdict)
    assert verdict.exit_code == 0


def test_legitimate_non_empty_shrink_is_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # One offender simplified below the bar, the other untouched: the floor is
    # still populated, the improved file is still MEASURED, and the verdict is
    # green. Locking the shrink in stays the runbook's re-boot duty — but the same
    # file falling OUT of the census would not pass (the rod above).
    _write(tmp_path, "src/improved.py", A_FUNCTION)
    _write(tmp_path, "src/heavy.py", A_FUNCTION)
    _snapshot(tmp_path, ("src/improved.py", "improved", 30), ("src/heavy.py", "heavy", 20))
    census = _census(("src/improved.py", "improved", 4), ("src/heavy.py", "heavy", 20))

    verdict = _stage_verdict(
        tmp_path, monkeypatch, _measured(census, _census(("src/heavy.py", "heavy", 20)))
    )

    assert verdict.passed, _codes(verdict)


def test_clean_repo_with_an_empty_floor_is_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The boot state a consumer adopts at: `[]` on disk, nothing over the bar, and
    # a census that DID measure something. Clean, and provably not a void.
    _snapshot(tmp_path)

    verdict = _stage_verdict(tmp_path, monkeypatch, _measured(_census(_light(tmp_path)), ""))

    assert verdict.passed, _codes(verdict)
    assert verdict.exit_code == 0


# --- the write-free invocation (the root of the fix) -------------------------


def test_measurement_argv_can_never_write_the_committed_floor() -> None:
    # The pinned tool reaches `create_snapshot_file` from exactly two places:
    # `--snapshot-create`, and the watermark compare's success path that
    # `--snapshot-ignore` switches off. Both flags are load-bearing, both runs.
    for offenders_only in (False, True):
        argv = measurement_argv(
            Path("/fake/complexipy"), Path("/repo/src"), offenders_only=offenders_only
        )
        assert argv[:2] == ["/fake/complexipy", "/repo/src"]
        assert "--snapshot-ignore" in argv, "the compare — and its rewrite — stays off"
        assert "--snapshot-create" not in argv, "the gate never writes the artifact it grades"
        assert "--plain" in argv, "the census must be machine-readable to be graded"
        assert ("--failed" in argv) is offenders_only


def test_measurement_runs_pin_columns_so_the_census_cannot_wrap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # rich wraps at 80 columns when stdout is not a terminal, and a wrapped census
    # row is an UNPARSEABLE census row — the gate would refuse a healthy repo, or
    # (worse, in a laxer parser) read a narrower world. COLUMNS is load-bearing.
    row = _light(tmp_path)
    _snapshot(tmp_path)
    seen: list[dict[str, str]] = []

    def recording_exec(
        argv: list[str],
        cwd: Path,
        env: Mapping[str, str],
        *,
        stdin: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        seen.append(dict(env))
        return subprocess.CompletedProcess(argv, 0, _census(row), "")

    monkeypatch.setattr(gate_runner, "_tool", lambda name: Path("/fake") / name)
    monkeypatch.setattr(gate_runner, "_exec", recording_exec)

    gate_runner._complexipy(_layout(tmp_path), {"PATH": "/usr/bin"})

    assert len(seen) == 2, "the census run and the offender run"
    for env in seen:
        assert int(env["COLUMNS"]) >= 1000, "an 80-column wrap would break the census parse"
        assert env["PYTHONIOENCODING"] == "utf-8", "the census decodes UTF-8, never by locale"
        assert env["PATH"] == "/usr/bin", "the caller's environment survives the overlay"


def test_the_committed_floor_is_only_ever_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Asserted on the artifact itself. With the tool faked this rod can only fail
    # if OUR code writes the floor; the tool-side half of the proof is the argv rod
    # above plus the two call sites in the pinned package. Under the tool's own
    # compare this very green run rewrote these bytes to the measured subset.
    _write(tmp_path, "src/heavy.py", A_FUNCTION)
    _snapshot(tmp_path, ("src/heavy.py", "heavy", 33))
    snapshot = tmp_path / "complexipy-snapshot.json"
    before = snapshot.read_bytes()
    rows = _census(("src/heavy.py", "heavy", 33))

    verdict = _stage_verdict(tmp_path, monkeypatch, _measured(rows, rows))

    assert verdict.passed, _codes(verdict)
    assert snapshot.read_bytes() == before, "the gate graded the floor without touching it"


# --- the ratchet as a pure function (no subprocess at all) -------------------


def test_grade_is_a_pure_function_of_the_floor_and_the_census(tmp_path: Path) -> None:
    # The property the tool's own compare cannot have: the comparison runs with no
    # subprocess, no write and no tool exit code, so it is testable in isolation
    # and no green run can destroy it. Every finding carries the measured tally.
    _write(tmp_path, "src/heavy.py", A_FUNCTION)
    floor = {("src/heavy.py", "heavy"): 20}
    census = Census(functions={("src/heavy.py", "heavy"): 31})

    verdict = grade(tmp_path, tmp_path / "src", floor, census, census)

    assert _codes(verdict) == ["COMPLEXIPY_WATERMARK_REGRESSION"]
    assert verdict.violations[0].context["measured_functions"] == 1
    assert verdict.violations[0].context["snapshot_functions"] == 1


def test_read_snapshot_keys_the_observed_on_disk_shape(tmp_path: Path) -> None:
    # Keyed the way complexipy's own output joins its two path fields: get that
    # join wrong and every committed watermark reads as a brand-new offender.
    # Shape and `Class::method` naming taken from a real consumer's snapshot.
    _write(
        tmp_path,
        "complexipy-snapshot.json",
        json.dumps(
            [
                {
                    "path": "src/pkg/mod.py",
                    "file_name": "mod.py",
                    "functions": [
                        {"name": "Engine::_run_inner", "complexity": 18},
                        {"name": "Engine::_execute_stage", "complexity": 27},
                    ],
                }
            ]
        ),
    )

    floor = read_snapshot(tmp_path / "complexipy-snapshot.json")

    assert floor == {
        ("src/pkg/mod.py", "Engine::_run_inner"): 18,
        ("src/pkg/mod.py", "Engine::_execute_stage"): 27,
    }


def test_census_parser_survives_a_path_containing_spaces() -> None:
    # `--plain` is space-separated, so the parse must split from the RIGHT: the
    # complexity and the function name are single tokens, a path is not.
    census = complexipy_ratchet.parse_census("src/odd dir/mod.py Klass::method 12\n")

    assert census.functions == {("src/odd dir/mod.py", "Klass::method"): 12}
    assert census.files == frozenset({"src/odd dir/mod.py"})


# --- the preserved absent-watermark doctrine ---------------------------------


def test_absent_floor_doctrine_is_untouched(tmp_path: Path) -> None:
    # Unchanged by this rework, and re-pinned here because the rework rewrote the
    # stage: Python present with no snapshot REFUSES; a Python-free repo skips.
    _write(tmp_path, "src/light.py", A_FUNCTION)

    with pytest.raises(GateError) as excinfo:
        gate_runner._complexipy(_layout(tmp_path, py_present=True), {})
    assert excinfo.value.code == "GATE_COMPLEXIPY_SNAPSHOT_MISSING"

    assert gate_runner._complexipy(_layout(tmp_path, py_present=False), {}) is None
