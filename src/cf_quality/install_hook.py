"""cf-install-hook — install a git pre-push hook that runs the cf-gate battery.

The recurring, expensive failure this tool exists to kill is the CI round-trip:
a budget breach or an unblessed exemption rides a push all the way to CI before
anyone learns it is red. The playbook's rule R3 — "no breach reaches CI" — wants
the gauge to speak BEFORE the push leaves the laptop.

So this installs a ``pre-push`` hook that ``exec``s the ``cf-gate`` aggregator;
git aborts the push the instant cf-gate exits non-zero (any red gauge). It is an
INSTALLER (a filesystem action), not a gauge, so its exit contract has no
"findings" rung: ``0`` installed · ``2`` could-not-install (a typed
:class:`~cf_quality.errors.GateError`).

Two correctness hazards it handles deliberately:

- the hooks directory. A plain repo keeps hooks in ``<repo>/.git/hooks``, but in
  a git WORKTREE ``.git`` is a file and the hook lookup resolves to the COMMON
  hooks dir. So it never hand-parses ``.git`` — it asks git itself via
  ``git rev-parse --git-path hooks``, which prints the right dir for plain repos
  AND worktrees;
- a foreign hook. It refuses to clobber a ``pre-push`` it did not write (no
  :data:`HOOK_MARKER`) unless ``--force`` is given.

IO is quarantined behind one injectable subprocess seam (``_exec`` / ``_run``)
so the resolve/install logic unit-tests without a real repo.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cf_quality.errors import GateError
from cf_quality.reporting import json_output_enabled

#: The sentinel line that identifies OUR hook (idempotency + clobber guard).
HOOK_MARKER = "# cf-quality pre-push gate (managed by cf-install-hook)"

#: The injected subprocess callable IO functions accept (defaults to ``_run``).
Run = Callable[[list[str]], "subprocess.CompletedProcess[str]"]


# --- the subprocess seam (the only IO; tests monkeypatch this) ---------------


def _which(name: str) -> str:
    """Resolve a tool to an absolute path; a missing tool is a typed error."""
    resolved = shutil.which(name)
    if resolved is None:
        raise GateError(
            code="INSTALL_HOOK_TOOL_MISSING",
            message=f"{name} is not on PATH — cf-install-hook needs git",
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
            code="INSTALL_HOOK_SUBPROCESS_FAILED",
            message=f"could not execute {argv[0]}: {exc}",
            context={"argv": argv},
        ) from exc


def _run(argv: list[str]) -> subprocess.CompletedProcess[str]:
    """The default seam wrapper IO functions call (real cwd + environment)."""
    return _exec(argv, Path.cwd(), os.environ)


# --- frozen value object -----------------------------------------------------


@dataclass(frozen=True)
class InstallResult:
    """What the install did: the hook path and whether it was new or replaced."""

    path: str
    action: str  # "installed" | "overwritten"

    def to_dict(self) -> dict[str, Any]:
        """The wire form — same vocabulary as the in-process form."""
        return {"path": self.path, "action": self.action}


# --- pure logic (no IO) ------------------------------------------------------


def _hook_body() -> str:
    """The pre-push script text (pure): marker + ``exec cf-gate``.

    A non-zero hook exit aborts the push, so ``exec cf-gate`` is the whole gate:
    if any gauge is red, cf-gate exits non-zero and git refuses the push.
    """
    return (
        "#!/bin/sh\n"
        f"{HOOK_MARKER}\n"
        "# Refuse the push when any cf-gate gauge is red "
        "(a non-zero hook exit aborts the push).\n"
        "exec cf-gate\n"
    )


# --- IO functions (call the seam) --------------------------------------------


def resolve_hooks_dir(repo_dir: Path, *, run: Run = _run) -> Path:
    """The repo's hooks dir, the way git resolves it (plain repos AND worktrees).

    Asks ``git rev-parse --git-path hooks`` rather than hand-parsing ``.git`` (a
    file in a worktree). A relative print is resolved against ``repo_dir``; a
    non-zero git exit means this is not a repo — a typed refusal.
    """
    proc = run([_which("git"), "-C", str(repo_dir), "rev-parse", "--git-path", "hooks"])
    if proc.returncode != 0:
        raise GateError(
            code="INSTALL_HOOK_NOT_A_REPO",
            message=f"{repo_dir} is not a git repo (git rev-parse exit {proc.returncode})",
            context={"repo_dir": str(repo_dir), "stderr": proc.stderr.strip()},
        )
    hooks = Path(proc.stdout.strip())
    if not hooks.is_absolute():
        hooks = repo_dir / hooks
    return hooks


def install_pre_push(repo_dir: Path, *, force: bool = False, run: Run = _run) -> InstallResult:
    """Install the cf-gate pre-push hook; refuse to clobber a foreign hook.

    Resolves the hooks dir via :func:`resolve_hooks_dir`, ensures it exists, and
    writes an executable ``pre-push``. A pre-existing hook WITHOUT
    :data:`HOOK_MARKER` is foreign — refused unless ``force``. ``action`` is
    ``"overwritten"`` when the target pre-existed, else ``"installed"``.
    """
    hooks_dir = resolve_hooks_dir(repo_dir, run=run)
    hooks_dir.mkdir(parents=True, exist_ok=True)
    target = hooks_dir / "pre-push"
    existed = target.exists()
    if existed and HOOK_MARKER not in target.read_text(encoding="utf-8") and not force:
        raise GateError(
            code="INSTALL_HOOK_FOREIGN_HOOK",
            message=f"a foreign pre-push hook exists at {target} — refusing to clobber "
            "(re-run with --force to overwrite)",
            context={"path": str(target)},
        )
    target.write_text(_hook_body(), encoding="utf-8")
    target.chmod(0o755)
    return InstallResult(path=str(target), action="overwritten" if existed else "installed")


# --- CLI ---------------------------------------------------------------------


def _emit(result: InstallResult, *, json_output: bool) -> None:
    if json_output:
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        return
    print(f"cf-install-hook: {result.action} {result.path}")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="cf-install-hook",
        description="install a git pre-push hook that runs the cf-gate battery",
    )
    parser.add_argument(
        "--repo-dir", dest="repo_dir", default=".", help="local git dir (default: .)"
    )
    parser.add_argument("--force", action="store_true", help="overwrite a foreign pre-push hook")
    parser.add_argument("--json", action="store_true", help="emit the JSON wire form")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Console entry point. 0 installed · 2 could-not-install (typed GateError)."""
    args = _parse_args(argv)
    try:
        result = install_pre_push(Path(args.repo_dir), force=args.force)
        _emit(result, json_output=bool(args.json) or json_output_enabled())
        return 0
    except GateError as err:
        print(json.dumps({"error": err.to_dict()}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
