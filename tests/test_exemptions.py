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


class TestBareNoqa:
    """Refuter: a codeless ``# noqa`` is a blanket suppression ruff honors —
    strictly more powerful than the gated ``# noqa: C901`` — and was invisible."""

    def test_bare_codeless_noqa_fails(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        write_src(tmp_path, "mod.py", "def gnarly():  # noqa\n    return 1\n")
        code, out, _ = run_gate(tmp_path, capsys)
        assert code == 1
        assert "BARE_NOQA" in out
        assert "src/mod.py:1" in out

    def test_bare_noqa_with_trailing_colon_still_bare(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        write_src(tmp_path, "mod.py", "x = 1  # noqa:\n")
        code, out, _ = run_gate(tmp_path, capsys)
        assert code == 1
        assert "BARE_NOQA" in out

    def test_bare_noqa_cannot_be_registered_away(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # A blanket suppression names no rule, so no registry entry can cover it.
        write_src(tmp_path, "mod.py", "def gnarly():  # noqa\n    return 1\n")
        write_exemptions(tmp_path, [entry("src/mod.py", "gnarly", "C901")], frozen_count=1)
        code, out, _ = run_gate(tmp_path, capsys)
        assert code == 1
        assert "BARE_NOQA" in out

    def test_noqa_inside_string_literal_is_ignored(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        write_src(tmp_path, "mod.py", 's = "# noqa"\n')
        code, out, _ = run_gate(tmp_path, capsys)
        assert code == 0
        assert "BARE_NOQA" not in out


class TestSecurityAndEleganceGating:
    """Refuter: ``# noqa: S602`` / ``# noqa: BLE001`` silenced the security
    battery and the Elegance Law's blind-except ban with no entry and no reason."""

    def test_unregistered_noqa_s_code_fails(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        body = 'import subprocess\nsubprocess.run("ls", shell=True)  # noqa: S602\n'
        write_src(tmp_path, "danger.py", body)
        write_exemptions(tmp_path, [], frozen_count=0)
        code, out, _ = run_gate(tmp_path, capsys)
        assert code == 1
        assert "UNREGISTERED_SUPPRESSION" in out
        assert "S602" in out

    def test_unregistered_noqa_ble_code_fails(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        body = "try:\n    x = 1\nexcept Exception:  # noqa: BLE001\n    pass\n"
        write_src(tmp_path, "swallow.py", body)
        write_exemptions(tmp_path, [], frozen_count=0)
        code, out, _ = run_gate(tmp_path, capsys)
        assert code == 1
        assert "UNREGISTERED_SUPPRESSION" in out
        assert "BLE001" in out

    def test_registered_s_code_passes(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        body = 'import subprocess  # noqa: S404\nsubprocess.run(["ls"])\n'
        write_src(tmp_path, "danger.py", body)
        write_exemptions(tmp_path, [entry("src/danger.py", 1, "S404")], frozen_count=1)
        code, _, _ = run_gate(tmp_path, capsys)
        assert code == 0

    def test_kit_registers_its_own_suppressions(self, capsys: pytest.CaptureFixture[str]) -> None:
        # The kit obeys the law it enforces: its own S404/S603 noqa comments
        # trace to reasoned entries in the kit's exemptions.json.
        kit_root = Path(__file__).resolve().parents[1]
        assert (kit_root / "exemptions.json").is_file(), "the kit must register itself"
        code, out, _ = run_gate(kit_root, capsys)
        assert code == 0, out
        assert "EXEMPTION RATCHET" in out


class TestLayoutDiscovery:
    """Refuter: only ``<root>/src`` was scanned — a flat/app layout made the
    whole gate a silent no-op."""

    def test_flat_layout_package_is_scanned(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        app = tmp_path / "app"
        app.mkdir()
        (app / "mod.py").write_text("def gnarly():  # noqa: C901\n    return 1\n", encoding="utf-8")
        code, _, err = run_gate(tmp_path, capsys)
        assert code == 2  # gated suppression + no exemptions.json = typed gate error
        assert "GATE_CONFIG_MISSING" in err

    def test_flat_layout_registered_suppression_passes(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        app = tmp_path / "app"
        app.mkdir()
        (app / "mod.py").write_text("def gnarly():  # noqa: C901\n    return 1\n", encoding="utf-8")
        write_exemptions(tmp_path, [entry("app/mod.py", "gnarly", "C901")], frozen_count=1)
        code, _, _ = run_gate(tmp_path, capsys)
        assert code == 0

    def test_root_level_module_is_scanned(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tmp_path / "serve.py").write_text("x = 1  # nosec\n", encoding="utf-8")
        code, out, _ = run_gate(tmp_path, capsys)
        assert code == 1
        assert "BARE_NOSEC" in out

    def test_tests_dir_is_not_scanned_in_flat_layout(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        tests = tmp_path / "tests"
        tests.mkdir()
        body = "def helper():  # noqa: C901\n    return 1\n"
        (tests / "test_x.py").write_text(body, encoding="utf-8")
        code, _, _ = run_gate(tmp_path, capsys)
        assert code == 0

    def test_src_layout_still_wins_over_siblings(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        write_src(tmp_path, "ok.py", "x = 1\n")
        app = tmp_path / "app"
        app.mkdir()
        (app / "mod.py").write_text("x = 1  # nosec\n", encoding="utf-8")
        code, _, _ = run_gate(tmp_path, capsys)
        assert code == 0  # src/ present: src/ is the measured surface


class TestSymbolCollision:
    """Refuter: N same-named suppressions collapsed onto ONE bare-name entry,
    so frozen_count never bumped — the ratchet undercounted."""

    COLLIDING = (
        "class A:\n"
        "    def run(self):  # noqa: C901\n"
        "        return 1\n"
        "\n"
        "class B:\n"
        "    def run(self):  # noqa: C901\n"
        "        return 2\n"
        "\n"
        "def run():  # noqa: C901\n"
        "    return 3\n"
    )

    def test_one_bare_name_entry_cannot_cover_three_suppressions(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        write_src(tmp_path, "mod.py", self.COLLIDING)
        write_exemptions(tmp_path, [entry("src/mod.py", "run", "C901")], frozen_count=1)
        code, out, _ = run_gate(tmp_path, capsys)
        assert code == 1
        assert "UNREGISTERED_SUPPRESSION" in out  # A.run and B.run are not covered

    def test_qualified_entries_cover_each_method(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        write_src(tmp_path, "mod.py", self.COLLIDING)
        entries = [
            entry("src/mod.py", "A.run", "C901"),
            entry("src/mod.py", "B.run", "C901"),
            entry("src/mod.py", "run", "C901"),
        ]
        write_exemptions(tmp_path, entries, frozen_count=3)
        code, _, _ = run_gate(tmp_path, capsys)
        assert code == 0

    def test_entry_matching_multiple_suppressions_is_overloaded(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        body = "def big():  # noqa: PLR0915\n    x = 1  # noqa: PLR0915\n    return x\n"
        write_src(tmp_path, "mod.py", body)
        write_exemptions(tmp_path, [entry("src/mod.py", "big", "PLR0915")], frozen_count=1)
        code, out, _ = run_gate(tmp_path, capsys)
        assert code == 1
        assert "EXEMPTION_ENTRY_OVERLOADED" in out
