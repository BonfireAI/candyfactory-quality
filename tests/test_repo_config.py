"""Contract for cf-repo-config — the consumer's declared layout.

The mount wave surfaced the defect this file pins: the gate assumed the
package sits at the repo root ('src' discovery), so a monorepo with the
package in a subdir drew a vacuous mypy gate and an un-importable pytest.

The fix keeps the ZERO-workflow-inputs doctrine intact: layout is declared in
COMMITTED repo state — a ``[tool.cf-quality]`` table in ``pyproject.toml`` or
a ``.cf-quality.toml`` file at the repo root — never in a caller knob.

Anti-gaming: a DECLARED source_root that does not exist, escapes the repo, or
holds zero .py files FAILS typed (``GATE_CONFIG_INVALID``) — pointing the
gauge at an empty room is a violation, not a pass. Absent declaration keeps
today's discovery exactly (src/ when present, else the repo root).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cf_quality.errors import GateError
from cf_quality.repo_config import (
    load,
    main,
    resolve_package_dir,
    resolve_source_root,
)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "consumer"
    repo.mkdir()
    return repo


def _declare(repo: Path, body: str, home: str = ".cf-quality.toml") -> None:
    (repo / home).write_text(body, encoding="utf-8")


def _monorepo(tmp_path: Path) -> Path:
    """A mexxa-shaped consumer: the package lives under server/, not the root."""
    repo = _repo(tmp_path)
    (repo / "server" / "src" / "pkg").mkdir(parents=True)
    (repo / "server" / "src" / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "server" / "pyproject.toml").write_text("[project]\nname='pkg'\n", encoding="utf-8")
    return repo


# --- absent declaration: today's discovery, unchanged -------------------------


def test_absent_config_discovers_src_when_present(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "src").mkdir()
    assert resolve_source_root(repo) == repo / "src"


def test_absent_config_defaults_to_repo_root_without_src(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    assert resolve_source_root(repo) == repo


def test_absent_config_package_dir_is_repo_root(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    assert resolve_package_dir(repo) == repo


def test_pyproject_without_cf_quality_table_is_absent(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _declare(repo, "[project]\nname='x'\n", home="pyproject.toml")
    config = load(repo)
    assert config.source_root is None and config.package_dir is None


# --- declared + valid ----------------------------------------------------------


def test_declared_source_root_via_dedicated_file(tmp_path: Path) -> None:
    repo = _monorepo(tmp_path)
    _declare(repo, '[tool.cf-quality]\nsource_root = "server/src"\n')
    assert resolve_source_root(repo) == repo / "server" / "src"


def test_declared_source_root_via_pyproject_table(tmp_path: Path) -> None:
    repo = _monorepo(tmp_path)
    _declare(
        repo,
        '[project]\nname = "umbrella"\n[tool.cf-quality]\nsource_root = "server/src"\n',
        home="pyproject.toml",
    )
    assert resolve_source_root(repo) == repo / "server" / "src"


def test_declared_package_dir_with_pyproject(tmp_path: Path) -> None:
    repo = _monorepo(tmp_path)
    _declare(repo, '[tool.cf-quality]\npackage_dir = "server"\n')
    assert resolve_package_dir(repo) == repo / "server"


# --- declared + invalid: the empty room is a violation, never a pass -----------


def test_declared_source_root_missing_fails_typed(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _declare(repo, '[tool.cf-quality]\nsource_root = "ghost/src"\n')
    with pytest.raises(GateError) as excinfo:
        resolve_source_root(repo)
    assert excinfo.value.code == "GATE_CONFIG_INVALID"


def test_declared_source_root_with_zero_py_files_fails_typed(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "empty" / "room").mkdir(parents=True)
    (repo / "empty" / "room" / "README.md").write_text("no code\n", encoding="utf-8")
    _declare(repo, '[tool.cf-quality]\nsource_root = "empty/room"\n')
    with pytest.raises(GateError) as excinfo:
        resolve_source_root(repo)
    assert excinfo.value.code == "GATE_CONFIG_INVALID"
    assert "empty" in excinfo.value.message or ".py" in excinfo.value.message


def test_declared_source_root_escaping_the_repo_fails_typed(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "mod.py").write_text("x = 1\n", encoding="utf-8")
    _declare(repo, '[tool.cf-quality]\nsource_root = "../outside"\n')
    with pytest.raises(GateError) as excinfo:
        resolve_source_root(repo)
    assert excinfo.value.code == "GATE_CONFIG_INVALID"


def test_declared_package_dir_without_pyproject_fails_typed(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "server").mkdir()
    _declare(repo, '[tool.cf-quality]\npackage_dir = "server"\n')
    with pytest.raises(GateError) as excinfo:
        resolve_package_dir(repo)
    assert excinfo.value.code == "GATE_CONFIG_INVALID"


def test_declared_in_both_homes_is_ambiguous_and_fails(tmp_path: Path) -> None:
    repo = _monorepo(tmp_path)
    _declare(repo, '[tool.cf-quality]\nsource_root = "server/src"\n')
    _declare(
        repo,
        '[tool.cf-quality]\nsource_root = "server/src"\n',
        home="pyproject.toml",
    )
    with pytest.raises(GateError) as excinfo:
        load(repo)
    assert excinfo.value.code == "GATE_CONFIG_INVALID"


def test_unknown_key_fails_typed_never_silently_ignored(tmp_path: Path) -> None:
    # A typo'd key silently ignored would be drift, not a decision.
    repo = _repo(tmp_path)
    _declare(repo, '[tool.cf-quality]\nsource_roots = "src"\n')
    with pytest.raises(GateError) as excinfo:
        load(repo)
    assert excinfo.value.code == "GATE_CONFIG_INVALID"


def test_non_string_value_fails_typed(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _declare(repo, "[tool.cf-quality]\nsource_root = 7\n")
    with pytest.raises(GateError) as excinfo:
        load(repo)
    assert excinfo.value.code == "GATE_CONFIG_INVALID"


def test_malformed_toml_fails_typed(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _declare(repo, "[tool.cf-quality\nsource_root = ")
    with pytest.raises(GateError) as excinfo:
        load(repo)
    assert excinfo.value.code == "GATE_CONFIG_INVALID"


# --- CLI ------------------------------------------------------------------------


def test_main_prints_declared_source_root_relative(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _monorepo(tmp_path)
    _declare(repo, '[tool.cf-quality]\nsource_root = "server/src"\n')
    assert main(["source-root", "--root", str(repo)]) == 0
    assert capsys.readouterr().out.strip() == "server/src"


def test_main_prints_discovered_default_when_absent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path)
    (repo / "src").mkdir()
    assert main(["source-root", "--root", str(repo)]) == 0
    assert capsys.readouterr().out.strip() == "src"
    assert main(["package-dir", "--root", str(repo)]) == 0
    assert capsys.readouterr().out.strip() == "."


def test_main_prints_declared_package_dir(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _monorepo(tmp_path)
    _declare(repo, '[tool.cf-quality]\npackage_dir = "server"\n')
    assert main(["package-dir", "--root", str(repo)]) == 0
    assert capsys.readouterr().out.strip() == "server"


def test_main_exits_two_typed_on_invalid_declaration(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path)
    _declare(repo, '[tool.cf-quality]\nsource_root = "ghost"\n')
    assert main(["source-root", "--root", str(repo)]) == 2
    err = capsys.readouterr().err
    assert "GATE_CONFIG_INVALID" in err
