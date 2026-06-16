"""cf-sticky-check — the sticky-intro gauge (the BubbleGum Law's mount).

``check`` mode: the consumer repo's CLAUDE.md must carry the canonical sticky
block byte-identical (line-ending normalization only), as LIVE content, and
exactly once. Detection is anchored to line overlap against the whole block,
never to its first line (the refuter's chewed-heading attack downgraded
TAMPERED to ABSENT and tricked mount into duplicating the block):

- a near-copy (>=50% of the block's non-empty lines present) that is not
  byte-identical fails ``STICKY_INTRO_TAMPERED`` with a unified diff;
- a block present only inside an HTML comment or a fenced code block fails
  ``STICKY_INTRO_BURIED`` — carried in bytes, invisible to a reader;
- a second copy (pristine or chewed, including a same-heading contradictory
  block) alongside the canonical one fails ``STICKY_INTRO_DUPLICATED``;
- neutralizing prose in the lines directly above the block ("DEPRECATED",
  "does not apply", "ignore", ...) fails ``STICKY_INTRO_NEUTRALIZED``;
- no recognizable trace of the block fails ``STICKY_INTRO_ABSENT``.

``mount`` mode: append the block under a one-line declared-mirror header when
absent; idempotent (a second mount is a no-op); refuses to mount over ANY
recognizable near-copy of the block — chewed gum (heading included) is never
silently duplicated or papered over.

The client membrane (ADR 0030 §11): client repos receive gate-config ONLY —
never sticky/chrome. A repo declaring ``[tool.cf-quality] client_repo = true``
(committed, Wizard-gated state — see :mod:`cf_quality.repo_config`) is
therefore waived from carrying the block, LOUDLY (the CLI prints the waiver,
never a silent pass), and the membrane is two-way:

- declared client + no CLAUDE.md (or a CLAUDE.md without chrome) -> pass,
  with the visible client-membrane notice;
- declared client + ANY recognizable sticky chrome (the canonical block,
  a chewed or older-vintage copy, or the kit's mirror header) fails
  ``STICKY_CLIENT_MEMBRANE_BREACHED``;
- ``mount`` refuses a declared client repo (``STICKY_MOUNT_CLIENT_MEMBRANE``)
  — the kit never pushes chrome through the membrane;
- an undeclared repo keeps today's behavior exactly, and a tampered
  declaration fails typed (``GATE_CONFIG_INVALID``) — the waiver cannot be
  adopted by accident or by a loose string.

The canonical text is loaded from the KIT's own packaged data file
(``cf_quality/data/sticky-intro.md``, via :mod:`importlib.resources` so wheel
and editable installs resolve identically), never from the consumer repo —
the gauge block comes from the factory, so a consumer cannot re-declare its
own edited copy as canonical (the declare-don't-fix and vendored-copy-edit
gaming vectors from the Law 5 refuter).

HONEST OPEN (salience): the neutralizer check is a keyword heuristic, not an
understanding of prose — wording it polices can be paraphrased past it. Full
salience (does the operative document actually TEACH the law?) is a reading
task; the heuristic catches the cheap wrappers and the rest belongs to review
and the scanning models themselves. Recorded in DESIGN.md Open issues.
"""

from __future__ import annotations

import argparse
import difflib
import math
import re
from importlib import resources
from pathlib import Path

from cf_quality import repo_config
from cf_quality.errors import GateError, GateViolation
from cf_quality.reporting import print_verdict

MIRROR_HEADER = (
    "<!-- declared mirror of candyfactory-canon ADR 0029 + ADR 0030"
    " · mounted by candyfactory-quality -->"
)
#: Any vintage of the kit's mount header marks chrome — the v1 header named
#: only ADR 0029, so the breach check keys on the stable mounted-by suffix.
_MOUNT_MARKER = "mounted by candyfactory-quality"
#: The loud waiver notice — printed whenever the membrane is honored.
CLIENT_MEMBRANE_NOTICE = (
    "=== client membrane declared — sticky intro not mounted per ADR 0030 §11 "
    "(client repos receive gate-config only, never chrome) ==="
)

_DATA_FILENAME = "sticky-intro.md"


def _normalize(text: str) -> str:
    """Line-ending normalization only — every other byte is load-bearing."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def canonical_text() -> str:
    """The canonical sticky block, from the kit's packaged data file.

    ``importlib.resources`` resolves the SAME path under a wheel install and
    an editable/source-tree install — the mount wave proved a filesystem-
    relative lookup is a lie under non-editable installs (the wheel had
    simply not packaged the file; the loader's editable fallback masked it).
    """
    resource = resources.files("cf_quality").joinpath("data", _DATA_FILENAME)
    try:
        return _normalize(resource.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise GateError(
            code="STICKY_CANONICAL_MISSING",
            message="the kit's canonical sticky-intro data file was not found",
            context={"resource": str(resource)},
        ) from exc


#: A near-copy is recognized when at least this share of the block's
#: non-empty lines appear verbatim in the document.
_OVERLAP_THRESHOLD = 0.5
#: Live lines inspected directly above the block for neutralizing prose.
_NEUTRALIZER_WINDOW = 5
_NEUTRALIZER = re.compile(
    r"\b(?:deprecated?|does not apply|disregard(?:ed)?|ignored?|obsolete|superseded?)\b",
    re.IGNORECASE,
)

#: (1-based original line number, line text) — a line a reader actually sees.
_LiveLine = tuple[int, str]


def _live_lines(lines: list[str]) -> list[_LiveLine]:
    """Lines a reader sees: HTML-comment regions and fenced code are dropped."""
    live: list[_LiveLine] = []
    in_comment = False
    in_fence = False
    for number, line in enumerate(lines, start=1):
        if in_fence:
            in_fence = not line.lstrip().startswith("```")
            continue
        if in_comment:
            in_comment = "-->" not in line
            continue
        stripped = line.lstrip()
        if stripped.startswith("```"):
            in_fence = True
            continue
        if "<!--" in line and "-->" not in line.split("<!--", 1)[1]:
            in_comment = True
            continue
        live.append((number, line))
    return live


def _find_block(canonical_lines: list[str], live: list[_LiveLine]) -> list[int]:
    """Start indices (into ``live``) of byte-identical occurrences of the block."""
    texts = [line for _, line in live]
    width = len(canonical_lines)
    return [i for i in range(len(texts) - width + 1) if texts[i : i + width] == canonical_lines]


def _near_match_start(canonical_lines: list[str], live: list[_LiveLine]) -> int | None:
    """Best-aligned start of a recognizable near-copy, or None below threshold."""
    significant = [line for line in canonical_lines if line.strip()]
    texts = [line for _, line in live]
    present = set(texts)
    matched = [line for line in significant if line in present]
    if len(matched) < math.ceil(len(significant) * _OVERLAP_THRESHOLD):
        return None
    first = matched[0]
    return max(0, texts.index(first) - canonical_lines.index(first))


def _tampered_violation(
    claude_md: Path, canonical_lines: list[str], live: list[_LiveLine], start: int
) -> GateViolation:
    """A recognizable near-copy of the block is present but not byte-identical."""
    found = [line for _, line in live[start : start + len(canonical_lines)]]
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
        line=live[start][0],
        context={"diff": diff},
    )


def _salience_violations(
    claude_md: Path, canonical_lines: list[str], live: list[_LiveLine], occurrences: list[int]
) -> list[GateViolation]:
    """The block is present and pristine; presence still is not salience."""
    path = str(claude_md)
    start = occurrences[0]
    if len(occurrences) > 1:
        return [_duplicated(path, "the canonical block appears more than once")]
    leftover = live[:start] + live[start + len(canonical_lines) :]
    heading = canonical_lines[0]
    if any(line == heading for _, line in leftover) or (
        _near_match_start(canonical_lines, leftover) is not None
    ):
        return [
            _duplicated(
                path,
                "a second (possibly contradictory) copy of the block exists "
                "alongside the canonical one",
            )
        ]
    window = live[max(0, start - _NEUTRALIZER_WINDOW) : start]
    if any(_NEUTRALIZER.search(line) for _, line in window):
        return [
            GateViolation(
                code="STICKY_INTRO_NEUTRALIZED",
                message=(
                    "the sticky intro is preceded by neutralizing prose "
                    "(deprecated / does not apply / ignore) — presence is not salience"
                ),
                path=path,
                line=live[start][0],
            )
        ]
    return []


def _duplicated(path: str, detail: str) -> GateViolation:
    return GateViolation(
        code="STICKY_INTRO_DUPLICATED",
        message=f"the sticky intro must appear exactly once: {detail}",
        path=path,
    )


def _membrane_violations(claude_md: Path, canonical_lines: list[str]) -> list[GateViolation]:
    """The two-way membrane: a declared client repo must NOT carry chrome.

    Chrome is recognized by the canonical heading line, the kit's mount
    marker (any vintage — the v1 header differs from today's), or an exact /
    near copy of the canonical block in the RAW bytes (a buried copy is
    chrome too). Prose merely naming the law is not chrome.
    """
    raw_lines = _normalize(claude_md.read_text(encoding="utf-8")).splitlines()
    raw_pairs = list(enumerate(raw_lines, start=1))
    heading = canonical_lines[0]
    carries_chrome = (
        any(line.strip() == heading for line in raw_lines)
        or any(_MOUNT_MARKER in line for line in raw_lines)
        or bool(_find_block(canonical_lines, raw_pairs))
        or _near_match_start(canonical_lines, raw_pairs) is not None
    )
    if not carries_chrome:
        return []
    return [
        GateViolation(
            code="STICKY_CLIENT_MEMBRANE_BREACHED",
            message=(
                "this repo declares client_repo = true but carries sticky chrome — "
                "the membrane is two-way: client repos receive gate-config only, "
                "never the sticky intro (remove the block or the declaration)"
            ),
            path=str(claude_md),
        )
    ]


def check(claude_md: Path) -> list[GateViolation]:
    """Gauge one CLAUDE.md against the kit's canonical sticky block."""
    client = repo_config.load(claude_md.parent).client_repo
    if not claude_md.is_file():
        if client:
            return []  # the membrane waives the mount; the CLI prints it loud
        return [
            GateViolation(
                code="STICKY_CLAUDE_MD_MISSING",
                message="the target repo has no CLAUDE.md to carry the sticky intro",
                path=str(claude_md),
            )
        ]
    canonical_lines = canonical_text().splitlines()
    if client:
        return _membrane_violations(claude_md, canonical_lines)
    raw_lines = _normalize(claude_md.read_text(encoding="utf-8")).splitlines()
    live = _live_lines(raw_lines)
    occurrences = _find_block(canonical_lines, live)
    if occurrences:
        return _salience_violations(claude_md, canonical_lines, live, occurrences)
    near = _near_match_start(canonical_lines, live)
    if near is not None:
        return [_tampered_violation(claude_md, canonical_lines, live, near)]
    raw_pairs = list(enumerate(raw_lines, start=1))
    if _find_block(canonical_lines, raw_pairs) or (
        _near_match_start(canonical_lines, raw_pairs) is not None
    ):
        return [
            GateViolation(
                code="STICKY_INTRO_BURIED",
                message=(
                    "the sticky intro sits inside an HTML comment or fenced code "
                    "block — carried in bytes, invisible to a reader; it teaches nothing"
                ),
                path=str(claude_md),
            )
        ]
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
    """Append the canonical block when absent. Returns True iff it wrote.

    Refuses on ANY recognizable near-copy (heading chewed or not) so a
    tampered block is never silently duplicated or papered over; refuses a
    declared client repo outright — the kit never pushes chrome through the
    client membrane.
    """
    if repo_config.load(claude_md.parent).client_repo:
        raise GateError(
            code="STICKY_MOUNT_CLIENT_MEMBRANE",
            message=(
                "refusing to mount the sticky intro into a declared client repo — "
                "client repos receive gate-config only, never sticky/chrome "
                "(the client membrane, ADR 0030 §11)"
            ),
            context={"path": str(claude_md)},
        )
    canonical = canonical_text()
    canonical_lines = canonical.splitlines()
    existing = _normalize(claude_md.read_text(encoding="utf-8")) if claude_md.is_file() else ""
    live = _live_lines(existing.splitlines())
    if _find_block(canonical_lines, live):
        return False  # already mounted byte-identical — no-op
    if _near_match_start(canonical_lines, live) is not None:
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
    notices: list[str] = []
    if not violations and repo_config.load(target.parent).client_repo:
        notices.append(CLIENT_MEMBRANE_NOTICE)  # the waiver is loud, never silent
    return print_verdict(
        "cf-sticky-check",
        violations,
        notices=notices,
        clean_summary="cf-sticky-check: OK",
        fail_summary=f"cf-sticky-check: FAIL ({len(violations)} violation(s))",
    )


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
        return print_verdict("cf-sticky-check", [], error)


if __name__ == "__main__":
    raise SystemExit(main())
