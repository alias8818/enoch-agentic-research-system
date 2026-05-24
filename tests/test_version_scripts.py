from __future__ import annotations

import pytest

from scripts import bump_version, validate_versioning


@pytest.mark.parametrize("module", [bump_version, validate_versioning])
def test_version_assignment_regex_avoids_sonar_duplicate_character_class(
    module,
) -> None:
    assert "[0-9A-Za-z.-]" not in module.VERSION_ASSIGNMENT.pattern


@pytest.mark.parametrize("module", [bump_version, validate_versioning])
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('version = "1.2.3"', "1.2.3"),
        ("version = '1.2.3-alpha.1'", "1.2.3-alpha.1"),
        ('version = "1.2.3+build.7"', "1.2.3+build.7"),
        ("1.2.3", "1.2.3"),
    ],
)
def test_read_version_file_text_keeps_existing_version_forms(
    module, raw, expected
) -> None:
    assert module.read_version_file_text(raw) == expected
