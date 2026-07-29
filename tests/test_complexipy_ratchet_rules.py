"""The ratchet's rules where they were VACUOUS or WRONG — one rod per refuter finding.

``tests/test_complexipy_snapshot.py`` pins the worlds the ratchet already graded
correctly. This file pins the worlds it graded green while measuring nothing, or
graded red while nothing was wrong:

- **the raised bar (the primary rule going vacuous).** ``_vacuity`` guarded only
  the CENSUS, and ``_skew`` is a subset check an empty subset satisfies trivially.
  So with ``[tool.complexipy] max-complexity-allowed = 100`` the census still
  listed every function (every floor file present, surface audit silent), the
  ``--failed`` run returned NOTHING, and the stage exited 0 while cheerfully
  reporting it had measured 681 functions against a 12-function floor. A function
  that went 33 -> 90 was green. That is
  ``gate-that-selects-by-the-value-it-guards-goes-vacuous`` inside the fix for it,
  and the closure is threshold-free by construction — the kit still declares no
  budget of its own;
- **the ignore comment that voided a watermark.** The audit was per-FILE, and an
  ignored function leaves its file in ``census.files``, so nothing fired: an
  unregistered exemption from the complexity gate, invisible to ``cf-exemptions``
  too;
- **the symlinked module accused of being outside the tree**, because the FILE was
  resolved rather than the roots;
- **the duplicate ``(path, name)`` pair** faking a skew, or hiding a regression;
- **the messages**, which stated a condition and named no remedy, while the docs
  claimed they named the re-boot;
- **the PASS with no evidence**, which a machine could not tell from a void.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from test_complexipy_snapshot import A_FUNCTION, _census, _codes, _measured, _snapshot
from test_complexipy_snapshot import _stage_verdict as _verdict
from test_gate_runner import _write

from cf_quality.errors import GateVerdict
from cf_quality.gate_runner import _Aggregate, _emit_human

# --- BLOCKER 2: the offender census's threshold-free vacuity closure -----------


def test_a_raised_threshold_empties_the_offender_set_and_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Reproduction (b) from the tool spike, arriving through CONFIG rather than
    # through `-mx`: the bar is high enough that a 90-complexity function is not an
    # offender. The census is complete, the file is measured, the surface audit has
    # nothing to say, the offender set is EMPTY — and the old ratchet iterated that
    # empty dict, found no regression, and exited 0 on a 33 -> 90 regression.
    #
    # The closure names no threshold. A floor entry proves that function was ABOVE
    # the bar when the floor was booted, so census 90 >= watermark 33 while the
    # offender run stays silent means threshold_now >= 90 >= 33 > threshold_at_boot.
    _write(tmp_path, "src/heavy.py", A_FUNCTION)
    _snapshot(tmp_path, ("src/heavy.py", "heavy", 33))

    verdict = _verdict(tmp_path, monkeypatch, _measured(_census(("src/heavy.py", "heavy", 90)), ""))

    assert verdict.error is not None
    assert verdict.error.code == "GATE_COMPLEXIPY_THRESHOLD_RAISED"
    assert verdict.exit_code == 2
    assert "src/heavy.py:heavy (measured 90 >= watermark 33)" in verdict.error.context["functions"]
    assert "--snapshot-create" in verdict.error.message, "the refusal names its remedy"


def test_a_function_exactly_at_its_watermark_still_must_appear_as_an_offender(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The tight edge of the same rule, and the reason it is `>=` and not `>`: at
    # census == watermark the function is still above the BOOT threshold, so an
    # offender run that omits it can only mean the bar moved. The green counterpart
    # (same numbers, offender run reporting it) is pinned in
    # test_complexipy_snapshot.test_unchanged_floor_is_clean_at_the_watermark.
    _write(tmp_path, "src/heavy.py", A_FUNCTION)
    _snapshot(tmp_path, ("src/heavy.py", "heavy", 33))

    verdict = _verdict(tmp_path, monkeypatch, _measured(_census(("src/heavy.py", "heavy", 33)), ""))

    assert verdict.error is not None
    assert verdict.error.code == "GATE_COMPLEXIPY_THRESHOLD_RAISED"


def test_a_hand_lowered_watermark_lands_in_the_same_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # complexipy stores only OVER-threshold functions, so a watermark of 1 could
    # never have come from the boot command. The floor was edited, and the refusal
    # is correct rather than a false positive.
    _write(tmp_path, "src/light.py", A_FUNCTION)
    _snapshot(tmp_path, ("src/light.py", "a_function", 1))

    census = _census(("src/light.py", "a_function", 4))

    verdict = _verdict(tmp_path, monkeypatch, _measured(census, ""))

    assert verdict.error is not None
    assert verdict.error.code == "GATE_COMPLEXIPY_THRESHOLD_RAISED"


def test_a_genuine_shrink_below_its_watermark_is_still_green(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # THE control rod on the closure above: it must fire on a moved bar and NOT on
    # the improvement it superficially resembles. 30 -> 4 is under the watermark, so
    # census < watermark and the rule does not engage. Without this rod the closure
    # could be "refuse whenever the offender set is empty", which would red every
    # healthy repo that fixed its last offender.
    _write(tmp_path, "src/improved.py", A_FUNCTION)
    _snapshot(tmp_path, ("src/improved.py", "improved", 30))

    verdict = _verdict(
        tmp_path, monkeypatch, _measured(_census(("src/improved.py", "improved", 4)), "")
    )

    assert verdict.passed, _codes(verdict)


# --- DEFECT 6: the ignore comment that silently voided a watermark ------------


def test_a_floor_function_missing_from_a_MEASURED_file_is_a_violation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `# complexipy: ignore` drops a function from BOTH runs while its file stays in
    # census.files, so the per-FILE audit saw nothing — an unregistered, unblessed
    # exemption from the complexity gate. The distinction that makes this catchable:
    # `--plain` without `--failed` lists every measured function regardless of
    # threshold, so a function that merely got SIMPLER would still be here.
    _write(tmp_path, "src/heavy.py", A_FUNCTION)
    _snapshot(tmp_path, ("src/heavy.py", "ignored", 33), ("src/heavy.py", "kept", 20))
    census = _census(("src/heavy.py", "kept", 20))

    verdict = _verdict(tmp_path, monkeypatch, _measured(census, census))

    assert _codes(verdict) == ["COMPLEXIPY_SNAPSHOT_FUNCTION_UNMEASURED"]
    assert verdict.exit_code == 1
    violation = verdict.violations[0]
    assert violation.path == "src/heavy.py" and violation.context["function"] == "ignored"
    assert "complexipy: ignore" in violation.message, "the message names the likely cause"
    assert "--snapshot-create" in violation.message, "and the remedy"


def test_a_whole_file_going_unmeasured_still_reports_once_not_per_function(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The per-function audit must not turn one narrowed file into N identical
    # findings — the file-level reading is the more informative one and comes first.
    _write(tmp_path, "src/heavy.py", A_FUNCTION)
    _snapshot(tmp_path, ("src/heavy.py", "one", 33), ("src/heavy.py", "two", 20))
    _write(tmp_path, "src/light.py", A_FUNCTION)

    verdict = _verdict(
        tmp_path, monkeypatch, _measured(_census(("src/light.py", "a_function", 1)), "")
    )

    assert _codes(verdict) == ["COMPLEXIPY_SNAPSHOT_FILE_UNMEASURED"]


# --- DEFECT 7: the symlinked module accused of being outside the tree ---------


def test_a_symlinked_module_inside_the_tree_is_not_called_outside_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `_surface_violations` resolved the FILE, so src/settings.py -> ../vendor/
    # settings.py resolved outside the graded root and the gate reported that the
    # floor entry "lies OUTSIDE the graded source root" — flatly false: it is
    # inside, and complexipy measured it. Roots are resolved; the floor's own paths
    # are repo-relative, so containment is lexical.
    _write(tmp_path, "vendor/settings.py", A_FUNCTION)
    (tmp_path / "src").mkdir(exist_ok=True)
    (tmp_path / "src" / "settings.py").symlink_to(tmp_path / "vendor" / "settings.py")
    _snapshot(tmp_path, ("src/settings.py", "settings", 20))
    census = _census(("src/settings.py", "settings", 20))

    verdict = _verdict(tmp_path, monkeypatch, _measured(census, census))

    assert verdict.passed, _codes(verdict)


def test_a_floor_entry_genuinely_outside_the_graded_root_is_still_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The control rod on the fix above: making the test lexical must not make it
    # vacuous. legacy/ is a real sibling of the graded src/, and still fires.
    _write(tmp_path, "legacy/heavy.py", A_FUNCTION)
    _write(tmp_path, "src/light.py", A_FUNCTION)
    _snapshot(tmp_path, ("legacy/heavy.py", "heavy", 33))

    verdict = _verdict(
        tmp_path, monkeypatch, _measured(_census(("src/light.py", "a_function", 1)), "")
    )

    assert _codes(verdict) == ["COMPLEXIPY_SURFACE_NARROWED"]
    assert "--snapshot-create" in verdict.violations[0].message, "the finding names its remedy"


# --- DEFECT 5: the vacuity leg consults the REPO-WIDE answer ------------------


def test_a_python_free_source_root_beside_real_code_cannot_report_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `resolve_source_root` returns root/src whenever src/ EXISTS, so a repo whose
    # code lives in app/ beside an empty-but-present src/ measured zero functions
    # with a floor of [] — and both old vacuity legs were blind, because leg 2
    # walked the same possibly-wrong source_root. The leg now rides the CALLER's
    # repo-wide py_present, the same answer the absent-snapshot doctrine uses, so
    # the two surfaces cannot disagree.
    _write(tmp_path, "app/real.py", A_FUNCTION)
    (tmp_path / "src").mkdir()
    _snapshot(tmp_path)

    verdict = _verdict(tmp_path, monkeypatch, _measured("", ""))

    assert verdict.error is not None
    assert verdict.error.code == "GATE_COMPLEXIPY_MEASURED_NOTHING"
    assert verdict.error.context["python_present"] is True
    assert verdict.exit_code == 2


# --- DEFECT 10: a duplicate pair must not fake a skew -------------------------


def test_a_duplicated_key_straddling_a_watermark_reports_the_regression_not_a_skew(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Observed live: one consumer file lists the same (path, name) twice. Under
    # last-writer-wins with sort = "desc" the offender map kept 40 while the census
    # kept 4, so the runs "disagreed" and the gate raised a bogus
    # GATE_COMPLEXIPY_MEASUREMENT_SKEW on a healthy repo — and in the mirror case
    # the regression vanished from both maps. max() on both sides gives one world.
    _write(tmp_path, "src/heavy.py", A_FUNCTION)
    _snapshot(tmp_path, ("src/heavy.py", "heavy", 20))
    census = _census(("src/heavy.py", "heavy", 40), ("src/heavy.py", "heavy", 4))

    verdict = _verdict(tmp_path, monkeypatch, _measured(census, census))

    assert verdict.error is None, "a repeated key is not two worlds"
    assert _codes(verdict) == ["COMPLEXIPY_WATERMARK_REGRESSION"]
    assert verdict.violations[0].context["measured"] == 40, "max(), so the HIGH value grades"
    assert verdict.violations[0].context["measured_functions"] == 2, "rows, not keys"


# --- DEFECT 9 + the evidence a PASS must carry -------------------------------


def test_every_regression_message_names_a_remedy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A message that states the condition and names nothing to do is half a
    # message, and the docs corrected on this branch already claimed these named
    # the re-boot. They now do — spelled with the resolved graded root.
    _write(tmp_path, "src/heavy.py", A_FUNCTION)
    _snapshot(tmp_path, ("src/heavy.py", "kept", 20))
    census = _census(("src/heavy.py", "kept", 26), ("src/heavy.py", "fresh", 40))

    verdict = _verdict(tmp_path, monkeypatch, _measured(census, census))

    assert _codes(verdict) == ["COMPLEXIPY_NEW_OFFENDER", "COMPLEXIPY_WATERMARK_REGRESSION"]
    for violation in verdict.violations:
        assert "complexipy src --snapshot-create" in violation.message
        assert "from the repo root" in violation.message


def test_a_passing_stage_carries_its_measurement_in_the_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The discrimination this whole rung exists to make: a machine reading the
    # aggregated JSON must be able to tell a clean grade from a vacuous one. The
    # counts used to go only to stderr via a hand-rolled print, so a PASSING stage's
    # to_dict() carried no evidence at all — and the workflows pipe only stdout into
    # $GITHUB_STEP_SUMMARY, so even the human never saw it on the board.
    _write(tmp_path, "src/heavy.py", A_FUNCTION)
    _snapshot(tmp_path, ("src/heavy.py", "heavy", 33))
    rows = _census(("src/heavy.py", "heavy", 33), ("src/other.py", "fine", 2))

    offenders = _census(("src/heavy.py", "heavy", 33))

    verdict = _verdict(tmp_path, monkeypatch, _measured(rows, offenders))

    assert verdict.passed, _codes(verdict)
    wire = verdict.to_dict()
    assert wire["evidence"]["measured_functions"] == 2
    assert wire["evidence"]["measured_files"] == 2
    assert wire["evidence"]["snapshot_functions"] == 1
    assert wire["notices"] == verdict.notices and len(verdict.notices) == 1
    assert "measured 2 function(s) in 2 file(s)" in verdict.notices[0]


def test_the_human_board_shows_the_measurement_beside_a_pass(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The notice must ride STDOUT beside the PASS line, because that is the stream
    # both workflows tee into $GITHUB_STEP_SUMMARY — a count only on stderr reaches
    # the run log and not the board that carries the verdict.
    verdict = GateVerdict(gate="complexipy", violations=[], notices=["— m"])

    _emit_human(_Aggregate(verdicts=[verdict]))

    assert "PASS  complexipy — m" in capsys.readouterr().out
