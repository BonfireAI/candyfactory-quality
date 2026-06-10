"""Contract tests for cf-file-budget — the BubbleGum Law's file-size ratchet.

Covers the four behaviors the gate must hold:
(a) check mode — new .py files over 500 lines fail; baselined files are
    frozen shrink-only (grow fails, shrink passes with a notice);
(b) init mode — generate file-budget.json from the tree;
(c) per-package LOC budgets — the sibling-file-accretion answer: a NEW
    499-line handle_extra.py next to a frozen handle.py FAILS because it
    draws against the package's frozen LOC total;
(d) declared-not-banned — a JSON entry with a one-line "purpose" registers
    a new file so it does not draw against the package budget (it still
    obeys the 500-line new-file cap).

Exit 0 clean / exit 1 with a typed GateViolation report / exit 2 when the
gate itself cannot run (typed GateError on stderr).
"""

import json
from pathlib import Path
from typing import Any

import pytest

from cf_quality.errors import GateError
from cf_quality.file_budget import (
    NEW_FILE_BUDGET,
    Budget,
    FileEntry,
    check_tree,
    count_lines,
    init_tree,
    load_budget,
    main,
)


def write_py(path: Path, lines: int) -> None:
    """Create a .py file with exactly ``lines`` physical lines."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"x{i} = {i}\n" for i in range(lines)), encoding="utf-8")


def write_budget(root: Path, data: dict[str, Any]) -> Path:
    config = root / "file-budget.json"
    config.write_text(json.dumps(data), encoding="utf-8")
    return config


def report_from(out: str) -> dict[str, Any]:
    """Extract the JSON violation report from captured stdout."""
    start = out.index("{")
    parsed: dict[str, Any] = json.loads(out[start:])
    return parsed


def violation_codes(report: dict[str, Any]) -> list[str]:
    return [v["code"] for v in report["violations"]]


class TestCountLines:
    def test_counts_physical_lines(self, tmp_path: Path) -> None:
        f = tmp_path / "a.py"
        write_py(f, 7)
        assert count_lines(f) == 7

    def test_empty_file_is_zero_lines(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.py"
        f.write_text("", encoding="utf-8")
        assert count_lines(f) == 0


class TestLoadBudget:
    def test_missing_config_means_empty_baseline(self, tmp_path: Path) -> None:
        budget = load_budget(tmp_path / "file-budget.json")
        assert budget.files == {}
        assert budget.packages == {}

    def test_malformed_json_raises_typed_gate_error(self, tmp_path: Path) -> None:
        config = tmp_path / "file-budget.json"
        config.write_text("{not json", encoding="utf-8")
        with pytest.raises(GateError) as exc_info:
            load_budget(config)
        assert exc_info.value.code == "GATE_CONFIG_INVALID"

    def test_int_entry_is_frozen_and_dict_entry_is_declared(self, tmp_path: Path) -> None:
        write_budget(
            tmp_path,
            {
                "files": {
                    "src/handle.py": 694,
                    "src/new_feature.py": {"purpose": "webhook adapter, design-reviewed"},
                },
                "packages": {"src": 694},
            },
        )
        budget = load_budget(tmp_path / "file-budget.json")
        assert budget.files["src/handle.py"] == FileEntry(frozen_lines=694, purpose=None)
        assert budget.files["src/new_feature.py"].purpose == "webhook adapter, design-reviewed"
        assert budget.files["src/new_feature.py"].frozen_lines is None
        assert budget.packages == {"src": 694}

    def test_non_object_top_level_raises_typed_gate_error(self, tmp_path: Path) -> None:
        config = tmp_path / "file-budget.json"
        config.write_text("[1, 2, 3]", encoding="utf-8")
        with pytest.raises(GateError) as exc_info:
            load_budget(config)
        assert exc_info.value.code == "GATE_CONFIG_INVALID"

    def test_bad_file_entry_type_raises_typed_gate_error(self, tmp_path: Path) -> None:
        write_budget(tmp_path, {"files": {"a.py": "six hundred"}})
        with pytest.raises(GateError) as exc_info:
            load_budget(tmp_path / "file-budget.json")
        assert exc_info.value.code == "GATE_CONFIG_INVALID"
        assert exc_info.value.context["path"] == "a.py"


class TestCheckNewFiles:
    def test_new_file_over_500_lines_fails(self, tmp_path: Path, capsys: Any) -> None:
        write_py(tmp_path / "src" / "big.py", NEW_FILE_BUDGET + 1)
        assert main(["check", "--root", str(tmp_path)]) == 1
        report = report_from(capsys.readouterr().out)
        assert violation_codes(report) == ["FILE_BUDGET_EXCEEDED"]
        offender = report["violations"][0]
        assert offender["path"] == "src/big.py"
        assert offender["context"]["lines"] == 501
        assert offender["context"]["budget"] == 500

    def test_new_file_at_exactly_500_lines_passes(self, tmp_path: Path) -> None:
        write_py(tmp_path / "src" / "fits.py", NEW_FILE_BUDGET)
        assert main(["check", "--root", str(tmp_path)]) == 0

    def test_report_lists_every_offender(self, tmp_path: Path, capsys: Any) -> None:
        write_py(tmp_path / "a.py", 600)
        write_py(tmp_path / "b.py", 700)
        assert main(["check", "--root", str(tmp_path)]) == 1
        report = report_from(capsys.readouterr().out)
        assert violation_codes(report) == ["FILE_BUDGET_EXCEEDED", "FILE_BUDGET_EXCEEDED"]
        assert {v["path"] for v in report["violations"]} == {"a.py", "b.py"}


class TestFrozenFiles:
    def test_frozen_file_that_grew_fails(self, tmp_path: Path, capsys: Any) -> None:
        write_py(tmp_path / "src" / "handle.py", 700)
        write_budget(tmp_path, {"files": {"src/handle.py": 694}, "packages": {"src": 694}})
        assert main(["check", "--root", str(tmp_path)]) == 1
        report = report_from(capsys.readouterr().out)
        assert "FILE_BUDGET_GREW" in violation_codes(report)
        grew = next(v for v in report["violations"] if v["code"] == "FILE_BUDGET_GREW")
        assert grew["path"] == "src/handle.py"
        assert grew["context"] == {"lines": 700, "frozen": 694}

    def test_frozen_file_that_shrank_passes_with_notice(self, tmp_path: Path, capsys: Any) -> None:
        write_py(tmp_path / "src" / "handle.py", 600)
        write_budget(tmp_path, {"files": {"src/handle.py": 694}, "packages": {"src": 694}})
        assert main(["check", "--root", str(tmp_path)]) == 0
        out = capsys.readouterr().out
        assert "shrink" in out
        assert "src/handle.py" in out
        assert "694" in out and "600" in out

    def test_frozen_file_at_frozen_size_passes_without_notice(
        self, tmp_path: Path, capsys: Any
    ) -> None:
        write_py(tmp_path / "src" / "handle.py", 694)
        write_budget(tmp_path, {"files": {"src/handle.py": 694}, "packages": {"src": 694}})
        assert main(["check", "--root", str(tmp_path)]) == 0
        assert "shrink" not in capsys.readouterr().out

    def test_frozen_file_deleted_passes_with_notice(self, tmp_path: Path, capsys: Any) -> None:
        write_budget(tmp_path, {"files": {"src/handle.py": 694}})
        assert main(["check", "--root", str(tmp_path)]) == 0
        out = capsys.readouterr().out
        assert "shrink" in out
        assert "src/handle.py" in out


class TestPackageBudget:
    """The sibling-file-accretion answer (refuter gaming vector #1)."""

    def test_handle_extra_at_499_next_to_frozen_handle_fails(
        self, tmp_path: Path, capsys: Any
    ) -> None:
        # Fixture package: chunk's anchor case. handle.py frozen at 700,
        # package frozen at 700 total. The burn agent dodges the per-file
        # gate by creating handle_extra.py at 499 lines — the package
        # budget catches the relocation of the accretion engine.
        write_py(tmp_path / "src" / "chunk" / "handle.py", 700)
        write_py(tmp_path / "src" / "chunk" / "handle_extra.py", 499)
        write_budget(
            tmp_path,
            {"files": {"src/chunk/handle.py": 700}, "packages": {"src/chunk": 700}},
        )
        assert main(["check", "--root", str(tmp_path)]) == 1
        report = report_from(capsys.readouterr().out)
        assert "PACKAGE_BUDGET_EXCEEDED" in violation_codes(report)
        pkg = next(v for v in report["violations"] if v["code"] == "PACKAGE_BUDGET_EXCEEDED")
        assert pkg["path"] == "src/chunk"
        assert pkg["context"]["lines"] == 1199
        assert pkg["context"]["frozen"] == 700
        assert pkg["context"]["new_files"] == ["src/chunk/handle_extra.py"]

    def test_new_file_fits_inside_room_freed_by_shrink(self, tmp_path: Path) -> None:
        # handle.py shrank 700 -> 600; a 50-line sibling fits in the freed room.
        write_py(tmp_path / "src" / "chunk" / "handle.py", 600)
        write_py(tmp_path / "src" / "chunk" / "helpers.py", 50)
        write_budget(
            tmp_path,
            {"files": {"src/chunk/handle.py": 700}, "packages": {"src/chunk": 700}},
        )
        assert main(["check", "--root", str(tmp_path)]) == 0

    def test_package_budget_counts_subdirectories(self, tmp_path: Path, capsys: Any) -> None:
        # Hiding the sibling one directory deeper does not dodge the draw.
        write_py(tmp_path / "src" / "chunk" / "handle.py", 700)
        write_py(tmp_path / "src" / "chunk" / "extra" / "handle_extra.py", 499)
        write_budget(
            tmp_path,
            {"files": {"src/chunk/handle.py": 700}, "packages": {"src/chunk": 700}},
        )
        assert main(["check", "--root", str(tmp_path)]) == 1
        report = report_from(capsys.readouterr().out)
        assert "PACKAGE_BUDGET_EXCEEDED" in violation_codes(report)


class TestDeclaredFiles:
    def test_declared_file_does_not_draw_against_package_budget(self, tmp_path: Path) -> None:
        write_py(tmp_path / "src" / "chunk" / "handle.py", 700)
        write_py(tmp_path / "src" / "chunk" / "webhook.py", 200)
        write_budget(
            tmp_path,
            {
                "files": {
                    "src/chunk/handle.py": 700,
                    "src/chunk/webhook.py": {"purpose": "webhook adapter, design-reviewed"},
                },
                "packages": {"src/chunk": 700},
            },
        )
        assert main(["check", "--root", str(tmp_path)]) == 0

    def test_declared_file_still_obeys_new_file_cap(self, tmp_path: Path, capsys: Any) -> None:
        write_py(tmp_path / "src" / "chunk" / "webhook.py", 501)
        write_budget(
            tmp_path,
            {"files": {"src/chunk/webhook.py": {"purpose": "declared but oversized"}}},
        )
        assert main(["check", "--root", str(tmp_path)]) == 1
        report = report_from(capsys.readouterr().out)
        assert violation_codes(report) == ["FILE_BUDGET_EXCEEDED"]


class TestInitMode:
    def test_init_freezes_only_files_over_budget_at_measured_size(self, tmp_path: Path) -> None:
        write_py(tmp_path / "src" / "chunk" / "handle.py", 694)
        write_py(tmp_path / "src" / "chunk" / "small.py", 100)
        assert main(["init", "--root", str(tmp_path)]) == 0
        data = json.loads((tmp_path / "file-budget.json").read_text(encoding="utf-8"))
        assert data["files"] == {"src/chunk/handle.py": 694}

    def test_init_records_package_totals_for_dirs_holding_frozen_files(
        self, tmp_path: Path
    ) -> None:
        write_py(tmp_path / "src" / "chunk" / "handle.py", 694)
        write_py(tmp_path / "src" / "chunk" / "small.py", 100)
        write_py(tmp_path / "src" / "other" / "tiny.py", 10)
        assert main(["init", "--root", str(tmp_path)]) == 0
        data = json.loads((tmp_path / "file-budget.json").read_text(encoding="utf-8"))
        assert data["packages"] == {"src/chunk": 794}

    def test_init_then_check_is_green_by_construction(self, tmp_path: Path) -> None:
        write_py(tmp_path / "src" / "chunk" / "handle.py", 694)
        write_py(tmp_path / "src" / "chunk" / "small.py", 100)
        assert main(["init", "--root", str(tmp_path)]) == 0
        assert main(["check", "--root", str(tmp_path)]) == 0

    def test_init_with_root_level_offender_uses_dot_package(self, tmp_path: Path) -> None:
        write_py(tmp_path / "monolith.py", 800)
        assert main(["init", "--root", str(tmp_path)]) == 0
        data = json.loads((tmp_path / "file-budget.json").read_text(encoding="utf-8"))
        assert data["files"] == {"monolith.py": 800}
        assert data["packages"] == {".": 800}

    def test_init_tree_skips_cache_and_hidden_directories(self, tmp_path: Path) -> None:
        write_py(tmp_path / "__pycache__" / "big.py", 600)
        write_py(tmp_path / ".venv" / "lib" / "big.py", 600)
        write_py(tmp_path / "src" / "ok.py", 10)
        data = init_tree(tmp_path)
        assert data["files"] == {}


class TestCheckTreeApi:
    def test_check_tree_returns_typed_violations(self, tmp_path: Path) -> None:
        write_py(tmp_path / "big.py", 600)
        violations, notices = check_tree(tmp_path, Budget(files={}, packages={}))
        assert len(violations) == 1
        assert violations[0].to_dict()["code"] == "FILE_BUDGET_EXCEEDED"
        assert notices == []


class TestMainErrors:
    def test_malformed_config_exits_2_with_typed_error_on_stderr(
        self, tmp_path: Path, capsys: Any
    ) -> None:
        (tmp_path / "file-budget.json").write_text("{broken", encoding="utf-8")
        write_py(tmp_path / "a.py", 10)
        assert main(["check", "--root", str(tmp_path)]) == 2
        err = json.loads(capsys.readouterr().err)
        assert err["error"]["code"] == "GATE_CONFIG_INVALID"
        assert err["error"]["retryable"] is False

    def test_explicit_config_path_is_honored(self, tmp_path: Path) -> None:
        write_py(tmp_path / "src" / "handle.py", 700)
        config = tmp_path / "budgets" / "fb.json"
        config.parent.mkdir()
        config.write_text(json.dumps({"files": {"src/handle.py": 700}}), encoding="utf-8")
        assert main(["check", "--root", str(tmp_path), "--config", str(config)]) == 0
