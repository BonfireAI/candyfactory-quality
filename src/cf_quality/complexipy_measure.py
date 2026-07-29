"""complexipy demoted to a measuring instrument — audited, invoked write-free, read.

**Why this sits apart from the ratchet.** The ratchet
(:mod:`cf_quality.complexipy_ratchet`) is a pure function of (committed floor,
measured census). Everything that must be TRUE before that function may be
trusted lives here: the consumer's own complexipy configuration, the argv, the
two subprocess runs, and the parse of what came back. One responsibility —
"produce a census the ratchet may reason over, or refuse" — and the ratchet
never touches a subprocess.

**The write-free claim, and its real precondition.** ``--snapshot-ignore`` alone
does NOT make the run write-free; that was the defect two refuters found in the
first cut of this fix, and it is the same defect the whole rung exists to
remove — a false invariant in a docstring. In the pinned ``complexipy==5.6.0``
exactly two callers reach ``create_snapshot_file``:

1. ``complexipy/utils/snapshot.py:85`` — ``handle_snapshot_watermark``'s
   no-violation branch, i.e. the compare's SUCCESS path. ``--snapshot-ignore``
   switches that off (``main.py:332``: ``should_run_snapshot_watermark =
   snapshot_file_exists and not snapshot_ignore``) and a consumer cannot switch
   it back on, because the CLI value wins (``utils/toml.py:179``:
   ``get_argument_value`` returns ``arg_value`` whenever it is not None).
2. ``main.py:323`` — ``handle_snapshot_file_creation``, an ENTIRELY separate
   branch driven by ``snapshot-create``, which ``--snapshot-ignore`` does not
   touch. The kit passes no CLI value for it, so ``utils/toml.py:235-240``
   resolves it from the consumer's ``complexipy.toml`` / ``.complexipy.toml`` /
   ``[tool.complexipy]``; and ``--snapshot-create`` is declared with no negating
   secondary name (``main.py:97-102``), so argv CANNOT force it off.

So the argv's guarantee holds only while the consumer's config carries no
``snapshot-create``, and :func:`audit_config` is what makes it hold: it reads
the SAME file the tool will read, in the tool's own search order, and REFUSES
the stage when a key would let the run write the floor, silence the census, or
print anything else onto the census stream. A typed refusal naming the key and
the file cannot be silently wrong. A cwd or env trick could be, and was
rejected for cause: ``main.py:66-67`` resolves the config, ``main.py:321`` the
snapshot path, and ``main.py:308-310`` every reported path from the SAME
``os.getcwd()``, so moving the cwd to hide the config would re-key the entire
census and break the floor comparison — and would silently drop the LEGITIMATE
``max-complexity-allowed`` this design deliberately honours.

**What is deliberately NOT refused.** ``max-complexity-allowed`` and ``exclude``
are the consumer's own threshold and surface authorities; the kit declares no
budget of its own here, because a second authority would flag a baselined band
as a new offender. ``no-ignore`` and ``check-script`` only ever make the census
LARGER. ``sort`` reorders rows only, and :func:`parse_census` aggregates
``max()`` per key, so no order can change the result.

**Reading the instrument.** Three channels come back and all three are evidence:
stdout (the census), the exit code, and stderr. This argv was measured over a
142-file tree emitting 681 census rows and **0 bytes of stderr**, so any stderr
at all rides the refusal context. The exit code is corroboration, never the
grade: with the compare disarmed, ``main.py:756-767 resolve_final_success``
reduces to ``has_success and valid_paths``, and ``has_success`` is ``not
failing_functions`` (``utils/output.py:44``), which is filled for every function
over the resolved threshold whether or not ``--failed`` was passed
(``utils/output.py:234-241``). Exit 1 is therefore the legitimate "some function
is over threshold"; exit 1 with an EMPTY census is a contradiction; any other
non-zero code is the tool declining to run.
"""

from __future__ import annotations

import subprocess
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from cf_quality.errors import GateError

#: ``(repo-relative file, function name)`` — the identity a watermark is keyed by.
#: complexipy keys on ``(path, file_name, name)``; ``path`` already carries the
#: file name in its own output, so the joined form is the same identity.
FunctionKey = tuple[str, str]

#: The config files complexipy itself consults, in ITS order
#: (``utils/toml.py:135-148`` ``get_complexipy_toml_config``): first hit wins, and
#: a hit is any file that exists and yields a table — so an EMPTY
#: ``complexipy.toml`` shadows a populated ``pyproject.toml``, and the audit must
#: agree with that or it would audit a file the tool never reads.
CONFIG_FILENAMES = ("complexipy.toml", ".complexipy.toml", "pyproject.toml")

#: Pinned onto every measurement run. ``COLUMNS`` is load-bearing: ``--plain``
#: prints through rich, which wraps at 80 columns when stdout is not a terminal,
#: and a wrapped census row is an unparseable census row. ``TERM`` is load-bearing
#: for the same reason at one remove — ``rich/console.py:1015-1016`` returns a HARD
#: 80x25 and never reads ``COLUMNS`` at all when ``is_dumb_terminal``, which is
#: ``is_terminal and TERM in ("dumb", "unknown")`` (``rich/console.py:986-988``).
#: ``PYTHONIOENCODING`` pins the child's encoding so the census does not emit by
#: locale.
_MEASURE_ENV = {
    "COLUMNS": "10000",
    "PYTHONIOENCODING": "utf-8",
    "NO_COLOR": "1",
    "TERM": "xterm",
}

#: Cleared for every measurement run: these are the two env names that force
#: rich's ``is_terminal`` True over a pipe (``rich/console.py:955-963``), which is
#: the other half of the dumb-terminal short circuit above.
_MEASURE_ENV_CLEARED = frozenset({"FORCE_COLOR", "TTY_COMPATIBLE"})

#: complexipy's own words when it could not analyze a path it was handed
#: (``utils/output.py:297`` ``print_invalid_paths``) — a silently narrower surface.
_UNMEASURABLE_MARKER = "Failed to process"

#: Every consumer config key that would defeat THIS measurement, with why. Derived
#: by walking the tool's own CLI-first/TOML-second resolver
#: (``utils/toml.py:193-333`` ``get_arguments_value``) for the keys this argv
#: leaves unset — those are exactly the keys a consumer's config can still win.
_DEFEATING_KEYS = {
    "snapshot-create": (
        "would make the run WRITE complexipy-snapshot.json from what it just "
        "measured (main.py:323, a branch --snapshot-ignore does not disarm)"
    ),
    "quiet": (
        "is rejected together with --plain, so the run exits 2 with an empty "
        "census and the gate would blame the repo (main.py:748)"
    ),
    "ratchet": (
        "requires --diff, which this argv never passes, so the run exits 2 "
        "before measuring anything (main.py:726-729)"
    ),
    "failed": (
        "would narrow the CENSUS run to offenders too, and the census listing "
        "every measured function is what the surface audit reasons over"
    ),
    "details": (
        'the legacy spelling of failed — "low" means offenders only (utils/toml.py:259-261)'
    ),
    "ignore-complexity": (
        "would decouple the exit code from the tool's own threshold verdict, "
        "and the exit code is how a contradicting run is caught"
    ),
    "report-ignored": (
        "prints one ignore-comment location per line onto the census stream "
        "(main.py:701-708), which is not a census row"
    ),
    "output": "redirects machine-readable output into the consumer's tree",
    "output-format": (
        "writes a report file and prints 'Results saved at ...' onto stdout "
        "BEFORE the census, unguarded by --plain (main.py:510)"
    ),
    "output-csv": "the legacy output-format spelling — same write, plus a Deprecated line",
    "output-json": "the legacy output-format spelling — same write, plus a Deprecated line",
    "output-gitlab": "the legacy output-format spelling — same write, plus a Deprecated line",
    "output-sarif": "the legacy output-format spelling — same write, plus a Deprecated line",
}


class Executor(Protocol):
    """The subprocess seam the caller injects (``gate_runner._exec``).

    Structural, not inherited: the runner stays the caller's — one place owns
    typed OSError translation and the no-shell fixed-argv discipline — while the
    tests keep patching that single seam.
    """

    def __call__(
        self,
        argv: list[str],
        cwd: Path,
        env: Mapping[str, str],
        *,
        stdin: str | None = None,
    ) -> subprocess.CompletedProcess[str]: ...


@dataclass(frozen=True)
class Census:
    """What ONE write-free complexipy run actually measured.

    The census is the gate's independent fact about its own measurement surface:
    it is read from the tool's output, never from the snapshot, so "the floor is
    empty" and "we graded nothing" can never be the same observation.

    ``functions`` is keyed by :data:`FunctionKey` and aggregated with ``max()``;
    ``rows`` counts the census LINES parsed. The two genuinely differ and both
    are load-bearing — on a real consumer 681 rows collapse to 680 keys, because
    ``@overload`` chains and ``if sys.platform:`` redefinitions repeat a
    ``(path, name)`` pair. Counting keys UNDER-reports the measurement, which is
    the anti-void evidence this stage exists to produce; and last-writer-wins
    would let the HIGHER value of a straddling pair vanish, making our mirror of
    complexipy's watermark rule strictly weaker than the rule it mirrors (the
    tool iterates its own LIST, not a map) and letting a bogus skew fire when
    only one of the two maps kept the high value.
    """

    functions: dict[FunctionKey, int]
    rows: int

    @property
    def files(self) -> frozenset[str]:
        """The distinct files this run measured — the surface audit's evidence."""
        return frozenset(path for path, _ in self.functions)


def refusal(code: str, message: str, context: Mapping[str, object]) -> GateError:
    """A refusal in the kit's typed vocabulary — the gate could not do its job."""
    return GateError(code=code, message=message, context=dict(context))


def _table(path: Path) -> Mapping[str, object] | None:
    """One config file's complexipy table, or None when the tool would not use it.

    Mirrors ``utils/toml.py::load_toml_config`` exactly: ``pyproject.toml``
    contributes only its ``[tool.complexipy]`` sub-table, every other name
    contributes the whole document — including an empty one, which is why an
    empty ``complexipy.toml`` shadows ``pyproject.toml``. ``ValueError`` is the
    catch because it subsumes both ``TOMLDecodeError`` and the
    ``UnicodeDecodeError`` a non-UTF-8 config raises; letting either escape would
    lose the whole battery to a traceback instead of one typed refusal.
    """
    if not path.is_file():
        return None
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise refusal(
            "GATE_COMPLEXIPY_CONFIG_UNREADABLE",
            f"cannot read {path.name}: {exc} — complexipy resolves its options from "
            "this file, so an unreadable one leaves the measurement unaudited; fix "
            "the TOML (or delete the file) and re-run",
            {"config": str(path), "reason": str(exc)},
        ) from exc
    if path.name != "pyproject.toml":
        return data
    tool = data.get("tool")
    if not isinstance(tool, dict):
        return None
    table = tool.get("complexipy")
    return table if isinstance(table, dict) else None


def _defeats(key: str, value: object) -> bool:
    """True when this key/value pair would defeat the measurement.

    Value-sensitive on purpose: ``snapshot-create = false`` provably writes
    nothing (``utils/snapshot.py:17``), so refusing it would be a false refusal,
    and a false refusal costs a consumer a red board for nothing. ``details`` is
    the one non-boolean-shaped key and only bites at ``"low"``.
    """
    if key not in _DEFEATING_KEYS:
        return False
    if key == "details":
        return str(value).strip().lower() == "low"
    return bool(value)


def audit_config(root: Path) -> str | None:
    """The consumer's complexipy config, audited before the instrument is trusted.

    Returns the filename the tool will read (None when it reads none) so a
    PASSING verdict can state which config was in force. Raises when that config
    carries a key from :data:`_DEFEATING_KEYS` — the mechanism that turns this
    module's write-free claim from an aspiration into an enforced precondition.
    """
    for name in CONFIG_FILENAMES:
        table = _table(root / name)
        if table is None:
            continue
        defeating = sorted(key for key, value in table.items() if _defeats(str(key), value))
        if defeating:
            detail = "; ".join(f"{key} ({_DEFEATING_KEYS[key]})" for key in defeating)
            raise refusal(
                "GATE_COMPLEXIPY_CONFIG_DEFEATS_MEASUREMENT",
                f"{name} sets complexipy option(s) this gate cannot measure through: "
                f"{detail} — remove them from {name}; max-complexity-allowed and "
                "exclude ARE honoured, so a real budget or a real exclusion needs no "
                "workaround here",
                {"config": name, "keys": defeating},
            )
        return name
    return None


def measurement_argv(tool: Path, source_root: Path, *, offenders_only: bool) -> list[str]:
    """The write-free measurement command — the root of the fix, not a nicety.

    Six tokens plus an optional ``--failed``, and the ABSENCE of a threshold flag
    is as load-bearing as the presence of ``--snapshot-ignore``: the kit never
    re-declares a budget complexipy already resolves from its own default / CLI /
    ``[tool.complexipy]``, because a second authority here would flag a
    consumer's baselined band as a new offender. ``--failed`` narrows the census
    to the functions the tool's OWN resolved threshold calls offenders.
    """
    argv = [str(tool), str(source_root), "--plain", "--color", "no", "--snapshot-ignore"]
    if offenders_only:
        argv.append("--failed")
    return argv


def _census_row(line: str) -> tuple[FunctionKey, int] | None:
    """``<path.py> <function> <complexity>`` -> the keyed measurement, else None.

    Split from the RIGHT: the complexity and the function name are single tokens
    while a path may contain spaces, so ``rsplit`` is the only safe direction.
    """
    parts = line.strip().rsplit(maxsplit=2)
    if len(parts) != 3 or not parts[0].endswith(".py"):
        return None
    try:
        complexity = int(parts[2])
    except ValueError:
        return None
    return (parts[0], parts[1]), complexity


def parse_census(stdout: str, context: Mapping[str, object] | None = None) -> Census:
    """complexipy ``--plain`` stdout -> the measured census.

    ``--plain`` is complexipy's documented scripting form: one
    ``<path> <function> <complexity>`` line per function it measured, over
    threshold or NOT — ``utils/output.py:234`` drops a row only when
    ``failed_only`` is set and ``:243`` appends every other one. That is why a
    function which merely fell below the bar is still HERE, and why its absence
    from a measured file means something else entirely (the ratchet's
    per-function surface audit reasons on exactly that distinction).

    A non-blank line that is not a census row REFUSES instead of being dropped:
    an unreadable census and an empty one look identical from a count, and the
    empty one is the exact world this gate exists to catch.
    """
    functions: dict[FunctionKey, int] = {}
    unreadable: list[str] = []
    rows = 0
    for line in stdout.splitlines():
        row = _census_row(line)
        if row is not None:
            rows += 1
            functions[row[0]] = max(functions.get(row[0], row[1]), row[1])
        elif line.strip():
            unreadable.append(line.strip())
    if unreadable:
        raise refusal(
            "GATE_COMPLEXIPY_OUTPUT_UNREADABLE",
            f"complexipy --plain emitted {len(unreadable)} line(s) that are not "
            "'<path> <function> <complexity>' — the census cannot be trusted, so the "
            "floor cannot be graded; check the repo root for a complexipy.toml or a "
            "[tool.complexipy] table adding output to the run",
            {**dict(context or {}), "lines": unreadable[:10], "measured_functions": rows},
        )
    return Census(functions=functions, rows=rows)


def _excerpt(text: str) -> list[str]:
    """The leading non-blank lines of a stream — evidence, never the whole tail."""
    return [line.strip() for line in text.splitlines() if line.strip()][:5]


def _refuse_unmeasurable(
    proc: subprocess.CompletedProcess[str], context: Mapping[str, object]
) -> None:
    """complexipy's own words for a path it could not analyze — a narrower surface.

    Kept a REFUSAL rather than a finding, deliberately and now declared: an
    unparseable file means the graded surface is narrower than the tree, so every
    OTHER function's clean reading is unsupported. A findings-level report would
    let the rest of the board read green beside a void. Both streams are scanned,
    because which one carries it depends on rich's console wiring.
    """
    marked = [
        line.strip()
        for line in f"{proc.stdout}\n{proc.stderr}".splitlines()
        if _UNMEASURABLE_MARKER in line
    ]
    if not marked:
        return
    raise refusal(
        "GATE_COMPLEXIPY_PATHS_UNMEASURABLE",
        f"complexipy could not analyze {len(marked)} path(s) — the graded surface is "
        "narrower than the tree, so a clean verdict would be a void; fix the named "
        "file(s) (a syntax error also reds ruff and mypy) and re-run the gate",
        {**dict(context), "paths": marked[:10]},
    )


def _refuse_instrument_failure(
    proc: subprocess.CompletedProcess[str], context: Mapping[str, object]
) -> None:
    """Refuse when the exit code contradicts the census, rather than blame the repo.

    Exit semantics taken from the pinned source, not from confidence (see this
    module's docstring for the reduction): 0 and 1 are the tool's only verdicts,
    1 means "some function is over threshold", and that cannot be true of a run
    which printed no function at all. That second clause is also the OFFENDER
    run's vacuity leg — an empty ``--failed`` census beside a non-zero exit is a
    contradiction — which is why one rule serves both runs. Any other code is
    ``typer`` declining to run: ``BadParameter`` exits 2 (``main.py:748``), as
    does ``validate_ratchet`` (``main.py:726-729``).
    """
    if proc.returncode == 0:
        return
    empty = not proc.stdout.strip()
    if proc.returncode == 1 and not empty:
        return
    detail = (
        "exit 1 means 'some function is over threshold', which no run that printed "
        "zero functions can be reporting"
        if proc.returncode == 1
        else "0 and 1 are the tool's only verdicts; anything else is it declining to run"
    )
    raise refusal(
        "GATE_COMPLEXIPY_INSTRUMENT_FAILED",
        f"complexipy exited {proc.returncode} with "
        f"{'an empty' if empty else 'a non-empty'} census — {detail}. This is the "
        "instrument failing, not the repo, so the gate refuses instead of charging "
        "it to the code; read `stderr` in this context, then check the repo root for "
        "a complexipy.toml or a [tool.complexipy] table",
        {**dict(context), "stdout_head": _excerpt(proc.stdout)},
    )


def _measure_env(env: Mapping[str, str]) -> dict[str, str]:
    """The caller's environment with the census pins ON and the tty forcers OFF."""
    kept = {key: value for key, value in env.items() if key not in _MEASURE_ENV_CLEARED}
    return {**kept, **_MEASURE_ENV}


def measure(
    root: Path,
    source_root: Path,
    env: Mapping[str, str],
    tool: Path,
    executor: Executor,
    *,
    offenders_only: bool,
) -> Census:
    """Run one write-free measurement from the repo root and read its census.

    cwd is the repo root deliberately: complexipy resolves its config
    (``main.py:66-67``), the snapshot path (``main.py:321``) and every reported
    path (``main.py:308-310``) against ``os.getcwd()``, so measuring from
    anywhere else would re-key the census and break the comparison. All three
    channels are consulted, and the exit code plus a stderr excerpt ride EVERY
    refusal raised here — a tool-side failure that reaches the board with its
    reason deleted is a failure re-attributed to the repo.

    ``UnicodeDecodeError`` is caught at the seam because ``text=True`` decodes in
    the PARENT, by the parent's locale — ``PYTHONIOENCODING`` pins the child
    only. That exception is a ``ValueError``, so it would otherwise escape the
    executor, escape ``gate_runner._run_stage`` (which catches ``GateError``) and
    lose the whole 12-stage board to a traceback.
    """
    argv = measurement_argv(tool, source_root, offenders_only=offenders_only)
    try:
        proc = executor(argv, root, _measure_env(env))
    except UnicodeDecodeError as exc:
        raise refusal(
            "GATE_COMPLEXIPY_OUTPUT_UNDECODABLE",
            f"complexipy's output does not decode in this locale: {exc} — the census "
            "is the only instrument the ratchet has, so the gate refuses rather than "
            "grade a truncated world",
            {"argv": argv, "offenders_only": offenders_only, "reason": str(exc)},
        ) from exc
    context: dict[str, object] = {
        "argv": argv,
        "offenders_only": offenders_only,
        "exit_code": proc.returncode,
        "stderr": _excerpt(proc.stderr),
    }
    _refuse_unmeasurable(proc, context)
    _refuse_instrument_failure(proc, context)
    return parse_census(proc.stdout, context)
