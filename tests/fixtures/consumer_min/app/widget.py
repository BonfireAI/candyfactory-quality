"""The consumer fixture's only source — a tiny, clean, fully typed module.

Kept deliberately trivial so cf-gate's ruff / mypy / complexipy stages all reach
a clean verdict: the e2e value is in proving the SHIPPED gauge grades a real
repo, not in this module's behaviour.
"""

from __future__ import annotations


def greet(name: str) -> str:
    """Return a greeting for ``name``."""
    return f"hello, {name}"


ANSWER: int = 42
