"""Tests for cf-install-hook — the cf-gate pre-push installer.

The thesis pinned here: the tool installs an EXECUTABLE ``pre-push`` hook that
``exec``s cf-gate (so any red gauge aborts the push BEFORE CI), resolves the
hooks dir the way git itself does (plain repos AND worktrees), is idempotent over
its OWN hook, and NEVER silently clobbers a foreign hook. The control rods:

- the script body is PURE — it starts ``#!/bin/sh``, carries the marker, and runs
  cf-gate;
- the subprocess seam (``install_hook._which`` / ``install_hook._exec``) is mocked
  with canned ``git rev-parse`` output, so resolve logic runs without a real repo,
  and the install writes into a real ``tmp_path``;
- the installer is an action, not a gauge: success exits 0, a setup GateError
  exits 2 — there is no "findings" rung.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest

from cf_quality import install_hook
from cf_quality.errors import GateError
from cf_quality.install_hook import (
    HOOK_MARKER,
    InstallResult,
    _hook_body,
    install_pre_push,
    main,
    resolve_hooks_dir,
)

# --- helpers -----------------------------------------------------------------


def _install_git(
    monkeypatch: pytest.MonkeyPatch, *, hooks_stdout: str, returncode: int = 0
) -> None:
    """Stub the seam so ``git rev-parse --git-path hooks`` returns canned output."""
    monkeypatch.setattr(install_hook, "_which", lambda name: f"/fake/{name}")

    def fake_exec(
        argv: list[str], cwd: Path, env: Mapping[str, str]
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, returncode, hooks_stdout, "boom")

    monkeypatch.setattr(install_hook, "_exec", fake_exec)


# --- pure: _hook_body --------------------------------------------------------


def test_hook_body_is_a_posix_sh_cf_gate_gate() -> None:
    body = _hook_body()

    assert body.startswith("#!/bin/sh")
    assert HOOK_MARKER in body.splitlines()
    assert "cf-gate" in body


# --- IO: resolve_hooks_dir ---------------------------------------------------


def test_resolve_hooks_dir_absolute_path_passthrough(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_git(monkeypatch, hooks_stdout="/srv/repo/.git/hooks\n")

    resolved = resolve_hooks_dir(Path("/srv/repo"))

    assert resolved == Path("/srv/repo/.git/hooks")


def test_resolve_hooks_dir_relative_path_is_joined_to_repo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_git(monkeypatch, hooks_stdout=".git/hooks\n")

    resolved = resolve_hooks_dir(Path("/srv/repo"))

    assert resolved == Path("/srv/repo/.git/hooks")


def test_resolve_hooks_dir_nonzero_git_exit_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_git(monkeypatch, hooks_stdout="", returncode=128)

    with pytest.raises(GateError) as excinfo:
        resolve_hooks_dir(Path("/not/a/repo"))

    assert excinfo.value.code == "INSTALL_HOOK_NOT_A_REPO"


# --- IO: install_pre_push ----------------------------------------------------


def _point_resolver_at(monkeypatch: pytest.MonkeyPatch, hooks_dir: Path) -> None:
    """Fake the resolver so install writes into a chosen dir without a real repo."""
    monkeypatch.setattr(
        install_hook, "resolve_hooks_dir", lambda repo_dir, *, run=install_hook._run: hooks_dir
    )


def test_install_writes_executable_hook_with_marker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    hooks = tmp_path / "hooks"
    _point_resolver_at(monkeypatch, hooks)

    result = install_pre_push(tmp_path)

    target = hooks / "pre-push"
    assert result == InstallResult(path=str(target), action="installed")
    assert HOOK_MARKER in target.read_text(encoding="utf-8")
    assert os.stat(target).st_mode & 0o111, "the hook must be executable"


def test_install_twice_over_our_hook_is_idempotent_overwrite(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    hooks = tmp_path / "hooks"
    _point_resolver_at(monkeypatch, hooks)

    first = install_pre_push(tmp_path)
    second = install_pre_push(tmp_path)

    assert first.action == "installed"
    assert second.action == "overwritten"


def test_install_refuses_foreign_hook_without_force(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    (hooks / "pre-push").write_text("#!/bin/sh\necho someone-elses-hook\n", encoding="utf-8")
    _point_resolver_at(monkeypatch, hooks)

    with pytest.raises(GateError) as excinfo:
        install_pre_push(tmp_path)

    assert excinfo.value.code == "INSTALL_HOOK_FOREIGN_HOOK"


def test_install_force_overwrites_foreign_hook(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    target = hooks / "pre-push"
    target.write_text("#!/bin/sh\necho someone-elses-hook\n", encoding="utf-8")
    _point_resolver_at(monkeypatch, hooks)

    result = install_pre_push(tmp_path, force=True)

    assert result.action == "overwritten"
    assert HOOK_MARKER in target.read_text(encoding="utf-8")


# --- main end to end ---------------------------------------------------------


def test_main_success_prints_action_and_path_returns_zero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    hooks = tmp_path / "hooks"
    _point_resolver_at(monkeypatch, hooks)

    exit_code = main(["--repo-dir", str(tmp_path)])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "installed" in out
    assert str(hooks / "pre-push") in out


def test_main_gate_error_exits_two(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _install_git(monkeypatch, hooks_stdout="", returncode=128)  # not a repo

    exit_code = main(["--repo-dir", "/not/a/repo"])
    err = capsys.readouterr().err

    assert exit_code == 2
    assert json.loads(err)["error"]["code"] == "INSTALL_HOOK_NOT_A_REPO"


def test_main_json_shape(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    hooks = tmp_path / "hooks"
    _point_resolver_at(monkeypatch, hooks)

    main(["--repo-dir", str(tmp_path), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert payload == InstallResult(path=str(hooks / "pre-push"), action="installed").to_dict()
