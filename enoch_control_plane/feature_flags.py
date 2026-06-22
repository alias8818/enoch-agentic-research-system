from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("enoch.feature_flags")

# Feature flags are stored in a JSON file alongside the main config.
# Each flag has: name, enabled (bool), description, and created_at.
# This lightweight system avoids external service dependencies while
# providing the toggle pattern for safe rollouts of agent-authored code.

_DEFAULT_FLAGS_PATH_NAME = "feature_flags.json"


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
            return {k: v for k, v in data.items() if isinstance(v, dict)}
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load feature flags from %s: %s", self._path, exc)
            return {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._flags, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
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
