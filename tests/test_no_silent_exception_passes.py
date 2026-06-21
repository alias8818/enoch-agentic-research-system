from __future__ import annotations

import ast
from pathlib import Path


def test_control_plane_has_no_pass_only_exception_handlers() -> None:
    root = Path("enoch_control_plane")
    offenders: list[str] = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ExceptHandler)
                and len(node.body) == 1
                and isinstance(node.body[0], ast.Pass)
            ):
                exc = ast.unparse(node.type) if node.type is not None else "bare"
                offenders.append(f"{path}:{node.lineno}: except {exc}: pass")
    assert offenders == []
