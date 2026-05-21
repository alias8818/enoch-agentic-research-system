from __future__ import annotations

from scripts import check_dashboard_v2_source_asset_pair as pairing


def test_pairing_ok_when_no_dashboard_source_changes() -> None:
    report = pairing.evaluate_pairing(["docs/readme.md", "enoch_control_plane/control_plane/router.py"])
    assert report["ok"] is True


def test_pairing_ok_when_source_and_assets_change_together() -> None:
    report = pairing.evaluate_pairing(
        [
            "dashboard/src/components/CommandHero.tsx",
            "enoch_control_plane/control_plane/dashboard_v2/index.html",
            "enoch_control_plane/control_plane/dashboard_v2/assets/index-abc.js",
        ]
    )
    assert report["ok"] is True


def test_pairing_fails_when_source_changes_without_assets() -> None:
    report = pairing.evaluate_pairing(["dashboard/src/components/CommandHero.tsx"])
    assert report["ok"] is False
    assert report["source_changed"] == ["dashboard/src/components/CommandHero.tsx"]
    assert report["asset_changed"] == []


def test_test_only_dashboard_changes_do_not_require_assets() -> None:
    report = pairing.evaluate_pairing(["dashboard/src/App.test.tsx"])
    assert report["ok"] is True
    assert report["source_changed"] == []
