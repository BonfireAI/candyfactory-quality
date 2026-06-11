"""The 2026-06-11 gate-hardening contract — four measured kit/CI defects.

Split from ``test_workflows.py`` by design (the file budget measures, review
judges): this file carries one coherent unit — the overnight-burn defects and
their control rods.

1. **Kit-pin honor** — ``github.job_workflow_sha`` observed EMPTY at run
   time; the kit checkout floated to main and consumers were gauged by an
   unpinned gauge. Functional rod: the step's script runs against a real git
   fixture and MUST re-anchor a floating checkout to the committed pin.
2. **Node-24 action pins** — GitHub forces Node 24 from 2026-06-16; the
   deprecated Node-20 SHAs are denylisted (ratchet: forward bumps free,
   rollback refused).
3. **complexipy joins the gate** — the watermark was runbook-only; now a
   workflow step with the mypy-style presence rule.
4. **first-party isort alignment** — the gate derives known-first-party from
   the consumer's resolved source root and feeds it to the pinned ruff gauge.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from test_workflows import (
    GATE_PATH,
    REPO,
    SELF_CI_PATH,
    _load,
    _run_script,
    _steps,
    _uses_refs,
)

# --- the kit-pin honor step (gauges floated to kit MAIN) -----------------------
#
# Observed defect: `github.job_workflow_sha` is DOCUMENTED as the reusable
# workflow's commit but evaluated EMPTY at run time, so the kit checkout
# received no `ref:` and actions/checkout fell back to the default branch
# (`git checkout -B main refs/remotes/origin/main`) — consumers pinned to a
# SHA were gauged by whatever kit MAIN carried (irreproducible counts, twice
# observed in one night). The pin of record is the one the consumer COMMITS
# in its caller stub; the gate re-anchors to it and REFUSES to float.


def _pin_honor_step() -> dict[str, Any]:
    steps = _steps(_load(GATE_PATH), "gate")
    matches = [s for s in steps if "declared kit pin" in s.get("name", "")]
    assert len(matches) == 1, "exactly one pin-honor step"
    return matches[0]


def test_gate_pin_honor_step_sits_between_kit_checkout_and_install() -> None:
    steps = _steps(_load(GATE_PATH), "gate")
    names = [s.get("name", "") for s in steps]
    checkout_idx = next(i for i, s in enumerate(steps) if "gauge kit" in s.get("name", ""))
    honor_idx = next(i for i, n in enumerate(names) if "declared kit pin" in n)
    install_idx = next(i for i, n in enumerate(names) if "Install the gauge kit" in n)
    assert checkout_idx < honor_idx < install_idx, (
        "the pin must be honored after the kit checkout and BEFORE the kit install — "
        "installing a floating kit and re-pinning afterwards would gauge with main's scripts"
    )


def test_gate_pin_honor_refuses_to_float_and_fails_safe() -> None:
    script = _pin_honor_step().get("run", "")
    assert "git fetch" in script and "git checkout" in script, "the step must re-anchor by SHA"
    assert script.count("exit 1") >= 2, "no-pin and multi-pin must both refuse (fail-safe)"
    assert "::error::" in script, "refusal must be loud"
    assert "JOB_WORKFLOW_SHA" in script, "the unreliable context value is named in the verdict"


def _run_pin_honor(
    workspace: Path, kit_dir: Path, job_workflow_sha: str = ""
) -> subprocess.CompletedProcess[str]:
    """Execute the pin-honor step's script exactly as the runner would."""
    script = _pin_honor_step()["run"]
    return subprocess.run(
        ["bash", "-e", "-c", script],
        cwd=kit_dir,
        env={
            "PATH": "/usr/bin:/bin",
            "GITHUB_WORKSPACE": str(workspace),
            "JOB_WORKFLOW_SHA": job_workflow_sha,
        },
        capture_output=True,
        text=True,
        check=False,
    )


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


def _pin_fixture(tmp_path: Path) -> tuple[Path, Path, str, str]:
    """A kit origin with two commits, a workspace whose kit checkout sits at
    main (the observed empty-job_workflow_sha fallback), and a consumer stub.

    Returns (workspace, kit_checkout, pinned_sha, main_sha).
    """
    origin = tmp_path / "kit-origin"
    origin.mkdir()
    _git(origin, "init", "-q", "-b", "main")
    (origin / "VERSION").write_text("pinned\n", encoding="utf-8")
    _git(origin, "add", "VERSION")
    _git(origin, "commit", "-q", "-m", "the pinned commit")
    pinned_sha = _git(origin, "rev-parse", "HEAD")
    (origin / "VERSION").write_text("main moved on\n", encoding="utf-8")
    _git(origin, "add", "VERSION")
    _git(origin, "commit", "-q", "-m", "main moved on")
    main_sha = _git(origin, "rev-parse", "HEAD")

    workspace = tmp_path / "ws"
    workspace.mkdir()
    _git(workspace, "clone", "-q", str(origin), str(workspace / ".cf-quality"))
    stub_dir = workspace / "repo" / ".github" / "workflows"
    stub_dir.mkdir(parents=True)
    (stub_dir / "quality.yml").write_text(
        "jobs:\n  gate:\n    uses: BonfireAI/candyfactory-quality"
        f"/.github/workflows/quality-gate.yml@{pinned_sha}\n",
        encoding="utf-8",
    )
    return workspace, workspace / ".cf-quality", pinned_sha, main_sha


def test_pin_honor_reanchors_floating_checkout_to_the_declared_pin(tmp_path: Path) -> None:
    # The control rod: kit checkout at main, consumer pins an older SHA —
    # the step MUST move the checkout to the pin (today's defect gauged main).
    workspace, kit_dir, pinned_sha, main_sha = _pin_fixture(tmp_path)
    assert _git(kit_dir, "rev-parse", "HEAD") == main_sha  # the observed fallback
    proc = _run_pin_honor(workspace, kit_dir)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert _git(kit_dir, "rev-parse", "HEAD") == pinned_sha
    assert pinned_sha in proc.stdout


def test_pin_honor_is_a_noop_when_already_at_the_pin(tmp_path: Path) -> None:
    workspace, kit_dir, pinned_sha, _ = _pin_fixture(tmp_path)
    _git(kit_dir, "checkout", "-q", "--detach", pinned_sha)
    proc = _run_pin_honor(workspace, kit_dir, job_workflow_sha=pinned_sha)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert _git(kit_dir, "rev-parse", "HEAD") == pinned_sha


def test_pin_honor_refuses_when_no_pin_is_committed(tmp_path: Path) -> None:
    # Fail-safe, never float: no parseable caller pin + unreliable context
    # value means the gate cannot know which gauge it is — refuse loudly.
    workspace, kit_dir, _, _ = _pin_fixture(tmp_path)
    (workspace / "repo" / ".github" / "workflows" / "quality.yml").unlink()
    proc = _run_pin_honor(workspace, kit_dir)
    assert proc.returncode == 1
    assert "refused" in proc.stdout


def test_pin_honor_refuses_two_distinct_pins(tmp_path: Path) -> None:
    workspace, kit_dir, _, main_sha = _pin_fixture(tmp_path)
    extra = workspace / "repo" / ".github" / "workflows" / "second.yml"
    extra.write_text(
        "jobs:\n  gate:\n    uses: BonfireAI/candyfactory-quality"
        f"/.github/workflows/quality-gate.yml@{main_sha}\n",
        encoding="utf-8",
    )
    proc = _run_pin_honor(workspace, kit_dir)
    assert proc.returncode == 1
    assert "refused" in proc.stdout


def test_pin_honor_accepts_job_workflow_sha_when_it_matches_head(tmp_path: Path) -> None:
    # When GitHub DOES populate the context value and the checkout already
    # rides it, a consumer with no parseable stub (e.g. a fork of the caller
    # shape) is still deterministic — no refusal needed.
    workspace, kit_dir, pinned_sha, _ = _pin_fixture(tmp_path)
    (workspace / "repo" / ".github" / "workflows" / "quality.yml").unlink()
    _git(kit_dir, "checkout", "-q", "--detach", pinned_sha)
    proc = _run_pin_honor(workspace, kit_dir, job_workflow_sha=pinned_sha)
    assert proc.returncode == 0, proc.stderr + proc.stdout


# --- Node-24 action pins (GitHub forces Node 24 on 2026-06-16) -----------------
#
# The deprecated Node-20 SHAs are denylisted (ratchet style — Dependabot may
# bump FORWARD freely; the gate refuses a roll BACK to the deprecated runtime).
# Observed: notioncrm run 27370755155's deprecation annotation named both.

_NODE20_DEPRECATED_SHAS = {
    "11bd71901bbe5b1630ceea73d27597364c9af683",  # actions/checkout v4.2.2 (node20)
    "0b93645e9fea7318ecaed2b359559ac225c90a2b",  # actions/setup-python v5.3.0 (node20)
}


def test_workflows_carry_no_deprecated_node20_action_pins() -> None:
    for path in (GATE_PATH, SELF_CI_PATH):
        for ref in _uses_refs(_load(path)):
            sha = ref.rpartition("@")[2]
            assert sha not in _NODE20_DEPRECATED_SHAS, (
                f"{path.name} pins {ref} — a Node-20 action; GitHub forces Node 24 "
                "from 2026-06-16 (bump to the Node-24 release of the same action)"
            )


# --- complexipy joins the gate (the watermark was runbook-only) -----------------


def test_gate_complexipy_refuses_python_repo_without_snapshot() -> None:
    # Same doctrine as the mypy baseline: green-by-file-absence is opt-in
    # gaming. A Python repo must carry its snapshot; only a Python-free repo
    # may skip, visibly.
    script = _run_script(_load(GATE_PATH), "gate")
    part = script[script.find("complexipy-snapshot.json") :]
    assert "::error::" in part, "a Python repo without a snapshot must fail loudly"
    assert "exit 1" in part
    assert "::notice::" in part, "the Python-free skip stays visible"


def test_gate_complexipy_targets_resolved_source_root_unpiped() -> None:
    steps = _steps(_load(GATE_PATH), "gate")
    complexipy_steps = [s for s in steps if "complexipy" in s.get("name", "")]
    assert len(complexipy_steps) == 1
    run = complexipy_steps[0]["run"]
    assert 'complexipy "$CF_SOURCE_ROOT"' in run
    for line in run.splitlines():
        if "complexipy" in line and "snapshot" not in line:
            assert "|" not in line, "piping complexipy masks its exit code (tool spike)"


def test_self_ci_runs_complexipy_against_committed_snapshot() -> None:
    script = _run_script(_load(SELF_CI_PATH), "gate")
    assert "complexipy src" in script, "the kit ratchets FIRST — its own watermark is gated"
    assert (REPO / "complexipy-snapshot.json").is_file(), (
        "the kit's own complexipy snapshot must be committed (boot per BASELINE-CONVENTIONS)"
    )


# --- first-party isort alignment (the I001 cross-config conflict) ---------------


def test_gate_resolves_first_party_names_for_the_ruff_gauge() -> None:
    script = _run_script(_load(GATE_PATH), "gate")
    assert "cf-repo-config first-party" in script, "the gate derives first-party names"
    assert "CF_FIRST_PARTY" in script


def test_gate_ruff_check_rides_derived_known_first_party() -> None:
    steps = _steps(_load(GATE_PATH), "gate")
    check_steps = [s for s in steps if s.get("run", "").startswith("ruff check")]
    assert len(check_steps) == 1
    assert "lint.isort.known-first-party=$CF_FIRST_PARTY" in check_steps[0]["run"]
