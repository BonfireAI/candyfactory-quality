"""Tests for cf-recursion-check — recursion is declared with a stated bound, or it fails.

Fixture classes mirror the Phase-A audit's false-positive taxonomy (12 of 14 raw
AST hits were NOT self-recursion): super().__init__ chains, super().model_validate
chains, same-named method calls on OTHER objects (obj.foo inside foo, including
object.__new__(cls)), and delegation (a same-named callable passed in as a
parameter). Genuine self-recursion passes only with a declared-bound marker
within 3 lines above the def: ``# recursion: bounded by <non-empty reason>``.

Mutual recursion (a -> b -> a) is an honest v1 OPEN — tested as documented
non-detection, not as a capability.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from cf_quality.errors import GateError, GateViolation
from cf_quality.recursion_check import main, scan_file, scan_tree


def _write(tmp_path: Path, source: str, name: str = "mod.py") -> Path:
    path = tmp_path / name
    path.write_text(textwrap.dedent(source), encoding="utf-8")
    return path


def _scan(tmp_path: Path, source: str) -> list[GateViolation]:
    return scan_file(_write(tmp_path, source), root=tmp_path)


# --- genuine self-recursion: undeclared FAILS -------------------------------


def test_undeclared_module_function_recursion_fails(tmp_path: Path) -> None:
    violations = _scan(
        tmp_path,
        """
        def countdown(n):
            if n <= 0:
                return
            countdown(n - 1)
        """,
    )
    assert len(violations) == 1
    violation = violations[0]
    assert violation.code == "RECURSION_UNDECLARED"
    assert violation.path == "mod.py"
    assert violation.line == 2
    assert "countdown" in violation.message
    assert violation.context["function"] == "countdown"


def test_undeclared_method_self_recursion_fails(tmp_path: Path) -> None:
    violations = _scan(
        tmp_path,
        """
        class Walker:
            def walk(self, node):
                for child in node.children:
                    self.walk(child)
        """,
    )
    assert len(violations) == 1
    assert violations[0].context["function"] == "Walker.walk"


def test_undeclared_classmethod_cls_recursion_fails(tmp_path: Path) -> None:
    violations = _scan(
        tmp_path,
        """
        class Builder:
            @classmethod
            def build(cls, spec):
                if spec.parent:
                    cls.build(spec.parent)
        """,
    )
    assert len(violations) == 1
    assert violations[0].context["function"] == "Builder.build"


def test_undeclared_async_function_recursion_fails(tmp_path: Path) -> None:
    violations = _scan(
        tmp_path,
        """
        async def drain(queue):
            if queue:
                await drain(queue[1:])
        """,
    )
    assert len(violations) == 1
    assert violations[0].context["function"] == "drain"


def test_undeclared_nested_function_recursion_fails(tmp_path: Path) -> None:
    violations = _scan(
        tmp_path,
        """
        def outer():
            def inner(n):
                if n:
                    inner(n - 1)
            inner(3)
        """,
    )
    assert len(violations) == 1
    assert violations[0].context["function"] == "inner"


# --- declared-bound marker: PASSES -------------------------------------------


def test_declared_recursion_directly_above_def_passes(tmp_path: Path) -> None:
    violations = _scan(
        tmp_path,
        """
        # recursion: bounded by depth of the stage-dependency graph
        def dfs(node):
            for child in node.children:
                dfs(child)
        """,
    )
    assert violations == []


def test_declared_recursion_exactly_three_lines_above_passes(tmp_path: Path) -> None:
    violations = _scan(
        tmp_path,
        """
        # recursion: bounded by halving ladder, depth < MAX_HALVINGS
        # (documented in the design doc)
        # extra comment line
        def ladder(batch):
            return ladder(batch[: len(batch) // 2])
        """,
    )
    assert violations == []


def test_declaration_four_lines_above_def_is_out_of_window(tmp_path: Path) -> None:
    violations = _scan(
        tmp_path,
        """
        # recursion: bounded by tree depth
        #
        #
        #
        def walk(node):
            walk(node.child)
        """,
    )
    assert len(violations) == 1


def test_declaration_with_empty_reason_still_fails(tmp_path: Path) -> None:
    violations = _scan(
        tmp_path,
        """
        # recursion: bounded by
        def walk(node):
            walk(node.child)
        """,
    )
    assert len(violations) == 1


def test_declared_method_recursion_passes(tmp_path: Path) -> None:
    violations = _scan(
        tmp_path,
        """
        class Walker:
            # recursion: bounded by AST depth (finite tree)
            def walk(self, node):
                for child in node.children:
                    self.walk(child)
        """,
    )
    assert violations == []


# --- Phase-A false-positive classes: must NOT flag ---------------------------


def test_super_init_chain_is_not_recursion(tmp_path: Path) -> None:
    violations = _scan(
        tmp_path,
        """
        class ToolError(Exception):
            def __init__(self, message):
                super().__init__(message)
        """,
    )
    assert violations == []


def test_super_model_validate_chain_is_not_recursion(tmp_path: Path) -> None:
    violations = _scan(
        tmp_path,
        """
        class Event(Base):
            @classmethod
            def model_validate(cls, obj):
                return super().model_validate(obj)
        """,
    )
    assert violations == []


def test_same_named_call_on_other_object_is_not_recursion(tmp_path: Path) -> None:
    violations = _scan(
        tmp_path,
        """
        class Scanner:
            def scan(self, target):
                return self.backend.scan(target)

        def scan(tree):
            walker = Scanner()
            return walker.scan(tree)
        """,
    )
    assert violations == []


def test_other_class_dispatch_is_not_recursion(tmp_path: Path) -> None:
    violations = _scan(
        tmp_path,
        """
        class CrmErrorCode(str):
            def __new__(cls, value):
                return object.__new__(cls)
        """,
    )
    assert violations == []


def test_delegation_via_same_named_parameter_is_not_recursion(tmp_path: Path) -> None:
    violations = _scan(
        tmp_path,
        """
        def retry(retry):
            return retry()
        """,
    )
    assert violations == []


def test_bare_name_call_inside_method_resolves_to_module_not_method(tmp_path: Path) -> None:
    violations = _scan(
        tmp_path,
        """
        def render(template):
            return template

        class Page:
            def render(self):
                return render(self.template)
        """,
    )
    assert violations == []


def test_call_only_inside_nested_def_does_not_flag_outer(tmp_path: Path) -> None:
    # outer -> inner -> outer is mutual-recursion-shaped: v1 OPEN, not flagged.
    violations = _scan(
        tmp_path,
        """
        def outer(n):
            def inner():
                return outer(n - 1)
            return inner
        """,
    )
    assert violations == []


# --- dynamic-class receivers: genuine self-recursion, refuter evasions A/B ---


def test_type_self_receiver_recursion_fails(tmp_path: Path) -> None:
    # Refuter evasion A: type(self).walk(self, n-1) resolves to the method itself.
    violations = _scan(
        tmp_path,
        """
        class Walker:
            def walk(self, n):
                if n <= 0:
                    return 0
                return type(self).walk(self, n - 1)
        """,
    )
    assert [v.code for v in violations] == ["RECURSION_UNDECLARED"]
    assert violations[0].context["function"] == "Walker.walk"


def test_dunder_class_receiver_recursion_fails(tmp_path: Path) -> None:
    # Refuter evasion B: self.__class__.crawl(self, n-1) resolves to the method itself.
    violations = _scan(
        tmp_path,
        """
        class Spider:
            def crawl(self, n):
                if n <= 0:
                    return 0
                return self.__class__.crawl(self, n - 1)
        """,
    )
    assert [v.code for v in violations] == ["RECURSION_UNDECLARED"]
    assert violations[0].context["function"] == "Spider.crawl"


def test_type_self_recursion_with_declared_bound_passes(tmp_path: Path) -> None:
    violations = _scan(
        tmp_path,
        """
        class Walker:
            # recursion: bounded by n, strictly decreasing to 0
            def walk(self, n):
                if n <= 0:
                    return 0
                return type(self).walk(self, n - 1)
        """,
    )
    assert violations == []


def test_type_of_other_object_is_not_recursion(tmp_path: Path) -> None:
    # type(other).walk(...) dispatches on a foreign object's class — not self.
    violations = _scan(
        tmp_path,
        """
        class Walker:
            def walk(self, other, n):
                return type(other).walk(other, n - 1)
        """,
    )
    assert violations == []


def test_module_qualified_self_call_is_documented_open_not_detected(tmp_path: Path) -> None:
    # Refuter evasion C: descend reached through sys.modules[__name__] is
    # genuine unbounded self-recursion this gate does NOT see (static dataflow
    # to the module object is out of scope). Pinned as a DISCLOSED limitation.
    violations = _scan(
        tmp_path,
        """
        import sys

        _self_mod = sys.modules[__name__]

        def descend(n):
            if n <= 0:
                return 0
            return _self_mod.descend(n - 1)
        """,
    )
    assert violations == []
    import cf_quality.recursion_check as rc

    assert rc.__doc__ is not None
    assert "module-qualified" in rc.__doc__, "the evasion must be disclosed in the HONEST OPEN"


# --- mutual recursion: honest v1 OPEN ----------------------------------------


def test_mutual_recursion_is_documented_open_not_detected(tmp_path: Path) -> None:
    # a -> b -> a is genuine recursion this v1 gate does NOT see. This test
    # pins the honest limitation; flipping it to detection is a v2 feature,
    # not a regression fix.
    violations = _scan(
        tmp_path,
        """
        def is_even(n):
            return n == 0 or is_odd(n - 1)

        def is_odd(n):
            return n != 0 and is_even(n - 1)
        """,
    )
    assert violations == []


# --- tree scan + typed gate errors -------------------------------------------


def test_scan_tree_walks_nested_packages(tmp_path: Path) -> None:
    pkg = tmp_path / "src" / "pkg"
    pkg.mkdir(parents=True)
    (pkg / "ok.py").write_text("def flat():\n    return 1\n", encoding="utf-8")
    (pkg / "bad.py").write_text("def loop():\n    loop()\n", encoding="utf-8")
    violations = scan_tree(tmp_path / "src")
    assert [v.path for v in violations] == ["pkg/bad.py"]


def test_scan_tree_missing_path_raises_typed_gate_error(tmp_path: Path) -> None:
    with pytest.raises(GateError) as excinfo:
        scan_tree(tmp_path / "absent")
    assert excinfo.value.code == "GATE_PATH_MISSING"
    assert excinfo.value.retryable is False


def test_unparseable_source_raises_typed_gate_error(tmp_path: Path) -> None:
    path = _write(tmp_path, "def broken(:\n", name="broken.py")
    with pytest.raises(GateError) as excinfo:
        scan_file(path, root=tmp_path)
    assert excinfo.value.code == "GATE_SOURCE_UNPARSEABLE"
    assert "broken.py" in excinfo.value.context["path"]


# --- CLI ----------------------------------------------------------------------


def test_main_returns_one_and_lists_finding(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "loops.py").write_text("def spiral(n):\n    return spiral(n - 1)\n", encoding="utf-8")
    exit_code = main([str(src)])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "spiral" in out
    assert "loops.py" in out
    assert "RECURSION_UNDECLARED" in out


def test_main_returns_zero_on_clean_tree(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "flat.py").write_text("def flat():\n    return 1\n", encoding="utf-8")
    exit_code = main([str(src)])
    assert exit_code == 0
    assert "OK" in capsys.readouterr().out


def test_main_returns_two_on_gate_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main([str(tmp_path / "absent")])
    assert exit_code == 2
    assert "GATE_PATH_MISSING" in capsys.readouterr().err


def test_main_default_honors_declared_source_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Mount-wave fix: with no paths argued, the scan root comes from the
    # committed repo config (cf-repo-config), not a hardcoded `src` — so a
    # monorepo's declared tree is measured, never an empty default.
    (tmp_path / ".cf-quality.toml").write_text(
        '[tool.cf-quality]\nsource_root = "server/src"\n', encoding="utf-8"
    )
    nested = tmp_path / "server" / "src"
    nested.mkdir(parents=True)
    (nested / "loops.py").write_text("def spiral(n):\n    return spiral(n - 1)\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    exit_code = main([])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "RECURSION_UNDECLARED" in out


def test_main_default_discovers_flat_layout_without_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Absent declaration and no src/: the default measures the repo root —
    # a flat layout is never a silent GATE_PATH_MISSING on the old `src`.
    (tmp_path / "loops.py").write_text(
        "def spiral(n):\n    return spiral(n - 1)\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    exit_code = main([])
    assert exit_code == 1
    assert "RECURSION_UNDECLARED" in capsys.readouterr().out
