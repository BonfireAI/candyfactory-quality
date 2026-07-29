"""cf-mirror-check — cross-repo copies are declared mirrors, and declarations expire.

Reads the target repo's ``MIRRORS.md`` — a markdown table with one row per
declared mirror: artifact | local path | parent repo | parent path |
pinned parent SHA | content sha256 | pinned date (YYYY-MM-DD). Three checks:

(a) every declared local file exists and its sha256 matches the declared
    content hash — divergence fails with BOTH hashes in the finding;
(b) rows missing any required field fail (a half-declaration is no
    declaration). ``pinned date`` IS a required field — the refuter showed
    that an optional date made expiry opt-out (omit the column, never
    expire), so a declaration without an expiry clock is no declaration;
(c) staleness — a ``pinned date`` older than ``--max-pin-age-days``
    (default 90) fails as a stale pin, and a FUTURE date fails outright
    (``MIRROR_PIN_FUTURE`` — the refuter's 2099 pin gave negative age and
    made a declaration immortal). This is the answer to the
    declare-don't-fix gaming vector: declaring a divergence legalizes it
    only temporarily; legalized drift expires and must be re-affirmed or
    healed.

``cf-mirror-check init`` emits a template ``MIRRORS.md``.

HONEST OPEN (v0): cross-repo fetch of the parent is OUT of scope — no
network. This gate verifies the LOCAL side of the declaration only (file
exists, bytes match the declared hash, pin is fresh). Whether the pinned
parent SHA still names real parent content, and whether the parent has moved
on since the pin, is NOT checked here; that diff requires fetching the parent
repo (auth design unbuilt — see the Law 5 refuter notes) and lands in a later
version or on Constable cadence. The required pin date is the backstop: with
expiry unavoidable (no omitted dates, no future dates), self-declared drift
is at worst max-pin-age old before a human must re-affirm it against the
parent. ALSO OPEN: the gate checks only DECLARED rows — an undeclared
cross-repo copy is invisible to it (the repo self-enumerates its mirrors);
a fingerprint scanner for likely-undeclared mirrors is Constable-cadence
work, recorded in DESIGN.md Open issues.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
from dataclasses import dataclass
from pathlib import Path

from cf_quality.errors import GateError, GateViolation
from cf_quality.reporting import print_verdict

DEFAULT_MAX_PIN_AGE_DAYS = 90

#: Required columns, by normalized (lowercased) header name, in display form.
REQUIRED_COLUMNS = (
    "artifact",
    "local path",
    "parent repo",
    "parent path",
    "pinned parent sha",
    "content sha256",
    "pinned date",
)
PINNED_DATE_COLUMN = "pinned date"

_TEMPLATE_HEADER = (
    "| artifact | local path | parent repo | parent path "
    "| pinned parent SHA | content sha256 | pinned date |"
)
_TEMPLATE_EXAMPLE = (
    "<!-- example row: | sticky-intro | src/cf_quality/data/sticky-intro.md | candyfactory-canon "
    "| decisions/0029-bubblegum-law.md | <full parent commit SHA> "
    "| <sha256 of the local file> | 2026-06-10 | -->"
)
_TEMPLATE = f"""\
# Declared mirrors

Every cross-repo copy in this repo is DECLARED here (the BubbleGum Law's
two-tier DRY: in-repo duplication is gated; cross-repo copies are declared
mirrors, so divergence is a decision, never silence). `cf-mirror-check`
fails the build when a mirrored file's bytes drift from the declared
`content sha256`, when a row is incomplete, or when a `pinned date` is older
than the max pin age (default 90 days) — legalized drift expires.

After editing a mirrored file deliberately: recompute `content sha256`
(`sha256sum <file>`), refresh `pinned parent SHA` against the parent, and
stamp `pinned date` with today's date.

{_TEMPLATE_HEADER}
|---|---|---|---|---|---|---|

{_TEMPLATE_EXAMPLE}
"""


@dataclass(frozen=True)
class MirrorRow:
    """One declared mirror, as read from MIRRORS.md (fields may be empty)."""

    artifact: str
    local_path: str
    parent_repo: str
    parent_path: str
    pinned_sha: str
    content_sha256: str
    pinned_date: str | None
    line: int

    def missing_fields(self) -> list[str]:
        """Display names of required fields this row left empty."""
        values = (
            self.artifact,
            self.local_path,
            self.parent_repo,
            self.parent_path,
            self.pinned_sha,
            self.content_sha256,
            self.pinned_date or "",
        )
        return [name for name, value in zip(REQUIRED_COLUMNS, values, strict=True) if not value]


def _split_table_line(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_separator(cells: list[str]) -> bool:
    return all(cell and set(cell) <= set("-: ") for cell in cells)


def _header_indices(cells: list[str]) -> dict[str, int]:
    """Map normalized column name -> index; raise if any required column is absent."""
    indices = {cell.lower(): i for i, cell in enumerate(cells)}
    missing = [name for name in REQUIRED_COLUMNS if name not in indices]
    if missing:
        raise GateError(
            code="MIRRORS_HEADER_INVALID",
            message="MIRRORS.md table header is missing required columns",
            context={"missing_columns": missing},
        )
    return indices


def _row_from_cells(cells: list[str], indices: dict[str, int], line: int) -> MirrorRow:
    def cell(name: str) -> str:
        index = indices[name]
        return cells[index] if index < len(cells) else ""

    pinned_index = indices.get(PINNED_DATE_COLUMN)
    pinned_date: str | None = None
    if pinned_index is not None and pinned_index < len(cells):
        pinned_date = cells[pinned_index] or None
    return MirrorRow(
        artifact=cell("artifact"),
        local_path=cell("local path"),
        parent_repo=cell("parent repo"),
        parent_path=cell("parent path"),
        pinned_sha=cell("pinned parent sha"),
        content_sha256=cell("content sha256"),
        pinned_date=pinned_date,
        line=line,
    )


def parse_mirrors(text: str) -> list[MirrorRow]:
    """Parse MIRRORS.md text into rows; raise GateError on a bad/absent header."""
    indices: dict[str, int] | None = None
    rows: list[MirrorRow] = []
    for line_no, raw in enumerate(text.splitlines(), start=1):
        if not raw.lstrip().startswith("|"):
            continue
        cells = _split_table_line(raw)
        if indices is None:
            indices = _header_indices(cells)
        elif not _is_separator(cells):
            rows.append(_row_from_cells(cells, indices, line_no))
    if indices is None:
        raise GateError(
            code="MIRRORS_HEADER_INVALID",
            message="MIRRORS.md contains no mirror table header",
            context={"missing_columns": list(REQUIRED_COLUMNS)},
        )
    return rows


def _check_content(repo: Path, row: MirrorRow) -> GateViolation | None:
    target = repo / row.local_path
    if not target.is_file():
        return GateViolation(
            code="MIRROR_FILE_MISSING",
            message=f"declared mirror '{row.artifact}' does not exist locally",
            path=row.local_path,
            line=row.line,
            context={"parent_repo": row.parent_repo, "parent_path": row.parent_path},
        )
    actual = hashlib.sha256(target.read_bytes()).hexdigest()
    declared = row.content_sha256.lower()
    if actual != declared:
        return GateViolation(
            code="MIRROR_DIVERGED",
            message=f"mirror '{row.artifact}' bytes diverge from the declared content hash",
            path=row.local_path,
            line=row.line,
            context={"declared_sha256": declared, "actual_sha256": actual},
        )
    return None


def _check_pin(row: MirrorRow, max_pin_age_days: int, today: dt.date) -> GateViolation | None:
    if row.pinned_date is None:
        # Defensive: completeness is checked before this runs, so a missing
        # pin is its own loud finding here, never a silent expiry bypass.
        return GateViolation(
            code="MIRROR_PIN_MISSING",
            message=f"mirror '{row.artifact}' has no pinned date — expiry is not optional",
            path=row.local_path,
            line=row.line,
        )
    try:
        pinned = dt.date.fromisoformat(row.pinned_date)
    except ValueError:
        return GateViolation(
            code="MIRROR_PIN_INVALID",
            message=f"mirror '{row.artifact}' pinned date is not YYYY-MM-DD",
            path=row.local_path,
            line=row.line,
            context={"pinned_date": row.pinned_date},
        )
    if pinned > today:
        return GateViolation(
            code="MIRROR_PIN_FUTURE",
            message=(
                f"mirror '{row.artifact}' pinned date {row.pinned_date} is in the "
                "future — a forward-dated pin would never expire and is refused"
            ),
            path=row.local_path,
            line=row.line,
            context={"pinned_date": row.pinned_date, "today": today.isoformat()},
        )
    age_days = (today - pinned).days
    if age_days > max_pin_age_days:
        return GateViolation(
            code="MIRROR_PIN_STALE",
            message=(
                f"mirror '{row.artifact}' pin is {age_days} days old "
                f"(max {max_pin_age_days}) — legalized drift expires; re-affirm or heal"
            ),
            path=row.local_path,
            line=row.line,
            context={
                "pinned_date": row.pinned_date,
                "age_days": age_days,
                "max_pin_age_days": max_pin_age_days,
            },
        )
    return None


def _check_row(
    repo: Path, row: MirrorRow, max_pin_age_days: int, today: dt.date
) -> list[GateViolation]:
    missing = row.missing_fields()
    if missing:
        return [
            GateViolation(
                code="MIRROR_ROW_INCOMPLETE",
                message="mirror row is missing required fields",
                path=row.local_path or "MIRRORS.md",
                line=row.line,
                context={"missing_fields": missing},
            )
        ]
    findings = [
        _check_content(repo, row),
        _check_pin(row, max_pin_age_days, today),
    ]
    return [finding for finding in findings if finding is not None]


def check_mirrors(
    repo: Path,
    *,
    max_pin_age_days: int = DEFAULT_MAX_PIN_AGE_DAYS,
    today: dt.date | None = None,
) -> tuple[list[GateViolation], int]:
    """Check every declared mirror in ``repo/MIRRORS.md`` — findings and row count."""
    mirrors_path = repo / "MIRRORS.md"
    if not mirrors_path.is_file():
        raise GateError(
            code="MIRRORS_FILE_MISSING",
            message="MIRRORS.md not found — run 'cf-mirror-check init' to create one",
            context={"repo": str(repo)},
        )
    rows = parse_mirrors(mirrors_path.read_text(encoding="utf-8"))
    effective_today = today if today is not None else dt.date.today()
    violations: list[GateViolation] = []
    for row in rows:
        violations.extend(_check_row(repo, row, max_pin_age_days, effective_today))
    return violations, len(rows)


def render_template() -> str:
    """The template MIRRORS.md that ``init`` writes."""
    return _TEMPLATE


def init_mirrors(repo: Path) -> Path:
    """Write a template MIRRORS.md into ``repo``; refuse to overwrite."""
    path = repo / "MIRRORS.md"
    if path.exists():
        raise GateError(
            code="MIRRORS_ALREADY_EXISTS",
            message="MIRRORS.md already exists — refusing to overwrite a live declaration",
            context={"path": str(path)},
        )
    path.write_text(render_template(), encoding="utf-8")
    return path


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="cf-mirror-check",
        description="Gate: cross-repo copies are declared mirrors, and declarations expire.",
    )
    parser.add_argument(
        "mode",
        nargs="?",
        choices=("check", "init"),
        default="check",
        help="check (default) verifies MIRRORS.md; init writes a template",
    )
    parser.add_argument("--repo", default=".", help="target repo root (default: cwd)")
    parser.add_argument(
        "--max-pin-age-days",
        type=int,
        default=DEFAULT_MAX_PIN_AGE_DAYS,
        help=f"fail pins older than this many days (default {DEFAULT_MAX_PIN_AGE_DAYS})",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Console entrypoint. Exit 0 clean, 1 on violations, 2 when the gate cannot run."""
    args = _parse_args(argv)
    repo = Path(args.repo)
    try:
        if args.mode == "init":
            path = init_mirrors(repo)
            print(f"wrote {path}")
            return 0
        violations, rows = check_mirrors(repo, max_pin_age_days=args.max_pin_age_days)
    except GateError as error:
        return print_verdict("cf-mirror-check", [], error)
    return print_verdict(
        "cf-mirror-check",
        violations,
        measured=f"— checked {rows} declared mirror row(s) in MIRRORS.md",
        evidence={"mirror_rows": rows},
        clean_summary="cf-mirror-check: OK",
        fail_summary=f"cf-mirror-check: FAIL ({len(violations)} violation(s))",
    )


if __name__ == "__main__":
    raise SystemExit(main())
