"""complexipy as an instrument — the preconditions that make its census trustworthy.

``tests/test_complexipy_snapshot.py`` pins the RATCHET: given a floor and a census,
which verdict. This file pins everything that must be true before that census may
be believed at all, which is where two refuters found the first cut of the fix
still defeatable:

- **the consumer's own complexipy config.** ``--snapshot-ignore`` disarms the
  watermark compare's rewrite, but ``handle_snapshot_file_creation``
  (``main.py:323``) is a SEPARATE branch driven by ``snapshot-create``, which the
  kit passes no CLI value for — so ``[tool.complexipy] snapshot-create = true``
  wins (``utils/toml.py:235-240``) and both measurement runs rewrite the floor
  while the gate grades the pre-write bytes it already read. ``--snapshot-create``
  has no negating secondary name (``main.py:97-102``), so argv cannot override it:
  the only honest mechanism is to READ that config and REFUSE. Two more config
  keys defeat the run the same way — ``quiet`` (rejected beside ``--plain``, exit
  2, empty census) and ``output-format`` / the legacy ``output-*`` flags (a report
  file written into the consumer's tree plus ``Results saved at ...`` and
  ``Deprecated: ...`` printed onto stdout BEFORE the census);
- **the exit code and stderr**, which used to be decoration and a discard. Every
  tool-side failure was therefore re-attributed to the repo with its reason
  deleted;
- **the parse's own hazards** — a duplicated ``(path, name)`` key, a non-UTF-8
  stream the PARENT decodes, and rich's dumb-terminal short circuit that ignores
  ``COLUMNS`` outright;
- **the key itself**: ``complexipy_floor._normalized_path`` is a line-for-line copy
  of ``complexipy.utils.output.normalize_path``, and the kit ships no
  ``MIRRORS.md`` for ``cf-mirror-check`` to gate. The rod here calls the INSTALLED
  function, which is a stronger guard than a declaration nobody checks: a 5.7.0
  change to that join fails the suite instead of re-keying every watermark into a
  ``NEW_OFFENDER``.
"""

from __future__ import annotations

import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest
from complexipy.utils.output import normalize_path
from test_complexipy_snapshot import _census, _light, _measured, _snapshot, _stage_verdict
from test_gate_runner import _layout, _write

from cf_quality import gate_runner
from cf_quality.complexipy_floor import _normalized_path
from cf_quality.complexipy_measure import audit_config, parse_census
from cf_quality.errors import GateError


def _config_verdict(
    root: Path, monkeypatch: pytest.MonkeyPatch, config: str, body: str
) -> GateError:
    """Mount a consumer complexipy config on an otherwise CLEAN repo, return the refusal."""
    _write(root, config, body)
    _snapshot(root)
    verdict = _stage_verdict(root, monkeypatch, _measured(_census(_light(root)), ""))
    assert verdict.error is not None, "a healthy census must not rescue a defeating config"
    assert verdict.exit_code == 2
    return verdict.error


# --- BLOCKER 1: a consumer config that defeats the measurement ----------------


@pytest.mark.parametrize(
    ("config", "body", "key"),
    [
        # THE one that re-opens the write. `--snapshot-ignore` does not touch
        # handle_snapshot_file_creation, and no CLI flag can negate this key.
        ("complexipy.toml", "snapshot-create = true\n", "snapshot-create"),
        ("pyproject.toml", "[tool.complexipy]\nsnapshot-create = true\n", "snapshot-create"),
        (".complexipy.toml", "snapshot-create = true\n", "snapshot-create"),
        # BadParameter beside --plain: exit 2, empty stdout. Un-audited, the gate
        # reported GATE_COMPLEXIPY_MEASURED_NOTHING and blamed the repo.
        ("complexipy.toml", "quiet = true\n", "quiet"),
        # A report file written into the consumer's tree, and two unguarded
        # console.print lines landing on stdout BEFORE the census.
        ("complexipy.toml", 'output-format = ["json"]\n', "output-format"),
        ("complexipy.toml", "output-json = true\n", "output-json"),
        ("complexipy.toml", 'output = "reports/"\n', "output"),
        # Would narrow the CENSUS run to offenders, blinding the surface audit and
        # the per-function audit that reasons on "still present, merely simpler".
        ("complexipy.toml", "failed = true\n", "failed"),
        ("complexipy.toml", 'details = "low"\n', "details"),
        # Decouples the exit code from the threshold verdict, which is the second
        # vacuity leg's only witness.
        ("complexipy.toml", "ignore-complexity = true\n", "ignore-complexity"),
        # Prints ignore-comment locations onto the census stream.
        ("complexipy.toml", "report-ignored = true\n", "report-ignored"),
        # --ratchet with no --diff exits 2 before measuring anything.
        ("complexipy.toml", "ratchet = true\n", "ratchet"),
    ],
)
def test_consumer_config_that_defeats_the_measurement_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config: str, body: str, key: str
) -> None:
    error = _config_verdict(tmp_path, monkeypatch, config, body)

    assert error.code == "GATE_COMPLEXIPY_CONFIG_DEFEATS_MEASUREMENT"
    assert error.context["keys"] == [key], "the refusal names the KEY, not just the file"
    assert error.context["config"] == config, "and the file it found it in"
    assert key in error.message and config in error.message


@pytest.mark.parametrize(
    ("config", "body"),
    [
        # The consumer's own threshold and surface authorities. The kit declares NO
        # budget of its own (measurement_argv carries no -mx), so refusing these
        # would break the very neutrality that keeps a baselined band from reading
        # as new — and Blocker 2's closure is threshold-free precisely so it can
        # stay honoured.
        ("complexipy.toml", "max-complexity-allowed = 25\n"),
        ("complexipy.toml", 'exclude = ["vendor"]\n'),
        # These only ever make the census LARGER, or reorder it (max() per key).
        ("complexipy.toml", "no-ignore = true\n"),
        ("complexipy.toml", "check-script = true\n"),
        ("complexipy.toml", 'sort = "desc"\n'),
        # Value-sensitive: a key at its harmless value is not a defeating key, and
        # a false refusal costs a consumer a red board for nothing.
        ("complexipy.toml", "snapshot-create = false\n"),
        ("complexipy.toml", 'details = "high"\n'),
        # pyproject.toml with no [tool.complexipy] is not a complexipy config.
        ("pyproject.toml", "[tool.other]\nsnapshot-create = true\n"),
    ],
)
def test_legitimate_consumer_config_is_honoured_not_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config: str, body: str
) -> None:
    _write(tmp_path, config, body)
    _snapshot(tmp_path)

    verdict = _stage_verdict(tmp_path, monkeypatch, _measured(_census(_light(tmp_path)), ""))

    assert verdict.passed, f"{config} carrying {body!r} must not be refused"


def test_config_search_order_mirrors_the_tools_own(tmp_path: Path) -> None:
    # utils/toml.py:135-148 stops at the FIRST file that yields a table, and for a
    # non-pyproject name that includes an EMPTY document — so an empty
    # complexipy.toml shadows a populated pyproject.toml. Audit a different file
    # than the tool reads and the audit is theatre.
    _write(tmp_path, "pyproject.toml", "[tool.complexipy]\nsnapshot-create = true\n")
    _write(tmp_path, ".complexipy.toml", "")

    assert audit_config(tmp_path) == ".complexipy.toml", "the shadowing file is the one in force"

    _write(tmp_path, "complexipy.toml", "")
    assert audit_config(tmp_path) == "complexipy.toml", "complexipy.toml outranks both"


def test_unreadable_complexipy_config_is_refused_not_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An unparseable config is not an absent config: the tool would crash on it,
    # and treating it as "no config" would leave the write-free claim unaudited.
    error = _config_verdict(tmp_path, monkeypatch, "complexipy.toml", "snapshot-create = tru\n")

    assert error.code == "GATE_COMPLEXIPY_CONFIG_UNREADABLE"


def test_non_utf8_complexipy_config_refuses_instead_of_crashing_the_battery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # UnicodeDecodeError is a ValueError, not a TOMLDecodeError — catching only the
    # latter loses the whole 12-stage board to a traceback.
    (tmp_path / "complexipy.toml").write_bytes(b'paths = "\xff\xfe"\n')
    _snapshot(tmp_path)

    verdict = _stage_verdict(tmp_path, monkeypatch, _measured(_census(_light(tmp_path)), ""))

    assert verdict.error is not None and verdict.error.code == "GATE_COMPLEXIPY_CONFIG_UNREADABLE"


def test_a_clean_repo_reports_which_config_was_in_force(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A PASS must say what it measured through — "no complexipy config" and "a
    # config we never looked at" are the same verdict otherwise.
    _write(tmp_path, "complexipy.toml", "max-complexity-allowed = 25\n")
    _snapshot(tmp_path)

    verdict = _stage_verdict(tmp_path, monkeypatch, _measured(_census(_light(tmp_path)), ""))

    assert verdict.passed
    assert verdict.evidence["complexipy_config"] == "complexipy.toml"


# --- DEFECT 3 / BLOCKER 2(b): the exit code and stderr are evidence -----------


def test_nonzero_exit_with_an_empty_census_refuses_and_carries_the_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Exit 1 means "some function is over threshold" (utils/output.py:44 + 234-241),
    # which no run that printed zero functions can be reporting. This is also the
    # OFFENDER run's vacuity leg — one rule, both runs. Before this the gate
    # reported GATE_COMPLEXIPY_MEASURED_NOTHING and charged it to the repo, with
    # complexipy's stderr thrown away.
    _write(tmp_path, "src/heavy.py", "def heavy():\n    return 1\n")
    _snapshot(tmp_path)
    responses = _measured("", "")
    responses["complexipy"] = (1, "", "Traceback: the instrument fell over\n")

    verdict = _stage_verdict(tmp_path, monkeypatch, responses)

    assert verdict.error is not None
    assert verdict.error.code == "GATE_COMPLEXIPY_INSTRUMENT_FAILED"
    assert verdict.error.context["exit_code"] == 1
    assert verdict.error.context["stderr"] == ["Traceback: the instrument fell over"]


def test_an_exit_code_that_is_not_a_verdict_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 0 and 1 are the tool's only verdicts; 2 is typer declining to run
    # (main.py:748 BadParameter, main.py:726-729 validate_ratchet). A census that
    # LOOKS parseable beside exit 2 is still a run that did not do its job.
    _snapshot(tmp_path)
    responses = _measured(_census(_light(tmp_path)), "")
    responses["complexipy"] = (2, _census(_light(tmp_path)), "Error: --ratchet requires --diff\n")

    verdict = _stage_verdict(tmp_path, monkeypatch, responses)

    assert verdict.error is not None
    assert verdict.error.code == "GATE_COMPLEXIPY_INSTRUMENT_FAILED"
    assert verdict.error.context["exit_code"] == 2


def test_the_offender_run_exit_code_is_cross_checked_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The census is healthy and the floor is met, so nothing else has anything to
    # say: only the offender run's own contradiction is left to catch it.
    _write(tmp_path, "src/heavy.py", "def heavy():\n    return 1\n")
    _snapshot(tmp_path, ("src/heavy.py", "heavy", 33))
    responses = _measured(_census(("src/heavy.py", "heavy", 33)), "")
    responses["complexipy-offenders"] = (1, "", "")

    verdict = _stage_verdict(tmp_path, monkeypatch, responses)

    assert verdict.error is not None
    assert verdict.error.code == "GATE_COMPLEXIPY_INSTRUMENT_FAILED"
    assert verdict.error.context["offenders_only"] is True


def test_exit_one_with_a_real_census_is_the_legitimate_offenders_exist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The control rod on the rod above: exit 1 is the NORMAL state of a repo
    # carrying a baselined floor, so the triage must not turn it into a refusal.
    _write(tmp_path, "src/heavy.py", "def heavy():\n    return 1\n")
    _snapshot(tmp_path, ("src/heavy.py", "heavy", 33))
    rows = _census(("src/heavy.py", "heavy", 33))
    responses = _measured(rows, rows)
    responses["complexipy"] = (1, rows, "")

    verdict = _stage_verdict(tmp_path, monkeypatch, responses)

    assert verdict.passed, "a baselined floor at its watermark is green, exit 1 or not"


def test_output_that_does_not_decode_refuses_instead_of_crashing_the_battery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # subprocess text=True decodes in the PARENT, by the PARENT's locale —
    # PYTHONIOENCODING pins the child only. UnicodeDecodeError is a ValueError, so
    # it escaped _exec (OSError only) and _run_stage (GateError only) and took the
    # whole board down with a traceback.
    _snapshot(tmp_path)

    def exploding_exec(
        argv: list[str], cwd: Path, env: Mapping[str, str], *, stdin: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")

    monkeypatch.setattr(gate_runner, "_tool", lambda name: Path("/fake") / name)
    monkeypatch.setattr(gate_runner, "_exec", exploding_exec)
    stage = gate_runner.Stage("complexipy", gate_runner._complexipy)

    verdict = gate_runner._run_stage(stage, _layout(tmp_path), {})

    assert verdict is not None and verdict.error is not None
    assert verdict.error.code == "GATE_COMPLEXIPY_OUTPUT_UNDECODABLE"
    assert verdict.exit_code == 2


# --- DEFECT 10: duplicate keys, and the count that must not collapse ----------


def test_duplicate_function_keys_aggregate_max_and_still_count_every_row() -> None:
    # Live on a real consumer: 681 census rows collapse to 680 keys, because an
    # @overload chain (or an `if sys.platform:` redefinition) repeats a
    # (path, name) pair. Last-writer-wins with sort = "desc" would keep the LOW
    # value here, dropping a regression complexipy's own compare — which iterates
    # its LIST, not a map — would catch. max() is order-independent, which is why
    # the fix is aggregation and NOT pinning --sort: a pinned flag would have to
    # survive in the argv for the rule to hold.
    census = parse_census("src/m.py f 40\nsrc/m.py f 4\nsrc/m.py g 7\n")

    assert census.functions == {("src/m.py", "f"): 40, ("src/m.py", "g"): 7}
    assert census.rows == 3, "the count is ROWS: keys under-report what was measured"


# --- the declared mirror, pinned against the INSTALLED tool -------------------


@pytest.mark.parametrize(
    ("path", "file_name"),
    [
        ("src/pkg/mod.py", "mod.py"),
        ("src/pkg", "mod.py"),
        ("src/pkg/", "mod.py"),
        ("", "mod.py"),
        ("mod.py", "mod.py"),
        ("src/odd dir/mod.py", "mod.py"),
    ],
)
def test_snapshot_key_join_mirrors_the_installed_normalize_path(path: str, file_name: str) -> None:
    # The kit ships no MIRRORS.md, so cf-mirror-check (skip-if-absent) gates
    # nothing here. This rod is the stronger guard: it calls complexipy's OWN
    # function, so a 5.7.0 change to the join fails the suite instead of silently
    # re-keying every committed watermark into a brand-new offender.
    assert _normalized_path(path, file_name) == normalize_path(path, file_name)


# --- the env pins (migrated here: they are instrument wiring, not ratchet) -----


def test_measurement_runs_pin_columns_and_term_so_the_census_cannot_wrap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # rich wraps at 80 columns when stdout is not a terminal, and a wrapped census
    # row is an UNPARSEABLE census row — the gate would refuse a healthy repo. But
    # COLUMNS is only load-bearing once TERM is: rich/console.py:1015-1016 returns
    # a HARD 80x25 and never reads COLUMNS at all when is_dumb_terminal, which is
    # `is_terminal and TERM in ("dumb", "unknown")` (rich/console.py:986-988).
    # FORCE_COLOR and TTY_COMPATIBLE are the two names that force is_terminal True
    # over a pipe (rich/console.py:955-963), so the overlay clears them.
    row = _light(tmp_path)
    _snapshot(tmp_path)
    seen: list[dict[str, str]] = []

    def recording_exec(
        argv: list[str], cwd: Path, env: Mapping[str, str], *, stdin: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        seen.append(dict(env))
        return subprocess.CompletedProcess(argv, 0, _census(row), "")

    monkeypatch.setattr(gate_runner, "_tool", lambda name: Path("/fake") / name)
    monkeypatch.setattr(gate_runner, "_exec", recording_exec)
    hostile = {"PATH": "/usr/bin", "TERM": "dumb", "FORCE_COLOR": "1", "TTY_COMPATIBLE": "1"}

    gate_runner._complexipy(_layout(tmp_path), hostile)

    assert len(seen) == 2, "the census run and the offender run"
    for env in seen:
        assert int(env["COLUMNS"]) >= 1000, "an 80-column wrap would break the census parse"
        assert env["PYTHONIOENCODING"] == "utf-8", "the census decodes UTF-8, never by locale"
        assert env["TERM"] not in ("dumb", "unknown"), "a dumb TERM ignores COLUMNS outright"
        assert "FORCE_COLOR" not in env and "TTY_COMPATIBLE" not in env, "no forced tty"
        assert env["PATH"] == "/usr/bin", "the caller's environment survives the overlay"
