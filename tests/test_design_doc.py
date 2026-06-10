"""DESIGN.md carries one section per refuter gaming vector — or an honest OPEN.

The launcher's hard requirement: every gaming vector from the adversarial
refuter pass gets its own section answering how the kit closes it, or an
explicit OPEN. A vector with no section is a silent skip, which is exactly
the failure mode the document exists to refuse — so the test enumerates the
vectors and the demanded glue sections by name.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
DESIGN_PATH = REPO_ROOT / "DESIGN.md"

#: One heading fragment per gaming vector from the refuter pass (law-candidates).
VECTOR_HEADINGS = (
    "Sibling-file accretion",
    "CC laundering",
    "Self-issued noqa",
    "jscpd untouched-file blind spot",
    "Fixture indirection",
    "Bare # nosec",
    "Test-target unbinding",
    "Caller-stub neutering",
    "ruff-sync exclude escape",
    "De-annotation invisibility",
    "Count-vs-set baseline laundering",
    "Declare-don't-fix mirror legalization",
    "Enrollment escape",
)

#: The demanded glue sections beyond the vectors.
GLUE_HEADINGS = (
    "Two-surface architecture",
    "SHA-pin doctrine",
    "Baseline-generation runbook",
    "Open issues",
)


def _design_text() -> str:
    if not DESIGN_PATH.is_file():
        pytest.fail("DESIGN.md does not exist at the repo root")
    return DESIGN_PATH.read_text(encoding="utf-8")


def _headings(text: str) -> list[str]:
    return [line.lstrip("#").strip() for line in text.splitlines() if line.startswith("#")]


@pytest.mark.parametrize("fragment", VECTOR_HEADINGS)
def test_every_gaming_vector_has_a_section(fragment: str) -> None:
    headings = _headings(_design_text())
    assert any(fragment.lower() in heading.lower() for heading in headings), (
        f"no DESIGN.md section heading mentions the gaming vector {fragment!r} — "
        "a vector with no answer must be an honest OPEN section, never a silent skip"
    )


@pytest.mark.parametrize("fragment", GLUE_HEADINGS)
def test_demanded_glue_sections_present(fragment: str) -> None:
    headings = _headings(_design_text())
    assert any(fragment.lower() in heading.lower() for heading in headings), (
        f"DESIGN.md is missing the demanded section {fragment!r}"
    )


def test_every_vector_section_carries_a_verdict() -> None:
    """Each vector answers CLOSED / PARTIAL / OPEN explicitly, never implicitly."""
    text = _design_text()
    verdicts = re.findall(r"^\*\*Verdict:\*\*\s*(CLOSED|PARTIAL|OPEN)\b", text, flags=re.M)
    assert len(verdicts) >= len(VECTOR_HEADINGS), (
        f"found {len(verdicts)} verdict lines for {len(VECTOR_HEADINGS)} vectors — "
        "every vector section must state **Verdict:** CLOSED | PARTIAL | OPEN"
    )


#: Internal Linear ticket pattern, concatenated so this guard's own source
#: never contains the contiguous literal and the repo-wide oracle stays empty.
_INTERNAL_TICKET = re.compile(rb"\bBON" + rb"-")

#: Tool/VCS caches that are not part of the shipped tree.
_SCAN_SKIP_DIRS = frozenset(
    {".git", "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".venv"}
)


def test_no_internal_ticket_references() -> None:
    """The kit graduates toward public surfaces: no internal Linear ids anywhere."""
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in sorted(REPO_ROOT.rglob("*"))
        if path.is_file()
        and not _SCAN_SKIP_DIRS.intersection(path.relative_to(REPO_ROOT).parts)
        and _INTERNAL_TICKET.search(path.read_bytes())
    ]
    assert not offenders, (
        f"internal ticket references found in: {offenders} — "
        "the kit must carry zero internal Linear ids in any file"
    )


def test_refuter_2026_06_10_boundaries_are_on_the_open_record() -> None:
    # The second refuter pass found v0 boundaries that are decisions, not
    # silence: each one is named in DESIGN.md's Open issues.
    text = DESIGN_PATH.read_text(encoding="utf-8")
    open_section = text[text.lower().index("## 5. open issues") :].lower()
    for needle in (
        "greenfield",  # package draw is relocation-only; greenfield dumps unbudgeted
        "module-qualified",  # sys.modules[__name__] self-recursion undetected
        "undeclared mirror",  # MIRRORS.md trusts the repo's self-enumeration
        "parent fetch",  # local-side-only mirror verification
        "salience",  # sticky-intro neutralizer detection is a heuristic
    ):
        assert needle in open_section, f"open-issue entry missing: {needle}"


def test_design_drops_the_false_required_reason_idiom_claim() -> None:
    # Refuter: DESIGN claimed the S603 suppression is "policed by ruff's
    # required-reason idiom" — no such idiom exists or is enabled.
    text = DESIGN_PATH.read_text(encoding="utf-8")
    assert "required-reason idiom" not in text


def test_readme_states_the_gated_suppression_families_precisely() -> None:
    # Refuter: README overclaimed that EVERY noqa/nosec traces to a reasoned
    # entry while only C901/PLR0915 were gated. The claim must name the gated
    # families exactly (form + security + Elegance).
    readme = (DESIGN_PATH.parent / "README.md").read_text(encoding="utf-8")
    assert "Every `# noqa` / `# nosec` traces" not in readme
    for fragment in ("C901", "PLR0915", "S", "BLE"):
        assert fragment in readme
