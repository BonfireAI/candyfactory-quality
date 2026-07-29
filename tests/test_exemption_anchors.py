"""Control rods for the anchor half of cf-exemptions — the rot the gate used to tolerate.

Split from ``test_exemptions.py`` by design (the file budget measures, review
judges): this file carries one coherent unit — an exemption entry that covers
NOTHING and the honesty of what the gate says about it.

The defect, measured with the kit's own resolver before the fix:
``_match_suppressions`` built ``matched_counts`` and failed only on
``count > 1``. A ``count == 0`` entry was silently tolerated, and
``frozen_count`` ratchets ENTRIES rather than live coverage, so the ratchet
stayed satisfied. Rename an enclosing ``def`` that holds a registered
suppression and two things happened at once: the site was reported
``UNREGISTERED_SUPPRESSION`` — "a self-issued suppression is not an
exemption", a convincing message that is WRONG after a rename — while the
orphaned entry was reported not at all. Rename an unrelated ``def`` INTO the
orphaned name and its suppression was silently blessed by an entry whose
``reason`` and ``approver`` describe entirely different code.

The rods assert MESSAGE TEXT, not only exit codes: the honesty of the message
is the contract here, and a red for the wrong reason is the thing being fixed.
The reused fixture helpers come from ``test_exemptions`` — one mechanism for
this gate's tests, never a parallel one.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from test_exemptions import entry, run_gate, write_exemptions, write_src

from cf_quality.exemption_anchors import covers
from cf_quality.exemptions import _matches, _scan_src

#: The accusation that must NOT reach a developer whose registry merely rotted.
SELF_ISSUED = "a self-issued suppression is not an exemption"

_AUDIT_RE = re.compile(
    r"=== ANCHOR AUDIT: (\d+) entries graded vs (\d+) live gated suppression\(s\)"
)


def audit_counts(out: str) -> tuple[int, int]:
    """(entries graded, live suppressions) as the gate itself reported them.

    The non-vacuity instrument: a gate whose population selects itself by the
    value it guards goes vacuous in silence, so every rod that claims a clean
    verdict reads the denominators back out of the output and asserts them.
    """
    match = _AUDIT_RE.search(out)
    assert match is not None, f"the gate must publish its anchor-audit denominators:\n{out}"
    return int(match.group(1)), int(match.group(2))


# --- rod 1: the rename rod ----------------------------------------------------

RENAMED = "def new_name():  # noqa: C901\n    return 1\n"


def test_rename_rod_names_the_missing_anchor(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The world: `def old_name` carried a REGISTERED `# noqa: C901` and was
    # renamed to `new_name`. The entry's anchor is now stale.
    write_src(tmp_path, "mod.py", RENAMED)
    write_exemptions(tmp_path, [entry("src/mod.py", "old_name", "C901")], frozen_count=1)
    code, out, _ = run_gate(tmp_path, capsys)
    assert code == 1
    assert "EXEMPTION_SYMBOL_MISSING" in out
    missing = "the anchored symbol 'old_name' no longer exists in src/mod.py (renamed or removed)"
    assert missing in out
    assert "re-anchor the entry to the enclosing symbol's current qualified name" in out


def test_rename_rod_does_not_accuse_the_blessed_site(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The suppression WAS blessed; only the pointer rotted. The old accusation
    # has cost real review time and nearly provoked rewrites of load-bearing
    # error barriers, so it must not be the message this developer sees.
    write_src(tmp_path, "mod.py", RENAMED)
    write_exemptions(tmp_path, [entry("src/mod.py", "old_name", "C901")], frozen_count=1)
    code, out, _ = run_gate(tmp_path, capsys)
    assert code == 1
    assert SELF_ISSUED not in out
    assert "UNREGISTERED_SUPPRESSION" in out, "the site is still unresolved — still red"
    assert "very probably a RENAME" in out
    assert "entry 0 anchored 'old_name'" in out, "the stale anchor must be NAMED"
    assert "Re-anchor that entry to 'new_name'" in out


def test_genuine_unregistered_suppression_keeps_the_strict_accusation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The converse rod (anti-softening): every registry entry is LIVE, so
    # nothing rotted and the original strict message stands verbatim.
    # Discrimination that swallowed this case would be softening in disguise.
    write_src(tmp_path, "mod.py", "def gnarly():  # noqa: C901\n    return 1\n")
    write_src(tmp_path, "other.py", "def elsewhere():  # noqa: C901\n    return 1\n")
    write_exemptions(tmp_path, [entry("src/other.py", "elsewhere", "C901")], frozen_count=1)
    code, out, _ = run_gate(tmp_path, capsys)
    assert code == 1
    assert "UNREGISTERED_SUPPRESSION" in out
    assert SELF_ISSUED in out
    assert "very probably a RENAME" not in out
    assert "1 anchors live, 0 dead" in out, "the strict branch must be the no-rot world"


# --- rod 2: the bystander rod -------------------------------------------------

BYSTANDER_BEFORE = (
    "def old_name():  # noqa: C901\n    return 1\n\n\ndef other():  # noqa: C901\n    return 2\n"
)
#: `old_name` -> `new_name` AND `other` -> `old_name`: the orphaned entry now
#: matches a stranger, and its reason/approver bless code nobody approved.
BYSTANDER_AFTER = (
    "def new_name():  # noqa: C901\n    return 1\n\n\ndef old_name():  # noqa: C901\n    return 2\n"
)
BYSTANDER_ENTRIES = [entry("src/mod.py", "old_name", "C901"), entry("src/mod.py", "other", "C901")]


def test_bystander_fixture_is_green_before_the_renames(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The rod's own non-vacuity: the world it breaks was genuinely clean, and
    # the gate graded a non-empty population to say so.
    write_src(tmp_path, "mod.py", BYSTANDER_BEFORE)
    write_exemptions(tmp_path, BYSTANDER_ENTRIES, frozen_count=2)
    code, out, _ = run_gate(tmp_path, capsys)
    assert code == 0
    assert audit_counts(out) == (2, 2)


def test_bystander_rename_is_not_silently_blessed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_src(tmp_path, "mod.py", BYSTANDER_AFTER)
    write_exemptions(tmp_path, BYSTANDER_ENTRIES, frozen_count=2)
    code, out, _ = run_gate(tmp_path, capsys)
    assert code == 1
    # The specific wrong world-state: entry 0's approval has landed on the
    # site at line 5, which is not the code its reason was written for.
    assert "EXEMPTION_ANCHOR_CONTESTED" in out
    assert "entry 0 (anchored 'old_name') claims src/mod.py:5" in out
    assert "unregistered: src/mod.py:1" in out
    assert "anchor every suppression in this group to its own qualified symbol" in out
    # And the entry whose symbol really did vanish is reported by name.
    assert "EXEMPTION_SYMBOL_MISSING" in out
    assert "the anchored symbol 'other' no longer exists in src/mod.py" in out
    assert SELF_ISSUED not in out


# --- rods 3-5: the remaining dead-anchor world-states -------------------------


def test_entry_whose_file_is_gone_is_red_with_the_file_missing_message(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_src(tmp_path, "mod.py", "def keeper():  # noqa: C901\n    return 1\n")
    entries = [entry("src/mod.py", "keeper", "C901"), entry("src/gone.py", "vanished", "C901")]
    write_exemptions(tmp_path, entries, frozen_count=2)
    code, out, _ = run_gate(tmp_path, capsys)
    assert code == 1
    assert "EXEMPTION_FILE_MISSING" in out
    assert "the anchored file src/gone.py no longer exists" in out
    assert "drop the entry (and lower frozen_count) or re-point it" in out


def test_symbol_alive_but_suppression_removed_is_red(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The remedy differs from a rename: nothing to re-anchor to, so the entry
    # goes and frozen_count comes down. The message must say THAT.
    write_src(tmp_path, "mod.py", "def keeper():\n    return 1\n")
    write_exemptions(tmp_path, [entry("src/mod.py", "keeper", "C901")], frozen_count=1)
    code, out, _ = run_gate(tmp_path, capsys)
    assert code == 1
    assert "EXEMPTION_SUPPRESSION_GONE" in out
    alive = "the anchored symbol 'keeper' exists in src/mod.py but carries no 'C901' suppression"
    assert alive in out
    assert "the suppression was removed; drop this entry and lower frozen_count" in out


LINE_DRIFT = "def keeper():  # noqa: C901\n    x = 1\n    y = 2\n    return x + y\n"


def test_line_anchor_pointing_at_a_clean_line_is_red(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    entries = [entry("src/mod.py", "keeper", "C901"), entry("src/mod.py", 3, "PLR0915")]
    write_src(tmp_path, "mod.py", LINE_DRIFT)
    write_exemptions(tmp_path, entries, frozen_count=2)
    code, out, _ = run_gate(tmp_path, capsys)
    assert code == 1
    assert "EXEMPTION_SUPPRESSION_GONE" in out
    assert "line 3 of src/mod.py carries no 'PLR0915' suppression" in out
    assert "a line anchor rots on any insertion above it" in out


def test_line_anchor_past_the_end_of_the_file_is_red(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_src(tmp_path, "mod.py", LINE_DRIFT)
    write_exemptions(tmp_path, [entry("src/mod.py", 99, "C901")], frozen_count=1)
    code, out, _ = run_gate(tmp_path, capsys)
    assert code == 1
    assert "line 99 does not exist in src/mod.py (the file has 4 lines)" in out
    # The live C901 at line 1 reads as rot, not as a self-issued suppression.
    assert SELF_ISSUED not in out
    assert "entry 0 anchored '99'" in out


# --- rods 6-8: green, loud, and non-vacuous -----------------------------------

LIVE_1TO1 = (
    "class A:\n"
    "    def run(self):  # noqa: C901\n"
    "        return 1\n"
    "\n"
    "\n"
    "def solo():  # noqa: PLR0915\n"
    "    return 2\n"
)


def test_all_anchors_live_one_to_one_is_clean_and_still_prints_loudly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    entries = [entry("src/mod.py", "A.run", "C901"), entry("src/mod.py", "solo", "PLR0915")]
    write_src(tmp_path, "mod.py", LIVE_1TO1)
    write_exemptions(tmp_path, entries, frozen_count=2)
    code, out, _ = run_gate(tmp_path, capsys)
    assert code == 0
    assert "registered: src/mod.py:2 'C901' (A.run) — covered by entry 0" in out
    assert "registered: src/mod.py:6 'PLR0915' (solo) — covered by entry 1" in out
    assert "2 anchors live, 0 dead, 0 unmeasured" in out
    assert "LINE-ANCHORED" not in out


def test_live_line_anchors_are_clean_but_reported_loudly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # A live consumer deliberately line-pins entries whose sites no symbol
    # identifies uniquely. Reding that would fail a repo for a documented
    # decision, so the gate NOTICES and hands the policy to the operator.
    write_src(tmp_path, "mod.py", "def keeper():  # noqa: C901\n    return 1\n")
    write_exemptions(tmp_path, [entry("src/mod.py", 1, "C901")], frozen_count=1)
    code, out, _ = run_gate(tmp_path, capsys)
    assert code == 0
    assert "=== LINE-ANCHORED ENTRIES: 1 of 1 (NOTICE, not a violation) ===" in out
    assert "line-anchored: entry 0 src/mod.py:1 'C901'" in out
    assert "migration path: replace symbol_or_line with the enclosing symbol's QUALIFIED" in out
    assert "EXEMPTION_SUPPRESSION_GONE" not in out
    assert "EXEMPTION_SYMBOL_MISSING" not in out
    assert audit_counts(out) == (1, 1)


def test_the_audit_publishes_a_non_empty_denominator(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Non-vacuity: a clean verdict is only worth something if the run graded a
    # non-empty set of entries AND saw a non-empty set of suppressions.
    entries = [entry("src/mod.py", "A.run", "C901"), entry("src/mod.py", "solo", "PLR0915")]
    write_src(tmp_path, "mod.py", LIVE_1TO1)
    write_exemptions(tmp_path, entries, frozen_count=2)
    code, out, _ = run_gate(tmp_path, capsys)
    assert code == 0
    graded, suppressions = audit_counts(out)
    assert graded == 2
    assert suppressions == 2


def test_a_run_that_grades_nothing_says_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The control rod on the rod: an empty population reports ZERO out loud,
    # so a vacuous clean verdict is legible instead of comfortable.
    write_exemptions(tmp_path, [], frozen_count=0)
    code, out, _ = run_gate(tmp_path, capsys)
    assert code == 0
    assert audit_counts(out) == (0, 0)


# --- the ungradeable: notices, never accusations ------------------------------


def test_entry_for_a_rule_this_gate_never_gates_is_a_notice(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # A consumer documenting an E402 it keeps for its own reasons has not
    # rotted anything: the scanner can never emit that rule, so grading the
    # entry as dead would invent a defect out of a documentation habit.
    write_src(tmp_path, "mod.py", "x = 1\n")
    write_exemptions(tmp_path, [entry("src/mod.py", 1, "E402")], frozen_count=1)
    code, out, _ = run_gate(tmp_path, capsys)
    assert code == 0
    assert "UNMEASURED ENTRY: entry 0" in out
    assert "names 'E402', a rule this gate never gates" in out
    assert audit_counts(out) == (0, 0)


def test_entry_outside_the_measured_surface_is_a_notice(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_src(tmp_path, "mod.py", "x = 1\n")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_x.py").write_text(
        "def helper():  # noqa: C901\n    return 1\n", encoding="utf-8"
    )
    write_exemptions(tmp_path, [entry("tests/test_x.py", "helper", "C901")], frozen_count=1)
    code, out, _ = run_gate(tmp_path, capsys)
    assert code == 0
    assert "sits outside the measured source surface" in out
    assert "EXEMPTION_SYMBOL_MISSING" not in out


def test_an_overloaded_entry_is_never_also_reported_as_dead(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Anti-softening in the other direction: the anchor audit must not pile a
    # second, contradictory verdict onto the collision refuter's finding.
    body = "def big():  # noqa: PLR0915\n    x = 1  # noqa: PLR0915\n    return x\n"
    write_src(tmp_path, "mod.py", body)
    write_exemptions(tmp_path, [entry("src/mod.py", "big", "PLR0915")], frozen_count=1)
    code, out, _ = run_gate(tmp_path, capsys)
    assert code == 1
    assert "EXEMPTION_ENTRY_OVERLOADED" in out
    assert "EXEMPTION_SYMBOL_MISSING" not in out
    assert "EXEMPTION_SUPPRESSION_GONE" not in out


class TestConsumerResolverContract:
    """The published surface a consumer's drift-proof pin actually calls.

    A consumer repo mirrors this gate's resolver in its own pin test and
    cross-checks the two entry by entry, *so that the mirror cannot silently
    drift*. It reaches in by name: `suppressions, _ = exemptions._scan_src(root)`
    and `exemptions._matches(suppression, entry)`. Changing that arity or
    flipping those arguments breaks the one test whose job is detecting drift,
    and the break cannot be repaired in one PR — a consumer patched for a new
    kit API fails against the currently pinned kit, so neither side can merge
    alone. These rods make the shape a contract rather than an accident: if you
    are here because a refactor turned them red, fix the refactor.
    """

    def test_scan_src_returns_exactly_two_values(self, tmp_path: Path) -> None:
        write_src(tmp_path, "mod.py", "def gnarly():  # noqa: C901\n    return 1\n")
        result = _scan_src(tmp_path)
        assert len(result) == 2, "the consumer pin unpacks exactly two values"
        suppressions, violations = result
        assert [(s.path, s.line, s.rule, s.symbol) for s in suppressions] == [
            ("src/mod.py", 1, "C901", "gnarly")
        ]
        assert violations == []

    def test_matches_keeps_its_published_argument_order(self, tmp_path: Path) -> None:
        write_src(tmp_path, "mod.py", "def gnarly():  # noqa: C901\n    return 1\n")
        suppressions, _ = _scan_src(tmp_path)
        suppression = suppressions[0]
        assert _matches(suppression, entry("src/mod.py", "gnarly", "C901")) is True
        assert _matches(suppression, entry("src/mod.py", 1, "C901")) is True
        assert _matches(suppression, entry("src/mod.py", "other", "C901")) is False
        assert _matches(suppression, entry("src/other.py", "gnarly", "C901")) is False

    def test_matches_is_a_pure_adapter_over_the_single_rule(self, tmp_path: Path) -> None:
        # ONE implementation of the rule: two would let coverage and liveness
        # disagree, which is the gauge that does not measure what its name says.
        body = "class A:\n    def run(self):  # noqa: C901\n        return 1\n"
        write_src(tmp_path, "mod.py", body)
        suppressions, _ = _scan_src(tmp_path)
        for anchor in ("A.run", "run", 2, 1):
            candidate = entry("src/mod.py", anchor, "C901")
            assert _matches(suppressions[0], candidate) == covers(candidate, suppressions[0])


def test_the_kit_own_registry_carries_no_dead_anchors(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The kit submits to the gate it ships: its own four entries are live
    # symbol anchors, 1:1, with nothing line-pinned and nothing unmeasured.
    kit_root = Path(__file__).resolve().parents[1]
    code, out, _ = run_gate(kit_root, capsys)
    assert code == 0, out
    graded, suppressions = audit_counts(out)
    assert graded >= 4, "the self-check must grade a non-empty registry"
    assert suppressions >= 4
    assert "0 dead, 0 unmeasured" in out
    assert "LINE-ANCHORED" not in out
