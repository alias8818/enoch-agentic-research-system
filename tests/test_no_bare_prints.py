from __future__ import annotations

import ast
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "enoch_control_plane"


def test_control_plane_package_has_no_bare_print_calls() -> None:
    offenders: list[str] = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id == "print":
                    rel = path.relative_to(PACKAGE_ROOT.parent)
                    offenders.append(f"{rel}:{node.lineno}")

    assert offenders == []
