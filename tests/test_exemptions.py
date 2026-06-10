"""TDD contract for cf-exemptions — the suppression-registration gate.

Answers the Law-2 refuter's "self-issued Wizard exemption" gaming vector:

(a) a bare ``# nosec`` (no rule id AND no reason) anywhere in src/ FAILS;
(b) every ``# noqa: C901`` / ``# noqa: PLR0915`` / ``# nosec B...`` must match
    a committed entry in exemptions.json ({file, symbol_or_line, rule,
    reason, approver}) — an unregistered suppression FAILS;
(c) the exemption count is ratcheted via ``frozen_count`` — removals free,
    additions require a loud, visible bump;
(d) fold-in wrappers: scripts/check_english.py and scripts/check_host_free.py
    run when present and their exit codes propagate; absent means silent skip.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from cf_quality.exemptions import main

REASON = "measured CC 12; split rejected at design review"


def write_src(root: Path, name: str, body: str) -> None:
    src = root / "src"
    src.mkdir(exist_ok=True)
    (src / name).write_text(body, encoding="utf-8")


def entry(
    file: str,
    symbol_or_line: int | str,
    rule: str,
    reason: str = REASON,
    approver: str = "wizard",
) -> dict[str, Any]:
    return {
        "file": file,
        "symbol_or_line": symbol_or_line,
        "rule": rule,
        "reason": reason,
        "approver": approver,
    }


def write_exemptions(root: Path, entries: list[dict[str, Any]], frozen_count: int) -> None:
    payload = {"frozen_count": frozen_count, "entries": entries}
    (root / "exemptions.json").write_text(json.dumps(payload), encoding="utf-8")


def run_gate(root: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    code = main(["--root", str(root)])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


class TestBareNosec:
    def test_bare_nosec_fails(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        write_src(tmp_path, "mod.py", "x = 1  # nosec\n")
        code, out, _ = run_gate(tmp_path, capsys)
        assert code == 1
        assert "BARE_NOSEC" in out
        assert "src/mod.py:1" in out

    def test_bare_nosec_with_trailing_colon_still_bare(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        write_src(tmp_path, "mod.py", "x = 1  # nosec:\n")
        code, out, _ = run_gate(tmp_path, capsys)
        assert code == 1
        assert "BARE_NOSEC" in out

    def test_nosec_with_reason_but_no_rule_id_is_not_bare(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        write_src(tmp_path, "mod.py", "x = 1  # nosec - reviewed by the wizard\n")
        code, out, _ = run_gate(tmp_path, capsys)
        assert code == 0
        assert "BARE_NOSEC" not in out

    def test_nosec_inside_string_literal_is_ignored(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        write_src(tmp_path, "mod.py", 's = "# nosec"\n')
        code, out, _ = run_gate(tmp_path, capsys)
        assert code == 0
        assert "BARE_NOSEC" not in out


class TestRegistration:
    def test_unregistered_noqa_c901_fails(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        write_src(tmp_path, "mod.py", "def gnarly():  # noqa: C901\n    return 1\n")
        write_exemptions(tmp_path, [], frozen_count=0)
        code, out, _ = run_gate(tmp_path, capsys)
        assert code == 1
        assert "UNREGISTERED_SUPPRESSION" in out
        assert "src/mod.py:1" in out

    def test_registered_noqa_c901_by_symbol_passes(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        write_src(tmp_path, "mod.py", "def gnarly():  # noqa: C901\n    return 1\n")
        write_exemptions(tmp_path, [entry("src/mod.py", "gnarly", "C901")], frozen_count=1)
        code, out, _ = run_gate(tmp_path, capsys)
        assert code == 0
        assert "UNREGISTERED_SUPPRESSION" not in out

    def test_registered_noqa_plr0915_by_line_passes(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        write_src(tmp_path, "mod.py", "def big():  # noqa: PLR0915\n    return 1\n")
        write_exemptions(tmp_path, [entry("src/mod.py", 1, "PLR0915")], frozen_count=1)
        code, out, _ = run_gate(tmp_path, capsys)
        assert code == 0

    def test_registered_wrong_rule_fails(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        write_src(tmp_path, "mod.py", "def gnarly():  # noqa: C901\n    return 1\n")
        write_exemptions(tmp_path, [entry("src/mod.py", "gnarly", "PLR0915")], frozen_count=1)
        code, out, _ = run_gate(tmp_path, capsys)
        assert code == 1
        assert "UNREGISTERED_SUPPRESSION" in out

    def test_unregistered_nosec_b_code_fails(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        body = 'import subprocess\nsubprocess.run(["ls"])  # nosec B603\n'
        write_src(tmp_path, "run.py", body)
        write_exemptions(tmp_path, [], frozen_count=0)
        code, out, _ = run_gate(tmp_path, capsys)
        assert code == 1
        assert "UNREGISTERED_SUPPRESSION" in out
        assert "B603" in out

    def test_registered_nosec_b_code_by_enclosing_symbol_passes(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        body = 'import subprocess\n\ndef runner():\n    subprocess.run(["ls"])  # nosec B603\n'
        write_src(tmp_path, "run.py", body)
        write_exemptions(tmp_path, [entry("src/run.py", "runner", "B603")], frozen_count=1)
        code, _, _ = run_gate(tmp_path, capsys)
        assert code == 0

    def test_multi_code_noqa_needs_every_gated_code_registered(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        write_src(tmp_path, "mod.py", "def big():  # noqa: C901, PLR0915\n    return 1\n")
        write_exemptions(tmp_path, [entry("src/mod.py", "big", "C901")], frozen_count=1)
        code, out, _ = run_gate(tmp_path, capsys)
        assert code == 1
        assert "PLR0915" in out

    def test_ungated_noqa_codes_need_no_registration(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        write_src(tmp_path, "mod.py", "x = 1  # noqa: E501\n")
        code, _, _ = run_gate(tmp_path, capsys)
        assert code == 0


class TestRatchet:
    def test_count_exceeding_frozen_count_fails_loudly(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        entries = [entry("src/a.py", "f", "C901"), entry("src/b.py", "g", "C901")]
        write_exemptions(tmp_path, entries, frozen_count=1)
        code, out, _ = run_gate(tmp_path, capsys)
        assert code == 1
        assert "EXEMPTION_COUNT_EXCEEDED" in out
        assert "frozen_count" in out

    def test_ratchet_banner_always_printed(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        write_src(tmp_path, "mod.py", "def gnarly():  # noqa: C901\n    return 1\n")
        write_exemptions(tmp_path, [entry("src/mod.py", "gnarly", "C901")], frozen_count=1)
        code, out, _ = run_gate(tmp_path, capsys)
        assert code == 0
        assert "EXEMPTION RATCHET" in out
        assert "1 entries / frozen_count 1" in out

    def test_removals_are_free_and_slack_is_announced(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        write_exemptions(tmp_path, [], frozen_count=2)
        code, out, _ = run_gate(tmp_path, capsys)
        assert code == 0
        assert "shrink" in out


class TestFoldIns:
    def test_foldin_failure_exit_code_propagates(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        scripts = tmp_path / "scripts"
        scripts.mkdir()
        (scripts / "check_english.py").write_text("import sys\nsys.exit(3)\n", encoding="utf-8")
        code, out, _ = run_gate(tmp_path, capsys)
        assert code == 3
        assert "fold-in check_english.py: exit 3" in out

    def test_foldin_success_passes_and_output_surfaces(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        scripts = tmp_path / "scripts"
        scripts.mkdir()
        (scripts / "check_english.py").write_text(
            'print("ENGLISH OK")\nraise SystemExit(0)\n', encoding="utf-8"
        )
        (scripts / "check_host_free.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
        code, out, _ = run_gate(tmp_path, capsys)
        assert code == 0
        assert "fold-in check_english.py: exit 0" in out
        assert "fold-in check_host_free.py: exit 0" in out
        assert "ENGLISH OK" in out

    def test_foldin_absent_skips_silently(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code, out, _ = run_gate(tmp_path, capsys)
        assert code == 0
        assert "fold-in" not in out


class TestGateErrors:
    def test_gated_suppression_without_exemptions_json_is_gate_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        write_src(tmp_path, "mod.py", "def gnarly():  # noqa: C901\n    return 1\n")
        code, _, err = run_gate(tmp_path, capsys)
        assert code == 2
        assert "GATE_CONFIG_MISSING" in err

    def test_entry_missing_approver_is_config_invalid(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        bad = entry("src/mod.py", "gnarly", "C901")
        del bad["approver"]
        write_exemptions(tmp_path, [bad], frozen_count=1)
        code, _, err = run_gate(tmp_path, capsys)
        assert code == 2
        assert "GATE_CONFIG_INVALID" in err
        assert "approver" in err

    def test_empty_reason_is_config_invalid(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        write_exemptions(
            tmp_path, [entry("src/mod.py", "gnarly", "C901", reason="  ")], frozen_count=1
        )
        code, _, err = run_gate(tmp_path, capsys)
        assert code == 2
        assert "GATE_CONFIG_INVALID" in err

    def test_missing_frozen_count_is_config_invalid(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tmp_path / "exemptions.json").write_text('{"entries": []}', encoding="utf-8")
        code, _, err = run_gate(tmp_path, capsys)
        assert code == 2
        assert "GATE_CONFIG_INVALID" in err
        assert "frozen_count" in err

    def test_malformed_json_is_config_invalid(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tmp_path / "exemptions.json").write_text("not json", encoding="utf-8")
        code, _, err = run_gate(tmp_path, capsys)
        assert code == 2
        assert "GATE_CONFIG_INVALID" in err

    def test_untokenizable_src_file_is_parse_failure(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        write_src(tmp_path, "bad.py", 'x = """unterminated\n')
        code, _, err = run_gate(tmp_path, capsys)
        assert code == 2
        assert "GATE_PARSE_FAILURE" in err


class TestCleanRepo:
    def test_clean_repo_without_src_or_json_passes(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code, out, _ = run_gate(tmp_path, capsys)
        assert code == 0
        assert "cf-exemptions: OK" in out
