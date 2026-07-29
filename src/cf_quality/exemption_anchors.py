"""The anchor half of cf-exemptions — a blessing that points at nothing is rot.

Split from :mod:`cf_quality.exemptions` because the file law MEASURES (that
module sits against the 500-line cap) and because the halves answer different
refuters: the matcher there asks "does every suppression have a blessing?";
this asks the mirror question the gate never asked — "does every blessing
still point at the code it blessed?"

The defect, measured against a live consumer registry: ``_match_suppressions``
counted how many suppressions each entry matched and failed only on
``count > 1``. A ``count == 0`` entry — one whose anchored symbol was RENAMED
away — was tolerated in silence, and ``frozen_count`` ratchets ENTRIES, never
live coverage, so the ratchet stayed satisfied. Two harms rode on the silence:

1. the renamed site matched nothing and was reported
   ``UNREGISTERED_SUPPRESSION`` — "a self-issued suppression is not an
   exemption". Convincing, and after a rename WRONG: the site WAS blessed; the
   pointer rotted. A consumer's notes record that this class of misleading
   message has cost real review time and nearly provoked rewrites of
   load-bearing error barriers. Naming innocent code as the culprit is the scar
   this module refuses, so :func:`audit` publishes the stale anchors
   (:attr:`AnchorAudit.rotted`) and the matcher picks its message from them;
2. rename some OTHER symbol INTO the orphaned name and its suppression is
   silently blessed by an entry whose ``reason`` and ``approver`` describe
   entirely different code — an approval transferred to code nobody approved
   (``EXEMPTION_ANCHOR_CONTESTED``).

Three world-states, three codes, three remedies — never one vague "dead entry",
because the reader ACTS on the message: ``EXEMPTION_FILE_MISSING``,
``EXEMPTION_SYMBOL_MISSING``, ``EXEMPTION_SUPPRESSION_GONE`` (each message
carries its own remedy; DESIGN.md §4.3 carries the table).

Deliberately NOT violations, because reding a consumer for a decision it
DOCUMENTED teaches consumers to pin an older SHA: (a) LINE-ANCHORED entries,
named loudly with their migration path and nothing more — the flagship consumer
pins 3 of 52 at sites no symbol identifies uniquely and documents each one, so
promotion is the operator's policy call (DESIGN.md open issue 18); (b)
UNMEASURABLE entries — outside the scanned surface, an ungated rule, an
unreadable file — because an entry the scanner never read cannot be graded, and
grading it anyway is the innocent-culprit failure running the other way.

Every denominator is printed (``=== ANCHOR AUDIT: ...``): a population that
selects itself by the value it guards goes vacuous in silence, so a run that
checked nothing must SAY it checked nothing.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cf_quality.errors import GateViolation
from cf_quality.exemption_surface import in_surface

GATED_NOQA_RULES = frozenset({"C901", "PLR0915"})
#: Whole rule families that are registry-gated code-by-code: the ruff-ported
#: bandit battery (S###) and the Elegance Law's blind-except ban (BLE###).
_GATED_FAMILY_RE = re.compile(r"^(?:S|BLE)\d+$")
#: The bandit ids a ``# nosec B###`` comment yields — the same suppression
#: reached through bandit's own vocabulary rather than ruff's.
_BANDIT_RULE_RE = re.compile(r"^B\d{3}$")
#: mypy error codes whose ``# type: ignore[...]`` suppression is registry-gated:
#: ``override`` is the one token that silences the substitutability gauge
#: (mypy's [override] / Liskov error) entirely. Other codes ride the mypy
#: gauge (``warn_unused_ignores``) + review.
GATED_TYPE_IGNORE_CODES = frozenset({"override"})

_REANCHOR = "re-anchor the entry to the enclosing symbol's current qualified name"
_DROP = "drop this entry and lower frozen_count"


@dataclass(frozen=True)
class Suppression:
    """One gated suppression comment found in the code under measurement."""

    path: str
    line: int
    rule: str
    symbol: str | None


@dataclass(frozen=True)
class AnchorAudit:
    """The anchor half's verdict.

    ``rotted`` maps a ``(file, rule)`` pair to descriptions of every entry in
    that group whose anchor covers nothing live — the ONLY input the matcher
    needs to stop accusing a renamed site of self-issuing its suppression. The
    discrimination rule lives at the matcher; the evidence is measured here.
    """

    violations: list[GateViolation]
    notices: list[str]
    rotted: dict[tuple[str, str], list[str]]


@dataclass(frozen=True)
class _FileFacts:
    """What one registry-named file IS, measured once per file.

    ``symbols`` is None when the file could not be parsed: absent an AST the
    module makes NO claim about whether a symbol exists, because "I could not
    read it" and "it is gone" are different world-states.
    """

    exists: bool
    scanned: bool
    lines: int
    symbols: frozenset[str] | None


def is_gated_code(code: str) -> bool:
    """Form budgets plus the whole S and BLE families are registry-gated."""
    return code in GATED_NOQA_RULES or _GATED_FAMILY_RE.match(code) is not None


def is_registrable_rule(rule: str) -> bool:
    """True when the SCANNER can ever emit this rule, so an entry for it is gradeable.

    The exact union of what :mod:`cf_quality.exemptions` extracts — gated ruff
    codes, bandit ``B###`` from ``# nosec``, gated type-ignore codes. An entry
    naming anything else (a consumer documenting an ``E402`` it keeps for its
    own reasons) can never match by construction, so grading it as rot would
    invent a defect out of a documentation habit.
    """
    return (
        is_gated_code(rule)
        or _BANDIT_RULE_RE.match(rule) is not None
        or rule in GATED_TYPE_IGNORE_CODES
    )


def covers(entry: dict[str, Any], suppression: Suppression) -> bool:
    """An entry covers a suppression by file + rule + (line OR enclosing symbol).

    THE one resolution rule, shared by the matcher (``exemptions._matches``
    adapts it at its published argument order) and the anchor audit. Two copies
    would let coverage and liveness disagree — a gauge that does not measure
    what its name says.
    """
    if entry["file"] != suppression.path or entry["rule"] != suppression.rule:
        return False
    anchor = str(entry["symbol_or_line"]).strip()
    return anchor == str(suppression.line) or anchor == suppression.symbol


def _read_source(file_path: Path) -> str | None:
    """The file's text, or None when it cannot be read — never an accusation.

    ``ValueError`` covers ``UnicodeDecodeError``; naming both would be a
    redundant handler pair.
    """
    try:
        return file_path.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return None


def _parse_source(text: str) -> ast.Module | None:
    """The parsed module, or None when the source will not parse."""
    try:
        return ast.parse(text)
    except (SyntaxError, ValueError):
        return None


def _spans_of(tree: ast.Module) -> list[tuple[int, int, str]]:
    """(start, end, QUALIFIED name) spans of every def/class in one parsed tree."""
    spans: list[tuple[int, int, str]] = []
    pending: list[tuple[ast.AST, str]] = [(tree, "")]
    while pending:
        node, prefix = pending.pop()
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                qualname = f"{prefix}{child.name}"
                if child.end_lineno is not None:
                    spans.append((child.lineno, child.end_lineno, qualname))
                pending.append((child, f"{qualname}."))
            else:
                pending.append((child, prefix))
    return spans


def symbol_spans(file_path: Path) -> list[tuple[int, int, str]]:
    """(start, end, QUALIFIED name) spans of every def/class.

    Names are dotted paths (``Outer.run``), never bare names — the refuter
    showed that bare names let N same-named suppressions collapse onto one
    registry entry. Empty when unparsable (line match only).
    """
    text = _read_source(file_path)
    tree = None if text is None else _parse_source(text)
    return [] if tree is None else _spans_of(tree)


def enclosing_symbol(spans: list[tuple[int, int, str]], line: int) -> str | None:
    """Innermost def/class name enclosing a line, or None at module level."""
    best: tuple[int, str] | None = None
    for start, end, name in spans:
        if start <= line <= end and (best is None or end - start < best[0]):
            best = (end - start, name)
    return best[1] if best else None


def _file_facts(root: Path, rel: str, surface: tuple[Path, ...]) -> _FileFacts:
    """Measure one registry-named file: existence, scanned-ness, size, symbols."""
    path = root / rel
    if not path.is_file():
        return _FileFacts(exists=False, scanned=False, lines=0, symbols=None)
    if not in_surface(path, surface):
        return _FileFacts(exists=True, scanned=False, lines=0, symbols=None)
    text = _read_source(path)
    if text is None:
        return _FileFacts(exists=True, scanned=True, lines=0, symbols=None)
    tree = _parse_source(text)
    symbols = None if tree is None else frozenset(name for _, _, name in _spans_of(tree))
    return _FileFacts(exists=True, scanned=True, lines=len(text.splitlines()), symbols=symbols)


def _unmeasured(index: int, entry: dict[str, Any], why: str) -> str:
    """A notice for an entry the gate cannot grade — never a verdict."""
    return (
        f"UNMEASURED ENTRY: entry {index} ({entry['file']} '{entry['rule']}' at "
        f"'{entry['symbol_or_line']}') {why} — the gate makes no claim about this "
        "anchor; it documents, it does not gate"
    )


def _dead(index: int, entry: dict[str, Any], code: str, message: str) -> GateViolation:
    """One zero-coverage verdict, always located at the registry that holds it."""
    return GateViolation(
        code=code,
        message=f"entry {index}: {message}",
        path="exemptions.json",
        context={
            "entry_index": index,
            "file": entry["file"],
            "rule": entry["rule"],
            "anchor": entry["symbol_or_line"],
        },
    )


def _line_anchor_verdict(
    index: int, entry: dict[str, Any], line: int, facts: _FileFacts
) -> GateViolation:
    """The line-anchored analogue of a dead symbol anchor: out of range, or clean."""
    rel, rule = entry["file"], entry["rule"]
    where = f"line {line} of {rel} carries no '{rule}' suppression"
    if line > facts.lines:
        where = (
            f"line {line} does not exist in {rel} (the file has {facts.lines} lines), "
            f"so it carries no '{rule}' suppression"
        )
    return _dead(
        index,
        entry,
        "EXEMPTION_SUPPRESSION_GONE",
        f"{where} — a line anchor rots on any insertion above it; the suppression moved or "
        f"was removed, so {_REANCHOR}, or {_DROP}",
    )


def _zero_coverage_verdict(
    index: int, entry: dict[str, Any], facts: _FileFacts
) -> GateViolation | str:
    """Name the world-state behind ONE entry that covers nothing live.

    A violation when the registry is provably wrong; a notice string when the
    entry is outside what this gate measures. The order is deliberate: file
    existence is unambiguous and is settled first, so a deleted file is never
    softened into "unmeasured" by a rule or surface technicality.
    """
    rel, rule = entry["file"], entry["rule"]
    anchor = str(entry["symbol_or_line"]).strip()
    if not facts.exists:
        return _dead(
            index,
            entry,
            "EXEMPTION_FILE_MISSING",
            f"the anchored file {rel} no longer exists — drop the entry (and lower "
            f"frozen_count) or re-point it at the file that carries the '{rule}' suppression",
        )
    if not facts.scanned:
        return _unmeasured(index, entry, "sits outside the measured source surface")
    if not is_registrable_rule(rule):
        return _unmeasured(index, entry, f"names '{rule}', a rule this gate never gates")
    if facts.symbols is None:
        return _unmeasured(index, entry, f"lives in {rel}, which could not be read or parsed")
    if anchor.isdigit():
        return _line_anchor_verdict(index, entry, int(anchor), facts)
    if anchor not in facts.symbols:
        return _dead(
            index,
            entry,
            "EXEMPTION_SYMBOL_MISSING",
            f"the anchored symbol '{anchor}' no longer exists in {rel} (renamed or "
            f"removed) — {_REANCHOR}",
        )
    return _dead(
        index,
        entry,
        "EXEMPTION_SUPPRESSION_GONE",
        f"the anchored symbol '{anchor}' exists in {rel} but carries no '{rule}' "
        f"suppression — the suppression was removed; {_DROP}",
    )


def _grade_entries(
    root: Path,
    entries: list[dict[str, Any]],
    suppressions: list[Suppression],
    surface: tuple[Path, ...],
) -> list[GateViolation | str | None]:
    """One positional verdict per entry: None = live coverage, violation = rot, str = notice."""
    facts: dict[str, _FileFacts] = {}
    verdicts: list[GateViolation | str | None] = []
    for index, entry in enumerate(entries):
        rel = str(entry["file"])
        if rel not in facts:
            facts[rel] = _file_facts(root, rel, surface)
        if any(covers(entry, suppression) for suppression in suppressions):
            verdicts.append(None)
        else:
            verdicts.append(_zero_coverage_verdict(index, entry, facts[rel]))
    return verdicts


def _rotted_index(
    entries: list[dict[str, Any]], verdicts: list[GateViolation | str | None]
) -> dict[tuple[str, str], list[str]]:
    """(file, rule) -> descriptions of the entries in that group covering nothing live."""
    rotted: dict[tuple[str, str], list[str]] = {}
    for index, verdict in enumerate(verdicts):
        if not isinstance(verdict, GateViolation):
            continue
        entry = entries[index]
        key = (str(entry["file"]), str(entry["rule"]))
        rotted.setdefault(key, []).append(f"entry {index} anchored '{entry['symbol_or_line']}'")
    return rotted


def _line_anchor_notices(entries: list[dict[str, Any]]) -> list[str]:
    """Part C: line anchors are named LOUDLY and are NOT a violation.

    Turning them red would fail a consumer for a documented decision (a live
    consumer pins sites no symbol identifies uniquely), so the gate reports the
    population plus the migration path and leaves the policy to the operator.
    Silence is not an option: this is the anchor shape that rots on insertion.
    """
    pinned = [
        (index, entry)
        for index, entry in enumerate(entries)
        if str(entry["symbol_or_line"]).strip().isdigit()
    ]
    if not pinned:
        return []
    notices = [
        f"=== LINE-ANCHORED ENTRIES: {len(pinned)} of {len(entries)} (NOTICE, not a violation) ==="
    ]
    notices.extend(
        f"line-anchored: entry {index} {entry['file']}:{entry['symbol_or_line']} "
        f"'{entry['rule']}' — rots on any insertion above the line"
        for index, entry in pinned
    )
    notices.append(
        "migration path: replace symbol_or_line with the enclosing symbol's QUALIFIED "
        "name (Class.method); keep a line only where no symbol identifies the site uniquely"
    )
    return notices


def _group_sites(
    owners: list[tuple[int, dict[str, Any]]], group: list[Suppression]
) -> tuple[dict[int, str], list[str]]:
    """Split one (file, rule) group into {entry index -> claimed site} and unregistered sites."""
    claimed: dict[int, str] = {}
    unregistered: list[str] = []
    for suppression in group:
        hits = [index for index, entry in owners if covers(entry, suppression)]
        site = f"{suppression.path}:{suppression.line}"
        if hits:
            claimed[hits[0]] = site
        else:
            unregistered.append(site)
    return claimed, unregistered


def _contested(
    entries: list[dict[str, Any]], suppressions: list[Suppression]
) -> list[GateViolation]:
    """The bystander refuter: a rename can move an approval onto code nobody approved.

    Rename a blessed ``def`` away and an unrelated ``def`` INTO its name: the
    orphaned entry matches the newcomer, its ``reason`` and ``approver`` bless
    code they never described, and the anchor is technically alive, so
    :func:`_zero_coverage_verdict` cannot see it. The GROUP is visible though —
    an entry claiming a site while a sibling site in the same (file, rule) pair
    is unregistered means the pairing cannot be settled by name alone. The gate
    names the ambiguity and both sides, never which site is the impostor: from
    one snapshot it cannot know, and naming an unprovable culprit is the
    misleading-message scar again.
    """
    violations: list[GateViolation] = []
    groups: dict[tuple[str, str], list[Suppression]] = {}
    for suppression in suppressions:
        groups.setdefault((suppression.path, suppression.rule), []).append(suppression)
    for (rel, rule), group in sorted(groups.items()):
        owners = [
            (index, entry)
            for index, entry in enumerate(entries)
            if (str(entry["file"]), str(entry["rule"])) == (rel, rule)
        ]
        claimed, unregistered = _group_sites(owners, group)
        if not claimed or not unregistered:
            continue
        violations.append(_contested_violation(rel, rule, entries, group, (claimed, unregistered)))
    return violations


def _contested_violation(
    rel: str,
    rule: str,
    entries: list[dict[str, Any]],
    group: list[Suppression],
    split: tuple[dict[int, str], list[str]],
) -> GateViolation:
    """The contested-group report: both sides named, no culprit invented."""
    claimed, unregistered = split
    claims = ", ".join(
        f"entry {index} (anchored '{entries[index]['symbol_or_line']}') claims {site}"
        for index, site in sorted(claimed.items())
    )
    return GateViolation(
        code="EXEMPTION_ANCHOR_CONTESTED",
        message=(
            f"{rel} '{rule}': {len(group)} live suppressions, {len(claimed)} claimed by "
            f"entries; unregistered: {', '.join(unregistered)}; {claims} — after a rename an "
            "entry's reason and approver can land on code nobody approved, and from one "
            "snapshot the gate cannot tell which site an entry was written for: anchor every "
            "suppression in this group to its own qualified symbol"
        ),
        path="exemptions.json",
        context={
            "file": rel,
            "rule": rule,
            "live_suppressions": len(group),
            "claimed_sites": sorted(claimed.values()),
            "unregistered_sites": unregistered,
        },
    )


def audit(
    root: Path,
    entries: list[dict[str, Any]],
    suppressions: list[Suppression],
    surface: tuple[Path, ...],
) -> AnchorAudit:
    """Grade every registry anchor against the live suppression population.

    ``surface`` is the discovered scan bases (``_discover_scan_paths``): an
    entry outside them cannot be graded, only noticed. The header line
    publishes the denominators the audit reasoned from because a population
    that selects itself by the value it guards goes vacuous in silence: a run
    that checked nothing must SAY it checked nothing.
    """
    verdicts = _grade_entries(root, entries, suppressions, surface)
    dead = [verdict for verdict in verdicts if isinstance(verdict, GateViolation)]
    unmeasured = [verdict for verdict in verdicts if isinstance(verdict, str)]
    live = sum(1 for verdict in verdicts if verdict is None)
    header = (
        f"=== ANCHOR AUDIT: {len(entries) - len(unmeasured)} entries graded vs "
        f"{len(suppressions)} live gated suppression(s) — {live} anchors live, "
        f"{len(dead)} dead, {len(unmeasured)} unmeasured ==="
    )
    return AnchorAudit(
        violations=[*dead, *_contested(entries, suppressions)],
        notices=[header, *unmeasured, *_line_anchor_notices(entries)],
        rotted=_rotted_index(entries, verdicts),
    )
