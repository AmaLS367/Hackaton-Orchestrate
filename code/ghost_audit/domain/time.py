"""Explicit timezone handling; never interpret evidence using the host timezone."""

from datetime import UTC, datetime
from typing import Annotated

from pydantic import BeforeValidator


def parse_timestamp(value: object) -> datetime:
    """Require an explicit timezone and normalize supported timestamps to UTC."""
    if isinstance(value, str):
        # ISO dates alone and timezone-free datetimes are ambiguous evidence.
        if "T" not in value and " " not in value:
            raise ValueError("timestamp must include a time and timezone")
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include an explicit timezone")
    return value.astimezone(UTC)


Timestamp = Annotated[datetime, BeforeValidator(parse_timestamp)]
