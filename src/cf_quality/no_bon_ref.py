"""cf-no-bon-ref — the no-ticket-ids law's shippable, consumer-facing sweep.

A Linear ticket id (the ``BON`` + ``-<n>`` shape) is a LOCAL index: meaningless
to anyone reading the code, the diff, or the git history. The law
([[no-ticket-ids-in-code]]) bans it from the CODE/CONFIG tree — comments,
docstrings, CSS, ``.gitignore``, config, test names — and says: describe the
work, never the ticket. This gauge enforces that on the CONSUMER tree.

It is the missing teeth: the kit's existing ``test_design_doc`` sweep guards
only the kit's OWN docs, and the Python ``cf-gate`` battery never swept a
consumer tree for ticket refs at all — so a consumer (mexxa) leaked refs to
main uncaught.

Jurisdiction — the law governs CODE, not provenance prose. The sweep covers
the code/config tree and SKIPS:

- version control, caches, vendored trees and any hidden directory
  (``.git``, ``__pycache__``, ``.venv``, ``node_modules``, ``build``,
  ``dist``); ``.gitignore`` and other hidden FILES are still swept;
- ``docs/`` and all markdown/rst (``.md`` / ``.markdown`` / ``.rst``) — ADRs,
  READMEs, design records and the law-debt ledger legitimately map epic ->
  ticket; that mapping is documentation's FUNCTION, not a leak. The law
  governs the CODE tree; this is a declared jurisdiction boundary, not a
  silent paths-ignore;
- binary files (any NUL byte) — a ticket id only ever leaks into text.

The reasoned escape: a ref that legitimately lives in a CODE path (generated
or vendored source carrying an upstream tag) is REGISTERED in
``no-bon-ref-exemptions.json`` ({frozen_count, entries:[{path, reason}]}),
mirroring the kit's exemptions ratchet — every blessing carries a reason and
is printed loudly, and adding one requires bumping ``frozen_count`` (a visible
decision, never a silent one).

The pattern this gauge hunts is assembled by concatenation so this module's
own source never carries it (the kit self-sweeps for the same literal).

Exit codes: 0 clean · 1 violations · 2 the gate itself could not run (typed
:class:`~cf_quality.errors.GateError` on stderr).
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections.abc import Iterator
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from cf_quality.errors import GateError, GateViolation
from cf_quality.reporting import print_verdict

#: The ticket-ref shape, built so this source stays self-clean (the prefix and
#: the dash never sit contiguous here): a ``BON`` prefix, a dash, then digits,
#: on a word boundary, matched against raw bytes (NUL-free text only).
_TICKET_RE = re.compile(rb"\bBON" + rb"-[0-9]+")

#: Named directories never swept (vendored / build output). Hidden dirs are
#: pruned separately; ``docs`` is the declared provenance jurisdiction.
_SKIP_DIRS = frozenset({"__pycache__", "node_modules", "build", "dist", "venv", "docs"})

#: Prose suffixes — markdown/rst are documentation, not code; a ticket ref in a
#: README or an ADR is provenance, not a leak. The law governs the code tree.
_PROSE_SUFFIXES = frozenset({".md", ".markdown", ".rst"})

_EXEMPTIONS_FILE = "no-bon-ref-exemptions.json"


def _is_binary(data: bytes) -> bool:
    """A NUL byte marks a binary file; a ticket id only leaks into text."""
    return b"\x00" in data


def iter_source_files(root: Path) -> Iterator[Path]:
    """Yield every text file under root, pruning hidden/vendored/provenance dirs."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and d not in _SKIP_DIRS)
        for name in sorted(filenames):
            if Path(name).suffix.lower() in _PROSE_SUFFIXES:
                continue
            yield Path(dirpath) / name


def _scan_bytes(data: bytes) -> Iterator[tuple[int, list[str]]]:
    """Yield (1-based line, refs) for every line carrying a ticket ref."""
    for index, line in enumerate(data.split(b"\n"), start=1):
        matches = _TICKET_RE.findall(line)
        if matches:
            yield index, [m.decode("ascii") for m in matches]


def scan_file(path: Path, root: Path) -> list[GateViolation]:
    """Scan one file; binary or unreadable files yield nothing (not a crash)."""
    try:
        data = path.read_bytes()
    except OSError:
        return []
    if _is_binary(data):
        return []
    rel = path.relative_to(root).as_posix()
    return [
        GateViolation(
            code="TICKET_REF_IN_SOURCE",
            message=(
                f"ticket reference {', '.join(refs)} in source — a ticket id is a "
                "local index, meaningless in the tree; describe the work, not the ticket"
            ),
            path=rel,
            line=line,
            context={"refs": refs},
        )
        for line, refs in _scan_bytes(data)
    ]


def scan_tree(root: Path) -> tuple[list[GateViolation], int]:
    """Sweep the code/config tree — findings and files swept; GateError when absent."""
    if not root.exists():
        raise GateError(
            code="GATE_PATH_MISSING",
            message=f"tree does not exist: {root}",
            context={"path": str(root)},
        )
    violations: list[GateViolation] = []
    swept = 0
    for path in iter_source_files(root):
        swept += 1
        violations.extend(scan_file(path, root))
    return sorted(violations, key=lambda v: (v.path, v.line or 0)), swept


# --- the reasoned, ratcheted exemption registry -----------------------------


def _config_error(message: str, context: dict[str, Any]) -> GateError:
    return GateError(code="GATE_CONFIG_INVALID", message=message, context=context)


def _validate_entry(index: int, entry: object) -> dict[str, str]:
    """Each entry is {path, reason}, both non-empty strings (a reasoned blessing)."""
    if not isinstance(entry, dict):
        raise _config_error(f"{_EXEMPTIONS_FILE} entry {index} is not an object", {"index": index})
    out: dict[str, str] = {}
    for key in ("path", "reason"):
        value = entry.get(key)
        if not (isinstance(value, str) and value.strip()):
            raise _config_error(
                f"{_EXEMPTIONS_FILE} entry {index} is missing or has an empty '{key}'",
                {"index": index, "key": key},
            )
        out[key] = value
    return out


def load_exemptions(root: Path) -> tuple[list[dict[str, str]], int] | None:
    """Parse the registry; None when absent; typed GateError when malformed."""
    config_path = root / _EXEMPTIONS_FILE
    if not config_path.is_file():
        return None
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        raise _config_error(
            f"{_EXEMPTIONS_FILE} is not valid JSON: {exc}", {"path": str(config_path)}
        ) from exc
    frozen = data.get("frozen_count") if isinstance(data, dict) else None
    if not isinstance(frozen, int) or isinstance(frozen, bool) or frozen < 0:
        raise _config_error(
            f"{_EXEMPTIONS_FILE} must carry an integer 'frozen_count' >= 0 (the ratchet)",
            {"path": str(config_path)},
        )
    entries = data.get("entries")
    if not isinstance(entries, list):
        raise _config_error(
            f"{_EXEMPTIONS_FILE} must carry an 'entries' list", {"path": str(config_path)}
        )
    return [_validate_entry(i, entry) for i, entry in enumerate(entries)], frozen


def _ratchet_violation(entry_count: int, frozen: int) -> list[GateViolation]:
    """Adding an exemption requires bumping frozen_count — a visible decision."""
    if entry_count > frozen:
        return [
            GateViolation(
                code="EXEMPTION_COUNT_EXCEEDED",
                message=(
                    f"{entry_count} exemption entries exceed frozen_count {frozen}: "
                    "adding an exemption requires bumping frozen_count — visible, never silent"
                ),
                path=_EXEMPTIONS_FILE,
                context={"entries": entry_count, "frozen_count": frozen},
            )
        ]
    return []


def _partition(
    violations: list[GateViolation], entries: list[dict[str, str]]
) -> tuple[list[GateViolation], list[str]]:
    """Split findings into still-failing and blessed-by-a-registered-entry (loud)."""
    failing: list[GateViolation] = []
    blessed: list[str] = []
    for violation in violations:
        match = next((e for e in entries if fnmatch(violation.path, e["path"])), None)
        if match is None:
            failing.append(violation)
        else:
            blessed.append(
                f"blessed: {violation.path}:{violation.line} — covered by "
                f"'{match['path']}' ({match['reason']})"
            )
    return failing, blessed


def check(root: Path) -> tuple[list[GateViolation], list[str], int]:
    """Sweep, apply the reasoned registry, ratchet — (violations, notices, files swept)."""
    found, swept = scan_tree(root)
    config = load_exemptions(root)
    if config is None:
        return found, [], swept
    entries, frozen = config
    failing, blessed = _partition(found, entries)
    failing.extend(_ratchet_violation(len(entries), frozen))
    notices = [
        f"=== TICKET-REF EXEMPTIONS: {len(entries)} entries / frozen_count {frozen} ===",
        *blessed,
    ]
    return failing, notices, swept


def main(argv: list[str] | None = None) -> int:
    """Console entry point. Exit 0 clean · 1 violations · 2 the gate could not run."""
    parser = argparse.ArgumentParser(
        prog="cf-no-bon-ref",
        description="No ticket id in the code/config tree — describe the work, not the ticket.",
    )
    parser.add_argument("--root", default=".", help="repo root to sweep (default: cwd)")
    args = parser.parse_args(argv)
    try:
        violations, notices, swept = check(Path(args.root).resolve())
    except GateError as exc:
        return print_verdict("cf-no-bon-ref", [], exc)
    return print_verdict(
        "cf-no-bon-ref",
        violations,
        notices=notices,
        measured=f"— swept {swept} file(s) of the code/config tree for ticket refs",
        evidence={"files_swept": swept},
        clean_summary="cf-no-bon-ref: OK (no ticket references in the code/config tree)",
        fail_summary=f"cf-no-bon-ref: FAIL ({len(violations)} ticket reference(s))",
    )


if __name__ == "__main__":
    raise SystemExit(main())
