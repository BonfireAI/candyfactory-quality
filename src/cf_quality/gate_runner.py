"""cf-gate — one collect-and-continue runner that aggregates every verdict.

The battery is split across many console scripts and external tools so each
gate can be mounted alone. That fidelity costs the local developer the two
things a gate is FOR: COMPLETE (every failure surfaced in one run, not the
first) and REPRODUCIBLE (the local command == CI). Per-step
``continue-on-error`` would buy COMPLETE at the cost of neutering, so a single
runner is the only compliant path: it RUNS every stage, collecting one
:class:`~cf_quality.errors.GateVerdict` each, and decides once at the end.

Exit contract (the kit-wide one, derived from the aggregate):

- 2 — a setup failure: a stage raised a typed :class:`GateError`. The layout
  stage is the sole hard short-circuit; every OTHER stage still runs when one
  errors, so a red run shows the whole board, then exits 2.
- 1 — every stage ran and at least one reported violations.
- 0 — every stage ran clean (or was legitimately, visibly skipped).

Stages mirror ``.github/workflows/quality-gate.yml``, declared once in
:func:`_stages`. cf-* gates run with ``CF_QUALITY_JSON=1`` and their verdict
JSON is parsed back; external tools (ruff, mypy, complexipy, pytest) map their
exit code to pass/fail. Gauge configs load from the INSTALLED package via
``importlib.resources`` (wheel == editable tree).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

from cf_quality.complexipy_ratchet import complexipy_verdict
from cf_quality.errors import GateError, GateVerdict, GateViolation
from cf_quality.mypy_normalize import normalize_mypy_stdout
from cf_quality.repo_config import (
    first_party_packages,
    resolve_package_dir,
    resolve_source_root,
)
from cf_quality.reporting import json_output_enabled, violation_location

RUNNER_GATE = "cf-gate"


@dataclass(frozen=True)
class Layout:
    """The resolved consumer layout every downstream stage reads.

    ``first_party`` is the TOML/JSON array literal cf-repo-config emits, spliced
    straight into ruff's ``lint.isort.known-first-party=...`` inline override.
    """

    root: Path
    source_root: Path
    package_dir: Path
    first_party: str
    py_present: bool


@dataclass(frozen=True)
class Stage:
    """One battery stage: a stable name and a runner returning its verdict.

    The runner returns None when the stage is legitimately and visibly skipped
    (no MIRRORS.md, or a Python-free repo for the type/complexity ratchets).
    """

    name: str
    run: Callable[[Layout, Mapping[str, str]], GateVerdict | None]


# --- subprocess plumbing ----------------------------------------------------


def _tool(name: str) -> Path:
    """The named console script / tool beside the running Python (absolute)."""
    candidate = Path(sys.executable).parent / name
    if not candidate.is_file():
        raise GateError(
            code="GATE_TOOL_MISSING",
            message=f"{name} is not installed beside the running Python — "
            "install the kit's [dev] extra (it pins the whole gauge battery)",
            context={"tool": name, "expected": str(candidate)},
        )
    return candidate


def _exec(
    argv: list[str], cwd: Path, env: Mapping[str, str], *, stdin: str | None = None
) -> subprocess.CompletedProcess[str]:
    """Run a fixed-argv tool (absolute path, no shell); OSError → typed error."""
    try:
        return subprocess.run(  # noqa: S603 — absolute argv from _tool, no shell
            argv,
            cwd=cwd,
            env=dict(env),
            input=stdin,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise GateError(
            code="GATE_SUBPROCESS_FAILED",
            message=f"could not execute {argv[0]}: {exc}",
            context={"argv": argv},
        ) from exc


@contextmanager
def _packaged_config(name: str) -> Iterator[Path]:
    """A concrete filesystem path to a packaged gauge config (wheel or editable).

    ``importlib.resources`` resolves the SAME ``cf_quality/_configs`` path under
    a clean wheel install and an editable source tree; ``as_file`` materializes
    a real path for the external tool's ``--config`` argument.
    """
    resource = resources.files("cf_quality").joinpath("_configs", name)
    if not resource.is_file():
        raise GateError(
            code="GATE_CONFIG_MISSING",
            message=f"packaged gauge config not found: {name} — the wheel must "
            f"ship cf_quality/_configs/{name} (extend [tool.setuptools.package-data])",
            context={"resource": str(resource)},
        )
    with resources.as_file(resource) as path:
        yield path


# --- verdict construction ---------------------------------------------------


def _external_violation(gate: str, proc: subprocess.CompletedProcess[str]) -> GateViolation:
    """A non-zero external tool maps to one finding carrying its output."""
    detail = (proc.stdout + proc.stderr).strip()
    return GateViolation(
        code=f"{gate.upper().replace('-', '_')}_FAILED",
        message=f"{gate} reported findings (exit {proc.returncode})",
        path=".",
        context={"exit_code": proc.returncode, "output": detail},
    )


def _run_external(gate: str, argv: list[str], *, cwd: Path, env: Mapping[str, str]) -> GateVerdict:
    """Run an external tool; exit 0 is clean, any non-zero is one violation."""
    proc = _exec(argv, cwd, env)
    if proc.returncode == 0:
        return GateVerdict(gate=gate, violations=[])
    return GateVerdict(gate=gate, violations=[_external_violation(gate, proc)])


def _violation_from_dict(data: Mapping[str, Any]) -> GateViolation:
    return GateViolation(
        code=data["code"],
        message=data["message"],
        path=data["path"],
        line=data.get("line"),
        context=data.get("context", {}),
        severity=data.get("severity", "error"),
        fixable=data.get("fixable", False),
    )


def _error_from_dict(data: Mapping[str, Any] | None) -> GateError | None:
    if data is None:
        return None
    return GateError(
        code=data["code"],
        message=data["message"],
        context=data.get("context", {}),
        retryable=data.get("retryable", False),
    )


#: Keys that mark a JSON object as a structured verdict (full, the subset, or a
#: bare ``{error}``) vs incidental JSON a human-text gate happened to print.
_VERDICT_KEYS = frozenset({"error", "passed", "exit_code", "violations"})


def _structured_verdict(gate: str, data: Mapping[str, Any]) -> GateVerdict:
    """Build a verdict from a cf-* gate's JSON — full shape or the subset.

    Honours an ``error`` field so a gate that exits 2 under its own GateError
    contract resolves to a GateError verdict; a partial emitter's has none.
    """
    return GateVerdict(
        gate=data.get("gate", gate),
        violations=[_violation_from_dict(item) for item in data.get("violations", [])],
        error=_error_from_dict(data.get("error")),
        notices=list(data.get("notices", [])),
        evidence=dict(data.get("evidence", {})),
    )


def _verdict_from_proc(gate: str, proc: subprocess.CompletedProcess[str]) -> GateVerdict:
    """Parse a cf-* gate's output into a verdict, robust to its three wire shapes.

    1. a full GateVerdict JSON (or any object carrying ``error``) → use it;
    2. the ``{gate, violations}`` subset (a partial emitter) → verdict, error=None;
    3. non-JSON human text (a foreign emitter) → exit-code semantics: rc 0 is
       clean, any non-zero is one violation carrying the output (NOT a GateError
       — unparseable output is not a gate-could-not-run condition).
    """
    raw = proc.stdout.strip() or proc.stderr.strip()
    try:
        data = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        data = None
    if isinstance(data, dict) and _VERDICT_KEYS & data.keys():
        return _structured_verdict(gate, data)
    if proc.returncode == 0:
        return GateVerdict(gate=gate, violations=[])
    return GateVerdict(gate=gate, violations=[_external_violation(gate, proc)])


def _run_cf_gate(
    gate: str, args: Sequence[str], *, cwd: Path, env: Mapping[str, str]
) -> GateVerdict:
    """Run a cf-* console gate in JSON mode and parse its verdict."""
    sub_env = {**env, "CF_QUALITY_JSON": "1"}
    return _verdict_from_proc(gate, _exec([str(_tool(gate)), *args], cwd, sub_env))


# --- the stages (declared once, mirroring quality-gate.yml) -----------------


def _ruff_check(layout: Layout, env: Mapping[str, str]) -> GateVerdict:
    with _packaged_config("ruff-base.toml") as cfg:
        argv = [
            str(_tool("ruff")),
            "check",
            ".",
            "--config",
            str(cfg),
            "--config",
            f"lint.isort.known-first-party={layout.first_party}",
        ]
        return _run_external("ruff-check", argv, cwd=layout.root, env=env)


def _ruff_format(layout: Layout, env: Mapping[str, str]) -> GateVerdict:
    with _packaged_config("ruff-base.toml") as cfg:
        argv = [str(_tool("ruff")), "format", "--check", ".", "--config", str(cfg)]
        return _run_external("ruff-format", argv, cwd=layout.root, env=env)


def _cf_runner(gate: str, *args: str) -> Callable[[Layout, Mapping[str, str]], GateVerdict]:
    def run(layout: Layout, env: Mapping[str, str]) -> GateVerdict:
        return _run_cf_gate(gate, args, cwd=layout.root, env=env)

    return run


def _cf_source_scoped(gate: str) -> Callable[[Layout, Mapping[str, str]], GateVerdict]:
    """A tree-recursing cf-* gate, scoped to the resolved source_root.

    quality-gate.yml passes bare ``.`` — in CI's venv-free workspace that grades
    only first-party source, but LOCALLY ``.`` recurses into ``.venv`` and floods
    false findings. The resolved source_root reproduces CI's EFFECTIVE scope.
    """

    def run(layout: Layout, env: Mapping[str, str]) -> GateVerdict:
        return _run_cf_gate(gate, [str(layout.source_root)], cwd=layout.root, env=env)

    return run


def _mirror_check(layout: Layout, env: Mapping[str, str]) -> GateVerdict | None:
    """Skip-if-absent: a repo with no MIRRORS.md declares no cross-repo copies."""
    if not (layout.root / "MIRRORS.md").is_file():
        return None
    return _run_cf_gate("cf-mirror-check", ["check", "--repo", "."], cwd=layout.root, env=env)


def _mypy(layout: Layout, env: Mapping[str, str]) -> GateVerdict | None:
    """mypy through the baseline ratchet — gate on the FILTER's exit, explicitly.

    No baseline + Python present REFUSES (anti-green-by-missing-file); a
    Python-free repo skips, visibly. The pipe is two captured processes so the
    verdict rides ``mypy-baseline filter``'s exit, never mypy's or a pipefail.
    mypy's stdout is env-normalized between the two so the verdict tracks code.
    """
    if not (layout.root / "mypy-baseline.txt").is_file():
        return _ratchet_skip_or_refuse(
            layout,
            "GATE_MYPY_BASELINE_MISSING",
            "mypy-baseline.txt",
            "boot the baseline (mypy <source-root> | python -m cf_quality.mypy_normalize"
            " | mypy-baseline sync), even at zero errors",
        )
    with _packaged_config("mypy-base.toml") as cfg:
        mypy_proc = _exec(
            [str(_tool("mypy")), str(layout.source_root), "--config-file", str(cfg)],
            layout.root,
            env,
        )
    normalized = normalize_mypy_stdout(mypy_proc.stdout)
    argv = [str(_tool("mypy-baseline")), "filter"]
    filter_proc = _exec(argv, layout.root, env, stdin=normalized)
    if filter_proc.returncode == 0:
        return GateVerdict(gate="mypy", violations=[])
    detail = (filter_proc.stdout + filter_proc.stderr).strip()
    return GateVerdict(
        gate="mypy",
        violations=[
            GateViolation(
                code="MYPY_NEW_ERRORS",
                message="mypy-baseline filter reported new type errors over the baseline",
                path=".",
                context={"exit_code": filter_proc.returncode, "output": detail},
            )
        ],
    )


def _complexipy(layout: Layout, env: Mapping[str, str]) -> GateVerdict | None:
    """complexipy WRITE-FREE (its compare REWRITES the floor) — refuse/skip as mypy's."""
    if not (layout.root / "complexipy-snapshot.json").is_file():
        return _ratchet_skip_or_refuse(
            layout,
            "GATE_COMPLEXIPY_SNAPSHOT_MISSING",
            "complexipy-snapshot.json",
            "boot the snapshot (complexipy <source-root> --snapshot-create), even when clean",
        )
    return complexipy_verdict(layout, env, _tool("complexipy"), _exec)


def _ratchet_skip_or_refuse(
    layout: Layout, code: str, filename: str, remedy: str
) -> GateVerdict | None:
    """Shared ratchet precondition: refuse on Python-with-no-watermark, else skip."""
    if not layout.py_present:
        return None
    raise GateError(
        code=code,
        message=f"Python files present but no {filename} — {remedy}",
        context={"expected": str(layout.root / filename)},
    )


def _pytest(layout: Layout, env: Mapping[str, str]) -> GateVerdict:
    """pytest from the declared package dir (where the suite + config live)."""
    return _run_external("pytest", [str(_tool("pytest"))], cwd=layout.package_dir, env=env)


def _stages() -> list[Stage]:
    """The 13-stage battery (layout is stage 1, resolved before this list runs)."""
    return [
        Stage("ruff-check", _ruff_check),
        Stage("ruff-format", _ruff_format),
        Stage("cf-sticky-check", _cf_runner("cf-sticky-check", "check", ".")),
        Stage("cf-file-budget", _cf_runner("cf-file-budget", "check")),
        Stage("cf-mirror-check", _mirror_check),
        Stage("cf-recursion-check", _cf_source_scoped("cf-recursion-check")),
        Stage("cf-exemptions", _cf_runner("cf-exemptions")),
        Stage("cf-no-bon-ref", _cf_runner("cf-no-bon-ref")),
        Stage("cf-import-contract", _cf_runner("cf-import-contract", "--root", ".")),
        Stage("mypy", _mypy),
        Stage("complexipy", _complexipy),
        Stage("pytest", _pytest),
    ]


# --- layout resolution + the collect-and-continue loop ----------------------


def _has_python(root: Path) -> bool:
    """Mirror the workflow's ``find . -name '*.py' -not -path '*/.*'`` test."""
    return any(
        not any(part.startswith(".") for part in path.relative_to(root).parts)
        for path in root.rglob("*.py")
    )


def _resolve_layout(root: Path) -> Layout:
    """Stage 1 — the declared layout; a failure here is a hard exit-2 setup error."""
    return Layout(
        root=root,
        source_root=resolve_source_root(root),
        package_dir=resolve_package_dir(root),
        first_party=json.dumps(first_party_packages(root)),
        py_present=_has_python(root),
    )


def _run_stage(stage: Stage, layout: Layout, env: Mapping[str, str]) -> GateVerdict | None:
    """Run one stage, turning a typed GateError into that stage's error verdict.

    A gate error is recorded (not raised) so the battery keeps running every
    other stage — the whole board shows — while the aggregate still exits 2.
    """
    try:
        return stage.run(layout, env)
    except GateError as exc:
        return GateVerdict(gate=stage.name, violations=[], error=exc)


def run_battery(root: Path, env: Mapping[str, str]) -> list[GateVerdict]:
    """Run stage 1 (layout), then every stage, collecting one verdict each.

    A layout failure short-circuits, returning the single setup-error verdict.
    """
    try:
        layout = _resolve_layout(root)
    except GateError as exc:
        return [GateVerdict(gate="cf-repo-config", violations=[], error=exc)]
    verdicts: list[GateVerdict] = []
    for stage in _stages():
        verdict = _run_stage(stage, layout, env)
        if verdict is not None:
            verdicts.append(verdict)
    return verdicts


def battery_exit_code(verdicts: Sequence[GateVerdict]) -> int:
    """The kit-wide exit contract over the aggregate: 2 error · 1 violations · 0 clean."""
    if any(verdict.error is not None for verdict in verdicts):
        return 2
    if any(verdict.violations for verdict in verdicts):
        return 1
    return 0


# --- emission (human aggregate by default, JSON on opt-in) ------------------


@dataclass(frozen=True)
class _Aggregate:
    verdicts: list[GateVerdict] = field(default_factory=list)
    exit_code: int = 0


def _gate_detail(verdict: GateVerdict) -> list[str]:
    """The per-gate failure lines: the typed error, else one line per finding."""
    if verdict.error is not None:
        return [f"  ERROR {verdict.error.code}: {verdict.error.message}"]
    return [
        f"  {violation_location(violation)}: {violation.code}: {violation.message}"
        for violation in verdict.violations
    ]


def _emit_human(agg: _Aggregate) -> None:
    """One status line per gate (with its notices — a PASS must show what it measured)."""
    failing = [verdict for verdict in agg.verdicts if not verdict.passed]
    for verdict in agg.verdicts:
        status = "PASS" if verdict.passed else "FAIL"
        print(f"{status}  {verdict.gate}", *verdict.notices)
    if not failing:
        print(f"\n{RUNNER_GATE}: PASS — every gate is clean")
        return
    print(
        f"\n{RUNNER_GATE}: FAIL — {len(failing)} of {len(agg.verdicts)} gate(s) red "
        f"(exit {agg.exit_code})"
    )
    for verdict in failing:
        print(verdict.gate)
        for line in _gate_detail(verdict):
            print(line)


def _emit_json(agg: _Aggregate) -> None:
    """The aggregated wire form — every stage's own to_dict() under one envelope."""
    payload = {
        "gate": RUNNER_GATE,
        "passed": agg.exit_code == 0,
        "exit_code": agg.exit_code,
        "stages": [verdict.to_dict() for verdict in agg.verdicts],
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    """Run the whole battery and exit on the worst verdict (0 / 1 / 2)."""
    parser = argparse.ArgumentParser(
        prog=RUNNER_GATE,
        description="Run every quality gate, collect each verdict, exit on the worst.",
    )
    parser.add_argument("--root", default=".", help="repo root (default: cwd)")
    parser.add_argument("--json", action="store_true", help="emit the aggregated JSON wire form")
    args = parser.parse_args(argv)
    verdicts = run_battery(Path(args.root).resolve(), os.environ)
    agg = _Aggregate(verdicts=verdicts, exit_code=battery_exit_code(verdicts))
    if args.json or json_output_enabled():
        _emit_json(agg)
    else:
        _emit_human(agg)
    return agg.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
