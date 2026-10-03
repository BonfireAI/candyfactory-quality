"""Tests for cf-mirror-check — declared mirrors stay byte-true and pins expire."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

import pytest

from cf_quality.errors import GateError
from cf_quality.mirror_check import (
    check_mirrors,
    init_mirrors,
    main,
    parse_mirrors,
    render_template,
)
from cf_quality.reporting import JSON_ENV_VAR

TODAY = dt.date(2026, 6, 10)

HEADER = (
    "| artifact | local path | parent repo | parent path "
    "| pinned parent SHA | content sha256 | pinned date |\n"
    "|---|---|---|---|---|---|---|\n"
)


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_mirrors(repo: Path, rows: str, header: str = HEADER) -> Path:
    path = repo / "MIRRORS.md"
    path.write_text("# Declared mirrors\n\n" + header + rows, encoding="utf-8")
    return path


def make_mirror(repo: Path, rel: str, content: bytes) -> str:
    """Create a mirrored file and return its true sha256."""
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return sha256_of(content)


def row(
    rel: str,
    digest: str,
    *,
    artifact: str = "sticky-intro",
    parent_repo: str = "candyfactory-canon",
    parent_path: str = "decisions/0029-bubblegum-law.md",
    sha: str = "a" * 40,
    pinned: str = "2026-06-01",
) -> str:
    return f"| {artifact} | {rel} | {parent_repo} | {parent_path} | {sha} | {digest} | {pinned} |\n"


def real_clock_pin(days_ago: int = 1) -> str:
    """An ISO pin relative to the REAL date, for tests that drive main().

    main() judges staleness against the real clock, so a fixed fixture date
    silently expires once the calendar passes it by the max pin age. Pins for
    the CLI path are therefore always written relative to today.
    """
    return (dt.date.today() - dt.timedelta(days=days_ago)).isoformat()


def main_at_pin_age(
    repo: Path, digest: str, age_days: int, capsys: pytest.CaptureFixture[str]
) -> tuple[int, str]:
    """Run main() on a row pinned ``age_days`` before the real today.

    Re-runs once if the date rolled over mid-call, so the measured age is exact
    rather than off by one at midnight. The real clock is never mocked. Each
    attempt drains capsys first and the returned stdout is that attempt's
    alone, so a discarded rolled-over run cannot leak into the assertions.
    """
    for _ in range(2):
        capsys.readouterr()  # discard anything a previous attempt printed
        before = dt.date.today()
        write_mirrors(repo, row("data/intro.md", digest, pinned=real_clock_pin(age_days)))
        code = main(["--repo", str(repo)])
        out = capsys.readouterr().out
        if dt.date.today() == before:
            return code, out
    raise AssertionError("the date rolled over during both attempts")


class TestParse:
    def test_missing_required_column_raises_typed_gate_error(self, tmp_path: Path) -> None:
        bad_header = "| artifact | local path |\n|---|---|\n"
        write_mirrors(tmp_path, "| x | y |\n", header=bad_header)
        with pytest.raises(GateError) as exc:
            parse_mirrors((tmp_path / "MIRRORS.md").read_text(encoding="utf-8"))
        assert exc.value.code == "MIRRORS_HEADER_INVALID"
        assert "parent repo" in str(exc.value.context["missing_columns"])

    def test_pinned_date_column_is_required(self, tmp_path: Path) -> None:
        # Refuter: omitting the column disabled staleness entirely (expiry was
        # opt-out). A declaration without an expiry clock is no declaration.
        header = (
            "| artifact | local path | parent repo | parent path "
            "| pinned parent SHA | content sha256 |\n|---|---|---|---|---|---|\n"
        )
        write_mirrors(tmp_path, "| a | b.md | c | d.md | e | f |\n", header=header)
        with pytest.raises(GateError) as exc:
            parse_mirrors((tmp_path / "MIRRORS.md").read_text(encoding="utf-8"))
        assert exc.value.code == "MIRRORS_HEADER_INVALID"
        assert "pinned date" in str(exc.value.context["missing_columns"])


class TestCheck:
    def test_clean_mirror_reports_no_violations(self, tmp_path: Path) -> None:
        digest = make_mirror(tmp_path, "data/intro.md", b"the law travels sticky\n")
        write_mirrors(tmp_path, row("data/intro.md", digest))
        assert check_mirrors(tmp_path, today=TODAY)[0] == []

    def test_diverged_mirror_fails_with_both_hashes(self, tmp_path: Path) -> None:
        make_mirror(tmp_path, "data/intro.md", b"drifted content\n")
        declared = sha256_of(b"the original content\n")
        write_mirrors(tmp_path, row("data/intro.md", declared))
        violations, _ = check_mirrors(tmp_path, today=TODAY)
        assert [v.code for v in violations] == ["MIRROR_DIVERGED"]
        v = violations[0]
        assert v.path == "data/intro.md"
        assert v.context["declared_sha256"] == declared
        assert v.context["actual_sha256"] == sha256_of(b"drifted content\n")

    def test_missing_local_file_fails(self, tmp_path: Path) -> None:
        write_mirrors(tmp_path, row("data/ghost.md", sha256_of(b"x")))
        violations, _ = check_mirrors(tmp_path, today=TODAY)
        assert [v.code for v in violations] == ["MIRROR_FILE_MISSING"]
        assert violations[0].path == "data/ghost.md"

    def test_row_missing_any_field_fails(self, tmp_path: Path) -> None:
        digest = make_mirror(tmp_path, "data/intro.md", b"content\n")
        incomplete = (
            f"| sticky-intro | data/intro.md |  | d.md | {'a' * 40} | {digest} | 2026-06-01 |\n"
        )
        write_mirrors(tmp_path, incomplete)
        violations, _ = check_mirrors(tmp_path, today=TODAY)
        assert [v.code for v in violations] == ["MIRROR_ROW_INCOMPLETE"]
        assert violations[0].context["missing_fields"] == ["parent repo"]

    def test_stale_pin_fails_at_default_90_days(self, tmp_path: Path) -> None:
        digest = make_mirror(tmp_path, "data/intro.md", b"content\n")
        old = (TODAY - dt.timedelta(days=120)).isoformat()
        write_mirrors(tmp_path, row("data/intro.md", digest, pinned=old))
        violations, _ = check_mirrors(tmp_path, today=TODAY)
        assert [v.code for v in violations] == ["MIRROR_PIN_STALE"]
        assert violations[0].context["age_days"] == 120
        assert violations[0].context["max_pin_age_days"] == 90

    def test_pin_exactly_at_max_age_is_not_stale(self, tmp_path: Path) -> None:
        digest = make_mirror(tmp_path, "data/intro.md", b"content\n")
        edge = (TODAY - dt.timedelta(days=90)).isoformat()
        write_mirrors(tmp_path, row("data/intro.md", digest, pinned=edge))
        assert check_mirrors(tmp_path, today=TODAY)[0] == []

    def test_custom_max_pin_age_days_is_honored(self, tmp_path: Path) -> None:
        digest = make_mirror(tmp_path, "data/intro.md", b"content\n")
        old = (TODAY - dt.timedelta(days=10)).isoformat()
        write_mirrors(tmp_path, row("data/intro.md", digest, pinned=old))
        violations, _ = check_mirrors(tmp_path, max_pin_age_days=7, today=TODAY)
        assert [v.code for v in violations] == ["MIRROR_PIN_STALE"]

    def test_row_with_empty_pinned_date_is_incomplete(self, tmp_path: Path) -> None:
        # Refuter: a blank pin made a declaration immortal (expiry opt-out).
        digest = make_mirror(tmp_path, "data/intro.md", b"content\n")
        write_mirrors(tmp_path, row("data/intro.md", digest, pinned=""))
        violations, _ = check_mirrors(tmp_path, today=TODAY)
        assert [v.code for v in violations] == ["MIRROR_ROW_INCOMPLETE"]
        assert "pinned date" in violations[0].context["missing_fields"]

    def test_future_pinned_date_fails_as_future(self, tmp_path: Path) -> None:
        # Refuter: a 2099 pin gave negative age, so staleness could never fire.
        digest = make_mirror(tmp_path, "data/intro.md", b"content\n")
        write_mirrors(tmp_path, row("data/intro.md", digest, pinned="2099-01-01"))
        violations, _ = check_mirrors(tmp_path, today=TODAY)
        assert [v.code for v in violations] == ["MIRROR_PIN_FUTURE"]
        assert violations[0].context["pinned_date"] == "2099-01-01"

    def test_max_pin_age_zero_expires_every_dated_pin_but_today(self, tmp_path: Path) -> None:
        digest = make_mirror(tmp_path, "data/intro.md", b"content\n")
        yesterday = (TODAY - dt.timedelta(days=1)).isoformat()
        write_mirrors(tmp_path, row("data/intro.md", digest, pinned=yesterday))
        violations, _ = check_mirrors(tmp_path, max_pin_age_days=0, today=TODAY)
        assert [v.code for v in violations] == ["MIRROR_PIN_STALE"]
        write_mirrors(tmp_path, row("data/intro.md", digest, pinned=TODAY.isoformat()))
        assert check_mirrors(tmp_path, max_pin_age_days=0, today=TODAY)[0] == []

    def test_unparseable_pinned_date_fails_as_invalid(self, tmp_path: Path) -> None:
        digest = make_mirror(tmp_path, "data/intro.md", b"content\n")
        write_mirrors(tmp_path, row("data/intro.md", digest, pinned="last tuesday"))
        violations, _ = check_mirrors(tmp_path, today=TODAY)
        assert [v.code for v in violations] == ["MIRROR_PIN_INVALID"]
        assert violations[0].context["pinned_date"] == "last tuesday"

    def test_hash_comparison_is_case_insensitive(self, tmp_path: Path) -> None:
        digest = make_mirror(tmp_path, "data/intro.md", b"content\n")
        write_mirrors(tmp_path, row("data/intro.md", digest.upper()))
        assert check_mirrors(tmp_path, today=TODAY)[0] == []

    def test_missing_mirrors_md_raises_typed_gate_error(self, tmp_path: Path) -> None:
        with pytest.raises(GateError) as exc:
            check_mirrors(tmp_path, today=TODAY)
        assert exc.value.code == "MIRRORS_FILE_MISSING"
        assert exc.value.retryable is False

    def test_multiple_rows_collect_all_violations(self, tmp_path: Path) -> None:
        digest = make_mirror(tmp_path, "data/good.md", b"fine\n")
        rows = (
            row("data/good.md", digest)
            + row("data/ghost.md", sha256_of(b"y"), artifact="ghost")
            + row("data/good.md", sha256_of(b"other"), artifact="diverged")
        )
        write_mirrors(tmp_path, rows)
        codes = sorted(v.code for v in check_mirrors(tmp_path, today=TODAY)[0])
        assert codes == ["MIRROR_DIVERGED", "MIRROR_FILE_MISSING"]

    def test_row_count_tracks_the_rows_checked(self, tmp_path: Path) -> None:
        # The board's denominator. Asserted here against a KNOWN row count,
        # because the zero case (a header with no rows) would equally survive a
        # hardcoded 0 — and then every board line would claim 0 mirrors checked
        # while the gate was really enforcing three.
        digest = make_mirror(tmp_path, "data/good.md", b"fine\n")
        rows = (
            row("data/good.md", digest)
            + row("data/ghost.md", sha256_of(b"y"), artifact="ghost")
            + row("data/good.md", sha256_of(b"other"), artifact="diverged")
        )
        write_mirrors(tmp_path, rows)
        assert check_mirrors(tmp_path, today=TODAY)[1] == 3


class TestInit:
    def test_init_writes_template_that_parses_clean(self, tmp_path: Path) -> None:
        path = init_mirrors(tmp_path)
        assert path == tmp_path / "MIRRORS.md"
        text = path.read_text(encoding="utf-8")
        assert text == render_template()
        assert parse_mirrors(text) == []  # template carries no live rows
        assert check_mirrors(tmp_path, today=TODAY)[0] == []  # green by construction

    def test_init_refuses_to_overwrite_existing(self, tmp_path: Path) -> None:
        (tmp_path / "MIRRORS.md").write_text("precious\n", encoding="utf-8")
        with pytest.raises(GateError) as exc:
            init_mirrors(tmp_path)
        assert exc.value.code == "MIRRORS_ALREADY_EXISTS"
        assert (tmp_path / "MIRRORS.md").read_text(encoding="utf-8") == "precious\n"


class TestMain:
    def test_main_clean_exits_zero(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        digest = make_mirror(tmp_path, "data/intro.md", b"content\n")
        write_mirrors(tmp_path, row("data/intro.md", digest, pinned=real_clock_pin()))
        assert main(["--repo", str(tmp_path)]) == 0
        # The denominator: a gate that read zero rows would also exit 0.
        assert "checked 1 declared mirror row(s)" in capsys.readouterr().out

    def test_main_divergence_exits_one_and_prints_finding(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        make_mirror(tmp_path, "data/intro.md", b"drifted\n")
        pinned = real_clock_pin()
        write_mirrors(tmp_path, row("data/intro.md", sha256_of(b"original\n"), pinned=pinned))
        assert main(["--repo", str(tmp_path)]) == 1
        out = capsys.readouterr().out
        assert "checked 1 declared mirror row(s)" in out
        finding_lines = [line for line in out.splitlines() if ": MIRROR_" in line]
        assert len(finding_lines) == 1  # exactly one finding: divergence, no pin noise
        assert "MIRROR_DIVERGED" in finding_lines[0]
        assert "data/intro.md" in finding_lines[0]
        assert "MIRROR_PIN_" not in out

    def test_main_gate_error_exits_two_on_stderr(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["--repo", str(tmp_path)]) == 2
        assert "MIRRORS_FILE_MISSING" in capsys.readouterr().err

    def test_main_init_creates_template(self, tmp_path: Path) -> None:
        assert main(["init", "--repo", str(tmp_path)]) == 0
        assert (tmp_path / "MIRRORS.md").exists()

    def test_main_init_existing_exits_two(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tmp_path / "MIRRORS.md").write_text("precious\n", encoding="utf-8")
        assert main(["init", "--repo", str(tmp_path)]) == 2
        assert "MIRRORS_ALREADY_EXISTS" in capsys.readouterr().err

    def test_main_max_pin_age_days_flag(self, tmp_path: Path) -> None:
        digest = make_mirror(tmp_path, "data/intro.md", b"content\n")
        write_mirrors(tmp_path, row("data/intro.md", digest, pinned=real_clock_pin(30)))
        assert main(["--repo", str(tmp_path), "--max-pin-age-days", "7"]) == 1
        assert main(["--repo", str(tmp_path), "--max-pin-age-days", "60"]) == 0


class TestMainRealClockControl:
    """Control for the real-clock path: main() takes no ``today``, so staleness is
    judged against the actual date. Healing the fixture dates must not have
    disarmed it. ``_check_pin`` refuses only ``age_days > max``, so 90 is allowed.
    """

    def test_main_pin_91_days_old_on_real_clock_exits_one_stale(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        digest = make_mirror(tmp_path, "data/intro.md", b"content\n")
        code, out = main_at_pin_age(tmp_path, digest, 91, capsys)
        assert code == 1
        assert "MIRROR_PIN_STALE" in out
        assert "91 days old (max 90)" in out

    def test_main_pin_exactly_90_days_old_on_real_clock_is_allowed_exits_zero(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        digest = make_mirror(tmp_path, "data/intro.md", b"content\n")
        code, out = main_at_pin_age(tmp_path, digest, 90, capsys)
        assert code == 0
        assert "checked 1 declared mirror row(s)" in out
        assert "MIRROR_PIN_STALE" not in out


class TestMainJsonWireForm:
    """Under CF_QUALITY_JSON the gate emits the canonical GateVerdict schema the
    rest of the battery already speaks, so cf-gate gets rich per-finding verdicts
    rather than falling back to the bare exit code. The human default is unchanged.
    """

    def test_violations_emit_gate_verdict_json(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(JSON_ENV_VAR, "1")
        make_mirror(tmp_path, "data/intro.md", b"drifted\n")
        pinned = real_clock_pin()
        write_mirrors(tmp_path, row("data/intro.md", sha256_of(b"original\n"), pinned=pinned))
        code = main(["--repo", str(tmp_path)])
        report = json.loads(capsys.readouterr().out)
        assert code == 1
        assert report["gate"] == "cf-mirror-check"
        assert report["passed"] is False
        assert report["exit_code"] == 1
        assert report["error"] is None
        assert report["evidence"] == {"mirror_rows": 1}
        assert len(report["violations"]) == 1  # exactly one finding, no pin noise
        (violation,) = report["violations"]
        assert violation["code"] == "MIRROR_DIVERGED"
        assert violation["path"] == "data/intro.md"

    def test_clean_emits_passing_verdict_json(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(JSON_ENV_VAR, "1")
        digest = make_mirror(tmp_path, "data/intro.md", b"content\n")
        write_mirrors(tmp_path, row("data/intro.md", digest, pinned=real_clock_pin()))
        code = main(["--repo", str(tmp_path)])
        report = json.loads(capsys.readouterr().out)
        assert code == 0
        assert report["gate"] == "cf-mirror-check"
        assert report["passed"] is True
        assert report["violations"] == []
        assert report["evidence"] == {"mirror_rows": 1}  # the denominator: one row read

    def test_gate_error_emits_verdict_json_on_stderr(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(JSON_ENV_VAR, "1")
        code = main(["--repo", str(tmp_path)])  # no MIRRORS.md: the gate cannot run
        captured = capsys.readouterr()
        assert code == 2
        assert captured.out == ""  # the wire form for a gate error lands on stderr
        report = json.loads(captured.err)
        assert report["exit_code"] == 2
        assert report["error"]["code"] == "MIRRORS_FILE_MISSING"
