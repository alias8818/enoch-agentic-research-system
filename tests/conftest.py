"""Shared pytest configuration."""

from __future__ import annotations

import json
import os
import secrets
import tempfile
from pathlib import Path

from hypothesis import settings

settings.register_profile("ci", max_examples=20, deadline=None)
settings.load_profile(
    os.environ.get("HYPOTHESIS_PROFILE", "ci" if os.environ.get("CI") else "default")
)


def _pytest_worker_id() -> str:
    return os.environ.get("PYTEST_XDIST_WORKER", "master")


def _isolated_gate_config_path() -> Path:
    root = Path(tempfile.gettempdir()) / "enoch-pytest-isolated" / _pytest_worker_id()
    root.mkdir(parents=True, exist_ok=True)
    config_path = root / "gate-config.json"
    if not config_path.exists():
        example_path = Path(__file__).resolve().parents[1] / "config.example.json"
        data = json.loads(example_path.read_text(encoding="utf-8"))
        data["state_dir"] = str(root / "state")
        data["project_root"] = str(root / "projects")
    else:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    token = str(data.get("control_api_bearer_token") or "")
    normalized = token.lower().replace("_", "-")
    if normalized.startswith("replace-with-") or "replace-me" in normalized:
        data["control_api_bearer_token"] = secrets.token_urlsafe(32)
        data["omx_inbound_bearer_token"] = data["control_api_bearer_token"]
    config_path.write_text(
        json.dumps(data, indent=2) + "\n",
        encoding="utf-8",
    )
    return config_path


def _install_isolated_gate_config_env() -> None:
    """Point ENOCH_CONFIG at a per-process sqlite state dir before app import.

    Importing ``enoch_control_plane.app`` eagerly opens
    ``control_plane.sqlite3`` under ``config.expanded_state_dir``. Without
    isolation, xdist workers (or a live gate on the same host) contend on the
    operator default ``~/.local/state/enoch-worker-gate`` database.
    """
    config_path = _isolated_gate_config_path()
    os.environ["ENOCH_CONFIG"] = str(config_path)
    os.environ["ENOCH_CONTROL_PLANE_CONFIG"] = str(config_path)


_install_isolated_gate_config_env()
