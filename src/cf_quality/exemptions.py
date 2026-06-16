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
    their exit codes; absent scripts are skipped silently.

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
import ast
import json
import re
import subprocess  # fold-in scripts run via sys.executable, fixed argv, no shell (S603 gated below)
import sys
import tokenize
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cf_quality import repo_config
from cf_quality.errors import GateError, GateViolation
from cf_quality.reporting import print_verdict

GATED_NOQA_RULES = frozenset({"C901", "PLR0915"})
#: Whole rule families that are registry-gated code-by-code: the ruff-ported
#: bandit battery (S###) and the Elegance Law's blind-except ban (BLE###).
_GATED_FAMILY_RE = re.compile(r"^(?:S|BLE)\d+$")
#: mypy error codes whose ``# type: ignore[...]`` suppression is registry-gated:
#: ``override`` is the one token that silences the substitutability gauge
#: (mypy's [override] / Liskov error) entirely. Other codes ride the mypy
#: gauge (``warn_unused_ignores`` fails the stale ones) + review.
GATED_TYPE_IGNORE_CODES = frozenset({"override"})
FOLD_IN_SCRIPTS = ("check_english.py", "check_host_free.py")
#: Directories never measured for suppressions (tests carry their own
#: per-file-ignores discipline; the rest is non-shipping surface). The set
#: itself lives in repo_config — one gauge-block, shared with the
#: first-party derivation, never two lists drifting apart.
EXCLUDED_SCAN_DIRS = repo_config.NON_SHIPPING_DIRS
REQUIRED_ENTRY_KEYS = ("file", "symbol_or_line", "rule", "reason", "approver")

_NOSEC_RE = re.compile(r"#\s*nosec\b(.*)")
_NOQA_RE = re.compile(r"#\s*noqa\b:?\s*([A-Z]+[0-9]+(?:[\s,]+[A-Z]+[0-9]+)*)?")
_TYPE_IGNORE_RE = re.compile(r"#\s*type:\s*ignore\s*\[([^\]]+)\]")
_B_CODE_RE = re.compile(r"\bB\d{3}\b")
_CODE_SPLIT_RE = re.compile(r"[\s,]+")


@dataclass(frozen=True)
class Suppression:
    """One gated suppression comment found in the code under measurement."""

    path: str
    line: int
    rule: str
    symbol: str | None


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


def _symbol_spans(file_path: Path) -> list[tuple[int, int, str]]:
    """(start, end, QUALIFIED name) spans of every def/class.

    Names are dotted paths (``Outer.run``), never bare names — the refuter
    showed that bare names let N same-named suppressions collapse onto one
    registry entry. Empty when unparsable (line match only).
    """
    try:
        tree = ast.parse(file_path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return []
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


def _enclosing_symbol(spans: list[tuple[int, int, str]], line: int) -> str | None:
    """Innermost def/class name enclosing a line, or None at module level."""
    best: tuple[int, str] | None = None
    for start, end, name in spans:
        if start <= line <= end and (best is None or end - start < best[0]):
            best = (end - start, name)
    return best[1] if best else None


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
            Suppression(rel_path, line, code, symbol) for code in codes if _is_gated_code(code)
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


def _is_gated_code(code: str) -> bool:
    """Form budgets plus the whole S and BLE families are registry-gated."""
    return code in GATED_NOQA_RULES or _GATED_FAMILY_RE.match(code) is not None


def _discover_scan_paths(root: Path) -> list[Path]:
    """The declared ``source_root`` when committed; else ``src/`` when
    present; otherwise every top-level Python location.

    A declared layout is honored exactly like the gauges honor it (typed
    failure on an invalid declaration, never a silent fallback). A flat or
    app layout is measured, never a silent no-op: top-level ``*.py`` files
    and every non-excluded directory holding Python count.
    """
    if repo_config.load(root).source_root is not None:
        return [repo_config.resolve_source_root(root)]
    src = root / "src"
    if src.is_dir():
        return [src]
    paths: list[Path] = []
    for child in sorted(root.iterdir()):
        if child.name.startswith(".") or child.name in EXCLUDED_SCAN_DIRS:
            continue
        if child.is_file() and child.suffix == ".py":
            paths.append(child)
        elif child.is_dir() and any(child.rglob("*.py")):
            paths.append(child)
    return paths


def _scan_src(root: Path) -> tuple[list[Suppression], list[GateViolation]]:
    """Scan the discovered Python surface for suppression comments."""
    suppressions: list[Suppression] = []
    violations: list[GateViolation] = []
    for base in _discover_scan_paths(root):
        files = [base] if base.is_file() else sorted(base.rglob("*.py"))
        for file_path in files:
            rel_path = file_path.relative_to(root).as_posix()
            spans = _symbol_spans(file_path)
            for line, text in _comment_tokens(file_path):
                found, broken = _classify_comment(
                    rel_path, line, text, _enclosing_symbol(spans, line)
                )
                suppressions.extend(found)
                violations.extend(broken)
    return suppressions, violations


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


def _matches(suppression: Suppression, entry: dict[str, Any]) -> bool:
    """An entry covers a suppression by file + rule + (line OR enclosing symbol)."""
    if entry["file"] != suppression.path or entry["rule"] != suppression.rule:
        return False
    symbol_or_line = str(entry["symbol_or_line"]).strip()
    return symbol_or_line == str(suppression.line) or symbol_or_line == suppression.symbol


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


def check(root: Path) -> tuple[list[GateViolation], list[str]]:
    """Run checks (a)-(c) against a repo root; returns (violations, report lines)."""
    suppressions, violations = _scan_src(root)
    config = _load_config(root)
    if config is None:
        if suppressions:
            raise GateError(
                code="GATE_CONFIG_MISSING",
                message="gated suppressions found in src/ but exemptions.json is missing",
                context={"suppressions": len(suppressions)},
            )
        return violations, ["no exemptions.json and no gated suppressions — nothing to register"]
    entries, frozen_count = config
    match_violations, registered_lines = _match_suppressions(suppressions, entries)
    violations.extend(match_violations)
    ratchet_violations, lines = _ratchet_report(len(entries), frozen_count)
    violations.extend(ratchet_violations)
    return violations, [*lines, *registered_lines]


def _match_suppressions(
    suppressions: list[Suppression], entries: list[dict[str, Any]]
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
        hits = [i for i, entry in enumerate(entries) if _matches(suppression, entry)]
        if not hits:
            violations.append(
                GateViolation(
                    code="UNREGISTERED_SUPPRESSION",
                    message=(
                        f"'{suppression.rule}' suppression has no matching entry in "
                        "exemptions.json — a self-issued suppression is not an exemption"
                    ),
                    path=suppression.path,
                    line=suppression.line,
                    context={"rule": suppression.rule, "symbol": suppression.symbol},
                )
            )
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
        violations, lines = check(root)
        fold_in_lines, fold_in_exit = _run_fold_ins(root)
    except GateError as error:
        return print_verdict("cf-exemptions", [], error)
    notices = [*lines, *fold_in_lines]
    if violations or fold_in_exit == 0:
        return print_verdict(
            "cf-exemptions",
            violations,
            notices=notices,
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
