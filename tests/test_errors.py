"""Contract tests for cf_quality.errors — the kit's Elegance Law vocabulary.

GateError is the typed failure every gate raises; GateViolation is a finding
a gate reports. Both must be self-describing: stable code, message, structured
context, explicit retryability — never a bare exception or a magic return.
"""

import pytest

from cf_quality.errors import GateError, GateViolation


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
        }

    def test_is_frozen_value_object(self) -> None:
        v = GateViolation(code="C", message="m", path="p.py")
        with pytest.raises(AttributeError):
            v.code = "OTHER"  # type: ignore[misc]
