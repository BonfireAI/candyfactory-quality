"""Behavioural rods for the gate's kit-pin re-anchor step.

In a reusable workflow ``ref: ${{ github.job_workflow_sha }}`` on the kit
checkout was observed to render EMPTY at run time, so the kit landed on its
main branch instead of the consumer's pinned commit. The step named "Honor the
consumer's declared kit pin" closes that hole: it re-anchors the kit checkout to
the ONE full-SHA pin the consumer committed in its workflows, and refuses when
there are several pins, or none and ``github.job_workflow_sha`` cannot vouch
for HEAD.

``test_workflows`` only proves the expression string is present on the checkout.
These rods pin what the honor step DOES: its position between the kit checkout
and the kit install, and its verdict in each case, by executing the step's own
``run`` script (lifted from the parsed YAML, never copied) with bash against a
real git world under ``tmp_path``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from test_workflows import GATE_PATH, _load, _steps

HONOR_PREFIX = "Honor the consumer's declared kit pin"
KIT_REPOSITORY = "BonfireAI/candyfactory-quality"
KIT_INSTALL_MARKER = ".cf-quality[dev]"
PIN_LINE = "      uses: BonfireAI/candyfactory-quality/.github/workflows/quality-gate.yml@{sha}\n"
GIT_IDENTITY = ("-c", "user.name=rod", "-c", "user.email=rod@example.invalid")


@dataclass(frozen=True)
class KitWorld:
    """A fixture world: a bare kit origin, a floated kit clone, a consumer."""

    workspace: Path
    kit: Path
    workflows: Path
    home: Path
    c1: str
    c2: str


def _gate_steps() -> list[dict[str, Any]]:
    return _steps(_load(GATE_PATH), "gate")


def _index_of_honor(steps: list[dict[str, Any]]) -> int:
    hits = [i for i, s in enumerate(steps) if str(s.get("name", "")).startswith(HONOR_PREFIX)]
    assert len(hits) == 1, f"exactly one honor step expected, found {len(hits)}"
    return hits[0]


def _honor_step() -> dict[str, Any]:
    steps = _gate_steps()
    return steps[_index_of_honor(steps)]


def _git(cwd: Path, *args: str, home: Path) -> str:
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(home)}
    done = subprocess.run(
        ["git", *GIT_IDENTITY, "-c", "commit.gpgsign=false", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


def _build_origin(root: Path, home: Path) -> tuple[Path, str, str]:
    """A bare kit origin with two commits C1, C2 and main at C2."""
    work = root / "kit-work"
    work.mkdir()
    _git(work, "init", "-q", "-b", "main", home=home)
    shas: list[str] = []
    for label in ("c1", "c2"):
        (work / "marker.txt").write_text(label, encoding="utf-8")
        _git(work, "add", "marker.txt", home=home)
        _git(work, "commit", "-q", "-m", label, home=home)
        shas.append(_git(work, "rev-parse", "HEAD", home=home))
    bare = root / "kit-origin.git"
    _git(root, "clone", "-q", "--bare", str(work), str(bare), home=home)
    _git(bare, "config", "uploadpack.allowAnySHA1InWant", "true", home=home)
    return bare, shas[0], shas[1]


@pytest.fixture
def world(tmp_path: Path) -> KitWorld:
    if shutil.which("bash") is None or shutil.which("git") is None:
        pytest.skip("the honor step is a bash script driving git; bash or git is absent")
    home = tmp_path / "home"
    home.mkdir()
    bare, c1, c2 = _build_origin(tmp_path, home)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    kit = workspace / ".cf-quality"
    # A shallow clone of main: the floated checkout, with C1 NOT present locally,
    # so a re-anchor must genuinely fetch the pin from origin.
    _git(workspace, "clone", "-q", "--depth", "1", bare.as_uri(), str(kit), home=home)
    workflows = workspace / "repo" / ".github" / "workflows"
    workflows.mkdir(parents=True)
    return KitWorld(workspace, kit, workflows, home, c1, c2)


def _stub(world: KitWorld, name: str, *shas: str) -> None:
    lines = ["on: [push]\n", "jobs:\n", "  quality:\n"]
    lines += [PIN_LINE.format(sha=sha) for sha in shas]
    (world.workflows / name).write_text("".join(lines), encoding="utf-8")


def _run_honor(world: KitWorld, job_workflow_sha: str) -> subprocess.CompletedProcess[str]:
    step = _honor_step()
    step_env = step.get("env", {})
    assert isinstance(step_env, dict) and "JOB_WORKFLOW_SHA" in step_env
    env = {key: "" for key in step_env}
    env.update(
        {
            "PATH": os.environ.get("PATH", ""),
            "HOME": str(world.home),
            "GITHUB_WORKSPACE": str(world.workspace),
            "JOB_WORKFLOW_SHA": job_workflow_sha,
        }
    )
    # `bash -e` mirrors the runner's default shell for an unannotated `run:`.
    return subprocess.run(
        ["bash", "-e", "-c", str(step["run"])],
        cwd=world.kit,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _head(world: KitWorld) -> str:
    return _git(world.kit, "rev-parse", "HEAD", home=world.home)


def _assert_refused(done: subprocess.CompletedProcess[str], world: KitWorld) -> None:
    assert done.returncode != 0, f"must refuse, got exit 0:\n{done.stdout}{done.stderr}"
    assert "::error::" in done.stdout + done.stderr, "a refusal must annotate ::error::"
    assert _head(world) == world.c2, "a refusal must leave the kit checkout untouched"


def _assert_reanchored(done: subprocess.CompletedProcess[str], world: KitWorld) -> None:
    assert done.returncode == 0, f"re-anchor failed:\n{done.stdout}{done.stderr}"
    assert _head(world) == world.c1, "the kit checkout must ride the declared pin"


def test_honor_step_sits_between_kit_checkout_and_kit_install() -> None:
    steps = _gate_steps()
    checkout = [
        i for i, s in enumerate(steps) if s.get("with", {}).get("repository") == KIT_REPOSITORY
    ]
    install = [i for i, s in enumerate(steps) if KIT_INSTALL_MARKER in str(s.get("run", ""))]
    honor = _index_of_honor(steps)
    assert len(checkout) == 1, "exactly one kit checkout"
    assert install, "no step installs the kit"
    assert checkout[0] < honor < install[0], (
        "honor step must follow the kit checkout and precede the kit install "
        f"(checkout={checkout[0]}, honor={honor}, install={install[0]})"
    )
    assert str(steps[honor].get("working-directory", "")).endswith("/.cf-quality")


def test_single_pin_behind_head_reanchors_to_the_pin(world: KitWorld) -> None:
    _stub(world, "quality.yml", world.c1)
    assert _head(world) == world.c2
    _assert_reanchored(_run_honor(world, ""), world)


def test_single_pin_equal_to_head_is_left_alone(world: KitWorld) -> None:
    _stub(world, "quality.yml", world.c2)
    done = _run_honor(world, "")
    assert done.returncode == 0, done.stdout + done.stderr
    assert _head(world) == world.c2
    assert "already rides the declared pin" in done.stdout


def test_two_distinct_pins_refuse(world: KitWorld) -> None:
    _stub(world, "quality.yml", world.c1)
    _stub(world, "nightly.yml", world.c2)
    _assert_refused(_run_honor(world, world.c2), world)


def test_repeated_identical_pin_counts_as_one(world: KitWorld) -> None:
    _stub(world, "quality.yml", world.c1)
    _stub(world, "nightly.yml", world.c1)
    _assert_reanchored(_run_honor(world, ""), world)


def test_no_pin_and_empty_job_workflow_sha_refuses_to_float(world: KitWorld) -> None:
    (world.workflows / "quality.yml").write_text(PIN_LINE.format(sha="main"), encoding="utf-8")
    _assert_refused(_run_honor(world, ""), world)


def test_no_pin_and_job_workflow_sha_at_head_proceeds(world: KitWorld) -> None:
    done = _run_honor(world, world.c2)
    assert done.returncode == 0, done.stdout + done.stderr
    assert _head(world) == world.c2
    assert "rides github.job_workflow_sha" in done.stdout


def test_no_pin_and_job_workflow_sha_off_head_refuses(world: KitWorld) -> None:
    _assert_refused(_run_honor(world, world.c1), world)
