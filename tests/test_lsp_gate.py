"""TDD contract for the lsp gate — substitutability and the override-suppression registry.

The gate has two surfaces, only one of which is new:

1. **Substitutability itself stays the live pinned mypy gauge** (credit-existing,
   nothing rebuilt): an override with an incompatible parameter type is an
   ``[override]`` error under ``configs/mypy-base.toml`` — mypy's own note names
   the Liskov substitution principle — and it surfaces as a NEW error through
   ``mypy | mypy-baseline filter`` (nonzero exit, the error printed), per
   ``configs/BASELINE-CONVENTIONS.md``. Consumer repos are graded with the
   kit's pinned config because most ship none of their own.
2. **The build delta is the override-suppression registry**: ``cf-exemptions``
   scans the measured tree for ``# type: ignore[override]`` tokens — the one
   comment that silences the gauge entirely (anchored below) — and every
   occurrence must match a five-field ``exemptions.json`` entry
   ({file, symbol_or_line, rule "override", reason, approver}) or the gate
   fails ``UNREGISTERED_SUPPRESSION`` naming the site. Same mechanism and
   entry shape as the BLE001 family; the count rides the ``frozen_count``
   ratchet, shrink-only. Measured estate-wide 2026-06-11: 4 live sites,
   registered at mount time in their own repos' registries.

Signal-honesty note (for the design record): the estate is composition-dominant
(max inheritance depth 3-4 by convention), so the substitutability signal is
honest but WEAK by construction — the gate's value is keeping it that way.
"""

import subprocess
import sys
from pathlib import Path

import pytest
from test_exemptions import entry, run_gate, write_exemptions, write_src

KIT_ROOT = Path(__file__).resolve().parents[1]
MYPY_GAUGE = KIT_ROOT / "configs" / "mypy-base.toml"

OVERRIDE_REASON = "measured incompatible override; interface redesign rejected at design review"

#: A subclass narrowing a parameter type — the textbook substitutability break.
INCOMPATIBLE_OVERRIDE = (
    "class Dispenser:\n"
    "    def feed(self, grams: int) -> int:\n"
    "        return grams\n"
    "\n"
    "\n"
    "class CandyDispenser(Dispenser):\n"
    "    def feed(self, grams: str) -> int:\n"
    "        return len(grams)\n"
)

#: The same break with the one comment that silences the gauge. Token line: 7.
SILENCED_OVERRIDE = INCOMPATIBLE_OVERRIDE.replace(
    "def feed(self, grams: str) -> int:\n",
    "def feed(self, grams: str) -> int:  # type: ignore[override]\n",
)
SILENCED_TOKEN_LINE = 7


def run_gauge(fixture: Path) -> subprocess.CompletedProcess[str]:
    """The documented type gate: ``mypy src | mypy-baseline filter``.

    Fixed argv from sys.executable / venv-internal paths only — no shell, no
    untrusted input (tests-context battery carve-out covers the S checks).
    """
    mypy_proc = subprocess.run(
        [sys.executable, "-m", "mypy", "src", "--config-file", str(MYPY_GAUGE)],
        cwd=fixture,
        capture_output=True,
        text=True,
        check=False,
    )
    filter_bin = Path(sys.executable).parent / "mypy-baseline"
    return subprocess.run(
        [str(filter_bin), "filter"],
        cwd=fixture,
        input=mypy_proc.stdout,
        capture_output=True,
        text=True,
        check=False,
    )


def boot_empty_baseline(fixture: Path) -> None:
    """Day-one boot of a zero-error repo: an empty committed baseline."""
    (fixture / "mypy-baseline.txt").write_text("", encoding="utf-8")


class TestSubstitutabilityStaysTheMypyGauge:
    """Credit-existing: the pinned gauge already enforces substitutability —
    these anchors pin the live behavior the registry leans on, nothing rebuilt."""

    def test_incompatible_override_is_a_new_error_through_the_baseline_filter(
        self, tmp_path: Path
    ) -> None:
        write_src(tmp_path, "feeder.py", INCOMPATIBLE_OVERRIDE)
        boot_empty_baseline(tmp_path)
        proc = run_gauge(tmp_path)
        # Gate on nonzero, never a specific value (observed filter semantics).
        assert proc.returncode != 0, proc.stdout
        assert "[override]" in proc.stdout
        assert "feeder.py" in proc.stdout
        # The oracle's own words tie this gate to its principle (observed note).
        assert "Liskov substitution principle" in proc.stdout

    def test_the_ignore_token_silences_the_gauge_entirely(self, tmp_path: Path) -> None:
        # The hole the registry closes: one comment and the same break passes
        # the gauge clean — without the registry no oracle sees it again.
        write_src(tmp_path, "feeder.py", SILENCED_OVERRIDE)
        boot_empty_baseline(tmp_path)
        proc = run_gauge(tmp_path)
        assert proc.returncode == 0, proc.stdout
        assert "[override]" not in proc.stdout


class TestOverrideSuppressionRegistry:
    """The build delta: every ``# type: ignore[override]`` token traces to a
    reasoned, approved registry entry — or the gate fails naming the site."""

    def test_unregistered_override_ignore_fails_naming_the_site(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        write_src(tmp_path, "mod.py", SILENCED_OVERRIDE)
        write_exemptions(tmp_path, [], frozen_count=0)
        code, out, _ = run_gate(tmp_path, capsys)
        assert code == 1
        assert "UNREGISTERED_SUPPRESSION" in out
        assert f"src/mod.py:{SILENCED_TOKEN_LINE}" in out
        assert "override" in out

    def test_override_ignore_without_registry_file_is_gate_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Same mechanism as the noqa families: a gated suppression with no
        # exemptions.json at all is a typed gate error, never a silent pass.
        write_src(tmp_path, "mod.py", SILENCED_OVERRIDE)
        code, _, err = run_gate(tmp_path, capsys)
        assert code == 2
        assert "GATE_CONFIG_MISSING" in err

    def test_registered_override_by_qualified_symbol_passes_with_entry_and_count(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        write_src(tmp_path, "mod.py", SILENCED_OVERRIDE)
        write_exemptions(
            tmp_path,
            [entry("src/mod.py", "CandyDispenser.feed", "override", reason=OVERRIDE_REASON)],
            frozen_count=1,
        )
        code, out, _ = run_gate(tmp_path, capsys)
        assert code == 0, out
        # The pass is loud: the registered site, its entry, and the frozen
        # count are all printed — a covered suppression is visible, not silent.
        assert "EXEMPTION RATCHET" in out
        assert "1 entries / frozen_count 1" in out
        assert "CandyDispenser.feed" in out
        assert "src/mod.py" in out

    def test_registered_override_by_line_passes_and_reports_the_site(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        write_src(tmp_path, "mod.py", SILENCED_OVERRIDE)
        write_exemptions(
            tmp_path,
            [entry("src/mod.py", SILENCED_TOKEN_LINE, "override", reason=OVERRIDE_REASON)],
            frozen_count=1,
        )
        code, out, _ = run_gate(tmp_path, capsys)
        assert code == 0, out
        assert "src/mod.py" in out
        assert "override" in out

    def test_entry_with_wrong_rule_does_not_cover_an_override(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        write_src(tmp_path, "mod.py", SILENCED_OVERRIDE)
        write_exemptions(
            tmp_path, [entry("src/mod.py", "CandyDispenser.feed", "BLE001")], frozen_count=1
        )
        code, out, _ = run_gate(tmp_path, capsys)
        assert code == 1
        assert "UNREGISTERED_SUPPRESSION" in out

    def test_multi_code_ignore_containing_override_is_gated(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # A multi-code ignore still silences the override error — hiding the
        # token in a code list is the obvious bypass, so it is gated too.
        body = SILENCED_OVERRIDE.replace(
            "# type: ignore[override]", "# type: ignore[override, misc]"
        )
        write_src(tmp_path, "mod.py", body)
        write_exemptions(tmp_path, [], frozen_count=0)
        code, out, _ = run_gate(tmp_path, capsys)
        assert code == 1
        assert "UNREGISTERED_SUPPRESSION" in out
        assert "override" in out

    def test_non_override_ignore_codes_need_no_registration(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Scope guard: the registry gates exactly the measured override family;
        # other mypy codes ride the gauge (warn_unused_ignores) + review.
        write_src(tmp_path, "mod.py", "data = load()  # type: ignore[name-defined]\n")
        code, out, _ = run_gate(tmp_path, capsys)
        assert code == 0
        assert "UNREGISTERED_SUPPRESSION" not in out

    def test_bare_type_ignore_is_not_an_override_suppression(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Scope guard: blanket type-ignores are the mypy gauge's jurisdiction
        # (warn_unused_ignores fails the stale ones); the registry gates the
        # override family only — exactly what was measured and frozen.
        write_src(tmp_path, "mod.py", "x = 1  # type: ignore\n")
        code, out, _ = run_gate(tmp_path, capsys)
        assert code == 0
        assert "UNREGISTERED_SUPPRESSION" not in out

    def test_token_inside_string_literal_is_ignored(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        write_src(tmp_path, "mod.py", 's = "# type: ignore[override]"\n')
        code, out, _ = run_gate(tmp_path, capsys)
        assert code == 0
        assert "UNREGISTERED_SUPPRESSION" not in out


class TestOverrideRatchet:
    """The override family rides the SAME shrink-only ratchet as every other
    gated family: additions bump frozen_count loudly, entries cover 1:1."""

    def test_override_entries_ride_the_frozen_count_ratchet(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        entries = [
            entry("src/a.py", "A.feed", "override", reason=OVERRIDE_REASON),
            entry("src/b.py", "B.feed", "override", reason=OVERRIDE_REASON),
        ]
        write_exemptions(tmp_path, entries, frozen_count=1)
        code, out, _ = run_gate(tmp_path, capsys)
        assert code == 1
        assert "EXEMPTION_COUNT_EXCEEDED" in out

    def test_one_entry_cannot_cover_two_override_sites(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # 1:1 or the ratchet lies: two tokens under one symbol sharing one
        # entry would keep frozen_count flat while live suppressions grow.
        body = SILENCED_OVERRIDE.replace(
            "        return len(grams)\n",
            "        size = len(grams)  # type: ignore[override]\n        return size\n",
        )
        write_src(tmp_path, "mod.py", body)
        write_exemptions(
            tmp_path,
            [entry("src/mod.py", "CandyDispenser.feed", "override", reason=OVERRIDE_REASON)],
            frozen_count=1,
        )
        code, out, _ = run_gate(tmp_path, capsys)
        assert code == 1
        assert "EXEMPTION_ENTRY_OVERLOADED" in out


class TestKitSelfCompliance:
    """The kit submits before it preaches: its own measured tree carries no
    override suppressions, so its registry owes the family zero entries."""

    def test_kit_src_carries_no_override_suppressions(self) -> None:
        offenders = [
            path
            for path in sorted((KIT_ROOT / "src").rglob("*.py"))
            if "# type: ignore[override]" in path.read_text(encoding="utf-8")
        ]
        assert offenders == [], f"unexpected override suppressions in the kit: {offenders}"
