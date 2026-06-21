"""cf-import-contract — the import-contract gate (layering direction).

Every mounted repo commits ONE exhaustive import contract (import-linter
form) naming every top-level package under its source root, plus a committed
ignore-count baseline (``import-contract-baseline.json``). The gate runs
three passes:

- PASS 1 — contract-file lint, BEFORE lint-imports: wildcard
  ``ignore_imports`` entries fail (``CONTRACT_LINT_WILDCARD`` — the one-line
  gutting), the ignore count ratchets shrink-only against the committed
  baseline (``CONTRACT_LINT_RATCHET``; an absent baseline is zero, never a
  free pass), every top-level package under the source root must be named in
  some contract clause (``CONTRACT_LINT_EXHAUSTIVENESS`` — kills
  rename-evasion and vacuity), and the kit-pinned settings may not be
  loosened (``CONTRACT_LINT_PINNED_CONFIG``).
- PASS 2 — ``lint-imports`` at the kit-pinned version (subprocess, cwd = the
  repo root, so flat layouts resolve): a violated contract is
  ``CONTRACT_BROKEN`` with the named edge + line; an edge covered by an
  enumerated ignore entry PASSES with the entry printed; a stale ignore entry
  is ``CONTRACT_STALE_IGNORE`` (unmatched-alerting, the baseline
  self-cleans); environment/config failures (uninstalled src-layout package,
  unreadable config) surface as a typed ``CONTRACT_CONFIG_ERROR`` exit 2 —
  never as a violation verdict.
- PASS 3 — companion AST scan: ``importlib.import_module`` / ``__import__``
  at module level inside contract-protected layers fails
  (``CONTRACT_DYNAMIC_IMPORT`` — the order-dependent-crash shape the static
  contract cannot see). Function-body dynamic loading is out of scope by
  design.

A repo with no contract and no top-level packages passes; packages with no
committed contract are ``CONTRACT_MISSING``.

HONEST SCOPE: this gate is a layering-direction proxy for dependency
inversion — core receiving concretes via Any-typed runtime injection passes;
abstraction quality stays review-tier; contract CONTENT is review-gated at
mount (vacuous-but-exhaustive remains possible for flat-layout repos).

Exit codes: 0 clean · 1 violations found · 2 the gate itself could not run
(typed :class:`~cf_quality.errors.GateError` on stderr).
"""

from __future__ import annotations

import argparse
import ast
import json

# subprocess: pass 2 runs the kit-pinned lint-imports beside sys.executable,
# fixed argv, no shell (S603 gated at the call site below).
import subprocess
import sys
import tomllib
from collections.abc import Iterator
from pathlib import Path

from cf_quality.errors import GateError, GateViolation
from cf_quality.repo_config import resolve_source_root
from cf_quality.reporting import print_verdict

BASELINE_FILENAME = "import-contract-baseline.json"
_PINNED_ALERTING = "error"
_CLAUSE_MODULE_KEYS = ("source_modules", "forbidden_modules", "modules", "layers", "containers")
_STALE_IGNORE_MARKER = "No matches for ignored import"
_SCOPE_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)


def _config_error(message: str, context: dict[str, object]) -> GateError:
    return GateError(code="CONTRACT_CONFIG_ERROR", message=message, context=context)


def _load_contract_table(root: Path) -> dict[str, object] | None:
    """The ``[tool.importlinter]`` table of the repo's pyproject, None when absent."""
    path = root / "pyproject.toml"
    if not path.is_file():
        return None
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise _config_error(f"cannot parse pyproject.toml: {exc}", {"path": str(path)}) from exc
    tool = data.get("tool")
    if not isinstance(tool, dict):
        return None
    table = tool.get("importlinter")
    return table if isinstance(table, dict) else None


def _load_baseline(root: Path) -> int:
    """The committed ignore-count baseline; ABSENT means zero, never a free pass."""
    path = root / BASELINE_FILENAME
    if not path.is_file():
        return 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise _config_error(
            f"cannot parse {BASELINE_FILENAME}: {exc}", {"path": str(path)}
        ) from exc
    value = data.get("ignored_imports") if isinstance(data, dict) else None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _config_error(
            f"{BASELINE_FILENAME} must carry a non-negative integer 'ignored_imports'",
            {"path": str(path), "value": repr(value)},
        )
    return value


def _contracts(table: dict[str, object]) -> list[dict[str, object]]:
    raw = table.get("contracts")
    if not isinstance(raw, list):
        return []
    return [clause for clause in raw if isinstance(clause, dict)]


def _ignore_entries(contracts: list[dict[str, object]]) -> list[str]:
    entries: list[str] = []
    for clause in contracts:
        raw = clause.get("ignore_imports")
        if isinstance(raw, list):
            entries.extend(entry for entry in raw if isinstance(entry, str))
    return entries


def _named_top_level(contracts: list[dict[str, object]]) -> set[str]:
    """Top-level package names appearing in any contract clause's module fields."""
    named: set[str] = set()
    for clause in contracts:
        for key in _CLAUSE_MODULE_KEYS:
            raw = clause.get(key)
            if isinstance(raw, list):
                named.update(m.split(".")[0] for m in raw if isinstance(m, str))
    return named


def _top_level_packages(source_root: Path) -> list[str]:
    """Importable top-level packages (dirs carrying ``__init__.py``) under the root."""
    return sorted(
        child.name
        for child in source_root.iterdir()
        if child.is_dir() and (child / "__init__.py").is_file()
    )


def _contract_violation(code: str, message: str, context: dict[str, object]) -> GateViolation:
    return GateViolation(code=code, message=message, path="pyproject.toml", context=context)


def _lint_ignores(ignores: list[str], baseline: int) -> list[GateViolation]:
    violations = [
        _contract_violation(
            "CONTRACT_LINT_WILDCARD",
            f"wildcard ignore_imports entry guts the contract: {entry!r} — "
            "every ignored edge is enumerated, never globbed",
            {"entry": entry},
        )
        for entry in ignores
        if "*" in entry
    ]
    if len(ignores) > baseline:
        violations.append(
            _contract_violation(
                "CONTRACT_LINT_RATCHET",
                f"ignore_imports count {len(ignores)} exceeds the committed baseline "
                f"{baseline} ({BASELINE_FILENAME}; absent means zero) — the ratchet "
                "only shrinks",
                {"count": len(ignores), "baseline": baseline},
            )
        )
    return violations


def _lint_pinned_settings(
    table: dict[str, object], contracts: list[dict[str, object]]
) -> list[GateViolation]:
    violations: list[GateViolation] = []
    if table.get("exclude_type_checking_imports") is True:
        violations.append(
            _contract_violation(
                "CONTRACT_LINT_PINNED_CONFIG",
                "exclude_type_checking_imports = true loosens the kit pin — "
                "TYPE_CHECKING edges stay under contract",
                {"setting": "exclude_type_checking_imports"},
            )
        )
    for clause in contracts:
        alerting = clause.get("unmatched_ignore_imports_alerting", _PINNED_ALERTING)
        if alerting != _PINNED_ALERTING:
            violations.append(
                _contract_violation(
                    "CONTRACT_LINT_PINNED_CONFIG",
                    f"unmatched_ignore_imports_alerting = {alerting!r} downgrades the "
                    "kit pin ('error') — the baseline self-cleans only while stale "
                    "ignores fail",
                    {
                        "setting": "unmatched_ignore_imports_alerting",
                        "contract": clause.get("name"),
                    },
                )
            )
    return violations


def _lint_exhaustiveness(root: Path, contracts: list[dict[str, object]]) -> list[GateViolation]:
    named = _named_top_level(contracts)
    return [
        _contract_violation(
            "CONTRACT_LINT_EXHAUSTIVENESS",
            f"top-level package '{package}' is named in no contract clause — "
            "every package under the source root sits inside the contract",
            {"package": package},
        )
        for package in _top_level_packages(resolve_source_root(root))
        if package not in named
    ]


def lint_contract(root: Path) -> list[GateViolation]:
    """PASS 1 — lint the committed contract file itself, before lint-imports."""
    root = root.resolve()
    table = _load_contract_table(root)
    if table is None:
        return []
    contracts = _contracts(table)
    violations = _lint_ignores(_ignore_entries(contracts), _load_baseline(root))
    violations += _lint_pinned_settings(table, contracts)
    violations += _lint_exhaustiveness(root, contracts)
    return violations


def _read_tree(path: Path) -> ast.Module:
    try:
        source = path.read_text(encoding="utf-8")
        return ast.parse(source, filename=str(path))
    except (OSError, SyntaxError) as exc:
        raise _config_error(
            f"cannot read/parse source file under contract: {path}",
            {"path": str(path), "detail": str(exc)},
        ) from exc


def _module_level_calls(tree: ast.Module) -> Iterator[ast.Call]:
    """Calls that execute at import time — never descends into function scopes.

    Iterative walk over the finite parsed tree (explicit pending stack).
    """
    pending: list[ast.AST] = list(tree.body)
    while pending:
        node = pending.pop()
        if isinstance(node, _SCOPE_NODES):
            continue
        if isinstance(node, ast.Call):
            yield node
        pending.extend(ast.iter_child_nodes(node))


def _is_dynamic_import(call: ast.Call) -> bool:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id == "__import__"
    return isinstance(func, ast.Attribute) and func.attr == "import_module"


def scan_dynamic_imports(root: Path) -> list[GateViolation]:
    """PASS 3 — module-level dynamic imports inside contract-protected layers."""
    root = root.resolve()
    table = _load_contract_table(root)
    if table is None:
        return []
    source_root = resolve_source_root(root)
    protected = _named_top_level(_contracts(table)) & set(_top_level_packages(source_root))
    violations: list[GateViolation] = []
    for package in sorted(protected):
        for path in sorted((source_root / package).rglob("*.py")):
            rel = path.relative_to(root).as_posix()
            violations.extend(
                GateViolation(
                    code="CONTRACT_DYNAMIC_IMPORT",
                    message="module-level dynamic import inside a contract-protected "
                    "layer — an import the static contract cannot see, and the "
                    "order-dependent-crash shape",
                    path=rel,
                    line=call.lineno,
                    context={"package": package},
                )
                for call in _module_level_calls(_read_tree(path))
                if _is_dynamic_import(call)
            )
    return violations


def _run_lint_imports(root: Path) -> tuple[int, str]:
    """Run the kit-pinned lint-imports with cwd = the repo root (flat layouts resolve)."""
    executable = Path(sys.executable).parent / "lint-imports"
    if not executable.is_file():
        raise _config_error(
            "lint-imports is not installed beside the running Python — install the "
            "kit's [dev] extra (it pins import-linter)",
            {"expected": str(executable)},
        )
    try:
        proc = subprocess.run(  # noqa: S603 — pinned venv executable, fixed argv, no shell
            [str(executable), "--no-cache"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise _config_error(
            f"lint-imports could not be executed: {exc}", {"executable": str(executable)}
        ) from exc
    return proc.returncode, proc.stdout + proc.stderr


def _edge_lines(output: str) -> list[str]:
    return [line.strip() for line in output.splitlines() if "->" in line]


def _pass_two_violations(exit_code: int, output: str) -> list[GateViolation]:
    """PASS 2 as typed findings — never parsed bare strings.

    A clean run yields nothing; a broken contract or a stale ignore becomes
    one CONTRACT_BROKEN / CONTRACT_STALE_IGNORE per reported edge (the
    lint-imports edge text rides in the message and context). A failure with
    no contract verdict at all is environment/config trouble — a typed
    CONTRACT_CONFIG_ERROR (exit 2), never a violation verdict.
    """
    if exit_code == 0:
        return []
    if _STALE_IGNORE_MARKER in output:
        return _edge_violations(
            "CONTRACT_STALE_IGNORE",
            "ignore_imports entries match no real edge — remove them; the baseline self-cleans",
            output,
        )
    if "BROKEN" in output:
        return _edge_violations(
            "CONTRACT_BROKEN",
            "lint-imports reports the committed contract violated",
            output,
        )
    raise _config_error(
        "lint-imports failed without a contract verdict (environment/config "
        "trouble, e.g. an uninstalled src-layout package)",
        {"exit_code": exit_code, "output_tail": output.strip().splitlines()[-3:]},
    )


def _edge_violations(code: str, summary: str, output: str) -> list[GateViolation]:
    """One finding per reported edge; a verdict with no edge still reports once."""
    edges = _edge_lines(output)
    if not edges:
        return [_contract_violation(code, summary, {"output": output.strip()})]
    return [_contract_violation(code, f"{summary}: {edge}", {"edge": edge}) for edge in edges]


def _missing_contract_verdict(root: Path) -> int:
    packages = _top_level_packages(resolve_source_root(root))
    if not packages:
        return print_verdict(
            "cf-import-contract",
            [],
            clean_summary="cf-import-contract: OK (no top-level packages, no contract required)",
        )
    violation = _contract_violation(
        "CONTRACT_MISSING",
        f"top-level package(s) {', '.join(packages)} carry no committed import "
        "contract ([tool.importlinter] in pyproject.toml)",
        {"packages": packages},
    )
    return print_verdict("cf-import-contract", [violation])


_CLEAN_SUMMARY = (
    "cf-import-contract: OK (contract linted, lint-imports kept, no module-level "
    "dynamic imports)"
)


def _pass_two(root: Path, *, tolerate_config_error: bool) -> list[GateViolation]:
    """PASS 2 — lint-imports as typed findings, aggregated with the other passes.

    A pass-2 config error (an uninstalled src-layout package, unreadable config)
    is tolerated ONLY when PASS 1 already condemned the contract file: the
    gutting attempt is the verdict (exit 1), never masked by the environment
    (exit 2). With a clean contract file the config error stays fatal.
    """
    try:
        exit_code, output = _run_lint_imports(root)
        return _pass_two_violations(exit_code, output)
    except GateError:
        if tolerate_config_error:
            return []
        raise


def _honored_notices(table: dict[str, object]) -> list[str]:
    return [
        f"ignored edge honored (enumerated, baseline-counted): {entry}"
        for entry in _ignore_entries(_contracts(table))
    ]


def _run_gate(root: Path) -> int:
    """Run all three passes, AGGREGATE their findings, then decide once.

    No cross-pass fail-fast: PASS 1 (contract-file lint), PASS 2 (lint-imports),
    and PASS 3 (the dynamic-import AST scan) each contribute their findings to
    ONE verdict, so a single run shows every layering problem at once.
    """
    table = _load_contract_table(root)
    if table is None:
        return _missing_contract_verdict(root)
    violations = lint_contract(root)
    violations += _pass_two(root, tolerate_config_error=bool(violations))
    violations += scan_dynamic_imports(root)
    notices: list[str] = [] if violations else _honored_notices(table)
    return print_verdict(
        "cf-import-contract", violations, notices=notices, clean_summary=_CLEAN_SUMMARY
    )


def main(argv: list[str] | None = None) -> int:
    """Console entry point. Exit 0 clean, 1 on violations, 2 on gate error."""
    parser = argparse.ArgumentParser(
        prog="cf-import-contract",
        description="The committed import contract holds — layering direction is gated.",
    )
    parser.add_argument("--root", default=".", help="repo root (default: cwd)")
    args = parser.parse_args(argv)
    try:
        return _run_gate(Path(args.root).resolve())
    except GateError as exc:
        return print_verdict("cf-import-contract", [], exc)


if __name__ == "__main__":
    raise SystemExit(main())
