from __future__ import annotations

from scripts import check_dashboard_v2_source_asset_pair as pairing


def test_pairing_ok_when_no_dashboard_source_changes() -> None:
    report = pairing.evaluate_pairing(
        ["docs/readme.md", "enoch_control_plane/control_plane/router.py"]
    )
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


def test_package_json_scripts_only_do_not_require_assets(monkeypatch) -> None:
    monkeypatch.setattr(
        pairing, "package_json_change_affects_build", lambda _base: False
    )
    report = pairing.evaluate_pairing(
        ["dashboard/package.json"], base_ref="origin/main"
    )
    assert report["ok"] is True
    assert report["source_changed"] == []


def test_package_json_dependency_change_affects_build(monkeypatch) -> None:
    def fake_loader(ref: str) -> dict[str, object] | None:
        if ref == "branch-base":
            return {
                "version": "1.0.0",
                "dependencies": {"react": "^19.2.1"},
                "devDependencies": {"vite": "^5.0.0"},
                "scripts": {"test": "vitest"},
            }
        if ref == "HEAD":
            return {
                "version": "1.0.0",
                "dependencies": {"react": "^19.2.2"},
                "devDependencies": {"vite": "^5.0.0"},
                "scripts": {"test": "vitest"},
            }
        return None

    monkeypatch.setattr(pairing, "_merge_base_ref", lambda _base: "branch-base")
    monkeypatch.setattr(pairing, "_load_package_json_from_ref", fake_loader)
    assert pairing.package_json_change_affects_build("origin/main") is True


def test_package_json_scripts_only_change_does_not_affect_build(monkeypatch) -> None:
    def fake_loader(ref: str) -> dict[str, object] | None:
        if ref == "branch-base":
            return {
                "version": "1.0.0",
                "dependencies": {"react": "^19.2.1"},
                "devDependencies": {"vite": "^5.0.0"},
                "scripts": {"test": "vitest"},
            }
        if ref == "HEAD":
            return {
                "version": "1.0.0",
                "dependencies": {"react": "^19.2.1"},
                "devDependencies": {"vite": "^5.0.0"},
                "scripts": {"test": "vitest --watch"},
            }
        return None

    monkeypatch.setattr(pairing, "_merge_base_ref", lambda _base: "branch-base")
    monkeypatch.setattr(pairing, "_load_package_json_from_ref", fake_loader)
    assert pairing.package_json_change_affects_build("origin/main") is False


def test_package_json_scripts_only_ignores_unrelated_main_dep_changes(
    monkeypatch,
) -> None:
    """Branch scripts-only edits must not fail when origin/main moved deps forward."""

    def fake_loader(ref: str) -> dict[str, object] | None:
        if ref == "branch-base":
            return {
                "version": "1.0.0",
                "dependencies": {"react": "^19.2.1"},
                "devDependencies": {"vite": "^5.0.0"},
                "scripts": {"test": "vitest"},
            }
        if ref == "HEAD":
            return {
                "version": "1.0.0",
                "dependencies": {"react": "^19.2.1"},
                "devDependencies": {"vite": "^5.0.0"},
                "scripts": {"test": "vitest --watch"},
            }
        if ref == "origin/main":
            return {
                "version": "1.0.0",
                "dependencies": {"react": "^19.3.0"},
                "devDependencies": {"vite": "^5.0.0"},
                "scripts": {"test": "vitest"},
            }
        return None

    monkeypatch.setattr(pairing, "_merge_base_ref", lambda _base: "branch-base")
    monkeypatch.setattr(pairing, "_load_package_json_from_ref", fake_loader)
    assert pairing.package_json_change_affects_build("origin/main") is False
