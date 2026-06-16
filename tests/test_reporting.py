"""Contract tests for cf_quality.reporting — the kit's one wire form.

Every gate emits its verdict through :func:`print_verdict`: human-readable by
default (the shape local readers and the gates' own tests assert) and the
machine-readable :class:`~cf_quality.errors.GateVerdict` JSON on opt-in, so CI
parses one schema across the whole battery. These tests pin both surfaces and
the opt-in switch.
"""

import json
from typing import Any

import pytest

from cf_quality.errors import GateError, GateViolation
from cf_quality.reporting import (
    JSON_ENV_VAR,
    json_output_enabled,
    print_verdict,
    violation_location,
)


def _violation(line: int | None = None) -> GateViolation:
    return GateViolation(code="CODE_X", message="broke the law", path="src/x.py", line=line)


class TestJsonOutputEnabled:
    def test_unset_env_is_human_default(self) -> None:
        assert json_output_enabled(env={}) is False

    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
    def test_truthy_values_opt_in(self, value: str) -> None:
        assert json_output_enabled(env={JSON_ENV_VAR: value}) is True

    @pytest.mark.parametrize("value", ["0", "false", "", "no", "maybe"])
    def test_falsy_values_stay_human(self, value: str) -> None:
        assert json_output_enabled(env={JSON_ENV_VAR: value}) is False


class TestViolationLocation:
    def test_line_anchored_uses_path_and_line(self) -> None:
        assert violation_location(_violation(line=7)) == "src/x.py:7"

    def test_unanchored_uses_bare_path(self) -> None:
        assert violation_location(_violation(line=None)) == "src/x.py"


class TestHumanDefault:
    def test_clean_prints_summary_and_returns_zero(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = print_verdict("cf-x", [], clean_summary="cf-x: OK")
        out = capsys.readouterr().out
        assert code == 0
        assert "cf-x: OK" in out

    def test_violations_print_findings_and_fail_summary(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = print_verdict(
            "cf-x", [_violation(line=7)], clean_summary="cf-x: OK", fail_summary="cf-x: FAIL (1)"
        )
        out = capsys.readouterr().out
        assert code == 1
        assert "src/x.py:7: CODE_X: broke the law" in out
        assert "cf-x: FAIL (1)" in out
        assert "cf-x: OK" not in out

    def test_notices_precede_findings(self, capsys: pytest.CaptureFixture[str]) -> None:
        print_verdict("cf-x", [_violation(line=7)], notices=["a notice"])
        out = capsys.readouterr().out
        assert out.index("a notice") < out.index("CODE_X")

    def test_default_human_output_is_not_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        print_verdict("cf-x", [_violation(line=7)], fail_summary="cf-x: FAIL (1)")
        out = capsys.readouterr().out
        with pytest.raises(json.JSONDecodeError):
            json.loads(out)

    def test_gate_error_goes_to_stderr_with_exit_two(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        err = GateError(code="GATE_BOOM", message="cannot run")
        code = print_verdict("cf-x", [], err, clean_summary="cf-x: OK")
        captured = capsys.readouterr()
        assert code == 2
        assert "GATE_BOOM" in captured.err
        assert "cf-x: OK" not in captured.out


class TestJsonWireForm:
    def test_json_shape_on_stdout(self, capsys: pytest.CaptureFixture[str]) -> None:
        code = print_verdict("cf-x", [_violation(line=7)], json_output=True)
        report: dict[str, Any] = json.loads(capsys.readouterr().out)
        assert code == 1
        assert report["gate"] == "cf-x"
        assert report["passed"] is False
        assert report["exit_code"] == 1
        assert report["error"] is None
        assert report["violations"][0]["code"] == "CODE_X"
        assert report["violations"][0]["severity"] == "error"

    def test_json_summary_and_notices_are_suppressed(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        print_verdict(
            "cf-x",
            [],
            json_output=True,
            notices=["a notice"],
            clean_summary="cf-x: OK",
        )
        out = capsys.readouterr().out
        assert "a notice" not in out
        assert "cf-x: OK" not in out
        assert json.loads(out)["passed"] is True

    def test_json_gate_error_goes_to_stderr(self, capsys: pytest.CaptureFixture[str]) -> None:
        err = GateError(code="GATE_BOOM", message="cannot run")
        code = print_verdict("cf-x", [], err, json_output=True)
        captured = capsys.readouterr()
        assert code == 2
        assert captured.out == ""
        report = json.loads(captured.err)
        assert report["exit_code"] == 2
        assert report["error"]["code"] == "GATE_BOOM"

    def test_env_var_opts_into_json(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(JSON_ENV_VAR, "1")
        print_verdict("cf-x", [], clean_summary="cf-x: OK")
        out = capsys.readouterr().out
        assert "cf-x: OK" not in out
        assert json.loads(out)["gate"] == "cf-x"
