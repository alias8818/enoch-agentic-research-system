"""Shared pytest configuration."""

from __future__ import annotations

import os

from hypothesis import settings

settings.register_profile("ci", max_examples=20, deadline=None)
settings.load_profile(
    os.environ.get("HYPOTHESIS_PROFILE", "ci" if os.environ.get("CI") else "default")
)
