"""cf-recursion-check — recursion is declared with a stated bound, or it fails.

The BubbleGum Law keeps recursion declared-not-banned: a genuinely
self-recursive function passes only when a declared-bound marker sits within
3 lines above its ``def`` line::

    # recursion: bounded by <non-empty reason>

What counts as GENUINE self-recursion (the name resolves to itself):

- a module-level or nested function calling its own bare name, unless that
  name is shadowed by one of its own parameters (delegation);
- a method calling itself through its own receiver (``self.f(...)`` /
  ``cls.f(...)`` — the first parameter), through its own class name
  (``MyClass.f(...)`` inside ``MyClass.f``), or through its own dynamically
  resolved class — ``type(self).f(...)`` and ``self.__class__.f(...)`` /
  ``cls.__class__.f(...)`` (the refuter's dynamic-receiver evasions).

What the Phase-A audit proved is NOT self-recursion (12 of 14 raw AST hits)
and this gate therefore excludes:

- ``super().__init__(...)`` / ``super().model_validate(...)`` chains —
  the receiver is a ``super()`` call, never the function itself;
- same-named method calls on OTHER objects (``obj.foo(...)`` inside ``foo``,
  including ``object.__new__(cls)`` inside ``__new__``);
- delegation through a same-named parameter (``def retry(retry): retry()``);
- a bare name call inside a method (``f()`` inside method ``f`` resolves to
  module scope, not the method).

HONEST OPEN (v1): mutual recursion (``a -> b -> a``) is NOT detected, and a
call that reaches the enclosing function only through a nested ``def`` is
treated as mutual-recursion-shaped and likewise not flagged. Detecting cycles
through the call graph is a v2 feature; the limitation is pinned by tests.
Also NOT detected (refuter evasion C, pinned by tests): a module-qualified
self-call — ``mod.f(...)`` where ``mod`` is ``sys.modules[__name__]`` or an
import of the enclosing module itself. Resolving which names alias the module
object requires dataflow analysis this AST gate does not do; the evasion is
declared here rather than silently missed.

Exit codes: 0 clean · 1 violations found · 2 the gate itself could not run
(typed :class:`~cf_quality.errors.GateError` on stderr).
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections.abc import Iterator
from pathlib import Path

from cf_quality.errors import GateError, GateViolation
from cf_quality.repo_config import resolve_source_root

_DECLARATION = re.compile(r"#\s*recursion:\s*bounded by\s+\S")
_DECLARATION_WINDOW = 3
_FUNCTION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)
_SCOPE_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)

_FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef


# recursion: bounded by AST depth (a parsed tree is finite and acyclic)
def _functions_with_context(
    node: ast.AST, class_name: str | None = None
) -> Iterator[tuple[_FunctionNode, str | None]]:
    """Yield every function/method with the name of its directly enclosing class."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, _FUNCTION_NODES):
            yield (child, class_name)
            yield from _functions_with_context(child, None)
        elif isinstance(child, ast.ClassDef):
            yield from _functions_with_context(child, child.name)
        else:
            yield from _functions_with_context(child, class_name)


def _own_scope_calls(fn: _FunctionNode) -> Iterator[ast.Call]:
    """Yield calls in the function's own scope, not those inside nested scopes."""
    pending: list[ast.AST] = list(fn.body)
    while pending:
        node = pending.pop()
        if isinstance(node, _SCOPE_NODES):
            continue
        if isinstance(node, ast.Call):
            yield node
        pending.extend(ast.iter_child_nodes(node))


def _parameter_names(fn: _FunctionNode) -> set[str]:
    args = fn.args
    names = {a.arg for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)}
    for special in (args.vararg, args.kwarg):
        if special is not None:
            names.add(special.arg)
    return names


def _self_receivers(fn: _FunctionNode, class_name: str) -> set[str]:
    """Names through which a method reaches itself: its receiver and its class."""
    receivers = {class_name}
    args = fn.args
    first = (*args.posonlyargs, *args.args)
    if first:
        receivers.add(first[0].arg)
    return receivers


def _is_own_class_receiver(node: ast.expr, receivers: set[str]) -> bool:
    """``type(self)`` / ``self.__class__`` style receivers resolving to the method's class."""
    if isinstance(node, ast.Call):
        return (
            isinstance(node.func, ast.Name)
            and node.func.id == "type"
            and len(node.args) == 1
            and not node.keywords
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id in receivers
        )
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "__class__"
        and isinstance(node.value, ast.Name)
        and node.value.id in receivers
    )


def _is_self_call(call: ast.Call, fn: _FunctionNode, class_name: str | None) -> bool:
    func = call.func
    if class_name is None:
        # Bare-name call to itself; a same-named parameter is delegation.
        return (
            isinstance(func, ast.Name)
            and func.id == fn.name
            and fn.name not in _parameter_names(fn)
        )
    # Method: self.f(...) / cls.f(...) / MyClass.f(...) resolve to itself, as
    # do the dynamic-class receivers type(self).f(...) and self.__class__.f(...).
    # super().f(...) has a super() Call receiver; obj.f(...) a foreign Name.
    if not (isinstance(func, ast.Attribute) and func.attr == fn.name):
        return False
    receivers = _self_receivers(fn, class_name)
    if isinstance(func.value, ast.Name):
        return func.value.id in receivers
    return _is_own_class_receiver(func.value, receivers)


def _self_call_line(fn: _FunctionNode, class_name: str | None) -> int | None:
    for call in _own_scope_calls(fn):
        if _is_self_call(call, fn, class_name):
            return call.lineno
    return None


def _has_declared_bound(lines: list[str], def_lineno: int) -> bool:
    """True if the marker comment sits within 3 lines above the def line."""
    start = max(0, def_lineno - 1 - _DECLARATION_WINDOW)
    window = lines[start : def_lineno - 1]
    return any(_DECLARATION.search(line) for line in window)


def _read_tree(path: Path) -> tuple[ast.Module, list[str]]:
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise GateError(
            code="GATE_SOURCE_UNREADABLE",
            message=f"cannot read source file: {path}",
            context={"path": str(path), "os_error": str(exc)},
        ) from exc
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        raise GateError(
            code="GATE_SOURCE_UNPARSEABLE",
            message=f"cannot parse source file: {path}",
            context={"path": str(path), "line": exc.lineno, "detail": exc.msg},
        ) from exc
    return tree, source.splitlines()


def scan_file(path: Path, root: Path) -> list[GateViolation]:
    """Scan one Python file; report undeclared genuine self-recursion."""
    tree, lines = _read_tree(path)
    try:
        rel = str(path.relative_to(root))
    except ValueError:
        rel = str(path)
    violations: list[GateViolation] = []
    for fn, class_name in _functions_with_context(tree):
        call_line = _self_call_line(fn, class_name)
        if call_line is None or _has_declared_bound(lines, fn.lineno):
            continue
        qualname = fn.name if class_name is None else f"{class_name}.{fn.name}"
        violations.append(
            GateViolation(
                code="RECURSION_UNDECLARED",
                message=(
                    f"function '{qualname}' is self-recursive without a declared "
                    "bound; add '# recursion: bounded by <reason>' within 3 lines "
                    "above its def"
                ),
                path=rel,
                line=fn.lineno,
                context={"function": qualname, "call_line": call_line},
            )
        )
    return violations


def scan_tree(root: Path) -> list[GateViolation]:
    """Scan every ``*.py`` under ``root``; raise GateError if the root is absent."""
    if not root.exists():
        raise GateError(
            code="GATE_PATH_MISSING",
            message=f"source tree does not exist: {root}",
            context={"path": str(root)},
        )
    violations: list[GateViolation] = []
    for path in sorted(root.rglob("*.py")):
        violations.extend(scan_file(path, root=root))
    return violations


def main(argv: list[str] | None = None) -> int:
    """Console entry point. Exit 0 clean, 1 on violations, 2 on gate error."""
    parser = argparse.ArgumentParser(
        prog="cf-recursion-check",
        description="Recursion is declared with a stated bound, or it fails.",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        default=None,
        help=(
            "source trees to scan (default: the repo's declared source_root "
            "from [tool.cf-quality], else src/ when present, else the cwd)"
        ),
    )
    args = parser.parse_args(argv)
    try:
        paths = args.paths or [str(resolve_source_root(Path()))]
        violations = [v for path in paths for v in scan_tree(Path(path))]
    except GateError as exc:
        print(json.dumps(exc.to_dict()), file=sys.stderr)
        return 2
    for violation in violations:
        print(f"{violation.path}:{violation.line}: {violation.code}: {violation.message}")
    if violations:
        print(f"cf-recursion-check: FAIL ({len(violations)} undeclared recursion(s))")
        return 1
    print("cf-recursion-check: OK (all self-recursion carries a declared bound)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
