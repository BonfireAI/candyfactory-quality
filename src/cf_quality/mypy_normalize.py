"""Make the mypy baseline a function of CODE, not the installed stub set.

mypy reports a missing third-party import in DIFFERENT words depending on
whether the package happens to be installed-without-stubs or absent entirely,
and it emits its stub-install hint notes ONCE per run, anchored to whichever
missing-import site it saw first. Both behaviours are properties of the
ENVIRONMENT, not the code under measurement, so feeding mypy's raw output
straight into ``mypy-baseline`` lets the baseline flip between machines and
CI runs — the phantom new/fixed deltas this transform exists to kill.

:func:`normalize_mypy_output` is a pure text pass over mypy's raw stdout lines
that:

- **(a)** maps every env-dependent missing-import diagnostic — ``import-untyped``
  (*Library stubs not installed*), the ``Skipping analyzing`` form, and
  ``import-not-found`` (*Cannot find implementation or library stub*) — onto ONE
  canonical line keyed by the imported module, so a given import yields the same
  baseline entry whether its package is installed-without-stubs or absent;
- **(b)** drops the once-per-run global stub-install notes (the
  ``mypy --install-types`` note, the ``#missing-imports`` See note, and the
  per-package ``Hint: "... pip install ...-stubs"`` note) so they never enter
  the baseline and cannot relocate between files;
- **(c)** leaves everything else byte-identical — real type errors and every
  other diagnostic (including first-party import errors of any other shape)
  pass through untouched.

The transform NEVER drops an error line; it only re-words the missing-import
diagnostics above and strips the global notes, so no real finding is masked.
Run the same normalization on both the boot/sync path and the gate/filter path
(see ``configs/BASELINE-CONVENTIONS.md``) so the booted baseline matches what
the filter later compares against.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterable

#: ``<path>:<line>[:<col>]: <severity>: <message>`` — the lazy location stops at
#: the FIRST severity token, so a message that itself contains ``: error: `` is
#: left intact.
_DIAGNOSTIC = re.compile(r"^(?P<loc>.+?): (?P<sev>error|note|warning): (?P<msg>.*)$")

#: The three env-dependent missing-import messages, each capturing the module.
_MISSING_IMPORT = (
    re.compile(r'Library stubs not installed for "(?P<mod>[^"]+)"'),
    re.compile(
        r'Skipping analyzing "(?P<mod>[^"]+)": module is installed, '
        r"but missing library stubs or py\.typed marker"
    ),
    re.compile(r'Cannot find implementation or library stub for module named "(?P<mod>[^"]+)"'),
)

#: The canonical error code every missing-import variant collapses onto.
_CANONICAL_CODE = "import-untyped"

#: Substrings marking the once-per-run global stub-install notes to drop.
_GLOBAL_NOTE_MARKERS = (
    '(or run "mypy --install-types"',
    "#missing-imports",
)

#: The per-package stub-install hint note (also once per run), to drop.
_HINT_NOTE = re.compile(r'^Hint: ".*\bpip install\b.*"$')


def _missing_import_module(message: str) -> str | None:
    """The imported module named by a missing-import message, else None."""
    for pattern in _MISSING_IMPORT:
        match = pattern.search(message)
        if match is not None:
            return match.group("mod")
    return None


def _is_dropped_note(message: str) -> bool:
    """True for the global / per-package stub-install notes that must not persist."""
    if any(marker in message for marker in _GLOBAL_NOTE_MARKERS):
        return True
    return _HINT_NOTE.match(message) is not None


def _canonical_line(loc: str, module: str) -> str:
    """The single deterministic form every missing-import variant maps to."""
    return f'{loc}: error: Library stubs not installed for "{module}"  [{_CANONICAL_CODE}]'


def _normalize_line(line: str) -> str | None:
    """Canonical form of one raw mypy line, or None to drop it.

    Conservative by design: a line that is not a diagnostic, or is a diagnostic
    that is neither a missing-import error nor a dropped note, returns verbatim.
    """
    parsed = _DIAGNOSTIC.match(line)
    if parsed is None:
        return line
    severity, message = parsed.group("sev"), parsed.group("msg")
    if severity == "note" and _is_dropped_note(message):
        return None
    if severity == "error":
        module = _missing_import_module(message)
        if module is not None:
            return _canonical_line(parsed.group("loc"), module)
    return line


def normalize_mypy_output(lines: Iterable[str]) -> list[str]:
    """Map raw mypy stdout lines to the deterministic, env-independent form."""
    normalized: list[str] = []
    for line in lines:
        result = _normalize_line(line.rstrip("\n"))
        if result is not None:
            normalized.append(result)
    return normalized


def normalize_mypy_stdout(raw_stdout: str) -> str:
    """Normalize mypy's raw stdout, re-joined newline-terminated for a pipe.

    The convenience form of :func:`normalize_mypy_output` for a captured
    subprocess: ``cf-gate`` feeds the result to ``mypy-baseline`` as stdin, and
    the boot/sync command applies the identical transform.
    """
    return "".join(f"{line}\n" for line in normalize_mypy_output(raw_stdout.splitlines()))


def main() -> int:
    """stdin -> stdout filter so the transform can sit in the mypy pipe."""
    for line in normalize_mypy_output(sys.stdin.read().splitlines()):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
