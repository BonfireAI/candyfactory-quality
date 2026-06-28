"""Tests for the CI surfaces: the reusable quality gate, the kit's own CI,
the consumer caller stub, and the SHA-pin doctrine.

These tests answer the Law-1 refuter's gaming vectors structurally:

- caller-stub neutering: the reusable workflow defines NO inputs at all,
  self-asserts its trigger context as its FIRST step, and the stub template
  bans ``paths:`` filters and ``continue-on-error`` in writing;
- pin rot: every ``uses:`` reference is a full 40-hex commit SHA;
- incomplete verdicts: the ~11 discrete fail-fast gate steps collapse into a
  SINGLE ``cf-gate`` step that runs every stage and aggregates, so a red run
  reports the whole board (COMPLETE at the CI layer); the per-stage skip/refuse
  semantics now live in ``cf_quality.gate_runner`` (its own test battery).
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

# The exact set of scopes a workflow `permissions:` block may request for the
# automatic GITHUB_TOKEN. `administration` is NOT among them (it is valid only
# for fine-grained PATs / GitHub Apps), so declaring it makes the YAML invalid.
VALID_GITHUB_TOKEN_PERMISSIONS = frozenset(
    {
        "actions",
        "attestations",
        "checks",
        "contents",
        "deployments",
        "discussions",
        "id-token",
        "issues",
        "models",
        "packages",
        "pages",
        "pull-requests",
        "repository-projects",
        "security-events",
        "statuses",
    }
)


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


# recursion: bounded by the finite depth of a yaml.safe_load tree (acyclic by construction)
def _permissions_keys(node: Any) -> set[str]:
    """Union of the keys of every ``permissions:`` mapping anywhere in the tree
    (top-level and per-job). A ``permissions`` value that is a bare string
    (e.g. ``read-all``) contributes no scope keys."""
    keys: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if str(key) == "permissions" and isinstance(value, dict):
                keys.update(str(k) for k in value)
            keys.update(_permissions_keys(value))
    elif isinstance(node, list):
        for item in node:
            keys.update(_permissions_keys(item))
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


def test_gate_runs_one_aggregating_cf_gate_step() -> None:
    # The ~11 fail-fast gate steps collapse into ONE cf-gate step: cf-gate runs
    # every stage, collects one verdict each, and exits on the worst — so a red
    # run reports the WHOLE board, not just the first failure (COMPLETE at CI).
    steps = _steps(_load(GATE_PATH), "gate")
    cf_steps = [s for s in steps if re.search(r"\bcf-gate\b", s.get("run", ""))]
    assert len(cf_steps) == 1, "exactly one aggregating cf-gate step IS the gate"
    # the discrete per-gate commands are no longer separate workflow steps —
    # those verdicts are aggregated inside cf-gate.
    script = _run_script(_load(GATE_PATH), "gate")
    assert "mypy-baseline filter" not in script
    assert "ruff format --check" not in script
    assert "complexipy " not in script


def test_gate_cf_gate_step_tees_board_to_step_summary() -> None:
    # A red CI run must surface every failing gate in the run summary, not bury
    # it in the logs: the cf-gate board is teed into $GITHUB_STEP_SUMMARY.
    cf_run = next(
        s["run"]
        for s in _steps(_load(GATE_PATH), "gate")
        if re.search(r"\bcf-gate\b", s.get("run", ""))
    )
    assert "GITHUB_STEP_SUMMARY" in cf_run, "the aggregated board must reach the step summary"
    assert "tee" in cf_run, "the board is teed so it appears in BOTH the log and the summary"


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


def test_self_ci_gates_through_cf_gate_directly() -> None:
    # The kit submits to its own gate via the INSTALLED cf-gate console script,
    # NOT via quality-gate.yml's workflow_call — so a broken reusable workflow
    # can never self-grade the kit green.
    data = _load(SELF_CI_PATH)
    script = _run_script(data, "gate")
    assert re.search(r"\bcf-gate\b", script), "self-ci must run the aggregating cf-gate"
    assert "pip install -e '.[dev]'" in script, "self-ci installs the kit + [dev] first"
    for job in data["jobs"].values():
        assert "uses" not in job, "self-ci must not delegate its job to a reusable workflow"


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


# --- workflow-altitude doctrine: layout resolution (zero-inputs preserved) ----
#
# The per-gate verdicts (ruff against the kit gauge, mypy through the baseline
# ratchet and its source-root targeting, complexipy, pytest from the package
# dir) moved INTO cf-gate when the ~11 fail-fast steps collapsed into the one
# aggregating step; those semantics now carry their own battery in
# cf_quality.gate_runner. The workflow keeps only the layout resolution it
# still needs at the YAML layer: the consumer package dir, resolved before the
# consumer install so an invalid declaration fails typed before the gate runs.


def test_gate_resolves_declared_layout_before_consumer_install() -> None:
    # Layout comes from COMMITTED consumer state via cf-repo-config — never a
    # caller knob (the inputs block stays empty). The package dir is resolved
    # before the consumer install so an invalid declaration fails typed before
    # anything is graded; cf-gate self-resolves the FULL layout internally.
    script = _run_script(_load(GATE_PATH), "gate")
    resolve_pos = script.find("cf-repo-config package-dir")
    assert resolve_pos >= 0, "the gate must resolve the declared package dir"
    install_pos = script.find("pip install -e")
    assert install_pos > resolve_pos, "layout resolution must precede the consumer install"


def test_gate_consumer_install_rides_declared_package_dir() -> None:
    script = _run_script(_load(GATE_PATH), "gate")
    install_part = script[script.find("pyproject.toml — consumer") - 200 :]
    assert 'cd "$CF_PACKAGE_DIR"' in install_part


def test_gate_self_assert_comment_matches_partial_verdict() -> None:
    # Refuter: the inline comment overclaimed ("refuse it loudly — neutering
    # vector #1") versus DESIGN §4.8's honest PARTIAL.
    text = GATE_PATH.read_text(encoding="utf-8")
    assert "remain procedural" in text, "the self-assert comment must state the PARTIAL residue"


# --- merged-main projection + in-band required-check self-verification --------


def _gate_step(name_substr: str) -> dict[str, Any]:
    for step in _steps(_load(GATE_PATH), "gate"):
        if name_substr in step.get("name", ""):
            return step
    raise AssertionError(f"no gate step named like {name_substr!r}")


def test_consumer_checkout_lands_pr_head_with_full_history() -> None:
    # The battery must grade the PR HEAD (a SHA) merged with CURRENT base — not
    # the default merge ref against a possibly-stale base. fetch-depth:0 gives
    # the merge a real merge-base.
    co = _gate_step("Checkout consumer repo")
    assert str(co["with"]["fetch-depth"]) == "0"
    assert "pull_request.head.sha" in co["with"]["ref"]


def test_gate_projects_merged_main_state_on_pull_request() -> None:
    step = _gate_step("Project the merged-main state")
    assert step["if"] == "github.event_name == 'pull_request'"
    run = step["run"]
    assert "git merge" in run and "FETCH_HEAD" in run
    assert "exit 1" in run, "an unmergeable PR is refused, not silently passed"
    assert "BASE_REF" in step["env"], "base ref is read from env, never interpolated into the shell"


def test_gate_self_verifies_required_mount_in_band() -> None:
    # The Elegance e2e: the gate refuses to pass unless it can confirm it is a
    # required, non-bypassable check — reusing the audit script (DRY).
    canary = [
        s for s in _steps(_load(GATE_PATH), "gate") if "check-required-mount.sh" in s.get("run", "")
    ]
    assert len(canary) == 1, "exactly one in-band mount canary"
    assert "exit 1" in canary[0]["run"]
    assert canary[0]["env"]["GH_TOKEN"], "the canary needs a token to read protection"


def _mount_canary() -> dict[str, Any]:
    canary = [
        s for s in _steps(_load(GATE_PATH), "gate") if "check-required-mount.sh" in s.get("run", "")
    ]
    assert len(canary) == 1, "exactly one in-band mount canary"
    return canary[0]


def test_mount_canary_reads_optional_ci_kit_token() -> None:
    # The canary reads branch protection (Administration:read) via an OPTIONAL
    # CI_KIT_TOKEN secret, falling back to the automatic token for the API host;
    # KIT_TOKEN carries the secret alone so the run can test its presence.
    env = _mount_canary()["env"]
    gh_token = env["GH_TOKEN"]
    assert "CI_KIT_TOKEN" in gh_token and "github.token" in gh_token
    assert "secrets.CI_KIT_TOKEN" in env["KIT_TOKEN"]


def test_mount_canary_degrades_without_admin_token() -> None:
    # No admin token → skip-with-warning (degrade, never brick); token present →
    # the strict proof reuses check-required-mount.sh and refuses on failure.
    run = _mount_canary()["run"]
    assert "::warning::" in run and '-z "$KIT_TOKEN"' in run
    assert "check-required-mount.sh" in run and "exit 1" in run


def test_gate_permissions_only_grant_valid_github_token_scopes() -> None:
    # `administration` is not a grantable GITHUB_TOKEN scope; declaring it makes
    # the workflow YAML invalid and the gate job dies at 0s without a status
    # check. The gate's top-level permissions must stay within the valid set.
    perms = _load(GATE_PATH).get("permissions")
    assert isinstance(perms, dict)
    keys = {str(k) for k in perms}
    invalid = keys - VALID_GITHUB_TOKEN_PERMISSIONS
    assert not invalid, f"non-grantable scope(s): {invalid}"
    assert "administration" not in keys


def test_still_exactly_one_aggregating_cf_gate_step_after_additions() -> None:
    # The new projection + canary steps must NOT read as a second battery step.
    steps = _steps(_load(GATE_PATH), "gate")
    cf_steps = [s for s in steps if re.search(r"\bcf-gate\b", s.get("run", ""))]
    assert len(cf_steps) == 1


# --- caller stub + the apply/audit mount scripts -----------------------------


def test_caller_permissions_only_grant_valid_github_token_scopes() -> None:
    gate = _load(TEMPLATE_PATH)["jobs"]["gate"]
    keys = {str(k) for k in gate["permissions"]}
    invalid = keys - VALID_GITHUB_TOKEN_PERMISSIONS
    assert not invalid, f"non-grantable scope(s): {invalid}"
    assert "administration" not in keys


def test_no_workflow_declares_administration_token_scope() -> None:
    # Regression guard: `administration` is not a grantable GITHUB_TOKEN scope, so
    # it must appear in NO permissions mapping (top-level or per-job) of any of
    # our workflow surfaces. This FAILS on the pre-fix files and PASSES after.
    for path in (GATE_PATH, SELF_CI_PATH, TEMPLATE_PATH):
        keys = _permissions_keys(_load(path))
        assert "administration" not in keys, f"{path.name} declares non-grantable 'administration'"


def test_mount_apply_script_present_and_proves_via_audit() -> None:
    apply = REPO / "templates" / "mount-required.sh"
    assert apply.is_file(), "the apply-side mount script must ship beside the audit"
    text = apply.read_text(encoding="utf-8")
    assert "branches/${branch}/protection" in text, "the first mount is a full PUT of protection"
    assert "enforce_admins" in text and "true" in text, "the mount must be non-bypassable"
    assert "check-required-mount.sh" in text, "the apply script proves the mount via the audit"
