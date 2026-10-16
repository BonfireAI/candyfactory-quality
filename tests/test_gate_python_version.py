"""Rods for the gate's consumer-declared Python version.

The gate accepts NO inputs, so a consumer moves its gated Python by COMMITTING a
``.python-version`` file at its repo root (committed consumer state, never a
caller knob). A resolver step, run in the consumer tree after the consumer
checkout, reads that file and feeds ``actions/setup-python`` through
``${{ steps.<id>.outputs.version }}``. No file means the backward-compatible
default ``3.12``; a committed file that is empty or malformed is REFUSED, never
quietly downgraded to the default.

The resolver is discovered by following setup-python's expression (never a
hardcoded step name), and its ``run`` script is lifted from the parsed YAML and
executed exactly as the runner executes a bash step, against a ``tmp_path``
consumer root.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from test_workflows import GATE_PATH, _load, _steps

STEP_OUTPUT_EXPR = re.compile(r"^\$\{\{\s*steps\.([A-Za-z0-9_-]+)\.outputs\.version\s*\}\}$")
DEFAULT_VERSION = "3.12"
CONSUMER_PATH = "repo"
REFUSAL_PREFIX = "::error::quality-gate refused:"
ACCEPTED_GRAMMAR = r"^3\.[0-9]+(\.[0-9]+)?$"
RAW_BYTES = re.compile(r"\(raw bytes: (?P<raw>.*)\) \S+ accepted grammar is ")


def _gate_job() -> dict[str, Any]:
    job = _load(GATE_PATH)["jobs"]["gate"]
    assert isinstance(job, dict), "the gate job did not parse to a mapping"
    return job


def _gate_steps() -> list[dict[str, Any]]:
    return _steps(_load(GATE_PATH), "gate")


def _setup_python_index(steps: list[dict[str, Any]]) -> int:
    hits = [i for i, s in enumerate(steps) if "setup-python" in str(s.get("uses", ""))]
    assert len(hits) == 1, f"exactly one setup-python step expected, found {len(hits)}"
    return hits[0]


def _resolver_index(steps: list[dict[str, Any]]) -> int:
    setup = steps[_setup_python_index(steps)]
    value = str(setup.get("with", {}).get("python-version", ""))
    match = STEP_OUTPUT_EXPR.match(value.strip())
    assert match, (
        "no resolver step feeds setup-python: python-version is "
        f"{value!r}, not ${{{{ steps.<id>.outputs.version }}}}"
    )
    step_id = match.group(1)
    hits = [i for i, s in enumerate(steps) if s.get("id") == step_id]
    assert len(hits) == 1, f"steps.{step_id} feeds setup-python; {len(hits)} steps carry that id"
    return hits[0]


def _resolver_script() -> str:
    steps = _gate_steps()
    script = steps[_resolver_index(steps)].get("run")
    assert isinstance(script, str) and script.strip(), "the resolver step has no run script"
    return script


def _consumer_root(tmp_path: Path) -> Path:
    consumer = tmp_path / CONSUMER_PATH
    consumer.mkdir()
    return consumer


def _run_resolver(tmp_path: Path, content: str | None) -> tuple[int, str, list[str]]:
    """Run the resolver against a consumer root; return (exit, stdout+stderr, version lines)."""
    consumer = _consumer_root(tmp_path)
    if content is not None:
        (consumer / ".python-version").write_bytes(content.encode("utf-8"))
    return _execute_resolver(tmp_path, consumer)


def _execute_resolver(tmp_path: Path, consumer: Path) -> tuple[int, str, list[str]]:
    """Execute the lifted resolver script in an already-built consumer root."""
    script = _resolver_script()
    bash = shutil.which("bash")
    assert bash is not None, "bash is required to execute the resolver step as the runner does"
    script_file = tmp_path / "resolver.sh"
    script_file.write_text(script, encoding="utf-8")
    output = tmp_path / "github_output"
    output.write_text("", encoding="utf-8")
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(tmp_path),
        "GITHUB_OUTPUT": str(output),
        "GITHUB_WORKSPACE": str(tmp_path),
    }
    done = subprocess.run(
        [bash, "--noprofile", "--norc", "-eo", "pipefail", str(script_file)],
        cwd=consumer,
        env=env,
        capture_output=True,
        encoding="utf-8",
        check=False,
    )
    lines = output.read_text(encoding="utf-8").splitlines()
    versions = [ln for ln in lines if ln.startswith("version=")]
    return done.returncode, done.stdout + done.stderr, versions


def _refusal_lines(combined: str) -> list[str]:
    """The typed refusal annotation line(s) in the resolver's combined output."""
    return [ln for ln in combined.splitlines() if ln.startswith(REFUSAL_PREFIX)]


def _single_refusal(combined: str) -> str:
    refusals = _refusal_lines(combined)
    assert len(refusals) == 1, (
        f"exactly one typed refusal line expected, got {refusals}:\n{combined}"
    )
    line = refusals[0]
    assert ACCEPTED_GRAMMAR in line, f"the refusal must state the accepted grammar: {line!r}"
    return line


def _raw_bytes_segment(line: str) -> str:
    """The shell-quoted ``raw bytes:`` segment of a refusal line (fixed text excluded)."""
    match = RAW_BYTES.search(line)
    assert match, f"the refusal carries no 'raw bytes:' segment: {line!r}"
    return match.group("raw")


# --- structure ----------------------------------------------------------------


def test_setup_python_version_comes_from_an_earlier_resolver_step() -> None:
    steps = _gate_steps()
    setup = _setup_python_index(steps)
    resolver = _resolver_index(steps)
    assert resolver < setup, f"resolver (step {resolver}) must precede setup-python ({setup})"


def test_resolver_runs_in_consumer_tree_after_consumer_checkout() -> None:
    steps = _gate_steps()
    checkouts = [
        i
        for i, s in enumerate(steps)
        if "actions/checkout" in str(s.get("uses", ""))
        and s.get("with", {}).get("path") == CONSUMER_PATH
    ]
    assert len(checkouts) == 1, f"one consumer checkout expected, found {len(checkouts)}"
    resolver = _resolver_index(steps)
    assert checkouts[0] < resolver, (
        f"resolver (step {resolver}) must follow the consumer checkout (step {checkouts[0]})"
    )
    default_wd = _gate_job().get("defaults", {}).get("run", {}).get("working-directory")
    assert default_wd == CONSUMER_PATH, f"job default working-directory is {default_wd!r}"
    own_wd = steps[resolver].get("working-directory", CONSUMER_PATH)
    assert own_wd == CONSUMER_PATH, f"resolver overrides working-directory to {own_wd!r}"


def test_setup_python_step_name_does_not_claim_312() -> None:
    steps = _gate_steps()
    name = str(steps[_setup_python_index(steps)].get("name", ""))
    assert "3.12" not in name, f"setup-python step name still claims a literal: {name!r}"


# --- behaviour: accepted declarations ------------------------------------------


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        pytest.param("3.14\n", "3.14", id="newline-terminated"),
        pytest.param("3.14.8", "3.14.8", id="patch-no-newline"),
        pytest.param("3.14\r\n", "3.14", id="crlf-terminated"),
        pytest.param("  3.14  \n", "3.14", id="surrounding-spaces"),
    ],
)
def test_resolver_accepts_committed_version(tmp_path: Path, content: str, expected: str) -> None:
    code, combined, versions = _run_resolver(tmp_path, content)
    assert code == 0, f"resolver refused {content!r}:\n{combined}"
    assert versions == [f"version={expected}"], f"GITHUB_OUTPUT version lines: {versions}"


def test_resolver_defaults_to_312_without_python_version_file(tmp_path: Path) -> None:
    code, combined, versions = _run_resolver(tmp_path, None)
    assert code == 0, f"resolver failed with no .python-version:\n{combined}"
    assert versions == [f"version={DEFAULT_VERSION}"], f"GITHUB_OUTPUT version lines: {versions}"
    notices = [ln for ln in combined.splitlines() if ln.startswith("::notice::")]
    assert len(notices) == 1, (
        f"the default must be announced by one ::notice:: line, got {notices}:\n{combined}"
    )
    notice = notices[0]
    assert DEFAULT_VERSION in notice, f"the ::notice:: must name the default it chose: {notice!r}"
    assert ".python-version" in notice, (
        f"the ::notice:: must name the absent .python-version: {notice!r}"
    )
    assert _refusal_lines(combined) == [], f"the default path must not refuse:\n{combined}"


# --- behaviour: refused declarations -------------------------------------------
# The expected ``raw bytes:`` segment is bash's ``printf '%q'`` rendering of the
# committed bytes, so the naming check reads only the quoted value, never the
# fixed message text (which itself contains 3.12 and 3.14.8).


@pytest.mark.parametrize(
    ("content", "rendered"),
    [
        pytest.param("", "''", id="empty"),
        pytest.param("  \n\t\n", r"$'  \n\t\n'", id="whitespace-only"),
    ],
)
def test_resolver_refuses_blank_python_version_file(
    tmp_path: Path, content: str, rendered: str
) -> None:
    code, combined, versions = _run_resolver(tmp_path, content)
    assert code != 0, f"a committed blank file must be refused, got exit 0:\n{combined}"
    assert versions == [], f"a refusal must write no version= line, wrote {versions}"
    line = _single_refusal(combined)
    assert _raw_bytes_segment(line) == rendered, f"the refusal must show the raw bytes: {line!r}"


@pytest.mark.parametrize(
    ("content", "rendered"),
    [
        pytest.param("python3.14", "python3.14", id="python3.14"),
        pytest.param("3.x", "3.x", id="3.x"),
        pytest.param("latest", "latest", id="latest"),
        pytest.param("3", "3", id="3"),
        pytest.param("7.2", "7.2", id="7.2"),
        pytest.param("3.99.1rc", "3.99.1rc", id="3.99.1rc"),
        pytest.param("3.14.8a1", "3.14.8a1", id="3.14.8a1"),
        pytest.param("3.14\n3.13\n", r"$'3.14\n3.13\n'", id="two-lines"),
    ],
)
def test_resolver_refuses_malformed_python_version(
    tmp_path: Path, content: str, rendered: str
) -> None:
    code, combined, versions = _run_resolver(tmp_path, content)
    assert code != 0, f"malformed {content!r} must be refused, got exit 0:\n{combined}"
    assert versions == [], f"a refusal must write no version= line, wrote {versions}"
    line = _single_refusal(combined)
    assert _raw_bytes_segment(line) == rendered, (
        f"the refusal must name the offending value {content!r} as {rendered}: {line!r}"
    )


def _dangling_symlink(consumer: Path) -> None:
    (consumer / ".python-version").symlink_to(consumer / "no-such-target")


def _directory(consumer: Path) -> None:
    (consumer / ".python-version").mkdir()


@pytest.mark.parametrize(
    "build",
    [
        pytest.param(_dangling_symlink, id="dangling-symlink"),
        pytest.param(_directory, id="directory"),
    ],
)
def test_resolver_fails_and_never_defaults_on_unreadable_python_version(
    tmp_path: Path, build: Callable[[Path], None]
) -> None:
    # Only a nonzero exit and no version= line are asserted: the unreadable path
    # dies untyped (cat under bash -e). A typed refusal here is OWED, not claimed.
    consumer = _consumer_root(tmp_path)
    build(consumer)
    code, combined, versions = _execute_resolver(tmp_path, consumer)
    assert code != 0, f"an unreadable .python-version must fail, got exit 0:\n{combined}"
    assert versions == [], f"it must never fall back to the default, wrote {versions}"
