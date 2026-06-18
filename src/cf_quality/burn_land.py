"""cf-burn-land — a cage-safe burn-LANDING planner and phantom-merge verifier.

A "burn" lands several PRs at once. Some are DISJOINT (their base is the trunk,
``main``) and merge in any order; some are STACKED (a PR's base is ANOTHER PR's
head branch) and must merge keystone→tip. Two expensive, recurring failure
modes this tool exists to kill:

1. a STACKED PR merged in the wrong order, or merged into its parent FEATURE
   branch instead of the trunk — GitHub still paints "MERGED" while the work
   never reached ``main`` (the phantom-merge trap);
2. trusting the "MERGED" badge instead of the git object store.

So the tool NEVER merges, rebases, or pushes — those stay with a human operator
(this process is assumed unable to run ``gh pr merge`` or force-push). It only
READS (via ``gh``), PLANS, and VERIFIES (via ``git cat-file``):

- ``plan``   — classify disjoint vs stacked, topo-order the stacked chain
  keystone→tip, and emit a safe merge ledger with the exact retarget command
  (``gh pr edit <N> --base main``) inlined for each stacked PR. A base CYCLE or
  an UNKNOWN base (neither the trunk nor another PR's head) is a typed refusal.
- ``verify`` — for each PR pick a WITNESS (a file the PR ADDED) and ask the
  object store ``git cat-file -e origin/<base>:<witness>``: rc 0 ⇒ truly landed,
  non-zero ⇒ PHANTOM (a finding). A PR that added no file has no witness ⇒ a
  visible WARNING, skipped, never a hard error — the run continues.

IO is quarantined behind one injectable subprocess seam (``_exec`` / ``_run``)
so the pure planning logic and the parsing logic unit-test without a network.

Exit contract (the kit-wide one): 0 clean · 1 findings (a phantom) · 2 the tool
itself could not run (a typed :class:`~cf_quality.errors.GateError`).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cf_quality.errors import GateError
from cf_quality.reporting import json_output_enabled

#: The gh PR fields this tool reads in one call.
_GH_FIELDS = "number,title,headRefName,baseRefName,state,files"

#: The injected subprocess callable IO functions accept (defaults to ``_run``).
Run = Callable[[list[str]], "subprocess.CompletedProcess[str]"]


# --- the subprocess seam (the only IO; tests monkeypatch this) ---------------


def _which(name: str) -> str:
    """Resolve a tool to an absolute path; a missing tool is a typed error."""
    resolved = shutil.which(name)
    if resolved is None:
        raise GateError(
            code="BURN_LAND_TOOL_MISSING",
            message=f"{name} is not on PATH — cf-burn-land needs gh and git",
            context={"tool": name},
        )
    return resolved


def _exec(argv: list[str], cwd: Path, env: Mapping[str, str]) -> subprocess.CompletedProcess[str]:
    """Run a fixed, absolute argv (no shell); OSError → typed GateError."""
    try:
        return subprocess.run(  # noqa: S603 — absolute argv from _which, no shell
            argv,
            cwd=cwd,
            env=dict(env),
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise GateError(
            code="BURN_LAND_SUBPROCESS_FAILED",
            message=f"could not execute {argv[0]}: {exc}",
            context={"argv": argv},
        ) from exc


def _run(argv: list[str]) -> subprocess.CompletedProcess[str]:
    """The default seam wrapper IO functions call (real cwd + environment)."""
    return _exec(argv, Path.cwd(), os.environ)


# --- frozen value objects ----------------------------------------------------


@dataclass(frozen=True)
class PrInfo:
    """One PR's landing-relevant metadata, parsed from ``gh pr view``."""

    number: int
    title: str
    head: str
    base: str
    added_paths: tuple[str, ...]
    state: str

    def to_dict(self) -> dict[str, Any]:
        """The wire form — same vocabulary as the in-process form."""
        return {
            "number": self.number,
            "title": self.title,
            "head": self.head,
            "base": self.base,
            "added_paths": list(self.added_paths),
            "state": self.state,
        }


@dataclass(frozen=True)
class LandingStep:
    """One PR's place in the ledger: its kind and its chosen witness path."""

    pr: PrInfo
    kind: str  # "disjoint" | "stacked"
    witness: str | None

    def to_dict(self) -> dict[str, Any]:
        """The wire form composing the PR's own ``to_dict()``."""
        return {"pr": self.pr.to_dict(), "kind": self.kind, "witness": self.witness}


@dataclass(frozen=True)
class LandingPlan:
    """The safe merge ledger: the disjoint set, then the stacked keystone→tip."""

    disjoint: list[LandingStep]
    stacked: list[LandingStep]

    def to_dict(self) -> dict[str, Any]:
        """The wire form composing each step's own ``to_dict()``."""
        return {
            "disjoint": [step.to_dict() for step in self.disjoint],
            "stacked": [step.to_dict() for step in self.stacked],
        }


@dataclass(frozen=True)
class LandingVerdict:
    """One PR's verify result: landed truth, the witness used, and the detail."""

    number: int
    landed: bool
    witness: str | None
    detail: str

    def to_dict(self) -> dict[str, Any]:
        """The wire form — same vocabulary as the in-process form."""
        return {
            "number": self.number,
            "landed": self.landed,
            "witness": self.witness,
            "detail": self.detail,
        }


# --- pure planning logic (no IO) ---------------------------------------------


def pick_witness(pr: PrInfo) -> str | None:
    """The first file the PR added, or None when it added no files."""
    return pr.added_paths[0] if pr.added_paths else None


def _classify(prs: Sequence[PrInfo], base: str) -> tuple[list[PrInfo], list[PrInfo]]:
    """Split PRs into (disjoint, stacked); an unknown base is a typed refusal."""
    heads = {pr.head for pr in prs}
    disjoint: list[PrInfo] = []
    stacked: list[PrInfo] = []
    for pr in prs:
        if pr.base == base:
            disjoint.append(pr)
        elif pr.base in heads:
            stacked.append(pr)
        else:
            raise GateError(
                code="BURN_LAND_UNKNOWN_BASE",
                message=f"PR #{pr.number} targets {pr.base!r}, which is neither "
                f"{base!r} nor another PR's head in this set",
                context={"number": pr.number, "base": pr.base},
            )
    return disjoint, stacked


def _order_stacked(stacked: Sequence[PrInfo]) -> list[PrInfo]:
    """Topologically order stacked PRs keystone→tip; a cycle is a typed refusal."""
    heads = {pr.head: pr for pr in stacked}
    remaining = {pr.number: pr for pr in stacked}
    placed: set[int] = set()
    order: list[PrInfo] = []
    while remaining:
        ready = sorted(
            (
                pr
                for pr in remaining.values()
                if pr.base not in heads or heads[pr.base].number in placed
            ),
            key=lambda pr: pr.number,
        )
        if not ready:
            raise GateError(
                code="BURN_LAND_CYCLE",
                message="stacked PRs form a base cycle — no keystone resolves",
                context={"cycle": sorted(remaining)},
            )
        for pr in ready:
            order.append(pr)
            placed.add(pr.number)
            del remaining[pr.number]
    return order


def plan_landings(prs: Sequence[PrInfo], *, base: str = "main") -> LandingPlan:
    """Classify, topo-order the stacked chain keystone→tip, and build the ledger."""
    disjoint, stacked = _classify(prs, base)
    ordered = _order_stacked(stacked)
    return LandingPlan(
        disjoint=[LandingStep(pr=pr, kind="disjoint", witness=pick_witness(pr)) for pr in disjoint],
        stacked=[LandingStep(pr=pr, kind="stacked", witness=pick_witness(pr)) for pr in ordered],
    )


# --- IO functions (call the seam; parse gh / git) ----------------------------


def _added_paths(files: Sequence[Any]) -> tuple[str, ...]:
    """gh ``files[]`` → the paths this PR ADDED.

    gh gives each file a ``path`` plus ``additions``/``deletions``. A witness
    only needs a path the PR introduced, so "added" is ``additions > 0`` and
    ``deletions == 0`` (no prior content removed) — good enough to witness a
    brand-new file, and conservative against picking a mere modification.
    """
    return tuple(
        str(entry["path"])
        for entry in files
        if isinstance(entry, Mapping)
        and entry.get("path")
        and int(entry.get("additions", 0)) > 0
        and int(entry.get("deletions", 0)) == 0
    )


def _require(data: Mapping[str, Any], key: str) -> Any:
    """Read a required gh field; its absence is a typed (not a KeyError) failure."""
    value = data.get(key)
    if value is None:
        raise GateError(
            code="BURN_LAND_GH_BADJSON",
            message=f"gh PR JSON is missing required field {key!r}",
            context={"field": key},
        )
    return value


def _parse_pr(raw: str, number: int) -> PrInfo:
    """Parse one ``gh pr view --json`` payload into a PrInfo."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GateError(
            code="BURN_LAND_GH_BADJSON",
            message=f"gh returned unparseable JSON for PR #{number}: {exc}",
            context={"number": number},
        ) from exc
    return PrInfo(
        number=int(data.get("number", number)),
        title=str(data.get("title", "")),
        head=str(_require(data, "headRefName")),
        base=str(_require(data, "baseRefName")),
        added_paths=_added_paths(data.get("files", [])),
        state=str(data.get("state", "")),
    )


def fetch_pr(number: int, *, repo: str | None = None, run: Run = _run) -> PrInfo:
    """Fetch one PR's metadata via gh; a non-zero gh exit is a typed failure."""
    argv = [_which("gh"), "pr", "view", str(number)]
    if repo is not None:
        argv += ["--repo", repo]
    argv += ["--json", _GH_FIELDS]
    proc = run(argv)
    if proc.returncode != 0:
        raise GateError(
            code="BURN_LAND_GH_FAILED",
            message=f"gh pr view #{number} failed (exit {proc.returncode})",
            context={"number": number, "stderr": proc.stderr.strip()},
        )
    return _parse_pr(proc.stdout, number)


def verify_landing(
    pr: PrInfo, *, base: str = "main", repo_dir: str = ".", run: Run = _run
) -> LandingVerdict:
    """Witness one PR against the object store: landed (rc 0) vs phantom (rc≠0).

    A PR with no added file has no witness — that is a WARNING the caller
    surfaces, not a failure, so the verdict is recorded ``landed=True`` and the
    run continues.
    """
    witness = pick_witness(pr)
    if witness is None:
        return LandingVerdict(
            number=pr.number,
            landed=True,
            witness=None,
            detail="added no files — no witness path; skipped (warning)",
        )
    proc = run([_which("git"), "-C", repo_dir, "cat-file", "-e", f"origin/{base}:{witness}"])
    landed = proc.returncode == 0
    state = "present" if landed else "ABSENT (phantom)"
    return LandingVerdict(
        number=pr.number,
        landed=landed,
        witness=witness,
        detail=f"witness {witness} {state} at origin/{base}",
    )


# --- CLI ---------------------------------------------------------------------


def _json_on(args: argparse.Namespace) -> bool:
    return bool(args.json) or json_output_enabled()


def _fetch_all(args: argparse.Namespace) -> list[PrInfo]:
    return [fetch_pr(number, repo=args.repo) for number in args.prs]


def _plan_lines(plan: LandingPlan, base: str) -> list[str]:
    """The human merge ledger, with each stacked PR's retarget command inlined."""
    lines = ["# disjoint set (merge in any order):"]
    lines += [f"  PR #{step.pr.number}  {step.pr.title}" for step in plan.disjoint] or ["  (none)"]
    lines.append(f"# stacked chain (merge keystone -> tip; retarget each to {base} first):")
    for step in plan.stacked:
        lines.append(f"  PR #{step.pr.number}  {step.pr.title}")
        lines.append(f"    gh pr edit {step.pr.number} --base {base}")
    if not plan.stacked:
        lines.append("  (none)")
    return lines


def _emit_plan(plan: LandingPlan, *, base: str, json_output: bool) -> None:
    if json_output:
        print(json.dumps(plan.to_dict(), indent=2, ensure_ascii=False))
        return
    for line in _plan_lines(plan, base):
        print(line)


def _cmd_plan(args: argparse.Namespace) -> int:
    plan = plan_landings(_fetch_all(args), base=args.base)
    _emit_plan(plan, base=args.base, json_output=_json_on(args))
    return 0


def _verify_line(verdict: LandingVerdict) -> str:
    if verdict.witness is None:
        return f"WARNING  PR #{verdict.number}: {verdict.detail}"
    if verdict.landed:
        return f"OK       PR #{verdict.number}: {verdict.detail}"
    return f"PHANTOM  PR #{verdict.number}: {verdict.detail}"


def _emit_verify(verdicts: Sequence[LandingVerdict], *, json_output: bool) -> int:
    """Print the verify report and return its exit code (1 if any phantom)."""
    phantoms = [verdict for verdict in verdicts if not verdict.landed]
    exit_code = 1 if phantoms else 0
    if json_output:
        payload = {
            "command": "verify",
            "exit_code": exit_code,
            "verdicts": [verdict.to_dict() for verdict in verdicts],
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        for verdict in verdicts:
            print(_verify_line(verdict))
    return exit_code


def _cmd_verify(args: argparse.Namespace) -> int:
    verdicts = [
        verify_landing(pr, base=args.base, repo_dir=args.repo_dir) for pr in _fetch_all(args)
    ]
    return _emit_verify(verdicts, json_output=_json_on(args))


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("prs", nargs="+", type=int, metavar="PR", help="PR numbers")
    parser.add_argument("--repo", default=None, help="owner/name (default: current repo)")
    parser.add_argument("--base", default="main", help="trunk base branch (default: main)")
    parser.add_argument(
        "--repo-dir", dest="repo_dir", default=".", help="local git dir for verify (default: .)"
    )
    parser.add_argument("--json", action="store_true", help="emit the JSON wire form")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="cf-burn-land",
        description="cage-safe burn-landing planner + phantom-merge verifier",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    _add_common(sub.add_parser("plan", help="emit a safe merge ledger"))
    _add_common(sub.add_parser("verify", help="verify PRs truly landed (anti-phantom)"))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Console entry point. 0 clean · 1 a phantom finding · 2 could-not-run."""
    args = _parse_args(argv)
    try:
        if args.command == "plan":
            return _cmd_plan(args)
        return _cmd_verify(args)
    except GateError as err:
        print(json.dumps({"error": err.to_dict()}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
