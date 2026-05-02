import logging
import signal
import sys
from types import FrameType

from app.collector import BackfillError, StockCollector
from app.config import load_app_config, load_stock_config
from app.providers.polygon import PolygonProvider
from app.sinks.thingsboard import ThingsBoardGatewaySink
from app.utils.time_utils import sleep_for_interval


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)

logger = logging.getLogger(__name__)
_should_stop = False
_signal_count = 0


def _is_stopping() -> bool:
    return _should_stop


def _handle_signal(signum: int, frame: FrameType | None) -> None:
    global _should_stop, _signal_count
    _signal_count += 1
    logger.info("Received signal %s, stopping...", signum)
    if _should_stop:
        raise KeyboardInterrupt
    _should_stop = True


def main() -> int:
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    config = load_app_config()
    stocks = load_stock_config(config.stock_config_path)

    logger.info("Loaded %s stock(s), daily mode", len(stocks))

    provider = PolygonProvider(
        api_key=config.polygon_api_key,
        max_retries=config.polygon_max_retries,
        retry_base_seconds=config.polygon_retry_base_seconds,
    )
    sink = ThingsBoardGatewaySink(
        host=config.thingsboard_mqtt_host,
        port=config.thingsboard_mqtt_port,
        client_id=config.thingsboard_mqtt_client_id,
        ca_cert=config.thingsboard_mqtt_ca_cert,
        client_cert=config.thingsboard_mqtt_client_cert,
        client_key=config.thingsboard_mqtt_client_key,
        keepalive_seconds=config.mqtt_keepalive_seconds,
    )

    collector = StockCollector(
        stocks=stocks,
        provider=provider,
        sink=sink,
        publish_chunk_size=config.publish_chunk_size,
        publish_chunk_delay_seconds=config.publish_chunk_delay_seconds,
        daily_market_days_ago=config.daily_market_days_ago,
        should_stop=_is_stopping,
    )

    sink.connect()
    logger.info("Connected to ThingsBoard MQTT host=%s port=%s", config.thingsboard_mqtt_host, config.thingsboard_mqtt_port)

    try:
        if config.backfill_market_days > 0:
            collector.run_backfill(config.backfill_market_days)
        else:
            while not _should_stop:
                collector.run_once()
                if _should_stop:
                    break
                logger.info("Sleeping for %s second(s)", config.poll_interval_seconds)
                sleep_for_interval(config.poll_interval_seconds, should_stop=_is_stopping)
    except KeyboardInterrupt:
        logger.info("Interrupted, stopping now...")
    except BackfillError:
        logger.exception("Backfill did not complete successfully")
        return 1
    finally:
        sink.disconnect()
        logger.info("Stopped")

    return 0


if __name__ == "__main__":
    sys.exit(main())
