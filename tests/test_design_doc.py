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


def test_no_internal_ticket_references() -> None:
    """The kit graduates toward public surfaces: no internal Linear ids."""
    assert not re.search(r"\bBON-\d+", _design_text()), (
        "DESIGN.md must not carry internal ticket references"
    )
