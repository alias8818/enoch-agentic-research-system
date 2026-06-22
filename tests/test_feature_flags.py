import json
import logging
from pathlib import Path
from typing import Any

import pytest

from enoch_control_plane.feature_flags import FeatureFlagStore


def write_flags(tmp_path: Path, flags: dict[str, Any]) -> None:
    tmp_path.joinpath("feature_flags.json").write_text(
        json.dumps(flags),
        encoding="utf-8",
    )


def test_is_enabled_honors_strict_boolean_values(tmp_path: Path) -> None:
    write_flags(
        tmp_path,
        {
            "enabled_flag": {"enabled": True},
            "disabled_flag": {"enabled": False},
        },
    )

    store = FeatureFlagStore(tmp_path)

    assert store.is_enabled("enabled_flag") is True
    assert store.is_enabled("disabled_flag", default=True) is False


def test_is_enabled_fails_closed_for_string_boolean_values(tmp_path: Path) -> None:
    write_flags(
        tmp_path,
        {
            "false_string": {"enabled": "false"},
            "zero_string": {"enabled": "0"},
            "true_string": {"enabled": "true"},
        },
    )

    store = FeatureFlagStore(tmp_path)

    assert store.is_enabled("false_string") is False
    assert store.is_enabled("zero_string") is False
    assert store.is_enabled("true_string") is False


def test_is_enabled_uses_default_only_when_flag_or_enabled_value_is_missing(
    tmp_path: Path,
) -> None:
    write_flags(tmp_path, {"missing_enabled": {"description": "not rolled out"}})

    store = FeatureFlagStore(tmp_path)

    assert store.is_enabled("unknown", default=True) is True
    assert store.is_enabled("missing_enabled", default=True) is True
    assert store.is_enabled("missing_enabled", default=False) is False


def test_load_ignores_non_mapping_flags_and_malformed_json(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    write_flags(tmp_path, {"valid": {"enabled": True}, "invalid": True})

    store = FeatureFlagStore(tmp_path)

    assert store.list_flags() == {"valid": {"enabled": True}}

    tmp_path.joinpath("feature_flags.json").write_text("{", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="enoch.feature_flags"):
        malformed_store = FeatureFlagStore(tmp_path)

    assert malformed_store.list_flags() == {}
    assert "Failed to load feature flags" in caplog.text


def test_set_flag_persists_and_preserves_existing_description(tmp_path: Path) -> None:
    store = FeatureFlagStore(tmp_path)

    created = store.set_flag("rollout", True, description="guarded rollout")
    updated = store.set_flag("rollout", False)
    reloaded = FeatureFlagStore(tmp_path)

    assert created["enabled"] is True
    assert updated["enabled"] is False
    assert updated["description"] == "guarded rollout"
    assert reloaded.list_flags()["rollout"]["description"] == "guarded rollout"
    assert reloaded.is_enabled("rollout") is False


def test_remove_flag_persists_only_when_flag_exists(tmp_path: Path) -> None:
    store = FeatureFlagStore(tmp_path)
    store.set_flag("temporary", True)

    assert store.remove_flag("temporary") is True
    assert store.remove_flag("temporary") is False
    assert FeatureFlagStore(tmp_path).list_flags() == {}
