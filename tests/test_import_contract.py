"""Tests for cf-import-contract — the import-contract gate (layering direction).

Every mounted repo commits ONE exhaustive import contract (import-linter
form) naming every top-level package under its source root, plus a committed
ignore-count baseline. The gate runs three passes:

- PASS 1 — contract-file lint, BEFORE lint-imports: wildcard ``ignore_imports``
  entries fail (one-line gutting), the ignore count is ratcheted shrink-only
  against the committed baseline, every top-level package under the source
  root must be named in some contract clause (exhaustiveness — kills
  rename-evasion and vacuity), and the kit-pinned settings may not be
  loosened (``exclude_type_checking_imports = true`` fails).
- PASS 2 — ``lint-imports`` at the kit-pinned version: a violated contract is
  a typed CONTRACT_BROKEN with the named edge + line; an edge covered by an
  enumerated ignore entry PASSES with the entry printed; a stale ignore entry
  fails (unmatched-alerting, the baseline self-cleans); packages present with
  no committed contract are a typed CONTRACT_MISSING; environment/config
  failures (uninstalled src-layout package, unreadable config) surface as a
  typed CONTRACT_CONFIG_ERROR — never as a violation verdict.
- PASS 3 — companion AST check: ``importlib.import_module`` or ``__import__``
  at module level inside contract-protected layers fails (module-level
  dynamic imports are the proven order-dependent-crash shape).

The eleven control-rod fixtures (R1..R11) are built inline below and MUST
behave as stated before ship.

HONEST SCOPE: this gate is a layering-direction proxy for dependency
inversion — core receiving concretes via Any-typed runtime injection passes;
abstraction quality stays review-tier; contract CONTENT is review-gated at
mount (vacuous-but-exhaustive remains possible for flat-layout repos).
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from cf_quality.errors import GateError, GateViolation
from cf_quality.import_contract import lint_contract, main, scan_dynamic_imports

KIT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_FILENAME = "import-contract-baseline.json"
TEMPLATE_PATH = KIT_ROOT / "templates" / "import-contract.toml"


def _package(root: Path, name: str, source: str = "") -> None:
    pkg = root / name
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text(source, encoding="utf-8")


def _contract_toml(
    roots: list[str],
    ignores: tuple[str, ...],
    tc_exclude: str | None,
    alerting: str,
) -> str:
    root_list = ", ".join(f'"{r}"' for r in roots)
    lines = [
        "[tool.importlinter]",
        f"root_packages = [{root_list}]",
        "include_external_packages = false",
    ]
    if tc_exclude is not None:
        lines.append(f"exclude_type_checking_imports = {tc_exclude}")
    lines += [
        "",
        "[[tool.importlinter.contracts]]",
        'name = "core does not import tenants"',
        'type = "forbidden"',
        'source_modules = ["core"]',
        'forbidden_modules = ["tenants"]',
        f'unmatched_ignore_imports_alerting = "{alerting}"',
    ]
    if ignores:
        entries = ", ".join(f'"{e}"' for e in ignores)
        lines.append(f"ignore_imports = [{entries}]")
    return "\n".join(lines) + "\n"


def _mount(
    root: Path,
    *,
    core: str = "",
    ignores: tuple[str, ...] = (),
    baseline: int | None = None,
    contract: bool = True,
    tc_exclude: str | None = "false",
    alerting: str = "error",
    extra_packages: tuple[str, ...] = (),
) -> Path:
    """A flat-layout consumer fixture: core + tenants under the repo root."""
    _package(root, "core", core)
    _package(root, "tenants")
    (root / "tenants" / "acme.py").write_text("X = 1\n", encoding="utf-8")
    for name in extra_packages:
        _package(root, name)
    if contract:
        roots = ["core", "tenants", *extra_packages]
        (root / "pyproject.toml").write_text(
            _contract_toml(roots, ignores, tc_exclude, alerting), encoding="utf-8"
        )
    if baseline is not None:
        (root / BASELINE_FILENAME).write_text(
            json.dumps({"ignored_imports": baseline}) + "\n", encoding="utf-8"
        )
    return root


def _mount_src_layout(root: Path, *, ignores: tuple[str, ...] = ()) -> Path:
    """A src-layout consumer fixture whose package is NOT pip-installed."""
    for name in ("mypkg", "other"):
        pkg = root / "src" / name
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("X = 1\n", encoding="utf-8")
    lines = [
        "[tool.importlinter]",
        'root_packages = ["mypkg", "other"]',
        "include_external_packages = false",
        "exclude_type_checking_imports = false",
        "",
        "[[tool.importlinter.contracts]]",
        'name = "mypkg does not import other"',
        'type = "forbidden"',
        'source_modules = ["mypkg"]',
        'forbidden_modules = ["other"]',
        'unmatched_ignore_imports_alerting = "error"',
    ]
    if ignores:
        entries = ", ".join(f'"{e}"' for e in ignores)
        lines.append(f"ignore_imports = [{entries}]")
    (root / "pyproject.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return root


# --- PASS 1: contract-file lint (runs BEFORE lint-imports) -------------------


def test_wildcard_ignore_entry_fails_contract_lint(tmp_path: Path) -> None:
    # R6 — `core.** -> tenants.**` is the one-line gutting of the whole gate.
    _mount(tmp_path, ignores=("core.** -> tenants.**",), baseline=1)
    violations = lint_contract(tmp_path)
    assert [v.code for v in violations] == ["CONTRACT_LINT_WILDCARD"]
    assert violations[0].context["entry"] == "core.** -> tenants.**"


def test_single_star_wildcard_also_fails_contract_lint(tmp_path: Path) -> None:
    _mount(tmp_path, ignores=("core.* -> tenants.acme",), baseline=1)
    assert [v.code for v in lint_contract(tmp_path)] == ["CONTRACT_LINT_WILDCARD"]


def test_ignore_count_above_baseline_fails_ratchet(tmp_path: Path) -> None:
    _mount(
        tmp_path,
        ignores=("core -> tenants.acme", "core -> tenants.beta"),
        baseline=1,
    )
    violations = lint_contract(tmp_path)
    assert [v.code for v in violations] == ["CONTRACT_LINT_RATCHET"]
    assert violations[0].context["count"] == 2
    assert violations[0].context["baseline"] == 1


def test_ignore_count_at_baseline_passes_lint(tmp_path: Path) -> None:
    _mount(tmp_path, ignores=("core -> tenants.acme",), baseline=1)
    assert lint_contract(tmp_path) == []


def test_ignores_without_committed_baseline_fail_ratchet(tmp_path: Path) -> None:
    # An absent baseline is an empty (zero) baseline, never a free pass.
    _mount(tmp_path, ignores=("core -> tenants.acme",), baseline=None)
    violations = lint_contract(tmp_path)
    assert [v.code for v in violations] == ["CONTRACT_LINT_RATCHET"]
    assert violations[0].context["baseline"] == 0


def test_exclude_type_checking_imports_true_fails_lint(tmp_path: Path) -> None:
    # R10 — loosening the pinned setting silently unguards TYPE_CHECKING edges.
    _mount(tmp_path, tc_exclude="true")
    assert [v.code for v in lint_contract(tmp_path)] == ["CONTRACT_LINT_PINNED_CONFIG"]


def test_unmatched_alerting_downgraded_to_none_fails_lint(tmp_path: Path) -> None:
    # The baseline self-cleans only while unmatched_ignore_imports_alerting=error.
    _mount(tmp_path, alerting="none")
    assert [v.code for v in lint_contract(tmp_path)] == ["CONTRACT_LINT_PINNED_CONFIG"]


def test_unnamed_top_level_package_fails_exhaustiveness(tmp_path: Path) -> None:
    # R7 — `billing` sits in root_packages but in NO contract clause: a package
    # kept out of every clause is the rename-evasion/vacuity hole.
    _mount(tmp_path, extra_packages=("billing",))
    violations = lint_contract(tmp_path)
    assert [v.code for v in violations] == ["CONTRACT_LINT_EXHAUSTIVENESS"]
    assert violations[0].context["package"] == "billing"


def test_all_packages_named_passes_lint(tmp_path: Path) -> None:
    _mount(tmp_path)
    assert lint_contract(tmp_path) == []


def test_unparseable_contract_raises_typed_config_error(tmp_path: Path) -> None:
    _mount(tmp_path, contract=False)
    (tmp_path / "pyproject.toml").write_text("[tool.importlinter\nbroken", encoding="utf-8")
    with pytest.raises(GateError) as excinfo:
        lint_contract(tmp_path)
    assert excinfo.value.code == "CONTRACT_CONFIG_ERROR"
    assert excinfo.value.retryable is False


def test_unparseable_baseline_raises_typed_config_error(tmp_path: Path) -> None:
    _mount(tmp_path, ignores=("core -> tenants.acme",))
    (tmp_path / BASELINE_FILENAME).write_text("not json", encoding="utf-8")
    with pytest.raises(GateError) as excinfo:
        lint_contract(tmp_path)
    assert excinfo.value.code == "CONTRACT_CONFIG_ERROR"


# --- PASS 3: companion dynamic-import scan ------------------------------------


def test_module_level_import_module_in_protected_layer_fails(tmp_path: Path) -> None:
    # R8 — importlib.import_module at module level inside a contract-protected
    # layer is the order-dependent-crash shape the static contract cannot see.
    _mount(
        tmp_path,
        core='import importlib\n_impl = importlib.import_module("tenants.acme")\n',
    )
    violations, _ = scan_dynamic_imports(tmp_path)
    assert [v.code for v in violations] == ["CONTRACT_DYNAMIC_IMPORT"]
    assert violations[0].path == "core/__init__.py"
    assert violations[0].line == 2
    assert isinstance(violations[0], GateViolation)


def test_module_level_dunder_import_in_protected_layer_fails(tmp_path: Path) -> None:
    _mount(tmp_path, core='_impl = __import__("tenants.acme")\n')
    violations, _ = scan_dynamic_imports(tmp_path)
    assert [v.code for v in violations] == ["CONTRACT_DYNAMIC_IMPORT"]
    assert violations[0].line == 1


def test_function_body_dynamic_import_is_not_module_level(tmp_path: Path) -> None:
    # The companion check is module-level only; deferred dynamic loading inside
    # a function body is pass-2/review territory, not an import-time crash.
    _mount(
        tmp_path,
        core=(
            "def load():\n"
            "    import importlib\n"
            '    return importlib.import_module("tenants.acme")\n'
        ),
    )
    findings, scanned = scan_dynamic_imports(tmp_path)
    assert findings == []
    # clean because the modules WERE opened, not because the walk found nothing:
    # core/__init__.py + tenants/__init__.py + tenants/acme.py.
    assert scanned == 3


# --- control rods through the CLI (the parsed-output surface) -----------------


def _run_main(root: Path, monkeypatch: pytest.MonkeyPatch) -> int:
    monkeypatch.chdir(root)
    return main([])


def test_r1_module_level_upward_edge_fails_contract_broken(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _mount(tmp_path, core="import tenants.acme\n")
    exit_code = _run_main(tmp_path, monkeypatch)
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "CONTRACT_BROKEN" in out
    assert "core -> tenants.acme" in out
    assert "l.1" in out


def test_r2_enumerated_ignore_entry_passes_with_entry_printed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _mount(tmp_path, core="import tenants.acme\n", ignores=("core -> tenants.acme",), baseline=1)
    exit_code = _run_main(tmp_path, monkeypatch)
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "core -> tenants.acme" in out, "the honored ignore entry must be printed visibly"
    assert "ignor" in out.lower()


def test_r3_packages_with_no_contract_fail_contract_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _mount(tmp_path, contract=False)
    exit_code = _run_main(tmp_path, monkeypatch)
    assert exit_code == 1
    assert "CONTRACT_MISSING" in capsys.readouterr().out


def test_pyproject_without_importlinter_table_is_contract_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _mount(tmp_path, contract=False)
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "consumer"\n', encoding="utf-8")
    exit_code = _run_main(tmp_path, monkeypatch)
    assert exit_code == 1
    assert "CONTRACT_MISSING" in capsys.readouterr().out


def test_repo_with_no_packages_and_no_contract_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "script.py").write_text("X = 1\n", encoding="utf-8")
    assert _run_main(tmp_path, monkeypatch) == 0


def test_r4_function_body_deferred_upward_import_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _mount(
        tmp_path,
        core="def load():\n    import tenants.acme\n    return tenants.acme.X\n",
    )
    exit_code = _run_main(tmp_path, monkeypatch)
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "CONTRACT_BROKEN" in out
    assert "core -> tenants.acme" in out


def test_r5_type_checking_guarded_upward_import_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _mount(
        tmp_path,
        core=("from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    import tenants.acme\n"),
    )
    exit_code = _run_main(tmp_path, monkeypatch)
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "CONTRACT_BROKEN" in out
    assert "core -> tenants.acme" in out


def test_r6_wildcard_ignore_fails_through_the_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _mount(tmp_path, ignores=("core.** -> tenants.**",), baseline=1)
    exit_code = _run_main(tmp_path, monkeypatch)
    assert exit_code == 1
    assert "CONTRACT_LINT_WILDCARD" in capsys.readouterr().out


def test_r7_unnamed_package_fails_through_the_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _mount(tmp_path, extra_packages=("billing",))
    exit_code = _run_main(tmp_path, monkeypatch)
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "CONTRACT_LINT_EXHAUSTIVENESS" in out
    assert "billing" in out


def test_r8_dynamic_import_fails_through_the_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _mount(
        tmp_path,
        core='import importlib\n_impl = importlib.import_module("tenants.acme")\n',
    )
    exit_code = _run_main(tmp_path, monkeypatch)
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "CONTRACT_DYNAMIC_IMPORT" in out


def test_r9_stale_ignore_entry_fails_unmatched_alerting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The entry matches no real edge: the committed baseline must self-clean.
    _mount(tmp_path, ignores=("core.absent -> tenants.ghost",), baseline=1)
    exit_code = _run_main(tmp_path, monkeypatch)
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "CONTRACT_STALE_IGNORE" in out
    assert "core.absent -> tenants.ghost" in out


def test_r10_exclude_type_checking_true_fails_through_the_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _mount(tmp_path, tc_exclude="true")
    exit_code = _run_main(tmp_path, monkeypatch)
    assert exit_code == 1
    assert "CONTRACT_LINT_PINNED_CONFIG" in capsys.readouterr().out


def test_r11_uninstalled_src_layout_is_config_error_never_a_violation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _mount_src_layout(tmp_path)
    exit_code = _run_main(tmp_path, monkeypatch)
    captured = capsys.readouterr()
    assert exit_code == 2
    assert "CONTRACT_CONFIG_ERROR" in captured.err
    assert "CONTRACT_BROKEN" not in captured.out
    assert "CONTRACT_BROKEN" not in captured.err


def test_contract_lint_verdict_lands_before_lint_imports_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # A wildcard ignore in an UNINSTALLED src-layout repo: pass 2 would die
    # CONTRACT_CONFIG_ERROR, but pass 1 lints the contract file first — the
    # gutting attempt is the verdict (exit 1), not the environment (exit 2).
    _mount_src_layout(tmp_path, ignores=("mypkg.** -> other.**",))
    exit_code = _run_main(tmp_path, monkeypatch)
    assert exit_code == 1
    assert "CONTRACT_LINT_WILDCARD" in capsys.readouterr().out


def test_clean_contracted_repo_passes_with_explicit_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _mount(tmp_path, core="VALUE = 1\n")
    exit_code = main(["--root", str(tmp_path)])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "OK" in out


# --- kit wiring: pin, console script, blessed template, honest scope ----------


def _kit_pyproject() -> dict[str, object]:
    return tomllib.loads((KIT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_console_script_is_registered() -> None:
    data = _kit_pyproject()
    project = data["project"]
    assert isinstance(project, dict)
    scripts = project["scripts"]
    assert isinstance(scripts, dict)
    assert scripts.get("cf-import-contract") == "cf_quality.import_contract:main"


def test_kit_pins_the_lint_imports_version() -> None:
    # Pass 2 runs lint-imports at the KIT-pinned version — a floating dep
    # would let the oracle drift under the contract.
    data = _kit_pyproject()
    project = data["project"]
    assert isinstance(project, dict)
    optional = project["optional-dependencies"]
    assert isinstance(optional, dict)
    dev = optional["dev"]
    assert isinstance(dev, list)
    pins = [d for d in dev if isinstance(d, str) and d.startswith("import-linter==")]
    assert len(pins) == 1, f"dev deps must pin import-linter exactly; found: {dev}"


def test_blessed_template_ships_the_pinned_settings() -> None:
    assert TEMPLATE_PATH.is_file(), "the kit must ship templates/import-contract.toml"
    data = tomllib.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))
    tool = data["tool"]
    assert isinstance(tool, dict)
    table = tool["importlinter"]
    assert isinstance(table, dict)
    assert table["include_external_packages"] is False
    assert table["exclude_type_checking_imports"] is False
    contracts = table["contracts"]
    assert isinstance(contracts, list) and contracts, "the template carries a sample contract"
    for contract in contracts:
        assert isinstance(contract, dict)
        assert contract["unmatched_ignore_imports_alerting"] == "error"


def test_honest_scope_is_disclosed_in_the_gate_docstring() -> None:
    import cf_quality.import_contract as gate

    assert gate.__doc__ is not None
    assert "proxy" in gate.__doc__, "the layering-direction-proxy scope must be disclosed"
    assert "review" in gate.__doc__, "abstraction quality stays review-tier — say so"
