from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import tempfile
from typing import Any

logger = logging.getLogger("enoch.feature_flags")

# Feature flags are stored in a JSON file alongside the main config.
# Each flag has: name, enabled (bool), description, and created_at.
# This lightweight system avoids external service dependencies while
# providing the toggle pattern for safe rollouts of agent-authored code.

_DEFAULT_FLAGS_PATH_NAME = "feature_flags.json"


class FeatureFlagLoadError(RuntimeError):
    """Raised when the feature flag file exists but cannot be loaded safely."""


def _fsync_dir(path: Path) -> None:
    try:
        dir_fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


class FeatureFlagStore:
    """Simple file-backed feature flag store.

    Flags are read from a JSON file in the config directory. Changes are
    persisted immediately so they survive restarts.

    Usage:
        flags = FeatureFlagStore(Path(".local/config"))
        if flags.is_enabled("new_evidence_sync"):
            ...
    """

    def __init__(self, config_dir: Path) -> None:
        self._path = config_dir / _DEFAULT_FLAGS_PATH_NAME
        self._flags: dict[str, dict[str, Any]] = self._load()

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self._path.exists():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("feature flags file must contain a JSON object")
            return {k: v for k, v in data.items() if isinstance(v, dict)}
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            logger.warning("Failed to load feature flags from %s: %s", self._path, exc)
            raise FeatureFlagLoadError(
                f"failed to load feature flags from {self._path}: {exc}"
            ) from exc

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=self._path.parent, delete=False
            ) as fh:
                json.dump(self._flags, fh, indent=2, sort_keys=True)
                fh.write("\n")
                fh.flush()
                os.fsync(fh.fileno())
                tmp = Path(fh.name)
            tmp.replace(self._path)
            _fsync_dir(self._path.parent)
        finally:
            if tmp is not None:
                try:
                    if tmp.exists():
                        tmp.unlink()
                except OSError as exc:
                    logger.debug(
                        "failed to remove temporary feature flag file", exc_info=exc
                    )

    def is_enabled(self, name: str, default: bool = False) -> bool:
        """Check if a feature flag is enabled. Returns default if flag doesn't exist."""
        flag = self._flags.get(name)
        if flag is None:
            return default
        enabled = flag.get("enabled")
        if enabled is None:
            return default
        return enabled is True

    def set_flag(
        self, name: str, enabled: bool, description: str = ""
    ) -> dict[str, Any]:
        """Create or update a feature flag."""
        from .models import utc_now

        self._flags[name] = {
            "enabled": enabled,
            "description": description
            or self._flags.get(name, {}).get("description", ""),
            "updated_at": utc_now(),
            "created_at": self._flags.get(name, {}).get("created_at", utc_now()),
        }
        self._save()
        logger.info("Feature flag '%s' set to enabled=%s", name, enabled)
        return self._flags[name]

    def list_flags(self) -> dict[str, dict[str, Any]]:
        """Return all feature flags."""
        return dict(self._flags)

    def remove_flag(self, name: str) -> bool:
        """Remove a feature flag. Returns True if it existed."""
        if name in self._flags:
            del self._flags[name]
            self._save()
            logger.info("Feature flag '%s' removed", name)
            return True
        return False
