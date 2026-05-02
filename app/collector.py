from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.providers.polygon import MARKET_TIMEZONE, PolygonProvider
from app.sinks.thingsboard import ThingsBoardGatewaySink
from app.utils.time_utils import previous_weekday_market_time, utc_now


logger = logging.getLogger(__name__)


class BackfillError(RuntimeError):
    pass


@dataclass(frozen=True)
class CollectionResult:
    success: bool
    skipped: bool = False

    def __bool__(self) -> bool:
        return self.success


class StockCollector:
    def __init__(
        self,
        stocks: list[dict[str, Any]],
        provider: PolygonProvider,
        sink: ThingsBoardGatewaySink,
        publish_chunk_size: int,
        publish_chunk_delay_seconds: float,
        daily_market_days_ago: int,
        should_stop: Callable[[], bool] | None = None,
    ) -> None:
        self.stocks = stocks
        self.provider = provider
        self.sink = sink
        self.publish_chunk_size = publish_chunk_size
        self.publish_chunk_delay_seconds = max(0.0, publish_chunk_delay_seconds)
        self.daily_market_days_ago = daily_market_days_ago
        self.should_stop = should_stop

    def run_once(self) -> None:
        self._run_for_days_ago(self.daily_market_days_ago)

    def run_backfill(self, market_days: int) -> None:
        days = max(0, market_days)
        if days == 0:
            logger.info("Backfill disabled")
            return

        skipped_dates: list[str] = []
        logger.info("Starting backfill for %s U.S. market weekday(s)", days)
        for days_ago in range(days, 0, -1):
            if self._is_stopping():
                raise BackfillError("Backfill interrupted before all market days completed")

            logger.info("Backfill progress: days_ago=%s", days_ago)
            result = self._run_for_days_ago(days_ago)
            if result.skipped:
                skipped_dates.append(self._target_market_date(days_ago))
                continue

            if not result:
                failed_date = self._target_market_date(days_ago)
                logger.error("Backfill stopped at failed market date: %s", failed_date)
                raise BackfillError(f"Backfill failed for market date {failed_date}")

        if skipped_dates:
            logger.info(
                "Backfill skipped %s market-closed/no-data day(s): %s",
                len(skipped_dates),
                ", ".join(skipped_dates),
            )

        logger.info("Backfill finished successfully for %s requested weekday(s)", days)

    def _run_for_days_ago(self, days_ago: int) -> CollectionResult:
        target_time = self._target_time_utc(days_ago)
        logger.info(
            "Collecting target_time_utc=%s target_market_date=%s",
            target_time.isoformat(),
            target_time.astimezone(MARKET_TIMEZONE).date().isoformat(),
        )
        payload = self._build_payload(target_time)

        if payload is None:
            logger.warning("Failed to generate telemetry payload for target_time=%s", target_time.isoformat())
            return CollectionResult(success=False)

        if not payload:
            logger.warning("No telemetry payload generated for target_time=%s", target_time.isoformat())
            return CollectionResult(success=True, skipped=True)

        published_chunks = self._publish_payload_chunks(payload)
        expected_chunks = self._expected_chunk_count(len(payload))
        if published_chunks != expected_chunks:
            logger.error(
                "Published only %s of %s expected chunk(s), target_time=%s",
                published_chunks,
                expected_chunks,
                target_time.isoformat(),
            )
            return CollectionResult(success=False)

        logger.info(
            "Published telemetry for %s stock(s) in %s chunk(s), target_time=%s",
            len(payload),
            published_chunks,
            target_time.isoformat(),
        )
        return CollectionResult(success=True)

    def _build_payload(self, target_time: datetime) -> dict[str, list[dict[str, Any]]] | None:
        if self._should_fetch_all_stocks():
            return self._build_all_stocks_payload(target_time)

        payload: dict[str, list[dict[str, Any]]] = {}

        for stock in self.stocks:
            if self._is_stopping():
                logger.info("Stopping before building remaining stock payload")
                break

            symbol = stock["symbol"]
            device_name = stock["device_name"]

            try:
                bar = self.provider.fetch_daily_bar(symbol, target_time)
            except Exception:
                logger.exception("Failed to fetch daily bar for symbol=%s", symbol)
                return None

            if bar is None:
                logger.warning(
                    "No daily bar found for symbol=%s target_time=%s",
                    symbol,
                    target_time.isoformat(),
                )
                continue

            payload[device_name] = [
                {
                    "ts": self._telemetry_timestamp_ms(target_time, bar.timestamp_ms),
                    "values": self._bar_values(symbol, bar),
                }
            ]

        return payload

    def _build_all_stocks_payload(self, target_time: datetime) -> dict[str, list[dict[str, Any]]] | None:
        try:
            bars = self.provider.fetch_grouped_daily_bars(target_time)
        except Exception:
            logger.exception("Failed to fetch grouped daily bars")
            return None

        payload: dict[str, list[dict[str, Any]]] = {}
        for symbol, bar in bars.items():
            if self._is_stopping():
                logger.info("Stopping before building remaining grouped daily payload")
                break

            payload[f"stock.{symbol}"] = [
                {
                    "ts": self._telemetry_timestamp_ms(target_time, bar.timestamp_ms),
                    "values": self._bar_values(symbol, bar),
                }
            ]

        logger.info("Built grouped daily payload for %s stock(s)", len(payload))
        return payload

    def _bar_values(self, symbol: str, bar: Any) -> dict[str, Any]:
        values: dict[str, Any] = {
            "symbol": symbol,
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "price": bar.close,
            "volume": bar.volume,
            "source": "polygon",
            "bar_timestamp_ms": bar.timestamp_ms,
        }

        if bar.transaction_count is not None:
            values["transaction_count"] = bar.transaction_count

        if bar.vwap is not None:
            values["vwap"] = bar.vwap

        return values

    def _publish_payload_chunks(self, payload: dict[str, list[dict[str, Any]]]) -> int:
        items = list(payload.items())
        chunk_size = max(1, self.publish_chunk_size)
        published_chunks = 0

        for start in range(0, len(items), chunk_size):
            if self._is_stopping():
                logger.info("Stopping before publishing remaining telemetry chunks")
                break

            chunk = dict(items[start : start + chunk_size])
            logger.info(
                "Publishing telemetry chunk %s-%s of %s stock(s)",
                start + 1,
                min(start + chunk_size, len(items)),
                len(items),
            )
            self.sink.publish_gateway_telemetry(chunk)
            published_chunks += 1
            self._sleep_between_chunks()

        return published_chunks

    def _expected_chunk_count(self, payload_size: int) -> int:
        chunk_size = max(1, self.publish_chunk_size)
        return (payload_size + chunk_size - 1) // chunk_size

    def _sleep_between_chunks(self) -> None:
        if self.publish_chunk_delay_seconds <= 0:
            return

        end_time = time.monotonic() + self.publish_chunk_delay_seconds
        while time.monotonic() < end_time:
            if self._is_stopping():
                return
            time.sleep(min(0.1, end_time - time.monotonic()))

    def _is_stopping(self) -> bool:
        return self.should_stop is not None and self.should_stop()

    def _should_fetch_all_stocks(self) -> bool:
        return any(stock["symbol"] in {"*", "ALL"} for stock in self.stocks)

    def _target_time_utc(self, days_ago: int) -> datetime:
        return previous_weekday_market_time(
            utc_now(),
            MARKET_TIMEZONE,
            days_ago,
        )

    def _target_market_date(self, days_ago: int) -> str:
        return self._target_time_utc(days_ago).astimezone(MARKET_TIMEZONE).date().isoformat()

    def _telemetry_timestamp_ms(self, target_time: datetime, bar_timestamp_ms: int) -> int:
        return bar_timestamp_ms
