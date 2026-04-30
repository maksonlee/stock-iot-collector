import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone, tzinfo


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def previous_weekday_market_time(
    now_utc: datetime,
    market_tz: tzinfo,
    days_ago: int = 1,
) -> datetime:
    if now_utc.tzinfo is None:
        raise ValueError("now_utc must be timezone-aware")

    remaining_days = max(1, days_ago)
    market_date = now_utc.astimezone(market_tz).date()

    while remaining_days > 0:
        market_date -= timedelta(days=1)
        if market_date.weekday() < 5:
            remaining_days -= 1

    return datetime(
        market_date.year,
        market_date.month,
        market_date.day,
        tzinfo=market_tz,
    ).astimezone(timezone.utc)


def datetime_to_unix_ms(dt: datetime) -> int:
    if dt.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    return int(dt.timestamp() * 1000)


def sleep_for_interval(seconds: int, should_stop: Callable[[], bool] | None = None) -> None:
    remaining_seconds = max(1, seconds)

    while remaining_seconds > 0:
        if should_stop is not None and should_stop():
            return

        sleep_seconds = min(1, remaining_seconds)
        time.sleep(sleep_seconds)
        remaining_seconds -= sleep_seconds
