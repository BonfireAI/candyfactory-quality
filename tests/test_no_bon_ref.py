"""Tests for cf-no-bon-ref — the consumer-tree ticket-reference sweep.

The law ([[no-ticket-ids-in-code]]): a Linear ticket id is a LOCAL index,
meaningless to anyone reading the code or the diff. It must never appear in
the code/config tree — describe the work, not the ticket. This gauge is the
shippable, consumer-facing enforcement of that law (the kit's existing
``test_design_doc`` sweep only guards the kit's OWN docs).

Every ticket-ref literal in this file is BUILT BY CONCATENATION so this test
file itself never carries the contiguous pattern the gauge (and the kit's own
self-sweep) hunts for. Fixtures are written under ``tmp_path`` — outside any
swept tree — so the realistic offending content exists only at runtime.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cf_quality.errors import GateError, GateViolation
from cf_quality.no_bon_ref import check, main, scan_tree

# The ticket-ref shape the gauge hunts, assembled so this source stays clean.
_REF = "BON" + "-" + "1828"
_REF2 = "BON" + "-" + "1829"


def _write(root: Path, rel: str, body: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


# --- the sweep: a ticket ref in the code/config tree FAILS -------------------


def test_ref_in_python_comment_is_a_violation(tmp_path: Path) -> None:
    _write(tmp_path, "src/widget.py", f"# touch hardening ({_REF})\nx = 1\n")
    violations, _ = scan_tree(tmp_path)
    assert len(violations) == 1
    v = violations[0]
    assert v.code == "TICKET_REF_IN_SOURCE"
    assert v.path == "src/widget.py"
    assert v.line == 1
    assert _REF in v.message


def test_ref_in_css_and_gitignore_and_config_all_caught(tmp_path: Path) -> None:
    _write(tmp_path, "src/styles/builder.css", f"/* TOUCH HARDENING ({_REF}) */\n")
    _write(tmp_path, ".gitignore", f"# Playwright ({_REF} e2e)\ntest-results\n")
    _write(tmp_path, "playwright.config.js", f"// device matrix ({_REF}).\n")
    paths = {v.path for v in scan_tree(tmp_path)[0]}
    assert paths == {"src/styles/builder.css", ".gitignore", "playwright.config.js"}


def test_ref_in_test_name_is_caught(tmp_path: Path) -> None:
    # the law explicitly governs TEST NAMES, so the tests/ tree is swept.
    _write(tmp_path, "tests/test_more.py", f'"""covers {_REF}."""\nx = 1\n')
    paths = {v.path for v in scan_tree(tmp_path)[0]}
    assert "tests/test_more.py" in paths


def test_multiple_refs_one_violation_per_line(tmp_path: Path) -> None:
    _write(tmp_path, "src/a.py", f"# {_REF}\n# {_REF2}\nok = 1\n")
    violations, _ = scan_tree(tmp_path)
    assert len(violations) == 2
    assert {v.line for v in violations} == {1, 2}


def test_clean_tree_has_no_violations(tmp_path: Path) -> None:
    _write(tmp_path, "src/widget.py", "# touch hardening (phone-first)\nx = 1\n")
    assert scan_tree(tmp_path)[0] == []


# --- jurisdiction: docs/ carry provenance, not banned -----------------------


def test_docs_dir_is_out_of_jurisdiction(tmp_path: Path) -> None:
    # docs/ (ADRs, design, the debt ledger) legitimately map epic -> ticket;
    # the law governs CODE, not provenance prose.
    _write(tmp_path, "docs/design/plan.md", f"Epic {_REF} ships the builder.\n")
    _write(tmp_path, "docs/law-debt.md", f"- {_REF2} backend typed-error debt\n")
    assert scan_tree(tmp_path)[0] == []


def test_markdown_anywhere_is_prose_not_code(tmp_path: Path) -> None:
    # a README or markdown note is documentation provenance, even outside docs/.
    _write(tmp_path, "ts/README.md", f"Built under {_REF}.\n")
    _write(tmp_path, "src/NOTES.md", f"see {_REF2}\n")
    assert scan_tree(tmp_path)[0] == []


def test_vendored_and_vcs_and_caches_are_skipped(tmp_path: Path) -> None:
    _write(tmp_path, "node_modules/dep/index.js", f"// {_REF}\n")
    _write(tmp_path, "__pycache__/x.txt", f"{_REF}\n")
    _write(tmp_path, ".git/COMMIT_EDITMSG", f"{_REF}\n")
    assert scan_tree(tmp_path)[0] == []


def test_binary_files_are_skipped(tmp_path: Path) -> None:
    (tmp_path / "asset.png").write_bytes(b"\x89PNG\x00\x00" + _REF.encode() + b"\x00")
    assert scan_tree(tmp_path)[0] == []


# --- the reasoned, ratcheted exemption registry -----------------------------


def test_registered_exemption_blesses_a_code_path_ref(tmp_path: Path) -> None:
    _write(tmp_path, "src/generated/schema.py", f"# generated; upstream tag {_REF}\n")
    _write(
        tmp_path,
        "no-bon-ref-exemptions.json",
        '{"frozen_count": 1, "entries": ['
        '{"path": "src/generated/*", "reason": "vendored upstream codegen carries its tag"}]}',
    )
    violations, notices, _ = check(tmp_path)
    assert violations == []
    assert any("src/generated/schema.py" in line for line in notices)


def test_exemption_not_matching_still_fails(tmp_path: Path) -> None:
    _write(tmp_path, "src/hand.py", f"# {_REF}\n")
    _write(
        tmp_path,
        "no-bon-ref-exemptions.json",
        '{"frozen_count": 1, "entries": [{"path": "src/other/*", "reason": "elsewhere"}]}',
    )
    violations, _, _ = check(tmp_path)
    assert [v.path for v in violations] == ["src/hand.py"]


def test_entries_over_frozen_count_fails_ratchet(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "no-bon-ref-exemptions.json",
        '{"frozen_count": 0, "entries": [{"path": "src/x/*", "reason": "r"}]}',
    )
    violations, _, _ = check(tmp_path)
    assert any(v.code == "EXEMPTION_COUNT_EXCEEDED" for v in violations)


def test_malformed_exemption_registry_is_typed_error(tmp_path: Path) -> None:
    _write(tmp_path, "no-bon-ref-exemptions.json", "{ not json")
    with pytest.raises(GateError) as exc:
        check(tmp_path)
    assert exc.value.code == "GATE_CONFIG_INVALID"


def test_exemption_entry_missing_reason_is_typed_error(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "no-bon-ref-exemptions.json",
        '{"frozen_count": 1, "entries": [{"path": "src/x/*"}]}',
    )
    with pytest.raises(GateError) as exc:
        check(tmp_path)
    assert exc.value.code == "GATE_CONFIG_INVALID"


# --- the console entry point ------------------------------------------------


def test_main_clean_returns_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write(tmp_path, "src/ok.py", "x = 1\n")
    assert main(["--root", str(tmp_path)]) == 0


def test_main_violation_returns_one(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write(tmp_path, "src/bad.py", f"# {_REF}\n")
    assert main(["--root", str(tmp_path)]) == 1


def test_main_config_error_returns_two(tmp_path: Path) -> None:
    _write(tmp_path, "src/ok.py", "x = 1\n")
    _write(tmp_path, "no-bon-ref-exemptions.json", "{ not json")
    assert main(["--root", str(tmp_path)]) == 2


def test_isinstance_findings_are_gate_violations(tmp_path: Path) -> None:
    _write(tmp_path, "src/bad.py", f"# {_REF}\n")
    violations, _ = scan_tree(tmp_path)
    assert all(isinstance(v, GateViolation) for v in violations)
