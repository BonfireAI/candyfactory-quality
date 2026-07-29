"""Tests for cf-gate — the collect-and-continue battery runner.

The thesis this file pins: one local command runs EVERY gate and reports all
failures in a single pass (COMPLETE), with the same gauge configs CI uses
sourced from the installed package (REPRODUCIBLE). The control rods:

- a repo that is red four different ways (ruff, file-budget, mypy, pytest)
  reports ALL four in one run — never just the first (the COMPLETE proof);
- a true setup failure (missing mypy baseline, unresolvable layout) exits 2,
  while violations after every gate ran exit 1 and a clean board exits 0;
- the mypy pipe gates on ``mypy-baseline filter``'s exit, not mypy's;
- the packaged gauge configs resolve via importlib.resources and stay
  value-faithful to ``configs/*-base.toml`` (the declared-mirror guard);
- cf-import-contract aggregates its three passes into one verdict.

The external tools and cf-* console gates are mocked at the subprocess seam
(``gate_runner._exec`` / ``gate_runner._tool``) so the REAL aggregation logic —
stage table, collect-and-continue loop, verdict parsing, exit derivation — runs
against representative tool output. The import-contract control rod exercises
the gate end to end (real lint-imports).
"""

from __future__ import annotations

import json
import subprocess
import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from cf_quality import gate_runner
from cf_quality.errors import GateError, GateVerdict, GateViolation
from cf_quality.gate_runner import battery_exit_code, run_battery
from cf_quality.import_contract import main as import_contract_main
from cf_quality.repo_config import first_party_packages

KIT_ROOT = Path(__file__).resolve().parents[1]

#: A canned (exit, stdout, stderr) response per stage tool, keyed by stage name.
Responses = Mapping[str, tuple[int, str, str]]


def _verdict_json(gate: str, violations: Sequence[GateViolation] = ()) -> str:
    """The JSON wire form a cf-* gate emits under CF_QUALITY_JSON=1."""
    return json.dumps(GateVerdict(gate=gate, violations=list(violations)).to_dict())


def _violation(code: str, message: str, path: str) -> GateViolation:
    return GateViolation(code=code, message=message, path=path)


def _response_key(argv: Sequence[str]) -> str:
    """Map a stage's argv back to its response key (ruff has two stages)."""
    name = Path(argv[0]).name
    if name == "ruff":
        return "ruff-format" if "format" in argv else "ruff-check"
    return name


def _install_fakes(monkeypatch: pytest.MonkeyPatch, responses: Responses) -> None:
    """Stub the subprocess seam: every tool resolves and returns canned output."""
    monkeypatch.setattr(gate_runner, "_tool", lambda name: Path("/fake") / name)

    def fake_exec(
        argv: list[str],
        cwd: Path,
        env: Mapping[str, str],
        *,
        stdin: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        returncode, stdout, stderr = responses[_response_key(argv)]
        return subprocess.CompletedProcess(argv, returncode, stdout, stderr)

    monkeypatch.setattr(gate_runner, "_exec", fake_exec)


def _write(root: Path, rel: str, content: str = "") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _clean_cf_responses() -> dict[str, tuple[int, str, str]]:
    """Every gate green — the baseline a test perturbs one stage at a time."""
    cf_gates = (
        "cf-sticky-check",
        "cf-file-budget",
        "cf-recursion-check",
        "cf-exemptions",
        "cf-no-bon-ref",
        "cf-import-contract",
    )
    responses: dict[str, tuple[int, str, str]] = {
        "ruff-check": (0, "", ""),
        "ruff-format": (0, "", ""),
        "pytest": (0, "", ""),
    }
    for gate in cf_gates:
        responses[gate] = (0, _verdict_json(gate), "")
    return responses


def _proc(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    """A canned CompletedProcess for unit-testing the verdict parser directly."""
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


# --- Bug 1: tree-recursing gates scope to source_root, not bare `.` ----------


def test_recursion_check_invoked_against_source_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # CI runs `cf-recursion-check .` in a venv-free workspace, so `.` grades only
    # first-party source. Run locally, `.` recurses into .venv and floods false
    # findings — so the runner must scope the gate to the resolved source_root.
    _write(tmp_path, "src/.keep", "")  # src/ exists (→ source_root) but holds no .py
    calls: list[list[str]] = []

    def recording_exec(
        argv: list[str],
        cwd: Path,
        env: Mapping[str, str],
        *,
        stdin: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        returncode, stdout, stderr = _clean_cf_responses()[_response_key(argv)]
        return subprocess.CompletedProcess(argv, returncode, stdout, stderr)

    monkeypatch.setattr(gate_runner, "_tool", lambda name: Path("/fake") / name)
    monkeypatch.setattr(gate_runner, "_exec", recording_exec)

    run_battery(tmp_path, {})

    recursion_argv = next(a for a in calls if Path(a[0]).name == "cf-recursion-check")
    assert recursion_argv[1:] == [str(tmp_path / "src")], "scoped to source_root, not `.`"
    assert "." not in recursion_argv[1:], "bare `.` would recurse into .venv locally"


# --- Bug 2: the verdict parser is robust to all three cf-* wire shapes --------


def test_parser_full_gateverdict_json_is_used_verbatim() -> None:
    raw = _verdict_json(
        "cf-recursion-check",
        [_violation("RECURSION_UNDECLARED", "unbounded recursion", "r.py")],
    )
    verdict = gate_runner._verdict_from_proc("cf-recursion-check", _proc(1, raw))

    assert verdict.gate == "cf-recursion-check"
    assert verdict.error is None
    assert [v.code for v in verdict.violations] == ["RECURSION_UNDECLARED"]
    assert verdict.exit_code == 1


def test_parser_violations_subset_json_builds_verdict() -> None:
    # file_budget emits {gate, violations} — no passed/exit_code/error fields.
    raw = json.dumps(
        {
            "gate": "cf-file-budget",
            "violations": [
                _violation("FILE_BUDGET_EXCEEDED", "big.py 700 > 500", "big.py").to_dict()
            ],
        }
    )
    verdict = gate_runner._verdict_from_proc("cf-file-budget", _proc(1, raw))

    assert verdict.gate == "cf-file-budget"
    assert verdict.error is None
    assert verdict.violations[0].code == "FILE_BUDGET_EXCEEDED"
    assert verdict.exit_code == 1


def test_parser_non_json_rc_zero_is_clean() -> None:
    # sticky-check emits human text; a clean run (rc 0) is a clean verdict.
    verdict = gate_runner._verdict_from_proc("cf-sticky-check", _proc(0, "cf-sticky-check: clean"))

    assert verdict.passed
    assert verdict.error is None
    assert verdict.violations == []


def test_parser_non_json_rc_nonzero_is_one_violation_not_gate_error() -> None:
    # Human text + non-zero exit → ONE violation carrying the output, NOT a
    # GateError: unparseable output is not a 'gate could not run' condition.
    verdict = gate_runner._verdict_from_proc(
        "cf-sticky-check", _proc(1, "sticky mismatch in foo.md", "boom")
    )

    assert verdict.error is None, "unparseable output is not a gate-could-not-run condition"
    assert len(verdict.violations) == 1
    assert verdict.exit_code == 1
    assert "sticky mismatch" in verdict.violations[0].context["output"]


# --- the COMPLETE proof ------------------------------------------------------


def test_one_run_reports_every_failing_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Red four ways at once: a ruff finding, a file-budget overrun, a mypy
    # regression, and a failing test. cf-gate must surface ALL four in ONE run.
    # pkg.py carries a FUNCTION (not a bare assignment) because the complexipy
    # stage now refuses a surface with nothing to grade (tests/
    # test_complexipy_snapshot.py) — a zero-function room could not report clean.
    _write(tmp_path, "pkg.py", "def one() -> int:\n    return 1\n")
    _write(tmp_path, "mypy-baseline.txt", "")
    _write(tmp_path, "complexipy-snapshot.json", "{}")
    responses = _clean_cf_responses()
    responses["ruff-check"] = (1, "pkg.py:1:1: E501 line too long", "")
    responses["cf-file-budget"] = (
        1,
        _verdict_json(
            "cf-file-budget",
            [_violation("FILE_BUDGET_EXCEEDED", "big.py is 700 lines (budget 500)", "big.py")],
        ),
        "",
    )
    responses["mypy"] = (1, "pkg.py: error: bad", "")
    responses["mypy-baseline"] = (1, "pkg.py: error: bad (new over baseline)", "")
    responses["complexipy"] = (0, "", "")
    responses["pytest"] = (1, "1 failed, 0 passed", "")
    _install_fakes(monkeypatch, responses)

    verdicts = run_battery(tmp_path, {})

    failing = {verdict.gate for verdict in verdicts if not verdict.passed}
    assert {"ruff-check", "cf-file-budget", "mypy", "pytest"} <= failing
    assert battery_exit_code(verdicts) == 1
    assert all(verdict.error is None for verdict in verdicts), "violations, not gate errors"


# --- the exit contract -------------------------------------------------------


def test_missing_mypy_baseline_is_a_gate_error_exit_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Python present but no baseline REFUSES (anti-green-by-missing-file). The
    # battery still runs every other stage (collect-and-continue) and exits 2.
    _write(tmp_path, "pkg.py", "x = 1\n")
    _install_fakes(monkeypatch, _clean_cf_responses())

    verdicts = run_battery(tmp_path, {})
    by_gate = {verdict.gate: verdict for verdict in verdicts}
    mypy_verdict = by_gate["mypy"]

    assert battery_exit_code(verdicts) == 2
    assert mypy_verdict.error is not None
    assert mypy_verdict.error.code == "GATE_MYPY_BASELINE_MISSING"
    assert by_gate["complexipy"].error is not None
    assert by_gate["pytest"].passed, "the battery ran past the gate errors"


def test_unresolvable_layout_short_circuits_to_exit_two(tmp_path: Path) -> None:
    # A declared source_root that does not exist fails stage 1; nothing
    # downstream can run, so the battery returns the single setup-error verdict.
    _write(tmp_path, "pyproject.toml", '[tool.cf-quality]\nsource_root = "does_not_exist"\n')

    verdicts = run_battery(tmp_path, {})

    assert len(verdicts) == 1
    assert verdicts[0].gate == "cf-repo-config"
    assert verdicts[0].error is not None
    assert battery_exit_code(verdicts) == 2


def test_clean_python_free_repo_exits_zero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write(tmp_path, "README.md", "# docs only\n")  # no .py anywhere
    _install_fakes(monkeypatch, _clean_cf_responses())

    verdicts = run_battery(tmp_path, {})
    gates = {verdict.gate for verdict in verdicts}

    assert battery_exit_code(verdicts) == 0
    assert all(verdict.passed for verdict in verdicts)
    assert "mypy" not in gates and "complexipy" not in gates, "ratchets skip, visibly, py-free"


def test_mypy_gates_on_filter_exit_not_mypy_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # mypy itself exits non-zero (baselined debt exists) but mypy-baseline
    # filter exits 0 (no NEW errors) — the verdict must ride the filter.
    # The function (not a bare assignment) keeps the complexipy stage's surface
    # non-vacuous, so this test grades the mypy pipe and nothing else.
    _write(tmp_path, "pkg.py", "def one() -> int:\n    return 1\n")
    _write(tmp_path, "mypy-baseline.txt", "")
    _write(tmp_path, "complexipy-snapshot.json", "{}")
    responses = _clean_cf_responses()
    responses["mypy"] = (1, "pkg.py: error: baselined debt", "")
    responses["mypy-baseline"] = (0, "", "")
    responses["complexipy"] = (0, "", "")
    _install_fakes(monkeypatch, responses)

    verdicts = run_battery(tmp_path, {})
    by_gate = {verdict.gate: verdict for verdict in verdicts}

    assert by_gate["mypy"].passed, "verdict must ride mypy-baseline filter's exit, not mypy's"
    assert battery_exit_code(verdicts) == 0


# --- config sourcing (the declared-mirror, wheel-resolvable guard) -----------


def test_packaged_configs_resolve_via_importlib_resources() -> None:
    for name in ("ruff-base.toml", "mypy-base.toml"):
        with gate_runner._packaged_config(name) as path:
            assert path.is_file(), f"packaged gauge config not resolvable: {name}"


def test_packaged_configs_mirror_the_canonical_configs() -> None:
    # Declared mirror, not a silent duplicate: the packaged gauge configs (shipped
    # in the wheel so cf-gate resolves them) must stay value-faithful to
    # configs/*-base.toml, the copies CI reads directly from the kit checkout.
    for name in ("ruff-base.toml", "mypy-base.toml"):
        canonical = tomllib.loads((KIT_ROOT / "configs" / name).read_text(encoding="utf-8"))
        with gate_runner._packaged_config(name) as path:
            packaged = tomllib.loads(path.read_text(encoding="utf-8"))
        assert packaged == canonical, f"packaged {name} drifted from configs/{name}"


# --- import-contract aggregation (the cross-pass fail-fast is closed) --------


def _mount_contract_repo(root: Path) -> None:
    (root / "core").mkdir()
    (root / "core" / "__init__.py").write_text(
        'import importlib\n_impl = importlib.import_module("tenants.acme")\n', encoding="utf-8"
    )
    (root / "tenants").mkdir()
    (root / "tenants" / "__init__.py").write_text("", encoding="utf-8")
    (root / "tenants" / "acme.py").write_text("X = 1\n", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        "\n".join(
            [
                "[tool.importlinter]",
                'root_packages = ["core", "tenants"]',
                "include_external_packages = false",
                "exclude_type_checking_imports = false",
                "",
                "[[tool.importlinter.contracts]]",
                'name = "core does not import tenants"',
                'type = "forbidden"',
                'source_modules = ["core"]',
                'forbidden_modules = ["tenants"]',
                'unmatched_ignore_imports_alerting = "error"',
                'ignore_imports = ["core.** -> tenants.**"]',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "import-contract-baseline.json").write_text(
        '{"ignored_imports": 1}\n', encoding="utf-8"
    )


def test_import_contract_aggregates_passes_into_one_verdict(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # A wildcard ignore (PASS 1) AND a module-level dynamic import (PASS 3) in
    # one repo: the old gate fail-fast on PASS 1 and never saw PASS 3. Aggregated,
    # both land in a single verdict.
    _mount_contract_repo(tmp_path)

    exit_code = import_contract_main(["--root", str(tmp_path)])
    out = capsys.readouterr().out

    assert exit_code == 1
    assert "CONTRACT_LINT_WILDCARD" in out, "PASS 1 finding"
    assert "CONTRACT_DYNAMIC_IMPORT" in out, "PASS 3 finding — aggregated, not fail-fast"


# --- per-stage targeting (migrated down from the YAML-altitude battery) -------
#
# These behaviors used to be asserted by PARSING quality-gate.yml's discrete
# steps. The ~11 fail-fast steps collapsed into the one cf-gate step, so the
# behaviors now LIVE in gate_runner and are pinned here, at the altitude they
# actually run: ruff rides the derived known-first-party; that first-party set
# is the SAME one cf-repo-config resolves; complexipy refuses a Python repo
# with no snapshot, skips a Python-free one visibly, and targets the resolved
# source_root in a single unpiped process (a pipe would mask its exit code).


def _layout(root: Path, *, first_party: str = "[]", py_present: bool = True) -> gate_runner.Layout:
    """A Layout for unit-testing one stage in isolation (source_root == src/)."""
    return gate_runner.Layout(
        root=root,
        source_root=root / "src",
        package_dir=root,
        first_party=first_party,
        py_present=py_present,
    )


def _record_calls(
    monkeypatch: pytest.MonkeyPatch, calls: list[tuple[list[str], str | None]]
) -> None:
    """Stub the subprocess seam to record (argv, stdin) and report a clean run."""
    monkeypatch.setattr(gate_runner, "_tool", lambda name: Path("/fake") / name)

    def recording_exec(
        argv: list[str],
        cwd: Path,
        env: Mapping[str, str],
        *,
        stdin: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        calls.append((list(argv), stdin))
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(gate_runner, "_exec", recording_exec)


def test_ruff_check_rides_layout_first_party(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The shared ruff gauge cannot name every consumer's packages, so the gate
    # splices the derived names into ruff's inline known-first-party override —
    # the I001 cross-config conflict's control rod, now an argv assertion.
    calls: list[tuple[list[str], str | None]] = []
    _record_calls(monkeypatch, calls)
    layout = _layout(tmp_path, first_party='["acme", "acme_core"]')

    gate_runner._ruff_check(layout, {})

    argv = calls[0][0]
    assert Path(argv[0]).name == "ruff" and argv[1] == "check"
    assert 'lint.isort.known-first-party=["acme", "acme_core"]' in argv


def test_layout_first_party_derives_from_resolved_source_root(tmp_path: Path) -> None:
    # The first-party set ruff rides is derived from the consumer's OWN resolved
    # source root — the exact list cf-repo-config emits (one resolver, never two).
    _write(tmp_path, "src/acme/__init__.py", "")
    _write(tmp_path, "src/acme/core.py", "X = 1\n")

    layout = gate_runner._resolve_layout(tmp_path)

    assert layout.first_party == json.dumps(first_party_packages(tmp_path))
    assert "acme" in json.loads(layout.first_party), "the package is a derived first-party name"


def test_complexipy_refuses_python_repo_without_snapshot(tmp_path: Path) -> None:
    # Same doctrine as the mypy baseline: green-by-file-absence is opt-in gaming.
    # A Python repo with no snapshot REFUSES with a typed GateError.
    _write(tmp_path, "pkg.py", "x = 1\n")
    layout = _layout(tmp_path, py_present=True)

    with pytest.raises(GateError) as excinfo:
        gate_runner._complexipy(layout, {})

    assert excinfo.value.code == "GATE_COMPLEXIPY_SNAPSHOT_MISSING"


def test_complexipy_skips_python_free_repo_visibly(tmp_path: Path) -> None:
    # Only a Python-free repo may skip — the stage returns None (the battery
    # omits it from the board), never a silent green.
    layout = _layout(tmp_path, py_present=False)

    assert gate_runner._complexipy(layout, {}) is None


def test_complexipy_targets_source_root_in_one_unpiped_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # With the snapshot present, complexipy grades the resolved source_root as a
    # SINGLE process — piping it (as the mypy stage pipes through the filter)
    # would mask its exit code (the tool-spike defect this rod fences off).
    # src/ carries a real function so the stage's vacuity guard (which refuses a
    # surface with nothing to grade) is satisfied and this rod still measures argv.
    _write(tmp_path, "src/mod.py", "def one() -> int:\n    return 1\n")
    _write(tmp_path, "complexipy-snapshot.json", "{}")
    calls: list[tuple[list[str], str | None]] = []
    _record_calls(monkeypatch, calls)
    layout = _layout(tmp_path)

    verdict = gate_runner._complexipy(layout, {})

    assert verdict is not None and verdict.passed
    assert len(calls) == 1, "one unpiped process — no stdin handoff like the mypy filter pipe"
    argv, stdin = calls[0]
    assert argv == [str(Path("/fake") / "complexipy"), str(tmp_path / "src")]
    assert stdin is None
