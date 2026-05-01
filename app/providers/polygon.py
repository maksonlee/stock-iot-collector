from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import time
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dateutil import tz
import requests


MARKET_TIMEZONE_NAME = "America/New_York"
logger = logging.getLogger(__name__)

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


class PolygonRequestError(RuntimeError):
    pass


class PolygonProvider:
    """
    Polygon/Massive daily aggregates provider.

    Endpoint format:
    /v2/aggs/ticker/{ticker}/range/1/day/{from}/{to}
    """

    def __init__(
        self,
        api_key: str,
        timeout_seconds: int = 20,
        max_retries: int = 5,
        retry_base_seconds: int = 60,
    ) -> None:
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.max_retries = max(0, max_retries)
        self.retry_base_seconds = max(1, retry_base_seconds)
        self.base_url = "https://api.polygon.io"

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

        data = self._get_json(url, params)
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

        data = self._get_json(url, params)
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

    def _get_json(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        safe_path = url.removeprefix(self.base_url)

        for attempt in range(self.max_retries + 1):
            response = requests.get(url, params=params, timeout=self.timeout_seconds)
            if response.status_code == 429 and attempt < self.max_retries:
                wait_seconds = self._retry_wait_seconds(response, attempt)
                logger.warning(
                    "Polygon rate limited path=%s attempt=%s/%s, sleeping %s second(s)",
                    safe_path,
                    attempt + 1,
                    self.max_retries + 1,
                    wait_seconds,
                )
                time.sleep(wait_seconds)
                continue

            if response.status_code >= 400:
                raise PolygonRequestError(
                    f"Polygon request failed status={response.status_code} path={safe_path}"
                )

            return response.json()

        raise PolygonRequestError(f"Polygon request failed after retries path={safe_path}")

    def _retry_wait_seconds(self, response: requests.Response, attempt: int) -> int:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return max(1, int(float(retry_after)))
            except ValueError:
                pass

        return self.retry_base_seconds * (attempt + 1)
