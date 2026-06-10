"""Tests for the CI surfaces: the reusable quality gate, the kit's own CI,
the consumer caller stub, and the SHA-pin doctrine.

These tests answer the Law-1 refuter's gaming vectors structurally:

- caller-stub neutering: the reusable workflow defines NO inputs at all,
  self-asserts its trigger context as its FIRST step, and the stub template
  bans ``paths:`` filters and ``continue-on-error`` in writing;
- pin rot: every ``uses:`` reference is a full 40-hex commit SHA;
- silent skips: the two conditional steps (mirror check, mypy baseline)
  must emit a VISIBLE notice when they skip, never pass quietly.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parent.parent
GATE_PATH = REPO / ".github" / "workflows" / "quality-gate.yml"
SELF_CI_PATH = REPO / ".github" / "workflows" / "self-ci.yml"
TEMPLATE_PATH = REPO / "templates" / "quality.caller.yml"
DOCTRINE_PATH = REPO / "docs" / "sha-pin-doctrine.md"

SHA_PINNED = re.compile(r"@[0-9a-f]{40}$")


def _load(path: Path) -> dict[Any, Any]:
    # dict[Any, Any]: YAML 1.1 parses the bare trigger key ``on`` as the
    # boolean True, so workflow mappings are genuinely not str-keyed.
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"{path.name} did not parse to a mapping"
    return data


def _triggers(data: dict[Any, Any]) -> dict[str, Any]:
    # YAML 1.1 parses the bare key `on` as boolean True.
    raw = data.get("on", data.get(True))
    assert isinstance(raw, dict), "workflow has no trigger mapping"
    return raw


def _steps(data: dict[str, Any], job: str) -> list[dict[str, Any]]:
    steps = data["jobs"][job]["steps"]
    assert isinstance(steps, list) and steps
    return steps


def _run_script(data: dict[str, Any], job: str) -> str:
    """All run scripts of a job, concatenated in step order."""
    return "\n".join(step.get("run", "") for step in _steps(data, job))


# recursion: bounded by the finite depth of a yaml.safe_load tree (acyclic by construction)
def _walk_keys(node: Any) -> list[str]:
    keys: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            keys.append(str(key))
            keys.extend(_walk_keys(value))
    elif isinstance(node, list):
        for item in node:
            keys.extend(_walk_keys(item))
    return keys


def _uses_refs(data: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for job in data["jobs"].values():
        if "uses" in job:
            refs.append(job["uses"])
        for step in job.get("steps", []):
            if "uses" in step:
                refs.append(step["uses"])
    return refs


# --- quality-gate.yml (the reusable gate) -----------------------------------


def test_gate_parses_as_yaml() -> None:
    _load(GATE_PATH)


def test_gate_is_workflow_call_only_with_no_inputs() -> None:
    triggers = _triggers(_load(GATE_PATH))
    assert list(triggers) == ["workflow_call"], "gate must be reusable-only"
    call = triggers["workflow_call"]
    assert call in (None, {}), "workflow_call must define NO inputs (anti-neutering)"


def test_gate_documents_why_inputs_are_absent() -> None:
    text = GATE_PATH.read_text(encoding="utf-8")
    assert "NO inputs" in text, "absence of inputs must be documented as deliberate"


def test_gate_has_no_continue_on_error_or_paths_filter() -> None:
    data = _load(GATE_PATH)
    keys = _walk_keys(data)
    assert "continue-on-error" not in keys
    assert "paths" not in keys and "paths-ignore" not in keys


def test_gate_first_step_self_asserts_trigger_context() -> None:
    first = _steps(_load(GATE_PATH), "gate")[0]
    script = first.get("run", "")
    assert "github.event_name" in str(first), "first step must read the trigger event"
    assert "exit 1" in script, "first step must fail loudly on a foreign trigger"
    assert "push" in script and "pull_request" in script


def test_gate_checks_out_kit_at_calling_sha_into_cf_quality() -> None:
    steps = _steps(_load(GATE_PATH), "gate")
    kit_steps = [
        s for s in steps if s.get("with", {}).get("repository") == "BonfireAI/candyfactory-quality"
    ]
    assert len(kit_steps) == 1, "exactly one kit checkout"
    with_block = kit_steps[0]["with"]
    assert with_block["path"] == ".cf-quality"
    assert "github.job_workflow_sha" in with_block["ref"], "kit must ride the calling SHA"
    assert "token" in with_block


def test_gate_documents_private_repo_access_assumption() -> None:
    text = GATE_PATH.read_text(encoding="utf-8")
    assert "private-repo access assumption" in text


def test_gate_uses_python_312() -> None:
    steps = _steps(_load(GATE_PATH), "gate")
    setup = [s for s in steps if "setup-python" in s.get("uses", "")]
    assert len(setup) == 1
    assert str(setup[0]["with"]["python-version"]) == "3.12"


def test_gate_installs_kit_with_tool_battery() -> None:
    script = _run_script(_load(GATE_PATH), "gate")
    assert ".cf-quality[dev]" in script, "gate must install the kit's pinned tool battery"


def test_gate_runs_full_battery_in_order() -> None:
    script = _run_script(_load(GATE_PATH), "gate")
    battery = [
        "ruff check",
        "ruff format --check",
        "cf-sticky-check check",
        "cf-file-budget check",
        "cf-mirror-check",
        "cf-recursion-check",
        "cf-exemptions",
        "mypy-baseline filter",
        "pytest",
    ]
    positions = [script.find(cmd) for cmd in battery]
    missing = [cmd for cmd, pos in zip(battery, positions, strict=True) if pos < 0]
    assert not missing, f"battery commands missing from gate: {missing}"
    assert positions == sorted(positions), "battery must run in the declared order"


def test_gate_mirror_step_skips_visibly_without_mirrors_md() -> None:
    script = _run_script(_load(GATE_PATH), "gate")
    assert "MIRRORS.md" in script
    mirror_part = script[script.find("MIRRORS.md") :]
    assert "::notice::" in mirror_part, "mirror skip must be a visible notice, never silent"


def test_gate_mypy_step_skips_visibly_without_baseline() -> None:
    script = _run_script(_load(GATE_PATH), "gate")
    assert "mypy-baseline.txt" in script
    mypy_part = script[script.find("mypy-baseline.txt") :]
    assert "::notice::" in mypy_part, "baseline skip must be a visible notice, never silent"


def test_gate_action_uses_are_full_sha_pinned() -> None:
    for ref in _uses_refs(_load(GATE_PATH)):
        assert SHA_PINNED.search(ref), f"unpinned uses ref: {ref}"


# --- self-ci.yml (the kit's own CI) -----------------------------------------


def test_self_ci_parses_and_triggers_on_push_and_pr() -> None:
    triggers = _triggers(_load(SELF_CI_PATH))
    assert "push" in triggers and "pull_request" in triggers


def test_self_ci_has_no_continue_on_error_or_paths_filter() -> None:
    keys = _walk_keys(_load(SELF_CI_PATH))
    assert "continue-on-error" not in keys
    assert "paths" not in keys and "paths-ignore" not in keys


def test_self_ci_runs_the_same_battery_on_itself() -> None:
    script = _run_script(_load(SELF_CI_PATH), "gate")
    for cmd in (
        "ruff check",
        "ruff format --check",
        "cf-sticky-check check",
        "cf-file-budget check",
        "cf-mirror-check",
        "cf-recursion-check",
        "cf-exemptions",
        "mypy",
        "pytest",
    ):
        assert cmd in script, f"self-ci missing battery command: {cmd}"


def test_self_ci_action_uses_are_full_sha_pinned() -> None:
    for ref in _uses_refs(_load(SELF_CI_PATH)):
        assert SHA_PINNED.search(ref), f"unpinned uses ref: {ref}"


def test_self_ci_uses_python_312() -> None:
    steps = _steps(_load(SELF_CI_PATH), "gate")
    setup = [s for s in steps if "setup-python" in s.get("uses", "")]
    assert len(setup) == 1
    assert str(setup[0]["with"]["python-version"]) == "3.12"


# --- templates/quality.caller.yml (the consumer stub) ------------------------


def test_caller_template_parses_and_triggers_on_push_and_pr() -> None:
    triggers = _triggers(_load(TEMPLATE_PATH))
    assert "push" in triggers and "pull_request" in triggers


def test_caller_template_has_no_neutering_keys() -> None:
    keys = _walk_keys(_load(TEMPLATE_PATH))
    assert "continue-on-error" not in keys
    assert "paths" not in keys and "paths-ignore" not in keys


def test_caller_template_calls_gate_with_full_sha_placeholder() -> None:
    data = _load(TEMPLATE_PATH)
    gate = data["jobs"]["gate"]
    uses = gate["uses"]
    prefix, _, ref = uses.partition("@")
    assert prefix == "BonfireAI/candyfactory-quality/.github/workflows/quality-gate.yml"
    assert len(ref) == 40, "placeholder ref must be full-SHA shaped (40 chars)"
    assert gate.get("secrets") == "inherit"


def test_caller_template_documents_structural_constraints() -> None:
    text = TEMPLATE_PATH.read_text(encoding="utf-8")
    for phrase in ("paths", "continue-on-error", "skip", "REQUIRED status check"):
        assert phrase in text, f"constraint comment missing: {phrase}"


def test_caller_template_stays_near_ten_lines() -> None:
    lines = TEMPLATE_PATH.read_text(encoding="utf-8").splitlines()
    code_lines = [ln for ln in lines if ln.strip() and not ln.lstrip().startswith("#")]
    assert len(code_lines) <= 12, "the caller stub must stay a ~10-line surface"


# --- docs/sha-pin-doctrine.md -------------------------------------------------


def test_sha_pin_doctrine_is_ten_lines_and_names_the_mechanisms() -> None:
    text = DOCTRINE_PATH.read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert len(lines) <= 10, "the doctrine is a 10-line document"
    assert "Dependabot" in text
    assert "40-hex" in text or "full commit SHA" in text
