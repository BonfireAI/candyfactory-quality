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
    first_party_packages,
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
    """A server/-rooted monorepo consumer: the package lives under server/, not the root."""
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


# --- first-party derivation (the isort alignment defect) -----------------------
#
# The kit's shared ruff gauge cannot statically name every consumer's packages,
# and ruff's path-based detection mis-files imports that do not resolve on disk
# (bonfire: `bonfire.tests.*` has no src/bonfire/tests, so the kit's gauge
# sorted it third-party while the repo's legacy `known-first-party = ["bonfire"]`
# holds it first-party — fixing the kit's I001 created NEW legacy I001).
# The gate therefore DERIVES the first-party names from the consumer's own
# resolved source root and feeds them to ruff at gauge time.


class TestFirstPartyPackages:
    def test_src_layout_names_the_package(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        (repo / "src" / "bonfire").mkdir(parents=True)
        (repo / "src" / "bonfire" / "__init__.py").write_text("", encoding="utf-8")
        assert first_party_packages(repo) == ["bonfire"]

    def test_declared_source_root_names_its_packages(self, tmp_path: Path) -> None:
        repo = _monorepo(tmp_path)
        _declare(repo, '[tool.cf-quality]\nsource_root = "server/src"\n')
        assert first_party_packages(repo) == ["pkg"]

    def test_top_level_modules_count(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        src = repo / "src"
        src.mkdir()
        (src / "single.py").write_text("x = 1\n", encoding="utf-8")
        (src / "pkg").mkdir()
        (src / "pkg" / "__init__.py").write_text("", encoding="utf-8")
        assert first_party_packages(repo) == ["pkg", "single"]

    def test_flat_layout_excludes_non_shipping_dirs(self, tmp_path: Path) -> None:
        # Repo-root source root (no src/): tests/docs/scripts are not
        # first-party import names; hidden dirs never count.
        repo = _repo(tmp_path)
        for name in ("app", "tests", "docs", "scripts"):
            (repo / name).mkdir()
            (repo / name / "__init__.py").write_text("", encoding="utf-8")
        (repo / ".hidden").mkdir()
        (repo / ".hidden" / "__init__.py").write_text("", encoding="utf-8")
        assert first_party_packages(repo) == ["app"]

    def test_namespace_package_without_init_counts(self, tmp_path: Path) -> None:
        # PEP 420: a dir holding .py files is importable without __init__.py.
        repo = _repo(tmp_path)
        (repo / "src" / "nspkg" / "inner").mkdir(parents=True)
        (repo / "src" / "nspkg" / "inner" / "mod.py").write_text("x = 1\n", encoding="utf-8")
        assert first_party_packages(repo) == ["nspkg"]

    def test_python_free_repo_yields_empty(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        (repo / "src").mkdir()
        (repo / "src" / "app.js").write_text("const x = 1;\n", encoding="utf-8")
        assert first_party_packages(repo) == []

    def test_main_prints_toml_array(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # The CLI form is a TOML array literal so the workflow can splice it
        # straight into `--config "lint.isort.known-first-party=..."`.
        repo = _repo(tmp_path)
        (repo / "src" / "bonfire").mkdir(parents=True)
        (repo / "src" / "bonfire" / "__init__.py").write_text("", encoding="utf-8")
        assert main(["first-party", "--root", str(repo)]) == 0
        assert capsys.readouterr().out.strip() == '["bonfire"]'

    def test_main_first_party_empty_array_for_python_free(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        repo = _repo(tmp_path)
        assert main(["first-party", "--root", str(repo)]) == 0
        assert capsys.readouterr().out.strip() == "[]"

    def test_main_first_party_invalid_declaration_exits_typed(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        repo = _repo(tmp_path)
        _declare(repo, '[tool.cf-quality]\nsource_root = "ghost"\n')
        assert main(["first-party", "--root", str(repo)]) == 2
        assert "GATE_CONFIG_INVALID" in capsys.readouterr().err
