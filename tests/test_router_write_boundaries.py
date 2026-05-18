from __future__ import annotations

import ast
from pathlib import Path


ROUTER_PATH = Path("enoch_control_plane/control_plane/router.py")


def _post_routes(tree: ast.Module) -> list[ast.FunctionDef]:
    routes: list[ast.FunctionDef] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for decorator in node.decorator_list:
            if (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr == "post"
            ):
                routes.append(node)
                break
    return routes


def _calls_name(node: ast.FunctionDef, name: str) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Name) and func.id == name:
                return True
            if isinstance(func, ast.Attribute) and func.attr == name:
                return True
    return False


def test_post_routes_have_explicit_write_boundary_or_safe_delegate() -> None:
    """Every POST route must state how readonly store writes are prevented.

    The router owns high-risk operator mutations.  A new POST endpoint should
    either call `_require_writable_store` directly, delegate live dispatch to
    `_live_dispatch` where that guard lives, or stay in the bounded preflight
    path whose observation writes are guarded centrally.
    """

    tree = ast.parse(ROUTER_PATH.read_text(encoding="utf-8"))
    unsafe: list[str] = []
    for route in _post_routes(tree):
        if _calls_name(route, "_require_writable_store"):
            continue
        if _calls_name(route, "_live_dispatch"):
            continue
        if _calls_name(route, "_record_preflight_observations"):
            continue
        if _calls_name(route, "worker_preflight"):
            continue
        unsafe.append(route.name)

    assert unsafe == []
