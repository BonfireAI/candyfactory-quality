"""Tests for the shared gate configs in ``configs/``.

Each config must parse with stdlib tooling (tomllib / json) and carry the
ratified BubbleGum budgets: CC <= 10, <= 50 statements, line-length 100,
py312, strict-leaning mypy, jscpd minTokens 35 (src) / 70 (tests).
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any

CONFIGS_DIR = Path(__file__).resolve().parent.parent / "configs"


def _load_toml(name: str) -> dict[str, Any]:
    return tomllib.loads((CONFIGS_DIR / name).read_text(encoding="utf-8"))


def _load_json(name: str) -> dict[str, Any]:
    data = json.loads((CONFIGS_DIR / name).read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


# --- ruff-base.toml ---------------------------------------------------------


def test_ruff_base_parses_as_toml() -> None:
    data = _load_toml("ruff-base.toml")
    assert isinstance(data, dict)


def test_ruff_base_carries_ratified_budgets() -> None:
    data = _load_toml("ruff-base.toml")
    assert data["line-length"] == 100
    assert data["target-version"] == "py312"
    assert data["lint"]["mccabe"]["max-complexity"] == 10
    assert data["lint"]["pylint"]["max-statements"] == 50


def test_ruff_base_selects_the_gate_rule_battery() -> None:
    select = _load_toml("ruff-base.toml")["lint"]["select"]
    for rule in ("C901", "PLR0915", "S", "BLE"):
        assert rule in select, f"missing rule family: {rule}"


def test_ruff_base_header_declares_vendoring_and_sync_allowlist() -> None:
    text = (CONFIGS_DIR / "ruff-base.toml").read_text(encoding="utf-8")
    assert "vendored per consumer repo" in text
    assert "drift caught by ruff-sync check" in text
    assert "[tool.ruff-sync].exclude allowlist: lint.per-file-ignores ONLY" in text


# --- mypy-base.toml ---------------------------------------------------------


def test_mypy_base_parses_as_toml() -> None:
    data = _load_toml("mypy-base.toml")
    assert isinstance(data, dict)


def test_mypy_base_carries_strict_leaning_profile() -> None:
    mypy = _load_toml("mypy-base.toml")["tool"]["mypy"]
    assert mypy["check_untyped_defs"] is True
    assert mypy["disallow_untyped_defs"] is True
    assert mypy["warn_unused_ignores"] is True
    assert mypy["warn_redundant_casts"] is True


def test_mypy_base_documents_per_module_grace_pattern() -> None:
    text = (CONFIGS_DIR / "mypy-base.toml").read_text(encoding="utf-8")
    assert "[[tool.mypy.overrides]]" in text
    assert "per-module grace" in text


# --- jscpd two-profile carve-out --------------------------------------------


def test_jscpd_src_profile_min_tokens_35() -> None:
    assert _load_json("jscpd.src.json")["minTokens"] == 35


def test_jscpd_tests_profile_min_tokens_70() -> None:
    assert _load_json("jscpd.tests.json")["minTokens"] == 70


def test_jscpd_profiles_are_two_files_because_one_cannot_carry_two_min_tokens() -> None:
    src = _load_json("jscpd.src.json")
    tests = _load_json("jscpd.tests.json")
    assert src["minTokens"] != tests["minTokens"]


# --- BASELINE-CONVENTIONS.md -------------------------------------------------


def test_baseline_conventions_documents_observed_workflows() -> None:
    text = (CONFIGS_DIR / "BASELINE-CONVENTIONS.md").read_text(encoding="utf-8")
    assert "--snapshot-create" in text  # complexipy watermark boot
    assert "mypy-baseline sync" in text  # type-debt baseline boot
    assert "mypy-baseline filter" in text  # CI-side set-difference gate
    assert "does NOT auto-shrink" in text  # the complexipy re-snapshot duty


def test_ruff_base_gates_blanket_and_unused_noqa() -> None:
    # Refuter: a codeless blanket noqa suppressed C901 with no backstop.
    # PGH004 fails blanket noqa at lint altitude; RUF100 fails unused ones.
    select = _load_toml("ruff-base.toml")["lint"]["select"]
    assert "PGH004" in select, "blanket-noqa must fail at lint altitude"
    assert "RUF100" in select, "unused noqa must fail at lint altitude"


def test_kit_own_ruff_config_gates_blanket_and_unused_noqa() -> None:
    import tomllib

    pyproject = tomllib.loads((CONFIGS_DIR.parent / "pyproject.toml").read_text(encoding="utf-8"))
    select = pyproject["tool"]["ruff"]["lint"]["select"]
    assert "PGH004" in select and "RUF100" in select
