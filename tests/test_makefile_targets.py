from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _makefile_targets(makefile: str) -> set[str]:
    targets: set[str] = set()
    for line in makefile.splitlines():
        if not line or line.startswith(("\t", "#", ".")):
            continue
        target, separator, remainder = line.partition(":")
        if not separator or "=" in target or target.strip() != target:
            continue
        if remainder.startswith("="):
            continue
        targets.add(target)
    return targets


def _phony_targets(makefile: str) -> set[str]:
    phony: set[str] = set()
    for line in makefile.splitlines():
        if line.startswith(".PHONY:"):
            phony.update(line.removeprefix(".PHONY:").split())
    return phony


def test_makefile_declares_all_recipes_phony() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")

    assert _makefile_targets(makefile) <= _phony_targets(makefile)
