from __future__ import annotations

import os
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest


pytestmark = pytest.mark.repo_root

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
        for directory in [ROOT / ".codegraph", ROOT / "__pycache__"]:
            if not directory.exists():
                directory.mkdir()
                created_dirs.append(directory)
        for directory in [
            ROOT / "node_modules",
            ROOT / "build",
            ROOT / ".pytest_cache",
            ROOT / ".ruff_cache",
            ROOT / ".mypy_cache",
            ROOT / ".hypothesis",
            ROOT / ".enoch",
            ROOT / "enoch_agentic_research_system.egg-info",
        ]:
            if not directory.exists():
                directory.mkdir()
                created_dirs.append(directory)

        payloads = {
            ROOT / "config.json": '{"omx_inbound_bearer_token":"aardvark-secret"}\n',
            ROOT / ".env.local": "ENOCH_SECRET=aardvark-secret\n",
            ROOT / ".coverage": "coverage data\n",
            ROOT / "nested-archive.tar.gz": "archive\n",
            ROOT / "nested-archive.tgz": "archive\n",
            ROOT / "nested-archive.zip": "archive\n",
            ROOT / "dist-wheel.whl": "wheel\n",
            ROOT / "secrets" / "aardvark_token.txt": "aardvark-secret\n",
            ROOT / "state" / "aardvark_state.json": '{"token":"aardvark-secret"}\n',
            ROOT / "logs" / "aardvark_events.json": '{"token":"aardvark-secret"}\n',
            ROOT / ".codegraph" / "codegraph.db-wal": "sqlite wal\n",
            ROOT / ".codegraph" / "codegraph.db-shm": "sqlite shm\n",
            ROOT / "__pycache__" / "archive_test.pyc": "bytecode\n",
            ROOT / "node_modules" / "package.json": "{}\n",
            ROOT / "build" / "artifact.js": "artifact\n",
            ROOT / ".pytest_cache" / "README.md": "cache\n",
            ROOT / ".ruff_cache" / "CACHEDIR.TAG": "cache\n",
            ROOT / ".mypy_cache" / "cache.json": "{}\n",
            ROOT / ".hypothesis" / "archive-example": "cache\n",
            ROOT / ".enoch" / "state.json": "{}\n",
            ROOT / "enoch_agentic_research_system.egg-info" / "PKG-INFO": "metadata\n",
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
            assert "enoch-agentic-research-system/.env.local" not in names
            assert "enoch-agentic-research-system/.coverage" not in names
            assert "enoch-agentic-research-system/nested-archive.tar.gz" not in names
            assert "enoch-agentic-research-system/nested-archive.tgz" not in names
            assert "enoch-agentic-research-system/nested-archive.zip" not in names
            assert "enoch-agentic-research-system/dist-wheel.whl" not in names
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
            assert not any(
                name.startswith("enoch-agentic-research-system/.codegraph/")
                for name in names
            )
            assert not any(
                name.startswith("enoch-agentic-research-system/__pycache__/")
                for name in names
            )
            assert not any(
                name.startswith("enoch-agentic-research-system/node_modules/")
                for name in names
            )
            assert not any(
                name.startswith("enoch-agentic-research-system/build/")
                for name in names
            )
            assert not any(
                name.startswith("enoch-agentic-research-system/.pytest_cache/")
                for name in names
            )
            assert not any(
                name.startswith("enoch-agentic-research-system/.ruff_cache/")
                for name in names
            )
            assert not any(
                name.startswith("enoch-agentic-research-system/.mypy_cache/")
                for name in names
            )
            assert not any(
                name.startswith("enoch-agentic-research-system/.hypothesis/")
                for name in names
            )
            assert not any(
                name.startswith("enoch-agentic-research-system/.enoch/")
                for name in names
            )
            assert not any(name.endswith(".egg-info/PKG-INFO") for name in names)
            assert not any(".db-" in name for name in names)
    finally:
        for path in reversed(created_paths):
            path.unlink(missing_ok=True)
        for directory in reversed(created_dirs):
            shutil.rmtree(directory, ignore_errors=True)
