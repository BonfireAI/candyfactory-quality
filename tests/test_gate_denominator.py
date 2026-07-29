"""Every cf-* gate states WHAT IT EXAMINED — the denominator contract.

A board line reading ``PASS  cf-no-bon-ref`` is a name, not an event: it reads
the same whether the gate swept four hundred files or none at all. So every
gate carries ONE denominator line on its verdict (``notices``) and the same
measurement in machine form (``evidence``), and both ride the wire the runner
parses back — which is what makes the aggregated board line say what was
measured instead of merely that something passed.

The control rod is the ZERO case: a gate driven to examine nothing must render
a visible ``0``, never an omitted line. A suppressed zero is exactly the vacuous
PASS this contract exists to expose, so it is asserted per gate, in the rendered
output, on a tree built to be empty.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from cf_quality import gate_runner
from cf_quality.errors import GateVerdict, GateViolation
from cf_quality.exemptions import main as exemptions_main
from cf_quality.file_budget import main as file_budget_main
from cf_quality.import_contract import main as import_contract_main
from cf_quality.mirror_check import main as mirror_main
from cf_quality.mirror_check import render_template
from cf_quality.no_bon_ref import main as no_bon_ref_main
from cf_quality.recursion_check import main as recursion_main
from cf_quality.sticky_check import main as sticky_main

# --- the wire carries the measurement (real JSON, no mock) -------------------


def test_wire_carries_populated_notices_and_evidence(
    tmp_path: Path, capsys: Any, monkeypatch: Any
) -> None:
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "b.css").write_text("body { color: red; }\n", encoding="utf-8")
    monkeypatch.setenv("CF_QUALITY_JSON", "1")

    assert no_bon_ref_main(["--root", str(tmp_path)]) == 0
    verdict = json.loads(capsys.readouterr().out)

    assert verdict["passed"] is True
    assert verdict["notices"] == ["— swept 2 file(s) of the code/config tree for ticket refs"]
    assert verdict["evidence"] == {"files_swept": 2}


def test_file_budget_speaks_the_wire_form_like_every_other_gate(
    tmp_path: Path, capsys: Any, monkeypatch: Any
) -> None:
    # It used to hand-roll its own JSON and print 'cf-file-budget: clean' even
    # under CF_QUALITY_JSON=1 — the wire form is now the shared one.
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setenv("CF_QUALITY_JSON", "1")

    assert file_budget_main(["check", "--root", str(tmp_path)]) == 0
    verdict = json.loads(capsys.readouterr().out)

    assert verdict["gate"] == "cf-file-budget"
    assert verdict["notices"] == ["— measured 1 file(s) against 0 frozen entry(ies)"]
    assert verdict["evidence"] == {"files_measured": 1, "frozen_files": 0}


def test_structured_verdict_round_trips_notices_and_evidence() -> None:
    source = GateVerdict(
        gate="cf-x",
        violations=[GateViolation(code="X_BROKE", message="m", path="p", line=3)],
        notices=["— measured 7 thing(s) against a 2-thing floor"],
        evidence={"things": 7, "floor": 2},
    )

    parsed = gate_runner._structured_verdict("cf-x", source.to_dict())

    assert parsed.notices == source.notices
    assert parsed.evidence == source.evidence
    assert [v.code for v in parsed.violations] == ["X_BROKE"]


def test_aggregated_board_line_carries_the_gate_denominator(tmp_path: Path, capsys: Any) -> None:
    # End to end: the real console script runs, its JSON is parsed back, and the
    # runner's board line shows the measurement instead of a bare PASS.
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    verdict = gate_runner._run_cf_gate(
        "cf-no-bon-ref", ["--root", str(tmp_path)], cwd=tmp_path, env=os.environ
    )
    assert verdict.passed

    gate_runner._emit_human(gate_runner._Aggregate(verdicts=[verdict], exit_code=0))
    board = capsys.readouterr().out.splitlines()[0]

    assert board == (
        "PASS  cf-no-bon-ref — swept 1 file(s) of the code/config tree for ticket refs"
    )


# --- the control rod: a gate that examined nothing must SHOW the zero --------


def test_zero_denominator_is_visible_for_no_bon_ref(tmp_path: Path, capsys: Any) -> None:
    assert no_bon_ref_main(["--root", str(tmp_path)]) == 0
    assert "— swept 0 file(s)" in capsys.readouterr().out


def test_zero_denominator_is_visible_for_recursion_check(tmp_path: Path, capsys: Any) -> None:
    assert recursion_main([str(tmp_path)]) == 0
    assert "— walked 0 Python file(s)" in capsys.readouterr().out


def test_zero_denominator_is_visible_for_file_budget(tmp_path: Path, capsys: Any) -> None:
    assert file_budget_main(["check", "--root", str(tmp_path)]) == 0
    assert "— measured 0 file(s)" in capsys.readouterr().out


def test_zero_denominator_is_visible_for_sticky_check(tmp_path: Path, capsys: Any) -> None:
    # The client-repo waiver: no CLAUDE.md to examine, and the gate is green —
    # the one shape where a PASS legitimately measured nothing, and says so.
    (tmp_path / ".cf-quality.toml").write_text(
        "[tool.cf-quality]\nclient_repo = true\n", encoding="utf-8"
    )

    assert sticky_main(["check", str(tmp_path)]) == 0
    assert "— examined 0 CLAUDE.md" in capsys.readouterr().out


def test_zero_denominator_is_visible_for_exemptions(tmp_path: Path, capsys: Any) -> None:
    assert exemptions_main(["--root", str(tmp_path)]) == 0
    assert "— measured 0 suppression(s) over 0 scan path(s)" in capsys.readouterr().out


def test_zero_denominator_is_visible_for_import_contract(tmp_path: Path, capsys: Any) -> None:
    assert import_contract_main(["--root", str(tmp_path)]) == 0
    assert "— linted 0 contract clause(s)" in capsys.readouterr().out


def test_zero_denominator_is_visible_for_mirror_check(tmp_path: Path, capsys: Any) -> None:
    # A MIRRORS.md carrying the header and no rows declares no cross-repo copies.
    (tmp_path / "MIRRORS.md").write_text(render_template(), encoding="utf-8")

    assert mirror_main(["check", "--repo", str(tmp_path)]) == 0
    assert "— checked 0 declared mirror row(s)" in capsys.readouterr().out
