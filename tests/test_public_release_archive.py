from __future__ import annotations

import os
import subprocess
import tarfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_public_release_archive_excludes_ignored_secret_state_paths(
    tmp_path: Path,
) -> None:
    sensitive_paths = [
        ROOT / "config.json",
        ROOT / "secrets" / "aardvark_token.txt",
        ROOT / "state" / "aardvark_state.json",
        ROOT / "logs" / "aardvark_events.json",
    ]
    existing_paths = [path for path in sensitive_paths if path.exists()]
    if existing_paths:
        pytest.skip(f"local sensitive path already exists: {existing_paths[0]}")

    created_paths: list[Path] = []
    created_dirs: list[Path] = []
    try:
        for directory in [ROOT / "secrets", ROOT / "state", ROOT / "logs"]:
            if not directory.exists():
                directory.mkdir()
                created_dirs.append(directory)

        payloads = {
            ROOT / "config.json": '{"omx_inbound_bearer_token":"aardvark-secret"}\n',
            ROOT / "secrets" / "aardvark_token.txt": "aardvark-secret\n",
            ROOT / "state" / "aardvark_state.json": '{"token":"aardvark-secret"}\n',
            ROOT / "logs" / "aardvark_events.json": '{"token":"aardvark-secret"}\n',
        }
        for path, content in payloads.items():
            path.write_text(content, encoding="utf-8")
            created_paths.append(path)

        archive_dir = tmp_path / "archive"
        env = os.environ | {
            "ENOCH_ARCHIVE_OUT_DIR": str(archive_dir),
            "ENOCH_ARCHIVE_NAME": "public.tar.gz",
        }
        subprocess.run(
            ["bash", "scripts/build_public_release_archive.sh"],
            cwd=ROOT,
            env=env,
            check=True,
            text=True,
            capture_output=True,
        )

        archive_path = archive_dir / "public.tar.gz"
        with tarfile.open(archive_path, "r:gz") as archive:
            names = archive.getnames()
            assert "enoch-agentic-research-system/config.json" not in names
            assert not any(
                name.startswith("enoch-agentic-research-system/secrets/")
                for name in names
            )
            assert not any(
                name.startswith("enoch-agentic-research-system/state/")
                for name in names
            )
            assert not any(
                name.startswith("enoch-agentic-research-system/logs/") for name in names
            )
    finally:
        for path in reversed(created_paths):
            path.unlink(missing_ok=True)
        for directory in reversed(created_dirs):
            directory.rmdir()
