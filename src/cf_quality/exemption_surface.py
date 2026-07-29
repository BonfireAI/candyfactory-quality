"""Which tree cf-exemptions measures — discovery, and membership in it.

The third module of the exemptions gate, and the file law is why there are
three: ``exemptions.py`` sat at 494 of its 500 measured lines, so the anchor
half (:mod:`cf_quality.exemption_anchors`) and this surface half had to leave.
They are not arbitrary slices. Each answers a question with its own defect
history and its own test file: *does every blessing still point at live code?*
(`test_exemption_anchors.py`) and *which tree did we even read?*
(`test_exemptions_source_root.py`).

The scar behind this one is the mexxa main-green pass: the gate discovered a
repo-root ``src/`` holding JavaScript, never visited the committed
``server/src``, and every registered exemption was documentation-grade because
the scanner never opened the files the entries covered. So the surface resolves
through cf-repo-config exactly like the gauges do — typed failure on an invalid
declaration, never a silent fallback — and a flat or app layout is DISCOVERED
rather than skipped (the refuter's src-only escape).

:func:`in_surface` exists because the anchor audit must grade an entry only
against files the scanner actually read: an entry pointing outside the measured
tree is undecidable, and calling it dead would accuse code the gate never
opened. Membership is tested against the very bases the scan walks, so the two
can never drift into disagreeing about what was measured.
"""

from __future__ import annotations

from pathlib import Path

from cf_quality import repo_config

#: Directories never measured for suppressions (tests carry their own
#: per-file-ignores discipline; the rest is non-shipping surface). The set
#: itself lives in repo_config — one gauge-block, shared with the first-party
#: derivation, never two lists drifting apart.
EXCLUDED_SCAN_DIRS = repo_config.NON_SHIPPING_DIRS


def discover_scan_paths(root: Path) -> list[Path]:
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


def in_surface(path: Path, surface: tuple[Path, ...]) -> bool:
    """Is this registry-named file inside the tree the scanner actually walked?

    Tested against the DISCOVERED bases the scan iterates, never a second
    discovery rule: the scan walks every ``*.py`` under each base, so "under a
    base" and "was read" are one set for the files a registry can name. Bases
    rather than a visited-path set, so ``exemptions._scan_src`` keeps the
    two-value arity a consumer's drift-proof pin unpacks.
    """
    resolved = path.resolve()
    for base in surface:
        anchor = base.resolve()
        if resolved == anchor or resolved.is_relative_to(anchor):
            return True
    return False
