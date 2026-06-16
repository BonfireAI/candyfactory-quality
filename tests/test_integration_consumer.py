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


def test_injected_type_error_flips_the_battery_red(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    consumer = _consumer_copy(tmp_path)
    _stub_pytest(monkeypatch)
    # A module-level type error: mypy flags it, ruff does not (it is not a lint
    # finding), so the mypy stage is the SOLE failure — the e2e path truly grades.
    (consumer / "app" / "widget.py").write_text("bad: int = 'not an int'\n", encoding="utf-8")

    verdicts = run_battery(consumer, os.environ)
    by_gate = {verdict.gate: verdict for verdict in verdicts}

    assert battery_exit_code(verdicts) == 1, _board(verdicts)
    assert not by_gate["mypy"].passed, "mypy-baseline filter must flag the new error over baseline"
    assert by_gate["mypy"].error is None, "a violation (a new error), not a gate setup error"
