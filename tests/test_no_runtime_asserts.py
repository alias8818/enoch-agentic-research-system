"""Regression guard for #281/#282: assert must not be used as runtime control flow.

`assert` statements are stripped under `python -O` / `PYTHONOPTIMIZE=1`, which
is the production setting for many systemd / container entrypoints. If a guard
is implemented as `assert X is not None` instead of an explicit
`if X is None: raise ...`, the guard silently disappears in optimized builds
and the next line crashes with a confusing downstream error (often
`TypeError: exceptions must derive from BaseException` when the assert was
narrowing an exception).

This test scans all production ``.py`` files under ``enoch_control_plane/``
and fails on any top-level or nested ``assert`` statement. Tests are
intentionally exempt - they assert freely. The same shape of regression also
bit ``supabase_store._with_retry`` and ``worker_evidence_sync`` and was fixed
in ``741bef9d`` ("Replace runtime asserts with explicit invariants"). This
guard ensures no future PR can reintroduce the same class of bug without
being noticed in CI.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PROD_ROOT = REPO_ROOT / "enoch_control_plane"


def _production_python_files() -> list[Path]:
    return sorted(PROD_ROOT.rglob("*.py"))


def test_production_modules_have_no_assert_statements() -> None:
    offenders: list[str] = []
    for path in _production_python_files():
        if "__pycache__" in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Assert):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")
    assert offenders == [], (
        "production code uses `assert` as runtime control flow; "
        "`python -O` will strip these. Replace with explicit "
        "`if ...: raise ...`. offenders: " + ", ".join(offenders)
    )


def test_replacement_invariant_for_with_retry() -> None:
    """Direct pin for the ``_with_retry`` invariant that #281 originally cited.

    The bug class: a retry loop ends without ever raising, then
    ``assert last_exc`` is followed by ``raise last_exc`` which becomes
    ``raise None`` under ``-O``. The invariant must be expressed with an
    explicit ``raise RuntimeError(...)``, not an ``assert``.
    """
    supabase_store = (PROD_ROOT / "control_plane" / "supabase_store.py").read_text(
        encoding="utf-8"
    )
    assert "invariant violated" in supabase_store, (
        "_with_retry must raise an explicit RuntimeError on the "
        "no-exception exit path; the `assert last_exc is not None` form "
        "was replaced for `python -O` safety."
    )


def test_replacement_invariant_for_worker_evidence_sync() -> None:
    """Direct pin for the worker evidence sync invariants that #281 cited."""
    worker_sync = (PROD_ROOT / "control_plane" / "worker_evidence_sync.py").read_text(
        encoding="utf-8"
    )
    assert "_require_worker_evidence_artifact_root" in worker_sync, (
        "worker_evidence_sync must use an explicit helper to assert the "
        "artifact_root invariant instead of "
        "`assert artifact_root is not None`."
    )
