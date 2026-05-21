from __future__ import annotations

import json
from pathlib import Path

from scripts import validate_dashboard_v2_assets


def _write_asset(root: Path, rel: str, content: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_compare_asset_trees_accepts_matching_files(tmp_path: Path) -> None:
    committed = tmp_path / "committed"
    built = tmp_path / "built"
    _write_asset(committed, "index.html", "<html>v2</html>\n")
    _write_asset(committed, "assets/index-abc.js", "console.log('ok');\n")
    _write_asset(built, "index.html", "<html>v2</html>\n")
    _write_asset(built, "assets/index-abc.js", "console.log('ok');\n")

    report = validate_dashboard_v2_assets.compare_asset_trees(
        committed_root=committed,
        built_root=built,
    )

    assert report["ok"] is True
    assert report["failures"] == []
    assert report["file_count"] == 2


def test_compare_asset_trees_rejects_hash_drift(tmp_path: Path) -> None:
    committed = tmp_path / "committed"
    built = tmp_path / "built"
    _write_asset(committed, "assets/index-abc.js", "committed\n")
    _write_asset(built, "assets/index-abc.js", "built\n")

    report = validate_dashboard_v2_assets.compare_asset_trees(
        committed_root=committed,
        built_root=built,
    )

    assert report["ok"] is False
    assert report["failures"] == ["hash drift: assets/index-abc.js"]
    assert report["files"][0]["committed_sha256"] != report["files"][0]["built_sha256"]


def test_compare_asset_trees_rejects_missing_and_extra_files(tmp_path: Path) -> None:
    committed = tmp_path / "committed"
    built = tmp_path / "built"
    _write_asset(committed, "index.html", "<html>v2</html>\n")
    _write_asset(committed, "assets/index-old.js", "old\n")
    _write_asset(built, "index.html", "<html>v2</html>\n")
    _write_asset(built, "assets/index-new.js", "new\n")

    report = validate_dashboard_v2_assets.compare_asset_trees(
        committed_root=committed,
        built_root=built,
    )

    assert report["ok"] is False
    assert "missing built file: assets/index-old.js" in report["failures"]
    assert "unexpected built file: assets/index-new.js" in report["failures"]


def test_validate_dashboard_v2_assets_rejects_missing_committed_dir(tmp_path: Path) -> None:
    report = validate_dashboard_v2_assets.validate_dashboard_v2_assets(
        repo_root=tmp_path,
        run_build=False,
    )

    assert report["ok"] is False
    assert report["failures"][0].startswith("missing committed assets directory:")


def test_main_json_success_when_skip_build_and_assets_present(tmp_path: Path, capsys) -> None:
    committed = tmp_path / "enoch_control_plane/control_plane/dashboard_v2"
    _write_asset(committed, "index.html", "<html>v2</html>\n")

    code = validate_dashboard_v2_assets.main(
        [
            "--repo-root",
            str(tmp_path),
            "--skip-build",
            "--json",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["file_count"] == 1


def test_main_json_failure_when_committed_assets_missing(tmp_path: Path, capsys) -> None:
    code = validate_dashboard_v2_assets.main(
        [
            "--repo-root",
            str(tmp_path),
            "--skip-build",
            "--json",
        ]
    )

    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["failures"][0].startswith("missing committed assets directory:")
