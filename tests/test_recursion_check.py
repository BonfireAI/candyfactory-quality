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
