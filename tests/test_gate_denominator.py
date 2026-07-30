"""Every cf-* gate states WHAT IT EXAMINED — the denominator contract.

A board line reading ``PASS  cf-no-bon-ref`` is a name, not an event: it reads
the same whether the gate swept four hundred files or none at all. So every
cf-* gate carries ONE denominator line on its verdict (``notices``) and the
same measurement in machine form (``evidence``), and both ride the wire the
runner parses back — which is what makes the aggregated board line say what was
measured instead of merely that something passed. The external tools on the
board (ruff, mypy, complexipy, pytest) are deliberately out of scope: they own
their own output and the kit does not compute their denominators.

The control rod is the ZERO case: a gate driven to examine nothing must render
a visible ``0``, never an omitted line. A suppressed zero is exactly the vacuous
PASS this contract exists to expose, so it is asserted per gate, in the rendered
output. Each zero fixture is built to be the SHAPE that hides the defect — a
tree of one unreadable binary, a ``src/`` holding no Python — not merely an
empty directory, because an empty directory drives every counting bug to 0 too.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from test_import_contract import _mount as mount_contract_repo
from test_import_contract import _run_main as contract_run_main

from cf_quality import gate_runner
from cf_quality.errors import GateVerdict, GateViolation
from cf_quality.exemptions import main as exemptions_main
from cf_quality.file_budget import main as file_budget_main
from cf_quality.import_contract import main as import_contract_main
from cf_quality.mirror_check import main as mirror_main
from cf_quality.mirror_check import render_template
from cf_quality.no_bon_ref import main as no_bon_ref_main
from cf_quality.recursion_check import main as recursion_main
from cf_quality.sticky_check import canonical_text
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
    assert verdict["notices"] == ["— read 2 text file(s) of the code/config tree for ticket refs"]
    assert verdict["evidence"] == {"files_read": 2}


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
    assert verdict["notices"] == [
        "— measured 1 file(s) against 0 frozen file entry(ies), 0 declared-not-banned "
        "entry(ies) and 0 frozen package budget(s)"
    ]
    # BOTH baselines the gate enforces ride the evidence — the package budget is
    # a second ceiling, and reporting only the file entries hid it.
    assert verdict["evidence"] == {
        "files_measured": 1,
        "frozen_files": 0,
        "declared_files": 0,
        "frozen_packages": 0,
    }


def test_declared_not_banned_entries_are_not_counted_as_frozen(
    tmp_path: Path, capsys: Any, monkeypatch: Any
) -> None:
    # A purpose-only entry has NO line ceiling — _check_file treats it exactly
    # like an undeclared file. Counting the whole baseline as "frozen" claimed a
    # shrink-only ratchet over a file that has none.
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "file-budget.json").write_text(
        json.dumps({"files": {"a.py": {"purpose": "adapter"}}, "packages": {}}), encoding="utf-8"
    )
    monkeypatch.setenv("CF_QUALITY_JSON", "1")

    assert file_budget_main(["check", "--root", str(tmp_path)]) == 0
    evidence = json.loads(capsys.readouterr().out)["evidence"]

    assert evidence["frozen_files"] == 0, "a purpose without a line count freezes nothing"
    assert evidence["declared_files"] == 1


def test_file_budget_evidence_carries_both_frozen_baselines(
    tmp_path: Path, capsys: Any, monkeypatch: Any
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "file-budget.json").write_text(
        json.dumps({"files": {}, "packages": {"src": 400}}), encoding="utf-8"
    )
    monkeypatch.setenv("CF_QUALITY_JSON", "1")

    assert file_budget_main(["check", "--root", str(tmp_path)]) == 0
    verdict = json.loads(capsys.readouterr().out)

    assert verdict["evidence"]["frozen_packages"] == 1, "a package ceiling is a measured budget"
    assert verdict["evidence"]["frozen_files"] == 0


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
        "PASS  cf-no-bon-ref — read 1 text file(s) of the code/config tree for ticket refs"
    )


# --- the control rod: a gate that examined nothing must SHOW the zero --------


def test_zero_denominator_counts_files_read_not_files_offered(tmp_path: Path, capsys: Any) -> None:
    # The shape that hides the defect: the walk OFFERS this file, scan_file
    # bails on the NUL byte before reading a line of it. A denominator counting
    # the offer would say 1 and certify a sweep that never looked inside.
    (tmp_path / "asset.png").write_bytes(b"\x89PNG\x00\x00binary\x00")

    assert no_bon_ref_main(["--root", str(tmp_path)]) == 0
    assert "— read 0 text file(s)" in capsys.readouterr().out


def test_zero_denominator_is_visible_for_recursion_check(tmp_path: Path, capsys: Any) -> None:
    # A present tree holding NO Python, not a bare empty dir: the walk offers a
    # file and the gate must still say 0. An empty directory drives every
    # counting bug to 0 and so proves nothing.
    (tmp_path / "notes.txt").write_text("not python\n", encoding="utf-8")

    assert recursion_main([str(tmp_path)]) == 0
    assert "— walked 0 Python file(s)" in capsys.readouterr().out


def test_recursion_denominator_tracks_the_files_it_walked(tmp_path: Path, capsys: Any) -> None:
    # The zero alone would survive a hardcoded 0. This is the other half of the
    # rod: the same gate on real Python must report the count, not the constant.
    for name in ("a.py", "b.py"):
        (tmp_path / name).write_text("x = 1\n", encoding="utf-8")

    assert recursion_main([str(tmp_path)]) == 0
    assert "— walked 2 Python file(s)" in capsys.readouterr().out


def test_zero_denominator_is_visible_for_file_budget(tmp_path: Path, capsys: Any) -> None:
    # Present tree, no Python — the budget measures *.py only, so a denominator
    # counting every file it was offered would read 1 here.
    (tmp_path / "README.md").write_text("# prose\n", encoding="utf-8")

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


def test_sticky_denominator_reads_one_when_a_claude_md_was_examined(
    tmp_path: Path, capsys: Any
) -> None:
    # Without this, `int(present)` could be hardcoded to 0 and every board line
    # would claim the gauge examined nothing while still grading the file.
    (tmp_path / "CLAUDE.md").write_text(canonical_text(), encoding="utf-8")

    assert sticky_main(["check", str(tmp_path)]) == 0
    assert "— examined 1 CLAUDE.md" in capsys.readouterr().out


def test_zero_denominator_for_exemptions_counts_files_not_surface_bases(
    tmp_path: Path, capsys: Any
) -> None:
    # The shape that hides the defect (and the mexxa scar itself): a repo-root
    # src/ that holds NO Python. The surface resolves to exactly one base either
    # way, so a base count reads 1 and certifies a scanner that opened nothing.
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.js").write_text("const x = 1;\n", encoding="utf-8")

    assert exemptions_main(["--root", str(tmp_path)]) == 0
    assert "— read 0 Python file(s)" in capsys.readouterr().out


def test_exemptions_denominator_tracks_the_files_it_tokenized(tmp_path: Path, capsys: Any) -> None:
    # The control rod's other half: the same repo with real Python must NOT
    # report the same number. A base count reported both worlds identically.
    (tmp_path / "src").mkdir()
    for name in ("a.py", "b.py", "c.py"):
        (tmp_path / "src" / name).write_text("x = 1\n", encoding="utf-8")

    assert exemptions_main(["--root", str(tmp_path)]) == 0
    assert "— read 3 Python file(s)" in capsys.readouterr().out


def test_zero_denominator_is_visible_for_import_contract_clauses(
    tmp_path: Path, capsys: Any
) -> None:
    assert import_contract_main(["--root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "— linted 0 contract clause(s); scanned 0 module(s)" in out


def test_import_contract_evidence_schema_is_identical_on_both_branches(
    tmp_path: Path, capsys: Any, monkeypatch: Any
) -> None:
    # One gate must speak ONE evidence schema. The no-contract branch and the
    # linted branch shipped different keys, so a machine reading the field it
    # knew got silence from the other half of the same gate. The mounted fixture
    # is REUSED from the gate's own suite rather than pasted.
    monkeypatch.setenv("CF_QUALITY_JSON", "1")
    bare = tmp_path / "bare"
    bare.mkdir()
    assert contract_run_main(bare, monkeypatch) == 0
    missing = json.loads(capsys.readouterr().out)["evidence"]

    mounted = tmp_path / "mounted"
    mount_contract_repo(mounted)
    assert contract_run_main(mounted, monkeypatch) == 0
    linted = json.loads(capsys.readouterr().out)["evidence"]

    assert missing.keys() == linted.keys() == {"contract_clauses", "modules_scanned"}
    assert missing == {"contract_clauses": 0, "modules_scanned": 0}
    assert linted["contract_clauses"] == 1
    assert linted["modules_scanned"] == 3, "core/__init__ + tenants/__init__ + tenants/acme"


def test_zero_denominator_is_visible_for_mirror_check(tmp_path: Path, capsys: Any) -> None:
    # A MIRRORS.md carrying the header and no rows declares no cross-repo copies.
    (tmp_path / "MIRRORS.md").write_text(render_template(), encoding="utf-8")

    assert mirror_main(["check", "--repo", str(tmp_path)]) == 0
    assert "— checked 0 declared mirror row(s)" in capsys.readouterr().out
