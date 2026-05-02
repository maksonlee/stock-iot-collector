import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class AppConfig:
    polygon_api_key: str
    stock_config_path: str

    poll_interval_seconds: int
    publish_chunk_size: int
    publish_chunk_delay_seconds: float
    daily_market_days_ago: int
    backfill_market_days: int
    polygon_max_retries: int
    polygon_retry_base_seconds: int

    thingsboard_mqtt_host: str
    thingsboard_mqtt_port: int
    thingsboard_mqtt_client_id: str

    thingsboard_mqtt_ca_cert: str
    thingsboard_mqtt_client_cert: str
    thingsboard_mqtt_client_key: str

    mqtt_keepalive_seconds: int = 60


def _get_required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _get_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(f"Environment variable {name} must be an integer") from exc


def _get_float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise RuntimeError(f"Environment variable {name} must be a number") from exc


def load_app_config() -> AppConfig:
    default_stock_config_path = "./config/stocks.yaml"
    if not Path(default_stock_config_path).exists():
        default_stock_config_path = "/etc/stock-iot-collector/stocks.yaml"

    return AppConfig(
        polygon_api_key=_get_required_env("POLYGON_API_KEY"),
        stock_config_path=os.getenv(
            "STOCK_CONFIG_PATH",
            default_stock_config_path,
        ),
        poll_interval_seconds=_get_int_env("POLL_INTERVAL_SECONDS", 3600),
        publish_chunk_size=_get_int_env("PUBLISH_CHUNK_SIZE", 50),
        publish_chunk_delay_seconds=_get_float_env("PUBLISH_CHUNK_DELAY_SECONDS", 0.1),
        daily_market_days_ago=_get_int_env("DAILY_MARKET_DAYS_AGO", 1),
        backfill_market_days=_get_int_env("BACKFILL_MARKET_DAYS", 0),
        polygon_max_retries=_get_int_env("POLYGON_MAX_RETRIES", 5),
        polygon_retry_base_seconds=_get_int_env("POLYGON_RETRY_BASE_SECONDS", 60),
        thingsboard_mqtt_host=_get_required_env("THINGSBOARD_MQTT_HOST"),
        thingsboard_mqtt_port=_get_int_env("THINGSBOARD_MQTT_PORT", 8883),
        thingsboard_mqtt_client_id=os.getenv(
            "THINGSBOARD_MQTT_CLIENT_ID",
            "stock-collector-01",
        ),
        thingsboard_mqtt_ca_cert=_get_required_env("THINGSBOARD_MQTT_CA_CERT"),
        thingsboard_mqtt_client_cert=_get_required_env("THINGSBOARD_MQTT_CLIENT_CERT"),
        thingsboard_mqtt_client_key=_get_required_env("THINGSBOARD_MQTT_CLIENT_KEY"),
        mqtt_keepalive_seconds=_get_int_env("MQTT_KEEPALIVE_SECONDS", 60),
    )


def load_stock_config(path: str) -> list[dict[str, Any]]:
    config_path = Path(path)
    if not config_path.exists():
        raise RuntimeError(f"Stock config file does not exist: {path}")

    with config_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    stocks = data.get("stocks", [])
    if not isinstance(stocks, list) or not stocks:
        raise RuntimeError("stocks.yaml must contain a non-empty 'stocks' list")

    normalized: list[dict[str, Any]] = []
    for item in stocks:
        symbol = item.get("symbol")
        if not symbol:
            raise RuntimeError("Each stock item must contain 'symbol'")

        normalized_symbol = str(symbol).upper()
        device_name = item.get("device_name") or f"stock.{normalized_symbol}"
        normalized.append(
            {
                "symbol": normalized_symbol,
                "device_name": device_name,
                "name": item.get("name", normalized_symbol),
                "market": item.get("market", ""),
                "currency": item.get("currency", "USD"),
            }
        )

    return normalized
