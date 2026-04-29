from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dateutil import tz
import requests


MARKET_TIMEZONE_NAME = "America/New_York"

try:
    MARKET_TIMEZONE = ZoneInfo(MARKET_TIMEZONE_NAME)
except ZoneInfoNotFoundError:
    MARKET_TIMEZONE = tz.gettz(MARKET_TIMEZONE_NAME)
    if MARKET_TIMEZONE is None:
        raise


@dataclass(frozen=True)
class AggregateBar:
    symbol: str
    timestamp_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    transaction_count: int | None = None
    vwap: float | None = None


class PolygonProvider:
    """
    Polygon/Massive aggregates provider.

    Endpoint format:
    /v2/aggs/ticker/{ticker}/range/1/minute/{from}/{to}
    """

    def __init__(self, api_key: str, timeout_seconds: int = 20) -> None:
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.base_url = "https://api.polygon.io"

    def fetch_bar(self, symbol: str, target_time_utc: datetime, timespan: str = "minute") -> AggregateBar | None:
        if timespan == "minute":
            return self.fetch_minute_bar(symbol, target_time_utc)
        if timespan == "day":
            return self.fetch_daily_bar(symbol, target_time_utc)
        raise ValueError("timespan must be one of: minute, day")

    def fetch_minute_bar(self, symbol: str, target_time_utc: datetime) -> AggregateBar | None:
        if target_time_utc.tzinfo is None:
            raise ValueError("target_time_utc must be timezone-aware")

        # Polygon aggregate API accepts YYYY-MM-DD. For a single minute,
        # we request the full target date, then select the target minute.
        target_date = target_time_utc.astimezone(timezone.utc).date().isoformat()
        target_ms = int(target_time_utc.timestamp() * 1000)

        url = (
            f"{self.base_url}/v2/aggs/ticker/{symbol}/range/1/minute/"
            f"{target_date}/{target_date}"
        )

        params: dict[str, Any] = {
            "adjusted": "true",
            "sort": "asc",
            "limit": 50000,
            "apiKey": self.api_key,
        }

        response = requests.get(url, params=params, timeout=self.timeout_seconds)
        response.raise_for_status()

        data = response.json()
        results = data.get("results") or []

        for row in results:
            if int(row.get("t")) == target_ms:
                return AggregateBar(
                    symbol=symbol,
                    timestamp_ms=int(row["t"]),
                    open=float(row["o"]),
                    high=float(row["h"]),
                    low=float(row["l"]),
                    close=float(row["c"]),
                    volume=float(row["v"]),
                    transaction_count=row.get("n"),
                    vwap=row.get("vw"),
                )

        return None

    def fetch_daily_bar(self, symbol: str, target_time_utc: datetime) -> AggregateBar | None:
        if target_time_utc.tzinfo is None:
            raise ValueError("target_time_utc must be timezone-aware")

        target_date = target_time_utc.astimezone(MARKET_TIMEZONE).date().isoformat()
        url = (
            f"{self.base_url}/v2/aggs/ticker/{symbol}/range/1/day/"
            f"{target_date}/{target_date}"
        )

        params: dict[str, Any] = {
            "adjusted": "true",
            "sort": "asc",
            "limit": 1,
            "apiKey": self.api_key,
        }

        response = requests.get(url, params=params, timeout=self.timeout_seconds)
        response.raise_for_status()

        data = response.json()
        results = data.get("results") or []
        if not results:
            return None

        row = results[0]
        return AggregateBar(
            symbol=symbol,
            timestamp_ms=int(row["t"]),
            open=float(row["o"]),
            high=float(row["h"]),
            low=float(row["l"]),
            close=float(row["c"]),
            volume=float(row["v"]),
            transaction_count=row.get("n"),
            vwap=row.get("vw"),
        )

    def fetch_grouped_daily_bars(self, target_time_utc: datetime) -> dict[str, AggregateBar]:
        if target_time_utc.tzinfo is None:
            raise ValueError("target_time_utc must be timezone-aware")

        target_date = target_time_utc.astimezone(MARKET_TIMEZONE).date().isoformat()
        url = f"{self.base_url}/v2/aggs/grouped/locale/us/market/stocks/{target_date}"

        params: dict[str, Any] = {
            "adjusted": "true",
            "apiKey": self.api_key,
        }

        response = requests.get(url, params=params, timeout=self.timeout_seconds)
        response.raise_for_status()

        data = response.json()
        results = data.get("results") or []
        bars: dict[str, AggregateBar] = {}

        for row in results:
            symbol = row.get("T")
            if not symbol:
                continue

            bars[str(symbol)] = AggregateBar(
                symbol=str(symbol),
                timestamp_ms=int(row["t"]),
                open=float(row["o"]),
                high=float(row["h"]),
                low=float(row["l"]),
                close=float(row["c"]),
                volume=float(row["v"]),
                transaction_count=row.get("n"),
                vwap=row.get("vw"),
            )

        return bars
