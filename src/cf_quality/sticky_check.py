"""cf-sticky-check — the sticky-intro gauge (the BubbleGum Law's mount).

``check`` mode: the consumer repo's CLAUDE.md must CONTAIN the canonical
sticky block byte-identical (line-ending normalization only). Chewed gum —
any edit inside the block — fails with a unified diff; an absent block fails.

``mount`` mode: append the block under a one-line declared-mirror header when
absent; idempotent (a second mount is a no-op); refuses to mount over a
tampered block so chewed gum is never silently duplicated or papered over.

The canonical text is loaded from the KIT's own packaged data file, never from
the consumer repo — the gauge block comes from the factory, so a consumer
cannot re-declare its own edited copy as canonical (the declare-don't-fix and
vendored-copy-edit gaming vectors from the Law 5 refuter).
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path

from cf_quality.errors import GateError, GateViolation

MIRROR_HEADER = (
    "<!-- declared mirror of candyfactory-canon ADR 0029 · mounted by candyfactory-quality -->"
)

_DATA_FILENAME = "sticky-intro.md"


def _normalize(text: str) -> str:
    """Line-ending normalization only — every other byte is load-bearing."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _candidate_data_files() -> tuple[Path, ...]:
    """Where the kit's canonical copy may live, in resolution order."""
    here = Path(__file__).resolve()
    return (
        here.parent / "data" / _DATA_FILENAME,  # wheel layout (package data)
        here.parents[2] / "data" / _DATA_FILENAME,  # source tree / editable install
    )


def canonical_text() -> str:
    """The canonical sticky block, from the kit's packaged data file."""
    for candidate in _candidate_data_files():
        if candidate.is_file():
            return _normalize(candidate.read_text(encoding="utf-8"))
    raise GateError(
        code="STICKY_CANONICAL_MISSING",
        message="the kit's canonical sticky-intro data file was not found",
        context={"searched": [str(path) for path in _candidate_data_files()]},
    )


def _tampered_violation(claude_md: Path, canonical: str, text: str) -> GateViolation:
    """The block's first line is present but the block is not byte-identical."""
    canonical_lines = canonical.splitlines()
    lines = text.splitlines()
    start = lines.index(canonical_lines[0])
    found = lines[start : start + len(canonical_lines)]
    diff = "\n".join(
        difflib.unified_diff(
            canonical_lines,
            found,
            fromfile="canonical sticky-intro (kit)",
            tofile=str(claude_md),
            lineterm="",
        )
    )
    return GateViolation(
        code="STICKY_INTRO_TAMPERED",
        message="the sticky intro was edited in place (chewed gum) — it must be byte-identical",
        path=str(claude_md),
        line=start + 1,
        context={"diff": diff},
    )


def check(claude_md: Path) -> list[GateViolation]:
    """Gauge one CLAUDE.md against the kit's canonical sticky block."""
    if not claude_md.is_file():
        return [
            GateViolation(
                code="STICKY_CLAUDE_MD_MISSING",
                message="the target repo has no CLAUDE.md to carry the sticky intro",
                path=str(claude_md),
            )
        ]
    canonical = canonical_text()
    text = _normalize(claude_md.read_text(encoding="utf-8"))
    if canonical in text:
        return []
    if canonical.splitlines()[0] in text.splitlines():
        return [_tampered_violation(claude_md, canonical, text)]
    return [
        GateViolation(
            code="STICKY_INTRO_ABSENT",
            message="the canonical sticky intro is not mounted in this CLAUDE.md",
            path=str(claude_md),
        )
    ]


def _mounted_text(existing: str, canonical: str) -> str:
    """Existing content, then a blank line, the mirror header, and the block."""
    if existing and not existing.endswith("\n"):
        existing += "\n"
    separator = "\n" if existing else ""
    return f"{existing}{separator}{MIRROR_HEADER}\n{canonical}"


def mount(claude_md: Path) -> bool:
    """Append the canonical block when absent. Returns True iff it wrote."""
    canonical = canonical_text()
    existing = _normalize(claude_md.read_text(encoding="utf-8")) if claude_md.is_file() else ""
    if canonical in existing:
        return False  # already mounted byte-identical — no-op
    if canonical.splitlines()[0] in existing.splitlines():
        raise GateError(
            code="STICKY_MOUNT_TAMPERED",
            message="refusing to mount over a tampered sticky intro — fix the chewed block first",
            context={"path": str(claude_md)},
        )
    claude_md.write_text(_mounted_text(existing, canonical), encoding="utf-8")
    return True


def _resolve_target(raw: str) -> Path:
    """Accept a consumer repo directory or a direct CLAUDE.md path."""
    path = Path(raw)
    return path / "CLAUDE.md" if path.is_dir() else path


def _run_check(target: Path) -> int:
    violations = check(target)
    for violation in violations:
        print(json.dumps(violation.to_dict(), ensure_ascii=False))
    return 1 if violations else 0


def _run_mount(target: Path) -> int:
    if mount(target):
        print(f"mounted sticky intro into {target}")
    else:
        print(f"already mounted (no-op): {target}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Exit 0 green · 1 violations (check) · 2 the gate itself failed."""
    parser = argparse.ArgumentParser(
        prog="cf-sticky-check",
        description="Gauge or mount the canonical BubbleGum sticky intro in a repo's CLAUDE.md.",
    )
    parser.add_argument("mode", choices=("check", "mount"))
    parser.add_argument("target", help="consumer repo directory, or its CLAUDE.md path")
    args = parser.parse_args(argv)
    target = _resolve_target(args.target)
    try:
        return _run_check(target) if args.mode == "check" else _run_mount(target)
    except GateError as error:
        print(json.dumps(error.to_dict(), ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
