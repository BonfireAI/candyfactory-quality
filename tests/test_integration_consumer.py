"""End-to-end integration test: grade a real consumer repo through cf-gate.

The kit's strongest defences — layout resolution (cf-repo-config), the mypy
``normalize -> mypy-baseline filter`` pipeline, and config-from-wheel (the
packaged ``_configs/*.toml``) — are otherwise proven only by unit / YAML-shape
tests, so a regression that re-wired any of them could still ship green. This
test closes that gap: it drives the REAL ``run_battery`` (the engine behind the
``cf-gate`` console script) against a tiny FIXTURE consumer repo and asserts the
whole path runs for real:

- the fixture's DECLARED layout (``[tool.cf-quality] source_root = "app"``)
  resolves through cf-repo-config to the right source_root / package_dir /
  first-party set — NOT the default discovery, which would pick the repo root;
- the mypy stage runs through normalize -> ``mypy-baseline filter`` against the
  fixture's empty baseline and the SHIPPED ``_configs/mypy-base.toml`` (the
  packaged gauge resolved via importlib.resources, not the inline pyproject
  mirror), reaching a clean verdict;
- the aggregate verdict is clean (exit 0) for the clean fixture;
- an injected type error flips the mypy stage red (exit 1), proving the e2e path
  actually GRADES rather than rubber-stamping the fixture.

Only the genuinely external pytest-on-the-fixture stage is stubbed: the fixture
ships no suite, and a real pytest-in-pytest would add nothing to the
layout+mypy+config path under test. ruff, complexipy, the cf-* gates, layout
resolution and the mypy pipeline all run for real against the packaged gauge.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from cf_quality import gate_runner, repo_config
from cf_quality.errors import GateVerdict
from cf_quality.gate_runner import battery_exit_code, run_battery

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "consumer_min"


def _consumer_copy(tmp_path: Path) -> Path:
    """A throwaway copy of the fixture so tool caches never touch the committed tree."""
    consumer = tmp_path / "consumer"
    shutil.copytree(FIXTURE, consumer)
    return consumer


def _stub_pytest(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub ONLY the pytest stage — the fixture ships no suite, and running
    pytest-in-pytest would not exercise layout / mypy / config (the path under test)."""
    monkeypatch.setattr(
        gate_runner,
        "_pytest",
        lambda layout, env: GateVerdict(gate="pytest", violations=[]),
    )


def _board(verdicts: list[GateVerdict]) -> str:
    """A readable per-gate board for assert messages on an unexpected verdict."""
    return "\n".join(
        f"{verdict.gate}: {'PASS' if verdict.passed else 'FAIL'}" for verdict in verdicts
    )


def test_declared_layout_resolves_through_repo_config(tmp_path: Path) -> None:
    # cf-repo-config reads the committed declaration and resolves it; the derived
    # first-party set is the SAME one ruff later rides (one resolver, never two).
    consumer = _consumer_copy(tmp_path)

    declared = repo_config.load(consumer)
    layout = gate_runner._resolve_layout(consumer)

    assert declared.source_root == "app", "the fixture commits a non-default source root"
    assert layout.source_root == (consumer / "app").resolve(), "declaration, not src/ discovery"
    assert layout.package_dir == consumer, "no package_dir declared -> the repo root"
    assert json.loads(layout.first_party) == ["widget"], "first-party derived from app/"


def test_mypy_stage_sources_the_shipped_packaged_gauge() -> None:
    # The mypy (and ruff) stages config from the WHEEL's _configs/, not the inline
    # pyproject mirror — the config-from-wheel defence this e2e fences.
    with gate_runner._packaged_config("mypy-base.toml") as cfg:
        assert cfg.is_file()
        assert cfg.parent.name == "_configs", "sourced from the packaged gauge dir"


def test_clean_consumer_passes_the_full_battery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    consumer = _consumer_copy(tmp_path)
    _stub_pytest(monkeypatch)

    verdicts = run_battery(consumer, os.environ)
    by_gate = {verdict.gate: verdict for verdict in verdicts}

    assert battery_exit_code(verdicts) == 0, _board(verdicts)
    assert all(verdict.passed for verdict in verdicts), _board(verdicts)
    assert by_gate["mypy"].passed, "the mypy normalize->baseline pipeline reached a clean verdict"
    assert "complexipy" in by_gate, "the ratchet stage ran (snapshot watermark present)"


def test_every_cf_gate_reaches_the_board_carrying_a_denominator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The denominator of the denominators — asserted through the REAL wire.

    Every other denominator test drives one gate's ``main`` in-process. This one
    is the only place the whole crossing is proven: gate subprocess -> JSON wire
    -> ``_structured_verdict`` parse-back -> the aggregated board. That crossing
    is where the measurement used to be thrown away, so a gate whose wire form
    regressed — or an eighth cf-* stage added without ``measured=`` — would
    otherwise land as a bare ``PASS`` with nothing going red.

    ``_verdict_from_proc`` FABRICATES an empty verdict for a cf-* gate whose
    output it cannot parse (wire shape 3). That fallback is invisible on a green
    board, which is exactly why the assertion is ``notices and evidence`` rather
    than a passed flag: it makes the silent fallback fatal for a kit gate.
    """
    consumer = _consumer_copy(tmp_path)
    _stub_pytest(monkeypatch)

    verdicts = run_battery(consumer, os.environ)
    cf_verdicts = [v for v in verdicts if v.gate.startswith("cf-") and v.error is None]

    assert cf_verdicts, _board(verdicts)  # the gates ran at all — never a vacuous loop
    for verdict in cf_verdicts:
        assert verdict.notices, f"{verdict.gate} reached the board with no denominator"
        assert verdict.evidence, f"{verdict.gate} carries no machine-form measurement"
        assert len(verdict.notices) == 1, f"{verdict.gate}: ONE denominator line, not a blob"


def test_injected_type_error_flips_the_battery_red(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    consumer = _consumer_copy(tmp_path)
    _stub_pytest(monkeypatch)
    # A module-level type error, APPENDED — never written OVER the module. mypy flags
    # it; ruff does not (it is no lint finding, and the value is double-quoted so
    # `ruff format --check` leaves it alone), so the mypy stage is the SOLE failure and
    # the e2e path truly grades. Replacing widget.py would delete the fixture's ONLY
    # function, leaving a source root that is Python-but-functionless: the complexipy
    # stage then correctly refuses for having measured nothing
    # (GATE_COMPLEXIPY_MEASURED_NOTHING — a setup error, exit 2), and the battery goes
    # red for a vacuous complexity grade instead of for the injected type error. Red
    # for the wrong reason is the failure mode this append exists to prevent.
    widget = consumer / "app" / "widget.py"
    widget.write_text(
        widget.read_text(encoding="utf-8") + 'bad: int = "not an int"\n', encoding="utf-8"
    )

    verdicts = run_battery(consumer, os.environ)
    by_gate = {verdict.gate: verdict for verdict in verdicts}

    assert battery_exit_code(verdicts) == 1, _board(verdicts)
    assert not by_gate["mypy"].passed, "mypy-baseline filter must flag the new error over baseline"
    assert by_gate["mypy"].error is None, "a violation (a new error), not a gate setup error"
