"""Typed failure vocabulary for the gauge kit (the Elegance Law).

Three shapes, one language:

- :class:`GateError` — the typed exception a gate *raises* when it cannot do
  its job (missing config, unreadable tree). Carries a stable code, a message,
  structured context, and explicit retryability. Never a bare exception.
- :class:`GateViolation` — a frozen value object a gate *reports* when the
  code under measurement breaks the law. A violation is a finding, not a
  crash: gates collect violations and exit non-zero; they raise GateError
  only when the gate itself cannot run.
- :class:`GateVerdict` — the aggregate a gate run resolves to: the gate's
  name, the violations it collected, and the GateError it died on (if any).
  Its :attr:`~GateVerdict.exit_code` and :attr:`~GateVerdict.passed` derive
  the kit-wide exit contract (0 clean · 1 violations · 2 the gate could not
  run) from those parts, so every gate reports one structured verdict. It also
  carries the ``notices`` and ``evidence`` a PASS needs: a verdict with no
  measurement behind it cannot be told from one that measured nothing.

All three serialize via ``to_dict()`` so the wire form and the in-process
form say the same thing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class GateError(Exception):
    """A gate could not perform its check.

    Attributes:
        code: Stable machine-readable error code (e.g. ``GATE_CONFIG_MISSING``).
        message: Human-readable description of what the world did.
        context: Structured detail a caller can reason about.
        retryable: Whether retrying the gate could succeed (default False —
            gate failures are deterministic unless declared otherwise).
    """

    def __init__(
        self,
        *,
        code: str,
        message: str,
        context: dict[str, Any] | None = None,
        retryable: bool = False,
    ) -> None:
        self.code = code
        self.message = message
        self.context: dict[str, Any] = context if context is not None else {}
        self.retryable = retryable
        super().__init__(f"{code}: {message}")

    def to_dict(self) -> dict[str, Any]:
        """The wire form — same vocabulary as the in-process form."""
        return {
            "code": self.code,
            "message": self.message,
            "context": self.context,
            "retryable": self.retryable,
        }


@dataclass(frozen=True)
class GateViolation:
    """A single finding a gate reports against the code under measurement.

    Attributes:
        code: Stable violation code (e.g. ``FILE_BUDGET_EXCEEDED``).
        message: What was measured and which budget it broke.
        path: Repo-relative path of the offending artifact.
        line: 1-based line number when the finding is line-anchored.
        context: Structured measurement detail (e.g. measured value, budget).
        severity: Finding weight (default ``"error"`` — every finding is a
            failure unless a gate downgrades it). Appended after the original
            fields so existing positional/keyword construction is untouched.
        fixable: Whether a tool could mechanically repair the finding
            (default ``False``). Appended for the same back-compat reason.
    """

    code: str
    message: str
    path: str
    line: int | None = None
    context: dict[str, Any] = field(default_factory=dict)
    severity: str = "error"
    fixable: bool = False

    def to_dict(self) -> dict[str, Any]:
        """The wire form — same vocabulary as the in-process form."""
        return {
            "code": self.code,
            "message": self.message,
            "path": self.path,
            "line": self.line,
            "context": self.context,
            "severity": self.severity,
            "fixable": self.fixable,
        }


@dataclass(frozen=True)
class GateVerdict:
    """The aggregate a single gate run resolves to — one structured verdict.

    Composes the existing primitives rather than restating them: the
    collected :class:`GateViolation` findings and the :class:`GateError` the
    gate died on (if any). The exit contract is *derived*, never stored, so
    it cannot drift from the parts it summarizes.

    Attributes:
        gate: The gate's stable name (e.g. ``cf-file-budget``).
        violations: Every finding the gate reported (empty when clean).
        error: The typed failure the gate raised when it could not run, or
            None when the gate completed (clean or with findings).
        notices: Informational lines a reader needs even on a PASS (default
            empty). Appended after the original fields, like GateViolation's
            ``severity``/``fixable``, so existing construction is untouched.
        evidence: The structured measurement behind the verdict (default
            empty) — counts, resolved config, whatever proves the gate looked.
            A PASS with no evidence is indistinguishable from a PASS that
            measured nothing, and telling those apart is the whole job of a
            ratchet; prose in ``notices`` cannot carry that to a machine, so
            the numbers ride their own field.
    """

    gate: str
    violations: list[GateViolation]
    error: GateError | None = None
    notices: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        """True only when the gate ran and found nothing."""
        return self.error is None and not self.violations

    @property
    def exit_code(self) -> int:
        """The kit-wide exit contract: 0 clean · 1 violations · 2 gate error."""
        if self.error is not None:
            return 2
        return 1 if self.violations else 0

    def to_dict(self) -> dict[str, Any]:
        """The stable wire form composing the parts' own ``to_dict()``."""
        return {
            "gate": self.gate,
            "passed": self.passed,
            "exit_code": self.exit_code,
            "error": self.error.to_dict() if self.error is not None else None,
            "violations": [violation.to_dict() for violation in self.violations],
            "notices": list(self.notices),
            "evidence": dict(self.evidence),
        }
