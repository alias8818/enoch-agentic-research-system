from __future__ import annotations

from pathlib import Path
import tomllib


RUNTIME_DEPENDENCIES = tomllib.loads(
    Path("pyproject.toml").read_text(encoding="utf-8")
)["project"]["dependencies"]


def _runtime_dependency(name: str) -> str:
    prefix = f"{name}>="
    matches = [dep for dep in RUNTIME_DEPENDENCIES if dep.startswith(prefix)]
    assert len(matches) == 1
    return matches[0]


def test_langgraph_runtime_dependency_is_major_bounded() -> None:
    assert _runtime_dependency("langgraph") == "langgraph>=1.1.10,<2.0.0"


def test_all_runtime_dependencies_have_upper_bounds() -> None:
    missing = [dep for dep in RUNTIME_DEPENDENCIES if "<" not in dep]

    assert missing == []
