"""Tests for cf-burn-land — the cage-safe burn-landing planner + verifier.

The thesis pinned here: the tool plans a SAFE merge order (disjoint any-order,
stacked keystone→tip) and VERIFIES truth against the git object store, never the
"MERGED" badge. The control rods:

- planning is PURE — a 3-deep stack orders keystone→tip, disjoint/stacked split
  cleanly, a base cycle and a dangling base each REFUSE with a typed code;
- the subprocess seam (``burn_land._which`` / ``burn_land._exec``) is mocked with
  canned gh JSON and canned ``git cat-file`` exits, exactly like
  ``test_gate_runner._install_fakes``, so the REAL parse/verify/exit logic runs
  without a network;
- a phantom (witness ABSENT) is a finding (exit 1), all-landed is clean (exit 0),
  a no-witness PR is a WARNING not an error, and a setup GateError exits 2.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest

from cf_quality import burn_land
from cf_quality.burn_land import (
    PrInfo,
    fetch_pr,
    main,
    pick_witness,
    plan_landings,
    verify_landing,
)
from cf_quality.errors import GateError

# --- helpers -----------------------------------------------------------------


def _pr(number: int, head: str, base: str, added: tuple[str, ...] = ()) -> PrInfo:
    return PrInfo(
        number=number,
        title=f"pr-{number}",
        head=head,
        base=base,
        added_paths=added,
        state="OPEN",
    )


def _gh_json(number: int, head: str, base: str, files: list[dict[str, object]]) -> str:
    return json.dumps(
        {
            "number": number,
            "title": f"pr-{number}",
            "headRefName": head,
            "baseRefName": base,
            "state": "OPEN",
            "files": files,
        }
    )


def _file(path: str, *, additions: int = 10, deletions: int = 0) -> dict[str, object]:
    return {"path": path, "additions": additions, "deletions": deletions}


def _install(
    monkeypatch: pytest.MonkeyPatch,
    *,
    gh_by_number: Mapping[int, tuple[int, str]] | None = None,
    git_landed: set[str] | None = None,
) -> None:
    """Stub the subprocess seam: gh returns canned JSON, git cat-file canned rc."""
    gh = gh_by_number or {}
    landed = git_landed or set()
    monkeypatch.setattr(burn_land, "_which", lambda name: f"/fake/{name}")

    def fake_exec(
        argv: list[str], cwd: Path, env: Mapping[str, str]
    ) -> subprocess.CompletedProcess[str]:
        name = Path(argv[0]).name
        if name == "gh":
            number = int(argv[3])  # ["/fake/gh", "pr", "view", "<n>", ...]
            returncode, stdout = gh[number]
            return subprocess.CompletedProcess(argv, returncode, stdout, "")
        witness = argv[-1].split(":", 1)[1]  # "origin/<base>:<witness>"
        return subprocess.CompletedProcess(argv, 0 if witness in landed else 1, "", "")

    monkeypatch.setattr(burn_land, "_exec", fake_exec)


# --- pure planning -----------------------------------------------------------


def test_plan_orders_three_deep_stack_keystone_to_tip() -> None:
    # PR1 is disjoint (base=main); PR2→PR3→PR4 stack on each other's heads. The
    # stacked chain must come out keystone (PR2) → tip (PR4), regardless of input
    # order — here deliberately shuffled.
    root = _pr(1, "b1", "main")
    tip = _pr(4, "b4", "b3")
    mid = _pr(3, "b3", "b2")
    keystone = _pr(2, "b2", "b1")

    plan = plan_landings([tip, root, mid, keystone])

    assert [step.pr.number for step in plan.disjoint] == [1]
    assert [step.pr.number for step in plan.stacked] == [2, 3, 4]
    assert all(step.kind == "stacked" for step in plan.stacked)


def test_plan_splits_disjoint_and_stacked() -> None:
    d1 = _pr(10, "x", "main")
    d2 = _pr(11, "y", "main")
    s1 = _pr(12, "z", "x")  # stacked on d1's head

    plan = plan_landings([d1, d2, s1])

    assert {step.pr.number for step in plan.disjoint} == {10, 11}
    assert [step.pr.number for step in plan.stacked] == [12]


def test_plan_rejects_base_cycle() -> None:
    a = _pr(1, "ba", "bb")  # base is b's head
    b = _pr(2, "bb", "ba")  # base is a's head — mutual, no keystone

    with pytest.raises(GateError) as excinfo:
        plan_landings([a, b])

    assert excinfo.value.code == "BURN_LAND_CYCLE"


def test_plan_rejects_unknown_base() -> None:
    orphan = _pr(7, "feat", "no-such-branch")  # neither main nor a known head

    with pytest.raises(GateError) as excinfo:
        plan_landings([orphan])

    assert excinfo.value.code == "BURN_LAND_UNKNOWN_BASE"


def test_pick_witness_takes_first_added_then_none() -> None:
    assert pick_witness(_pr(1, "h", "main", ("a.py", "b.py"))) == "a.py"
    assert pick_witness(_pr(2, "h", "main", ())) is None


# --- IO: fetch_pr ------------------------------------------------------------


def test_fetch_pr_parses_gh_json(monkeypatch: pytest.MonkeyPatch) -> None:
    files = [
        _file("new_module.py"),  # added (deletions 0) → a witness
        _file("touched.py", additions=3, deletions=4),  # modified → NOT added
    ]
    _install(monkeypatch, gh_by_number={7: (0, _gh_json(7, "feat-7", "main", files))})

    pr = fetch_pr(7)

    assert pr == PrInfo(
        number=7,
        title="pr-7",
        head="feat-7",
        base="main",
        added_paths=("new_module.py",),
        state="OPEN",
    )


def test_fetch_pr_nonzero_gh_exit_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, gh_by_number={7: (1, "")})

    with pytest.raises(GateError) as excinfo:
        fetch_pr(7)

    assert excinfo.value.code == "BURN_LAND_GH_FAILED"


# --- IO: verify_landing ------------------------------------------------------


def test_verify_landing_true_when_witness_present(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, git_landed={"new.py"})
    pr = _pr(1, "feat", "main", ("new.py",))

    verdict = verify_landing(pr)

    assert verdict.landed is True
    assert verdict.witness == "new.py"


def test_verify_landing_phantom_when_witness_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, git_landed=set())
    pr = _pr(1, "feat", "main", ("new.py",))

    verdict = verify_landing(pr)

    assert verdict.landed is False
    assert "phantom" in verdict.detail.lower()


def test_verify_landing_no_witness_is_warning_not_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, git_landed=set())
    pr = _pr(1, "feat", "main", ())  # added no files

    verdict = verify_landing(pr)

    assert verdict.witness is None
    assert verdict.landed is True, "no witness is a warning, not a phantom finding"
    assert "warning" in verdict.detail.lower()


# --- main(verify) end to end -------------------------------------------------


def test_main_verify_phantom_exits_one(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(
        monkeypatch,
        gh_by_number={
            1: (0, _gh_json(1, "feat-1", "main", [_file("landed.py")])),
            2: (0, _gh_json(2, "feat-2", "main", [_file("phantom.py")])),
        },
        git_landed={"landed.py"},  # PR 2's witness is ABSENT → phantom
    )

    assert main(["verify", "1", "2"]) == 1


def test_main_verify_all_landed_exits_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(
        monkeypatch,
        gh_by_number={1: (0, _gh_json(1, "feat-1", "main", [_file("landed.py")]))},
        git_landed={"landed.py"},
    )

    assert main(["verify", "1"]) == 0


def test_main_verify_gate_error_exits_two(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _install(monkeypatch, gh_by_number={1: (1, "")})  # gh fails → setup GateError

    exit_code = main(["verify", "1"])
    err = capsys.readouterr().err

    assert exit_code == 2
    assert json.loads(err)["error"]["code"] == "BURN_LAND_GH_FAILED"


def test_main_verify_json_shape(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _install(
        monkeypatch,
        gh_by_number={1: (0, _gh_json(1, "feat-1", "main", [_file("landed.py")]))},
        git_landed={"landed.py"},
    )

    main(["verify", "1", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert payload["command"] == "verify"
    assert payload["exit_code"] == 0
    assert payload["verdicts"][0]["number"] == 1
    assert payload["verdicts"][0]["landed"] is True


def test_main_plan_emits_retarget_commands(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _install(
        monkeypatch,
        gh_by_number={
            1: (0, _gh_json(1, "b1", "main", [_file("a.py")])),  # disjoint
            2: (0, _gh_json(2, "b2", "b1", [_file("b.py")])),  # stacked on PR1
        },
    )

    assert main(["plan", "1", "2"]) == 0
    out = capsys.readouterr().out

    assert "gh pr edit 2 --base main" in out, "stacked PR's retarget command is inlined"
    assert "gh pr edit 1" not in out, "a disjoint PR needs no retarget"
