import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone, tzinfo


def utc_now_floor_minute() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(second=0, microsecond=0)


def target_minute_utc(delay_minutes: int) -> datetime:
    return utc_now_floor_minute() - timedelta(minutes=delay_minutes)


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


def sleep_until_next_minute(offset_seconds: int = 1) -> None:
    now = time.time()
    next_minute = (int(now // 60) + 1) * 60 + offset_seconds
    sleep_seconds = max(1, next_minute - now)
    time.sleep(sleep_seconds)


def sleep_for_interval(seconds: int, should_stop: Callable[[], bool] | None = None) -> None:
    remaining_seconds = max(1, seconds)

    while remaining_seconds > 0:
        if should_stop is not None and should_stop():
            return

        sleep_seconds = min(1, remaining_seconds)
        time.sleep(sleep_seconds)
        remaining_seconds -= sleep_seconds
