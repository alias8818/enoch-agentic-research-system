from __future__ import annotations

import ast
from pathlib import Path

SILENT_EXCEPT_JUSTIFICATION = "silent-except:"
LOGGING_CALL_NAMES = {"debug", "info", "warning", "error", "exception", "critical"}


def _source_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def _has_silent_except_justification(lines: list[str], node: ast.ExceptHandler) -> bool:
    for line_no in range(node.lineno, getattr(node, "end_lineno", node.lineno) + 1):
        if SILENT_EXCEPT_JUSTIFICATION in lines[line_no - 1]:
            return True
    return False


def _is_empty_literal(node: ast.AST | None) -> bool:
    if node is None:
        return True
    if isinstance(node, ast.Constant):
        return node.value in (None, "", 0, False)
    if isinstance(node, ast.List | ast.Tuple | ast.Set):
        return len(node.elts) == 0
    if isinstance(node, ast.Dict):
        return len(node.keys) == 0
    return False


def _is_logging_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    return isinstance(node.func, ast.Attribute) and node.func.attr in LOGGING_CALL_NAMES


def _handler_has_observable_action(node: ast.ExceptHandler) -> bool:
    return any(
        isinstance(child, ast.Raise) or _is_logging_call(child)
        for child in ast.walk(node)
    )


def _exception_name(node: ast.ExceptHandler) -> str:
    return ast.unparse(node.type) if node.type is not None else "bare"


def _silent_handler_reason(node: ast.ExceptHandler) -> str | None:
    if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
        return "pass-only"
    if any(
        isinstance(stmt, ast.Continue) for stmt in node.body
    ) and not _handler_has_observable_action(node):
        return "continue-without-observable-action"
    if (
        _exception_name(node) == "Exception"
        and len(node.body) == 1
        and isinstance(node.body[0], ast.Return)
        and _is_empty_literal(node.body[0].value)
        and not _handler_has_observable_action(node)
    ):
        return "broad-exception-empty-return"
    return None


def test_control_plane_exception_handlers_are_observable_or_explicitly_justified() -> (
    None
):
    offenders: list[str] = []
    root = Path("enoch_control_plane")
    for path in sorted(root.rglob("*.py")):
        lines = _source_lines(path)
        tree = ast.parse("\n".join(lines), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            reason = _silent_handler_reason(node)
            if reason is None or _has_silent_except_justification(lines, node):
                continue
            offenders.append(
                f"{path}:{node.lineno}: except {_exception_name(node)}: {reason} without logging/raise or {SILENT_EXCEPT_JUSTIFICATION} justification"
            )
    assert offenders == []
