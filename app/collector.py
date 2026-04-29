from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from app.providers.polygon import MARKET_TIMEZONE, PolygonProvider
from app.sinks.thingsboard import ThingsBoardGatewaySink
from app.utils.time_utils import previous_weekday_market_time, target_minute_utc, utc_now_floor_minute


logger = logging.getLogger(__name__)


class StockCollector:
    def __init__(
        self,
        stocks: list[dict[str, Any]],
        provider: PolygonProvider,
        sink: ThingsBoardGatewaySink,
        delay_minutes: int,
        polygon_timespan: str,
        publish_chunk_size: int,
        daily_market_days_ago: int,
    ) -> None:
        self.stocks = stocks
        self.provider = provider
        self.sink = sink
        self.delay_minutes = delay_minutes
        self.polygon_timespan = polygon_timespan
        self.publish_chunk_size = publish_chunk_size
        self.daily_market_days_ago = daily_market_days_ago

    def run_once(self) -> None:
        target_time = self._target_time_utc()
        logger.info(
            "Collecting target_time_utc=%s target_market_date=%s",
            target_time.isoformat(),
            target_time.astimezone(MARKET_TIMEZONE).date().isoformat(),
        )
        payload = self._build_payload(target_time)

        if not payload:
            logger.warning("No telemetry payload generated for target_time=%s", target_time.isoformat())
            return

        published_chunks = self._publish_payload_chunks(payload)
        logger.info(
            "Published telemetry for %s stock(s) in %s chunk(s), target_time=%s",
            len(payload),
            published_chunks,
            target_time.isoformat(),
        )

    def _build_payload(self, target_time: datetime) -> dict[str, list[dict[str, Any]]]:
        if self._should_fetch_all_stocks():
            return self._build_all_stocks_payload(target_time)

        payload: dict[str, list[dict[str, Any]]] = {}

        for stock in self.stocks:
            symbol = stock["symbol"]
            device_name = stock["device_name"]

            try:
                bar = self.provider.fetch_bar(symbol, target_time, self.polygon_timespan)
            except Exception:
                logger.exception("Failed to fetch %s bar for symbol=%s", self.polygon_timespan, symbol)
                continue

            if bar is None:
                logger.warning(
                    "No %s bar found for symbol=%s target_time=%s",
                    self.polygon_timespan,
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

    def _build_all_stocks_payload(self, target_time: datetime) -> dict[str, list[dict[str, Any]]]:
        if self.polygon_timespan != "day":
            raise RuntimeError("All-stock collection is only supported with POLYGON_TIMESPAN=day")

        try:
            bars = self.provider.fetch_grouped_daily_bars(target_time)
        except Exception:
            logger.exception("Failed to fetch grouped daily bars")
            return {}

        payload: dict[str, list[dict[str, Any]]] = {}
        for symbol, bar in bars.items():
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
            "delay_minutes": self.delay_minutes,
            "aggregate_timespan": self.polygon_timespan,
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
            chunk = dict(items[start : start + chunk_size])
            logger.info(
                "Publishing telemetry chunk %s-%s of %s stock(s)",
                start + 1,
                min(start + chunk_size, len(items)),
                len(items),
            )
            self.sink.publish_gateway_telemetry(chunk)
            published_chunks += 1

        return published_chunks

    def _should_fetch_all_stocks(self) -> bool:
        return any(stock["symbol"] in {"*", "ALL"} for stock in self.stocks)

    def _target_time_utc(self) -> datetime:
        if self.polygon_timespan == "day":
            return previous_weekday_market_time(
                utc_now_floor_minute(),
                MARKET_TIMEZONE,
                self.daily_market_days_ago,
            )

        return target_minute_utc(self.delay_minutes)

    def _telemetry_timestamp_ms(self, target_time: datetime, bar_timestamp_ms: int) -> int:
        return bar_timestamp_ms
