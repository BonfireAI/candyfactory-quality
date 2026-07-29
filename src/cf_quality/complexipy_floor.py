"""The committed cognitive-complexity floor — the ONE place that touches the artifact.

``complexipy-snapshot.json`` is the per-function watermark no later run may
exceed. The whole point of this rung is that the pinned ``complexipy==5.6.0``
REWRITES that file on the success path of its own compare
(``complexipy/utils/snapshot.py:85``), so the artifact needs an owner that reads
it and never writes it. That owner is this module, deliberately alone in it: one
importable surface to audit, and a reviewer can prove "the gate never writes the
floor" by reading forty lines instead of grepping a battery.

Two invariants live here and nowhere else:

- **The KEY.** :func:`_normalized_path` is a declared mirror of
  ``complexipy.utils.output.normalize_path`` (5.6.0, lines 274-280): the snapshot
  stores ``path`` and ``file_name`` separately while ``--plain`` prints them
  joined. Join them differently and every committed watermark reads as a
  brand-new offender. The mirror is pinned by a test calling the INSTALLED
  function, not by a declaration file — a 5.7.0 change to that join must fail the
  suite, not wait for a reviewer to notice.
- **Unreadable is not empty.** A malformed floor REFUSES. Reading it as ``[]``
  would be green-by-unreadable-file, the same gaming vector as
  green-by-missing-file, which the caller already refuses.
"""

from __future__ import annotations

import json
from pathlib import Path

from cf_quality.complexipy_measure import FunctionKey, refusal
from cf_quality.errors import GateError

#: The committed floor's filename (CWD-relative for complexipy, repo root for us).
SNAPSHOT_FILENAME = "complexipy-snapshot.json"


def _normalized_path(path: str, file_name: str) -> str:
    """Join a snapshot entry's two path fields the way complexipy's output does."""
    cleaned = path.rstrip("/")
    if cleaned.endswith(file_name):
        return cleaned
    return f"{cleaned}/{file_name}" if cleaned else file_name


def _refuse_snapshot(snapshot: Path, reason: str) -> GateError:
    return refusal(
        "GATE_COMPLEXIPY_SNAPSHOT_UNREADABLE",
        f"{SNAPSHOT_FILENAME} is not a readable complexipy snapshot: {reason} — an "
        "unreadable floor is not an empty floor, so the gate refuses; re-boot it from "
        "the repo root (complexipy <source-root> --snapshot-create) and commit it",
        {"snapshot": str(snapshot), "reason": reason},
    )


def _entry_watermarks(entry: object, snapshot: Path) -> dict[FunctionKey, int]:
    """One snapshot entry's watermarks; any other shape REFUSES rather than skips."""
    if not isinstance(entry, dict) or not isinstance(entry.get("functions"), list):
        raise _refuse_snapshot(snapshot, f"entry is not {{path, file_name, functions}}: {entry!r}")
    path = _normalized_path(str(entry.get("path", "")), str(entry.get("file_name", "")))
    watermarks: dict[FunctionKey, int] = {}
    for function in entry["functions"]:
        if not isinstance(function, dict) or not isinstance(function.get("complexity"), int):
            raise _refuse_snapshot(snapshot, f"function is not {{name, complexity}}: {function!r}")
        watermarks[(path, str(function.get("name", "")))] = int(function["complexity"])
    return watermarks


def read_snapshot(snapshot: Path) -> dict[FunctionKey, int]:
    """The committed floor as ``{(file, function): watermark}`` — read, never written.

    The catch is ``ValueError``, which subsumes both ``json.JSONDecodeError`` and
    the ``UnicodeDecodeError`` a non-UTF-8 snapshot raises. The narrower
    ``JSONDecodeError`` let that one escape this function, escape
    ``gate_runner._run_stage`` (which catches only ``GateError``) and lose the
    entire 12-stage board to a traceback instead of one typed refusal.
    """
    try:
        raw = json.loads(snapshot.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise _refuse_snapshot(snapshot, str(exc)) from exc
    if not isinstance(raw, list):
        raise _refuse_snapshot(snapshot, f"top level is {type(raw).__name__}, not a list")
    floor: dict[FunctionKey, int] = {}
    for entry in raw:
        floor.update(_entry_watermarks(entry, snapshot))
    return floor
