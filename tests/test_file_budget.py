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
    def test_new_file_over_500_lines_fails(
        self, tmp_path: Path, capsys: Any, monkeypatch: Any
    ) -> None:
        monkeypatch.setenv("CF_QUALITY_JSON", "1")
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

    def test_report_lists_every_offender(
        self, tmp_path: Path, capsys: Any, monkeypatch: Any
    ) -> None:
        monkeypatch.setenv("CF_QUALITY_JSON", "1")
        write_py(tmp_path / "a.py", 600)
        write_py(tmp_path / "b.py", 700)
        assert main(["check", "--root", str(tmp_path)]) == 1
        report = report_from(capsys.readouterr().out)
        assert violation_codes(report) == ["FILE_BUDGET_EXCEEDED", "FILE_BUDGET_EXCEEDED"]
        assert {v["path"] for v in report["violations"]} == {"a.py", "b.py"}


class TestFrozenFiles:
    def test_frozen_file_that_grew_fails(
        self, tmp_path: Path, capsys: Any, monkeypatch: Any
    ) -> None:
        monkeypatch.setenv("CF_QUALITY_JSON", "1")
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
        self, tmp_path: Path, capsys: Any, monkeypatch: Any
    ) -> None:
        monkeypatch.setenv("CF_QUALITY_JSON", "1")
        # Fixture package: the big-legacy-module anchor case. handle.py frozen at 700,
        # package frozen at 700 total. The burn agent dodges the per-file
        # gate by creating handle_extra.py at 499 lines — the package
        # budget catches the relocation of the accretion engine.
        write_py(tmp_path / "src" / "engine" / "handle.py", 700)
        write_py(tmp_path / "src" / "engine" / "handle_extra.py", 499)
        write_budget(
            tmp_path,
            {"files": {"src/engine/handle.py": 700}, "packages": {"src/engine": 700}},
        )
        assert main(["check", "--root", str(tmp_path)]) == 1
        report = report_from(capsys.readouterr().out)
        assert "PACKAGE_BUDGET_EXCEEDED" in violation_codes(report)
        pkg = next(v for v in report["violations"] if v["code"] == "PACKAGE_BUDGET_EXCEEDED")
        assert pkg["path"] == "src/engine"
        assert pkg["context"]["lines"] == 1199
        assert pkg["context"]["frozen"] == 700
        assert pkg["context"]["new_files"] == ["src/engine/handle_extra.py"]

    def test_new_file_fits_inside_room_freed_by_shrink(self, tmp_path: Path) -> None:
        # handle.py shrank 700 -> 600; a 50-line sibling fits in the freed room.
        write_py(tmp_path / "src" / "engine" / "handle.py", 600)
        write_py(tmp_path / "src" / "engine" / "helpers.py", 50)
        write_budget(
            tmp_path,
            {"files": {"src/engine/handle.py": 700}, "packages": {"src/engine": 700}},
        )
        assert main(["check", "--root", str(tmp_path)]) == 0

    def test_package_budget_counts_subdirectories(
        self, tmp_path: Path, capsys: Any, monkeypatch: Any
    ) -> None:
        monkeypatch.setenv("CF_QUALITY_JSON", "1")
        # Hiding the sibling one directory deeper does not dodge the draw.
        write_py(tmp_path / "src" / "engine" / "handle.py", 700)
        write_py(tmp_path / "src" / "engine" / "extra" / "handle_extra.py", 499)
        write_budget(
            tmp_path,
            {"files": {"src/engine/handle.py": 700}, "packages": {"src/engine": 700}},
        )
        assert main(["check", "--root", str(tmp_path)]) == 1
        report = report_from(capsys.readouterr().out)
        assert "PACKAGE_BUDGET_EXCEEDED" in violation_codes(report)


class TestDeclaredFiles:
    def test_declared_file_does_not_draw_against_package_budget(self, tmp_path: Path) -> None:
        write_py(tmp_path / "src" / "engine" / "handle.py", 700)
        write_py(tmp_path / "src" / "engine" / "webhook.py", 200)
        write_budget(
            tmp_path,
            {
                "files": {
                    "src/engine/handle.py": 700,
                    "src/engine/webhook.py": {"purpose": "webhook adapter, design-reviewed"},
                },
                "packages": {"src/engine": 700},
            },
        )
        assert main(["check", "--root", str(tmp_path)]) == 0

    def test_declared_file_still_obeys_new_file_cap(
        self, tmp_path: Path, capsys: Any, monkeypatch: Any
    ) -> None:
        monkeypatch.setenv("CF_QUALITY_JSON", "1")
        write_py(tmp_path / "src" / "engine" / "webhook.py", 501)
        write_budget(
            tmp_path,
            {"files": {"src/engine/webhook.py": {"purpose": "declared but oversized"}}},
        )
        assert main(["check", "--root", str(tmp_path)]) == 1
        report = report_from(capsys.readouterr().out)
        assert violation_codes(report) == ["FILE_BUDGET_EXCEEDED"]


class TestInitMode:
    def test_init_freezes_only_files_over_budget_at_measured_size(self, tmp_path: Path) -> None:
        write_py(tmp_path / "src" / "engine" / "handle.py", 694)
        write_py(tmp_path / "src" / "engine" / "small.py", 100)
        assert main(["init", "--root", str(tmp_path)]) == 0
        data = json.loads((tmp_path / "file-budget.json").read_text(encoding="utf-8"))
        assert data["files"] == {"src/engine/handle.py": 694}

    def test_init_records_package_totals_for_dirs_holding_frozen_files(
        self, tmp_path: Path
    ) -> None:
        write_py(tmp_path / "src" / "engine" / "handle.py", 694)
        write_py(tmp_path / "src" / "engine" / "small.py", 100)
        write_py(tmp_path / "src" / "other" / "tiny.py", 10)
        assert main(["init", "--root", str(tmp_path)]) == 0
        data = json.loads((tmp_path / "file-budget.json").read_text(encoding="utf-8"))
        assert data["packages"] == {"src/engine": 794}

    def test_init_then_check_is_green_by_construction(self, tmp_path: Path) -> None:
        write_py(tmp_path / "src" / "engine" / "handle.py", 694)
        write_py(tmp_path / "src" / "engine" / "small.py", 100)
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


def write_joined_py(path: Path, statements: int, per_line: int) -> None:
    """Real statements re-flowed N-per-physical-line via ';' (the refuter's attack 1)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        "; ".join(f"x{j} = {j}" for j in range(i, min(i + per_line, statements)))
        for i in range(0, statements, per_line)
    ]
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


class TestCompressionResistance:
    """Refuter attack 1: statement-joining must not manufacture a shrink.

    The draw is anchored to ``max(physical lines, logical statements)`` so
    re-flowing the same code onto fewer physical lines cannot free headroom.
    """

    def test_statement_joining_cannot_fake_a_shrink(self, tmp_path: Path, capsys: Any) -> None:
        # 900 real statements joined 3-per-line = 300 physical lines, against a
        # 700 freeze: the truth is GROWTH, never a shrink notice.
        write_joined_py(tmp_path / "src" / "engine" / "handle.py", 900, 3)
        write_budget(
            tmp_path,
            {"files": {"src/engine/handle.py": 700}, "packages": {"src/engine": 700}},
        )
        assert main(["check", "--root", str(tmp_path)]) == 1
        out = capsys.readouterr().out
        assert "ratchet the baseline down" not in out  # no shrink notice was printed
        assert "FILE_BUDGET_GREW" in out

    def test_joined_shrink_cannot_free_package_headroom(
        self, tmp_path: Path, capsys: Any, monkeypatch: Any
    ) -> None:
        monkeypatch.setenv("CF_QUALITY_JSON", "1")
        # The full refuter repro: joined handle.py + a brand-new 380-line
        # sibling = 1280 real statements in a package frozen at 700.
        write_joined_py(tmp_path / "src" / "engine" / "handle.py", 900, 3)
        write_py(tmp_path / "src" / "engine" / "new_engine.py", 380)
        write_budget(
            tmp_path,
            {"files": {"src/engine/handle.py": 700}, "packages": {"src/engine": 700}},
        )
        assert main(["check", "--root", str(tmp_path)]) == 1
        codes = violation_codes(report_from(capsys.readouterr().out))
        assert "PACKAGE_BUDGET_EXCEEDED" in codes

    def test_new_file_cap_counts_statements_not_just_lines(
        self, tmp_path: Path, capsys: Any, monkeypatch: Any
    ) -> None:
        monkeypatch.setenv("CF_QUALITY_JSON", "1")
        # 600 statements squeezed onto 200 physical lines is a >500 file in truth.
        write_joined_py(tmp_path / "src" / "mod.py", 600, 3)
        assert main(["check", "--root", str(tmp_path)]) == 1
        assert "FILE_BUDGET_EXCEEDED" in violation_codes(report_from(capsys.readouterr().out))

    def test_measure_is_max_of_lines_and_statements(self, tmp_path: Path) -> None:
        from cf_quality.file_budget import measure_file

        multi_line = tmp_path / "a.py"
        multi_line.write_text("x = (\n    1,\n    2,\n)\n", encoding="utf-8")
        assert measure_file(multi_line) == 4  # one statement across four lines
        joined = tmp_path / "b.py"
        joined.write_text("a = 1; b = 2; c = 3\n", encoding="utf-8")
        assert measure_file(joined) == 3  # three statements on one line

    def test_init_freezes_the_compression_resistant_measure(self, tmp_path: Path) -> None:
        write_joined_py(tmp_path / "src" / "dense.py", 600, 3)
        data = init_tree(tmp_path)
        assert data["files"] == {"src/dense.py": 600}
        assert data["packages"] == {"src": 600}

    def test_unparseable_python_raises_typed_gate_error(self, tmp_path: Path) -> None:
        bad = tmp_path / "broken.py"
        bad.write_text("def broken(:\n", encoding="utf-8")
        with pytest.raises(GateError) as exc:
            check_tree(tmp_path, Budget(files={}, packages={}))
        assert exc.value.code == "GATE_SOURCE_UNPARSEABLE"


class TestGreenfieldPackageBoundary:
    """Refuter attack 2: greenfield multi-file dumps never seed a package budget.

    This is a DISCLOSED v0 boundary, not silence: the package draw engages
    only for directories already holding a >500 offender at init time.
    """

    def test_greenfield_sub_500_siblings_pass_and_the_boundary_is_disclosed(
        self, tmp_path: Path
    ) -> None:
        for name in ("a", "b", "c", "d", "e"):
            write_py(tmp_path / "src" / "engine" / f"engine_{name}.py", 499)
        data = init_tree(tmp_path)
        assert data == {"files": {}, "packages": {}}  # nothing seeded the draw
        violations, _, _ = check_tree(tmp_path, Budget(files={}, packages={}))
        assert violations == []  # 2495 lines in one package, green — the boundary
        import cf_quality.file_budget as fb

        assert fb.__doc__ is not None
        assert "greenfield" in fb.__doc__, "the relocation-only boundary must be disclosed"


class TestCheckTreeApi:
    def test_check_tree_returns_typed_violations(self, tmp_path: Path) -> None:
        write_py(tmp_path / "big.py", 600)
        violations, notices, files = check_tree(tmp_path, Budget(files={}, packages={}))
        assert len(violations) == 1
        assert violations[0].to_dict()["code"] == "FILE_BUDGET_EXCEEDED"
        assert notices == []
        assert files == 1  # the denominator is the tree it actually measured


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
