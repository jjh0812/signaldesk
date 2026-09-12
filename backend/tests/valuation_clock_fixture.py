"""Test-only clocks; never imported by the application or the startup scripts.

Pin both generated input dates and API 'now' to the same instant. Do not change
OS time/TZ, market session dates, or production future-price validation.
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

FIXED_UTC = datetime(2026, 9, 10, 16, 30, tzinfo=timezone.utc)
MARKET_DAY = FIXED_UTC.astimezone(ZoneInfo("America/New_York")).date()


def clock_at(instant):
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("The test clock requires an aware instant.")

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                raise AssertionError("API clocks must request an explicit timezone.")
            return instant.astimezone(tz)

    return FrozenDateTime


FixedDateTime = clock_at(FIXED_UTC)
