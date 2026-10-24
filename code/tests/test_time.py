from datetime import UTC, datetime

import pytest

from ghost_audit.time import parse_timestamp


@pytest.mark.parametrize("value", ["2026-01-02T08:00:00Z", "2026-01-02T12:00:00+04:00",
                                  datetime(2026, 1, 2, 8, tzinfo=UTC)])
def test_normalizes_offsets(value):
    assert parse_timestamp(value) == datetime(2026, 1, 2, 8, tzinfo=UTC)


@pytest.mark.parametrize("value", ["2026-01-02", "2026-01-02T08:00:00", "bad", 123,
                                  datetime(2026, 1, 2, 8)])
def test_rejects_ambiguous_or_invalid_timestamps(value):
    with pytest.raises((ValueError, TypeError)):
        parse_timestamp(value)
