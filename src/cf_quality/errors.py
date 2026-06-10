"""Typed failure vocabulary for the gauge kit (the Elegance Law).

Two shapes, one language:

- :class:`GateError` — the typed exception a gate *raises* when it cannot do
  its job (missing config, unreadable tree). Carries a stable code, a message,
  structured context, and explicit retryability. Never a bare exception.
- :class:`GateViolation` — a frozen value object a gate *reports* when the
  code under measurement breaks the law. A violation is a finding, not a
  crash: gates collect violations and exit non-zero; they raise GateError
  only when the gate itself cannot run.

Both serialize via ``to_dict()`` so the wire form and the in-process form say
the same thing.
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
    """

    code: str
    message: str
    path: str
    line: int | None = None
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """The wire form — same vocabulary as the in-process form."""
        return {
            "code": self.code,
            "message": self.message,
            "path": self.path,
            "line": self.line,
            "context": self.context,
        }
