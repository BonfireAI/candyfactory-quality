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

# The tests-context battery — rules test code legitimately trips, measured
# estate-wide 2026-06-10: S101 pytest's assert · S105/S106 fake credentials ·
# S603/S607 subprocess runs of the repo's own CLI · S608 fixture SQL strings ·
# B017 broad pytest.raises. Src keeps the full battery.
TESTS_CONTEXT_BATTERY = {"S101", "S105", "S106", "S603", "S607", "S608", "B017"}

# The glob set must actually cover test trees: root and nested, files at any
# depth under tests/, and conftest.py wherever it lives.
TESTS_CONTEXT_GLOBS = ("tests/*", "tests/**", "**/tests/*", "**/tests/**", "**/conftest.py")

# The comment anchoring the carve-out to its measurement, verbatim in both
# the shipped gauge and the kit's own mirror of it.
TESTS_CONTEXT_ANCHOR = (
    "tests-context battery, measured estate-wide 2026-06-10; src keeps the full battery"
)


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


def test_ruff_base_test_ignores_cover_nested_layouts() -> None:
    # Mount-wave regression: 'tests/*' matches only repo-root tests — a
    # server/-rooted monorepo consumer (server/tests) drew 845 false S101. The doubled glob
    # '**/tests/*' covers nested layouts; the root form stays, harmless.
    ignores = _load_toml("ruff-base.toml")["lint"]["per-file-ignores"]
    assert "S101" in ignores["**/tests/*"], "nested tests/ dirs must carry the S101 carve-out"
    assert "S101" in ignores["tests/*"], "the root-level form stays alongside the doubled glob"


def test_ruff_base_tests_carve_out_pins_the_measured_battery() -> None:
    # Estate-wide CI measurement (2026-06-10): the gauge's ruff step failed
    # largely on security hits in TEST code — fake creds, subprocess on the
    # repo's own CLI, fixture SQL, broad pytest.raises. The refuter doctrine:
    # FP noise trains agents to ignore the gate, so the tests context carves
    # out the measured battery EXACTLY — no more, no less.
    ignores = _load_toml("ruff-base.toml")["lint"]["per-file-ignores"]
    for glob in TESTS_CONTEXT_GLOBS:
        assert glob in ignores, f"tests-context glob missing from ruff-base.toml: {glob}"
        assert set(ignores[glob]) == TESTS_CONTEXT_BATTERY, f"battery drift at {glob}"
    assert set(ignores) == set(TESTS_CONTEXT_GLOBS), "no carve-out globs beyond the tests context"


def test_kit_own_ruff_config_test_ignores_cover_nested_layouts() -> None:
    # The kit mirrors the gauge it ships (it submits before it preaches).
    pyproject = _load_toml("../pyproject.toml")
    ignores = pyproject["tool"]["ruff"]["lint"]["per-file-ignores"]
    assert "S101" in ignores["**/tests/*"]
    assert "S101" in ignores["tests/*"]


def test_kit_own_ruff_config_mirrors_the_tests_carve_out_battery() -> None:
    # Same pin against the kit's own pyproject mirror — gauge and mirror may
    # never drift on the carve-out (declared-mirror discipline).
    pyproject = _load_toml("../pyproject.toml")
    ignores = pyproject["tool"]["ruff"]["lint"]["per-file-ignores"]
    for glob in TESTS_CONTEXT_GLOBS:
        assert glob in ignores, f"tests-context glob missing from pyproject mirror: {glob}"
        assert set(ignores[glob]) == TESTS_CONTEXT_BATTERY, f"battery drift at {glob}"


def test_tests_carve_out_comment_anchors_the_measurement() -> None:
    # The carve-out carries its measurement anchor verbatim in both surfaces —
    # a budget without its measurement is a vibe (BubbleGum doctrine).
    base = (CONFIGS_DIR / "ruff-base.toml").read_text(encoding="utf-8")
    mirror = (CONFIGS_DIR.parent / "pyproject.toml").read_text(encoding="utf-8")
    assert TESTS_CONTEXT_ANCHOR in base
    assert TESTS_CONTEXT_ANCHOR in mirror


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
    # 2026-07-28: this line used to pin the substring "does NOT auto-shrink",
    # which is FALSE for the pinned complexipy 5.6.0 — a PASSING compare calls
    # create_snapshot_file on handle_snapshot_watermark's no-violation branch and
    # was observed rewriting a populated snapshot to []. The assertion was
    # therefore gating a false sentence into the document. It is replaced, not
    # softened: where one substring pinned one (wrong) claim, four now pin the
    # whole corrected contract — the measured write behaviour, its evidence, the
    # write-free measurement that disarms it, and the operator duty that survived
    # it. Delete any one of those teachings from the doc and this test fails.
    assert "A passing plain-run compare REWRITES the snapshot" in text  # measured on 5.6.0
    assert "handle_snapshot_watermark" in text  # the destructive call site, named
    assert "--snapshot-ignore" in text  # the write-free measurement the gate mounts
    assert "The re-snapshot duty is still yours" in text  # the surviving shrink duty


def test_baseline_conventions_teaches_the_config_that_can_defeat_the_gate() -> None:
    # 2026-07-28, second correction: `--snapshot-ignore` alone does NOT make the run
    # write-free. `snapshot-create` is a separate branch resolved CLI-first/TOML-
    # second with no negating flag, so a consumer's own complexipy config could put
    # the rewrite back while the gate graded pre-write bytes. A consumer cannot
    # comply with a refusal they were never told about, so the mount doc must carry
    # the key list, the refusal, and the two options that ARE honoured.
    text = (CONFIGS_DIR / "BASELINE-CONVENTIONS.md").read_text(encoding="utf-8")
    assert "GATE_COMPLEXIPY_CONFIG_DEFEATS_MEASUREMENT" in text
    assert "snapshot-create" in text and "ignore-complexity" in text and "output-format" in text
    assert "max-complexity-allowed" in text, "the threshold the kit deliberately honours"
    assert "GATE_COMPLEXIPY_THRESHOLD_RAISED" in text, "raising the bar refuses, not passes"
    assert "GATE_COMPLEXIPY_INSTRUMENT_FAILED" in text, "a tool failure is not the repo's"


def test_baseline_conventions_cannot_reacquire_the_false_unmeasured_claim() -> None:
    # A doc fix pass on this branch asserted that "an improvement that empties a floor
    # file of functions … FAILS (COMPLEXIPY_SNAPSHOT_FILE_UNMEASURED)". That is FALSE:
    # `--plain` without `--failed` lists every measured function regardless of
    # threshold (complexipy/utils/output.py:234,243), so such a file stays in
    # census.files and the gate is GREEN. UNMEASURED fires when the file was not
    # MEASURED; the per-FUNCTION code is what catches a single lost function. This rod
    # bites in both directions: the true rule must be stated, and the false phrasing
    # must not come back.
    for name in ("BASELINE-CONVENTIONS.md",):
        text = (CONFIGS_DIR / name).read_text(encoding="utf-8")
        assert "empties a floor file of functions" not in text, f"{name}: the false claim is back"
        assert "COMPLEXIPY_SNAPSHOT_FUNCTION_UNMEASURED" in text, "the per-function rule"
        assert "was not **measured** at all" in text, "the true trigger, spelled out"


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
