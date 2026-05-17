from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWED = {
    Path("enoch_control_plane/timeutils.py"),
}


def test_runtime_code_uses_canonical_utc_datetime_parser() -> None:
    offenders: list[str] = []
    for base in (ROOT / "enoch_control_plane", ROOT / "scripts"):
        for path in base.rglob("*.py"):
            rel = path.relative_to(ROOT)
            if "__pycache__" in rel.parts or rel in ALLOWED:
                continue
            text = path.read_text()
            if "datetime.fromisoformat" in text:
                offenders.append(str(rel))

    assert offenders == []
