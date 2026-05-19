from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "apply-github-protections.sh"


def _fake_gh(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "gh-calls.txt"
    gh = bin_dir / "gh"
    gh.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$*\" >> \"$GH_CALLS\"\n"
        "cat >/dev/null || true\n",
        encoding="utf-8",
    )
    gh.chmod(0o755)
    calls.write_text("", encoding="utf-8")
    return bin_dir


def test_apply_github_protections_derives_counts_from_manifest(tmp_path: Path) -> None:
    manifest = tmp_path / "ecosystem.json"
    manifest.write_text(json.dumps({"artifact_count": 12, "promising_signal_count": 7}), encoding="utf-8")
    bin_dir = _fake_gh(tmp_path)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "GH_CALLS": str(tmp_path / "gh-calls.txt"),
            "ECOSYSTEM_MANIFEST": str(manifest),
        }
    )

    subprocess.run(["bash", str(SCRIPT)], cwd=ROOT, env=env, check=True, text=True)

    calls = (tmp_path / "gh-calls.txt").read_text(encoding="utf-8")
    assert "12 AI-generated research artifacts produced by Enoch" in calls
    assert "7 bounded Enoch promising signals preserved" in calls
    assert "388 AI-generated" not in calls
    assert "4 bounded Enoch promising" not in calls


def test_apply_github_protections_fails_closed_on_missing_manifest_count(tmp_path: Path) -> None:
    manifest = tmp_path / "ecosystem.json"
    manifest.write_text(json.dumps({"artifact_count": 12}), encoding="utf-8")
    bin_dir = _fake_gh(tmp_path)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "GH_CALLS": str(tmp_path / "gh-calls.txt"),
            "ECOSYSTEM_MANIFEST": str(manifest),
        }
    )

    result = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert "promising_signal_count" in result.stderr
    assert (tmp_path / "gh-calls.txt").read_text(encoding="utf-8") == ""


def test_apply_github_protections_rejects_boolean_manifest_count(tmp_path: Path) -> None:
    manifest = tmp_path / "ecosystem.json"
    manifest.write_text(
        json.dumps({"artifact_count": True, "promising_signal_count": 7}),
        encoding="utf-8",
    )
    bin_dir = _fake_gh(tmp_path)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "GH_CALLS": str(tmp_path / "gh-calls.txt"),
            "ECOSYSTEM_MANIFEST": str(manifest),
        }
    )

    result = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert "artifact_count" in result.stderr
    assert (tmp_path / "gh-calls.txt").read_text(encoding="utf-8") == ""
