"""Tests for cf_quality.mypy_normalize — the env-independence filter.

The thesis this file pins: the normalized mypy stream is a function of the CODE
under measurement, never of which third-party packages happen to be installed.
The control rods:

- the SAME missing third-party import canonicalizes to ONE line whether it
  reads as ``import-untyped`` (installed-without-stubs), the ``Skipping
  analyzing`` form, or ``import-not-found`` (absent);
- the once-per-run global stub-install notes (``mypy --install-types``,
  ``#missing-imports``, and the per-package ``Hint: … pip install …-stubs``) are
  stripped, so they cannot enter the baseline or relocate between files;
- GUARDS: a real type error and a real first-party import error of any other
  shape pass through byte-identical — the filter never masks a real finding.
"""

from __future__ import annotations

import io

import pytest

from cf_quality.mypy_normalize import (
    main,
    normalize_mypy_output,
    normalize_mypy_stdout,
)

# The three env-dependent renderings of the SAME missing third-party import.
_IMPORT_UNTYPED = (
    'src/app.py:3: error: Library stubs not installed for "requests"  [import-untyped]'
)
_SKIPPING = (
    'src/app.py:3: error: Skipping analyzing "requests": module is installed, '
    "but missing library stubs or py.typed marker  [import-untyped]"
)
_IMPORT_NOT_FOUND = (
    "src/app.py:3: error: Cannot find implementation or library stub "
    'for module named "requests"  [import-not-found]'
)

# The single deterministic form all three above collapse onto.
_CANONICAL = 'src/app.py:3: error: Library stubs not installed for "requests"  [import-untyped]'

# The once-per-run stub-install notes anchored to the first missing-import site.
_HINT_NOTE = 'src/app.py:3: note: Hint: "python3 -m pip install types-requests"'
_INSTALL_NOTE = (
    'src/app.py:3: note: (or run "mypy --install-types" to install all missing stub packages)'
)
_SEE_NOTE = (
    "src/app.py:3: note: See "
    "https://mypy.readthedocs.io/en/stable/running_mypy.html#missing-imports"
)


# --- (a) canonicalization: every variant collapses onto one line -------------


def test_import_untyped_and_not_found_canonicalize_identically() -> None:
    untyped = normalize_mypy_output([_IMPORT_UNTYPED])
    not_found = normalize_mypy_output([_IMPORT_NOT_FOUND])
    assert untyped == not_found == [_CANONICAL]


def test_skipping_analyzing_variant_canonicalizes_to_the_same_line() -> None:
    assert normalize_mypy_output([_SKIPPING]) == [_CANONICAL]


def test_all_three_variants_yield_the_identical_canonical_line() -> None:
    for variant in (_IMPORT_UNTYPED, _SKIPPING, _IMPORT_NOT_FOUND):
        assert normalize_mypy_output([variant]) == [_CANONICAL]


def test_canonical_form_is_keyed_by_module_and_preserves_location() -> None:
    other = (
        "pkg/svc.py:42: error: Cannot find implementation or library stub "
        'for module named "yaml"  [import-not-found]'
    )
    assert normalize_mypy_output([other]) == [
        'pkg/svc.py:42: error: Library stubs not installed for "yaml"  [import-untyped]'
    ]


# --- (b) the once-per-run global / per-package notes are stripped -------------


def test_install_types_global_note_is_stripped() -> None:
    assert normalize_mypy_output([_INSTALL_NOTE]) == []


def test_missing_imports_see_note_is_stripped() -> None:
    assert normalize_mypy_output([_SEE_NOTE]) == []


def test_per_package_stub_hint_note_is_stripped() -> None:
    assert normalize_mypy_output([_HINT_NOTE]) == []


def test_a_full_installed_without_stubs_block_reduces_to_one_canonical_line() -> None:
    block = [_IMPORT_UNTYPED, _HINT_NOTE, _INSTALL_NOTE, _SEE_NOTE]
    assert normalize_mypy_output(block) == [_CANONICAL]


# --- (c) GUARDS: real findings survive byte-identical -------------------------


def test_real_type_error_survives_byte_identical() -> None:
    error = (
        "src/app.py:7: error: Incompatible return value type "
        '(got "str", expected "int")  [return-value]'
    )
    assert normalize_mypy_output([error]) == [error]


def test_real_first_party_import_error_is_not_masked() -> None:
    # `from myapp.config import settings` where the name is absent: a genuine
    # first-party import error of a DIFFERENT shape — it must pass through, not
    # be rewritten as a missing-stub diagnostic.
    error = 'src/app.py:2: error: Module "myapp.config" has no attribute "settings"  [attr-defined]'
    assert normalize_mypy_output([error]) == [error]


def test_unrelated_note_and_summary_lines_pass_through() -> None:
    lines = [
        'src/app.py:9: note: Revealed type is "builtins.int"',
        "Found 1 error in 1 file (checked 3 source files)",
    ]
    assert normalize_mypy_output(lines) == lines


def test_success_line_passes_through() -> None:
    line = "Success: no issues found in 3 source files"
    assert normalize_mypy_output([line]) == [line]


# --- the captured-subprocess wrapper cf-gate feeds to mypy-baseline ----------


def test_normalize_mypy_stdout_canonicalizes_and_newline_terminates() -> None:
    summary = "Found 1 error in 1 file (checked 3 source files)"
    raw = "\n".join([_IMPORT_NOT_FOUND, _INSTALL_NOTE, summary]) + "\n"
    assert normalize_mypy_stdout(raw) == f"{_CANONICAL}\n{summary}\n"


# --- the main() stdin->stdout filter -----------------------------------------


def test_main_filters_stdin_to_stdout(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    summary = "Found 1 error in 1 file (checked 3 source files)"
    stdin = "\n".join([_IMPORT_NOT_FOUND, _INSTALL_NOTE, summary])
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    exit_code = main()
    out = capsys.readouterr().out
    assert exit_code == 0
    assert out == f"{_CANONICAL}\n{summary}\n"
