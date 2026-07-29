"""Contract tests for cf_quality.errors — the kit's Elegance Law vocabulary.

GateError is the typed failure every gate raises; GateViolation is a finding
a gate reports. Both must be self-describing: stable code, message, structured
context, explicit retryability — never a bare exception or a magic return.
"""

import pytest

from cf_quality.errors import GateError, GateVerdict, GateViolation


class TestGateError:
    def test_is_an_exception(self) -> None:
        assert issubclass(GateError, Exception)

    def test_carries_code_message_context_retryable(self) -> None:
        err = GateError(
            code="GATE_CONFIG_MISSING",
            message="exemptions.json not found",
            context={"path": "exemptions.json"},
        )
        assert err.code == "GATE_CONFIG_MISSING"
        assert err.message == "exemptions.json not found"
        assert err.context == {"path": "exemptions.json"}
        assert err.retryable is False  # default: gate failures are not retryable

    def test_retryable_can_be_declared(self) -> None:
        err = GateError(code="GATE_IO", message="transient read failure", retryable=True)
        assert err.retryable is True

    def test_context_defaults_to_empty_dict(self) -> None:
        err = GateError(code="GATE_X", message="m")
        assert err.context == {}

    def test_str_includes_code_and_message(self) -> None:
        err = GateError(code="GATE_X", message="boom")
        assert "GATE_X" in str(err)
        assert "boom" in str(err)

    def test_to_dict_is_the_wire_form(self) -> None:
        err = GateError(code="GATE_X", message="boom", context={"k": "v"}, retryable=True)
        assert err.to_dict() == {
            "code": "GATE_X",
            "message": "boom",
            "context": {"k": "v"},
            "retryable": True,
        }

    def test_raisable_and_catchable(self) -> None:
        with pytest.raises(GateError) as exc_info:
            raise GateError(code="GATE_X", message="boom")
        assert exc_info.value.code == "GATE_X"


class TestGateViolation:
    def test_carries_code_message_and_location(self) -> None:
        v = GateViolation(
            code="FILE_BUDGET_EXCEEDED",
            message="new file is 612 lines (budget 500)",
            path="src/big.py",
            line=1,
            context={"lines": 612, "budget": 500},
        )
        assert v.code == "FILE_BUDGET_EXCEEDED"
        assert v.path == "src/big.py"
        assert v.line == 1
        assert v.context["budget"] == 500

    def test_line_and_context_optional(self) -> None:
        v = GateViolation(code="STICKY_MISSING", message="no sticky intro", path="README.md")
        assert v.line is None
        assert v.context == {}

    def test_to_dict_is_the_wire_form(self) -> None:
        v = GateViolation(code="C", message="m", path="p.py", line=3, context={"a": 1})
        assert v.to_dict() == {
            "code": "C",
            "message": "m",
            "path": "p.py",
            "line": 3,
            "context": {"a": 1},
            "severity": "error",
            "fixable": False,
        }

    def test_is_frozen_value_object(self) -> None:
        v = GateViolation(code="C", message="m", path="p.py")
        with pytest.raises(AttributeError):
            v.code = "OTHER"  # type: ignore[misc]

    def test_severity_and_fixable_default_back_compatibly(self) -> None:
        # The two new fields carry defaults, so old construction is untouched.
        v = GateViolation(code="C", message="m", path="p.py")
        assert v.severity == "error"
        assert v.fixable is False

    def test_positional_construction_unbroken_by_new_fields(self) -> None:
        # The original five fields keep their positions; the additions are last.
        v = GateViolation("C", "m", "p.py", 7, {"k": "v"})
        assert (v.code, v.message, v.path, v.line, v.context) == ("C", "m", "p.py", 7, {"k": "v"})
        assert v.severity == "error"
        assert v.fixable is False

    def test_new_fields_are_declarable(self) -> None:
        v = GateViolation(code="C", message="m", path="p.py", severity="warning", fixable=True)
        assert v.severity == "warning"
        assert v.fixable is True
        assert v.to_dict()["severity"] == "warning"
        assert v.to_dict()["fixable"] is True


class TestGateVerdict:
    def test_clean_verdict_passed_and_exit_zero(self) -> None:
        verdict = GateVerdict(gate="cf-x", violations=[])
        assert verdict.passed is True
        assert verdict.exit_code == 0

    def test_violations_fail_with_exit_one(self) -> None:
        verdict = GateVerdict(
            gate="cf-x",
            violations=[GateViolation(code="C", message="m", path="p.py")],
        )
        assert verdict.passed is False
        assert verdict.exit_code == 1

    def test_error_dominates_with_exit_two(self) -> None:
        # A gate error outranks any findings: the gate could not run.
        verdict = GateVerdict(
            gate="cf-x",
            violations=[GateViolation(code="C", message="m", path="p.py")],
            error=GateError(code="GATE_X", message="boom"),
        )
        assert verdict.passed is False
        assert verdict.exit_code == 2

    def test_to_dict_composes_the_part_wire_forms(self) -> None:
        # `notices` and `evidence` were APPENDED (2026-07-28), the same way
        # GateViolation gained severity/fixable: a PASSING gate carried no
        # measurement in its wire form, so a machine reading the aggregated JSON
        # could not tell a clean grade from one that measured nothing — which is
        # the whole discrimination a ratchet exists to make. Both default empty,
        # so every existing construction is untouched; the key set grows.
        violation = GateViolation(code="C", message="m", path="p.py", line=2)
        error = GateError(code="GATE_X", message="boom", context={"k": "v"})
        verdict = GateVerdict(gate="cf-x", violations=[violation], error=error)
        assert verdict.to_dict() == {
            "gate": "cf-x",
            "passed": False,
            "exit_code": 2,
            "error": error.to_dict(),
            "violations": [violation.to_dict()],
            "notices": [],
            "evidence": {},
        }

    def test_clean_to_dict_has_null_error_and_stable_keys(self) -> None:
        verdict = GateVerdict(gate="cf-x", violations=[])
        report = verdict.to_dict()
        assert report["error"] is None
        assert set(report) == {
            "gate",
            "passed",
            "exit_code",
            "error",
            "violations",
            "notices",
            "evidence",
        }

    def test_evidence_and_notices_ride_the_wire_form_on_a_pass(self) -> None:
        # The rod on the append above: a clean verdict must be able to CARRY its
        # measurement, not merely have somewhere to put it.
        verdict = GateVerdict(
            gate="complexipy", violations=[], notices=["— measured 2"], evidence={"n": 2}
        )
        report = verdict.to_dict()
        assert report["passed"] is True
        assert report["notices"] == ["— measured 2"] and report["evidence"] == {"n": 2}
