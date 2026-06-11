"""cf-exemptions honors the committed ``[tool.cf-quality] source_root``.

Split from ``test_exemptions.py`` by design (the file budget measures,
review judges): this file carries one coherent unit — the declared-layout
defect and its control rod.

Kit-gate defect (mexxa main-green pass): cf-exemptions discovered the
repo-root ``src/`` (JS in mexxa's case) and IGNORED the committed
``source_root`` — every registered exemption was documentation-grade because
the scanner never visited the files it covered. The measured tree must
resolve through cf-repo-config exactly like the gauges do.

Control rod: a repo with ``source_root = "server/src"`` and an unregistered
suppression in ``server/src/`` MUST fail — before this fix it silently
passed.
"""

from pathlib import Path

import pytest
from test_exemptions import entry, run_gate, write_exemptions


def _monorepo(tmp_path: Path, body: str) -> None:
    """Repo-root src/ holds only JS (the mexxa shape); Python lives in server/src."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.js").write_text("const x = 1;\n", encoding="utf-8")
    server_src = tmp_path / "server" / "src"
    server_src.mkdir(parents=True)
    (server_src / "mod.py").write_text(body, encoding="utf-8")
    (tmp_path / ".cf-quality.toml").write_text(
        '[tool.cf-quality]\nsource_root = "server/src"\n', encoding="utf-8"
    )


def test_unregistered_suppression_under_declared_root_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _monorepo(tmp_path, "def gnarly():  # noqa: C901\n    return 1\n")
    code, _, err = run_gate(tmp_path, capsys)
    assert code == 2  # gated suppression + no exemptions.json = typed gate error
    assert "GATE_CONFIG_MISSING" in err


def test_registered_suppression_under_declared_root_passes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _monorepo(tmp_path, "def gnarly():  # noqa: C901\n    return 1\n")
    write_exemptions(tmp_path, [entry("server/src/mod.py", "gnarly", "C901")], frozen_count=1)
    code, _, _ = run_gate(tmp_path, capsys)
    assert code == 0


def test_unregistered_suppression_with_registry_present_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _monorepo(tmp_path, "def gnarly():  # noqa: C901\n    return 1\n")
    write_exemptions(tmp_path, [entry("server/src/other.py", "ghost", "C901")], frozen_count=1)
    code, out, _ = run_gate(tmp_path, capsys)
    assert code == 1
    assert "UNREGISTERED_SUPPRESSION" in out
    assert "server/src/mod.py:1" in out


def test_declared_root_excludes_undeclared_siblings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The declared root IS the measured tree (mirroring the mypy gate):
    # a suppression outside it is the legacy surface, not this gate's.
    _monorepo(tmp_path, "x = 1\n")
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "old.py").write_text("x = 1  # nosec\n", encoding="utf-8")
    code, _, _ = run_gate(tmp_path, capsys)
    assert code == 0


def test_invalid_declared_root_fails_typed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ".cf-quality.toml").write_text(
        '[tool.cf-quality]\nsource_root = "ghost/src"\n', encoding="utf-8"
    )
    code, _, err = run_gate(tmp_path, capsys)
    assert code == 2
    assert "GATE_CONFIG_INVALID" in err
