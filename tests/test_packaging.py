"""Packaging contract — the built WHEEL must carry the canonical sticky data.

The 9-repo mount wave surfaced the defect this file pins: the wheel omitted
the sticky-intro data file, so ``cf-sticky-check`` exited 2
(``STICKY_CANONICAL_MISSING``) under a NON-EDITABLE install — the exact mode
the CI gate uses (``pip install <kit-dir>``). Editable installs resolve the
source tree and masked it, so the oracle here is deliberately the harsh one:
build the wheel, install it into a CLEAN venv (no source tree on sys.path),
and run the console script against a fixture repo.
"""

from __future__ import annotations

import subprocess
import sys
import venv
import zipfile
from pathlib import Path

import pytest

from cf_quality.sticky_check import canonical_text

KIT_ROOT = Path(__file__).resolve().parents[1]


def _run(argv: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    # Fixed argv built from sys.executable / venv-internal absolute paths only —
    # no shell, no untrusted input. S603 is carved out for the tests context
    # (measured estate-wide 2026-06-10), so the suppression this call once
    # carried became an unused directive (RUF100) and was removed.
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, check=False)


@pytest.fixture(scope="module")
def built_wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The kit's wheel, built exactly as a non-editable install would build it."""
    wheel_dir = tmp_path_factory.mktemp("wheel")
    proc = _run(
        [sys.executable, "-m", "pip", "wheel", "--no-deps", "-w", str(wheel_dir), str(KIT_ROOT)]
    )
    assert proc.returncode == 0, f"wheel build failed:\n{proc.stdout}\n{proc.stderr}"
    wheels = list(wheel_dir.glob("candyfactory_quality-*.whl"))
    assert len(wheels) == 1, f"expected exactly one wheel, found {wheels}"
    return wheels[0]


@pytest.fixture(scope="module")
def clean_install(built_wheel: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A clean venv holding ONLY the wheel — no source tree to fall back on."""
    venv_dir = tmp_path_factory.mktemp("cleanvenv")
    venv.create(venv_dir, with_pip=True)
    pip = venv_dir / "bin" / "pip"
    proc = _run([str(pip), "install", "--quiet", str(built_wheel)])
    assert proc.returncode == 0, f"wheel install failed:\n{proc.stdout}\n{proc.stderr}"
    return venv_dir


def test_wheel_ships_the_canonical_sticky_data(built_wheel: Path) -> None:
    with zipfile.ZipFile(built_wheel) as wheel:
        names = wheel.namelist()
    assert "cf_quality/data/sticky-intro.md" in names, (
        f"the wheel must package the canonical sticky-intro data file; contents: {names}"
    )


def test_sticky_check_works_from_a_clean_wheel_install(clean_install: Path, tmp_path: Path) -> None:
    # The regression: under a non-editable install (CI's exact mode) the gauge
    # must still find its OWN canonical copy — exit 0 on a mounted fixture,
    # never exit 2 STICKY_CANONICAL_MISSING.
    fixture = tmp_path / "consumer"
    fixture.mkdir()
    (fixture / "CLAUDE.md").write_text(canonical_text(), encoding="utf-8")
    script = clean_install / "bin" / "cf-sticky-check"
    proc = _run([str(script), "check", str(fixture)])
    assert "STICKY_CANONICAL_MISSING" not in proc.stderr, (
        f"the wheel lost its canonical data file:\n{proc.stderr}"
    )
    assert proc.returncode == 0, f"exit {proc.returncode}:\n{proc.stdout}\n{proc.stderr}"


def test_clean_wheel_install_reports_absence_not_gate_failure(
    clean_install: Path, tmp_path: Path
) -> None:
    # Violation reporting (exit 1) must also ride the packaged data, so a
    # lawless fixture draws STICKY_INTRO_ABSENT — not a gate crash (exit 2).
    fixture = tmp_path / "consumer"
    fixture.mkdir()
    (fixture / "CLAUDE.md").write_text("# no law here\n", encoding="utf-8")
    script = clean_install / "bin" / "cf-sticky-check"
    proc = _run([str(script), "check", str(fixture)])
    assert proc.returncode == 1, f"exit {proc.returncode}:\n{proc.stdout}\n{proc.stderr}"
    assert "STICKY_INTRO_ABSENT" in proc.stdout
