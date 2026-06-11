"""cf-repo-config — the consumer's declared layout, committed never knobbed.

The quality gate carries ZERO workflow inputs by doctrine (a skip/mode input
is a neutering vector). A monorepo whose package lives in a subdir therefore
declares its layout in COMMITTED repo state instead — a ``[tool.cf-quality]``
table in ``pyproject.toml``, or in a dedicated ``.cf-quality.toml`` at the
repo root (one home only; both at once is ambiguous and fails)::

    [tool.cf-quality]
    source_root = "server/src"   # the tree mypy gates (and gate defaults)
    package_dir = "server"       # where the installable package lives

Anti-gaming (the empty-room rule): a DECLARED ``source_root`` must exist,
stay inside the repo, and hold at least one ``.py`` file — pointing the gauge
at an empty room is a violation (``GATE_CONFIG_INVALID``), never a pass. A
declared ``package_dir`` must exist and carry a ``pyproject.toml``. Unknown
keys fail typed: a typo'd key silently ignored would be drift, not a
decision.

Absent declaration keeps the historical discovery exactly: ``src/`` when
present, else the repo root. See DESIGN.md "Declared source roots".
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

from cf_quality.errors import GateError

CONFIG_FILENAME = ".cf-quality.toml"
_ALLOWED_KEYS = frozenset({"source_root", "package_dir"})

#: Directory names that are never first-party import surface when the source
#: root is the repo root itself (tests carry their own per-file-ignores
#: discipline; the rest is non-shipping). cf-exemptions shares this set for
#: its scan discovery — one gauge-block, never two lists drifting apart.
NON_SHIPPING_DIRS = frozenset(
    {
        "tests",
        "test",
        "docs",
        "examples",
        "scripts",
        "__pycache__",
        "node_modules",
        "build",
        "dist",
        "venv",
    }
)


@dataclass(frozen=True)
class RepoConfig:
    """The committed ``[tool.cf-quality]`` declaration; both fields optional."""

    source_root: str | None = None
    package_dir: str | None = None


def _config_error(message: str, context: dict[str, object]) -> GateError:
    return GateError(code="GATE_CONFIG_INVALID", message=message, context=context)


def _read_table(path: Path) -> dict[str, object] | None:
    """The ``[tool.cf-quality]`` table of one TOML file, or None when absent."""
    if not path.is_file():
        return None
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise _config_error(f"cannot parse {path.name}: {exc}", {"path": str(path)}) from exc
    tool = data.get("tool")
    if not isinstance(tool, dict):
        return None
    table = tool.get("cf-quality")
    if table is None:
        return None
    if not isinstance(table, dict):
        raise _config_error(
            f"[tool.cf-quality] in {path.name} must be a table", {"path": str(path)}
        )
    return table


def _string_field(table: dict[str, object], key: str, home: str) -> str | None:
    value = table.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise _config_error(
            f"[tool.cf-quality] {key} in {home} must be a non-empty string",
            {"home": home, "key": key, "value": repr(value)},
        )
    return value


def load(root: Path) -> RepoConfig:
    """The committed declaration of one repo; all-absent means 'use discovery'."""
    homes = {
        CONFIG_FILENAME: _read_table(root / CONFIG_FILENAME),
        "pyproject.toml": _read_table(root / "pyproject.toml"),
    }
    declared = {home: table for home, table in homes.items() if table is not None}
    if len(declared) > 1:
        raise _config_error(
            "[tool.cf-quality] is declared in BOTH .cf-quality.toml and "
            "pyproject.toml — one home only; two homes is ambiguity, not redundancy",
            {"homes": sorted(declared)},
        )
    if not declared:
        return RepoConfig()
    home, table = next(iter(declared.items()))
    unknown = sorted(set(table) - _ALLOWED_KEYS)
    if unknown:
        raise _config_error(
            f"unknown [tool.cf-quality] key(s) in {home}: {', '.join(unknown)} — "
            "a typo'd key silently ignored would be drift, not a decision",
            {"home": home, "unknown_keys": unknown},
        )
    return RepoConfig(
        source_root=_string_field(table, "source_root", home),
        package_dir=_string_field(table, "package_dir", home),
    )


def _declared_dir(root: Path, raw: str, key: str) -> Path:
    """A declared directory, validated to exist INSIDE the repo."""
    candidate = (root / raw).resolve()
    if not candidate.is_relative_to(root.resolve()):
        raise _config_error(
            f"declared {key} escapes the repo: {raw!r} — the gauge measures "
            "this repo, never a tree outside it",
            {"key": key, "declared": raw},
        )
    if not candidate.is_dir():
        raise _config_error(
            f"declared {key} does not exist: {raw!r}",
            {"key": key, "declared": raw},
        )
    return candidate


def resolve_source_root(root: Path) -> Path:
    """The tree the type gate measures: declared (validated) or discovered."""
    config = load(root)
    if config.source_root is None:
        src = root / "src"
        return src if src.is_dir() else root
    declared = _declared_dir(root, config.source_root, "source_root")
    if next(declared.rglob("*.py"), None) is None:
        raise _config_error(
            f"declared source_root holds zero .py files: {config.source_root!r} — "
            "pointing the gauge at an empty room is a violation, not a pass",
            {"source_root": config.source_root},
        )
    return declared


def resolve_package_dir(root: Path) -> Path:
    """Where the installable package lives: declared (validated) or the root."""
    config = load(root)
    if config.package_dir is None:
        return root
    declared = _declared_dir(root, config.package_dir, "package_dir")
    if not (declared / "pyproject.toml").is_file():
        raise _config_error(
            f"declared package_dir has no pyproject.toml: {config.package_dir!r} — "
            "an uninstallable package dir is the same empty room",
            {"package_dir": config.package_dir},
        )
    return declared


def first_party_packages(root: Path) -> list[str]:
    """The consumer's own top-level import names, derived from its source root.

    The shared ruff gauge cannot statically name every consumer's packages,
    and ruff's on-disk detection mis-files first-party imports that do not
    resolve on disk (a module authored RED before it exists, or tests
    addressed by package path) — the kit's I001 verdict then contradicts the
    consumer's legacy ``known-first-party``. The gate therefore derives the
    names from the consumer's OWN resolved source root: top-level packages
    (any directory holding Python — PEP 420 needs no ``__init__.py``) and
    top-level modules. At a repo-root source root the non-shipping
    directories are excluded; hidden entries never count.
    """
    source_root = resolve_source_root(root)
    at_repo_root = source_root.resolve() == root.resolve()
    names: set[str] = set()
    for child in source_root.iterdir():
        if child.name.startswith(".") or (at_repo_root and child.name in NON_SHIPPING_DIRS):
            continue
        if child.is_file() and child.suffix == ".py":
            names.add(child.stem)
        elif child.is_dir() and next(child.rglob("*.py"), None) is not None:
            names.add(child.name)
    return sorted(names)


def _relative_form(root: Path, target: Path) -> str:
    """Root-relative POSIX form for shell consumption ('.' for the root itself)."""
    return target.resolve().relative_to(root.resolve()).as_posix()


def _resolve_field(root: Path, field: str) -> str:
    """One CLI field's stdout form; first-party is a TOML/JSON array literal
    so the workflow can splice it into ``lint.isort.known-first-party=...``."""
    if field == "first-party":
        return json.dumps(first_party_packages(root))
    target = resolve_source_root(root) if field == "source-root" else resolve_package_dir(root)
    return _relative_form(root, target)


def main(argv: list[str] | None = None) -> int:
    """Exit 0 resolved (value on stdout) · 2 invalid declaration (typed, stderr)."""
    parser = argparse.ArgumentParser(
        prog="cf-repo-config",
        description="Resolve the consumer repo's declared layout ([tool.cf-quality]).",
    )
    parser.add_argument("field", choices=("source-root", "package-dir", "first-party"))
    parser.add_argument("--root", default=".", help="repo root (default: cwd)")
    args = parser.parse_args(argv)
    try:
        resolved = _resolve_field(Path(args.root), args.field)
    except GateError as error:
        print(json.dumps(error.to_dict(), ensure_ascii=False), file=sys.stderr)
        return 2
    print(resolved)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
