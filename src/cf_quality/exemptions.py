"""cf-exemptions — the suppression-registration gate of the BubbleGum Law.

Answers the Law-2 refuter's "self-issued Wizard exemption" gaming vector by
making Wizard-gating mechanical, never prose:

(a) a bare ``# nosec`` (no rule id AND no reason) anywhere in src/ FAILS;
(b) every gated suppression — ``# noqa: C901``, ``# noqa: PLR0915``, or
    ``# nosec B...`` — must match a committed entry in ``exemptions.json``
    ({file, symbol_or_line, rule, reason, approver}); an unregistered
    suppression FAILS the gate;
(c) the exemption count is ratcheted: ``exemptions.json`` carries
    ``frozen_count``. Entries may be removed freely; additions require
    bumping ``frozen_count``, and the gate prints the ratchet loudly on
    every run — a visible decision, never a silent one;
(d) fold-in wrappers: when the target repo ships ``scripts/check_english.py``
    or ``scripts/check_host_free.py`` the gate runs them and propagates
    their exit codes; absent scripts are skipped silently.

Comments are read via :mod:`tokenize` (COMMENT tokens only), so suppression
text inside string literals never trips the gate.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess  # noqa: S404 — fold-in scripts run via sys.executable, fixed argv, no shell
import sys
import tokenize
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cf_quality.errors import GateError, GateViolation

GATED_NOQA_RULES = frozenset({"C901", "PLR0915"})
FOLD_IN_SCRIPTS = ("check_english.py", "check_host_free.py")
REQUIRED_ENTRY_KEYS = ("file", "symbol_or_line", "rule", "reason", "approver")

_NOSEC_RE = re.compile(r"#\s*nosec\b(.*)")
_NOQA_RE = re.compile(r"#\s*noqa\b:?\s*([A-Z]+[0-9]+(?:[\s,]+[A-Z]+[0-9]+)*)?")
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
    """(start, end, name) spans of every def/class; empty when unparsable (line match only)."""
    try:
        tree = ast.parse(file_path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return []
    spans: list[tuple[int, int, str]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
            and node.end_lineno is not None
        ):
            spans.append((node.lineno, node.end_lineno, node.name))
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
            Suppression(rel_path, line, code, symbol) for code in codes if code in GATED_NOQA_RULES
        )
    return suppressions, violations


def _scan_src(root: Path) -> tuple[list[Suppression], list[GateViolation]]:
    """Scan every Python file under <root>/src for suppression comments."""
    src = root / "src"
    if not src.is_dir():
        return [], []
    suppressions: list[Suppression] = []
    violations: list[GateViolation] = []
    for file_path in sorted(src.rglob("*.py")):
        rel_path = file_path.relative_to(root).as_posix()
        spans = _symbol_spans(file_path)
        for line, text in _comment_tokens(file_path):
            found, broken = _classify_comment(rel_path, line, text, _enclosing_symbol(spans, line))
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
    for suppression in suppressions:
        if not any(_matches(suppression, entry) for entry in entries):
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
    ratchet_violations, lines = _ratchet_report(len(entries), frozen_count)
    violations.extend(ratchet_violations)
    return violations, lines


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
        print(json.dumps(error.to_dict()), file=sys.stderr)
        return 2
    for line in [*lines, *fold_in_lines]:
        print(line)
    for violation in violations:
        location = f"{violation.path}:{violation.line}" if violation.line else violation.path
        print(f"{location}: {violation.code}: {violation.message}")
    if violations:
        print(f"cf-exemptions: FAIL ({len(violations)} violation(s))")
        return 1
    if fold_in_exit != 0:
        print(f"cf-exemptions: FAIL (fold-in exit {fold_in_exit})")
        return fold_in_exit
    print("cf-exemptions: OK")
    return 0
