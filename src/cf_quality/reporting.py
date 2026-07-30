"""Uniform structured output for the gauge battery — one wire form.

Every gate already speaks the typed vocabulary of :mod:`cf_quality.errors`
(a :class:`~cf_quality.errors.GateViolation` per finding, a
:class:`~cf_quality.errors.GateError` when the gate itself cannot run). This
module is where that vocabulary reaches a reader, so the battery does not
hand-roll its emission gate by gate:

- the DEFAULT is the human-readable report local callers expect — informational
  notices, then one line per finding, then a gate-supplied summary;
- the OPT-IN is the machine-readable JSON wire form file-budget pioneered
  (``{gate, violations, error, ...}``), the only thing on stdout, so CI parses
  one :class:`~cf_quality.errors.GateVerdict` schema across every gate.

JSON is requested explicitly (``json_output=True``) or via the
``CF_QUALITY_JSON`` environment variable; absent both, the default human
output — the shape the gates' existing tests assert — is unchanged.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping, Sequence
from typing import Any

from cf_quality.errors import GateError, GateVerdict, GateViolation

#: Opt-in switch: set truthy to make every gate emit the JSON wire form.
JSON_ENV_VAR = "CF_QUALITY_JSON"
_TRUTHY = frozenset({"1", "true", "yes", "on"})


def json_output_enabled(env: Mapping[str, str] | None = None) -> bool:
    """True when the JSON wire form is requested via :data:`JSON_ENV_VAR`."""
    source = os.environ if env is None else env
    return source.get(JSON_ENV_VAR, "").strip().lower() in _TRUTHY


def violation_location(violation: GateViolation) -> str:
    """The human line prefix: ``path:line`` when anchored, else the path."""
    if violation.line is not None:
        return f"{violation.path}:{violation.line}"
    return violation.path


def print_verdict(
    gate: str,
    violations: Sequence[GateViolation],
    error: GateError | None = None,
    *,
    json_output: bool | None = None,
    notices: Sequence[str] = (),
    measured: str | None = None,
    evidence: Mapping[str, Any] | None = None,
    clean_summary: str | None = None,
    fail_summary: str | None = None,
) -> int:
    """Emit a gate's verdict and return its exit code (0 / 1 / 2).

    Default (human): print ``notices``, then one ``path:line: CODE: message``
    line per finding, then ``fail_summary`` (findings) or ``clean_summary``
    (clean) when supplied. Opt-in (``json_output`` true, or the
    ``CF_QUALITY_JSON`` env var): print only the :class:`GateVerdict` JSON
    wire form. Either way the return value is the derived exit code.

    ``measured`` is THE denominator: the ONE line saying what the gate
    examined. It rides the verdict — to the wire, and to the aggregated board
    line — and prints first in human mode; ``evidence`` is that same
    measurement in machine form. ``notices`` stays the gate's multi-line HUMAN
    report prose (registered exemptions, shrink reports) and never reaches the
    wire, where it would bury the denominator in a blob.
    """
    verdict = GateVerdict(
        gate=gate,
        violations=list(violations),
        error=error,
        notices=[measured] if measured is not None else [],
        evidence=dict(evidence or {}),
    )
    if json_output is None:
        json_output = json_output_enabled()
    if json_output:
        return _emit_json(verdict)
    return _emit_human(verdict, notices, clean_summary, fail_summary)


def _emit_json(verdict: GateVerdict) -> int:
    """The single wire form — to stderr on a gate error, else to stdout."""
    stream = sys.stderr if verdict.error is not None else sys.stdout
    print(json.dumps(verdict.to_dict(), indent=2, ensure_ascii=False), file=stream)
    return verdict.exit_code


def _emit_human(
    verdict: GateVerdict,
    notices: Sequence[str],
    clean_summary: str | None,
    fail_summary: str | None,
) -> int:
    """The denominator, then notices, findings, and a summary — the default."""
    if verdict.error is not None:
        print(json.dumps(verdict.error.to_dict(), ensure_ascii=False), file=sys.stderr)
        return verdict.exit_code
    for notice in (*verdict.notices, *notices):
        print(notice)
    for violation in verdict.violations:
        print(f"{violation_location(violation)}: {violation.code}: {violation.message}")
    summary = fail_summary if verdict.violations else clean_summary
    if summary is not None:
        print(summary)
    return verdict.exit_code
