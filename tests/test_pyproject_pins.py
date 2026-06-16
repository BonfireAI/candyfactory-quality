"""Guard: the [dev] gauge battery is pinned EXACTLY, and the lockfile pins it too.

A floating gauge tool (ruff/mypy/complexipy) makes the gate verdict
NON-DETERMINISTIC — the grade would drift under the code as the tool updates.
This is the determinism leg of the gate-observability epic (BON-1661 / BON-1665):
the verdict must be a pure function of the code, not of whatever happened to
resolve at install time.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_PYPROJECT = _ROOT / "pyproject.toml"
_LOCKFILE = _ROOT / "requirements-lock.txt"

_BATTERY = ("ruff", "mypy", "mypy-baseline", "complexipy", "pytest", "import-linter")


def _dev_deps() -> list[str]:
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    return data["project"]["optional-dependencies"]["dev"]


def test_every_dev_dependency_is_exactly_pinned() -> None:
    unpinned = [dep for dep in _dev_deps() if "==" not in dep]
    assert not unpinned, f"[dev] deps must be == pinned for a deterministic gauge; floating: {unpinned}"


def test_lockfile_is_committed_and_pins_the_battery() -> None:
    assert _LOCKFILE.is_file(), "requirements-lock.txt must be committed (the transitive freeze CI installs)"
    locked = _LOCKFILE.read_text(encoding="utf-8").lower()
    missing = [tool for tool in _BATTERY if f"{tool}==" not in locked]
    assert not missing, f"requirements-lock.txt missing pinned gauge tools: {missing}"
