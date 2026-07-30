"""cf-file-budget — the BubbleGum Law's file-size ratchet.

Anti-gaming disclosure (baked in per the refuter verdict on Law 2): this
budget exists to stop single-file accretion dumps by burn agents, not to
worship small files — mechanical splits without design get bounced at
review, and the per-package LOC budgets below close the sibling-file
relocation of the same accretion (a 499-line ``handle_extra.py`` next to a
frozen ``handle.py`` draws against the package's frozen total and FAILS).

The unit of measure is COMPRESSION-RESISTANT (the refuter's statement-joining
attack): every draw is anchored to ``max(physical lines, logical statements)``
(``measure_file``). Re-flowing 900 statements onto 300 ``;``-joined physical
lines still measures 900 — a "shrink" cannot be manufactured by compressing
the same code onto fewer lines, and the freed headroom cannot be spent on
real new-code accretion. An unparseable .py file is a typed gate error,
never a silent line-count fallback.

Three rules, all anchored to ``file-budget.json``:

1. **New files** (not in the baseline) may not exceed 500 (measured) lines.
2. **Frozen files** (``path -> measured size``) may only shrink:
   current > frozen fails; current < frozen passes with a shrink notice.
3. **Baselined packages** (``dir -> frozen size total``, recursive) may not
   grow: every undeclared .py file under the dir draws against the total.
   A new file may be *declared* with ``{"purpose": "one-line"}`` —
   declared-not-banned — which exempts it from the package draw while it
   still obeys the 500-line new-file cap.

HONEST OPEN (v0, disclosed per the refuter's greenfield finding): the package
draw is RELOCATION-ONLY. ``init`` baselines a package total only for
directories already holding a >500 offender, so a greenfield burn that
authors many sub-500 sibling files in a fresh package never draws against a
package ceiling — that accretion is bounded by review and by the per-function
gates (ruff C901/PLR0915), not by this gate. An aggregate per-directory
ceiling would need a measured anchor this kit does not yet have (budgets are
measured, never invented); the boundary is recorded in DESIGN.md Open issues.

Exit codes: 0 clean · 1 violations (typed GateViolation report on stdout)
· 2 the gate itself could not run (typed GateError on stderr).
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cf_quality.errors import GateError, GateViolation
from cf_quality.reporting import print_verdict

NEW_FILE_BUDGET = 500
SKIP_DIR_NAMES = {"__pycache__", "node_modules", "build", "dist", "venv"}


@dataclass(frozen=True)
class FileEntry:
    """One ``files`` entry: a frozen offender, a declared new file, or both."""

    frozen_lines: int | None = None
    purpose: str | None = None


@dataclass(frozen=True)
class Budget:
    """The committed baseline: frozen files and frozen package LOC totals."""

    files: dict[str, FileEntry]
    packages: dict[str, int]


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise GateError(
            code="GATE_READ_FAILED",
            message=f"cannot read {path}: {exc}",
            context={"path": str(path)},
        ) from exc


def count_lines(path: Path) -> int:
    """Count physical lines; raises a typed GateError when unreadable."""
    return len(_read_text(path).splitlines())


def count_statements(path: Path) -> int:
    """Count logical statements (``ast.stmt`` nodes, nested included).

    Raises a typed GateError when the file is unreadable or unparseable —
    never a silent fallback to a gameable line count.
    """
    text = _read_text(path)
    try:
        tree = ast.parse(text, filename=str(path))
    except (SyntaxError, ValueError) as exc:
        raise GateError(
            code="GATE_SOURCE_UNPARSEABLE",
            message=f"cannot parse {path}: {exc}",
            context={"path": str(path)},
        ) from exc
    return sum(1 for node in ast.walk(tree) if isinstance(node, ast.stmt))


def measure_file(path: Path) -> int:
    """The compression-resistant size every draw is anchored to.

    ``max(physical lines, logical statements)``: normally formatted code
    measures by its lines; ``;``-joined or re-flowed code measures by its
    statements, so compressing source cannot manufacture budget headroom.
    """
    return max(count_lines(path), count_statements(path))


def iter_python_files(root: Path) -> Iterator[Path]:
    """Yield every .py file under root, pruning caches/venvs/hidden dirs."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            d for d in dirnames if d not in SKIP_DIR_NAMES and not d.startswith(".")
        )
        for name in sorted(filenames):
            if name.endswith(".py"):
                yield Path(dirpath) / name


def _config_error(message: str, context: dict[str, Any]) -> GateError:
    return GateError(code="GATE_CONFIG_INVALID", message=message, context=context)


def _parse_file_entry(path_key: str, raw: object) -> FileEntry:
    if isinstance(raw, int) and not isinstance(raw, bool):
        return FileEntry(frozen_lines=raw)
    if isinstance(raw, dict):
        lines = raw.get("lines")
        purpose = raw.get("purpose")
        lines_ok = lines is None or (isinstance(lines, int) and not isinstance(lines, bool))
        if lines_ok and isinstance(purpose, str) and purpose:
            return FileEntry(frozen_lines=lines, purpose=purpose)
    raise _config_error(
        f"files entry for {path_key!r} must be a frozen line count (int) or "
        'an object with a one-line "purpose" (declared-not-banned)',
        {"path": path_key, "entry": repr(raw)},
    )


def load_budget(config_path: Path) -> Budget:
    """Load file-budget.json; a missing file is an empty (day-one) baseline."""
    if not config_path.exists():
        return Budget(files={}, packages={})
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise _config_error(
            f"cannot parse {config_path}: {exc}", {"config": str(config_path)}
        ) from exc
    if not isinstance(data, dict):
        raise _config_error(f"{config_path} must hold a JSON object", {"config": str(config_path)})
    raw_files = data.get("files", {})
    raw_packages = data.get("packages", {})
    if not isinstance(raw_files, dict) or not isinstance(raw_packages, dict):
        raise _config_error(
            '"files" and "packages" must be JSON objects', {"config": str(config_path)}
        )
    files = {key: _parse_file_entry(key, raw) for key, raw in raw_files.items()}
    for pkg, total in raw_packages.items():
        if not isinstance(total, int) or isinstance(total, bool):
            raise _config_error(
                f"packages entry for {pkg!r} must be a frozen LOC total (int)",
                {"package": pkg, "entry": repr(total)},
            )
    return Budget(files=files, packages=dict(raw_packages))


def _in_package(rel: str, package: str) -> bool:
    return package == "." or rel.startswith(package.rstrip("/") + "/")


def _check_file(rel: str, lines: int, entry: FileEntry | None) -> GateViolation | str | None:
    """One file's verdict: a violation, a shrink notice (str), or None."""
    if entry is None or entry.frozen_lines is None:
        if lines > NEW_FILE_BUDGET:
            return GateViolation(
                code="FILE_BUDGET_EXCEEDED",
                message=f"new file is {lines} lines (budget {NEW_FILE_BUDGET})",
                path=rel,
                context={"lines": lines, "budget": NEW_FILE_BUDGET},
            )
        return None
    if lines > entry.frozen_lines:
        return GateViolation(
            code="FILE_BUDGET_GREW",
            message=f"frozen file grew to {lines} lines (frozen {entry.frozen_lines}, shrink-only)",
            path=rel,
            context={"lines": lines, "frozen": entry.frozen_lines},
        )
    if lines < entry.frozen_lines:
        return f"shrink: {rel} {entry.frozen_lines} -> {lines} (ratchet the baseline down)"
    return None


def _check_packages(budget: Budget, measured: dict[str, int]) -> list[GateViolation]:
    """Per-package LOC draw — the sibling-file-accretion catch."""
    violations: list[GateViolation] = []
    for package, frozen in sorted(budget.packages.items()):
        total = 0
        new_files: list[str] = []
        for rel, lines in measured.items():
            entry = budget.files.get(rel)
            declared = entry is not None and entry.purpose is not None
            if declared or not _in_package(rel, package):
                continue
            total += lines
            if entry is None:
                new_files.append(rel)
        if total > frozen:
            violations.append(
                GateViolation(
                    code="PACKAGE_BUDGET_EXCEEDED",
                    message=f"package {package} is {total} lines (frozen {frozen}, shrink-only)",
                    path=package,
                    context={"lines": total, "frozen": frozen, "new_files": sorted(new_files)},
                )
            )
    return violations


def check_tree(root: Path, budget: Budget) -> tuple[list[GateViolation], list[str], int]:
    """Measure the tree; return (violations, notices, the count of files measured)."""
    measured = {
        path.relative_to(root).as_posix(): measure_file(path) for path in iter_python_files(root)
    }
    violations: list[GateViolation] = []
    notices: list[str] = []
    for rel, lines in sorted(measured.items()):
        verdict = _check_file(rel, lines, budget.files.get(rel))
        if isinstance(verdict, GateViolation):
            violations.append(verdict)
        elif isinstance(verdict, str):
            notices.append(verdict)
    for rel, entry in sorted(budget.files.items()):
        if entry.frozen_lines is not None and rel not in measured:
            notices.append(f"shrink: {rel} {entry.frozen_lines} -> deleted (drop from baseline)")
    violations.extend(_check_packages(budget, measured))
    return violations, notices, len(measured)


def init_tree(root: Path) -> dict[str, Any]:
    """Generate baseline data: files >500 frozen at measured size + package totals."""
    measured = {
        path.relative_to(root).as_posix(): measure_file(path) for path in iter_python_files(root)
    }
    files = {rel: lines for rel, lines in measured.items() if lines > NEW_FILE_BUDGET}
    package_dirs = {str(Path(rel).parent.as_posix()) for rel in files}
    packages = {
        package: sum(lines for rel, lines in measured.items() if _in_package(rel, package))
        for package in package_dirs
    }
    return {"files": dict(sorted(files.items())), "packages": dict(sorted(packages.items()))}


def _run_check(root: Path, config: Path) -> int:
    budget = load_budget(config)
    violations, notices, files = check_tree(root, budget)
    return print_verdict(
        "cf-file-budget",
        violations,
        notices=notices,
        measured=(
            f"— measured {files} file(s) against {len(budget.files)} frozen file entry(ies) "
            f"and {len(budget.packages)} frozen package budget(s)"
        ),
        evidence={
            "files_measured": files,
            "frozen_files": len(budget.files),
            "frozen_packages": len(budget.packages),
        },
        clean_summary="cf-file-budget: clean",
        fail_summary=f"cf-file-budget: FAIL ({len(violations)} violation(s))",
    )


def _run_init(root: Path, config: Path) -> int:
    data = init_tree(root)
    config.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(
        f"cf-file-budget: wrote {config} "
        f"({len(data['files'])} frozen files, {len(data['packages'])} packages)"
    )
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="cf-file-budget", description=__doc__)
    parser.add_argument("mode", choices=["check", "init"], help="check the tree / write baseline")
    parser.add_argument("--root", type=Path, default=Path(), help="repo root (default: cwd)")
    parser.add_argument(
        "--config", type=Path, default=None, help="baseline path (default: <root>/file-budget.json)"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Console entry point. 0 clean · 1 violations · 2 gate could not run."""
    args = _parse_args(argv)
    config = args.config if args.config is not None else args.root / "file-budget.json"
    try:
        if args.mode == "init":
            return _run_init(args.root, config)
        return _run_check(args.root, config)
    except GateError as err:
        print(json.dumps({"error": err.to_dict()}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
