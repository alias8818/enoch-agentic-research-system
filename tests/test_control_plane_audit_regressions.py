from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = REPO_ROOT / "enoch_control_plane"


def _python_files() -> list[Path]:
    return sorted(PACKAGE_ROOT.rglob("*.py"))


def test_no_legacy_dispatch_envelope_uuid4_path_remains() -> None:
    app_source = (PACKAGE_ROOT / "app.py").read_text(encoding="utf-8")

    assert not (PACKAGE_ROOT / "dispatch_envelope.py").exists()
    assert "envelope_id = str(uuid.uuid4())" not in app_source
    assert '"envelope_id": envelope_id' in app_source
    assert '"kind": "dispatch_envelope"' in app_source


def test_no_fixed_refresh_token_jitter_window_remains() -> None:
    assert not (PACKAGE_ROOT / "control_plane" / "auth.py").exists()
    offenders: list[str] = []
    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            target_names = {
                target.id for target in node.targets if isinstance(target, ast.Name)
            }
            if "jitter_sec" in target_names and isinstance(node.value, ast.Constant):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")

    assert offenders == []


def test_cited_import_time_observability_singletons_remain_removed() -> None:
    app_source = (PACKAGE_ROOT / "app.py").read_text(encoding="utf-8")

    assert "_OBSERVATION_STORE" not in app_source
    assert "_PROFILING_STORE" not in app_source
    assert "_CALLBACK_OUTBOX" not in app_source
    assert "dispatcher =" not in app_source
    assert "lifespan=lifespan" in app_source
