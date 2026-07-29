"""cf-exemptions — the suppression-registration gate of the BubbleGum Law.

Answers the Law-2 refuter's "self-issued Wizard exemption" gaming vector by
making Wizard-gating mechanical, never prose:

(a) a bare ``# nosec`` (no rule id AND no reason) FAILS, and so does a bare
    codeless ``# noqa`` (``BARE_NOQA``) — ruff honors a codeless noqa as a
    BLANKET suppression, strictly more powerful than any coded one (the
    refuter's bare-noqa bypass); it names no rule, so no registry entry can
    cover it. The ruff gauge independently selects PGH004/RUF100 so blanket
    and unused noqa also fail at lint altitude;
(b) every gated suppression must match a committed entry in
    ``exemptions.json`` ({file, symbol_or_line, rule, reason, approver}); an
    unregistered suppression FAILS the gate. Gated families: the form budgets
    (``# noqa: C901`` / ``# noqa: PLR0915``), the security battery
    (``# noqa: S###`` and ``# nosec B###``), and the Elegance Law's
    blind-except ban (``# noqa: BLE###``) — everything the gauge selects as a
    security or honesty gate, per the refuter's S602/BLE001 bypass. Other
    noqa codes (style/imports: E/F/I/UP/B) ride on ruff + review. The
    substitutability gauge gets the same protection: a coded
    ``type: ignore[override]`` comment silences mypy's [override] (Liskov)
    error entirely, so the override family is registry-gated too (rule
    ``override``); other type-ignore codes and bare ``# type: ignore`` stay
    the mypy gauge's jurisdiction (``warn_unused_ignores``). Registered
    sites pass LOUDLY — each covered suppression is printed with its entry,
    a visible exemption, never a silent one;
(c) the exemption count is ratcheted: ``exemptions.json`` carries
    ``frozen_count``. Entries may be removed freely; additions require
    bumping ``frozen_count``, and the gate prints the ratchet loudly on
    every run — a visible decision, never a silent one. Symbols are matched
    by QUALIFIED name (``ClassA.run``, never bare ``run``), and an entry
    matching more than one live suppression fails
    (``EXEMPTION_ENTRY_OVERLOADED``) — the refuter's name-collision attack
    collapsed N same-named suppressions onto one frozen entry;
(d) fold-in wrappers: when the target repo ships ``scripts/check_english.py``
    or ``scripts/check_host_free.py`` the gate runs them and propagates
    their exit codes; absent scripts are skipped silently;
(e) every entry must still ANCHOR at live code — the mirror of (b), delegated
    whole to :mod:`cf_quality.exemption_anchors` (that module's docstring and
    DESIGN.md §4.3 carry the taxonomy). The one thing decided HERE is which
    message an unmatched suppression earns (:func:`_unregistered_violation`).

The measured surface is the committed ``[tool.cf-quality] source_root`` when
declared — resolved through cf-repo-config exactly like the gauges (the
mexxa main-green pass proved the old behavior: a JS repo-root ``src/`` was
discovered, the declared ``server/src`` never visited, and every registered
exemption was documentation-grade). Absent a declaration, ``<root>/src``
when it exists; otherwise the layout is DISCOVERED (top-level
packages/modules outside tests/docs/scripts), so a flat or app layout is
measured, never a silent no-op (the refuter's src-only escape).

Comments are read via :mod:`tokenize` (COMMENT tokens only), so suppression
text inside string literals never trips the gate.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess  # fold-in scripts run via sys.executable, fixed argv, no shell (S603 gated below)
import sys
import tokenize
from pathlib import Path
from typing import Any

from cf_quality import exemption_anchors
from cf_quality.errors import GateError, GateViolation
from cf_quality.exemption_anchors import (
    GATED_TYPE_IGNORE_CODES,
    Suppression,
    covers,
    enclosing_symbol,
    is_gated_code,
    symbol_spans,
)
from cf_quality.exemption_surface import discover_scan_paths
from cf_quality.reporting import print_verdict

FOLD_IN_SCRIPTS = ("check_english.py", "check_host_free.py")
REQUIRED_ENTRY_KEYS = ("file", "symbol_or_line", "rule", "reason", "approver")

_NOSEC_RE = re.compile(r"#\s*nosec\b(.*)")
_NOQA_RE = re.compile(r"#\s*noqa\b:?\s*([A-Z]+[0-9]+(?:[\s,]+[A-Z]+[0-9]+)*)?")
_TYPE_IGNORE_RE = re.compile(r"#\s*type:\s*ignore\s*\[([^\]]+)\]")
_B_CODE_RE = re.compile(r"\bB\d{3}\b")
_CODE_SPLIT_RE = re.compile(r"[\s,]+")


def _comment_tokens(file_path: Path) -> list[tuple[int, str]]:
    """All COMMENT tokens of a file as (line, text); typed error if unreadable."""
    try:
        with tokenize.open(file_path) as handle:
            tokens = list(tokenize.generate_tokens(handle.readline))
    except (tokenize.TokenError, SyntaxError, UnicodeDecodeError) as exc:
        raise GateError(
            code="GATE_PARSE_FAILURE",
            message=f"cannot tokenize {file_path.name}: {exc}",
            context={"path": str(file_path)},
        ) from exc
    return [(tok.start[0], tok.string) for tok in tokens if tok.type == tokenize.COMMENT]


def _classify_comment(
    rel_path: str, line: int, text: str, symbol: str | None
) -> tuple[list[Suppression], list[GateViolation]]:
    """Extract gated suppressions and bare-nosec violations from one comment."""
    suppressions: list[Suppression] = []
    violations: list[GateViolation] = []
    nosec = _NOSEC_RE.search(text)
    if nosec:
        rest = nosec.group(1)
        b_codes = _B_CODE_RE.findall(rest)
        reason = _B_CODE_RE.sub("", rest).strip(" \t:,-")
        if b_codes:
            suppressions.extend(Suppression(rel_path, line, code, symbol) for code in b_codes)
        elif not reason:
            violations.append(
                GateViolation(
                    code="BARE_NOSEC",
                    message="bare '# nosec' with no rule id and no reason",
                    path=rel_path,
                    line=line,
                )
            )
    noqa = _NOQA_RE.search(text)
    if noqa and noqa.group(1):
        codes = _CODE_SPLIT_RE.split(noqa.group(1).strip())
        suppressions.extend(
            Suppression(rel_path, line, code, symbol) for code in codes if is_gated_code(code)
        )
    elif noqa:
        violations.append(
            GateViolation(
                code="BARE_NOQA",
                message=(
                    "codeless '# noqa' is a blanket suppression (ruff silences "
                    "EVERY rule on the line) — name the rule and register it"
                ),
                path=rel_path,
                line=line,
            )
        )
    suppressions.extend(_type_ignore_suppressions(rel_path, line, text, symbol))
    return suppressions, violations


def _type_ignore_suppressions(
    rel_path: str, line: int, text: str, symbol: str | None
) -> list[Suppression]:
    """Gated ``# type: ignore[...]`` codes found in one comment.

    Only the codes in :data:`GATED_TYPE_IGNORE_CODES` are registry-gated
    (the override family — the one comment that blinds the substitutability
    gauge). A multi-code ignore (``[override, misc]``) is still gated: hiding
    the token in a code list is the obvious bypass. A bare ``# type: ignore``
    names no code and stays the mypy gauge's jurisdiction.
    """
    match = _TYPE_IGNORE_RE.search(text)
    if not match:
        return []
    codes = _CODE_SPLIT_RE.split(match.group(1).strip())
    return [
        Suppression(rel_path, line, code, symbol)
        for code in codes
        if code in GATED_TYPE_IGNORE_CODES
    ]


def _scan_src(root: Path) -> tuple[list[Suppression], list[GateViolation]]:
    """Scan the discovered Python surface for suppression comments.

    The ``(suppressions, violations)`` ARITY is a published contract, not an
    implementation detail: a consumer's drift-proof pin unpacks exactly two
    values from this to cross-check its mirrored resolver (see
    :func:`_matches`). The anchor audit therefore takes its surface from
    :mod:`cf_quality.exemption_surface` rather than riding a third element.
    """
    suppressions: list[Suppression] = []
    violations: list[GateViolation] = []
    for base in discover_scan_paths(root):
        files = [base] if base.is_file() else sorted(base.rglob("*.py"))
        for file_path in files:
            rel_path = file_path.relative_to(root).as_posix()
            spans = symbol_spans(file_path)
            for line, text in _comment_tokens(file_path):
                found, broken = _classify_comment(
                    rel_path, line, text, enclosing_symbol(spans, line)
                )
                suppressions.extend(found)
                violations.extend(broken)
    return suppressions, violations


def _matches(suppression: Suppression, entry: dict[str, Any]) -> bool:
    """The resolution rule at its PUBLISHED name and argument order.

    A pure adapter over :func:`cf_quality.exemption_anchors.covers` — ONE
    implementation of the rule, never two, because two would let coverage and
    liveness disagree. The name survives the anchor-half split deliberately: a
    consumer's ``test_exemption_anchors_are_drift_proof`` pin calls
    ``exemptions._matches(suppression, entry)`` to prove its mirrored resolver
    has not drifted from this gate, and a cross-repo signature break cannot
    land as one PR. A contract, not dead code — do not "clean it up".
    """
    return covers(entry, suppression)


def _validate_entry(index: int, entry: Any) -> None:
    """Every entry carries the full five-field registration, none of it empty."""
    if not isinstance(entry, dict):
        raise GateError(
            code="GATE_CONFIG_INVALID",
            message=f"exemptions.json entry {index} is not an object",
            context={"index": index},
        )
    for key in REQUIRED_ENTRY_KEYS:
        value = entry.get(key)
        if key == "symbol_or_line" and isinstance(value, int) and not isinstance(value, bool):
            continue
        if isinstance(value, str) and value.strip():
            continue
        raise GateError(
            code="GATE_CONFIG_INVALID",
            message=f"exemptions.json entry {index} is missing or has an empty '{key}'",
            context={"index": index, "key": key},
        )


def _load_config(root: Path) -> tuple[list[dict[str, Any]], int] | None:
    """Parse exemptions.json; None when absent; typed error when malformed."""
    config_path = root / "exemptions.json"
    if not config_path.is_file():
        return None
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise GateError(
            code="GATE_CONFIG_INVALID",
            message=f"exemptions.json is not valid JSON: {exc}",
            context={"path": str(config_path)},
        ) from exc
    frozen_count = data.get("frozen_count") if isinstance(data, dict) else None
    if not isinstance(frozen_count, int) or isinstance(frozen_count, bool) or frozen_count < 0:
        raise GateError(
            code="GATE_CONFIG_INVALID",
            message="exemptions.json must carry an integer 'frozen_count' >= 0 (the ratchet)",
            context={"path": str(config_path)},
        )
    entries = data.get("entries")
    if not isinstance(entries, list):
        raise GateError(
            code="GATE_CONFIG_INVALID",
            message="exemptions.json must carry an 'entries' list",
            context={"path": str(config_path)},
        )
    for index, entry in enumerate(entries):
        _validate_entry(index, entry)
    return entries, frozen_count


def _ratchet_report(entry_count: int, frozen_count: int) -> tuple[list[GateViolation], list[str]]:
    """The count ratchet — always loud, never silent."""
    lines = [f"=== EXEMPTION RATCHET: {entry_count} entries / frozen_count {frozen_count} ==="]
    violations: list[GateViolation] = []
    if entry_count > frozen_count:
        violations.append(
            GateViolation(
                code="EXEMPTION_COUNT_EXCEEDED",
                message=(
                    f"{entry_count} exemption entries exceed frozen_count {frozen_count}: "
                    "adding an exemption requires bumping frozen_count — a visible, "
                    "reviewed decision, never a silent one"
                ),
                path="exemptions.json",
                context={"entries": entry_count, "frozen_count": frozen_count},
            )
        )
    elif entry_count < frozen_count:
        lines.append(
            f"RATCHET SLACK: frozen_count {frozen_count} exceeds live entries "
            f"{entry_count} — frozen_count may shrink to {entry_count}"
        )
    lines.append("additions require bumping frozen_count (visible decision, never silent)")
    return violations, lines


def check(root: Path) -> tuple[list[GateViolation], list[str], dict[str, int]]:
    """Run checks (a)-(e) — (violations, report lines, the counts measured)."""
    suppressions, violations = _scan_src(root)
    surface = tuple(discover_scan_paths(root))
    counts = {"suppressions": len(suppressions), "scan_paths": len(surface), "entries": 0}
    config = _load_config(root)
    if config is None:
        if suppressions:
            raise GateError(
                code="GATE_CONFIG_MISSING",
                message="gated suppressions found in src/ but exemptions.json is missing",
                context={"suppressions": len(suppressions)},
            )
        quiet = "no exemptions.json and no gated suppressions — nothing to register"
        return violations, [quiet], counts
    entries, frozen_count = config
    counts["entries"] = len(entries)
    anchors = exemption_anchors.audit(root, entries, suppressions, surface)
    match_violations, registered_lines = _match_suppressions(suppressions, entries, anchors.rotted)
    violations.extend(anchors.violations)
    violations.extend(match_violations)
    ratchet_violations, lines = _ratchet_report(len(entries), frozen_count)
    violations.extend(ratchet_violations)
    return violations, [*lines, *anchors.notices, *registered_lines], counts


def _unregistered_violation(
    suppression: Suppression, rotted: dict[tuple[str, str], list[str]]
) -> GateViolation:
    """Check (b)'s verdict — and the DISCRIMINATION that stops it from lying.

    A suppression with no entry is only *probably* self-issued. When the
    registry holds a stale anchor for the SAME file and the SAME rule — an
    entry the audit graded as covering nothing live — the likelier world is a
    RENAME: the site was blessed and the pointer rotted. The accusation ("a
    self-issued suppression is not an exemption") has cost real review time and
    nearly provoked rewrites of load-bearing error barriers, so it is reserved
    for the case where NOTHING rotted: every entry for the pair is live, or no
    entry names it. Then the strict message stands verbatim. This cannot soften
    the gate — code, path, line and exit level are IDENTICAL in both branches,
    only the prose differs, and the rot branch is reachable only once the
    orphan has emitted its OWN violation, so it never subtracts a finding.
    """
    key = (suppression.path, suppression.rule)
    stale = rotted.get(key)
    if not stale:
        message = (
            f"'{suppression.rule}' suppression has no matching entry in "
            "exemptions.json — a self-issued suppression is not an exemption"
        )
    else:
        hint = suppression.symbol or f"line {suppression.line}"
        message = (
            f"'{suppression.rule}' suppression has no matching entry, but the registry holds a "
            f"STALE anchor for this file+rule ({', '.join(stale)}) covering nothing live — very "
            "probably a RENAME: this site WAS blessed and the registry pointer rotted. "
            f"Re-anchor that entry to '{hint}' rather than reading this site as unblessed"
        )
    return GateViolation(
        code="UNREGISTERED_SUPPRESSION",
        message=message,
        path=suppression.path,
        line=suppression.line,
        context={
            "rule": suppression.rule,
            "symbol": suppression.symbol,
            "stale_anchors": list(stale or ()),
        },
    )


def _match_suppressions(
    suppressions: list[Suppression],
    entries: list[dict[str, Any]],
    rotted: dict[tuple[str, str], list[str]],
) -> tuple[list[GateViolation], list[str]]:
    """Every suppression needs an entry; every entry covers at most ONE.

    The 1:1 discipline is the ratchet's truth condition: N suppressions
    sharing one entry would keep ``frozen_count`` flat while live
    suppressions grow (the refuter's collision undercount). Covered
    suppressions are reported LOUDLY (site + entry) — a registered
    exemption is visible, never silent.
    """
    violations: list[GateViolation] = []
    registered: list[str] = []
    matched_counts = [0] * len(entries)
    for suppression in suppressions:
        hits = [i for i, entry in enumerate(entries) if covers(entry, suppression)]
        if not hits:
            violations.append(_unregistered_violation(suppression, rotted))
        else:
            registered.append(_registered_line(suppression, hits[0], entries[hits[0]]))
        for index in hits:
            matched_counts[index] += 1
    for index, count in enumerate(matched_counts):
        if count > 1:
            violations.append(
                GateViolation(
                    code="EXEMPTION_ENTRY_OVERLOADED",
                    message=(
                        f"exemptions.json entry {index} covers {count} live suppressions — "
                        "each suppression needs its own reasoned entry (1:1, ratchet-true)"
                    ),
                    path="exemptions.json",
                    context={"entry_index": index, "matched_suppressions": count},
                )
            )
    return violations, registered


def _registered_line(suppression: Suppression, index: int, entry: dict[str, Any]) -> str:
    """One loud report line for a covered suppression: the site and its entry."""
    site = f"{suppression.path}:{suppression.line}"
    symbol = f" ({suppression.symbol})" if suppression.symbol else ""
    return (
        f"registered: {site} '{suppression.rule}'{symbol} — covered by entry {index} "
        f"[{entry['symbol_or_line']}], approver {entry['approver']}"
    )


def _run_fold_ins(root: Path) -> tuple[list[str], int]:
    """Check (d): run repo-local wrapper scripts when present, propagate exit codes."""
    lines: list[str] = []
    exit_code = 0
    for name in FOLD_IN_SCRIPTS:
        script = root / "scripts" / name
        if not script.is_file():
            continue
        try:
            proc = subprocess.run(  # noqa: S603 — sys.executable + fixed repo-local script
                [sys.executable, str(script)],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as exc:
            raise GateError(
                code="GATE_FOLD_IN_FAILED",
                message=f"could not execute fold-in script {name}: {exc}",
                context={"script": str(script)},
                retryable=True,
            ) from exc
        lines.append(f"fold-in {name}: exit {proc.returncode}")
        if proc.stdout.strip():
            lines.append(proc.stdout.rstrip())
        if proc.stderr.strip():
            lines.append(proc.stderr.rstrip())
        if proc.returncode != 0 and exit_code == 0:
            exit_code = proc.returncode
    return lines, exit_code


def main(argv: list[str] | None = None) -> int:
    """Console entry point: 0 clean, 1 violations, 2 the gate itself could not run."""
    parser = argparse.ArgumentParser(
        prog="cf-exemptions",
        description="Every suppression traces to a reasoned, approved exemptions.json entry.",
    )
    parser.add_argument("--root", default=".", help="repo root to gate (default: cwd)")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    try:
        violations, lines, counts = check(root)
        fold_in_lines, fold_in_exit = _run_fold_ins(root)
    except GateError as error:
        return print_verdict("cf-exemptions", [], error)
    notices = [*lines, *fold_in_lines]
    if violations or fold_in_exit == 0:
        return print_verdict(
            "cf-exemptions",
            violations,
            notices=notices,
            measured=(
                f"— measured {counts['suppressions']} suppression(s) over "
                f"{counts['scan_paths']} scan path(s) against {counts['entries']} entry(ies)"
            ),
            evidence=counts,
            clean_summary="cf-exemptions: OK",
            fail_summary=f"cf-exemptions: FAIL ({len(violations)} violation(s))",
        )
    # A fold-in wrapper failed with no gate violation of our own: the wrapper
    # owns the verdict, and its exit code is outside the gate's 0/1/2 contract,
    # so it is propagated verbatim rather than folded into a GateVerdict.
    for line in notices:
        print(line)
    print(f"cf-exemptions: FAIL (fold-in exit {fold_in_exit})")
    return fold_in_exit
