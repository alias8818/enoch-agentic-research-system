from __future__ import annotations

from datetime import datetime, timezone

from enoch_control_plane.timeutils import parse_utc_datetime


def test_parse_utc_datetime_treats_naive_strings_as_utc() -> None:
    parsed = parse_utc_datetime("2026-05-10T04:45:00")

    assert parsed == datetime(2026, 5, 10, 4, 45, tzinfo=timezone.utc)


def test_parse_utc_datetime_normalizes_z_suffix() -> None:
    parsed = parse_utc_datetime("2026-05-10T04:45:00Z")

    assert parsed == datetime(2026, 5, 10, 4, 45, tzinfo=timezone.utc)


def test_parse_utc_datetime_normalizes_offset_datetimes() -> None:
    parsed = parse_utc_datetime("2026-05-10T00:45:00-04:00")

    assert parsed == datetime(2026, 5, 10, 4, 45, tzinfo=timezone.utc)


def test_parse_utc_datetime_rejects_invalid_values() -> None:
    assert parse_utc_datetime(None) is None
    assert parse_utc_datetime("") is None
    assert parse_utc_datetime("not-a-date") is None
