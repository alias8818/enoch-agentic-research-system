from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_notion_sync_unit_is_credential_gated_and_non_dispatching() -> None:
    service = (ROOT / "deploy" / "enoch-notion-sync.service").read_text(encoding="utf-8")
    script = (ROOT / "deploy" / "enoch_notion_sync.sh").read_text(encoding="utf-8")
    assert "EnvironmentFile=-/etc/enoch/notion-sync.env" in service
    assert "notion_sync" in script
    assert "NOTION_TOKEN" in script
    assert "/control/dispatch-next" not in service + script
    assert "192.168.1.77" not in service + script


def test_paper_draft_unit_never_dispatches() -> None:
    service = (ROOT / "deploy" / "enoch-paper-draft-next.service").read_text(encoding="utf-8")
    script = (ROOT / "deploy" / "enoch_paper_draft_next.sh").read_text(encoding="utf-8")
    combined = service + script
    assert "/control/papers/draft-next" in combined
    assert "/control/dispatch-next" not in combined
    assert "192.168.1.77" not in combined


def test_install_script_installs_sync_and_draft_units() -> None:
    install = (ROOT / "scripts" / "install-control-plane.sh").read_text(encoding="utf-8")
    for name in ["enoch-notion-sync.service", "enoch-notion-sync.timer", "enoch-paper-draft-next.service", "enoch-paper-draft-next.timer"]:
        assert name in install
